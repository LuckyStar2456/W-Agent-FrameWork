"""Public workflow definitions, node contracts, events, and results."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Protocol, TypeAlias

from w_agent.kernel import ScopePath
from w_agent.models import CancellationToken


class WorkflowKind(StrEnum):
    DAG = "dag"
    STATE_GRAPH = "state-graph"
    PYTHON = "python"


class WorkflowStopReason(StrEnum):
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"
    MAX_STEPS = "max-steps"


class WorkflowEventType(StrEnum):
    WORKFLOW_STARTED = "workflow-started"
    WORKFLOW_RESUMED = "workflow-resumed"
    NODE_STARTED = "node-started"
    NODE_COMPLETED = "node-completed"
    NODE_FAILED = "node-failed"
    WORKFLOW_PAUSED = "workflow-paused"
    WORKFLOW_COMPLETED = "workflow-completed"


class WorkflowCheckpointStatus(StrEnum):
    READY = "ready"
    PAUSED = "paused"
    RESUMING = "resuming"


@dataclass(frozen=True, slots=True)
class WorkflowContext:
    run_id: str
    input: Any = None
    state: Mapping[str, Any] = field(default_factory=dict)
    scope: ScopePath = field(default_factory=ScopePath.application)
    cancellation: CancellationToken | None = None
    session_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id or not self.run_id.strip():
            raise ValueError("workflow run id must not be empty")
        if self.session_id is not None and not self.session_id.strip():
            raise ValueError("session id must not be empty")
        object.__setattr__(self, "state", MappingProxyType(dict(self.state)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class WorkflowNodeContext:
    run_id: str
    node: str
    input: Any
    state: Mapping[str, Any]
    outputs: Mapping[str, Any]
    scope: ScopePath
    cancellation: CancellationToken | None
    resume_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", MappingProxyType(dict(self.state)))
        object.__setattr__(self, "outputs", MappingProxyType(dict(self.outputs)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class WorkflowNodeResult:
    output: Any = None
    state_updates: Mapping[str, Any] = field(default_factory=dict)
    next_node: str | None = None
    pause: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "state_updates",
            MappingProxyType(dict(self.state_updates)),
        )


WorkflowNodeHandler: TypeAlias = Callable[
    [WorkflowNodeContext],
    WorkflowNodeResult | Any | Awaitable[WorkflowNodeResult | Any],
]


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    name: str
    handler: WorkflowNodeHandler

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("workflow node name must not be empty")


@dataclass(frozen=True, slots=True)
class DagWorkflowDefinition:
    name: str
    nodes: tuple[WorkflowNode, ...]
    dependencies: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    version: str = "1"
    kind: WorkflowKind = field(default=WorkflowKind.DAG, init=False)

    def __post_init__(self) -> None:
        _validate_identity(self.name, self.version)
        node_names = _node_map(self.nodes)
        dependencies = {
            name: tuple(values) for name, values in self.dependencies.items()
        }
        unknown_nodes = set(dependencies) - set(node_names)
        unknown_dependencies = {
            dependency
            for values in dependencies.values()
            for dependency in values
            if dependency not in node_names
        }
        if unknown_nodes or unknown_dependencies:
            raise ValueError("DAG dependencies reference unknown nodes")
        for name in node_names:
            dependencies.setdefault(name, ())
        _assert_acyclic(tuple(node_names), dependencies)
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "dependencies", MappingProxyType(dependencies))


@dataclass(frozen=True, slots=True)
class StateGraphDefinition:
    name: str
    nodes: tuple[WorkflowNode, ...]
    entry: str
    transitions: Mapping[str, str | None] = field(default_factory=dict)
    max_steps: int = 100
    version: str = "1"
    kind: WorkflowKind = field(default=WorkflowKind.STATE_GRAPH, init=False)

    def __post_init__(self) -> None:
        _validate_identity(self.name, self.version)
        node_names = _node_map(self.nodes)
        if self.entry not in node_names:
            raise ValueError("state graph entry is unknown")
        if self.max_steps <= 0:
            raise ValueError("state graph max_steps must be positive")
        transitions = dict(self.transitions)
        for source, target in transitions.items():
            if source not in node_names or (
                target is not None and target not in node_names
            ):
                raise ValueError("state graph transition references unknown node")
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "transitions", MappingProxyType(transitions))


@dataclass(frozen=True, slots=True)
class PythonWorkflowDefinition:
    name: str
    handler: WorkflowNodeHandler
    version: str = "1"
    max_resumes: int = 100
    kind: WorkflowKind = field(default=WorkflowKind.PYTHON, init=False)

    def __post_init__(self) -> None:
        _validate_identity(self.name, self.version)
        if self.max_resumes <= 0:
            raise ValueError("python workflow max_resumes must be positive")


WorkflowDefinition: TypeAlias = (
    DagWorkflowDefinition | StateGraphDefinition | PythonWorkflowDefinition
)


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    sequence: int
    type: WorkflowEventType
    run_id: str
    data: Mapping[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ValueError("workflow event sequence must be positive")
        if not self.run_id or not self.run_id.strip():
            raise ValueError("workflow event run id must not be empty")
        if self.session_id is not None and not self.session_id.strip():
            raise ValueError("workflow event session id must not be empty")
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True, slots=True)
class WorkflowCheckpoint:
    run_id: str
    workflow_name: str
    workflow_version: str
    kind: WorkflowKind
    scope: ScopePath
    input: Any
    state: Mapping[str, Any]
    outputs: Mapping[str, Any]
    completed_nodes: tuple[str, ...]
    remaining_nodes: tuple[str, ...] = ()
    current_node: str | None = None
    graph_steps: int = 0
    resume_count: int = 0
    session_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    status: WorkflowCheckpointStatus = WorkflowCheckpointStatus.READY
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported workflow checkpoint schema version")
        if not self.run_id or not self.run_id.strip():
            raise ValueError("workflow checkpoint run id must not be empty")
        _validate_identity(self.workflow_name, self.workflow_version)
        if self.graph_steps < 0 or self.resume_count < 0:
            raise ValueError("workflow checkpoint counters must not be negative")
        if self.session_id is not None and not self.session_id.strip():
            raise ValueError("workflow checkpoint session id must not be empty")
        object.__setattr__(self, "state", MappingProxyType(dict(self.state)))
        object.__setattr__(self, "outputs", MappingProxyType(dict(self.outputs)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "completed_nodes", tuple(self.completed_nodes))
        object.__setattr__(self, "remaining_nodes", tuple(self.remaining_nodes))


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointSummary:
    """Privacy-safe checkpoint projection for discovery and recovery UIs.

    Runtime input, state, output, scope, and metadata values are deliberately
    excluded. Applications must load the full checkpoint only after selecting
    an exact run for an authorized recovery operation.
    """

    run_id: str
    workflow_name: str
    workflow_version: str
    kind: WorkflowKind
    status: WorkflowCheckpointStatus
    session_id: str | None
    current_node: str | None
    completed_nodes: tuple[str, ...]
    remaining_nodes: tuple[str, ...]
    graph_steps: int
    resume_count: int

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint: WorkflowCheckpoint,
    ) -> "WorkflowCheckpointSummary":
        return cls(
            run_id=checkpoint.run_id,
            workflow_name=checkpoint.workflow_name,
            workflow_version=checkpoint.workflow_version,
            kind=checkpoint.kind,
            status=checkpoint.status,
            session_id=checkpoint.session_id,
            current_node=checkpoint.current_node,
            completed_nodes=checkpoint.completed_nodes,
            remaining_nodes=checkpoint.remaining_nodes,
            graph_steps=checkpoint.graph_steps,
            resume_count=checkpoint.resume_count,
        )


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    run_id: str
    stop_reason: WorkflowStopReason
    output: Any
    state: Mapping[str, Any]
    outputs: Mapping[str, Any]
    events: tuple[WorkflowEvent, ...]
    completed_nodes: tuple[str, ...]
    checkpoint_id: str | None = None
    failure: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", MappingProxyType(dict(self.state)))
        object.__setattr__(self, "outputs", MappingProxyType(dict(self.outputs)))


class WorkflowEngineProtocol(Protocol):
    async def start(
        self,
        definition: WorkflowDefinition,
        context: WorkflowContext,
    ) -> WorkflowResult: ...

    async def resume(
        self,
        definition: WorkflowDefinition,
        run_id: str,
        *,
        cancellation: CancellationToken | None = None,
    ) -> WorkflowResult: ...


def _validate_identity(name: str, version: str) -> None:
    if not name or not name.strip() or not version or not version.strip():
        raise ValueError("workflow name and version must not be empty")


def _node_map(nodes: tuple[WorkflowNode, ...]) -> dict[str, WorkflowNode]:
    result = {node.name: node for node in nodes}
    if not result or len(result) != len(nodes):
        raise ValueError("workflow nodes must be non-empty and uniquely named")
    return result


def _assert_acyclic(
    nodes: tuple[str, ...],
    dependencies: Mapping[str, tuple[str, ...]],
) -> None:
    remaining = set(nodes)
    resolved: set[str] = set()
    while remaining:
        ready = {
            node for node in remaining if set(dependencies.get(node, ())) <= resolved
        }
        if not ready:
            raise ValueError("DAG contains a dependency cycle")
        resolved.update(ready)
        remaining -= ready
