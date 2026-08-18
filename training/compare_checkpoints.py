"""
compare_checkpoints.py
Phase 4 step 12: before/after eval comparison. Generates completions from
TWO checkpoints (old adapter vs. new) against the same eval prompt set,
scores each via eval_geometry.evaluate_completions() -- the same
valid_json_rate/schema_valid_rate/build_valid_rate metrics
GeometryEvalCallback reports during training -- and reports a side-by-side
diff. Exits nonzero if the new adapter regresses build_valid_rate beyond
--tolerance, so this is usable as a promotion gate, not just a report.

STATUS -- read before trusting this as the full step 12: the "matches
intent" dimension step 12 was meant to also cover (Phase 3 stage 1's
hand-authored eval set, human-rated) does NOT exist yet -- that set was
never built (see ../README.md's Phase 3 status). This script only
compares the geometry-validity metrics that already exist.
--eval-prompts defaults to val.jsonl as a stand-in, which is NOT the same
signal as stage 1 would be (synthetic/flywheel val prompts sampled for
training-distribution coverage, not deliberately varied across a
difficulty spectrum for eval purposes). Point --eval-prompts at the real
stage-1 file once it's built; no code change needed here.

NOTE: not executed in the sandbox this was authored in -- no torch/GPU
there. Written against train.py's already-fixed generate() pattern
(return_dict=True, see train.py's docstring for why that fix mattered)
and reuses _free_memory()/evaluate_completions() directly rather than
reimplementing them, so it can't drift from what training itself does.

Usage:
    python compare_checkpoints.py \
        --base-model google/gemma-4-E4B-it \
        --old-adapter /workspace/outputs/adapter_v1 \
        --new-adapter /workspace/outputs/adapter_v2 \
        --eval-prompts /workspace/data/val.jsonl \
        --n-samples 50
"""

from __future__ import annotations
import argparse
import json
import os
import random
import sys

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train import _free_memory  # reused, not reimplemented -- see its docstring
from eval_geometry import evaluate_completions


def load_eval_prompts(path: str, n_samples: int, seed: int) -> list[list[dict]]:
    with open(path) as f:
        records = [json.loads(line) for line in f if line.strip()]
    prompts = [r["prompt"] for r in records if "prompt" in r]
    if n_samples and n_samples < len(prompts):
        prompts = random.Random(seed).sample(prompts, n_samples)
    return prompts


def evaluate_checkpoint(base_model_id: str, adapter_dir: str, prompts: list[list[dict]],
                         use_qlora: bool, max_new_tokens: int) -> dict:
    tokenizer = AutoTokenizer.from_pretrained(base_model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quant_config = None
    if use_qlora:
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
        )
    base = AutoModelForCausalLM.from_pretrained(
        base_model_id, quantization_config=quant_config, device_map="auto", dtype=torch.bfloat16,
    )
    model = PeftModel.from_pretrained(base, adapter_dir)
    model.eval()

    completions = []
    device = model.device
    with torch.no_grad():
        for msgs in prompts:
            # return_dict=True + **inputs: the same fix train.py's
            # GeometryEvalCallback needed -- apply_chat_template can
            # return a bare tensor or a BatchEncoding depending on
            # transformers version, and generate() only handles the
            # latter correctly when unpacked this way.
            inputs = tokenizer.apply_chat_template(
                msgs, tokenize=True, add_generation_prompt=True,
                return_tensors="pt", return_dict=True,
            ).to(device)
            out = model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=False,
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            )
            prompt_len = inputs["input_ids"].shape[1]
            completions.append(tokenizer.decode(out[0][prompt_len:], skip_special_tokens=True))
            del inputs, out

    metrics = evaluate_completions(completions, check_geometry=True)

    del model, base, tokenizer
    _free_memory(tag=f"after evaluating {adapter_dir}")
    return metrics


def print_comparison(old: dict, new: dict):
    print(f"{'metric':<20}{'old':>10}{'new':>10}{'delta':>10}")
    for key in ("valid_json_rate", "schema_valid_rate", "build_valid_rate"):
        o, n = old.get(key), new.get(key)
        if o is None or n is None:
            print(f"{key:<20}{'n/a':>10}{'n/a':>10}")
            continue
        delta = n - o
        sign = "+" if delta >= 0 else ""
        print(f"{key:<20}{o:>10.3f}{n:>10.3f}{sign}{delta:>9.3f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-model", required=True)
    ap.add_argument("--old-adapter", required=True)
    ap.add_argument("--new-adapter", required=True)
    ap.add_argument("--eval-prompts", default="/workspace/data/val.jsonl")
    ap.add_argument("--n-samples", type=int, default=50)
    ap.add_argument("--max-new-tokens", type=int, default=800)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--use-qlora", action="store_true", default=True)
    ap.add_argument("--tolerance", type=float, default=0.0,
                     help="allowed build_valid_rate regression before failing (e.g. 0.02 = 2 points)")
    args = ap.parse_args()

    prompts = load_eval_prompts(args.eval_prompts, args.n_samples, args.seed)
    print(f"{len(prompts)} eval prompts loaded from {args.eval_prompts}")

    print(f"\nevaluating OLD: {args.old_adapter}")
    old_metrics = evaluate_checkpoint(args.base_model, args.old_adapter, prompts,
                                       args.use_qlora, args.max_new_tokens)

    print(f"\nevaluating NEW: {args.new_adapter}")
    new_metrics = evaluate_checkpoint(args.base_model, args.new_adapter, prompts,
                                       args.use_qlora, args.max_new_tokens)

    print()
    print_comparison(old_metrics, new_metrics)

    old_bvr = old_metrics.get("build_valid_rate") or 0.0
    new_bvr = new_metrics.get("build_valid_rate") or 0.0
    if new_bvr < old_bvr - args.tolerance:
        print(f"\nREGRESSION: build_valid_rate dropped {old_bvr:.3f} -> {new_bvr:.3f} "
              f"(beyond tolerance {args.tolerance}) -- do not promote without review")
        sys.exit(1)

    print(f"\nOK to promote: build_valid_rate {old_bvr:.3f} -> {new_bvr:.3f}")
    sys.exit(0)


if __name__ == "__main__":
    main()
