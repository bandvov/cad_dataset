"""
mine_flywheel_dedup.py
Phase 4 step 5: dedup verified flywheel records against the existing
training corpus, reusing build_dataset.py's own structure_hash()
(feature_type+operation sequence) so "collides with existing data" means
the same thing here as everywhere else in this pipeline.

Usage:
    python mine_flywheel_dedup.py \
        --corpus out/train.full.jsonl out/val.full.jsonl \
        --candidates out/flywheel_repairs.verified.jsonl out/flywheel_edits.verified.jsonl \
        --out out/flywheel_deduped.jsonl
"""

from __future__ import annotations
import argparse
import json
import os

from build_dataset import structure_hash


def load_jsonl(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f]


def existing_hashes(corpus_paths: list[str]) -> set[tuple[str, str]]:
    seen = set()
    for path in corpus_paths:
        if not os.path.exists(path):
            continue
        for r in load_jsonl(path):
            seen.add((r["task_type"], structure_hash(r["json_ir"])))
    return seen


def dedup(candidates: list[dict], seen: set[tuple[str, str]]) -> tuple[list[dict], list[dict]]:
    kept, dropped = [], []
    for r in candidates:
        key = (r["task_type"], structure_hash(r["json_ir"]))
        if key in seen:
            dropped.append(r)
        else:
            seen.add(key)  # also dedupe across/within candidate files themselves
            kept.append(r)
    return kept, dropped


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", nargs="+", default=["out/train.full.jsonl", "out/val.full.jsonl"])
    ap.add_argument("--candidates", nargs="+", required=True)
    ap.add_argument("--out", default="out/flywheel_deduped.jsonl")
    args = ap.parse_args()

    seen = existing_hashes(args.corpus)
    print(f"{len(seen)} structural hashes loaded from existing corpus")

    candidates = []
    for path in args.candidates:
        candidates.extend(load_jsonl(path))
    print(f"{len(candidates)} flywheel candidates loaded")

    kept, dropped = dedup(candidates, seen)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        for r in kept:
            f.write(json.dumps(r) + "\n")
    print(f"kept {len(kept)}, dropped {len(dropped)} (collided with existing corpus or each other)")


if __name__ == "__main__":
    main()
