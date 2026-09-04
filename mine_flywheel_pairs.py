"""
mine_flywheel_pairs.py
Phase 4 step 2: repair-pair construction. Takes step 1's extracted event
JSONL (mine_flywheel_data.py's output) and, for each FAILED event that has
an attempted IR (`failed_ir`), looks for the next successful event in the
SAME project within a bounded time window and pairs them into a candidate
repair record matching gen_repair.py's record shape.

CHANGE (flywheel-auth fix, step 5): fetch_project_log() used to hit GET
/v1/logs with no Authorization header. Now requires --auth-token (an
admin user's session token, see make_admin.py) and hits GET
/v1/admin/logs instead of the user_id-scoped /v1/logs -- this script
inherently needs to see events across every user, which the non-admin
route structurally can't provide regardless of whose token is sent.
fetch_version() now also sends the token, but note it hits
/v1/projects/{id}/versions/{index}, which is OWNER-scoped and does NOT
recognize admin as a bypass (see flywheel_common.py's fetch_version() for
the same caveat) -- an admin token here still only resolves fixes for
projects it owns. A failed fetch here already degrades to "counted as
unresolved" rather than crashing (see find_eventual_fix's caller below),
so this is a coverage gap, not a new failure mode.

IMPORTANT -- read before using this output for anything: this pairing is
a heuristic, not a verified causal fix. "The next successful thing that
happened in this project" is a reasonable guess that the user kept
working on the SAME problem until it worked, but this script has no way
to confirm that -- the user could just as easily have abandoned the
failed attempt and started something unrelated in the same project.
Every candidate here is written with "verified": false. Step 4
(re-running both sides through executor.py -- confirm the broken IR
still fails and the fixed IR still compiles) is what actually confirms
anything. Nothing from this script's output should be used as training
data before that step runs, same rule gen_repair.py already follows for
synthetic data.

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
    python mine_flywheel_pairs.py \
        --llm-service-url http://localhost:8001 \
        --auth-token <admin session token> \
        --in out/flywheel_events.jsonl \
        --max-lookforward-minutes 60 \
        --out out/flywheel_pairs_candidates.jsonl \
        --unresolved-out out/flywheel_pairs_unresolved.jsonl

Stdlib only, same as mine_flywheel_data.py.
"""

from __future__ import annotations
import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _auth_headers(auth_token: str | None) -> dict:
    headers = {"Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    return headers


def fetch_project_log(llm_service_url: str, project_id: str, auth_token: str | None,
                       limit: int = 5000) -> list[dict]:
    """Raw chronological event list for one project -- GET /v1/admin/logs
    (cross-user; see module docstring), not /v1/admin/logs/outcomes (see
    original module docstring for why the raw stream is needed here
    rather than the single-next-event classification)."""
    params = {"project_id": project_id, "limit": str(limit)}
    url = f"{llm_service_url.rstrip('/')}/v1/admin/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=_auth_headers(auth_token))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            events = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError(
                f"{e.code} from {url} -- --auth-token must be an admin user's session "
                f"token (grant one via make_admin.py)"
            ) from e
        raise
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach llm-service at {url}: {e}") from e
    events.sort(key=lambda e: e["created_at"])  # /v1/admin/logs returns DESC; we want chronological
    return events


def fetch_version(llm_service_url: str, project_id: str, version_index: int,
                   auth_token: str | None = None) -> dict | None:
    """See module docstring's CHANGE note -- this endpoint is OWNER-scoped
    and does not treat admin as a bypass, so this only resolves for
    projects the token's own user owns."""
    url = f"{llm_service_url.rstrip('/')}/v1/projects/{project_id}/versions/{version_index}"
    req = urllib.request.Request(url, headers=_auth_headers(auth_token))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach llm-service at {url}: {e}") from e


def find_eventual_fix(project_log: list[dict], failure_event: dict,
                       max_lookforward_minutes: float) -> dict | None:
    """Pure function, no I/O: given a project's full chronological event
    log and one failure within it, scans forward for the first
    success=True event with a version_index, within the time window.
    Multiple failed retries in between are fine and expected -- this
    doesn't stop at the first non-matching event, unlike
    compute_outcomes()'s single-next-event classification."""
    failure_dt = _parse_dt(failure_event["created_at"])
    deadline = failure_dt + timedelta(minutes=max_lookforward_minutes)

    # find the failure's own position by id (created_at alone isn't a
    # reliable unique key if two events land in the same second)
    try:
        start = next(i for i, e in enumerate(project_log) if e["id"] == failure_event["id"])
    except StopIteration:
        start = 0
        # failure_event came from a differently-scoped fetch than
        # project_log (shouldn't happen in normal use, but don't crash --
        # fall back to scanning the whole log by timestamp instead)

    for event in project_log[start + 1:]:
        event_dt = _parse_dt(event["created_at"])
        if event_dt > deadline:
            break
        if (event.get("success") is True and event.get("version_index") is not None
                and event.get("action") in ("generate", "apply")):
            # deliberately excludes "undo"/"redo": those have success=True
            # and a version_index too, but represent reverting to an
            # earlier, unrelated version -- not a fix for THIS failure --
            # and would otherwise get paired here incorrectly
            return event
    return None


