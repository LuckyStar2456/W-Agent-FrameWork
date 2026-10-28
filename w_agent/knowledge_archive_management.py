"""Explicit local raw-archive management; no execution or directory restore.

Database files, source roots, output directories and ancestors are host-owned
and quiescent. Link checks are not an OS sandbox against concurrent renames.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

from w_agent.knowledge_archives import (
    KnowledgeArchiveError, KnowledgeArchiveReceipt, KnowledgeRawBlob,
    SQLiteKnowledgeRawArchive, archive_knowledge_sources,
)
from w_agent.knowledge_files import _digest, _reject_link
from w_agent.knowledge_import_store import SQLiteKnowledgeImportStore
from w_agent.knowledge_ingestion import _label
from w_agent.knowledge_sqlite import _worker


def _flags(request: object, *required: str) -> None:
    for name in request.__dataclass_fields__:
        if name.startswith("confirm_") and type(getattr(request, name)) is not bool:
            raise KnowledgeArchiveError("archive-confirmation-invalid")
    if any(getattr(request, name) is not True for name in required):
        raise KnowledgeArchiveError("archive-operation-not-authorized")


def _path(value: str | Path) -> Path:
    """Pure validation only: confirmations precede any filesystem operation."""
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise KnowledgeArchiveError("archive-path-invalid")
    candidate = Path(value)
    parts = candidate.parts[1:] if candidate.anchor else candidate.parts
    if (any(ord(char) < 32 or ord(char) == 127 for char in str(value))
            or any(part == ".." or part.endswith((".", " ")) or ":" in part
                   or PureWindowsPath(part).is_reserved() for part in parts)):
        raise KnowledgeArchiveError("archive-path-invalid")
    return candidate.absolute()


def _checked_file(path: Path, *, missing: bool = False) -> None:
    try:
        for parent in reversed(path.parents):
            info = parent.lstat()
            _reject_link(info)
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError
        try:
            info = path.lstat()
        except FileNotFoundError:
            if missing:
                return
            raise
        _reject_link(info)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError
    except Exception:
        raise KnowledgeArchiveError("archive-file-unavailable-or-linked") from None


def _separate(source: Path, target: Path) -> None:
    if os.path.normcase(str(source)) == os.path.normcase(str(target)):
        raise KnowledgeArchiveError("archive-databases-must-differ")
    try:
        same = source.samefile(target)
    except FileNotFoundError:
        same = False
    except OSError:
        raise KnowledgeArchiveError("archive-database-identity-unavailable") from None
    if same:
        raise KnowledgeArchiveError("archive-databases-must-differ")


@dataclass(frozen=True, slots=True)
class KnowledgeArchivePreviewRequest:
    trace_database: Path = field(repr=False)
    namespace: str = field(repr=False)
    version: str = field(repr=False)
    confirm_read: bool = False

    def __post_init__(self) -> None:
        _flags(self, "confirm_read")
        _label(self.namespace)
        _label(self.version)
        object.__setattr__(self, "trace_database", _path(self.trace_database))


@dataclass(frozen=True, slots=True)
class KnowledgeArchiveCreateRequest:
    trace_database: Path = field(repr=False)
    archive_database: Path = field(repr=False)
    root: Path = field(repr=False)
    namespace: str = field(repr=False)
    version: str = field(repr=False)
    expected_trace_digest: str
    confirm_read: bool = False
    confirm_sources: bool = False
    confirm_write: bool = False
    confirm_create: bool = False

    def __post_init__(self) -> None:
        _flags(self, "confirm_read", "confirm_sources", "confirm_write")
        _label(self.namespace)
        _label(self.version)
        _digest(self.expected_trace_digest)
        for name in ("trace_database", "archive_database", "root"):
            object.__setattr__(self, name, _path(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class KnowledgeArchiveInspectRequest:
    archive_database: Path = field(repr=False)
    trace_digest: str
    confirm_read: bool = False

    def __post_init__(self) -> None:
        _flags(self, "confirm_read")
        _digest(self.trace_digest)
        object.__setattr__(self, "archive_database", _path(self.archive_database))


@dataclass(frozen=True, slots=True)
class KnowledgeArchiveExportRequest:
    archive_database: Path = field(repr=False)
    trace_digest: str
    expected_receipt_digest: str
    blob_digest: str
    destination: Path = field(repr=False)
    confirm_read: bool = False
    confirm_export: bool = False
    confirm_path: bool = False

    def __post_init__(self) -> None:
        _flags(self, "confirm_read", "confirm_export", "confirm_path")
        for name in ("trace_digest", "expected_receipt_digest", "blob_digest"):
            _digest(getattr(self, name))
        for name in ("archive_database", "destination"):
            object.__setattr__(self, name, _path(getattr(self, name)))


def _receipt_summary(receipt: KnowledgeArchiveReceipt) -> dict:
    return {"trace_digest": receipt.trace_digest, "receipt_digest": receipt.digest,
            "blob_count": len(receipt.blob_digests), "blob_digests": list(receipt.blob_digests)}


async def preview_local_knowledge_archive(request: KnowledgeArchivePreviewRequest) -> dict:
    """Read exact saved version; return approval hash/counts, no source paths/text."""
    if not isinstance(request, KnowledgeArchivePreviewRequest):
        raise TypeError("typed archive preview request required")
    _flags(request, "confirm_read")
    await _worker(lambda: _checked_file(request.trace_database))
    trace = await SQLiteKnowledgeImportStore(request.trace_database).load(request.namespace, request.version)
    records = trace.imported.records
    return {"trace_digest": trace.digest, "source_count": len(records),
            "blob_count": len({record.raw_digest for record in records}),
            "raw_bytes": sum(record.raw_bytes for record in records),
            "chunk_count": len(trace.snapshot.documents), "source_files_read": False}


async def archive_local_knowledge_sources(request: KnowledgeArchiveCreateRequest) -> dict:
    """Approve exact saved trace, then read originals; no implicit DB adoption."""
    if not isinstance(request, KnowledgeArchiveCreateRequest):
        raise TypeError("typed archive creation request required")
    _flags(request, "confirm_read", "confirm_sources", "confirm_write")

    def check() -> None:
        _checked_file(request.trace_database)
        _checked_file(request.archive_database, missing=request.confirm_create)
        _separate(request.trace_database, request.archive_database)

    await _worker(check)
    trace = await SQLiteKnowledgeImportStore(request.trace_database).load(request.namespace, request.version)
    if trace.digest != request.expected_trace_digest:
        raise KnowledgeArchiveError("archive-trace-approval-mismatch")
    archive = SQLiteKnowledgeRawArchive(request.archive_database)

    class ApprovedDestination:
        async def save(self, receipt, blobs, *, confirm_write=False):
            # Only after every source was read and verified by archive_knowledge_sources.
            if request.confirm_create:
                await archive.initialize(confirm_create=True)
            return await archive.save(receipt, blobs, confirm_write=confirm_write)

    receipt = await archive_knowledge_sources(
        trace, request.root, ApprovedDestination(), expected_trace_digest=request.expected_trace_digest,
        confirm_read=True, confirm_write=True,
    )
    return {**_receipt_summary(receipt), "archived": True}


async def inspect_local_knowledge_archive(request: KnowledgeArchiveInspectRequest) -> dict:
    """Verify receipt and referenced blob hashes read-only, without returning bytes."""
    if not isinstance(request, KnowledgeArchiveInspectRequest):
        raise TypeError("typed archive inspection request required")
    _flags(request, "confirm_read")
    await _worker(lambda: _checked_file(request.archive_database))
    receipt = await SQLiteKnowledgeRawArchive(request.archive_database).receipt(request.trace_digest, confirm_read=True)
    return {**_receipt_summary(receipt), "verified": True}


def _new_destination(path: Path) -> None:
    _checked_file(path, missing=True)
    if path.exists():
        raise KnowledgeArchiveError("archive-export-destination-exists")


def _write_new_blob(path: Path, data: bytes) -> None:
    """Exclusive file creation; never truncate, follow links, mkdir or execute."""
    descriptor, owned = None, None
    try:
        _new_destination(path)
        parent_identity = path.parent.stat()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        owned = os.fstat(descriptor)
        if not stat.S_ISREG(owned.st_mode):
            raise ValueError
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(data)
            output.flush()
            os.fsync(descriptor)
        _checked_file(path)
        current, parent = path.stat(), path.parent.stat()
        if ((current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino)
                or (parent.st_dev, parent.st_ino) != (parent_identity.st_dev, parent_identity.st_ino)):
            raise ValueError
    except Exception:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
            descriptor = None
        # Remove only our still-identifiable file. Never erase a replacement.
        if owned is not None:
            try:
                _checked_file(path)
                current = path.lstat()
                if owned.st_ino and (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                    path.unlink()
            except Exception:
                pass  # Retained partial file is possible; do not mask original failure.
        raise KnowledgeArchiveError("archive-export-failed-inspect-destination-partial-file-may-remain") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


async def export_local_knowledge_blob(request: KnowledgeArchiveExportRequest) -> dict:
    """Read approved receipt membership, verify bytes, write a single new file."""
    if not isinstance(request, KnowledgeArchiveExportRequest):
        raise TypeError("typed archive export request required")
    _flags(request, "confirm_read", "confirm_export", "confirm_path")

    def check() -> None:
        _checked_file(request.archive_database)
        _new_destination(request.destination)

    await _worker(check)
    archive = SQLiteKnowledgeRawArchive(request.archive_database)
    receipt = await archive.receipt(request.trace_digest, confirm_read=True)
    if receipt.digest != request.expected_receipt_digest or request.blob_digest not in receipt.blob_digests:
        raise KnowledgeArchiveError("archive-export-receipt-or-blob-approval-mismatch")
    blob = KnowledgeRawBlob(request.blob_digest, await archive.load(request.blob_digest, confirm_read=True))
    await _worker(lambda: _write_new_blob(request.destination, blob.data))
    return {"exported": True, "trace_digest": receipt.trace_digest, "receipt_digest": receipt.digest,
            "blob_digest": blob.digest, "bytes": len(blob.data)}
