"""
store.py
Persists the current feature tree per project, versioned (Phase 2 item 1),
and owns the production request log (Phase 3 item 2). SQLite: this is a
single-writer-at-a-time workload per project, and a file-based store
avoids standing up another service for a small amount of structured data.

Undo/redo model: each project has a linear, append-only version list plus
a `current_version_index` pointer. Undo/redo just move the pointer.
Generating after an undo truncates the "future" versions beyond the
pointer before appending -- standard editor undo/redo semantics.

Auth status: steps 1-8 of the auth plan are in this file --
users/sessions (steps 1-4), get_current_user support (step 5, in
main.py), owner_id on projects (step 6), user_id on request_log (step
7), and the legacy-data backfill helpers used by
migrate_legacy_owner.py (step 8). Frontend auth support (steps 10-12)
is not implemented -- see SESSION_HANDOFF.md.

CHANGE: added rename_project() -- lets a project's display name be
updated in place (see llm-service/app/main.py's PATCH
/v1/projects/{id}). Only touches name/updated_at; version history and
current_version_index are untouched, same "cheap metadata edit" shape as
every other project-level field would be if one existed.

CHANGE (admin roles, step 1 of the flywheel-auth fix): added an
`is_admin` column on `users` and a `set_admin()` helper. This is schema
+ data-layer only -- nothing in main.py enforces or reads this yet (that's
the next step: a `get_current_admin_user` dependency and admin-scoped log
routes). The motivating gap: `/v1/logs*` is correctly scoped to
`user_id` (step 7), which means even a well-formed request from an
ordinary user's token could never see cross-user data -- the flywheel
miners need to see everyone's production events, which requires a
distinct privileged-caller concept, not just "any authenticated caller."
`is_admin` is that concept. Defaults to 0/False for every existing and
newly created user -- nobody is an admin until `set_admin()` (or its
future CLI wrapper) is run explicitly.
"""

from __future__ import annotations
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone


