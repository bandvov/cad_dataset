"""
build_dataset.py
End-to-end pipeline:
  1. run gen_single_feature.py, gen_chains.py in-process to get candidate
     "generate" records
  2. verify every candidate through executor.py (real build123d execution);
     keep verified ones, quarantine the rest
  3. run gen_regenerate.py off the verified chain records (recipe replay)
     and gen_repair.py off the verified pool (fault injection), each of
     which does its own internal verification
  4. dedupe by IR structure hash, split train/val by a hashed id (not
     random) so re-runs are reproducible, convert to Gemma chat-completion
     format, write final jsonl files

Requires a real build123d install to do anything beyond step 1's raw
generation -- see README.md "Verification" section. Run with
--skip-verification to only exercise the generation + formatting plumbing
(useful for testing this script itself without build123d installed).
"""

from __future__ import annotations
import argparse
import hashlib
import json
import os
import random
import sys
import time

import gen_single_feature
import gen_chains
import gen_regenerate
import gen_repair
from executor import BatchExecutor


def verify_records(records: list[dict], be: BatchExecutor | None, skip: bool,
                    label: str = "") -> tuple[list[dict], list[dict]]:
    verified, quarantined = [], []
    n = len(records)
    start = time.time()
    for i, rec in enumerate(records):
        if skip:
            rec["verified"] = None  # unknown -- verification was skipped
            verified.append(rec)
            continue
        result = be.execute(rec["json_ir"])
        if result.get("success"):
            rec["verified"] = True
            rec["geometry_stats"] = result["stats"]
            verified.append(rec)
        else:
            rec["verified"] = False
            rec["verification_error"] = {"error_type": result.get("error_type"),
                                          "error": result.get("error")}
            quarantined.append(rec)
        if not skip and ((i + 1) % 20 == 0 or i + 1 == n):
            elapsed = time.time() - start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"   [{label}] {i + 1}/{n}  ({rate:.1f} rec/s, {elapsed:.0f}s elapsed)",
                  flush=True)
    return verified, quarantined


def structure_hash(ir: dict) -> str:
    """Hash of feature_type sequence + operation choices, used for dedup
    and for family-based (not random) train/val split, so val measures
    generalization to unseen shape topologies rather than memorized
    dimension variants of the same tree."""
    sig = [(f["feature_type"], f.get("operation")) for f in ir["features"]]
    return hashlib.sha1(json.dumps(sig).encode()).hexdigest()


def to_chat_format(rec: dict) -> dict:
    """Renders one dataset record as a TRL "conversational prompt-completion"
    example: {"prompt": [...], "completion": [...]}, each a list of chat
    messages. This is the format current trl's completion_only_loss=True
    expects (trl removed DataCollatorForCompletionOnlyLM; the replacement
    needs prompt/completion as separate columns, not a single merged
    messages list with a response-template string to search for -- see
    training/README.md). Repair/regenerate tasks fold their extra context
    into the prompt turn."""
    task = rec["task_type"]
    if task == "generate":
        user = rec["instruction"]
        model_out = json.dumps(rec["json_ir"])
    elif task == "repair":
        user = (
            f"{rec['instruction']}\n\n"
            f"Broken feature tree:\n{json.dumps(rec['broken_ir'])}\n\n"
            f"Error: {rec['error']}"
        )
        model_out = json.dumps(rec["json_ir"])
    elif task == "regenerate":
        user = (
            f"Here is the current part:\n{json.dumps(rec['base_ir'])}\n\n"
            f"{rec['instruction']}"
        )
        model_out = json.dumps(rec["json_ir"])
    else:
        raise ValueError(f"unknown task_type {task}")

    return {
        "record_id": rec["record_id"],
        "task_type": task,
        "prompt": [{"role": "user", "content": user}],
        "completion": [{"role": "assistant", "content": model_out}],
    }


