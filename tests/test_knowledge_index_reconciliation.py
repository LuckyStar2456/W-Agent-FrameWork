"""Draft independent-evidence index reconciliation regressions; unexecuted."""

import asyncio
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest

from w_agent import (
    DenseVectorPoint, KnowledgeDocument, KnowledgeIndexAttempt, KnowledgeIndexJournalError,
    KnowledgeIndexJournalSnapshot,
    KnowledgeIndexReconciliation, KnowledgeSnapshot, KnowledgeVectorIndex,
    QdrantVectorSearch, QdrantVectorWriter, QdrantWriteResult,
    SQLiteKnowledgeIndexJournal, journaled_knowledge_upsert, knowledge_index_manifest,
)


def configuration():
    index = KnowledgeVectorIndex(KnowledgeSnapshot("n", "v", (KnowledgeDocument("id", "body"),)), "model", 2)
    writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "knowledge"))
    plan = writer.plan((DenseVectorPoint(index.point_ids[0], (1, 2)),))
    manifest = knowledge_index_manifest(index, writer)
    return manifest, plan


def decision(manifest, plan, *, expected="unknown", outcome="completed", attempt_id="a", identity="review-1"):
    return KnowledgeIndexReconciliation(identity, manifest.digest, attempt_id, plan.digest, expected, outcome,
                                        "PRIVATE_EVIDENCE_REF", "PRIVATE_ACTOR_REF")


async def pending_store(tmp_path, *, outcome="unknown"):
    manifest, plan = configuration()
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "index.sqlite")
    await journal.initialize(confirm_create=True)
    await journal.begin(manifest, "a", plan, confirm_write=True)
    if outcome != "pending":
        receipt = QdrantWriteResult(plan.digest, 1, outcome, 17) if outcome == "acknowledged" else None
        await journal.record(manifest.digest, "a", outcome=outcome, receipt=receipt, confirm_write=True)
    return journal, manifest, plan


@pytest.mark.asyncio
@pytest.mark.parametrize("original", ["pending", "acknowledged", "unknown"])
@pytest.mark.parametrize("resolved", ["completed", "not-applied"])
async def test_reconciliation_preserves_observation_and_reopens(tmp_path, original, resolved):
    journal, manifest, plan = await pending_store(tmp_path, outcome=original)
    before = await journal.inspect(manifest.digest)
    item = decision(manifest, plan, expected=original, outcome=resolved)
    after = await journal.reconcile(item, confirm_inactive=True, confirm_write=True)
    assert after.attempts == before.attempts
    assert after.effective_outcome("a") == resolved
    assert after.reconciliations == (item,) and not after.unresolved_attempt_ids
    assert after.all_points_confirmed == (resolved == "completed")
    assert after.confirmed_point_ids == (manifest.point_ids if resolved == "completed" else ())
    reopened = SQLiteKnowledgeIndexJournal(journal.database_path)
    assert await reopened.inspect(manifest.digest) == after
    assert await reopened.reconcile(item, confirm_inactive=True, confirm_write=True) == after
    assert "PRIVATE" not in repr(item)
    with pytest.raises(ValueError):
        after.effective_outcome("missing")


@pytest.mark.asyncio
@pytest.mark.parametrize("inactive,write", [(False, True), (True, False), (1, True), (True, 1)])
async def test_both_literal_confirmations_are_required(tmp_path, inactive, write):
    journal, manifest, plan = await pending_store(tmp_path)
    before = await journal.inspect(manifest.digest)
    with pytest.raises(KnowledgeIndexJournalError, match="confirmation-required"):
        await journal.reconcile(decision(manifest, plan), confirm_inactive=inactive, confirm_write=write)
    assert await journal.inspect(manifest.digest) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"plan_digest": "0" * 64}, {"expected_outcome": "pending"},
    {"attempt_id": "missing"}, {"manifest_digest": "0" * 64},
])
async def test_stale_or_mismatched_decision_does_not_mutate_journal(tmp_path, changes):
    journal, manifest, plan = await pending_store(tmp_path)
    before = await journal.inspect(manifest.digest)
    with pytest.raises(KnowledgeIndexJournalError):
        await journal.reconcile(replace(decision(manifest, plan), **changes), confirm_inactive=True, confirm_write=True)
    assert await journal.inspect(manifest.digest) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"outcome": "not-applied"}, {"evidence_ref": "new-evidence"},
    {"actor_ref": "new-actor"}, {"reconciliation_id": "new-review"},
])
async def test_saved_decision_cannot_be_overwritten(tmp_path, changes):
    journal, manifest, plan = await pending_store(tmp_path)
    item = decision(manifest, plan)
    before = await journal.reconcile(item, confirm_inactive=True, confirm_write=True)
    with pytest.raises(KnowledgeIndexJournalError, match="reconciliation-conflict"):
        await journal.reconcile(replace(item, **changes), confirm_inactive=True, confirm_write=True)
    assert await journal.inspect(manifest.digest) == before


@pytest.mark.asyncio
async def test_decision_id_cannot_be_reused_for_another_attempt_in_manifest(tmp_path):
    journal, manifest, plan = await pending_store(tmp_path)
    await journal.reconcile(decision(manifest, plan), confirm_inactive=True, confirm_write=True)
    await journal.begin(manifest, "b", plan, confirm_write=True)
    with pytest.raises(KnowledgeIndexJournalError, match="reconciliation-conflict"):
        await journal.reconcile(decision(manifest, plan, expected="pending", attempt_id="b"),
                                confirm_inactive=True, confirm_write=True)
    assert (await journal.inspect(manifest.digest)).unresolved_attempt_ids == ("b",)


