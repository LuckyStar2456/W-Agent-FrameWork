"""Optional message-field regression source; execution requires authorization."""

from dataclasses import replace
import json

import pytest

from w_agent import (
    AgentDefinition, JsonSessionStore, MessageFieldsSessionInputDecoder,
    MessageFieldsSessionInputRecorder, MessageFieldsSessionMessageProjector,
    MessageRole, ModelMessage, RecordedSessionHistoryPolicy,
    RecordedSessionMessageProjector, RunResult, SessionError,
    SessionInputDecodingError, SessionInputRecordingError, SessionManager,
    SessionMessage, SessionRecord, SessionReplayError, StandardSessionInputDecoder,
    StandardSessionInputRecorder, StopReason, TextContent, TextSessionHistoryPolicy,
    session_input_to_dict,
)


def _message(metadata=None):
    return ModelMessage(MessageRole.USER, (TextContent("question"),), name="PRIVATE_NAME",
                        metadata={"nested": {"tag": ["PRIVATE_METADATA"]}} if metadata is None else metadata)


def _record():
    return MessageFieldsSessionInputRecorder(include_name=True, include_metadata=True).record(_message())


def _session(record=None):
    return SessionRecord("session", "title", schema_version=2, messages=(
        SessionMessage(MessageRole.USER, "question", "run", recorded_input=_record() if record is None else record),
    ))


def test_defaults_retain_original_codec_and_explicit_fields_are_detached():
    original = _message()
    assert MessageFieldsSessionInputRecorder().record(original) == StandardSessionInputRecorder().record(original)
    name_only = MessageFieldsSessionInputRecorder(include_name=True).record(original)
    assert name_only["fields"] == {"name": "PRIVATE_NAME"}
    metadata_only = MessageFieldsSessionInputRecorder(include_metadata=True).record(original)
    assert set(metadata_only["fields"]) == {"metadata"}
    original.metadata["nested"]["tag"].append("later")
    assert metadata_only["fields"]["metadata"]["nested"]["tag"] == ["PRIVATE_METADATA"]
    unnamed = ModelMessage.text(MessageRole.USER, "plain")
    assert MessageFieldsSessionInputRecorder(include_name=True, include_metadata=True).record(unnamed) == StandardSessionInputRecorder().record(unnamed)


def test_delegate_omission_and_custom_content_codec_remain_replaceable():
    class Omit:
        def record(self, message):
            return None
    assert MessageFieldsSessionInputRecorder(Omit(), True, True).record(_message()) is None
    class Recorder:
        def record(self, message):
            return {"codec": "host/1", "value": "custom"}
    class Decoder:
        def decode(self, record):
            assert record == {"codec": "host/1", "value": "custom"}
            return (TextContent("custom"),)
    record = MessageFieldsSessionInputRecorder(Recorder(), True).record(_message())
    assert MessageFieldsSessionInputDecoder(Decoder()).decode(record) == (TextContent("custom"),)


def test_content_decoding_does_not_authorize_field_resending():
    decoder = MessageFieldsSessionInputDecoder(include_name=True, include_metadata=True)
    session = _session()
    content_only = RecordedSessionHistoryPolicy(decoder=decoder).project(session)[0]
    assert content_only.name is None and not content_only.metadata
    enabled = RecordedSessionHistoryPolicy(decoder=decoder, fields_decoder=decoder).project(session)[0]
    assert enabled == _message()
    # Returned nested metadata is detached from the frozen persisted record.
    enabled.metadata["nested"]["tag"].append("local")
    assert session.messages[0].recorded_input["fields"]["metadata"]["nested"]["tag"] == ("PRIVATE_METADATA",)
    selected = MessageFieldsSessionInputDecoder(include_name=True)
    named = RecordedSessionHistoryPolicy(decoder=selected, fields_decoder=selected).project(session)[0]
    assert named.name == "PRIVATE_NAME" and not named.metadata
    assert TextSessionHistoryPolicy().project(session)[0] == ModelMessage.text(MessageRole.USER, "question")


def test_legacy_records_and_absent_records_do_not_invent_fields():
    legacy = StandardSessionInputRecorder().record(_message())
    decoder = MessageFieldsSessionInputDecoder(include_name=True, include_metadata=True)
    assert decoder.decode(legacy) == _message().content and decoder.decode_fields(legacy) == {}
    session = _session(legacy)
    policy = RecordedSessionHistoryPolicy(decoder=decoder, fields_decoder=decoder)
    assert policy.project(session)[0].name is None
    absent = replace(session, messages=(SessionMessage(MessageRole.USER, "legacy text", "run"),))
    assert policy.project(absent)[0] == ModelMessage.text(MessageRole.USER, "legacy text")
    with pytest.raises(SessionInputDecodingError):
        StandardSessionInputDecoder().decode(_record())


