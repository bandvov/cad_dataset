"""
validator.py
Given a compiled build123d Part/Shape (already built, in-process), verify it
is a sane single solid and extract stats used for (a) filtering the dataset
and (b) auxiliary metadata stored alongside each record.

Kept separate from executor.py so it can also be called directly by anyone
poking at a shape interactively, not just from the subprocess worker.
"""

from __future__ import annotations
from typing import Any


class ValidationError(Exception):
    pass


def validate_shape(part) -> dict[str, Any]:
    is_valid_attr = getattr(part, "is_valid", None)
    if is_valid_attr is not None:
        is_valid_result = is_valid_attr() if callable(is_valid_attr) else is_valid_attr
        if not is_valid_result:
            raise ValidationError("shape reports invalid topology (is_valid)")

    volume = float(part.volume)
    if volume <= 1e-9:
        raise ValidationError(f"non-positive/degenerate volume ({volume})")

    solids = part.solids()
    n_solids = len(solids)
    if n_solids == 0:
        raise ValidationError("result contains zero solids")
    if n_solids > 1:
        # not necessarily wrong (some real parts are legitimately multi-body)
        # but flagged distinctly so the dataset builder can choose to keep
        # or drop these depending on the target task distribution
        pass

    bbox = part.bounding_box()
    bbox_size = (
        bbox.max.X - bbox.min.X,
        bbox.max.Y - bbox.min.Y,
        bbox.max.Z - bbox.min.Z,
    )
    if min(bbox_size) <= 1e-6:
        raise ValidationError(f"degenerate bounding box {bbox_size}")

    faces = part.faces()
    edges = part.edges()

    return {
        "volume": volume,
        "area": float(part.area) if hasattr(part, "area") else None,
        "n_solids": n_solids,
        "n_faces": len(faces),
        "n_edges": len(edges),
        "bbox_min": [bbox.min.X, bbox.min.Y, bbox.min.Z],
        "bbox_max": [bbox.max.X, bbox.max.Y, bbox.max.Z],
        "center_of_mass": list(part.center()) if hasattr(part, "center") else None,
    }
