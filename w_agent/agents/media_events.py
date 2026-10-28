"""Provider-neutral encoding for explicitly persisted model output blocks."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Protocol

from w_agent.models import AudioContent, ContentBlock, ImageContent


class ModelOutputEventEncodingError(ValueError):
    """Raised when a model output block cannot be encoded safely."""


class ModelOutputEventEncoder(Protocol):
    """Replaceable encoder for one completed provider-neutral output block."""

    def encode(
        self,
        block: ContentBlock,
        *,
        index: int,
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class StandardMultimodalEventEncoder:
    """Encode image/audio outputs without performing I/O.

    Returning ``None`` for other block types keeps text and tool disclosure on
    their existing, separately controlled event paths. Inline bytes are
    bounded before base64 expansion. Applications may replace this encoder for
    new content types or external blob storage.
    """

    max_inline_bytes: int = 8 * 1024 * 1024
    max_reference_chars: int = 16_384

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_inline_bytes, bool)
            or not isinstance(self.max_inline_bytes, int)
            or self.max_inline_bytes <= 0
        ):
            raise ValueError("max_inline_bytes must be a positive integer")
        if (
            isinstance(self.max_reference_chars, bool)
            or not isinstance(self.max_reference_chars, int)
            or self.max_reference_chars <= 0
        ):
            raise ValueError("max_reference_chars must be a positive integer")

    def encode(
        self,
        block: ContentBlock,
        *,
        index: int,
    ) -> Mapping[str, Any] | None:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ModelOutputEventEncodingError(
                "model output block index must be a non-negative integer"
            )
        if not isinstance(block, (ImageContent, AudioContent)):
            return None
        media_type = _media_type(block.media_type)
        kind = "image" if isinstance(block, ImageContent) else "audio"
        if block.url is not None:
            reference = _reference(block.url, self.max_reference_chars)
            return {
                "kind": kind,
                "source": "url",
                "media_type": media_type,
                "url": reference,
            }
        assert block.data is not None
        if len(block.data) > self.max_inline_bytes:
            raise ModelOutputEventEncodingError(
                "inline model output exceeds the configured event limit"
            )
        return {
            "kind": kind,
            "source": "inline",
            "media_type": media_type,
            "size_bytes": len(block.data),
            "sha256": hashlib.sha256(block.data).hexdigest(),
            "data_base64": base64.b64encode(block.data).decode("ascii"),
        }


def normalize_model_output_event(value: object) -> dict[str, Any]:
    """Return a detached JSON-compatible object from a custom encoder."""

    if not isinstance(value, Mapping):
        raise ModelOutputEventEncodingError(
            "model output event encoder must return an object"
        )
    normalized = _json_value(value)
    assert isinstance(normalized, dict)
    return normalized


def _reference(value: object, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or any(ord(character) < 32 for character in value)
    ):
        raise ModelOutputEventEncodingError(
            "model output media reference is invalid"
        )
    return value


def _media_type(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 255
        or any(ord(character) < 32 for character in value)
    ):
        raise ModelOutputEventEncodingError("model output media type is invalid")
    return value


def _json_value(value: object, *, depth: int = 0) -> Any:
    if depth > 32:
        raise ModelOutputEventEncodingError("model output event is too deeply nested")
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ModelOutputEventEncodingError(
                "model output event contains a non-finite number"
            )
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ModelOutputEventEncodingError(
                    "model output event keys must be strings"
                )
            result[key] = _json_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_value(item, depth=depth + 1) for item in value]
    raise ModelOutputEventEncodingError(
        f"model output event contains unsupported {type(value).__name__}"
    )
