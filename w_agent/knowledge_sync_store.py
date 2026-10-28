"""Durable exact sync artifacts, per-batch observations and local head CAS.

One database coordinates this sync API only. Other databases, endpoint aliases,
ordinary upserts and unrelated processes can bypass it; it is not a remote lease.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from w_agent.knowledge_files import _digest
from w_agent.knowledge_ingestion import _json, _label
from w_agent.knowledge_sqlite import _worker
from w_agent.knowledge_sync import (
    MAX_SYNC_BYTES, KnowledgeSyncError, KnowledgeSyncPlan, KnowledgeSyncRetryRecord,
    KnowledgeSyncStatus, QdrantDeletePlan, _canonical_sync_endpoint, knowledge_sync_retry_digest,
)
from w_agent.vector_indexing import QdrantWriteResult
from w_agent.vector_retrieval import _integer, _timeout

_APPLICATION_ID = 0x57415359
_TABLES = {
    "sync_targets": "CREATE TABLE sync_targets (target TEXT PRIMARY KEY, endpoint TEXT NOT NULL, vector_name TEXT, head TEXT, active TEXT)",
    "sync_plans": "CREATE TABLE sync_plans (digest TEXT PRIMARY KEY, target TEXT NOT NULL, payload TEXT NOT NULL)",
    "sync_batches": "CREATE TABLE sync_batches (plan TEXT NOT NULL, position INTEGER NOT NULL, outcome TEXT NOT NULL, receipt TEXT, evidence TEXT, PRIMARY KEY (plan, position))",
    "sync_retries": "CREATE TABLE sync_retries (plan TEXT NOT NULL, position INTEGER NOT NULL, generation INTEGER NOT NULL, retry_id TEXT NOT NULL, prior_outcome TEXT NOT NULL, PRIMARY KEY (plan, position, generation), UNIQUE (plan, retry_id))",
}


@dataclass(frozen=True, slots=True)
class SQLiteKnowledgeSyncJournal:
    """Explicitly created plaintext plan/vector/trace cache and no-replay journal.

    Every prepared plan is durable before network entry. Identical staging is
    idempotent; competing predecessors/targets fail. Upsert batches precede all
    deletes. An acknowledged/pending/unknown result prevents further batches.
    """

    database_path: Path = field(repr=False)
    timeout: float = 5.0
    max_plans: int = 1024
    max_total_bytes: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (str, Path)) or not str(self.database_path).strip() or str(self.database_path) == ":memory:":
            raise ValueError("sync journal requires a local file")
        object.__setattr__(self, "database_path", Path(self.database_path).absolute())
        _timeout(self.timeout)
        _integer(self.max_plans, 4096)
        _integer(self.max_total_bytes, 2**31)

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
        objects = db.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' ORDER BY name").fetchall()
        if (db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != 1
                or objects != [("table", name, _TABLES[name]) for name in sorted(_TABLES)]):
            raise KnowledgeSyncError("knowledge-sync-database-unsupported")

    async def validate_existing(self) -> None:
        """Read-only schema preflight; never creates a missing database."""
        def validate() -> None:
            try:
                with closing(self._connect("ro")) as db:
                    self._check(db)
            except KnowledgeSyncError:
                raise
            except Exception:
                raise KnowledgeSyncError("knowledge-sync-database-unavailable") from None
        await _worker(validate)

    async def preflight_target(self, endpoint: str, vector_name: str | None, previous_index_digest: str | None) -> None:
        """Reject known head conflicts before embedding; stage still performs CAS.

        This read-only check reserves nothing. A competing caller can still win
        after it returns, so embedding charges may precede a stage conflict.
        """
        _canonical_sync_endpoint(endpoint)
        if previous_index_digest is not None:
            _digest(previous_index_digest)
        target = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()

        def check() -> None:
            try:
                with closing(self._connect("ro")) as db:
                    db.execute("BEGIN")
                    self._check(db)
                    row = db.execute("SELECT endpoint, vector_name, head, active FROM sync_targets WHERE target = ?", (target,)).fetchone()
                    if row is None:
                        if previous_index_digest is not None:
                            raise KnowledgeSyncError("knowledge-sync-predecessor-not-applied")
                    elif row != (endpoint, vector_name, previous_index_digest, None):
                        raise KnowledgeSyncError("knowledge-sync-head-conflict-or-unresolved")
                    if db.execute("SELECT count(*) FROM sync_plans").fetchone()[0] >= self.max_plans:
                        raise KnowledgeSyncError("knowledge-sync-capacity-exceeded")
            except KnowledgeSyncError:
                raise
            except Exception:
                raise KnowledgeSyncError("knowledge-sync-preflight-failed") from None
        await _worker(check)

    async def initialize(self, *, confirm_create: bool = False) -> None:
        if confirm_create is not True:
            raise KnowledgeSyncError("knowledge-sync-create-not-authorized")
        await _worker(self._initialize)

    def _initialize(self) -> None:
        try:
            with closing(self._connect("rwc")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone() is None:
                    if (db.execute("PRAGMA application_id").fetchone()[0] != 0
                            or db.execute("PRAGMA user_version").fetchone()[0] != 0):
                        raise KnowledgeSyncError("knowledge-sync-database-unsupported")
                    db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    db.execute("PRAGMA user_version = 1")
                    for schema in _TABLES.values():
                        db.execute(schema)
                self._check(db)
        except KnowledgeSyncError:
            raise
        except Exception:
            raise KnowledgeSyncError("knowledge-sync-initialize-failed-file-may-exist") from None

    @staticmethod
    def _load(db: sqlite3.Connection, digest: str) -> KnowledgeSyncPlan:
        row = db.execute("SELECT CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload END, target "
                         "FROM sync_plans WHERE digest = ?", (MAX_SYNC_BYTES, digest)).fetchone()
        if row is None:
            raise KnowledgeSyncError("knowledge-sync-plan-not-found")
        plan = KnowledgeSyncPlan.from_json(row[0], expected_digest=digest)
        if row[1] != plan.target_key:
            raise KnowledgeSyncError("knowledge-sync-plan-corrupt")
        return plan

    @staticmethod
    def _status(db: sqlite3.Connection, plan: KnowledgeSyncPlan) -> KnowledgeSyncStatus:
        rows = db.execute("SELECT position, outcome, receipt, evidence FROM sync_batches WHERE plan = ? ORDER BY position LIMIT 17",
                          (plan.digest,)).fetchall()
        batches = plan.batches
        SQLiteKnowledgeSyncJournal._retries(db, plan)
        if len(rows) != len(batches):
            raise KnowledgeSyncError("knowledge-sync-journal-corrupt")
        outcomes = []
        blocked = False
        for index, (position, outcome, receipt, evidence) in enumerate(rows):
            if position != index or outcome not in {"ready", "pending", "unknown", "not-sent", "acknowledged", "completed"}:
                raise KnowledgeSyncError("knowledge-sync-journal-corrupt")
            if evidence is not None:
                _label(evidence)
                if outcome not in {"pending", "unknown", "acknowledged"}:
                    raise KnowledgeSyncError("knowledge-sync-journal-corrupt")
            if outcome in {"acknowledged", "completed"}:
                if not isinstance(receipt, str) or len(receipt) > 1024:
                    raise KnowledgeSyncError("knowledge-sync-journal-corrupt")
                value = json.loads(receipt)
                observed = QdrantWriteResult(**value)
                batch = batches[index]
                count = len(batch.point_ids) if isinstance(batch, QdrantDeletePlan) else len(batch.points)
                if observed.plan_digest != batch.digest or observed.point_count != count or observed.status != outcome:
                    raise KnowledgeSyncError("knowledge-sync-journal-corrupt")
            elif receipt is not None:
                raise KnowledgeSyncError("knowledge-sync-journal-corrupt")
            effective = "completed" if evidence is not None else outcome
            if blocked and effective != "ready":
                raise KnowledgeSyncError("knowledge-sync-journal-order-corrupt")
            outcomes.append(effective)
            blocked = blocked or effective != "completed"
        return KnowledgeSyncStatus(plan.digest, tuple(outcomes), all(value == "completed" for value in outcomes))

    @staticmethod
    def _retries(db: sqlite3.Connection, plan: KnowledgeSyncPlan) -> tuple[KnowledgeSyncRetryRecord, ...]:
        rows = db.execute("SELECT position, generation, retry_id, prior_outcome FROM sync_retries WHERE plan = ? ORDER BY position, generation LIMIT 65",
                          (plan.digest,)).fetchall()
        if len(rows) > 64:
            raise KnowledgeSyncError("knowledge-sync-retry-history-corrupt")
        records = tuple(KnowledgeSyncRetryRecord(*row) for row in rows)
        expected: dict[int, int] = {}
        seen: set[str] = set()
        for record in records:
            if record.batch >= len(plan.batches) or record.generation != expected.get(record.batch, 0) or record.retry_id in seen:
                raise KnowledgeSyncError("knowledge-sync-retry-history-corrupt")
            expected[record.batch] = record.generation + 1
            seen.add(record.retry_id)
        return records

    async def stage(self, plan: KnowledgeSyncPlan, *, confirm_write: bool = False) -> KnowledgeSyncStatus:
        if confirm_write is not True or not isinstance(plan, KnowledgeSyncPlan):
            raise KnowledgeSyncError("knowledge-sync-stage-not-authorized")
        payload, digest = plan.to_json(), plan.digest
        KnowledgeSyncPlan.from_json(payload, expected_digest=digest)
        return await _worker(lambda: self._stage(plan, payload))

    def _stage(self, plan: KnowledgeSyncPlan, payload: str) -> KnowledgeSyncStatus:
        try:
            with closing(self._connect("rw")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._check(db)
                if db.execute("SELECT 1 FROM sync_plans WHERE digest = ?", (plan.digest,)).fetchone() is not None:
                    stored = self._load(db, plan.digest)
                    if stored != plan:
                        raise KnowledgeSyncError("knowledge-sync-plan-conflict")
                    return self._status(db, stored)
                row = db.execute("SELECT endpoint, vector_name, head, active FROM sync_targets WHERE target = ?", (plan.target_key,)).fetchone()
                expected_head = plan.previous.digest if plan.previous is not None else None
                if row is None:
                    if expected_head is not None:
                        raise KnowledgeSyncError("knowledge-sync-predecessor-not-applied")
                elif row[:2] != (plan.endpoint, plan.vector_name) or row[2] != expected_head or row[3] is not None:
                    raise KnowledgeSyncError("knowledge-sync-head-conflict-or-unresolved")
                count, size = db.execute("SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))), 0) FROM sync_plans").fetchone()
                if count >= self.max_plans or size + len(payload.encode("utf-8")) > self.max_total_bytes:
                    raise KnowledgeSyncError("knowledge-sync-capacity-exceeded")
                db.execute("INSERT INTO sync_plans VALUES (?, ?, ?)", (plan.digest, plan.target_key, payload))
                batches = plan.batches
                db.executemany("INSERT INTO sync_batches VALUES (?, ?, 'ready', NULL, NULL)",
                               ((plan.digest, index) for index in range(len(batches))))
                head = expected_head if batches else plan.current.digest
                active = plan.digest if batches else None
                if row is None:
                    db.execute("INSERT INTO sync_targets VALUES (?, ?, ?, ?, ?)",
                               (plan.target_key, plan.endpoint, plan.vector_name, head, active))
                else:
                    db.execute("UPDATE sync_targets SET head = ?, active = ? WHERE target = ?", (head, active, plan.target_key))
                return self._status(db, plan)
        except KnowledgeSyncError:
            raise
        except Exception:
            raise KnowledgeSyncError("knowledge-sync-stage-failed-inspect-before-retry") from None

    async def load_plan(self, plan_digest: str) -> KnowledgeSyncPlan:
        _digest(plan_digest)
        return await _worker(lambda: self._read(plan_digest, status=False))

    async def inspect(self, plan_digest: str) -> KnowledgeSyncStatus:
        _digest(plan_digest)
        return await _worker(lambda: self._read(plan_digest, status=True))

    async def inspect_retries(self, plan_digest: str) -> tuple[KnowledgeSyncRetryRecord, ...]:
        _digest(plan_digest)
        return await _worker(lambda: self._read(plan_digest, status="retries"))

    async def inspect_observations(self, plan_digest: str) -> tuple[dict[str, object], ...]:
        """Expose raw receipts/evidence references for host review, not bodies."""
        _digest(plan_digest)
        return await _worker(lambda: self._read(plan_digest, status="observations"))

    def _read(self, digest: str, *, status: bool | str):
        try:
            with closing(self._connect("ro")) as db:
                db.execute("BEGIN")
                self._check(db)
                plan = self._load(db, digest)
                checked = self._status(db, plan)
                if status == "retries":
                    return self._retries(db, plan)
                if status == "observations":
                    retries = self._retries(db, plan)
                    rows = db.execute("SELECT position, outcome, receipt, evidence FROM sync_batches WHERE plan = ? ORDER BY position",
                                      (digest,)).fetchall()
                    return tuple({"batch": position, "generation": sum(item.batch == position for item in retries),
                                  "outcome": outcome, "batch_digest": plan.batches[position].digest,
                                  "operation_id": json.loads(receipt)["operation_id"] if receipt is not None else None,
                                  "evidence_ref": evidence}
                                 for position, outcome, receipt, evidence in rows)
                return checked if status else plan
        except KnowledgeSyncError:
            raise
        except Exception:
            raise KnowledgeSyncError("knowledge-sync-read-failed") from None

    async def claim(self, plan_digest: str, batch: int, *, confirm_write: bool = False) -> None:
        await self._mutate(plan_digest, batch, "claim", confirm_write=confirm_write)

    async def retry_not_sent(self, plan_digest: str, batch: int, *, generation: int, retry_id: str,
                             confirm_retry_digest: str, confirm_write: bool = False) -> KnowledgeSyncStatus:
        """Preserve the failed generation before explicitly admitting a new one.

        Only adapter-reported not-sent is eligible. Pending/unknown/acknowledged
        never reset, even with this confirmation. There is no automatic retry.
        """
        record = KnowledgeSyncRetryRecord(batch, generation, retry_id)
        if confirm_retry_digest != knowledge_sync_retry_digest(plan_digest, batch, generation):
            raise KnowledgeSyncError("knowledge-sync-retry-confirmation-invalid")
        return await self._mutate(plan_digest, batch, "retry", evidence=record, confirm_write=confirm_write)

    async def record(self, plan_digest: str, batch: int, outcome: str, *, receipt: QdrantWriteResult | None = None,
                     confirm_write: bool = False) -> KnowledgeSyncStatus:
        if outcome not in {"completed", "acknowledged", "unknown", "not-sent"}:
            raise KnowledgeSyncError("knowledge-sync-observation-invalid")
        return await self._mutate(plan_digest, batch, outcome, receipt=receipt, confirm_write=confirm_write)

    async def reconcile_completed(self, plan_digest: str, batch: int, *, evidence_ref: str,
                                  confirm_applied: bool = False, confirm_inactive: bool = False,
                                  confirm_write: bool = False) -> KnowledgeSyncStatus:
        """Host-reviewed completion only; preserves original observations.

        This does not query Qdrant. A false host declaration may lose data.
        There is no 'not applied' reset or automatic retry of uncertain batches.
        """
        if confirm_applied is not True or confirm_inactive is not True:
            raise KnowledgeSyncError("knowledge-sync-reconciliation-not-authorized")
        _label(evidence_ref)
        return await self._mutate(plan_digest, batch, "reconcile", evidence=evidence_ref, confirm_write=confirm_write)

    async def _mutate(self, digest: str, batch: int, action: str, *, receipt=None, evidence=None, confirm_write=False):
        if confirm_write is not True:
            raise KnowledgeSyncError("knowledge-sync-write-not-authorized")
        _digest(digest)
        if type(batch) is not int or not 0 <= batch < 16:
            raise KnowledgeSyncError("knowledge-sync-batch-invalid")
        return await _worker(lambda: self._change(digest, batch, action, receipt, evidence))

    def _change(self, digest: str, batch: int, action: str, receipt, evidence) -> KnowledgeSyncStatus:
        try:
            with closing(self._connect("rw")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._check(db)
                plan = self._load(db, digest)
                status = self._status(db, plan)
                if batch >= len(status.outcomes):
                    raise KnowledgeSyncError("knowledge-sync-batch-invalid")
                target = db.execute("SELECT active FROM sync_targets WHERE target = ?", (plan.target_key,)).fetchone()
                if target != (digest,):
                    raise KnowledgeSyncError("knowledge-sync-not-active")
                row = db.execute("SELECT outcome, evidence FROM sync_batches WHERE plan = ? AND position = ?", (digest, batch)).fetchone()
                if any(value != "completed" for value in status.outcomes[:batch]):
                    raise KnowledgeSyncError("knowledge-sync-prior-batch-unresolved")
                if action == "claim":
                    if row != ("ready", None):
                        raise KnowledgeSyncError("knowledge-sync-batch-already-attempted")
                    db.execute("UPDATE sync_batches SET outcome = 'pending' WHERE plan = ? AND position = ?", (digest, batch))
                elif action == "retry":
                    history = self._retries(db, plan)
                    generation = sum(item.batch == batch for item in history)
                    if (row != ("not-sent", None) or not isinstance(evidence, KnowledgeSyncRetryRecord)
                            or evidence.generation != generation or evidence.batch != batch
                            or len(history) >= 64 or any(item.retry_id == evidence.retry_id for item in history)):
                        raise KnowledgeSyncError("knowledge-sync-retry-conflict-or-unresolved")
                    db.execute("INSERT INTO sync_retries VALUES (?, ?, ?, ?, ?)",
                               (digest, batch, generation, evidence.retry_id, row[0]))
                    db.execute("UPDATE sync_batches SET outcome = 'ready', receipt = NULL, evidence = NULL WHERE plan = ? AND position = ?",
                               (digest, batch))
                elif action == "reconcile":
                    if row[0] not in {"pending", "unknown", "acknowledged"} or row[1] is not None:
                        raise KnowledgeSyncError("knowledge-sync-reconciliation-conflict")
                    db.execute("UPDATE sync_batches SET evidence = ? WHERE plan = ? AND position = ?", (evidence, digest, batch))
                else:
                    if row != ("pending", None):
                        raise KnowledgeSyncError("knowledge-sync-observation-conflict")
                    encoded = None
                    if action in {"completed", "acknowledged"}:
                        if not isinstance(receipt, QdrantWriteResult) or receipt.status != action:
                            raise KnowledgeSyncError("knowledge-sync-receipt-invalid")
                        encoded = _json({"plan_digest": receipt.plan_digest, "point_count": receipt.point_count,
                                         "status": receipt.status, "operation_id": receipt.operation_id})
                    elif receipt is not None:
                        raise KnowledgeSyncError("knowledge-sync-receipt-invalid")
                    db.execute("UPDATE sync_batches SET outcome = ?, receipt = ? WHERE plan = ? AND position = ?",
                               (action, encoded, digest, batch))
                updated = self._status(db, plan)  # Validate before transaction commit.
                if updated.finished:
                    db.execute("UPDATE sync_targets SET head = ?, active = NULL WHERE target = ?", (plan.current.digest, plan.target_key))
                return updated
        except KnowledgeSyncError:
            raise
        except Exception:
            raise KnowledgeSyncError("knowledge-sync-journal-write-failed-inspect-before-retry") from None
