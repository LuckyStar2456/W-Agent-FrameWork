"""Explicit immutable trace persistence; no source-file reads or binary archive."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from w_agent.knowledge_ingestion import _label
from w_agent.knowledge_provenance import TracedKnowledgeImport
from w_agent.knowledge_sqlite import KnowledgeStoreError, _worker
from w_agent.vector_retrieval import _integer, _timeout

_APPLICATION_ID = 0x57414954
_TABLE = "CREATE TABLE knowledge_imports (namespace TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (namespace, version))"
_MAX_TRACE_BYTES = 96 * 1024 * 1024


class KnowledgeImportStore(Protocol):
    """Replaceable exact-version trace cache; save never re-reads source files."""

    async def save(self, trace: TracedKnowledgeImport, *, confirm_write: bool = False) -> str: ...

    async def load(self, namespace: str, version: str) -> TracedKnowledgeImport: ...


@dataclass(frozen=True, slots=True)
class SQLiteKnowledgeImportStore:
    """Dedicated host-controlled SQLite database, plaintext extracted originals.

    Construction performs no I/O. initialize is explicit; no implicit parents,
    migration, overwrite, deletion or adoption of other databases. Cancellation
    drains started SQLite work and may follow a committed write.
    """

    database_path: Path = field(repr=False)
    timeout: float = 5.0
    max_imports: int = 1024
    max_total_bytes: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (str, Path)) or not str(self.database_path).strip() or str(self.database_path) == ":memory:":
            raise ValueError("knowledge import store requires a local file")
        object.__setattr__(self, "database_path", Path(self.database_path).absolute())
        _timeout(self.timeout)
        _integer(self.max_imports, 4096)
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
        objects = db.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
        if (db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != 1
                or objects != [("table", "knowledge_imports", _TABLE)]):
            raise KnowledgeStoreError("knowledge-import-database-unsupported")

    async def initialize(self, *, confirm_create: bool = False) -> None:
        if confirm_create is not True:
            raise KnowledgeStoreError("knowledge-import-create-not-authorized")
        await _worker(self._initialize)

    def _initialize(self) -> None:
        try:
            with closing(self._connect("rwc")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone() is None:
                    if (db.execute("PRAGMA application_id").fetchone()[0] != 0
                            or db.execute("PRAGMA user_version").fetchone()[0] != 0):
                        raise KnowledgeStoreError("knowledge-import-database-unsupported")
                    db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    db.execute("PRAGMA user_version = 1")
                    db.execute(_TABLE)
                self._check(db)
        except KnowledgeStoreError:
            raise
        except Exception:
            raise KnowledgeStoreError("knowledge-import-initialize-failed", may_have_written=True) from None

    async def save(self, trace: TracedKnowledgeImport, *, confirm_write: bool = False) -> str:
        if confirm_write is not True:
            raise KnowledgeStoreError("knowledge-import-write-not-authorized")
        if not isinstance(trace, TracedKnowledgeImport):
            raise KnowledgeStoreError("knowledge-import-invalid")
        payload, digest = trace.to_json(), trace.digest
        # Check the same complete deterministic contract used when reopening.
        TracedKnowledgeImport.from_json(payload, expected_digest=digest)
        return await _worker(lambda: self._save(trace, payload, digest))

    def _save(self, trace: TracedKnowledgeImport, payload: str, digest: str) -> str:
        entered = False
        try:
            with closing(self._connect("rw")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._check(db)
                key = (trace.snapshot.namespace, trace.snapshot.version)
                row = self._row(db, *key)
                if row is not None:
                    existing = TracedKnowledgeImport.from_json(row[0], expected_digest=row[1])
                    if (existing.snapshot.namespace, existing.snapshot.version) != key or row != (payload, digest):
                        raise KnowledgeStoreError("knowledge-import-version-conflict")
                    return digest
                count, size = db.execute("SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))), 0) FROM knowledge_imports").fetchone()
                if count >= self.max_imports or size + len(payload.encode("utf-8")) > self.max_total_bytes:
                    raise KnowledgeStoreError("knowledge-import-capacity-exceeded")
                entered = True
                db.execute("INSERT INTO knowledge_imports VALUES (?, ?, ?, ?)", (*key, digest, payload))
            return digest
        except KnowledgeStoreError:
            raise
        except Exception:
            raise KnowledgeStoreError("knowledge-import-save-failed", may_have_written=entered) from None

    @staticmethod
    def _row(db: sqlite3.Connection, namespace: str, version: str):
        return db.execute("SELECT CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload END, digest "
                          "FROM knowledge_imports WHERE namespace = ? AND version = ?",
                          (_MAX_TRACE_BYTES, namespace, version)).fetchone()

    async def load(self, namespace: str, version: str) -> TracedKnowledgeImport:
        _label(namespace)
        _label(version)
        return await _worker(lambda: self._load(namespace, version))

    def _load(self, namespace: str, version: str) -> TracedKnowledgeImport:
        try:
            with closing(self._connect("ro")) as db:
                db.execute("BEGIN")
                self._check(db)
                row = self._row(db, namespace, version)
                if row is None:
                    raise KnowledgeStoreError("knowledge-import-not-found")
                trace = TracedKnowledgeImport.from_json(row[0], expected_digest=row[1])
                if (trace.snapshot.namespace, trace.snapshot.version) != (namespace, version):
                    raise ValueError
                return trace
        except KnowledgeStoreError:
            raise
        except Exception:
            raise KnowledgeStoreError("knowledge-import-load-failed") from None
