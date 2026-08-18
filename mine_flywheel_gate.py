"""
mine_flywheel_gate.py
Phase 4 step 9: volume gate. Checks verified flywheel record counts
against minimum thresholds before the data is considered ready to fold
into a training run -- prevents triggering retraining (step 11) on a
trickle of low-signal data. Exit 0 = pass, exit 1 = fail (safe to use in
a shell pipeline / step 10's scheduler).

Usage:
    python mine_flywheel_gate.py \
        --repairs out/flywheel_repairs.verified.jsonl --min-repairs 10 \
        --edits out/flywheel_edits.verified.jsonl --min-edits 10 \
        --min-total 50
"""

from __future__ import annotations
import argparse
import json
import os
import sys


def count_jsonl(path: str) -> int:
    if not path or not os.path.exists(path):
        return 0
    with open(path) as f:
        return sum(1 for line in f if line.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repairs", default="out/flywheel_repairs.verified.jsonl")
    ap.add_argument("--edits", default="out/flywheel_edits.verified.jsonl")
    ap.add_argument("--min-repairs", type=int, default=0)
    ap.add_argument("--min-edits", type=int, default=0)
    ap.add_argument("--min-total", type=int, default=50)
    args = ap.parse_args()

    n_repairs = count_jsonl(args.repairs)
    n_edits = count_jsonl(args.edits)
    total = n_repairs + n_edits

    checks = [
        ("total", total, args.min_total),
        ("repairs", n_repairs, args.min_repairs),
        ("edits", n_edits, args.min_edits),
    ]

    print(f"repairs: {n_repairs}  edits: {n_edits}  total: {total}")
    failed = [name for name, actual, minimum in checks if actual < minimum]
    for name, actual, minimum in checks:
        status = "OK" if actual >= minimum else "FAIL"
        print(f"  [{status}] {name}: {actual} >= {minimum}")

    if failed:
        print(f"GATE FAILED: {', '.join(failed)} below threshold -- not ready for training")
        sys.exit(1)

    print("GATE PASSED: ready for step 11 (retraining trigger)")
    sys.exit(0)


if __name__ == "__main__":
    main()
