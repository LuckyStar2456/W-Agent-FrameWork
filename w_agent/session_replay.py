"""Read-only Session views over text records and independently paged Run logs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol

from w_agent.agents import (
    RunEventAccumulator, RunEventCursor, RunEventPage, RunEventPageSource, RunEventReducer,
    RunReplaySnapshot, TranscriptRunEventReducer,
)
from w_agent.agents.event_accumulator import _freeze
from w_agent.agents.event_replay import _normalize_projection
from w_agent.sessions import SessionError, SessionMessage, SessionRecord, _validate_id
from w_agent.session_inputs import StandardSessionInputDecoder
from w_agent.session_message_fields import _flags, _unwrap_message_fields
from w_agent.agents.event_replay import MediaProjectionMode


class SessionReplayError(SessionError):
    """A Session display page could not be read consistently."""


class SessionRecordSource(Protocol):
    async def get(self, session_id: str) -> SessionRecord | None: ...


class SessionRunReplaySource(RunEventPageSource, Protocol):
    """RunEventReplay or an application router with the same read API."""


class SessionMessageProjector(Protocol):
    """Trusted pure projection of Session text, separate from Run disclosure."""

    @property
    def identity(self) -> str: ...

    def project(self, message: SessionMessage) -> Mapping[str, Any] | None: ...


def _positive(value: object) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("Session replay limits must be positive integers")


def _object(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Session projection must be a JSON object")
    return _freeze(_normalize_projection(value))


def _identity(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("Session replay needs a bounded projection identity")
    return value


@dataclass(frozen=True, slots=True)
class TextSessionMessageProjector:
    """Expose role/character count by default; text is an independent opt-in."""

    include_text: bool = False
    max_text_chars: int = 1_000_000

    def __post_init__(self) -> None:
        if type(self.include_text) is not bool:
            raise ValueError("include_text must be a boolean")
        _positive(self.max_text_chars)

    @property
    def identity(self) -> str:
        return f"w-agent.session-text/1/{int(self.include_text)}/{self.max_text_chars}"

    def project(self, message: SessionMessage) -> Mapping[str, Any]:
        if not isinstance(message.text, str) or len(message.text) > self.max_text_chars:
            raise ValueError("Session message text exceeds the configured limit")
        data: dict[str, Any] = {"role": message.role.value, "characters": len(message.text)}
        if self.include_text:
            data["text"] = message.text
        return data


@dataclass(frozen=True, slots=True)
class RecordedSessionMessageProjector:
    """Opt into standard input-block display, never model-context authorization."""

    include_text: bool = False
    media_mode: MediaProjectionMode | str = MediaProjectionMode.METADATA
    max_text_chars: int = 1_000_000
    max_blocks: int = 256
    max_inline_bytes: int = 8 * 1024 * 1024
    max_reference_chars: int = 16_384

    def __post_init__(self) -> None:
        TextSessionMessageProjector(self.include_text, self.max_text_chars)
        StandardSessionInputDecoder(self.max_blocks, self.max_text_chars, self.max_inline_bytes, self.max_reference_chars)
        object.__setattr__(self, "media_mode", MediaProjectionMode(self.media_mode))

    @property
    def identity(self) -> str:
        settings = [self.include_text, self.media_mode.value, self.max_text_chars,
                    self.max_blocks, self.max_inline_bytes, self.max_reference_chars]
        return "w-agent.session-recorded-view/1/" + hashlib.sha256(json.dumps(settings).encode()).hexdigest()

    def project(self, message: SessionMessage) -> Mapping[str, Any]:
        data = dict(TextSessionMessageProjector(self.include_text, self.max_text_chars).project(message))
        data["input_recorded"] = message.recorded_input is not None
        if message.recorded_input is not None:
            decoder = StandardSessionInputDecoder(self.max_blocks, self.max_text_chars,
                                                   self.max_inline_bytes, self.max_reference_chars)
            data["input_blocks"] = list(decoder.project(message.recorded_input,
                include_text=self.include_text, media_mode=self.media_mode))
        return data


@dataclass(frozen=True, slots=True)
class MessageFieldsSessionMessageProjector:
    """Wrap any content projector; field disclosure is independent and defaults off."""

    projector: SessionMessageProjector = field(default_factory=RecordedSessionMessageProjector)
    include_name: bool = False
    include_metadata: bool = False
    max_field_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        _flags(self.include_name, self.include_metadata)
        _positive(self.max_field_bytes)
        _identity(self.projector.identity)
        if not callable(getattr(self.projector, "project", None)):
            raise ValueError("message-field projection requires a content projector")

    @property
    def identity(self) -> str:
        settings = [self.projector.identity, self.include_name, self.include_metadata, self.max_field_bytes]
        return "w-agent.session-fields-view/1/" + hashlib.sha256(json.dumps(settings).encode()).hexdigest()

    def project(self, message: SessionMessage) -> Mapping[str, Any] | None:
        try:
            fields = {}
            if message.recorded_input is not None:
                content, fields = _unwrap_message_fields(message.recorded_input, self.max_field_bytes)
                message = replace(message, recorded_input=content)
            projected = self.projector.project(message)
            if projected is None:
                return None
            data = dict(projected)
            if "input_fields" in data:
                raise ValueError("content projector must not set input_fields")
            selected = {key: value for key, value in fields.items()
                        if (key == "name" and self.include_name)
                        or (key == "metadata" and self.include_metadata)}
            if selected:
                data["input_fields"] = selected
            return data
        except Exception:
            raise SessionReplayError("Session message-field projection failed") from None


def build_session_message_projector(
    *, include_text: bool = False,
    input_media: MediaProjectionMode | str | None = None,
    include_name: bool = False, include_metadata: bool = False,
) -> SessionMessageProjector:
    """Build explicit built-in disclosure without I/O or permission grants.

    Fully default text-only views retain their legacy identity. Input-block views
    use a wrapper-aware projector even when message fields themselves are hidden;
    their changed identity deliberately rejects older, incompatible caches.
    """
    _flags(include_name, include_metadata)
    projector = (TextSessionMessageProjector(include_text=include_text)
                 if input_media is None else RecordedSessionMessageProjector(
                     include_text=include_text, media_mode=input_media))
    if input_media is None and not include_name and not include_metadata:
        return projector
    return MessageFieldsSessionMessageProjector(
        projector=projector, include_name=include_name, include_metadata=include_metadata,
    )


@dataclass(frozen=True, slots=True)
class SessionRunView:
    replay: RunReplaySnapshot
    messages: tuple[Mapping[str, Any], ...] = ()
    has_more: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.replay, RunReplaySnapshot) or type(self.has_more) is not bool:
            raise ValueError("invalid Session Run view")
        if not isinstance(self.messages, (tuple, list)):
            raise ValueError("Session messages must be a sequence")
        object.__setattr__(self, "messages", tuple(_object(item) for item in self.messages))

    def to_dict(self) -> dict[str, Any]:
        return {"replay": self.replay.to_dict(), "messages": _normalize_projection(self.messages), "has_more": self.has_more}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SessionRunView:
        if not isinstance(data, Mapping) or set(data) != {"replay", "messages", "has_more"}:
            raise ValueError("invalid Session Run view envelope")
        return cls(RunReplaySnapshot.from_dict(data["replay"]), data["messages"], data["has_more"])


@dataclass(frozen=True, slots=True)
class SessionReplaySnapshot:
    """Trusted display cache, never authority, a Session record or execution state."""

    session_id: str
    projection: str
    run_ids: tuple[str, ...]
    runs: tuple[SessionRunView, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_id(self.session_id, "session")
        _identity(self.projection)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported Session replay schema")
        if not isinstance(self.run_ids, (tuple, list)) or not isinstance(self.runs, (tuple, list)):
            raise ValueError("Session replay runs must be sequences")
        ids, runs = tuple(self.run_ids), tuple(self.runs)
        for run_id in ids:
            _validate_id(run_id, "run")
        if len(set(ids)) != len(ids) or any(not isinstance(run, SessionRunView) for run in runs):
            raise ValueError("invalid Session replay runs")
        selected = tuple(run.replay.cursor.run_id for run in runs)
        if len(set(selected)) != len(selected) or tuple(key for key in ids if key in selected) != selected:
            raise ValueError("Session Run views must be an ordered subset of membership")
        object.__setattr__(self, "run_ids", ids)
        object.__setattr__(self, "runs", runs)

    @property
    def pending_run_ids(self) -> tuple[str, ...]:
        """Unvisited or last-observed nonempty tails; not a liveness guarantee."""
        views = {run.replay.cursor.run_id: run for run in self.runs}
        return tuple(key for key in self.run_ids if key not in views or views[key].has_more)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "session_id": self.session_id,
                "projection": self.projection, "run_ids": list(self.run_ids),
                "runs": [run.to_dict() for run in self.runs]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SessionReplaySnapshot:
        if not isinstance(data, Mapping) or set(data) != {"schema_version", "session_id", "projection", "run_ids", "runs"}:
            raise ValueError("invalid Session replay snapshot envelope")
        if not isinstance(data["runs"], (tuple, list)):
            raise ValueError("Session replay runs must be a sequence")
        return cls(data["session_id"], data["projection"], data["run_ids"],
                   tuple(SessionRunView.from_dict(item) for item in data["runs"]), data["schema_version"])


@dataclass(frozen=True, slots=True)
class SessionReplayPage:
    snapshot: SessionReplaySnapshot
    runs_read: tuple[str, ...]
    events_applied: int
    next_run_offset: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, SessionReplaySnapshot):
            raise ValueError("Session replay page needs a snapshot")
        if type(self.events_applied) is not int or self.events_applied < 0:
            raise ValueError("invalid Session replay event count")
        if not isinstance(self.runs_read, (tuple, list)):
            raise ValueError("Session page runs must be a sequence")
        read = tuple(self.runs_read)
        if len(set(read)) != len(read) or any(key not in self.snapshot.run_ids for key in read):
            raise ValueError("Session page read an unrelated Run")
        if self.next_run_offset is not None and (
            type(self.next_run_offset) is not int or not 0 < self.next_run_offset < len(self.snapshot.run_ids)
        ):
            raise ValueError("invalid Session next Run offset")
        object.__setattr__(self, "runs_read", read)


class _SessionBoundReplay:
    def __init__(self, source: SessionRunReplaySource, session_id: str, allow_unscoped: bool) -> None:
        self.source, self.session_id, self.allow_unscoped = source, session_id, allow_unscoped

    async def page(self, run_id: str, *, cursor: RunEventCursor | None = None, limit: int = 100) -> RunEventPage:
        cursor = cursor if cursor is not None else RunEventCursor(run_id)
        page = await self.source.page(run_id, cursor=cursor, limit=limit)
        if not isinstance(page, RunEventPage) or page.cursor != cursor or len(page.events) > limit:
            raise SessionReplayError("Run source returned an invalid page")
        for event in page.events:
            if event.session_id != self.session_id and not (event.session_id is None and self.allow_unscoped):
                raise SessionReplayError("Run event belongs to another Session")
        return page


class SessionEventReplay:
    """Build bounded batches of per-Run views without changing or executing stores.

    Run offsets paginate membership, not events. Each read Run consumes one
    event page from its own cursor. Start another sweep at offset zero to find
    new events in older Runs, including resumed approvals. Custom components
    are trusted Python; hosts pin sources and authorize content disclosure.
    """

    def __init__(
        self, sessions: SessionRecordSource, replay: SessionRunReplaySource, *,
        reducer: RunEventReducer | None = None,
        message_projector: SessionMessageProjector | None = None,
        allow_unscoped_events: bool = False,
        max_runs: int = 1024, max_messages_per_run: int = 4096,
        max_runs_per_page: int = 32, max_events_per_run_page: int = 1000,
        max_run_snapshot_bytes: int = 8 * 1024 * 1024,
        max_snapshot_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        for value in (max_runs, max_messages_per_run, max_runs_per_page, max_events_per_run_page,
                      max_run_snapshot_bytes, max_snapshot_bytes):
            _positive(value)
        if type(allow_unscoped_events) is not bool:
            raise ValueError("allow_unscoped_events must be a boolean")
        self.sessions, self.replay = sessions, replay
        self.reducer = reducer if reducer is not None else TranscriptRunEventReducer()
        self.message_projector = message_projector if message_projector is not None else TextSessionMessageProjector()
        for component, method in ((sessions, "get"), (replay, "page"), (self.reducer, "reduce"),
                                  (self.reducer, "initial_state"), (self.message_projector, "project")):
            if not callable(getattr(component, method, None)):
                raise ValueError("Session replay component is missing a required method")
        self.allow_unscoped_events = allow_unscoped_events
        self.max_runs, self.max_messages_per_run = max_runs, max_messages_per_run
        self.max_runs_per_page, self.max_events_per_run_page = max_runs_per_page, max_events_per_run_page
        self.max_run_snapshot_bytes, self.max_snapshot_bytes = max_run_snapshot_bytes, max_snapshot_bytes

    @property
    def identity(self) -> str:
        settings = [_identity(self.reducer.identity), _identity(self.message_projector.identity),
                    self.allow_unscoped_events, self.max_runs, self.max_messages_per_run,
                    self.max_runs_per_page, self.max_events_per_run_page,
                    self.max_run_snapshot_bytes, self.max_snapshot_bytes]
        return "w-agent.session-view/1/" + hashlib.sha256(json.dumps(settings).encode("utf-8")).hexdigest()

    def _bounded(self, snapshot: SessionReplaySnapshot) -> None:
        if len(json.dumps(snapshot.to_dict(), ensure_ascii=False, allow_nan=False).encode("utf-8")) > self.max_snapshot_bytes:
            raise SessionReplayError("Session replay snapshot exceeds its byte limit")

    async def page(
        self, session_id: str, *, snapshot: SessionReplaySnapshot | None = None,
        run_offset: int = 0, run_limit: int = 10, event_limit: int = 100,
    ) -> SessionReplayPage:
        _validate_id(session_id, "session")
        _positive(run_limit)
        _positive(event_limit)
        if type(run_offset) is not int or run_offset < 0:
            raise ValueError("Run offset must be a non-negative integer")
        if run_limit > self.max_runs_per_page or event_limit > self.max_events_per_run_page:
            raise ValueError("Session replay request exceeds page limits")
        try:
            identity = self.identity
        except Exception:
            raise SessionReplayError("invalid Session projection configuration") from None
        if snapshot is not None and (
            not isinstance(snapshot, SessionReplaySnapshot) or snapshot.session_id != session_id
            or snapshot.projection != identity
        ):
            raise ValueError("snapshot belongs to another Session or projection configuration")
        try:
            session = await self.sessions.get(session_id)
            if not isinstance(session, SessionRecord) or session.session_id != session_id:
                raise SessionReplayError("Session is missing or mismatched")
            ids = tuple(run.run_id for run in session.runs)
            if len(ids) > self.max_runs or len(set(ids)) != len(ids):
                raise SessionReplayError("Session membership exceeds limits or contains duplicates")
            if run_offset > len(ids):
                raise SessionReplayError("Run offset is beyond Session membership")
            if snapshot is not None:
                self._bounded(snapshot)
                if ids[:len(snapshot.run_ids)] != snapshot.run_ids:
                    raise SessionReplayError("Session membership changed; rebuild the view")
                if any(view.replay.reducer != self.reducer.identity for view in snapshot.runs):
                    raise SessionReplayError("Session snapshot contains another Run reducer")
            known = set(ids)
            if any(message.run_id not in known for message in session.messages):
                raise SessionReplayError("Session message references an unregistered Run")
            views = {view.replay.cursor.run_id: view for view in snapshot.runs} if snapshot else {}
            end = min(len(ids), run_offset + run_limit)
            selected = ids[run_offset:end]
            accumulator = RunEventAccumulator(
                _SessionBoundReplay(self.replay, session_id, self.allow_unscoped_events),
                self.reducer, max_snapshot_bytes=self.max_run_snapshot_bytes,
            )
            applied = 0
            for run_id in selected:
                messages = []
                count = 0
                message_bytes = 0
                for message in session.messages:
                    if message.run_id != run_id:
                        continue
                    count += 1
                    if count > self.max_messages_per_run:
                        raise SessionReplayError("Session message count exceeds the limit")
                    projected = self.message_projector.project(message)
                    if projected is not None:
                        value = _object(projected)
                        message_bytes += len(json.dumps(_normalize_projection(value), ensure_ascii=False, allow_nan=False).encode("utf-8"))
                        if message_bytes > self.max_snapshot_bytes:
                            raise SessionReplayError("Session message views exceed the byte limit")
                        messages.append(value)
                prior = views.get(run_id)
                page = await accumulator.page(run_id, snapshot=prior.replay if prior else None, limit=event_limit)
                applied += page.events_applied
                views[run_id] = SessionRunView(page.snapshot, tuple(messages), page.has_more)
                candidate = SessionReplaySnapshot(session_id, identity, ids, tuple(views[key] for key in ids if key in views))
                self._bounded(candidate)
            candidate = SessionReplaySnapshot(session_id, identity, ids, tuple(views[key] for key in ids if key in views))
            self._bounded(candidate)
            if self.identity != identity or await self.sessions.get(session_id) != session:
                raise SessionReplayError("Session or projection changed while reading; try again")
            return SessionReplayPage(candidate, selected, applied, end if end < len(ids) else None)
        except Exception:
            raise SessionReplayError("Session replay page failed; snapshot not advanced") from None
