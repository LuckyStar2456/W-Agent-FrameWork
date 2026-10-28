"""Pure named knowledge bindings; no provider, storage or code auto-discovery."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from w_agent.knowledge_context import AsyncKnowledgeContextPolicy, KnowledgeRetriever
from w_agent.session_context import TextSessionHistoryPolicy
from w_agent.session_context_templates import SessionHistoryLimits
from w_agent.sessions import AsyncSessionHistoryPolicy, SessionHistoryPolicy, SessionRecord
from w_agent.models import ModelMessage
from w_agent.vector_retrieval import _integer, _timeout


@dataclass(frozen=True, slots=True)
class LocalKnowledgeConfig:
    """An opaque catalog selection, never a path, factory, credential or grant."""

    binding: str

    def __post_init__(self) -> None:
        if not isinstance(self.binding, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", self.binding):
            raise ValueError("knowledge.binding must be a bounded opaque name")


@dataclass(frozen=True, slots=True)
class LocalKnowledgeBinding:
    """Borrowed host retriever and context bounds; construction performs no I/O."""

    retriever: KnowledgeRetriever = field(repr=False)
    limit: int = 4
    limits: SessionHistoryLimits = field(default_factory=SessionHistoryLimits)
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if not callable(getattr(self.retriever, "retrieve", None)) or not isinstance(self.limits, SessionHistoryLimits):
            raise ValueError("knowledge binding needs a retriever and typed limits")
        _integer(self.limit, 128)
        _timeout(self.timeout)

    def context_policy(self, query: str, *, history_policy: SessionHistoryPolicy | AsyncSessionHistoryPolicy | None = None,
                       include_history: bool = True) -> AsyncKnowledgeContextPolicy:
        """Build a fresh per-call policy; do not infer query or share mutable state."""
        if type(include_history) is not bool:
            raise ValueError("knowledge history switch must be boolean")
        selected_history = history_policy if history_policy is not None else TextSessionHistoryPolicy()
        if not include_history:
            selected_history = _NoHistory()
        return AsyncKnowledgeContextPolicy(
            query, self.retriever,
            history_policy=selected_history,
            limit=self.limit, limits=self.limits, timeout=self.timeout,
        )


class _NoHistory:
    def project(self, session: SessionRecord) -> tuple[ModelMessage, ...]:
        return ()
