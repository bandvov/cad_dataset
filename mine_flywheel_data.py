"""
mine_flywheel_data.py
Phase 4 step 1: log extraction. Pulls outcome-classified events from
llm-service's GET /v1/admin/logs/outcomes (see llm-service/app/store.py's
compute_outcomes() for exactly what each outcome label means and doesn't
mean), filters by outcome type and date range, and writes the matching
raw events to a JSONL file.

CHANGE (flywheel-auth fix, step 5): this used to hit GET /v1/logs/outcomes
with no Authorization header at all. That route is user_id-scoped (auth
step 7) -- even sending a token would only ever return one user's events,
never useful for mining production data across everyone. Now points at
GET /v1/admin/logs/outcomes (added alongside get_current_admin_user in
the flywheel-auth fix's steps 2-3) and requires --auth-token, the session
token of a user with is_admin=True (grant one via make_admin.py). A
non-admin or missing token now fails loudly (401/403) instead of the
previous silent-empty-or-wrong-scope behavior.

This is EXTRACTION ONLY -- turning these events into verified training
pairs (matching a failed_ir to its eventual fix, re-running through
executor.py, deduping against the existing corpus, converting to chat
format) is steps 2-7 of the flywheel plan and not implemented here. This
script's output is those steps' input.

Usage:
    python mine_flywheel_data.py \
        --llm-service-url http://localhost:8001 \
        --auth-token <admin session token> \
        --outcomes retried edited abandoned \
        --since 2026-08-01 --until 2026-08-08 \
        --out out/flywheel_events.jsonl

Stdlib only, deliberately -- this is a small extraction script, not worth
a requirements.txt of its own. Run it anywhere Python 3.10+ is available
with network access to llm-service.
"""

from __future__ import annotations
import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

# The literal outcome labels store.py's compute_outcomes() actually
# produces -- see that function's docstring for exact definitions.
KNOWN_OUTCOMES = {"accepted", "edited", "undone", "retried", "continued", "no_further_activity"}

# NOT a real outcome label -- see _matches_outcome()'s docstring for what
# this alias actually means and why it's narrower than it sounds.
ABANDONED_ALIAS = "abandoned"


def _parse_dt(s: str) -> datetime:
    """Accepts a bare date (YYYY-MM-DD) or a full ISO8601 timestamp;
    always returns a timezone-aware UTC datetime so it can be compared
    against event['created_at'], which store.py always writes as UTC
    ISO8601 (datetime.now(timezone.utc).isoformat())."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _matches_outcome(event: dict, wanted: set[str]) -> bool:
    """"abandoned" is NOT one of compute_outcomes()'s literal labels.
    That function's docstring is explicit that "no_further_activity" is
    deliberately ambiguous between "accepted and just never exported" and
    "abandoned" -- it refuses to guess between them. This script defines
    "abandoned" as the one unambiguous subset of that label: a generate/
    apply that FAILED and nothing followed -- the user hit an error and
    never tried again, as opposed to a success nothing followed (which
    could just as easily mean they were happy with it). Pass
    "no_further_activity" directly instead of "abandoned" if you want the
    full ambiguous set, successes included."""
    outcome = event.get("outcome")
    if outcome in wanted:
        return True
    if ABANDONED_ALIAS in wanted and outcome == "no_further_activity" and event.get("success") is False:
        return True
    return False


def fetch_outcomes(llm_service_url: str, project_id: str | None, limit: int,
                    auth_token: str | None = None) -> list[dict]:
    """Hits the ADMIN log route (cross-user) -- see module docstring's
    CHANGE note. auth_token must be an admin user's session token; a
    missing/non-admin token raises (via urllib.error.HTTPError, 401/403)
    rather than silently returning an empty or wrongly-scoped result."""
    params = {"limit": str(limit)}
    if project_id:
        params["project_id"] = project_id
    url = f"{llm_service_url.rstrip('/')}/v1/admin/logs/outcomes?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError(
                f"{e.code} from {url} -- --auth-token must be an admin user's session "
                f"token (grant one via make_admin.py); a normal user's token cannot "
                f"see cross-user log data"
            ) from e
        raise
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach llm-service at {url}: {e}") from e


def filter_events(events: list[dict], outcomes: set[str],
                   since: datetime | None, until: datetime | None) -> list[dict]:
    filtered = []
    for e in events:
        if not _matches_outcome(e, outcomes):
            continue
        created = _parse_dt(e["created_at"])
        if since is not None and created < since:
            continue
        if until is not None and created > until:
            continue
        filtered.append(e)
    return filtered


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm-service-url", default=os.environ.get("LLM_SERVICE_URL", "http://localhost:8001"))
    ap.add_argument("--auth-token", default=os.environ.get("LLM_SERVICE_ADMIN_TOKEN"),
                     required=os.environ.get("LLM_SERVICE_ADMIN_TOKEN") is None,
                     help="session token of a user with is_admin=True (see make_admin.py). "
                          "Required -- GET /v1/admin/logs/outcomes has no unauthenticated path. "
                          "Can also be set via LLM_SERVICE_ADMIN_TOKEN.")
    ap.add_argument("--project-id", default=None,
                     help="restrict to one project; default mines across all projects")
    ap.add_argument("--fetch-limit", type=int, default=5000,
                     help="events fetched from the API before filtering (compute_outcomes' own limit param)")
    ap.add_argument("--outcomes", nargs="+", default=["retried", "edited", "abandoned"],
                     help=f"outcome labels to keep. Known: {sorted(KNOWN_OUTCOMES)}, "
                          f"plus the alias '{ABANDONED_ALIAS}' (see _matches_outcome docstring)")
    ap.add_argument("--since", default=None,
                     help="ISO date/timestamp (e.g. 2026-08-01), inclusive lower bound on created_at")
    ap.add_argument("--until", default=None,
                     help="ISO date/timestamp, inclusive upper bound on created_at")
    ap.add_argument("--out", default="out/flywheel_events.jsonl")
    args = ap.parse_args()

    unknown = set(args.outcomes) - KNOWN_OUTCOMES - {ABANDONED_ALIAS}
    if unknown:
        ap.error(f"unknown outcome label(s) {sorted(unknown)}; "
                  f"known: {sorted(KNOWN_OUTCOMES)} plus alias '{ABANDONED_ALIAS}'")

    since = _parse_dt(args.since) if args.since else None
    until = _parse_dt(args.until) if args.until else None

    print(f"fetching outcomes from {args.llm_service_url} (limit={args.fetch_limit})...")
    events = fetch_outcomes(args.llm_service_url, args.project_id, args.fetch_limit, args.auth_token)
    print(f"  {len(events)} generate/apply events returned")

    filtered = filter_events(events, set(args.outcomes), since, until)
    print(f"  {len(filtered)} match outcomes={args.outcomes} "
          f"since={args.since or '-inf'} until={args.until or '+inf'}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        for e in filtered:
            f.write(json.dumps(e) + "\n")
    print(f"wrote {len(filtered)} events to {args.out}")

    counts = Counter(e["outcome"] for e in filtered)
    for outcome, n in counts.most_common():
        print(f"    {outcome}: {n}")


if __name__ == "__main__":
    main()
