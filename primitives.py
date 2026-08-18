"""
primitives.py
Shared building blocks used by every gen_*.py script: parameter samplers,
id generation, and geometry-safe ranges that keep procedurally generated
IR from being degenerate by construction (rather than relying purely on
rejection sampling after the fact -- that keeps executor calls, which are
the expensive part of the pipeline, focused on real edge cases).

Nothing in here imports build123d, so the generator scripts are runnable
and unit-testable without a build123d install.
"""

from __future__ import annotations
import random
import itertools
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# id bookkeeping
# ---------------------------------------------------------------------------
class IdGen:
    """Deterministic, readable ids per compiled IR: sketch_1, extrude_1, ..."""

    def __init__(self):
        self._counters: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}_{self._counters[prefix]}"


# ---------------------------------------------------------------------------
# geometry-safe parameter ranges (mm)
# ---------------------------------------------------------------------------
RANGES = {
    "small_dim": (10, 60),      # small feature footprint
    "med_dim": (40, 200),       # general part footprint
    "large_dim": (150, 500),    # large / enclosure-scale
    "wall_thickness": (1.5, 6),
    "extrude_thin": (2, 15),
    "extrude_med": (10, 80),
    "hole_radius": (1.5, 8),
    "fillet_small": (0.5, 3),
    "chamfer_small": (0.5, 3),
    "pattern_count": (2, 8),
    "revolve_radius": (10, 80),
}


def rnd(key: str, rng: random.Random) -> float:
    lo, hi = RANGES[key]
    return round(rng.uniform(lo, hi), 2)


def safe_fillet_radius(edge_length: float, rng: random.Random) -> float:
    """Fillet radius must stay well under half the shortest adjacent edge
    to avoid self-intersecting the fillet -- keep a comfortable margin."""
    cap = max(0.3, edge_length * 0.35)
    lo, hi = RANGES["fillet_small"]
    return round(min(rng.uniform(lo, hi), cap), 2)


def safe_hole_depth(material_thickness: float, rng: random.Random,
                     through: bool = False) -> float:
    if through:
        return round(material_thickness + 0.5, 2)  # slight over-cut, common practice
    return round(rng.uniform(material_thickness * 0.2, material_thickness * 0.75), 2)


def non_overlapping_positions(n: int, extent: float, min_gap: float,
                               rng: random.Random) -> list[tuple[float, float]]:
    """Cheap on-grid jittered placement so sketch primitives don't
    coincide (which produces degenerate boolean sketch ops)."""
    cols = max(1, int(n ** 0.5))
    rows = (n + cols - 1) // cols
    cell = extent / max(cols, rows)
    pts = []
    for i in range(n):
        r, c = divmod(i, cols)
        base_x = -extent / 2 + cell * (c + 0.5)
        base_y = -extent / 2 + cell * (r + 0.5)
        jitter = min_gap * 0.2
        pts.append((
            round(base_x + rng.uniform(-jitter, jitter), 2),
            round(base_y + rng.uniform(-jitter, jitter), 2),
        ))
    return pts


# ---------------------------------------------------------------------------
# instruction phrasing -- deliberately varied register/verbosity so the
# model doesn't overfit to one template style
# ---------------------------------------------------------------------------
PHRASING_TEMPLATES = [
    "{verb} {desc}.",
    "{verb} {desc} — {detail}.",
    "I need {desc}. {detail_cap}.",
    "Can you {verb_lower} {desc}?",
    "{desc_cap}, {detail}.",
    "Design {desc} for me.",
    "Model {desc}.",
]

VERBS = ["Create", "Generate", "Build", "Design", "Make"]


def phrase_instruction(desc: str, detail: str, rng: random.Random) -> str:
    template = rng.choice(PHRASING_TEMPLATES)
    verb = rng.choice(VERBS)
    return template.format(
        verb=verb,
        verb_lower=verb.lower(),
        desc=desc,
        desc_cap=desc[0].upper() + desc[1:],
        detail=detail,
        detail_cap=detail[0].upper() + detail[1:] if detail else "",
    ).strip()


@dataclass
class Record:
    task_type: str
    instruction: str
    json_ir: dict
    complexity: int
    units: str = "mm"
    source: str = "procedural"
    extra: dict | None = None

    def to_dict(self, record_id: str) -> dict:
        d = {
            "record_id": record_id,
            "task_type": self.task_type,
            "schema_version": 2,
            "complexity": self.complexity,
            "units": self.units,
            "source": self.source,
            "instruction": self.instruction,
            "json_ir": self.json_ir,
        }
        if self.extra:
            d.update(self.extra)
        return d
