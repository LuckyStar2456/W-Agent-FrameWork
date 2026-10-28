import hashlib
import sqlite3
from dataclasses import replace

import pytest

from w_agent.knowledge_archives import (
    KnowledgeArchiveError, KnowledgeArchiveReceipt, KnowledgeRawBlob,
    SQLiteKnowledgeRawArchive, archive_knowledge_sources,
)
from w_agent.knowledge_files import LocalTextKnowledgeImporter
from w_agent.knowledge_provenance import prepare_traced_knowledge_import


async def trace(tmp_path, files=None):
    files = files if files is not None else {"a.md": b"hello", "b.md": b"hello"}
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    imported = await LocalTextKnowledgeImporter(tmp_path).load(tuple(files), confirm_read=True)
    return prepare_traced_knowledge_import("manual", "v1", imported)


@pytest.mark.asyncio
async def test_raw_archive_roundtrip_dedup_trace_binding_and_reopen(tmp_path):
    traced = await trace(tmp_path)
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db")
    await archive.initialize(confirm_create=True)
    receipt = await archive_knowledge_sources(traced, tmp_path, archive, expected_trace_digest=traced.digest,
                                              confirm_read=True, confirm_write=True)
    assert receipt.trace_digest == traced.digest and len(receipt.blob_digests) == 1
    reopened = SQLiteKnowledgeRawArchive(tmp_path / "raw.db")
    assert await reopened.receipt(traced.digest, confirm_read=True) == receipt
    assert await reopened.load(receipt.blob_digests[0], confirm_read=True) == b"hello"
    assert await archive_knowledge_sources(traced, tmp_path, reopened, expected_trace_digest=traced.digest,
                                           confirm_read=True, confirm_write=True) == receipt
    with sqlite3.connect(tmp_path / "raw.db") as db:
        assert db.execute("select count(*) from archive_blobs").fetchone() == (1,)
    assert b"hello".decode() not in repr(KnowledgeRawBlob(receipt.blob_digests[0], b"hello"))


@pytest.mark.asyncio
@pytest.mark.parametrize("permission", ["read", "write", "digest"])
async def test_missing_authority_no_read_or_write(tmp_path, permission):
    traced = await trace(tmp_path)
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db")
    options = dict(expected_trace_digest=traced.digest, confirm_read=True, confirm_write=True)
    options["expected_trace_digest" if permission == "digest" else "confirm_" + permission] = "0" * 64 if permission == "digest" else False
    with pytest.raises((KnowledgeArchiveError, ValueError)):
        await archive_knowledge_sources(traced, tmp_path, archive, **options)
    assert not archive.database_path.exists()


@pytest.mark.asyncio
async def test_source_drift_validated_entire_batch_before_any_archive_save(tmp_path):
    traced = await trace(tmp_path, {"a.md": b"first", "b.md": b"second"})
    (tmp_path / "b.md").write_bytes(b"change")
    class RejectSave:
        async def save(self, *args, **kwargs):
            pytest.fail("no archive call before all sources verify")
    with pytest.raises(KnowledgeArchiveError, match="source-changed"):
        await archive_knowledge_sources(traced, tmp_path, RejectSave(), expected_trace_digest=traced.digest,
                                       confirm_read=True, confirm_write=True)


@pytest.mark.asyncio
async def test_archive_capacity_atomic_no_partial_blobs(tmp_path):
    traced = await trace(tmp_path, {"a.md": b"first", "b.md": b"second"})
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db", max_blobs=1)
    await archive.initialize(confirm_create=True)
    with pytest.raises(KnowledgeArchiveError, match="capacity"):
        await archive_knowledge_sources(traced, tmp_path, archive, expected_trace_digest=traced.digest,
                                       confirm_read=True, confirm_write=True)
    with sqlite3.connect(archive.database_path) as db:
        assert db.execute("select count(*) from archive_blobs").fetchone() == (0,)
        assert db.execute("select count(*) from archive_traces").fetchone() == (0,)


