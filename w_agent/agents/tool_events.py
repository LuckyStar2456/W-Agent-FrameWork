"""Opt-in, bounded encoding of model-visible tool results for replay."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from w_agent.models import ToolResultContent

from .media_events import normalize_model_output_event


class ToolResultEventEncodingError(ValueError):
    """A tool-result event cannot be represented within its JSON limit."""


class ToolResultEventEncoder(Protocol):
    """Trusted, synchronous projection; return None to deliberately omit.

    Receives only the model-visible result and tool name, not continuation
    tickets, executor data or authority. Implementations should be pure.
    """

    def encode(
        self, result: ToolResultContent, *, name: str,
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class TextToolResultEventEncoder:
    """Record text without truncation, external reads or implicit redaction."""

    max_text_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if type(self.max_text_bytes) is not int or self.max_text_bytes <= 0:
            raise ValueError("max_text_bytes must be a positive integer")

    def encode(
        self, result: ToolResultContent, *, name: str,
    ) -> Mapping[str, Any]:
        if not isinstance(result.content, str) or type(result.is_error) is not bool:
            raise ToolResultEventEncodingError("invalid model-visible tool result")
        # Bound characters before allocating UTF-8; the envelope has a separate cap.
        if len(result.content) > self.max_text_bytes:
            raise ToolResultEventEncodingError("tool result text exceeds the configured limit")
        try:
            size = len(result.content.encode("utf-8"))
        except UnicodeError:
            raise ToolResultEventEncodingError("tool result text must be valid UTF-8") from None
        if size > self.max_text_bytes:
            raise ToolResultEventEncodingError("tool result text exceeds the configured limit")
        return {"kind": "text", "text": result.content, "is_error": result.is_error}


def normalize_tool_result_event(
    value: object, *, max_bytes: int = 64 * 1024,
) -> dict[str, Any]:
    """Detach finite JSON (depth <= 32) and bound its serialized UTF-8 body.

    This validates transport shape, not application-specific schemas or secrets.
    Unknown custom encodings remain usable by application-owned replay reducers.
    """
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    try:
        # Reuse the finite-JSON normalization contract used by media events.
        normalized = normalize_model_output_event(value)
        encoded = json.dumps(normalized, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > max_bytes:
            raise ToolResultEventEncodingError("tool result event exceeds the configured limit")
        return normalized
    except (TypeError, ValueError, OverflowError):
        raise ToolResultEventEncodingError("tool result event must be a bounded JSON object") from None
