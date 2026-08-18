"""
stub_build123d/build123d.py
A fake, minimal stand-in for the real `build123d` package, used ONLY to
smoke-test compiler.py / executor.py plumbing (subprocess round-trip,
exception propagation, dispatch coverage of every feature type) in an
environment with no network access to actually pip install build123d.

THIS DOES NO REAL GEOMETRY. Volumes/areas are fabricated from bounding
dimensions with simple formulas so validator.py's sanity checks pass on
"reasonable" input and fail on deliberately-degenerate input (zero/negative
dims), which is enough to test the CompileError / ValidationError paths
without an OCCT kernel.

Do NOT use this to judge whether the real build123d API calls in
compiler.py are syntactically/semantically correct -- only a real install
can tell you that. See README.md.
"""

from __future__ import annotations
import math


class FakeBuildError(Exception):
    pass


class Align:
    CENTER = "CENTER"
    MIN = "MIN"
    MAX = "MAX"


class GeomType:
    CIRCLE = "CIRCLE"
    LINE = "LINE"


class Kind:
    ARC = "ARC"
    INTERSECTION = "INTERSECTION"
    TANGENT = "TANGENT"


class _Vec:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X, self.Y, self.Z = x, y, z

    def __iter__(self):
        return iter((self.X, self.Y, self.Z))

    def __add__(self, o):
        return _Vec(self.X + o.X, self.Y + o.Y, self.Z + o.Z)


class _Location:
    def __init__(self, pos=(0, 0, 0), rot_deg=(0, 0, 0)):
        self.pos = tuple(pos)
        self.rot_deg = tuple(rot_deg)

    def __mul__(self, other):
        if isinstance(other, _Location):
            px, py, pz = self.pos
            ox, oy, oz = other.pos
            return _Location((px + ox, py + oy, pz + oz),
                              tuple(a + b for a, b in zip(self.rot_deg, other.rot_deg)))
        if isinstance(other, (_Shape2D, _Shape3D)):
            other = other.copy()
            other.loc = self * other.loc
            return other
        raise FakeBuildError(f"cannot compose Location with {type(other)}")


class Pos(_Location):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        super().__init__((x, y, z))


class Rot(_Location):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        super().__init__((0, 0, 0), (x, y, z))


class Rotation(_Location):
    def __init__(self, axis, angle):
        super().__init__((0, 0, 0), (0, 0, angle))


class Axis:
    X = "X"
    Y = "Y"
    Z = "Z"

    def __init__(self, origin=(0, 0, 0), direction=(0, 0, 1)):
        self.origin, self.direction = origin, direction


class Plane:
    XY = None  # set below
    YZ = None
    XZ = None

    def __init__(self, origin=(0, 0, 0), z_dir=(0, 0, 1)):
        self.origin = origin
        self.z_dir = z_dir

    @property
    def location(self):
        return _Location(self.origin)

    def __mul__(self, other):
        return self.location * other


Plane.XY = Plane((0, 0, 0), (0, 0, 1))
Plane.YZ = Plane((0, 0, 0), (1, 0, 0))
Plane.XZ = Plane((0, 0, 0), (0, 1, 0))


class _ShapeList(list):
    def group_by(self, axis):
        if not self:
            raise FakeBuildError("group_by on empty ShapeList")
        buckets: dict[float, list] = {}
        for e in self:
            key = round(e.pos_along(axis), 3)
            buckets.setdefault(key, []).append(e)
        ordered = [buckets[k] for k in sorted(buckets)]
        return [_ShapeList(g) for g in ordered]

    def filter_by(self, geom_type):
        return _ShapeList([e for e in self if getattr(e, "geom_type", None) == geom_type])


class _Edge:
    def __init__(self, z=0.0, length=10.0, geom_type=GeomType.LINE):
        self.z, self.length, self.geom_type = z, length, geom_type

    def pos_along(self, axis):
        return self.z if axis == "Z" else 0.0


