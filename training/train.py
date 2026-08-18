"""
train.py
QLoRA supervised fine-tuning of Gemma 4 on the cad_dataset chat-completion
jsonl files (train.jsonl / val.jsonl, each record:
{"prompt": [{"role": "user", ...}], "completion": [{"role": "assistant", ...}]}).

API NOTE (read this if you hit an ImportError): earlier versions of this
script used `trl.DataCollatorForCompletionOnlyLM`, which trl has REMOVED
(not renamed -- the class is gone). The replacement isn't a drop-in
collator swap, it's a dataset-shape change: trl now wants separate
"prompt"/"completion" columns (each a list of chat messages) instead of one
merged "messages" list + a response-template string to search for inside
the rendered text. `build_dataset.py` already writes this shape. With that
shape, `SFTConfig(completion_only_loss=True)` (the default when the
dataset has prompt/completion columns) handles the masking internally --
no custom collator, no response_template/instruction_template strings to
keep in sync with your tokenizer's exact turn markers, no dataset_text_field.
This is meaningfully more robust than the old approach: the old collator
worked by *finding a literal substring* in rendered text, which silently
breaks if the chat template ever renders turn markers slightly differently
than you assumed. See training/README.md for the trl version this was
written against and what to check if trl's API has moved again since.

Key choices:
  * packing=False, always. Each example is one complete JSON IR document;
    packing (concatenating multiple examples into one training sequence)
    would happily slice a JSON object in half across a packed boundary.
  * prompt/completion + completion_only_loss=True: only the model's JSON
    output is trained on, not the user instruction tokens.
  * GeometryEvalCallback (see eval_geometry.py) periodically generates
    completions for a sample of the val set and reports valid_json_rate /
    schema_valid_rate / build_valid_rate -- the metric that actually
    matters for this task, not just eval loss.

NOTE: not executed in the sandbox this was authored in (no network access
there, no GPU). Run the small smoke-test config first (see README.md)
before committing to a full run.
"""

from __future__ import annotations
import argparse
import gc
import json
import os
import random
import sys

import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainerCallback,
)
from peft import LoraConfig, prepare_model_for_kbit_training, get_peft_model
from trl import SFTConfig, SFTTrainer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_geometry import evaluate_completions


def env(key, default=None, cast=str):
    val = os.environ.get(key)
    return cast(val) if val is not None else default


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model-id", default=env("MODEL_ID", "google/gemma-4-E4B-it"))
    p.add_argument("--train-file", default=env("TRAIN_FILE", "/workspace/data/train.jsonl"))
    p.add_argument("--val-file", default=env("VAL_FILE", "/workspace/data/val.jsonl"))
    p.add_argument("--output-dir", default=env("OUTPUT_DIR", "/workspace/outputs/adapter"))

    p.add_argument("--use-qlora", action="store_true", default=env("USE_QLORA", "1") == "1")
    p.add_argument("--lora-r", type=int, default=env("LORA_R", 16, int))
    p.add_argument("--lora-alpha", type=int, default=env("LORA_ALPHA", 32, int))
    p.add_argument("--lora-dropout", type=float, default=env("LORA_DROPOUT", 0.05, float))

    p.add_argument("--max-seq-length", type=int, default=env("MAX_SEQ_LEN", 2048, int))
    p.add_argument("--per-device-batch-size", type=int, default=env("BATCH_SIZE", 2, int))
    p.add_argument("--grad-accum", type=int, default=env("GRAD_ACCUM", 8, int))
    p.add_argument("--learning-rate", type=float, default=env("LEARNING_RATE", 2e-4, float))
    p.add_argument("--num-epochs", type=float, default=env("NUM_EPOCHS", 3, float))
    p.add_argument("--warmup-ratio", type=float, default=env("WARMUP_RATIO", 0.03, float))
    p.add_argument("--logging-steps", type=int, default=env("LOGGING_STEPS", 10, int))
    p.add_argument("--eval-steps", type=int, default=env("EVAL_STEPS", 100, int))
    p.add_argument("--save-steps", type=int, default=env("SAVE_STEPS", 100, int))

    p.add_argument("--geometry-eval-samples", type=int, default=env("GEOMETRY_EVAL_SAMPLES", 20, int))
    p.add_argument("--skip-geometry-eval", action="store_true", default=env("SKIP_GEOMETRY_EVAL", "0") == "1")
    p.add_argument("--empty-cache-every-n-steps", type=int,
                    default=env("EMPTY_CACHE_EVERY_N_STEPS", 0, int),
                    help="periodic VRAM+RAM unload during training, independent of the "
                         "always-on cleanup around GeometryEvalCallback's generate() calls. "
                         "0 (default) disables this -- only turn it on if you're actually "
                         "seeing fragmentation-driven OOMs mid-run, since the sync point "
                         "has real overhead.")

    p.add_argument("--report-to", default=env("REPORT_TO", "none"))
    p.add_argument("--seed", type=int, default=env("SEED", 42, int))
    p.add_argument("--resume-from-checkpoint", default=env("RESUME_FROM_CHECKPOINT", None),
                    help="'auto' to resume from the latest checkpoint in --output-dir, "
                         "a specific checkpoint path, or omit for a fresh run. A crash "
                         "partway through (e.g. an eval-time bug) doesn't lose the run -- "
                         "save_steps checkpoints already exist in --output-dir, this just "
                         "lets you point back at them instead of restarting from step 0.")
    return p.parse_args()


