"""Immutable associations and real Runtime preparation/resume boundaries."""

import asyncio
import sqlite3
import threading

import pytest

from w_agent import (
    LocalKnowledgeBinding, ToolSideEffect, assemble_local_runtime,
    local_runtime_config_from_mapping, python_tool,
)
from w_agent.service_usage import InMemoryServiceUsageLedger, ServiceUsageError
from w_agent.service_usage_links import (
    InMemoryServiceUsageLinkStore, ServiceUsageRunLink, SQLiteServiceUsageLinkStore,
)
from w_agent.service_usage_runtime import LocalServiceUsageBinding
from tests.test_service_usage_runtime import configuration, templates
from tests.test_service_usage_resume_frontends import ApprovalProvider, registry


@pytest.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryServiceUsageLinkStore(max_links=2)
    value = SQLiteServiceUsageLinkStore(tmp_path / "links.db", max_links=2)
    await value.initialize(confirm_create=True)
    return value


@pytest.mark.asyncio
async def test_immutable_authorized_bounded_links(store):
    first = ServiceUsageRunLink("session", "run-2", "op")
    with pytest.raises(ServiceUsageError):
        await store.bind(first)
    assert await store.get("run-2") is None
    await store.bind(first, confirm_write=True)
    await store.bind(first, confirm_write=True)
    assert await store.get("run-2") == first
    for conflict in (ServiceUsageRunLink("other", "run-2", "op"),
                     ServiceUsageRunLink("session", "run-2", "other")):
        with pytest.raises(ServiceUsageError):
            await store.bind(conflict, confirm_write=True)
    second = ServiceUsageRunLink("session", "run-1", "op")
    await store.bind(second, confirm_write=True)
    assert await store.for_session("session") == (second, first)
    assert await store.for_operation("op") == (second, first)
    assert await store.for_operation("unknown") == ()
    with pytest.raises(ServiceUsageError):
        await store.bind(ServiceUsageRunLink("session", "run-3", "op"), confirm_write=True)
    assert set(first.to_dict()) == {"session_id", "run_id", "operation_id"}


@pytest.mark.parametrize("value", ["", "../x", "x\n", "x" * 129, True])
def test_ids_and_binding_are_strict(value):
    with pytest.raises(ValueError):
        ServiceUsageRunLink(value, "run", "op")
    with pytest.raises(ValueError):
        ServiceUsageRunLink("session", value, "op")
    with pytest.raises(ValueError):
        LocalServiceUsageBinding(InMemoryServiceUsageLedger(), "op", links=object())


@pytest.mark.asyncio
async def test_sqlite_requires_creation_and_reopens_with_same_capacity(tmp_path):
    path = tmp_path / "links.db"
    store = SQLiteServiceUsageLinkStore(path, max_links=2)
    with pytest.raises(ServiceUsageError):
        await store.get("run")
    with pytest.raises(ServiceUsageError):
        await store.bind(ServiceUsageRunLink("session", "run", "op"), confirm_write=True)
    with pytest.raises(ServiceUsageError):
        await store.initialize()
    assert not path.exists()
    await store.initialize(confirm_create=True)
    link = ServiceUsageRunLink("session", "run", "op")
    await store.bind(link, confirm_write=True)
    reopened = SQLiteServiceUsageLinkStore(path, max_links=2)
    assert await reopened.get("run") == link
    with pytest.raises(ServiceUsageError):
        await SQLiteServiceUsageLinkStore(path, max_links=3).get("run")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE usage_run_links SET operation_id = ?", ("x" * 100000,))
    with pytest.raises(ServiceUsageError):
        await reopened.get("run")


@pytest.mark.asyncio
async def test_foreign_database_is_not_adopted(tmp_path):
    path = tmp_path / "foreign.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE preserve (value TEXT)")
        db.execute("INSERT INTO preserve VALUES ('untouched')")
    with pytest.raises(ServiceUsageError):
        await SQLiteServiceUsageLinkStore(path).initialize(confirm_create=True)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM preserve").fetchone() == ("untouched",)


@pytest.mark.asyncio
async def test_runtime_link_precedes_retrieval_and_survives_preparation_failure(tmp_path):
    links, ledger, created, observed = InMemoryServiceUsageLinkStore(), InMemoryServiceUsageLedger(), [], []

    class Retriever:
        async def retrieve(self, query, *, limit):
            observed.extend(await links.for_operation("operation"))
            assert len(observed) == 1
            raise RuntimeError("offline preparation failed")

    runtime = assemble_local_runtime(configuration(knowledge=True), tmp_path / "state",
        templates=templates(created), knowledge_bindings={"docs": LocalKnowledgeBinding(Retriever())},
        service_usage_bindings={"observations": LocalServiceUsageBinding(
            ledger, "operation", links=links, retrieval_source_ref="retrieval")})
    async with runtime:
        with pytest.raises(Exception):
            await runtime.run("question", knowledge_query="query", confirm_knowledge_query=True)
    assert len(observed) == 1
    assert await links.for_session(observed[0].session_id) == tuple(observed)
    assert created[0].calls == 0 and created[0].close_calls == 1
    records = await ledger.records("operation")
    assert len(records) == 1 and records[0].service == "retrieval"


