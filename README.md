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
schema.py            canonical IR field definitions + structural validate_ir()
compiler.py           direct interpreter: IR -> build123d geometry, in-process
executor.py           runs compiler.py in a timeout'd subprocess, isolated
validator.py           geometric sanity checks + stat extraction (real build123d)
primitives.py          parameter samplers, safe ranges, instruction phrasing
gen_single_feature.py  one feature type per record (full FEATURE_TYPES coverage)
gen_chains.py           2-8 feature chains built from a *replayable recipe*
gen_repair.py            execution-verified fault injection (real error text only)
gen_regenerate.py        replays a chain's recipe with one edited input
build_dataset.py         orchestrates all of the above -> verify -> dedupe -> split
mine_flywheel_data.py     Phase 4 step 1: extracts outcome-classified production
                          events (retried/edited/abandoned) from llm-service's
                          request log -- extraction only; pairing, re-verification,
                          dedup, and chat-format conversion are later, not-yet-built
                          steps in the flywheel plan (see its module docstring)
stub_build123d/          fake build123d, PLUMBING TESTS ONLY, see warning above
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

## Data flywheel (Phase 4)

Mines production usage (via `llm-service`'s request log) back into
training data. Pipeline order:

1. `mine_flywheel_data.py` -- log extraction (done)
2. `mine_flywheel_repairs.py` -- repair-pair construction (done)
3. `mine_flywheel_edits.py` -- edit-pair construction (done)
4. `mine_flywheel_verify.py` -- re-verification via real build123d (done)
5. `mine_flywheel_dedup.py` -- dedup against existing corpus (done)
6. PII/content scrub -- **not implemented**
7. `mine_flywheel_chatformat.py` -- chat-format conversion (done)
8. `build_dataset.py --include-flywheel-data` -- merge into train/val (done)
9. `mine_flywheel_gate.py` -- volume/quality gate (done)
10. **TODO**: scheduling -- cron/compose service to run steps 1-9
    periodically (e.g. weekly) against the production `cad_sessions.db`.
11. **TODO**: retraining trigger -- hook step 9's gate into
    `training/train.py`, either manual (point `TRAIN_FILE`/`VAL_FILE` at
    the gated output) or automated (compose job that runs `docker compose
    up train` when the gate passes).

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
#   out/*.quarantine.jsonl                   <- failed verification, for debugging
```
