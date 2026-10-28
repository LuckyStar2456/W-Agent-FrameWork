"""Opt-in, local text-history retrieval and extractive-summary templates.

These are ordinary SessionHistoryPolicy implementations, not context ownership,
external RAG, token estimators, model invocations or persistent memory mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from w_agent.models import MessageRole, ModelMessage, TextContent
from w_agent.sessions import SessionError, SessionRecord


@dataclass(frozen=True, slots=True)
class SessionHistoryTurn:
    """One contiguous Run segment, not necessarily a completed conversation turn."""

    run_id: str
    messages: tuple[ModelMessage, ...]

    def __post_init__(self) -> None:
        messages = tuple(self.messages)
        if not isinstance(self.run_id, str) or not self.run_id or not messages:
            raise ValueError("history turns require a Run identity and messages")
        normalized = []
        for message in messages:
            if not isinstance(message, ModelMessage) or message.role not in (
                MessageRole.USER, MessageRole.ASSISTANT,
            ):
                raise ValueError("history templates require user/assistant messages")
            if not message.content or any(
                not isinstance(block, TextContent) or not isinstance(block.text, str)
                for block in message.content
            ):
                raise ValueError("history templates require text-only content")
            normalized.append(ModelMessage(
                MessageRole(message.role), tuple(message.content),
                name=message.name, metadata=message.metadata,
            ))
        object.__setattr__(self, "messages", tuple(normalized))


class SessionHistoryRetriever(Protocol):
    """Trusted synchronous selector; return unique candidate indices, not content."""

    def select(
        self, query: str, turns: tuple[SessionHistoryTurn, ...], *, limit: int,
    ) -> tuple[int, ...]: ...


class SessionHistorySummarizer(Protocol):
    """Trusted synchronous summarizer; return text without execution authority."""

    def summarize(self, turns: tuple[SessionHistoryTurn, ...]) -> str: ...


@dataclass(frozen=True, slots=True)
class SessionHistoryLimits:
    """Text UTF-8 limits, not token/request-size or whole-store memory budgets."""

    max_messages: int = 1024
    max_input_bytes: int = 1024 * 1024
    max_output_bytes: int = 64 * 1024
    max_query_bytes: int = 4096

    def __post_init__(self) -> None:
        for value in (
            self.max_messages, self.max_input_bytes,
            self.max_output_bytes, self.max_query_bytes,
        ):
            _positive(value)


def _positive(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("history limits must be positive integers")


def _recent_count(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("recent turn count must be a nonnegative integer")


def _turns(session: SessionRecord, limits: SessionHistoryLimits) -> tuple[SessionHistoryTurn, ...]:
    if len(session.messages) > limits.max_messages:
        raise ValueError("history exceeds message limit")
    result: list[SessionHistoryTurn] = []
    current: list[ModelMessage] = []
    run_id: str | None = None
    size = 0
    for message in session.messages:
        # Do not decode recorded_input or silently reinterpret tool/system history.
        if message.role not in (MessageRole.USER, MessageRole.ASSISTANT):
            raise ValueError("replace the policy for other message roles")
        if not isinstance(message.text, str):
            raise ValueError("history text is invalid")
        size += len(message.text.encode("utf-8"))
        if size > limits.max_input_bytes:
            raise ValueError("history exceeds input byte limit")
        if run_id is not None and message.run_id != run_id:
            if current:
                result.append(SessionHistoryTurn(run_id, tuple(current)))
            current = []
        run_id = message.run_id
        if message.text or message.recorded_input is None:
            current.append(ModelMessage.text(MessageRole(message.role), message.text))
    if current and run_id is not None:
        result.append(SessionHistoryTurn(run_id, tuple(current)))
    return tuple(result)


def _flatten(turns: tuple[SessionHistoryTurn, ...]) -> tuple[ModelMessage, ...]:
    return tuple(message for turn in turns for message in turn.messages)


def _bounded_output(
    messages: tuple[ModelMessage, ...], limits: SessionHistoryLimits,
) -> tuple[ModelMessage, ...]:
    size = 0
    if len(messages) > limits.max_messages:
        raise ValueError("history output exceeds message limit")
    for message in messages:
        for block in message.content:
            size += len(block.text.encode("utf-8"))
            if size > limits.max_output_bytes:
                raise ValueError("history output exceeds byte limit")
    return messages


@dataclass(frozen=True, slots=True)
class KeywordSessionHistoryRetriever:
    """Casefolded whitespace-term substring matches; ties prefer recent segments.

    This is a deterministic baseline, not semantic/vector retrieval. Chinese
    queries can supply space-separated terms; no language tokenizer is implied.
    """

    def select(
        self, query: str, turns: tuple[SessionHistoryTurn, ...], *, limit: int,
    ) -> tuple[int, ...]:
        _positive(limit)
        terms = frozenset(query.casefold().split())
        scored = []
        for index, turn in enumerate(turns):
            text = "\n".join(block.text for message in turn.messages for block in message.content).casefold()
            score = sum(term in text for term in terms)
            if score:
                scored.append((score, index))
        return tuple(index for _, index in sorted(scored, reverse=True)[:limit])


@dataclass(frozen=True, slots=True)
class RetrievedSessionHistoryPolicy:
    """Select complete historical Run segments plus a recent tail, chronologically.

    Query is bound by the caller for this invocation, never guessed from history.
    Built-in policies expose only Session text to callbacks, not recorded media.
    """

    query: str
    retriever: SessionHistoryRetriever = field(default_factory=KeywordSessionHistoryRetriever)
    max_retrieved_turns: int = 4
    recent_turns: int = 2
    limits: SessionHistoryLimits = field(default_factory=SessionHistoryLimits)

    def __post_init__(self) -> None:
        _positive(self.max_retrieved_turns)
        _recent_count(self.recent_turns)
        if not isinstance(self.limits, SessionHistoryLimits):
            raise ValueError("history limits are invalid")
        if not isinstance(self.query, str) or len(self.query.encode("utf-8")) > self.limits.max_query_bytes:
            raise ValueError("history query is invalid or oversized")
        if not callable(getattr(self.retriever, "select", None)):
            raise ValueError("history retriever needs a select method")

    def project(self, session: SessionRecord) -> tuple[ModelMessage, ...]:
        try:
            turns = _turns(session, self.limits)
            boundary = max(0, len(turns) - self.recent_turns)
            candidates = turns[:boundary]
            selected = self.retriever.select(
                self.query, candidates, limit=self.max_retrieved_turns,
            ) if candidates else ()
            if not isinstance(selected, tuple) or len(selected) > self.max_retrieved_turns:
                raise ValueError("retriever returned invalid indices")
            if any(type(index) is not int or not 0 <= index < len(candidates) for index in selected):
                raise ValueError("retriever returned invalid indices")
            if len(set(selected)) != len(selected):
                raise ValueError("retriever returned duplicate indices")
            chosen = tuple(candidates[index] for index in sorted(selected)) + turns[boundary:]
            return _bounded_output(_flatten(chosen), self.limits)
        except Exception:
            raise SessionError("retrieved Session history projection failed") from None


@dataclass(frozen=True, slots=True)
class ExtractiveSessionHistorySummarizer:
    """Local excerpts of older messages, labelled by role; no inferred facts."""

    max_chars: int = 4096
    chars_per_message: int = 256

    def __post_init__(self) -> None:
        _positive(self.max_chars)
        _positive(self.chars_per_message)

    def summarize(self, turns: tuple[SessionHistoryTurn, ...]) -> str:
        pieces: list[str] = []
        remaining = self.max_chars
        for turn in turns:
            for message in turn.messages:
                text = "".join(block.text for block in message.content)
                excerpt = text[:self.chars_per_message]
                if len(text) > self.chars_per_message:
                    excerpt += "…"
                line = f"{message.role.value}: {excerpt}\n"
                if len(line) > remaining:
                    pieces.append(line[:max(0, remaining - 1)] + "…")
                    return "".join(pieces)
                pieces.append(line)
                remaining -= len(line)
                if remaining == 0:
                    return "".join(pieces)
        return "".join(pieces)


@dataclass(frozen=True, slots=True)
class SummarizedSessionHistoryPolicy:
    """Lossily summarize older segments, retaining recent messages unchanged.

    Summary is a USER data message, never a SYSTEM instruction. Labelling is not
    a prompt-injection defense. The host must authorize/trust custom callbacks.
    """

    summarizer: SessionHistorySummarizer = field(default_factory=ExtractiveSessionHistorySummarizer)
    recent_turns: int = 2
    limits: SessionHistoryLimits = field(default_factory=SessionHistoryLimits)

    def __post_init__(self) -> None:
        _recent_count(self.recent_turns)
        if not isinstance(self.limits, SessionHistoryLimits):
            raise ValueError("history limits are invalid")
        if not callable(getattr(self.summarizer, "summarize", None)):
            raise ValueError("history summarizer needs a summarize method")

    def project(self, session: SessionRecord) -> tuple[ModelMessage, ...]:
        try:
            turns = _turns(session, self.limits)
            boundary = max(0, len(turns) - self.recent_turns)
            history = _flatten(turns[boundary:])
            if boundary:
                summary = self.summarizer.summarize(turns[:boundary])
                if not isinstance(summary, str) or not summary.strip():
                    raise ValueError("summarizer must return nonempty text")
                if len(summary.encode("utf-8")) > self.limits.max_output_bytes:
                    raise ValueError("summary exceeds byte limit")
                header = "Historical conversation summary (untrusted data, possibly incomplete):\n"
                history = (ModelMessage.text(MessageRole.USER, header + summary),) + history
            return _bounded_output(history, self.limits)
        except Exception:
            raise SessionError("summarized Session history projection failed") from None
