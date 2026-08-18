# Training: Docker + docker compose

QLoRA fine-tuning of Gemma 4 on `../out/train.jsonl` / `../out/val.jsonl`
(produced by `build_dataset.py` one level up), plus a geometry-aware eval
callback that reuses this repo's own `schema.py` / `executor.py` to check
whether generated completions actually compile to valid build123d geometry
-- not just whether the loss went down.

## Verification status -- read before a long run

None of this was executed in the sandbox it was authored in: no network
access (no `docker pull`, no `pip install`, no `huggingface_hub` download),
no GPU. Everything here follows documented patterns (HF Transformers +
TRL SFTTrainer + PEFT LoRA + bitsandbytes QLoRA, Gemma's
`<start_of_turn>user` / `<start_of_turn>model` turn syntax) but has three
soft spots you should confirm before trusting a multi-hour run:

1. **The base image tag** (`pytorch/pytorch:2.6.0-cuda12.4-cudnn9-devel`)
   -- confirmed to exist on Docker Hub as of this writing, but still
   confirm it matches your host's CUDA driver version (`nvidia-smi`)
   before building.
2. **trl API drift** -- this already bit us once: `trl` removed
   `DataCollatorForCompletionOnlyLM` outright (not renamed). `train.py` now
   uses the current replacement: a `{"prompt": [...], "completion": [...]}`
   dataset shape (which `build_dataset.py` writes directly) plus
   `SFTConfig(completion_only_loss=True)`, which trl handles internally via
   the tokenizer's chat template rather than string-matching a response
   template in rendered text. This was written against `trl>=0.12` per
   `requirements.txt`, but trl's SFT API has moved fast across versions --
   if you hit an error on this, check `pip show trl` and the current
   `SFTConfig` docs for `completion_only_loss` / `assistant_only_loss`
   before assuming the logic is wrong; it's plausibly the same kind of API
   drift again; run `python -c "from trl import SFTConfig; help(SFTConfig)"`
   inside the container to check current field names first.
3. **`target_modules="all-linear"`** in the LoraConfig -- a PEFT shorthand
   that targets every linear layer; if your installed peft version doesn't
   support the string form, replace with an explicit list
   (`["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"]`
   is the usual Gemma/Llama-family set, but check the model's actual module
   names via `for n, _ in model.named_modules(): print(n)`).

Run the smoke test below first; it's designed to surface exactly these
three issues cheaply (small model, 1 GPU, a handful of steps) before you
point it at a multi-hour job.

### If you hit `RuntimeError: operator torchvision::nms does not exist`

