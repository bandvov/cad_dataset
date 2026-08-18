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

NOTE: no auth/multi-tenancy yet (no users table, no owner_id) -- that's
planned but not implemented. See the auth implementation steps discussed
separately; this file intentionally does not contain a partial attempt.
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
from datetime import datetime, timezone


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
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectNotFound(KeyError):
    pass


class ProjectStore:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        try:
            self._conn.execute("ALTER TABLE projects ADD COLUMN owner_id TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists -- fine, this only matters for pre-existing DB files
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id)")
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
    def create_project(self, name: str) -> dict:
        pid = str(uuid.uuid4())
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO projects (id, name, created_at, updated_at, current_version_index) "
                "VALUES (?, ?, ?, ?, -1)",
                (pid, name, now, now),
            )
        return {"id": pid, "name": name, "created_at": now, "updated_at": now}

    def list_projects(self) -> list[dict]:
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT id, name, created_at, updated_at FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_project(self, project_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            return cur.rowcount > 0

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
        """Returns user_id if the token is valid, else None."""
        with self._cursor() as cur:
            row = cur.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)).fetchone()
        return row["user_id"] if row else None

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
    # request log (Phase 3 item 2)
    # ------------------------------------------------------------------ #
    def log_event(self, *, project_id: str | None, action: str, prompt: str | None = None,
                   success: bool | None = None, error_type: str | None = None,
                   error: str | None = None, attempts: int | None = None,
                   version_index: int | None = None, failed_ir: dict | None = None) -> dict:
        eid = str(uuid.uuid4())
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO request_log (id, project_id, action, prompt, success, "
                "error_type, error, attempts, version_index, failed_ir, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (eid, project_id, action, prompt,
                 None if success is None else int(success),
                 error_type, error, attempts, version_index,
                 json.dumps(failed_ir) if failed_ir is not None else None, now),
            )
        return {"id": eid, "created_at": now}

    def list_events(self, project_id: str | None = None, limit: int = 200) -> list[dict]:
        with self._cursor() as cur:
            if project_id is not None:
                rows = cur.execute(
                    "SELECT * FROM request_log WHERE project_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = cur.execute(
                    "SELECT * FROM request_log ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_event(r) for r in rows]

    @staticmethod
    def _row_to_event(row) -> dict:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
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

    def log_summary(self) -> dict:
        with self._cursor() as cur:
            total = cur.execute("SELECT COUNT(*) AS n FROM request_log").fetchone()["n"]
            by_action = cur.execute(
                "SELECT action, COUNT(*) AS n, "
                "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS n_success, "
                "AVG(attempts) AS avg_attempts "
                "FROM request_log GROUP BY action"
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

    def compute_outcomes(self, project_id: str | None = None, limit: int = 500) -> list[dict]:
        """See earlier documentation of this method: outcome labels are a
        literal fact about event sequence, not a read of user intent."""
        events = self.list_events(project_id=project_id, limit=limit)
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
