"""Draft exact-plan staging/execution boundaries; unexecuted, fake transports only."""

import hashlib
import json
import sqlite3
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from w_agent import (
    DenseVectorPoint, HttpToolResponse, KnowledgeDocument, KnowledgeIndexJournalError,
    KnowledgeIndexPlanError, KnowledgeSnapshot, KnowledgeVectorIndex, PreparedKnowledgeIndexPlan,
    QdrantVectorSearch, QdrantVectorWriter, SQLiteKnowledgeIndexJournal,
    SQLiteKnowledgeIndexPlanStore, execute_prepared_knowledge_plan, inspect_stored_knowledge_plan,
    knowledge_index_manifest, prepare_knowledge_index_plan, prepared_knowledge_plan_from_json,
    VectorIndexWriteError, VectorRetrievalError,
)


class Transport:
    def __init__(self):
        self.requests = []

    async def send(self, request, **kwargs):
        self.requests.append(request)
        return HttpToolResponse(200, {}, b'{"status":"ok","result":{"status":"completed","operation_id":1}}')


class Embedder:
    def __init__(self):
        self.inputs = []

    async def embed(self, text):
        self.inputs.append(text)
        return (0.125, -0.5)


def configuration():
    transport = Transport()
    writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "PRIVATE_COLLECTION", transport=transport))
    index = KnowledgeVectorIndex(KnowledgeSnapshot("n", "v1", (KnowledgeDocument("d", "PRIVATE_BODY"),)), "PRIVATE_MODEL", 2)
    artifact = PreparedKnowledgeIndexPlan(knowledge_index_manifest(index, writer),
                                         writer.plan((DenseVectorPoint(index.point_ids[0], (0.125, -0.5)),)))
    return index, writer, transport, artifact


def test_roundtrip_identity_and_explicit_sensitive_views():
    _, _, _, artifact = configuration()
    encoded = artifact.to_json()
    assert prepared_knowledge_plan_from_json(encoded, expected_digest=artifact.digest) == artifact
    assert "PRIVATE_BODY" not in encoded and "PRIVATE_MODEL" in encoded
    assert "PRIVATE" not in repr(artifact)
    summary = artifact.summary()
    assert "PRIVATE" not in json.dumps(summary)
    assert summary["authorized"] is False and summary["remote_state_verified"] is False
    assert artifact.summary(include_target=True)["embedding_key"] == "PRIVATE_MODEL"
    assert "vector" not in artifact.summary(include_target=True)


@pytest.mark.parametrize("mutation", ["extra", "dimension", "point", "plan_digest", "manifest_digest", "boolean", "nan", "duplicates", "noncanonical"])
def test_rehashed_invalid_payload_is_still_rejected(mutation):
    _, _, _, artifact = configuration()
    value = json.loads(artifact.to_json())
    if mutation == "extra":
        value["extra"] = True
    elif mutation == "dimension":
        value["manifest"]["dimensions"] = 3
    elif mutation == "point":
        value["points"][0]["id"] = "00000000-0000-0000-0000-000000000000"
    elif mutation in {"plan_digest", "manifest_digest"}:
        value[mutation] = "a" * 64
    elif mutation == "boolean":
        value["points"][0]["vector"][0] = True
    elif mutation == "nan":
        value["points"][0]["vector"][0] = float("nan")
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if mutation == "duplicates":
        payload = payload.replace('"format":', '"format":"duplicate","format":', 1)
    elif mutation == "noncanonical":
        payload += "\n"
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with pytest.raises(KnowledgeIndexPlanError, match="decode-failed"):
        prepared_knowledge_plan_from_json(payload, expected_digest=digest)


