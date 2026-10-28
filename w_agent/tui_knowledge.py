"""Optional local knowledge panel, reusing the public management operations."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Checkbox, Input, Label, Static

from w_agent.knowledge_management import LocalKnowledgeRequest, manage_local_knowledge


class KnowledgePanel(Vertical):
    DEFAULT_CSS = "KnowledgePanel { height: auto; }"

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace
        self._operation_task: asyncio.Task[None] | None = None
        self._panel_closing = False

    def compose(self) -> ComposeResult:
        yield Label("Local knowledge / 本地知识：preview by default; no model or index calls")
        yield Input(str(self.workspace / ".wagent" / "knowledge.sqlite3"), placeholder="Database (parent must exist)", id="km-database")
        yield Input(placeholder="Namespace / 命名空间 (optional for list)", id="km-namespace")
        yield Input(placeholder="Exact version / 固定版本", id="km-version")
        yield Input(str(self.workspace), placeholder="Trusted import root", id="km-root")
        yield Input('["README.md"]', placeholder='Selected relative paths, JSON array', id="km-paths")
        yield Checkbox("Recursive / 递归导入", id="km-recursive")
        yield Checkbox("PDF / Office (optional parser dependencies)", id="km-document-formats")
        yield Input("4096", placeholder="Chunk UTF-8 bytes", id="km-chunk")
        yield Input(placeholder="Expected preview digest / 保存时锁定预览摘要（可选）", id="km-preview-digest")
        yield Input(placeholder="Keyword query / 关键词", id="km-query")
        yield Input("4", placeholder="Result limit", id="km-limit")
        yield Input(placeholder="READ KNOWLEDGE — required for every operation", id="km-read")
        yield Input(placeholder="WRITE KNOWLEDGE — import: save instead of preview", id="km-write")
        yield Input(placeholder="CREATE KNOWLEDGE — import: create DB (also needs WRITE)", id="km-create")
        yield Input(placeholder="SHOW TEXT — search: disclose matched bodies", id="km-text")
        yield Button("Import / Preview 导入预览", id="km-import")
        yield Button("Versions 版本目录", id="km-list")
        yield Button("Search 固定版本检索", id="km-search")
        yield Button("Cancel 取消（写入可能已完成）", id="km-cancel", disabled=True)
        yield Static("No files loaded / 尚未读取文件", id="km-result", markup=False)

    def _value(self, name: str) -> str:
        return self.query_one(f"#km-{name}", Input).value

    def _path(self, name: str) -> Path:
        value = self._value(name)
        if not value.strip():
            raise ValueError("path is required")
        path = Path(value)
        return path if path.is_absolute() else self.workspace / path

    def _capture(self, action: str) -> LocalKnowledgeRequest:
        confirmations = {key: self._value(key) for key in ("read", "write", "create", "text")}
        for key in confirmations:
            self.query_one(f"#km-{key}", Input).value = ""
        words = {"read": "READ KNOWLEDGE", "write": "WRITE KNOWLEDGE", "create": "CREATE KNOWLEDGE", "text": "SHOW TEXT"}
        if any(value and value != words[key] for key, value in confirmations.items()):
            raise ValueError("invalid confirmation")
        options = dict(
            action=action, database=self._path("database"),
            namespace=self._value("namespace") or None,
            confirm_read=confirmations["read"] == words["read"],
            confirm_write=confirmations["write"] == words["write"],
            confirm_create=confirmations["create"] == words["create"],
            include_text=confirmations["text"] == words["text"],
        )
        if action == "import":
            raw = self._value("paths")
            if len(raw.encode("utf-8")) > 256 * 1024:
                raise ValueError("selection too large")
            paths = json.loads(raw)
            if not isinstance(paths, list):
                raise ValueError("selection must be an array")
            options.update(root=self._path("root"), paths=tuple(paths),
                           version=self._value("version"), chunk_bytes=int(self._value("chunk")),
                           recursive=self.query_one("#km-recursive", Checkbox).value,
                           document_formats=self.query_one("#km-document-formats", Checkbox).value,
                           expected_preview_digest=self._value("preview-digest") or None)
        elif action == "search":
            options.update(version=self._value("version"), query=self._value("query"), limit=int(self._value("limit")))
        return LocalKnowledgeRequest(**options)

    def _busy(self, busy: bool) -> None:
        for widget in self.query("Input, Checkbox, Button"):
            widget.disabled = not busy if widget.id == "km-cancel" else busy

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        identity = event.button.id or ""
        if not identity.startswith("km-"):
            return
        event.stop()
        if identity == "km-cancel":
            if self._operation_task is not None:
                self._operation_task.cancel()
            return
        if self._operation_task is not None and not self._operation_task.done():
            return
        try:
            request = self._capture(identity.removeprefix("km-"))
        except Exception:
            self.query_one("#km-result", Static).update("Invalid options or missing confirmation / 参数或确认无效")
            return
        self._busy(True)
        self.query_one("#km-result", Static).update("Working / 处理中")
        self._operation_task = asyncio.create_task(self._execute(request))
        self._operation_task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        # A task cancelled before its first instruction never enters _execute.
        cancelled = task.cancelled()
        error = None if cancelled else task.exception()
        if self._panel_closing or task is not self._operation_task:
            return
        if cancelled or error is not None:
            self.query_one("#km-result", Static).update(
                "Stopped. Write may have completed; inspect exact version. / 已停止，写入可能已完成，请核对版本。"
            )
        self._busy(False)

    async def _execute(self, request: LocalKnowledgeRequest) -> None:
        try:
            result = await manage_local_knowledge(request)
            output = json.dumps(result, ensure_ascii=True, indent=2)
        except asyncio.CancelledError:
            output = "Cancelled. Write may have completed; inspect exact version before retry. / 已取消，写入可能已完成，请先核对版本。"
        except Exception:
            output = "Operation failed. Inspect exact version before retrying a write. / 操作失败，重试写入前请核对版本。"
        if not self._panel_closing:
            self.query_one("#km-result", Static).update(Text(output))

    async def on_unmount(self) -> None:
        self._panel_closing = True
        if self._operation_task is not None and not self._operation_task.done():
            self._operation_task.cancel()
            try:
                await self._operation_task
            except asyncio.CancelledError:
                pass
