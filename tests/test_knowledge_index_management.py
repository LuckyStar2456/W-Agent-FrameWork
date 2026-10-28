"""Draft local index management/CLI tests; not run in this development round."""

from dataclasses import replace
import json

import pytest
from typer.testing import CliRunner

from w_agent import (
    DenseVectorPoint, KnowledgeDocument, KnowledgeSnapshot, KnowledgeVectorIndex,
    QdrantVectorSearch, QdrantVectorWriter, SQLiteKnowledgeIndexJournal,
    KnowledgeIndexReconciliation, knowledge_index_manifest,
)
from w_agent.knowledge_index_journal import KnowledgeIndexJournalError
from w_agent.knowledge_index_management import (
    KnowledgeIndexReviewRequest, knowledge_index_review_view, review_local_knowledge_index,
)


async def pending(tmp_path):
    index = KnowledgeVectorIndex(KnowledgeSnapshot("n", "v", (KnowledgeDocument("d", "PRIVATE_BODY"),)), "PRIVATE_MODEL", 2)
    writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "PRIVATE_COLLECTION"))
    plan = writer.plan((DenseVectorPoint(index.point_ids[0], (1, 2)),))
    manifest = knowledge_index_manifest(index, writer)
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.db")
    await journal.initialize(confirm_create=True)
    await journal.begin(manifest, "attempt-1", plan, confirm_write=True)
    decision = KnowledgeIndexReconciliation("review-1", manifest.digest, "attempt-1", plan.digest,
                                           "pending", "completed", "PRIVATE_EVIDENCE", "PRIVATE_ACTOR")
    return journal, manifest, decision


@pytest.mark.asyncio
async def test_local_review_preserves_original_and_redacts_details(tmp_path):
    journal, manifest, decision = await pending(tmp_path)
    request = KnowledgeIndexReviewRequest(journal.database_path, manifest.digest, confirm_read=True)
    before = await review_local_knowledge_index(request)
    assert before["remote_state_verified"] is False
    assert before["unresolved_attempt_ids"] == ["attempt-1"]
    assert not before["all_points_locally_confirmed"]
    assert "PRIVATE" not in json.dumps(before)
    assert knowledge_index_review_view(await journal.inspect(manifest.digest))["remote_state_verified"] is False
    after = await review_local_knowledge_index(replace(request, decision=decision, confirm_write=True, confirm_inactive=True))
    assert after["all_points_locally_confirmed"] is True
    assert after["remote_state_verified"] is False
    assert after["attempts"][0]["original_outcome"] == "pending"
    assert after["attempts"][0]["effective_outcome"] == "completed"
    assert "PRIVATE" not in json.dumps(after)
    detailed = await review_local_knowledge_index(replace(request, include_details=True))
    assert detailed["manifest"]["embedding_key"] == "PRIVATE_MODEL"
    assert detailed["attempts"][0]["reconciliation"]["evidence_ref"] == "PRIVATE_EVIDENCE"
    assert "PRIVATE_BODY" not in json.dumps(detailed)
    # A reread is not a new attempt, replay or modification.
    assert len((await journal.inspect(manifest.digest)).attempts) == 1


@pytest.mark.parametrize("overrides", [
    {"confirm_read": False}, {"confirm_read": 1}, {"include_details": 1},
    {"confirm_write": True}, {"confirm_inactive": True}, {"manifest_digest": "bad"},
])
def test_preflight_without_io(tmp_path, overrides):
    options = dict(database=tmp_path / "absent.db", manifest_digest="a" * 64, confirm_read=True)
    options.update(overrides)
    with pytest.raises(ValueError):
        KnowledgeIndexReviewRequest(**options)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_reconciliation_consent_stale_identity_and_immutable_decision(tmp_path):
    journal, manifest, decision = await pending(tmp_path)
    request = KnowledgeIndexReviewRequest(journal.database_path, manifest.digest, confirm_read=True)
    for options in ({}, {"confirm_write": True}, {"confirm_inactive": True}):
        with pytest.raises(ValueError):
            replace(request, decision=decision, **options)
    with pytest.raises(ValueError):
        replace(request, manifest_digest="b" * 64, decision=decision, confirm_write=True, confirm_inactive=True)
    approved = replace(request, decision=decision, confirm_write=True, confirm_inactive=True)
    with pytest.raises(KnowledgeIndexJournalError):
        await review_local_knowledge_index(replace(approved, decision=replace(decision, expected_outcome="unknown")))
    saved = await review_local_knowledge_index(approved)
    assert await review_local_knowledge_index(approved) == saved
    with pytest.raises(KnowledgeIndexJournalError):
        await review_local_knowledge_index(replace(approved, decision=replace(decision, outcome="not-applied")))


@pytest.mark.asyncio
async def test_missing_db_is_not_created(tmp_path):
    request = KnowledgeIndexReviewRequest(tmp_path / "missing.db", "a" * 64, confirm_read=True)
    with pytest.raises(KnowledgeIndexJournalError):
        await review_local_knowledge_index(request)
    assert not request.database.exists()


def test_cli_missing_consent_never_enters_service(tmp_path, monkeypatch):
    import w_agent.knowledge_index_cli as adapter
    from w_agent.cli import app

    async def forbidden(request):
        pytest.fail("service called without consent")

    monkeypatch.setattr(adapter, "review_local_knowledge_index", forbidden)
    result = CliRunner().invoke(app, ["knowledge-index-inspect", "--database", str(tmp_path / "missing.db"),
                                    "--manifest-digest", "a" * 64])
    assert result.exit_code == 2


def test_cli_captures_independent_decision_fields(tmp_path, monkeypatch):
    import w_agent.knowledge_index_cli as adapter
    from w_agent.cli import app

    captured = []

    async def review(request):
        captured.append(request)
        return {"remote_state_verified": False}

    monkeypatch.setattr(adapter, "review_local_knowledge_index", review)
    result = CliRunner().invoke(app, [
        "knowledge-index-reconcile", "--database", str(tmp_path / "journal.db"),
        "--manifest-digest", "a" * 64, "--attempt-id", "a", "--plan-digest", "b" * 64,
        "--expected-outcome", "unknown", "--outcome", "not-applied", "--reconciliation-id", "r",
        "--evidence-ref", "PRIVATE_EVIDENCE", "--actor-ref", "actor",
        "--confirm-read", "--confirm-write", "--confirm-inactive",
    ])
    assert result.exit_code == 0, result.output
    assert captured[0].decision.evidence_ref == "PRIVATE_EVIDENCE"
    assert captured[0].include_details is False
    assert json.loads(result.output)["remote_state_verified"] is False
    assert "PRIVATE_EVIDENCE" not in result.output
