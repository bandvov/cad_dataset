"""
patch.py
Merges a patch (list of append/modify/delete ops) into a base json_ir,
so the LLM only has to emit what changed, not the whole feature tree.
Deliberately does NOT re-run schema/bounds validation itself -- the
merged tree goes through the exact same validate_ir()/compile_ir() path
every other IR does (via the geometry service's /v1/compile), so a
dangling reference from a bad `delete` or a malformed `modify` surfaces
there, with the same error_type/error shape the repair loop already
knows how to consume. This module's only job is producing the merged
tree; correctness is still the compiler/schema's job, same division of
labor as every other feature type here.

Currently only `append` is wired up end-to-end (orchestrator.
generate_append_stream()); `modify`/`delete` are implemented here so the
shape exists ahead of the LLM-driven paths that will need them (same
staging approach RATE_LIMIT_PER_MINUTE/is_admin took elsewhere in this
project -- add the primitive before the caller that needs it).
"""

from __future__ import annotations
import copy
from typing import Any


class PatchError(Exception):
    """Raised for a patch that's malformed independent of geometry --
    unknown op, missing id, id collision. Kept separate from SchemaError
    (schema.py) since this is about the patch's own shape, not the
    resulting IR's."""


def apply_patch(base_ir: dict, patch: list[dict]) -> dict:
    ir = copy.deepcopy(base_ir)
    features: list[dict] = ir.setdefault("features", [])
    by_id = {f["id"]: i for i, f in enumerate(features)}

    for op in patch:
        kind = op.get("op")

        if kind == "append":
            feat = op.get("feature")
            if not isinstance(feat, dict) or "id" not in feat:
                raise PatchError(f"append op missing a valid 'feature': {op!r}")
            if feat["id"] in by_id:
                raise PatchError(f"append: id '{feat['id']}' already exists -- use 'modify'")
            by_id[feat["id"]] = len(features)
            features.append(feat)

        elif kind == "modify":
            fid = op.get("id")
            fields = op.get("fields")
            if fid not in by_id:
                raise PatchError(f"modify: unknown id '{fid}'")
            if not isinstance(fields, dict) or not fields:
                raise PatchError(f"modify '{fid}': 'fields' must be a non-empty object")
            features[by_id[fid]].update(fields)

        elif kind == "delete":
            fid = op.get("id")
            if fid not in by_id:
                raise PatchError(f"delete: unknown id '{fid}'")
            # leave reference-integrity checking to validate_ir() post-merge
            # (it already raises on forward/undefined source/target refs --
            # a delete that orphans a downstream feature hits that same
            # check for free)
            idx = by_id.pop(fid)
            features.pop(idx)
            by_id = {f["id"]: i for i, f in enumerate(features)}  # reindex

        else:
            raise PatchError(f"unknown patch op '{kind}'")

    return ir
