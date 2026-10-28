"""Draft full-build selection/persistence/continuation tests; not executed."""

import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from w_agent import (
    DenseVectorPoint, HttpToolResponse, KnowledgeDocument, KnowledgeSnapshot, KnowledgeVectorIndex,
    QdrantVectorSearch, QdrantVectorWriter, PreparedKnowledgeIndexPlan, knowledge_index_manifest,
    KnowledgeIndexPlanInfo, SQLiteKnowledgeIndexPlanStore, SQLiteKnowledgeIndexJournal,
    KnowledgeIndexReconciliation, KnowledgeIndexJournalSnapshot, KnowledgeIndexJournalError,
    KnowledgeBuildError, KnowledgeIndexBuild, SQLiteKnowledgeBuildStore, assemble_knowledge_build,
    knowledge_build_from_json, knowledge_build_progress, inspect_knowledge_build_progress,
    execute_knowledge_build_batch, create_local_knowledge_build, review_local_knowledge_build,
    VectorIndexWriteError,
    KnowledgeBuildExecuteRequest, KnowledgeIndexHostOptions, KnowledgeIndexHostBinding,
    execute_local_knowledge_build_batch,
)

import w_agent.knowledge_build_management as management


class Transport:
    def __init__(self, fail=False):
        self.requests = []
        self.fail = fail

    async def send(self, request, **kwargs):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("PRIVATE_REMOTE_FAILURE")
        return HttpToolResponse(200, {}, b'{"status":"ok","result":{"status":"completed"}}')


def configuration():
    transport = Transport()
    index = KnowledgeVectorIndex(KnowledgeSnapshot("n", "v", (
        KnowledgeDocument("a", "PRIVATE_BODY_A"), KnowledgeDocument("b", "PRIVATE_BODY_B"),
    )), "PRIVATE_MODEL", 2)
    writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "PRIVATE_COLLECTION", transport=transport))
    manifest = knowledge_index_manifest(index, writer)
    artifacts = tuple(PreparedKnowledgeIndexPlan(manifest, writer.plan((DenseVectorPoint(point, (1, 2)),))) for point in index.point_ids)
    build = KnowledgeIndexBuild("manual-build", "v1", manifest, tuple(KnowledgeIndexPlanInfo.from_artifact(a) for a in artifacts))
    return writer, transport, artifacts, build


async def staged(tmp_path):
    writer, transport, artifacts, build = configuration()
    plans = SQLiteKnowledgeIndexPlanStore(tmp_path / "plans.db")
    await plans.initialize(confirm_create=True)
    for artifact in artifacts:
        await plans.save(artifact, confirm_write=True)
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.db")
    await journal.initialize(confirm_create=True)
    return writer, transport, artifacts, build, plans, journal


async def managed_build(tmp_path, monkeypatch, *, fail_exit=False):
    writer, transport, artifacts, build, plans, journal = await staged(tmp_path)
    store = SQLiteKnowledgeBuildStore(tmp_path / "builds.db")
    await store.initialize(confirm_create=True)
    await store.save(build, confirm_write=True)
    events = []

    @asynccontextmanager
    async def scope(options):
        events.append("enter")
        try:
            yield KnowledgeIndexHostBinding(writer)  # No embedder exists.
        finally:
            events.append("exit")
            if fail_exit:
                raise RuntimeError("PRIVATE_CLEANUP_FAILURE")

    monkeypatch.setattr(management, "knowledge_index_host_scope", scope)
    request = KnowledgeBuildExecuteRequest(
        KnowledgeIndexHostOptions("host:factory", "write-only", True), store.database_path,
        build.name, build.version, plans.database_path, journal.database_path,
        artifacts[0].digest, build.digest, artifacts[0].digest,
        confirm_read=True, confirm_remote_write=True, confirm_record=True,
    )
    return request, transport, events, build, journal


