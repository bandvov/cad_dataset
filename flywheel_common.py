"""flywheel_common.py -- shared helpers for mine_flywheel_repairs.py (step 2)
and mine_flywheel_edits.py (step 3). Stdlib only."""

from __future__ import annotations
import json
import urllib.error
import urllib.request


def group_by_project(events: list[dict]) -> dict[str, list[dict]]:
    by_project: dict[str, list[dict]] = {}
    for e in events:
        by_project.setdefault(e["project_id"], []).append(e)
    for pid in by_project:
        by_project[pid].sort(key=lambda e: e["created_at"])
    return by_project


def fetch_version(llm_service_url: str, project_id: str, version_index: int) -> dict:
    url = f"{llm_service_url.rstrip('/')}/v1/projects/{project_id}/versions/{version_index}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())
