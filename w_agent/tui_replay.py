"""Optional replay panel with explicit trusted-cache import and new-file export."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Checkbox, Input, Label, Static
from textual.worker import Worker

from w_agent._cli_replay import ViewOptions, _render, run_view, session_view
from w_agent.agents import (
    JsonlRunStore, RunEventAccumulator, RunEventReplay, RunReplaySnapshot,
    TranscriptRunEventReducer,
)
from w_agent.session_replay import (
    SessionEventReplay, SessionReplaySnapshot, build_session_message_projector,
)
from w_agent.sessions import JsonSessionStore
from w_agent.media_display import MediaDisplay
from w_agent.tui_media import ReplayMediaPanel


@dataclass(frozen=True, slots=True)
class ReplaySelection:
    kind: str
    identifier: str
    state_root: Path
    session_root: Path
    text: bool = False
    tools: bool = False
    results: bool = False
    session_text: bool = False
    media: str = "metadata"
    unscoped: bool = False
    input_media: str = "off"
    input_name: bool = False
    input_metadata: bool = False

    @property
    def sensitive(self) -> bool:
        return (self.text or self.tools or self.results or self.session_text or self.media != "metadata"
                or self.input_media in {"references", "content"} or self.input_name or self.input_metadata)


@dataclass(frozen=True, slots=True)
class ReplayView:
    selection: ReplaySelection
    snapshot: RunReplaySnapshot | SessionReplaySnapshot
    body: str
    summary: str
    next_run_offset: int = 0


class ReplayReadError(ValueError):
    """Fixed, content-free presentation diagnostic."""


def _snapshot_body(snapshot: RunReplaySnapshot | SessionReplaySnapshot) -> str:
    body = json.dumps(snapshot.to_dict(), ensure_ascii=True, allow_nan=False, indent=2)
    if len(body) > 64 * 1024 * 1024:
        raise ReplayReadError("Escaped display exceeds 64 MiB; view not advanced.")
    return body


async def import_replay_view(
    selection: ReplaySelection, path: Path, *, confirmed: bool = False,
    trusted: bool = False, event_limit: int = 100, run_limit: int = 10,
    run_offset: int = 0,
) -> ReplayView:
    """Import a trusted CLI/TUI cache and read one batch from its bound stores.

    This is not offline viewing or authenticity validation. Never infer settings
    or authority from cache data; the user supplies the selection independently.
    """
    if confirmed is not True or trusted is not True:
        raise ReplayReadError("Type VIEW CONTENT and TRUST CACHE for this import.")
    if selection.kind not in {"run", "session"}:
        raise ReplayReadError("Kind must be run/session.")
    if selection.input_media not in {"off", "metadata", "references", "content"}:
        raise ReplayReadError("Input media must be off/metadata/references/content.")
    if (type(event_limit) is not int or not 1 <= event_limit <= 500
            or type(run_limit) is not int or not 1 <= run_limit <= 32
            or type(run_offset) is not int or run_offset < 0):
        raise ReplayReadError("Events: 1–500; Runs: 1–32; offset: non-negative.")
    options = ViewOptions(
        include_text=selection.text, include_tools=selection.tools,
        include_tool_results=selection.results, media=selection.media,
        include_session_text=selection.session_text, confirm_sensitive=True,
        trust_snapshot=True, input_media=None if selection.input_media == "off" else selection.input_media,
        include_input_name=selection.input_name, include_input_metadata=selection.input_metadata,
    )
    try:
        if selection.kind == "run":
            rendered = await run_view(selection.identifier, selection.state_root,
                                      options=options, snapshot=path, limit=event_limit)
        else:
            rendered = await session_view(
                selection.identifier, selection.state_root, selection.session_root,
                options=options, snapshot=path, run_offset=run_offset,
                run_limit=run_limit, event_limit=event_limit,
                allow_unscoped_events=selection.unscoped,
            )
        payload = json.loads(rendered)
        data, page = payload["cache"]["snapshot"], payload["page"]
        snapshot = (RunReplaySnapshot.from_dict(data) if selection.kind == "run"
                    else SessionReplaySnapshot.from_dict(data))
        current = replace(selection, state_root=selection.state_root.resolve(strict=True),
                          session_root=selection.session_root.resolve())
        next_offset = page.get("next_run_offset") or 0
        summary = (f"Trusted cache imported; applied {page['events_applied']} new recorded events. "
                   f"Next membership offset: {next_offset}. Not execution completion or authenticity proof.")
        return ReplayView(current, snapshot, _snapshot_body(snapshot), summary, next_offset)
    except Exception:
        raise ReplayReadError("Cache import failed; check trust, sources, ID, projection and limits. Prior view retained.") from None


def export_replay_view(
    view: ReplayView, path: Path, *, confirmed: bool = False, save_confirmed: bool = False,
) -> None:
    """Write a CLI-compatible cache to a new JSON file, never replace a file.

    No directories are created. A failed write can leave a partial new file;
    no automatic retry, deletion, or rollback is attempted.
    """
    if confirmed is not True or save_confirmed is not True:
        raise ReplayReadError("Type VIEW CONTENT and SAVE CACHE for this export.")
    try:
        selection = view.selection
        root = selection.state_root.resolve(strict=True)
        sessions = selection.session_root.resolve()
        if root != selection.state_root or sessions != selection.session_root:
            raise ReplayReadError("Source paths changed; rebuild the view before exporting.")
        if (root / "runs").resolve() != root / "runs":
            raise ReplayReadError("Run store was redirected; rebuild the view before exporting.")
        target = path.parent.resolve(strict=True) / path.name
        # Prevent writing new files into the selected authoritative stores.
        if (path.suffix.lower() != ".json" or ":" in path.name or path.is_reserved()
                or target.is_relative_to(root / "runs")
                or target.is_relative_to(sessions)):
            raise ReplayReadError("Choose a new .json file outside the selected Run and Session stores.")
        sources = {"runs": str(root / "runs")}
        if selection.kind == "session":
            sources["sessions"] = str(sessions)
        body = _render(selection.kind, sources, view.snapshot.to_dict(), {
            "next_run_offset": view.next_run_offset or None,
            "exported_view": True,
        })
        # Exclusive creation also rejects existing files and final-path symlinks.
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(body + "\n")
    except ReplayReadError:
        raise
    except Exception:
        raise ReplayReadError("Cache export failed; no existing file replaced. A partial new file may remain.") from None


async def read_replay_view(
    selection: ReplaySelection, prior: ReplayView | None = None, *,
    confirmed: bool = False, event_limit: int = 100, run_limit: int = 10,
    run_offset: int = 0,
) -> ReplayView:
    """Read one batch, returning a new immutable view only after complete success."""
    if selection.sensitive and not confirmed:
        raise ReplayReadError("Type VIEW CONTENT for this sensitive read.")
    if selection.kind not in {"run", "session"} or selection.media not in {"metadata", "references", "content"}:
        raise ReplayReadError("Kind must be run/session; media must be metadata/references/content.")
    if selection.input_media not in {"off", "metadata", "references", "content"}:
        raise ReplayReadError("Input media must be off/metadata/references/content.")
    if type(selection.input_name) is not bool or type(selection.input_metadata) is not bool:
        raise ReplayReadError("Input-field disclosure settings must be booleans.")
    if selection.kind != "session" and (selection.input_name or selection.input_metadata):
        raise ReplayReadError("Input-field disclosure requires Session mode.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", selection.identifier):
        raise ReplayReadError("Enter a safe local ID of 1 to 128 characters.")
    if (type(event_limit) is not int or not 1 <= event_limit <= 500
            or type(run_limit) is not int or not 1 <= run_limit <= 32
            or type(run_offset) is not int or run_offset < 0):
        raise ReplayReadError("Events: 1–500; Runs: 1–32; offset: non-negative.")
    try:
        root = selection.state_root.resolve(strict=True)
        runs = root / "runs"
        sessions = selection.session_root.resolve()
        if not runs.is_dir() or runs.resolve() != runs:
            raise ReplayReadError("Select an existing, unredirected Run store.")
        if selection.kind == "session" and not sessions.is_dir():
            raise ReplayReadError("Select an existing Session store.")
        current = replace(selection, state_root=root, session_root=sessions)
        if prior is not None and prior.selection != current:
            raise ReplayReadError("Selection changed; clear the view before reading again.")
        if current.kind == "run":
            path = (runs / current.identifier).resolve()
            if path.parent != runs or not (path / "events.jsonl").is_file():
                raise ReplayReadError("The selected Run log does not exist in this store.")
        reducer = TranscriptRunEventReducer(
            include_text=current.text, include_tools=current.tools,
            include_tool_results=current.results, media_mode=current.media,
        )
        replay = RunEventReplay(JsonlRunStore(root))
        if current.kind == "run":
            page = await RunEventAccumulator(replay, reducer).page(
                current.identifier, snapshot=prior.snapshot if prior else None, limit=event_limit,
            )
            snapshot = page.snapshot
            summary = (f"Run sequence {snapshot.cursor.sequence}; applied {page.events_applied}; "
                       f"more recorded events: {page.has_more}. Not execution completion.")
            next_offset = 0
        else:
            page = await SessionEventReplay(
                JsonSessionStore(sessions), replay, reducer=reducer,
                message_projector=build_session_message_projector(
                    include_text=current.session_text,
                    input_media=None if current.input_media == "off" else current.input_media,
                    include_name=current.input_name, include_metadata=current.input_metadata,
                ),
                allow_unscoped_events=current.unscoped,
            ).page(current.identifier, snapshot=prior.snapshot if prior else None,
                   event_limit=event_limit, run_limit=run_limit, run_offset=run_offset)
            snapshot = page.snapshot
            next_offset = page.next_run_offset if page.next_run_offset is not None else 0
            summary = (f"Read {len(page.runs_read)} Runs; applied {page.events_applied}; "
                       f"pending views: {len(snapshot.pending_run_ids)}; next membership offset: {next_offset}. "
                       "Zero starts another sweep, not execution completion.")
        body = _snapshot_body(snapshot)
        return ReplayView(current, snapshot, body, summary, next_offset)
    except ReplayReadError:
        raise
    except Exception:
        raise ReplayReadError("Read failed; check stores, membership and recorded events. View not advanced.") from None


_INPUTS = ("kind", "id", "state-root", "session-root", "media", "input-media", "event-limit", "run-limit", "offset", "confirm",
           "cache-path", "cache-confirm")
_FLAGS = ("text", "tools", "results", "session-text", "unscoped", "input-name", "input-metadata")
_SELECTION_INPUTS = {"kind", "id", "state-root", "session-root", "media", "input-media"}
DISPLAY_CHARS = 16_000


class ReplayPanel(Vertical):
    """Explicit reads and cache writes, with no Agent execution actions."""

    DEFAULT_CSS = """
    ReplayPanel { height: auto; }
    ReplayPanel #replay-body { height: auto; min-height: 8; }
    """

    def __init__(self, workspace: Path, *, media_renderer: MediaDisplay | None = None) -> None:
        super().__init__()
        self.workspace = workspace
        self._view: ReplayView | None = None
        self._worker: Worker[None] | None = None
        self._busy = False
        self._closing = False
        self._generation = 0
        self._display_offset = 0
        self.media_panel = ReplayMediaPanel(workspace, renderer=media_renderer)

    def compose(self) -> ComposeResult:
        yield Label("Recorded content / 记录回放 — no model/tool execution; cache writes require explicit confirmation")
        yield Label("Kind (run/session), exact ID, Run state root, Session root")
        yield Input(value="run", id="replay-kind")
        yield Input(placeholder="Exact Run or Session ID", id="replay-id")
        yield Input(value=".wagent", id="replay-state-root")
        yield Input(value=".wagent/sessions", id="replay-session-root")
        yield Checkbox("Model text / 模型文本", id="replay-text")
        yield Checkbox("Tool identity and arguments / 工具身份与参数", id="replay-tools")
        yield Checkbox("Recorded tool results / 工具结果正文", id="replay-results")
        yield Checkbox("Session message text / Session 文本", id="replay-session-text")
        yield Checkbox("Recorded input names / 已记录输入名称 (Session only)", id="replay-input-name")
        yield Checkbox("Recorded input metadata / 已记录输入元数据 (Session only)", id="replay-input-metadata")
        yield Checkbox("Legacy events with no Session ID / 接受无 Session ID 的旧事件", id="replay-unscoped")
        yield Label("Media: metadata / references / content (never fetched)")
        yield Input(value="metadata", id="replay-media")
        yield Label("Session input media / 输入媒体: off / metadata / references / content")
        yield Input(value="off", id="replay-input-media")
        yield Label("Events per Run (1–500), Runs per batch (1–32), Session membership offset")
        yield Input(value="100", id="replay-event-limit")
        yield Input(value="10", id="replay-run-limit")
        yield Input(value="0", id="replay-offset")
        yield Input(placeholder="Type VIEW CONTENT for each sensitive read", id="replay-confirm")
        yield Button("Read next batch / 读取下一批", id="replay-read", variant="primary")
        yield Label("Trusted JSON cache / 受信缓存 — import reads next batch; export creates a new file")
        yield Input(placeholder="Cache .json path (relative to workspace or absolute)", id="replay-cache-path")
        yield Input(placeholder="Type TRUST CACHE to import or SAVE CACHE to export; also VIEW CONTENT above", id="replay-cache-confirm")
        yield Button("Import + read batch / 导入并读取一批", id="replay-import")
        yield Button("Export current snapshot / 导出当前快照", id="replay-export")
        yield Button("Clear view / 清空视图", id="replay-clear")
        yield Static("No recorded content read. Selection changes clear cached content.", id="replay-status", markup=False)
        yield Button("Previous display slice / 上一屏", id="replay-prev")
        yield Button("Next display slice / 下一屏", id="replay-next")
        yield Static("No snapshot.", id="replay-body", classes="panel", markup=False)
        yield self.media_panel

    def _value(self, name: str) -> str:
        return self.query_one(f"#replay-{name}", Input).value.strip()

    def _path(self, name: str) -> Path:
        path = Path(self._value(name))
        return path if path.is_absolute() else self.workspace / path

    def _lock(self, locked: bool) -> None:
        for name in _INPUTS + _FLAGS + ("read", "import", "export"):
            self.query_one(f"#replay-{name}").disabled = locked

    def clear_view(self) -> None:
        self._generation += 1
        self._view = None
        self._display_offset = 0
        self.media_panel.set_snapshot(None)
        self.query_one("#replay-confirm", Input).value = ""
        self.query_one("#replay-cache-confirm", Input).value = ""
        self.query_one("#replay-offset", Input).value = "0"
        self.query_one("#replay-body", Static).update(Text("No snapshot."))
        self.query_one("#replay-status", Static).update(Text(
            "View cleared; in-flight delivery is discarded. An already-started cache write may finish."
        ))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in {f"replay-{name}" for name in _SELECTION_INPUTS}:
            if self._view is not None or self._busy:
                self.clear_view()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id in {f"replay-{name}" for name in _FLAGS}:
            if self._view is not None or self._busy:
                self.clear_view()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "replay-read":
            self.start_read()
        elif event.button.id in {"replay-import", "replay-export"}:
            self.start_cache(export=event.button.id == "replay-export")
        elif event.button.id == "replay-clear":
            self.clear_view()
        elif event.button.id in {"replay-prev", "replay-next"}:
            delta = -DISPLAY_CHARS if event.button.id == "replay-prev" else DISPLAY_CHARS
            end = ((len(self._view.body) - 1) // DISPLAY_CHARS) * DISPLAY_CHARS if self._view else 0
            self._display_offset = min(max(0, self._display_offset + delta), end)
            self._show_slice()

    def _show_slice(self) -> None:
        if self._view is None:
            return
        start = self._display_offset
        body = self._view.body[start:start + DISPLAY_CHARS]
        self.query_one("#replay-body", Static).update(Text(body))
        self.query_one("#replay-status", Static).update(Text(
            f"{self._view.summary}\nDisplay characters {start + 1}–{start + len(body)} / {len(self._view.body)}. "
            "Display paging does not read more events."
        ))

    def start_read(self) -> None:
        if self._busy or self._closing:
            return
        confirmed = self._value("confirm") == "VIEW CONTENT"
        self.query_one("#replay-confirm", Input).value = ""
        self.query_one("#replay-cache-confirm", Input).value = ""
        try:
            selection = ReplaySelection(
                self._value("kind"), self._value("id"), self._path("state-root"), self._path("session-root"),
                **{name.replace("-", "_"): self.query_one(f"#replay-{name}", Checkbox).value for name in _FLAGS},
                media=self._value("media"),
                input_media=self._value("input-media"),
            )
            limits = {"event_limit": int(self._value("event-limit")),
                      "run_limit": int(self._value("run-limit")), "run_offset": int(self._value("offset"))}
        except ValueError:
            self.query_one("#replay-status", Static).update(Text("Invalid numeric paging input; nothing read."))
            return
        self._busy = True
        self._lock(True)
        self.query_one("#replay-status", Static).update(Text("Reading one bounded batch…"))
        self._worker = self.run_worker(
            self._read(selection, self._view, confirmed, limits, self._generation),
            name="replay-view", group="replay-view", exclusive=False, exit_on_error=False,
        )

    def start_cache(self, *, export: bool) -> None:
        if self._busy or self._closing:
            return
        confirmed = self._value("confirm") == "VIEW CONTENT"
        cache_confirmed = self._value("cache-confirm") == ("SAVE CACHE" if export else "TRUST CACHE")
        self.query_one("#replay-confirm", Input).value = ""
        self.query_one("#replay-cache-confirm", Input).value = ""
        try:
            if not confirmed or not cache_confirmed:
                raise ReplayReadError("Cache actions require VIEW CONTENT plus SAVE CACHE (export) or TRUST CACHE (import).")
            if not self._value("cache-path"):
                raise ReplayReadError("Enter an explicit cache file path.")
            if export and self._view is None:
                raise ReplayReadError("Read a snapshot before exporting.")
            selection = ReplaySelection(
                self._value("kind"), self._value("id"), self._path("state-root"), self._path("session-root"),
                **{name.replace("-", "_"): self.query_one(f"#replay-{name}", Checkbox).value for name in _FLAGS},
                media=self._value("media"), input_media=self._value("input-media"),
            )
            if export and self._view is not None and replace(
                selection, state_root=selection.state_root.resolve(), session_root=selection.session_root.resolve(),
            ) != self._view.selection:
                raise ReplayReadError("Selection changed; rebuild the view before exporting.")
            limits = {} if export else {
                "event_limit": int(self._value("event-limit")),
                "run_limit": int(self._value("run-limit")), "run_offset": int(self._value("offset")),
            }
            path = self._path("cache-path")
        except ReplayReadError as error:
            self.query_one("#replay-status", Static).update(Text(str(error)))
            return
        except (ValueError, OSError, RuntimeError):
            self.query_one("#replay-status", Static).update(Text("Invalid cache path or paging input; nothing read or written."))
            return
        self._busy = True
        self._lock(True)
        self.query_one("#replay-status", Static).update(Text("Exporting captured snapshot…" if export else "Importing trusted cache and reading one batch…"))
        self._worker = self.run_worker(
            self._cache(selection, path, self._view, export, limits, self._generation),
            name="replay-cache", group="replay-view", exclusive=False, exit_on_error=False,
        )

    async def _cache(self, selection: ReplaySelection, path: Path, prior: ReplayView | None,
                     export: bool, limits: dict[str, int], generation: int) -> None:
        try:
            if self._closing or generation != self._generation:
                return
            if export:
                if prior is None:
                    raise ReplayReadError("No captured snapshot to export.")
                await asyncio.to_thread(export_replay_view, prior, path, confirmed=True, save_confirmed=True)
                if not self._closing and generation == self._generation:
                    self.query_one("#replay-status", Static).update(Text("Cache exported to the selected new file. Contains the captured disclosure; protect it as sensitive data."))
            else:
                view = await asyncio.to_thread(lambda: asyncio.run(import_replay_view(
                    selection, path, confirmed=True, trusted=True, **limits,
                )))
                if not self._closing and generation == self._generation:
                    self._view = view
                    self.media_panel.set_snapshot(view.snapshot)
                    self._display_offset = 0
                    self.query_one("#replay-offset", Input).value = str(view.next_run_offset)
                    self._show_slice()
        except ReplayReadError as error:
            if not self._closing and generation == self._generation:
                self.query_one("#replay-status", Static).update(Text(str(error)))
        except Exception:
            if not self._closing and generation == self._generation:
                self.query_one("#replay-status", Static).update(Text("Cache action failed; prior view retained. Check the selected file before retrying."))
        finally:
            self._busy = False
            if not self._closing:
                self._lock(False)

    async def _read(self, selection: ReplaySelection, prior: ReplayView | None,
                    confirmed: bool, limits: dict[str, int], generation: int) -> None:
        try:
            # Keep store reads, projection and large serialization off the UI thread.
            view = await asyncio.to_thread(lambda: asyncio.run(read_replay_view(
                selection, prior, confirmed=confirmed, **limits,
            )))
            if not self._closing and generation == self._generation:
                self._view = view
                self.media_panel.set_snapshot(view.snapshot)
                self._display_offset = 0
                self.query_one("#replay-offset", Input).value = str(view.next_run_offset)
                self._show_slice()
        except ReplayReadError as error:
            if not self._closing and generation == self._generation:
                self.query_one("#replay-status", Static).update(Text(str(error)))
        except Exception:
            if not self._closing and generation == self._generation:
                self.query_one("#replay-status", Static).update(Text("View read failed; prior snapshot retained."))
        finally:
            self._busy = False
            if not self._closing:
                self._lock(False)

    def on_unmount(self) -> None:
        self._closing = True
        self._generation += 1
        self._view = None
        if self._worker is not None:
            self._worker.cancel()
        # Cancellation discards delivery; already-running reads/writes may finish.
