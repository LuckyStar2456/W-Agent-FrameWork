"""Draft catalog/coverage/missing-batch regressions; unexecuted."""

import json
import sqlite3
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from w_agent import (
    DenseVectorPoint, KnowledgeDocument, KnowledgeSnapshot, KnowledgeVectorIndex,
    QdrantVectorWriter, QdrantVectorSearch, knowledge_index_manifest, PreparedKnowledgeIndexPlan,
    SQLiteKnowledgeIndexPlanStore, SQLiteKnowledgeSnapshotStore, KnowledgeIndexPlanError,
    KnowledgeIndexPlanInfo, KnowledgePlanCoverage, plan_missing_knowledge_batches,
    review_knowledge_plan_catalog, review_missing_knowledge_batches,
)
from w_agent.knowledge_vectors import knowledge_document_embedding_text


def configuration(count=3):
    snapshot = KnowledgeSnapshot("n", "v", tuple(KnowledgeDocument(str(i), "PRIVATE_BODY") for i in range(count)))
    index = KnowledgeVectorIndex(snapshot, "PRIVATE_MODEL", 2)
    writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "PRIVATE_COLLECTION"))
    manifest = knowledge_index_manifest(index, writer)

    def artifact(positions, vector=(1, 2)):
        return PreparedKnowledgeIndexPlan(manifest, writer.plan(tuple(
            DenseVectorPoint(index.point_ids[i], vector) for i in positions)))

    return index, manifest, artifact


def test_coverage_keeps_overlap_separate_from_missing_and_execution():
    index, manifest, artifact = configuration()
    first, second = artifact((0, 1)), artifact((1, 2), (3, 4))
    coverage = KnowledgePlanCoverage(manifest, tuple(KnowledgeIndexPlanInfo.from_artifact(a) for a in (first, second)))
    assert coverage.prepared_point_ids == index.point_ids
    assert coverage.missing_point_ids == () and coverage.overlapping_point_ids == (index.point_ids[1],)
    summary = coverage.summary()
    assert summary["all_points_prepared"] and not summary["batches_disjoint"]
    assert not summary["execution_selected"] and not summary["remote_state_verified"]
    assert "PRIVATE" not in json.dumps(summary)
    with pytest.raises(ValueError):
        KnowledgePlanCoverage(manifest, (coverage.plans[0], coverage.plans[0]))


def test_batch_suggestions_are_stable_bounded_and_skip_only_staged_ids():
    index, manifest, artifact = configuration(6)
    coverage = KnowledgePlanCoverage(manifest, (KnowledgeIndexPlanInfo.from_artifact(artifact((0, 3))),))
    width = len(knowledge_document_embedding_text(index.snapshot.documents[0]).encode("utf-8"))
    batches = plan_missing_knowledge_batches(index, coverage, max_input_bytes=width * 2, max_vector_values=4)
    assert [batch.document_ids for batch in batches] == [("1", "2"), ("4", "5")]
    assert [batch.input_bytes for batch in batches] == [width * 2, width * 2]
    assert batches == plan_missing_knowledge_batches(index, coverage, max_documents=2)
    assert all("document_ids" not in batch.summary() for batch in batches)
    assert batches[0].summary(include_ids=True)["document_ids"] == ["1", "2"]
    assert len(plan_missing_knowledge_batches(index, coverage, max_vector_values=2)) == 4
    with pytest.raises(ValueError):
        plan_missing_knowledge_batches(index, coverage, max_input_bytes=width - 1)
    with pytest.raises(ValueError):
        plan_missing_knowledge_batches(index, coverage, max_documents=True)
    with pytest.raises(ValueError):
        plan_missing_knowledge_batches(replace(index, embedding_key="other"), coverage)
    empty = KnowledgePlanCoverage(manifest, ())
    assert sum(len(batch.document_ids) for batch in plan_missing_knowledge_batches(index, empty)) == 6


@pytest.mark.asyncio
async def test_verified_catalog_and_local_batch_review(tmp_path):
    index, manifest, artifact = configuration()
    plans = SQLiteKnowledgeIndexPlanStore(tmp_path / "plans.db")
    await plans.initialize(confirm_create=True)
    assert await plans.list_plans() == ()
    await plans.save(artifact((0,)), confirm_write=True)
    await plans.save(artifact((1,)), confirm_write=True)
    catalog = await review_knowledge_plan_catalog(plans.database_path, confirm_read=True)
    assert catalog["artifacts_integrity_verified"] is True
    assert [item["artifact_digest"] for item in catalog["plans"]] == sorted(item["artifact_digest"] for item in catalog["plans"])
    assert catalog["coverage"][0]["missing_point_count"] == 1
    assert "PRIVATE" not in json.dumps(catalog)
    source = SQLiteKnowledgeSnapshotStore(tmp_path / "source.db")
    await source.initialize(confirm_create=True)
    await source.save(index.snapshot, confirm_write=True)
    reviewed = await review_missing_knowledge_batches(plans.database_path, source.database_path, "n", "v", manifest.digest,
                                                     confirm_read=True, include_ids=True)
    assert reviewed["advisory_only"] and reviewed["batches"][0]["document_ids"] == ["2"]
    assert "PRIVATE_BODY" not in json.dumps(reviewed)
    with pytest.raises(KnowledgeIndexPlanError, match="manifest-not-found"):
        await review_knowledge_plan_catalog(plans.database_path, manifest_digest="a" * 64, confirm_read=True)


