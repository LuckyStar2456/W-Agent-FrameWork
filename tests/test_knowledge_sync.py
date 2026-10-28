"""Real local persistence and fake-network delta synchronization regressions."""

import asyncio
import json
import sqlite3
from dataclasses import replace

import pytest

from w_agent.knowledge_files import LocalTextKnowledgeImporter
from w_agent.knowledge_import_store import SQLiteKnowledgeImportStore
from w_agent.knowledge_provenance import prepare_traced_knowledge_import
from w_agent.knowledge_sqlite import KnowledgeStoreError
from w_agent.knowledge_sync import (
    KnowledgeSyncError, KnowledgeSyncIndex, KnowledgeSyncPlan, QdrantDeletePlan,
    SyncVectorKnowledgeRetriever, execute_knowledge_sync, knowledge_sync_retry_digest, prepare_knowledge_sync_index,
)
from w_agent.knowledge_sync_qdrant import QdrantKnowledgeSyncWriter
from w_agent.knowledge_sync_store import SQLiteKnowledgeSyncJournal
from w_agent.tools.http_adapter import HttpToolResponse
from w_agent.vector_indexing import DenseVectorPoint, QdrantVectorWriter, VectorIndexWriteError
from w_agent.vector_retrieval import QdrantVectorSearch, VectorSearchMatch


class Embedder:
    def __init__(self):
        self.calls = []

    async def embed(self, text):
        self.calls.append(text)
        return (1.0, 2.0)


class Transport:
    def __init__(self):
        self.requests = []
        self.status = "completed"
        self.failure = None

    async def send(self, request):
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return HttpToolResponse(200, {}, json.dumps({"status": "ok", "result": {"status": self.status, "operation_id": 1}}).encode())


async def trace(tmp_path, version, files, *, chunk_bytes=4096, previous=None):
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    imported = await LocalTextKnowledgeImporter(tmp_path).load(tuple(files), confirm_read=True, previous=previous)
    return prepare_traced_knowledge_import("manual", version, imported, chunk_bytes=chunk_bytes)


def writer(transport, **kwargs):
    return QdrantKnowledgeSyncWriter(QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "dedicated", transport=transport, **kwargs)))


async def index(trace, *, previous=None, embedding_key="model-v1", embedder=None, **options):
    return await prepare_knowledge_sync_index(trace, embedding_key, 2, embedder or Embedder(), previous=previous,
                                              confirm_embedding=True,
                                              confirm_reuse_digest=previous.digest if previous is not None else None, **options)


async def execute(plan, adapter, journal, **overrides):
    options = dict(confirm_plan_digest=plan.digest, confirm_upsert_digest=plan.upsert_digest,
                   confirm_delete_digest=plan.delete_digest, confirm_record=True)
    options.update(overrides)
    return await execute_knowledge_sync(plan, adapter, journal, **options)


@pytest.mark.asyncio
async def test_trace_cache_restart_incremental_parse_and_conflict(tmp_path):
    traced = await trace(tmp_path, "v1", {"a.md": "refund"})
    store = SQLiteKnowledgeImportStore(tmp_path / "trace.sqlite")
    assert not store.database_path.exists()
    with pytest.raises(KnowledgeStoreError):
        await store.save(traced)
    with pytest.raises(KnowledgeStoreError):
        await store.load("manual", "v1")
    assert not store.database_path.exists()
    await store.initialize(confirm_create=True)
    await store.save(traced, confirm_write=True)
    assert await store.save(traced, confirm_write=True) == traced.digest
    loaded = await SQLiteKnowledgeImportStore(store.database_path).load("manual", "v1")
    assert loaded == traced
    repeated = await LocalTextKnowledgeImporter(tmp_path).load(("a.md",), confirm_read=True, previous=loaded.imported)
    assert repeated == loaded.imported
    changed = await trace(tmp_path, "v1", {"a.md": "other"})
    with pytest.raises(KnowledgeStoreError, match="version-conflict"):
        await store.save(changed, confirm_write=True)
    assert await store.load("manual", "v1") == traced


