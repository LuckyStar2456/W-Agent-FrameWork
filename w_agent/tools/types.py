"""Provider-neutral tool execution contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Protocol

from w_agent.kernel import ScopePath
from w_agent.models import CancellationToken, ToolDefinition


class ToolSideEffect(StrEnum):
    """Declared effect class used by policy and approval plugins."""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"


class ToolPolicyAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require-approval"


class ToolOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    NEEDS_APPROVAL = "needs-approval"
    TIMED_OUT = "timed-out"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One stable, scoped tool invocation requested by an agent loop."""

    id: str
    name: str
    arguments: Mapping[str, Any]
    scope: ScopePath = field(default_factory=ScopePath.application)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("tool call id must not be empty")
        if not self.name or not self.name.strip():
            raise ValueError("tool call name must not be empty")
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Authority and cancellation supplied by the local application."""

    permissions: frozenset[str] = frozenset()
    approved_call_ids: frozenset[str] = frozenset()
    cancellation: CancellationToken | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        object.__setattr__(
            self,
            "approved_call_ids",
            frozenset(self.approved_call_ids),
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


ToolHandler = Callable[[Mapping[str, Any], ToolExecutionContext], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ToolBinding:
    """A public definition bound to one replaceable execution handler."""

    definition: ToolDefinition
    handler: ToolHandler
    side_effect: ToolSideEffect = ToolSideEffect.READ
    required_permissions: frozenset[str] = frozenset()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_permissions",
            frozenset(self.required_permissions),
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ToolPolicyDecision:
    action: ToolPolicyAction
    reason: str
    policy: str


class ToolPolicy(Protocol):
    """Replaceable policy stage evaluated in the execution path."""

    async def evaluate(
        self,
        binding: ToolBinding,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolPolicyDecision: ...


@dataclass(frozen=True, slots=True)
class ToolFailure:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    tool_name: str
    outcome: ToolOutcome
    content: str = ""
    data: Any = None
    failure: ToolFailure | None = None
    policy_decision: ToolPolicyDecision | None = None

    @property
    def is_error(self) -> bool:
        return self.outcome != ToolOutcome.SUCCEEDED


class ToolExecutorProtocol(Protocol):
    """Replaceable executor consumed by agent loops and workflows."""

    async def execute(
        self,
        call: ToolCall,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult: ...


@dataclass(frozen=True, slots=True)
class ToolAuditRecord:
    """Prompt-free audit entry that excludes argument values and output."""

    call_id: str
    tool_name: str
    side_effect: ToolSideEffect | None
    argument_keys: tuple[str, ...]
    outcome: ToolOutcome
    started_at: datetime
    completed_at: datetime
    duration_ms: float
    failure_code: str | None = None
    policy: str | None = None


class ToolAuditSink(Protocol):
    async def record(self, entry: ToolAuditRecord) -> None: ...