class _Face:
    def __init__(self, z=0.0):
        self.z = z

    def pos_along(self, axis):
        return self.z if axis == "Z" else 0.0


class _Shape2D:
    """Fake Sketch. Tracks a bounding footprint only."""

    def __init__(self, w=1.0, h=1.0):
        if w <= 0 or h <= 0:
            raise FakeBuildError(f"non-positive sketch dimension w={w} h={h}")
        self.w, self.h = w, h
        self.loc = _Location()

    def copy(self):
        c = _Shape2D(self.w, self.h)
        c.loc = self.loc
        return c

    def __add__(self, other):
        return _Shape2D(max(self.w, other.w), max(self.h, other.h))

    def __sub__(self, other):
        return self  # fake: subtraction doesn't shrink footprint

    def __and__(self, other):
        return _Shape2D(min(self.w, other.w), min(self.h, other.h))


class _Shape3D:
    """Fake Part/Solid. Volume is a plausible fabricated number so
    validator.py's sanity checks exercise their real logic paths."""

    def __init__(self, w=1.0, h=1.0, t=1.0, n_edges=12, n_faces=6, fillets=0):
        if w <= 0 or h <= 0 or t <= 0:
            raise FakeBuildError(f"non-positive solid dimension w={w} h={h} t={t}")
        self.w, self.h, self.t = w, h, t
        self.loc = _Location()
        self._n_edges, self._n_faces = n_edges, n_faces
        self._fillets = fillets

    def copy(self):
        c = _Shape3D(self.w, self.h, self.t, self._n_edges, self._n_faces, self._fillets)
        c.loc = self.loc
        return c

    # -- boolean ops (fake: just track a scaling factor) --
    def __add__(self, other):
        return _Shape3D(self.w, self.h, self.t + getattr(other, "t", 0) * 0.1,
                         self._n_edges + 4, self._n_faces + 2, self._fillets)

    def __sub__(self, other):
        vol_frac = 0.85
        return _Shape3D(self.w, self.h, self.t * vol_frac, self._n_edges + 4,
                         self._n_faces + 2, self._fillets)

    def __and__(self, other):
        return _Shape3D(min(self.w, other.w), min(self.h, other.h),
                         min(self.t, other.t), self._n_edges, self._n_faces, self._fillets)

    def is_valid(self):
        return self.w > 0 and self.h > 0 and self.t > 0

    @property
    def volume(self):
        return self.w * self.h * self.t

    @property
    def area(self):
        return 2 * (self.w * self.h + self.w * self.t + self.h * self.t)

    def solids(self):
        return _ShapeList([self])

    def faces(self):
        return _ShapeList([_Face(z=0.0), _Face(z=self.t)])

    def edges(self):
        if self._fillets >= self._n_edges:
            return _ShapeList([])  # simulate "no edges left to fillet"
        return _ShapeList([_Edge(z=0.0, length=self.w) for _ in range(2)] +
                           [_Edge(z=self.t, length=self.w) for _ in range(2)])

    def bounding_box(self):
        class BB:
            pass
        bb = BB()
        bb.min = _Vec(-self.w / 2, -self.h / 2, 0)
        bb.max = _Vec(self.w / 2, self.h / 2, self.t)
        return bb

    def center(self):
        return _Vec(0, 0, self.t / 2)


# -- sketch primitive constructors --
def Rectangle(width, height, **kw):
    return _Shape2D(width, height)


def Circle(radius, **kw):
    if radius <= 0:
        raise FakeBuildError(f"non-positive circle radius {radius}")
    return _Shape2D(radius * 2, radius * 2)


def Polygon(*pts, **kw):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return _Shape2D(max(xs) - min(xs) or 1, max(ys) - min(ys) or 1)


def SlotOverall(width, height, **kw):
    return _Shape2D(width, height)


def Line(*pts, **kw):
    return _Shape2D(10, 10)


def Polyline(*pts, **kw):
    return _Shape2D(10, 10)


