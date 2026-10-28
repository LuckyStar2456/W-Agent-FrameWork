"""Recovery, exact retry and shared-journal coordination regressions."""

import asyncio
import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from w_agent.knowledge_build_management import list_local_knowledge_builds
from w_agent.knowledge_build_sqlite import SQLiteKnowledgeBuildStore
from w_agent.knowledge_builds import (
    KnowledgeBuildError, execute_knowledge_build_batch, inspect_knowledge_build_progress,
    knowledge_build_retry_id, retry_knowledge_build_batch,
)
from w_agent.knowledge_build_recovery import (
    KnowledgePreparationRecoveryError, SQLiteKnowledgePreparationStore,
    prepare_recoverable_knowledge_plan,
)
from w_agent.knowledge_context import KnowledgeDocument
from w_agent.knowledge_index_journal import (
    KnowledgeIndexJournalError, KnowledgeIndexReconciliation, SQLiteKnowledgeIndexJournal,
)
from w_agent.knowledge_index_management import list_local_knowledge_journals
from w_agent.knowledge_ingestion import KnowledgeSnapshot
from w_agent.knowledge_plan_sqlite import SQLiteKnowledgeIndexPlanStore
from w_agent.knowledge_vectors import KnowledgeVectorIndex
from test_knowledge_builds import configuration, staged


@pytest.mark.asyncio
async def test_catalogs_reopen_order_and_suppress_sensitive_fields(tmp_path):
    _, _, artifacts, build, _, journal = await staged(tmp_path)
    builds = SQLiteKnowledgeBuildStore(tmp_path / "builds.db")
    await builds.initialize(confirm_create=True)
    await builds.save(replace(build, name="z"), confirm_write=True)
    await builds.save(replace(build, name="a"), confirm_write=True)
    await journal.begin(build.manifest, "pending-a", artifacts[0].plan, confirm_write=True)
    listing = await list_local_knowledge_builds(builds.database_path, confirm_read=True)
    assert [item["name"] for item in listing["builds"]] == ["a", "z"]
    receipts = await list_local_knowledge_journals(journal.database_path, confirm_read=True)
    assert receipts["journals"][0]["unresolved_attempt_ids"] == ["pending-a"]
    assert "PRIVATE" not in json.dumps([listing, receipts])


@pytest.mark.asyncio
async def test_catalog_missing_and_corrupt_database_are_not_empty(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(KnowledgeBuildError):
        await list_local_knowledge_builds(missing, confirm_read=True)
    with pytest.raises(KnowledgeIndexJournalError):
        await list_local_knowledge_journals(missing, confirm_read=True)
    assert not missing.exists()
    _, _, _, build = configuration()
    store = SQLiteKnowledgeBuildStore(tmp_path / "builds.db")
    await store.initialize(confirm_create=True)
    await store.save(build, confirm_write=True)
    with closing(sqlite3.connect(store.database_path)) as db, db:
        db.execute("UPDATE knowledge_builds SET name='tampered'")
    with pytest.raises(KnowledgeBuildError, match="identity-mismatch"):
        await store.list_builds()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["not-sent", "unknown"])
