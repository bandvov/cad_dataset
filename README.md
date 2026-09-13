# CAD feature-tree dataset generator (build123d, JSON IR)

Generates a Gemma-chat-completion dataset for CAD feature-tree generation,
repair, and regeneration, targeting a structured JSON intermediate
representation (see `schema.py`) that `compiler.py` interprets directly
into build123d geometry (no source-code generation step in between).

## IMPORTANT — verification status

This was built and its **plumbing** was tested in a sandbox with **no
network access**, so `build123d` could not be installed or executed here.
Everything that doesn't require real geometry (schema validation, the
generators, recipe replay, fault injection logic, subprocess/executor
wiring, jsonl I/O, dedupe/split, chat formatting) was exercised end-to-end
against `stub_build123d/` — a fake, minimal `build123d` stand-in that
implements the same call surface with fabricated volumes, just enough to
smoke-test control flow and error propagation. **It does not validate real
geometry** and cannot tell you whether `compiler.py`'s actual build123d API
calls (exact kwarg names, `Plane`/`Pos`/`Rot` composition order, etc.) are
correct for your installed version.

**Before trusting any generated data, you must:**

```bash
pip install build123d --break-system-packages   # or into a venv
python3 build_dataset.py --n-single-per-type 20 --n-chains 50 \
    --n-repair 30 --n-regenerate 30 --out-dir out_smoke
```

Verification runs through a **persistent worker subprocess**
(`executor.BatchExecutor`), not one fresh interpreter per record — the
first record pays build123d/OCP's cold-import cost (commonly several
seconds), everything after that is fast. You should see progress lines
like `[single] 100/260 (500.0 rec/s, ...)` streaming during verification;
if the very first batch takes a couple minutes before its first progress
line, that's the import cost, not a hang -- give it a moment before
assuming something's stuck. If a single record genuinely hangs (a
pathological OCCT call), that one worker is killed and respawned
automatically and the batch continues.

Check the console output: verified vs. quarantined counts per generator.
If quarantine rates are high, inspect `out_smoke/*.quarantine.jsonl` —
each entry carries `verification_error` with the real exception. Common
first-run fixes are typically small API-name drift in `compiler.py`
(build123d's algebra API has changed method names across versions; pin a
version and check its changelog against the calls in `compiler.py`'s
`_do_*` methods) rather than logic errors, since the interpreter's control
flow was already exercised via the stub.

Do not delete `stub_build123d/` until you've done a real-build123d run —
if something breaks, re-running against the stub with a debugger is the
fastest way to tell "my Python logic is wrong" apart from "my build123d
API call is wrong."

## Architecture

```
schema.py              canonical IR field definitions + structural validate_ir()
compiler.py            direct interpreter: IR -> build123d geometry, in-process
executor.py            runs compiler.py in a timeout'd subprocess, isolated
validator.py           geometric sanity checks + stat extraction (real build123d)
primitives.py          parameter samplers, safe ranges, instruction phrasing
chat_format.py         shared turn rendering -- the SAME wording at training
                       and inference, so phrasing can't drift between the
                       dataset and what the running service sends the model
gen_single_feature.py  one feature type per record (full FEATURE_TYPES coverage)
gen_chains.py          2-8 feature chains built from a *replayable recipe*
gen_repair.py          execution-verified fault injection (real error text only)
gen_regenerate.py      replays a chain's recipe with one edited input
build_dataset.py       orchestrates all of the above -> verify -> dedupe -> split;
                       --include-flywheel-data merges verified mined records
mine_flywheel_data.py  flywheel step 1: extract outcome-classified production
                       events (retried/edited/abandoned) from llm-service's
                       admin log -- extraction only; pairing, re-verification,
                       dedup, and chat-format conversion are later steps (see
                       its module docstring)
mine_flywheel_repairs.py  flywheel step 2: pair failed events with the
                       eventual successful fix -> repair records (verified=false)
mine_flywheel_pairs.py standalone variant of step 2 -- consumes step 1's
                       filtered events JSONL (--max-lookforward-minutes)
mine_flywheel_edits.py flywheel step 3: "edited" events paired with the manual
                       apply that followed them -> regenerate records
mine_flywheel_verify.py  flywheel step 4: re-run pairs through real build123d,
                       mark verified true / quarantine drift
mine_flywheel_dedup.py flywheel step 5: dedup vs. corpus via structure_hash
mine_flywheel_gate.py  flywheel volume/quality gate, exit 0/1 (retraining trigger)
mine_repair_pairs.py   earlier pre-auth repair-pair miner -- superseded by the
                       --auth-token scripts above (relevant only if you hit
                       it in old output dirs / branches)
flywheel_common.py     shared fetch/group helpers for the repair/edit miners
migrate_legacy_owner.py  one-time backfill of pre-auth rows -> a "legacy" user
verify_auth_e2e.py     HTTP end-to-end auth check against a live stack
stub_build123d/        fake build123d, PLUMBING TESTS ONLY, see warning above
```

