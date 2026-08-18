"""
mine_flywheel_repairs.py
Phase 4 step 2: for each FAILED generate/apply event classified "retried"
or "abandoned" (no_further_activity + failed), walks that project's full
timeline forward past any further retries to find the next SUCCESSFUL
generate/apply -- "the eventual fix" -- and pairs them into a record
shaped like gen_repair.py's synthetic output (source="flywheel",
verified=False -- re-verification is step 4, NOT done here).

Needs the FULL, unfiltered outcome log (not step 1's default filtered
output) to find fixes -- fetches it directly unless --events-file points
at a file that already contains every outcome category.

Usage:
    python mine_flywheel_repairs.py --llm-service-url http://localhost:8001 \
        --out out/flywheel_repairs.jsonl --unfixed-out out/flywheel_unfixed.jsonl
"""

from __future__ import annotations
import argparse
import json
import os

from flywheel_common import group_by_project, fetch_version
from mine_flywheel_data import fetch_outcomes

FAILURE_OUTCOMES = {"retried"}  # "abandoned" handled via the success==False check below


def find_eventual_fix(timeline: list[dict], start_index: int) -> dict | None:
    for e in timeline[start_index + 1:]:
        if e["action"] not in ("generate", "apply"):
            continue
        if e.get("success"):
            return e
        # another failure -- same retry chain, keep walking
    return None


def build_repair_pairs(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (pairs, unfixed). unfixed failures are reported, not
    dropped, so the true fixable rate stays visible."""
    pairs, unfixed = [], []
    for pid, timeline in group_by_project(events).items():
        for i, event in enumerate(timeline):
            if event.get("success") is not False:
                continue
            in_scope = event.get("outcome") in FAILURE_OUTCOMES or (
                event.get("outcome") == "no_further_activity"
            )
            if not in_scope or event.get("failed_ir") is None:
                continue
            fix = find_eventual_fix(timeline, i)
            if fix is None:
                unfixed.append(event)
            else:
                pairs.append({"project_id": pid, "failure": event, "fix": fix})
    return pairs, unfixed


def make_repair_record(pair: dict, fixed_ir: dict) -> dict:
    failure = pair["failure"]
    return {
        "record_id": f"flywheel_repair_{failure['id']}",
        "task_type": "repair",
        "schema_version": 2,
        "complexity": len(fixed_ir.get("features", [])),
        "units": "mm",
        "source": "flywheel",
        "instruction": "This part fails to build. Diagnose and fix it.",
        "broken_ir": failure["failed_ir"],
        "error_type": failure.get("error_type"),
        "error": failure.get("error"),
        "json_ir": fixed_ir,
        "verified": False,  # step 4's job -- never claim True before re-execution
        "original_prompt": failure.get("prompt"),  # metadata only, not used by to_chat_format
        "project_id": pair["project_id"],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm-service-url", default=os.environ.get("LLM_SERVICE_URL", "http://localhost:8001"))
    ap.add_argument("--events-file", default=None,
                     help="JSONL with ALL outcome categories (not step 1's filtered default) -- "
                          "if omitted, fetches the full unfiltered log directly instead")
    ap.add_argument("--project-id", default=None)
    ap.add_argument("--fetch-limit", type=int, default=5000)
    ap.add_argument("--out", default="out/flywheel_repairs.jsonl")
    ap.add_argument("--unfixed-out", default="out/flywheel_unfixed.jsonl")
    args = ap.parse_args()

    if args.events_file:
        with open(args.events_file) as f:
            events = [json.loads(l) for l in f]
    else:
        events = fetch_outcomes(args.llm_service_url, args.project_id, args.fetch_limit)
    print(f"{len(events)} events loaded")

    pairs, unfixed = build_repair_pairs(events)
    print(f"{len(pairs)} candidate repair pairs, {len(unfixed)} unfixed failures")

    records, skipped = [], 0
    for pair in pairs:
        try:
            version = fetch_version(args.llm_service_url, pair["project_id"], pair["fix"]["version_index"])
        except Exception:
            skipped += 1
            continue
        records.append(make_repair_record(pair, version["json_ir"]))
    if skipped:
        print(f"  ({skipped} pairs skipped -- couldn't fetch the fix version)")

    for path, rows in ((args.out, records), (args.unfixed_out, unfixed)):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    print(f"wrote {len(records)} repair records (verified=False) to {args.out}")
    print(f"wrote {len(unfixed)} unfixed failures to {args.unfixed_out}")


if __name__ == "__main__":
    main()
