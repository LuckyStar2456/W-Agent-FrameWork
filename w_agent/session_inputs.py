"""Opt-in, replaceable Session input recording without retrieval or execution."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from w_agent.agents.media_events import StandardMultimodalEventEncoder, normalize_model_output_event
from w_agent.agents.event_replay import MediaProjectionMode, _media_block_projection
from w_agent.models import AudioContent, ContentBlock, ImageContent, ModelMessage, TextContent


MAX_SESSION_INPUT_BYTES = 16 * 1024 * 1024
STANDARD_SESSION_INPUT_CODEC = "w-agent.session-input/1"


class SessionInputRecordingError(ValueError):
    """Input recording failed before Agent execution; no sensitive details."""


class SessionInputRecorder(Protocol):
    """Trusted pure recorder; return a codec-tagged JSON object, or omit with None."""

    def record(self, message: ModelMessage) -> Mapping[str, Any] | None: ...


class SessionInputDecoder(Protocol):
    """Trusted host-supplied decoder; no dynamic imports based on codec names."""

    def decode(self, record: Mapping[str, Any]) -> tuple[ContentBlock, ...]: ...


class SessionInputDecodingError(ValueError):
    """Recorded input is unsupported, corrupt or exceeds decoding limits."""


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def session_input_to_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached finite-JSON copy, validating the bounded record envelope."""
    try:
        result = normalize_model_output_event(value)
        codec = result.get("codec")
        if not isinstance(codec, str) or not codec.strip() or len(codec) > 256:
            raise ValueError("invalid codec")
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_SESSION_INPUT_BYTES:
            raise ValueError("record too large")
        return result
    except Exception:
        raise SessionInputRecordingError("invalid or oversized Session input record") from None


def freeze_session_input(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Detach and deeply freeze a record; never interpret codec fields as code."""
    return _freeze(session_input_to_dict(value))


@dataclass(frozen=True, slots=True)
class StandardSessionInputRecorder:
    """Record ordered text/image/audio blocks, excluding message metadata and name.

    URLs are stored verbatim without fetching. Inline data uses bounded Base64
    and SHA-256 metadata. Unknown blocks fail instead of silently losing input.
    Custom recorders may use other codecs and JSON payloads, never auto-loaded.
    """

    max_blocks: int = 256
    max_text_chars: int = 1_000_000
    max_inline_bytes: int = 8 * 1024 * 1024
    max_reference_chars: int = 16_384

    def __post_init__(self) -> None:
        for value in (self.max_blocks, self.max_text_chars, self.max_inline_bytes, self.max_reference_chars):
            if type(value) is not int or value <= 0:
                raise ValueError("Session input recording limits must be positive integers")

    def record(self, message: ModelMessage) -> Mapping[str, Any]:
        try:
            if not isinstance(message, ModelMessage) or not 1 <= len(message.content) <= self.max_blocks:
                raise ValueError("invalid message")
            encoder = StandardMultimodalEventEncoder(self.max_inline_bytes, self.max_reference_chars)
            blocks = []
            encoded_bytes = 0
            for index, block in enumerate(message.content):
                if isinstance(block, TextContent):
                    if not isinstance(block.text, str) or len(block.text) > self.max_text_chars:
                        raise ValueError("invalid text")
                    value = {"kind": "text", "text": block.text}
                else:
                    value = encoder.encode(block, index=index)
                    if value is None:
                        raise ValueError("unsupported block")
                encoded_bytes += len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                if encoded_bytes > MAX_SESSION_INPUT_BYTES:
                    raise ValueError("message too large")
                blocks.append(value)
            return session_input_to_dict({"codec": STANDARD_SESSION_INPUT_CODEC, "blocks": blocks})
        except Exception:
            raise SessionInputRecordingError("Session input recording failed; check content types and limits") from None


@dataclass(frozen=True, slots=True)
class StandardSessionInputDecoder:
    """Validate standard recorded blocks; project or reconstruct without I/O."""

    max_blocks: int = 256
    max_text_chars: int = 1_000_000
    max_inline_bytes: int = 8 * 1024 * 1024
    max_reference_chars: int = 16_384

    def __post_init__(self) -> None:
        for value in (self.max_blocks, self.max_text_chars, self.max_inline_bytes, self.max_reference_chars):
            if type(value) is not int or value <= 0:
                raise ValueError("Session input decoding limits must be positive integers")

    @property
    def identity(self) -> str:
        limits = [self.max_blocks, self.max_text_chars, self.max_inline_bytes, self.max_reference_chars]
        return "w-agent.session-input-decoder/1/" + hashlib.sha256(json.dumps(limits).encode()).hexdigest()

    def project(
        self, record: Mapping[str, Any], *, include_text: bool = False,
        media_mode: MediaProjectionMode | str = MediaProjectionMode.METADATA,
    ) -> tuple[dict[str, Any], ...]:
        try:
            if type(include_text) is not bool:
                raise ValueError("invalid text switch")
            mode = MediaProjectionMode(media_mode)
            data = session_input_to_dict(record)
            if set(data) != {"codec", "blocks"} or data["codec"] != STANDARD_SESSION_INPUT_CODEC:
                raise ValueError("unsupported codec or envelope")
            blocks = data["blocks"]
            if not isinstance(blocks, list) or not 1 <= len(blocks) <= self.max_blocks:
                raise ValueError("invalid block sequence")
            result = []
            for block in blocks:
                if not isinstance(block, dict):
                    raise ValueError("invalid block")
                if block.get("kind") == "text":
                    if set(block) != {"kind", "text"} or not isinstance(block["text"], str) or len(block["text"]) > self.max_text_chars:
                        raise ValueError("invalid text")
                    projected = {"kind": "text", "characters": len(block["text"])}
                    if include_text:
                        projected["text"] = block["text"]
                else:
                    fields = {"kind", "source", "media_type"}
                    fields |= {"url"} if block.get("source") == "url" else {"size_bytes", "sha256", "data_base64"}
                    if set(block) != fields:
                        raise ValueError("invalid media fields")
                    projected = _media_block_projection(
                        block, mode, max_inline_bytes=self.max_inline_bytes,
                        max_reference_chars=self.max_reference_chars,
                    )
                    if projected["source"] == "inline" and not projected["media_type"]:
                        raise ValueError("inline media needs a media type")
                result.append(projected)
            return tuple(result)
        except Exception:
            raise SessionInputDecodingError("Session input decoding failed; check codec, integrity and limits") from None

    def decode(self, record: Mapping[str, Any]) -> tuple[ContentBlock, ...]:
        projected = self.project(record, include_text=True, media_mode="content")
        blocks = []
        for block in projected:
            if block["kind"] == "text":
                blocks.append(TextContent(block["text"]))
                continue
            cls = ImageContent if block["kind"] == "image" else AudioContent
            if block["source"] == "url":
                blocks.append(cls(url=block["url"], media_type=block["media_type"]))
            else:
                blocks.append(cls(data=base64.b64decode(block["data_base64"], validate=True), media_type=block["media_type"]))
        return tuple(blocks)
