"""Open agent runtime contracts and built-in loops."""

from .persistence import (
    InMemoryRunStore,
    JsonlRunStore,
    RunResumeConflictError,
    RunStore,
    RunStoreError,
)
from .react import ReactAgentExecution, ReactAgentLoop, ReactResumeExecution
from .templates import (
    CODING_AGENT_TEMPLATE,
    CUSTOMER_SUPPORT_AGENT_TEMPLATE,
    AgentTemplate,
    coding_agent,
    customer_support_agent,
)
from .types import (
    AgentDefinition,
    AgentExecution,
    AgentLoop,
    CheckpointStatus,
    CostBudget,
    RunCheckpoint,
    RunCheckpointSummary,
    RunContext,
    RunEvent,
    RunEventType,
    RunResult,
    StopReason,
    TokenBudget,
)

__all__ = [
    "AgentDefinition",
    "AgentExecution",
    "AgentLoop",
    "AgentTemplate",
    "CODING_AGENT_TEMPLATE",
    "CUSTOMER_SUPPORT_AGENT_TEMPLATE",
    "CheckpointStatus",
    "CostBudget",
    "InMemoryRunStore",
    "JsonlRunStore",
    "ReactAgentExecution",
    "ReactAgentLoop",
    "ReactResumeExecution",
    "RunCheckpoint",
    "RunCheckpointSummary",
    "RunContext",
    "RunEvent",
    "RunEventType",
    "RunResult",
    "RunResumeConflictError",
    "RunStore",
    "RunStoreError",
    "StopReason",
    "TokenBudget",
    "coding_agent",
    "customer_support_agent",
]