@pytest.mark.asyncio
async def test_explicit_preparation_then_reopen_and_execute_without_reembedding(tmp_path):
    index, writer, transport, _ = configuration()
    embedder = Embedder()
    with pytest.raises(VectorRetrievalError):
        await prepare_knowledge_index_plan(index, embedder, writer)
    assert not embedder.inputs and not transport.requests
    artifact = await prepare_knowledge_index_plan(index, embedder, writer, confirm_embedding=True)
    assert len(embedder.inputs) == 1 and not transport.requests
    store = SQLiteKnowledgeIndexPlanStore(tmp_path / "plans.db")
    for flag in (False, 1):
        with pytest.raises(KnowledgeIndexPlanError):
            await store.initialize(confirm_create=flag)
        with pytest.raises(KnowledgeIndexPlanError):
            await store.save(artifact, confirm_write=flag)
    assert not store.database_path.exists()
    await store.initialize(confirm_create=True)
    digest = await store.save(artifact, confirm_write=True)
    assert await store.save(artifact, confirm_write=True) == digest
    loaded = await SQLiteKnowledgeIndexPlanStore(store.database_path).load(digest)
    assert loaded == artifact
    preview = await inspect_stored_knowledge_plan(store.database_path, digest, confirm_read=True)
    assert preview["artifact_digest"] == digest and "PRIVATE" not in json.dumps(preview)
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.db")
    await journal.initialize(confirm_create=True)
    with pytest.raises(KnowledgeIndexPlanError):
        await execute_prepared_knowledge_plan(loaded, writer, journal, attempt_id="a", confirm_artifact_digest="0" * 64, confirm_record=True)
    assert not transport.requests
    receipt = await execute_prepared_knowledge_plan(loaded, writer, journal, attempt_id="a", confirm_artifact_digest=digest, confirm_record=True)
    assert receipt.status == "completed" and len(embedder.inputs) == 1
    assert transport.requests[0].json_body["points"][0]["vector"] == [0.125, -0.5]
    with pytest.raises(KnowledgeIndexJournalError):
        await execute_prepared_knowledge_plan(loaded, writer, journal, attempt_id="a", confirm_artifact_digest=digest, confirm_record=True)
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_wrong_writer_rejected_before_journal_and_transport(tmp_path):
    _, writer, transport, artifact = configuration()
    wrong_writer = QdrantVectorWriter(replace(writer.backend, collection="different"))
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "never-created.db")
    with pytest.raises(KnowledgeIndexPlanError, match="writer-mismatch"):
        await execute_prepared_knowledge_plan(artifact, wrong_writer, journal, attempt_id="a",
                                             confirm_artifact_digest=artifact.digest, confirm_record=True)
    assert not journal.database_path.exists() and not transport.requests


@pytest.mark.asyncio
async def test_unknown_write_keeps_exact_plan_and_does_not_retry(tmp_path):
    _, writer, _, artifact = configuration()

    class FailingTransport:
        calls = 0

        async def send(self, request, **kwargs):
            self.calls += 1
            raise RuntimeError("PRIVATE_REMOTE_ERROR")

    transport = FailingTransport()
    writer = QdrantVectorWriter(replace(writer.backend, transport=transport))
    store = SQLiteKnowledgeIndexPlanStore(tmp_path / "plans.db")
    await store.initialize(confirm_create=True)
    await store.save(artifact, confirm_write=True)
    journal = SQLiteKnowledgeIndexJournal(tmp_path / "journal.db")
    await journal.initialize(confirm_create=True)
    with pytest.raises(VectorIndexWriteError):
        await execute_prepared_knowledge_plan(artifact, writer, journal, attempt_id="a",
                                             confirm_artifact_digest=artifact.digest, confirm_record=True)
    state = await journal.inspect(artifact.manifest.digest)
    assert state.attempts[0].outcome == "unknown" and state.unresolved_attempt_ids == ("a",)
    assert await store.load(artifact.digest) == artifact
    assert transport.calls == 1
    with pytest.raises(KnowledgeIndexJournalError):
        await execute_prepared_knowledge_plan(artifact, writer, journal, attempt_id="a",
                                             confirm_artifact_digest=artifact.digest, confirm_record=True)
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_empty_and_invalid_batches_never_embed():
    index, writer, _, _ = configuration()
    embedder = Embedder()
    with pytest.raises(KnowledgeIndexPlanError):
        await prepare_knowledge_index_plan(index, embedder, writer, document_ids=(), confirm_embedding=True)
    with pytest.raises(VectorRetrievalError):
        await prepare_knowledge_index_plan(index, embedder, writer, document_ids=("missing",), confirm_embedding=True)
    assert not embedder.inputs


@pytest.mark.asyncio
async def test_missing_and_corrupt_store_never_returns_partial_plan(tmp_path):
    _, _, _, artifact = configuration()
    store = SQLiteKnowledgeIndexPlanStore(tmp_path / "plans.db")
    with pytest.raises(KnowledgeIndexPlanError):
        await store.load(artifact.digest)
    assert not store.database_path.exists()
    await store.initialize(confirm_create=True)
    await store.save(artifact, confirm_write=True)
    db = sqlite3.connect(store.database_path)
    try:
        db.execute("UPDATE knowledge_index_plans SET payload = '{}' ")
        db.commit()
    finally:
        db.close()
    with pytest.raises(KnowledgeIndexPlanError):
        await store.load(artifact.digest)
    with pytest.raises(KnowledgeIndexPlanError):
        await store.save(artifact, confirm_write=True)  # Never repair by silently overwriting.


def test_cli_without_consent_does_not_load_store(tmp_path, monkeypatch):
    from w_agent.cli import app

    async def forbidden(*args):
        pytest.fail("unauthorized load")

    monkeypatch.setattr(SQLiteKnowledgeIndexPlanStore, "load", forbidden)
    result = CliRunner().invoke(app, ["knowledge-plan-inspect", "--database", str(tmp_path / "absent.db"),
                                    "--artifact-digest", "a" * 64])
    assert result.exit_code == 2 and not (tmp_path / "absent.db").exists()