@pytest.mark.asyncio
async def test_version_only_zero_embedding_and_zero_remote_writes(tmp_path):
    first = await index(await trace(tmp_path, "v1", {"a.md": "same"}))
    second_trace = await trace(tmp_path, "v2", {"a.md": "same"})
    with pytest.raises(KnowledgeSyncError):
        await prepare_knowledge_sync_index(second_trace, "model-v1", 2, previous=first)
    second = await prepare_knowledge_sync_index(second_trace, "model-v1", 2, previous=first, confirm_reuse_digest=first.digest)
    assert first.trace.snapshot.documents[0].document_id != second.trace.snapshot.documents[0].document_id
    assert first.points == second.points
    transport = Transport()
    adapter = writer(transport)
    journal = SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite")
    await journal.initialize(confirm_create=True)
    initial = KnowledgeSyncPlan(adapter.endpoint, None, first)
    assert (await execute(initial, adapter, journal)).finished
    delta = KnowledgeSyncPlan(adapter.endpoint, None, second, first)
    assert delta.upsert_points == delta.delete_ids == ()
    assert (await execute(delta, adapter, journal)).finished
    assert len(transport.requests) == 1
    reopened = await SQLiteKnowledgeSyncJournal(journal.database_path).load_plan(delta.digest)
    assert reopened == delta and reopened.current == second


@pytest.mark.asyncio
async def test_changed_added_removed_plan_reuses_unchanged_vectors_and_source_ids(tmp_path):
    first = await index(await trace(tmp_path, "v1", {"same.md": "keep", "change.md": "old", "gone.md": "remove"}))
    embedder = Embedder()
    second = await index(await trace(tmp_path, "v2", {"same.md": "keep", "change.md": "new", "added.md": "add"}), previous=first, embedder=embedder)
    assert len(embedder.calls) == 2
    assert all("keep" not in text for text in embedder.calls)
    transport = Transport()
    adapter = writer(transport)
    journal = SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite")
    await journal.initialize(confirm_create=True)
    await execute(KnowledgeSyncPlan(adapter.endpoint, None, first), adapter, journal)
    plan = KnowledgeSyncPlan(adapter.endpoint, None, second, first)
    assert len(plan.upsert_points) == len(plan.delete_ids) == 2
    assert plan.summary()["files"] == {"added": 1, "changed": 1, "removed": 1, "unchanged": 1}
    assert set(plan.delete_ids) == set(first.point_ids) - set(second.point_ids)
    before = len(transport.requests)
    with pytest.raises(KnowledgeSyncError, match="confirmation"):
        await execute(plan, adapter, journal, confirm_delete_digest=None)
    assert len(transport.requests) == before
    assert (await execute(plan, adapter, journal)).finished
    upsert, delete = transport.requests[-2:]
    assert upsert.method == "PUT" and delete.method == "POST"
    assert delete.url.endswith("/points/delete")
    assert delete.query == {"wait": "true"}
    assert delete.json_body == {"points": list(plan.delete_ids)}
    assert not (set(plan.delete_ids) & set(second.point_ids))
    await execute(plan, adapter, journal)
    assert len(transport.requests) == before + 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["model", "chunk", "raw"])
async def test_cache_keys_bind_model_chunk_configuration_and_raw_source(tmp_path, change):
    original = await trace(tmp_path, "v1", {"a.md": "abcdefgh"})
    previous = await index(original)
    key, chunk_bytes = ("model-v2" if change == "model" else "model-v1"), (4 if change == "chunk" else 4096)
    current = await trace(tmp_path, "v2", {"a.md": "abcdefgh"}, chunk_bytes=chunk_bytes)
    if change == "raw":
        (tmp_path / "a.md").write_bytes(b"\xef\xbb\xbfabcdefgh")
        loaded = await LocalTextKnowledgeImporter(tmp_path).load(("a.md",), confirm_read=True)
        current = prepare_traced_knowledge_import("manual", "v2", loaded)
    embedder = Embedder()
    prepared = await index(current, previous=previous, embedding_key=key, embedder=embedder)
    assert embedder.calls and not set(previous.point_ids).intersection(prepared.point_ids)


