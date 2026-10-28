"""Optional Textual transport for the same public application execution API."""

import asyncio
import json
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Label, Static

from w_agent.application import execute_application_entry, load_application_call


class ApplicationPanel(Vertical):
    DEFAULT_CSS = """
    ApplicationPanel { height: auto; }
    ApplicationPanel #application-result { height: auto; min-height: 3; }
    """

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace
        self._operation_task: asyncio.Task[None] | None = None
        self._closing = False

    def compose(self) -> ComposeResult:
        yield Label("Custom Harness / 自定义应用 — same project as Python and CLI")
        yield Input(placeholder="Trusted module:project_or_factory / 受信项目入口", id="application-entry")
        yield Input(placeholder="Call JSON: operation, args, kwargs / 调用参数文件", id="application-input")
        yield Label("Imports, startup and execution are UNSANDBOXED and may access files/services/models. / 导入、启动和执行不隔离，可能访问文件、服务与模型。")
        yield Input(placeholder="Type RUN APPLICATION to authorize / 输入以明确授权本次执行", id="application-confirm")
        yield Button("Run application / 执行应用", id="application-run", variant="warning")
        yield Button("Cancel / 取消", id="application-cancel", disabled=True)
        yield Static("No application executed. / 尚未执行应用。", id="application-result", markup=False)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "application-run":
            event.stop()
            self._begin()
        elif event.button.id == "application-cancel":
            event.stop()
            self._cancel()

    def _begin(self) -> None:
        if self._closing or (self._operation_task is not None and not self._operation_task.done()):
            return
        confirmation = self.query_one("#application-confirm", Input)
        authorized = confirmation.value == "RUN APPLICATION"
        confirmation.value = ""
        output = self.query_one("#application-result", Static)
        if not authorized:
            output.update(Text("Rejected: type RUN APPLICATION to authorize unsandboxed code and execution."))
            return
        entry = self.query_one("#application-entry", Input).value.strip()
        source = self.query_one("#application-input", Input).value.strip()
        if not entry or not source:
            output.update(Text("Rejected: entry and call JSON path are required."))
            return
        path = Path(source)
        if not path.is_absolute():
            path = self.workspace / path
        self.query_one("#application-run", Button).disabled = True
        self.query_one("#application-cancel", Button).disabled = False
        output.update(Text("Running application…"))
        self._operation_task = asyncio.create_task(self._execute(entry, path))
        self._operation_task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        error = None if task.cancelled() else task.exception()
        if self._closing or task is not self._operation_task:
            return
        if task.cancelled():
            self.query_one("#application-result", Static).update(Text(
                "Application cancelled; cleanup drained. No automatic replay.",
            ))
        elif error is not None:
            self.query_one("#application-result", Static).update(Text(
                f"Application failed: {type(error).__name__}; no automatic replay.",
            ))
        self.query_one("#application-run", Button).disabled = False
        self.query_one("#application-cancel", Button).disabled = True

    def _cancel(self) -> None:
        task = self._operation_task
        if task is not None and not task.done() and not task.cancelling():
            task.cancel()

    async def _execute(self, entry: str, path: Path) -> None:
        lines: list[str] = []

        def display(value, key):
            line = json.dumps({key: value}, ensure_ascii=False, allow_nan=False)
            if len(line) > 8192:
                line = line[:8192] + " … [display truncated]"
            lines.append(line)
            del lines[:-20]
            if not self._closing:
                self.query_one("#application-result", Static).update(Text("\n".join(lines)))

        try:
            call = await asyncio.to_thread(load_application_call, path)
            result = await execute_application_entry(
                entry, call, confirmed=True, on_item=lambda value: display(value, "item"),
            )
            display(result, "result")
        except asyncio.CancelledError:
            if not self._closing:
                self.query_one("#application-result", Static).update(Text("Application cancelled; cleanup drained. No automatic replay."))
            raise
        except Exception as error:
            if not self._closing:
                self.query_one("#application-result", Static).update(Text(
                    f"Application failed: {type(error).__name__}; no automatic replay.",
                ))
        finally:
            if not self._closing:
                self.query_one("#application-run", Button).disabled = False
                self.query_one("#application-cancel", Button).disabled = True

    async def on_unmount(self) -> None:
        self._closing = True
        self._cancel()
        if self._operation_task is not None:
            try:
                await self._operation_task
            except asyncio.CancelledError:
                pass
