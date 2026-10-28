"""Opt-in local, cross-process workflow pause requests using SQLite."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .control import _validate_run_id


class WorkflowPauseControlError(RuntimeError):
    """A pause request could not be read or changed safely."""


class SQLiteWorkflowPauseController:
    """Durable requests in one trusted local state root, keyed by exact run ID.

    Construction and absent-store reads do not create files. Request writes and
    clears are SQLite transactions; clearing never resumes or claims a run.
    Each operation opens its own connection, so instances may be used by other
    threads/processes. Queries use bounded local I/O (100 ms lock timeout), not
    an IPC service or a polling worker. Storage errors fail closed.

    This is not an execution lock, liveness registry, or an authorization
    boundary against another process able to write the same state directory.
    Use a local filesystem and one workflow execution owner per state root.
    Requests persist until explicitly cleared, including after completion.
    """

    def __init__(self, state_root: str | Path) -> None:
        self.database_path = Path(state_root).resolve() / "workflow-control.sqlite3"

    def request_pause(self, run_id: str) -> None:
        _validate_run_id(run_id)
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.database_path, timeout=0.1)) as db:
                with db:
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS workflow_pause_requests_v1 "
                        "(run_id TEXT PRIMARY KEY NOT NULL)"
                    )
                    db.execute(
                        "INSERT OR IGNORE INTO workflow_pause_requests_v1 "
                        "(run_id) VALUES (?)",
                        (run_id,),
                    )
        except (OSError, sqlite3.Error):
            raise WorkflowPauseControlError(
                "workflow pause request could not be persisted"
            ) from None

    def clear(self, run_id: str) -> None:
        _validate_run_id(run_id)
        try:
            if not self._exists():
                return
            # rw refuses to recreate a database removed between stat/connect.
            with closing(self._connect("rw")) as db:
                with db:
                    db.execute(
                        "DELETE FROM workflow_pause_requests_v1 WHERE run_id = ?",
                        (run_id,),
                    )
        except (OSError, sqlite3.Error):
            raise WorkflowPauseControlError(
                "workflow pause request could not be cleared"
            ) from None

    def is_pause_requested(self, run_id: str) -> bool:
        _validate_run_id(run_id)
        try:
            if not self._exists():
                return False
            with closing(self._connect("ro")) as db:
                return db.execute(
                    "SELECT 1 FROM workflow_pause_requests_v1 WHERE run_id = ?",
                    (run_id,),
                ).fetchone() is not None
        except (OSError, sqlite3.Error):
            raise WorkflowPauseControlError(
                "workflow pause request could not be read"
            ) from None

    def _exists(self) -> bool:
        try:
            self.database_path.stat()
        except FileNotFoundError:
            return False
        return True

    def _connect(self, mode: str) -> sqlite3.Connection:
        return sqlite3.connect(
            f"{self.database_path.as_uri()}?mode={mode}", uri=True, timeout=0.1
        )
