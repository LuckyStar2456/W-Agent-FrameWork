"""Draft field-input and per-call recording regressions."""

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli
from w_agent import (
    AgentDefinition, BuiltinSessionHistoryOptions, InputManifestError,
    InputManifestLimits, LocalAgentRuntime, MessageFieldsSessionInputRecorder,
    RunResult, SessionManager, StopReason, input_manifest_from_mapping,
)


def manifest(**fields):
    return {"schema_version": 1, "messages": [{
        "role": "user", "content": [{"type": "text", "text": "question"}], **fields,
    }]}


def test_manifest_requires_explicit_opt_in_and_detaches_fields():
    data = manifest(name="PRIVATE_NAME", metadata={"tags": ["original"]})
    with pytest.raises(InputManifestError):
        input_manifest_from_mapping(data)
    message = input_manifest_from_mapping(data, allow_message_fields=True)[0]
    data["messages"][0]["metadata"]["tags"].append("changed")
    assert message.name == "PRIVATE_NAME"
    assert message.metadata == {"tags": ["original"]}


@pytest.mark.parametrize("fields", [
    {"name": ""}, {"name": None}, {"name": "x" * 257},
    {"metadata": []}, {"metadata": {"x": float("nan")}},
    {"metadata": {"x": object()}}, {"permissions": ["execute"]}, {"role": "system"},
])
def test_invalid_fields_are_rejected_without_content(fields):
    with pytest.raises(InputManifestError) as error:
        input_manifest_from_mapping(manifest(**fields), allow_message_fields=True)
    assert str(error.value) == "invalid input manifest; check schema, content types and size limits"


@pytest.mark.parametrize("limits", [
    InputManifestLimits(max_message_field_bytes=8),
    InputManifestLimits(max_content_bytes=8),
])
def test_field_bytes_are_bounded(limits):
    with pytest.raises(InputManifestError):
        input_manifest_from_mapping(manifest(name="名字"), allow_message_fields=True, limits=limits)


class Loop:
    def __init__(self):
        self.contexts = []

    async def run(self, definition, context):
        self.contexts.append(context)
        return RunResult(context.run_id, StopReason.COMPLETED, "answer", context.messages, (), 1, 0)


def runtime():
    return LocalAgentRuntime(SimpleNamespace(), AgentDefinition("agent"), Loop(),
                             SessionManager(), SimpleNamespace(providers=lambda: ()), SimpleNamespace())


@pytest.mark.asyncio
async def test_per_call_recorder_does_not_change_manager_default_or_authorize_history():
    host = runtime()
    default = host.sessions.input_recorder
    messages = input_manifest_from_mapping(manifest(name="PRIVATE_NAME", metadata={"tag": "private"}),
                                           allow_message_fields=True)
    first = await host.run_messages(messages, record_inputs=True,
        input_recorder=MessageFieldsSessionInputRecorder(include_name=True, include_metadata=True))
    assert host.loop.contexts[0].messages == messages
    assert host.sessions.input_recorder is default
    second = await host.run_messages(messages, session_id=first.session.session_id, record_inputs=True,
                                    **BuiltinSessionHistoryOptions("recorded").runtime_options())
    assert host.loop.contexts[1].messages[0].name is None
    assert not host.loop.contexts[1].messages[0].metadata
    inputs = [item for item in second.session.messages if item.recorded_input is not None]
    assert "fields" in inputs[0].recorded_input and "fields" not in inputs[1].recorded_input
    selected = BuiltinSessionHistoryOptions("recorded", include_name=True).runtime_options()["history_policy"]
    history = selected.project(second.session)
    assert history[0].name == "PRIVATE_NAME" and not history[0].metadata
    assert host.sessions.input_recorder is default
    await host.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("record,recorder", [(False, MessageFieldsSessionInputRecorder()), (True, object())])
async def test_invalid_per_call_recorder_precedes_session_creation(record, recorder):
    host = runtime()
    with pytest.raises(ValueError, match="per-call recorder"):
        await host.run("question", record_inputs=record, input_recorder=recorder)
    assert await host.sessions.list() == () and host.loop.contexts == []


@pytest.mark.parametrize("mode", ["text", "none", "retrieved", "summarized"])
def test_history_fields_require_recorded_mode(mode):
    with pytest.raises(ValueError, match="recorded mode"):
        BuiltinSessionHistoryOptions(mode, include_name=True)


@pytest.mark.parametrize("options", [
    ["--record-input-name"], ["--history-name"],
    ["--history", "recorded", "--history-metadata"],
    ["--record-inputs", "--input-message-fields", "--record-input-metadata"],
])
def test_cli_invalid_field_selection_precedes_loading(monkeypatch, options):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid field selection reached loader")
    for name in ("load_input_manifest", "load_tool_entries", "load_local_runtime_config", "open_local_runtime"):
        monkeypatch.setattr(cli, name, forbidden)
    result = CliRunner().invoke(cli.app, ["run", "--input-file", "unread.json", "--confirm-model-call", *options])
    assert result.exit_code == 2


def test_cli_separately_forwards_current_recorded_and_historical_fields(tmp_path, monkeypatch):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(manifest(name="PRIVATE_NAME", metadata={"tag": "PRIVATE_METADATA"})), encoding="utf-8")
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
        "--input-message-fields", "--record-inputs", "--confirm-input-recording", "--record-input-name",
        "--history", "recorded", "--confirm-history-media", "--history-metadata", "--json"])
    assert result.exit_code == 0, result.output
    assert captured["messages"][0].name == "PRIVATE_NAME"
    assert captured["input_recorder"].include_name and not captured["input_recorder"].include_metadata
    decoder = captured["history_policy"].fields_decoder
    assert decoder.include_metadata and not decoder.include_name
    assert captured["closed"] and captured["record_inputs"]
    assert "PRIVATE_NAME" not in result.output and "PRIVATE_METADATA" not in result.output
