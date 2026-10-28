"""Explicit dedicated SQLite storage for service observations, not budgets."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from w_agent.knowledge_sqlite import _worker
from w_agent.service_usage import ServiceUsageError, ServiceUsageRecord, _decode, _encode, _label, _transition
from w_agent.vector_retrieval import _timeout

_APP_ID = 0x57535547
_SCHEMA = {
    "service_limits": "CREATE TABLE service_limits (singleton INTEGER PRIMARY KEY, max_records INTEGER NOT NULL)",
    "service_records": "CREATE TABLE service_records (operation_id TEXT NOT NULL, record_id TEXT NOT NULL, service TEXT NOT NULL, granularity TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (operation_id, record_id))",
}
_MAX_BYTES = 16384


@dataclass(frozen=True, slots=True)
class SQLiteServiceUsageLedger:
    database_path: Path = field(repr=False)
    max_records: int = 10000
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (str, Path)) or not str(self.database_path).strip() or str(self.database_path) == ":memory:":
            raise ValueError("service ledger requires a local file")
        if type(self.max_records) is not int or not 1 <= self.max_records <= 100000:
            raise ValueError("invalid service ledger capacity")
        _timeout(self.timeout)
        object.__setattr__(self, "database_path", Path(self.database_path).absolute())

    def _connect(self, mode: str) -> sqlite3.Connection:
        db = sqlite3.connect(f"{self.database_path.as_uri()}?mode={mode}", uri=True, timeout=self.timeout, isolation_level=None)
        try:
            db.execute("PRAGMA trusted_schema = OFF")
        except Exception:
            db.close()
            raise
        return db

    def _check(self, db: sqlite3.Connection) -> None:
        objects = db.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' ORDER BY name").fetchall()
        if (db.execute("PRAGMA application_id").fetchone()[0] != _APP_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != 1
                or objects != [("table", name, _SCHEMA[name]) for name in sorted(_SCHEMA)]
                or db.execute("SELECT singleton, max_records FROM service_limits").fetchall() != [(1, self.max_records)]):
            raise ServiceUsageError("service-usage-database-unsupported")

    async def initialize(self, *, confirm_create: bool = False) -> None:
        if confirm_create is not True:
            raise ServiceUsageError("service-usage-create-not-authorized")
        await _worker(self._initialize)

    def _initialize(self) -> None:
        try:
            with closing(self._connect("rwc")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if not db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone():
                    if db.execute("PRAGMA application_id").fetchone()[0] or db.execute("PRAGMA user_version").fetchone()[0]:
                        raise ServiceUsageError("service-usage-database-unsupported")
                    db.execute(f"PRAGMA application_id = {_APP_ID}")
                    db.execute("PRAGMA user_version = 1")
                    for schema in _SCHEMA.values():
                        db.execute(schema)
                    db.execute("INSERT INTO service_limits VALUES (1, ?)", (self.max_records,))
                self._check(db)
        except ServiceUsageError:
            raise
        except Exception:
            raise ServiceUsageError("service-usage-initialize-failed-inspect-store") from None

    async def record(self, record: ServiceUsageRecord) -> None:
        try:
            if not isinstance(record, ServiceUsageRecord):
                raise ValueError
            payload = _encode(record)
            if len(payload.encode("utf-8")) > _MAX_BYTES:
                raise ValueError
            _decode(payload)
        except Exception:
            raise ServiceUsageError("service-usage-record-invalid") from None
        await _worker(lambda: self._record(record, payload))

    def _record(self, record: ServiceUsageRecord, payload: str) -> None:
        try:
            with closing(self._connect("rw")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._check(db)
                key = (record.operation_id, record.record_id)
                rows = db.execute("SELECT DISTINCT granularity FROM service_records WHERE operation_id = ? AND service = ?",
                                  (record.operation_id, record.service)).fetchall()
                if any(row != (record.granularity,) for row in rows):
                    raise ServiceUsageError("service-usage-mixed-run-and-attempt-accounting")
                row = db.execute("SELECT CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload END FROM service_records WHERE operation_id = ? AND record_id = ?",
                                 (_MAX_BYTES, *key)).fetchone()
                previous = _decode(row[0]) if row is not None else None
                if previous is not None and (previous.operation_id, previous.record_id) != key:
                    raise ValueError
                _transition(previous, record)
                if row is None and db.execute("SELECT count(*) FROM service_records").fetchone()[0] >= self.max_records:
                    raise ServiceUsageError("service-usage-capacity-exceeded")
                db.execute("INSERT INTO service_records VALUES (?, ?, ?, ?, ?) ON CONFLICT(operation_id, record_id) DO UPDATE SET payload = excluded.payload",
                           (*key, record.service, record.granularity, payload))
        except ServiceUsageError:
            raise
        except Exception:
            raise ServiceUsageError("service-usage-write-failed-inspect-store-no-retry-call") from None

    async def records(self, operation_id: str) -> tuple[ServiceUsageRecord, ...]:
        _label(operation_id)
        return await _worker(lambda: self._records(operation_id))

    def _records(self, operation_id: str) -> tuple[ServiceUsageRecord, ...]:
        try:
            with closing(self._connect("ro")) as db:
                db.execute("BEGIN")
                self._check(db)
                rows = db.execute("SELECT record_id, service, granularity, CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload END FROM service_records WHERE operation_id = ? ORDER BY record_id LIMIT ?",
                                  (_MAX_BYTES, operation_id, self.max_records + 1)).fetchall()
                if len(rows) > self.max_records:
                    raise ValueError
                records = []
                for identity, service, granularity, payload in rows:
                    item = _decode(payload)
                    if (item.operation_id, item.record_id, item.service, item.granularity) != (operation_id, identity, service, granularity):
                        raise ValueError
                    records.append(item)
                return tuple(records)
        except ServiceUsageError:
            raise
        except Exception:
            raise ServiceUsageError("service-usage-read-failed") from None