@pytest.mark.asyncio
async def test_failed_link_prevents_history_and_model(tmp_path):
    class FailingLinks(InMemoryServiceUsageLinkStore):
        async def bind(self, link, *, confirm_write=False):
            raise ServiceUsageError("link refused")

    created, history = [], []
    runtime = assemble_local_runtime(configuration(), tmp_path, templates=templates(created),
        service_usage_bindings={"observations": LocalServiceUsageBinding(
            InMemoryServiceUsageLedger(), "operation", links=FailingLinks())})
    async def conversation(*args, **kwargs):
        history.append(True)
        raise AssertionError("history should not run")
    runtime.sessions.conversation = conversation
    async with runtime:
        with pytest.raises(ServiceUsageError):
            await runtime.run("question")
    assert created[0].calls == 0 and not history


@pytest.mark.asyncio
async def test_cancelled_sqlite_bind_drains_worker_without_model(tmp_path, monkeypatch):
    links = SQLiteServiceUsageLinkStore(tmp_path / "links.db")
    await links.initialize(confirm_create=True)
    entered, release, created = threading.Event(), threading.Event(), []
    original = SQLiteServiceUsageLinkStore._bind
    def waiting(self, link):
        original(self, link)
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(SQLiteServiceUsageLinkStore, "_bind", waiting)
    runtime = assemble_local_runtime(configuration(), tmp_path / "state", templates=templates(created),
        service_usage_bindings={"observations": LocalServiceUsageBinding(
            InMemoryServiceUsageLedger(), "operation", links=links)})
    async with runtime:
        task = asyncio.create_task(runtime.run("question"))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(await links.for_operation("operation")) == 1
    assert created[0].calls == 0 and created[0].close_calls == 1


@pytest.mark.asyncio
async def test_multiple_runs_share_operation_not_a_per_run_ledger(tmp_path):
    links = InMemoryServiceUsageLinkStore()
    binding = LocalServiceUsageBinding(InMemoryServiceUsageLedger(), "operation", links=links)
    runtime = assemble_local_runtime(configuration(), tmp_path, templates=templates([]),
        service_usage_bindings={"observations": binding})
    async with runtime:
        first = await runtime.run("first")
        second = await runtime.run("second", session_id=first.session.session_id)
        summary = await runtime.service_usage_summary()
    matches = await links.for_session(first.session.session_id)
    assert {link.run_id for link in matches} == {first.result.run_id, second.result.run_id}
    assert summary["scope"] == "host-operation-not-this-run"
    assert summary["known_usage"]["total_tokens"] == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("rejection", ["missing", "operation", "session"])
async def test_resume_rejects_link_mismatch_before_claim_tool_or_model(tmp_path, rejection):
    links = SQLiteServiceUsageLinkStore(tmp_path / "links.db")
    await links.initialize(confirm_create=True)
    ledger, writes = InMemoryServiceUsageLedger(), []
    def save_note(text: str) -> str:
        writes.append(text)
        return "saved"
    tool = python_tool(save_note, side_effect=ToolSideEffect.WRITE,
        required_permissions=frozenset({"notes.write"}))
    config = local_runtime_config_from_mapping({
        "provider": {"template": "fake", "name": "test-provider", "model": "test-model"},
        "agent": {"name": "tools", "max_tool_calls": 1, "require_usage": True},
        "tools": {"enabled": ["save_note"]}, "service_usage": {"binding": "observations"},
    })
    def runtime(provider, binding):
        return assemble_local_runtime(config, tmp_path / "state", templates=registry(provider),
            tool_bindings={"save_note": tool}, service_usage_bindings={"observations": binding})
    initial = ApprovalProvider()
    async with runtime(initial, LocalServiceUsageBinding(ledger, "operation", links=links)) as current:
        pending = await current.run("save", permissions=frozenset({"notes.write"}))
    assert pending.result.stop_reason.value == "needs-approval"
    before = await ledger.records("operation")
    reopened = SQLiteServiceUsageLinkStore(tmp_path / "links.db")
    wrong_store = InMemoryServiceUsageLinkStore() if rejection == "missing" else reopened
    rejected = ApprovalProvider(resume_phase=True)
    wrong_binding = LocalServiceUsageBinding(ledger, "other" if rejection == "operation" else "operation", links=wrong_store)
    async with runtime(rejected, wrong_binding) as current:
        with pytest.raises(ServiceUsageError):
            await current.resume("other-session" if rejection == "session" else pending.session.session_id,
                pending.result.run_id, approved_call_ids=frozenset({"save-1"}), permissions=frozenset({"notes.write"}))
    assert not writes and rejected.calls == 0
    assert await ledger.records("operation") == before
    resumed = ApprovalProvider(resume_phase=True)
    async with runtime(resumed, LocalServiceUsageBinding(ledger, "operation", links=reopened)) as current:
        outcome = await current.resume(pending.session.session_id, pending.result.run_id,
            approved_call_ids=frozenset({"save-1"}), permissions=frozenset({"notes.write"}))
    assert outcome.result.stop_reason.value == "completed"
    assert writes == ["value"] and initial.calls == resumed.calls == 1
    assert initial.close_calls == resumed.close_calls == rejected.close_calls == 1
    records = await ledger.records("operation")
    assert len(records) == 2 and records[0] == before[0]
    assert len(await reopened.for_operation("operation")) == 1
