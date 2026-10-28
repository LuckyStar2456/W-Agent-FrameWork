"""Draft Session input-recording regressions; execution awaits authorization."""

import base64
import json
from dataclasses import replace

import pytest

from w_agent import (
    AgentDefinition, AudioContent, ImageContent, InMemorySessionStore, JsonSessionStore,
    MessageRole, ModelMessage, RunResult, SessionError, SessionInputRecordingError,
    SessionManager, SessionMessage, SessionRecord, StandardSessionInputRecorder,
    StopReason, TextContent, TextSessionMessageProjector, ToolCallContent,
    ToolExecutionContext, session_input_to_dict,
)


class Loop:
    def __init__(self):
        self.calls = []

    async def run(self, definition, context):
        self.calls.append(context)
        return RunResult(context.run_id, StopReason.COMPLETED, "answer", context.messages, (), 1, 0)

    async def resume(self, run_id, **kwargs):
        return RunResult(run_id, StopReason.COMPLETED, "resumed", (), (), 1, 0)


def _input():
    return ModelMessage(MessageRole.USER, (
        TextContent("before"), ImageContent(data=b"PRIVATE_IMAGE", media_type="image/png"),
        TextContent("after"), AudioContent(url="https://example.test/PRIVATE_AUDIO"),
    ), name="PRIVATE_NAME", metadata={"PRIVATE_METADATA": True})


@pytest.mark.asyncio
async def test_default_stays_schema_one_and_does_not_record_media(tmp_path):
    manager = SessionManager(JsonSessionStore(tmp_path))
    await manager.create("title", session_id="session")
    await manager.run_agent(Loop(), AgentDefinition("agent"), "session", (_input(),), run_id="first")
    record = await manager.get("session")
    assert record.schema_version == 1
    assert record.messages[0].text == "beforeafter"
    assert record.messages[0].recorded_input is None
    raw = (tmp_path / "session.json").read_text(encoding="utf-8")
    assert "recorded_input" not in raw and "PRIVATE" not in raw


@pytest.mark.asyncio
async def test_opt_in_roundtrip_order_immutability_and_text_history(tmp_path):
    manager = SessionManager(JsonSessionStore(tmp_path))
    await manager.create("title", session_id="session")
    loop = Loop()
    await manager.run_agent(loop, AgentDefinition("agent"), "session", (_input(),),
                            run_id="first", record_inputs=True)
    record = await SessionManager(JsonSessionStore(tmp_path)).get("session")
    assert record.schema_version == 2
    payload = record.messages[0].recorded_input
    assert [block["kind"] for block in payload["blocks"]] == ["text", "image", "text", "audio"]
    assert base64.b64decode(payload["blocks"][1]["data_base64"]) == b"PRIVATE_IMAGE"
    assert payload["blocks"][3]["url"].endswith("PRIVATE_AUDIO")
    assert "PRIVATE_NAME" not in json.dumps(session_input_to_dict(payload))
    assert "PRIVATE_METADATA" not in json.dumps(session_input_to_dict(payload))
    with pytest.raises(TypeError):
        payload["blocks"][0]["text"] = "changed"
    detached = session_input_to_dict(payload)
    detached["blocks"][0]["text"] = "changed"
    assert payload["blocks"][0]["text"] == "before"
    await manager.run_agent(loop, AgentDefinition("agent"), "session",
                            (ModelMessage.text(MessageRole.USER, "next"),), run_id="second")
    assert [msg.content[0].text for msg in loop.calls[1].messages] == ["beforeafter", "answer", "next"]
    assert (await manager.get("session")).schema_version == 2


@pytest.mark.asyncio
async def test_media_only_input_retained_but_not_in_text_context_or_duplicate_on_resume(tmp_path):
    manager = SessionManager(JsonSessionStore(tmp_path))
    await manager.create("title", session_id="session")
    message = ModelMessage(MessageRole.USER, (AudioContent(data=b"audio", media_type="audio/wav"),))
    loop = Loop()
    await manager.run_agent(loop, AgentDefinition("agent"), "session", (message,), run_id="first", record_inputs=True)
    before = await manager.get("session")
    assert before.messages[0].text == "" and before.messages[0].recorded_input is not None
    assert len(await manager.conversation("session")) == 1  # Assistant answer only.
    await manager.resume_agent(loop, "session", "first", tool_context=ToolExecutionContext())
    after = await manager.get("session")
    assert sum(msg.recorded_input is not None for msg in after.messages) == 1
    assert after.messages[0] == before.messages[0]
    archived = await manager.archive("session")
    assert archived.schema_version == 2 and archived.messages == after.messages


@pytest.mark.asyncio
async def test_unknown_block_rejects_before_agent_and_store_update():
    manager = SessionManager()
    before = await manager.create("title", session_id="session")
    loop = Loop()
    with pytest.raises(SessionInputRecordingError, match="Agent not started"):
        await manager.run_agent(loop, AgentDefinition("agent"), "session",
            (ModelMessage(MessageRole.ASSISTANT, (ToolCallContent("id", "PRIVATE", "{}"),)),), record_inputs=True)
    assert loop.calls == [] and await manager.get("session") == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["raise", "nan", "cycle", "non-string-key", "missing-codec"])
