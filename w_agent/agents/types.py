"""Open agent-loop contracts shared by built-in and third-party runtimes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from w_agent.kernel import ScopePath
from w_agent.models import CancellationToken, ModelMessage, ToolCallContent
from w_agent.tools import ToolCall, ToolExecutionContext


class StopReason(StrEnum):
    COMPLETED = "completed"
    NEEDS_APPROVAL = "needs-approval"
    MAX_STEPS = "max-steps"
    MAX_TOOL_CALLS = "max-tool-calls"
    MODEL_ERROR = "model-error"
    CANCELLED = "cancelled"


class RunEventType(StrEnum):
    RUN_STARTED = "run-started"
    MODEL_STARTED = "model-started"
    MODEL_COMPLETED = "model-completed"
    MODEL_FAILED = "model-failed"
    TOOL_REQUESTED = "tool-requested"
    TOOL_COMPLETED = "tool-completed"
    RUN_RESUMED = "run-resumed"
    RUN_COMPLETED = "run-completed"


class CheckpointStatus(StrEnum):
    PENDING_APPROVAL = "pending-approval"
    READY = "ready"
    RESUMING = "resuming"


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Replaceable loop configuration rather than an execution implementation."""

    name: str
    system_prompt: str | None = None
    model: str | None = None
    max_steps: int = 8
    max_tool_calls: int = 16
    temperature: float | None = None
    max_output_tokens: int | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("agent name must not be empty")
        if self.max_steps <= 0 or self.max_tool_calls < 0:
            raise ValueError("agent budgets are invalid")
        object.__setattr__(self, "extensions", MappingProxyType(dict(self.extensions)))


@dataclass(frozen=True, slots=True)
class RunContext:
    """One immutable run input plus application-granted tool authority."""

    run_id: str
    messages: tuple[ModelMessage, ...]
    scope: ScopePath = field(default_factory=ScopePath.application)
    cancellation: CancellationToken | None = None
    tool_context: ToolExecutionContext = field(default_factory=ToolExecutionContext)
    session_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id or not self.run_id.strip():
            raise ValueError("run id must not be empty")
        if not self.messages:
            raise ValueError("run context needs at least one message")
        if self.session_id is not None and not self.session_id.strip():
            raise ValueError("session id must not be empty")
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class RunEvent:
    sequence: int
    type: RunEventType
    run_id: str
    data: Mapping[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ValueError("run event sequence must be positive")
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True, slots=True)
class RunCheckpoint:
    """Serializable state at an approval boundary."""

    run_id: str
    definition: AgentDefinition
    scope: ScopePath
    messages: tuple[ModelMessage, ...]
    pending_tool_call: ToolCall | None
    remaining_tool_calls: tuple[ToolCallContent, ...]
    steps: int
    tool_calls: int
    latest_output: str
    session_id: str | None = None
    status: CheckpointStatus = CheckpointStatus.PENDING_APPROVAL
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported run checkpoint schema version")
        if self.steps < 0 or self.tool_calls < 0:
            raise ValueError("checkpoint counters must not be negative")
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(
            self,
            "remaining_tool_calls",
            tuple(self.remaining_tool_calls),
        )


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    stop_reason: StopReason
    output: str
    messages: tuple[ModelMessage, ...]
    events: tuple[RunEvent, ...]
    steps: int
    tool_calls: int
    pending_tool_call: ToolCall | None = None
    checkpoint_id: str | None = None


class AgentExecution(Protocol):
    result: RunResult | None

    def __aiter__(self) -> AsyncIterator[RunEvent]: ...


class AgentLoop(Protocol):
    """A reasoning strategy replaceable independently of models and tools."""

    async def run(
        self,
        definition: AgentDefinition,
        context: RunContext,
    ) -> RunResult: ...

    def stream(
        self,
        definition: AgentDefinition,
        context: RunContext,
    ) -> AgentExecution: ...