@pytest.mark.asyncio
async def test_embedding_authority_and_total_limits_before_calls(tmp_path):
    source = await trace(tmp_path, "v1", {"a.md": "private text"})
    embedder = Embedder()
    with pytest.raises(KnowledgeSyncError):
        await prepare_knowledge_sync_index(source, "model", 2, embedder)
    with pytest.raises(KnowledgeSyncError):
        await index(source, embedder=embedder, max_input_bytes=1)
    assert embedder.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("PRIVATE"), asyncio.CancelledError()])
async def test_unknown_upsert_blocks_replay_other_plans_and_head(tmp_path, failure):
    current = await index(await trace(tmp_path, "v1", {"a.md": "body"}))
    transport, journal = Transport(), SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite")
    adapter = writer(transport)
    await journal.initialize(confirm_create=True)
    plan = KnowledgeSyncPlan(adapter.endpoint, None, current)
    transport.failure = failure
    with pytest.raises((VectorIndexWriteError, asyncio.CancelledError)):
        await execute(plan, adapter, journal)
    assert (await journal.inspect(plan.digest)).outcomes == ("unknown",)
    transport.failure = None
    with pytest.raises(KnowledgeSyncError, match="no-replay"):
        await execute(plan, adapter, journal)
    other = await index(await trace(tmp_path, "v2", {"a.md": "next"}), previous=current)
    with pytest.raises(KnowledgeSyncError, match="conflict-or-unresolved"):
        await execute(KnowledgeSyncPlan(adapter.endpoint, None, other, current), adapter, journal)
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_acknowledged_upsert_does_not_delete_and_host_reconciliation_can_continue(tmp_path):
    first = await index(await trace(tmp_path, "v1", {"a.md": "old"}))
    second = await index(await trace(tmp_path, "v2", {"a.md": "new"}), previous=first)
    transport, journal = Transport(), SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite")
    adapter = writer(transport)
    await journal.initialize(confirm_create=True)
    await execute(KnowledgeSyncPlan(adapter.endpoint, None, first), adapter, journal)
    plan = KnowledgeSyncPlan(adapter.endpoint, None, second, first)
    transport.status = "acknowledged"
    assert (await execute(plan, adapter, journal)).outcomes == ("acknowledged", "ready")
    assert len(transport.requests) == 2
    await journal.reconcile_completed(plan.digest, 0, evidence_ref="host-check-1", confirm_applied=True,
                                      confirm_inactive=True, confirm_write=True)
    transport.status = "completed"
    assert (await execute(plan, adapter, journal)).finished
    assert len(transport.requests) == 3 and transport.requests[-1].method == "POST"
    observed = await journal.inspect_observations(plan.digest)
    assert observed[0]["outcome"] == "acknowledged" and observed[0]["operation_id"] == 1
    assert observed[0]["evidence_ref"] == "host-check-1"
    with sqlite3.connect(journal.database_path) as db:
        assert db.execute("SELECT outcome, evidence FROM sync_batches WHERE plan = ? AND position = 0", (plan.digest,)).fetchone() == ("acknowledged", "host-check-1")


@pytest.mark.asyncio
async def test_unknown_delete_never_replays_completed_upsert(tmp_path):
    first = await index(await trace(tmp_path, "v1", {"gone.md": "gone"}))
    second = await index(await trace(tmp_path, "v2", {}), previous=first)
    transport, journal = Transport(), SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite")
    adapter = writer(transport)
    await journal.initialize(confirm_create=True)
    await execute(KnowledgeSyncPlan(adapter.endpoint, None, first), adapter, journal)
    plan = KnowledgeSyncPlan(adapter.endpoint, None, second, first)
    transport.failure = RuntimeError("timeout")
    with pytest.raises(VectorIndexWriteError):
        await execute(plan, adapter, journal)
    assert (await journal.inspect(plan.digest)).outcomes == ("unknown",)
    transport.failure = None
    with pytest.raises(KnowledgeSyncError, match="no-replay"):
        await execute(plan, adapter, journal)
    assert len(transport.requests) == 2