@pytest.mark.asyncio
async def test_managed_preflight_and_approval_fail_before_host(tmp_path, monkeypatch):
    request, transport, events, _, _ = await managed_build(tmp_path, monkeypatch)
    for field in ("confirm_read", "confirm_remote_write", "confirm_record"):
        with pytest.raises(ValueError):
            replace(request, **{field: False})
        with pytest.raises(ValueError):
            replace(request, **{field: 1})
    with pytest.raises(ValueError):
        replace(request, approved_artifact_digest="f" * 64)
    with pytest.raises(ValueError):
        replace(request, journal_database=request.plan_database)
    with pytest.raises(KnowledgeBuildError, match="approval-mismatch"):
        await execute_local_knowledge_build_batch(replace(request, approved_build_digest="f" * 64))
    with pytest.raises(KnowledgeBuildError):
        await execute_local_knowledge_build_batch(replace(request, artifact_digest="f" * 64,
                                                        approved_artifact_digest="f" * 64))
    assert not events and not transport.requests


@pytest.mark.asyncio
async def test_managed_execution_only_host_and_duplicate_refusal(tmp_path, monkeypatch):
    request, transport, events, build, _ = await managed_build(tmp_path, monkeypatch)
    result = await execute_local_knowledge_build_batch(request)
    assert result["attempt_id"] == build.attempt_id(request.artifact_digest)
    assert result["receipt_status"] == "completed" and result["remote_state_verified"] is False
    assert events == ["enter", "exit"] and len(transport.requests) == 1
    with pytest.raises(KnowledgeBuildError, match="already-attempted-or-blocked"):
        await execute_local_knowledge_build_batch(request)
    assert len(transport.requests) == 1 and events == ["enter", "exit"] * 2


@pytest.mark.asyncio
async def test_managed_journal_creation_is_explicit(tmp_path, monkeypatch):
    request, transport, _, _, _ = await managed_build(tmp_path, monkeypatch)
    path = tmp_path / "new-journal.db"
    request = replace(request, journal_database=path)
    with pytest.raises(KnowledgeIndexJournalError):
        await execute_local_knowledge_build_batch(request)
    assert not path.exists() and not transport.requests
    await execute_local_knowledge_build_batch(replace(request, confirm_create_journal=True))
    assert path.exists() and len(transport.requests) == 1


@pytest.mark.asyncio
async def test_managed_cleanup_failure_preserves_completed_receipt(tmp_path, monkeypatch):
    request, transport, events, build, journal = await managed_build(tmp_path, monkeypatch, fail_exit=True)
    with pytest.raises(RuntimeError, match="PRIVATE_CLEANUP_FAILURE"):
        await execute_local_knowledge_build_batch(request)
    assert len(transport.requests) == 1 and events == ["enter", "exit"]
    progress = await inspect_knowledge_build_progress(build, journal)
    assert progress["batches"][0]["effective_outcome"] == "completed"
    assert not progress["batches"][0]["can_request_first_execution"]


@pytest.mark.asyncio
async def test_managed_unknown_result_is_not_resent(tmp_path, monkeypatch):
    request, transport, _, build, journal = await managed_build(tmp_path, monkeypatch)
    transport.fail = True
    with pytest.raises(VectorIndexWriteError):
        await execute_local_knowledge_build_batch(request)
    progress = await inspect_knowledge_build_progress(build, journal)
    assert progress["batches"][0]["effective_outcome"] == "unknown"
    transport.fail = False
    with pytest.raises(KnowledgeBuildError, match="already-attempted-or-blocked"):
        await execute_local_knowledge_build_batch(request)
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_managed_target_mismatch_does_not_create_journal(tmp_path, monkeypatch):
    request, transport, _, _, _ = await managed_build(tmp_path, monkeypatch)
    wrong = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "OTHER_COLLECTION", transport=transport))

    @asynccontextmanager
    async def scope(options):
        yield KnowledgeIndexHostBinding(wrong)

    monkeypatch.setattr(management, "knowledge_index_host_scope", scope)
    path = tmp_path / "not-created.db"
    request = replace(request, journal_database=path, confirm_create_journal=True)
    with pytest.raises(KnowledgeBuildError, match="writer-mismatch"):
        await execute_local_knowledge_build_batch(request)
    assert not path.exists() and not transport.requests


