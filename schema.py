from __future__ import annotations
import difflib
from typing import Any


SKETCH_PRIMITIVE_TYPES = {
    "Rectangle": {"required": ["width", "height"], "optional": ["position", "rotation", "mode"]},
    "Circle": {"required": ["radius"], "optional": ["position", "mode"]},
    "Polygon": {"required": ["points"], "optional": ["position", "rotation", "mode"]},
    "Slot": {"required": ["width", "height"], "optional": ["position", "rotation", "mode"]},
    "Line": {"required": ["points"], "optional": []},
    "Spline": {"required": ["points"], "optional": []},
    "Polyline": {"required": ["points"], "optional": []},
}

WIRE_PRIMITIVE_TYPES = {"Line", "Spline", "Polyline"}

FEATURE_TYPES = {
    "Sketch": {"required": ["primitives"], "optional": ["plane"]},
    "Extrude": {"required": ["source", "amount"], "optional": ["both", "taper", "operation"]},
    "Revolve": {"required": ["source"], "optional": ["axis", "angle", "operation"]},
    "Loft": {"required": ["sources"], "optional": ["ruled", "operation"]},
    "Sweep": {"required": ["profile", "path"], "optional": ["is_frenet", "operation"]},
    "Fillet": {"required": ["selector", "radius"], "optional": ["target"]},
    "Chamfer": {"required": ["selector", "length"], "optional": ["target", "length2", "angle"]},
    "Shell": {"required": ["thickness"], "optional": ["target", "open_selector"]},
    "Hole": {"required": ["style", "radius", "depth", "location"],
             "optional": ["target", "cb_radius", "cb_depth", "cs_angle"]},
    "Mirror": {"required": ["plane"], "optional": ["target", "operation"]},
    "LinearPattern": {"required": ["direction", "count", "spacing"], "optional": ["target", "operation"]},
    "CircularPattern": {"required": ["axis", "count", "angle"], "optional": ["target", "operation"]},
}

SOLID_PRODUCING = {
    "Extrude", "Revolve", "Loft", "Sweep", "Mirror", "LinearPattern", "CircularPattern",
}
SOLID_MODIFYING = {"Fillet", "Chamfer", "Shell", "Hole"}

BOOLEAN_OPS = {"ADD", "SUBTRACT", "INTERSECT", "CUT"}
SKETCH_MODES = {"ADD", "SUBTRACT", "INTERSECT", "CUT"}
SELECTOR_AXES = {"X", "Y", "Z"}
SELECTOR_CRITERIA = {"max", "min", "all"}
SELECTOR_FILTER_KINDS = {"GeomType", "near_point"}

# Always allowed on every feature regardless of type, alongside each
# type's own required/optional fields (see the unknown-field check in
# validate_ir()).
_ALWAYS_ALLOWED_FEATURE_KEYS = {"id", "feature_type"}


class SchemaError(ValueError):
    pass


class BoundsError(ValueError):
    pass


BOUNDS = {
    "max_features": 60,
    "max_primitives_per_sketch": 20,
    "max_polygon_points": 200,
    "max_loft_sources": 8,
    "max_pattern_count": 50,
    "min_dimension_mm": 1e-3,
    "max_dimension_mm": 10_000.0,
    "max_fillet_or_chamfer_mm": 500.0,
    "max_revolve_angle_deg": 360.0 * 10,
    "max_near_point_tolerance_mm": 50.0,
}


def _check_dim(value, name: str, violations: list[str], max_override: float | None = None):
    lo = BOUNDS["min_dimension_mm"]
    hi = max_override if max_override is not None else BOUNDS["max_dimension_mm"]
    if not isinstance(value, (int, float)):
        return
    if value != value:
        violations.append(f"{name} is NaN")
    elif value < lo or value > hi:
        violations.append(f"{name}={value} out of bounds [{lo}, {hi}]")


def validate_bounds(ir: dict) -> list[str]:
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
            sel = feat.get("selector", {})
            if sel.get("filter_by") == "near_point":
                tol = sel.get("tolerance", 1e-3)
                if isinstance(tol, (int, float)) and tol > BOUNDS["max_near_point_tolerance_mm"]:
                    violations.append(
                        f"'{fid}'.selector.tolerance={tol} exceeds max "
                        f"{BOUNDS['max_near_point_tolerance_mm']} (too loose to isolate an edge)"
                    )

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