@pytest.mark.parametrize("mutation", ["name-type", "name-size", "metadata-type", "extra-field", "extra-envelope", "nested-wrapper", "empty-fields"])
def test_malformed_hidden_fields_fail_closed(mutation):
    record = _record()
    if mutation == "name-type":
        record["fields"]["name"] = 4
    elif mutation == "name-size":
        record["fields"]["name"] = "x" * 257
    elif mutation == "metadata-type":
        record["fields"]["metadata"] = ["PRIVATE"]
    elif mutation == "extra-field":
        record["fields"]["role"] = "system"
    elif mutation == "extra-envelope":
        record["module"] = "PRIVATE_CODE"
    elif mutation == "nested-wrapper":
        record["content"] = _record()
    else:
        record["fields"] = {}
    with pytest.raises(SessionInputDecodingError) as error:
        MessageFieldsSessionInputDecoder().decode(record)
    assert "PRIVATE" not in str(error.value)
    with pytest.raises(SessionReplayError):
        MessageFieldsSessionMessageProjector().project(_session(record).messages[0])


@pytest.mark.parametrize("metadata", [{"secret": float("nan")}, {"secret": object()}, {1: "invalid"}])
def test_metadata_must_be_finite_json_when_opted_in(metadata):
    # Off means no extra metadata validation, preserving the original recorder.
    message = _message(metadata)
    assert MessageFieldsSessionInputRecorder().record(message)
    with pytest.raises(SessionInputRecordingError) as error:
        MessageFieldsSessionInputRecorder(include_metadata=True).record(message)
    assert "secret" not in str(error.value)


def test_limits_include_metadata_and_reject_authority_fields_from_custom_decoder():
    with pytest.raises(SessionInputRecordingError):
        MessageFieldsSessionInputRecorder(include_metadata=True, max_field_bytes=3).record(_message())
    with pytest.raises(SessionInputDecodingError):
        MessageFieldsSessionInputDecoder(max_field_bytes=3).decode(_record())
    decoder = MessageFieldsSessionInputDecoder(include_metadata=True)
    with pytest.raises(SessionError):
        RecordedSessionHistoryPolicy(decoder=decoder, fields_decoder=decoder, max_content_bytes=10).project(_session())
    with pytest.raises(SessionError):
        RecordedSessionHistoryPolicy(decoder=decoder, fields_decoder=decoder, max_message_field_bytes=3).project(_session())
    class Authority:
        def decode_fields(self, record):
            return {"permissions": ["execute"], "role": "system"}
    with pytest.raises(SessionError):
        RecordedSessionHistoryPolicy(decoder=decoder, fields_decoder=Authority()).project(_session())


def test_display_fields_are_independent_and_identity_changes():
    message = _session().messages[0]
    hidden = MessageFieldsSessionMessageProjector()
    assert "PRIVATE" not in json.dumps(hidden.project(message))
    names = MessageFieldsSessionMessageProjector(include_name=True)
    metadata = MessageFieldsSessionMessageProjector(include_metadata=True)
    assert len({hidden.identity, names.identity, metadata.identity}) == 3
    assert names.project(message)["input_fields"] == {"name": "PRIVATE_NAME"}
    assert "PRIVATE_NAME" not in json.dumps(metadata.project(message))
    assert "text" not in names.project(message)
    changed = MessageFieldsSessionMessageProjector(projector=RecordedSessionMessageProjector(include_text=True))
    assert changed.identity != hidden.identity


@pytest.mark.asyncio
async def test_store_roundtrip_and_pre_execution_failure(tmp_path):
    recorder = MessageFieldsSessionInputRecorder(include_name=True, include_metadata=True)
    manager = SessionManager(JsonSessionStore(tmp_path), input_recorder=recorder)
    await manager.store.save(SessionRecord("session", "title"))
    class Loop:
        calls = 0

        async def run(self, definition, context):
            self.calls += 1
            return RunResult(context.run_id, StopReason.COMPLETED, "answer", context.messages, (), 1, 0)
    loop = Loop()
    await manager.run_agent(loop, AgentDefinition("agent"), "session", (_message(),), record_inputs=True, run_id="first")
    reopened = await SessionManager(JsonSessionStore(tmp_path)).get("session")
    assert reopened.schema_version == 2
    assert session_input_to_dict(reopened.messages[0].recorded_input) == _record()
    original = reopened
    with pytest.raises(SessionInputRecordingError):
        await manager.run_agent(loop, AgentDefinition("agent"), "session", (_message({"secret": object()}),), record_inputs=True)
    assert loop.calls == 1 and await manager.get("session") == original