def test_build_execute_cli_requires_all_confirmations(monkeypatch, tmp_path):
    from w_agent.cli import app
    import w_agent.knowledge_build_cli as cli

    calls = []

    async def execute(request):
        calls.append(request)
        return {"receipt_status": "completed", "remote_state_verified": False}

    monkeypatch.setattr(cli, "execute_local_knowledge_build_batch", execute)
    args = ["knowledge-build-execute", "--host", "host:factory", "--binding", "write-only",
            "--build-database", str(tmp_path / "builds.db"), "--name", "b", "--version", "v1",
            "--plan-database", str(tmp_path / "plans.db"), "--journal-database", str(tmp_path / "journal.db"),
            "--artifact-digest", "a" * 64, "--approved-artifact-digest", "a" * 64,
            "--approved-build-digest", "b" * 64]
    assert CliRunner().invoke(app, args).exit_code == 2 and not calls
    result = CliRunner().invoke(app, args + ["--confirm-code", "--confirm-read", "--confirm-remote-write", "--confirm-record"])
    assert result.exit_code == 0 and len(calls) == 1
    assert calls[0].approved_build_digest == "b" * 64
    assert not calls[0].confirm_create_journal


def test_build_requires_disjoint_full_selection_and_binds_names_order():
    _, _, _, build = configuration()
    with pytest.raises(KnowledgeBuildError):
        replace(build, plans=build.plans[:1])
    with pytest.raises(ValueError):
        replace(build, plans=(build.plans[0], build.plans[0], build.plans[1]))
    with pytest.raises(KnowledgeBuildError):
        replace(build, plans=(build.plans[0], replace(build.plans[0], artifact_digest="a" * 64), build.plans[1]))
    with pytest.raises(KnowledgeBuildError, match="journal-mismatch"):
        knowledge_build_progress(build, KnowledgeIndexJournalSnapshot(replace(build.manifest, embedding_key="other")))
    assert replace(build, plans=tuple(reversed(build.plans))).digest != build.digest
    assert replace(build, version="v2").digest != build.digest
    assert "PRIVATE" not in json.dumps(build.summary())
    assert knowledge_build_from_json(build.to_json(), expected_digest=build.digest) == build
    assert build.attempt_id(build.plans[0].artifact_digest) == build.attempt_id(build.plans[0].artifact_digest)
    value = json.loads(build.to_json())
    value["plans"].pop()
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    with pytest.raises(KnowledgeBuildError, match="decode-failed"):
        knowledge_build_from_json(payload, expected_digest=hashlib.sha256(payload.encode()).hexdigest())


@pytest.mark.asyncio
async def test_preview_named_save_reopen_and_conflict(tmp_path):
    _, _, artifacts, build, plans, _ = await staged(tmp_path)
    digests = tuple(item.digest for item in artifacts)
    assembled = await assemble_knowledge_build(build.name, build.version, plans, digests, confirm_read=True)
    assert assembled == build
    target = tmp_path / "builds.db"
    preview = await create_local_knowledge_build(plans.database_path, target, build.name, build.version, digests, confirm_read=True)
    assert preview["state"] == "preview" and not target.exists()
    saved = await create_local_knowledge_build(plans.database_path, target, build.name, build.version, digests,
                                             confirm_read=True, confirm_save=True, confirm_create=True)
    assert saved["state"] == "saved" and saved["build_digest"] == build.digest
    store = SQLiteKnowledgeBuildStore(target)
    assert await store.load(build.name, build.version) == build
    assert await store.save(build, confirm_write=True) == build.digest
    with pytest.raises(KnowledgeBuildError, match="version-conflict"):
        await store.save(replace(build, plans=tuple(reversed(build.plans))), confirm_write=True)
    reviewed = await review_local_knowledge_build(target, build.name, build.version, confirm_read=True)
    assert reviewed["artifact_availability_checked"] is False and "progress" not in reviewed


@pytest.mark.asyncio
async def test_explicit_per_batch_continuation_uses_stable_ids_and_never_replays(tmp_path):
    writer, transport, artifacts, build, plans, journal = await staged(tmp_path)
    initial = await inspect_knowledge_build_progress(build, journal)
    assert all(item["can_request_first_execution"] for item in initial["batches"])
    first = artifacts[0].digest
    await execute_knowledge_build_batch(build, first, plans, writer, journal,
        confirm_build_digest=build.digest, confirm_artifact_digest=first, confirm_record=True)
    progress = await inspect_knowledge_build_progress(build, journal)
    assert progress["batches"][0]["effective_outcome"] == "completed"
    assert progress["batches"][1]["can_request_first_execution"]
    assert not progress["all_batches_locally_completed"]
    with pytest.raises(KnowledgeBuildError, match="already-attempted-or-blocked"):
        await execute_knowledge_build_batch(build, first, plans, writer, journal,
            confirm_build_digest=build.digest, confirm_artifact_digest=first, confirm_record=True)
    assert len(transport.requests) == 1
    second = artifacts[1].digest
    await execute_knowledge_build_batch(build, second, plans, writer, journal,
        confirm_build_digest=build.digest, confirm_artifact_digest=second, confirm_record=True)
    completed = await inspect_knowledge_build_progress(build, journal)
    assert completed["all_batches_locally_completed"] and not completed["remote_state_verified"]