@pytest.mark.asyncio
async def test_claim_is_atomic_across_journal_instances_and_stale_head_is_rejected(tmp_path):
    current = await index(await trace(tmp_path, "v1", {"a.md": "body"}))
    transport = Transport()
    adapter = writer(transport)
    first = SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite")
    second = SQLiteKnowledgeSyncJournal(first.database_path)
    await first.initialize(confirm_create=True)
    plan = KnowledgeSyncPlan(adapter.endpoint, None, current)
    await first.stage(plan, confirm_write=True)
    results = await asyncio.gather(first.claim(plan.digest, 0, confirm_write=True), second.claim(plan.digest, 0, confirm_write=True), return_exceptions=True)
    assert sum(isinstance(item, KnowledgeSyncError) for item in results) == 1
    assert (await second.inspect(plan.digest)).outcomes == ("pending",)
    assert not transport.requests


@pytest.mark.asyncio
async def test_plan_tampering_and_wrong_cache_vector_rejected(tmp_path):
    current = await index(await trace(tmp_path, "v1", {"a.md": "body"}))
    plan = KnowledgeSyncPlan("http://localhost:6333/collections/dedicated/points", None, current)
    assert KnowledgeSyncPlan.from_json(plan.to_json(), expected_digest=plan.digest) == plan
    with pytest.raises(KnowledgeSyncError):
        KnowledgeSyncPlan.from_json(plan.to_json().replace("body", "other"), expected_digest=plan.digest)
    with pytest.raises(ValueError):
        replace(current, points=(DenseVectorPoint("00000000-0000-0000-0000-000000000000", (1.0, 2.0)),))
    altered = replace(current, points=(DenseVectorPoint(current.point_ids[0], (9.0, 9.0)),))
    with pytest.raises(ValueError, match="cannot replace"):
        KnowledgeSyncPlan(plan.endpoint, None, altered, current)


@pytest.mark.asyncio
async def test_retrieval_resolves_current_snapshot_document_ids_not_remote_payload(tmp_path):
    current = await index(await trace(tmp_path, "v2", {"a.md": "refund"}))

    class Search:
        async def search(self, vector, *, limit, point_ids=None):
            assert point_ids == current.point_ids
            return (VectorSearchMatch(point_ids[0], 1.0),)

    result = await SyncVectorKnowledgeRetriever(current, Embedder(), Search()).retrieve("refund", limit=1)
    assert result == current.trace.snapshot.documents


