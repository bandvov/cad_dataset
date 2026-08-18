"""
executor.py
Two ways to run JSON IR through the compiler+validator, both in an
isolated subprocess so a bad IR can't hang or crash the caller:

  execute_ir(ir)        -- one-shot: spawns a fresh interpreter per call.
                             Simple and fully isolated, but pays build123d/
                             OCP's cold-import cost (commonly several
                             seconds) on every single call.

  BatchExecutor          -- spawns ONE persistent worker and feeds it many
                             IRs over a stdin/stdout JSON-lines protocol,
                             paying the import cost once. Use this for any
                             batch beyond a few dozen records -- the
                             difference between build_dataset.py finishing
                             in a couple minutes vs. appearing to hang for
                             tens of minutes with zero output, since
                             nothing gets written until the whole batch is
                             verified.

If a single item hangs past its timeout inside BatchExecutor (a genuine
OCCT-level hang), that one worker is killed and a fresh one spawned for
the next item -- one bad IR costs one respawn, not the whole batch.
"""

from __future__ import annotations
import json
import os
import queue
import subprocess
import sys
import threading
from typing import Any

_WORKER_SRC = r'''
import sys, json

def main():
    payload = json.loads(sys.stdin.read())
    ir = payload["ir"]
    sys.path.insert(0, payload["module_dir"])

    from compiler import compile_ir, CompileError
    from validator import validate_shape

    try:
        part = compile_ir(ir)
    except CompileError as e:
        print(json.dumps({"success": False, "error_type": "CompileError", "error": str(e)}))
        return
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"success": False, "error_type": type(e).__name__, "error": str(e)}))
        return

    try:
        stats = validate_shape(part)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"success": False, "error_type": "ValidationError", "error": str(e)}))
        return

    print(json.dumps({"success": True, "stats": stats}))

if __name__ == "__main__":
    main()
'''


def execute_ir(ir: dict, timeout: float = 20.0, module_dir: str | None = None) -> dict[str, Any]:
    """One-shot: fresh interpreter per call. Fine for gen_repair.py's
    ad-hoc broken/fixed pair checks or small standalone runs; for a full
    build_dataset.py batch, use BatchExecutor instead (see module docstring)."""
    module_dir = module_dir or os.path.dirname(os.path.abspath(__file__))
    payload = json.dumps({"ir": ir, "module_dir": module_dir})

    try:
        proc = subprocess.run(
            [sys.executable, "-c", _WORKER_SRC],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error_type": "Timeout",
                "error": f"execution exceeded {timeout}s"}

    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-20:])
        return {"success": False, "error_type": "SubprocessCrash",
                "error": tail or f"child exited with code {proc.returncode}"}

    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    if not lines:
        return {"success": False, "error_type": "NoOutput",
                "error": "worker produced no output; stderr: " + proc.stderr[-500:]}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"success": False, "error_type": "BadWorkerOutput",
                "error": lines[-1][:500]}


_BATCH_WORKER_SRC = r'''
import sys, json
sys.path.insert(0, sys.argv[1])
from compiler import compile_ir, CompileError
from validator import validate_shape

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        ir = json.loads(line)
    except Exception as e:
        print(json.dumps({"success": False, "error_type": "BadInput", "error": str(e)}), flush=True)
        continue
    try:
        part = compile_ir(ir)
        stats = validate_shape(part)
        print(json.dumps({"success": True, "stats": stats}), flush=True)
    except CompileError as e:
        print(json.dumps({"success": False, "error_type": "CompileError", "error": str(e)}), flush=True)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"success": False, "error_type": type(e).__name__, "error": str(e)}), flush=True)
'''


class BatchExecutor:
    """
    Usage:
        with BatchExecutor(timeout_per_item=20.0) as be:
            for ir in irs:
                result = be.execute(ir)
    """

    def __init__(self, module_dir: str | None = None, timeout_per_item: float = 20.0):
        self.module_dir = module_dir or os.path.dirname(os.path.abspath(__file__))
        self.timeout = timeout_per_item
        self.proc: subprocess.Popen | None = None
        self._out_queue: "queue.Queue" = queue.Queue()
        self._reader_thread: threading.Thread | None = None

    def _spawn(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-c", _BATCH_WORKER_SRC, self.module_dir],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._out_queue = queue.Queue()

        def _reader():
            for line in self.proc.stdout:
                self._out_queue.put(line)
            self._out_queue.put(None)  # signals stdout EOF (worker exited)

        self._reader_thread = threading.Thread(target=_reader, daemon=True)
        self._reader_thread.start()

    def _kill(self):
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
        self.proc = None

    def __enter__(self):
        self._spawn()
        return self

    def execute(self, ir: dict) -> dict[str, Any]:
        if self.proc is None or self.proc.poll() is not None:
            self._spawn()
        try:
            self.proc.stdin.write(json.dumps(ir) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            self._kill()
            self._spawn()
            return self.execute(ir)

        try:
            line = self._out_queue.get(timeout=self.timeout)
        except queue.Empty:
            self._kill()  # hung worker, likely stuck in a native OCCT call
            return {"success": False, "error_type": "Timeout",
                    "error": f"execution exceeded {self.timeout}s (worker restarted)"}

        if line is None:
            stderr_tail = self.proc.stderr.read()[-1000:] if self.proc and self.proc.stderr else ""
            self._kill()
            return {"success": False, "error_type": "WorkerCrash", "error": stderr_tail}

        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {"success": False, "error_type": "BadWorkerOutput", "error": line[:500]}

    def __exit__(self, *exc):
        if self.proc is not None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self._kill()
