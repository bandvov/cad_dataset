# llm-service

The self-correcting CAD generation orchestrator: sits between the product/
UI layer and two backend services --

```
product/UI  --->  llm-service  --->  llamacpp (fine-tuned Gemma, GGUF)
                       |
                       v
                  geometry service (../service/) : compile / validate / export
```

`POST /v1/generate` implements the loop: render the prompt (via
`chat_format.py`, shared with training so wording matches what the model
was trained on), call llama.cpp, parse JSON, validate against the geometry
service, and on failure feed the real error back as a repair turn
(`chat_format.render_repair_user_turn` -- the exact shape
`../gen_repair.py` trained the model to handle), retrying up to
`max_attempts`. `success=false` after that means give up and tell the
user, not silently return broken geometry.

## Verification status

Not executed in this repo's authoring sandbox: no `fastapi`/`httpx`
installed there, no Docker, no network to pull the llama.cpp image or a
real GGUF model. What that means concretely:

- `orchestrator.extract_json()` (pure Python, no I/O) -- smoke-tested
  standalone against clean JSON, markdown-fenced JSON, and JSON with
  stray surrounding text.
- `orchestrator.generate_stream()`'s event sequencing -- traced end-to-end
  with `httpx`/`_chat`/`_compile` stubbed out (no real network needed for
  this part): confirmed the fail→repair→retry→success sequence, the
  exhausted-attempts failure path, and the JSON-parse-failure path all
  produce the correct event order and terminal event. What was NOT
  verified is the real HTTP calls themselves (`_chat`/`_compile`'s actual
  request/response handling against a live llama.cpp/geometry service).
- The llama.cpp image tag/env vars (`ghcr.io/ggml-org/llama.cpp:server-cuda`,
  `LLAMA_ARG_MODEL` etc.) and the `/v1/chat/completions` OpenAI-compatible
  shape are confirmed from current llama.cpp documentation/examples, not
  run here.
- The `convert` service's `convert_hf_to_gguf.py` path and `llama-quantize`
  binary name inside the `full-cuda` image tag are the documented
  locations but were not verified against a real pull -- llama.cpp's image
  layout has changed before (the project moved from `ggerganov/llama.cpp`
  to `ghcr.io/ggml-org/llama.cpp` on GitHub Container Registry).

Test each piece before trusting the whole loop: `/health` on all three
services first, then a raw curl against `llamacpp:8080/v1/chat/completions`,
then `llm-service:8001/v1/generate` with a trivial prompt.

## Getting a GGUF model

1. Train + merge per `../training/README.md` -- you should have
   `../training/outputs/merged/` (a plain HF model directory).
2. Convert + quantize:
   ```bash
   cp .env.example .env   # set GGUF_FILENAME, QUANT_TYPE
   docker compose --profile tools run --rm convert
   ```
   Produces `./models/<GGUF_FILENAME>`. This step was not run in this
   repo's sandbox (see Verification status) -- if the script path has
   moved, `docker compose --profile tools run --rm convert bash` to get
   a shell in the image and find it (`find / -name "convert_hf*"`).

## Running the full stack

**Preferred**: the root `docker-compose.yml` (repo root, one directory up)
runs the entire application -- geometry service, llama.cpp, this
orchestrator, and the frontend -- as one stack, one command:

```bash
cd ..
cp .env.example .env
docker compose up --build
```

See the root `README.md` for what's included/excluded (training and GGUF
conversion are deliberately separate, offline steps).

**Alternative**: run just this directory's services against a
geometry service running elsewhere, or combine only two of the three
compose files. Two ways:

```bash
# multi-file -f, sharing a network via -p (works on recent compose;
# see the fallback below if your version handles this differently)
docker compose -p cad-stack -f ../service/docker-compose.yml -f docker-compose.yml up

# or point at an already-running geometry service by host-mapped port
# instead of relying on in-network service-name resolution
GEOMETRY_SERVICE_URL=http://host.docker.internal:8000 docker compose up llamacpp llm-service
```

## Smoke test

```bash
curl localhost:8001/health
curl -X POST localhost:8001/v1/generate -H "Content-Type: application/json" -d '{
  "prompt": "A 40x30mm plate extruded 10mm thick with a 3mm fillet on the top edges.",
  "max_attempts": 3
}'
```

A healthy response has `"success": true`, a `json_ir` that matches the
prompt, and `attempts` — ideally 1, since that's a simple single-chain
example the model should get right first try. If `attempts` is
consistently >1 even on simple prompts, or `success` is false, check
`conversation` in the response for the actual repair turns exchanged --
that's the same signal you'd log in production for the data flywheel
(see the earlier product-layer discussion: abandoned/heavily-repaired
prompts are exactly the highest-value next training examples).

