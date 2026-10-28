"""Draft host-backed prepare/execute boundaries; never executed this round."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from w_agent import (
    HttpToolResponse, KnowledgeDocument, KnowledgeSnapshot, QdrantVectorSearch,
    QdrantVectorWriter, SQLiteKnowledgeSnapshotStore, SQLiteKnowledgeIndexPlanStore,
    KnowledgeIndexJournalError,
)
import w_agent.knowledge_plan_actions as actions


class Embedder:
    def __init__(self):
        self.calls = []

    async def embed(self, text):
        self.calls.append(text)
        return (1.0, 2.0)


class Transport:
    def __init__(self):
        self.calls = []

    async def send(self, request, **kwargs):
        self.calls.append(request)
        return HttpToolResponse(200, {}, b'{"status":"ok","result":{"status":"completed"}}')


class Context:
    def __init__(self, catalog, events, *, fail_exit=False):
        self.catalog, self.events, self.fail_exit = catalog, events, fail_exit

    async def __aenter__(self):
        self.events.append("enter")
        return self.catalog

    async def __aexit__(self, *args):
        self.events.append("exit")
        if self.fail_exit:
            raise RuntimeError("PRIVATE_CLEANUP_ERROR")
        return True  # Must not suppress action errors/cancellation.


def host(monkeypatch, *, fail_exit=False):
    embedder, transport, events = Embedder(), Transport(), []
    writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "knowledge", transport=transport))
    binding = actions.KnowledgeIndexHostBinding(writer, embedder, "model-r1", 2)
    original_import = actions.importlib.import_module

    def import_host(name, package=None):
        if name != "host":
            return original_import(name, package)
        return SimpleNamespace(factory=lambda: Context(
            {"manual": binding, "write-only": actions.KnowledgeIndexHostBinding(writer)}, events, fail_exit=fail_exit))

    monkeypatch.setattr(actions.importlib, "import_module", import_host)
    return embedder, transport, events


def prepare_request(tmp_path, **options):
    values = dict(host=actions.KnowledgeIndexHostOptions("host:factory", "manual", True),
                  source_database=tmp_path / "source.db", namespace="n", version="v1",
                  plan_database=tmp_path / "plans.db", confirm_read=True,
                  confirm_embedding=True, confirm_save=True, confirm_create=True)
    values.update(options)
    return actions.KnowledgePlanPrepareRequest(**values)


async def source(tmp_path):
    store = SQLiteKnowledgeSnapshotStore(tmp_path / "source.db")
    await store.initialize(confirm_create=True)
    await store.save(KnowledgeSnapshot("n", "v1", (KnowledgeDocument("doc", "PRIVATE_BODY"),)), confirm_write=True)


@pytest.mark.asyncio
async def test_prepare_save_then_separately_authorized_execute_without_reembedding(tmp_path, monkeypatch):
    await source(tmp_path)
    embedder, transport, events = host(monkeypatch)
    saved = await actions.prepare_local_knowledge_plan(prepare_request(tmp_path))
    assert events == ["enter", "exit"] and len(embedder.calls) == 1 and not transport.calls
    assert saved["authorized"] is False and saved["operation"] == "prepare-save"
    request = actions.KnowledgePlanExecuteRequest(
        actions.KnowledgeIndexHostOptions("host:factory", "write-only", True),
        tmp_path / "plans.db", saved["artifact_digest"], saved["artifact_digest"],
        tmp_path / "journal.db", "attempt-1", True, True, True, True,
    )
    receipt = await actions.execute_local_knowledge_plan(request)
    assert receipt["receipt_status"] == "completed" and receipt["remote_state_verified"] is False
    assert len(embedder.calls) == 1 and len(transport.calls) == 1
    with pytest.raises(KnowledgeIndexJournalError):
        await actions.execute_local_knowledge_plan(request)
    assert len(transport.calls) == 1 and events == ["enter", "exit"] * 3


@pytest.mark.parametrize("options", [{"confirm_read": False}, {"confirm_embedding": False},
                                      {"confirm_save": False}, {"confirm_embedding": 1},
                                      {"confirm_create": 1}, {"document_ids": ()}])
def test_prepare_preflight_requires_independent_consent(tmp_path, options):
    with pytest.raises(ValueError):
        prepare_request(tmp_path, **options)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_invalid_selection_or_missing_store_fails_before_host_code(tmp_path, monkeypatch):
    await source(tmp_path)
    monkeypatch.setattr(actions.importlib, "import_module", lambda name: pytest.fail("host code entered"))
    with pytest.raises(actions.KnowledgePlanActionError, match="selection-invalid"):
        await actions.prepare_local_knowledge_plan(prepare_request(tmp_path, document_ids=("absent",)))
    assert not (tmp_path / "plans.db").exists()
    from w_agent.knowledge_index_plans import KnowledgeIndexPlanError
    with pytest.raises(KnowledgeIndexPlanError):
        await actions.prepare_local_knowledge_plan(prepare_request(tmp_path, confirm_create=False))
    assert not (tmp_path / "plans.db").exists()


@pytest.mark.asyncio
async def test_cleanup_failure_does_not_mean_saved_plan_rolled_back(tmp_path, monkeypatch):
    await source(tmp_path)
    _, _, events = host(monkeypatch, fail_exit=True)
    saved_digests = []
    original = SQLiteKnowledgeIndexPlanStore.save

    async def capture(self, artifact, *, confirm_write=False):
        digest = await original(self, artifact, confirm_write=confirm_write)
        saved_digests.append(digest)
        return digest

    monkeypatch.setattr(SQLiteKnowledgeIndexPlanStore, "save", capture)
    with pytest.raises(actions.KnowledgePlanActionError, match="cleanup-failed") as error:
        await actions.prepare_local_knowledge_plan(prepare_request(tmp_path))
    assert "PRIVATE" not in str(error.value) and events == ["enter", "exit"]
    assert (await SQLiteKnowledgeIndexPlanStore(tmp_path / "plans.db").load(saved_digests[0])).digest == saved_digests[0]


@pytest.mark.asyncio
async def test_host_exit_cannot_suppress_error_or_cancellation(monkeypatch):
    _, _, events = host(monkeypatch)
    for error in (ValueError("body"), asyncio.CancelledError()):
        with pytest.raises(type(error)):
            async with actions.knowledge_index_host_scope(actions.KnowledgeIndexHostOptions("host:factory", "manual", True)):
                raise error
    assert events == ["enter", "exit"] * 2


@pytest.mark.asyncio
async def test_invalid_catalog_is_closed(monkeypatch):
    events = []
    monkeypatch.setattr(actions.importlib, "import_module", lambda name: SimpleNamespace(factory=lambda: Context({}, events)))
    with pytest.raises(actions.KnowledgePlanActionError, match="catalog-invalid"):
        async with actions.knowledge_index_host_scope(actions.KnowledgeIndexHostOptions("host:factory", "manual", True)):
            pytest.fail("invalid catalog yielded")
    assert events == ["enter", "exit"]


@pytest.mark.parametrize("value", ['[]', '[true]', '["a","a"]', '[null]', '[NaN]', '{}'])
def test_document_selection_json_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        actions.parse_knowledge_document_ids(value)


def test_execute_preflight_and_cli_refuse_missing_permissions(tmp_path, monkeypatch):
    from w_agent.cli import app
    import w_agent.knowledge_plan_action_cli as adapter

    async def forbidden(request):
        pytest.fail("action entered without consent")

    monkeypatch.setattr(adapter, "execute_local_knowledge_plan", forbidden)
    args = ["knowledge-plan-execute", "--host-entry", "host:factory", "--binding", "manual",
            "--plan-database", str(tmp_path / "plans.db"), "--artifact-digest", "a" * 64,
            "--approved-digest", "b" * 64, "--journal-database", str(tmp_path / "journal.db"),
            "--attempt-id", "a", "--confirm-code", "--confirm-read", "--confirm-remote-write", "--confirm-record"]
    assert CliRunner().invoke(app, args).exit_code == 2
    request = actions.KnowledgePlanExecuteRequest(
        actions.KnowledgeIndexHostOptions("host:factory", "manual", True),
        tmp_path / "plans.db", "a" * 64, "a" * 64, tmp_path / "journal.db", "a", True, True, True,
    )
    for field in ("confirm_read", "confirm_remote_write", "confirm_record"):
        with pytest.raises(ValueError):
            replace(request, **{field: False})
    assert list(tmp_path.iterdir()) == []
