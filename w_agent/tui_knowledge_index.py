"""Optional local index journal review and host-evidence reconciliation panel."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Label, Static

from w_agent.knowledge_index_journal import KnowledgeIndexReconciliation
from w_agent.knowledge_index_management import KnowledgeIndexReviewRequest, review_local_knowledge_index, list_local_knowledge_journals

_CONFIRMATIONS = {
    "read": "READ INDEX", "details": "SHOW INDEX DETAILS",
    "write": "WRITE DECISION", "inactive": "NO LATE EFFECTS",
}


@dataclass(frozen=True, slots=True)
class _Catalog:
    database: Path
    include_details: bool


class KnowledgeIndexPanel(Vertical):
    DEFAULT_CSS = "KnowledgeIndexPanel { height: auto; }"

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace
        self._operation_task: asyncio.Task[None] | None = None
        self._panel_closing = False

    def compose(self) -> ComposeResult:
        yield Label("Index journal / 索引日志：local observations are NOT remote acceptance / 本地记录不等于远端验收")
        yield Input(str(self.workspace / ".wagent" / "knowledge-index.sqlite3"), placeholder="Existing journal DB (not body snapshot DB)", id="ki-database")
        for name, hint in (
            ("manifest", "Exact manifest SHA-256 / 清单摘要"),
            ("attempt", "Exact attempt ID / 尝试 ID"),
            ("plan", "Exact plan SHA-256 / 计划摘要"),
            ("expected", "Original observation: pending / acknowledged / unknown"),
            ("outcome", "Host decision: completed / not-applied"),
            ("decision", "Unique reconciliation ID / 对账 ID"),
            ("evidence", "Independent evidence reference (not evidence body)"),
            ("actor", "Host actor reference (not identity verification)"),
        ):
            yield Input(placeholder=hint, id=f"ki-{name}")
        yield Label("Reconcile only after independent review and stopping/draining all possible late effects. / 先独立核实证据并排除迟到效果。")
        for name, word in _CONFIRMATIONS.items():
            yield Input(placeholder=word, id=f"ki-{name}")
        yield Button("Inspect local journal / 查看本地日志", id="ki-inspect")
        yield Button("List journal manifests / 列出日志清单", id="ki-list")
        yield Button("Save reviewed decision / 保存已审查决定", id="ki-reconcile")
        yield Button("Cancel / 取消（决定可能已保存）", id="ki-cancel", disabled=True)
        yield Static("No journal loaded / 尚未读取日志", id="ki-result", markup=False)

    def _value(self, key: str) -> str:
        return self.query_one(f"#ki-{key}", Input).value

    def _capture(self, reconcile: bool, *, catalog: bool = False) -> KnowledgeIndexReviewRequest | _Catalog:
        confirmations = {key: self._value(key) for key in _CONFIRMATIONS}
        for key in _CONFIRMATIONS:
            self.query_one(f"#ki-{key}", Input).value = ""
        if any(value and value != _CONFIRMATIONS[key] for key, value in confirmations.items()):
            raise ValueError("invalid index confirmation")
        raw_path = self._value("database")
        if not raw_path.strip():
            raise ValueError("journal path required")
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.workspace / path
        if catalog:
            if confirmations["read"] != _CONFIRMATIONS["read"] or confirmations["write"] or confirmations["inactive"]:
                raise ValueError("catalog requires read consent only")
            return _Catalog(path, confirmations["details"] == _CONFIRMATIONS["details"])
        decision = None
        if reconcile:
            decision = KnowledgeIndexReconciliation(
                self._value("decision"), self._value("manifest"), self._value("attempt"),
                self._value("plan"), self._value("expected"), self._value("outcome"),
                self._value("evidence"), self._value("actor"),
            )
        return KnowledgeIndexReviewRequest(
            path, self._value("manifest"), decision,
            confirm_read=confirmations["read"] == _CONFIRMATIONS["read"],
            include_details=confirmations["details"] == _CONFIRMATIONS["details"],
            confirm_write=confirmations["write"] == _CONFIRMATIONS["write"],
            confirm_inactive=confirmations["inactive"] == _CONFIRMATIONS["inactive"],
        )

    def _busy(self, busy: bool) -> None:
        for widget in self.query("Input, Button"):
            widget.disabled = not busy if widget.id == "ki-cancel" else busy

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        identity = event.button.id
        if identity not in {"ki-inspect", "ki-reconcile", "ki-cancel", "ki-list"}:
            return
        event.stop()
        if identity == "ki-cancel":
            if self._operation_task is not None:
                self._operation_task.cancel()
            return
        if self._operation_task is not None and not self._operation_task.done():
            return
        try:
            request = self._capture(identity == "ki-reconcile", catalog=identity == "ki-list")
        except Exception:
            self.query_one("#ki-result", Static).update("Invalid options or missing consent / 参数或确认无效")
            return
        self._busy(True)
        self.query_one("#ki-result", Static).update("Working / 处理中")
        self._operation_task = asyncio.create_task(self._execute(request))
        self._operation_task.add_done_callback(self._finished)

    async def _execute(self, request: KnowledgeIndexReviewRequest | _Catalog) -> None:
        try:
            if isinstance(request, _Catalog):
                result = await list_local_knowledge_journals(request.database, confirm_read=True, include_details=request.include_details)
            else:
                result = await review_local_knowledge_index(request)
            output = json.dumps(result, ensure_ascii=True, indent=2)
        except asyncio.CancelledError:
            output = "Cancelled; a decision may be committed. Inspect before retry. / 已取消，决定可能已保存，请先查看日志。"
        except Exception:
            output = "Review failed; a decision may be committed. Inspect before retry. / 操作失败，决定可能已保存，请先查看日志。"
        if not self._panel_closing:
            self.query_one("#ki-result", Static).update(Text(output))

    def _finished(self, task: asyncio.Task[None]) -> None:
        cancelled = task.cancelled()
        error = None if cancelled else task.exception()
        if self._panel_closing or task is not self._operation_task:
            return
        if cancelled or error is not None:
            self.query_one("#ki-result", Static).update("Stopped; inspect journal before retry. / 已停止，重试前请核对日志。")
        self._busy(False)

    async def on_unmount(self) -> None:
        self._panel_closing = True
        if self._operation_task is not None and not self._operation_task.done():
            self._operation_task.cancel()
            try:
                await self._operation_task
            except asyncio.CancelledError:
                pass
