"""Offline real-SQLite management chain with explicit host lifecycle."""

import asyncio
import json
import sys
import types
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from w_agent.knowledge_plan_actions import KnowledgeIndexHostBinding, KnowledgeIndexHostOptions
from w_agent.knowledge_sync import KnowledgeSyncError, knowledge_sync_retry_digest
from w_agent.knowledge_sync_management import (
    KnowledgeSyncExecuteRequest, KnowledgeSyncImportRequest, KnowledgeSyncInspectRequest,
    KnowledgeSyncPrepareRequest, KnowledgeSyncReconcileRequest, KnowledgeSyncRetryRequest,
    execute_local_knowledge_sync, import_local_knowledge_sync, inspect_local_knowledge_sync,
    prepare_local_knowledge_sync, reconcile_local_knowledge_sync, retry_local_knowledge_sync,
)
from w_agent.knowledge_sync_store import SQLiteKnowledgeSyncJournal
from w_agent.tools.http_adapter import HttpToolResponse
from w_agent.vector_indexing import QdrantVectorWriter
from w_agent.vector_retrieval import QdrantVectorSearch


@pytest.fixture
def host(monkeypatch):
    state = types.SimpleNamespace(events=[], embeds=[], sends=[], status="completed", failure=None,
                                  embed_failure=None, cleanup_failure=False)

    class Embedder:
        async def embed(self, text):
            state.embeds.append(text)
            if state.embed_failure:
                raise state.embed_failure
            return (1.0, 2.0)

    class Transport:
        async def send(self, request):
            state.sends.append(request)
            if state.failure:
                raise state.failure
            return HttpToolResponse(200, {}, json.dumps({"status": "ok", "result": {"status": state.status, "operation_id": 1}}).encode())

    state.writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "private-collection", transport=Transport()))

    @asynccontextmanager
    async def catalog():
        state.events.append("enter")
        try:
            yield {"prepare": KnowledgeIndexHostBinding(state.writer, Embedder(), "private-model", 2),
                   "execute": KnowledgeIndexHostBinding(state.writer)}
        finally:
            state.events.append("exit")
            if state.cleanup_failure:
                raise RuntimeError("private cleanup failure")

    monkeypatch.setitem(sys.modules, "sync_test_host", types.SimpleNamespace(catalog=catalog))
    return state


def host_options(binding="prepare"):
    return KnowledgeIndexHostOptions("sync_test_host:catalog", binding, True)


async def imported(tmp_path, version="v1", text="private original body", paths=("a.md",)):
    (tmp_path / "a.md").write_text(text, encoding="utf-8")
    request = KnowledgeSyncImportRequest(tmp_path / "trace.db", tmp_path, paths, "manual", version, confirm_read=True)
    preview = await import_local_knowledge_sync(request)
    result = await import_local_knowledge_sync(replace(request, expected_preview_digest=preview["preview_digest"],
                                                     confirm_record=True, confirm_create=True))
    return result


def prepare_request(tmp_path, trace, **overrides):
    options = dict(host=host_options(), trace_database=tmp_path / "trace.db", namespace="manual", version=trace["version"],
                   journal_database=tmp_path / "sync.db", expected_trace_digest=trace["trace_digest"],
                   confirm_read=True, confirm_embedding=True, confirm_record=True, confirm_create=True)
    options.update(overrides)
    return KnowledgeSyncPrepareRequest(**options)


def execute_request(tmp_path, plan, **overrides):
    options = dict(host=host_options("execute"), journal_database=tmp_path / "sync.db", plan_digest=plan["plan_digest"],
                   approved_plan_digest=plan["plan_digest"], approved_upsert_digest=plan["upsert_digest"],
                   approved_delete_digest=plan["delete_digest"], confirm_read=True, confirm_record=True)
    options.update(overrides)
    return KnowledgeSyncExecuteRequest(**options)


async def inspect(tmp_path, plan):
    return await inspect_local_knowledge_sync(KnowledgeSyncInspectRequest(tmp_path / "sync.db", plan["plan_digest"], True))


@pytest.mark.asyncio
async def test_complete_import_prepare_review_execute_incremental_delete(tmp_path, host):
    first = await prepare_local_knowledge_sync(prepare_request(tmp_path, await imported(tmp_path)))
    assert host.events == ["enter", "exit"] and len(host.embeds) == 1 and not host.sends
    review = await inspect(tmp_path, first)
    assert review["outcomes"] == ["ready"]
    assert host.events == ["enter", "exit"]
    output = json.dumps(review)
    assert all(secret not in output for secret in ("private original", "private-model", "localhost", "a.md", str(tmp_path)))
    done = await execute_local_knowledge_sync(execute_request(tmp_path, first))
    assert done["finished"] and len(host.sends) == 1 and len(host.embeds) == 1
    # Same bytes under new version reuse exact prior vectors, requiring no embedding.
    trace = await imported(tmp_path, "v2")
    second = await prepare_local_knowledge_sync(prepare_request(tmp_path, trace, previous_plan_digest=first["plan_digest"],
        approved_reuse_digest=first["current_index_digest"], confirm_embedding=False))
    assert second["finished"] and second["reused_points"] == 1 and len(host.embeds) == 1
    # An explicit empty selection removes only the preceding manifest's points.
    trace = await imported(tmp_path, "v3", paths=())
    third = await prepare_local_knowledge_sync(prepare_request(tmp_path, trace, previous_plan_digest=second["plan_digest"],
        approved_reuse_digest=second["current_index_digest"], confirm_embedding=False))
    assert third["delete_points"] == 1 and third["upsert_points"] == 0
    with pytest.raises(KnowledgeSyncError, match="approval"):
        await execute_local_knowledge_sync(execute_request(tmp_path, third, approved_delete_digest=None))
    assert len(host.sends) == 1
    assert (await execute_local_knowledge_sync(execute_request(tmp_path, third, approved_upsert_digest=None)))["finished"]
    assert len(host.sends) == 2