## Streaming progress (NDJSON)

`POST /v1/generate` blocks until the whole loop finishes, which can be
several LLM round-trips deep on a hard prompt. `POST /v1/generate/stream`
runs the identical loop (same `orchestrator.generate_stream()` --
`generate()` is just a thin wrapper that drains it, so there's one
implementation, not two that can drift) but streams one JSON object per
line as each step happens:

```bash
curl -N -X POST localhost:8001/v1/generate/stream \
  -H "Content-Type: application/json" \
  -d '{"prompt": "A 40x30mm plate, 10mm thick."}'
```
(`-N` disables curl's output buffering so lines print as they arrive.)

```
{"event": "start", "max_attempts": 3}
{"event": "attempt_start", "attempt": 1, "max_attempts": 3}
{"event": "llm_response", "attempt": 1, "content": "..."}
{"event": "validating", "attempt": 1}
{"event": "attempt_failed", "attempt": 1, "error_type": "CompileError", "error": "..."}
{"event": "repairing", "attempt": 1, "next_attempt": 2}
{"event": "attempt_start", "attempt": 2, "max_attempts": 3}
...
{"event": "success", "attempts": 2, "json_ir": {...}, "stats": {...}, "conversation": [...]}
```

Terminal line is always exactly one `success` or `failure` event. If
`export_format` was set and the run succeeded, one more `{"event":
"exported", ...}` line follows with the file. `Content-Type` is
`application/x-ndjson` -- most HTTP clients (fetch with a `ReadableStream`
reader, `httpx` with `iter_lines()`) can consume this directly without a
special SSE/NDJSON library.

This is what you want behind a "generating..." progress UI in the product
layer -- show "attempt 2 of 3, fixing a validation error" instead of a
silent spinner for however many repair rounds it takes.

## Editing an existing part

Two ways, depending on whether you want persistence:

**Stateless** (caller manages state): pass `base_ir` explicitly to
`/v1/generate` -- the orchestrator renders it as a regenerate turn, same
shape as `../gen_regenerate.py`'s training data:

```bash
curl -X POST localhost:8001/v1/generate -H "Content-Type: application/json" -d '{
  "prompt": "Make the plate twice as thick.",
  "base_ir": { ...previous json_ir... }
}'
```

**Projects** (persisted, versioned -- the normal product flow): see below.

## Projects: persisted, versioned parts

A "project" is a part with history -- every successful generation appends
a version; undo/redo moves a pointer through that history without losing
it (see `app/store.py` for the exact semantics, including what happens if
you generate again after an undo -- it truncates the redo-future, standard
editor behavior). Backed by SQLite at `DB_PATH` (default
`/data/cad_sessions.db`, bind-mounted to `./data` by `docker-compose.yml`
so it survives container restarts).

```bash
# create a project
curl -X POST localhost:8001/v1/projects -H "Content-Type: application/json" \
  -d '{"name": "Mounting bracket"}'
# -> {"id": "...", "name": "Mounting bracket", ...}

# generate in it -- base_ir is taken automatically from the project's
# current version, you don't pass it yourself
curl -X POST localhost:8001/v1/projects/<id>/generate -H "Content-Type: application/json" \
  -d '{"prompt": "A 40x30mm plate, 10mm thick, with a 3mm fillet."}'

# iterate -- this becomes version 1, automatically based on version 0
curl -X POST localhost:8001/v1/projects/<id>/generate -H "Content-Type: application/json" \
  -d '{"prompt": "Make it twice as thick."}'

# undo back to version 0
curl -X POST "localhost:8001/v1/projects/<id>/undo?export_format=glb"

# fetch project metadata + version history (no file bytes)
curl localhost:8001/v1/projects/<id>

# raw binary export of the CURRENT version -- for restoring a viewport
# after a page reload, when you already have json_ir/stats from the GET
# above and just need render bytes
curl "localhost:8001/v1/projects/<id>/render?format=step" -o part.step
```

`GET /v1/projects/<id>` response shape:
```json
{
  "id": "...", "name": "...", "current_version_index": 1, "version_count": 2,
  "can_undo": true, "can_redo": false,
  "history": [{"version_index": 0, "prompt": "...", "created_at": "..."}, ...],
  "current": {"version_index": 1, "prompt": "...", "json_ir": {...}, "stats": {...}}
}
```

Note `history` entries have no `json_ir` -- only `current` does. To fetch a
**specific historical version's** full IR (not just the current one):
```bash
curl localhost:8001/v1/projects/<id>/versions/0
# -> {"id": "...", "version_index": 0, "prompt": "...", "json_ir": {...}, "stats": {...}, "created_at": "..."}
```
This is what `mine_flywheel_data.py`'s pairing step uses -- the "eventual
successful version" that fixes a mined failure is very often no longer
the project's current version by the time mining runs.

## Structured editing (Phase 2 item 4): apply an edited tree directly

For when the model gets something wrong, or the user wants an exact
number rather than re-prompting and hoping. `POST /v1/projects/{id}/apply`
takes a full `json_ir` (the frontend patches one field and sends the
whole tree back), validates it via `orchestrator.compile_only()` --
straight to the geometry service, **no model call at all** -- and versions
it on success exactly like a prompted edit:

```bash
curl -X POST localhost:8001/v1/projects/<id>/apply -H "Content-Type: application/json" -d '{
  "json_ir": { ...edited tree... }
}'
```

422 on invalid geometry, same `error_type`/`error` shape as `/v1/compile`
-- this endpoint is a thin pass-through to the geometry service's own
validation, it doesn't add its own rules. Versions created this way store
`prompt: null` (there wasn't one); `GET /v1/projects/<id>`'s `history`
reflects that, and the frontend renders it as `"(edit)"` when
reconstructing chat history on page restore.

## Request log (Phase 3 item 2)

Every mutating action -- generate (stateless and project-scoped), apply,
undo, redo, download -- is logged: prompt, success/failure, error detail,
attempts, which version it produced (if any), and on FAILURE the actual
attempted IR (`failed_ir` -- useful precisely because it's exactly the
highest-value future training data, per the earlier data-flywheel
discussion: real failures your synthetic generators wouldn't invent).

```bash
# raw event stream
curl "localhost:8001/v1/logs?project_id=<id>&limit=100"

# aggregate: event counts, success rate, avg attempts, per action type
curl localhost:8001/v1/logs/summary

# "what happened next" classification -- see below before trusting this
curl "localhost:8001/v1/logs/outcomes?project_id=<id>"
```

**Read this before treating `/v1/logs/outcomes` as a satisfaction metric.**
"What did the user do next" isn't something this service can observe as
*intent* -- only as a raw fact (which action, if any, followed). Each
generate/apply event gets classified by looking at the very next event in
the same project:

| outcome | meaning |
|---|---|
| `accepted` | next action was an explicit download -- the one genuinely positive signal here (see the `log-download` endpoint note below for why this needs its own explicit signal rather than reusing the render/restore GET) |
| `edited` | next action was a manual apply (Phase 2 item 4) -- the model's result needed a hand fix |
| `undone` | next action was undo -- rejected outright |
| `retried` | THIS event failed, and the next action was another generate -- a real failure the user tried to route around |
| `continued` | THIS event succeeded, and the next action was another generate -- could be healthy iteration ("now add a hole") or could mean the result wasn't quite right; **this log genuinely can't tell those apart**, and the label doesn't pretend to |
| `no_further_activity` | nothing followed -- ambiguous between "accepted and never exported" and "abandoned," surfaced as its own label rather than guessed into either |

`accepted`/`edited`/`undone`/`retried` are reasonably trustworthy signals.
`continued` and `no_further_activity` are not verdicts -- they're exactly
the cases where a human-rated eval (Phase 3 item 1, not yet built) would
add the judgment this event log structurally cannot.

**Why downloads need their own explicit log call**: `GET
/v1/projects/{id}/render` is used for two different things -- an actual
user-initiated download, AND restoring the viewport silently after a page
reload. If both counted as "download" events, every page refresh would
look like an "accepted" signal. `POST /v1/projects/{id}/log-download`
(called by the frontend's download button, not the render fetch itself)
keeps those separate.

## Config (`.env`, see `.env.example`)

| var | default | meaning |
|---|---|---|
| `GGUF_FILENAME` | model.gguf | file in `./models/` llama.cpp serves |
| `LLAMACPP_IMAGE` | `ghcr.io/ggml-org/llama.cpp:server-cuda` | swap to `:server` for CPU-only |
| `N_GPU_LAYERS` | 999 | set 0 for CPU-only |
| `CTX_SIZE` | 4096 | llama.cpp context window |
| `LLM_SERVICE_PORT` | 8001 | host port for this orchestrator |
| `GEOMETRY_SERVICE_URL` | http://geometry:8000 | override if not running the combined stack |
| `DB_PATH` | /data/cad_sessions.db | project/version store location (set in docker-compose.yml, not `.env`) |
