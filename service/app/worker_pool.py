"""
worker_pool.py
A fixed-size pool of persistent, resource-limited subprocess workers that
compile+validate (and optionally export) JSON IR. Same isolation
philosophy as cad_dataset/executor.py's BatchExecutor -- a persistent
worker avoids paying build123d/OCP's cold-import cost per request -- but
extended for:
  * multiple concurrent workers (a pool, not one worker), since this is a
    live HTTP service, not a sequential batch job
  * per-worker resource ceilings (RLIMIT_AS / RLIMIT_CPU), so one
    adversarial or hallucinated IR (e.g. a huge pattern count) can't
    starve the whole service -- defense in depth alongside the container-
    level cpu/memory limits set in docker-compose.yml
  * an export path, not just validate

RESOURCE LIMIT CAVEAT: RLIMIT_AS/RLIMIT_CPU are POSIX rlimits applied via
preexec_fn before exec in the child. This is best-effort -- some native
allocators (OCCT's memory management included) don't always play perfectly
with RLIMIT_AS, and a worker can still be killed abruptly (SIGSEGV/OOM)
rather than raising a clean Python exception. That's fine: submit() treats
any dead/unresponsive worker as a failure and respawns, same as
BatchExecutor's timeout-triggered restart. Don't rely on RLIMIT_AS alone --
the docker-compose.yml container-level memory limit is the real backstop.
"""

from __future__ import annotations
import base64
import json
import os
import queue
import subprocess
import sys
import threading
from typing import Any

_WORKER_SRC = r'''
import sys, json, base64, os, tempfile
sys.path.insert(0, sys.argv[1])
from compiler import compile_ir, CompileError
from validator import validate_shape
from build123d import export_step, export_stl, export_gltf

_EXPORTERS = {"step": export_step, "stl": export_stl, "glb": export_gltf}
_CONTENT_TYPES = {
    "step": "application/step",
    "stl": "model/stl",
    "glb": "model/gltf-binary",
}
_SUFFIX = {"step": ".step", "stl": ".stl", "glb": ".glb"}

def handle(job):
    ir = job["ir"]
    try:
        part = compile_ir(ir)
    except CompileError as e:
        return {"success": False, "error_type": "CompileError", "error": str(e)}
    except Exception as e:  # noqa: BLE001 -- includes schema.SchemaError
        return {"success": False, "error_type": type(e).__name__, "error": str(e)}

    try:
        stats = validate_shape(part)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error_type": "ValidationError", "error": str(e)}

    result = {"success": True, "stats": stats}
    fmt = job.get("export_format")
    if fmt:
        if fmt not in _EXPORTERS:
            return {"success": False, "error_type": "UnsupportedFormat",
                     "error": f"unknown export format '{fmt}'"}
        path = tempfile.mktemp(suffix=_SUFFIX[fmt])
        try:
            if fmt == "glb":
                _EXPORTERS[fmt](part, path, binary=True)
            else:
                _EXPORTERS[fmt](part, path)
            with open(path, "rb") as f:
                data = f.read()
            result["file_b64"] = base64.b64encode(data).decode("ascii")
            result["content_type"] = _CONTENT_TYPES[fmt]
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error_type": "ExportError", "error": str(e)}
        finally:
            if os.path.exists(path):
                os.unlink(path)
    return result

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        job = json.loads(line)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"success": False, "error_type": "BadInput", "error": str(e)}), flush=True)
        continue
    try:
        res = handle(job)
    except Exception as e:  # noqa: BLE001
        res = {"success": False, "error_type": type(e).__name__, "error": str(e)}
    print(json.dumps(res), flush=True)
'''


class _Worker:
    def __init__(self, module_dir: str, mem_limit_mb: int | None, cpu_time_limit_s: int | None):
        self.module_dir = module_dir
        self.mem_limit_mb = mem_limit_mb
        self.cpu_time_limit_s = cpu_time_limit_s
        self.proc: subprocess.Popen | None = None
        self._out_queue: "queue.Queue" = queue.Queue()
        self._spawn()

    def _limit_resources(self):
        """Runs in the child, after fork, before exec (POSIX only) --
        see module docstring for why this is defense-in-depth, not the
        sole safeguard."""
        import resource
        if self.mem_limit_mb:
            limit = self.mem_limit_mb * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            except Exception:  # noqa: BLE001
                pass
        if self.cpu_time_limit_s:
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (self.cpu_time_limit_s, self.cpu_time_limit_s))
            except Exception:  # noqa: BLE001
                pass

    def _spawn(self):
        preexec = self._limit_resources if os.name == "posix" else None
        self.proc = subprocess.Popen(
            [sys.executable, "-c", _WORKER_SRC, self.module_dir],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
            preexec_fn=preexec,
        )
        self._out_queue = queue.Queue()

        def _reader():
            for line in self.proc.stdout:
                self._out_queue.put(line)
            self._out_queue.put(None)  # stdout EOF -- worker exited

        threading.Thread(target=_reader, daemon=True).start()

    def _kill(self):
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
        self.proc = None

    def execute(self, job: dict, timeout: float) -> dict[str, Any]:
        if self.proc is None or self.proc.poll() is not None:
            self._spawn()
        try:
            self.proc.stdin.write(json.dumps(job) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            self._kill()
            self._spawn()
            return self.execute(job, timeout)

        try:
            line = self._out_queue.get(timeout=timeout)
        except queue.Empty:
            self._kill()  # hung worker, likely stuck in a native OCCT call
            return {"success": False, "error_type": "Timeout",
                    "error": f"execution exceeded {timeout}s (worker restarted)"}

        if line is None:
            stderr_tail = self.proc.stderr.read()[-1000:] if self.proc and self.proc.stderr else ""
            self._kill()
            return {"success": False, "error_type": "WorkerCrash", "error": stderr_tail}

        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {"success": False, "error_type": "BadWorkerOutput", "error": line[:500]}


class GeometryWorkerPool:
    """Thread-safe fixed-size pool. Call .submit() from a worker thread
    (e.g. FastAPI's run_in_threadpool) since it blocks on subprocess pipe
    I/O -- never call it directly from an async event loop coroutine."""

    def __init__(self, module_dir: str | None = None, pool_size: int = 4,
                 timeout: float = 20.0, mem_limit_mb: int = 2048, cpu_time_limit_s: int = 30):
        self.module_dir = module_dir or os.environ.get("CAD_LIB_PATH", "/app/cad_lib")
        self.timeout = timeout
        self.mem_limit_mb = mem_limit_mb
        self.cpu_time_limit_s = cpu_time_limit_s
        self.pool_size = pool_size
        self._available: "queue.Queue[_Worker]" = queue.Queue()
        for _ in range(pool_size):
            self._available.put(_Worker(self.module_dir, mem_limit_mb, cpu_time_limit_s))

    def submit(self, job: dict) -> dict[str, Any]:
        worker = self._available.get()
        try:
            return worker.execute(job, self.timeout)
        finally:
            if worker.proc is None:
                worker = _Worker(self.module_dir, self.mem_limit_mb, self.cpu_time_limit_s)
            self._available.put(worker)

    def shutdown(self):
        while not self._available.empty():
            self._available.get()._kill()
