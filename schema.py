"""
schema.py
Single source of truth for the JSON IR feature-tree format used across the
compiler and every data generator. Keeping this in one place means the
compiler and generators can never silently drift apart on field names.

IR shape:
{
  "features": [ {feature}, {feature}, ... ]
}

Every feature has: "id" (unique str) and "feature_type" (one of FEATURE_TYPES).
See FEATURE_SPECS below for required/optional fields per type.

NOTE ON THE (removed) ROOT "operation" FIELD: earlier versions of this
schema required a root {"operation": "part", "features": [...]} shape.
That field was dropped -- it never varied (there was only ever one kind
of document), nothing past validate_ir() ever read it, and it turned out
to be the single most common thing a fine-tuned model got wrong (emitting
the value as the key instead of the key itself: {"part": "part"}). A
root-level type discriminator only earns its keep when two possible
document shapes could be structurally ambiguous; a future assembly format
(see root README.md's "Known limitations") would have its own "bodies"
key at the root with each body's own nested "features" list, which is
already unambiguous against this shape without any extra tag. validate_ir()
below silently ignores an "operation" key if one is still present (old
generated data, old stored project versions), so nothing needs migrating.
"""

from __future__ import annotations
from typing import Any


SKETCH_PRIMITIVE_TYPES = {
    # closed 2D regions (combined into a Sketch via boolean "mode")
    "Rectangle": {"required": ["width", "height"], "optional": ["position", "rotation", "mode"]},
    "Circle": {"required": ["radius"], "optional": ["position", "mode"]},
    "Polygon": {"required": ["points"], "optional": ["position", "rotation", "mode"]},
    "Slot": {"required": ["width", "height"], "optional": ["position", "rotation", "mode"]},
    # open wires (used as Sweep paths / construction geometry, no "mode")
    "Line": {"required": ["points"], "optional": []},
    "Spline": {"required": ["points"], "optional": []},
    "Polyline": {"required": ["points"], "optional": []},
}

WIRE_PRIMITIVE_TYPES = {"Line", "Spline", "Polyline"}

FEATURE_TYPES = {
    "Sketch": {
        "required": ["primitives"],
        "optional": ["plane"],
    },
    "Extrude": {
        "required": ["source", "amount"],
        "optional": ["both", "taper", "operation"],
    },
    "Revolve": {
        "required": ["source"],
        "optional": ["axis", "angle", "operation"],
    },
    "Loft": {
        "required": ["sources"],
        "optional": ["ruled", "operation"],
    },
    "Sweep": {
        "required": ["profile", "path"],
        "optional": ["is_frenet", "operation"],
    },
    "Fillet": {
        "required": ["selector", "radius"],
        "optional": ["target"],
    },
    "Chamfer": {
        "required": ["selector", "length"],
        "optional": ["target", "length2", "angle"],
    },
    "Shell": {
        "required": ["thickness"],
        "optional": ["target", "open_selector"],
    },
    "Hole": {
        "required": ["style", "radius", "depth", "location"],
        "optional": ["target", "cb_radius", "cb_depth", "cs_angle"],
    },
    "Mirror": {
        "required": ["plane"],
        "optional": ["target", "operation"],
    },
    "LinearPattern": {
        "required": ["direction", "count", "spacing"],
        "optional": ["target", "operation"],
    },
    "CircularPattern": {
        "required": ["axis", "count", "angle"],
        "optional": ["target", "operation"],
    },
}

# Feature types that consume/produce full solid geometry and combine into
# the running part via a boolean "operation" (default ADD if omitted).
# NOTE: this is a PER-FEATURE field (Extrude.operation, Mirror.operation,
# etc. -- ADD/SUBTRACT/INTERSECT), unrelated to the removed root-level
# "operation" field discussed in the module docstring above. Same key
# name, different level, different meaning -- don't conflate them.
SOLID_PRODUCING = {
    "Extrude", "Revolve", "Loft", "Sweep", "Mirror", "LinearPattern", "CircularPattern",
}
# Feature types that mutate the current solid in place (no separate operand).
SOLID_MODIFYING = {"Fillet", "Chamfer", "Shell", "Hole"}

BOOLEAN_OPS = {"ADD", "SUBTRACT", "INTERSECT"}
SKETCH_MODES = {"ADD", "SUBTRACT", "INTERSECT"}
SELECTOR_AXES = {"X", "Y", "Z"}
SELECTOR_CRITERIA = {"max", "min", "all"}


