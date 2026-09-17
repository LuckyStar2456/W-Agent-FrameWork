"""Deterministic model mocks and explicit local record/replay cassettes."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any

from w_agent.models import (
    AudioContent,
    BlockEnd,
    BlockStart,
    CancellationToken,
    ErrorEvent,
    FinishEvent,
    FinishReason,
    ImageContent,
    ModelDescriptor,
    ModelError,
    ModelFailure,
    ModelFailureKind,
    ModelRequest,
    StreamEvent,
    TextContent,
    TextDelta,
    TokenUsage,
    ToolCallContent,
    ToolCallDelta,
    ToolResultContent,
    UsageEvent,
)


class ModelCassetteError(RuntimeError):
    """A local model cassette is corrupt, exhausted, or mismatched."""


@dataclass(frozen=True, slots=True)
class ScriptedModelTurn:
    events: tuple[StreamEvent, ...] = ()
    failure: ModelFailure | None = None
    expected_model: str | None = None
    expected_tools: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", tuple(self.events))
        if (not self.events) == (self.failure is None):
            raise ValueError("scripted turn needs exactly one event script or failure")
        if self.expected_tools is not None:
            object.__setattr__(self, "expected_tools", tuple(self.expected_tools))


class ScriptedModelProvider:
    """Network-free provider with a finite, deterministic turn script."""

    def __init__(
        self,
        descriptor: ModelDescriptor,
        turns: Sequence[ScriptedModelTurn],
    ) -> None:
        if descriptor.provider.strip() == "":
            raise ValueError("scripted provider identity must not be empty")
        self.descriptor = descriptor
        self._turns = list(turns)
        self._lock = asyncio.Lock()
        self.requests: list[ModelRequest] = []

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        return (self.descriptor,)

    async def resolve(self, model: str) -> ModelDescriptor:
        if model != self.descriptor.model:
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.CONFIGURATION,
                    "scripted-model-not-found",
                    "scripted model does not exist",
                    provider=self.descriptor.provider,
                    model=model,
                )
            )
        return self.descriptor

    async def stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[StreamEvent]:
        async with self._lock:
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            if not self._turns:
                raise ModelError(
                    ModelFailure(
                        ModelFailureKind.CONFIGURATION,
                        "scripted-turns-exhausted",
                        "scripted model turns are exhausted",
                        provider=self.descriptor.provider,
                        model=request.model,
                    )
                )
            turn = self._turns.pop(0)
            self.requests.append(request)
            if turn.expected_model is not None and request.model != turn.expected_model:
                raise ModelError(
                    ModelFailure(
                        ModelFailureKind.CONFIGURATION,
                        "scripted-request-mismatch",
                        "scripted request model did not match",
                        provider=self.descriptor.provider,
                        model=request.model,
                    )
                )
            tool_names = tuple(tool.name for tool in request.tools)
            if turn.expected_tools is not None and tool_names != turn.expected_tools:
                raise ModelError(
                    ModelFailure(
                        ModelFailureKind.CONFIGURATION,
                        "scripted-request-mismatch",
                        "scripted request tools did not match",
                        provider=self.descriptor.provider,
                        model=request.model,
                    )
                )
            if turn.failure is not None:
                raise ModelError(turn.failure)
            for event in turn.events:
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                yield event

    @property
    def remaining_turns(self) -> int:
        return len(self._turns)


@dataclass(frozen=True, slots=True)
class ModelCassetteRecord:
    request_shape: Mapping[str, Any]
    events: tuple[StreamEvent, ...] = ()
    failure: ModelFailure | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_shape",
            MappingProxyType(dict(self.request_shape)),
        )
        object.__setattr__(self, "events", tuple(self.events))
        if (not self.events) == (self.failure is None):
            raise ValueError(
                "cassette record needs exactly one event script or failure"
            )


class JsonlModelCassette:
    """Append-only local cassette. Records may contain sensitive model content."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    async def append(self, record: ModelCassetteRecord) -> None:
        await asyncio.to_thread(self._append_sync, record)

    async def records(self) -> tuple[ModelCassetteRecord, ...]:
        return await asyncio.to_thread(self._records_sync)

    def _append_sync(self, record: ModelCassetteRecord) -> None:
        payload = json.dumps(
            _record_to_data(record),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _records_sync(self) -> tuple[ModelCassetteRecord, ...]:
        with self._lock:
            if not self.path.exists():
                return ()
            try:
                return tuple(
                    _record_from_data(json.loads(line))
                    for line in self.path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            except ModelCassetteError:
                raise
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise ModelCassetteError("model cassette is corrupt") from exc


class RecordingModelProvider:
    """Explicitly record complete provider turns into a local cassette."""

    def __init__(
        self,
        provider: Any,
        cassette: JsonlModelCassette,
        *,
        allow_sensitive_content: bool,
        redact: Callable[[str], str] | None = None,
    ) -> None:
        if allow_sensitive_content is not True:
            raise ValueError("recording model content requires explicit authorization")
        self.provider = provider
        self.cassette = cassette
        self.redact = redact or (lambda value: value)
        self._lock = asyncio.Lock()

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        return await self.provider.list_models()

    async def resolve(self, model: str) -> ModelDescriptor:
        return await self.provider.resolve(model)

    async def stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[StreamEvent]:
        async with self._lock:
            events: list[StreamEvent] = []
            recorded = False
            try:
                async for event in self.provider.stream(
                    request,
                    cancellation=cancellation,
                ):
                    captured = _redact_event(event, self.redact)
                    events.append(captured)
                    if isinstance(event, (FinishEvent, ErrorEvent)):
                        await self.cassette.append(
                            ModelCassetteRecord(_request_shape(request), tuple(events))
                        )
                        recorded = True
                    yield event
            except ModelError as exc:
                if not recorded:
                    await self.cassette.append(
                        ModelCassetteRecord(
                            _request_shape(request),
                            failure=_safe_failure(exc.failure),
                        )
                    )
                raise


class ReplayModelProvider:
    """Replay cassette turns sequentially without network access."""

    def __init__(
        self,
        descriptor: ModelDescriptor,
        records: Sequence[ModelCassetteRecord],
        *,
        allow_sensitive_content: bool,
    ) -> None:
        if allow_sensitive_content is not True:
            raise ValueError("replaying model content requires explicit authorization")
        self.descriptor = descriptor
        self._records = list(records)
        self._lock = asyncio.Lock()

    @classmethod
    async def from_cassette(
        cls,
        descriptor: ModelDescriptor,
        cassette: JsonlModelCassette,
        *,
        allow_sensitive_content: bool,
    ) -> "ReplayModelProvider":
        return cls(
            descriptor,
            await cassette.records(),
            allow_sensitive_content=allow_sensitive_content,
        )

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        return (self.descriptor,)

    async def resolve(self, model: str) -> ModelDescriptor:
        if model != self.descriptor.model:
            raise ModelCassetteError("replay model does not match requested model")
        return self.descriptor

    async def stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[StreamEvent]:
        async with self._lock:
            if not self._records:
                raise ModelCassetteError("model cassette is exhausted")
            record = self._records.pop(0)
            if dict(record.request_shape) != _request_shape(request):
                raise ModelCassetteError("model cassette request shape did not match")
            if record.failure is not None:
                raise ModelError(record.failure)
            for event in record.events:
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                yield event

    @property
    def remaining_records(self) -> int:
        return len(self._records)


def _request_shape(request: ModelRequest) -> dict[str, Any]:
    return {
        "model": request.model,
        "messages": [
            {
                "role": message.role.value,
                "block_types": [block.type for block in message.content],
                "named": message.name is not None,
            }
            for message in request.messages
        ],
        "tools": [tool.name for tool in request.tools],
        "response_schema": request.response_schema is not None,
        "temperature": request.temperature,
        "max_output_tokens": request.max_output_tokens,
        "stop_count": len(request.stop),
        "extension_keys": sorted(request.extensions),
    }


def _safe_failure(failure: ModelFailure) -> ModelFailure:
    return ModelFailure(
        failure.kind,
        failure.code,
        "recorded model failure message omitted",
        failure.retryable,
        failure.provider,
        failure.model,
    )


def _redact_event(event: StreamEvent, redact: Callable[[str], str]) -> StreamEvent:
    if isinstance(event, TextDelta):
        return TextDelta(event.index, redact(event.text))
    if isinstance(event, ToolCallDelta):
        return ToolCallDelta(
            event.index,
            event.id,
            event.name,
            redact(event.arguments_delta),
        )
    if isinstance(event, BlockEnd):
        block = event.block
        if isinstance(block, TextContent):
            block = TextContent(redact(block.text))
        elif isinstance(block, ToolCallContent):
            block = ToolCallContent(
                block.id,
                block.name,
                redact(block.arguments),
            )
        elif isinstance(block, ToolResultContent):
            block = ToolResultContent(
                block.call_id,
                redact(block.content),
                block.is_error,
            )
        return BlockEnd(event.index, block)
    if isinstance(event, ErrorEvent):
        return ErrorEvent(_safe_failure(event.failure))
    return event


def _record_to_data(record: ModelCassetteRecord) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_shape": dict(record.request_shape),
        "events": [_event_to_data(event) for event in record.events],
        "failure": _failure_to_data(record.failure) if record.failure else None,
    }


def _record_from_data(data: Mapping[str, Any]) -> ModelCassetteRecord:
    if data.get("schema_version") != 1 or not isinstance(
        data.get("request_shape"), Mapping
    ):
        raise ModelCassetteError("unsupported model cassette record")
    failure = data.get("failure")
    return ModelCassetteRecord(
        dict(data["request_shape"]),
        tuple(_event_from_data(item) for item in data.get("events", ())),
        _failure_from_data(failure) if isinstance(failure, Mapping) else None,
    )


def _event_to_data(event: StreamEvent) -> dict[str, Any]:
    if isinstance(event, BlockStart):
        return {
            "type": "block-start",
            "index": event.index,
            "block_type": event.block_type,
        }
    if isinstance(event, TextDelta):
        return {"type": "text-delta", "index": event.index, "text": event.text}
    if isinstance(event, ToolCallDelta):
        return {
            "type": "tool-call-delta",
            "index": event.index,
            "id": event.id,
            "name": event.name,
            "arguments_delta": event.arguments_delta,
        }
    if isinstance(event, BlockEnd):
        return {
            "type": "block-end",
            "index": event.index,
            "block": _block_to_data(event.block),
        }
    if isinstance(event, UsageEvent):
        return {
            "type": "usage",
            "input_tokens": event.usage.input_tokens,
            "output_tokens": event.usage.output_tokens,
            "cached_input_tokens": event.usage.cached_input_tokens,
        }
    if isinstance(event, ErrorEvent):
        return {
            "type": "error",
            "failure": _failure_to_data(_safe_failure(event.failure)),
        }
    if isinstance(event, FinishEvent):
        return {"type": "finish", "reason": event.reason.value}
    raise TypeError(f"unsupported stream event {type(event).__name__}")


def _event_from_data(data: Mapping[str, Any]) -> StreamEvent:
    kind = data["type"]
    if kind == "block-start":
        return BlockStart(int(data["index"]), str(data["block_type"]))
    if kind == "text-delta":
        return TextDelta(int(data["index"]), str(data["text"]))
    if kind == "tool-call-delta":
        return ToolCallDelta(
            int(data["index"]),
            str(data["id"]),
            str(data["name"]),
            str(data["arguments_delta"]),
        )
    if kind == "block-end":
        return BlockEnd(int(data["index"]), _block_from_data(data["block"]))
    if kind == "usage":
        return UsageEvent(
            TokenUsage(
                int(data["input_tokens"]),
                int(data["output_tokens"]),
                int(data.get("cached_input_tokens", 0)),
            )
        )
    if kind == "error":
        return ErrorEvent(_failure_from_data(data["failure"]))
    if kind == "finish":
        return FinishEvent(FinishReason(str(data["reason"])))
    raise ModelCassetteError(f"unsupported cassette event type {kind!r}")


def _block_to_data(block: Any) -> dict[str, Any]:
    if isinstance(block, TextContent):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolCallContent):
        return {
            "type": "tool-call",
            "id": block.id,
            "name": block.name,
            "arguments": block.arguments,
        }
    if isinstance(block, ToolResultContent):
        return {
            "type": "tool-result",
            "call_id": block.call_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    if isinstance(block, ImageContent):
        return {
            "type": "image",
            "url": block.url,
            "data": _bytes(block.data),
            "media_type": block.media_type,
        }
    if isinstance(block, AudioContent):
        return {
            "type": "audio",
            "url": block.url,
            "data": _bytes(block.data),
            "media_type": block.media_type,
        }
    raise TypeError(f"unsupported content block {type(block).__name__}")


def _block_from_data(data: Mapping[str, Any]) -> Any:
    kind = data["type"]
    if kind == "text":
        return TextContent(str(data["text"]))
    if kind == "tool-call":
        return ToolCallContent(
            str(data["id"]), str(data["name"]), str(data["arguments"])
        )
    if kind == "tool-result":
        return ToolResultContent(
            str(data["call_id"]),
            str(data["content"]),
            bool(data.get("is_error", False)),
        )
    if kind == "image":
        return ImageContent(
            url=data.get("url"),
            data=_unbytes(data.get("data")),
            media_type=data.get("media_type"),
        )
    if kind == "audio":
        return AudioContent(
            url=data.get("url"),
            data=_unbytes(data.get("data")),
            media_type=data.get("media_type"),
        )
    raise ModelCassetteError(f"unsupported cassette block type {kind!r}")


def _failure_to_data(failure: ModelFailure) -> dict[str, Any]:
    return {
        "kind": failure.kind.value,
        "code": failure.code,
        "message": failure.message,
        "retryable": failure.retryable,
        "provider": failure.provider,
        "model": failure.model,
    }


def _failure_from_data(data: Mapping[str, Any]) -> ModelFailure:
    return ModelFailure(
        ModelFailureKind(str(data["kind"])),
        str(data["code"]),
        str(data["message"]),
        bool(data.get("retryable", False)),
        data.get("provider"),
        data.get("model"),
    )


def _bytes(value: bytes | None) -> str | None:
    return None if value is None else base64.b64encode(value).decode("ascii")


def _unbytes(value: Any) -> bytes | None:
    return None if value is None else base64.b64decode(str(value), validate=True)
