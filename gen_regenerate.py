"""
gen_regenerate.py
Takes "generate" records produced by gen_chains.py (which carry a replayable
"recipe" in record["recipe"]), edits one input value, and replays
build_from_recipe() to get the new tree. Because every dependent quantity
in gen_chains.py's apply_* functions is a formula of PartState rather than
an independent random draw, this guarantees the edited tree is internally
consistent -- e.g. resizing the base updates pattern spacing, boss size,
and hole position together, the way a real regeneration must.

Usage:
    python gen_regenerate.py --in out/chains.jsonl --out out/regenerate.jsonl --n 500
"""

from __future__ import annotations
import argparse
import copy
import json
import random

from gen_chains import build_from_recipe, STEP_REGISTRY


def _edit_base_dim(recipe: dict, rng: random.Random) -> tuple[dict, str]:
    dim = rng.choice(["w", "h", "t"])
    factor = rng.choice([0.6, 0.75, 1.25, 1.5, 1.8])
    old = recipe["base"][dim]
    new = round(old * factor, 2)
    recipe["base"][dim] = new
    label = {"w": "width", "h": "height", "t": "thickness"}[dim]
    direction = "Increase" if factor > 1 else "Decrease"
    pct = abs(round((factor - 1) * 100))
    return recipe, f"{direction} the base {label} by {pct}% (from {old}mm to {new}mm)."


def _edit_discrete_count(recipe: dict, rng: random.Random):
    countable = [s for s in recipe["steps"] if "count" in s["params"]]
    if not countable:
        return None
    step = rng.choice(countable)
    old = step["params"]["count"]
    lo, hi = (2, 5) if step["step"] == "linear_pattern" else (3, 6)
    choices = [c for c in range(lo, hi + 1) if c != old]
    if not choices:
        return None
    new = rng.choice(choices)
    step["params"]["count"] = new
    kind = "linear" if step["step"] == "linear_pattern" else "circular"
    return recipe, f"Change the {kind} pattern count from {old} to {new}."


def _edit_hole_kind(recipe: dict, rng: random.Random):
    holes = [s for s in recipe["steps"] if s["step"] == "hole"]
    if not holes:
        return None
    step = rng.choice(holes)
    old = step["params"]["through"]
    step["params"]["through"] = not old
    new_kind, old_kind = ("blind", "through") if old else ("through", "blind")
    return recipe, f"Change the hole from {old_kind} to {new_kind}."


EDITORS = [_edit_base_dim, _edit_discrete_count, _edit_hole_kind]


def make_regenerate_record(record: dict, rng: random.Random):
    if "recipe" not in record:
        return None  # only chain-recipe records support consistent replay
    base_recipe = copy.deepcopy(record["recipe"])

    applicable = [e for e in EDITORS if e is not _edit_base_dim]  # base dim always applies
    editor = rng.choice([_edit_base_dim] + [e for e in applicable])
    result = editor(base_recipe, rng)
    if result is None:
        result = _edit_base_dim(base_recipe, rng)  # fallback, always valid
    new_recipe, edit_instruction = result

    new_ir, _full_instr, complexity = build_from_recipe(new_recipe)

    return {
        "record_id": f"regen_{record['record_id']}",
        "task_type": "regenerate",
        "schema_version": 2,
        "complexity": complexity,
        "units": record.get("units", "mm"),
        "source": record.get("source", "procedural"),
        "instruction": edit_instruction,
        "base_ir": record["json_ir"],
        "json_ir": new_ir,
        "recipe": new_recipe,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="input", required=True,
                     help="chains.jsonl produced by gen_chains.py (needs 'recipe' field)")
    ap.add_argument("--out", default="out/regenerate.jsonl")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    pool = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                pool.append(json.loads(line))
    rng.shuffle(pool)

    written = 0
    with open(args.out, "w") as out:
        for record in pool:
            if written >= args.n:
                break
            rec = make_regenerate_record(record, rng)
            if rec is None:
                continue
            out.write(json.dumps(rec) + "\n")
            written += 1

    print(f"wrote {written} regenerate records to {args.out}")


if __name__ == "__main__":
    main()
