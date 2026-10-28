"""Read-only, versioned accumulation of recorded RunEvents for application views."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .event_replay import (
    MediaProjectionMode, MultimodalRunEventProjector, RunEventCursor, RunEventPage, RunEventPageSource,
    _normalize_projection, safe_run_event_to_dict,
)
from .persistence import RunStoreError
from .types import RunEvent, RunEventType
from .tool_events import normalize_tool_result_event


class RunEventReducer(Protocol):
    """Replaceable pure view reducer; identity must include schema and options."""

    @property
    def identity(self) -> str: ...

    def initial_state(self) -> Mapping[str, Any]: ...

    def reduce(self, state: Mapping[str, Any], event: RunEvent) -> Mapping[str, Any]: ...


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class RunReplaySnapshot:
    """JSON view state and its consumed position, never an execution checkpoint."""

    cursor: RunEventCursor
    reducer: str
    state: Mapping[str, Any]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported replay snapshot schema")
        if not isinstance(self.cursor, RunEventCursor):
            raise ValueError("replay snapshot needs a cursor")
        if not isinstance(self.reducer, str) or not self.reducer.strip() or len(self.reducer) > 256:
            raise ValueError("replay snapshot needs a bounded reducer identity")
        if not isinstance(self.state, Mapping):
            raise ValueError("replay snapshot state must be an object")
        object.__setattr__(self, "state", _freeze(_normalize_projection(self.state)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "cursor": {"run_id": self.cursor.run_id, "sequence": self.cursor.sequence},
            "reducer": self.reducer, "state": _normalize_projection(self.state),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RunReplaySnapshot:
        if not isinstance(data, Mapping) or set(data) != {"schema_version", "cursor", "reducer", "state"}:
            raise ValueError("invalid replay snapshot envelope")
        cursor = data["cursor"]
        if not isinstance(cursor, Mapping) or set(cursor) != {"run_id", "sequence"}:
            raise ValueError("invalid replay snapshot cursor")
        return cls(RunEventCursor(cursor["run_id"], cursor["sequence"]),
                   data["reducer"], data["state"], data["schema_version"])


@dataclass(frozen=True, slots=True)
class ReducedRunEventPage:
    snapshot: RunReplaySnapshot
    events_applied: int
    has_more: bool

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, RunReplaySnapshot):
            raise ValueError("reduced page needs a replay snapshot")
        if type(self.events_applied) is not int or not 0 <= self.events_applied <= self.snapshot.cursor.sequence:
            raise ValueError("invalid reduced page event count")
        if type(self.has_more) is not bool or (self.has_more and self.events_applied == 0):
            raise ValueError("invalid reduced page continuation flag")


class RunEventAccumulator:
    """Apply one contiguous page atomically to a detached display snapshot.

    No tools, model calls, URL fetches, acknowledgements or checkpoint writes.
    Hosts authorize raw-event access and own snapshot storage. Custom reducers
    are trusted Python, not a sandbox. A failed page never modifies its input
    snapshot; persist the returned snapshot and cursor together, not separately.
    """

    def __init__(
        self, replay: RunEventPageSource, reducer: RunEventReducer, *,
        max_snapshot_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        if type(max_snapshot_bytes) is not int or max_snapshot_bytes <= 0:
            raise ValueError("snapshot byte limit must be positive")
        if not callable(getattr(reducer, "reduce", None)) or not callable(getattr(reducer, "initial_state", None)):
            raise ValueError("event reducer needs initial_state and reduce methods")
        self.replay, self.reducer = replay, reducer
        self.max_snapshot_bytes = max_snapshot_bytes

    def _bounded(self, snapshot: RunReplaySnapshot) -> None:
        encoded = json.dumps(snapshot.to_dict(), ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > self.max_snapshot_bytes:
            raise RunStoreError("replay snapshot exceeds the configured byte limit")

    async def page(
        self, run_id: str, *, snapshot: RunReplaySnapshot | None = None, limit: int = 100,
    ) -> ReducedRunEventPage:
        if type(limit) is not int or limit <= 0:
            raise ValueError("run event page limit must be a positive integer")
        identity = self.reducer.identity
        if snapshot is not None and (
            not isinstance(snapshot, RunReplaySnapshot) or snapshot.cursor.run_id != run_id
            or snapshot.reducer != identity
        ):
            raise ValueError("snapshot belongs to another run or reducer configuration")
        try:
            current = snapshot or RunReplaySnapshot(RunEventCursor(run_id), identity, self.reducer.initial_state())
            self._bounded(current)
        except (TypeError, ValueError):
            raise RunStoreError("invalid initial replay state") from None
        page = await self.replay.page(run_id, cursor=current.cursor, limit=limit)
        if not isinstance(page, RunEventPage) or page.cursor != current.cursor or len(page.events) > limit:
            raise RunStoreError("event reader returned an invalid page; snapshot not advanced")
        for event in page.events:
            try:
                # Give trusted reducers a mutable detached copy, never the input snapshot.
                state = self.reducer.reduce(_normalize_projection(current.state), event)
                current = RunReplaySnapshot(RunEventCursor(run_id, event.sequence), identity, state)
                self._bounded(current)
                if self.reducer.identity != identity:
                    raise ValueError("reducer identity changed during a page")
            except Exception:
                raise RunStoreError("run event reduction failed; snapshot not advanced") from None
        return ReducedRunEventPage(current, len(page.events), page.has_more)


@dataclass(frozen=True, slots=True)
class TranscriptRunEventReducer:
    """Rebuild recorded text/tool/media views with explicit content disclosure.

    Final model text is separate from delta blocks, never appended to them.
    Tool events remain an ordered history (including repeated approval outcomes),
    not commands. Missing recorded bodies cannot be reconstructed or inferred.
    """

    include_text: bool = False
    include_tools: bool = False
    media_mode: MediaProjectionMode | str = MediaProjectionMode.METADATA
    max_blocks: int = 1024
    max_tool_events: int = 4096
    max_text_chars: int = 1_000_000
    max_inline_bytes: int = 8 * 1024 * 1024
    max_reference_chars: int = 16_384
    include_tool_results: bool = False
    max_tool_result_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if type(self.include_text) is not bool or type(self.include_tools) is not bool:
            raise ValueError("transcript disclosure switches must be booleans")
        if type(self.include_tool_results) is not bool:
            raise ValueError("include_tool_results must be a boolean")
        for value in (self.max_blocks, self.max_tool_events, self.max_text_chars,
                      self.max_inline_bytes, self.max_reference_chars, self.max_tool_result_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError("transcript limits must be positive integers")
        object.__setattr__(self, "media_mode", MediaProjectionMode(self.media_mode))

    @property
    def identity(self) -> str:
        settings = [self.include_text, self.include_tools, self.media_mode.value,
                    self.max_blocks, self.max_tool_events, self.max_text_chars,
                    self.max_inline_bytes, self.max_reference_chars]
        version = 1
        if self.include_tool_results:
            # Preserve a6 identities when the new disclosure path is unused.
            settings.extend([self.include_tool_results, self.max_tool_result_bytes])
            version = 2
        digest = hashlib.sha256(json.dumps(settings).encode("utf-8")).hexdigest()
        return f"w-agent.transcript/{version}/{digest}"

    def initial_state(self) -> Mapping[str, Any]:
        return {"blocks": [], "models": [], "tool_events": [], "stop_reason": None,
                "usage": {}, "cost": {}}

    def _text(self, value: Any) -> str:
        if not isinstance(value, str) or len(value) > self.max_text_chars:
            raise ValueError("invalid or oversized transcript text")
        return value

    def reduce(self, state: Mapping[str, Any], event: RunEvent) -> Mapping[str, Any]:
        data = _normalize_projection(state)
        safe = safe_run_event_to_dict(event)["data"]
        kind = event.type
        if kind in {RunEventType.MODEL_TEXT_DELTA, RunEventType.MODEL_TOOL_CALL_DELTA, RunEventType.MODEL_OUTPUT_BLOCK}:
            step, index = event.data.get("step"), event.data.get("block_index")
            if type(step) is not int or step < 0 or type(index) is not int or index < 0:
                raise ValueError("invalid transcript block position")
            block_kind = {RunEventType.MODEL_TEXT_DELTA: "text", RunEventType.MODEL_TOOL_CALL_DELTA: "tool-call",
                          RunEventType.MODEL_OUTPUT_BLOCK: "media"}[kind]
            matches = [item for item in data["blocks"] if item["step"] == step and item["block_index"] == index]
            if matches:
                block = matches[0]
                if block["kind"] != block_kind or kind is RunEventType.MODEL_OUTPUT_BLOCK:
                    raise ValueError("conflicting transcript block")
            else:
                if len(data["blocks"]) >= self.max_blocks:
                    raise ValueError("transcript block limit exceeded")
                block = {"step": step, "block_index": index, "kind": block_kind, "characters": 0}
                data["blocks"].append(block)
            if kind is RunEventType.MODEL_OUTPUT_BLOCK:
                block["media"] = MultimodalRunEventProjector(
                    self.media_mode, max_inline_bytes=self.max_inline_bytes,
                    max_reference_chars=self.max_reference_chars,
                ).project(event)["data"]["block"]
            else:
                text = self._text(event.data.get("text" if block_kind == "text" else "arguments_delta", ""))
                block["characters"] += len(text)
                if block["characters"] > self.max_text_chars:
                    raise ValueError("transcript text limit exceeded")
                if block_kind == "text" and self.include_text:
                    block["text"] = block.get("text", "") + text
                elif block_kind == "tool-call" and self.include_tools:
                    block["arguments_delta"] = block.get("arguments_delta", "") + text
                    for field in ("call_id", "name"):
                        value = event.data.get(field)
                        if value is not None and value != "":
                            value = self._text(value)
                            if field in block and block[field] != value:
                                raise ValueError("tool delta identity changed")
                            block[field] = value
        elif kind is RunEventType.MODEL_COMPLETED:
            if len(data["models"]) >= self.max_blocks:
                raise ValueError("transcript model limit exceeded")
            model = dict(safe)
            model["sequence"] = event.sequence
            if self.include_text:
                model["text"] = self._text(event.data.get("text", ""))
            data["models"].append(model)
        elif kind in {RunEventType.TOOL_REQUESTED, RunEventType.TOOL_COMPLETED}:
            if len(data["tool_events"]) >= self.max_tool_events:
                raise ValueError("transcript tool event limit exceeded")
            tool = {"sequence": event.sequence, "type": kind.value, **safe}
            if self.include_tools:
                for field in ("call_id", "name"):
                    tool[field] = self._text(event.data.get(field))
                if kind is RunEventType.TOOL_REQUESTED:
                    arguments = event.data.get("arguments")
                    if not isinstance(arguments, Mapping):
                        raise ValueError("tool request arguments must be an object")
                    tool["arguments"] = _normalize_projection(arguments)
            if self.include_tool_results and kind is RunEventType.TOOL_COMPLETED:
                status = event.data.get("result_recording")
                has_result = "result" in event.data
                if status is None and not has_result:
                    pass  # Old logs or an approval boundary have no recorded body.
                elif status not in {"recorded", "omitted", "failed"}:
                    raise ValueError("invalid tool result recording status")
                elif event.data.get("outcome") == "needs-approval":
                    raise ValueError("pending approval cannot contain a tool result")
                elif status == "recorded" and has_result:
                    tool["result"] = normalize_tool_result_event(
                        event.data["result"], max_bytes=self.max_tool_result_bytes,
                    )
                elif status == "recorded" or has_result:
                    raise ValueError("tool result body and recording status disagree")
            data["tool_events"].append(tool)
        elif kind is RunEventType.RUN_COMPLETED:
            data["stop_reason"] = safe.get("stop_reason")
        elif kind is RunEventType.RUN_RESUMED:
            data["stop_reason"] = None
        elif kind is RunEventType.TOKEN_USAGE:
            data["usage"] = safe  # Run-level cumulative counters, never sum snapshots.
        elif kind is RunEventType.COST_USAGE:
            data["cost"] = safe
        return data