@pytest.mark.asyncio
async def test_reconciled_pending_observation_is_frozen_against_late_record(tmp_path):
    journal, manifest, plan = await pending_store(tmp_path, outcome="pending")
    before = await journal.reconcile(decision(manifest, plan, expected="pending"), confirm_inactive=True, confirm_write=True)
    with pytest.raises(KnowledgeIndexJournalError, match="observation-reconciled"):
        await journal.record(manifest.digest, "a", outcome="completed",
            receipt=QdrantWriteResult(plan.digest, 1, "completed"), confirm_write=True)
    assert await journal.inspect(manifest.digest) == before


@pytest.mark.asyncio
async def test_not_applied_clears_uncertainty_but_does_not_invent_coverage(tmp_path):
    journal, manifest, plan = await pending_store(tmp_path)
    after = await journal.reconcile(decision(manifest, plan, outcome="not-applied"), confirm_inactive=True, confirm_write=True)
    assert not after.all_points_confirmed and not after.unresolved_attempt_ids
    await journal.begin(manifest, "b", plan, confirm_write=True)
    completed = await journal.record(manifest.digest, "b", outcome="completed",
        receipt=QdrantWriteResult(plan.digest, 1, "completed"), confirm_write=True)
    assert completed.all_points_confirmed and completed.reconciliations == after.reconciliations
    await journal.begin(manifest, "c", plan, confirm_write=True)
    assert not (await journal.inspect(manifest.digest)).all_points_confirmed
    restored = await journal.reconcile(decision(manifest, plan, expected="pending", outcome="not-applied",
                                               attempt_id="c", identity="review-2"),
                                       confirm_inactive=True, confirm_write=True)
    assert restored.all_points_confirmed  # Earlier completed evidence still exists.


@pytest.mark.asyncio
async def test_two_connections_commit_only_one_conflicting_decision(tmp_path):
    journal, manifest, plan = await pending_store(tmp_path)
    other = SQLiteKnowledgeIndexJournal(journal.database_path)
    results = await asyncio.gather(
        journal.reconcile(decision(manifest, plan), confirm_inactive=True, confirm_write=True),
        other.reconcile(decision(manifest, plan, outcome="not-applied", identity="other"),
                        confirm_inactive=True, confirm_write=True), return_exceptions=True,
    )
    assert sum(isinstance(item, KnowledgeIndexJournalError) for item in results) == 1
    assert len((await journal.inspect(manifest.digest)).reconciliations) == 1


@pytest.mark.asyncio
async def test_v1_reads_do_not_rewrite_and_explicit_reconciliation_writes_v2(tmp_path):
    journal, manifest, plan = await pending_store(tmp_path)

    def stored():
        with closing(sqlite3.connect(journal.database_path)) as db:
            return db.execute("SELECT payload FROM knowledge_index_journals").fetchone()[0]

    before = stored()
    assert json.loads(before)["format"] == "wagent-knowledge-index-journal-v1"
    assert "reconciliations" not in json.loads(before)
    await journal.inspect(manifest.digest)
    assert stored() == before
    await journal.reconcile(decision(manifest, plan), confirm_inactive=True, confirm_write=True)
    after = json.loads(stored())
    assert after["format"] == "wagent-knowledge-index-journal-v2"
    assert after["attempts"] == json.loads(before)["attempts"]
    assert len(after["reconciliations"]) == 1
    with closing(sqlite3.connect(journal.database_path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_rehashed_but_inconsistent_decision_is_rejected_on_load(tmp_path):
    journal, manifest, plan = await pending_store(tmp_path)
    await journal.reconcile(decision(manifest, plan), confirm_inactive=True, confirm_write=True)
    with closing(sqlite3.connect(journal.database_path)) as db, db:
        payload = json.loads(db.execute("SELECT payload FROM knowledge_index_journals").fetchone()[0])
        payload["reconciliations"][0]["expected_outcome"] = "acknowledged"
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        db.execute("UPDATE knowledge_index_journals SET payload=?, digest=?",
                   (encoded, hashlib.sha256(encoded.encode()).hexdigest()))
    with pytest.raises(KnowledgeIndexJournalError):
        await journal.inspect(manifest.digest)


@pytest.mark.parametrize("changes", [
    {"outcome": "unknown"}, {"expected_outcome": "completed"}, {"expected_outcome": "not-sent"},
    {"evidence_ref": ""}, {"actor_ref": "\n"}, {"plan_digest": "wrong"},
])
def test_decision_requires_complete_bounded_evidence_references(changes):
    manifest, plan = configuration()
    with pytest.raises(ValueError):
        replace(decision(manifest, plan), **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "not-applied"])
async def test_custom_journal_cannot_authorize_send_with_reconciled_pending(outcome):
    manifest, plan = configuration()

    class NeverSend:
        calls = 0

        async def send(self, request, **kwargs):
            self.calls += 1
            raise AssertionError("reconciled pending must not authorize a write")

    transport = NeverSend()
    writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "knowledge", transport=transport))
    observation = KnowledgeIndexAttempt("a", plan.digest, manifest.point_ids)
    resolved = decision(manifest, plan, expected="pending", outcome=outcome)

    class ReconciledJournal:
        async def begin(self, *args, **kwargs):
            return KnowledgeIndexJournalSnapshot(manifest, (observation,), (resolved,))

        async def record(self, *args, **kwargs):
            raise AssertionError("must reject before recording a remote receipt")

    with pytest.raises(KnowledgeIndexJournalError, match="pending-record-invalid"):
        await journaled_knowledge_upsert(writer, plan, manifest, ReconciledJournal(), attempt_id="a",
                                        confirm_digest=plan.digest, confirm_record=True)
    assert transport.calls == 0