def Spline(*pts, **kw):
    return _Shape2D(10, 10)


def Cylinder(radius, height, **kw):
    if radius <= 0 or height <= 0:
        raise FakeBuildError(f"non-positive cylinder dims r={radius} h={height}")
    return _Shape3D(radius * 2, radius * 2, height)


def Cone(r1, r2, height, **kw):
    if height <= 0:
        raise FakeBuildError(f"non-positive cone height {height}")
    return _Shape3D(r1 * 2, r1 * 2, height)


# -- operation free functions --
def extrude(sketch, amount, both=False, taper=0.0, **kw):
    if amount <= 0:
        raise FakeBuildError(f"non-positive extrude amount {amount}")
    return _Shape3D(sketch.w, sketch.h, amount * (2 if both else 1))


def revolve(sketch, axis, revolution_arc=360, **kw):
    if revolution_arc <= 0:
        raise FakeBuildError("non-positive revolution_arc")
    return _Shape3D(sketch.w * 2, sketch.w * 2, sketch.h)


def loft(sections, ruled=False, **kw):
    if len(sections) < 2:
        raise FakeBuildError("loft needs >=2 sections")
    ws = [s.w for s in sections]
    hs = [s.h for s in sections]
    return _Shape3D(max(ws), max(hs), 10)


def sweep(sections, path, is_frenet=False, **kw):
    return _Shape3D(sections.w, sections.h, 50)


def mirror(part, about, **kw):
    return part.copy()


def fillet(edges, radius):
    if radius <= 0:
        raise FakeBuildError(f"non-positive fillet radius {radius}")
    if not edges:
        raise FakeBuildError("no fillets could be built: empty edge selection")
    base = edges[0]
    parent_hint = getattr(edges, "_parent", None)
    # crude "too large" check: reject if radius > 40% of the shortest edge length
    shortest = min(e.length for e in edges)
    if radius > shortest * 0.4:
        raise FakeBuildError(
            f"BRepFilletAPI_MakeFillet: no fillets could be built (radius {radius} "
            f"too large for edge length {shortest})"
        )
    return _Shape3D(10, 10, 10, fillets=1)


def chamfer(edges, length, length2=None, angle=None):
    if length <= 0:
        raise FakeBuildError(f"non-positive chamfer length {length}")
    if not edges:
        raise FakeBuildError("no chamfers could be built: empty edge selection")
    shortest = min(e.length for e in edges)
    if length > shortest * 0.4:
        raise FakeBuildError(
            f"BRepFilletAPI_MakeChamfer: no chamfers could be built (length {length} "
            f"too large for edge length {shortest})"
        )
    return _Shape3D(10, 10, 10, fillets=1)


def offset(part, amount, openings=None, **kw):
    if amount >= 0:
        raise FakeBuildError("shell offset amount must be negative (material removal)")
    if abs(amount) >= min(part.w, part.h, part.t) / 2:
        raise FakeBuildError(
            f"BRepOffsetAPI_MakeThickSolid: offset {amount} too large for wall of "
            f"thickness {min(part.w, part.h, part.t)}"
        )
    return part.copy()


# -- fake exporters, for smoke-testing service/app/worker_pool.py's export
# path only. Write a tiny placeholder payload, NOT real STEP/STL/glTF --
# never use these bytes as evidence the real build123d exporters work. --
def export_step(shape, path, **kw):
    with open(path, "w") as f:
        f.write(f"ISO-10303-21;\nFAKE STEP for stub testing, volume={shape.volume}\nENDSEC;\n")
    return True


def export_stl(shape, path, **kw):
    with open(path, "w") as f:
        f.write(f"solid fake\nendsolid fake\n")
    return True


def export_gltf(shape, path, binary=True, **kw):
    with open(path, "wb" if binary else "w") as f:
        payload = b"glTF-fake-binary-payload" if binary else "fake-gltf-json"
        f.write(payload if binary else payload)
    return True
