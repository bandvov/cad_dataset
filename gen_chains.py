"""
gen_chains.py
Composes 2-8 features into a single part with real dependencies. Design:
every downstream feature's size/position is a *fixed formula* of the
running PartState (base width/height/thickness and whatever the previous
steps changed), not an independent random draw. Randomness only decides
(a) which step types appear and in what order, and (b) a handful of
discrete choices (pattern counts, through vs. blind hole, which axis/side
a fillet or chamfer selector targets, and -- as of this version -- which
existing hole a hole-rim fillet targets and whether it targets one or
both rims).

That discrete "recipe" (step sequence + discrete choices + base dims) is
stored alongside the record. gen_regenerate.py replays the exact same
formulas with one changed input, so every dependent value in the tree is
recomputed consistently rather than left stale -- see README.md.

NOTE ON THE "hole_fillet" STEP (added): this is the training-data side of
the near_point selector added to schema.py/compiler.py (see those
modules' docstrings for the motivation -- axis/GeomType selectors can't
isolate one hole's rim edge). A hole_fillet step always targets a hole
placed by an EARLIER "hole" step in the same recipe (tracked via
PartState.holes, populated by apply_hole) -- sample_recipe enforces this
by excluding "hole_fillet" from the step pool until at least one "hole"
step has already been chosen. The recipe stores which hole ordinally
("hole_ordinal": 1 = the first hole placed, 2 = the second, ...) rather
than a feature id, since ids are only assigned deterministically at
build_from_recipe() time.

hole_fillet always targets the single rim at the hole's recorded
position (real x, y, z -- no null coordinates), regardless of whether the
hole is through or blind. This deliberately does not attempt "fillet both
ends of a through-hole in one feature" -- that would need a null-Z
selector plus re-checking the hole's through/blind state at apply time
(since gen_regenerate.py's `_edit_hole_kind` can flip it after the recipe
was first sampled), which is more selector surface than this step needs
to cover right now.

Run standalone: python gen_chains.py --n 500 --out out/chains.jsonl
"""

from __future__ import annotations
import argparse
import json
import random

from primitives import IdGen, rnd, phrase_instruction, Record, side_label


class PartState:
    def __init__(self, w, h, t):
        self.w, self.h, self.t = w, h, t
        self.top_z = t
        self.min_edge = min(w, h, t)
        # Every hole placed so far, in order -- populated by apply_hole(),
        # consumed by apply_hole_fillet() via a 1-based "hole_ordinal" (see
        # module docstring). Each entry: {"id", "position", "radius",
        # "depth", "through"}.
        self.holes: list[dict] = []


# --------------------------------------------------------------------------- #
# deterministic "apply" functions: state + explicit discrete params -> IR
# features appended in place. No rng in here -- every continuous value is a
# fixed formula of state, which is what makes replay-on-edit consistent.
# --------------------------------------------------------------------------- #
def apply_base(state: PartState, idgen: IdGen, features: list) -> str:
    sk, ex = idgen.next("sketch"), idgen.next("extrude")
    features.append({"id": sk, "feature_type": "Sketch", "primitives": [
        {"type": "Rectangle", "parameters": {"width": state.w, "height": state.h,
                                              "position": [0, 0], "rotation": 0, "mode": "ADD"}}]})
    features.append({"id": ex, "feature_type": "Extrude", "source": sk, "amount": state.t, "operation": "ADD"})
    return f"a {state.w}x{state.h}mm base block extruded {state.t}mm"


def apply_fillet(state: PartState, idgen: IdGen, features: list, params: dict) -> str:
    r = round(min(state.min_edge * 0.12, 3.0), 2)
    r = max(r, 0.3)
    # axis/criterion: default to the old Z/max ("top") behavior if a
    # caller doesn't supply one (e.g. gen_regenerate.py replaying an
    # older recipe recorded before this field existed).
    axis = params.get("axis", "Z")
    criterion = params.get("criterion", "max")
    features.append({"id": idgen.next("fillet"), "feature_type": "Fillet",
                      "selector": {"of": "edges", "filter_by": axis, "criterion": criterion}, "radius": r})
    return f"round the {side_label(axis, criterion)} edges with a {r}mm fillet"


def apply_chamfer(state: PartState, idgen: IdGen, features: list, params: dict) -> str:
    length = round(min(state.min_edge * 0.12, 3.0), 2)
    length = max(length, 0.3)
    axis = params.get("axis", "Z")
    criterion = params.get("criterion", "min")
    features.append({"id": idgen.next("chamfer"), "feature_type": "Chamfer",
                      "selector": {"of": "edges", "filter_by": axis, "criterion": criterion}, "length": length})
    return f"chamfer the {side_label(axis, criterion)} edges by {length}mm"


