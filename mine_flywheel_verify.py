"""
mine_flywheel_verify.py
Phase 4 step 4: re-verification. Runs every candidate record from
mine_flywheel_repairs.py / mine_flywheel_edits.py through
executor.BatchExecutor -- the same real build123d gate every other record
in this pipeline goes through. Nothing is trusted just because production
logged it that way (things drift: a fix that worked when logged might not
compile against a newer build123d/schema version). Sets verified=True
only on records that pass; everything else goes to a quarantine file, not
silently dropped.

Repair records: broken_ir must FAIL, json_ir (fix) must SUCCEED.
Edit records:   base_ir must SUCCEED, json_ir (edited) must SUCCEED.

Usage:
    python mine_flywheel_verify.py \
        --repairs out/flywheel_repairs.jsonl --edits out/flywheel_edits.jsonl \
        --out-repairs out/flywheel_repairs.verified.jsonl \
        --out-edits out/flywheel_edits.verified.jsonl \
        --quarantine out/flywheel_quarantine.jsonl
"""

from __future__ import annotations
import argparse
import json
import os

from executor import BatchExecutor


def verify_repair(rec: dict, be: BatchExecutor) -> tuple[bool, str | None]:
    broken = be.execute(rec["broken_ir"])
    if broken.get("success"):
        return False, "broken_ir unexpectedly compiled -- no longer reproduces the failure"
    fixed = be.execute(rec["json_ir"])
    if not fixed.get("success"):
        return False, f"fix no longer compiles: {fixed.get('error')}"
    return True, None


def verify_edit(rec: dict, be: BatchExecutor) -> tuple[bool, str | None]:
    base = be.execute(rec["base_ir"])
    if not base.get("success"):
        return False, f"base_ir no longer compiles: {base.get('error')}"
    edited = be.execute(rec["json_ir"])
    if not edited.get("success"):
        return False, f"edited json_ir no longer compiles: {edited.get('error')}"
    return True, None


def run(records: list[dict], verify_fn, be: BatchExecutor, label: str):
    verified, quarantined = [], []
    for i, rec in enumerate(records):
        ok, reason = verify_fn(rec, be)
        if ok:
            verified.append({**rec, "verified": True})
        else:
            quarantined.append({**rec, "verified": False, "verification_error": reason})
        if (i + 1) % 20 == 0 or i + 1 == len(records):
            print(f"  [{label}] {i + 1}/{len(records)}  ({len(verified)} verified)", flush=True)
    return verified, quarantined


def load_jsonl(path: str) -> list[dict]:
    if not path or not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(l) for l in f]


def write_jsonl(path: str, rows: list[dict]):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repairs", default="out/flywheel_repairs.jsonl")
    ap.add_argument("--edits", default="out/flywheel_edits.jsonl")
    ap.add_argument("--out-repairs", default="out/flywheel_repairs.verified.jsonl")
    ap.add_argument("--out-edits", default="out/flywheel_edits.verified.jsonl")
    ap.add_argument("--quarantine", default="out/flywheel_quarantine.jsonl")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    repairs = load_jsonl(args.repairs)
    edits = load_jsonl(args.edits)
    print(f"{len(repairs)} repair candidates, {len(edits)} edit candidates")

    with BatchExecutor(timeout_per_item=args.timeout) as be:
        v_repairs, q_repairs = run(repairs, verify_repair, be, "repairs")
        v_edits, q_edits = run(edits, verify_edit, be, "edits")

    write_jsonl(args.out_repairs, v_repairs)
    write_jsonl(args.out_edits, v_edits)
    write_jsonl(args.quarantine, q_repairs + q_edits)
    print(f"verified: {len(v_repairs)} repairs, {len(v_edits)} edits")
    print(f"quarantined: {len(q_repairs) + len(q_edits)} -> {args.quarantine}")


if __name__ == "__main__":
    main()
