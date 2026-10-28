"""Opt-in async text-history templates for host-owned retrieval and summarization.

No transport, credentials, implicit model calls, retries or persistence. Injected
callbacks are trusted code; the host authorizes destinations and meters charges.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from typing import Protocol

from w_agent.models import MessageRole, ModelMessage
from w_agent.session_context_templates import (
    SessionHistoryLimits, SessionHistoryTurn, _bounded_output, _flatten,
    _positive, _recent_count, _turns,
)
from w_agent.sessions import SessionError, SessionRecord


class AsyncSessionHistoryRetriever(Protocol):
    """Select unique indices into bounded older segments, not arbitrary content."""

    async def select(
        self, query: str, turns: tuple[SessionHistoryTurn, ...], *, limit: int,
    ) -> tuple[int, ...]: ...


class AsyncSessionHistorySummarizer(Protocol):
    """Return summary text; externally incurred usage must be metered by the host."""

    async def summarize(self, turns: tuple[SessionHistoryTurn, ...]) -> str: ...


def _settings(limits: SessionHistoryLimits, timeout: float, recent_turns: int) -> None:
    _recent_count(recent_turns)
    if not isinstance(limits, SessionHistoryLimits):
        raise ValueError("history limits are invalid")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("history callback timeout must be finite and positive")


@dataclass(frozen=True, slots=True)
class AsyncRetrievedSessionHistoryPolicy:
    """Await a host selector, restore chronological order and retain recent text.

    The callback receives only older text segments. No media, Session metadata,
    credentials or tools are attached. The selector may perform authorized I/O;
    embedding/vector services and their charges are outside Agent Run accounting.
    """

    query: str
    retriever: AsyncSessionHistoryRetriever
    max_retrieved_turns: int = 4
    recent_turns: int = 2
    limits: SessionHistoryLimits = field(default_factory=SessionHistoryLimits)
    timeout: float = 30.0

    def __post_init__(self) -> None:
        _settings(self.limits, self.timeout, self.recent_turns)
        _positive(self.max_retrieved_turns)
        if (not isinstance(self.query, str) or not self.query.strip()
                or len(self.query.encode("utf-8")) > self.limits.max_query_bytes):
            raise ValueError("async history query must be nonempty and bounded")
        if not callable(getattr(self.retriever, "select", None)):
            raise ValueError("async history retriever needs a select method")

    async def project(self, session: SessionRecord) -> tuple[ModelMessage, ...]:
        try:
            turns = _turns(session, self.limits)
            boundary = max(0, len(turns) - self.recent_turns)
            candidates = turns[:boundary]
            _bounded_output(_flatten(turns[boundary:]), self.limits)
            selected = ()
            if candidates:
                async with asyncio.timeout(self.timeout):
                    selected = await self.retriever.select(self.query, candidates, limit=self.max_retrieved_turns)
            if not isinstance(selected, tuple) or len(selected) > self.max_retrieved_turns:
                raise ValueError("invalid selected indices")
            if any(type(index) is not int or not 0 <= index < len(candidates) for index in selected):
                raise ValueError("invalid selected index")
            if len(set(selected)) != len(selected):
                raise ValueError("duplicate selected indices")
            chosen = tuple(candidates[index] for index in sorted(selected)) + turns[boundary:]
            return _bounded_output(_flatten(chosen), self.limits)
        except Exception:
            raise SessionError("async retrieved Session history preparation failed") from None


@dataclass(frozen=True, slots=True)
class AsyncSummarizedSessionHistoryPolicy:
    """Await a host summarizer; place its lossy result in a USER data message.

    This adapter is not a model-backed summarizer or a budget controller. Hosts
    must authorize and meter any external work in their callback separately.
    Labels are not a prompt-injection defense. No callback runs without old text.
    """

    summarizer: AsyncSessionHistorySummarizer
    recent_turns: int = 2
    limits: SessionHistoryLimits = field(default_factory=SessionHistoryLimits)
    timeout: float = 30.0

    def __post_init__(self) -> None:
        _settings(self.limits, self.timeout, self.recent_turns)
        if not callable(getattr(self.summarizer, "summarize", None)):
            raise ValueError("async history summarizer needs a summarize method")

    async def project(self, session: SessionRecord) -> tuple[ModelMessage, ...]:
        try:
            turns = _turns(session, self.limits)
            boundary = max(0, len(turns) - self.recent_turns)
            history = _bounded_output(_flatten(turns[boundary:]), self.limits)
            if boundary:
                async with asyncio.timeout(self.timeout):
                    summary = await self.summarizer.summarize(turns[:boundary])
                if not isinstance(summary, str) or not summary.strip():
                    raise ValueError("summary must be nonempty text")
                if len(summary.encode("utf-8")) > self.limits.max_output_bytes:
                    raise ValueError("summary exceeds byte limit")
                header = "Historical conversation summary (untrusted data, possibly incomplete):\n"
                history = (ModelMessage.text(MessageRole.USER, header + summary),) + history
            return _bounded_output(history, self.limits)
        except Exception:
            raise SessionError("async summarized Session history preparation failed") from None