def apply_hole(state: PartState, idgen: IdGen, features: list, params: dict) -> str:
    through = params["through"]
    radius = round(min(state.w, state.h) * 0.08, 2)
    depth = round(state.t + 0.5, 2) if through else round(state.t * 0.5, 2)
    hid = idgen.next("hole")
    position = (0, 0, state.top_z)
    features.append({
        "id": hid, "feature_type": "Hole", "style": "simple",
        "radius": radius, "depth": depth,
        "location": {"position": list(position), "normal": [0, 0, -1]},
    })
    state.holes.append({"id": hid, "position": position, "radius": radius,
                         "depth": depth, "through": through})
    kind = "through" if through else "blind"
    return f"drill a {kind} hole of radius {radius}mm"


def apply_hole_fillet(state: PartState, idgen: IdGen, features: list, params: dict) -> str:
    """Fillets the rim of a hole placed by an earlier "hole" step, using
    the near_point selector (schema.py / compiler.py) rather than
    GeomType: CIRCLE -- the whole point being that this correctly targets
    ONE hole's edge even when other holes or rounded corners exist
    elsewhere on the part, which a GeomType filter cannot do. Always
    targets the single rim at the hole's recorded position, whether the
    hole is through or blind."""
    ordinal = params["hole_ordinal"]
    hole = state.holes[ordinal - 1]
    x, y, z = hole["position"]

    # keep the fillet comfortably smaller than the hole itself so it can't
    # collapse into or overlap the hole's own interior
    radius = round(min(hole["radius"] * 0.3, 2.0), 2)
    radius = max(radius, 0.2)
    # tolerance wide enough to survive float rounding in `position` but
    # well under schema.BOUNDS["max_near_point_tolerance_mm"], and small
    # enough to stay well clear of any other hole on a realistic layout
    tolerance = round(max(0.1, hole["radius"] * 0.15), 2)

    features.append({
        "id": idgen.next("fillet"), "feature_type": "Fillet",
        "selector": {"of": "edges", "filter_by": "near_point",
                     "point": [x, y, z], "tolerance": tolerance},
        "radius": radius,
    })
    return f"round the rim of that hole with a {radius}mm fillet"


def apply_shell(state: PartState, idgen: IdGen, features: list, params: dict) -> str:
    thickness = round(min(max(state.min_edge * 0.2, 1.0), 6.0, state.min_edge * 0.3), 2)
    features.append({
        "id": idgen.next("shell"), "feature_type": "Shell", "thickness": thickness,
        "open_selector": {"of": "faces", "filter_by": "Z", "criterion": "max"},
    })
    state.min_edge = min(state.min_edge, thickness)
    return f"shell it out to a {thickness}mm wall thickness, open on top"


def apply_linear_pattern(state: PartState, idgen: IdGen, features: list, params: dict) -> str:
    count = params["count"]
    spacing = round(state.w * 1.3, 2)
    features.append({
        "id": idgen.next("pattern"), "feature_type": "LinearPattern",
        "direction": [1, 0, 0], "count": count, "spacing": spacing, "operation": "ADD",
    })
    return f"repeat it {count} times along X, {spacing}mm apart"


def apply_circular_pattern(state: PartState, idgen: IdGen, features: list, params: dict) -> str:
    count = params["count"]
    features.append({
        "id": idgen.next("pattern"), "feature_type": "CircularPattern",
        "axis": {"origin": [state.w, 0, 0], "direction": [0, 0, 1]}, "count": count, "angle": 360,
    })
    return f"arrange {count} copies in a circular pattern"


def apply_boss(state: PartState, idgen: IdGen, features: list, params: dict) -> str:
    bw = round(state.w * 0.3, 2)
    bh = round(state.h * 0.3, 2)
    bt = round(state.t * 0.5 + 3, 2)
    sk, ex = idgen.next("sketch"), idgen.next("extrude")
    features.append({
        "id": sk, "feature_type": "Sketch",
        "plane": {"origin": [0, 0, state.top_z], "normal": [0, 0, 1]},
        "primitives": [{"type": "Rectangle", "parameters": {"width": bw, "height": bh,
                                                              "position": [0, 0], "rotation": 0, "mode": "ADD"}}],
    })
    features.append({"id": ex, "feature_type": "Extrude", "source": sk, "amount": bt, "operation": "ADD"})
    state.top_z += bt
    state.min_edge = min(state.min_edge, bw, bh, bt)
    return f"add a {bw}x{bh}mm boss on top, {bt}mm tall"


