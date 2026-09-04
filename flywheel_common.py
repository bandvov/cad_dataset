"""flywheel_common.py -- shared helpers for mine_flywheel_repairs.py (step 2)
and mine_flywheel_edits.py (step 3). Stdlib only.

CHANGE (flywheel-auth fix, step 5): fetch_version() now sends an
Authorization header when given a token -- GET
/v1/projects/{id}/versions/{index} is behind Depends(get_current_user)
and has always required auth; this script simply never sent any. Note
this endpoint is OWNER-scoped (_require_owned_project() in main.py), and
admin status does NOT bypass that check -- an admin token here still only
sees versions of projects it owns. Fetching an arbitrary user's version
data this way will 404 even with a valid admin token. Callers already
treat a failed/missing fetch as "skip this pair, don't crash" (see
mine_flywheel_repairs.py/mine_flywheel_edits.py's `except Exception`
handling), so this is a coverage gap, not a crash risk -- worth a real
fix (an admin-scoped version-fetch route, or an ownership bypass for
admins on this route) if flywheel coverage of other users' fixes turns
out to matter in practice."""

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


def fetch_version(llm_service_url: str, project_id: str, version_index: int,
                   auth_token: str | None = None) -> dict:
    url = f"{llm_service_url.rstrip('/')}/v1/projects/{project_id}/versions/{version_index}"
    headers = {"Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())
