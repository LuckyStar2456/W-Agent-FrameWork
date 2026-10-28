"""Offline end-to-end knowledge evaluation entry points and consent boundaries."""

import asyncio
import json
import sys
import types
from contextlib import asynccontextmanager

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli
from w_agent import (
    BlockEnd, BlockStart, EvaluationCase, EvaluationDataset, FinishEvent,
    FinishReason, KnowledgeDocument, LocalKnowledgeBinding, MessageRole,
    ModelCapability, ModelDescriptor, ProviderTemplate, ProviderTemplateRegistry,
    TextContent, TokenUsage, UsageEvent, assemble_local_runtime,
    local_runtime_config_from_mapping,
)
from w_agent._knowledge_ui import KnowledgeEntryError, KnowledgeEvaluationOptions


ENTRY = "knowledge_evaluation_test_host:factory"
FLAGS = ["--knowledge-entry", ENTRY, "--confirm-knowledge-code", "--confirm-knowledge-queries"]


def prepare(monkeypatch, *, prompts=("refund", "coding"), retrieval_failure=False):
    events, queries, requests, runtimes = [], [], [], []

    class Retriever:
        async def retrieve(self, query, *, limit):
            queries.append(query)
            if retrieval_failure:
                raise ValueError("PRIVATE_BACKEND_ERROR")
            return (KnowledgeDocument(query, f"evidence for {query}"),)

    @asynccontextmanager
    async def factory():
        events.append("knowledge-open")
        try:
            yield {"manual": LocalKnowledgeBinding(Retriever())}
        finally:
            events.append("knowledge-close")

    module = types.ModuleType("knowledge_evaluation_test_host")
    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)

    class Provider:
        async def resolve(self, model):
            return ModelDescriptor("offline", "offline", frozenset({ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT}))

        async def list_models(self):
            return (await self.resolve("offline"),)

        async def stream(self, request, *, cancellation=None):
            requests.append(request)
            yield BlockStart(0, "text")
            yield BlockEnd(0, TextContent("answer"))
            yield UsageEvent(TokenUsage(3, 2))
            yield FinishEvent(FinishReason.STOP)

        async def aclose(self):
            events.append("provider-close")

    config = local_runtime_config_from_mapping({
        "provider": {"template": "offline", "name": "offline", "model": "offline"},
        "knowledge": {"binding": "manual"},
    })
    templates = ProviderTemplateRegistry((ProviderTemplate("offline", "Offline", "test", None, lambda **kw: Provider()),))

    def assemble(config, root, **kwargs):
        runtime = assemble_local_runtime(config, root, templates=templates, **kwargs)
        runtimes.append(runtime)
        return runtime

    dataset = EvaluationDataset(tuple(EvaluationCase(str(i), prompt, "answer", metadata={"knowledge_query": "ignored", "permissions": ["all"]})
                                      for i, prompt in enumerate(prompts)))
    monkeypatch.setattr(cli, "load_local_runtime_config", lambda path: config)
    monkeypatch.setattr(cli, "open_local_runtime", assemble)
    monkeypatch.setattr(cli, "load_evaluation_dataset", lambda path: dataset)
    return events, queries, requests, runtimes


def test_cli_retrieves_each_case_with_isolated_messages_and_cleanup(monkeypatch, tmp_path):
    events, queries, requests, _ = prepare(monkeypatch)
    report_path = tmp_path / "report.json"
    result = CliRunner().invoke(cli.app, ["evaluate", "unused.json", "--confirm-model-call", "--json", "--report", str(report_path), "--state-root", str(tmp_path), *FLAGS])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["passed"] == 2 and report["usage"]["total_tokens"] == 10
    assert "retrieval-not-included" in report["knowledge"]["accounting_scope"]
    assert json.loads(report_path.read_text())["accounting_scope"] == report["accounting_scope"]
    assert queries == ["refund", "coding"] and len(requests) == 2
    for query, request in zip(queries, requests):
        users = [message for message in request.messages if message.role == MessageRole.USER]
        assert len(users) == 2
        assert query in users[0].content[0].text and users[1].content[0].text == query
        assert not any(message.role == MessageRole.ASSISTANT for message in request.messages)
    assert events == ["knowledge-open", "provider-close", "knowledge-close"]
    assert "evidence for" not in result.output