class SchemaError(ValueError):
    pass


class BoundsError(ValueError):
    """Raised for IR that's structurally well-formed but has values a real
    request should never plausibly need -- a hallucinated pattern count of
    50000, a 1e9mm dimension, a tree with hundreds of features. This is
    the pre-execution sanity gate Phase 1 called for: reject fast, before
    ever spawning a worker, rather than relying only on the per-job
    timeout/rlimit backstop (which still burns a worker slot, and in the
    worst case can OOM before the timeout even fires)."""


# Deliberately generous -- these bound "no sane request needs more than
# this," not "this is the most a real part could ever have." Tune based on
# production data (see the earlier product-layer discussion: log requests
# that hit these limits, since that tells you whether the bound is too
# tight for real usage before it tells you about a hallucination).
BOUNDS = {
    "max_features": 60,
    "max_primitives_per_sketch": 20,
    "max_polygon_points": 200,
    "max_loft_sources": 8,
    "max_pattern_count": 50,
    "min_dimension_mm": 1e-3,
    "max_dimension_mm": 10_000.0,       # 10 meters -- generous for "a part"
    "max_fillet_or_chamfer_mm": 500.0,
    "max_revolve_angle_deg": 360.0 * 10,  # allow a few extra wraps, not thousands
}


def _check_dim(value, name: str, violations: list[str], max_override: float | None = None):
    lo = BOUNDS["min_dimension_mm"]
    hi = max_override if max_override is not None else BOUNDS["max_dimension_mm"]
    if not isinstance(value, (int, float)):
        return  # type issues are validate_ir's job, not bounds
    if value != value:  # NaN
        violations.append(f"{name} is NaN")
    elif value < lo or value > hi:
        violations.append(f"{name}={value} out of bounds [{lo}, {hi}]")


def validate_bounds(ir: dict) -> list[str]:
    """Returns a list of human-readable violation strings (empty = OK).
    Separate from validate_ir() on purpose: structural validity and
    resource/value sanity are different concerns, and callers (e.g.
    build_dataset.py's own generators, which are formula-bounded and will
    never trip these) don't need to pay for a check they can't fail."""
    violations: list[str] = []
    features = ir.get("features", [])
    if len(features) > BOUNDS["max_features"]:
        violations.append(f"tree has {len(features)} features, max {BOUNDS['max_features']}")

    for feat in features:
        fid = feat.get("id", "?")
        ftype = feat.get("feature_type")

        if ftype == "Sketch":
            prims = feat.get("primitives", [])
            if len(prims) > BOUNDS["max_primitives_per_sketch"]:
                violations.append(
                    f"'{fid}' has {len(prims)} primitives, max {BOUNDS['max_primitives_per_sketch']}"
                )
            for prim in prims:
                params = prim.get("parameters", {})
                for key in ("width", "height", "radius"):
                    if key in params:
                        _check_dim(params[key], f"'{fid}'.{prim.get('type')}.{key}", violations)
                pts = params.get("points")
                if pts is not None and len(pts) > BOUNDS["max_polygon_points"]:
                    violations.append(
                        f"'{fid}' primitive has {len(pts)} points, max {BOUNDS['max_polygon_points']}"
                    )

        elif ftype == "Extrude":
            _check_dim(feat.get("amount"), f"'{fid}'.amount", violations)

        elif ftype == "Revolve":
            angle = feat.get("angle", 360)
            if not (0 < angle <= BOUNDS["max_revolve_angle_deg"]):
                violations.append(f"'{fid}'.angle={angle} out of bounds (0, {BOUNDS['max_revolve_angle_deg']}]")

        elif ftype == "Loft":
            n = len(feat.get("sources", []))
            if n > BOUNDS["max_loft_sources"]:
                violations.append(f"'{fid}' has {n} sources, max {BOUNDS['max_loft_sources']}")

        elif ftype in ("Fillet", "Chamfer"):
            key = "radius" if ftype == "Fillet" else "length"
            _check_dim(feat.get(key), f"'{fid}'.{key}", violations,
                       max_override=BOUNDS["max_fillet_or_chamfer_mm"])

        elif ftype == "Shell":
            _check_dim(feat.get("thickness"), f"'{fid}'.thickness", violations)

        elif ftype == "Hole":
            for key in ("radius", "depth", "cb_radius", "cb_depth"):
                if key in feat:
                    _check_dim(feat[key], f"'{fid}'.{key}", violations)

        elif ftype in ("LinearPattern", "CircularPattern"):
            count = feat.get("count", 0)
            if count > BOUNDS["max_pattern_count"]:
                violations.append(f"'{fid}'.count={count} exceeds max {BOUNDS['max_pattern_count']}")
            if count < 1:
                violations.append(f"'{fid}'.count={count} must be >= 1")
            if ftype == "LinearPattern":
                _check_dim(feat.get("spacing"), f"'{fid}'.spacing", violations)

    return violations


