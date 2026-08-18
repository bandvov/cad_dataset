"""
gen_single_feature.py
Produces one record per build123d feature type, covering the full IR
surface (schema.FEATURE_TYPES). Modifying features (Fillet/Chamfer/Shell/
Hole/Mirror/Pattern) get a minimal base block (sketch+extrude) so they have
something valid to operate on -- the *feature under test* is still just one
addition to that scaffold, which is what "single feature" refers to here.

Run standalone: python gen_single_feature.py --n-per-type 200 --out out/single_feature.jsonl
"""

from __future__ import annotations
import argparse
import json
import random

from primitives import IdGen, rnd, safe_fillet_radius, safe_hole_depth, phrase_instruction, Record


def _base_block(rng: random.Random, idgen: IdGen):
    """A simple rectangular plate: Sketch -> Extrude. Returns
    (features_list, dims) where dims = (width, height, thickness)."""
    width = rnd("med_dim", rng)
    height = rnd("med_dim", rng)
    thickness = rnd("extrude_thin", rng)

    sk_id = idgen.next("sketch")
    ex_id = idgen.next("extrude")
    features = [
        {
            "id": sk_id, "feature_type": "Sketch",
            "primitives": [{
                "type": "Rectangle",
                "parameters": {"width": width, "height": height, "position": [0, 0],
                                "rotation": 0, "mode": "ADD"},
            }],
        },
        {
            "id": ex_id, "feature_type": "Extrude",
            "source": sk_id, "amount": thickness, "operation": "ADD",
        },
    ]
    return features, (width, height, thickness), ex_id


# --------------------------------------------------------------------------- #
# solid-producing feature generators
# --------------------------------------------------------------------------- #
def gen_extrude(rng: random.Random) -> Record:
    idgen = IdGen()
    w, h = rnd("med_dim", rng), rnd("med_dim", rng)
    amount = rnd("extrude_med", rng)
    sk_id, ex_id = idgen.next("sketch"), idgen.next("extrude")
    ir = {"operation": "part", "features": [
        {"id": sk_id, "feature_type": "Sketch", "primitives": [
            {"type": "Rectangle", "parameters": {"width": w, "height": h, "position": [0, 0],
                                                   "rotation": 0, "mode": "ADD"}}]},
        {"id": ex_id, "feature_type": "Extrude", "source": sk_id, "amount": amount, "operation": "ADD"},
    ]}
    instr = phrase_instruction(f"a {w}x{h}mm plate extruded {amount}mm thick", "flat rectangular block", rng)
    return Record("generate", instr, ir, complexity=1)


def gen_revolve(rng: random.Random) -> Record:
    idgen = IdGen()
    r = rnd("revolve_radius", rng)
    h = rnd("med_dim", rng)
    sk_id, rv_id = idgen.next("sketch"), idgen.next("revolve")
    # profile: rectangle offset from the revolve axis (Y axis at x=0)
    ir = {"operation": "part", "features": [
        {"id": sk_id, "feature_type": "Sketch", "primitives": [
            {"type": "Rectangle", "parameters": {"width": r * 0.4, "height": h,
                                                   "position": [r, 0], "rotation": 0, "mode": "ADD"}}]},
        {"id": rv_id, "feature_type": "Revolve", "source": sk_id,
         "axis": {"origin": [0, 0, 0], "direction": [0, 1, 0]}, "angle": 360, "operation": "ADD"},
    ]}
    instr = phrase_instruction(f"a revolved ring, radius {r}mm, height {h}mm", "axisymmetric turned part", rng)
    return Record("generate", instr, ir, complexity=1)


