"""
main.py
HTTP API for the self-correcting CAD generation loop. Sits between the
product/UI layer and two backend services: llama.cpp (the fine-tuned
model) and the geometry service (compile/validate/export). This is the
"llm-service" the person building the CAD product talks to; it should
never need direct access to build123d itself, that's the geometry
service's job -- see cad_dataset/service/.

NOTE: not executed in the sandbox this was authored in -- no fastapi/
httpx installed there, no network to reach real llama.cpp/geometry
services. Syntax/AST-checked only; test against the real stack (see
README.md) before trusting this in production.
"""

from __future__ import annotations
import base64
import json
import os
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from orchestrator import Orchestrator
from store import ProjectStore, ProjectNotFound

app = FastAPI(title="LLM Service (CAD generation orchestrator)", version="1.0")

orchestrator = Orchestrator(
    llama_url=os.environ.get("LLAMACPP_URL", "http://llamacpp:8080"),
    geometry_url=os.environ.get("GEOMETRY_SERVICE_URL", "http://geometry:8000"),
    http_timeout=float(os.environ.get("HTTP_TIMEOUT", "60")),
)

STORE = ProjectStore(os.environ.get("DB_PATH", "/data/cad_sessions.db"))


class GenerateRequest(BaseModel):
    prompt: str
    base_ir: dict | None = None  # present -> this is an edit/regenerate, not a fresh generate
    max_attempts: int = 3
    export_format: Literal["step", "stl", "glb"] | None = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/generate")
async def generate(req: GenerateRequest):
    """The main product-facing endpoint. success=false with a populated
    `error` means the model couldn't produce valid geometry within
    max_attempts -- surface that to the user rather than the raw IR;
    `conversation` is included for debugging/observability (log it --
    per the product-layer discussion, prompts + outcomes are exactly the
    signal to mine for the next round of training data)."""
    result = await orchestrator.generate(req.prompt, req.base_ir, req.max_attempts)
    STORE.log_event(
        project_id=None, action="generate", prompt=req.prompt,
        success=result.success, error=result.error, attempts=result.attempts,
        failed_ir=None if result.success else result.json_ir,
    )
    response = {
        "success": result.success,
        "json_ir": result.json_ir,
        "attempts": result.attempts,
        "stats": result.stats,
        "error": result.error,
        "conversation": result.conversation,
    }
    if result.success and req.export_format:
        exported = await orchestrator.export(result.json_ir, req.export_format)
        if exported:
            data, content_type, stats = exported
            response["file_b64"] = base64.b64encode(data).decode("ascii")
            response["content_type"] = content_type
    return response


@app.post("/v1/generate/stream")
async def generate_stream(req: GenerateRequest):
    """Same loop as /v1/generate, streamed as newline-delimited JSON
    (NDJSON) -- one `{"event": ...}\\n` object per line, flushed as each
    step happens, so a client can show live progress ("attempt 1/3",
    "repairing...") instead of waiting silently for the whole loop.

    Event shapes (see orchestrator.generate_stream() for the exact set):
      {"event": "start", "max_attempts": 3}
      {"event": "attempt_start", "attempt": 1, "max_attempts": 3}
      {"event": "llm_response", "attempt": 1, "content": "..."}
      {"event": "validating", "attempt": 1}
      {"event": "attempt_failed", "attempt": 1, "error_type": "...", "error": "..."}
      {"event": "repairing", "attempt": 1, "next_attempt": 2}
      {"event": "success", "attempts": 2, "json_ir": {...}, "stats": {...}, "conversation": [...]}
      {"event": "failure", "attempts": 3, "json_ir": {...}, "error": "...", "conversation": [...]}
      {"event": "exported", "content_type": "...", "file_b64": "..."}   -- only if export_format set and success

    curl example:
      curl -N -X POST localhost:8001/v1/generate/stream \\
        -H "Content-Type: application/json" \\
        -d '{"prompt": "A 40x30mm plate, 10mm thick."}'
    (-N disables curl's output buffering so lines print as they arrive)
    """
    async def event_lines():
        final_event = None
        async for event in orchestrator.generate_stream(req.prompt, req.base_ir, req.max_attempts):
            yield json.dumps(event) + "\n"
            if event["event"] in ("success", "failure"):
                final_event = event
            if event["event"] == "success" and req.export_format:
                exported = await orchestrator.export(event["json_ir"], req.export_format)
                if exported:
                    data, content_type, _stats = exported
                    yield json.dumps({
                        "event": "exported",
                        "content_type": content_type,
                        "file_b64": base64.b64encode(data).decode("ascii"),
                    }) + "\n"
        if final_event is not None:
            STORE.log_event(
                project_id=None, action="generate", prompt=req.prompt,
                success=(final_event["event"] == "success"),
                error=final_event.get("error"), attempts=final_event.get("attempts"),
                failed_ir=None if final_event["event"] == "success" else final_event.get("json_ir"),
            )

    return StreamingResponse(event_lines(), media_type="application/x-ndjson")


