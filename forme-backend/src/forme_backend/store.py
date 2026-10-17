from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "forme.sqlite3"
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS uploads (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    expected_bytes INTEGER NOT NULL,
                    actual_bytes INTEGER,
                    sha256 TEXT,
                    status TEXT NOT NULL,
                    reason_code TEXT,
                    next_action TEXT,
                    review_notes TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads(status);
                CREATE TABLE IF NOT EXISTS customer_sessions (
                    id TEXT PRIMARY KEY,
                    authenticated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS submissions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES customer_sessions(id),
                    upload_id TEXT NOT NULL UNIQUE REFERENCES uploads(id),
                    color TEXT NOT NULL,
                    material TEXT NOT NULL,
                    template_id TEXT NOT NULL DEFAULT '01',
                    inspiration TEXT NOT NULL,
                    inspiration_image_name TEXT,
                    inspiration_image_type TEXT,
                    inspiration_image_bytes INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_submissions_session_created ON submissions(session_id, created_at);
                CREATE TABLE IF NOT EXISTS workflow_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    upload_id TEXT NOT NULL REFERENCES uploads(id),
                    status TEXT NOT NULL,
                    reason_code TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_upload ON workflow_events(upload_id, id);
                CREATE TABLE IF NOT EXISTS model_jobs (
                    id TEXT PRIMARY KEY,
                    submission_id TEXT NOT NULL UNIQUE REFERENCES submissions(id),
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    reason_code TEXT,
                    next_action TEXT,
                    metrics_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_model_jobs_status ON model_jobs(status);
                CREATE TABLE IF NOT EXISTS model_job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES model_jobs(id),
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    reason_code TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_model_job_events_job ON model_job_events(job_id,id);
                CREATE TABLE IF NOT EXISTS view_reviews (
                    submission_id TEXT PRIMARY KEY REFERENCES submissions(id),
                    status TEXT NOT NULL,
                    result_json TEXT,
                    updated_at TEXT NOT NULL
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(uploads)")}
            if "review_notes" not in columns:
                db.execute("ALTER TABLE uploads ADD COLUMN review_notes TEXT")
            if "session_id" not in columns:
                db.execute("ALTER TABLE uploads ADD COLUMN session_id TEXT")
            submission_columns = {row["name"] for row in db.execute("PRAGMA table_info(submissions)")}
            if "template_id" not in submission_columns:
                db.execute("ALTER TABLE submissions ADD COLUMN template_id TEXT NOT NULL DEFAULT '01'")
            session_columns = {row["name"] for row in db.execute("PRAGMA table_info(customer_sessions)")}
            if "authenticated" not in session_columns:
                db.execute("ALTER TABLE customer_sessions ADD COLUMN authenticated INTEGER NOT NULL DEFAULT 0")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def create_session(self, session_id: str) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO customer_sessions(id,authenticated,created_at) VALUES(?,?,?)", (session_id, 1, now()))

    def session_exists(self, session_id: str) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM customer_sessions WHERE id=? AND authenticated=1 AND datetime(created_at)>=datetime('now','-7 days')", (session_id,)).fetchone() is not None

    def revoke_session(self, session_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM customer_sessions WHERE id=?", (session_id,))

    def create_upload(self, upload_id: str, filename: str, content_type: str, size: int, session_id: str | None = None) -> dict[str, Any]:
        timestamp = now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO uploads(id,session_id,filename,content_type,expected_bytes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (upload_id, session_id, filename, content_type, size, "initiated", timestamp, timestamp),
            )
            db.execute(
                "INSERT INTO workflow_events(upload_id,status,created_at) VALUES(?,?,?)",
                (upload_id, "initiated", timestamp),
            )
        return self.get_upload(upload_id)

    def get_upload(self, upload_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "null")
        return result

    def transition(self, upload_id: str, source: str, target: str, **updates: Any) -> bool:
        allowed = {"actual_bytes", "sha256", "reason_code", "next_action", "review_notes", "metadata_json"}
        if set(updates) - allowed:
            raise ValueError("Unexpected upload update field")
        columns = ["status=?", "updated_at=?"] + [f"{key}=?" for key in updates]
        values = [target, now(), *updates.values(), upload_id, source]
        with self._connect() as db:
            result = db.execute(
                f"UPDATE uploads SET {', '.join(columns)} WHERE id=? AND status=?", values
            )
            if result.rowcount == 1:
                db.execute(
                    "INSERT INTO workflow_events(upload_id,status,reason_code,note,created_at) VALUES(?,?,?,?,?)",
                    (upload_id, target, updates.get("reason_code"), updates.get("review_notes"), now()),
                )
            return result.rowcount == 1

    def claim_uploaded(self) -> dict[str, Any] | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM uploads WHERE status='uploaded' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            db.execute("UPDATE uploads SET status='validating', updated_at=? WHERE id=?", (now(), row["id"]))
            db.execute("INSERT INTO workflow_events(upload_id,status,created_at) VALUES(?,?,?)", (row["id"], "validating", now()))
            upload_id = row["id"]
        return self.get_upload(upload_id)

    def claim_for_validation(self, upload_id: str) -> dict[str, Any] | None:
        if self.transition(upload_id, "uploaded", "validating"):
            return self.get_upload(upload_id)
        return None

    def list_uploads(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, filename, expected_bytes, actual_bytes, status, reason_code, created_at, updated_at "
                "FROM uploads ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def requeue_interrupted_validation(self) -> int:
        """For the single-worker MVP, retry items left in validating after a worker restart."""
        with self._connect() as db:
            result = db.execute(
                "UPDATE uploads SET status='uploaded', updated_at=? WHERE status='validating'", (now(),)
            )
            return result.rowcount

    def create_submission(self, submission_id: str, session_id: str, upload_id: str, color: str, material: str, inspiration: str, template_id: str = "01") -> dict[str, Any]:
        timestamp = now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO submissions(id,session_id,upload_id,color,material,template_id,inspiration,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (submission_id, session_id, upload_id, color, material, template_id, inspiration, timestamp, timestamp),
            )
        return self.get_submission(submission_id)

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            events = db.execute(
                "SELECT status,reason_code,note,created_at FROM workflow_events WHERE upload_id=? ORDER BY id",
                (result["upload_id"],),
            ).fetchall()
        result["upload"] = self.get_upload(result["upload_id"])
        result["events"] = [dict(event) for event in events]
        return result

    def list_submissions(self, session_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = (
            "SELECT s.id,s.session_id,s.upload_id,s.color,s.material,s.template_id,s.inspiration,s.inspiration_image_name,"
            "s.created_at,u.filename,u.actual_bytes,u.status,u.reason_code "
            "FROM submissions s JOIN uploads u ON u.id=s.upload_id"
        )
        params: list[Any] = []
        if session_id is not None:
            query += " WHERE s.session_id=?"
            params.append(session_id)
        query += " ORDER BY s.created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def attach_inspiration(self, submission_id: str, filename: str, content_type: str, byte_size: int) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE submissions SET inspiration_image_name=?,inspiration_image_type=?,inspiration_image_bytes=?,updated_at=? WHERE id=?",
                (filename, content_type, byte_size, now(), submission_id),
            )

    def create_model_job(self, job_id: str, submission_id: str) -> dict[str, Any]:
        timestamp = now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO model_jobs(id,submission_id,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (job_id, submission_id, "queued", "queued", timestamp, timestamp),
            )
            db.execute(
                "INSERT INTO model_job_events(job_id,status,stage,created_at) VALUES(?,?,?,?)",
                (job_id, "queued", "queued", timestamp),
            )
        return self.get_model_job(job_id)

    def get_model_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM model_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return None
            events = db.execute(
                "SELECT status,stage,reason_code,note,created_at FROM model_job_events WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        result = dict(row)
        result["metrics"] = json.loads(result.pop("metrics_json") or "null")
        result["events"] = [dict(event) for event in events]
        return result

    def model_job_for_submission(self, submission_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT id FROM model_jobs WHERE submission_id=?", (submission_id,)).fetchone()
        return self.get_model_job(row["id"]) if row else None

    def claim_model_job(self) -> dict[str, Any] | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM model_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                return None
            timestamp = now()
            db.execute("UPDATE model_jobs SET status='running',stage='extracting_frames',updated_at=? WHERE id=?", (timestamp, row["id"]))
            db.execute(
                "INSERT INTO model_job_events(job_id,status,stage,created_at) VALUES(?,?,?,?)",
                (row["id"], "running", "extracting_frames", timestamp),
            )
        return self.get_model_job(row["id"])

    def transition_model_job(self, job_id: str, stage: str, *, status: str = "running", reason_code: str | None = None,
                             next_action: str | None = None, metrics: dict | None = None, note: str | None = None) -> None:
        timestamp = now()
        with self._connect() as db:
            db.execute(
                "UPDATE model_jobs SET status=?,stage=?,reason_code=?,next_action=?,metrics_json=COALESCE(?,metrics_json),updated_at=? WHERE id=?",
                (status, stage, reason_code, next_action, json.dumps(metrics) if metrics is not None else None, timestamp, job_id),
            )
            db.execute(
                "INSERT INTO model_job_events(job_id,status,stage,reason_code,note,created_at) VALUES(?,?,?,?,?,?)",
                (job_id, status, stage, reason_code, note, timestamp),
            )

    def requeue_interrupted_model_jobs(self) -> int:
        with self._connect() as db:
            result = db.execute("UPDATE model_jobs SET status='queued',stage='queued',updated_at=? WHERE status='running'", (now(),))
            return result.rowcount

    def get_view_review(self, submission_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM view_reviews WHERE submission_id=?", (submission_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["data"] = json.loads(result.pop("result_json") or "{}")
        return result

    def set_view_review(self, submission_id: str, status: str, data: dict | None = None) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO view_reviews(submission_id,status,result_json,updated_at) VALUES(?,?,?,?) "
                       "ON CONFLICT(submission_id) DO UPDATE SET status=excluded.status,result_json=excluded.result_json,updated_at=excluded.updated_at",
                       (submission_id, status, json.dumps(data or {}, ensure_ascii=False), now()))
