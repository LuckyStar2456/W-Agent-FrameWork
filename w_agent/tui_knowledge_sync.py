"""Optional UI for shared explicit knowledge synchronization management."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Checkbox, Input, Label, Static

from w_agent.knowledge_plan_actions import KnowledgeIndexHostOptions
from w_agent.knowledge_sync_management import (
    KnowledgeSyncExecuteRequest, KnowledgeSyncImportRequest, KnowledgeSyncInspectRequest, KnowledgeSyncPrepareRequest,
    execute_local_knowledge_sync, import_local_knowledge_sync, inspect_local_knowledge_sync, prepare_local_knowledge_sync,
)


_CONFIRMATIONS = {
    "read": "READ SYNC", "code": "LOAD INDEX HOST", "embed": "EMBED SYNC",
    "record": "RECORD SYNC", "create": "CREATE SYNC", "upsert": "UPSERT SYNC",
    "delete": "DELETE SYNC",
}
_Request = KnowledgeSyncImportRequest | KnowledgeSyncInspectRequest | KnowledgeSyncPrepareRequest | KnowledgeSyncExecuteRequest


class KnowledgeSyncPanel(Vertical):
    """Captures exact host requests; never grants authority from preview output."""

    DEFAULT_CSS = """
    KnowledgeSyncPanel { height: auto; }
    KnowledgeSyncPanel #ks-result { height: auto; min-height: 3; }
    """

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace
        self._operation_task: asyncio.Task[None] | None = None
        self._panel_closing = False
        self._display = ""
        self._display_offset = 0

    def compose(self) -> ComposeResult:
        yield Label("Knowledge sync / 知识增量同步 — no automatic reads, embedding, approval or retry")
        yield Label("Step 1: preview selected local text files, then save the exact approved trace. / 第一步：预览选中的本地文本，再锁定保存追溯。")
        yield Input(str(self.workspace / ".wagent" / "knowledge-traces.sqlite3"),
                    placeholder="Trace database / 追溯库", id="ks-trace")
        yield Input(placeholder="Exact trace namespace / 命名空间", id="ks-namespace")
        yield Input(placeholder="Exact trace version / 固定版本", id="ks-version")
        yield Input(str(self.workspace), placeholder="Trusted local import root / 本地导入根目录", id="ks-root")
        yield Input('["README.md"]', placeholder="Selected relative paths, JSON array / 相对路径数组", id="ks-paths")
        yield Checkbox("Recursive text import / 递归文本导入", id="ks-recursive")
        yield Checkbox("Enable optional PDF/DOCX/XLSX/PPTX parsers (trusted files only) / 显式启用可选文档解析", id="ks-document-formats")
        yield Input("4096", placeholder="Chunk UTF-8 byte limit / 每块字节数", id="ks-chunk")
        yield Input("utf8", placeholder="Splitter: utf8 or structure / 分块策略（非模型语义）", id="ks-splitter")
        yield Input("0", placeholder="Structure overlap characters / 结构分块重叠字符数", id="ks-overlap")
        yield Input(placeholder="Reviewed preview digest (required to save) / 锁定保存必填预览摘要", id="ks-preview-digest")
        yield Button("Preview trace import / 追溯导入预览（只读）", id="ks-preview")
        yield Button("Save approved trace / 保存已批准追溯", id="ks-import")
        yield Input(str(self.workspace / ".wagent" / "knowledge-sync.sqlite3"),
                    placeholder="Existing journal DB (parent must exist) / 同步日志库", id="ks-journal")
        yield Input(placeholder="Exact saved plan SHA-256 / 已保存计划摘要", id="ks-plan")
        yield Label("Inspect: READ SYNC only; no host import / 检查只需读取确认，不加载宿主")
        yield Button("Inspect plan and batch outcomes / 检查计划与批次状态", id="ks-inspect")
        yield Label("Preparation reads archived trace, may bill embedding, then stages/locks the target. / 准备读取追溯存档、可能计费并锁定目标。")
        for key, hint in (
            ("trace-digest", "Reviewed trace SHA-256 / 已审查追溯摘要"),
            ("previous", "Previous completed plan digest (optional) / 前驱计划摘要"),
            ("reuse", "Separately approved previous index digest (optional) / 复用缓存批准摘要"),
            ("host", "Trusted local module:factory / 受信宿主入口"),
            ("binding", "Named host binding / 宿主绑定名称"),
        ):
            yield Input(placeholder=hint, id=f"ks-{key}")
        yield Label("Host is explicitly authorized UNSANDBOXED Python. / 宿主是明确授权的不隔离本地 Python。")
        yield Label("Execution approvals are typed independently, never filled from preview. Delete removes stale points. / 独立手填批准，删除会移除旧点。")
        for key, hint in (
            ("approved-plan", "Separately approved exact plan digest / 计划批准摘要"),
            ("approved-upsert", "Approved upsert digest (also type UPSERT SYNC) / 覆盖写入批准摘要"),
            ("approved-delete", "Approved delete digest (also type DELETE SYNC) / 删除批准摘要"),
        ):
            yield Input(placeholder=hint, id=f"ks-{key}")
        yield Label("Single-action confirmations / 单次动作确认：unused confirmations must be blank")
        for key, word in _CONFIRMATIONS.items():
            yield Input(placeholder=word, id=f"ks-{key}")
        yield Button("Prepare and stage / 准备并暂存（可能计费，不远端写入）", id="ks-prepare")
        yield Button("Execute approved sync / 执行批准同步（可远端覆盖/删除）", id="ks-execute")
        yield Button("Cancel / 取消（不承诺回滚）", id="ks-cancel", disabled=True)
        yield Static("No operation performed / 尚未操作", id="ks-result", markup=False)
        yield Button("Previous result slice / 上一屏", id="ks-prev")
        yield Button("Next result slice / 下一屏", id="ks-next")
        yield Static("No result / 尚无结果", id="ks-page", markup=False)

    def _value(self, name: str) -> str:
        return self.query_one(f"#ks-{name}", Input).value

    def _path(self, name: str) -> Path:
        value = self._value(name)
        if not value.strip():
            raise ValueError("explicit local path required")
        path = Path(value)
        return path if path.is_absolute() else self.workspace / path

    def _capture(self, action: str) -> _Request:
        words = {name: self._value(name) for name in _CONFIRMATIONS}
        for name in words:
            self.query_one(f"#ks-{name}", Input).value = ""
        if any(value not in {"", _CONFIRMATIONS[name]} for name, value in words.items()):
            raise ValueError("invalid confirmation phrase")
        allowed = {
            "preview": {"read"},
            "import": {"read", "record", "create"},
            "inspect": {"read"},
            "prepare": {"read", "code", "embed", "record", "create"},
            "execute": {"read", "code", "record", "upsert", "delete"},
        }
        if action not in allowed or any(value and name not in allowed[action] for name, value in words.items()):
            raise ValueError("unrelated action consent")
        flags = {name: value == _CONFIRMATIONS[name] for name, value in words.items()}
        if action in {"preview", "import"}:
            if action == "import" and not flags["record"]:
                raise ValueError("saving trace requires independent record consent")
            raw_paths = self._value("paths")
            if len(raw_paths.encode("utf-8")) > 256 * 1024:
                raise ValueError("path selection exceeds limit")
            paths = json.loads(raw_paths)
            chunk = self._value("chunk")
            overlap = self._value("overlap")
            if (not isinstance(paths, list) or any(not isinstance(path, str) for path in paths)
                    or not 1 <= len(chunk) <= 10 or not chunk.isascii() or not chunk.isdecimal()
                    or not 1 <= len(overlap) <= 10 or not overlap.isascii() or not overlap.isdecimal()):
                raise ValueError("invalid import selection or chunk bound")
            return KnowledgeSyncImportRequest(
                trace_database=self._path("trace"), root=self._path("root"), paths=tuple(paths),
                namespace=self._value("namespace"), version=self._value("version"),
                chunk_bytes=int(chunk), recursive=self.query_one("#ks-recursive", Checkbox).value,
                splitter=self._value("splitter"), overlap_chars=int(overlap),
                document_formats=self.query_one("#ks-document-formats", Checkbox).value,
                expected_preview_digest=self._value("preview-digest") or None,
                confirm_read=flags["read"], confirm_record=flags["record"], confirm_create=flags["create"],
            )
        journal = self._path("journal")
        if action == "inspect":
            return KnowledgeSyncInspectRequest(journal, self._value("plan"), confirm_read=flags["read"])
        host = KnowledgeIndexHostOptions(self._value("host"), self._value("binding"), flags["code"])
        if action == "prepare":
            return KnowledgeSyncPrepareRequest(
                host=host, trace_database=self._path("trace"), namespace=self._value("namespace"),
                version=self._value("version"), journal_database=journal,
                expected_trace_digest=self._value("trace-digest"),
                previous_plan_digest=self._value("previous") or None,
                approved_reuse_digest=self._value("reuse") or None,
                confirm_read=flags["read"], confirm_embedding=flags["embed"],
                confirm_record=flags["record"], confirm_create=flags["create"],
            )
        upsert, delete = self._value("approved-upsert"), self._value("approved-delete")
        if bool(upsert) != flags["upsert"] or bool(delete) != flags["delete"]:
            raise ValueError("write digest and independent action consent must be paired")
        return KnowledgeSyncExecuteRequest(
            host=host, journal_database=journal, plan_digest=self._value("plan"),
            approved_plan_digest=self._value("approved-plan"),
            approved_upsert_digest=upsert or None, approved_delete_digest=delete or None,
            confirm_read=flags["read"], confirm_record=flags["record"],
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        identity = event.button.id
        if identity not in {"ks-preview", "ks-import", "ks-inspect", "ks-prepare", "ks-execute", "ks-cancel", "ks-prev", "ks-next"}:
            return
        event.stop()
        if identity == "ks-cancel":
            if self._operation_task is not None and not self._operation_task.done():
                self._operation_task.cancel()
            return
        if self._panel_closing or (self._operation_task is not None and not self._operation_task.done()):
            return
        if identity in {"ks-prev", "ks-next"}:
            end = max(0, ((len(self._display) - 1) // 16000) * 16000)
            self._display_offset = min(end, max(0, self._display_offset + (-16000 if identity == "ks-prev" else 16000)))
            self._show_slice()
            return
        try:
            request = self._capture(identity.removeprefix("ks-"))
        except Exception:
            self._show("Invalid fields/consent; nothing dispatched. / 参数或确认无效，未派发操作。")
            return
        self._busy(True)
        self._show("Working / 处理中")
        self._operation_task = asyncio.create_task(self._run(request))
        self._operation_task.add_done_callback(self._finished)

    async def _run(self, request: _Request) -> None:
        try:
            if isinstance(request, KnowledgeSyncImportRequest):
                result = await import_local_knowledge_sync(request)
            elif isinstance(request, KnowledgeSyncInspectRequest):
                result = await inspect_local_knowledge_sync(request)
            elif isinstance(request, KnowledgeSyncPrepareRequest):
                result = await prepare_local_knowledge_sync(request)
            else:
                result = await execute_local_knowledge_sync(request)
            output = json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2)
            if len(output) > 2 * 1024 * 1024:
                output = "Operation returned an oversized result; inspect the journal. / 结果过大，请核对日志。"
        except (Exception, asyncio.CancelledError):
            output = "Stopped/failed; billing, local saves or remote writes may exist. Inspect the exact plan before retry. Unknown outcomes are never automatically replayed. / 已停止或失败，可能已计费或写入，请核对精确计划，未知结果不自动重发。"
        if not self._panel_closing:
            self._show(output)

    def _busy(self, busy: bool) -> None:
        for widget in self.query("Input, Checkbox, Button"):
            if widget.id == "ks-cancel":
                widget.disabled = not busy
            else:
                widget.disabled = busy

    def _show(self, output: str) -> None:
        # Every manager result is ASCII-escaped JSON, not Rich markup/terminal code.
        self._display = output
        self._display_offset = 0
        self._show_slice()

    def _show_slice(self) -> None:
        start = self._display_offset
        self.query_one("#ks-result", Static).update(Text(self._display[start:start + 16000]))
        self.query_one("#ks-page", Static).update(Text(
            f"Display {start}–{min(start + 16000, len(self._display))} / {len(self._display)}; paging performs no I/O."
        ))

    def _finished(self, task: asyncio.Task[None]) -> None:
        cancelled = task.cancelled()
        error = None if cancelled else task.exception()
        if self._panel_closing or task is not self._operation_task:
            return
        if cancelled or error is not None:
            self._show("Stopped; billing/local saves/remote writes may exist. Inspect before retry; unknown outcomes are not replayed. / 已停止，请核对日志，未知结果不可自动重发。")
        self._busy(False)

    async def on_unmount(self) -> None:
        self._panel_closing = True
        if self._operation_task is not None and not self._operation_task.done():
            self._operation_task.cancel()
            try:
                await self._operation_task
            except asyncio.CancelledError:
                pass
