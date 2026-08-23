"""
verify_auth_e2e.py
Auth plan step 14: end-to-end verification against a running llm-service.
Exercises exactly the checks the plan calls out:

  1. signup -> login -> create project (user A)
  2. a second user (user B) cannot see or access user A's project --
     GET/DELETE both 404, and it's absent from user B's project list
  3. request log scoping (step 7): user B's /v1/logs doesn't show user
     A's events for that project
  4. migration (step 8) left no orphaned legacy rows -- flagged as a
     manual step (see below), not automated

Talks to a REAL, running llm-service over HTTP -- this is integration
verification, not a unit test. Creates two throwaway users (random
suffixed emails) and one throwaway project, and deletes the project as
part of the run; it does not delete the users (no such endpoint exists).

Usage:
    python verify_auth_e2e.py --llm-service-url http://localhost:8001
    python verify_auth_e2e.py --llm-service-url http://localhost:8001 --expect-migrated

Exit 0 if every automated check passes, 1 otherwise -- usable as a CI/
deploy gate, same convention as mine_flywheel_gate.py.

NOT executed in the sandbox this was authored in -- no running llm-service
here (no network, no Docker). Run this against a real stack (`docker
compose up`, or at minimum llm-service + geometry) before trusting auth
is actually enforced end-to-end. Stdlib only, same as the mine_flywheel_*
scripts this mirrors.
"""

from __future__ import annotations
import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.request


class Check:
    def __init__(self, name: str):
        self.name = name
        self.passed: bool | None = None  # None = not automatable, see _manual_check
        self.detail = ""


def _request(method: str, url: str, body: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach {url}: {e}") from e
    parsed = None
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
    return status, parsed


def _manual_check(name: str, detail: str) -> Check:
    c = Check(name)
    c.passed = None
    c.detail = detail
    return c


def run(base_url: str, expect_migrated: bool) -> list[Check]:
    checks: list[Check] = []

    def record(name: str, condition, detail: str = "") -> bool:
        c = Check(name)
        c.passed = bool(condition)
        c.detail = detail
        checks.append(c)
        return c.passed

    suffix = secrets.token_hex(4)
    email_a = f"verify-a-{suffix}@example.test"
    email_b = f"verify-b-{suffix}@example.test"
    password = "verify-password-123"

    # ---- 1. signup -> login -> create project (user A) ----
    status, body = _request("POST", f"{base_url}/v1/auth/signup", {"email": email_a, "password": password})
    if not record("signup user A", status == 200 and body and "token" in body, f"status={status}"):
        return checks

    status, body = _request("POST", f"{base_url}/v1/auth/login", {"email": email_a, "password": password})
    if not record("login user A", status == 200 and body and "token" in body, f"status={status}"):
        return checks
    token_a = body["token"]

    status, body = _request("POST", f"{base_url}/v1/projects", {"name": "verify-project"}, token=token_a)
    if not record("create project as user A", status == 200 and body and "id" in body, f"status={status}"):
        return checks
    project_id = body["id"]

    status, body = _request("POST", f"{base_url}/v1/auth/signup", {"email": email_b, "password": password})
    if not record("signup user B", status == 200 and body and "token" in body, f"status={status}"):
        return checks
    token_b = body["token"]

    # ---- 2. user B cannot see/access user A's project ----
    status, _body = _request("GET", f"{base_url}/v1/projects/{project_id}", token=token_b)
    record("user B GET user A's project -> 404", status == 404, f"status={status}")

    status, body = _request("GET", f"{base_url}/v1/projects", token=token_b)
    visible_ids = {p["id"] for p in body} if isinstance(body, list) else set()
    record("user A's project absent from user B's project list",
           project_id not in visible_ids, f"status={status} n_visible={len(visible_ids)}")

    status, _body = _request("DELETE", f"{base_url}/v1/projects/{project_id}", token=token_b)
    record("user B DELETE user A's project -> 404", status == 404, f"status={status}")

    # confirms the 404s above are real ownership checks, not a broken route
    status, body = _request("GET", f"{base_url}/v1/projects/{project_id}", token=token_a)
    record("user A can still GET their own project",
           status == 200 and body and body.get("id") == project_id, f"status={status}")

    # ---- 3. request log scoping (step 7) ----
    status, body = _request("GET", f"{base_url}/v1/logs?project_id={project_id}", token=token_a)
    n_a = len(body) if isinstance(body, list) else -1
    record("user A sees their own request_log events for this project",
           status == 200 and n_a > 0, f"status={status} n={n_a}")

    status, body = _request("GET", f"{base_url}/v1/logs?project_id={project_id}", token=token_b)
    n_b = len(body) if isinstance(body, list) else -1
    record("user B sees none of user A's request_log events for this project",
           status == 200 and n_b == 0, f"status={status} n={n_b}")

    # cleanup -- delete the verification project as its rightful owner
    _request("DELETE", f"{base_url}/v1/projects/{project_id}", token=token_a)

    # ---- 4. migration (step 8) left no orphaned legacy rows ----
    # Not automatable over HTTP: there is no endpoint exposing
    # owner_id/user_id IS NULL counts (deliberately -- that's operator/DB
    # data, not something to hand to any authenticated user). Left as an
    # explicit manual step rather than silently skipped.
    if expect_migrated:
        checks.append(_manual_check(
            "migration (step 8) left no orphaned legacy rows",
            "Run: python llm-service/app/migrate_legacy_owner.py "
            "--db-path <path> --owner-email <email>  (omit --apply -- dry "
            "run only) and confirm both legacy counts report 0.",
        ))

    return checks


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm-service-url", default=os.environ.get("LLM_SERVICE_URL", "http://localhost:8001"))
    ap.add_argument("--expect-migrated", action="store_true",
                     help="also print the manual step for confirming step 8's "
                          "migration left no orphaned rows")
    args = ap.parse_args()

    base_url = args.llm_service_url.rstrip("/")
    try:
        checks = run(base_url, args.expect_migrated)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"\nverify_auth_e2e -- {base_url}\n")
    n_pass = n_fail = n_manual = 0
    for c in checks:
        if c.passed is None:
            n_manual += 1
            print(f"  [MANUAL] {c.name}\n           {c.detail}")
        elif c.passed:
            n_pass += 1
            print(f"  [PASS]   {c.name}  ({c.detail})")
        else:
            n_fail += 1
            print(f"  [FAIL]   {c.name}  ({c.detail})")

    print(f"\n{n_pass} passed, {n_fail} failed, {n_manual} manual step(s) flagged")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
