"""Draft CLI knowledge authorization/lifecycle regressions; unexecuted."""

import asyncio
import sys
import types
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli
from w_agent import InMemoryKnowledgeDocumentStore, KnowledgeDocument, KeywordKnowledgeRetriever, LocalKnowledgeBinding
from w_agent._knowledge_ui import KnowledgeEntryError, KnowledgeRunOptions, knowledge_binding_scope


def binding():
    return LocalKnowledgeBinding(KeywordKnowledgeRetriever(InMemoryKnowledgeDocumentStore((KnowledgeDocument("id", "body"),))))


def install(monkeypatch, factory):
    module = types.ModuleType("knowledge_test_host")
    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return "knowledge_test_host:factory"


@pytest.mark.parametrize("code,query", [(False, True), (True, False), (1, True), (True, 1)])
def test_two_distinct_literal_consents_are_required(code, query):
    with pytest.raises(KnowledgeEntryError):
        KnowledgeRunOptions("host:factory", "query", code, query)


@pytest.mark.asyncio
async def test_selection_precedes_import_and_setup(monkeypatch):
    calls = []
    entry = install(monkeypatch, lambda: calls.append(True))
    with pytest.raises(KnowledgeEntryError):
        async with knowledge_binding_scope(KnowledgeRunOptions(entry, "query", True, True), selected=None):
            pytest.fail("missing selection was accepted")
    assert not calls


@pytest.mark.asyncio
async def test_cleanup_cannot_suppress_runtime_exception(monkeypatch):
    events = []

    class Context:
        async def __aenter__(self):
            events.append("enter")
            return {"manual": binding()}

        async def __aexit__(self, kind, error, traceback):
            events.append(kind)
            return True

    entry = install(monkeypatch, Context)
    with pytest.raises(RuntimeError, match="original"):
        async with knowledge_binding_scope(KnowledgeRunOptions(entry, "query", True, True), selected="manual"):
            raise RuntimeError("original")
    assert events == ["enter", RuntimeError]


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog", [{}, {"manual": object()}, {"bad key": None}, []])
async def test_invalid_catalog_is_closed_before_rejection(monkeypatch, catalog):
    events = []

    @asynccontextmanager
    async def factory():
        try:
            yield catalog
        finally:
            events.append("closed")

    entry = install(monkeypatch, factory)
    with pytest.raises(KnowledgeEntryError):
        async with knowledge_binding_scope(KnowledgeRunOptions(entry, "query", True, True), selected="manual"):
            pytest.fail("invalid catalog reached runtime")
    assert events == ["closed"]


@pytest.mark.parametrize("flags", [[], ["--confirm-knowledge-code"], ["--confirm-knowledge-query"]])
def test_cli_denied_consent_precedes_input_and_tool_loaders(monkeypatch, flags):
    for name in ("load_input_manifest", "load_tool_entries", "load_local_runtime_config"):
        monkeypatch.setattr(cli, name, lambda *args, **kwargs: pytest.fail("denied run invoked loader"))
    result = CliRunner().invoke(cli.app, ["run", "--input-file", "absent.json", "--confirm-model-call",
        "--knowledge-entry", "host:factory", "--knowledge-query", "PRIVATE_QUERY", *flags])
    assert result.exit_code != 0 and "PRIVATE_QUERY" not in result.output


def test_cli_loads_selected_binding_and_forwards_query_once(monkeypatch):
    events, captured = [], {}
    selected = binding()

    @asynccontextmanager
    async def factory():
        events.append("enter")
        try:
            yield {"manual": selected}
        finally:
            events.append("exit")

    entry = install(monkeypatch, factory)
    monkeypatch.setattr(cli, "load_local_runtime_config", lambda path: SimpleNamespace(knowledge=SimpleNamespace(binding="manual")))

    class Runtime:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            events.append("runtime-close")

        async def run(self, prompt, **options):
            captured.update(options)
            events.append("run")
            return object()

    def assemble(config, root, **options):
        assert options["knowledge_bindings"]["manual"] is selected
        return Runtime()

    monkeypatch.setattr(cli, "open_local_runtime", assemble)
    monkeypatch.setattr(cli, "_local_run_payload", lambda run: {"status": "done"})
    result = CliRunner().invoke(cli.app, ["run", "question", "--confirm-model-call", "--history", "none",
        "--knowledge-entry", entry, "--knowledge-query", "EXPLICIT_QUERY", "--confirm-knowledge-code", "--confirm-knowledge-query", "--json"])
    assert result.exit_code == 0, result.output
    assert captured["knowledge_query"] == "EXPLICIT_QUERY" and captured["confirm_knowledge_query"] is True
    assert captured["include_history"] is False
    assert events == ["enter", "run", "runtime-close", "exit"]


@pytest.mark.asyncio
async def test_cancelled_runtime_still_exits_entered_knowledge_host(monkeypatch):
    events, started = [], asyncio.Event()

    @asynccontextmanager
    async def factory():
        try:
            yield {"manual": binding()}
        finally:
            events.append("closed")

    entry = install(monkeypatch, factory)

    async def run():
        async with knowledge_binding_scope(KnowledgeRunOptions(entry, "query", True, True), selected="manual"):
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["closed"]