def _check_dataset_shape(dataset, path: str):
    """Fail fast and clearly if the jsonl is in the old {"messages": [...]}
    format from before build_dataset.py switched to {"prompt": [...],
    "completion": [...]} (required by current trl's completion_only_loss
    -- see module docstring). A bare KeyError several calls deep in
    template rendering doesn't tell you *why*; this does."""
    cols = dataset.column_names
    if "prompt" in cols and "completion" in cols:
        return
    if "messages" in cols:
        raise RuntimeError(
            f"{path} is in the OLD dataset format (has a 'messages' column). "
            "This version of train.py needs the current build_dataset.py output "
            "shape: {'prompt': [...], 'completion': [...]}. "
            "Re-run build_dataset.py to regenerate train.jsonl/val.jsonl -- "
            "the old jsonl won't work with this trainer. See the trl API "
            "note at the top of this file for why the format changed."
        )
    raise RuntimeError(
        f"{path} has columns {cols}, expected 'prompt' and 'completion'. "
        "Re-run build_dataset.py to produce a compatible train.jsonl/val.jsonl."
    )


def _print_template_sample(dataset, tokenizer):
    """Sanity check before spending GPU time: render one example's full
    prompt+completion through the tokenizer's chat template and eyeball
    it. If this doesn't look like a real Gemma conversation (turn markers
    present, roles rendered sensibly), stop and investigate before
    committing to a full run."""
    sample = dataset[0]
    full_messages = sample["prompt"] + sample["completion"]
    rendered = tokenizer.apply_chat_template(full_messages, tokenize=False, add_generation_prompt=False)
    print("=" * 70)
    print("CHAT TEMPLATE SAMPLE -- verify this looks right before trusting a full run:")
    print(rendered[:1500])
    print("=" * 70)


def _free_memory(tag: str = "", verbose: bool = True):
    """Explicit VRAM + RAM unload. Both matter here, separately, because
    they free different things:

    - VRAM unload (torch.cuda.empty_cache): PyTorch's CUDA caching
      allocator holds onto freed GPU blocks for reuse rather than handing
      them back to the driver immediately -- normally a good thing (avoids
      allocator overhead), but this training loop interleaves two very
      different GPU workloads on the same model: backprop (activations,
      gradients, optimizer states) and GeometryEvalCallback's
      model.generate() calls (KV cache, growing per token, freed all at
      once at the end). That handoff is exactly the pattern that causes
      allocator fragmentation -- the cache can hold enough *total* free
      memory while having no single contiguous block big enough for the
      next allocation, producing an OOM that "shouldn't" happen given the
      reported free memory. empty_cache() forces a full defragmentation
      pass at the boundary between these two workloads.
    - RAM unload (gc.collect): Python's reference-counting GC usually
      frees things immediately, but PyTorch tensors/autograd graph nodes
      participate in reference cycles (a tensor's grad_fn can reference
      tensors that reference it back) that only get collected by the
      cyclic collector, not by refcounting alone. Without an explicit
      gc.collect(), CPU-side history from generate()'s intermediate
      tensors can linger longer than you'd expect from the code's
      apparent scope, and -- because some of those objects hold CUDA
      tensor references -- that also indirectly delays VRAM being freed
      in the first place. Run gc.collect() BEFORE empty_cache() for
      exactly this reason: give Python's collector a chance to drop CUDA
      references first, so empty_cache() has more to actually reclaim.
    """
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        if verbose:
            allocated = torch.cuda.memory_allocated() / 1e9
            reserved = torch.cuda.memory_reserved() / 1e9
            label = f" [{tag}]" if tag else ""
            print(f"[mem]{label} VRAM allocated={allocated:.2f}GB reserved={reserved:.2f}GB")