@pytest.mark.asyncio
async def test_import_preview_lock_prevents_source_and_destination_changes(tmp_path):
    (tmp_path / "a.md").write_text("first", encoding="utf-8")
    request = KnowledgeSyncImportRequest(tmp_path / "trace.db", tmp_path, ("a.md",), "manual", "v1", confirm_read=True)
    preview = await import_local_knowledge_sync(request)
    assert not (tmp_path / "trace.db").exists()
    for changed in (replace(request, trace_database=tmp_path / "other.db"), replace(request, recursive=True)):
        with pytest.raises(KnowledgeSyncError, match="preview-changed"):
            await import_local_knowledge_sync(replace(changed, confirm_record=True, confirm_create=True,
                                                     expected_preview_digest=preview["preview_digest"]))
    (tmp_path / "a.md").write_text("changed", encoding="utf-8")
    with pytest.raises(KnowledgeSyncError, match="preview-changed"):
        await import_local_knowledge_sync(replace(request, confirm_record=True, confirm_create=True,
                                                 expected_preview_digest=preview["preview_digest"]))
    assert not (tmp_path / "trace.db").exists() and not (tmp_path / "other.db").exists()


@pytest.mark.parametrize("change", [{"confirm_read": False}, {"confirm_record": False}, {"confirm_embedding": 1}, {"expected_trace_digest": "bad"}])
def test_prepare_authorization_validation(tmp_path, change):
    with pytest.raises(ValueError):
        prepare_request(tmp_path, {"version": "v1", "trace_digest": "a" * 64}, **change)


@pytest.mark.asyncio
async def test_preflight_failures_do_not_import_host_or_embed(tmp_path, host):
    trace = await imported(tmp_path)
    with pytest.raises(KnowledgeSyncError, match="trace-approval"):
        await prepare_local_knowledge_sync(prepare_request(tmp_path, trace, expected_trace_digest="a" * 64))
    with pytest.raises(KnowledgeSyncError, match="unavailable"):
        await prepare_local_knowledge_sync(prepare_request(tmp_path, trace, confirm_create=False))
    assert not host.events and not host.embeds and not (tmp_path / "sync.db").exists()
    plan = await prepare_local_knowledge_sync(prepare_request(tmp_path, trace))
    with pytest.raises(KnowledgeSyncError, match="head-conflict"):
        await prepare_local_knowledge_sync(prepare_request(tmp_path, trace))
    assert len(host.embeds) == 1  # Duplicate prepare refused before billed model call.
    with pytest.raises(KnowledgeSyncError, match="action-approval"):
        await execute_local_knowledge_sync(execute_request(tmp_path, plan, approved_upsert_digest=None))
    assert not host.sends


@pytest.mark.asyncio
async def test_not_sent_inspect_retry_exact_returned_generation_and_execute(tmp_path, host):
    plan = await prepare_local_knowledge_sync(prepare_request(tmp_path, await imported(tmp_path)))
    journal = SQLiteKnowledgeSyncJournal(tmp_path / "sync.db")
    await journal.claim(plan["plan_digest"], 0, confirm_write=True)
    await journal.record(plan["plan_digest"], 0, "not-sent", confirm_write=True)
    candidate = (await inspect(tmp_path, plan))["retry_candidates"][0]
    assert candidate["generation"] == 0
    result = await retry_local_knowledge_sync(KnowledgeSyncRetryRequest(tmp_path / "sync.db", plan["plan_digest"],
        candidate["batch"], candidate["generation"], "retry-one", candidate["retry_digest"], True, True))
    assert result["outcomes"] == ["ready"] and not host.sends
    assert len(await journal.inspect_retries(plan["plan_digest"])) == 1
    assert (await execute_local_knowledge_sync(execute_request(tmp_path, plan)))["finished"]


