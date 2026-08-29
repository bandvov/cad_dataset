"""
compiler.py
Direct interpreter for the JSON IR feature tree: walks ir["features"] in
order and executes each one directly against the build123d API, building
up a running `Part` solid. This is NOT a code generator -- there is no
intermediate Python-source string. The IR is the only source of truth,
and this module is the only thing that knows how to turn it into geometry.

NOTE ON VERIFICATION: this was written against the documented build123d
algebra API (Plane/Pos/Rot composition, Sketch/Part boolean operators,
extrude/revolve/loft/sweep/fillet/chamfer/offset free functions). It has
NOT been executed against a real build123d install in this sandbox (no
network access here to pip install it). Before trusting generated data,
run this against your local build123d install and fix any API drift --
see README.md "Verification" section for the smoke test to run first.
"""

from __future__ import annotations
from typing import Any


class CompileError(Exception):
    """Raised for any failure while interpreting the IR: unknown ids,
    unsupported feature types, or the underlying build123d call itself
    raising (degenerate geometry, invalid boolean, etc). The message is
    kept close to the underlying exception text on purpose -- repair-task
    data depends on realistic error strings.
    """


class IRCompiler:
    """One instance per compile() call. Not reused across IRs."""

    def __init__(self):
        import build123d as bd  # imported lazily so this module can be
        self.bd = bd            # imported even where build123d isn't installed
        self.registry: dict[str, Any] = {}   # feature id -> compiled object
        self.current_part: Any = None        # running Part (bd.Part / bd.Solid)

    # ------------------------------------------------------------------ #
    # public entry point
    # ------------------------------------------------------------------ #
    def compile(self, ir: dict) -> Any:
        from schema import validate_ir, validate_bounds, BoundsError
        validate_ir(ir)
        violations = validate_bounds(ir)
        if violations:
            raise BoundsError("; ".join(violations))

        dispatch = {
            "Sketch": self._do_sketch,
            "Extrude": self._do_extrude,
            "Revolve": self._do_revolve,
            "Loft": self._do_loft,
            "Sweep": self._do_sweep,
            "Fillet": self._do_fillet,
            "Chamfer": self._do_chamfer,
            "Shell": self._do_shell,
            "Hole": self._do_hole,
            "Mirror": self._do_mirror,
            "LinearPattern": self._do_linear_pattern,
            "CircularPattern": self._do_circular_pattern,
        }

        for feat in ir["features"]:
            fid, ftype = feat["id"], feat["feature_type"]
            handler = dispatch.get(ftype)
            if handler is None:
                raise CompileError(f"no interpreter for feature_type '{ftype}'")
            try:
                result = handler(feat)
            except CompileError:
                raise
            except Exception as e:  # noqa: BLE001 - deliberately broad, re-raised typed
                raise CompileError(
                    f"feature '{fid}' ({ftype}) failed: {type(e).__name__}: {e}"
                ) from e
            self.registry[fid] = result

        if self.current_part is None:
            raise CompileError("IR produced no solid geometry (no ADD-ing feature ran)")
        return self.current_part

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _plane(self, plane_spec: dict | None):
        bd = self.bd
        if not plane_spec:
            return bd.Plane.XY
        if not isinstance(plane_spec, dict):
            raise CompileError(
                f"'plane' must be an object with 'origin'/'normal', "
                f"got {type(plane_spec).__name__}: {plane_spec!r}"
            )
        origin = tuple(plane_spec.get("origin", (0, 0, 0)))
        normal = tuple(plane_spec.get("normal", (0, 0, 1)))
        return bd.Plane(origin=origin, z_dir=normal)

    def _place(self, shape, plane_spec: dict | None, position, rotation_deg: float):
        """Locate a 2D primitive: plane origin/normal, then local xy offset,
        then rotation about the local Z axis. Follows build123d's documented
        composition pattern: Plane * Pos(...) * Rot(...) * shape."""
        bd = self.bd
        plane = self._plane(plane_spec)
        x, y = (position or [0, 0])[:2]
        return plane * bd.Pos(x, y, 0) * bd.Rot(0, 0, rotation_deg or 0) * shape

    def _combine(self, new_solid, operation: str | None):
        """Fold a new solid into self.current_part per the boolean op."""
        op = operation or "ADD"
        if op not in ("ADD", "SUBTRACT", "INTERSECT"):
            raise CompileError(f"invalid operation '{op}'")
        if self.current_part is None:
            if op != "ADD":
                raise CompileError(
                    f"first solid-producing feature must use ADD, got '{op}'"
                )
            self.current_part = new_solid
        elif op == "ADD":
            self.current_part = self.current_part + new_solid
        elif op == "SUBTRACT":
            self.current_part = self.current_part - new_solid
        else:
            self.current_part = self.current_part & new_solid
        return self.current_part

    def _resolve_target(self, feat: dict):
        """Fillet/Chamfer/Shell/Hole/Mirror/Pattern operate on an explicit
        'target' feature id if given, else on the current running part."""
        target_id = feat.get("target")
        if target_id is None:
            if self.current_part is None:
                raise CompileError("no target specified and no current part exists yet")
            return self.current_part
        if target_id not in self.registry:
            raise CompileError(f"unknown target id '{target_id}'")
        return self.registry[target_id]

    # ------------------------------------------------------------------ #
    # sketch primitives
    # ------------------------------------------------------------------ #
    def _build_primitive(self, prim: dict, plane_spec: dict | None):
        bd = self.bd
        ptype = prim["type"]
        params = prim.get("parameters", {})
        mode = params.get("mode", "ADD")
        position = params.get("position", [0, 0])
        rotation = params.get("rotation", 0)

        if ptype == "Rectangle":
            shape = bd.Rectangle(params["width"], params["height"])
        elif ptype == "Circle":
            shape = bd.Circle(params["radius"])
        elif ptype == "Polygon":
            pts = [tuple(p) for p in params["points"]]
            shape = bd.Polygon(*pts)
        elif ptype == "Slot":
            shape = bd.SlotOverall(params["width"], params["height"])
        elif ptype in ("Line", "Polyline"):
            pts = [tuple(p) for p in params["points"]]
            shape = bd.Polyline(*pts) if ptype == "Polyline" else bd.Line(*pts[:2])
        elif ptype == "Spline":
            pts = [tuple(p) for p in params["points"]]
            shape = bd.Spline(*pts)
        else:
            raise CompileError(f"unsupported primitive type '{ptype}'")

        placed = self._place(shape, plane_spec, position, rotation)
        return placed, mode

    def _do_sketch(self, feat: dict):
        from schema import WIRE_PRIMITIVE_TYPES
        plane_spec = feat.get("plane")
        primitives = feat["primitives"]

        wire_types = {p["type"] for p in primitives} & WIRE_PRIMITIVE_TYPES
        if wire_types:
            # open-wire "sketch" used as a sweep path / construction line;
            # only a single wire primitive is meaningful here
            if len(primitives) != 1:
                raise CompileError("wire-type Sketch must contain exactly one primitive")
            shape, _mode = self._build_primitive(primitives[0], plane_spec)
            return shape  # a Wire/Edge, not a Sketch region

        sketch = None
        for prim in primitives:
            shape, mode = self._build_primitive(prim, plane_spec)
            if sketch is None:
                if mode != "ADD":
                    raise CompileError("first sketch primitive must use mode ADD")
                sketch = shape
            elif mode == "ADD":
                sketch = sketch + shape
            elif mode == "SUBTRACT":
                sketch = sketch - shape
            elif mode == "INTERSECT":
                sketch = sketch & shape
            else:
                raise CompileError(f"invalid sketch primitive mode '{mode}'")
        return sketch

    # ------------------------------------------------------------------ #
    # solid-producing features
    # ------------------------------------------------------------------ #
    def _do_extrude(self, feat: dict):
        bd = self.bd
        sketch = self.registry[feat["source"]]
        kwargs = {"amount": feat["amount"]}
        if feat.get("both"):
            kwargs["both"] = True
        if feat.get("taper"):
            kwargs["taper"] = feat["taper"]
        solid = bd.extrude(sketch, **kwargs)
        return self._combine(solid, feat.get("operation"))

    def _do_revolve(self, feat: dict):
        bd = self.bd
        sketch = self.registry[feat["source"]]
        axis_spec = feat.get("axis", {"origin": [0, 0, 0], "direction": [0, 1, 0]})
        axis = bd.Axis(tuple(axis_spec.get("origin", (0, 0, 0))),
                        tuple(axis_spec.get("direction", (0, 1, 0))))
        angle = feat.get("angle", 360)
        solid = bd.revolve(sketch, axis=axis, revolution_arc=angle)
        return self._combine(solid, feat.get("operation"))

    def _do_loft(self, feat: dict):
        bd = self.bd
        sections = [self.registry[sid] for sid in feat["sources"]]
        if len(sections) < 2:
            raise CompileError("Loft requires at least 2 source sketches")
        solid = bd.loft(sections, ruled=feat.get("ruled", False))
        return self._combine(solid, feat.get("operation"))

    def _do_sweep(self, feat: dict):
        bd = self.bd
        profile = self.registry[feat["profile"]]
        path = self.registry[feat["path"]]
        solid = bd.sweep(sections=profile, path=path, is_frenet=feat.get("is_frenet", False))
        return self._combine(solid, feat.get("operation"))

    def _do_mirror(self, feat: dict):
        bd = self.bd
        target = self._resolve_target(feat)
        plane_name = feat["plane"]
        plane = {"XY": bd.Plane.XY, "YZ": bd.Plane.YZ, "XZ": bd.Plane.XZ}.get(plane_name)
        if plane is None:
            raise CompileError(f"unknown mirror plane '{plane_name}'")
        mirrored = bd.mirror(target, about=plane)
        return self._combine(mirrored, feat.get("operation", "ADD"))

    def _do_linear_pattern(self, feat: dict):
        bd = self.bd
        target = self._resolve_target(feat)
        dx, dy, dz = feat["direction"]
        count = feat["count"]
        spacing = feat["spacing"]
        copies = target
        for i in range(1, count):
            offset = bd.Pos(dx * spacing * i, dy * spacing * i, dz * spacing * i)
            copies = copies + (offset * target)
        return self._merge_pattern(target, copies, feat)

    def _merge_pattern(self, target, pattern_result, feat):
        # pattern_result already includes one copy of target at the origin
        # position; since `target` (when it's the current part) is already
        # unioned into self.current_part, only fold in the *additional*
        # copies to avoid double-unioning the base instance.
        extra = pattern_result - target
        return self._combine(extra, feat.get("operation", "ADD"))

    def _rotate_copy(self, shape, origin, direction, angle_deg):
        """Returns a rotated COPY of `shape` about the given world axis,
        without mutating `shape`. For the common case of an axis parallel
        to Z (which is all our generators ever produce), this is done via
        pure Pos/Rot composition -- translate the axis to the origin,
        rotate about local Z, translate back -- since that only relies on
        Pos/Rot semantics that are unambiguously documented, rather than a
        Rotation(axis=..., angle=...) call that isn't a real signature.
        For a tilted axis, falls back to Shape.rotate(Axis, angle), which
        build123d does document as a direct-manipulation method."""
        bd = self.bd
        ox, oy, oz = origin
        dx, dy, dz = direction
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return bd.Pos(ox, oy, oz) * bd.Rot(0, 0, angle_deg) * bd.Pos(-ox, -oy, -oz) * shape
        axis = bd.Axis(origin, direction)
        return shape.rotate(axis, angle_deg)

    def _do_circular_pattern(self, feat: dict):
        target = self._resolve_target(feat)
        axis_spec = feat["axis"]
        origin = tuple(axis_spec.get("origin", (0, 0, 0)))
        direction = tuple(axis_spec.get("direction", (0, 0, 1)))
        count = feat["count"]
        total_angle = feat.get("angle", 360)
        step = total_angle / count
        copies = target
        for i in range(1, count):
            copies = copies + self._rotate_copy(target, origin, direction, step * i)
        return self._merge_pattern(target, copies, feat)

    # ------------------------------------------------------------------ #
    # solid-modifying features (selectors)
    # ------------------------------------------------------------------ #
    def _resolve_selector(self, shape, selector: dict):
        bd = self.bd
        of = selector["of"]
        entities = shape.edges() if of == "edges" else shape.faces()

        filter_by = selector.get("filter_by")
        criterion = selector.get("criterion", "all")

        if filter_by in ("X", "Y", "Z"):
            axis = getattr(bd.Axis, filter_by)
            groups = entities.group_by(axis)
            if criterion == "max":
                chosen = groups[-1]
            elif criterion == "min":
                chosen = groups[0]
            else:
                chosen = entities
        elif filter_by == "GeomType":
            geom_type = getattr(bd.GeomType, selector["geom_type"])
            chosen = entities.filter_by(geom_type)
        elif filter_by is None or filter_by == "all":
            chosen = entities
        else:
            raise CompileError(f"unsupported selector.filter_by '{filter_by}'")

        if not chosen:
            raise CompileError(
                f"selector matched zero {of} (filter_by={filter_by}, criterion={criterion})"
            )
        return chosen

    def _do_fillet(self, feat: dict):
        bd = self.bd
        target = self._resolve_target(feat)
        entities = self._resolve_selector(target, feat["selector"])
        result = bd.fillet(entities, radius=feat["radius"])
        self.current_part = result
        return result

    def _do_chamfer(self, feat: dict):
        bd = self.bd
        target = self._resolve_target(feat)
        entities = self._resolve_selector(target, feat["selector"])
        kwargs = {"length": feat["length"]}
        if "length2" in feat:
            kwargs["length2"] = feat["length2"]
        if "angle" in feat:
            kwargs["angle"] = feat["angle"]
        result = bd.chamfer(entities, **kwargs)
        self.current_part = result
        return result

    def _do_shell(self, feat: dict):
        bd = self.bd
        target = self._resolve_target(feat)
        openings = None
        if "open_selector" in feat:
            openings = self._resolve_selector(target, feat["open_selector"])
        amount = -abs(feat["thickness"])
        try:
            result = bd.offset(target, amount=amount, openings=openings)
        except Exception:
            # default Kind.ARC can fail on sharp rectilinear corners;
            # Kind.INTERSECTION (square corners) is the documented fallback
            result = bd.offset(target, amount=amount, openings=openings, kind=bd.Kind.INTERSECTION)
        self.current_part = result
        return result

    def _do_hole(self, feat: dict):
        """Holes are implemented as boolean subtraction of a positioned
        cylinder (simple) or compound cylinder+cone (counterbore /
        countersink) rather than build123d's context-manager Hole classes,
        since those are designed for the builder API's implicit Locations
        context rather than direct interpretation of a standalone IR."""
        bd = self.bd
        target = self._resolve_target(feat)
        loc = feat["location"]
        origin = tuple(loc.get("position", (0, 0, 0)))
        normal = tuple(loc.get("normal", (0, 0, -1)))
        plane = bd.Plane(origin=origin, z_dir=normal)

        style = feat["style"]
        radius = feat["radius"]
        depth = feat["depth"]
        align = (bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)
        cutter = plane * bd.Cylinder(radius, depth, align=align)

        if style == "counterbore":
            cb_r, cb_d = feat["cb_radius"], feat["cb_depth"]
            cb = plane * bd.Cylinder(cb_r, cb_d, align=align)
            cutter = cutter + cb
        elif style == "countersink":
            import math
            cs_angle = feat.get("cs_angle", 90)
            cs_r = radius + depth * math.tan(math.radians(cs_angle / 2))
            cs = plane * bd.Cone(cs_r, radius, depth, align=align)
            cutter = cutter + cs
        elif style != "simple":
            raise CompileError(f"unsupported hole style '{style}'")

        result = target - cutter
        self.current_part = result
        return result


def compile_ir(ir: dict):
    """Convenience wrapper: one-shot compile."""
    return IRCompiler().compile(ir)
