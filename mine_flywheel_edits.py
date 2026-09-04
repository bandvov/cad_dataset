"""
mine_flywheel_edits.py
Phase 4 step 3: for each event classified "edited" (next action was a
manual apply, Phase 2 item 4), pairs it with that apply -- if the apply
itself succeeded -- into a record shaped like gen_regenerate.py's
synthetic output (base_ir -> edited json_ir, source="flywheel",
verified=False -- step 4's job, not done here).

CHANGE (flywheel-auth fix, step 5): now requires --auth-token (an admin
user's session token, see make_admin.py), threaded into both
fetch_outcomes() (now hitting the admin-scoped GET
/v1/admin/logs/outcomes) and fetch_version() (still owner-scoped -- see
flywheel_common.py's docstring for the coverage caveat).

Unlike synthetic regenerate data, there's no natural-language edit
instruction (the user changed a field directly in the UI, no prompt
involved) and no recipe. Instead of leaving `instruction` empty, a
best-effort description is synthesized by diffing the two trees'
top-level scalar fields -- see diff_instruction().

Usage:
    python mine_flywheel_edits.py --llm-service-url http://localhost:8001 \
        --auth-token <admin session token> \
        --out out/flywheel_edits.jsonl
"""

from __future__ import annotations
import argparse
import json
import os

from flywheel_common import group_by_project, fetch_version
from mine_flywheel_data import fetch_outcomes


def find_next(timeline: list[dict], start_index: int) -> dict | None:
    return timeline[start_index + 1] if start_index + 1 < len(timeline) else None


def build_edit_pairs(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (pairs, unpaired). unpaired = "edited"-labeled events whose
    following apply itself failed (no valid edited state to pair)."""
    pairs, unpaired = [], []
    for pid, timeline in group_by_project(events).items():
        for i, event in enumerate(timeline):
            if event.get("outcome") != "edited":
                continue
            nxt = find_next(timeline, i)
            if nxt is None or nxt.get("action") != "apply" or not nxt.get("success"):
                unpaired.append(event)
                continue
            pairs.append({"project_id": pid, "base_event": event, "edit_event": nxt})
    return pairs, unpaired


def diff_instruction(base_ir: dict, edited_ir: dict) -> str:
    """Best-effort description of what changed -- finds the first scalar
    field that differs between matching features (by id) and phrases it.
    Falls back to a generic description if the diff isn't a simple single
    scalar change (e.g. feature count changed) -- structured editing is
    scoped to single-field edits (see frontend/src/lib/featureEdit.js),
    so a clean single-field diff is the expected common case, not multiple
    changes at once."""
    base_by_id = {f["id"]: f for f in base_ir.get("features", [])}
    edited_by_id = {f["id"]: f for f in edited_ir.get("features", [])}
    for fid, edited_feat in edited_by_id.items():
        base_feat = base_by_id.get(fid)
        if base_feat is None:
            continue
        for key, new_val in edited_feat.items():
            old_val = base_feat.get(key)
            if old_val != new_val and not isinstance(new_val, (dict, list)):
                return f"Change {edited_feat.get('feature_type', fid)}.{key} from {old_val} to {new_val}."
    return "Apply the edited feature tree."


def make_edit_record(pair: dict, base_ir: dict, edited_ir: dict) -> dict:
    return {
        "record_id": f"flywheel_edit_{pair['edit_event']['id']}",
        "task_type": "regenerate",
        "schema_version": 2,
        "complexity": len(edited_ir.get("features", [])),
        "units": "mm",
        "source": "flywheel",
        "instruction": diff_instruction(base_ir, edited_ir),
        "base_ir": base_ir,
        "json_ir": edited_ir,
        "verified": False,  # step 4's job -- never claim True before re-execution
        "project_id": pair["project_id"],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm-service-url", default=os.environ.get("LLM_SERVICE_URL", "http://localhost:8001"))
    ap.add_argument("--auth-token", default=os.environ.get("LLM_SERVICE_ADMIN_TOKEN"),
                     required=os.environ.get("LLM_SERVICE_ADMIN_TOKEN") is None,
                     help="session token of a user with is_admin=True (see make_admin.py). "
                          "Required unless --events-file is given.")
    ap.add_argument("--events-file", default=None,
                     help="JSONL with ALL outcome categories -- if omitted, fetches fresh")
    ap.add_argument("--project-id", default=None)
    ap.add_argument("--fetch-limit", type=int, default=5000)
    ap.add_argument("--out", default="out/flywheel_edits.jsonl")
    args = ap.parse_args()

    if args.events_file:
        with open(args.events_file) as f:
            events = [json.loads(l) for l in f]
    else:
        events = fetch_outcomes(args.llm_service_url, args.project_id, args.fetch_limit, args.auth_token)
    print(f"{len(events)} events loaded")

    pairs, unpaired = build_edit_pairs(events)
    print(f"{len(pairs)} candidate edit pairs, {len(unpaired)} unpaired (apply itself failed)")

    records, skipped = [], 0
    for pair in pairs:
        base_ev, edit_ev = pair["base_event"], pair["edit_event"]
        try:
            base_ir = (fetch_version(args.llm_service_url, pair["project_id"],
                                      base_ev["version_index"], args.auth_token)["json_ir"]
                       if base_ev.get("version_index") is not None else base_ev.get("failed_ir"))
            edited_ir = fetch_version(args.llm_service_url, pair["project_id"],
                                       edit_ev["version_index"], args.auth_token)["json_ir"]
        except Exception:
            skipped += 1
            continue
        if base_ir is None:
            skipped += 1
            continue
        records.append(make_edit_record(pair, base_ir, edited_ir))
    if skipped:
        print(f"  ({skipped} pairs skipped -- couldn't resolve base/edited IR, e.g. owned by "
              f"another user; an admin token doesn't bypass project ownership on that route)")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(records)} edit records (verified=False) to {args.out}")


if __name__ == "__main__":
    main()
