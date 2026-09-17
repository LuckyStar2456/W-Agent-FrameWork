"""Append-only local run events and approval checkpoints."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Protocol

from w_agent.kernel import ScopePath
from w_agent.models import (
    AudioContent,
    ImageContent,
    MessageRole,
    ModelMessage,
    TextContent,
    TokenUsage,
    ToolCallContent,
    ToolResultContent,
)
from w_agent.tools import ToolCall

from .types import (
    AgentDefinition,
    CheckpointStatus,
    RunCheckpoint,
    RunEvent,
    RunEventType,
    TokenBudget,
)


class RunStoreError(RuntimeError):
    """Persistent run state is invalid, conflicting, or unavailable."""


class RunResumeConflictError(RunStoreError):
    """A checkpoint was already claimed and cannot be replayed safely."""


class RunStore(Protocol):
    async def append(self, event: RunEvent) -> None: ...

    async def events(self, run_id: str) -> tuple[RunEvent, ...]: ...

    async def save_checkpoint(self, checkpoint: RunCheckpoint) -> None: ...

    async def load_checkpoint(self, run_id: str) -> RunCheckpoint | None: ...

    async def claim_checkpoint(self, run_id: str) -> RunCheckpoint: ...

    async def delete_checkpoint(self, run_id: str) -> None: ...


class InMemoryRunStore:
    """Deterministic store for local development and tests."""

    def __init__(self) -> None:
        self._events: dict[str, list[RunEvent]] = {}
        self._checkpoints: dict[str, RunCheckpoint] = {}
        self._lock = asyncio.Lock()

    async def append(self, event: RunEvent) -> None:
        async with self._lock:
            events = self._events.setdefault(event.run_id, [])
            if event.sequence != len(events) + 1:
                raise RunStoreError(
                    f"run event sequence {event.sequence} does not follow {len(events)}"
                )
            events.append(event)

    async def events(self, run_id: str) -> tuple[RunEvent, ...]:
        async with self._lock:
            return tuple(self._events.get(run_id, ()))

    async def save_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        async with self._lock:
            self._checkpoints[checkpoint.run_id] = checkpoint

    async def load_checkpoint(self, run_id: str) -> RunCheckpoint | None:
        async with self._lock:
            return self._checkpoints.get(run_id)

    async def claim_checkpoint(self, run_id: str) -> RunCheckpoint:
        async with self._lock:
            checkpoint = self._checkpoints.get(run_id)
            if checkpoint is None:
                raise RunStoreError(f"run {run_id!r} has no approval checkpoint")
            if checkpoint.status not in {
                CheckpointStatus.PENDING_APPROVAL,
                CheckpointStatus.READY,
            }:
                raise RunResumeConflictError(
                    f"run {run_id!r} checkpoint is already being resumed"
                )
            claimed = replace(checkpoint, status=CheckpointStatus.RESUMING)
            self._checkpoints[run_id] = claimed
            return claimed

    async def delete_checkpoint(self, run_id: str) -> None:
        async with self._lock:
            self._checkpoints.pop(run_id, None)


class JsonlRunStore:
    """Crash-aware filesystem store for one local developer workspace."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.runs_root = self.root / "runs"
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    async def append(self, event: RunEvent) -> None:
        await asyncio.to_thread(self._append_sync, event)

    async def events(self, run_id: str) -> tuple[RunEvent, ...]:
        return await asyncio.to_thread(self._events_sync, run_id)

    async def save_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        await asyncio.to_thread(self._save_checkpoint_sync, checkpoint)

    async def load_checkpoint(self, run_id: str) -> RunCheckpoint | None:
        return await asyncio.to_thread(self._load_checkpoint_sync, run_id)

    async def claim_checkpoint(self, run_id: str) -> RunCheckpoint:
        return await asyncio.to_thread(self._claim_checkpoint_sync, run_id)

    async def delete_checkpoint(self, run_id: str) -> None:
        await asyncio.to_thread(self._delete_checkpoint_sync, run_id)

    def _run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
            raise ValueError("run id is not safe for local persistence")
        path = (self.runs_root / run_id).resolve()
        if path.parent != self.runs_root:
            raise ValueError("run path escapes the store root")
        return path

    def _append_sync(self, event: RunEvent) -> None:
        with self._lock:
            run_dir = self._run_dir(event.run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            path = run_dir / "events.jsonl"
            current = self._events_sync(event.run_id)
            if event.sequence != len(current) + 1:
                raise RunStoreError(
                    f"run event sequence {event.sequence} does not follow {len(current)}"
                )
            payload = json.dumps(
                _event_to_data(event),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(payload + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def _events_sync(self, run_id: str) -> tuple[RunEvent, ...]:
        with self._lock:
            path = self._run_dir(run_id) / "events.jsonl"
            if not path.exists():
                return ()
            events = [
                _event_from_data(json.loads(line))
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for expected, event in enumerate(events, 1):
                if event.sequence != expected or event.run_id != run_id:
                    raise RunStoreError(f"run {run_id!r} has a corrupt event log")
            return tuple(events)

    def _save_checkpoint_sync(self, checkpoint: RunCheckpoint) -> None:
        with self._lock:
            path = self._run_dir(checkpoint.run_id) / "checkpoint.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(path, _checkpoint_to_data(checkpoint))

    def _load_checkpoint_sync(self, run_id: str) -> RunCheckpoint | None:
        with self._lock:
            path = self._run_dir(run_id) / "checkpoint.json"
            if not path.exists():
                return None
            return _checkpoint_from_data(json.loads(path.read_text(encoding="utf-8")))

    def _claim_checkpoint_sync(self, run_id: str) -> RunCheckpoint:
        with self._lock:
            checkpoint = self._load_checkpoint_sync(run_id)
            if checkpoint is None:
                raise RunStoreError(f"run {run_id!r} has no approval checkpoint")
            if checkpoint.status not in {
                CheckpointStatus.PENDING_APPROVAL,
                CheckpointStatus.READY,
            }:
                raise RunResumeConflictError(
                    f"run {run_id!r} checkpoint is already being resumed"
                )
            claimed = replace(checkpoint, status=CheckpointStatus.RESUMING)
            self._save_checkpoint_sync(claimed)
            return claimed

    def _delete_checkpoint_sync(self, run_id: str) -> None:
        with self._lock:
            path = self._run_dir(run_id) / "checkpoint.json"
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(payload + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _event_to_data(event: RunEvent) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sequence": event.sequence,
        "type": event.type.value,
        "run_id": event.run_id,
        "session_id": event.session_id,
        "created_at": event.created_at.isoformat(),
        "data": _json_value(event.data),
    }


def _event_from_data(data: Mapping[str, Any]) -> RunEvent:
    if data.get("schema_version") != 1:
        raise RunStoreError("unsupported run event schema version")
    return RunEvent(
        int(data["sequence"]),
        RunEventType(str(data["type"])),
        str(data["run_id"]),
        data.get("data", {}),
        session_id=data.get("session_id"),
        created_at=datetime.fromisoformat(str(data["created_at"])),
    )


def _checkpoint_to_data(checkpoint: RunCheckpoint) -> dict[str, Any]:
    definition = checkpoint.definition
    return {
        "schema_version": checkpoint.schema_version,
        "run_id": checkpoint.run_id,
        "session_id": checkpoint.session_id,
        "status": checkpoint.status.value,
        "definition": {
            "name": definition.name,
            "system_prompt": definition.system_prompt,
            "model": definition.model,
            "max_steps": definition.max_steps,
            "max_tool_calls": definition.max_tool_calls,
            "temperature": definition.temperature,
            "max_output_tokens": definition.max_output_tokens,
            "extensions": _json_value(definition.extensions),
            "token_budget": (
                {
                    "max_input_tokens": definition.token_budget.max_input_tokens,
                    "max_output_tokens": definition.token_budget.max_output_tokens,
                    "max_total_tokens": definition.token_budget.max_total_tokens,
                    "require_usage": definition.token_budget.require_usage,
                }
                if definition.token_budget is not None
                else None
            ),
        },
        "scope": [[item.kind, item.value] for item in checkpoint.scope],
        "messages": [_message_to_data(item) for item in checkpoint.messages],
        "pending_tool_call": (
            _tool_call_to_data(checkpoint.pending_tool_call)
            if checkpoint.pending_tool_call is not None
            else None
        ),
        "remaining_tool_calls": [
            _content_to_data(item) for item in checkpoint.remaining_tool_calls
        ],
        "steps": checkpoint.steps,
        "tool_calls": checkpoint.tool_calls,
        "latest_output": checkpoint.latest_output,
        "usage": {
            "input_tokens": checkpoint.usage.input_tokens,
            "output_tokens": checkpoint.usage.output_tokens,
            "cached_input_tokens": checkpoint.usage.cached_input_tokens,
        },
        "model_calls": checkpoint.model_calls,
        "reported_usage_calls": checkpoint.reported_usage_calls,
    }


def _checkpoint_from_data(data: Mapping[str, Any]) -> RunCheckpoint:
    definition = data["definition"]
    token_budget = definition.get("token_budget")
    usage = data.get("usage", {})
    remaining = tuple(_content_from_data(item) for item in data["remaining_tool_calls"])
    if not all(isinstance(item, ToolCallContent) for item in remaining):
        raise RunStoreError("checkpoint contains a non-tool remaining block")
    return RunCheckpoint(
        run_id=str(data["run_id"]),
        session_id=data.get("session_id"),
        definition=AgentDefinition(
            name=str(definition["name"]),
            system_prompt=definition.get("system_prompt"),
            model=definition.get("model"),
            max_steps=int(definition["max_steps"]),
            max_tool_calls=int(definition["max_tool_calls"]),
            temperature=definition.get("temperature"),
            max_output_tokens=definition.get("max_output_tokens"),
            extensions=definition.get("extensions", {}),
            token_budget=(
                TokenBudget(
                    max_input_tokens=token_budget.get("max_input_tokens"),
                    max_output_tokens=token_budget.get("max_output_tokens"),
                    max_total_tokens=token_budget.get("max_total_tokens"),
                    require_usage=bool(token_budget.get("require_usage", False)),
                )
                if isinstance(token_budget, Mapping)
                else None
            ),
        ),
        scope=ScopePath.from_pairs(tuple(tuple(item) for item in data["scope"])),
        messages=tuple(_message_from_data(item) for item in data["messages"]),
        pending_tool_call=(
            _tool_call_from_data(data["pending_tool_call"])
            if data.get("pending_tool_call") is not None
            else None
        ),
        remaining_tool_calls=remaining,
        steps=int(data["steps"]),
        tool_calls=int(data["tool_calls"]),
        latest_output=str(data["latest_output"]),
        usage=TokenUsage(
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
        ),
        model_calls=int(data.get("model_calls", 0)),
        reported_usage_calls=int(data.get("reported_usage_calls", 0)),
        status=CheckpointStatus(str(data["status"])),
        schema_version=int(data["schema_version"]),
    )


def _tool_call_to_data(call: ToolCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "name": call.name,
        "arguments": _json_value(call.arguments),
        "scope": [[item.kind, item.value] for item in call.scope],
        "metadata": _json_value(call.metadata),
    }


def _tool_call_from_data(data: Mapping[str, Any]) -> ToolCall:
    return ToolCall(
        str(data["id"]),
        str(data["name"]),
        data.get("arguments", {}),
        ScopePath.from_pairs(tuple(tuple(item) for item in data["scope"])),
        data.get("metadata", {}),
    )


def _message_to_data(message: ModelMessage) -> dict[str, Any]:
    return {
        "role": message.role.value,
        "name": message.name,
        "metadata": _json_value(message.metadata),
        "content": [_content_to_data(item) for item in message.content],
    }


def _message_from_data(data: Mapping[str, Any]) -> ModelMessage:
    return ModelMessage(
        MessageRole(str(data["role"])),
        tuple(_content_from_data(item) for item in data["content"]),
        name=data.get("name"),
        metadata=data.get("metadata", {}),
    )


def _content_to_data(content: Any) -> dict[str, Any]:
    if isinstance(content, TextContent):
        return {"type": "text", "text": content.text}
    if isinstance(content, ImageContent):
        return {
            "type": "image",
            "url": content.url,
            "data": _encode_bytes(content.data),
            "media_type": content.media_type,
        }
    if isinstance(content, AudioContent):
        return {
            "type": "audio",
            "url": content.url,
            "data": _encode_bytes(content.data),
            "media_type": content.media_type,
        }
    if isinstance(content, ToolCallContent):
        return {
            "type": "tool-call",
            "id": content.id,
            "name": content.name,
            "arguments": content.arguments,
        }
    if isinstance(content, ToolResultContent):
        return {
            "type": "tool-result",
            "call_id": content.call_id,
            "content": content.content,
            "is_error": content.is_error,
        }
    raise TypeError(f"unsupported model content {type(content).__name__}")


def _content_from_data(data: Mapping[str, Any]) -> Any:
    content_type = data["type"]
    if content_type == "text":
        return TextContent(str(data["text"]))
    if content_type == "image":
        return ImageContent(
            url=data.get("url"),
            data=_decode_bytes(data.get("data")),
            media_type=data.get("media_type"),
        )
    if content_type == "audio":
        return AudioContent(
            url=data.get("url"),
            data=_decode_bytes(data.get("data")),
            media_type=data.get("media_type"),
        )
    if content_type == "tool-call":
        return ToolCallContent(
            str(data["id"]),
            str(data["name"]),
            str(data["arguments"]),
        )
    if content_type == "tool-result":
        return ToolResultContent(
            str(data["call_id"]),
            str(data["content"]),
            bool(data.get("is_error", False)),
        )
    raise RunStoreError(f"unsupported model content type {content_type!r}")


def _encode_bytes(value: bytes | None) -> str | None:
    return None if value is None else base64.b64encode(value).decode("ascii")


def _decode_bytes(value: Any) -> bytes | None:
    return None if value is None else base64.b64decode(str(value), validate=True)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError(f"value {type(value).__name__} is not JSON serializable")
