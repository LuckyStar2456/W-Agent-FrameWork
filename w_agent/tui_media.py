"""Optional Textual media panel consuming only the current replay projection."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Label, Static

from w_agent.agents import RunReplaySnapshot
from w_agent.media_display import (
    MediaDisplay, MediaDisplayError, MediaPreview, TerminalMediaDisplay,
    export_recorded_media, safe_media_text,
)
from w_agent.session_replay import SessionReplaySnapshot


def replay_media_blocks(snapshot: RunReplaySnapshot | SessionReplaySnapshot,
                        *, limit: int = 256) -> tuple[Mapping[str, object], ...]:
    """Select known media slots, not arbitrary tool result or metadata mappings."""
    if type(limit) is not int or not 1 <= limit <= 1024:
        raise ValueError("Invalid media catalog limit.")
    blocks: list[Mapping[str, object]] = []

    def add(value: object) -> None:
        if isinstance(value, Mapping) and value.get("kind") in {"image", "audio"}:
            if len(blocks) >= limit:
                raise MediaDisplayError("Media catalog limit exceeded; read fewer events/Runs.")
            blocks.append(value)

    runs = (snapshot,) if isinstance(snapshot, RunReplaySnapshot) else tuple(run.replay for run in snapshot.runs)
    for run in runs:
        for block in run.state.get("blocks", ()):
            if isinstance(block, Mapping) and block.get("kind") == "media":
                add(block.get("media"))
    if isinstance(snapshot, SessionReplaySnapshot):
        for run in snapshot.runs:
            for message in run.messages:
                for block in message.get("input_blocks", ()):
                    add(block)
    return tuple(blocks)


class ReplayMediaPanel(Vertical):
    """An independently confirmed view/export of one captured recorded block."""

    DEFAULT_CSS = """
    ReplayMediaPanel { height: auto; }
    ReplayMediaPanel #media-preview { height: auto; min-height: 2; }
    """

    def __init__(self, workspace: Path, *, renderer: MediaDisplay | None = None) -> None:
        super().__init__()
        self.workspace = workspace
        self.renderer = renderer if renderer is not None else TerminalMediaDisplay()
        self._blocks: tuple[Mapping[str, object], ...] = ()
        self._index = 0
        self._generation = 0
        self._operation_task: asyncio.Task[None] | None = None
        self._panel_closing = False

    def compose(self) -> ComposeResult:
        yield Label("Media preview / 媒体预览 — independently disclosed; no fetch or playback")
        yield Static("No recorded media selected.", id="media-catalog", markup=False)
        yield Button("Previous media / 上一项", id="media-prev")
        yield Button("Next media / 下一项", id="media-next")
        yield Input(placeholder="VIEW MEDIA or EXPORT MEDIA (one action)", id="media-confirm")
        yield Button("Preview selected / 预览所选", id="media-view")
        yield Input(placeholder="Existing local export directory / 已有本地导出目录", id="media-directory")
        yield Button("Export selected to new file / 导出新文件", id="media-export")
        yield Static("Media is hidden. Inline preview requires a content-mode replay.", id="media-preview", markup=False)

    def set_snapshot(self, snapshot: RunReplaySnapshot | SessionReplaySnapshot | None) -> None:
        self._generation += 1
        self._index = 0
        self._blocks = ()
        try:
            if snapshot is not None:
                self._blocks = replay_media_blocks(snapshot)
            self._reset_display()
        except MediaDisplayError as error:
            self._reset_display()
            self.query_one("#media-preview", Static).update(Text(str(error)))

    def _reset_display(self) -> None:
        self.query_one("#media-confirm", Input).value = ""
        label = "No recorded media selected."
        if self._blocks:
            block = self._blocks[self._index]
            label = (f"{self._index + 1}/{len(self._blocks)} — "
                     f"{safe_media_text(block.get('kind'), 16)} / "
                     f"{safe_media_text(block.get('source'), 16)}. Contents hidden.")
        self.query_one("#media-catalog", Static).update(Text(label))
        self.query_one("#media-preview", Static).update(Text("Media hidden; confirm each preview or export separately."))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        action = event.button.id
        if action in {"media-prev", "media-next"}:
            if self._blocks:
                self._index = (self._index + (-1 if action == "media-prev" else 1)) % len(self._blocks)
                self._generation += 1
                self._reset_display()
            return
        if action not in {"media-view", "media-export"}:
            return
        if self._operation_task is not None and not self._operation_task.done():
            return
        confirmation = self.query_one("#media-confirm", Input).value
        self.query_one("#media-confirm", Input).value = ""
        export = action == "media-export"
        if confirmation != ("EXPORT MEDIA" if export else "VIEW MEDIA") or not self._blocks:
            self.query_one("#media-preview", Static).update(Text("Select media and type VIEW MEDIA or EXPORT MEDIA for that action."))
            return
        directory = self.query_one("#media-directory", Input).value.strip()
        if export and not directory:
            self.query_one("#media-preview", Static).update(Text("Enter an explicit existing export directory."))
            return
        self.query_one("#media-preview", Static).update(Text("Processing bounded local media…"))
        self._operation_task = asyncio.create_task(self._present(
            self._blocks[self._index], export, directory, self._generation))

    async def _present(self, block: Mapping[str, object], export: bool, directory: str, generation: int) -> None:
        try:
            if export:
                path = Path(directory)
                if not path.is_absolute():
                    path = self.workspace / path
                target = await asyncio.to_thread(export_recorded_media, block, path, confirmed=True)
                result = Text("Exported sensitive recorded bytes (format may be untrusted): " + safe_media_text(target))
            else:
                preview = await asyncio.to_thread(self.renderer.render, block, confirmed=True)
                if not isinstance(preview, MediaPreview):
                    raise MediaDisplayError("Renderer must return MediaPreview.")
                result = Text(safe_media_text(preview.summary))
                # Trust no escape/control sequences or unbounded output from extensions.
                if preview.image_art:
                    art = "\n".join(safe_media_text(line, 128) for line in preview.image_art[:32768].splitlines()[:64])
                    result.append("\n" + art)
            if not self._panel_closing and generation == self._generation:
                self.query_one("#media-preview", Static).update(result)
        except MediaDisplayError as error:
            if not self._panel_closing and generation == self._generation:
                self.query_one("#media-preview", Static).update(Text(safe_media_text(error)))
        except Exception:
            if not self._panel_closing and generation == self._generation:
                self.query_one("#media-preview", Static).update(Text("Media operation failed; no automatic retry or playback."))

    def on_unmount(self) -> None:
        self._panel_closing = True
        self._generation += 1
        self._blocks = ()
        if self._operation_task is not None:
            self._operation_task.cancel()
        # Already-running file writes may finish; cancellation only discards delivery.