def gen_loft(rng: random.Random) -> Record:
    idgen = IdGen()
    w, h = rnd("med_dim", rng), rnd("med_dim", rng)
    top_r = rnd("small_dim", rng)
    stack_h = rnd("extrude_med", rng)
    sk1, sk2, lf = idgen.next("sketch"), idgen.next("sketch"), idgen.next("loft")
    ir = {"operation": "part", "features": [
        {"id": sk1, "feature_type": "Sketch", "plane": {"origin": [0, 0, 0], "normal": [0, 0, 1]},
         "primitives": [{"type": "Rectangle",
                          "parameters": {"width": w, "height": h, "position": [0, 0],
                                         "rotation": 0, "mode": "ADD"}}]},
        {"id": sk2, "feature_type": "Sketch", "plane": {"origin": [0, 0, stack_h], "normal": [0, 0, 1]},
         "primitives": [{"type": "Circle",
                          "parameters": {"radius": top_r, "position": [0, 0], "mode": "ADD"}}]},
        {"id": lf, "feature_type": "Loft", "sources": [sk1, sk2], "ruled": False, "operation": "ADD"},
    ]}
    instr = phrase_instruction("a lofted transition from a rectangular base to a circular top",
                                f"base {w}x{h}mm, top radius {top_r}mm, height {stack_h}mm", rng)
    return Record("generate", instr, ir, complexity=1)


def gen_sweep(rng: random.Random) -> Record:
    idgen = IdGen()
    r = round(rng.uniform(3, 15), 2)
    pts = [[round(rng.uniform(-80, 80), 1), round(rng.uniform(-80, 80), 1), round(rng.uniform(0, 40), 1)]
           for _ in range(4)]
    prof, path, sw = idgen.next("sketch"), idgen.next("sketch"), idgen.next("sweep")
    ir = {"operation": "part", "features": [
        {"id": path, "feature_type": "Sketch", "primitives": [
            {"type": "Spline", "parameters": {"points": pts}}]},
        {"id": prof, "feature_type": "Sketch",
         "plane": {"origin": pts[0], "normal": [1, 0, 0]},
         "primitives": [{"type": "Circle", "parameters": {"radius": r, "position": [0, 0], "mode": "ADD"}}]},
        {"id": sw, "feature_type": "Sweep", "profile": prof, "path": path, "is_frenet": True, "operation": "ADD"},
    ]}
    instr = phrase_instruction(f"a swept pipe of radius {r}mm along a curved path", "tube following a spline", rng)
    return Record("generate", instr, ir, complexity=1)


# --------------------------------------------------------------------------- #
# solid-modifying feature generators (all use _base_block as scaffold)
# --------------------------------------------------------------------------- #
def gen_fillet(rng: random.Random) -> Record:
    idgen = IdGen()
    features, (w, h, t), ex_id = _base_block(rng, idgen)
    r = safe_fillet_radius(min(w, h, t), rng)
    fid = idgen.next("fillet")
    features.append({
        "id": fid, "feature_type": "Fillet",
        "selector": {"of": "edges", "filter_by": "Z", "criterion": "max"},
        "radius": r,
    })
    instr = phrase_instruction(f"a plate with a {r}mm fillet on the top edges", "rounded top perimeter", rng)
    return Record("generate", instr, {"operation": "part", "features": features}, complexity=2)


def gen_chamfer(rng: random.Random) -> Record:
    idgen = IdGen()
    features, (w, h, t), ex_id = _base_block(rng, idgen)
    length = safe_fillet_radius(min(w, h, t), rng)
    fid = idgen.next("chamfer")
    features.append({
        "id": fid, "feature_type": "Chamfer",
        "selector": {"of": "edges", "filter_by": "Z", "criterion": "max"},
        "length": length,
    })
    instr = phrase_instruction(f"a plate with a {length}mm chamfer on the top edges", "beveled top perimeter", rng)
    return Record("generate", instr, {"operation": "part", "features": features}, complexity=2)


def gen_shell(rng: random.Random) -> Record:
    idgen = IdGen()
    features, (w, h, t), ex_id = _base_block(rng, idgen)
    thickness = round(min(RANGES_wall(rng), t * 0.4), 2)
    sid = idgen.next("shell")
    features.append({
        "id": sid, "feature_type": "Shell", "thickness": thickness,
        "open_selector": {"of": "faces", "filter_by": "Z", "criterion": "max"},
    })
    instr = phrase_instruction(f"a hollow box, wall thickness {thickness}mm, open on top", "shelled enclosure", rng)
    return Record("generate", instr, {"operation": "part", "features": features}, complexity=2)


