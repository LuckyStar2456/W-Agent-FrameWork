"""Provider-neutral tool execution contracts."""

from __future__ import annotations

import json
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
    invocation: ToolCall | None = None
    agent_run_id: str | None = None

    def __post_init__(self) -> None:
        if self.agent_run_id is not None and (
            not isinstance(self.agent_run_id, str) or not self.agent_run_id.strip()
        ):
            raise ValueError("agent run id must be a non-empty string")
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        object.__setattr__(
            self,
            "approved_call_ids",
            frozenset(self.approved_call_ids),
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


ToolHandler = Callable[[Mapping[str, Any], ToolExecutionContext], Awaitable[Any]]


class ToolContinuationError(RuntimeError):
    """A suspended tool cannot be continued safely; never retry its start handler."""


@dataclass(frozen=True, slots=True)
class ToolContinuation:
    """Versioned JSON reference for explicit tool continuation, not authority.

    Keep payloads free of secrets and executable objects. A binding owns the
    meaning and validation of its kind/version/payload. Stores remain trusted.
    """

    kind: str
    payload: Mapping[str, Any]
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("continuation kind is required")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("continuation version must be a positive integer")
        if not isinstance(self.payload, Mapping):
            raise ValueError("continuation payload must be a JSON object")
        try:
            payload = json.loads(json.dumps(dict(self.payload), allow_nan=False))
        except (TypeError, ValueError, OverflowError):
            raise ValueError("continuation payload must be finite JSON data") from None
        object.__setattr__(self, "payload", MappingProxyType(payload))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "version": self.version, "payload": dict(self.payload)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ToolContinuation:
        if not isinstance(value, Mapping) or set(value) != {"kind", "version", "payload"}:
            raise ValueError("invalid tool continuation envelope")
        return cls(value["kind"], value["payload"], value["version"])


ToolResumeHandler = Callable[
    [Mapping[str, Any], ToolContinuation, ToolExecutionContext], Awaitable[Any]
]


@dataclass(frozen=True, slots=True)
class ToolBinding:
    """A public definition bound to one replaceable execution handler."""

    definition: ToolDefinition
    handler: ToolHandler
    side_effect: ToolSideEffect = ToolSideEffect.READ
    required_permissions: frozenset[str] = frozenset()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    resume_handler: ToolResumeHandler | None = None

    def __post_init__(self) -> None:
        if self.resume_handler is not None and not callable(self.resume_handler):
            raise ValueError("tool resume handler must be callable")
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
    continuation: ToolContinuation | None = None

    def __post_init__(self) -> None:
        if self.continuation is not None and (
            not isinstance(self.continuation, ToolContinuation)
            or self.outcome != ToolOutcome.NEEDS_APPROVAL
        ):
            raise ValueError("continuation results must await approval")

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


class ResumableToolExecutorProtocol(ToolExecutorProtocol, Protocol):
    """Optional extension; a continuation must never fall back to execute()."""

    async def resume(
        self, call: ToolCall, continuation: ToolContinuation,
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
