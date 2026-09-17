"""Open agent-loop contracts shared by built-in and third-party runtimes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from w_agent.kernel import ScopePath
from w_agent.models import CancellationToken, ModelMessage
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
    RUN_COMPLETED = "run-completed"


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
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id or not self.run_id.strip():
            raise ValueError("run id must not be empty")
        if not self.messages:
            raise ValueError("run context needs at least one message")
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class RunEvent:
    sequence: int
    type: RunEventType
    run_id: str
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ValueError("run event sequence must be positive")
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


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
