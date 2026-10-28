"""Draft pure preparation and persistent knowledge-version regressions; unrun."""

import asyncio
import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from uuid import UUID

import pytest

from w_agent import (
    KnowledgeDocument, KnowledgeRetrievalError, KnowledgeSnapshot, KnowledgeStoreError,
    KeywordKnowledgeRetriever, SQLiteKnowledgeSnapshotStore, Utf8KnowledgeTextSplitter,
    prepare_knowledge_snapshot,
)
from w_agent.knowledge_sqlite import _worker


def source(text="refund rules", *, identity="faq", title="Title", reference="manual:faq"):
    return KnowledgeDocument(identity, text, reference, title)


def snapshot(version="v1", text="refund rules"):
    return prepare_knowledge_snapshot("客服", version, (source(text),))


def test_utf8_splitter_preserves_multibyte_characters_without_normalization():
    text = "退款🙂说明abc e\u0301"
    chunks = Utf8KnowledgeTextSplitter(7).split(text)
    assert "".join(chunks) == text
    assert all(0 < len(chunk.encode("utf-8")) <= 7 for chunk in chunks)
    assert Utf8KnowledgeTextSplitter(4).split("a       b") == ("a   ", "b")
    assert len(Utf8KnowledgeTextSplitter(4).split("a" * 4096)) == 1024
    with pytest.raises(ValueError):
        Utf8KnowledgeTextSplitter(4).split("a" * 4097)


@pytest.mark.parametrize("size", [True, 0, 3, 1024 * 1024 + 1, 4.0])
def test_bad_chunk_configuration(size):
    with pytest.raises(ValueError):
        Utf8KnowledgeTextSplitter(size)


def test_preparation_ids_bind_version_namespace_parent_chunk_body_and_citations():
    first = snapshot()
    assert first == snapshot() and first.digest == snapshot().digest
    identity = first.documents[0].document_id
    assert str(UUID(identity)) == identity
    assert first.documents[0].source == "manual:faq" and first.documents[0].title == "Title"
    variants = (
        snapshot("v2"), snapshot(text="changed"),
        prepare_knowledge_snapshot("other", "v1", (source(),)),
        prepare_knowledge_snapshot("客服", "v1", (source(identity=1),)),
        prepare_knowledge_snapshot("客服", "v1", (source(title="Other"),)),
        prepare_knowledge_snapshot("客服", "v1", (source(reference="other"),)),
        prepare_knowledge_snapshot("客服", "v1", (source(),), splitter=Utf8KnowledgeTextSplitter(4)),
    )
    assert all(item.documents[0].document_id != identity for item in variants)
    assert "refund rules" not in repr(first)
    assert json.loads(first.to_json())["documents"][0]["text"] == "refund rules"
    assert first.digest == hashlib.sha256(first.to_json().encode("utf-8")).hexdigest()


def test_empty_snapshot_and_user_named_versions_are_explicit():
    empty = prepare_knowledge_snapshot("本地知识", "试验方案 A", ())
    assert empty.documents == ()
    assert empty.as_document_store().documents == ()
    assert KnowledgeSnapshot("namespace", "v1", (source(),)).digest != KnowledgeSnapshot("namespace", "v2", (source(),)).digest


@pytest.mark.parametrize("chunks", [[], (), ("",), (" ",), (1,), ("a",) * 1025])
def test_custom_splitter_results_are_validated(chunks):
    class Splitter:
        def split(self, text):
            return chunks

    with pytest.raises(KnowledgeRetrievalError, match="^knowledge snapshot preparation failed$"):
        prepare_knowledge_snapshot("n", "v", (source(),), splitter=Splitter())


def test_input_batch_is_validated_before_custom_splitter_and_errors_are_sanitized():
    class Splitter:
        calls = 0

        def split(self, text):
            self.calls += 1
            raise RuntimeError("PRIVATE_BODY")

    splitter = Splitter()
    with pytest.raises(KnowledgeRetrievalError):
        prepare_knowledge_snapshot("n", "v", (source(), source()), splitter=splitter)
    assert splitter.calls == 0
    with pytest.raises(KnowledgeRetrievalError) as error:
        prepare_knowledge_snapshot("n", "v", (source(),), splitter=splitter)
    assert splitter.calls == 1 and "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("label", ["", " ", "x\n", "a" * 129, "中" * 43, 1])
def test_version_labels_are_bounded_and_noncontrol(label):
    with pytest.raises(ValueError):
        KnowledgeSnapshot("namespace", label, ())


@pytest.mark.asyncio
async def test_no_implicit_database_creation_or_unauthorized_write(tmp_path):
    path = tmp_path / "knowledge.sqlite"
    store = SQLiteKnowledgeSnapshotStore(path)
    assert not path.exists()
    with pytest.raises(KnowledgeStoreError):
        await store.load("客服", "v1")
    assert not path.exists()
    for operation in (store.initialize(), store.initialize(confirm_create=1), store.save(snapshot()),
                      store.save(snapshot(), confirm_write=1), store.save(snapshot(), confirm_write=True)):
        with pytest.raises(KnowledgeStoreError):
            await operation
    assert not path.exists()
    await store.initialize(confirm_create=True)
    await store.initialize(confirm_create=True)
    assert path.exists()
    with pytest.raises(KnowledgeStoreError, match="knowledge-snapshot-write-not-authorized"):
        await store.save(snapshot())


