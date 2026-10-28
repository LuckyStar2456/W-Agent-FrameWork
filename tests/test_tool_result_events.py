"""Draft tool-result encoding coverage; execution awaits user authorization."""

import json

import pytest

from w_agent import (
    AgentDefinition, CheckpointStatus, RunCheckpoint, ScopePath,
    TextToolResultEventEncoder, ToolResultContent, ToolResultEventEncodingError,
    normalize_tool_result_event,
)
from w_agent.agents.persistence import _checkpoint_from_data, _checkpoint_to_data


def test_text_encoding_and_utf8_envelope_limits():
    result = ToolResultContent("call", "猫", True)
    encoder = TextToolResultEventEncoder(max_text_bytes=3)
    body = encoder.encode(result, name="tool")
    assert body == {"kind": "text", "text": "猫", "is_error": True}
    size = len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    assert normalize_tool_result_event(body, max_bytes=size) == body
    with pytest.raises(ToolResultEventEncodingError):
        normalize_tool_result_event(body, max_bytes=size - 1)
    with pytest.raises(ToolResultEventEncodingError):
        TextToolResultEventEncoder(max_text_bytes=2).encode(result, name="tool")
    with pytest.raises(ToolResultEventEncodingError):
        encoder.encode(ToolResultContent("call", "\ud800"), name="tool")


@pytest.mark.parametrize("value", [[], {"bytes": b"x"}, {"nan": float("nan")}, {1: "key"}, {"object": object()}])
def test_custom_event_payload_rejects_non_json(value):
    with pytest.raises(ToolResultEventEncodingError):
        normalize_tool_result_event(value)


def test_custom_event_detaches_nested_containers_and_rejects_cycles():
    original = {"kind": "application", "values": [1, {"value": True}]}
    normalized = normalize_tool_result_event(original)
    original["values"][1]["value"] = False
    assert normalized["values"][1]["value"] is True
    cycle = {}
    cycle["self"] = cycle
    with pytest.raises(ToolResultEventEncodingError):
        normalize_tool_result_event(cycle)


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "100"])
def test_limits_are_strict_positive_integers(value):
    with pytest.raises(ValueError):
        AgentDefinition("agent", max_tool_result_event_bytes=value)
    with pytest.raises(ValueError):
        TextToolResultEventEncoder(max_text_bytes=value)
    with pytest.raises(ValueError):
        normalize_tool_result_event({}, max_bytes=value)


def test_recording_flag_is_strict_and_old_checkpoint_defaults_remain_off():
    with pytest.raises(ValueError):
        AgentDefinition("agent", emit_tool_results="true")
    checkpoint = RunCheckpoint(
        "run", AgentDefinition("agent", emit_tool_results=True, max_tool_result_event_bytes=2048),
        ScopePath.application(), (), None, (), 0, 0, "", status=CheckpointStatus.READY,
    )
    data = _checkpoint_to_data(checkpoint)
    assert _checkpoint_from_data(data).definition == checkpoint.definition
    del data["definition"]["emit_tool_results"]
    del data["definition"]["max_tool_result_event_bytes"]
    restored = _checkpoint_from_data(data)
    assert restored.definition.emit_tool_results is False
    assert restored.definition.max_tool_result_event_bytes == 64 * 1024
