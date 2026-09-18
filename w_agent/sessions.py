"""Local session lifecycle and cross-run text conversation projection."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import os
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any, Mapping, Protocol
from uuid import uuid4

from w_agent.agents import (
    AgentDefinition,
    AgentExecution,
    AgentLoop,
    RunContext,
    RunEvent,
    RunResult,
)
from w_agent.kernel import ScopePath
from w_agent.models import (
    CancellationToken,
    MessageRole,
    ModelCost,
    ModelMessage,
    TextContent,
    TokenUsage,
    PricingError,
)
from w_agent.tools import ToolExecutionContext

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class SessionError(RuntimeError):
    """Session state is missing, invalid, archived, or conflicting."""


class SessionStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class SessionMessage:
    role: MessageRole
    text: str
    run_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        _validate_id(self.run_id, "run")


@dataclass(frozen=True, slots=True)
class SessionRunRecord:
    run_id: str
    agent_name: str
    stop_reason: str
    output: str
    usage: TokenUsage
    usage_complete: bool
    steps: int
    tool_calls: int
    model_calls: int = 0
    reported_usage_calls: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    cost: ModelCost | None = None
    cost_complete: bool = False
    priced_usage_calls: int = 0

    def __post_init__(self) -> None:
        _validate_id(self.run_id, "run")
        if min(
            self.steps,
            self.tool_calls,
            self.model_calls,
            self.reported_usage_calls,
            self.priced_usage_calls,
        ) < 0:
            raise ValueError("session run counters must not be negative")
        if self.reported_usage_calls > self.model_calls:
            raise ValueError("reported usage calls cannot exceed model calls")
        if self.priced_usage_calls > self.reported_usage_calls:
            raise ValueError("priced usage calls cannot exceed reported usage calls")


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    title: str
    status: SessionStatus = SessionStatus.ACTIVE
    messages: tuple[SessionMessage, ...] = ()
    runs: tuple[SessionRunRecord, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_id(self.session_id, "session")
        if not self.title.strip():
            raise ValueError("session title must not be empty")
        if self.schema_version != 1:
            raise ValueError("unsupported session schema version")
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "runs", tuple(self.runs))
        _validate_json(self.metadata, "session metadata")
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentUsageSummary:
    """Prompt-free aggregate across local sessions for one agent name."""

    agent_name: str
    session_ids: tuple[str, ...]
    run_count: int
    usage: TokenUsage
    model_calls: int
    reported_usage_calls: int
    cost: ModelCost | None = None
    priced_usage_calls: int = 0

    def __post_init__(self) -> None:
        if not self.agent_name.strip():
            raise ValueError("agent usage summary name must not be empty")
        session_ids = tuple(self.session_ids)
        if len(set(session_ids)) != len(session_ids):
            raise ValueError("agent usage summary session ids must be unique")
        for session_id in session_ids:
            _validate_id(session_id, "session")
        if min(
            self.run_count,
            self.model_calls,
            self.reported_usage_calls,
            self.priced_usage_calls,
        ) < 0:
            raise ValueError("agent usage summary counters must not be negative")
        if self.reported_usage_calls > self.model_calls:
            raise ValueError("reported usage calls cannot exceed model calls")
        if self.priced_usage_calls > self.reported_usage_calls:
            raise ValueError("priced usage calls cannot exceed reported usage calls")
        object.__setattr__(self, "session_ids", session_ids)

    @property
    def session_count(self) -> int:
        return len(self.session_ids)

    @property
    def usage_complete(self) -> bool:
        return self.reported_usage_calls == self.model_calls

    @property
    def cost_complete(self) -> bool:
        return self.cost is not None and self.priced_usage_calls == self.model_calls


class SessionStore(Protocol):
    async def save(self, session: SessionRecord) -> None: ...

    async def get(self, session_id: str) -> SessionRecord | None: ...

    async def list(self, *, include_archived: bool = False) -> tuple[SessionRecord, ...]: ...


class ResumableAgentLoop(Protocol):
    async def resume(
        self,
        run_id: str,
        *,
        tool_context: ToolExecutionContext,
        cancellation: CancellationToken | None = None,
    ) -> RunResult: ...


RunEventCallback = Callable[[RunEvent], Awaitable[None] | None]


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = asyncio.Lock()

    async def save(self, session: SessionRecord) -> None:
        async with self._lock:
            self._sessions[session.session_id] = session

    async def get(self, session_id: str) -> SessionRecord | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def list(self, *, include_archived: bool = False) -> tuple[SessionRecord, ...]:
        async with self._lock:
            values = tuple(self._sessions.values())
        return _visible_sessions(values, include_archived)


class JsonSessionStore:
    """Atomic JSON session records for one local lifecycle owner."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    async def save(self, session: SessionRecord) -> None:
        await asyncio.to_thread(self._save_sync, session)

    async def get(self, session_id: str) -> SessionRecord | None:
        return await asyncio.to_thread(self._get_sync, session_id)

    async def list(self, *, include_archived: bool = False) -> tuple[SessionRecord, ...]:
        return await asyncio.to_thread(self._list_sync, include_archived)

    def _path(self, session_id: str) -> Path:
        _validate_id(session_id, "session")
        path = (self.root / f"{session_id}.json").resolve()
        if path.parent != self.root:
            raise SessionError("session path escapes the store root")
        return path

    def _save_sync(self, session: SessionRecord) -> None:
        with self._lock:
            path = self._path(session.session_id)
            temporary = path.with_suffix(".json.tmp")
            payload = json.dumps(
                _session_to_data(session),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)

    def _get_sync(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            path = self._path(session_id)
            if not path.is_file():
                return None
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return _session_from_data(data)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise SessionError("session record is corrupt") from error

    def _list_sync(self, include_archived: bool) -> tuple[SessionRecord, ...]:
        with self._lock:
            sessions = tuple(
                self._get_sync(path.stem)
                for path in self.root.glob("*.json")
                if _SAFE_ID.fullmatch(path.stem)
            )
        return _visible_sessions(
            (item for item in sessions if item is not None),
            include_archived,
        )


class SessionManager:
    """Coordinate sessions and ordinary AgentLoop runs without private hooks."""

    def __init__(self, store: SessionStore | None = None) -> None:
        self.store = store or InMemorySessionStore()
        self._lock = asyncio.Lock()

    async def create(
        self,
        title: str,
        *,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> SessionRecord:
        session = SessionRecord(
            session_id or f"session-{uuid4().hex}",
            title,
            metadata=metadata or {},
        )
        async with self._lock:
            if await self.store.get(session.session_id) is not None:
                raise SessionError("session already exists")
            await self.store.save(session)
        return session

    async def get(self, session_id: str) -> SessionRecord:
        session = await self.store.get(session_id)
        if session is None:
            raise SessionError("session does not exist")
        return session

    async def list(self, *, include_archived: bool = False) -> tuple[SessionRecord, ...]:
        return await self.store.list(include_archived=include_archived)

    async def agent_usage(
        self,
        agent_name: str | None = None,
        *,
        include_archived: bool = False,
    ) -> tuple[AgentUsageSummary, ...]:
        """Aggregate known usage/cost without reading prompts or running models."""

        if agent_name is not None and not agent_name.strip():
            raise ValueError("agent name filter must not be empty")
        sessions = await self.store.list(include_archived=include_archived)
        grouped: dict[str, list[tuple[str, SessionRunRecord]]] = {}
        for session in sessions:
            for run in session.runs:
                if agent_name is not None and run.agent_name != agent_name:
                    continue
                grouped.setdefault(run.agent_name, []).append(
                    (session.session_id, run)
                )
        summaries: list[AgentUsageSummary] = []
        for name, entries in grouped.items():
            runs = tuple(run for _, run in entries)
            usage = TokenUsage(
                sum(run.usage.input_tokens for run in runs),
                sum(run.usage.output_tokens for run in runs),
                sum(run.usage.cached_input_tokens for run in runs),
            )
            summaries.append(
                AgentUsageSummary(
                    name,
                    tuple(dict.fromkeys(session_id for session_id, _ in entries)),
                    len(runs),
                    usage,
                    sum(run.model_calls for run in runs),
                    sum(run.reported_usage_calls for run in runs),
                    cost=_aggregate_run_cost(runs),
                    priced_usage_calls=sum(
                        run.priced_usage_calls for run in runs
                    ),
                )
            )
        return tuple(sorted(summaries, key=lambda item: item.agent_name))

    async def archive(self, session_id: str, *, archived: bool = True) -> SessionRecord:
        async with self._lock:
            session = await self.get(session_id)
            updated = replace(
                session,
                status=(SessionStatus.ARCHIVED if archived else SessionStatus.ACTIVE),
                updated_at=datetime.now(UTC),
            )
            await self.store.save(updated)
        return updated

    async def conversation(self, session_id: str) -> tuple[ModelMessage, ...]:
        session = await self.get(session_id)
        return tuple(
            ModelMessage.text(message.role, message.text)
            for message in session.messages
        )

    async def run_agent(
        self,
        loop: AgentLoop,
        definition: AgentDefinition,
        session_id: str,
        messages: Iterable[ModelMessage],
        *,
        run_id: str | None = None,
        include_history: bool = True,
        scope: ScopePath | None = None,
        cancellation: CancellationToken | None = None,
        tool_context: ToolExecutionContext | None = None,
        metadata: Mapping[str, Any] | None = None,
        event_callback: RunEventCallback | None = None,
    ) -> RunResult:
        current = tuple(messages)
        if not current:
            raise ValueError("session run needs at least one current message")
        session = await self._active(session_id)
        history = await self.conversation(session_id) if include_history else ()
        resolved_run_id = run_id or f"run-{uuid4().hex}"
        context = RunContext(
            resolved_run_id,
            (*history, *current),
            scope=scope or ScopePath.application(),
            cancellation=cancellation,
            tool_context=tool_context or ToolExecutionContext(),
            session_id=session_id,
            metadata=metadata or {},
        )
        if event_callback is None:
            result = await loop.run(definition, context)
        else:
            result = await _consume_execution(
                loop.stream(definition, context),
                event_callback,
            )
        if result.run_id != resolved_run_id:
            raise SessionError("agent returned a different run id")
        await self._record(session, definition, current, result, append_input=True)
        return result

    async def resume_agent(
        self,
        loop: ResumableAgentLoop,
        session_id: str,
        run_id: str,
        *,
        tool_context: ToolExecutionContext,
        cancellation: CancellationToken | None = None,
        event_callback: RunEventCallback | None = None,
    ) -> RunResult:
        session = await self._active(session_id)
        if not any(item.run_id == run_id for item in session.runs):
            raise SessionError("run does not belong to session")
        if event_callback is None:
            result = await loop.resume(
                run_id,
                tool_context=tool_context,
                cancellation=cancellation,
            )
        else:
            resume_stream = getattr(loop, "resume_stream", None)
            if resume_stream is None:
                raise SessionError(
                    "agent loop does not support streamed approval resume"
                )
            result = await _consume_execution(
                resume_stream(
                    run_id,
                    tool_context=tool_context,
                    cancellation=cancellation,
                ),
                event_callback,
            )
        if result.run_id != run_id:
            raise SessionError("resumed agent returned a different run id")
        await self._record(
            session,
            AgentDefinition(next(item.agent_name for item in session.runs if item.run_id == run_id)),
            (),
            result,
            append_input=False,
        )
        return result

    async def _active(self, session_id: str) -> SessionRecord:
        session = await self.get(session_id)
        if session.status is SessionStatus.ARCHIVED:
            raise SessionError("archived session is read-only")
        return session

    async def _record(
        self,
        session: SessionRecord,
        definition: AgentDefinition,
        current: tuple[ModelMessage, ...],
        result: RunResult,
        *,
        append_input: bool,
    ) -> None:
        async with self._lock:
            latest = await self.get(session.session_id)
            messages = list(latest.messages)
            if append_input:
                messages.extend(_project_messages(current, result.run_id))
            existing = next((item for item in latest.runs if item.run_id == result.run_id), None)
            if result.output and (existing is None or existing.output != result.output):
                messages.append(
                    SessionMessage(MessageRole.ASSISTANT, result.output, result.run_id)
                )
            now = datetime.now(UTC)
            run = SessionRunRecord(
                result.run_id,
                definition.name,
                result.stop_reason.value,
                result.output,
                result.usage,
                result.usage_complete,
                result.steps,
                result.tool_calls,
                result.model_calls,
                result.reported_usage_calls,
                created_at=existing.created_at if existing is not None else now,
                updated_at=now,
                cost=result.cost,
                cost_complete=result.cost_complete,
                priced_usage_calls=result.priced_usage_calls,
            )
            runs = tuple(
                run if item.run_id == result.run_id else item for item in latest.runs
            )
            if existing is None:
                runs = (*runs, run)
            await self.store.save(
                replace(
                    latest,
                    messages=tuple(messages),
                    runs=runs,
                    updated_at=now,
                )
            )


async def _consume_execution(
    execution: AgentExecution,
    event_callback: RunEventCallback,
) -> RunResult:
    """Consume one public event stream while projecting each event to a host."""

    async for event in execution:
        callback_result = event_callback(event)
        if inspect.isawaitable(callback_result):
            await callback_result
    if execution.result is None:
        raise SessionError("agent event stream completed without a result")
    return execution.result


def _project_messages(
    messages: Iterable[ModelMessage],
    run_id: str,
) -> tuple[SessionMessage, ...]:
    projected: list[SessionMessage] = []
    for message in messages:
        text = "".join(
            block.text for block in message.content if isinstance(block, TextContent)
        )
        if text:
            projected.append(SessionMessage(message.role, text, run_id))
    return tuple(projected)


def _visible_sessions(
    sessions: Iterable[SessionRecord],
    include_archived: bool,
) -> tuple[SessionRecord, ...]:
    values = (
        item
        for item in sessions
        if include_archived or item.status is SessionStatus.ACTIVE
    )
    return tuple(sorted(values, key=lambda item: item.updated_at, reverse=True))


def _aggregate_run_cost(
    runs: tuple[SessionRunRecord, ...],
) -> ModelCost | None:
    costs = tuple(run.cost for run in runs)
    if not costs or any(cost is None for cost in costs):
        return None
    total = costs[0]
    assert total is not None
    try:
        for cost in costs[1:]:
            assert cost is not None
            total = total.add(cost)
    except PricingError:
        return None
    return total


def _validate_id(value: str, label: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{label} id is not safe for local persistence")


def _session_to_data(session: SessionRecord) -> dict[str, Any]:
    return {
        "schema_version": session.schema_version,
        "session_id": session.session_id,
        "title": session.title,
        "status": session.status.value,
        "messages": [
            {
                "role": item.role.value,
                "text": item.text,
                "run_id": item.run_id,
                "created_at": item.created_at.isoformat(),
            }
            for item in session.messages
        ],
        "runs": [
            {
                "run_id": item.run_id,
                "agent_name": item.agent_name,
                "stop_reason": item.stop_reason,
                "output": item.output,
                "usage": {
                    "input_tokens": item.usage.input_tokens,
                    "output_tokens": item.usage.output_tokens,
                    "cached_input_tokens": item.usage.cached_input_tokens,
                },
                "usage_complete": item.usage_complete,
                "steps": item.steps,
                "tool_calls": item.tool_calls,
                "model_calls": item.model_calls,
                "reported_usage_calls": item.reported_usage_calls,
                "cost": _cost_to_data(item.cost),
                "cost_complete": item.cost_complete,
                "priced_usage_calls": item.priced_usage_calls,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in session.runs
        ],
        "metadata": _thaw_json(session.metadata),
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def _session_from_data(data: Mapping[str, Any]) -> SessionRecord:
    return SessionRecord(
        session_id=str(data["session_id"]),
        title=str(data["title"]),
        status=SessionStatus(str(data["status"])),
        messages=tuple(
            SessionMessage(
                MessageRole(str(item["role"])),
                str(item["text"]),
                str(item["run_id"]),
                datetime.fromisoformat(str(item["created_at"])),
            )
            for item in data.get("messages", ())
        ),
        runs=tuple(_run_from_data(item) for item in data.get("runs", ())),
        metadata=data.get("metadata", {}),
        created_at=datetime.fromisoformat(str(data["created_at"])),
        updated_at=datetime.fromisoformat(str(data["updated_at"])),
        schema_version=int(data["schema_version"]),
    )


def _run_from_data(data: Mapping[str, Any]) -> SessionRunRecord:
    usage = data["usage"]
    return SessionRunRecord(
        run_id=str(data["run_id"]),
        agent_name=str(data["agent_name"]),
        stop_reason=str(data["stop_reason"]),
        output=str(data["output"]),
        usage=TokenUsage(
            int(usage["input_tokens"]),
            int(usage["output_tokens"]),
            int(usage.get("cached_input_tokens", 0)),
        ),
        usage_complete=bool(data["usage_complete"]),
        steps=int(data["steps"]),
        tool_calls=int(data["tool_calls"]),
        model_calls=int(data.get("model_calls", 0)),
        reported_usage_calls=int(data.get("reported_usage_calls", 0)),
        cost=_cost_from_data(data.get("cost")),
        cost_complete=bool(data.get("cost_complete", False)),
        priced_usage_calls=int(data.get("priced_usage_calls", 0)),
        created_at=datetime.fromisoformat(str(data["created_at"])),
        updated_at=datetime.fromisoformat(str(data["updated_at"])),
    )


def _cost_to_data(cost: ModelCost | None) -> dict[str, str] | None:
    if cost is None:
        return None
    return {
        "currency": cost.currency,
        "price_table_version": cost.price_table_version,
        "input_cost": str(cost.input_cost),
        "output_cost": str(cost.output_cost),
        "cached_input_cost": str(cost.cached_input_cost),
    }


def _cost_from_data(data: Any) -> ModelCost | None:
    if not isinstance(data, Mapping):
        return None
    return ModelCost(
        currency=str(data["currency"]),
        price_table_version=str(data["price_table_version"]),
        input_cost=str(data.get("input_cost", "0")),
        output_cost=str(data.get("output_cost", "0")),
        cached_input_cost=str(data.get("cached_input_cost", "0")),
    )


def _validate_json(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_json(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_json(item, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} contains a non-finite number")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError(f"{path} contains a non-JSON value")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value
