"""
eval_geometry.py
Scores a batch of raw model completions (expected to be JSON IR text) on
three increasingly strict levels:
  1. valid_json   - does it parse as JSON at all
  2. schema_valid  - does it pass schema.validate_ir() (structural checks)
  3. build_valid    - does it actually compile+execute to valid geometry
                       through the real build123d install (executor.execute_ir)

This directly reuses the cad_dataset repo's own verification pipeline
(schema.py / executor.py) rather than re-implementing IR validation here,
so the eval metric can never silently drift from what the dataset itself
considers "correct". The cad_dataset repo root must be on sys.path --
see CAD_DATASET_PATH handling below, wired up from train.py.
"""

from __future__ import annotations
import json
import sys
import os


def _ensure_cad_dataset_on_path():
    path = os.environ.get("CAD_DATASET_PATH", "/workspace/cad_dataset")
    if path not in sys.path:
        sys.path.insert(0, path)


def evaluate_completions(completions: list[str], build_timeout: float = 15.0,
                          check_geometry: bool = True) -> dict:
    _ensure_cad_dataset_on_path()
    from schema import validate_ir, SchemaError

    n = len(completions)
    if n == 0:
        return {"n": 0, "valid_json_rate": None, "schema_valid_rate": None, "build_valid_rate": None}

    n_json_ok = 0
    n_schema_ok = 0
    n_build_ok = 0
    schema_valid_irs = []

    for text in completions:
        try:
            ir = json.loads(text)
        except json.JSONDecodeError:
            continue
        n_json_ok += 1
        try:
            validate_ir(ir)
        except SchemaError:
            continue
        n_schema_ok += 1
        schema_valid_irs.append(ir)

    build_checked = 0
    if check_geometry and schema_valid_irs:
        from executor import execute_ir
        for ir in schema_valid_irs:
            result = execute_ir(ir, timeout=build_timeout)
            build_checked += 1
            if result.get("success"):
                n_build_ok += 1

    return {
        "n": n,
        "valid_json_rate": n_json_ok / n,
        "schema_valid_rate": n_schema_ok / n,
        "build_valid_rate": (n_build_ok / build_checked) if build_checked else None,
    }