### Why a direct interpreter, not codegen

`compiler.py` walks `ir["features"]` and calls the build123d API in-process
(`bd.extrude(...)`, `bd.fillet(...)`, etc.) rather than emitting a Python
source string and `exec`-ing it. This keeps the IR as the single source of
truth, makes errors easy to attribute to a specific feature id (see
`CompileError` messages), and means there's no second translation layer
that could itself contain bugs independent of the IR.

### Why "recipe replay" for chains/regenerate

`gen_chains.py`'s `apply_*` functions are pure formulas of a `PartState`
(no internal randomness) — e.g. fillet radius is always
`min(state.min_edge * 0.12, 3.0)`. Randomness only picks *which* steps
appear, in what order, and a few discrete choices (pattern counts,
through/blind hole). That full recipe (base dims + step list) is stored in
the record. `gen_regenerate.py` edits one input to the recipe and replays
the same formulas, so every dependent value in the tree — a pattern's
spacing, a boss's size, a hole's Z position — updates consistently. This
is what lets `regenerate` task data actually teach parameter propagation
instead of leaving stale values in an edited tree, which is the most
common way this kind of dataset misleads a fine-tuned model.

### Why fault injection + real execution for repair

`gen_repair.py` never hand-writes an error string. Every "broken" example
is actually run through `execute_ir()`; the pair is only kept if the
broken version *actually fails* and the original *actually succeeds*. This
guarantees the `error` field in every repair record matches what the real
build123d / OCCT kernel says, not an invented approximation — which
matters because that's the signal you want the model to learn to read at
inference time when a user's edit breaks their part.

## Dataset record format & task types

Every record in the pipeline (synthetic and flywheel-mined) shares one
core shape, so `build_dataset.py`'s dedupe/split/chat-format steps never
special-case a source. Fields come from `primitives.Record.to_dict()`
(the synthetic generators) and the `mine_flywheel_*.py` scripts mirror
it exactly (`source: "flywheel"` / `"production_flywheel"`):

```json
{
  "record_id": "chain_abc123",
  "task_type": "generate | repair | regenerate",
  "schema_version": 2,
  "complexity": 5,
  "units": "mm",
  "source": "procedural | flywheel | production_flywheel",
  "instruction": "Add a 3mm fillet to the top edges.",
  "json_ir": { "features": [ ... ] }
}
```

Task-specific extra fields:

- **`generate`** (`gen_single_feature.py`, `gen_chains.py`) — the base
  shape above; chain records (and the regenerate records derived from
  them) also carry `recipe` (base dims + step list) so
  `gen_regenerate.py` can replay the same formulas with one edited input.
