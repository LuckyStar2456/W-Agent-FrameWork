"""Open agent-loop contracts shared by built-in and third-party runtimes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from w_agent.kernel import ScopePath
from w_agent.models import (
    AttemptRecord,
    CancellationToken,
    ModelCost,
    ModelMessage,
    TokenUsage,
    ToolCallContent,
)
from w_agent.tools import ToolCall, ToolExecutionContext


class StopReason(StrEnum):
    COMPLETED = "completed"
    NEEDS_APPROVAL = "needs-approval"
    MAX_STEPS = "max-steps"
    MAX_TOOL_CALLS = "max-tool-calls"
    TOKEN_BUDGET = "token-budget"
    TOKEN_USAGE_UNAVAILABLE = "token-usage-unavailable"
    TOKEN_ESTIMATE_UNAVAILABLE = "token-estimate-unavailable"
    COST_BUDGET = "cost-budget"
    COST_UNAVAILABLE = "cost-unavailable"
    MODEL_ERROR = "model-error"
    CANCELLED = "cancelled"


class RunEventType(StrEnum):
    RUN_STARTED = "run-started"
    MODEL_STARTED = "model-started"
    MODEL_COMPLETED = "model-completed"
    MODEL_FAILED = "model-failed"
    TOKEN_USAGE = "token-usage"
    TOKEN_ESTIMATED = "token-estimated"
    TOKEN_ESTIMATE_UNAVAILABLE = "token-estimate-unavailable"
    TOKEN_BUDGET_WARNING = "token-budget-warning"
    TOKEN_BUDGET_STOPPED = "token-budget-stopped"
    COST_USAGE = "cost-usage"
    COST_BUDGET_STOPPED = "cost-budget-stopped"
    TOOL_REQUESTED = "tool-requested"
    TOOL_COMPLETED = "tool-completed"
    RUN_RESUMED = "run-resumed"
    RUN_COMPLETED = "run-completed"


class CheckpointStatus(StrEnum):
    PENDING_APPROVAL = "pending-approval"
    READY = "ready"
    RESUMING = "resuming"


@dataclass(frozen=True, slots=True)
class TokenBudget:
    """Cumulative provider-reported token limits for one agent run."""

    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    require_usage: bool = False
    require_estimate: bool = False
    soft_limit_ratio: Decimal | str | int | float | None = None

    def __post_init__(self) -> None:
        limits = (
            self.max_input_tokens,
            self.max_output_tokens,
            self.max_total_tokens,
        )
        if any(value is not None and value <= 0 for value in limits):
            raise ValueError("token budget limits must be positive")
        if not isinstance(self.require_usage, bool) or not isinstance(
            self.require_estimate, bool
        ):
            raise ValueError("token budget requirement flags must be booleans")
        if self.soft_limit_ratio is not None:
            if isinstance(self.soft_limit_ratio, bool):
                raise ValueError("soft token limit ratio must be between 0 and 1")
            try:
                ratio = (
                    self.soft_limit_ratio
                    if isinstance(self.soft_limit_ratio, Decimal)
                    else Decimal(str(self.soft_limit_ratio))
                )
            except (InvalidOperation, ValueError) as error:
                raise ValueError(
                    "soft token limit ratio must be between 0 and 1"
                ) from error
            if not ratio.is_finite() or ratio <= 0 or ratio > 1:
                raise ValueError("soft token limit ratio must be between 0 and 1")
            object.__setattr__(self, "soft_limit_ratio", ratio)

    def exceeded_limits(self, usage: TokenUsage) -> tuple[str, ...]:
        """Return stable names for every exceeded cumulative limit."""

        exceeded: list[str] = []
        if (
            self.max_input_tokens is not None
            and usage.input_tokens > self.max_input_tokens
        ):
            exceeded.append("input_tokens")
        if (
            self.max_output_tokens is not None
            and usage.output_tokens > self.max_output_tokens
        ):
            exceeded.append("output_tokens")
        if (
            self.max_total_tokens is not None
            and usage.total_tokens > self.max_total_tokens
        ):
            exceeded.append("total_tokens")
        return tuple(exceeded)


@dataclass(frozen=True, slots=True)
class CostBudget:
    """Cumulative monetary limit tied to one explicit price-table version."""

    max_cost: Decimal | str | int | float
    price_table_version: str
    currency: str = "USD"

    def __post_init__(self) -> None:
        if isinstance(self.max_cost, bool):
            raise ValueError("cost budget must be a positive finite decimal")
        try:
            amount = (
                self.max_cost
                if isinstance(self.max_cost, Decimal)
                else Decimal(str(self.max_cost))
            )
        except (InvalidOperation, ValueError) as error:
            raise ValueError("cost budget must be a positive finite decimal") from error
        if not amount.is_finite() or amount <= 0:
            raise ValueError("cost budget must be a positive finite decimal")
        version = self.price_table_version.strip()
        currency = self.currency.strip().upper()
        if not version or not currency:
            raise ValueError("cost budget version and currency must not be empty")
        object.__setattr__(self, "max_cost", amount)
        object.__setattr__(self, "price_table_version", version)
        object.__setattr__(self, "currency", currency)


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
    token_budget: TokenBudget | None = None
    cost_budget: CostBudget | None = None

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
    usage: TokenUsage = field(default_factory=TokenUsage)
    model_calls: int = 0
    reported_usage_calls: int = 0
    attempts: tuple[AttemptRecord, ...] = ()
    cost: ModelCost | None = None
    priced_usage_calls: int = 0

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported run checkpoint schema version")
        if min(
            self.steps,
            self.tool_calls,
            self.model_calls,
            self.reported_usage_calls,
            self.priced_usage_calls,
        ) < 0:
            raise ValueError("checkpoint counters must not be negative")
        if self.reported_usage_calls > self.model_calls:
            raise ValueError("reported usage calls cannot exceed model calls")
        if self.priced_usage_calls > self.reported_usage_calls:
            raise ValueError("priced usage calls cannot exceed reported usage calls")
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "attempts", tuple(self.attempts))
        object.__setattr__(
            self,
            "remaining_tool_calls",
            tuple(self.remaining_tool_calls),
        )


@dataclass(frozen=True, slots=True)
class RunCheckpointSummary:
    """Prompt-free discovery view for a persisted approval checkpoint."""

    run_id: str
    session_id: str | None
    status: CheckpointStatus
    agent_name: str
    pending_call_id: str | None
    pending_tool_name: str | None
    pending_argument_keys: tuple[str, ...]
    remaining_tool_calls: int
    steps: int
    tool_calls: int
    usage: TokenUsage
    model_calls: int
    reported_usage_calls: int
    cost: ModelCost | None = None
    priced_usage_calls: int = 0

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.agent_name.strip():
            raise ValueError("checkpoint summary identity must not be empty")
        if (self.pending_call_id is None) != (self.pending_tool_name is None):
            raise ValueError("checkpoint summary pending-call fields must be paired")
        if min(
            self.remaining_tool_calls,
            self.steps,
            self.tool_calls,
            self.model_calls,
            self.reported_usage_calls,
            self.priced_usage_calls,
        ) < 0:
            raise ValueError("checkpoint summary counters must not be negative")
        if self.reported_usage_calls > self.model_calls:
            raise ValueError("reported usage calls cannot exceed model calls")
        if self.priced_usage_calls > self.reported_usage_calls:
            raise ValueError("priced usage calls cannot exceed reported usage calls")
        object.__setattr__(
            self,
            "pending_argument_keys",
            tuple(self.pending_argument_keys),
        )

    @property
    def usage_complete(self) -> bool:
        return self.model_calls == self.reported_usage_calls

    @property
    def cost_complete(self) -> bool:
        return self.cost is not None and self.priced_usage_calls == self.model_calls


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
    usage: TokenUsage = field(default_factory=TokenUsage)
    model_calls: int = 0
    reported_usage_calls: int = 0
    attempts: tuple[AttemptRecord, ...] = ()
    cost: ModelCost | None = None
    priced_usage_calls: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "attempts", tuple(self.attempts))

    @property
    def usage_complete(self) -> bool:
        """Whether every model attempt supplied usage metadata."""

        return self.reported_usage_calls == self.model_calls

    @property
    def cost_complete(self) -> bool:
        """Whether every model attempt was priced by one table version."""

        return self.cost is not None and self.priced_usage_calls == self.model_calls


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
