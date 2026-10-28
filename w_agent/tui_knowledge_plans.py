"""Explicit preparation, inspection and execution of staged knowledge plans."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Label, Static

from w_agent.knowledge_batches import review_missing_knowledge_batches
from w_agent.knowledge_index_journal import _digest
from w_agent.knowledge_ingestion import _label
from w_agent.knowledge_plan_sqlite import inspect_stored_knowledge_plan
from w_agent.knowledge_plan_catalog import review_knowledge_plan_catalog
from w_agent.knowledge_plan_actions import (
    KnowledgeIndexHostOptions, KnowledgePlanExecuteRequest, KnowledgePlanPrepareRequest,
    execute_local_knowledge_plan, parse_knowledge_document_ids, prepare_local_knowledge_plan,
)
from w_agent.vector_retrieval import _integer

_ACTION_WORDS = {
    "code": "LOAD INDEX HOST", "embed": "EMBED DOCUMENTS", "save": "SAVE PLAN",
    "create": "CREATE PLAN STORE", "write": "WRITE INDEX", "record": "RECORD WRITE",
    "create-journal": "CREATE INDEX JOURNAL",
}


@dataclass(frozen=True, slots=True)
class _BatchAdviceRequest:
    plan_database: Path
    source_database: Path
    namespace: str
    version: str
    manifest_digest: str
    include_ids: bool
    max_documents: int
    max_input_bytes: int
    max_vector_values: int

    def __post_init__(self) -> None:
        _label(self.namespace)
        _label(self.version)
        _digest(self.manifest_digest)
        if type(self.include_ids) is not bool:
            raise ValueError("batch disclosure must be boolean")
        _integer(self.max_documents, 128)
        _integer(self.max_input_bytes, 32 * 1024 * 1024)
        _integer(self.max_vector_values, 1024 * 1024)
        if self.plan_database.absolute() == self.source_database.absolute():
            raise ValueError("plan and source databases must differ")


class KnowledgePlansPanel(Vertical):
    DEFAULT_CSS = "KnowledgePlansPanel { height: auto; }"

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace
        self._operation_task: asyncio.Task[None] | None = None
        self._panel_closing = False

    def compose(self) -> ComposeResult:
        yield Label("Exact saved plans / 精确计划：staged is NOT authorized or executed / 暂存不等于授权或已写入")
        yield Input(str(self.workspace / ".wagent" / "knowledge-plans.sqlite3"), placeholder="Existing plan database", id="kp-database")
        yield Input(placeholder="Exact artifact SHA-256 / 计划工件摘要", id="kp-digest")
        yield Input(placeholder="READ PLAN / READ SOURCE / READ BATCH INPUTS", id="kp-read")
        yield Input(placeholder="SHOW TARGET (optional / 可选)", id="kp-target")
        yield Button("Inspect saved plan / 查看暂存计划", id="kp-inspect")
        yield Input(placeholder="Manifest SHA-256: optional for catalog, required for advice / 目录可选、批次建议必填", id="kp-manifest-filter")
        yield Button("List plans and coverage / 计划目录与批次覆盖", id="kp-list")
        yield Label("Trusted host Python runs locally without isolation; explicit developer authorization only. / 宿主 Python 为明确授权的不隔离开发代码。")
        for key, hint in (
            ("host", "Host module:factory"), ("binding", "Named host binding"),
            ("source", "Existing source snapshot DB / 正文快照库"),
            ("namespace", "Source namespace"), ("version", "Exact source version"),
            ("document-ids", "Optional JSON document IDs (blank = whole single batch)"),
            ("journal", "Index journal DB (separate from plan DB)"),
            ("attempt", "Unique write attempt ID"), ("approved", "Separately reviewed artifact SHA-256"),
        ):
            yield Input(placeholder=hint, id=f"kp-{key}")
        yield Label("Batch advice reads source bodies and staged plans locally, no embedding or writes. / 批次建议在本地读取正文与计划，不调用模型或写入。")
        yield Input(placeholder="SHOW BATCH IDS (optional / 可选)", id="kp-ids")
        for key, value, hint in (
            ("max-documents", "128", "Batch maximum documents (1–128) / 每批文档上限"),
            ("max-input-bytes", "1048576", "Batch input bytes (1–33554432) / 每批输入字节上限"),
            ("max-vector-values", "1048576", "Batch vector values (1–1048576) / 每批向量值总数上限"),
        ):
            yield Label(hint)
            yield Input(value, placeholder=hint, id=f"kp-{key}")
        yield Button("Suggest missing batches / 缺失批次建议（仅本地读取）", id="kp-batches")
        for key, word in _ACTION_WORDS.items():
            yield Input(placeholder=word, id=f"kp-{key}")
        yield Button("Prepare and save / 准备并保存（可能计费）", id="kp-prepare")
        yield Button("Execute approved plan / 执行已审查计划（远端覆盖写入）", id="kp-execute")
        yield Button("Cancel / 取消", id="kp-cancel", disabled=True)
        yield Static("Nothing loaded / 尚未读取", id="kp-result", markup=False)

    def _consume_consents(self) -> dict[str, str]:
        values = {key: self.query_one(f"#kp-{key}", Input).value
                  for key in ("read", "target", "ids", *_ACTION_WORDS)}
        for key in values:
            self.query_one(f"#kp-{key}", Input).value = ""
        return values

    def _capture(self, *, catalog: bool = False) -> tuple[Path, str | None, bool]:
        consent = self._consume_consents()
        read, target = consent["read"], consent["target"]
        extra = [consent[key] for key in ("ids", *_ACTION_WORDS)]
        raw = self.query_one("#kp-database", Input).value
        digest = self.query_one("#kp-manifest-filter" if catalog else "#kp-digest", Input).value
        if read != "READ PLAN" or target not in {"", "SHOW TARGET"} or not raw.strip() or any(extra):
            raise ValueError("plan read consent required")
        if digest or not catalog:
            _digest(digest)
        path = Path(raw)
        return (path if path.is_absolute() else self.workspace / path, digest or None, target == "SHOW TARGET")

    def _capture_batches(self) -> _BatchAdviceRequest:
        consent = self._consume_consents()
        if (consent["read"] != "READ BATCH INPUTS" or consent["ids"] not in {"", "SHOW BATCH IDS"}
                or consent["target"] or any(consent[key] for key in _ACTION_WORDS)):
            raise ValueError("batch advice requires separate read/disclosure consent")

        def value(key: str) -> str:
            return self.query_one(f"#kp-{key}", Input).value

        def number(key: str) -> int:
            raw = value(key)
            if not 1 <= len(raw) <= 10 or not raw.isascii() or not raw.isdecimal():
                raise ValueError("batch bound must be an ASCII positive integer")
            return int(raw)

        return _BatchAdviceRequest(
            self._path("database"), self._path("source"), value("namespace"), value("version"),
            value("manifest-filter"), consent["ids"] == "SHOW BATCH IDS", number("max-documents"),
            number("max-input-bytes"), number("max-vector-values"),
        )

    def _path(self, key: str) -> Path:
        value = self.query_one(f"#kp-{key}", Input).value
        if not value.strip():
            raise ValueError("path is required")
        path = Path(value)
        return path if path.is_absolute() else self.workspace / path

    def _capture_action(self, action: str) -> KnowledgePlanPrepareRequest | KnowledgePlanExecuteRequest:
        def value(key: str) -> str:
            return self.query_one(f"#kp-{key}", Input).value

        consent = self._consume_consents()
        if consent["ids"] or any(consent[key] not in {"", word} for key, word in _ACTION_WORDS.items()):
            raise ValueError("invalid action confirmation")
        host = KnowledgeIndexHostOptions(value("host"), value("binding"), consent["code"] == _ACTION_WORDS["code"])
        if action == "prepare":
            if any(consent[key] for key in ("write", "record", "create-journal")) or consent["target"] not in {"", "SHOW TARGET"}:
                raise ValueError("prepare does not accept execution consent")
            return KnowledgePlanPrepareRequest(
                host, self._path("source"), value("namespace"), value("version"), self._path("database"),
                parse_knowledge_document_ids(value("document-ids") or None),
                consent["read"] == "READ SOURCE", consent["embed"] == _ACTION_WORDS["embed"],
                consent["save"] == _ACTION_WORDS["save"], consent["create"] == _ACTION_WORDS["create"],
                consent["target"] == "SHOW TARGET",
            )
        if action != "execute" or any(consent[key] for key in ("target", "embed", "save", "create")):
            raise ValueError("execute does not accept preparation consent")
        return KnowledgePlanExecuteRequest(
            host, self._path("database"), value("digest"), value("approved"), self._path("journal"), value("attempt"),
            consent["read"] == "READ PLAN", consent["write"] == _ACTION_WORDS["write"],
            consent["record"] == _ACTION_WORDS["record"], consent["create-journal"] == _ACTION_WORDS["create-journal"],
        )

    def _busy(self, busy: bool) -> None:
        for widget in self.query("Input, Button"):
            widget.disabled = not busy if widget.id == "kp-cancel" else busy

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id not in {"kp-inspect", "kp-list", "kp-batches", "kp-cancel", "kp-prepare", "kp-execute"}:
            return
        event.stop()
        if event.button.id == "kp-cancel":
            if self._operation_task is not None:
                self._operation_task.cancel()
            return
        if self._panel_closing or (self._operation_task is not None and not self._operation_task.done()):
            return
        try:
            action = event.button.id.removeprefix("kp-")
            if action in {"inspect", "list"}:
                captured = self._capture(catalog=action == "list")
            elif action == "batches":
                captured = self._capture_batches()
            else:
                captured = self._capture_action(action)
        except Exception:
            self.query_one("#kp-result", Static).update("Invalid options/consent / 参数或确认无效")
            return
        self._busy(True)
        self.query_one("#kp-result", Static).update("Working / 处理中")
        if action == "inspect":
            operation = self._inspect(*captured)
        elif action == "list":
            operation = self._catalog(*captured)
        elif action == "batches":
            operation = self._batches(captured)
        else:
            operation = self._action(captured)
        self._operation_task = asyncio.create_task(operation)
        self._operation_task.add_done_callback(self._finished)

    async def _batches(self, request: _BatchAdviceRequest) -> None:
        try:
            result = await review_missing_knowledge_batches(
                request.plan_database, request.source_database, request.namespace, request.version,
                request.manifest_digest, confirm_read=True, include_ids=request.include_ids,
                max_documents=request.max_documents, max_input_bytes=request.max_input_bytes,
                max_vector_values=request.max_vector_values,
            )
            output = json.dumps(result, ensure_ascii=True, indent=2)
        except asyncio.CancelledError:
            output = "Batch advice cancelled; no preparation/write requested / 批次建议已取消，未请求准备或写入"
        except Exception:
            output = "Batch advice failed; check consent, snapshot identity and limits / 批次建议失败，请检查授权、快照身份与限额"
        if not self._panel_closing:
            self.query_one("#kp-result", Static).update(Text(output))

    async def _catalog(self, path: Path, manifest_digest: str | None, include_target: bool) -> None:
        try:
            result = await review_knowledge_plan_catalog(
                path, manifest_digest=manifest_digest, confirm_read=True, include_target=include_target,
            )
            output = json.dumps(result, ensure_ascii=True, indent=2)
        except asyncio.CancelledError:
            output = "Catalog cancelled / 目录读取已取消"
        except Exception:
            output = "Catalog read failed; no execution requested / 目录读取失败，未请求执行"
        if not self._panel_closing:
            self.query_one("#kp-result", Static).update(Text(output))

    async def _action(self, request: KnowledgePlanPrepareRequest | KnowledgePlanExecuteRequest) -> None:
        try:
            result = (await prepare_local_knowledge_plan(request) if isinstance(request, KnowledgePlanPrepareRequest)
                      else await execute_local_knowledge_plan(request))
            output = json.dumps(result, ensure_ascii=True, indent=2)
        except (Exception, asyncio.CancelledError):
            output = "Stopped/failed; billing or writes may already exist. Inspect before retry. / 已停止或失败，可能已计费或写入，请先核对状态。"
        if not self._panel_closing:
            self.query_one("#kp-result", Static).update(Text(output))

    async def _inspect(self, path: Path, digest: str, include_target: bool) -> None:
        try:
            result = await inspect_stored_knowledge_plan(path, digest, confirm_read=True, include_target=include_target)
            output = json.dumps(result, ensure_ascii=True, indent=2)
        except asyncio.CancelledError:
            output = "Cancelled / 已取消"
        except Exception:
            output = "Read failed; no execution requested / 读取失败，未请求执行"
        if not self._panel_closing:
            self.query_one("#kp-result", Static).update(Text(output))

    def _finished(self, task: asyncio.Task[None]) -> None:
        cancelled = task.cancelled()
        error = None if cancelled else task.exception()
        if self._panel_closing or task is not self._operation_task:
            return
        if cancelled or error is not None:
            self.query_one("#kp-result", Static).update("Stopped; inspect state before retry / 已停止，重试前请核对状态")
        self._busy(False)

    async def on_unmount(self) -> None:
        self._panel_closing = True
        if self._operation_task is not None and not self._operation_task.done():
            self._operation_task.cancel()
            try:
                await self._operation_task
            except asyncio.CancelledError:
                pass
