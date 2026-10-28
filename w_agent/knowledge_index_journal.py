"""Explicit snapshot-index manifests and durable local write observations.

This is not a remote-state verifier, execution lease, retry queue or distributed
transaction. Hosts own index authorization, database trust and reconciliation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from w_agent.knowledge_ingestion import _json, _label
from w_agent.knowledge_sqlite import _worker
from w_agent.knowledge_vectors import KnowledgeVectorIndex
from w_agent.vector_indexing import QdrantUpsertPlan, QdrantVectorWriter, QdrantWriteResult, VectorIndexWriteError
from w_agent.vector_retrieval import _integer, _point_id, _reject_constant, _timeout, _unique_object

_APPLICATION_ID = 0x57414B4A
_TABLE = "CREATE TABLE knowledge_index_journals (manifest_digest TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL)"
_MAX_PAYLOAD = 8 * 1024 * 1024
_OUTCOMES = {"pending", "completed", "acknowledged", "unknown", "not-sent"}


def _digest(value: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("knowledge index digest is invalid")


def _ids(value: tuple[str, ...], maximum: int) -> None:
    if not isinstance(value, tuple) or not 1 <= len(value) <= maximum:
        raise ValueError("knowledge index IDs must be a bounded nonempty tuple")
    if any(not isinstance(item, str) or _point_id(item) != item for item in value) or len(set(value)) != len(value):
        raise ValueError("knowledge index IDs must be unique canonical UUIDs")


class KnowledgeIndexJournalError(RuntimeError):
    """Fixed local-journal errors; neither failure nor cancellation proves no commit."""


@dataclass(frozen=True, slots=True)
class KnowledgeIndexManifest:
    """Expected identities/target without document bodies, vectors or API keys."""

    snapshot_digest: str
    embedding_key: str = field(repr=False)
    dimensions: int
    endpoint: str = field(repr=False)
    vector_name: str | None
    point_ids: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        _digest(self.snapshot_digest)
        _label(self.embedding_key)
        _integer(self.dimensions, 65536)
        _ids(self.point_ids, 1024)
        if self.vector_name is not None:
            _label(self.vector_name)
        if (not isinstance(self.endpoint, str) or len(self.endpoint) > 4096
                or any(ord(char) <= 32 or ord(char) == 127 for char in self.endpoint)):
            raise ValueError("knowledge index endpoint is invalid")
        parsed = urlsplit(self.endpoint)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment):
            raise ValueError("knowledge index endpoint is invalid")
        _ = parsed.port

    def to_dict(self) -> dict:
        return {"snapshot_digest": self.snapshot_digest, "embedding_key": self.embedding_key,
                "dimensions": self.dimensions, "endpoint": self.endpoint,
                "vector_name": self.vector_name, "point_ids": list(self.point_ids)}

    @property
    def digest(self) -> str:
        return hashlib.sha256(_json({"format": "wagent-knowledge-index-manifest-v1", **self.to_dict()}).encode("utf-8")).hexdigest()

    def validate_plan(self, plan: QdrantUpsertPlan) -> None:
        if (not isinstance(plan, QdrantUpsertPlan) or plan.endpoint != self.endpoint
                or plan.vector_name != self.vector_name
                or any(point.point_id not in self.point_ids or len(point.vector) != self.dimensions for point in plan.points)):
            raise KnowledgeIndexJournalError("knowledge-index-plan-mismatch")


def knowledge_index_manifest(index: KnowledgeVectorIndex, writer: QdrantVectorWriter) -> KnowledgeIndexManifest:
    """Pure manifest for a nonempty snapshot and a host-selected write target."""
    if not isinstance(index, KnowledgeVectorIndex) or not isinstance(writer, QdrantVectorWriter):
        raise ValueError("knowledge manifest requires an index and writer")
    return KnowledgeIndexManifest(index.snapshot_digest, index.embedding_key, index.dimensions,
                                  writer.endpoint, writer.backend.vector_name, index.point_ids)


@dataclass(frozen=True, slots=True)
class KnowledgeIndexAttempt:
    attempt_id: str
    plan_digest: str
    point_ids: tuple[str, ...] = field(repr=False)
    outcome: str = "pending"
    operation_id: int | None = None

    def __post_init__(self) -> None:
        _label(self.attempt_id)
        _digest(self.plan_digest)
        _ids(self.point_ids, 128)
        if not isinstance(self.outcome, str) or self.outcome not in _OUTCOMES:
            raise ValueError("knowledge index outcome is invalid")
        if self.operation_id is not None and (
            self.outcome not in {"acknowledged", "completed"}
            or type(self.operation_id) is not int or not 0 <= self.operation_id < 2**64
        ):
            raise ValueError("knowledge index operation ID is invalid")

    def to_dict(self) -> dict:
        return {"attempt_id": self.attempt_id, "plan_digest": self.plan_digest,
                "point_ids": list(self.point_ids), "outcome": self.outcome, "operation_id": self.operation_id}


@dataclass(frozen=True, slots=True)
class KnowledgeIndexReconciliation:
    """Host-reviewed evidence about a terminal attempt, never remote verification.

    not-applied means no effect from this attempt and no possible late effect,
    not merely an absent search hit or a cancelled local coroutine.
    """

    reconciliation_id: str
    manifest_digest: str
    attempt_id: str
    plan_digest: str
    expected_outcome: str
    outcome: str
    evidence_ref: str = field(repr=False)
    actor_ref: str = field(repr=False)

    def __post_init__(self) -> None:
        for value in (self.reconciliation_id, self.attempt_id, self.evidence_ref, self.actor_ref):
            _label(value)
        _digest(self.manifest_digest)
        _digest(self.plan_digest)
        if not isinstance(self.expected_outcome, str) or self.expected_outcome not in {"pending", "acknowledged", "unknown"}:
            raise ValueError("knowledge reconciliation requires an unresolved observation")
        if not isinstance(self.outcome, str) or self.outcome not in {"completed", "not-applied"}:
            raise ValueError("knowledge reconciliation outcome is invalid")

    def to_dict(self) -> dict:
        return {"reconciliation_id": self.reconciliation_id, "manifest_digest": self.manifest_digest,
                "attempt_id": self.attempt_id, "plan_digest": self.plan_digest,
                "expected_outcome": self.expected_outcome, "outcome": self.outcome,
                "evidence_ref": self.evidence_ref, "actor_ref": self.actor_ref}


@dataclass(frozen=True, slots=True)
class KnowledgeIndexJournalSnapshot:
    manifest: KnowledgeIndexManifest = field(repr=False)
    attempts: tuple[KnowledgeIndexAttempt, ...] = ()
    reconciliations: tuple[KnowledgeIndexReconciliation, ...] = ()

    def __post_init__(self) -> None:
        if (not isinstance(self.manifest, KnowledgeIndexManifest) or not isinstance(self.attempts, tuple)
                or len(self.attempts) > 1024):
            raise ValueError("knowledge index journal is invalid")
        seen = set()
        for attempt in self.attempts:
            if (not isinstance(attempt, KnowledgeIndexAttempt) or attempt.attempt_id in seen
                    or any(identity not in self.manifest.point_ids for identity in attempt.point_ids)):
                raise ValueError("knowledge index journal attempt is invalid")
            seen.add(attempt.attempt_id)
        if not isinstance(self.reconciliations, tuple) or len(self.reconciliations) > 1024:
            raise ValueError("knowledge index reconciliations are invalid")
        by_id = {item.attempt_id: item for item in self.attempts}
        decisions, targets = set(), set()
        manifest_digest = self.manifest.digest
        for decision in self.reconciliations:
            if not isinstance(decision, KnowledgeIndexReconciliation):
                raise ValueError("knowledge index reconciliation is invalid")
            attempt = by_id.get(decision.attempt_id)
            if (attempt is None or decision.manifest_digest != manifest_digest
                    or decision.plan_digest != attempt.plan_digest or decision.expected_outcome != attempt.outcome
                    or decision.reconciliation_id in decisions or decision.attempt_id in targets):
                raise ValueError("knowledge index reconciliation does not match its observation")
            decisions.add(decision.reconciliation_id)
            targets.add(decision.attempt_id)

    def effective_outcome(self, attempt_id: str) -> str:
        """Report a derived result without modifying the original observation."""
        for decision in self.reconciliations:
            if decision.attempt_id == attempt_id:
                return decision.outcome
        for attempt in self.attempts:
            if attempt.attempt_id == attempt_id:
                return attempt.outcome
        raise ValueError("knowledge index attempt is not in this snapshot")

    @property
    def unresolved_attempt_ids(self) -> tuple[str, ...]:
        resolved = {item.attempt_id for item in self.reconciliations}
        return tuple(item.attempt_id for item in self.attempts
                     if item.attempt_id not in resolved and item.outcome in {"pending", "acknowledged", "unknown"})

    @property
    def confirmed_point_ids(self) -> tuple[str, ...]:
        resolved = {item.attempt_id: item.outcome for item in self.reconciliations}
        completed = {identity for item in self.attempts
                     if resolved.get(item.attempt_id, item.outcome) == "completed" for identity in item.point_ids}
        uncertain = {identity for item in self.attempts
                     if resolved.get(item.attempt_id, item.outcome) in {"pending", "acknowledged", "unknown"} for identity in item.point_ids}
        return tuple(identity for identity in self.manifest.point_ids if identity in completed - uncertain)

    @property
    def all_points_confirmed(self) -> bool:
        """All IDs have completed receipts/host decisions and no unresolved writes.

        This does not establish current remote existence, relevance or durability.
        """
        return len(self.confirmed_point_ids) == len(self.manifest.point_ids)

    def to_json(self) -> str:
        data = {"format": "wagent-knowledge-index-journal-v1", "manifest": self.manifest.to_dict(),
                "attempts": [item.to_dict() for item in self.attempts]}
        if self.reconciliations:
            data["format"] = "wagent-knowledge-index-journal-v2"
            data["reconciliations"] = [item.to_dict() for item in self.reconciliations]
        return _json(data)


class KnowledgeIndexJournal(Protocol):
    """Local persistence only; remote writes must never be inferred from state."""

    async def begin(self, manifest: KnowledgeIndexManifest, attempt_id: str, plan: QdrantUpsertPlan,
                    *, confirm_write: bool = False) -> KnowledgeIndexJournalSnapshot: ...

    async def record(self, manifest_digest: str, attempt_id: str, *, outcome: str,
                     receipt: QdrantWriteResult | None = None, confirm_write: bool = False) -> KnowledgeIndexJournalSnapshot: ...

    async def inspect(self, manifest_digest: str) -> KnowledgeIndexJournalSnapshot: ...


class KnowledgeIndexReconciler(Protocol):
    """Optional capability; hosts stop/drain relevant work before confirming.

    confirm_inactive is an assertion, not a lease or a remotely checked fact.
    It covers the exact attempt's local and remote possibility of late effects.
    """

    async def reconcile(self, decision: KnowledgeIndexReconciliation, *,
                        confirm_inactive: bool = False, confirm_write: bool = False) -> KnowledgeIndexJournalSnapshot: ...


class CoordinatedKnowledgeIndexJournal(KnowledgeIndexJournal, Protocol):
    """Atomically refuse unresolved overlapping writes in a shared journal."""

    async def begin_exclusive(self, manifest: KnowledgeIndexManifest, attempt_id: str,
                              plan: QdrantUpsertPlan, *, confirm_write: bool = False
                              ) -> KnowledgeIndexJournalSnapshot: ...


def _decode(payload: str, digest: str, manifest_digest: str) -> KnowledgeIndexJournalSnapshot:
    if (not isinstance(payload, str) or len(payload.encode("utf-8")) > _MAX_PAYLOAD
            or hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest):
        raise ValueError
    value = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ValueError
    version = value.get("format")
    if version not in {"wagent-knowledge-index-journal-v1", "wagent-knowledge-index-journal-v2"}:
        raise ValueError
    fields = {"format", "manifest", "attempts"}
    if version == "wagent-knowledge-index-journal-v2":
        fields.add("reconciliations")
    if set(value) != fields:
        raise ValueError
    manifest = value["manifest"]
    if (not isinstance(manifest, dict) or set(manifest) != {"snapshot_digest", "embedding_key", "dimensions", "endpoint", "vector_name", "point_ids"}
            or not isinstance(manifest["point_ids"], list) or not isinstance(value["attempts"], list) or len(value["attempts"]) > 1024):
        raise ValueError
    resolved = KnowledgeIndexManifest(**{**manifest, "point_ids": tuple(manifest["point_ids"])})
    attempts = []
    for item in value["attempts"]:
        if (not isinstance(item, dict) or set(item) != {"attempt_id", "plan_digest", "point_ids", "outcome", "operation_id"}
                or not isinstance(item["point_ids"], list)):
            raise ValueError
        attempts.append(KnowledgeIndexAttempt(**{**item, "point_ids": tuple(item["point_ids"])}))
    raw_decisions = value.get("reconciliations", [])
    if not isinstance(raw_decisions, list) or len(raw_decisions) > 1024:
        raise ValueError
    decisions = []
    for item in raw_decisions:
        if not isinstance(item, dict) or set(item) != {
            "reconciliation_id", "manifest_digest", "attempt_id", "plan_digest",
            "expected_outcome", "outcome", "evidence_ref", "actor_ref",
        }:
            raise ValueError
        decisions.append(KnowledgeIndexReconciliation(**item))
    snapshot = KnowledgeIndexJournalSnapshot(resolved, tuple(attempts), tuple(decisions))
    if resolved.digest != manifest_digest or snapshot.to_json() != payload:
        raise ValueError
    return snapshot


@dataclass(frozen=True, slots=True)
class SQLiteKnowledgeIndexJournal:
    """Dedicated trusted database, separate from knowledge body snapshots."""

    database_path: Path = field(repr=False)
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (str, Path)) or not str(self.database_path).strip() or str(self.database_path) == ":memory:":
            raise ValueError("knowledge journal requires a local file path")
        object.__setattr__(self, "database_path", Path(self.database_path).absolute())
        _timeout(self.timeout)

    def _connect(self, mode: str) -> sqlite3.Connection:
        db = sqlite3.connect(f"{self.database_path.as_uri()}?mode={mode}", uri=True, timeout=self.timeout, isolation_level=None)
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
                != [("table", "knowledge_index_journals", _TABLE)]):
            raise KnowledgeIndexJournalError("knowledge-index-database-unsupported")

    async def initialize(self, *, confirm_create: bool = False) -> None:
        if confirm_create is not True:
            raise KnowledgeIndexJournalError("knowledge-index-creation-not-authorized")
        await _worker(self._initialize)

    def _initialize(self) -> None:
        try:
            with closing(self._connect("rwc")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone() is None:
                    if db.execute("PRAGMA application_id").fetchone()[0] != 0 or db.execute("PRAGMA user_version").fetchone()[0] != 0:
                        raise KnowledgeIndexJournalError("knowledge-index-database-unsupported")
                    db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    db.execute("PRAGMA user_version = 1")
                    db.execute(_TABLE)
                self._check(db)
        except KnowledgeIndexJournalError:
            raise
        except Exception:
            raise KnowledgeIndexJournalError("knowledge-index-initialization-failed") from None

    async def begin(self, manifest: KnowledgeIndexManifest, attempt_id: str, plan: QdrantUpsertPlan,
                    *, confirm_write: bool = False) -> KnowledgeIndexJournalSnapshot:
        if confirm_write is not True:
            raise KnowledgeIndexJournalError("knowledge-index-write-not-authorized")
        if not isinstance(manifest, KnowledgeIndexManifest):
            raise KnowledgeIndexJournalError("knowledge-index-manifest-invalid")
        manifest.validate_plan(plan)
        try:
            attempt = KnowledgeIndexAttempt(attempt_id, plan.digest, tuple(point.point_id for point in plan.points))
        except Exception:
            raise KnowledgeIndexJournalError("knowledge-index-attempt-invalid") from None
        return await _worker(lambda: self._operate(manifest.digest, manifest=manifest, new_attempt=attempt))

    async def record(self, manifest_digest: str, attempt_id: str, *, outcome: str,
                     receipt: QdrantWriteResult | None = None, confirm_write: bool = False) -> KnowledgeIndexJournalSnapshot:
        if confirm_write is not True:
            raise KnowledgeIndexJournalError("knowledge-index-write-not-authorized")
        try:
            _digest(manifest_digest)
            _label(attempt_id)
            if outcome not in {"completed", "acknowledged", "unknown", "not-sent"}:
                raise ValueError
            if outcome in {"completed", "acknowledged"}:
                if not isinstance(receipt, QdrantWriteResult) or receipt.status != outcome:
                    raise ValueError
            elif receipt is not None:
                raise ValueError
        except Exception:
            raise KnowledgeIndexJournalError("knowledge-index-observation-invalid") from None
        return await _worker(lambda: self._operate(manifest_digest, attempt_id=attempt_id, outcome=outcome, receipt=receipt))

    async def inspect(self, manifest_digest: str) -> KnowledgeIndexJournalSnapshot:
        try:
            _digest(manifest_digest)
        except Exception:
            raise KnowledgeIndexJournalError("knowledge-index-identity-invalid") from None
        return await _worker(lambda: self._operate(manifest_digest))

    async def list_journals(self) -> tuple[KnowledgeIndexJournalSnapshot, ...]:
        """Read and validate the bounded receipt directory without creating files."""
        return await _worker(self._list_journals)

    @staticmethod
    def _entries(db: sqlite3.Connection):
        count, size = db.execute("SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))), 0) FROM knowledge_index_journals").fetchone()
        if count > 1024 or size > 128 * 1024 * 1024:
            raise KnowledgeIndexJournalError("knowledge-index-catalog-limit-exceeded")
        for key, payload, digest in db.execute(
            "SELECT manifest_digest, CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload END, digest "
            "FROM knowledge_index_journals ORDER BY manifest_digest", (_MAX_PAYLOAD,),
        ):
            yield _decode(payload, digest, key)

    def _list_journals(self) -> tuple[KnowledgeIndexJournalSnapshot, ...]:
        try:
            with closing(self._connect("ro")) as db:
                db.execute("BEGIN")
                self._check(db)
                return tuple(self._entries(db))
        except KnowledgeIndexJournalError:
            raise
        except Exception:
            raise KnowledgeIndexJournalError("knowledge-index-catalog-read-failed") from None

    async def begin_exclusive(self, manifest: KnowledgeIndexManifest, attempt_id: str,
                              plan: QdrantUpsertPlan, *, confirm_write: bool = False
                              ) -> KnowledgeIndexJournalSnapshot:
        """Reserve points under BEGIN IMMEDIATE across manifests in this database.

        No expiry: pending, unknown and acknowledged need explicit reconciliation.
        Other databases and remote writers remain the host's responsibility.
        """
        if confirm_write is not True or not isinstance(manifest, KnowledgeIndexManifest):
            raise KnowledgeIndexJournalError("knowledge-index-write-not-authorized")
        manifest.validate_plan(plan)
        attempt = KnowledgeIndexAttempt(attempt_id, plan.digest, tuple(point.point_id for point in plan.points))
        return await _worker(lambda: self._operate(manifest.digest, manifest=manifest,
                                                   new_attempt=attempt, exclusive=True))

    async def reconcile(self, decision: KnowledgeIndexReconciliation, *,
                        confirm_inactive: bool = False, confirm_write: bool = False) -> KnowledgeIndexJournalSnapshot:
        if confirm_write is not True or confirm_inactive is not True:
            raise KnowledgeIndexJournalError("knowledge-index-reconciliation-confirmation-required")
        if not isinstance(decision, KnowledgeIndexReconciliation):
            raise KnowledgeIndexJournalError("knowledge-index-reconciliation-invalid")
        return await _worker(lambda: self._operate(decision.manifest_digest, reconciliation=decision))

    def _operate(self, key: str, *, manifest=None, new_attempt=None, attempt_id=None, outcome=None, receipt=None,
                 reconciliation: KnowledgeIndexReconciliation | None = None,
                 exclusive: bool = False) -> KnowledgeIndexJournalSnapshot:
        writing = new_attempt is not None or outcome is not None or reconciliation is not None
        try:
            with closing(self._connect("rw" if writing else "ro")) as db, db:
                db.execute("BEGIN IMMEDIATE" if writing else "BEGIN")
                self._check(db)
                row = db.execute("SELECT CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload ELSE NULL END, digest "
                                 "FROM knowledge_index_journals WHERE manifest_digest = ?", (_MAX_PAYLOAD, key)).fetchone()
                if row is None:
                    if manifest is None:
                        raise KnowledgeIndexJournalError("knowledge-index-manifest-not-found")
                    snapshot = KnowledgeIndexJournalSnapshot(manifest)
                else:
                    snapshot = _decode(row[0], row[1], key)
                    if manifest is not None and snapshot.manifest != manifest:
                        raise KnowledgeIndexJournalError("knowledge-index-manifest-conflict")
                attempts = list(snapshot.attempts)
                decisions = list(snapshot.reconciliations)
                if new_attempt is not None:
                    if any(item.attempt_id == new_attempt.attempt_id for item in attempts):
                        raise KnowledgeIndexJournalError("knowledge-index-attempt-already-exists")
                    if exclusive:
                        points = set(new_attempt.point_ids)
                        for existing in self._entries(db):
                            if (existing.manifest.endpoint, existing.manifest.vector_name) != (manifest.endpoint, manifest.vector_name):
                                continue
                            unresolved = set(existing.unresolved_attempt_ids)
                            if any(item.attempt_id in unresolved and points.intersection(item.point_ids)
                                   for item in existing.attempts):
                                raise KnowledgeIndexJournalError("knowledge-index-overlapping-attempt-unresolved")
                    attempts.append(new_attempt)
                elif outcome is not None:
                    position = next((index for index, item in enumerate(attempts) if item.attempt_id == attempt_id), None)
                    if position is None:
                        raise KnowledgeIndexJournalError("knowledge-index-attempt-not-found")
                    previous = attempts[position]
                    if receipt is not None and (receipt.plan_digest != previous.plan_digest or receipt.point_count != len(previous.point_ids)):
                        raise KnowledgeIndexJournalError("knowledge-index-receipt-mismatch")
                    updated = replace(previous, outcome=outcome, operation_id=receipt.operation_id if receipt is not None else None)
                    if previous != updated and any(item.attempt_id == attempt_id for item in decisions):
                        raise KnowledgeIndexJournalError("knowledge-index-observation-reconciled")
                    if previous.outcome != "pending" and previous != updated:
                        raise KnowledgeIndexJournalError("knowledge-index-observation-conflict")
                    attempts[position] = updated
                elif reconciliation is not None:
                    if reconciliation not in decisions:
                        previous = next((item for item in attempts if item.attempt_id == reconciliation.attempt_id), None)
                        if (previous is None or previous.plan_digest != reconciliation.plan_digest
                                or previous.outcome != reconciliation.expected_outcome
                                or any(item.attempt_id == reconciliation.attempt_id
                                       or item.reconciliation_id == reconciliation.reconciliation_id for item in decisions)):
                            raise KnowledgeIndexJournalError("knowledge-index-reconciliation-conflict")
                        decisions.append(reconciliation)
                if writing:
                    snapshot = KnowledgeIndexJournalSnapshot(snapshot.manifest, tuple(attempts), tuple(decisions))
                    payload = snapshot.to_json()
                    size = len(payload.encode("utf-8"))
                    count, total = db.execute("SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))), 0) FROM knowledge_index_journals").fetchone()
                    prior_size = len(row[0].encode("utf-8")) if row is not None else 0
                    if size > _MAX_PAYLOAD or (row is None and count >= 1024) or total - prior_size + size > 128 * 1024 * 1024:
                        raise KnowledgeIndexJournalError("knowledge-index-capacity-exceeded")
                    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                    if row is None:
                        db.execute("INSERT INTO knowledge_index_journals VALUES (?, ?, ?)", (key, payload, digest))
                    else:
                        db.execute("UPDATE knowledge_index_journals SET payload = ?, digest = ? WHERE manifest_digest = ?", (payload, digest, key))
                return snapshot
        except KnowledgeIndexJournalError:
            raise
        except Exception:
            raise KnowledgeIndexJournalError("knowledge-index-journal-operation-failed") from None


async def journaled_knowledge_upsert(
    writer: QdrantVectorWriter, plan: QdrantUpsertPlan, manifest: KnowledgeIndexManifest,
    journal: KnowledgeIndexJournal, *, attempt_id: str, confirm_digest: str,
    confirm_record: bool = False,
) -> QdrantWriteResult:
    """Durably mark pending before one explicitly approved write; never retry.

    Local commit/remote write/receipt commit are separate. Crashes may leave
    pending records even when nothing was sent, or after a successful write.
    """
    if (not isinstance(writer, QdrantVectorWriter) or not isinstance(plan, QdrantUpsertPlan)
            or not isinstance(manifest, KnowledgeIndexManifest)):
        raise KnowledgeIndexJournalError("knowledge-index-write-configuration-invalid")
    if confirm_record is not True:
        raise KnowledgeIndexJournalError("knowledge-index-write-not-authorized")
    manifest.validate_plan(plan)
    if (plan.endpoint != writer.endpoint or plan.vector_name != writer.backend.vector_name
            or not isinstance(confirm_digest, str) or confirm_digest != plan.digest):
        raise KnowledgeIndexJournalError("knowledge-index-write-confirmation-invalid")
    if any(not callable(getattr(journal, name, None)) for name in ("begin", "record")):
        raise KnowledgeIndexJournalError("knowledge-index-journal-invalid")
    expected = KnowledgeIndexAttempt(attempt_id, plan.digest, tuple(point.point_id for point in plan.points))
    started = await journal.begin(manifest, attempt_id, plan, confirm_write=confirm_record)
    if (not isinstance(started, KnowledgeIndexJournalSnapshot) or started.manifest != manifest
            or expected not in started.attempts
            or started.effective_outcome(attempt_id) != "pending"):
        raise KnowledgeIndexJournalError("knowledge-index-pending-record-invalid")
    try:
        receipt = await writer.upsert(plan, confirm_digest=confirm_digest)
    except (Exception, asyncio.CancelledError) as error:
        outcome = "not-sent" if isinstance(error, VectorIndexWriteError) and not error.may_have_written else "unknown"
        try:
            await journal.record(manifest.digest, attempt_id, outcome=outcome, confirm_write=confirm_record)
        except (Exception, asyncio.CancelledError):
            pass  # Persisted pending is already conservative; preserve the write failure.
        raise
    try:
        recorded = await journal.record(manifest.digest, attempt_id, outcome=receipt.status,
                                        receipt=receipt, confirm_write=confirm_record)
        expected = replace(expected, outcome=receipt.status, operation_id=receipt.operation_id)
        if (not isinstance(recorded, KnowledgeIndexJournalSnapshot) or recorded.manifest != manifest
                or expected not in recorded.attempts):
            raise KnowledgeIndexJournalError("knowledge-index-final-record-invalid")
    except asyncio.CancelledError:
        raise
    except Exception:
        raise KnowledgeIndexJournalError("knowledge-index-receipt-persistence-failed") from None
    return receipt