class MemoryCleanupCallback(TrainerCallback):
    """Periodic VRAM+RAM unload during training itself, independent of
    GeometryEvalCallback's per-eval cleanup below. Off by default
    (every_n_steps=0) since the cleanup calls have real overhead
    (torch.cuda.synchronize() is a hard sync point) -- only worth paying
    for on memory-constrained setups actually seeing fragmentation-driven
    OOMs partway through a run rather than right at the first eval."""

    def __init__(self, every_n_steps: int):
        self.every_n_steps = every_n_steps

    def on_step_end(self, args, state, control, **kwargs):
        if self.every_n_steps > 0 and state.global_step % self.every_n_steps == 0:
            _free_memory(tag=f"step {state.global_step}")


class GeometryEvalCallback(TrainerCallback):
    """After each Trainer eval, generate completions for a handful of val
    prompts and report JSON/schema/build validity rates -- the metric that
    actually reflects whether the model learned the task, not just loss."""

    def __init__(self, tokenizer, model, val_dataset_raw, n_samples: int, skip: bool):
        self.tokenizer = tokenizer
        self.model = model
        self.skip = skip
        rng = random.Random(0)
        idxs = rng.sample(range(len(val_dataset_raw)), min(n_samples, len(val_dataset_raw)))
        self.prompts = [val_dataset_raw[i]["prompt"] for i in idxs]

    def on_evaluate(self, args, state, control, **kwargs):
        if self.skip or not self.prompts:
            return
        was_training = self.model.training
        self.model.eval()

        # unload before generation starts: defragment VRAM ahead of a
        # workload (KV cache growth) with a very different allocation
        # pattern from the backprop steps that just ran -- see
        # _free_memory()'s docstring for why this matters here specifically
        _free_memory(tag=f"eval step={state.global_step} pre-generate", verbose=False)

        completions = []
        device = self.model.device
        with torch.no_grad():
            for msgs in self.prompts:
                # return_dict=True is required here, not optional: some
                # transformers versions return a bare tensor from
                # apply_chat_template(tokenize=True, return_tensors="pt"),
                # others return a BatchEncoding -- passing the wrong one
                # positionally to generate() fails deep inside generate()'s
                # internals with a confusing AttributeError (BatchEncoding
                # has no .shape). return_dict=True + **inputs is the
                # version-independent pattern regardless of which one your
                # installed transformers defaults to.
                inputs = self.tokenizer.apply_chat_template(
                    msgs, tokenize=True, add_generation_prompt=True,
                    return_tensors="pt", return_dict=True,
                ).to(device)
                out = self.model.generate(
                    **inputs, max_new_tokens=800, do_sample=False,
                    pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
                )
                prompt_len = inputs["input_ids"].shape[1]
                new_tokens = out[0][prompt_len:]
                completions.append(self.tokenizer.decode(new_tokens, skip_special_tokens=True))
                del inputs, out, new_tokens  # drop references promptly rather than
                                               # waiting for the next loop iteration
                                               # to overwrite them
        if was_training:
            self.model.train()

        # unload after generation ends: release the KV cache / decode
        # buffers before training resumes, so the next backward pass gets
        # a clean, defragmented allocator state rather than competing with
        # whatever generate() left behind
        _free_memory(tag=f"eval step={state.global_step} post-generate")

        metrics = evaluate_completions(completions, check_geometry=True)
        print(f"[geometry-eval] step={state.global_step} {metrics}")
        if hasattr(kwargs.get("metrics", {}), "update"):
            kwargs["metrics"].update({f"geom/{k}": v for k, v in metrics.items() if v is not None})