@pytest.mark.asyncio
async def test_archive_missing_read_no_creation_and_explicit_read_required(tmp_path):
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db")
    for confirmed in (False, True):
        with pytest.raises(KnowledgeArchiveError):
            await archive.load("0" * 64, confirm_read=confirmed)
    assert not archive.database_path.exists()
    with pytest.raises(KnowledgeArchiveError):
        await archive.initialize()


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["blob", "receipt"])
async def test_archive_corruption_fails_closed(tmp_path, corruption):
    traced = await trace(tmp_path)
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db")
    await archive.initialize(confirm_create=True)
    await archive_knowledge_sources(traced, tmp_path, archive, expected_trace_digest=traced.digest,
                                   confirm_read=True, confirm_write=True)
    with sqlite3.connect(archive.database_path) as db:
        db.execute("UPDATE archive_blobs SET payload = ?", (b"wrong",)) if corruption == "blob" else db.execute("DELETE FROM archive_sources")
    with pytest.raises(KnowledgeArchiveError):
        await archive.receipt(traced.digest, confirm_read=True)


@pytest.mark.asyncio
async def test_empty_manifest_receipt_and_inert_binary_storage(tmp_path):
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db")
    await archive.initialize(confirm_create=True)
    traced = await trace(tmp_path, {})
    receipt = await archive_knowledge_sources(traced, tmp_path, archive, expected_trace_digest=traced.digest,
                                             confirm_read=True, confirm_write=True)
    assert receipt.blob_digests == ()
    data = b"\x00MZ malicious-looking bytes are never executed"
    blob = KnowledgeRawBlob(hashlib.sha256(data).hexdigest(), data)
    binary_receipt = KnowledgeArchiveReceipt("a" * 64, (blob.digest,))
    await archive.save(binary_receipt, (blob,), confirm_write=True)
    assert await archive.load(blob.digest, confirm_read=True) == data


@pytest.mark.asyncio
async def test_archive_receipt_conflict_and_wrong_store_response(tmp_path):
    traced = await trace(tmp_path)
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db")
    await archive.initialize(confirm_create=True)
    await archive_knowledge_sources(traced, tmp_path, archive, expected_trace_digest=traced.digest,
                                   confirm_read=True, confirm_write=True)
    with pytest.raises(KnowledgeArchiveError, match="conflict"):
        await archive.save(KnowledgeArchiveReceipt(traced.digest, ()), (), confirm_write=True)
    class WrongStore:
        async def save(self, receipt, blobs, *, confirm_write):
            return replace(receipt, trace_digest="0" * 64)
    with pytest.raises(KnowledgeArchiveError, match="receipt-mismatch"):
        await archive_knowledge_sources(traced, tmp_path, WrongStore(), expected_trace_digest=traced.digest,
                                       confirm_read=True, confirm_write=True)


@pytest.mark.asyncio
async def test_raw_archive_total_capacity_and_batch_shape_reject_before_write(tmp_path):
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db", max_total_bytes=3)
    await archive.initialize(confirm_create=True)
    data = b"large"
    blob = KnowledgeRawBlob(hashlib.sha256(data).hexdigest(), data)
    receipt = KnowledgeArchiveReceipt("a" * 64, (blob.digest,))
    with pytest.raises(KnowledgeArchiveError, match="batch-invalid"):
        await archive.save(receipt, (), confirm_write=True)
    with pytest.raises(KnowledgeArchiveError, match="not-authorized"):
        await archive.save(receipt, (blob,))
    with pytest.raises(KnowledgeArchiveError, match="capacity"):
        await archive.save(receipt, (blob,), confirm_write=True)
    with pytest.raises(ValueError):
        KnowledgeRawBlob(blob.digest, b"different")
    with sqlite3.connect(archive.database_path) as db:
        assert db.execute("select count(*) from archive_blobs").fetchone() == (0,)


@pytest.mark.asyncio
async def test_source_missing_or_nonregular_is_never_archived(tmp_path):
    traced = await trace(tmp_path, {"a.md": b"source"})
    (tmp_path / "a.md").unlink()
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db")
    for directory in (False, True):
        if directory:
            (tmp_path / "a.md").mkdir()
        with pytest.raises(KnowledgeArchiveError, match="source-changed"):
            await archive_knowledge_sources(traced, tmp_path, archive, expected_trace_digest=traced.digest,
                                           confirm_read=True, confirm_write=True)
    assert not archive.database_path.exists()


@pytest.mark.asyncio
async def test_other_sqlite_database_not_adopted(tmp_path):
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db")
    with sqlite3.connect(archive.database_path) as db:
        db.execute("CREATE TABLE existing (value TEXT)")
    with pytest.raises(KnowledgeArchiveError, match="unsupported"):
        await archive.initialize(confirm_create=True)
    with sqlite3.connect(archive.database_path) as db:
        assert db.execute("SELECT name FROM sqlite_master").fetchall() == [("existing",)]
