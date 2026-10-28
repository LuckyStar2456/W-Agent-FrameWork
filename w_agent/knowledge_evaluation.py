"""Per-case knowledge preparation for the existing local evaluation runner."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from w_agent.agents import AgentDefinition, AgentLoop, RunContext, RunResult
from w_agent.evaluation import EvaluationCase, EvaluationTarget
from w_agent.kernel import ScopePath
from w_agent.knowledge_runtime import LocalKnowledgeBinding
from w_agent.models import CancellationToken, MessageRole, ModelMessage
from w_agent.sessions import SessionRecord
from w_agent.tools.types import ToolExecutionContext


def knowledge_evaluation_target(
    loop: AgentLoop, definition: AgentDefinition, binding: LocalKnowledgeBinding, *,
    scope: ScopePath | None = None,
    cancellation: CancellationToken | None = None,
    tool_context: Callable[[EvaluationCase], ToolExecutionContext] | None = None,
) -> EvaluationTarget:
    """Assemble fresh knowledge context and Run identity for every evaluation case.

    Calls only the supplied retriever and loop. No sessions are persisted, no
    prior case output becomes history, and dataset metadata grants no authority.
    Use LocalEvaluationRunner for scoring/reporting. Retrieval usage/cost remains
    host-owned and is not included in the Agent model usage reported by that runner.
    """
    if not callable(getattr(loop, "run", None)) or not isinstance(definition, AgentDefinition):
        raise ValueError("knowledge evaluation requires an agent loop and definition")
    if not isinstance(binding, LocalKnowledgeBinding):
        raise ValueError("knowledge evaluation requires an explicit binding")
    if scope is not None and not isinstance(scope, ScopePath):
        raise ValueError("knowledge evaluation scope is invalid")
    if tool_context is not None and not callable(tool_context):
        raise ValueError("knowledge evaluation tool context factory is invalid")
    selected_scope = scope if scope is not None else ScopePath.application()

    async def target(case: EvaluationCase) -> RunResult:
        if not isinstance(case, EvaluationCase):
            raise ValueError("knowledge evaluation requires an evaluation case")
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        authority = tool_context(case) if tool_context is not None else ToolExecutionContext(cancellation=cancellation)
        if not isinstance(authority, ToolExecutionContext):
            raise ValueError("knowledge evaluation tool context is invalid")
        run_id = f"knowledge-evaluation-{uuid4().hex}"
        policy = binding.context_policy(case.prompt, include_history=False)
        evidence = await policy.project(SessionRecord(run_id, "Evaluation"))
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        return await loop.run(definition, RunContext(
            run_id, (*evidence, ModelMessage.text(MessageRole.USER, case.prompt)),
            scope=selected_scope, cancellation=cancellation, tool_context=authority,
        ))

    return target