@pytest.mark.asyncio
async def test_corrupt_filtered_out_plan_still_rejects_whole_catalog(tmp_path):
    _, manifest, artifact = configuration()
    plans = SQLiteKnowledgeIndexPlanStore(tmp_path / "plans.db")
    await plans.initialize(confirm_create=True)
    await plans.save(artifact((0,)), confirm_write=True)
    db = sqlite3.connect(plans.database_path)
    try:
        db.execute("INSERT INTO knowledge_index_plans VALUES (?, ?)", ("a" * 64, "{}"))
        db.commit()
    finally:
        db.close()
    with pytest.raises(KnowledgeIndexPlanError):
        await review_knowledge_plan_catalog(plans.database_path, manifest_digest=manifest.digest, confirm_read=True)


@pytest.mark.asyncio
async def test_catalog_cap_and_missing_db_are_not_silent_truncation_or_creation(tmp_path):
    plans = SQLiteKnowledgeIndexPlanStore(tmp_path / "plans.db")
    with pytest.raises(KnowledgeIndexPlanError):
        await plans.list_plans()
    assert not plans.database_path.exists()
    await plans.initialize(confirm_create=True)
    db = sqlite3.connect(plans.database_path)
    try:
        db.executemany("INSERT INTO knowledge_index_plans VALUES (?, ?)", ((f"{i:064x}", "{}") for i in range(129)))
        db.commit()
    finally:
        db.close()
    with pytest.raises(KnowledgeIndexPlanError, match="catalog-limit-exceeded"):
        await plans.list_plans()


def test_cli_catalog_requires_consent_before_store_access(tmp_path, monkeypatch):
    from w_agent.cli import app

    async def forbidden(self):
        pytest.fail("unauthorized catalog access")

    monkeypatch.setattr(SQLiteKnowledgeIndexPlanStore, "list_plans", forbidden)
    result = CliRunner().invoke(app, ["knowledge-plan-list", "--database", str(tmp_path / "missing.db")])
    assert result.exit_code == 2 and not (tmp_path / "missing.db").exists()


@pytest.mark.asyncio
async def test_batch_review_limits_and_paths_fail_before_reads(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("invalid batch review must not read storage")

    monkeypatch.setattr(SQLiteKnowledgeIndexPlanStore, "list_plans", forbidden)
    monkeypatch.setattr(SQLiteKnowledgeSnapshotStore, "load", forbidden)
    for options in ({"max_documents": True}, {"max_documents": 129}, {"max_input_bytes": 0},
                    {"max_vector_values": 1048577}, {"include_ids": 1}):
        with pytest.raises((ValueError, KnowledgeIndexPlanError)):
            await review_missing_knowledge_batches(tmp_path / "plans.db", tmp_path / "source.db",
                                                  "n", "v", "a" * 64, confirm_read=True, **options)
    with pytest.raises(ValueError):
        await review_missing_knowledge_batches(tmp_path / "same.db", tmp_path / "same.db",
                                              "n", "v", "a" * 64, confirm_read=True)


@pytest.mark.asyncio
async def test_review_respects_custom_batch_bounds_and_hides_ids_by_default(tmp_path):
    index, manifest, artifact = configuration(5)
    plans = SQLiteKnowledgeIndexPlanStore(tmp_path / "plans.db")
    source = SQLiteKnowledgeSnapshotStore(tmp_path / "source.db")
    await plans.initialize(confirm_create=True)
    await source.initialize(confirm_create=True)
    await plans.save(artifact((0,)), confirm_write=True)
    await source.save(index.snapshot, confirm_write=True)
    result = await review_missing_knowledge_batches(plans.database_path, source.database_path, "n", "v",
                                                  manifest.digest, confirm_read=True, max_documents=2)
    assert [item["document_count"] for item in result["batches"]] == [2, 2]
    assert result["limits"]["max_documents"] == 2
    assert all("document_ids" not in item and "point_ids" not in item for item in result["batches"])
    assert "PRIVATE" not in json.dumps(result)


def test_cli_passes_explicit_batch_limits(tmp_path, monkeypatch):
    from w_agent.cli import app
    import w_agent.knowledge_index_cli as cli

    calls = []

    async def review(*args, **kwargs):
        calls.append((args, kwargs))
        return {"advisory_only": True, "batches": []}

    monkeypatch.setattr(cli, "review_missing_knowledge_batches", review)
    result = CliRunner().invoke(app, ["knowledge-plan-batches", "--plan-database", str(tmp_path / "plans.db"),
        "--source-database", str(tmp_path / "source.db"), "--namespace", "n", "--version", "v",
        "--manifest-digest", "a" * 64, "--confirm-read", "--max-documents", "3",
        "--max-input-bytes", "512", "--max-vector-values", "6"])
    assert result.exit_code == 0 and len(calls) == 1
    assert calls[0][1] == {"confirm_read": True, "include_ids": False, "max_documents": 3,
                           "max_input_bytes": 512, "max_vector_values": 6}
