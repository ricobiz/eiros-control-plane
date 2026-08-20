from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

from .models import JobState, RenderJob, TERMINAL_STATES


class InvalidTransition(RuntimeError):
    pass


_ALLOWED: dict[JobState, set[JobState]] = {
    JobState.QUEUED: {JobState.PROVISIONING, JobState.CANCELLED, JobState.FAILED},
    JobState.PROVISIONING: {JobState.STAGING, JobState.QUEUED, JobState.FAILED, JobState.CANCELLED},
    JobState.STAGING: {JobState.RUNNING, JobState.QUEUED, JobState.FAILED, JobState.CANCELLED},
    JobState.RUNNING: {JobState.COLLECTING, JobState.FAILED, JobState.CANCELLED},
    JobState.COLLECTING: {JobState.DONE, JobState.RUNNING, JobState.FAILED, JobState.CANCELLED},
    JobState.DONE: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}


class JobStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    attempt_token TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    retries INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    output_path TEXT NOT NULL DEFAULT ''
                )
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row) -> RenderJob:
        return RenderJob(
            job_id=row["job_id"],
            attempt_token=row["attempt_token"],
            state=JobState(row["state"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            retries=int(row["retries"]),
            error=row["error"],
            output_path=row["output_path"],
        )

    def create_job(self) -> RenderJob:
        now = time.time()
        job = RenderJob(str(uuid.uuid4()), uuid.uuid4().hex, JobState.QUEUED, now, now)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs(job_id, attempt_token, state, created_at, updated_at, retries, error, output_path) VALUES(?,?,?,?,?,?,?,?)",
                (job.job_id, job.attempt_token, job.state.value, now, now, 0, "", ""),
            )
        return job

    def get_job(self, job_id: str) -> RenderJob:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._row(row)

    def transition(
        self,
        job_id: str,
        new_state: JobState,
        *,
        expected: JobState | None = None,
        error: str | None = None,
        output_path: str | None = None,
        increment_retries: bool = False,
    ) -> RenderJob:
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            current = JobState(row["state"])
            if expected is not None and current is not expected:
                raise InvalidTransition(f"expected {expected.value}, found {current.value}")
            if new_state not in _ALLOWED[current]:
                raise InvalidTransition(f"{current.value} -> {new_state.value} not allowed")
            retries = int(row["retries"]) + (1 if increment_retries else 0)
            conn.execute(
                "UPDATE jobs SET state=?, updated_at=?, retries=?, error=?, output_path=? WHERE job_id=?",
                (
                    new_state.value,
                    now,
                    retries,
                    row["error"] if error is None else error,
                    row["output_path"] if output_path is None else output_path,
                    job_id,
                ),
            )
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row(row)

    def list_active(self) -> list[RenderJob]:
        terminal = tuple(s.value for s in TERMINAL_STATES)
        q = f"SELECT * FROM jobs WHERE state NOT IN ({','.join('?' for _ in terminal)}) ORDER BY created_at"
        with self._connect() as conn:
            rows = conn.execute(q, terminal).fetchall()
        return [self._row(r) for r in rows]
