"""
mine_flywheel_chatformat.py
Phase 4 step 7: converts verified, deduped flywheel records (step 5's
output) into the same {prompt, completion} chat shape as synthetic data,
reusing build_dataset.py's to_chat_format() directly -- no reimplementation,
so flywheel and synthetic records are guaranteed to render identically.

Usage:
    python mine_flywheel_chatformat.py \
        --in out/flywheel_deduped.jsonl --out out/flywheel_chat.jsonl
"""

from __future__ import annotations
import argparse
import json
import os

from build_dataset import to_chat_format


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="input", default="out/flywheel_deduped.jsonl")
    ap.add_argument("--out", default="out/flywheel_chat.jsonl")
    args = ap.parse_args()

    with open(args.input) as f:
        records = [json.loads(l) for l in f]

    chat_records = [to_chat_format(r) for r in records]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        for r in chat_records:
            f.write(json.dumps(r) + "\n")
    print(f"converted {len(chat_records)} records -> {args.out}")


if __name__ == "__main__":
    main()