@pytest.mark.parametrize("flags", [[], ["--confirm-knowledge-code"], ["--confirm-knowledge-queries"]])
def test_cli_unauthorized_knowledge_precedes_dataset_and_code(monkeypatch, flags):
    monkeypatch.setattr(cli, "load_evaluation_dataset", lambda path: pytest.fail("read before consent"))
    result = CliRunner().invoke(cli.app, ["evaluate", "unused", "--confirm-model-call", "--knowledge-entry", ENTRY, *flags])
    assert result.exit_code == 2


def test_all_case_queries_preflight_before_any_host_or_tool_code(monkeypatch):
    events, queries, requests, _ = prepare(monkeypatch, prompts=("valid", "x" * 4097))
    monkeypatch.setattr(cli, "load_tool_entries", lambda entries: pytest.fail("tool loaded before dataset preflight"))
    result = CliRunner().invoke(cli.app, ["evaluate", "unused", "--confirm-model-call", "--tool-entry", "host:tool", "--confirm-tool-code", *FLAGS])
    assert result.exit_code == 2 and not events and not queries and not requests


def test_retrieval_error_is_not_silent_model_only_fallback(monkeypatch):
    events, queries, requests, _ = prepare(monkeypatch, retrieval_failure=True)
    result = CliRunner().invoke(cli.app, ["evaluate", "unused", "--confirm-model-call", "--json", *FLAGS])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["errors"] == 2
    assert queries == ["refund", "coding"] and not requests
    assert events == ["knowledge-open", "provider-close", "knowledge-close"]
    assert "PRIVATE_BACKEND_ERROR" not in result.output


@pytest.mark.parametrize("code,queries", [(True, 1), (1, True), (False, True)])
def test_options_require_literal_distinct_consents(code, queries):
    with pytest.raises(KnowledgeEntryError):
        KnowledgeEvaluationOptions(ENTRY, code, queries)


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, True])
async def test_tui_case_queries_and_one_shot_confirmations(tmp_path, monkeypatch, authorized):
    pytest.importorskip("textual")
    import w_agent.tui as tui

    events, queries, requests, _ = prepare(monkeypatch)
    for name in ("load_local_runtime_config", "open_local_runtime", "load_evaluation_dataset"):
        monkeypatch.setattr(tui, name, getattr(cli, name))

    class App(tui.WAgentTui):
        async def on_mount(self):
            pass

    app = App(tmp_path)
    async with app.run_test(size=(110, 50)):
        app.query_one("#evaluation-knowledge-entry").value = ENTRY
        app.query_one("#evaluation-knowledge-code").value = "LOAD KNOWLEDGE"
        app.query_one("#evaluation-knowledge-queries").value = "QUERY ALL CASES" if authorized else "wrong"
        app.query_one("#evaluation-confirm").value = "EVALUATE"
        app.query_one("#evaluation-report").value = ""
        await app._run_evaluation()
        result = str(app.query_one("#evaluation-result").content)
        assert not app._evaluation_busy
        assert app.query_one("#evaluation-knowledge-code").value == ""
        assert app.query_one("#evaluation-knowledge-queries").value == ""
        if authorized:
            assert queries == ["refund", "coding"] and len(requests) == 2
            assert "Passed: 2/2" in result and "retrieval usage/cost not included" in result
            assert events[-1] == "knowledge-close"
        else:
            assert "QUERY ALL CASES" in result and not events and not requests


@pytest.mark.asyncio
async def test_tui_evaluation_busy_resets_on_cancellation(tmp_path, monkeypatch):
    pytest.importorskip("textual")
    from w_agent.tui import WAgentTui
    app = WAgentTui(tmp_path)

    async def cancel():
        assert app._evaluation_busy
        raise asyncio.CancelledError

    monkeypatch.setattr(app, "_execute_evaluation", cancel)
    with pytest.raises(asyncio.CancelledError):
        await app._run_evaluation()
    assert not app._evaluation_busy