def _check_unknown_fields(feat: dict, fid: str, ftype: str, spec: dict) -> None:
    """Rejects any top-level feature key that isn't 'id'/'feature_type' or
    one of this feature type's own required/optional fields -- e.g. a
    Shell with 'selector' instead of 'open_selector'. Before this check,
    an unrecognized key was simply never read by compiler.py (Python
    dicts silently ignore extra keys), so a wrong-but-plausible field
    name compiled to valid, non-degenerate geometry with no error and no
    repair-loop signal at all -- the mistake was invisible until a human
    noticed the rendered part didn't look right. Runs a close-match
    suggestion (via difflib) against this type's actual field names so
    the resulting SchemaError message doubles as a usable repair-turn
    hint, not just a bare rejection."""
    allowed = _ALWAYS_ALLOWED_FEATURE_KEYS | set(spec["required"]) | set(spec["optional"])
    unknown = set(feat.keys()) - allowed
    if not unknown:
        return
    candidates = sorted(allowed - _ALWAYS_ALLOWED_FEATURE_KEYS)
    parts = []
    for key in sorted(unknown):
        suggestion = difflib.get_close_matches(key, candidates, n=1, cutoff=0.6)
        if suggestion:
            parts.append(f"'{key}' (did you mean '{suggestion[0]}'?)")
        else:
            parts.append(f"'{key}'")
    raise SchemaError(
        f"feature '{fid}' ({ftype}) has unrecognized field(s): {', '.join(parts)}"
    )


def _validate_selector_shape(sel, label: str) -> None:
    """Validates one selector dict's shape -- shared by Fillet/Chamfer's
    required 'selector' field AND Shell's optional 'open_selector' field,
    since both use the identical {of, filter_by, criterion} (or
    near_point / GeomType variant) shape. `label` is a human-readable
    prefix for error messages, e.g. "Fillet 'fillet_1' selector" or
    "Shell 'shell_1' open_selector".

    Before this helper existed, two related gaps were both live at once:
    Shell's open_selector had NO shape validation anywhere (only its
    presence as a recognized key was checked), and even Fillet/Chamfer's
    selector validation assumed `sel` was already a dict and called
    `sel.get(...)` immediately -- a non-dict selector (e.g. a bare list)
    raised a raw AttributeError instead of a clean SchemaError, and for
    Shell specifically that AttributeError never even fired here; it
    surfaced three layers down as compiler.py's `selector["of"]`
    TypeError once _resolve_selector actually ran. The isinstance check
    below is what turns both of those into one clear, actionable error at
    validation time instead of a raw Python exception at compile time."""
    if not isinstance(sel, dict):
        raise SchemaError(
            f"{label} must be an object with 'of'/'filter_by'/'criterion' fields, "
            f"got {type(sel).__name__}: {sel!r}"
        )
    if sel.get("of") not in ("edges", "faces"):
        raise SchemaError(f"{label}.of must be 'edges' or 'faces'")

    filter_by = sel.get("filter_by")
    if filter_by == "near_point":
        point = sel.get("point")
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            raise SchemaError(
                f"{label}.filter_by=near_point requires a 3-element "
                f"'point' [x, y, z] (any coordinate may be null to leave it unconstrained)"
            )
        for coord in point:
            if coord is not None and not isinstance(coord, (int, float)):
                raise SchemaError(f"{label}.point coordinates must be numbers or null")
        if all(c is None for c in point):
            raise SchemaError(
                f"{label}.point cannot have every coordinate null -- that matches "
                f"every edge, same as filter_by=all"
            )
        tolerance = sel.get("tolerance", 1e-3)
        if not isinstance(tolerance, (int, float)) or tolerance <= 0:
            raise SchemaError(f"{label}.tolerance must be a positive number")
    elif filter_by == "GeomType":
        if "geom_type" not in sel:
            raise SchemaError(f"{label}.filter_by=GeomType requires 'geom_type'")
    elif filter_by in SELECTOR_AXES or filter_by in (None, "all"):
        if sel.get("criterion") not in SELECTOR_CRITERIA:
            raise SchemaError(f"{label}.criterion invalid")
    else:
        raise SchemaError(
            f"{label}.filter_by unrecognized: {filter_by!r} "
            f"(expected an axis {sorted(SELECTOR_AXES)}, {sorted(SELECTOR_FILTER_KINDS)}, "
            f"'all', or null)"
        )


def validate_ir(ir: dict) -> None:
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

        _check_unknown_fields(feat, fid, ftype, spec)

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
            _validate_selector_shape(feat["selector"], f"{ftype} '{fid}' selector")

        if ftype == "Shell" and "open_selector" in feat:
            _validate_selector_shape(feat["open_selector"], f"Shell '{fid}' open_selector")

        op = feat.get("operation")
        if op is not None and op not in BOOLEAN_OPS:
            raise SchemaError(f"feature '{fid}' has invalid operation '{op}'")
