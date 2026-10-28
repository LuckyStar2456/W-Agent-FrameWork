"""Explicit bounded raw-source archival; bytes are never parsed or executed."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from w_agent.knowledge_files import LocalTextKnowledgeImporter, _digest, _reject_link, _stamp
from w_agent.knowledge_provenance import TracedKnowledgeImport
from w_agent.knowledge_sqlite import _worker
from w_agent.vector_retrieval import _integer, _timeout


class KnowledgeArchiveError(RuntimeError):
    """Fixed archive error; inspect local storage after interrupted writes."""


@dataclass(frozen=True, slots=True)
class KnowledgeRawBlob:
    digest: str
    data: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _digest(self.digest)
        if not isinstance(self.data, bytes) or len(self.data) > 1024 * 1024 or hashlib.sha256(self.data).hexdigest() != self.digest:
            raise ValueError("invalid raw knowledge blob")


@dataclass(frozen=True, slots=True)
class KnowledgeArchiveReceipt:
    """Content-addressed association to the exact complete source manifest.

    The validated trace owns relative-path/raw-digest mapping. This receipt does
    not expose those paths or originals; caller retains the trace separately.
    """

    trace_digest: str
    blob_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.trace_digest)
        if not isinstance(self.blob_digests, tuple) or len(self.blob_digests) > 1024:
            raise ValueError("invalid knowledge archive receipt")
        for digest in self.blob_digests:
            _digest(digest)
        if tuple(sorted(set(self.blob_digests))) != self.blob_digests:
            raise ValueError("archive blob digests must be sorted and unique")

    @property
    def digest(self) -> str:
        payload = json.dumps(["wagent-raw-archive-receipt-v1", self.trace_digest, self.blob_digests], separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class KnowledgeRawArchive(Protocol):
    """Replaceable immutable storage; save binds all blobs to an exact trace."""

    async def save(self, receipt: KnowledgeArchiveReceipt, blobs: tuple[KnowledgeRawBlob, ...], *, confirm_write: bool = False) -> KnowledgeArchiveReceipt: ...

    async def load(self, digest: str, *, confirm_read: bool = False) -> bytes: ...

    async def receipt(self, trace_digest: str, *, confirm_read: bool = False) -> KnowledgeArchiveReceipt: ...


_APPLICATION_ID = 0x57415241
_TABLES = {
    "archive_blobs": "CREATE TABLE archive_blobs (digest TEXT PRIMARY KEY, payload BLOB NOT NULL)",
    "archive_sources": "CREATE TABLE archive_sources (trace_digest TEXT NOT NULL, blob_digest TEXT NOT NULL, PRIMARY KEY (trace_digest, blob_digest))",
    "archive_traces": "CREATE TABLE archive_traces (trace_digest TEXT PRIMARY KEY, receipt_digest TEXT NOT NULL)",
}


@dataclass(frozen=True, slots=True)
class SQLiteKnowledgeRawArchive:
    """Dedicated atomic content-addressed SQLite template, plaintext raw bytes.

    No directory creation, migration, replacement, restore, garbage collection
    or execution. Bounds are logical payload limits, not physical disk quotas.
    Host must protect this database, its ancestors and its source tree.
    """

    database_path: Path = field(repr=False)
    timeout: float = 5.0
    max_blobs: int = 4096
    max_traces: int = 1024
    max_total_bytes: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (str, Path)) or not str(self.database_path).strip() or str(self.database_path) == ":memory:":
            raise ValueError("raw archive requires a local database file")
        object.__setattr__(self, "database_path", Path(self.database_path).absolute())
        _timeout(self.timeout)
        _integer(self.max_blobs, 65536)
        _integer(self.max_traces, 4096)
        _integer(self.max_total_bytes, 2**31)

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
        objects = db.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' ORDER BY name").fetchall()
        if (db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != 1
                or objects != [("table", name, _TABLES[name]) for name in sorted(_TABLES)]):
            raise KnowledgeArchiveError("knowledge-archive-database-unsupported")

    async def initialize(self, *, confirm_create: bool = False) -> None:
        if confirm_create is not True:
            raise KnowledgeArchiveError("knowledge-archive-create-not-authorized")
        def initialize() -> None:
            try:
                with closing(self._connect("rwc")) as db, db:
                    db.execute("BEGIN IMMEDIATE")
                    if db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone() is None:
                        if db.execute("PRAGMA application_id").fetchone()[0] != 0 or db.execute("PRAGMA user_version").fetchone()[0] != 0:
                            raise KnowledgeArchiveError("knowledge-archive-database-unsupported")
                        db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                        db.execute("PRAGMA user_version = 1")
                        for schema in _TABLES.values():
                            db.execute(schema)
                    self._check(db)
            except KnowledgeArchiveError:
                raise
            except Exception:
                raise KnowledgeArchiveError("knowledge-archive-initialize-failed-file-may-exist") from None
        await _worker(initialize)

    @staticmethod
    def _blob(db: sqlite3.Connection, digest: str) -> bytes:
        row = db.execute("SELECT CASE WHEN length(payload) <= 1048576 THEN payload END FROM archive_blobs WHERE digest = ?", (digest,)).fetchone()
        if row is None:
            raise KnowledgeArchiveError("knowledge-archive-blob-not-found")
        return KnowledgeRawBlob(digest, row[0]).data

    @staticmethod
    def _receipt(db: sqlite3.Connection, digest: str) -> KnowledgeArchiveReceipt:
        stored = db.execute("SELECT receipt_digest FROM archive_traces WHERE trace_digest = ?", (digest,)).fetchone()
        if stored is None:
            raise KnowledgeArchiveError("knowledge-archive-trace-not-found")
        rows = db.execute("SELECT blob_digest FROM archive_sources WHERE trace_digest = ? ORDER BY blob_digest LIMIT 1025", (digest,)).fetchall()
        result = KnowledgeArchiveReceipt(digest, tuple(row[0] for row in rows))
        if result.digest != stored[0]:
            raise KnowledgeArchiveError("knowledge-archive-receipt-corrupt")
        for blob_digest in result.blob_digests:
            SQLiteKnowledgeRawArchive._blob(db, blob_digest)
        return result

    async def save(self, receipt: KnowledgeArchiveReceipt, blobs: tuple[KnowledgeRawBlob, ...], *, confirm_write: bool = False) -> KnowledgeArchiveReceipt:
        if confirm_write is not True:
            raise KnowledgeArchiveError("knowledge-archive-write-not-authorized")
        if (not isinstance(receipt, KnowledgeArchiveReceipt) or not isinstance(blobs, tuple) or len(blobs) > 1024
                or any(not isinstance(blob, KnowledgeRawBlob) for blob in blobs)
                or tuple(sorted(blob.digest for blob in blobs)) != receipt.blob_digests
                or sum(len(blob.data) for blob in blobs) > 16 * 1024 * 1024):
            raise KnowledgeArchiveError("knowledge-archive-batch-invalid")
        return await _worker(lambda: self._save(receipt, blobs))

    def _save(self, receipt: KnowledgeArchiveReceipt, blobs: tuple[KnowledgeRawBlob, ...]) -> KnowledgeArchiveReceipt:
        try:
            with closing(self._connect("rw")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._check(db)
                if db.execute("SELECT 1 FROM archive_traces WHERE trace_digest = ?", (receipt.trace_digest,)).fetchone() is not None:
                    if self._receipt(db, receipt.trace_digest) != receipt:
                        raise KnowledgeArchiveError("knowledge-archive-receipt-conflict")
                    return receipt
                additions = []
                for blob in blobs:
                    if db.execute("SELECT 1 FROM archive_blobs WHERE digest = ?", (blob.digest,)).fetchone() is None:
                        additions.append(blob)
                    elif self._blob(db, blob.digest) != blob.data:
                        raise KnowledgeArchiveError("knowledge-archive-blob-conflict")
                count, size = db.execute("SELECT count(*), coalesce(sum(length(payload)), 0) FROM archive_blobs").fetchone()
                if (count + len(additions) > self.max_blobs or size + sum(len(blob.data) for blob in additions) > self.max_total_bytes
                        or db.execute("SELECT count(*) FROM archive_traces").fetchone()[0] >= self.max_traces):
                    raise KnowledgeArchiveError("knowledge-archive-capacity-exceeded")
                db.executemany("INSERT INTO archive_blobs VALUES (?, ?)", ((blob.digest, blob.data) for blob in additions))
                db.execute("INSERT INTO archive_traces VALUES (?, ?)", (receipt.trace_digest, receipt.digest))
                db.executemany("INSERT INTO archive_sources VALUES (?, ?)", ((receipt.trace_digest, digest) for digest in receipt.blob_digests))
            return receipt
        except KnowledgeArchiveError:
            raise
        except Exception:
            raise KnowledgeArchiveError("knowledge-archive-save-failed-inspect-before-retry") from None

    async def load(self, digest: str, *, confirm_read: bool = False) -> bytes:
        if confirm_read is not True:
            raise KnowledgeArchiveError("knowledge-archive-read-not-authorized")
        _digest(digest)
        return await _worker(lambda: self._read(digest, blob=True))

    async def receipt(self, trace_digest: str, *, confirm_read: bool = False) -> KnowledgeArchiveReceipt:
        if confirm_read is not True:
            raise KnowledgeArchiveError("knowledge-archive-read-not-authorized")
        _digest(trace_digest)
        return await _worker(lambda: self._read(trace_digest, blob=False))

    def _read(self, digest: str, *, blob: bool):
        try:
            with closing(self._connect("ro")) as db:
                db.execute("BEGIN")
                self._check(db)
                return self._blob(db, digest) if blob else self._receipt(db, digest)
        except KnowledgeArchiveError:
            raise
        except Exception:
            raise KnowledgeArchiveError("knowledge-archive-read-failed") from None


def _read_sources(trace: TracedKnowledgeImport, root: Path) -> tuple[KnowledgeRawBlob, ...]:
    """Re-read exact manifest only, with the importer's link/stamp restrictions."""
    try:
        importer = LocalTextKnowledgeImporter(root)
        for ancestor in reversed((importer.root, *importer.root.parents)):
            _reject_link(ancestor.lstat())
        total = 0
        blobs = {}
        for record in trace.imported.records:
            path, original = importer._checked(record.relative_path)
            if not stat.S_ISREG(original.st_mode) or original.st_size != record.raw_bytes or original.st_size > 1024 * 1024:
                raise ValueError
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            descriptor = os.open(path, flags)
            try:
                with os.fdopen(descriptor, "rb", closefd=False) as source:
                    before = os.fstat(descriptor)
                    if not stat.S_ISREG(before.st_mode) or _stamp(before) != _stamp(original):
                        raise ValueError
                    data = source.read(min(1024 * 1024, 16 * 1024 * 1024 - total) + 1)
                    if _stamp(before) != _stamp(os.fstat(descriptor)):
                        raise ValueError
            finally:
                os.close(descriptor)
            if len(data) != record.raw_bytes:
                raise ValueError
            total += len(data)
            if total > 16 * 1024 * 1024:
                raise ValueError
            blobs[record.raw_digest] = KnowledgeRawBlob(record.raw_digest, data)
        return tuple(blobs[digest] for digest in sorted(blobs))
    except Exception:
        raise KnowledgeArchiveError("knowledge-archive-source-changed-or-unavailable") from None