# ---------------------------------------------------------------------- #
# Projects: persisted, versioned feature trees (Phase 2 item 1 -- "a CAD
# service isn't 'prompt -> JSON', it's session state: a user has a part,
# iterates on it, and expects edits to compose"). See store.py for the
# undo/redo model. The stateless /v1/generate above still exists for
# one-off use; these endpoints are for the normal product flow where a
# user is iterating on one part across multiple turns.
# ---------------------------------------------------------------------- #

class CreateProjectRequest(BaseModel):
    name: str = "Untitled part"


class ProjectGenerateRequest(BaseModel):
    prompt: str
    max_attempts: int = 3
    export_format: Literal["step", "stl", "glb"] | None = "glb"


def _export_field(export_format: str | None):
    """Decorator-free helper: attach a base64 export to a response dict
    if requested and available, used by both project_generate and the
    undo/redo endpoints so the frontend always has something to render
    immediately after any of these three actions."""
    async def attach(response: dict, ir: dict):
        if not export_format:
            return response
        exported = await orchestrator.export(ir, export_format)
        if exported:
            data, content_type, _stats = exported
            response["file_b64"] = base64.b64encode(data).decode("ascii")
            response["content_type"] = content_type
        return response
    return attach


@app.post("/v1/projects")
async def create_project(req: CreateProjectRequest):
    return STORE.create_project(req.name)


@app.get("/v1/projects")
async def list_projects():
    return STORE.list_projects()


@app.get("/v1/projects/{project_id}")
async def get_project(project_id: str):
    try:
        return STORE.get_project(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="project not found")


@app.get("/v1/projects/{project_id}/versions/{version_index}")
async def get_project_version(project_id: str, version_index: int):
    """Fetch a specific historical version's full IR -- GET
    /v1/projects/{id} only returns full IR for `current`, metadata only
    (prompt, created_at) for past versions in `history`. Used by
    mine_flywheel_repairs.py (Phase 4 step 2) to resolve a logged fix's
    version_index back to an actual json_ir, since that fix is usually no
    longer the project's current version by the time mining runs."""
    try:
        STORE.get_project(project_id)  # 404 if the project itself doesn't exist
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="project not found")
    version = STORE.get_version(project_id, version_index)
    if version is None:
        raise HTTPException(status_code=404, detail="version not found")
    return version


@app.delete("/v1/projects/{project_id}")
async def delete_project(project_id: str):
    if not STORE.delete_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    return {"deleted": True}


@app.post("/v1/projects/{project_id}/generate")
async def project_generate(project_id: str, req: ProjectGenerateRequest):
    """Same self-correcting loop as /v1/generate, but base_ir is taken
    automatically from the project's current version (None for a
    project's first generation), and a successful result is appended as
    a new version -- this IS the "edits compose" behavior from the
    product-layer discussion, not something the frontend has to
    orchestrate by passing base_ir itself."""
    try:
        project = STORE.get_project(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="project not found")

    base_ir = project["current"]["json_ir"] if project["current"] else None
    result = await orchestrator.generate(req.prompt, base_ir, req.max_attempts)

    response = {
        "success": result.success,
        "json_ir": result.json_ir,
        "attempts": result.attempts,
        "stats": result.stats,
        "error": result.error,
        "conversation": result.conversation,
    }
    version_index = None
    if result.success:
        version = STORE.add_version(project_id, result.json_ir, req.prompt, result.stats)
        version_index = version["version_index"]
        response["version_index"] = version_index
        response = await _export_field(req.export_format)(response, result.json_ir)

    STORE.log_event(
        project_id=project_id, action="generate", prompt=req.prompt,
        success=result.success, error=result.error, attempts=result.attempts,
        version_index=version_index, failed_ir=None if result.success else result.json_ir,
    )
    return response


class ApplyEditRequest(BaseModel):
    json_ir: dict
    export_format: Literal["step", "stl", "glb"] | None = "glb"


