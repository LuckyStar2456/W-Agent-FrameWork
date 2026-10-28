"""Explicit append-only knowledge versions in a dedicated trusted SQLite file."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from w_agent.knowledge_context import KnowledgeDocument
from w_agent.knowledge_ingestion import KnowledgeSnapshot, KnowledgeSnapshotInfo, MAX_SNAPSHOT_BYTES, _label
from w_agent.vector_retrieval import _integer, _reject_constant, _timeout, _unique_object

_APPLICATION_ID = 0x57414B53
_TABLE = "CREATE TABLE knowledge_snapshots (namespace TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (namespace, version))"
_T = TypeVar("_T")


class KnowledgeStoreError(RuntimeError):
    """No body/path details; cancellation propagates separately and may follow commit."""

    def __init__(self, code: str, *, may_have_written: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.may_have_written = may_have_written


async def _worker(operation: Callable[[], _T]) -> _T:
    """Drain a started worker before cancellation returns; do not claim rollback."""
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        # Consume an exception without replacing the caller's cancellation.
        if not task.cancelled():
            task.exception()
        raise


def _decode(payload: str, digest: str, namespace: str, version: str) -> KnowledgeSnapshot:
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ValueError
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
        raise ValueError
    value = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if (not isinstance(value, dict) or set(value) != {"format", "namespace", "version", "documents"}
            or value["format"] != "wagent-knowledge-snapshot-v1"
            or value["namespace"] != namespace or value["version"] != version
            or not isinstance(value["documents"], list) or len(value["documents"]) > 1024):
        raise ValueError
    documents = []
    for item in value["documents"]:
        if not isinstance(item, dict) or set(item) != {"id", "text", "source", "title"}:
            raise ValueError
        documents.append(KnowledgeDocument(item["id"], item["text"], item["source"], item["title"]))
    snapshot = KnowledgeSnapshot(namespace, version, tuple(documents))
    if snapshot.to_json() != payload:
        raise ValueError
    return snapshot


@dataclass(frozen=True, slots=True)
class SQLiteKnowledgeSnapshotStore:
    """No I/O until initialize/save/load; no implicit migration, overwrite or delete.

    Parent directory must exist. Local file and its directory are trusted and
    host-controlled. Limits govern admission, not physical disk/WAL size.
    """

    database_path: Path = field(repr=False)
    timeout: float = 5.0
    max_snapshots: int = 1024
    max_total_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (str, Path)) or not str(self.database_path).strip() or str(self.database_path) == ":memory:":
            raise ValueError("knowledge database requires a local file path")
        object.__setattr__(self, "database_path", Path(self.database_path).absolute())
        _timeout(self.timeout)
        _integer(self.max_snapshots, 4096)
        _integer(self.max_total_bytes, 2**31)

    def _connect(self, mode: str) -> sqlite3.Connection:
        connection = sqlite3.connect(f"{self.database_path.as_uri()}?mode={mode}", uri=True,
                                     timeout=self.timeout, isolation_level=None)
        try:
            connection.execute("PRAGMA trusted_schema = OFF")
        except Exception:
            connection.close()
            raise
        return connection

    @staticmethod
    def _check(db: sqlite3.Connection) -> None:
        objects = db.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
        if (db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != 1
                or objects != [("table", "knowledge_snapshots", _TABLE)]):
            raise KnowledgeStoreError("knowledge-database-unsupported")

    @staticmethod
    def _row(db: sqlite3.Connection, namespace: str, version: str):
        return db.execute(
            "SELECT CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload ELSE NULL END, digest "
            "FROM knowledge_snapshots WHERE namespace = ? AND version = ?",
            (MAX_SNAPSHOT_BYTES, namespace, version),
        ).fetchone()

    async def initialize(self, *, confirm_create: bool = False) -> None:
        """Explicitly create a dedicated database, or verify its exact schema."""
        if confirm_create is not True:
            raise KnowledgeStoreError("knowledge-database-creation-not-authorized")
        await _worker(self._initialize)

    async def list_snapshots(self, namespace: str | None = None) -> tuple[KnowledgeSnapshotInfo, ...]:
        """Read bounded metadata only, sorted lexically; never select an implicit latest."""
        if namespace is not None:
            _label(namespace)
        return await _worker(lambda: self._list_snapshots(namespace))

    def _list_snapshots(self, namespace: str | None) -> tuple[KnowledgeSnapshotInfo, ...]:
        try:
            with closing(self._connect("ro")) as db:
                db.execute("BEGIN")
                self._check(db)
                # Bound even hostile stored label/digest values before fetching them.
                query = (
                    "SELECT CASE WHEN length(CAST(namespace AS BLOB)) <= 128 THEN namespace END, "
                    "CASE WHEN length(CAST(version AS BLOB)) <= 128 THEN version END, "
                    "CASE WHEN length(CAST(digest AS BLOB)) = 64 THEN digest END, "
                    "length(CAST(payload AS BLOB)) FROM knowledge_snapshots "
                )
                parameters: tuple = ()
                if namespace is not None:
                    query += "WHERE namespace = ? "
                    parameters = (namespace,)
                rows = db.execute(query + "ORDER BY namespace, version LIMIT 4097", parameters).fetchall()
                if len(rows) > 4096:
                    raise KnowledgeStoreError("knowledge-catalog-limit-exceeded")
                return tuple(KnowledgeSnapshotInfo(*row) for row in rows)
        except KnowledgeStoreError:
            raise
        except Exception:
            raise KnowledgeStoreError("knowledge-catalog-read-failed") from None

    def _initialize(self) -> None:
        entered = False
        try:
            entered = True  # Connecting may create a new file even if SQL later fails.
            with closing(self._connect("rwc")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                objects = db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone()
                if objects is None:
                    if (db.execute("PRAGMA application_id").fetchone()[0] != 0
                            or db.execute("PRAGMA user_version").fetchone()[0] != 0):
                        raise KnowledgeStoreError("knowledge-database-unsupported")
                    db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    db.execute("PRAGMA user_version = 1")
                    db.execute(_TABLE)
                self._check(db)
        except KnowledgeStoreError:
            raise
        except Exception:
            raise KnowledgeStoreError("knowledge-database-initialization-failed", may_have_written=entered) from None

    async def save(self, snapshot: KnowledgeSnapshot, *, confirm_write: bool = False) -> str:
        if confirm_write is not True:
            raise KnowledgeStoreError("knowledge-snapshot-write-not-authorized")
        if not isinstance(snapshot, KnowledgeSnapshot):
            raise KnowledgeStoreError("knowledge-snapshot-invalid")
        payload = snapshot.to_json()
        digest = snapshot.digest
        return await _worker(lambda: self._save(snapshot, payload, digest))

    def _save(self, snapshot: KnowledgeSnapshot, payload: str, digest: str) -> str:
        entered = False
        try:
            with closing(self._connect("rw")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._check(db)
                existing = self._row(db, snapshot.namespace, snapshot.version)
                if existing is not None:
                    _decode(existing[0], existing[1], snapshot.namespace, snapshot.version)
                    if existing != (payload, digest):
                        raise KnowledgeStoreError("knowledge-version-conflict")
                    return digest
                count, size = db.execute("SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))), 0) FROM knowledge_snapshots").fetchone()
                if count >= self.max_snapshots or size + len(payload.encode("utf-8")) > self.max_total_bytes:
                    raise KnowledgeStoreError("knowledge-store-capacity-exceeded")
                entered = True
                db.execute("INSERT INTO knowledge_snapshots VALUES (?, ?, ?, ?)",
                           (snapshot.namespace, snapshot.version, digest, payload))
            return digest
        except KnowledgeStoreError:
            raise
        except Exception:
            raise KnowledgeStoreError("knowledge-snapshot-save-failed", may_have_written=entered) from None

    async def load(self, namespace: str, version: str) -> KnowledgeSnapshot:
        try:
            _label(namespace)
            _label(version)
        except Exception:
            raise KnowledgeStoreError("knowledge-snapshot-identity-invalid") from None
        return await _worker(lambda: self._load(namespace, version))

    def _load(self, namespace: str, version: str) -> KnowledgeSnapshot:
        try:
            with closing(self._connect("ro")) as db, db:
                db.execute("BEGIN")
                self._check(db)
                row = self._row(db, namespace, version)
                if row is None:
                    raise KnowledgeStoreError("knowledge-version-not-found")
                return _decode(row[0], row[1], namespace, version)
        except KnowledgeStoreError:
            raise
        except Exception:
            raise KnowledgeStoreError("knowledge-snapshot-load-failed") from None