async def archive_knowledge_sources(
    trace: TracedKnowledgeImport, root: Path, archive: KnowledgeRawArchive, *,
    expected_trace_digest: str, confirm_read: bool = False, confirm_write: bool = False,
) -> KnowledgeArchiveReceipt:
    """Read approved original bytes, validate all, then explicitly archive.

    Nothing initializes the destination implicitly. The SQLite template commits
    blobs and trace association atomically; custom stores own their guarantees.
    No transaction spans the trace/sync databases. Cancellation drains workers
    and may follow a committed archive. SHA-256 is integrity, not authentication.
    """
    if confirm_read is not True or confirm_write is not True:
        raise KnowledgeArchiveError("knowledge-archive-source-operation-not-authorized")
    if not isinstance(trace, TracedKnowledgeImport):
        raise KnowledgeArchiveError("knowledge-archive-trace-invalid")
    _digest(expected_trace_digest)
    validated = TracedKnowledgeImport.from_json(trace.to_json(), expected_digest=expected_trace_digest)
    blobs = await _worker(lambda: _read_sources(validated, root))
    receipt = KnowledgeArchiveReceipt(expected_trace_digest, tuple(blob.digest for blob in blobs))
    saved = await archive.save(receipt, blobs, confirm_write=True)
    if saved != receipt:
        raise KnowledgeArchiveError("knowledge-archive-receipt-mismatch")
    return receipt