@pytest.mark.asyncio
async def test_foreign_databases_capacity_corruption_and_delete_authority(tmp_path):
    foreign = tmp_path / "foreign.sqlite"
    with sqlite3.connect(foreign) as db:
        db.execute("CREATE TABLE private_data (value TEXT)")
    for store in (SQLiteKnowledgeImportStore(foreign), SQLiteKnowledgeSyncJournal(foreign)):
        with pytest.raises((KnowledgeStoreError, KnowledgeSyncError), match="unsupported"):
            await store.initialize(confirm_create=True)
    current = await index(await trace(tmp_path, "v1", {"a.md": "body"}))
    journal = SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite", max_total_bytes=1)
    await journal.initialize(confirm_create=True)
    transport = Transport()
    adapter = writer(transport)
    plan = KnowledgeSyncPlan(adapter.endpoint, None, current)
    with pytest.raises(KnowledgeSyncError, match="capacity"):
        await execute(plan, adapter, journal)
    assert not transport.requests
    delete = QdrantDeletePlan(adapter.endpoint + "/delete", current.point_ids)
    with pytest.raises(VectorIndexWriteError) as error:
        await adapter.delete(delete, confirm_digest="0" * 64)
    assert not error.value.may_have_written and not transport.requests
    await replace(journal, max_total_bytes=512 * 1024 * 1024).stage(plan, confirm_write=True)
    with sqlite3.connect(journal.database_path) as db:
        db.execute("UPDATE sync_plans SET payload = 'PRIVATE'")
    with pytest.raises(KnowledgeSyncError):
        await journal.load_plan(plan.digest)


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", [
    "https://EXAMPLE.com/collections/c/points", "https://example.com:443/collections/c/points",
    "http://example.com:80/collections/c/points", "https://example.com/collections/c/points/",
    "https://example.com/./collections/c/points", "https://example.com/x/../collections/c/points",
    "https://example.com/%63ollections/c/points", "https://example.com//collections/c/points",
    "https://example.com./collections/c/points", "https://user:secret@example.com/collections/c/points",
])
async def test_alias_spellings_rejected_before_journal_or_network(tmp_path, endpoint):
    current = await index(await trace(tmp_path, "v1", {"a.md": "body"}))
    with pytest.raises(ValueError, match="canonical"):
        KnowledgeSyncPlan(endpoint, None, current)


@pytest.mark.asyncio
async def test_completed_batch_resume_reuses_staged_vectors_without_resending(tmp_path):
    current = await index(await trace(tmp_path, "v1", {"a.md": "abcd" * 129}, chunk_bytes=4))
    transport, journal = Transport(), SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite")
    adapter = writer(transport)
    await journal.initialize(confirm_create=True)
    plan = KnowledgeSyncPlan(adapter.endpoint, None, current)

    class InterruptAfterReceipt:
        stage = journal.stage
        claim = journal.claim

        async def record(self, *args, **kwargs):
            await journal.record(*args, **kwargs)
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await execute(plan, adapter, InterruptAfterReceipt())
    assert (await journal.inspect(plan.digest)).outcomes == ("completed", "ready")
    saved = await SQLiteKnowledgeSyncJournal(journal.database_path).load_plan(plan.digest)
    assert (await execute(saved, adapter, journal)).finished
    assert [len(request.json_body["points"]) for request in transport.requests] == [128, 1]


@pytest.mark.asyncio
async def test_empty_initial_plan_requires_consent_then_advances_head_without_network(tmp_path):
    empty = await index(await trace(tmp_path, "empty", {}))
    transport, journal = Transport(), SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite")
    adapter = writer(transport)
    await journal.initialize(confirm_create=True)
    plan = KnowledgeSyncPlan(adapter.endpoint, None, empty)
    with pytest.raises(KnowledgeSyncError):
        await execute(plan, adapter, journal, confirm_record=False)
    assert (await execute(plan, adapter, journal)).finished
    current = await index(await trace(tmp_path, "v2", {"a.md": "body"}), previous=empty)
    assert (await execute(KnowledgeSyncPlan(adapter.endpoint, None, current, empty), adapter, journal)).finished
    assert len(transport.requests) == 1
    with pytest.raises(KnowledgeSyncError, match="conflict"):
        await execute(KnowledgeSyncPlan(adapter.endpoint, None, current), adapter, journal)


@pytest.mark.asyncio
async def test_named_vector_switch_cannot_skip_writes_using_previous_cache(tmp_path):
    current = await index(await trace(tmp_path, "v1", {"a.md": "body"}))
    transport, journal = Transport(), SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite")
    adapter = writer(transport)
    await journal.initialize(confirm_create=True)
    await execute(KnowledgeSyncPlan(adapter.endpoint, None, current), adapter, journal)
    named = writer(transport, vector_name="other")
    with pytest.raises(KnowledgeSyncError, match="conflict"):
        await execute(KnowledgeSyncPlan(adapter.endpoint, "other", current, current), named, journal)
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_trace_store_rejects_payload_corruption_without_disclosure(tmp_path):
    source = await trace(tmp_path, "v1", {"a.md": "body"})
    store = SQLiteKnowledgeImportStore(tmp_path / "trace.sqlite")
    await store.initialize(confirm_create=True)
    await store.save(source, confirm_write=True)
    with sqlite3.connect(store.database_path) as db:
        db.execute("UPDATE knowledge_imports SET payload = 'PRIVATE'")
    with pytest.raises(KnowledgeStoreError, match="^knowledge-import-load-failed$"):
        await store.load("manual", "v1")