Fixed as of this version, but worth understanding if you see anything
like it again -- it's a genuinely confusing failure mode because the
traceback points nowhere near the real cause. What actually happens:
`torch` and `torchvision` are compiled against each other's ABI, so they
must be an exact matched pair. `requirements.txt` used to leave torch as
an open floor (`torch>=2.5.0`) and never pinned torchvision at all; pip
would resolve torch to whatever satisfied that floor while the base
image's pre-baked torchvision (built against ITS torch version) stayed
put, and the resulting mismatch makes torchvision fail to load. That
failure then cascades through an unrelated-looking import chain --
`transformers`'s lazy module loader, triggered by importing
`TrainerCallback`, pulls in `peft`, which does a broad `from transformers
import BloomPreTrainedModel` just to build a lookup table, which pulls in
transformers' object-detection loss utilities, which import
`torchvision.io` -- surfacing as a bare `ModuleNotFoundError: Could not
import module 'TrainerCallback'`, nowhere near torchvision or vision
models. Fixed by pinning `torch`/`torchvision`/`torchaudio` to an exact,
mutually-compatible triple in `requirements.txt` (per
[pytorch.org's compatibility matrix](https://pytorch.org/get-started/previous-versions/))
and matching the Dockerfile's base image tag to the same torch version, so
pip isn't silently upgrading torch away from what the image shipped with.

### If save_steps/eval_steps don't line up

`load_best_model_at_end=True` requires `save_steps` to be a round multiple
of `eval_steps` (transformers needs a checkpoint to exist at whatever step
it decided was "best"). This is easy to hit by tuning `EVAL_STEPS`/
`SAVE_STEPS` independently -- `train.py` now auto-adjusts `save_steps` up
to the nearest valid multiple and prints a warning when it does, rather
than crashing several frames deep in transformers' own validation. Set
both explicitly to matching or cleanly-divisible values if you want exact
control over checkpoint cadence.

### If you hit `KeyError: 'prompt'` at startup

`train.py` used to expect `{"messages": [...]}` jsonl records; it now
expects `{"prompt": [...], "completion": [...]}` (required by current
trl's `completion_only_loss`, see the docstring at the top of `train.py`
for why). If `../out/train.jsonl` predates that change, regenerate it:

```bash
cd ..
python3 build_dataset.py --n-single-per-type 300 --n-chains 3000 \
    --n-repair 1500 --n-regenerate 1500 --out-dir out
```

`train.py` now checks the dataset shape at startup and raises a clear
error naming this exact fix if it detects the old format, rather than the
confusing `KeyError` several calls deep in template rendering.

### If eval crashes with `AttributeError` inside `BatchEncoding.__getattr__`

Fixed as of this version, but worth understanding if you see anything
like it again: `tokenizer.apply_chat_template(..., tokenize=True,
return_tensors="pt")` returns a **bare tensor** in some transformers
versions and a **`BatchEncoding`** (dict-like) in others, depending on
version and model. `GeometryEvalCallback` used to assume a bare tensor
(`inputs.shape[1]`, passed positionally to `generate()`); on a version
that returns a `BatchEncoding` instead, `generate()` fails deep in its own
internals trying `.shape` on something dict-like -- a `KeyError` caught
and re-raised as a bare `AttributeError`, several frames from the actual
cause. Fixed by explicitly requesting `return_dict=True` and unpacking
with `model.generate(**inputs, ...)` -- the version-independent pattern
regardless of what your installed transformers defaults to.

**If this crashes partway through a run** (as it did here, at 71% /
2h47m in), you don't need to restart from step 0 -- `save_steps`
checkpoints already exist in `--output-dir`. Resume into the fix:
```bash
# in .env:
RESUME_FROM_CHECKPOINT=auto
# or a specific one: /workspace/outputs/adapter/checkpoint-84
docker compose up train
```

## Setup

```bash
cd training
cp .env.example .env
# edit .env: set HF_TOKEN (needs Gemma 4 license accepted on the model
# page), pick MODEL_ID sized to your GPU:
#   E2B-it   ~8-10GB VRAM (QLoRA)   -- smallest, good for the smoke test
#   E4B-it   ~17GB VRAM
#   26B-A4B  ~22GB VRAM (QLoRA)
#   31B      40GB+
```

Make sure `../out/train.jsonl` and `../out/val.jsonl` exist (run
`build_dataset.py` first, against a **real** build123d install -- see the
top-level README's verification section).

## Smoke test (do this first)

Cheap config to confirm the whole path works: small model, tiny step
count, geometry eval on.

```bash
# in .env, temporarily set:
#   MODEL_ID=google/gemma-4-E2B-it
#   NUM_EPOCHS=1
#   EVAL_STEPS=5
#   SAVE_STEPS=5
#   GEOMETRY_EVAL_SAMPLES=5

docker compose build train
docker compose --env-file .env run --rm train \
    python train.py --num-epochs 1 --eval-steps 5 --save-steps 5
```

Watch the console for:
- the "CHAT TEMPLATE SAMPLE" printout at startup -- confirm it looks like
  a real Gemma conversation, turn markers included
- `[geometry-eval] step=... {...}` lines -- `valid_json_rate` should be
  nonzero within the first few hundred steps on real training data; if
  it's stuck at 0 for a long time on real data, something upstream (data
  format, template mismatch, masking) is wrong, not the model being slow
  to learn

## Full run

```bash
docker compose --env-file .env up train
```

Checkpoints and the final adapter land in `./outputs/adapter` (bind-mounted
to the host, survives container removal).

## VRAM + RAM unload during training

This training loop interleaves two workloads with very different memory
patterns on the same model: normal backprop steps, and
`GeometryEvalCallback` periodically calling `model.generate()` (KV cache
growth, freed all at once at the end) to compute `valid_json_rate`/
`schema_valid_rate`/`build_valid_rate`. That handoff is exactly the
pattern that causes CUDA allocator fragmentation -- an OOM with plenty of
*total* free memory reported, just no single contiguous block big enough.

Two things happen automatically, no flags needed:
- **Around every eval's `generate()` calls** (`_free_memory()` in
  `train.py`): a VRAM defragmentation pass (`torch.cuda.empty_cache()`)
  both before generation starts and after it ends, plus a `gc.collect()`
  pass before each -- run in that order deliberately, since PyTorch
  tensors participate in reference cycles the cyclic GC has to clear
  before CUDA memory tied to them is actually reclaimable.
- **Once after `trainer.train()` completes**, before saving -- the
  optimizer states (2x model size for AdamW) are the largest VRAM
  consumer and aren't needed for `save_model()`, which matters if you
  chain straight into `merge_adapter.py` in the same container.

One thing is opt-in: `EMPTY_CACHE_EVERY_N_STEPS` (default `0`, disabled)
runs the same cleanup periodically during plain training steps, not just
around eval. `torch.cuda.synchronize()` inside `_free_memory()` is a hard
sync point with real overhead, so only turn this on if you're actually
seeing fragmentation-driven OOMs mid-run (not just at/after the first
eval, which the always-on cleanup above already covers) -- try `200` as a
starting point.

`merge_adapter.py` gets the RAM half only (no VRAM -- it loads to CPU):
after `merge_and_unload()`, the base model's original weights are still
referenced even though they've been folded into the merged model, so
they're dropped and GC'd explicitly before `save_pretrained()`, which
needs its own headroom to serialize a full-precision model.

## Merge adapter -> standalone model

```bash
docker compose --env-file .env run --rm merge
```

Output in `./outputs/merged` -- a plain HF model directory, loadable with
`AutoModelForCausalLM.from_pretrained("./outputs/merged")`, no PEFT
required. From here, standard next steps (not included in this repo):
GGUF conversion for llama.cpp/Ollama, or serving directly with vLLM/TGI.

### If you hit `Couldn't instantiate the backend tokenizer... sentencepiece or tiktoken`

Fixed as of this version. This error is confusing because it names
`sentencepiece`, but `sentencepiece` is already in `requirements.txt` --
in the same image `train.py` used to load this exact model's tokenizer
successfully hours earlier in the same run. The actual issue is
transformers' slow-to-fast tokenizer *reconversion* path (triggered when
loading from a locally re-saved tokenizer rather than the canonical hub
repo) being sensitive to sentencepiece/protobuf version combinations in
ways that error message doesn't diagnose correctly. `merge_adapter.py`
now loads the tokenizer from `--base-model` (hub) instead of
`--adapter-dir` (the local save) -- the identical content, since
`train.py`'s `tokenizer.save_pretrained()` doesn't modify anything, but
sidesteps the broken reconversion path entirely rather than chasing a
sentencepiece/protobuf pin that may not even be the real variable.