@pytest.mark.asyncio
async def test_durable_reopen_exact_versions_and_pinned_local_retrieval(tmp_path):
    store = SQLiteKnowledgeSnapshotStore(tmp_path / "knowledge.sqlite")
    await store.initialize(confirm_create=True)
    first, second = snapshot(), snapshot("v2", "changed refund policy")
    assert await store.save(first, confirm_write=True) == first.digest
    assert await store.save(first, confirm_write=True) == first.digest
    pinned = (await store.load("客服", "v1")).as_document_store()
    await store.save(second, confirm_write=True)
    reopened = SQLiteKnowledgeSnapshotStore(store.database_path)
    assert await reopened.load("客服", "v1") == first
    assert await reopened.load("客服", "v2") == second
    assert await pinned.get_many((first.documents[0].document_id,)) == first.documents
    assert await KeywordKnowledgeRetriever(pinned).retrieve("refund", limit=1) == first.documents
    with pytest.raises(KnowledgeStoreError, match="knowledge-version-not-found"):
        await reopened.load("客服", "latest")


@pytest.mark.asyncio
async def test_same_version_conflict_never_overwrites(tmp_path):
    store = SQLiteKnowledgeSnapshotStore(tmp_path / "knowledge.sqlite")
    await store.initialize(confirm_create=True)
    original = snapshot()
    await store.save(original, confirm_write=True)
    with pytest.raises(KnowledgeStoreError, match="knowledge-version-conflict") as error:
        await store.save(snapshot(text="changed"), confirm_write=True)
    assert not error.value.may_have_written
    assert await store.load("客服", "v1") == original


@pytest.mark.asyncio
async def test_concurrent_writers_commit_only_one_conflicting_version(tmp_path):
    path = tmp_path / "knowledge.sqlite"
    first, second = SQLiteKnowledgeSnapshotStore(path), SQLiteKnowledgeSnapshotStore(path)
    await first.initialize(confirm_create=True)
    candidates = (snapshot(text="one"), snapshot(text="two"))
    results = await asyncio.gather(first.save(candidates[0], confirm_write=True),
                                   second.save(candidates[1], confirm_write=True), return_exceptions=True)
    assert sum(isinstance(result, str) for result in results) == 1
    errors = [result for result in results if isinstance(result, KnowledgeStoreError)]
    assert len(errors) == 1 and errors[0].code == "knowledge-version-conflict"
    assert await first.load("客服", "v1") in candidates


@pytest.mark.asyncio
async def test_count_and_serialized_capacity_reject_without_partial_record(tmp_path):
    store = SQLiteKnowledgeSnapshotStore(tmp_path / "knowledge.sqlite", max_snapshots=1)
    await store.initialize(confirm_create=True)
    await store.save(snapshot(), confirm_write=True)
    with pytest.raises(KnowledgeStoreError, match="capacity"):
        await store.save(snapshot("v2"), confirm_write=True)
    assert await store.save(snapshot(), confirm_write=True) == snapshot().digest
    with pytest.raises(KnowledgeStoreError, match="not-found"):
        await store.load("客服", "v2")
    tiny = SQLiteKnowledgeSnapshotStore(tmp_path / "tiny.sqlite", max_total_bytes=1)
    await tiny.initialize(confirm_create=True)
    with pytest.raises(KnowledgeStoreError, match="capacity"):
        await tiny.save(snapshot(), confirm_write=True)


@pytest.mark.asyncio
async def test_foreign_database_and_missing_parent_are_not_adopted(tmp_path):
    path = tmp_path / "foreign.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE private_data (value TEXT)")
        db.execute("INSERT INTO private_data VALUES ('keep')")
    with pytest.raises(KnowledgeStoreError, match="unsupported"):
        await SQLiteKnowledgeSnapshotStore(path).initialize(confirm_create=True)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT value FROM private_data").fetchall() == [("keep",)]
    with pytest.raises(KnowledgeStoreError):
        await SQLiteKnowledgeSnapshotStore(tmp_path / "missing" / "db.sqlite").initialize(confirm_create=True)
    assert not (tmp_path / "missing").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("change_digest", [False, True])
async def test_tampered_payload_or_digest_fails_without_body_disclosure(tmp_path, change_digest):
    store = SQLiteKnowledgeSnapshotStore(tmp_path / "knowledge.sqlite")
    await store.initialize(confirm_create=True)
    await store.save(snapshot(), confirm_write=True)
    with closing(sqlite3.connect(store.database_path)) as db, db:
        if change_digest:
            db.execute("UPDATE knowledge_snapshots SET digest = 'PRIVATE_SECRET'")
        else:
            db.execute("UPDATE knowledge_snapshots SET payload = 'PRIVATE_SECRET'")
    with pytest.raises(KnowledgeStoreError) as error:
        await store.load("客服", "v1")
    assert "PRIVATE" not in str(error.value)


@pytest.mark.asyncio
async def test_worker_cancellation_drains_started_operation_before_return():
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def operation():
        started.set()
        release.wait()
        finished.set()
        return "may have committed"

    task = asyncio.create_task(_worker(operation))
    await asyncio.to_thread(started.wait)
    try:
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()  # Repeated cancellation must not orphan the worker.
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