@app.post("/v1/projects/{project_id}/apply")
async def project_apply_edit(project_id: str, req: ApplyEditRequest):
    """Structured-editing fallback (Phase 2 item 4): apply a directly-
    edited feature tree without going through the model at all -- for
    when the model got something wrong, or the user just wants to type an
    exact number rather than re-prompt and hope. Validates against the
    geometry service via orchestrator.compile_only() and, on success,
    appends a new version with the SAME semantics as a model-generated
    edit (undo/redo doesn't distinguish how a version was produced).
    `prompt` is stored as None for these versions -- see store.py's
    history and the frontend's restore logic, which renders that as
    "(edit)" rather than a fabricated prompt string."""
    try:
        STORE.get_project(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="project not found")

    result = await orchestrator.compile_only(req.json_ir)
    if not result.get("valid"):
        STORE.log_event(
            project_id=project_id, action="apply", success=False,
            error_type=result.get("error_type"), error=result.get("error"),
            failed_ir=req.json_ir,
        )
        raise HTTPException(status_code=422, detail={
            "error_type": result.get("error_type"),
            "error": result.get("error"),
        })

    version = STORE.add_version(project_id, req.json_ir, None, result.get("stats"))
    STORE.log_event(
        project_id=project_id, action="apply", success=True,
        version_index=version["version_index"],
    )
    response = {
        "success": True,
        "json_ir": req.json_ir,
        "stats": result.get("stats"),
        "version_index": version["version_index"],
    }
    return await _export_field(req.export_format)(response, req.json_ir)


@app.post("/v1/projects/{project_id}/undo")
async def project_undo(project_id: str, export_format: Literal["step", "stl", "glb"] | None = "glb"):
    try:
        STORE.get_project(project_id)  # 404 if the project itself doesn't exist
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="project not found")
    version = STORE.undo(project_id)
    STORE.log_event(
        project_id=project_id, action="undo", success=version is not None,
        error=None if version else "nothing to undo",
        version_index=version["version_index"] if version else None,
    )
    if version is None:
        raise HTTPException(status_code=409, detail="nothing to undo")
    response = {"json_ir": version["json_ir"], "stats": version["stats"],
                "version_index": version["version_index"]}
    return await _export_field(export_format)(response, version["json_ir"])


@app.post("/v1/projects/{project_id}/redo")
async def project_redo(project_id: str, export_format: Literal["step", "stl", "glb"] | None = "glb"):
    try:
        STORE.get_project(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="project not found")
    version = STORE.redo(project_id)
    STORE.log_event(
        project_id=project_id, action="redo", success=version is not None,
        error=None if version else "nothing to redo",
        version_index=version["version_index"] if version else None,
    )
    if version is None:
        raise HTTPException(status_code=409, detail="nothing to redo")
    response = {"json_ir": version["json_ir"], "stats": version["stats"],
                "version_index": version["version_index"]}
    return await _export_field(export_format)(response, version["json_ir"])


@app.get("/v1/projects/{project_id}/render")
async def project_render(project_id: str, format: Literal["step", "stl", "glb"] = "glb"):
    """Raw binary export of the project's CURRENT version, for restoring
    the viewport on page load (the frontend already has the ir/stats from
    GET /v1/projects/{id}; it only needs bytes here, so this returns the
    file directly rather than wrapping it in base64+JSON like the
    generate/undo/redo endpoints do)."""
    try:
        project = STORE.get_project(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="project not found")
    if project["current"] is None:
        raise HTTPException(status_code=409, detail="project has no versions yet")

    exported = await orchestrator.export(project["current"]["json_ir"], format)
    if exported is None:
        raise HTTPException(status_code=422, detail="export failed")
    data, content_type, stats = exported
    return Response(content=data, media_type=content_type,
                     headers={"X-Geometry-Stats": json.dumps(stats),
                              "Content-Disposition": f'attachment; filename="part.{format}"'})


@app.post("/v1/projects/{project_id}/log-download")
async def log_download(project_id: str):
    """Explicit download-intent signal, called by the frontend right when
    a user clicks a download button (see frontend/src/App.jsx's
    handleDownload). Deliberately separate from GET .../render above --
    that endpoint is ALSO used to restore the viewport after a page
    reload, and conflating the two would make every reload look like an
    "accepted" signal in compute_outcomes() below. This endpoint does
    nothing but log; the actual file bytes still come from .../render."""
    try:
        STORE.get_project(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="project not found")
    STORE.log_event(project_id=project_id, action="download", success=True)
    return {"logged": True}


# ---------------------------------------------------------------------- #
# Request log (Phase 3 item 2): "log every production request: prompt,
# generated IR, validity outcome, and -- critically -- what the user did
# next." See store.py's compute_outcomes() docstring for exactly what
# each outcome label does and doesn't claim to mean -- this is raw event
# sequence, not a validated read of user satisfaction.
# ---------------------------------------------------------------------- #

@app.get("/v1/logs")
async def get_logs(project_id: str | None = None, limit: int = 200):
    return STORE.list_events(project_id=project_id, limit=limit)


@app.get("/v1/logs/outcomes")
async def get_log_outcomes(project_id: str | None = None, limit: int = 500):
    return STORE.compute_outcomes(project_id=project_id, limit=limit)


@app.get("/v1/logs/summary")
async def get_log_summary():
    return STORE.log_summary()
