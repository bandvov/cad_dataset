"""
gen_repair.py
Takes already-verified "generate" records (from gen_single_feature.py /
gen_chains.py, post build_dataset.py verification pass) and injects one
plausible fault per record. Critically: both the broken and the fixed
version are run through the real executor -- we only keep a pair if the
broken IR actually fails and the fixed IR actually succeeds. We never
hand-write error strings; the "error" field is always what build123d /
our compiler actually raised.

This means gen_repair.py must be run *after* you have a real build123d
install available, since it needs execute_ir() to work. See README.md.

Usage:
    python gen_repair.py --in out/single_feature.verified.jsonl \
                          --in out/chains.verified.jsonl \
                          --out out/repair.jsonl --n 500
"""

from __future__ import annotations
import argparse
import copy
import json
import random

from executor import execute_ir


def _find_features(ir: dict, feature_type: str):
    return [f for f in ir["features"] if f["feature_type"] == feature_type]


# --------------------------------------------------------------------------- #
# fault injectors -- each returns (broken_ir, fault_description) or None if
# this fault type doesn't apply to the given IR
# --------------------------------------------------------------------------- #
def fault_oversize_fillet(ir: dict, rng: random.Random):
    fillets = _find_features(ir, "Fillet")
    if not fillets:
        return None
    broken = copy.deepcopy(ir)
    target = rng.choice(_find_features(broken, "Fillet"))
    old = target["radius"]
    target["radius"] = round(old * rng.uniform(4, 10) + 5, 2)
    return broken, f"increased fillet radius from {old}mm to {target['radius']}mm (too large for the edge)"


def fault_oversize_chamfer(ir: dict, rng: random.Random):
    chamfers = _find_features(ir, "Chamfer")
    if not chamfers:
        return None
    broken = copy.deepcopy(ir)
    target = rng.choice(_find_features(broken, "Chamfer"))
    old = target["length"]
    target["length"] = round(old * rng.uniform(4, 10) + 5, 2)
    return broken, f"increased chamfer length from {old}mm to {target['length']}mm (too large for the edge)"


def fault_zero_dimension(ir: dict, rng: random.Random):
    sketches = _find_features(ir, "Sketch")
    candidates = []
    for sk in sketches:
        for prim in sk["primitives"]:
            if prim["type"] in ("Rectangle",) and "width" in prim.get("parameters", {}):
                candidates.append((prim, "width"))
            if prim["type"] in ("Rectangle",) and "height" in prim.get("parameters", {}):
                candidates.append((prim, "height"))
            if prim["type"] == "Circle":
                candidates.append((prim, "radius"))
    if not candidates:
        return None
    broken = copy.deepcopy(ir)
    # re-locate the same (prim, key) pair inside the deep copy by index walk
    flat = []
    for sk in broken["features"]:
        if sk["feature_type"] != "Sketch":
            continue
        for prim in sk["primitives"]:
            if prim["type"] == "Rectangle":
                flat.append((prim, "width"))
                flat.append((prim, "height"))
            elif prim["type"] == "Circle":
                flat.append((prim, "radius"))
    prim, key = rng.choice(flat)
    old = prim["parameters"][key]
    prim["parameters"][key] = round(rng.choice([-abs(old), 0.0]), 2)
    return broken, f"set {key} to {prim['parameters'][key]} (was {old}) — non-positive dimension"


def fault_negative_hole_depth(ir: dict, rng: random.Random):
    holes = _find_features(ir, "Hole")
    if not holes:
        return None
    broken = copy.deepcopy(ir)
    target = rng.choice(_find_features(broken, "Hole"))
    old = target["depth"]
    target["depth"] = round(-abs(old) if rng.random() < 0.5 else 0.0, 2)
    return broken, f"set hole depth to {target['depth']}mm (was {old}mm) — non-positive depth"