- **`repair`** (`gen_repair.py`, flywheel step 2) — adds `broken_ir`,
  `error`, `error_type` (always real build123d/OCCT output, never
  hand-written; see "Why fault injection" above) and
  `fault_description` (synthetic injectors only — `null` for real
  production failures, which don't come with a label attached).
- **`regenerate`** (`gen_regenerate.py`, flywheel step 3) — adds
  `base_ir` (the part being edited) alongside the target `json_ir`.

After verification, records also carry `verified` (bool — the flywheel
scripts always write `verified: false` until step 4 re-runs them through
real build123d) plus `geometry_stats` / `verification_error`.

`chat_format.py` renders instruction + task context into the actual chat
turns, shared by training and inference so the model sees identical
wording at serving time. `build_dataset.py`'s final output is TRL's
conversational `{"prompt": [...], "completion": [...]}` shape
(`completion_only_loss=True`, see `training/README.md`):

```json
{
  "prompt": [{ "role": "user", "content": "..." }],
  "completion": [{ "role": "assistant", "content": "<json_ir as JSON>" }]
}
```

Output files (`build_dataset.py --out-dir out`):

| file | contents |
|---|---|
| `out/train.jsonl`, `out/val.jsonl` | Gemma chat-completion records (what `training/` consumes) |
| `out/train.full.jsonl`, `out/val.full.jsonl` | same records, full IR + metadata, for debugging/inspection |
| `out/*.quarantine.jsonl` | failed verification, each with `verification_error` |
| `out/single_feature.verified.jsonl`, `out/chains.verified.jsonl`, `out/repair.jsonl`, `out/regenerate.jsonl` | per-generator intermediate state |

The train/val split is by a hash of `record_id` (reproducible across
runs), after dedup on an IR structural hash — see the known-limitations
note about near-duplicate topologies.

## Data flywheel (Phase 4)

Mines production usage (via `llm-service`'s request log) back into
training data. Pipeline order:

1. `mine_flywheel_data.py` -- log extraction (done)
2. `mine_flywheel_repairs.py` -- repair-pair construction (done)
3. `mine_flywheel_edits.py` -- edit-pair construction (done)
4. `mine_flywheel_verify.py` -- re-verification via real build123d (done)
5. `mine_flywheel_dedup.py` -- dedup against existing corpus (done)
6. PII/content scrub -- **not implemented**
7. `build_dataset.py --include-flywheel-data` -- merge into train/val (done).
   Consumes step 5's output (`flywheel_deduped.jsonl`) directly --
   `build_dataset.py` runs its own `to_chat_format()` internally as part
   of the merge, so there's no separate chat-format step between dedup
   and merge.
8. `mine_flywheel_gate.py` -- volume/quality gate (done)
9. **TODO**: scheduling -- cron/compose service to run steps 1-8
    periodically (e.g. weekly) against the production `cad_sessions.db`.
10. **TODO**: retraining trigger -- hook step 9's gate into
    `training/train.py`, either manual (point `TRAIN_FILE`/`VAL_FILE` at
    the gated output) or automated (compose job that runs `docker compose
    up train` when the gate passes).

Two other repair-pair miners exist in the tree for historical reasons:
`mine_flywheel_pairs.py` is an older standalone version of step 2 that
consumes step 1's *filtered* events JSONL and takes
`--max-lookforward-minutes`; `mine_repair_pairs.py` predates the auth
work (no `--auth-token`; fetches project/version history on the caller's
own scope) and is superseded by the admin-token scripts above.
`flywheel_common.py` holds the shared helpers (`group_by_project`,
token-aware `fetch_version`) that the step-2/3 scripts import. Remember
everything mined below is `verified: false` until step 4 re-runs it
through real build123d — nothing is trusted just because production
logged it.

**End to end** (requires the app stack running with real build123d;
`$ADMIN_TOKEN` is a `make_admin.py`-granted admin session token):

```bash
# 1. extract outcome-classified events
python mine_flywheel_data.py --llm-service-url http://localhost:8001 \
    --auth-token "$ADMIN_TOKEN" --outcomes retried edited abandoned \
    --out out/flywheel_events.jsonl

# 2. repair pairs (fetches the full unfiltered log itself; alternative:
#    mine_flywheel_pairs.py --in out/flywheel_events.jsonl)
python mine_flywheel_repairs.py --llm-service-url http://localhost:8001 \
    --auth-token "$ADMIN_TOKEN" --out out/flywheel_repairs.jsonl \
    --unfixed-out out/flywheel_unfixed.jsonl

# 3. edit pairs
python mine_flywheel_edits.py --llm-service-url http://localhost:8001 \
    --auth-token "$ADMIN_TOKEN" --out out/flywheel_edits.jsonl

# 4. re-verify through real build123d (executor.BatchExecutor)
python mine_flywheel_verify.py \
    --repairs out/flywheel_repairs.jsonl --edits out/flywheel_edits.jsonl \
    --out-repairs out/flywheel_repairs.verified.jsonl \
    --out-edits out/flywheel_edits.verified.jsonl \
    --quarantine out/flywheel_quarantine.jsonl

# 5. dedup against the existing corpus
python mine_flywheel_dedup.py --corpus out/train.full.jsonl out/val.full.jsonl \
    --candidates out/flywheel_repairs.verified.jsonl out/flywheel_edits.verified.jsonl \
    --out out/flywheel_deduped.jsonl

# 7. merge into the next dataset build (re-checks verified=true itself)
python build_dataset.py --n-single-per-type 300 --n-chains 3000 \
    --n-repair 1500 --n-regenerate 1500 --out-dir out \
    --include-flywheel-data out/flywheel_deduped.jsonl

# 8. volume gate -- exit 1 if below threshold
python mine_flywheel_gate.py --repairs out/flywheel_repairs.verified.jsonl \
    --edits out/flywheel_edits.verified.jsonl \
    --min-repairs 10 --min-edits 10 --min-total 50
```

**Auth (flywheel-auth fix, all 5 steps done)**: steps 1-3 above
(`mine_flywheel_data.py`, `mine_flywheel_pairs.py`, and by extension
`mine_flywheel_repairs.py`/`mine_flywheel_edits.py`, which import from
them) now require `--auth-token` — the session token of a user with
`is_admin=True` (grant one via `llm-service/app/make_admin.py`; also
readable from the `LLM_SERVICE_ADMIN_TOKEN` env var). The log-fetching
calls hit `llm-service`'s admin-scoped `/v1/admin/logs*` routes rather
than the per-user `/v1/logs*` ones, since mining needs to see every
user's production events, not just one caller's own. **Known remaining
limitation**: version-fetch (resolving a fix's `json_ir` via `GET
/v1/projects/{id}/versions/{index}`) is still owner-scoped — an admin
token only resolves fixes for projects it happens to own; a failed fetch
here degrades to "counted as unresolved," not a crash. See
`flywheel_common.py`'s docstring for the full caveat. Verified for real
against a live `uvicorn` instance + seeded SQLite data, not just
syntax-checked — see `SESSION_HANDOFF.md`.

## Selector convention (Fillet/Chamfer/Shell openings)

Selectors are declarative, not raw edge indices (which aren't stable
across parameter changes / regeneration):

```json
{"of": "edges", "filter_by": "Z", "criterion": "max"}
```

`compiler._resolve_selector()` maps this to
`shape.edges().group_by(Axis.Z)[-1]` (top edges) or `[0]` (bottom edges),
or `filter_by: "GeomType"` + `geom_type: "CIRCLE"` for circular edges.
Extend `_resolve_selector` if you need more selector kinds (by face
normal, by radius, etc.) — keep the same declarative-not-indexed
philosophy so regeneration doesn't produce stale/wrong selections.

## Known limitations / things to tighten next

- **Hole feature is a boolean-subtract cylinder/cone stand-in**, not
  build123d's `Hole`/`CounterBoreHole`/`CounterSinkHole` classes (those
  are designed for the builder-API `Locations` context, awkward to drive
  from a flat IR). Geometrically equivalent, but if you specifically want
  the model to learn those class names for downstream code-gen, this will
  need revisiting.
- **`gen_chains.py` complexity is currently capped by `STEP_REGISTRY`** (7
  step kinds); real parts often have deeper feature-specific dependencies
  (e.g. a fillet applied *after* a pattern, patterns of patterns). Easy to
  extend by adding more `apply_*` functions plus their formulas.
- **No multi-body / assembly support** — every IR produces exactly one
  solid. If your target use case includes assemblies, that's a schema
  extension (a `"features"` list per body, plus a top-level assembly
  transform list).
- **Instruction phrasing diversity is template-based** (`primitives.py:
  PHRASING_TEMPLATES`). For a production dataset, consider running a
  fraction of instructions through an LLM paraphraser afterward for more
  natural register variation — the IR/verification pipeline doesn't care
  how the instruction was phrased, only that the `json_ir` is correct.
- **`build_dataset.py`'s train/val split is by IR structural hash**
  (feature-type sequence + booleans), which prevents leaking the exact
  same shape topology across the split but does not prevent near-duplicate
  topologies (e.g. two different chains that both go
  Sketch→Extrude→Fillet→Hole with different dims) from appearing on both
  sides. Tighten by hashing on a coarser "part family" tag if you add one.

## Authentication, admin roles, and legacy data

`llm-service` auth uses opaque session tokens (no JWT, no signing secret
to manage): `POST /v1/auth/signup|login` return `{token, user}`, and
every `/v1/projects*` and `/v1/logs*` call requires
`Authorization: Bearer <token>`. Projects and the request log are scoped
by owner/user — someone else's project returns 404 (not 403), and a
second user can't see your events. Logout revokes immediately;
`SESSION_LIFETIME_HOURS` (blank = never) only caps how long an unused
token keeps working, and `RATE_LIMIT_PER_MINUTE` (default 60) is
enforced per-user by an in-memory middleware that returns 429 with a
`Retry-After` header (`<= 0` disables it entirely). Details live in
`llm-service/app/store.py`, `rate_limiter.py`, and `main.py` — see
`llm-service/README.md`.

The flywheel miners need to see *every* user's events, which a normal
user token structurally can't. Admin is a per-user `is_admin` flag;
grant/revoke it on an existing user (sign up first — this CLI does not
create accounts):

```bash
python llm-service/app/make_admin.py --db-path ./llm-service/data/cad_sessions.db \
    --email you@example.com --apply        # grant (omit --apply for a dry run)
python llm-service/app/make_admin.py --db-path ./llm-service/data/cad_sessions.db \
    --email you@example.com --revoke --apply   # revoke
```

Admins get three unscoped routes, `/v1/admin/logs{,/outcomes,/summary}`
(403 for non-admins), which the `mine_flywheel_*` scripts hit with
`--auth-token` (or `LLM_SERVICE_ADMIN_TOKEN`). **Admin does NOT bypass
project/version ownership** — fetching another user's project version
still 404s, and the miners degrade that to "counted as unresolved", not
a crash (see `flywheel_common.py`'s docstring).

Pre-auth legacy rows (`projects.owner_id IS NULL`, `request_log.user_id
IS NULL`) are a deliberate stopgap — still visible to any authenticated
user — until you run the backfill:

```bash
python migrate_legacy_owner.py --db-path ./llm-service/data/cad_sessions.db \
    --owner-email legacy@yourcompany.example          # dry-run report first
python migrate_legacy_owner.py --db-path ./llm-service/data/cad_sessions.db \
    --owner-email legacy@yourcompany.example --apply  # actually write
```

It assigns all pre-auth rows to one designated "legacy" user (created on
demand with a random password), is idempotent (only NULL columns are
ever written), and deliberately never touches stateless `/v1/generate`
log rows that have no project to anchor an owner to.

`verify_auth_e2e.py` (repo root) is the end-to-end check of the whole
auth surface against a live stack — signup/login, cross-user 404s,
project-list and request-log scoping — exit 0/1, usable as a deploy/CI
gate:

```bash
docker compose up --build   # then, in another shell:
python verify_auth_e2e.py --llm-service-url http://localhost:8001
python verify_auth_e2e.py --llm-service-url http://localhost:8001 --expect-migrated
```

## Running the application

The dataset/training pipeline above (and `training/`) is offline batch
work. Once you have a trained model (`training/merge_adapter.py` output,
converted to GGUF -- see `llm-service/README.md`), the root
`docker-compose.yml` runs the actual running application -- geometry
service, llama.cpp, `llm-service` orchestrator, and the frontend -- as
one stack:

```bash
cp .env.example .env
docker compose up --build
```

Then open `http://localhost:3000` (or `$FRONTEND_PORT`). Each service's
own README (`service/`, `llm-service/`, `frontend/`) covers its endpoints
and internals in more depth; this just wires them together. Deliberately
NOT included here: `training/` and `llm-service`'s `convert` profile --
those are one-off/offline steps (train, merge, quantize to GGUF), not
part of the running app; you need their output (a GGUF file in
`llm-service/models/`) before `docker compose up` here can start
`llamacpp`.

## Quick start

```bash
# 1. plumbing-only dry run (no build123d needed) -- sanity check the scripts
python3 build_dataset.py --skip-verification --n-single-per-type 20 --n-chains 50 --out-dir out_dry

# 2. real run, once build123d is installed
python3 build_dataset.py \
    --n-single-per-type 300 --n-chains 3000 \
    --n-repair 1500 --n-regenerate 1500 \
    --out-dir out

# outputs:
#   out/train.jsonl, out/val.jsonl          <- Gemma chat-completion format
#   out/train.full.jsonl, out/val.full.jsonl <- same records with full IR/metadata
#   out/*.quarantine.jsonl