"""Append-only SQLite staging of exact knowledge-vector plans in a separate DB."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from w_agent.knowledge_index_journal import _digest
from w_agent.knowledge_plan_catalog import KnowledgeIndexPlanInfo
from w_agent.knowledge_index_plans import (
    MAX_KNOWLEDGE_PLAN_BYTES, KnowledgeIndexPlanError, PreparedKnowledgeIndexPlan,
    prepared_knowledge_plan_from_json,
)
from w_agent.knowledge_sqlite import _worker
from w_agent.vector_retrieval import _timeout

_APPLICATION_ID = 0x57414B50
_TABLE = "CREATE TABLE knowledge_index_plans (artifact_digest TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL)"


@dataclass(frozen=True, slots=True)
class SQLiteKnowledgeIndexPlanStore:
    """Explicit creation, digest-keyed insert-only plans, no implicit migration.

    Trusted local DB/directory required. Contains sensitive vectors, not API keys
    or source bodies. Limits bound payload admission, not SQLite disk/WAL usage.
    No connections survive an operation; cancellation drains started workers.
    """

    database_path: Path = field(repr=False)
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (str, Path)) or not str(self.database_path).strip() or str(self.database_path) == ":memory:":
            raise ValueError("knowledge plan store requires a local path")
        object.__setattr__(self, "database_path", Path(self.database_path).absolute())
        _timeout(self.timeout)

    def _connect(self, mode: str) -> sqlite3.Connection:
        db = sqlite3.connect(f"{self.database_path.as_uri()}?mode={mode}", uri=True,
                             timeout=self.timeout, isolation_level=None)
        try:
            db.execute("PRAGMA trusted_schema = OFF")
        except Exception:
            db.close()
            raise
        return db

    @staticmethod
    def _check(db: sqlite3.Connection) -> None:
        if (db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != 1
                or db.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
                != [("table", "knowledge_index_plans", _TABLE)]):
            raise KnowledgeIndexPlanError("knowledge-plan-database-unsupported")

    async def initialize(self, *, confirm_create: bool = False) -> None:
        if confirm_create is not True:
            raise KnowledgeIndexPlanError("knowledge-plan-creation-not-authorized")
        await _worker(self._initialize)

    def _initialize(self) -> None:
        try:
            with closing(self._connect("rwc")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone() is None:
                    if db.execute("PRAGMA application_id").fetchone()[0] != 0 or db.execute("PRAGMA user_version").fetchone()[0] != 0:
                        raise KnowledgeIndexPlanError("knowledge-plan-database-unsupported")
                    db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    db.execute("PRAGMA user_version = 1")
                    db.execute(_TABLE)
                self._check(db)
        except KnowledgeIndexPlanError:
            raise
        except Exception:
            raise KnowledgeIndexPlanError("knowledge-plan-initialization-failed") from None

    async def save(self, artifact: PreparedKnowledgeIndexPlan, *, confirm_write: bool = False) -> str:
        if confirm_write is not True or not isinstance(artifact, PreparedKnowledgeIndexPlan):
            raise KnowledgeIndexPlanError("knowledge-plan-save-not-authorized")
        digest, payload = artifact.digest, artifact.to_json()
        await _worker(lambda: self._operate(digest, payload))
        return digest

    async def validate_existing(self) -> None:
        """Read-only schema preflight; not a reservation or disk-capacity guarantee."""
        await _worker(self._validate_existing)

    def _validate_existing(self) -> None:
        try:
            with closing(self._connect("ro")) as db:
                self._check(db)
        except KnowledgeIndexPlanError:
            raise
        except Exception:
            raise KnowledgeIndexPlanError("knowledge-plan-store-preflight-failed") from None

    async def load(self, artifact_digest: str) -> PreparedKnowledgeIndexPlan:
        try:
            _digest(artifact_digest)
        except Exception:
            raise KnowledgeIndexPlanError("knowledge-plan-identity-invalid") from None
        return await _worker(lambda: self._operate(artifact_digest))

    async def list_plans(self) -> tuple[KnowledgeIndexPlanInfo, ...]:
        """Verify all staged artifacts in one bounded read transaction, retaining no vectors."""
        return await _worker(self._list_plans)

    def _list_plans(self) -> tuple[KnowledgeIndexPlanInfo, ...]:
        try:
            with closing(self._connect("ro")) as db:
                db.execute("BEGIN")
                self._check(db)
                count, size = db.execute("SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))), 0) FROM knowledge_index_plans").fetchone()
                if count > 128 or size > 256 * 1024 * 1024:
                    raise KnowledgeIndexPlanError("knowledge-plan-catalog-limit-exceeded")
                cursor = db.execute(
                    "SELECT CASE WHEN length(CAST(artifact_digest AS BLOB)) = 64 THEN artifact_digest END, "
                    "CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload END "
                    "FROM knowledge_index_plans ORDER BY artifact_digest LIMIT 129", (MAX_KNOWLEDGE_PLAN_BYTES,),
                )
                entries = []
                for digest, payload in cursor:
                    artifact = prepared_knowledge_plan_from_json(payload, expected_digest=digest)
                    entries.append(KnowledgeIndexPlanInfo.from_artifact(artifact))
                    del artifact  # Keep only identity metadata across rows.
                return tuple(entries)
        except KnowledgeIndexPlanError:
            raise
        except Exception:
            raise KnowledgeIndexPlanError("knowledge-plan-catalog-read-failed") from None

    def _operate(self, digest: str, payload: str | None = None) -> PreparedKnowledgeIndexPlan:
        try:
            with closing(self._connect("rw" if payload is not None else "ro")) as db, db:
                db.execute("BEGIN IMMEDIATE" if payload is not None else "BEGIN")
                self._check(db)
                row = db.execute(
                    "SELECT CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload END "
                    "FROM knowledge_index_plans WHERE artifact_digest = ?", (MAX_KNOWLEDGE_PLAN_BYTES, digest),
                ).fetchone()
                if row is not None:
                    existing = prepared_knowledge_plan_from_json(row[0], expected_digest=digest)
                    if payload is not None and payload != row[0]:
                        raise KnowledgeIndexPlanError("knowledge-plan-content-conflict")
                    return existing
                if payload is None:
                    raise KnowledgeIndexPlanError("knowledge-plan-not-found")
                artifact = prepared_knowledge_plan_from_json(payload, expected_digest=digest)
                count, size = db.execute("SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))), 0) FROM knowledge_index_plans").fetchone()
                if count >= 128 or size + len(payload.encode("utf-8")) > 256 * 1024 * 1024:
                    raise KnowledgeIndexPlanError("knowledge-plan-store-capacity-exceeded")
                db.execute("INSERT INTO knowledge_index_plans VALUES (?, ?)", (digest, payload))
                return artifact
        except KnowledgeIndexPlanError:
            raise
        except Exception:
            raise KnowledgeIndexPlanError("knowledge-plan-store-operation-failed") from None


async def inspect_stored_knowledge_plan(
    database: str | Path, artifact_digest: str, *, confirm_read: bool = False, include_target: bool = False,
) -> dict[str, object]:
    """Local read-only management view; no vector output, execution or initialization."""
    if confirm_read is not True or type(include_target) is not bool:
        raise KnowledgeIndexPlanError("knowledge-plan-inspection-not-authorized")
    _digest(artifact_digest)
    artifact = await SQLiteKnowledgeIndexPlanStore(database).load(artifact_digest)
    return artifact.summary(include_target=include_target)