def fault_zero_match_selector(ir: dict, rng: random.Random):
    """Swap a Fillet/Chamfer selector to filter by a GeomType that won't be
    present on a purely rectilinear block -- guaranteed CompileError from
    our own selector resolution, independent of exact build123d version
    behavior, so this fault type is the most robust one available."""
    candidates = _find_features(ir, "Fillet") + _find_features(ir, "Chamfer")
    if not candidates:
        return None
    broken = copy.deepcopy(ir)
    broken_candidates = _find_features(broken, "Fillet") + _find_features(broken, "Chamfer")
    target = rng.choice(broken_candidates)
    old_sel = dict(target["selector"])
    target["selector"] = {"of": "edges", "filter_by": "GeomType", "geom_type": "CIRCLE"}
    return broken, f"changed selector from {old_sel} to filter_by GeomType CIRCLE (no circular edges present)"


def fault_undefined_reference(ir: dict, rng: random.Random):
    """Point a source/target field at a nonexistent id -- tests that the
    model can repair broken references, not just bad numeric parameters."""
    broken = copy.deepcopy(ir)
    ref_bearing = [f for f in broken["features"]
                   if f["feature_type"] in ("Extrude", "Revolve") and "source" in f]
    if not ref_bearing:
        return None
    target = rng.choice(ref_bearing)
    old = target["source"]
    target["source"] = old + "_missing"
    return broken, f"changed source reference from '{old}' to '{target['source']}' (id does not exist)"


FAULT_TYPES = [
    fault_oversize_fillet,
    fault_oversize_chamfer,
    fault_zero_dimension,
    fault_negative_hole_depth,
    fault_zero_match_selector,
    fault_undefined_reference,
]


def make_repair_record(record: dict, rng: random.Random, timeout: float, execute_fn=None):
    """Returns a repair-task dict, or None if no applicable/verifiable fault
    could be produced for this record.

    execute_fn: callable(ir, timeout=...) -> result dict, defaults to the
    one-shot execute_ir. Pass a BatchExecutor's .execute (bound, ignores
    timeout kwarg since it's fixed at construction) when calling this in
    a loop -- see build_dataset.py -- to avoid paying a fresh build123d
    cold-import per repair record."""
    execute_fn = execute_fn or execute_ir
    ir = record["json_ir"]
    applicable = [f for f in FAULT_TYPES if f(ir, rng) is not None]
    if not applicable:
        return None
    fault_fn = rng.choice(applicable)
    result = fault_fn(ir, rng)
    if result is None:
        return None
    broken_ir, fault_desc = result

    broken_result = execute_fn(broken_ir, timeout=timeout)
    if broken_result.get("success"):
        return None  # fault didn't actually break it -- discard, don't fabricate

    fixed_result = execute_fn(ir, timeout=timeout)
    if not fixed_result.get("success"):
        return None  # the "known good" record wasn't actually good -- discard

    return {
        "record_id": f"repair_{record['record_id']}",
        "task_type": "repair",
        "schema_version": 2,
        "complexity": record["complexity"],
        "units": record.get("units", "mm"),
        "source": record.get("source", "procedural"),
        "instruction": "This part fails to build. Diagnose and fix it.",
        "fault_description": fault_desc,
        "broken_ir": broken_ir,
        "error_type": broken_result.get("error_type"),
        "error": broken_result.get("error"),
        "json_ir": ir,
        "verified": True,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", action="append", required=True,
                     help="verified generate-task jsonl file(s), repeatable")
    ap.add_argument("--out", default="out/repair.jsonl")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    pool = []
    for path in args.inputs:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    pool.append(json.loads(line))
    rng.shuffle(pool)

    written = 0
    skipped = 0
    with open(args.out, "w") as out:
        for record in pool:
            if written >= args.n:
                break
            rec = make_repair_record(record, rng, args.timeout)
            if rec is None:
                skipped += 1
                continue
            out.write(json.dumps(rec) + "\n")
            written += 1

    print(f"wrote {written} repair records to {args.out} (skipped {skipped} unverifiable attempts)")


if __name__ == "__main__":
    main()
