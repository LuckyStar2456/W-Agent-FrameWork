"""CLI-compatible read views shared with TUI cache import; no execution authority."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from w_agent.agents import (
    JsonlRunStore, RunEventAccumulator, RunEventReplay, RunReplaySnapshot,
    TranscriptRunEventReducer,
)
from w_agent.session_replay import (
    SessionEventReplay, SessionReplaySnapshot, build_session_message_projector,
)
from w_agent.sessions import JsonSessionStore


MAX_CACHE_BYTES = 64 * 1024 * 1024


class ReplayViewError(ValueError):
    """Content-free diagnostic suitable for terminal output."""


@dataclass(frozen=True, slots=True)
class ViewOptions:
    include_text: bool = False
    include_tools: bool = False
    include_tool_results: bool = False
    media: str = "metadata"
    include_session_text: bool = False
    confirm_sensitive: bool = False
    trust_snapshot: bool = False
    input_media: str | None = None
    include_input_name: bool = False
    include_input_metadata: bool = False

    def authorize(self, snapshot: Path | None) -> None:
        # Before any snapshot or store access, including filesystem preflight.
        if self.media not in {"metadata", "references", "content"}:
            raise ReplayViewError("--media must be metadata, references, or content")
        if self.input_media not in {None, "metadata", "references", "content"}:
            raise ReplayViewError("--input-media must be metadata, references, or content")
        if type(self.include_input_name) is not bool or type(self.include_input_metadata) is not bool:
            raise ReplayViewError("input-field disclosure settings must be booleans")
        sensitive = (self.include_text or self.include_tools or self.include_tool_results
                     or self.include_session_text or self.media != "metadata"
                     or self.input_media in {"references", "content"}
                     or self.include_input_name or self.include_input_metadata)
        if (sensitive or snapshot is not None) and not self.confirm_sensitive:
            raise ReplayViewError("content or cached views require --confirm-sensitive-content")
        if snapshot is not None and not self.trust_snapshot:
            raise ReplayViewError("cached views require --trust-snapshot; use only your own trusted cache")

    def reducer(self) -> TranscriptRunEventReducer:
        return TranscriptRunEventReducer(
            include_text=self.include_text, include_tools=self.include_tools,
            include_tool_results=self.include_tool_results, media_mode=self.media,
        )


def _identifier(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ReplayViewError("view ID must be a safe local ID of 1 to 128 characters")


def _directory(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ReplayViewError("view source must be an existing directory")
    return resolved


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON value")


def _load_cache(path: Path | None, kind: str, sources: dict[str, str]) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.is_file():
        raise ReplayViewError("snapshot must be a regular local JSON file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_CACHE_BYTES + 1)
    if len(raw) > MAX_CACHE_BYTES:
        raise ReplayViewError("snapshot file exceeds 64 MiB")
    payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                         parse_constant=_reject_constant)
    if not isinstance(payload, dict) or set(payload) != {"cache", "page"}:
        raise ReplayViewError("snapshot must contain a complete CLI view response")
    cache = payload["cache"]
    if (not isinstance(payload["page"], dict) or not isinstance(cache, dict)
            or set(cache) != {"schema_version", "kind", "sources", "snapshot"}
            or type(cache["schema_version"]) is not int or cache["schema_version"] != 1
            or cache["kind"] != kind or cache["sources"] != sources
            or not isinstance(cache["snapshot"], dict)):
        raise ReplayViewError("snapshot envelope or source binding does not match this view")
    # This is a trusted cache, not a proof of redaction or unchanged historical logs.
    return cache["snapshot"]


def _render(kind: str, sources: dict[str, str], snapshot: dict[str, Any], page: dict[str, Any]) -> str:
    result = json.dumps({
        "cache": {"schema_version": 1, "kind": kind, "sources": sources, "snapshot": snapshot},
        "page": page,
    }, ensure_ascii=True, allow_nan=False, indent=2)
    # ASCII escaping also prevents terminal controls, bidi text and Rich markup execution.
    if len(result) + 1 > MAX_CACHE_BYTES:
        raise ReplayViewError("serialized view exceeds 64 MiB; no new snapshot emitted")
    return result


async def run_view(
    run_id: str, state_root: Path, *, options: ViewOptions,
    snapshot: Path | None = None, limit: int = 100,
) -> str:
    options.authorize(snapshot)
    if options.include_input_name or options.include_input_metadata:
        raise ReplayViewError("input-field disclosure requires a Session view")
    _identifier(run_id)
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ReplayViewError("--limit must be between 1 and 500")
    try:
        root = _directory(state_root)
        runs = _directory(root / "runs")
        # Match JsonlRunStore's containment rule; refuse a missing log, not a fake empty Run.
        run_dir = (runs / run_id).resolve(strict=True)
        if runs != root / "runs" or run_dir.parent != runs or not (run_dir / "events.jsonl").is_file():
            raise ReplayViewError("Run log is missing or outside the selected store")
        sources = {"runs": str(runs)}
        cached = _load_cache(snapshot, "run", sources)
        prior = RunReplaySnapshot.from_dict(cached) if cached is not None else None
        reader = RunEventAccumulator(RunEventReplay(JsonlRunStore(root)), options.reducer())
        page = await reader.page(run_id, snapshot=prior, limit=limit)
        return _render("run", sources, page.snapshot.to_dict(), {
            "events_applied": page.events_applied, "has_more": page.has_more,
        })
    except ReplayViewError:
        raise
    except Exception:
        raise ReplayViewError("Run view failed; verify source, cache, configuration and recorded events; no new snapshot emitted") from None


async def session_view(
    session_id: str, state_root: Path, session_root: Path, *, options: ViewOptions,
    snapshot: Path | None = None, run_offset: int = 0, run_limit: int = 10,
    event_limit: int = 100, allow_unscoped_events: bool = False,
) -> str:
    options.authorize(snapshot)
    _identifier(session_id)
    if type(run_offset) is not int or run_offset < 0:
        raise ReplayViewError("--run-offset must be non-negative")
    if type(run_limit) is not int or not 1 <= run_limit <= 32:
        raise ReplayViewError("--run-limit must be between 1 and 32")
    if type(event_limit) is not int or not 1 <= event_limit <= 500:
        raise ReplayViewError("--event-limit must be between 1 and 500")
    try:
        # All roots are checked before constructors (which otherwise create directories).
        root = _directory(state_root)
        runs = _directory(root / "runs")
        sessions = _directory(session_root)
        if runs != root / "runs":
            raise ReplayViewError("Run store must not be redirected outside the selected root")
        sources = {"runs": str(runs), "sessions": str(sessions)}
        cached = _load_cache(snapshot, "session", sources)
        prior = SessionReplaySnapshot.from_dict(cached) if cached is not None else None
        reader = SessionEventReplay(
            JsonSessionStore(sessions), RunEventReplay(JsonlRunStore(root)),
            reducer=options.reducer(),
            message_projector=build_session_message_projector(
                include_text=options.include_session_text, input_media=options.input_media,
                include_name=options.include_input_name, include_metadata=options.include_input_metadata,
            ),
            allow_unscoped_events=allow_unscoped_events,
        )
        page = await reader.page(session_id, snapshot=prior, run_offset=run_offset,
                                 run_limit=run_limit, event_limit=event_limit)
        return _render("session", sources, page.snapshot.to_dict(), {
            "events_applied": page.events_applied, "runs_read": list(page.runs_read),
            "next_run_offset": page.next_run_offset,
            "pending_run_ids": list(page.snapshot.pending_run_ids),
        })
    except ReplayViewError:
        raise
    except Exception:
        raise ReplayViewError("Session view failed; verify source, cache, configuration and recorded events; no new snapshot emitted") from None
