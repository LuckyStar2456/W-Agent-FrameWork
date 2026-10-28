"""Replaceable, explicit policies for constructing Session model history."""

from __future__ import annotations

from dataclasses import dataclass, field
import json

from w_agent.models import AudioContent, ImageContent, ModelMessage, TextContent
from w_agent.session_inputs import SessionInputDecoder, StandardSessionInputDecoder
from w_agent.session_message_fields import (
    SessionMessageFieldsDecoder, _normalize_message_fields,
)
from w_agent.sessions import SessionError, SessionRecord


@dataclass(frozen=True, slots=True)
class TextSessionHistoryPolicy:
    """Preserve legacy text history; ignore additional recorded input bodies."""

    def project(self, session: SessionRecord) -> tuple[ModelMessage, ...]:
        return tuple(ModelMessage.text(message.role, message.text) for message in session.messages
                     if message.text or message.recorded_input is None)


@dataclass(frozen=True, slots=True)
class RecordedSessionHistoryPolicy:
    """Opt into recorded input blocks, with text fallback only for absent records.

    No silent fallback for unknown/corrupt records, no downloads, tool replay,
    output-media reconstruction, truncation or persisted authority. Hosts own
    consent and Provider destination/capability policy. Custom decoders are
    trusted Python; replace the history policy too for new block categories.
    """

    decoder: SessionInputDecoder = field(default_factory=StandardSessionInputDecoder)
    max_messages: int = 1024
    max_content_bytes: int = 32 * 1024 * 1024
    fields_decoder: SessionMessageFieldsDecoder | None = None
    max_message_field_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if not callable(getattr(self.decoder, "decode", None)):
            raise ValueError("history input decoder needs a decode method")
        if self.fields_decoder is not None and not callable(getattr(self.fields_decoder, "decode_fields", None)):
            raise ValueError("history field decoder needs a decode_fields method")
        for value in (self.max_messages, self.max_content_bytes, self.max_message_field_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError("history limits must be positive integers")

    def project(self, session: SessionRecord) -> tuple[ModelMessage, ...]:
        try:
            if len(session.messages) > self.max_messages:
                raise ValueError("history exceeds message limit")
            result = []
            size = 0
            for message in session.messages:
                blocks = (self.decoder.decode(message.recorded_input) if message.recorded_input is not None
                          else (TextContent(message.text),))
                if not isinstance(blocks, tuple) or not blocks:
                    raise ValueError("decoder must return a nonempty block tuple")
                for block in blocks:
                    if isinstance(block, TextContent):
                        size += len(block.text.encode("utf-8"))
                    elif isinstance(block, (ImageContent, AudioContent)):
                        size += len(block.data) if block.data is not None else len(block.url.encode("utf-8"))
                        size += len((block.media_type or "").encode("utf-8"))
                    else:
                        raise ValueError("replace the history policy for additional block types")
                    if size > self.max_content_bytes:
                        raise ValueError("history exceeds byte limit")
                fields = {}
                if self.fields_decoder is not None and message.recorded_input is not None:
                    fields = _normalize_message_fields(
                        self.fields_decoder.decode_fields(message.recorded_input), self.max_message_field_bytes,
                    )
                    if fields:
                        size += len(json.dumps(fields, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                    if size > self.max_content_bytes:
                        raise ValueError("history exceeds byte limit")
                result.append(ModelMessage(message.role, blocks, **fields))
            return tuple(result)
        except Exception:
            raise SessionError("recorded Session history projection failed; no model invocation started") from None
