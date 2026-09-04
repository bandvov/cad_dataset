"""
make_admin.py
Flywheel-auth fix, step 4 of 5: CLI to grant (or revoke) admin status on
an existing user, driving store.py's set_admin() (step 1). Same
dry-run-by-default, explicit --apply shape as migrate_legacy_owner.py --
this is a privilege escalation, so it should never happen as a silent
side effect of running the script.

Unlike migrate_legacy_owner.py's legacy-user bootstrap, this does NOT
create an account -- the target user must already exist (sign up
normally first). Guessing/creating an admin account here would be a much
bigger footgun than this script's counterpart.

Usage:
    # dry run (default) -- prints current status, changes nothing
    python make_admin.py --db-path /data/cad_sessions.db --email admin@yourcompany.example

    # grant
    python make_admin.py --db-path /data/cad_sessions.db \
        --email admin@yourcompany.example --apply

    # revoke
    python make_admin.py --db-path /data/cad_sessions.db \
        --email admin@yourcompany.example --revoke --apply
"""

from __future__ import annotations
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import ProjectStore


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db-path", default=os.environ.get("DB_PATH", "/data/cad_sessions.db"))
    ap.add_argument("--email", required=True, help="email of an EXISTING user to grant/revoke admin on")
    ap.add_argument("--revoke", action="store_true", help="revoke admin instead of granting it")
    ap.add_argument("--apply", action="store_true",
                     help="actually write the change -- omit for a dry-run report only")
    args = ap.parse_args()

    store = ProjectStore(args.db_path)
    user = store.get_user_by_email(args.email)
    if user is None:
        print(f"no user found with email '{args.email}' -- this script does not create "
              f"accounts, sign up first")
        sys.exit(1)

    action = "revoke" if args.revoke else "grant"
    print(f"user {user['id']} ({user['email']}) -- current is_admin={user['is_admin']}")

    if user["is_admin"] == (not args.revoke):
        print(f"already {'admin' if user['is_admin'] else 'non-admin'} -- nothing to do")
        return

    if not args.apply:
        print(f"\ndry run only -- rerun with --apply to {action} admin")
        return

    updated = store.set_admin(user["id"], not args.revoke)
    verb = "revoked" if args.revoke else "granted"
    print(f"\n{verb} admin -- is_admin is now {updated['is_admin']}")


if __name__ == "__main__":
    main()