def _reconcile_save_eval_steps(save_steps: int, eval_steps: int) -> int:
    """transformers requires save_steps to be a round multiple of
    eval_steps when load_best_model_at_end=True (a checkpoint has to
    exist at the step being evaluated, or it can't identify "best"). This
    is a mechanical constraint, not a modeling choice, and it's easy to
    violate by tuning EVAL_STEPS/SAVE_STEPS independently (e.g. following
    the smoke-test section of README.md, which suggests lowering both --
    if you only change one, you'll hit this). Auto-adjust save_steps up
    to the nearest valid multiple with a clear printed warning, rather
    than hard-crashing several frames deep in transformers' own validation."""
    if eval_steps <= 0 or save_steps <= 0:
        return save_steps  # let transformers raise its own error on this
    if save_steps % eval_steps == 0:
        return save_steps
    adjusted = ((save_steps // eval_steps) + 1) * eval_steps
    print(
        f"[train.py] save_steps={save_steps} is not a round multiple of "
        f"eval_steps={eval_steps} (required by load_best_model_at_end=True) "
        f"-- adjusting save_steps to {adjusted}. Set --save-steps/--eval-steps "
        f"to matching or cleanly-divisible values to control this directly."
    )
    return adjusted


def main():
    args = parse_args()
    torch.manual_seed(args.seed)
    random.seed(args.seed)

    print(f"loading tokenizer/model: {args.model_id}")
    tokenizer = AutoTokenizer.from_pretrained(args.model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quant_config = None
    if args.use_qlora:
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

    model = AutoModelForCausalLM.from_pretrained(
        args.model_id,
        quantization_config=quant_config,
        device_map="auto",
        dtype=torch.bfloat16,
    )
    if args.use_qlora:
        model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules="all-linear",  # verify your peft version supports this shorthand;
                                        # otherwise list explicit module names (q_proj, k_proj, ...)
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    print(f"loading dataset: train={args.train_file} val={args.val_file}")
    raw = load_dataset("json", data_files={"train": args.train_file, "validation": args.val_file})
    _check_dataset_shape(raw["train"], args.train_file)
    # no formatting/remapping step needed here -- the jsonl already has
    # {"prompt": [...], "completion": [...]} with role "assistant" (not
    # "model"), which is exactly what SFTTrainer's conversational
    # prompt-completion format expects. It applies the tokenizer's chat
    # template internally.

    _print_template_sample(raw["train"], tokenizer)

    reconciled_save_steps = _reconcile_save_eval_steps(args.save_steps, args.eval_steps)

    sft_config = SFTConfig(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.per_device_batch_size,
        per_device_eval_batch_size=args.per_device_batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.learning_rate,
        num_train_epochs=args.num_epochs,
        warmup_ratio=args.warmup_ratio,
        logging_steps=args.logging_steps,
        eval_strategy="steps",
        eval_steps=args.eval_steps,
        save_strategy="steps",
        save_steps=reconciled_save_steps,
        save_total_limit=3,
        load_best_model_at_end=True,
        bf16=True,
        gradient_checkpointing=True,
        max_length=args.max_seq_length,
        packing=False,  # DO NOT enable -- see module docstring
        completion_only_loss=True,  # trains only on the "completion" turn; see module docstring
                                     # for why this replaced DataCollatorForCompletionOnlyLM
        report_to=args.report_to,
        seed=args.seed,
    )

    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=raw["train"],
        eval_dataset=raw["validation"],
        processing_class=tokenizer,
    )

    geom_cb = GeometryEvalCallback(
        tokenizer=tokenizer, model=model, val_dataset_raw=raw["validation"],
        n_samples=args.geometry_eval_samples, skip=args.skip_geometry_eval,
    )
    trainer.add_callback(geom_cb)
    if args.empty_cache_every_n_steps > 0:
        trainer.add_callback(MemoryCleanupCallback(args.empty_cache_every_n_steps))

    resume = args.resume_from_checkpoint or None  # "" from an unset .env var != no resume
    if resume == "auto":
        resume = True  # transformers auto-detects the latest checkpoint in output_dir
    trainer.train(resume_from_checkpoint=resume)

    # unload once more before saving: training's optimizer states (2x
    # model size for AdamW) are the single largest VRAM consumer and
    # aren't needed for save_model()/save_pretrained() below, which is
    # also the point in the run most likely to be memory-constrained if
    # you immediately chain into merge_adapter.py in the same container
    _free_memory(tag="post-training, pre-save")

    print(f"saving adapter + tokenizer to {args.output_dir}")
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    with open(os.path.join(args.output_dir, "train_args.json"), "w") as f:
        json.dump(vars(args), f, indent=2)


if __name__ == "__main__":
    main()
