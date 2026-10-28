"""Draft local index-journal tests; no real services or executed validation."""

import asyncio
import json
import sqlite3
from contextlib import closing

import pytest

from w_agent import (
    DenseVectorPoint, HttpToolResponse, KnowledgeDocument, KnowledgeIndexJournalError,
    KnowledgeSnapshot, KnowledgeVectorIndex, QdrantVectorSearch, QdrantVectorWriter,
    QdrantWriteResult, SQLiteKnowledgeIndexJournal, VectorIndexWriteError,
    journaled_knowledge_upsert, knowledge_index_manifest,
)


class Transport:
    def __init__(self, status="completed", *, fail=False):
        self.status = status
        self.fail = fail
        self.requests = []

    async def send(self, request, **kwargs):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("PRIVATE_REMOTE_ERROR")
        return HttpToolResponse(200, {}, json.dumps({
            "status": "ok", "result": {"status": self.status, "operation_id": 7},
        }).encode())


def setup(transport=None):
    index = KnowledgeVectorIndex(KnowledgeSnapshot("n", "v", (
        KnowledgeDocument("a", "PRIVATE_BODY_A"), KnowledgeDocument("b", "PRIVATE_BODY_B"),
    )), "model-v1", 2)
    writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "knowledge", transport=transport or Transport()))
    manifest = knowledge_index_manifest(index, writer)
    plans = tuple(writer.plan((DenseVectorPoint(identity, (0.1, 0.2)),)) for identity in index.point_ids)
    return index, writer, manifest, plans


@pytest.mark.asyncio
async def test_creation_and_writes_require_separate_consent(tmp_path):
    transport = Transport()
    _, writer, manifest, plans = setup(transport)
    path = tmp_path / "journal.sqlite"
    journal = SQLiteKnowledgeIndexJournal(path)
    assert not path.exists()
    for consent in (False, 1):
        with pytest.raises(KnowledgeIndexJournalError):
            await journal.initialize(confirm_create=consent)
        with pytest.raises(KnowledgeIndexJournalError):
            await journaled_knowledge_upsert(writer, plans[0], manifest, journal, attempt_id="a",
                confirm_digest=plans[0].digest, confirm_record=consent)
    assert not path.exists() and not transport.requests
    await journal.initialize(confirm_create=True)
    with pytest.raises(KnowledgeIndexJournalError):
        await journal.begin(manifest, "a", plans[0])
    with pytest.raises(KnowledgeIndexJournalError):
        await journaled_knowledge_upsert(writer, plans[0], manifest, journal, attempt_id="a",
            confirm_digest="0" * 64, confirm_record=True)
    assert not transport.requests


@pytest.mark.asyncio
async def test_durable_partial_then_full_coverage_and_duplicate_attempt_never_resends(tmp_path):
    transport = Transport()
    index, writer, manifest, plans = setup(transport)
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.sqlite")
    await journal.initialize(confirm_create=True)
    first = await journaled_knowledge_upsert(writer, plans[0], manifest, journal, attempt_id="first",
        confirm_digest=plans[0].digest, confirm_record=True)
    reopened = SQLiteKnowledgeIndexJournal(journal.database_path)
    progress = await reopened.inspect(manifest.digest)
    assert progress.confirmed_point_ids == (index.point_ids[0],) and not progress.all_points_confirmed
    assert not progress.unresolved_attempt_ids
    with pytest.raises(KnowledgeIndexJournalError, match="already-exists"):
        await journaled_knowledge_upsert(writer, plans[0], manifest, reopened, attempt_id="first",
            confirm_digest=plans[0].digest, confirm_record=True)
    assert len(transport.requests) == 1
    assert await reopened.record(manifest.digest, "first", outcome="completed", receipt=first, confirm_write=True) == progress
    await journaled_knowledge_upsert(writer, plans[1], manifest, reopened, attempt_id="second",
        confirm_digest=plans[1].digest, confirm_record=True)
    assert (await reopened.inspect(manifest.digest)).all_points_confirmed
    assert "PRIVATE_BODY" not in (await reopened.inspect(manifest.digest)).to_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["pending", "acknowledged", "unknown"])
async def test_unresolved_overlap_blocks_previously_completed_point(tmp_path, outcome):
    index, _, manifest, plans = setup()
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.sqlite")
    await journal.initialize(confirm_create=True)
    for number, plan in enumerate(plans):
        await journal.begin(manifest, str(number), plan, confirm_write=True)
        await journal.record(manifest.digest, str(number), outcome="completed",
            receipt=QdrantWriteResult(plan.digest, 1, "completed", 1), confirm_write=True)
    assert (await journal.inspect(manifest.digest)).all_points_confirmed
    await journal.begin(manifest, "retry", plans[0], confirm_write=True)
    if outcome != "pending":
        receipt = QdrantWriteResult(plans[0].digest, 1, "acknowledged", 2) if outcome == "acknowledged" else None
        await journal.record(manifest.digest, "retry", outcome=outcome, receipt=receipt, confirm_write=True)
    state = await journal.inspect(manifest.digest)
    assert state.confirmed_point_ids == (index.point_ids[1],)
    assert state.unresolved_attempt_ids == ("retry",) and not state.all_points_confirmed


@pytest.mark.asyncio
async def test_not_sent_does_not_invalidate_prior_completed_observation(tmp_path):
    index, _, manifest, plans = setup()
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.sqlite")
    await journal.initialize(confirm_create=True)
    await journal.begin(manifest, "first", plans[0], confirm_write=True)
    await journal.record(manifest.digest, "first", outcome="completed",
        receipt=QdrantWriteResult(plans[0].digest, 1, "completed"), confirm_write=True)
    await journal.begin(manifest, "refused", plans[0], confirm_write=True)
    state = await journal.record(manifest.digest, "refused", outcome="not-sent", confirm_write=True)
    assert state.confirmed_point_ids == (index.point_ids[0],) and not state.unresolved_attempt_ids