def RANGES_wall(rng: random.Random) -> float:
    from primitives import RANGES
    lo, hi = RANGES["wall_thickness"]
    return round(rng.uniform(lo, hi), 2)


def gen_hole(rng: random.Random, style: str) -> Record:
    idgen = IdGen()
    features, (w, h, t), ex_id = _base_block(rng, idgen)
    radius = round(rng.uniform(1.5, min(w, h) * 0.15), 2)
    depth = safe_hole_depth(t, rng, through=(style == "simple" and rng.random() < 0.5))
    hid = idgen.next("hole")
    hole_feat = {
        "id": hid, "feature_type": "Hole", "style": style,
        "radius": radius, "depth": depth,
        "location": {"position": [0, 0, t], "normal": [0, 0, -1]},
    }
    if style == "counterbore":
        hole_feat["cb_radius"] = round(radius * 1.8, 2)
        hole_feat["cb_depth"] = round(depth * 0.3, 2)
    elif style == "countersink":
        hole_feat["cs_angle"] = 90
    features.append(hole_feat)
    instr = phrase_instruction(f"a plate with a {style} hole, radius {radius}mm", f"depth {depth}mm", rng)
    return Record("generate", instr, {"operation": "part", "features": features}, complexity=2)


def gen_mirror(rng: random.Random) -> Record:
    idgen = IdGen()
    features, (w, h, t), ex_id = _base_block(rng, idgen)
    mid = idgen.next("mirror")
    features.append({"id": mid, "feature_type": "Mirror", "plane": "YZ", "operation": "ADD"})
    instr = phrase_instruction("a plate mirrored across the YZ plane", "symmetric doubled block", rng)
    return Record("generate", instr, {"operation": "part", "features": features}, complexity=2)


def gen_linear_pattern(rng: random.Random) -> Record:
    idgen = IdGen()
    features, (w, h, t), ex_id = _base_block(rng, idgen)
    count = rng.randint(2, 6)
    spacing = round(w * 1.5, 2)
    pid = idgen.next("pattern")
    features.append({
        "id": pid, "feature_type": "LinearPattern",
        "direction": [1, 0, 0], "count": count, "spacing": spacing, "operation": "ADD",
    })
    instr = phrase_instruction(f"{count} plates in a linear array spaced {spacing}mm apart", "repeated block feature", rng)
    return Record("generate", instr, {"operation": "part", "features": features}, complexity=2)


def gen_circular_pattern(rng: random.Random) -> Record:
    idgen = IdGen()
    features, (w, h, t), ex_id = _base_block(rng, idgen)
    count = rng.randint(3, 8)
    pid = idgen.next("pattern")
    features.append({
        "id": pid, "feature_type": "CircularPattern",
        "axis": {"origin": [w, 0, 0], "direction": [0, 0, 1]}, "count": count, "angle": 360,
    })
    instr = phrase_instruction(f"{count} plates arranged in a circular pattern", "radially repeated feature", rng)
    return Record("generate", instr, {"operation": "part", "features": features}, complexity=2)


GENERATORS = {
    "Extrude": gen_extrude,
    "Revolve": gen_revolve,
    "Loft": gen_loft,
    "Sweep": gen_sweep,
    "Fillet": gen_fillet,
    "Chamfer": gen_chamfer,
    "Shell": gen_shell,
    "Hole_simple": lambda rng: gen_hole(rng, "simple"),
    "Hole_counterbore": lambda rng: gen_hole(rng, "counterbore"),
    "Hole_countersink": lambda rng: gen_hole(rng, "countersink"),
    "Mirror": gen_mirror,
    "LinearPattern": gen_linear_pattern,
    "CircularPattern": gen_circular_pattern,
}


def generate(n_per_type: int, seed: int = 0):
    rng = random.Random(seed)
    records = []
    for name, fn in GENERATORS.items():
        for i in range(n_per_type):
            rec = fn(rng)
            records.append(rec.to_dict(f"single_{name}_{i:05d}"))
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-type", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="out/single_feature.jsonl")
    args = ap.parse_args()

    records = generate(args.n_per_type, args.seed)
    with open(args.out, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(records)} records to {args.out}")


if __name__ == "__main__":
    main()
