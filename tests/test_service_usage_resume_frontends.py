"""Real persisted approval resumes through CLI/TUI, with offline usage hosts."""

import asyncio
import json
import sys
import types
from contextlib import asynccontextmanager

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli
from w_agent import (
    BlockEnd, BlockStart, FinishEvent, FinishReason, ProviderTemplate,
    ProviderTemplateRegistry, TextContent, TokenUsage, ToolCallContent,
    ToolSideEffect, UsageEvent, assemble_local_runtime, local_runtime_config_from_mapping,
    python_tool,
)
from w_agent.service_usage import InMemoryServiceUsageLedger
from w_agent.service_usage_runtime import LocalServiceUsageBinding
from tests.test_local_runtime import ToolCallingProvider


ENTRY = "_service_usage_resume_host:factory"
TOOL_ENTRY = "_service_usage_resume_host:tools"


class ApprovalProvider(ToolCallingProvider):
    def __init__(self, *, resume_phase=False):
        super().__init__()
        self.resume_phase = resume_phase

    async def stream(self, request, *, cancellation=None):
        assert not self.closed
        self.calls += 1
        if self.resume_phase:
            # The persisted tool result, not a replayed initial prompt-only call.
            assert any(message.role.value == "tool" for message in request.messages)
            block, usage, finish = TextContent("saved"), TokenUsage(3, 1), FinishReason.STOP
        else:
            block = ToolCallContent("save-1", "save_note", '{"text":"value"}')
            usage, finish = TokenUsage(4, 1), FinishReason.TOOL_CALLS
        yield BlockStart(0, block.type)
        yield BlockEnd(0, block)
        yield UsageEvent(usage)
        yield FinishEvent(finish)


def registry(provider):
    return ProviderTemplateRegistry((ProviderTemplate("fake", "Fake", "test", None, lambda **_: provider),))


async def seed_pending(tmp_path, monkeypatch):
    ledger, writes, lifecycle, tool_loads, resumed_providers = InMemoryServiceUsageLedger(), [], [], [], []
    usage = LocalServiceUsageBinding(ledger, "same-host-operation")

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
    initial_provider = ApprovalProvider()
    runtime = assemble_local_runtime(config, tmp_path / ".wagent", templates=registry(initial_provider),
        tool_bindings={"save_note": tool}, service_usage_bindings={"observations": usage})
    async with runtime:
        pending = await runtime.run("save", permissions=frozenset({"notes.write"}))
    assert pending.result.stop_reason.value == "needs-approval"
    assert not writes and initial_provider.calls == initial_provider.close_calls == 1
    initial_records = await ledger.records(usage.operation_id)
    assert len(initial_records) == 1 and initial_records[0].usage == TokenUsage(4, 1)

    @asynccontextmanager
    async def factory():
        lifecycle.append("open")
        try:
            yield {"observations": usage}
        finally:
            lifecycle.append("close")

    def load_tools():
        tool_loads.append(True)
        return (tool,)

    module = types.ModuleType("_service_usage_resume_host")
    module.factory, module.tools = factory, load_tools
    monkeypatch.setitem(sys.modules, module.__name__, module)

    def build_runtime(config, state_root, **kwargs):
        provider = ApprovalProvider(resume_phase=True)
        resumed_providers.append(provider)
        return assemble_local_runtime(config, state_root, templates=registry(provider), **kwargs)

    return {
        "ledger": ledger, "writes": writes, "lifecycle": lifecycle, "tool_loads": tool_loads,
        "providers": resumed_providers, "config": config, "build": build_runtime,
        "pending": pending, "initial_record": initial_records[0], "initial_provider": initial_provider,
    }


async def assert_exact_resume(state):
    records = await state["ledger"].records("same-host-operation")
    assert len(records) == 2
    assert records[0] == state["initial_record"]  # Neither rewritten nor added a second time.
    assert records[1].usage == TokenUsage(3, 1)
    assert records[1].record_id != records[0].record_id
    assert all(record.status == "completed" and record.granularity == "attempt" for record in records)
    assert sum(record.usage.total_tokens for record in records) == 9
    assert state["writes"] == ["value"]
    assert state["lifecycle"] == ["open", "close"]
    assert state["tool_loads"] == [True]
    assert len(state["providers"]) == 1
    assert state["providers"][0].calls == state["providers"][0].close_calls == 1
    assert state["initial_provider"].calls == state["initial_provider"].close_calls == 1


def test_cli_resume_observes_only_new_attempt_and_closes_factory_once(tmp_path, monkeypatch):
    state = asyncio.run(seed_pending(tmp_path, monkeypatch))
    monkeypatch.setattr(cli, "load_local_runtime_config", lambda _: state["config"])
    monkeypatch.setattr(cli, "open_local_runtime", state["build"])
    pending = state["pending"]
    response = CliRunner().invoke(cli.app, [
        "run-resume", pending.session.session_id, pending.result.run_id,
        "--state-root", str(tmp_path / ".wagent"), "--approve-tool-call", "save-1",
        "--confirm-model-call", "--tool-entry", TOOL_ENTRY, "--confirm-tool-code",
        "--grant-permission", "notes.write", "--usage-entry", ENTRY,
        "--confirm-usage-code", "--confirm-usage-recording", "--json",
    ])
    assert response.exit_code == 0, response.output
    result = json.loads(response.output)
    assert result["stop_reason"] == "completed" and result["usage"]["total_tokens"] == 9
    assert result["run_id"] == pending.result.run_id
    assert result["service_usage"]["records"] == 2
    assert result["service_usage"]["known_usage"]["total_tokens"] == 9
    assert result["service_usage"]["scope"] == "host-operation-not-this-run"
    asyncio.run(assert_exact_resume(state))


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [False, True])
async def test_tui_resume_consumes_both_consents_before_import_and_counts_only_resume(tmp_path, monkeypatch, authorized):
    pytest.importorskip("textual")
    import w_agent.tui as tui

    state = await seed_pending(tmp_path, monkeypatch)
    monkeypatch.setattr(tui, "load_local_runtime_config", lambda _: state["config"])
    monkeypatch.setattr(tui, "open_local_runtime", state["build"])

    class App(tui.WAgentTui):
        async def on_mount(self):
            pass

    app = App(tmp_path)
    async with app.run_test(size=(120, 60)):
        pending = state["pending"]
        values = {
            "session": pending.session.session_id, "run": pending.result.run_id, "call": "save-1",
            "tool-entries": TOOL_ENTRY, "permissions": "notes.write", "tool-confirm": "LOAD TOOLS",
            "confirm": "RESUME", "usage-entry": ENTRY, "usage-code": "LOAD USAGE",
            "usage-record": "RECORD USAGE" if authorized else "",
        }
        for suffix, value in values.items():
            app.query_one(f"#checkpoint-{suffix}").value = value
        await app._resume_configured_agent()
        assert app.query_one("#checkpoint-usage-code").value == ""
        assert app.query_one("#checkpoint-usage-record").value == ""
        if not authorized:
            assert not state["lifecycle"] and not state["providers"] and not state["tool_loads"]
            assert not state["writes"]
            assert await state["ledger"].records("same-host-operation") == (state["initial_record"],)
            assert "RECORD USAGE" in str(app.query_one("#checkpoint-resume-result").content)
            return
        assert "Stop: completed" in str(app.query_one("#checkpoint-resume-result").content)
        summary = str(app.query_one("#checkpoint-usage-result").content)
        assert "host-operation-not-this-run" in summary and '"total_tokens": 9' in summary
        assert "run-resumed" in str(app.query_one("#checkpoint-events").content)
        await assert_exact_resume(state)
