"""Draft context/disclosure coverage; running it requires user authorization."""

import json
from dataclasses import replace

import pytest

from w_agent import (
    AgentDefinition, AudioContent, ImageContent, InMemoryRunStore, JsonSessionStore,
    MessageRole, ModelMessage, RecordedSessionHistoryPolicy, RecordedSessionMessageProjector,
    RunEventReplay, RunResult, SessionError, SessionEventReplay, SessionInputDecodingError,
    SessionManager, SessionMessage, SessionRecord, SessionReplayError, SessionRunRecord,
    StandardSessionInputDecoder, StandardSessionInputRecorder, StopReason, TextContent,
    TextSessionHistoryPolicy, TextSessionMessageProjector, TokenUsage, session_input_to_dict,
)


def _input():
    return ModelMessage(MessageRole.USER, (
        TextContent("PRIVATE_TEXT"), ImageContent(data=b"PRIVATE_IMAGE", media_type="image/png"),
        AudioContent(url="https://example.test/PRIVATE_AUDIO"), TextContent("tail"),
    ))


def _record():
    return StandardSessionInputRecorder().record(_input())


def _session(record=None):
    return SessionRecord("session", "title", messages=(
        SessionMessage(MessageRole.USER, "PRIVATE_TEXTtail", "old", recorded_input=record if record is not None else _record()),
        SessionMessage(MessageRole.ASSISTANT, "answer", "old"),
    ), runs=(SessionRunRecord("old", "agent", "completed", "answer", TokenUsage(1, 1), True, 1, 0),), schema_version=2)


class Loop:
    def __init__(self):
        self.contexts = []

    async def run(self, definition, context):
        self.contexts.append(context)
        return RunResult(context.run_id, StopReason.COMPLETED, "done", context.messages, (), 1, 0)


def test_standard_decoder_restores_order_and_does_not_invent_metadata():
    assert StandardSessionInputDecoder().decode(_record()) == _input().content
    projected = RecordedSessionHistoryPolicy().project(_session())
    assert projected[0] == _input()
    assert projected[1] == ModelMessage.text(MessageRole.ASSISTANT, "answer")


@pytest.mark.parametrize("mode,has_url,has_body", [("metadata", False, False), ("references", True, False), ("content", True, True)])
def test_input_disclosure_modes_independent_of_text(mode, has_url, has_body):
    message = _session().messages[0]
    data = RecordedSessionMessageProjector(media_mode=mode).project(message)
    assert "PRIVATE_TEXT" not in json.dumps(data)
    assert ("url" in data["input_blocks"][2]) is has_url
    assert ("data_base64" in data["input_blocks"][1]) is has_body
    assert data["input_recorded"] is True
    plain = TextSessionMessageProjector(include_text=True).project(message)
    assert "input_blocks" not in plain and "recorded_input" not in plain
    assert "PRIVATE_AUDIO" not in json.dumps(plain)
    text = RecordedSessionMessageProjector(include_text=True).project(message)
    assert text["input_blocks"][0]["text"] == "PRIVATE_TEXT"
    assert "url" not in text["input_blocks"][2]


@pytest.mark.parametrize("mutation", ["digest", "size", "base64", "codec", "extra", "kind", "empty", "text-type"])
def test_corrupt_or_unsupported_records_fail_closed(mutation):
    data = session_input_to_dict(_record())
    block = data["blocks"][1]
    if mutation == "digest":
        block["sha256"] = "0" * 64
    elif mutation == "size":
        block["size_bytes"] += 1
    elif mutation == "base64":
        block["data_base64"] = "!PRIVATE"
    elif mutation == "codec":
        data["codec"] = "PRIVATE_PLUGIN"
    elif mutation == "extra":
        data["module"] = "PRIVATE_PLUGIN"
    elif mutation == "kind":
        block["kind"] = "tool-call"
    elif mutation == "empty":
        data["blocks"] = []
    else:
        data["blocks"][0]["text"] = 1
    with pytest.raises(SessionInputDecodingError) as error:
        StandardSessionInputDecoder().decode(data)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("options", [dict(max_blocks=1), dict(max_text_chars=1), dict(max_inline_bytes=1), dict(max_reference_chars=1)])
def test_decoder_limits(options):
    with pytest.raises(SessionInputDecodingError):
        StandardSessionInputDecoder(**options).decode(_record())


