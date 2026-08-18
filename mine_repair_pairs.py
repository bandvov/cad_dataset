"""
mine_repair_pairs.py
Phase 4 step 2: repair-pair construction. Takes step 1's output
(mine_flywheel_data.py's JSONL of outcome-classified events) and, for each
event with a failed_ir, looks up whether a LATER version was created in
the same project -- if so, pairs the failure (broken_ir/error/error_type)
with that later version (the fix), producing candidate repair records in
the same shape gen_repair.py's synthetic records use.

NOT GEOMETRY-VERIFIED at this stage -- these are pairings based on log
timestamps, not re-execution. Every record here has "verified": false.
Step 4 of the flywheel plan (re-running both broken_ir and json_ir through
executor.py, the same discipline gen_repair.py already applies to
synthetic data) is required before any of this is safe to merge into
training data. Treat this script's output as candidates, not ground truth.

Why "abandoned" events never produce a pair, and that's correct: an
"abandoned" event (see mine_flywheel_data.py's alias) means nothing
followed the failure at all -- by definition there is no "eventual
successful version" to pair with. Feeding abandoned-only input through
this script will report 0 pairs, which is the right answer, not a bug.
Feed it "retried" events (or unfiltered) to actually get pairs -- those
are the failures a later version in the same project might have fixed.

Needs GET /v1/projects/{id}/versions/{version_index} (added alongside
this script, see llm-service/app/store.py's get_version()) since the
version that eventually fixed a failure is often no longer a project's
CURRENT version by the time mining runs.

Usage:
    python mine_repair_pairs.py \
        --llm-service-url http://localhost:8001 \
        --events out/flywheel_events.jsonl \
        --max-gap-hours 24 \
        --out out/flywheel_repair_candidates.jsonl

Stdlib only, deliberately, same as mine_flywheel_data.py.
"""

from __future__ import annotations
import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def find_fix_version(llm_service_url: str, project_id: str, after: datetime,
                      max_gap_hours: float | None) -> dict | None:
    """The next version created in this project after `after`, fetched in
    full via GET .../versions/{index} (not get_project()'s `current`,
    since the fix may since have been superseded by further edits).
    Returns None if no later version exists, the project itself is gone,
    or the gap exceeds max_gap_hours."""
    base = llm_service_url.rstrip("/")
    try:
        project = fetch_json(f"{base}/v1/projects/{project_id}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise

    candidates = [v for v in project.get("history", []) if _parse_dt(v["created_at"]) > after]
    if not candidates:
        return None
    candidates.sort(key=lambda v: v["created_at"])
    nxt = candidates[0]

    if max_gap_hours is not None:
        gap_hours = (_parse_dt(nxt["created_at"]) - after).total_seconds() / 3600
        if gap_hours > max_gap_hours:
            return None

    return fetch_json(f"{base}/v1/projects/{project_id}/versions/{nxt['version_index']}")


def build_repair_record(event: dict, fix_version: dict) -> dict:
    """Mirrors gen_repair.py's record shape (record_id, task_type,
    schema_version, complexity, units, source, instruction,
    fault_description, broken_ir, error_type, error, json_ir, verified)
    so downstream steps (dedup, chat-format conversion, build_dataset.py
    merging) don't need to special-case flywheel-mined records. Extra
    provenance fields beyond that shape are additive, not a replacement
    for it -- anything consuming only gen_repair.py's fields still works."""
    fix_ir = fix_version["json_ir"]
    return {
        "record_id": f"flywheel_repair_{event['id']}",
        "task_type": "repair",
        "schema_version": 2,
        "complexity": len(fix_ir.get("features", [])),
        "units": "mm",
        "source": "production_flywheel",
        "instruction": "This part fails to build. Diagnose and fix it.",
        # Unlike gen_repair.py's synthetic fault_description (which names
        # exactly which fault injector ran), we don't actually know what a
        # real user/model did wrong -- don't fabricate a specific
        # narrative for a real failure we didn't engineer.
        "fault_description": "production failure (mined from request log, not a synthetic injected fault)",
        "broken_ir": event["failed_ir"],
        "error_type": event.get("error_type"),
        "error": event.get("error"),
        "json_ir": fix_ir,
        "verified": False,  # step 4 (re-verification) has not run yet -- see module docstring
        # provenance, for audit/debugging -- not part of gen_repair.py's shape
        "mined_from_event_id": event["id"],
        "project_id": event["project_id"],
        "original_prompt": event.get("prompt"),
        "failure_created_at": event["created_at"],
        "fix_version_index": fix_version["version_index"],
        "fix_prompt": fix_version.get("prompt"),
        "fix_created_at": fix_version.get("created_at"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm-service-url", default=os.environ.get("LLM_SERVICE_URL", "http://localhost:8001"))
    ap.add_argument("--events", required=True, help="step 1's output JSONL (mine_flywheel_data.py)")
    ap.add_argument("--max-gap-hours", type=float, default=None,
                     help="skip pairing if the fix came more than this many hours after the "
                          "failure. Unbounded by default -- a long gap might still be a "
                          "legitimate 'came back later and fixed it', and this script doesn't "
                          "try to judge that, only pair by timestamp.")
    ap.add_argument("--out", default="out/flywheel_repair_candidates.jsonl")
    args = ap.parse_args()

    with open(args.events) as f:
        events = [json.loads(line) for line in f if line.strip()]

    n_no_project = 0
    n_no_broken_ir = 0
    n_no_fix = 0
    records = []

    for event in events:
        project_id = event.get("project_id")
        if not project_id:
            n_no_project += 1  # stateless (no-project) generate -- nothing to look up history in
            continue
        if not event.get("failed_ir"):
            n_no_broken_ir += 1  # model output wasn't valid JSON at all -- no broken_ir to pair
            continue

        failure_time = _parse_dt(event["created_at"])
        fix_version = find_fix_version(args.llm_service_url, project_id, failure_time, args.max_gap_hours)
        if fix_version is None:
            n_no_fix += 1
            continue

        records.append(build_repair_record(event, fix_version))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    print(f"read {len(events)} candidate events from {args.events}")
    print(f"  skipped {n_no_project} with no project_id (stateless /v1/generate, no history to search)")
    print(f"  skipped {n_no_broken_ir} with no failed_ir (model output wasn't valid JSON)")
    gap_note = f" within {args.max_gap_hours}h" if args.max_gap_hours else ""
    print(f"  skipped {n_no_fix} with no later version found in the same project{gap_note}")
    print(f"  paired {len(records)} repair candidates -> {args.out}")
    print()
    print("NOTE: these are candidates only, NOT geometry-verified -- run step 4")
    print("(re-verification through executor.py) before using this for training.")


if __name__ == "__main__":
    main()
