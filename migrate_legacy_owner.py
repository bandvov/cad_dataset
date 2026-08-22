"""
migrate_legacy_owner.py
Auth plan step 8: one-time backfill for rows created before auth existed
(steps 1-6) -- projects.owner_id IS NULL and their request_log.user_id IS
NULL rows. Assigns them to a single designated "legacy" user rather than
leaving them permanently shared across every authenticated caller (that
sharing is currently only a stopgap -- see _require_owned_project() /
list_events() in main.py / store.py).

Does NOT touch request_log rows with no project_id (the stateless
/v1/generate path) -- there's no project to anchor an owner to, and
guessing one would misattribute requests nobody authenticated for. Those
stay user_id=NULL indefinitely; that's expected, not a bug this script
should "fix".

Usage:
    # dry run (default) -- prints counts, changes nothing
    python migrate_legacy_owner.py --db-path /data/cad_sessions.db \
        --owner-email legacy@yourcompany.example

    # apply
    python migrate_legacy_owner.py --db-path /data/cad_sessions.db \
        --owner-email legacy@yourcompany.example --apply

If --owner-email doesn't match an existing user, a new one is created
with a random password -- nobody is meant to log in as this account
directly, it exists only to hold pre-auth data. Re-running is safe: only
NULL columns are ever written (see store.py's backfill_legacy_ownership
docstring).
"""

from __future__ import annotations
import argparse
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import ProjectStore


def get_or_create_legacy_user(store: ProjectStore, email: str) -> dict:
    existing = store.get_user_by_email(email)
    if existing:
        return existing
    print(f"no existing user '{email}' -- creating one to own legacy data")
    return store.create_user(email, secrets.token_urlsafe(24))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db-path", default=os.environ.get("DB_PATH", "/data/cad_sessions.db"))
    ap.add_argument("--owner-email", required=True,
                     help="email of the user (existing or newly created) that legacy "
                          "pre-auth projects/request_log rows should be assigned to")
    ap.add_argument("--apply", action="store_true",
                     help="actually write changes -- omit for a dry-run report only")
    args = ap.parse_args()

    store = ProjectStore(args.db_path)

    before = store.count_legacy_rows()
    print(f"legacy projects (owner_id IS NULL): {before['legacy_projects']}")
    print(f"legacy request_log events with a project_id (migratable): "
          f"{before['legacy_request_log_events_migratable']}")
    print(f"legacy request_log events with NO project_id (stateless "
          f"/v1/generate -- never migrated, see docstring): "
          f"{before['legacy_request_log_events_stateless']}")

    if before["legacy_projects"] == 0 and before["legacy_request_log_events_migratable"] == 0:
        print("nothing to migrate")
        return

    if not args.apply:
        print("\ndry run only -- rerun with --apply to write changes")
        return

    user = get_or_create_legacy_user(store, args.owner_email)
    print(f"\nassigning legacy rows to user {user['id']} ({user['email']})")

    result = store.backfill_legacy_ownership(user["id"])
    print(f"updated {result['projects_updated']} projects, "
          f"{result['request_log_events_updated']} request_log events")

    after = store.count_legacy_rows()
    print(f"\nremaining after migration:")
    print(f"  legacy projects: {after['legacy_projects']} (should be 0)")
    print(f"  legacy request_log events (migratable): "
          f"{after['legacy_request_log_events_migratable']} (should be 0)")
    print(f"  legacy request_log events (stateless, expected to remain): "
          f"{after['legacy_request_log_events_stateless']}")


if __name__ == "__main__":
    main()