@pytest.mark.asyncio
async def test_foreign_unknown_blocks_only_overlapping_batches_until_review(tmp_path):
    writer, transport, artifacts, build, plans, journal = await staged(tmp_path)
    await journal.begin(build.manifest, "foreign", artifacts[0].plan, confirm_write=True)
    await journal.record(build.manifest.digest, "foreign", outcome="unknown", confirm_write=True)
    progress = await inspect_knowledge_build_progress(build, journal)
    assert progress["batches"][0]["blocked_by_attempt_ids"] == ["foreign"]
    assert progress["batches"][1]["can_request_first_execution"]
    with pytest.raises(KnowledgeBuildError):
        await execute_knowledge_build_batch(build, artifacts[0].digest, plans, writer, journal,
            confirm_build_digest=build.digest, confirm_artifact_digest=artifacts[0].digest, confirm_record=True)
    assert not transport.requests
    await journal.reconcile(KnowledgeIndexReconciliation("r", build.manifest.digest, "foreign", artifacts[0].plan.digest,
        "unknown", "not-applied", "evidence", "actor"), confirm_inactive=True, confirm_write=True)
    assert (await inspect_knowledge_build_progress(build, journal))["batches"][0]["can_request_first_execution"]


@pytest.mark.asyncio
async def test_unknown_own_attempt_remains_blocked_and_unavailable_journal_is_not_fresh(tmp_path):
    writer, transport, artifacts, build, plans, journal = await staged(tmp_path)
    transport.fail = True
    digest = artifacts[0].digest
    with pytest.raises(VectorIndexWriteError):
        await execute_knowledge_build_batch(build, digest, plans, writer, journal,
            confirm_build_digest=build.digest, confirm_artifact_digest=digest, confirm_record=True)
    progress = await inspect_knowledge_build_progress(build, journal)
    assert progress["batches"][0]["effective_outcome"] == "unknown"
    with pytest.raises(KnowledgeBuildError):
        await execute_knowledge_build_batch(build, digest, plans, writer, journal,
            confirm_build_digest=build.digest, confirm_artifact_digest=digest, confirm_record=True)
    assert len(transport.requests) == 1
    missing = SQLiteKnowledgeIndexJournal(tmp_path / "absent.db")
    with pytest.raises(KnowledgeIndexJournalError):
        await inspect_knowledge_build_progress(build, missing)
    assert not missing.database_path.exists()


@pytest.mark.asyncio
async def test_mismatched_attempt_identity_and_missing_approval_fail(tmp_path):
    writer, transport, artifacts, build, plans, journal = await staged(tmp_path)
    with pytest.raises(KnowledgeBuildError, match="confirmation-invalid"):
        await execute_knowledge_build_batch(build, artifacts[0].digest, plans, writer, journal,
            confirm_build_digest="a" * 64, confirm_artifact_digest=artifacts[0].digest, confirm_record=True)
    assert not transport.requests
    await journal.begin(build.manifest, build.attempt_id(artifacts[0].digest), artifacts[1].plan, confirm_write=True)
    with pytest.raises(KnowledgeBuildError, match="attempt-mismatch"):
        await inspect_knowledge_build_progress(build, journal)


def test_cli_build_creation_without_read_permission_never_loads_plans(tmp_path, monkeypatch):
    from w_agent.cli import app

    async def forbidden(*args):
        pytest.fail("unconfirmed load")

    monkeypatch.setattr(SQLiteKnowledgeIndexPlanStore, "load", forbidden)
    result = CliRunner().invoke(app, ["knowledge-build-create", "--plan-database", str(tmp_path / "plans.db"),
        "--build-database", str(tmp_path / "builds.db"), "--name", "n", "--version", "v",
        "--artifact-digest", "a" * 64])
    assert result.exit_code == 2 and list(tmp_path.iterdir()) == []