def build_pair_record(failure_event: dict, fix_event: dict, fixed_ir: dict) -> dict:
    """Matches gen_repair.py's record shape (see that module) so both
    flow through the same build_dataset.py dedup/split/chat-format
    pipeline later -- with two deliberate differences: "verified": false
    (see module docstring) and "fault_description": null (synthetic
    fault injection knows exactly what it broke and why; a real
    production failure doesn't come with that label attached)."""
    failure_dt = _parse_dt(failure_event["created_at"])
    fix_dt = _parse_dt(fix_event["created_at"])
    return {
        "record_id": f"flywheel_repair_{failure_event['id']}",
        "task_type": "repair",
        "schema_version": 2,
        "complexity": len(fixed_ir.get("features", [])) if fixed_ir else None,
        "units": "mm",
        "source": "flywheel",
        "instruction": "This part fails to build. Diagnose and fix it.",
        "fault_description": None,
        "broken_ir": failure_event.get("failed_ir"),
        "error_type": failure_event.get("error_type"),
        "error": failure_event.get("error"),
        "json_ir": fixed_ir,
        "verified": False,
        "flywheel_meta": {
            "project_id": failure_event["project_id"],
            "failure_event_id": failure_event["id"],
            "fix_event_id": fix_event["id"],
            "failure_created_at": failure_event["created_at"],
            "fix_created_at": fix_event["created_at"],
            "lookforward_seconds": (fix_dt - failure_dt).total_seconds(),
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm-service-url", default=os.environ.get("LLM_SERVICE_URL", "http://localhost:8001"))
    ap.add_argument("--auth-token", default=os.environ.get("LLM_SERVICE_ADMIN_TOKEN"),
                     required=os.environ.get("LLM_SERVICE_ADMIN_TOKEN") is None,
                     help="session token of a user with is_admin=True (see make_admin.py). "
                          "Required for GET /v1/admin/logs. Can also be set via "
                          "LLM_SERVICE_ADMIN_TOKEN.")
    ap.add_argument("--in", dest="input", required=True, help="step 1's output (mine_flywheel_data.py)")
    ap.add_argument("--max-lookforward-minutes", type=float, default=60.0,
                     help="how far forward to search for an eventual fix before giving up")
    ap.add_argument("--out", default="out/flywheel_pairs_candidates.jsonl")
    ap.add_argument("--unresolved-out", default="out/flywheel_pairs_unresolved.jsonl",
                     help="failures with no eventual fix found -- still worth a look, "
                          "just not usable as a repair pair")
    args = ap.parse_args()

    with open(args.input) as f:
        events = [json.loads(line) for line in f if line.strip()]

    failures = [e for e in events if e.get("success") is False and e.get("failed_ir") is not None]
    skipped_no_project = [e for e in events if e.get("success") is False and e.get("project_id") is None]
    skipped_no_ir = [e for e in events
                     if e.get("success") is False and e.get("project_id") is not None
                     and e.get("failed_ir") is None]
    print(f"{len(events)} input events: {len(failures)} candidate failures "
          f"({len(skipped_no_project)} skipped -- no project [stateless /v1/generate], "
          f"{len(skipped_no_ir)} skipped -- no parseable failed_ir)")

    by_project: dict[str, list[dict]] = {}
    for e in failures:
        by_project.setdefault(e["project_id"], []).append(e)

    log_cache: dict[str, list[dict]] = {}
    candidates, unresolved = [], []
    n_forbidden_version_fetch = 0

    for project_id, project_failures in by_project.items():
        if project_id not in log_cache:
            print(f"fetching full log for project {project_id}...")
            log_cache[project_id] = fetch_project_log(args.llm_service_url, project_id, args.auth_token)
        project_log = log_cache[project_id]

        for failure in project_failures:
            fix_event = find_eventual_fix(project_log, failure, args.max_lookforward_minutes)
            if fix_event is None:
                unresolved.append(failure)
                continue
            fixed_version = fetch_version(args.llm_service_url, project_id,
                                           fix_event["version_index"], args.auth_token)
            if fixed_version is None:
                # either the referenced version no longer exists, or (see
                # module docstring) the admin token doesn't own this
                # project -- either way, treat as unresolved rather than
                # guessing
                unresolved.append(failure)
                n_forbidden_version_fetch += 1
                continue
            candidates.append(build_pair_record(failure, fix_event, fixed_version["json_ir"]))

    for path, records in ((args.out, candidates), (args.unresolved_out, unresolved)):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    print(f"wrote {len(candidates)} candidate repair pairs to {args.out} "
          f"(verified=false -- run step 4 before training on these)")
    print(f"wrote {len(unresolved)} unresolved failures to {args.unresolved_out}")
    if n_forbidden_version_fetch:
        print(f"  ({n_forbidden_version_fetch} of those unresolved were version fetches that 404'd -- "
              f"an admin token only resolves versions for projects it owns; see flywheel_common.py's "
              f"fetch_version() docstring)")


if __name__ == "__main__":
    main()
