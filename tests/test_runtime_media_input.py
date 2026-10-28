"""Draft Runtime and CLI media entry tests; no live Provider calls."""

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli
from w_agent import (
    AgentDefinition, ImageContent, LocalAgentRuntime, MessageRole, ModelMessage,
    RecordedSessionHistoryPolicy, RunResult, SessionManager, StopReason, TextContent,
)


class Loop:
    def __init__(self):
        self.contexts = []

    async def run(self, definition, context):
        self.contexts.append(context)
        return RunResult(context.run_id, StopReason.COMPLETED, "answer", context.messages, (), 1, 0)


def _runtime():
    return LocalAgentRuntime(SimpleNamespace(), AgentDefinition("agent"), Loop(),
                             SessionManager(), SimpleNamespace(providers=lambda: ()), SimpleNamespace())


@pytest.mark.asyncio
async def test_runtime_typed_input_recording_history_and_permissions():
    runtime = _runtime()
    message = ModelMessage(MessageRole.USER, (TextContent("question"), ImageContent(url="https://example.test/image")))
    first = await runtime.run_messages((message,), record_inputs=True, permissions=frozenset({"read"}))
    assert first.session.schema_version == 2 and first.session.title == "Agent run"
    assert runtime.loop.contexts[0].messages == (message,)
    assert runtime.loop.contexts[0].tool_context.permissions == frozenset({"read"})
    await runtime.run("second", session_id=first.session.session_id, history_policy=RecordedSessionHistoryPolicy())
    assert runtime.loop.contexts[1].messages[0] == message
    await runtime.run("third", session_id=first.session.session_id, include_history=False)
    assert len(runtime.loop.contexts[2].messages) == 1
    await runtime.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await runtime.run_messages((message,))


@pytest.mark.asyncio
async def test_runtime_default_text_title_and_validation_before_session_creation():
    runtime = _runtime()
    for messages, options in [((), {}), (("bad",), {}), ((ModelMessage.text(MessageRole.USER, "x"),), {"record_inputs": 1})]:
        with pytest.raises(ValueError):
            await runtime.run_messages(messages, **options)
    assert await runtime.sessions.list() == ()
    run = await runtime.run("Old prompt title")
    assert run.session.title == "Old prompt title" and run.session.schema_version == 1


@pytest.mark.parametrize("args,expected", [
    (["--input-file", "missing.json"], "confirm-model-call"),
    (["text", "--confirm-model-call", "--record-inputs"], "confirm-input-recording"),
    (["text", "--confirm-model-call", "--history", "recorded"], "confirm-history-media"),
    (["text", "--confirm-model-call", "--history", "bad"], "--history"),
    (["text", "--input-file", "missing.json", "--confirm-model-call"], "exactly one"),
    (["--confirm-model-call"], "exactly one"),
])
def test_cli_rejects_before_file_reads_imports_or_assembly(monkeypatch, args, expected):
    def forbidden(*args, **kwargs):
        pytest.fail("operation before authorization/argument checks")
    for name in ("load_input_manifest", "load_tool_entries", "load_local_runtime_config", "open_local_runtime"):
        monkeypatch.setattr(cli, name, forbidden)
    result = CliRunner().invoke(cli.app, ["run", *args])
    assert result.exit_code == 2 and expected in result.output


def test_cli_manifest_options_are_forwarded_and_runtime_closed(tmp_path, monkeypatch):
    path = tmp_path / "input.json"
    path.write_text(json.dumps({"schema_version": 1, "messages": [{"role": "user", "content": [
        {"type": "image", "url": "https://example.test/PRIVATE_INPUT"}]}]}), encoding="utf-8")
    captured = {}
    class Runtime:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            captured["closed"] = True

        async def run_messages(self, messages, **kwargs):
            captured.update(kwargs)
            captured["messages"] = messages
            return SimpleNamespace(session=SimpleNamespace(session_id="session"),
                result=RunResult("run", StopReason.COMPLETED, "answer", messages, (), 1, 0))
    monkeypatch.setattr(cli, "load_local_runtime_config", lambda path: object())
    monkeypatch.setattr(cli, "open_local_runtime", lambda *args, **kwargs: Runtime())
    result = CliRunner().invoke(cli.app, ["run", "--input-file", str(path), "--confirm-model-call",
        "--record-inputs", "--confirm-input-recording", "--history", "recorded", "--confirm-history-media", "--json"])
    assert result.exit_code == 0, result.output
    assert captured["record_inputs"] is True and isinstance(captured["history_policy"], RecordedSessionHistoryPolicy)
    assert isinstance(captured["messages"][0].content[0], ImageContent)
    assert captured["closed"] is True and "PRIVATE_INPUT" not in result.stdout


def test_malformed_manifest_prevents_tool_imports(tmp_path, monkeypatch):
    path = tmp_path / "input.json"
    path.write_text("PRIVATE_BROKEN", encoding="utf-8")
    monkeypatch.setattr(cli, "load_tool_entries", lambda *args: pytest.fail("tools loaded before parsing input"))
    result = CliRunner().invoke(cli.app, ["run", "--input-file", str(path), "--confirm-model-call",
        "--tool-entry", "example:tool", "--confirm-tool-code"])
    assert result.exit_code == 2 and "PRIVATE_BROKEN" not in result.output
