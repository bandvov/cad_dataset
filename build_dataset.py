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
from typing import Counter

import gen_single_feature
import gen_chains
import gen_regenerate
import gen_repair
from executor import BatchExecutor
import chat_format


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


def content_hash(ir: dict) -> str:
    """Exact-content hash (floats rounded to avoid FP-noise false
    negatives) -- for TRUE duplicate detection only. Two records with the
    same topology but different dimensions must NOT collide here."""
    def _round(obj):
        if isinstance(obj, float):
            return round(obj, 6)
        if isinstance(obj, dict):
            return {k: _round(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_round(v) for v in obj]
        return obj
    return hashlib.sha1(json.dumps(_round(ir), sort_keys=True).encode()).hexdigest()


# structure_hash(ir) unchanged -- now used ONLY for per-family diversity
# capping, not as the duplicate test.

def structure_hash(ir: dict) -> str:
    """Hash of feature_type sequence + operation choices, used for dedup
    and for family-based (not random) train/val split, so val measures
    generalization to unseen shape topologies rather than memorized
    dimension variants of the same tree."""
    sig = [(f["feature_type"], f.get("operation")) for f in ir["features"]]
    return hashlib.sha1(json.dumps(sig).encode()).hexdigest()


def _vec_sig(v, default=None):
    """Rounded vector signature; None coords stay None. Direction/normal
    only, never positions, so dimensional variants still share a bucket."""
    if not isinstance(v, (list, tuple)):
        return default
    return tuple(None if c is None else round(float(c), 3) for c in v)


def _selector_sig(sel) -> tuple | None:
    """Which KIND of selection this is (axis+criterion, geom type, or which
    near_point axes are constrained), never the numeric point/tolerance."""
    if not isinstance(sel, dict):
        return None
    fb = sel.get("filter_by")
    sig = [sel.get("of"), fb]
    if fb in ("X", "Y", "Z", "all", None):
        sig.append(sel.get("criterion"))
    elif fb == "GeomType":
        sig.append(sel.get("geom_type"))
    elif fb == "near_point":
        # which coords are null (unconstrained) is the behavior being taught
        sig.append(tuple(c is None for c in (sel.get("point") or [])))
    return tuple(sig)


def _feature_signature(f: dict) -> tuple:
    t = f["feature_type"]
    sig: list = [t, f.get("operation")]
    if t == "Sketch":
        plane = f.get("plane")
        normal = _vec_sig(plane.get("normal"), (0.0, 0.0, 1.0)) if isinstance(
            plane, dict) else (0.0, 0.0, 1.0)
        sig.append(normal)
        sig.append(tuple((p.get("type"), p.get("parameters", {}).get("mode", "ADD"))
                         for p in f.get("primitives", [])))
    elif t in ("Fillet", "Chamfer"):
        sig.append(_selector_sig(f.get("selector")))
    elif t == "Shell":
        sig.append(_selector_sig(f.get("open_selector")))
    elif t == "Hole":
        loc = f.get("location") or {}
        sig += [f.get("style"), _vec_sig(loc.get("normal"), (0.0, 0.0, -1.0))]
    elif t == "Mirror":
        sig.append(f.get("plane"))
    elif t == "LinearPattern":
        sig.append(_vec_sig(f.get("direction")))
    elif t == "CircularPattern":
        sig.append(_vec_sig((f.get("axis") or {}).get(
            "direction"), (0.0, 0.0, 1.0)))
    elif t == "Revolve":
        sig.append(_vec_sig((f.get("axis") or {}).get(
            "direction"), (0.0, 1.0, 0.0)))
    elif t == "Loft":
        sig += [len(f.get("sources", [])), bool(f.get("ruled", False))]
    elif t == "Sweep":
        sig.append(bool(f.get("is_frenet", False)))
    return tuple(sig)


def family_hash(ir: dict) -> str:
    """Finer-grained than structure_hash(): same feature-type sequence AND
    same *kind* of plane / selector / hole normal / mirror plane / pattern
    axis. Still ignores all numeric dimensions, so dimensional variants of
    one design share a bucket (that's what the per-bucket cap is for), but
    a Z/max fillet and an X/min fillet, or a sketch on XY vs YZ, no longer
    compete for the same 8 slots."""
    sig = [_feature_signature(f) for f in ir["features"]]
    return hashlib.sha1(json.dumps(sig, default=str).encode()).hexdigest()


def to_chat_format(rec: dict) -> dict:
    """Renders one dataset record as a TRL "conversational prompt-completion"
    example: {"prompt": [...], "completion": [...]}, each a list of chat
    messages. This is the format current trl's completion_only_loss=True
    expects (see training/README.md). Repair/regenerate tasks fold their
    extra context into the prompt turn via chat_format.py -- the SAME
    module orchestrator.py uses at serving time, so the wording here can
    never drift from what inference actually sends the model."""
    task = rec["task_type"]
    if task == "generate":
        user = chat_format.render_generate_user_turn(rec["instruction"])
    elif task == "repair":
        user = chat_format.render_repair_user_turn(
            broken_ir=rec["broken_ir"], error=rec["error"], instruction=rec["instruction"]
        )
    elif task == "regenerate":
        user = chat_format.render_regenerate_user_turn(
            rec["base_ir"], rec["instruction"])
    else:
        raise ValueError(f"unknown task_type {task}")

    model_out = json.dumps(rec["json_ir"])

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
    ap.add_argument("--max-per-bucket", type=int, default=8,
                    help="max dimensional variants kept per (task_type, topology) family")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    print("== generating single-feature records ==", flush=True)
    single = gen_single_feature.generate(
        args.n_single_per_type, seed=args.seed)
    print(f"   {len(single)} candidates generated", flush=True)
    print("== generating chain records ==", flush=True)
    chains = gen_chains.generate(args.n_chains, seed=args.seed)
    print(f"   {len(chains)} candidates generated", flush=True)

    be = None if args.skip_verification else BatchExecutor(
        timeout_per_item=args.timeout)
    try:
        print("== verifying single-feature records "
              "(first batch pays a one-time build123d import cost, ~seconds) ==", flush=True)
        single_ok, single_bad = verify_records(
            single, be, args.skip_verification, label="single")
        print(
            f"   {len(single_ok)} verified, {len(single_bad)} quarantined", flush=True)
        print("== verifying chain records ==", flush=True)
        chains_ok, chains_bad = verify_records(
            chains, be, args.skip_verification, label="chains")
        print(
            f"   {len(chains_ok)} verified, {len(chains_bad)} quarantined", flush=True)

        write_jsonl(f"{args.out_dir}/single_feature.verified.jsonl", single_ok)
        write_jsonl(
            f"{args.out_dir}/single_feature.quarantine.jsonl", single_bad)
        write_jsonl(f"{args.out_dir}/chains.verified.jsonl", chains_ok)
        write_jsonl(f"{args.out_dir}/chains.quarantine.jsonl", chains_bad)

        generate_pool = single_ok + chains_ok

        repair_records, regen_records = [], []
        if not args.skip_verification:
            print("== generating + verifying repair records ==", flush=True)
            rng = random.Random(args.seed)
            def execute_fn(ir, timeout=None): return be.execute(ir)  # noqa: E731
            pool_copy = list(generate_pool)
            rng.shuffle(pool_copy)
            for i, rec in enumerate(pool_copy):
                if len(repair_records) >= args.n_repair:
                    break
                r = gen_repair.make_repair_record(
                    rec, rng, args.timeout, execute_fn=execute_fn)
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
            regen_ok, regen_bad = verify_records(
                regen_records, be, False, label="regenerate")
            print(
                f"   {len(regen_ok)} verified, {len(regen_bad)} quarantined", flush=True)
            write_jsonl(
                f"{args.out_dir}/regenerate.quarantine.jsonl", regen_bad)
            regen_records = regen_ok
        else:
            print(
                "== skipping repair/regenerate verification (--skip-verification) ==", flush=True)
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
        print(
            f"== including {len(flywheel_records)} verified flywheel records ==", flush=True)

    # ---- dedupe + family-based split + chat format ----
    all_records = generate_pool + repair_records + regen_records + flywheel_records

    # ---- exact dedup, then per-structural-family cap, then split + chat format ----
    seen_content: set[tuple[str, str]] = set()
    bucket_counts: dict[tuple[str, str], int] = {}
    deduped = []
    n_exact_dupes = n_bucket_capped = 0

    old_b = len({(r["task_type"], structure_hash(r["json_ir"]))
                for r in all_records})
    new_b = len({(r["task_type"], family_hash(r["json_ir"]))
                for r in all_records})
    print(f"== buckets: {old_b} by feature-type sequence only -> {new_b} by family "
          f"(cap {args.max_per_bucket} each => ceiling {old_b * args.max_per_bucket} -> "
          f"{new_b * args.max_per_bucket} records) ==")
    

    for r in all_records:
        task = r["task_type"]

        c_key = (task, content_hash(r["json_ir"]))
        if c_key in seen_content:
            n_exact_dupes += 1
            continue
        seen_content.add(c_key)

        s_key = (task, family_hash(r["json_ir"]))
        count = bucket_counts.get(s_key, 0)
        if count >= args.max_per_bucket:
            n_bucket_capped += 1
            continue
        bucket_counts[s_key] = count + 1
        deduped.append(r)

    print(f"== {len(all_records)} total: {n_exact_dupes} exact duplicates, "
          f"{n_bucket_capped} over per-bucket cap ({args.max_per_bucket}), "
          f"{len(deduped)} kept ==")

    def split_bucket(record_id: str) -> str:
        h = int(hashlib.sha1(record_id.encode()).hexdigest(), 16)
        return "val" if (h % 1000) / 1000 < args.val_frac else "train"

    train, val = [], []
    for r in deduped:
        (val if split_bucket(r["record_id"]) == "val" else train).append(r)

    fam_total = Counter((r["task_type"], family_hash(r["json_ir"]))
                        for r in all_records)
    sizes = sorted(fam_total.values(), reverse=True)
    print(f"== family sizes: top 10 = {sizes[:10]}")
    print(f"   {sum(1 for s in sizes if s == 1)} families with 1 record, "
        f"{sum(1 for s in sizes if s <= 3)} with <=3, "
        f"{sum(1 for s in sizes if s > args.max_per_bucket)} saturated (>cap)")
    by_src = Counter(r["record_id"].split("_")[0] for r in all_records)
    print(f"   candidates by generator: {dict(by_src)}")
    
    print("="*80)

    beh = Counter()
    
    for r in deduped:
        for f in r["json_ir"]["features"]:
            t = f["feature_type"]
            if t == "Sketch":
                n = (f.get("plane") or {}).get("normal", [0, 0, 1])
                beh[("sketch_normal", tuple(n))] += 1
            elif t in ("Fillet", "Chamfer"):
                s = f["selector"]
                beh[(t, s.get("filter_by"), s.get("criterion") or s.get("geom_type")
                    or tuple(c is None for c in s.get("point", [])))] += 1
            elif t == "Hole":
                beh[("hole_normal", tuple(f["location"].get("normal", [])))] += 1
            elif t == "Mirror":
                beh[("mirror_plane", f.get("plane"))] += 1
                
    for k, v in sorted(beh.items(), key=lambda kv: kv[1]):
        print(f"{v:5d}  {k}")    

    train_chat = [to_chat_format(r) for r in train]
    val_chat = [to_chat_format(r) for r in val]

    write_jsonl(f"{args.out_dir}/train.jsonl", train_chat)
    write_jsonl(f"{args.out_dir}/val.jsonl", val_chat)
    # also keep the full-metadata (non-chat) versions for debugging/inspection
    write_jsonl(f"{args.out_dir}/train.full.jsonl", train)
    write_jsonl(f"{args.out_dir}/val.full.jsonl", val)

    print(
        f"== wrote {len(train_chat)} train / {len(val_chat)} val chat records to {args.out_dir}/ ==")


if __name__ == "__main__":
    main()