async def test_custom_recorder_failures_are_sanitized(mode):
    class Recorder:
        def record(self, message):
            if mode == "raise":
                raise RuntimeError("PRIVATE")
            if mode == "nan":
                return {"codec": "custom/1", "value": float("nan")}
            if mode == "non-string-key":
                return {"codec": "custom/1", 1: "PRIVATE"}
            if mode == "missing-codec":
                return {"payload": "PRIVATE"}
            value = {"codec": "custom/1"}
            value["cycle"] = value
            return value
    manager = SessionManager(input_recorder=Recorder())
    await manager.create("title", session_id="session")
    loop = Loop()
    with pytest.raises(SessionInputRecordingError) as error:
        await manager.run_agent(loop, AgentDefinition("agent"), "session", (_input(),), record_inputs=True)
    assert "PRIVATE" not in str(error.value) and not loop.calls


@pytest.mark.asyncio
async def test_custom_codec_is_frozen_before_execution_and_never_auto_loaded():
    payload = {"codec": "custom.blob/1", "ref": {"key": "first"}}
    class Recorder:
        def record(self, message):
            return payload
    class MutatingLoop(Loop):
        async def run(self, definition, context):
            payload["ref"]["key"] = "changed"
            return await super().run(definition, context)
    manager = SessionManager(input_recorder=Recorder())
    await manager.create("title", session_id="session")
    await manager.run_agent(MutatingLoop(), AgentDefinition("agent"), "session", (_input(),), record_inputs=True)
    assert (await manager.get("session")).messages[0].recorded_input["ref"]["key"] == "first"


@pytest.mark.asyncio
async def test_omitting_recorder_retains_legacy_text_and_schema():
    class Omit:
        def record(self, message):
            return None
    manager = SessionManager(input_recorder=Omit())
    await manager.create("title", session_id="session")
    await manager.run_agent(Loop(), AgentDefinition("agent"), "session", (_input(),), record_inputs=True)
    stored = await manager.get("session")
    assert stored.schema_version == 1 and stored.messages[0].text == "beforeafter"


@pytest.mark.asyncio
async def test_limits_fail_before_model_call():
    for manager in (
        SessionManager(max_recorded_batch_bytes=10),
        SessionManager(input_recorder=StandardSessionInputRecorder(max_inline_bytes=1)),
        SessionManager(input_recorder=StandardSessionInputRecorder(max_blocks=1)),
        SessionManager(input_recorder=StandardSessionInputRecorder(max_text_chars=1)),
    ):
        await manager.create("title", session_id="session")
        loop = Loop()
        with pytest.raises(SessionInputRecordingError):
            await manager.run_agent(loop, AgentDefinition("agent"), "session", (_input(),), record_inputs=True)
        assert loop.calls == []


@pytest.mark.asyncio
async def test_schema_one_cannot_smuggle_recorded_input_and_newer_schema_rejected(tmp_path):
    manager = SessionManager(JsonSessionStore(tmp_path))
    await manager.create("title", session_id="session")
    await manager.run_agent(Loop(), AgentDefinition("agent"), "session", (_input(),), record_inputs=True)
    path = tmp_path / "session.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for schema in (1, 3, True, "2"):
        path.write_text(json.dumps({**raw, "schema_version": schema}), encoding="utf-8")
        with pytest.raises(SessionError):
            await manager.get("session")


def test_manual_rich_record_requires_schema_two_and_valid_codec():
    message = SessionMessage(MessageRole.USER, "", "run", recorded_input={"codec": "custom/1", "blob": "reference"})
    with pytest.raises(ValueError, match="schema version 2"):
        SessionRecord("session", "title", messages=(message,))
    assert SessionRecord("session", "title", messages=(message,), schema_version=2).messages[0] == message
    with pytest.raises(SessionInputRecordingError):
        replace(message, recorded_input={"codec": ""})


def test_existing_session_projection_does_not_disclose_input_media():
    message = SessionMessage(MessageRole.USER, "text", "run",
                             recorded_input=StandardSessionInputRecorder().record(_input()))
    for include_text in (False, True):
        projected = TextSessionMessageProjector(include_text=include_text).project(message)
        assert "recorded_input" not in projected
        assert "PRIVATE" not in json.dumps(projected)


@pytest.mark.asyncio
async def test_streamed_execution_uses_same_prepared_input_record():
    class Execution:
        def __init__(self, context):
            self.result = RunResult(context.run_id, StopReason.COMPLETED, "streamed", context.messages, (), 1, 0)

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class StreamLoop:
        def stream(self, definition, context):
            return Execution(context)

    manager = SessionManager()
    await manager.create("title", session_id="session")
    await manager.run_agent(StreamLoop(), AgentDefinition("agent"), "session", (_input(),),
                            record_inputs=True, event_callback=lambda event: None)
    record = await manager.get("session")
    assert record.schema_version == 2
    assert record.messages[0].recorded_input is not None
    assert record.messages[-1].text == "streamed"


@pytest.mark.asyncio
async def test_store_failure_after_execution_does_not_retry_agent():
    class FailingStore(InMemorySessionStore):
        async def save(self, session):
            if session.runs:
                raise SessionError("write failed")
            await super().save(session)
    manager = SessionManager(FailingStore())
    await manager.create("title", session_id="session")
    loop = Loop()
    with pytest.raises(SessionError):
        await manager.run_agent(loop, AgentDefinition("agent"), "session", (_input(),), record_inputs=True)
    assert len(loop.calls) == 1 and not (await manager.get("session")).runs