def hash_password(password: str, salt: str | None = None) -> str:
    """PBKDF2-HMAC-SHA256, stdlib only -- no bcrypt/argon2 dependency for
    what's still a small service. Returns "salt$hash" so verify_password
    needs nothing but the stored string."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt, _, _ = stored.partition("$")
    if not salt:
        return False
    return secrets.compare_digest(hash_password(password, salt), stored)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    owner_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    current_version_index INTEGER NOT NULL DEFAULT -1
);

CREATE TABLE IF NOT EXISTS versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_index INTEGER NOT NULL,
    prompt TEXT,
    json_ir TEXT NOT NULL,
    stats TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, version_index)
);

CREATE TABLE IF NOT EXISTS request_log (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    user_id TEXT,
    action TEXT NOT NULL,
    prompt TEXT,
    success INTEGER,
    error_type TEXT,
    error TEXT,
    attempts INTEGER,
    version_index INTEGER,
    failed_ir TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_log_project_time
    ON request_log(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_request_log_user_time
    ON request_log(user_id, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class ProjectNotFound(KeyError):
    pass


class UserNotFound(KeyError):
    pass


class ProjectStore:
    def __init__(self, db_path: str, session_lifetime_hours: float | None = None):
        """session_lifetime_hours: auth step 9 config knob. None (default)
        means sessions never passively expire -- opaque tokens don't need
        a signed expiry the way JWT would (revocation is already
        immediate via delete_session/logout, which removes the row
        outright), so this is a policy choice, not a security
        requirement. Set it if you want inactive sessions to eventually
        stop working on their own."""
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        self.session_lifetime_hours = session_lifetime_hours
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        # migration guards -- only matter for DB files created before the
        # column existed; a no-op (OperationalError swallowed) on fresh
        # DBs where SCHEMA above already created it
        for stmt in (
            "ALTER TABLE projects ADD COLUMN owner_id TEXT",
            "ALTER TABLE request_log ADD COLUMN user_id TEXT",
            "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_request_log_user_time ON request_log(user_id, created_at)")
        self._conn.commit()

    @contextmanager
    def _cursor(self):
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    # ------------------------------------------------------------------ #
    # projects
    # ------------------------------------------------------------------ #
    def create_project(self, name: str, owner_id: str | None = None) -> dict:
        pid = str(uuid.uuid4())
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO projects (id, owner_id, name, created_at, updated_at, current_version_index) "
                "VALUES (?, ?, ?, ?, ?, -1)",
                (pid, owner_id, name, now, now),
            )
        return {"id": pid, "owner_id": owner_id, "name": name, "created_at": now, "updated_at": now}

    def list_projects(self, owner_id: str | None = None) -> list[dict]:
        with self._cursor() as cur:
            if owner_id is not None:
                rows = cur.execute(
                    "SELECT id, owner_id, name, created_at, updated_at FROM projects "
                    "WHERE owner_id = ? ORDER BY updated_at DESC",
                    (owner_id,),
                ).fetchall()
            else:
                rows = cur.execute(
                    "SELECT id, owner_id, name, created_at, updated_at FROM projects ORDER BY updated_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def delete_project(self, project_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            return cur.rowcount > 0

    def rename_project(self, project_id: str, name: str) -> dict:
        """Renames a project in place. Only touches name/updated_at --
        current_version_index and version history are untouched, same
        "cheap metadata update" shape as any other project field edit
        would be if one existed. Raises ProjectNotFound if the id doesn't
        exist (or isn't owned by the caller -- that check happens one
        layer up, in main.py's _require_owned_project(), same as every
        other mutating project endpoint)."""
        now = _now()
        with self._cursor() as cur:
            self._get_project_row(cur, project_id)  # raises ProjectNotFound
            cur.execute(
                "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
                (name, now, project_id),
            )
            row = cur.execute(
                "SELECT id, owner_id, name, created_at, updated_at FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        return dict(row)

    def _get_project_row(self, cur, project_id: str):
        row = cur.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise ProjectNotFound(project_id)
        return row

    def get_project(self, project_id: str) -> dict:
        with self._cursor() as cur:
            proj = self._get_project_row(cur, project_id)
            versions = cur.execute(
                "SELECT id, version_index, prompt, created_at FROM versions "
                "WHERE project_id = ? ORDER BY version_index",
                (project_id,),
            ).fetchall()
            current = None
            if proj["current_version_index"] >= 0:
                current = cur.execute(
                    "SELECT * FROM versions WHERE project_id = ? AND version_index = ?",
                    (project_id, proj["current_version_index"]),
                ).fetchone()
        return {
            "id": proj["id"],
            "owner_id": proj["owner_id"],
            "name": proj["name"],
            "created_at": proj["created_at"],
            "updated_at": proj["updated_at"],
            "current_version_index": proj["current_version_index"],
            "version_count": len(versions),
            "can_undo": proj["current_version_index"] > 0,
            "can_redo": proj["current_version_index"] < len(versions) - 1,
            "history": [
                {"version_index": v["version_index"], "prompt": v["prompt"], "created_at": v["created_at"]}
                for v in versions
            ],
            "current": self._row_to_version(current),
        }

    # ------------------------------------------------------------------ #
    # users
    # ------------------------------------------------------------------ #
    def create_user(self, email: str, password: str) -> dict:
        uid = str(uuid.uuid4())
        now = _now()
        try:
            with self._cursor() as cur:
                cur.execute(
                    "INSERT INTO users (id, email, password_hash, is_admin, created_at) VALUES (?, ?, ?, 0, ?)",
                    (uid, email, hash_password(password), now),
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"email '{email}' already registered")
        return {"id": uid, "email": email, "is_admin": False, "created_at": now}

    def authenticate(self, email: str, password: str) -> dict | None:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT id, email, password_hash, is_admin, created_at FROM users WHERE email = ?",
                (email,),
            ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return {"id": row["id"], "email": row["email"], "is_admin": bool(row["is_admin"]),
                "created_at": row["created_at"]}

    def get_user(self, user_id: str) -> dict | None:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT id, email, is_admin, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return self._row_to_user(row)

    def get_user_by_email(self, email: str) -> dict | None:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT id, email, is_admin, created_at FROM users WHERE email = ?", (email,)
            ).fetchone()
        return self._row_to_user(row)

    @staticmethod
    def _row_to_user(row) -> dict | None:
        if row is None:
            return None
        return {"id": row["id"], "email": row["email"], "is_admin": bool(row["is_admin"]),
                "created_at": row["created_at"]}

    def set_admin(self, user_id: str, is_admin: bool) -> dict:
        """Grants or revokes admin status for a user. Data-layer only --
        no HTTP route calls this yet (that's the next step: a small CLI,
        same "dry-run-free but explicit and operator-driven" shape as
        migrate_legacy_owner.py, or a route gated behind an existing
        admin -- TBD). Raises UserNotFound if the id doesn't exist, same
        style as ProjectNotFound elsewhere in this file, so callers can't
        silently grant admin to a typo'd user id and get back an empty
        success."""
        with self._cursor() as cur:
            row = cur.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise UserNotFound(user_id)
            cur.execute(
                "UPDATE users SET is_admin = ? WHERE id = ?",
                (1 if is_admin else 0, user_id),
            )
            updated = cur.execute(
                "SELECT id, email, is_admin, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return self._row_to_user(updated)

    # ------------------------------------------------------------------ #
    # sessions (opaque, revocable tokens -- not JWT)
    # ------------------------------------------------------------------ #
    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                (token, user_id, _now()),
            )
        return token

    def verify_session(self, token: str) -> str | None:
        """Returns user_id if the token is valid and not expired, else
        None. Expiry is checked lazily here (not swept by a background
        job -- this service doesn't run one) and an expired row is
        deleted on read, same "checked lazily, cleaned up lazily"
        approach as the rest of this store. If session_lifetime_hours is
        None, every session is valid until explicitly logged out."""
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT user_id, created_at FROM sessions WHERE token = ?", (token,)
            ).fetchone()
        if row is None:
            return None
        if self.session_lifetime_hours is not None:
            age_hours = (datetime.now(timezone.utc) - _parse_dt(row["created_at"])).total_seconds() / 3600
            if age_hours > self.session_lifetime_hours:
                self.delete_session(token)
                return None
        return row["user_id"]

    def delete_session(self, token: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return cur.rowcount > 0

    def get_version(self, project_id: str, version_index: int) -> dict | None:
        """Read-only fetch of a SPECIFIC historical version, not just the
        current one -- needed by the flywheel miner. Never touches
        current_version_index."""
        with self._cursor() as cur:
            self._get_project_row(cur, project_id)  # raises ProjectNotFound
            row = cur.execute(
                "SELECT * FROM versions WHERE project_id = ? AND version_index = ?",
                (project_id, version_index),
            ).fetchone()
        return self._row_to_version(row)

    @staticmethod
    def _row_to_version(row) -> dict | None:
        if row is None:
            return None
        return {
            "id": row["id"],
            "version_index": row["version_index"],
            "prompt": row["prompt"],
            "json_ir": json.loads(row["json_ir"]),
            "stats": json.loads(row["stats"]) if row["stats"] else None,
            "created_at": row["created_at"],
        }

    # ------------------------------------------------------------------ #
    # versions / undo-redo
    # ------------------------------------------------------------------ #
    def add_version(self, project_id: str, json_ir: dict, prompt: str | None,
                     stats: dict | None) -> dict:
        with self._cursor() as cur:
            proj = self._get_project_row(cur, project_id)
            new_index = proj["current_version_index"] + 1
            cur.execute(
                "DELETE FROM versions WHERE project_id = ? AND version_index >= ?",
                (project_id, new_index),
            )
            vid = str(uuid.uuid4())
            now = _now()
            cur.execute(
                "INSERT INTO versions (id, project_id, version_index, prompt, json_ir, stats, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (vid, project_id, new_index, prompt, json.dumps(json_ir),
                 json.dumps(stats) if stats is not None else None, now),
            )
            cur.execute(
                "UPDATE projects SET current_version_index = ?, updated_at = ? WHERE id = ?",
                (new_index, now, project_id),
            )
            row = cur.execute(
                "SELECT * FROM versions WHERE project_id = ? AND version_index = ?",
                (project_id, new_index),
            ).fetchone()
        return self._row_to_version(row)

    def undo(self, project_id: str) -> dict | None:
        return self._move(project_id, -1)

    def redo(self, project_id: str) -> dict | None:
        return self._move(project_id, +1)

    def _move(self, project_id: str, delta: int) -> dict | None:
        with self._cursor() as cur:
            proj = self._get_project_row(cur, project_id)
            new_index = proj["current_version_index"] + delta
            if new_index < 0:
                return None
            max_row = cur.execute(
                "SELECT MAX(version_index) AS m FROM versions WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            max_index = max_row["m"]
            if max_index is None or new_index > max_index:
                return None
            now = _now()
            cur.execute(
                "UPDATE projects SET current_version_index = ?, updated_at = ? WHERE id = ?",
                (new_index, now, project_id),
            )
            row = cur.execute(
                "SELECT * FROM versions WHERE project_id = ? AND version_index = ?",
                (project_id, new_index),
            ).fetchone()
        return self._row_to_version(row)

    # ------------------------------------------------------------------ #
    # request log (Phase 3 item 2 / auth step 7: scoped by user_id)
    # ------------------------------------------------------------------ #
    def log_event(self, *, project_id: str | None, action: str, prompt: str | None = None,
                   success: bool | None = None, error_type: str | None = None,
                   error: str | None = None, attempts: int | None = None,
                   version_index: int | None = None, failed_ir: dict | None = None,
                   user_id: str | None = None) -> dict:
        """user_id is None for the stateless /v1/generate path (no auth
        there) and for any pre-migration row -- see list_events() /
        compute_outcomes() for how those legacy rows stay visible to any
        authenticated caller until migrate_legacy_owner.py (step 8) runs."""
        eid = str(uuid.uuid4())
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO request_log (id, project_id, user_id, action, prompt, success, "
                "error_type, error, attempts, version_index, failed_ir, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (eid, project_id, user_id, action, prompt,
                 None if success is None else int(success),
                 error_type, error, attempts, version_index,
                 json.dumps(failed_ir) if failed_ir is not None else None, now),
            )
        return {"id": eid, "created_at": now}

    def list_events(self, project_id: str | None = None, user_id: str | None = None,
                     limit: int = 200) -> list[dict]:
        conditions, params = [], []
        if project_id is not None:
            conditions.append("project_id = ?")
            params.append(project_id)
        if user_id is not None:
            # legacy rows (user_id IS NULL, predating step 7 / not yet
            # backfilled by step 8) stay visible to any authenticated
            # user -- same stopgap policy _require_owned_project() already
            # applies to owner_id=None projects
            conditions.append("(user_id = ? OR user_id IS NULL)")
            params.append(user_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._cursor() as cur:
            rows = cur.execute(
                f"SELECT * FROM request_log {where} ORDER BY created_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    @staticmethod
    def _row_to_event(row) -> dict:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "user_id": row["user_id"],
            "action": row["action"],
            "prompt": row["prompt"],
            "success": None if row["success"] is None else bool(row["success"]),
            "error_type": row["error_type"],
            "error": row["error"],
            "attempts": row["attempts"],
            "version_index": row["version_index"],
            "failed_ir": json.loads(row["failed_ir"]) if row["failed_ir"] else None,
            "created_at": row["created_at"],
        }

    def log_summary(self, user_id: str | None = None) -> dict:
        where = "WHERE user_id = ? OR user_id IS NULL" if user_id is not None else ""
        params = (user_id,) if user_id is not None else ()
        with self._cursor() as cur:
            total = cur.execute(
                f"SELECT COUNT(*) AS n FROM request_log {where}", params
            ).fetchone()["n"]
            by_action = cur.execute(
                f"SELECT action, COUNT(*) AS n, "
                f"SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS n_success, "
                f"AVG(attempts) AS avg_attempts "
                f"FROM request_log {where} GROUP BY action",
                params,
            ).fetchall()
        return {
            "total_events": total,
            "by_action": [
                {
                    "action": r["action"],
                    "count": r["n"],
                    "success_rate": (r["n_success"] / r["n"]) if r["n"] and r["n_success"] is not None else None,
                    "avg_attempts": r["avg_attempts"],
                }
                for r in by_action
            ],
        }

    def compute_outcomes(self, project_id: str | None = None, user_id: str | None = None,
                          limit: int = 500) -> list[dict]:
        """See earlier documentation of this method: outcome labels are a
        literal fact about event sequence, not a read of user intent."""
        events = self.list_events(project_id=project_id, user_id=user_id, limit=limit)
        events.sort(key=lambda e: e["created_at"])

        by_project: dict[str | None, list[dict]] = {}
        for e in events:
            by_project.setdefault(e["project_id"], []).append(e)

        results = []
        for pid, proj_events in by_project.items():
            for i, event in enumerate(proj_events):
                if event["action"] not in ("generate", "apply"):
                    continue
                nxt = proj_events[i + 1] if i + 1 < len(proj_events) else None
                if nxt is None:
                    outcome = "no_further_activity"
                elif nxt["action"] == "download":
                    outcome = "accepted"
                elif nxt["action"] == "apply":
                    outcome = "edited"
                elif nxt["action"] == "undo":
                    outcome = "undone"
                elif nxt["action"] in ("generate", "apply"):
                    outcome = "retried" if event["success"] is False else "continued"
                else:
                    outcome = "other"
                results.append({**event, "outcome": outcome})
        return results

    # ------------------------------------------------------------------ #
    # auth step 8: legacy data migration. Assigns pre-auth rows
    # (owner_id/user_id IS NULL) to a designated user rather than leaving
    # them permanently shared -- see migrate_legacy_owner.py, the script
    # that actually drives this.
    # ------------------------------------------------------------------ #
    def count_legacy_rows(self) -> dict:
        with self._cursor() as cur:
            n_projects = cur.execute(
                "SELECT COUNT(*) AS n FROM projects WHERE owner_id IS NULL"
            ).fetchone()["n"]
            n_events_migratable = cur.execute(
                "SELECT COUNT(*) AS n FROM request_log "
                "WHERE user_id IS NULL AND project_id IS NOT NULL"
            ).fetchone()["n"]
            n_events_stateless = cur.execute(
                "SELECT COUNT(*) AS n FROM request_log "
                "WHERE user_id IS NULL AND project_id IS NULL"
            ).fetchone()["n"]
        return {
            "legacy_projects": n_projects,
            "legacy_request_log_events_migratable": n_events_migratable,
            "legacy_request_log_events_stateless": n_events_stateless,
        }

    def backfill_legacy_ownership(self, default_user_id: str) -> dict:
        """Assigns every owner_id IS NULL project to default_user_id, and
        every user_id IS NULL request_log row that belongs to one of
        those (pre-update) legacy projects to the same user. request_log
        rows with NO project_id (the stateless /v1/generate path, which
        has never had a user concept) are left untouched -- there's no
        project to anchor them to, and guessing an owner would
        misattribute requests nobody authenticated for.

        Idempotent: only NULL columns are ever written, so a repeat or
        partial-failure rerun is safe. The legacy project id set is
        captured BEFORE the projects UPDATE so the request_log UPDATE
        below is scoped to exactly those (not to "whatever now has this
        owner_id", which could accidentally include already-owned rows
        created after migration started)."""
        with self._cursor() as cur:
            legacy_project_ids = [
                r["id"] for r in cur.execute(
                    "SELECT id FROM projects WHERE owner_id IS NULL"
                ).fetchall()
            ]
            cur.execute(
                "UPDATE projects SET owner_id = ? WHERE owner_id IS NULL",
                (default_user_id,),
            )
            n_projects = cur.rowcount

            n_events = 0
            if legacy_project_ids:
                placeholders = ",".join("?" for _ in legacy_project_ids)
                cur.execute(
                    f"UPDATE request_log SET user_id = ? "
                    f"WHERE user_id IS NULL AND project_id IN ({placeholders})",
                    (default_user_id, *legacy_project_ids),
                )
                n_events = cur.rowcount
        return {"projects_updated": n_projects, "request_log_events_updated": n_events}
