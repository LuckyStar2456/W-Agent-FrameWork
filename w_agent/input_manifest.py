"""Strict local user-message files, separate from executable configuration."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from w_agent.models import AudioContent, ImageContent, MessageRole, ModelMessage, TextContent
from w_agent.session_message_fields import _normalize_message_fields


class InputManifestError(ValueError):
    """Content-free rejection of malformed or oversized input."""


@dataclass(frozen=True, slots=True)
class InputManifestLimits:
    max_file_bytes: int = 16 * 1024 * 1024
    max_messages: int = 256
    max_blocks_per_message: int = 256
    max_text_chars: int = 1_000_000
    max_inline_bytes: int = 8 * 1024 * 1024
    max_reference_chars: int = 16_384
    max_content_bytes: int = 32 * 1024 * 1024
    max_message_field_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        for value in (self.max_file_bytes, self.max_messages, self.max_blocks_per_message,
                      self.max_text_chars, self.max_inline_bytes, self.max_reference_chars,
                      self.max_content_bytes, self.max_message_field_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError("input manifest limits must be positive integers")


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("non-finite JSON value")


def input_manifest_from_mapping(
    data: Mapping[str, Any], *, limits: InputManifestLimits | None = None,
    allow_message_fields: bool = False,
) -> tuple[ModelMessage, ...]:
    """Parse schema 1 user messages without imports, permissions or external I/O.

    Other roles/types remain available through Python ModelMessages or a host
    parser. This template never downloads URLs or opens referenced files.
    """
    limits = limits if limits is not None else InputManifestLimits()
    try:
        if type(allow_message_fields) is not bool:
            raise ValueError("message-field selection must be boolean")
        if not isinstance(data, Mapping) or set(data) != {"schema_version", "messages"}:
            raise ValueError("invalid envelope")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError("unsupported schema")
        messages = data["messages"]
        if not isinstance(messages, (tuple, list)) or not 1 <= len(messages) <= limits.max_messages:
            raise ValueError("invalid message count")
        result = []
        total = 0
        for message in messages:
            allowed = {"role", "content", "name", "metadata"} if allow_message_fields else {"role", "content"}
            if (not isinstance(message, Mapping) or not {"role", "content"} <= set(message)
                    or not set(message) <= allowed or message["role"] != "user"):
                raise ValueError("invalid user message")
            fields = _normalize_message_fields(
                {key: message[key] for key in ("name", "metadata") if key in message},
                limits.max_message_field_bytes,
            )
            if fields:
                total += len(json.dumps(fields, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                if total > limits.max_content_bytes:
                    raise ValueError("oversized input batch")
            content = message["content"]
            if not isinstance(content, (tuple, list)) or not 1 <= len(content) <= limits.max_blocks_per_message:
                raise ValueError("invalid block count")
            blocks = []
            for block in content:
                if not isinstance(block, Mapping):
                    raise ValueError("invalid block")
                if block.get("type") == "text":
                    if set(block) != {"type", "text"} or not isinstance(block["text"], str) or len(block["text"]) > limits.max_text_chars:
                        raise ValueError("invalid text")
                    total += len(block["text"].encode("utf-8"))
                    blocks.append(TextContent(block["text"]))
                elif block.get("type") in {"image", "audio"}:
                    cls = ImageContent if block["type"] == "image" else AudioContent
                    media_type = block.get("media_type")
                    if media_type is not None and (not isinstance(media_type, str) or not media_type
                            or len(media_type) > 255 or any(ord(char) < 32 for char in media_type)):
                        raise ValueError("invalid media type")
                    if "url" in block:
                        if set(block) not in ({"type", "url"}, {"type", "url", "media_type"}):
                            raise ValueError("invalid URL fields")
                        url = block["url"]
                        if not isinstance(url, str) or not url or len(url) > limits.max_reference_chars or any(ord(char) < 33 for char in url):
                            raise ValueError("invalid reference")
                        parsed = urlsplit(url)
                        _ = parsed.port  # Validate a supplied port without network I/O.
                        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
                            raise ValueError("only HTTP(S) without userinfo is accepted")
                        total += len(url.encode("utf-8"))
                        blocks.append(cls(url=url, media_type=media_type))
                    else:
                        if set(block) != {"type", "data_base64", "media_type"} or not media_type:
                            raise ValueError("invalid inline fields")
                        encoded = block["data_base64"]
                        if not isinstance(encoded, str) or len(encoded) > ((limits.max_inline_bytes + 2) // 3) * 4:
                            raise ValueError("oversized inline content")
                        raw = base64.b64decode(encoded, validate=True)
                        if len(raw) > limits.max_inline_bytes:
                            raise ValueError("oversized inline content")
                        total += len(raw)
                        blocks.append(cls(data=raw, media_type=media_type))
                    total += len((media_type or "").encode("utf-8"))
                else:
                    raise ValueError("unsupported block type")
                if total > limits.max_content_bytes:
                    raise ValueError("oversized input batch")
            result.append(ModelMessage(MessageRole.USER, tuple(blocks), **fields))
        return tuple(result)
    except Exception:
        raise InputManifestError("invalid input manifest; check schema, content types and size limits") from None


def load_input_manifest(
    path: str | Path, *, limits: InputManifestLimits | None = None,
    allow_message_fields: bool = False,
) -> tuple[ModelMessage, ...]:
    """Read a bounded UTF-8 JSON file, never referenced files, URLs or code."""
    limits = limits if limits is not None else InputManifestLimits()
    try:
        if type(allow_message_fields) is not bool:
            raise ValueError("message-field selection must be boolean")
        source = Path(path)
        if not source.is_file():
            raise ValueError("not a regular file")
        with source.open("rb") as stream:
            raw = stream.read(limits.max_file_bytes + 1)
        if len(raw) > limits.max_file_bytes:
            raise ValueError("oversized manifest")
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object_pairs, parse_constant=_constant)
        return input_manifest_from_mapping(data, limits=limits, allow_message_fields=allow_message_fields)
    except Exception:
        raise InputManifestError("input file could not be loaded; check UTF-8 JSON, schema and limits") from None