async def test_retry_requires_resolved_predecessor_and_preserves_history(tmp_path, outcome):
    writer, transport, artifacts, build, plans, journal = await staged(tmp_path)
    artifact = artifacts[0]
    identity = build.attempt_id(artifact.digest)
    await journal.begin(build.manifest, identity, artifact.plan, confirm_write=True)
    await journal.record(build.manifest.digest, identity, outcome=outcome, confirm_write=True)
    options = dict(previous_attempt_id=identity, confirm_build_digest=build.digest,
                   confirm_artifact_digest=artifact.digest, confirm_record=True)
    if outcome == "unknown":
        with pytest.raises(KnowledgeBuildError, match="retry-not-safe-or-stale"):
            await retry_knowledge_build_batch(build, artifact.digest, plans, writer, journal, **options)
        assert not transport.requests
        await journal.reconcile(KnowledgeIndexReconciliation(
            "review", build.manifest.digest, identity, artifact.plan.digest,
            "unknown", "not-applied", "host-evidence", "operator",
        ), confirm_inactive=True, confirm_write=True)
    await retry_knowledge_build_batch(build, artifact.digest, plans, writer, journal, **options)
    state = (await inspect_knowledge_build_progress(build, journal))["batches"][0]
    assert state["effective_outcome"] == "completed"
    assert state["attempt_history"] == [identity, knowledge_build_retry_id(build, artifact.digest, identity)]
    with pytest.raises(KnowledgeBuildError, match="retry-not-safe-or-stale"):
        await retry_knowledge_build_batch(build, artifact.digest, plans, writer, journal, **options)
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_concurrent_retry_sends_once(tmp_path):
    writer, transport, artifacts, build, plans, journal = await staged(tmp_path)
    artifact = artifacts[0]
    identity = build.attempt_id(artifact.digest)
    await journal.begin(build.manifest, identity, artifact.plan, confirm_write=True)
    await journal.record(build.manifest.digest, identity, outcome="not-sent", confirm_write=True)
    async def run():
        return await retry_knowledge_build_batch(
            build, artifact.digest, plans, writer, SQLiteKnowledgeIndexJournal(journal.database_path),
            previous_attempt_id=identity, confirm_build_digest=build.digest,
            confirm_artifact_digest=artifact.digest, confirm_record=True,
        )
    results = await asyncio.gather(run(), run(), return_exceptions=True)
    assert sum(isinstance(item, Exception) for item in results) == 1
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_exclusive_begin_coordinates_cross_manifest_overlap(tmp_path):
    _, _, artifacts, build, _, journal = await staged(tmp_path)
    foreign = replace(build.manifest, embedding_key="another-label")
    results = await asyncio.gather(
        journal.begin_exclusive(build.manifest, "first", artifacts[0].plan, confirm_write=True),
        SQLiteKnowledgeIndexJournal(journal.database_path).begin_exclusive(
            foreign, "second", artifacts[0].plan, confirm_write=True),
        return_exceptions=True,
    )
    assert sum(isinstance(item, KnowledgeIndexJournalError) for item in results) == 1
    assert len(await journal.list_journals()) == 1


@pytest.mark.asyncio
async def test_build_refuses_foreign_manifest_unknown_at_atomic_begin(tmp_path):
    writer, transport, artifacts, build, plans, journal = await staged(tmp_path)
    await journal.begin(replace(build.manifest, embedding_key="foreign"), "foreign", artifacts[0].plan, confirm_write=True)
    with pytest.raises(KnowledgeIndexJournalError, match="overlapping-attempt-unresolved"):
        await execute_knowledge_build_batch(
            build, artifacts[0].digest, plans, writer, journal,
            confirm_build_digest=build.digest, confirm_artifact_digest=artifacts[0].digest, confirm_record=True,
        )
    assert not transport.requests


class Embedder:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    async def embed(self, text):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider unavailable")
        return (1.0, 2.0)


async def recovery_stores(tmp_path):
    writer, transport, _, _ = configuration()
    index = KnowledgeVectorIndex(KnowledgeSnapshot("n", "v", (KnowledgeDocument("a", "body"),)), "model", 2)
    checkpoints = SQLiteKnowledgePreparationStore(tmp_path / "prepare.db")
    plans = SQLiteKnowledgeIndexPlanStore(tmp_path / "plans.db")
    await checkpoints.initialize(confirm_create=True)
    await plans.initialize(confirm_create=True)
    return writer, transport, index, checkpoints, plans


