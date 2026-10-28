"""Read persisted agent events after a run or client connection is interrupted."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable

from w_agent.models import FinishReason
from w_agent.tools import ToolOutcome

from .persistence import RunStoreError
from .types import CheckpointStatus, RunEvent, RunEventType, StopReason


_SAFE_COUNT_FIELDS = (
    "step",
    "tool_count",
    "block_index",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_input_tokens",
    "estimated_input_tokens",
    "projected_input_tokens",
    "projected_total_tokens",
    "max_output_tokens",
    "model_calls",
    "reported_usage_calls",
    "priced_usage_calls",
    "route_count",
    "attempt_count",
    "tool_calls",
)
_SAFE_FLAG_FIELDS = (
    "usage_reported",
    "usage_complete",
    "attempt_usage_complete",
    "cost_complete",
    "exact",
    "conservative",
    "estimated",
)
_SAFE_ENUM_FIELDS = {
    "finish_reason": frozenset(item.value for item in FinishReason),
    "outcome": frozenset(item.value for item in ToolOutcome),
    "stop_reason": frozenset(item.value for item in StopReason),
    "checkpoint_status": frozenset(item.value for item in CheckpointStatus),
    "result_recording": frozenset({"recorded", "omitted", "failed"}),
}
_SAFE_COST_FIELDS = ("cost", "primary_attempt_cost", "projected_cost")
_SAFE_ESTIMATOR = re.compile(r"^[A-Za-z0-9_.:/-]{1,96}$")
_SAFE_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_SAFE_CURRENCY = re.compile(r"^[A-Z]{3}$")


class RunEventSource(Protocol):
    """Minimal read-only contract accepted by the replay cursor."""

    async def events(self, run_id: str) -> tuple[RunEvent, ...]: ...


@runtime_checkable
class PagedRunEventSource(Protocol):
    """Optional bounded-reading capability for large event logs."""

    async def events_page(
        self,
        run_id: str,
        after_sequence: int,
        limit: int,
    ) -> tuple[tuple[RunEvent, ...], bool]: ...


class RunEventPageSource(Protocol):
    """Replaceable validated-page reader accepted by event accumulators."""

    async def page(
        self, run_id: str, *, cursor: RunEventCursor | None = None, limit: int = 100,
    ) -> RunEventPage: ...


class RunEventProjector(Protocol):
    """Replace one authorized raw event with a JSON-compatible view."""

    def project(self, event: RunEvent) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SafeRunEventProjector:
    """Conservative projector that removes model and tool content."""

    def project(self, event: RunEvent) -> Mapping[str, Any]:
        return safe_run_event_to_dict(event)


@dataclass(frozen=True, slots=True)
class RunEventFieldPolicy:
    """Default-deny selections for top-level fields in ``RunEvent.data``."""

    include: tuple[str, ...] = ()
    mask: tuple[str, ...] = ()
    mask_value: str = "[redacted]"

    def __post_init__(self) -> None:
        include = _field_names(self.include, "include")
        mask = _field_names(self.mask, "mask")
        if set(include).intersection(mask):
            raise ValueError("run event fields cannot be included and masked")
        if (
            not isinstance(self.mask_value, str)
            or not self.mask_value
            or len(self.mask_value) > 128
            or any(ord(character) < 32 for character in self.mask_value)
        ):
            raise ValueError("run event mask value is invalid")
        object.__setattr__(self, "include", include)
        object.__setattr__(self, "mask", mask)


@dataclass(frozen=True, slots=True)
class FieldPolicyRunEventProjector:
    """Declarative exact-event allowlist with optional fixed masks.

    A ``"*"`` policy is used only when no exact event-type policy exists.
    Policies select top-level data fields; use a custom projector for nested
    transformations or application-specific authorization decisions.
    """

    policies: Mapping[RunEventType | str, RunEventFieldPolicy]

    def __post_init__(self) -> None:
        if not isinstance(self.policies, Mapping):
            raise ValueError("run event field policies must be a mapping")
        normalized: dict[str, RunEventFieldPolicy] = {}
        valid_types = frozenset(item.value for item in RunEventType)
        for event_type, policy in self.policies.items():
            key = (
                event_type.value
                if isinstance(event_type, RunEventType)
                else event_type
            )
            if not isinstance(key, str) or key not in valid_types.union({"*"}):
                raise ValueError("run event field policy has an invalid event type")
            if key in normalized:
                raise ValueError("run event field policy repeats an event type")
            if not isinstance(policy, RunEventFieldPolicy):
                raise ValueError("run event field policy entry is invalid")
            normalized[key] = policy
        object.__setattr__(self, "policies", MappingProxyType(normalized))

    def project(self, event: RunEvent) -> Mapping[str, Any]:
        if not isinstance(event, RunEvent):
            raise TypeError("field-policy projection needs a RunEvent")
        policy = self.policies.get(event.type.value)
        if policy is None:
            policy = self.policies.get("*")
        data: dict[str, Any] = {}
        if policy is not None:
            for name in policy.include:
                if name in event.data:
                    data[name] = event.data[name]
            for name in policy.mask:
                if name in event.data:
                    data[name] = policy.mask_value
        return _normalize_projection(
            {
                "sequence": event.sequence,
                "type": event.type.value,
                "created_at": event.created_at.isoformat(),
                "data": data,
            }
        )


class RunEventPathAction(StrEnum):
    """Built-in transformations for one selected nested event value."""

    COPY = "copy"
    MASK = "mask"


@dataclass(frozen=True, slots=True)
class RunEventPathRule:
    """Map one nested source path into a nested output-object path."""

    source: tuple[str | int, ...]
    target: tuple[str, ...]
    action: RunEventPathAction | str = RunEventPathAction.COPY
    mask_value: str = "[redacted]"

    def __post_init__(self) -> None:
        source = _source_path(self.source)
        target = _target_path(self.target)
        try:
            action = RunEventPathAction(self.action)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid run event path action") from error
        if (
            not isinstance(self.mask_value, str)
            or not self.mask_value
            or len(self.mask_value) > 128
            or any(ord(character) < 32 for character in self.mask_value)
        ):
            raise ValueError("run event path mask value is invalid")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "action", action)


@dataclass(frozen=True, slots=True)
class NestedFieldRunEventProjector:
    """Default-deny nested copy/mask/rename template for event data.

    Exact event-type rules win over ``"*"`` fallback rules. Source paths may
    traverse JSON objects and arrays. Targets always build JSON objects, which
    keeps collisions deterministic and makes renaming explicit.
    """

    policies: Mapping[
        RunEventType | str,
        tuple[RunEventPathRule, ...],
    ]

    def __post_init__(self) -> None:
        if not isinstance(self.policies, Mapping):
            raise ValueError("nested run event policies must be a mapping")
        normalized: dict[str, tuple[RunEventPathRule, ...]] = {}
        valid_types = frozenset(item.value for item in RunEventType)
        for event_type, raw_rules in self.policies.items():
            key = (
                event_type.value
                if isinstance(event_type, RunEventType)
                else event_type
            )
            if not isinstance(key, str) or key not in valid_types.union({"*"}):
                raise ValueError("nested run event policy has an invalid event type")
            if key in normalized:
                raise ValueError("nested run event policy repeats an event type")
            if not isinstance(raw_rules, (tuple, list)):
                raise ValueError("nested run event rules must be a sequence")
            rules = tuple(raw_rules)
            if len(rules) > 256:
                raise ValueError("nested run event policy has too many rules")
            if not all(isinstance(rule, RunEventPathRule) for rule in rules):
                raise ValueError("nested run event policy contains an invalid rule")
            _validate_target_paths(rules)
            normalized[key] = rules
        object.__setattr__(self, "policies", MappingProxyType(normalized))

    def project(self, event: RunEvent) -> Mapping[str, Any]:
        if not isinstance(event, RunEvent):
            raise TypeError("nested field projection needs a RunEvent")
        rules = self.policies.get(event.type.value)
        if rules is None:
            rules = self.policies.get("*", ())
        data: dict[str, Any] = {}
        for rule in rules:
            found, value = _read_source_path(event.data, rule.source)
            if not found:
                continue
            projected = (
                rule.mask_value
                if rule.action is RunEventPathAction.MASK
                else value
            )
            _write_target_path(data, rule.target, projected)
        return _normalize_projection(
            {
                "sequence": event.sequence,
                "type": event.type.value,
                "created_at": event.created_at.isoformat(),
                "data": data,
            }
        )


class MediaProjectionMode(StrEnum):
    """Disclosure levels for persisted standard image/audio output blocks."""

    METADATA = "metadata"
    REFERENCES = "references"
    CONTENT = "content"


@dataclass(frozen=True, slots=True)
class MultimodalRunEventProjector:
    """Project standard model media events with explicit disclosure levels.

    Metadata mode never returns a URL or inline body. References mode may
    return URL sources but still omits inline bodies. Content mode returns the
    recorded source. Non-media events are delegated to a replaceable fallback,
    which defaults to the conservative safe projector.
    """

    mode: MediaProjectionMode | str = MediaProjectionMode.METADATA
    fallback: RunEventProjector | None = None
    max_inline_bytes: int = 8 * 1024 * 1024
    max_reference_chars: int = 16_384

    def __post_init__(self) -> None:
        try:
            mode = MediaProjectionMode(self.mode)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid media projection mode") from error
        if (
            isinstance(self.max_inline_bytes, bool)
            or not isinstance(self.max_inline_bytes, int)
            or self.max_inline_bytes <= 0
        ):
            raise ValueError("media projection inline limit must be positive")
        if (
            isinstance(self.max_reference_chars, bool)
            or not isinstance(self.max_reference_chars, int)
            or self.max_reference_chars <= 0
        ):
            raise ValueError("media projection reference limit must be positive")
        fallback = (
            SafeRunEventProjector()
            if self.fallback is None
            else self.fallback
        )
        if not callable(getattr(fallback, "project", None)):
            raise ValueError("media projection fallback needs a project method")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "fallback", fallback)

    def project(self, event: RunEvent) -> Mapping[str, Any]:
        if not isinstance(event, RunEvent):
            raise TypeError("multimodal projection needs a RunEvent")
        if event.type is not RunEventType.MODEL_OUTPUT_BLOCK:
            assert self.fallback is not None
            projected = self.fallback.project(event)
            if not isinstance(projected, Mapping):
                raise TypeError("media projection fallback returned a non-object")
            return _normalize_projection(projected)
        step = _non_negative_integer(event.data.get("step"), "step")
        block_index = _non_negative_integer(
            event.data.get("block_index"),
            "block index",
        )
        block = _media_block_projection(
            event.data.get("block"),
            self.mode,
            max_inline_bytes=self.max_inline_bytes,
            max_reference_chars=self.max_reference_chars,
        )
        return _normalize_projection(
            {
                "sequence": event.sequence,
                "type": event.type.value,
                "created_at": event.created_at.isoformat(),
                "data": {
                    "step": step,
                    "block_index": block_index,
                    "block": block,
                },
            }
        )


@dataclass(frozen=True, slots=True)
class RunEventCursor:
    """A run-bound position after the last event consumed by a caller."""

    run_id: str
    sequence: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run event cursor needs a run id")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("run event cursor sequence must be an integer")
        if self.sequence < 0:
            raise ValueError("run event cursor sequence must not be negative")


@dataclass(frozen=True, slots=True)
class RunEventPage:
    """One ordered, immutable page from the event log of a single run."""

    cursor: RunEventCursor
    events: tuple[RunEvent, ...]
    next_cursor: RunEventCursor
    has_more: bool

    def __post_init__(self) -> None:
        if not isinstance(self.cursor, RunEventCursor) or not isinstance(
            self.next_cursor, RunEventCursor
        ):
            raise ValueError("run event page needs valid cursors")
        events = tuple(self.events)
        if not all(isinstance(event, RunEvent) for event in events):
            raise ValueError("run event page contains an invalid event")
        if self.cursor.run_id != self.next_cursor.run_id:
            raise ValueError("run event page cursors refer to different runs")
        expected = self.cursor.sequence + 1
        for event in events:
            if event.run_id != self.cursor.run_id or event.sequence != expected:
                raise ValueError("run event page is not contiguous")
            expected += 1
        if self.next_cursor.sequence != expected - 1:
            raise ValueError("run event page next cursor is invalid")
        if not isinstance(self.has_more, bool):
            raise ValueError("run event page has_more must be a boolean")
        if self.has_more and not events:
            raise ValueError("run event page cannot be empty with more events")
        object.__setattr__(self, "events", events)


@dataclass(frozen=True, slots=True)
class ProjectedRunEventPage:
    """One ordered page of JSON-compatible application event views."""

    cursor: RunEventCursor
    events: tuple[Mapping[str, Any], ...]
    next_cursor: RunEventCursor
    has_more: bool

    def __post_init__(self) -> None:
        if not isinstance(self.cursor, RunEventCursor) or not isinstance(
            self.next_cursor, RunEventCursor
        ):
            raise ValueError("projected run event page needs valid cursors")
        raw_events = tuple(self.events)
        if self.cursor.run_id != self.next_cursor.run_id:
            raise ValueError("projected run event page cursors refer to different runs")
        if self.next_cursor.sequence != self.cursor.sequence + len(raw_events):
            raise ValueError("projected run event page next cursor is invalid")
        if not isinstance(self.has_more, bool):
            raise ValueError("projected run event page has_more must be a boolean")
        if not all(isinstance(event, Mapping) for event in raw_events):
            raise ValueError("projected run event page contains a non-object view")
        events = tuple(_normalize_projection(event) for event in raw_events)
        if self.has_more and not events:
            raise ValueError("projected run event page cannot be empty with more events")
        object.__setattr__(self, "events", events)


class RunEventReplay:
    """Page recorded events without re-running an agent, model, or tool.

    Event data can contain model text and other application content. Callers
    decide who may read the raw log and how to redact it for a user interface.
    A new reader can use the same ``JsonlRunStore`` root after process restart.
    """

    def __init__(self, source: RunEventSource | PagedRunEventSource) -> None:
        self.source = source

    async def page(
        self,
        run_id: str,
        *,
        cursor: RunEventCursor | None = None,
        limit: int = 100,
    ) -> RunEventPage:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run event replay needs a run id")
        if cursor is not None and not isinstance(cursor, RunEventCursor):
            raise ValueError("run event replay cursor is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("run event page limit must be a positive integer")
        active_cursor = cursor or RunEventCursor(run_id)
        if active_cursor.run_id != run_id:
            raise ValueError("run event cursor belongs to another run")

        if isinstance(self.source, PagedRunEventSource):
            selected, has_more = await self.source.events_page(
                run_id,
                active_cursor.sequence,
                limit,
            )
            if len(selected) > limit:
                raise RunStoreError("run event source exceeded the page limit")
        else:
            recorded = await self.source.events(run_id)
            for expected, event in enumerate(recorded, 1):
                if (
                    not isinstance(event, RunEvent)
                    or event.run_id != run_id
                    or event.sequence != expected
                ):
                    raise RunStoreError("run event log is not contiguous")
            if active_cursor.sequence > len(recorded):
                raise RunStoreError("run event cursor is ahead of the log")
            selected = recorded[active_cursor.sequence : active_cursor.sequence + limit]
            has_more = active_cursor.sequence + len(selected) < len(recorded)
        next_cursor = RunEventCursor(run_id, active_cursor.sequence + len(selected))
        return RunEventPage(
            active_cursor,
            selected,
            next_cursor,
            has_more=has_more,
        )

    async def projected_page(
        self,
        run_id: str,
        *,
        projector: RunEventProjector | None = None,
        cursor: RunEventCursor | None = None,
        limit: int = 100,
    ) -> ProjectedRunEventPage:
        """Page events and return only validated JSON-compatible projections.

        The safe content-free projector is the default. Supplying another
        projector is an explicit application decision made after read access
        to the raw event store has already been granted.
        """

        active_projector = (
            SafeRunEventProjector() if projector is None else projector
        )
        project = getattr(active_projector, "project", None)
        if not callable(project):
            raise TypeError("run event projector needs a callable project method")
        raw_page = await self.page(run_id, cursor=cursor, limit=limit)
        projected: list[Mapping[str, Any]] = []
        for event in raw_page.events:
            try:
                view = project(event)
            except Exception as error:
                raise RunStoreError("run event projector failed") from error
            if not isinstance(view, Mapping):
                raise RunStoreError("run event projector returned a non-object view")
            try:
                projected.append(_normalize_projection(view))
            except (TypeError, ValueError) as error:
                raise RunStoreError(
                    "run event projector returned a non-JSON-compatible view"
                ) from error
        return ProjectedRunEventPage(
            raw_page.cursor,
            tuple(projected),
            raw_page.next_cursor,
            raw_page.has_more,
        )


def _field_names(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"run event {label} fields must be a sequence")
    names = tuple(value)
    for name in names:
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 128
            or any(ord(character) < 32 for character in name)
        ):
            raise ValueError(f"run event {label} field name is invalid")
    if len(set(names)) != len(names):
        raise ValueError(f"run event {label} fields must be unique")
    return names


def _source_path(value: object) -> tuple[str | int, ...]:
    if not isinstance(value, (tuple, list)) or not value or len(value) > 32:
        raise ValueError("run event source path must contain 1 to 32 segments")
    path = tuple(value)
    for segment in path:
        if isinstance(segment, str):
            if (
                not segment
                or len(segment) > 128
                or any(ord(character) < 32 for character in segment)
            ):
                raise ValueError("run event source path has an invalid key")
        elif (
            isinstance(segment, bool)
            or not isinstance(segment, int)
            or segment < 0
        ):
            raise ValueError("run event source path has an invalid index")
    return path


def _target_path(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or not value or len(value) > 32:
        raise ValueError("run event target path must contain 1 to 32 segments")
    path = tuple(value)
    for segment in path:
        if (
            not isinstance(segment, str)
            or not segment
            or len(segment) > 128
            or any(ord(character) < 32 for character in segment)
        ):
            raise ValueError("run event target path has an invalid key")
    return path


def _validate_target_paths(rules: tuple[RunEventPathRule, ...]) -> None:
    targets = [rule.target for rule in rules]
    for index, left in enumerate(targets):
        for right in targets[index + 1 :]:
            shared = min(len(left), len(right))
            if left[:shared] == right[:shared]:
                raise ValueError("nested run event target paths collide")


def _read_source_path(
    value: object,
    path: tuple[str | int, ...],
) -> tuple[bool, Any]:
    current = value
    for segment in path:
        if isinstance(segment, str) and isinstance(current, Mapping):
            if segment not in current:
                return False, None
            current = current[segment]
            continue
        if (
            isinstance(segment, int)
            and not isinstance(segment, bool)
            and isinstance(current, (list, tuple))
        ):
            if segment >= len(current):
                return False, None
            current = current[segment]
            continue
        return False, None
    return True, current


def _write_target_path(
    target: dict[str, Any],
    path: tuple[str, ...],
    value: Any,
) -> None:
    current = target
    for segment in path[:-1]:
        existing = current.get(segment)
        if existing is None:
            child: dict[str, Any] = {}
            current[segment] = child
        else:
            if not isinstance(existing, dict):
                raise ValueError("nested run event target path collides")
            child = existing
        current = child
    current[path[-1]] = value


def _non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"run event media {label} is invalid")
    return value


def _media_block_projection(
    value: object,
    mode: MediaProjectionMode,
    *,
    max_inline_bytes: int,
    max_reference_chars: int,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("run event media block must be an object")
    kind = value.get("kind")
    source = value.get("source")
    media_type = value.get("media_type")
    if kind not in {"image", "audio"}:
        raise ValueError("run event media block kind is invalid")
    if source not in {"url", "inline"}:
        raise ValueError("run event media block source is invalid")
    if media_type is not None and (
        not isinstance(media_type, str)
        or not media_type
        or len(media_type) > 255
        or any(ord(character) < 32 for character in media_type)
    ):
        raise ValueError("run event media type is invalid")
    projected: dict[str, Any] = {
        "kind": kind,
        "source": source,
        "media_type": media_type,
    }
    if source == "url":
        url = value.get("url")
        if (
            not isinstance(url, str)
            or not url
            or len(url) > max_reference_chars
            or any(ord(character) < 32 for character in url)
        ):
            raise ValueError("run event media URL is invalid")
        if mode in {MediaProjectionMode.REFERENCES, MediaProjectionMode.CONTENT}:
            projected["url"] = url
        return projected

    size_bytes = _non_negative_integer(value.get("size_bytes"), "size")
    digest = value.get("sha256")
    encoded = value.get("data_base64")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("run event media digest is invalid")
    if size_bytes > max_inline_bytes:
        raise ValueError("run event inline media exceeds the projection limit")
    max_encoded_chars = ((max_inline_bytes + 2) // 3) * 4
    if not isinstance(encoded, str) or len(encoded) > max_encoded_chars:
        raise ValueError("run event inline media content is invalid")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("run event inline media content is invalid") from error
    if len(raw) != size_bytes or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("run event inline media integrity check failed")
    projected["size_bytes"] = size_bytes
    projected["sha256"] = digest
    if mode is MediaProjectionMode.CONTENT:
        projected["data_base64"] = encoded
    return projected


def _normalize_projection(value: object, *, _depth: int = 0) -> Any:
    if _depth > 32:
        raise ValueError("run event projection is too deeply nested")
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("run event projection contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("run event projection keys must be strings")
            normalized[key] = _normalize_projection(item, _depth=_depth + 1)
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _normalize_projection(item, _depth=_depth + 1)
            for item in value
        ]
    raise TypeError("run event projection contains an unsupported value")


def safe_run_event_to_dict(event: RunEvent) -> dict[str, Any]:
    """Project a recorded or live event without model/tool content.

    Hosts may use their own projector after applying their own read authority.
    This conservative default does not return text, arguments, results, raw
    errors, metadata, or unconstrained identifiers from event data.
    """

    if not isinstance(event, RunEvent):
        raise TypeError("safe event projection needs a RunEvent")
    data: dict[str, Any] = {}
    for name in _SAFE_COUNT_FIELDS:
        value = event.data.get(name)
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 10**18
        ):
            data[name] = value
    for name in _SAFE_FLAG_FIELDS:
        value = event.data.get(name)
        if isinstance(value, bool):
            data[name] = value
    for name, allowed in _SAFE_ENUM_FIELDS.items():
        value = event.data.get(name)
        if isinstance(value, str) and value in allowed:
            data[name] = value
    estimator = event.data.get("estimator")
    if isinstance(estimator, str) and _SAFE_ESTIMATOR.fullmatch(estimator):
        data["estimator"] = estimator
    for name in ("soft_limit_ratio", "max_cost"):
        value = event.data.get(name)
        if (
            isinstance(value, str)
            and len(value) <= 64
            and _SAFE_DECIMAL.fullmatch(value)
        ):
            data[name] = value
    for name in _SAFE_COST_FIELDS:
        value = event.data.get(name)
        if not isinstance(value, Mapping):
            continue
        total = value.get("total")
        currency = value.get("currency")
        if (
            isinstance(total, str)
            and isinstance(currency, str)
            and len(total) <= 64
            and _SAFE_DECIMAL.fullmatch(total)
            and _SAFE_CURRENCY.fullmatch(currency)
        ):
            data[name] = {"total": total, "currency": currency}
    return {
        "sequence": event.sequence,
        "type": event.type.value,
        "created_at": event.created_at.isoformat(),
        "data": data,
    }