@pytest.mark.asyncio
async def test_receipt_mismatch_and_final_observation_overwrite_are_rejected(tmp_path):
    _, _, manifest, plans = setup()
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.sqlite")
    await journal.initialize(confirm_create=True)
    await journal.begin(manifest, "a", plans[0], confirm_write=True)
    for receipt in (QdrantWriteResult(plans[1].digest, 1, "completed"), QdrantWriteResult(plans[0].digest, 2, "completed")):
        with pytest.raises(KnowledgeIndexJournalError, match="mismatch"):
            await journal.record(manifest.digest, "a", outcome="completed", receipt=receipt, confirm_write=True)
    await journal.record(manifest.digest, "a", outcome="unknown", confirm_write=True)
    with pytest.raises(KnowledgeIndexJournalError, match="observation-conflict"):
        await journal.record(manifest.digest, "a", outcome="completed",
            receipt=QdrantWriteResult(plans[0].digest, 1, "completed"), confirm_write=True)


@pytest.mark.asyncio
async def test_foreign_plan_target_dimension_and_ids_rejected_before_persistence(tmp_path):
    index, writer, manifest, plans = setup()
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "absent.sqlite")
    wrong_writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "other", transport=Transport()))
    bad_plans = (
        wrong_writer.plan(plans[0].points),
        writer.plan((DenseVectorPoint(index.point_ids[0], (1,)),)),
        writer.plan((DenseVectorPoint("00000000-0000-0000-0000-000000000001", (1, 2)),)),
    )
    for plan in bad_plans:
        with pytest.raises(KnowledgeIndexJournalError, match="plan-mismatch"):
            await journal.begin(manifest, "a", plan, confirm_write=True)
    assert not journal.database_path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_acknowledged_and_failed_remote_calls_never_claim_completion(tmp_path, fail):
    transport = Transport("acknowledged", fail=fail)
    _, writer, manifest, plans = setup(transport)
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.sqlite")
    await journal.initialize(confirm_create=True)
    if fail:
        with pytest.raises(VectorIndexWriteError):
            await journaled_knowledge_upsert(writer, plans[0], manifest, journal, attempt_id="a",
                confirm_digest=plans[0].digest, confirm_record=True)
    else:
        await journaled_knowledge_upsert(writer, plans[0], manifest, journal, attempt_id="a",
            confirm_digest=plans[0].digest, confirm_record=True)
    state = await journal.inspect(manifest.digest)
    assert state.attempts[0].outcome == ("unknown" if fail else "acknowledged")
    assert not state.confirmed_point_ids and len(transport.requests) == 1


@pytest.mark.asyncio
async def test_receipt_storage_failure_keeps_pending_and_does_not_replay_remote(tmp_path):
    transport = Transport()
    _, writer, manifest, plans = setup(transport)
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.sqlite")
    await journal.initialize(confirm_create=True)

    class FailingRecord:
        async def begin(self, *args, **kwargs):
            return await journal.begin(*args, **kwargs)

        async def record(self, *args, **kwargs):
            raise RuntimeError("PRIVATE_STORAGE_ERROR")

    with pytest.raises(KnowledgeIndexJournalError, match="receipt-persistence-failed"):
        await journaled_knowledge_upsert(writer, plans[0], manifest, FailingRecord(), attempt_id="a",
            confirm_digest=plans[0].digest, confirm_record=True)
    assert len(transport.requests) == 1
    assert (await journal.inspect(manifest.digest)).attempts[0].outcome == "pending"


@pytest.mark.asyncio
async def test_two_process_like_connections_cannot_begin_same_attempt(tmp_path):
    _, _, manifest, plans = setup()
    path = tmp_path / "journal.sqlite"
    first, second = SQLiteKnowledgeIndexJournal(path), SQLiteKnowledgeIndexJournal(path)
    await first.initialize(confirm_create=True)
    results = await asyncio.gather(first.begin(manifest, "a", plans[0], confirm_write=True),
                                   second.begin(manifest, "a", plans[0], confirm_write=True), return_exceptions=True)
    assert sum(isinstance(item, KnowledgeIndexJournalError) for item in results) == 1
    assert len((await first.inspect(manifest.digest)).attempts) == 1


@pytest.mark.asyncio
async def test_remote_cancellation_records_unknown_and_drains_transport(tmp_path):
    started, closed = asyncio.Event(), asyncio.Event()

    class SlowTransport:
        async def send(self, request, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

    _, writer, manifest, plans = setup(SlowTransport())
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.sqlite")
    await journal.initialize(confirm_create=True)
    task = asyncio.create_task(journaled_knowledge_upsert(writer, plans[0], manifest, journal,
        attempt_id="a", confirm_digest=plans[0].digest, confirm_record=True))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert (await journal.inspect(manifest.digest)).attempts[0].outcome == "unknown"


@pytest.mark.asyncio
async def test_corrupt_local_payload_is_not_adopted(tmp_path):
    _, _, manifest, plans = setup()
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.sqlite")
    await journal.initialize(confirm_create=True)
    await journal.begin(manifest, "a", plans[0], confirm_write=True)
    with closing(sqlite3.connect(journal.database_path)) as db, db:
        db.execute("UPDATE knowledge_index_journals SET payload = 'PRIVATE_CORRUPTION'")
    with pytest.raises(KnowledgeIndexJournalError) as error:
        await journal.inspect(manifest.digest)
    assert "PRIVATE" not in str(error.value)
