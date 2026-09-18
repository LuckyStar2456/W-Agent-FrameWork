"""Explicit, replaceable strategies for recovering a visible model stream."""

from __future__ import annotations

from typing import Protocol

from .types import (
    BlockEnd,
    BlockStart,
    FinishEvent,
    ModelRequest,
    ModelStreamProtocolError,
    StreamEvent,
    TextContent,
    TextDelta,
    UsageEvent,
)


class StreamReplayFilter(Protocol):
    """Suppress a verified replay prefix and emit only its unseen suffix."""

    def feed(self, event: StreamEvent) -> tuple[StreamEvent, ...]: ...

    def finish(self) -> None: ...


class StreamRecoveryStrategy(Protocol):
    """Replaceable opt-in strategy used after a visible stream interruption."""

    def can_recover(
        self, request: ModelRequest, visible_events: tuple[StreamEvent, ...]
    ) -> bool: ...

    def start(
        self, request: ModelRequest, visible_events: tuple[StreamEvent, ...]
    ) -> StreamReplayFilter: ...


class VerifiedTextPrefixRecovery:
    """Replay a text-only request and suppress an exactly matching text prefix.

    This strategy deliberately supports one text block only. It rejects tools,
    usage-before-failure, multiple blocks, and divergent replay text. It is not
    enabled by default because every replay can create another billable request.
    """

    def can_recover(
        self, request: ModelRequest, visible_events: tuple[StreamEvent, ...]
    ) -> bool:
        if request.tools or not visible_events:
            return False
        try:
            _visible_text_state(visible_events)
        except ModelStreamProtocolError:
            return False
        return True

    def start(
        self, request: ModelRequest, visible_events: tuple[StreamEvent, ...]
    ) -> StreamReplayFilter:
        if not self.can_recover(request, visible_events):
            raise ModelStreamProtocolError(
                "visible stream is not eligible for verified text-prefix recovery"
            )
        index, text, closed = _visible_text_state(visible_events)
        return _VerifiedTextReplayFilter(index, text, closed)


class _VerifiedTextReplayFilter:
    def __init__(self, index: int, prefix: str, prefix_closed: bool) -> None:
        self._index = index
        self._prefix = prefix
        self._prefix_closed = prefix_closed
        self._replay_index: int | None = None
        self._replay_text = ""
        self._replay_closed = False
        self._finished = False

    def feed(self, event: StreamEvent) -> tuple[StreamEvent, ...]:
        if self._finished:
            raise self._error("replay emitted an event after finish")
        if isinstance(event, BlockStart):
            if event.block_type != "text" or self._replay_index is not None:
                raise self._error("replay is not a single text block")
            self._replay_index = event.index
            return ()
        if isinstance(event, TextDelta):
            if event.index != self._replay_index or self._replay_closed:
                raise self._error("replay text delta references an invalid block")
            before = len(self._replay_text)
            self._replay_text += event.text
            self._verify_prefix()
            if self._prefix_closed:
                return ()
            prefix_length = len(self._prefix)
            if len(self._replay_text) <= prefix_length:
                return ()
            unseen_start = max(before, prefix_length)
            unseen = self._replay_text[unseen_start:]
            return (TextDelta(self._index, unseen),) if unseen else ()
        if isinstance(event, BlockEnd):
            if event.index != self._replay_index or self._replay_closed:
                raise self._error("replay ended an invalid text block")
            if not isinstance(event.block, TextContent):
                raise self._error("replay produced non-text content")
            if event.block.text != self._replay_text:
                raise self._error("replay block conflicts with its text deltas")
            self._verify_prefix(complete=True)
            self._replay_closed = True
            if self._prefix_closed:
                return ()
            return (BlockEnd(self._index, TextContent(self._replay_text)),)
        if isinstance(event, UsageEvent):
            if not self._caught_up() or not self._replay_closed:
                raise self._error("replay reported usage before matching the prefix")
            return (event,)
        if isinstance(event, FinishEvent):
            if not self._caught_up() or not self._replay_closed:
                raise self._error("replay finished before matching the prefix")
            self._finished = True
            return (event,)
        raise self._error("replay produced a non-text stream event")

    def finish(self) -> None:
        if not self._finished:
            raise self._error("replay stream ended without finish")

    def _caught_up(self) -> bool:
        return len(self._replay_text) >= len(self._prefix)

    def _verify_prefix(self, *, complete: bool = False) -> None:
        if len(self._replay_text) <= len(self._prefix):
            if not self._prefix.startswith(self._replay_text):
                raise self._error("replay text diverged before the visible prefix")
            if complete and self._replay_text != self._prefix:
                raise self._error("replay ended before the visible prefix")
            return
        if self._prefix_closed or not self._replay_text.startswith(self._prefix):
            raise self._error("replay text diverged from the visible prefix")

    @staticmethod
    def _error(message: str) -> ModelStreamProtocolError:
        return ModelStreamProtocolError(f"verified text-prefix recovery: {message}")


def _visible_text_state(
    events: tuple[StreamEvent, ...],
) -> tuple[int, str, bool]:
    index: int | None = None
    text = ""
    closed = False
    for event in events:
        if isinstance(event, BlockStart):
            if event.block_type != "text" or index is not None:
                raise ModelStreamProtocolError("visible prefix is not one text block")
            index = event.index
        elif isinstance(event, TextDelta):
            if index is None or event.index != index or closed:
                raise ModelStreamProtocolError("visible text delta is invalid")
            text += event.text
        elif isinstance(event, BlockEnd):
            if (
                index is None
                or event.index != index
                or closed
                or not isinstance(event.block, TextContent)
                or event.block.text != text
            ):
                raise ModelStreamProtocolError("visible text block end is invalid")
            closed = True
        else:
            raise ModelStreamProtocolError(
                "visible prefix contains a non-replayable stream event"
            )
    if index is None:
        raise ModelStreamProtocolError("visible prefix has no text block")
    return index, text, closed