def validate_ir(ir: dict) -> None:
    """Structural validation only (field presence / id references).
    Does NOT check geometric validity -- that requires actual execution,
    see executor.py / validator.py.

    Root shape is just {"features": [...]} -- see the module docstring
    for why the old root "operation": "part" requirement was dropped.
    Any extra/legacy top-level keys (including an old "operation" or a
    model's malformed "part") are simply never inspected here, so old
    stored/generated data with the old key still validates fine without
    a migration.
    """
    features = ir.get("features")
    if not isinstance(features, list) or not features:
        raise SchemaError("'features' must be a non-empty list")

    seen_ids: set[str] = set()
    for i, feat in enumerate(features):
        fid = feat.get("id")
        ftype = feat.get("feature_type")
        if not fid or not isinstance(fid, str):
            raise SchemaError(f"feature[{i}] missing valid 'id'")
        if fid in seen_ids:
            raise SchemaError(f"duplicate feature id '{fid}'")
        seen_ids.add(fid)
        if ftype not in FEATURE_TYPES:
            raise SchemaError(f"feature '{fid}' has unknown feature_type '{ftype}'")

        spec = FEATURE_TYPES[ftype]
        for req in spec["required"]:
            if req not in feat:
                raise SchemaError(f"feature '{fid}' ({ftype}) missing required field '{req}'")

        # reference checks: any field naming a prior feature id must exist earlier in the list
        ref_fields = []
        if ftype == "Extrude":
            ref_fields = ["source"]
        elif ftype == "Revolve":
            ref_fields = ["source"]
        elif ftype == "Loft":
            for src in feat["sources"]:
                if src not in seen_ids:
                    raise SchemaError(f"Loft '{fid}' references undefined/forward source '{src}'")
        elif ftype == "Sweep":
            ref_fields = ["profile", "path"]
        elif ftype in ("Fillet", "Chamfer", "Shell", "Hole", "Mirror",
                        "LinearPattern", "CircularPattern"):
            if "target" in feat and feat["target"] not in seen_ids:
                raise SchemaError(f"{ftype} '{fid}' references undefined/forward target '{feat['target']}'")

        for rf in ref_fields:
            if feat[rf] not in seen_ids:
                raise SchemaError(f"{ftype} '{fid}' references undefined/forward '{rf}'={feat[rf]}")

        if ftype == "Sketch":
            plane = feat.get("plane")
            if plane is not None and not isinstance(plane, dict):
                raise SchemaError(
                    f"Sketch '{fid}'.plane must be an object with 'origin'/'normal', "
                    f"got {type(plane).__name__}"
                )
            for p_i, prim in enumerate(feat["primitives"]):
                ptype = prim.get("type")
                if ptype not in SKETCH_PRIMITIVE_TYPES:
                    raise SchemaError(f"Sketch '{fid}' primitive[{p_i}] unknown type '{ptype}'")
                pspec = SKETCH_PRIMITIVE_TYPES[ptype]
                params = prim.get("parameters", {})
                for req in pspec["required"]:
                    if req not in params:
                        raise SchemaError(
                            f"Sketch '{fid}' primitive[{p_i}] ({ptype}) missing '{req}'"
                        )

        if ftype in ("Fillet", "Chamfer"):
            sel = feat["selector"]
            if sel.get("of") not in ("edges", "faces"):
                raise SchemaError(f"{ftype} '{fid}' selector.of must be 'edges' or 'faces'")
            if sel.get("criterion") not in SELECTOR_CRITERIA:
                raise SchemaError(f"{ftype} '{fid}' selector.criterion invalid")

        op = feat.get("operation")
        if op is not None and op not in BOOLEAN_OPS:
            raise SchemaError(f"feature '{fid}' has invalid operation '{op}'")