@pytest.mark.asyncio
async def test_confirmed_not_sent_explicit_retry_keeps_old_attempt_and_uses_new_generation(tmp_path):
    current = await index(await trace(tmp_path, "v1", {"a.md": "body"}))
    transport, journal = Transport(), SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite")
    tiny = writer(transport, max_request_bytes=1)
    await journal.initialize(confirm_create=True)
    plan = KnowledgeSyncPlan(tiny.endpoint, None, current)
    with pytest.raises(VectorIndexWriteError) as error:
        await execute(plan, tiny, journal)
    assert error.value.may_have_written is False and not transport.requests
    assert (await journal.inspect(plan.digest)).outcomes == ("not-sent",)
    approval = knowledge_sync_retry_digest(plan.digest, 0, 0)
    with pytest.raises(KnowledgeSyncError):
        await journal.retry_not_sent(plan.digest, 0, generation=0, retry_id="retry-1", confirm_retry_digest="0" * 64, confirm_write=True)
    await journal.retry_not_sent(plan.digest, 0, generation=0, retry_id="retry-1", confirm_retry_digest=approval, confirm_write=True)
    assert (await journal.inspect(plan.digest)).outcomes == ("ready",)
    history = await SQLiteKnowledgeSyncJournal(journal.database_path).inspect_retries(plan.digest)
    assert [(item.batch, item.generation, item.retry_id, item.prior_outcome) for item in history] == [(0, 0, "retry-1", "not-sent")]
    assert (await execute(plan, writer(transport), journal)).finished
    assert len(transport.requests) == 1
    assert await journal.inspect_retries(plan.digest) == history
    assert (await journal.inspect_observations(plan.digest))[0]["generation"] == 1


@pytest.mark.asyncio
async def test_retry_permission_cannot_reset_unknown_and_stale_generation_cannot_reauthorize(tmp_path):
    current = await index(await trace(tmp_path, "v1", {"a.md": "body"}))
    transport, journal = Transport(), SQLiteKnowledgeSyncJournal(tmp_path / "sync.sqlite")
    tiny = writer(transport, max_request_bytes=1)
    await journal.initialize(confirm_create=True)
    plan = KnowledgeSyncPlan(tiny.endpoint, None, current)
    for generation in range(2):
        with pytest.raises(VectorIndexWriteError):
            await execute(plan, tiny, journal)
        if generation == 1:
            with pytest.raises(KnowledgeSyncError, match="conflict"):
                await journal.retry_not_sent(plan.digest, 0, generation=0, retry_id="stale", confirm_retry_digest=knowledge_sync_retry_digest(plan.digest, 0, 0), confirm_write=True)
        await journal.retry_not_sent(plan.digest, 0, generation=generation, retry_id=f"retry-{generation}",
                                     confirm_retry_digest=knowledge_sync_retry_digest(plan.digest, 0, generation), confirm_write=True)
    transport.failure = RuntimeError("unknown")
    with pytest.raises(VectorIndexWriteError):
        await execute(plan, writer(transport), journal)
    with pytest.raises(KnowledgeSyncError, match="conflict-or-unresolved"):
        await journal.retry_not_sent(plan.digest, 0, generation=2, retry_id="unsafe", confirm_retry_digest=knowledge_sync_retry_digest(plan.digest, 0, 2), confirm_write=True)
    assert (await journal.inspect(plan.digest)).outcomes == ("unknown",)
    assert len(await journal.inspect_retries(plan.digest)) == 2