## Before/after eval comparison (Phase 4 step 12)

```bash
docker compose --env-file .env run --rm compare
```

Generates completions from `OLD_ADAPTER` and `NEW_ADAPTER` against the
same eval prompts, scores both via `eval_geometry.evaluate_completions()`
(the same metrics `GeometryEvalCallback` reports during training), and
prints a side-by-side diff. Exits nonzero if `build_valid_rate` regresses
beyond `--tolerance` -- usable as a promotion gate in a pipeline, not just
a report.

**What this does NOT cover yet**: step 12 was meant to also compare
against Phase 3 stage 1's hand-authored eval set (human-rated "matches
intent" scoring). That set doesn't exist -- see the top-level
`README.md`'s Phase 3 status. `--eval-prompts` defaults to `val.jsonl`
as a stand-in, which is a different signal (synthetic/flywheel prompts
sampled for training coverage, not a deliberately varied difficulty
spectrum built for eval). This script only compares geometry-validity
metrics; it can't tell you whether the new adapter's parts are actually
*better*, only whether they're still as buildable. Point `--eval-prompts`
at the real stage-1 file once it exists -- no code change needed.

## Why completion-only loss + no packing

See the docstring at the top of `train.py` -- short version: packing
would slice a JSON document across a sequence boundary, and training loss
on the user-instruction tokens wastes signal on text the model isn't
being asked to generate. Both choices are made explicitly in `train.py`,
not left at library defaults.