@pytest.mark.asyncio
async def test_failed_staging_resumes_ready_checkpoint_without_reembedding(tmp_path):
    writer, transport, index, checkpoints, plans = await recovery_stores(tmp_path)
    embedder = Embedder()
    class FailedPlans:
        async def save(self, *args, **kwargs):
            raise RuntimeError("disk unavailable")
    with pytest.raises(RuntimeError, match="disk unavailable"):
        await prepare_recoverable_knowledge_plan(
            index, embedder, writer, checkpoints, FailedPlans(), attempt_id="first",
            confirm_embedding=True, confirm_write=True,
        )
    assert (await checkpoints.list_checkpoints())[0].state == "ready"
    artifact = await prepare_recoverable_knowledge_plan(
        index, embedder, writer, SQLiteKnowledgePreparationStore(checkpoints.database_path), plans,
        attempt_id="resume", confirm_write=True,
    )
    assert await plans.load(artifact.digest) == artifact
    assert embedder.calls == 1 and not transport.requests


@pytest.mark.asyncio
async def test_pending_preparation_requires_retirement_and_new_explicit_embedding(tmp_path):
    writer, _, index, checkpoints, plans = await recovery_stores(tmp_path)
    embedder = Embedder(fail=True)
    options = dict(index=index, embedder=embedder, writer=writer, checkpoints=checkpoints, plans=plans,
                   attempt_id="first", confirm_embedding=True, confirm_write=True)
    with pytest.raises(Exception):
        await prepare_recoverable_knowledge_plan(**options)
    item = (await checkpoints.list_checkpoints())[0]
    assert item.state == "pending"
    with pytest.raises(KnowledgePreparationRecoveryError, match="pending-needs-review"):
        await prepare_recoverable_knowledge_plan(**options)
    assert embedder.calls == 1
    with pytest.raises(KnowledgePreparationRecoveryError, match="inactivity-required"):
        await checkpoints.abandon(item.batch_digest, item.attempt_id, evidence_ref="stopped", confirm_write=True)
    await checkpoints.abandon(item.batch_digest, item.attempt_id, evidence_ref="worker-stopped",
                              confirm_inactive=True, confirm_write=True)
    embedder.fail = False
    artifact = await prepare_recoverable_knowledge_plan(**{**options, "attempt_id": "second"})
    assert embedder.calls == 2
    with pytest.raises(KnowledgePreparationRecoveryError, match="transition-conflict"):
        await checkpoints.complete(item.batch_digest, "first", artifact, confirm_write=True)
    assert {entry.state for entry in await checkpoints.list_checkpoints()} == {"abandoned", "ready"}


@pytest.mark.asyncio
async def test_concurrent_preparation_has_one_embedding_owner(tmp_path):
    writer, _, index, checkpoints, plans = await recovery_stores(tmp_path)
    embedder = Embedder()
    async def run(attempt):
        return await prepare_recoverable_knowledge_plan(
            index, embedder, writer, SQLiteKnowledgePreparationStore(checkpoints.database_path), plans,
            attempt_id=attempt, confirm_embedding=True, confirm_write=True,
        )
    await asyncio.gather(run("a"), run("b"), return_exceptions=True)
    assert embedder.calls == 1
    assert len(await plans.list_plans()) == 1


def test_catalog_cli_requires_read_before_creating_anything(tmp_path):
    from w_agent.cli import app
    for command in ("knowledge-build-list", "knowledge-index-list", "knowledge-preparation-list"):
        result = CliRunner().invoke(app, [command, "--database", str(tmp_path / "none.db")])
        assert result.exit_code == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_managed_prepare_checkpoint_reopens_without_embedding_consent(tmp_path, monkeypatch):
    import w_agent.knowledge_plan_actions as actions
    from test_knowledge_plan_actions import host, source, prepare_request

    embedder, transport, _ = host(monkeypatch)
    await source(tmp_path)
    request = prepare_request(tmp_path, preparation_database=tmp_path / "checkpoints.db",
                              preparation_attempt_id="first")
    first = await actions.prepare_local_knowledge_plan(request)
    second = await actions.prepare_local_knowledge_plan(replace(
        request, confirm_create=False, confirm_embedding=False, preparation_attempt_id="resume",
    ))
    assert first["artifact_digest"] == second["artifact_digest"]
    assert len(embedder.calls) == 1 and not transport.calls