@pytest.mark.asyncio
async def test_retry_exhausted_remains_inspectable(tmp_path, host):
    plan = await prepare_local_knowledge_sync(prepare_request(tmp_path, await imported(tmp_path)))
    journal = SQLiteKnowledgeSyncJournal(tmp_path / "sync.db")
    for generation in range(64):
        await journal.claim(plan["plan_digest"], 0, confirm_write=True)
        await journal.record(plan["plan_digest"], 0, "not-sent", confirm_write=True)
        await journal.retry_not_sent(plan["plan_digest"], 0, generation=generation, retry_id=f"retry-{generation}",
            confirm_retry_digest=knowledge_sync_retry_digest(plan["plan_digest"], 0, generation), confirm_write=True)
    await journal.claim(plan["plan_digest"], 0, confirm_write=True)
    await journal.record(plan["plan_digest"], 0, "not-sent", confirm_write=True)
    review = await inspect(tmp_path, plan)
    assert review["retry_exhausted"] and review["retry_count"] == 64 and review["retry_candidates"] == []


@pytest.mark.asyncio
async def test_unknown_never_replays_then_explicit_host_reconciliation(tmp_path, host):
    plan = await prepare_local_knowledge_sync(prepare_request(tmp_path, await imported(tmp_path)))
    host.failure = RuntimeError("private transport details")
    with pytest.raises(Exception):
        await execute_local_knowledge_sync(execute_request(tmp_path, plan))
    events = list(host.events)
    with pytest.raises(KnowledgeSyncError, match="unresolved"):
        await execute_local_knowledge_sync(execute_request(tmp_path, plan))
    review = await inspect(tmp_path, plan)
    assert review["outcomes"] == ["unknown"] and not review["retry_candidates"]
    assert len(host.sends) == 1 and host.events == events
    with pytest.raises(KnowledgeSyncError):
        await retry_local_knowledge_sync(KnowledgeSyncRetryRequest(tmp_path / "sync.db", plan["plan_digest"], 0, 0,
            "not-allowed", knowledge_sync_retry_digest(plan["plan_digest"], 0, 0), True, True))
    result = await reconcile_local_knowledge_sync(KnowledgeSyncReconcileRequest(tmp_path / "sync.db", plan["plan_digest"],
        0, "host-evidence", plan["plan_digest"], True, True, True, True))
    assert result["finished"] and len(host.sends) == 1 and host.events == events


@pytest.mark.asyncio
async def test_changed_file_only_new_chunks_embed(tmp_path, host):
    (tmp_path / "b.md").write_text("unchanged", encoding="utf-8")
    first = await prepare_local_knowledge_sync(prepare_request(tmp_path, await imported(tmp_path, paths=("a.md", "b.md"))))
    await execute_local_knowledge_sync(execute_request(tmp_path, first))
    next_trace = await imported(tmp_path, "v2", text="modified", paths=("a.md", "b.md"))
    second = await prepare_local_knowledge_sync(prepare_request(tmp_path, next_trace, previous_plan_digest=first["plan_digest"],
        approved_reuse_digest=first["current_index_digest"]))
    assert len(host.embeds) == 3 and second["upsert_points"] == second["delete_points"] == second["reused_points"] == 1


@pytest.mark.asyncio
async def test_read_missing_does_not_create(tmp_path):
    with pytest.raises(KnowledgeSyncError):
        await inspect_local_knowledge_sync(KnowledgeSyncInspectRequest(tmp_path / "missing.db", "a" * 64, True))
    assert not (tmp_path / "missing.db").exists()


@pytest.mark.asyncio
async def test_prepare_cancellation_closes_host_no_plan_replay_claim(tmp_path, host):
    host.embed_failure = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await prepare_local_knowledge_sync(prepare_request(tmp_path, await imported(tmp_path)))
    assert host.events == ["enter", "exit"] and not host.sends


@pytest.mark.asyncio
async def test_cleanup_failure_after_execution_preserves_receipt(tmp_path, host):
    plan = await prepare_local_knowledge_sync(prepare_request(tmp_path, await imported(tmp_path)))
    host.cleanup_failure = True
    with pytest.raises(Exception, match="cleanup-failed"):
        await execute_local_knowledge_sync(execute_request(tmp_path, plan))
    assert (await inspect(tmp_path, plan))["finished"] and len(host.sends) == 1


@pytest.mark.asyncio
async def test_wrong_host_target_no_send_and_no_claim(tmp_path, host):
    plan = await prepare_local_knowledge_sync(prepare_request(tmp_path, await imported(tmp_path)))
    host.writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "wrong-collection"))
    with pytest.raises(KnowledgeSyncError, match="confirmation-invalid"):
        await execute_local_knowledge_sync(execute_request(tmp_path, plan))
    assert not host.sends and (await inspect(tmp_path, plan))["outcomes"] == ["ready"]


@pytest.mark.asyncio
async def test_acknowledgement_barrier_no_second_factory_entry(tmp_path, host):
    plan = await prepare_local_knowledge_sync(prepare_request(tmp_path, await imported(tmp_path)))
    host.status = "acknowledged"
    result = await execute_local_knowledge_sync(execute_request(tmp_path, plan))
    assert not result["finished"] and result["outcomes"] == ["acknowledged"]
    events = list(host.events)
    with pytest.raises(KnowledgeSyncError, match="unresolved"):
        await execute_local_knowledge_sync(execute_request(tmp_path, plan))
    assert host.events == events and len(host.sends) == 1