def test_history_limits_and_legacy_fallback():
    for policy in (RecordedSessionHistoryPolicy(max_messages=1), RecordedSessionHistoryPolicy(max_content_bytes=1)):
        with pytest.raises(SessionError):
            policy.project(_session())
    legacy = SessionRecord("session", "title", messages=(SessionMessage(MessageRole.USER, "legacy", "old"),))
    assert RecordedSessionHistoryPolicy().project(legacy) == TextSessionHistoryPolicy().project(legacy)
    media_only = replace(_session(), messages=(SessionMessage(MessageRole.USER, "", "old", recorded_input=
        StandardSessionInputRecorder().record(ModelMessage(MessageRole.USER, (ImageContent(url="https://example.test/image"),)))),))
    assert TextSessionHistoryPolicy().project(media_only) == ()
    assert isinstance(RecordedSessionHistoryPolicy().project(media_only)[0].content[0], ImageContent)


@pytest.mark.asyncio
async def test_explicit_per_run_policy_is_not_persisted(tmp_path):
    store = JsonSessionStore(tmp_path)
    await store.save(_session())
    manager = SessionManager(store)
    original = await manager.get("session")
    assert await manager.conversation("session") == TextSessionHistoryPolicy().project(original)
    assert await manager.conversation("session", history_policy=RecordedSessionHistoryPolicy()) == RecordedSessionHistoryPolicy().project(original)
    assert await manager.get("session") == original
    loop = Loop()
    await manager.run_agent(loop, AgentDefinition("agent"), "session", (ModelMessage.text(MessageRole.USER, "new"),),
                            history_policy=RecordedSessionHistoryPolicy(), run_id="second")
    assert loop.contexts[0].messages[0].content == _input().content
    reopened = SessionManager(JsonSessionStore(tmp_path))
    await reopened.run_agent(loop, AgentDefinition("agent"), "session", (ModelMessage.text(MessageRole.USER, "again"),), run_id="third")
    assert all(isinstance(block, TextContent) for msg in loop.contexts[1].messages for block in msg.content)
    assert sum(msg.recorded_input is not None for msg in (await reopened.get("session")).messages) == 1


@pytest.mark.asyncio
async def test_custom_policy_and_include_history_false(tmp_path):
    manager = SessionManager(JsonSessionStore(tmp_path))
    await manager.store.save(_session())
    class Policy:
        def project(self, session):
            return (ModelMessage.text(MessageRole.SYSTEM, "custom"),)
    assert (await manager.conversation("session", history_policy=Policy()))[0].content[0].text == "custom"
    class Broken:
        def project(self, session):
            raise RuntimeError("PRIVATE_ERROR")
    loop = Loop()
    with pytest.raises(SessionError) as error:
        await manager.run_agent(loop, AgentDefinition("agent"), "session", (ModelMessage.text(MessageRole.USER, "new"),), history_policy=Broken())
    assert "PRIVATE" not in str(error.value) and not loop.contexts
    await manager.run_agent(loop, AgentDefinition("agent"), "session", (ModelMessage.text(MessageRole.USER, "new"),),
                            history_policy=Broken(), include_history=False)
    assert len(loop.contexts[0].messages) == 1


def test_custom_decoder_is_host_injected_and_unknown_codec_has_no_fallback():
    session = _session({"codec": "custom/1", "ref": "host-owned"})
    with pytest.raises(SessionError):
        RecordedSessionHistoryPolicy().project(session)
    class Decoder:
        def decode(self, record):
            assert record["codec"] == "custom/1"
            return (TextContent("decoded"),)
    assert RecordedSessionHistoryPolicy(decoder=Decoder()).project(session)[0].content[0].text == "decoded"
    with pytest.raises(SessionInputDecodingError):
        RecordedSessionMessageProjector().project(session.messages[0])


@pytest.mark.asyncio
async def test_recorded_display_identity_and_failed_page_do_not_advance(tmp_path):
    store = JsonSessionStore(tmp_path)
    await store.save(_session())
    reader = SessionEventReplay(store, RunEventReplay(InMemoryRunStore()), message_projector=RecordedSessionMessageProjector())
    page = await reader.page("session")
    assert "PRIVATE" not in json.dumps(page.snapshot.to_dict())
    changed = SessionEventReplay(store, RunEventReplay(InMemoryRunStore()), message_projector=RecordedSessionMessageProjector(media_mode="content"))
    with pytest.raises(ValueError, match="configuration"):
        await changed.page("session", snapshot=page.snapshot)
    corrupted = _record()
    corrupted["blocks"][1]["sha256"] = "0" * 64
    await store.save(_session(corrupted))
    with pytest.raises(SessionReplayError):
        await reader.page("session", snapshot=page.snapshot)
    assert page.snapshot.runs[0].messages[0]["input_recorded"] is True