def write_jsonl(path: str, records: list[dict]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-single-per-type", type=int, default=150)
    ap.add_argument("--n-chains", type=int, default=800)
    ap.add_argument("--n-repair", type=int, default=500)
    ap.add_argument("--n-regenerate", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--skip-verification", action="store_true",
                     help="don't execute build123d -- plumbing-only test run")
    ap.add_argument("--include-flywheel-data", nargs="+", default=[],
                     help="Phase 4 step 8: path(s) to verified flywheel records "
                          "(mine_flywheel_verify.py / mine_flywheel_dedup.py output) "
                          "to merge into the same dedup+split+chat-format pipeline as "
                          "synthetic data. Records without verified=true are dropped "
                          "with a warning, never trusted just because the file claims it.")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    print("== generating single-feature records ==", flush=True)
    single = gen_single_feature.generate(args.n_single_per_type, seed=args.seed)
    print(f"   {len(single)} candidates generated", flush=True)
    print("== generating chain records ==", flush=True)
    chains = gen_chains.generate(args.n_chains, seed=args.seed)
    print(f"   {len(chains)} candidates generated", flush=True)

    be = None if args.skip_verification else BatchExecutor(timeout_per_item=args.timeout)
    try:
        print("== verifying single-feature records "
              "(first batch pays a one-time build123d import cost, ~seconds) ==", flush=True)
        single_ok, single_bad = verify_records(single, be, args.skip_verification, label="single")
        print(f"   {len(single_ok)} verified, {len(single_bad)} quarantined", flush=True)
        print("== verifying chain records ==", flush=True)
        chains_ok, chains_bad = verify_records(chains, be, args.skip_verification, label="chains")
        print(f"   {len(chains_ok)} verified, {len(chains_bad)} quarantined", flush=True)

        write_jsonl(f"{args.out_dir}/single_feature.verified.jsonl", single_ok)
        write_jsonl(f"{args.out_dir}/single_feature.quarantine.jsonl", single_bad)
        write_jsonl(f"{args.out_dir}/chains.verified.jsonl", chains_ok)
        write_jsonl(f"{args.out_dir}/chains.quarantine.jsonl", chains_bad)

        generate_pool = single_ok + chains_ok

        repair_records, regen_records = [], []
        if not args.skip_verification:
            print("== generating + verifying repair records ==", flush=True)
            rng = random.Random(args.seed)
            execute_fn = lambda ir, timeout=None: be.execute(ir)  # noqa: E731
            pool_copy = list(generate_pool)
            rng.shuffle(pool_copy)
            for i, rec in enumerate(pool_copy):
                if len(repair_records) >= args.n_repair:
                    break
                r = gen_repair.make_repair_record(rec, rng, args.timeout, execute_fn=execute_fn)
                if r:
                    repair_records.append(r)
                if (i + 1) % 20 == 0:
                    print(f"   [repair] {i + 1} candidates checked, "
                          f"{len(repair_records)}/{args.n_repair} kept", flush=True)
            print(f"   {len(repair_records)} repair records", flush=True)

            print("== generating regenerate records ==", flush=True)
            rng2 = random.Random(args.seed + 1)
            for rec in chains_ok:
                if len(regen_records) >= args.n_regenerate:
                    break
                r = gen_regenerate.make_regenerate_record(rec, rng2)
                if r:
                    regen_records.append(r)
            # regenerate outputs also need verification -- the edited IR could
            # push a formula-derived value out of bounds (e.g. shell thickness
            # after a big resize)
            regen_ok, regen_bad = verify_records(regen_records, be, False, label="regenerate")
            print(f"   {len(regen_ok)} verified, {len(regen_bad)} quarantined", flush=True)
            write_jsonl(f"{args.out_dir}/regenerate.quarantine.jsonl", regen_bad)
            regen_records = regen_ok
        else:
            print("== skipping repair/regenerate verification (--skip-verification) ==", flush=True)
    finally:
        if be is not None:
            be.__exit__(None, None, None)

    write_jsonl(f"{args.out_dir}/repair.jsonl", repair_records)
    write_jsonl(f"{args.out_dir}/regenerate.jsonl", regen_records)

    # ---- Phase 4 step 8: fold in verified flywheel records ----
    flywheel_records = []
    for path in args.include_flywheel_data:
        with open(path) as f:
            rows = [json.loads(line) for line in f if line.strip()]
        ok = [r for r in rows if r.get("verified") is True]
        if len(ok) < len(rows):
            print(f"   [flywheel] {path}: dropped {len(rows) - len(ok)} record(s) "
                  f"without verified=true", flush=True)
        flywheel_records.extend(ok)
    if flywheel_records:
        print(f"== including {len(flywheel_records)} verified flywheel records ==", flush=True)

    # ---- dedupe + family-based split + chat format ----
    all_records = generate_pool + repair_records + regen_records + flywheel_records
    seen_hashes = set()
    deduped = []
    for r in all_records:
        ir_for_hash = r["json_ir"]
        h = structure_hash(ir_for_hash)
        key = (r["task_type"], h)
        if key in seen_hashes:
            continue
        seen_hashes.add(key)
        deduped.append(r)
    print(f"== {len(all_records)} total, {len(deduped)} after structural dedupe ==")

    def split_bucket(record_id: str) -> str:
        h = int(hashlib.sha1(record_id.encode()).hexdigest(), 16)
        return "val" if (h % 1000) / 1000 < args.val_frac else "train"

    train, val = [], []
    for r in deduped:
        (val if split_bucket(r["record_id"]) == "val" else train).append(r)

    train_chat = [to_chat_format(r) for r in train]
    val_chat = [to_chat_format(r) for r in val]

    write_jsonl(f"{args.out_dir}/train.jsonl", train_chat)
    write_jsonl(f"{args.out_dir}/val.jsonl", val_chat)
    # also keep the full-metadata (non-chat) versions for debugging/inspection
    write_jsonl(f"{args.out_dir}/train.full.jsonl", train)
    write_jsonl(f"{args.out_dir}/val.full.jsonl", val)

    print(f"== wrote {len(train_chat)} train / {len(val_chat)} val chat records to {args.out_dir}/ ==")


if __name__ == "__main__":
    main()