STEP_REGISTRY = {
    "fillet": apply_fillet,
    "chamfer": apply_chamfer,
    "hole": apply_hole,
    "hole_fillet": apply_hole_fillet,
    "shell": apply_shell,
    "linear_pattern": apply_linear_pattern,
    "circular_pattern": apply_circular_pattern,
    "boss": apply_boss,
}
STEP_WEIGHTS = {
    "fillet": 1.0, "chamfer": 0.8, "hole": 1.2, "hole_fillet": 0.7, "shell": 0.5,
    "linear_pattern": 0.6, "circular_pattern": 0.5, "boss": 0.9,
}


def sample_recipe(rng: random.Random, n_extra: int) -> dict:
    """The discrete part of the design: step order + any params that
    aren't a pure formula of state (counts, through/blind, fillet/chamfer
    axis+criterion, and which hole a hole_fillet step targets)."""
    w, h = rnd("med_dim", rng), rnd("med_dim", rng)
    t = rnd("extrude_med", rng)
    names = list(STEP_REGISTRY.keys())
    steps = []
    last_name = None
    # Tracks each "hole" step's through/blind choice, in order, so
    # hole_fillet steps can be assigned a valid 1-based "hole_ordinal"
    # (state.holes is built in this same order during build_from_recipe,
    # via apply_hole) and can decide whether "both_rims" is even a
    # sensible request to make at sample time.
    hole_through_flags: list[bool] = []
    for _ in range(n_extra):
        # avoid the same step repeating back-to-back on the same selector
        # (e.g. chamfering the already-chamfered bottom edge again) -- low
        # yield through verification and semantically odd
        pool_names = [n for n in names if n != last_name]
        # hole_fillet has nothing to target until at least one hole exists
        if not hole_through_flags:
            pool_names = [n for n in pool_names if n != "hole_fillet"]
        pool_weights = [STEP_WEIGHTS[n] for n in pool_names]
        name = rng.choices(pool_names, weights=pool_weights, k=1)[0]
        last_name = name
        params = {}
        if name == "hole":
            params["through"] = rng.random() < 0.6
            hole_through_flags.append(params["through"])
        elif name == "hole_fillet":
            params["hole_ordinal"] = rng.randint(1, len(hole_through_flags))
        elif name in ("linear_pattern",):
            params["count"] = rng.randint(2, 5)
        elif name == "circular_pattern":
            params["count"] = rng.randint(3, 6)
        elif name in ("fillet", "chamfer"):
            # previously always Z/max ("top") for fillet and Z/min
            # ("bottom") for chamfer -- every training record described
            # the same side regardless of instruction wording, so the
            # fine-tuned model never learned to emit an X/Y filter_by.
            params["axis"] = rng.choice(["X", "Y", "Z"])
            params["criterion"] = rng.choice(["max", "min"])
        steps.append({"step": name, "params": params})
    return {"base": {"w": w, "h": h, "t": t}, "steps": steps}


def build_from_recipe(recipe: dict) -> tuple[dict, str, int]:
    """Deterministically replays a recipe into (json_ir, instruction, complexity).
    Used both for initial generation and for gen_regenerate.py edits."""
    idgen = IdGen()
    features: list = []
    base = recipe["base"]
    state = PartState(base["w"], base["h"], base["t"])
    desc = apply_base(state, idgen, features)
    step_descs = []
    for step in recipe["steps"]:
        fn = STEP_REGISTRY[step["step"]]
        step_descs.append(fn(state, idgen, features, step["params"]))

    if step_descs:
        instr = f"{desc[0].upper()}{desc[1:]}, then {', then '.join(step_descs)}."
    else:
        instr = desc[0].upper() + desc[1:] + "."
    return {"features": features}, instr, len(features)


def generate(n: int, min_extra=1, max_extra=6, seed: int = 0):
    rng = random.Random(seed)
    records = []
    for i in range(n):
        n_extra = rng.randint(min_extra, max_extra)
        recipe = sample_recipe(rng, n_extra)
        ir, instr, complexity = build_from_recipe(recipe)
        rec = Record("generate", instr, ir, complexity=complexity, extra={"recipe": recipe})
        records.append(rec.to_dict(f"chain_{i:05d}"))
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="out/chains.jsonl")
    args = ap.parse_args()

    records = generate(args.n, seed=args.seed)
    with open(args.out, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(records)} records to {args.out}")


if __name__ == "__main__":
    main()
