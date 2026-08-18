"""
main.py
HTTP API around the IR compiler/validator/exporter, backed by
GeometryWorkerPool (see worker_pool.py). This is the production runtime
path -- the self-correcting inference loop, the export/render pipeline,
and any structured-editing UI all call this service instead of importing
compiler.py/validator.py directly. Offline batch tools (build_dataset.py,
the training eval callback) keep importing those modules directly in-
process; there's no reason to add a network hop for a batch job already
running in a container with build123d installed.

Endpoints:
  GET  /health           -- liveness + pool size
  POST /v1/compile       -- validate only, returns geometry stats or error
  POST /v1/export        -- validate + export to STEP/STL/GLB, returns the
                              file bytes directly (Content-Type set per
                              format), geometry stats in X-Geometry-Stats

NOTE: not executed in the sandbox this was authored in -- no fastapi/
uvicorn installed there and no network to get them. Syntax-checked
(py_compile) and the worker_pool subprocess mechanics were smoke-tested
against stub_build123d (see cad_dataset/stub_build123d/), but the FastAPI
routing itself has not been run. Test with `curl` against /health and a
trivial /v1/compile body before pointing real traffic at this.
"""

from __future__ import annotations
import base64
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from worker_pool import GeometryWorkerPool

# schema.py lives in the shared cad_lib copy (see Dockerfile) -- imported
# directly here (not just inside worker subprocesses) so bounds-checking
# happens in the FastAPI process itself, before a worker is ever touched.
sys.path.insert(0, os.environ.get("CAD_LIB_PATH", "/app/cad_lib"))
from schema import validate_bounds  # noqa: E402

POOL: GeometryWorkerPool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global POOL
    POOL = GeometryWorkerPool(
        module_dir=os.environ.get("CAD_LIB_PATH", "/app/cad_lib"),
        pool_size=int(os.environ.get("POOL_SIZE", "4")),
        timeout=float(os.environ.get("JOB_TIMEOUT", "20")),
        mem_limit_mb=int(os.environ.get("WORKER_MEM_LIMIT_MB", "2048")),
        cpu_time_limit_s=int(os.environ.get("WORKER_CPU_LIMIT_S", "30")),
    )
    yield
    POOL.shutdown()


app = FastAPI(title="CAD Geometry Service", version="1.0", lifespan=lifespan)


class CompileRequest(BaseModel):
    json_ir: dict


class ExportRequest(BaseModel):
    json_ir: dict
    format: Literal["step", "stl", "glb"] = "step"


@app.get("/health")
def health():
    return {"status": "ok", "pool_size": POOL.pool_size if POOL else 0}


@app.post("/v1/compile")
async def compile_endpoint(req: CompileRequest):
    """Compile + validate only, no file output. This is what the
    inference self-correction loop should call after each generation
    attempt: if valid=false, feed error_type/error back to the model as a
    repair turn and retry (the model was trained on exactly this shape of
    correction, see cad_dataset/gen_repair.py)."""
    assert POOL is not None
    violations = validate_bounds(req.json_ir)
    if violations:
        return {
            "valid": False,
            "error_type": "BoundsError",
            "error": "; ".join(violations),
        }
    result = await run_in_threadpool(POOL.submit, {"ir": req.json_ir})
    if result.get("success"):
        return {"valid": True, "stats": result["stats"]}
    return {
        "valid": False,
        "error_type": result.get("error_type"),
        "error": result.get("error"),
    }


@app.post("/v1/export")
async def export_endpoint(req: ExportRequest):
    """Compile + validate + export. Returns 422 with the same
    error_type/error shape as /v1/compile on failure (don't export
    something that didn't validate) -- callers should call /v1/compile
    (or just check this response's status) before assuming success."""
    assert POOL is not None
    violations = validate_bounds(req.json_ir)
    if violations:
        raise HTTPException(status_code=422, detail={
            "error_type": "BoundsError",
            "error": "; ".join(violations),
        })
    result = await run_in_threadpool(
        POOL.submit, {"ir": req.json_ir, "export_format": req.format}
    )
    if not result.get("success"):
        raise HTTPException(status_code=422, detail={
            "error_type": result.get("error_type"),
            "error": result.get("error"),
        })

    data = base64.b64decode(result["file_b64"])
    return Response(
        content=data,
        media_type=result["content_type"],
        headers={
            "X-Geometry-Stats": json.dumps(result["stats"]),
            "Content-Disposition": f'attachment; filename="part.{req.format}"',
        },
    )
