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

NOTE on export error propagation: orchestrator.export() used to return
None on any failure, so every caller here (project_render, _export_field,
the /v1/generate export branch, the /v1/generate/stream "exported" event)
collapsed a BoundsError, a CompileError (stored IR no longer validates),
and a genuine build123d ExportError into the same opaque "export failed"
422 -- no way to tell which without going around this service and hitting
the geometry service directly. orchestrator.export() now raises
ExportFailed carrying the geometry service's real error_type/error; every
call site below catches it and threads that detail through instead.
"""

from __future__ import annotations
import base64
import json
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orchestrator import Orchestrator, ExportFailed
from store import ProjectStore, ProjectNotFound

app = FastAPI(title="LLM Service (CAD generation orchestrator)", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # your frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


orchestrator = Orchestrator(
    llama_url=os.environ.get("LLAMACPP_URL", "http://llamacpp:8080"),
    geometry_url=os.environ.get("GEOMETRY_SERVICE_URL", "http://geometry:8000"),
    http_timeout=float(os.environ.get("HTTP_TIMEOUT", "60")),
)

def _env_float(key: str) -> float | None:
    val = os.environ.get(key)
    return float(val) if val else None  # unset or blank -> None (no expiry), not 0.0


STORE = ProjectStore(
    os.environ.get("DB_PATH", "/data/cad_sessions.db"),
    session_lifetime_hours=_env_float("SESSION_LIFETIME_HOURS"),
)


class GenerateRequest(BaseModel):
    prompt: str
    base_ir: dict | None = None  # present -> this is an edit/regenerate, not a fresh generate
    max_attempts: int = 3
    export_format: Literal["step", "stl", "glb"] | None = None


class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/v1/auth/signup")
async def signup(req: SignupRequest):
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    try:
        user = STORE.create_user(req.email, req.password)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"token": STORE.create_session(user["id"]), "user": user}


@app.post("/v1/auth/login")
async def login(req: LoginRequest):
    user = STORE.authenticate(req.email, req.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    return {"token": STORE.create_session(user["id"]), "user": user}


_security = HTTPBearer()


async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(_security)) -> dict:
    """Reads the Authorization: Bearer <token> header, verifies it against
    the sessions table, and injects the user."""
    user_id = STORE.verify_session(creds.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    user = STORE.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return user


@app.post("/v1/auth/logout")
async def logout(creds: HTTPAuthorizationCredentials = Depends(_security)):
    STORE.delete_session(creds.credentials)
    return {"logged_out": True}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/generate")
async def generate(req: GenerateRequest):
    """The main product-facing endpoint. Deliberately NOT behind auth
    (see SESSION_HANDOFF.md) -- its log_event() call below gets
    user_id=None, same bucket as legacy/pre-migration rows. success=false
    with a populated `error` means the model couldn't produce valid
    geometry within max_attempts -- surface that to the user rather than
    the raw IR; `conversation` is included for debugging/observability."""
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
        try:
            data, content_type, _stats = await orchestrator.export(result.json_ir, req.export_format)
            response["file_b64"] = base64.b64encode(data).decode("ascii")
            response["content_type"] = content_type
        except ExportFailed as e:
            # Generation itself succeeded -- only the optional export
            # failed. Don't fail the whole response over that; surface it
            # as its own field so the caller knows the part is valid but
            # couldn't be exported, and why.
            response["export_error_type"] = e.error_type
            response["export_error"] = e.error
    return response


@app.post("/v1/generate/stream")
async def generate_stream(req: GenerateRequest):
    """Same loop as /v1/generate, streamed as newline-delimited JSON
    (NDJSON) -- one `{"event": ...}\\n` object per line, flushed as each
    step happens, so a client can show live progress ("attempt 1/3",
    "repairing...") instead of waiting silently for the whole loop.

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
                try:
                    data, content_type, _stats = await orchestrator.export(
                        event["json_ir"], req.export_format
                    )
                    yield json.dumps({
                        "event": "exported",
                        "content_type": content_type,
                        "file_b64": base64.b64encode(data).decode("ascii"),
                    }) + "\n"
                except ExportFailed as e:
                    yield json.dumps({
                        "event": "export_failed",
                        "error_type": e.error_type,
                        "error": e.error,
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
# Projects: persisted, versioned feature trees (Phase 2 item 1). See
# store.py for the undo/redo model. The stateless /v1/generate above
# still exists for one-off use; these endpoints are for the normal
# product flow where a user is iterating on one part across multiple
# turns.
# ---------------------------------------------------------------------- #

class CreateProjectRequest(BaseModel):
    name: str = "Untitled part"


class ProjectGenerateRequest(BaseModel):
    prompt: str
    max_attempts: int = 3
    export_format: Literal["step", "stl", "glb"] | None = "glb"


def _export_field(export_format: str | None):
    """Decorator-free helper: attach a base64 export to a response dict
    if requested and available, used by generate/undo/redo/apply so the
    frontend always has something to render immediately after any of
    these actions.

    On ExportFailed, does NOT raise -- the mutating action itself (the
    new version, the undo/redo pointer move, the applied edit) already
    succeeded and is already persisted; failing the whole request over a
    failed render/export would be misleading. Instead attaches
    export_error_type/export_error so the frontend can show "saved, but
    couldn't render a preview: <reason>" rather than a silent missing
    viewport with no explanation, or a rejected request that actually
    went through server-side."""
    async def attach(response: dict, ir: dict):
        if not export_format:
            return response
        try:
            data, content_type, _stats = await orchestrator.export(ir, export_format)
            response["file_b64"] = base64.b64encode(data).decode("ascii")
            response["content_type"] = content_type
        except ExportFailed as e:
            response["export_error_type"] = e.error_type
            response["export_error"] = e.error
        return response
    return attach


def _require_owned_project(project_id: str, user: dict) -> dict:
    """Fetches a project and verifies the current user owns it. Legacy
    rows with owner_id=None (pre-auth data not yet backfilled by
    migrate_legacy_owner.py -- auth step 8) are accessible to any
    authenticated user for now, not locked out. 404 (not 403) on a
    mismatch, same as "doesn't exist" -- ownership isn't something to
    leak via status code."""
    try:
        project = STORE.get_project(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="project not found")
    if project["owner_id"] is not None and project["owner_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@app.post("/v1/projects")
async def create_project(req: CreateProjectRequest, user: dict = Depends(get_current_user)):
    return STORE.create_project(req.name, owner_id=user["id"])


@app.get("/v1/projects")
async def list_projects(user: dict = Depends(get_current_user)):
    return STORE.list_projects(owner_id=user["id"])


@app.get("/v1/projects/{project_id}")
async def get_project(project_id: str, user: dict = Depends(get_current_user)):
    return _require_owned_project(project_id, user)


@app.get("/v1/projects/{project_id}/versions/{version_index}")
async def get_project_version(project_id: str, version_index: int,
                                user: dict = Depends(get_current_user)):
    """Fetch a specific historical version's full IR -- GET
    /v1/projects/{id} only returns full IR for `current`, metadata only
    (prompt, created_at) for past versions in `history`. Used by
    mine_flywheel_repairs.py to resolve a logged fix's version_index back
    to an actual json_ir."""
    _require_owned_project(project_id, user)
    version = STORE.get_version(project_id, version_index)
    if version is None:
        raise HTTPException(status_code=404, detail="version not found")
    return version


@app.delete("/v1/projects/{project_id}")
async def delete_project(project_id: str, user: dict = Depends(get_current_user)):
    _require_owned_project(project_id, user)
    STORE.delete_project(project_id)
    return {"deleted": True}


@app.post("/v1/projects/{project_id}/generate")
async def project_generate(project_id: str, req: ProjectGenerateRequest,
                             user: dict = Depends(get_current_user)):
    """Same self-correcting loop as /v1/generate, but base_ir is taken
    automatically from the project's current version (None for a
    project's first generation), and a successful result is appended as
    a new version -- this IS the "edits compose" behavior, not something
    the frontend has to orchestrate by passing base_ir itself."""
    project = _require_owned_project(project_id, user)

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
        user_id=user["id"],
    )
    return response


class ApplyEditRequest(BaseModel):
    json_ir: dict
    export_format: Literal["step", "stl", "glb"] | None = "glb"


@app.post("/v1/projects/{project_id}/apply")
async def project_apply_edit(project_id: str, req: ApplyEditRequest,
                               user: dict = Depends(get_current_user)):
    """Structured-editing fallback (Phase 2 item 4): apply a directly-
    edited feature tree without going through the model at all. Validates
    against the geometry service via orchestrator.compile_only() and, on
    success, appends a new version with the SAME semantics as a
    model-generated edit. `prompt` is stored as None for these versions."""
    _require_owned_project(project_id, user)

    result = await orchestrator.compile_only(req.json_ir)
    if not result.get("valid"):
        STORE.log_event(
            project_id=project_id, action="apply", success=False,
            error_type=result.get("error_type"), error=result.get("error"),
            failed_ir=req.json_ir, user_id=user["id"],
        )
        raise HTTPException(status_code=422, detail={
            "error_type": result.get("error_type"),
            "error": result.get("error"),
        })

    version = STORE.add_version(project_id, req.json_ir, None, result.get("stats"))
    STORE.log_event(
        project_id=project_id, action="apply", success=True,
        version_index=version["version_index"], user_id=user["id"],
    )
    response = {
        "success": True,
        "json_ir": req.json_ir,
        "stats": result.get("stats"),
        "version_index": version["version_index"],
    }
    return await _export_field(req.export_format)(response, req.json_ir)


@app.post("/v1/projects/{project_id}/undo")
async def project_undo(project_id: str, export_format: Literal["step", "stl", "glb"] | None = "glb",
                         user: dict = Depends(get_current_user)):
    _require_owned_project(project_id, user)
    version = STORE.undo(project_id)
    STORE.log_event(
        project_id=project_id, action="undo", success=version is not None,
        error=None if version else "nothing to undo",
        version_index=version["version_index"] if version else None,
        user_id=user["id"],
    )
    if version is None:
        raise HTTPException(status_code=409, detail="nothing to undo")
    response = {"json_ir": version["json_ir"], "stats": version["stats"],
                "version_index": version["version_index"]}
    return await _export_field(export_format)(response, version["json_ir"])


@app.post("/v1/projects/{project_id}/redo")
async def project_redo(project_id: str, export_format: Literal["step", "stl", "glb"] | None = "glb",
                         user: dict = Depends(get_current_user)):
    _require_owned_project(project_id, user)
    version = STORE.redo(project_id)
    STORE.log_event(
        project_id=project_id, action="redo", success=version is not None,
        error=None if version else "nothing to redo",
        version_index=version["version_index"] if version else None,
        user_id=user["id"],
    )
    if version is None:
        raise HTTPException(status_code=409, detail="nothing to redo")
    response = {"json_ir": version["json_ir"], "stats": version["stats"],
                "version_index": version["version_index"]}
    return await _export_field(export_format)(response, version["json_ir"])


@app.get("/v1/projects/{project_id}/render")
async def project_render(project_id: str, format: Literal["step", "stl", "glb"] = "glb",
                           user: dict = Depends(get_current_user)):
    """Raw binary export of the project's CURRENT version, for restoring
    the viewport on page load. Unlike _export_field()'s callers above,
    export here IS the entire point of the request -- there's no other
    mutating action that already succeeded -- so an ExportFailed DOES
    become the request's own 422, but now with the geometry service's
    real error_type/error instead of the generic "export failed" this
    used to collapse to."""
    project = _require_owned_project(project_id, user)
    if project["current"] is None:
        raise HTTPException(status_code=409, detail="project has no versions yet")

    try:
        data, content_type, stats = await orchestrator.export(project["current"]["json_ir"], format)
    except ExportFailed as e:
        raise HTTPException(status_code=422, detail={
            "error_type": e.error_type,
            "error": e.error,
        })
    return Response(content=data, media_type=content_type,
                     headers={"X-Geometry-Stats": json.dumps(stats),
                              "Content-Disposition": f'attachment; filename="part.{format}"'})


@app.post("/v1/projects/{project_id}/log-download")
async def log_download(project_id: str, user: dict = Depends(get_current_user)):
    """Explicit download-intent signal, called by the frontend right when
    a user clicks a download button. Deliberately separate from GET
    .../render above -- that endpoint is ALSO used to restore the
    viewport after a page reload, and conflating the two would make
    every reload look like an "accepted" signal in compute_outcomes()
    below. This endpoint does nothing but log; the actual file bytes
    still come from .../render."""
    _require_owned_project(project_id, user)
    STORE.log_event(project_id=project_id, action="download", success=True, user_id=user["id"])
    return {"logged": True}


# ---------------------------------------------------------------------- #
# Request log (Phase 3 item 2 / auth step 7): scoped by user_id.
# See store.py's compute_outcomes() docstring for exactly what each
# outcome label does and doesn't claim to mean -- this is raw event
# sequence, not a validated read of user satisfaction.
# ---------------------------------------------------------------------- #

@app.get("/v1/logs")
async def get_logs(project_id: str | None = None, limit: int = 200,
                    user: dict = Depends(get_current_user)):
    return STORE.list_events(project_id=project_id, user_id=user["id"], limit=limit)


@app.get("/v1/logs/outcomes")
async def get_log_outcomes(project_id: str | None = None, limit: int = 500,
                             user: dict = Depends(get_current_user)):
    return STORE.compute_outcomes(project_id=project_id, user_id=user["id"], limit=limit)


@app.get("/v1/logs/summary")
async def get_log_summary(user: dict = Depends(get_current_user)):
    return STORE.log_summary(user_id=user["id"])
