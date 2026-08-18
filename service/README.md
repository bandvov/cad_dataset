# Geometry service (compile / validate / export)

HTTP wrapper around `compiler.py`/`validator.py` (the same IR interpreter
used by `build_dataset.py` and the training eval callback), for the
production runtime path: the inference self-correction loop, export/render
pipeline, and any structured-editing UI backend.

## Why this is its own service, not a shared library call

- Different resource profile than the LLM server (CPU-bound native
  geometry kernel vs. GPU-bound inference) -- scales independently.
- One canonical definition of "what does this IR mean," used by every
  runtime consumer, rather than re-imported/vendored copies that can drift
  out of sync with what training actually validated against.
- OCCT can segfault or hang on adversarial/hallucinated IR; isolating that
  in per-job subprocess workers (same pattern as `executor.BatchExecutor`)
  means a bad request can't take down the model-serving process too.

Offline batch tools (`build_dataset.py`, the training eval callback) keep
importing `schema.py`/`compiler.py`/`executor.py` directly in-process --
no reason to add a network hop to a batch job already running in a
container with build123d installed.

## Verification status

Not executed in the sandbox this was authored in: no `fastapi`/`uvicorn`
installed there, no network to get them, no Docker. What WAS verified:

- `worker_pool.py`'s subprocess mechanics (compile success/failure paths,
  export success/failure paths, concurrent submission across a multi-
  worker pool) were smoke-tested against `stub_build123d/` (which now
  includes fake `export_step`/`export_stl`/`export_gltf` -- placeholder
  bytes only, never treat stub-generated files as real geometry output).
- `main.py`'s FastAPI routing itself was NOT executed (no fastapi
  installed here) -- syntax/AST-checked only.
- `export_step`/`export_stl`/`export_gltf` are confirmed as real
  build123d free functions (not `Part` methods -- those are deprecated)
  from current build123d docs, but the exact call was not run against a
  real install.

Before trusting this in production: `docker compose build && docker
compose up`, then run the curl smoke test below against a **real**
build123d install and a genuinely simple part first.

## Endpoints

**`GET /health`** -- liveness + pool size.

**`POST /v1/compile`** -- validate only, no file output.
```bash
curl -X POST localhost:8000/v1/compile -H "Content-Type: application/json" -d '{
  "json_ir": {
    "operation": "part",
    "features": [
      {"id": "sketch_1", "feature_type": "Sketch", "primitives": [
        {"type": "Rectangle", "parameters": {"width": 40, "height": 30, "position": [0,0], "rotation": 0, "mode": "ADD"}}]},
      {"id": "extrude_1", "feature_type": "Extrude", "source": "sketch_1", "amount": 10, "operation": "ADD"}
    ]
  }
}'
# -> {"valid": true, "stats": {"volume": ..., "n_faces": ..., ...}}
```

**`POST /v1/export`** -- validate + export to STEP/STL/GLB, returns the
file bytes directly (`format`: `"step"` | `"stl"` | `"glb"`, default `step`).
Geometry stats come back in the `X-Geometry-Stats` header. A 422 response
means the IR didn't validate -- same `error_type`/`error` shape as
`/v1/compile`, don't retry the export without fixing the IR first.
```bash
curl -X POST localhost:8000/v1/export -H "Content-Type: application/json" \
  -d '{"json_ir": {...}, "format": "step"}' -o part.step -D -
```

## Using this from the inference self-correction loop

```
generate IR from model
  -> POST /v1/compile
  -> if valid: done, optionally POST /v1/export for the deliverable
  -> if invalid: feed {error_type, error} back to the model as a repair
     turn (this is exactly the shape gen_repair.py trained the model on),
     retry, cap at ~2-3 attempts
  -> if still invalid: surface a clear failure to the user
```

## Resource limits -- read before scaling pool size

Two independent layers of defense, added deliberately as separate
mechanisms rather than relying on one:

1. **Semantic bounds** (`schema.validate_bounds()`, checked both here in
   the FastAPI process before a job is ever submitted, AND inside
   `compiler.py` itself as the actual last line of defense regardless of
   caller). Rejects obviously-absurd values fast -- a hallucinated pattern
   `count: 50000`, a `1e9`mm dimension, a 200-feature tree -- with a clear
   `BoundsError` and no worker spent. This is what actually stops a
   pathological request; tune `schema.BOUNDS` based on production data
   (log requests that hit these limits -- that tells you if a bound is too
   tight for real usage before it tells you about a hallucination).
2. **Per-worker resource ceilings** (`WORKER_MEM_LIMIT_MB`/`WORKER_CPU_LIMIT_S`,
   `JOB_TIMEOUT`) -- the backstop for anything that passes bounds checking
   but still turns out to be pathological in practice (e.g. a legitimately
   complex but slow boolean operation). `POOL_SIZE` workers each hold a
   full build123d/OCP import in memory; these rlimits are **best-effort**
   (see `worker_pool.py` docstring for why) -- the real backstop is the
   container-level `deploy.resources.limits` in `docker-compose.yml`, size
   it for `POOL_SIZE * WORKER_MEM_LIMIT_MB` plus headroom.

## Config (`.env`, see `.env.example`)

| var | default | meaning |
|---|---|---|
| `SERVICE_PORT` | 8000 | host port |
| `POOL_SIZE` | 4 | concurrent worker subprocesses |
| `JOB_TIMEOUT` | 20 | per-job seconds before kill+respawn |
| `WORKER_MEM_LIMIT_MB` | 2048 | best-effort per-worker RLIMIT_AS |
| `WORKER_CPU_LIMIT_S` | 30 | best-effort per-worker RLIMIT_CPU |
| `SERVICE_CPU_LIMIT` / `SERVICE_MEM_LIMIT` | 4 / 8g | container-level ceiling |
