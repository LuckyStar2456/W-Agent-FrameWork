"""Durable preparation checkpoints with explicit uncertain-attempt retirement.

Ready checkpoints retain sensitive vectors. A pending checkpoint never expires or
automatically repeats embedding: cancellation may follow provider billing. Hosts
share one checkpoint database for coordination and own external worker shutdown.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from w_agent.knowledge_batches import KnowledgePreparationBatch
from w_agent.knowledge_index_journal import _digest, knowledge_index_manifest
from w_agent.knowledge_index_plans import (
    MAX_KNOWLEDGE_PLAN_BYTES, KnowledgeIndexPlanStore, PreparedKnowledgeIndexPlan,
    prepare_knowledge_index_plan, prepared_knowledge_plan_from_json,
)
from w_agent.knowledge_ingestion import _label
from w_agent.knowledge_sqlite import _worker
from w_agent.knowledge_vectors import KnowledgeVectorIndex, knowledge_document_embedding_text
from w_agent.vector_indexing import QdrantVectorWriter
from w_agent.vector_retrieval import AsyncTextEmbedder, _timeout

_APPLICATION_ID = 0x57414B52
_TABLE = ("CREATE TABLE knowledge_preparations (batch_digest TEXT NOT NULL, attempt_id TEXT NOT NULL, "
          "state TEXT NOT NULL, artifact_digest TEXT, payload TEXT, evidence_ref TEXT, "
          "PRIMARY KEY (batch_digest, attempt_id))")


class KnowledgePreparationRecoveryError(RuntimeError):
    """A checkpoint error does not establish whether embedding was billed."""


@dataclass(frozen=True, slots=True)
class KnowledgePreparationCheckpoint:
    batch_digest: str
    attempt_id: str
    state: str
    artifact: PreparedKnowledgeIndexPlan | None = field(default=None, repr=False)
    evidence_ref: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _digest(self.batch_digest)
        _label(self.attempt_id)
        if self.state not in {"pending", "ready", "abandoned"}:
            raise ValueError("invalid preparation state")
        if (self.state == "ready") != isinstance(self.artifact, PreparedKnowledgeIndexPlan):
            raise ValueError("ready preparation requires a verified artifact")
        if self.state == "abandoned":
            _label(self.evidence_ref)
        elif self.evidence_ref is not None:
            raise ValueError("only abandoned preparation has retirement evidence")

    def summary(self) -> dict[str, object]:
        return {"batch_digest": self.batch_digest, "attempt_id": self.attempt_id,
                "state": self.state, "artifact_digest": self.artifact.digest if self.artifact else None,
                "embedding_may_have_been_billed": True, "remote_state_verified": False}


class KnowledgePreparationStore(Protocol):
    async def inspect(self, batch_digest: str) -> tuple[KnowledgePreparationCheckpoint, ...]: ...

    async def begin(self, batch_digest: str, attempt_id: str, *, confirm_write: bool = False
                    ) -> KnowledgePreparationCheckpoint: ...

    async def complete(self, batch_digest: str, attempt_id: str, artifact: PreparedKnowledgeIndexPlan,
                       *, confirm_write: bool = False) -> KnowledgePreparationCheckpoint: ...


@dataclass(frozen=True, slots=True)
class SQLiteKnowledgePreparationStore:
    """Bounded, dedicated local checkpoint database; construction has no I/O."""

    database_path: Path = field(repr=False)
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (str, Path)) or not str(self.database_path).strip() or str(self.database_path) == ":memory:":
            raise ValueError("preparation database requires a local path")
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
                != [("table", "knowledge_preparations", _TABLE)]):
            raise KnowledgePreparationRecoveryError("knowledge-preparation-database-unsupported")

    async def initialize(self, *, confirm_create: bool = False) -> None:
        if confirm_create is not True:
            raise KnowledgePreparationRecoveryError("knowledge-preparation-create-not-authorized")
        await _worker(self._initialize)

    def _initialize(self) -> None:
        try:
            with closing(self._connect("rwc")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone() is None:
                    if db.execute("PRAGMA application_id").fetchone()[0] or db.execute("PRAGMA user_version").fetchone()[0]:
                        raise KnowledgePreparationRecoveryError("knowledge-preparation-database-unsupported")
                    db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    db.execute("PRAGMA user_version = 1")
                    db.execute(_TABLE)
                self._check(db)
        except KnowledgePreparationRecoveryError:
            raise
        except Exception:
            raise KnowledgePreparationRecoveryError("knowledge-preparation-initialization-failed") from None

    async def inspect(self, batch_digest: str) -> tuple[KnowledgePreparationCheckpoint, ...]:
        _digest(batch_digest)
        return await _worker(lambda: self._operate(batch_digest))

    async def list_checkpoints(self) -> tuple[KnowledgePreparationCheckpoint, ...]:
        return await _worker(lambda: self._operate(None))

    async def begin(self, batch_digest: str, attempt_id: str, *, confirm_write: bool = False
                    ) -> KnowledgePreparationCheckpoint:
        return await self._write(KnowledgePreparationCheckpoint(batch_digest, attempt_id, "pending"), confirm_write)

    async def complete(self, batch_digest: str, attempt_id: str, artifact: PreparedKnowledgeIndexPlan,
                       *, confirm_write: bool = False) -> KnowledgePreparationCheckpoint:
        return await self._write(KnowledgePreparationCheckpoint(batch_digest, attempt_id, "ready", artifact), confirm_write)

    async def abandon(self, batch_digest: str, attempt_id: str, *, evidence_ref: str,
                      confirm_inactive: bool = False, confirm_write: bool = False
                      ) -> KnowledgePreparationCheckpoint:
        """Retire a pending worker using host evidence; billing remains unknown.

        Host must stop/drain that worker before asserting inactivity. A late
        complete call is rejected, but this cannot stop a remote provider call.
        """
        if confirm_inactive is not True:
            raise KnowledgePreparationRecoveryError("knowledge-preparation-inactivity-required")
        return await self._write(KnowledgePreparationCheckpoint(
            batch_digest, attempt_id, "abandoned", evidence_ref=evidence_ref,
        ), confirm_write)

    async def _write(self, item: KnowledgePreparationCheckpoint, confirmed: bool) -> KnowledgePreparationCheckpoint:
        if confirmed is not True:
            raise KnowledgePreparationRecoveryError("knowledge-preparation-write-not-authorized")
        await _worker(lambda: self._operate(item.batch_digest, item))
        return item

    def _operate(self, batch_digest: str | None, update: KnowledgePreparationCheckpoint | None = None
                 ) -> tuple[KnowledgePreparationCheckpoint, ...]:
        try:
            with closing(self._connect("rw" if update else "ro")) as db, db:
                db.execute("BEGIN IMMEDIATE" if update else "BEGIN")
                self._check(db)
                count, size = db.execute("SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))), 0) FROM knowledge_preparations").fetchone()
                if count > 1024 or size > 256 * 1024 * 1024:
                    raise KnowledgePreparationRecoveryError("knowledge-preparation-capacity-exceeded")
                rows = db.execute(
                    "SELECT batch_digest, attempt_id, state, artifact_digest, "
                    "CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload END, evidence_ref "
                    "FROM knowledge_preparations WHERE (? IS NULL OR batch_digest = ?) ORDER BY batch_digest, attempt_id",
                    (MAX_KNOWLEDGE_PLAN_BYTES, batch_digest, batch_digest),
                )
                entries = []
                for batch, attempt, state, digest, payload, evidence in rows:
                    if state != "ready" and (digest is not None or payload is not None):
                        raise ValueError("unexpected preparation payload")
                    artifact = prepared_knowledge_plan_from_json(payload, expected_digest=digest) if state == "ready" else None
                    entries.append(KnowledgePreparationCheckpoint(batch, attempt, state, artifact, evidence))
                active = [item.batch_digest for item in entries if item.state != "abandoned"]
                if len(set(active)) != len(active):
                    raise ValueError("conflicting active preparation checkpoints")
                if update is None:
                    return tuple(entries)
                previous = next((item for item in entries if item.attempt_id == update.attempt_id), None)
                if update.state == "pending":
                    if previous is not None or active:
                        raise KnowledgePreparationRecoveryError("knowledge-preparation-already-attempted-or-active")
                    if count >= 1024:
                        raise KnowledgePreparationRecoveryError("knowledge-preparation-capacity-exceeded")
                elif previous is None or (previous.state != "pending" and previous != update):
                    raise KnowledgePreparationRecoveryError("knowledge-preparation-transition-conflict")
                payload = update.artifact.to_json() if update.artifact else None
                prior_bytes = len(previous.artifact.to_json().encode("utf-8")) if previous and previous.artifact else 0
                if size - prior_bytes + (len(payload.encode("utf-8")) if payload else 0) > 256 * 1024 * 1024:
                    raise KnowledgePreparationRecoveryError("knowledge-preparation-capacity-exceeded")
                values = (update.state, update.artifact.digest if update.artifact else None, payload,
                          update.evidence_ref, update.batch_digest, update.attempt_id)
                if previous is None:
                    db.execute("INSERT INTO knowledge_preparations (state, artifact_digest, payload, evidence_ref, batch_digest, attempt_id) VALUES (?, ?, ?, ?, ?, ?)", values)
                else:
                    db.execute("UPDATE knowledge_preparations SET state=?, artifact_digest=?, payload=?, evidence_ref=? WHERE batch_digest=? AND attempt_id=?", values)
                return (update,)
        except KnowledgePreparationRecoveryError:
            raise
        except Exception:
            raise KnowledgePreparationRecoveryError("knowledge-preparation-operation-failed") from None


async def prepare_recoverable_knowledge_plan(
    index: KnowledgeVectorIndex, embedder: AsyncTextEmbedder, writer: QdrantVectorWriter,
    checkpoints: KnowledgePreparationStore, plans: KnowledgeIndexPlanStore, *, attempt_id: str,
    document_ids: tuple[str | int, ...] | None = None, confirm_embedding: bool = False,
    confirm_write: bool = False,
) -> PreparedKnowledgeIndexPlan:
    """Resume a durable ready batch without embedding; otherwise prepare it once.

    Persist ready vectors before staging. A failed plan save is recoverable with
    zero provider calls; pending after a crash requires explicit host retirement.
    Batch granularity bounds rework, but does not retain individual partial vectors.
    """
    if confirm_write is not True:
        raise KnowledgePreparationRecoveryError("knowledge-preparation-write-not-authorized")
    _label(attempt_id)
    manifest = knowledge_index_manifest(index, writer)
    selected = document_ids if document_ids is not None else tuple(item.document_id for item in index.snapshot.documents)
    documents = {item.document_id: item for item in index.snapshot.documents}
    points = tuple(index.point_id(identity) for identity in selected)
    width = sum(len(knowledge_document_embedding_text(documents[identity]).encode("utf-8")) for identity in selected)
    batch = KnowledgePreparationBatch(manifest.digest, selected, points, width)
    if width > 1024 * 1024 or len(points) * index.dimensions > 1024 * 1024:
        raise KnowledgePreparationRecoveryError("knowledge-preparation-batch-too-large")
    entries = await checkpoints.inspect(batch.digest)
    active = [item for item in entries if item.state != "abandoned"]
    if len(active) > 1:
        raise KnowledgePreparationRecoveryError("knowledge-preparation-checkpoints-invalid")
    if active:
        checkpoint = active[0]
        if checkpoint.state != "ready":
            raise KnowledgePreparationRecoveryError("knowledge-preparation-pending-needs-review")
        artifact = checkpoint.artifact
        if (artifact.manifest != manifest or tuple(point.point_id for point in artifact.plan.points) != points
                or writer.plan(artifact.plan.points) != artifact.plan):
            raise KnowledgePreparationRecoveryError("knowledge-preparation-artifact-mismatch")
    else:
        if confirm_embedding is not True:
            raise KnowledgePreparationRecoveryError("knowledge-preparation-embedding-not-authorized")
        checkpoint = await checkpoints.begin(batch.digest, attempt_id, confirm_write=True)
        if checkpoint != KnowledgePreparationCheckpoint(batch.digest, attempt_id, "pending"):
            raise KnowledgePreparationRecoveryError("knowledge-preparation-reservation-invalid")
        artifact = await prepare_knowledge_index_plan(
            index, embedder, writer, document_ids=selected, confirm_embedding=True,
        )
        checkpoint = await checkpoints.complete(batch.digest, attempt_id, artifact, confirm_write=True)
        if checkpoint != KnowledgePreparationCheckpoint(batch.digest, attempt_id, "ready", artifact):
            raise KnowledgePreparationRecoveryError("knowledge-preparation-checkpoint-invalid")
    saved_digest = await plans.save(artifact, confirm_write=True)
    if saved_digest != artifact.digest:
        raise KnowledgePreparationRecoveryError("knowledge-preparation-staging-mismatch")
    return artifact
