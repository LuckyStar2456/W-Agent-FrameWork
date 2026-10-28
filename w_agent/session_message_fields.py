"""Explicit message-field recording, disclosure and re-sending, without authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from w_agent.agents.media_events import normalize_model_output_event
from w_agent.models import ContentBlock, ModelMessage
from w_agent.session_inputs import (
    SessionInputDecoder, SessionInputDecodingError, SessionInputRecorder,
    SessionInputRecordingError, StandardSessionInputDecoder,
    StandardSessionInputRecorder, session_input_to_dict,
)


MESSAGE_FIELDS_INPUT_CODEC = "w-agent.session-message/1"
DEFAULT_MESSAGE_FIELD_BYTES = 64 * 1024


class SessionMessageFieldsDecoder(Protocol):
    """Trusted pure decoder; return only explicitly selected name/metadata fields."""

    def decode_fields(self, record: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _positive(value: object) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("message-field limit must be a positive integer")


def _flags(name: bool, metadata: bool) -> None:
    if type(name) is not bool or type(metadata) is not bool:
        raise ValueError("message-field selections must be booleans")


def _normalize_message_fields(
    fields: Mapping[str, Any], max_bytes: int = DEFAULT_MESSAGE_FIELD_BYTES,
) -> dict[str, Any]:
    _positive(max_bytes)
    data = normalize_model_output_event(fields)
    if not set(data) <= {"name", "metadata"}:
        raise ValueError("unsupported message fields")
    if "name" in data and (
        not isinstance(data["name"], str) or not data["name"] or len(data["name"]) > 256
    ):
        raise ValueError("invalid message name")
    if "metadata" in data and not isinstance(data["metadata"], dict):
        raise ValueError("message metadata must be a finite JSON object")
    if not data:
        return data
    if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")) > max_bytes:
        raise ValueError("message fields exceed byte limit")
    return data


def _unwrap_message_fields(
    record: Mapping[str, Any], max_bytes: int = DEFAULT_MESSAGE_FIELD_BYTES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    data = session_input_to_dict(record)
    if data["codec"] != MESSAGE_FIELDS_INPUT_CODEC:
        return data, {}
    if set(data) != {"codec", "content", "fields"}:
        raise ValueError("invalid message-field envelope")
    fields = _normalize_message_fields(data["fields"], max_bytes)
    if not fields:
        raise ValueError("empty message-field envelope")
    content = session_input_to_dict(data["content"])
    if content["codec"] == MESSAGE_FIELDS_INPUT_CODEC:
        raise ValueError("nested message-field wrappers are unsupported")
    return content, fields


@dataclass(frozen=True, slots=True)
class MessageFieldsSessionInputRecorder:
    """Wrap a content recorder; name/metadata are separately opt-in, default off.

    A delegate returning None omits the entire record, including fields. No fields
    selected/present retains the delegate's original codec and envelope.
    """

    recorder: SessionInputRecorder = field(default_factory=StandardSessionInputRecorder)
    include_name: bool = False
    include_metadata: bool = False
    max_field_bytes: int = DEFAULT_MESSAGE_FIELD_BYTES

    def __post_init__(self) -> None:
        _flags(self.include_name, self.include_metadata)
        _positive(self.max_field_bytes)
        if not callable(getattr(self.recorder, "record", None)):
            raise ValueError("message-field recorder requires a content recorder")

    def record(self, message: ModelMessage) -> Mapping[str, Any] | None:
        try:
            content = self.recorder.record(message)
            if content is None:
                return None
            content = session_input_to_dict(content)
            if content["codec"] == MESSAGE_FIELDS_INPUT_CODEC:
                raise ValueError("nested message-field wrappers are unsupported")
            fields: dict[str, Any] = {}
            if self.include_name and message.name is not None:
                fields["name"] = message.name
            if self.include_metadata and message.metadata:
                fields["metadata"] = message.metadata
            if not fields:
                return content
            fields = _normalize_message_fields(fields, self.max_field_bytes)
            return session_input_to_dict({
                "codec": MESSAGE_FIELDS_INPUT_CODEC, "content": content, "fields": fields,
            })
        except Exception:
            raise SessionInputRecordingError("Session message-field recording failed") from None


@dataclass(frozen=True, slots=True)
class MessageFieldsSessionInputDecoder:
    """Unwrap content independently from selected fields; no implicit re-sending.

    decode() returns content only. decode_fields() requires separate host wiring
    into a history policy. Both validate the wrapper even when fields are hidden.
    """

    decoder: SessionInputDecoder = field(default_factory=StandardSessionInputDecoder)
    include_name: bool = False
    include_metadata: bool = False
    max_field_bytes: int = DEFAULT_MESSAGE_FIELD_BYTES

    def __post_init__(self) -> None:
        _flags(self.include_name, self.include_metadata)
        _positive(self.max_field_bytes)
        if not callable(getattr(self.decoder, "decode", None)):
            raise ValueError("message-field decoder requires a content decoder")

    def decode(self, record: Mapping[str, Any]) -> tuple[ContentBlock, ...]:
        try:
            content, _ = _unwrap_message_fields(record, self.max_field_bytes)
            return self.decoder.decode(content)
        except Exception:
            raise SessionInputDecodingError("Session message-field decoding failed") from None

    def decode_fields(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            _, fields = _unwrap_message_fields(record, self.max_field_bytes)
            return {key: value for key, value in fields.items()
                    if (key == "name" and self.include_name)
                    or (key == "metadata" and self.include_metadata)}
        except Exception:
            raise SessionInputDecodingError("Session message-field decoding failed") from None
