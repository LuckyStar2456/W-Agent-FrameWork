"""Explicit immutable build selection and one-batch execution UI."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Label, Static

from w_agent.knowledge_build_management import (
    KnowledgeBuildExecuteRequest, create_local_knowledge_build,
    execute_local_knowledge_build_batch, review_local_knowledge_build,
    list_local_knowledge_builds,
)
from w_agent.knowledge_index_journal import _digest
from w_agent.knowledge_ingestion import _label
from w_agent.knowledge_plan_actions import KnowledgeIndexHostOptions

_WORDS = {
    "read": "READ BUILD INPUTS", "save": "SAVE BUILD", "create": "CREATE BUILD STORE",
    "code": "LOAD INDEX HOST", "write": "WRITE INDEX", "record": "RECORD WRITE",
    "create-journal": "CREATE INDEX JOURNAL",
}


@dataclass(frozen=True, slots=True)
class _Create:
    plans: Path
    builds: Path
    name: str
    version: str
    artifacts: tuple[str, ...]
    save: bool
    create: bool


@dataclass(frozen=True, slots=True)
class _Review:
    builds: Path
    name: str
    version: str
    journal: Path | None


@dataclass(frozen=True, slots=True)
class _Catalog:
    builds: Path


class KnowledgeBuildsPanel(Vertical):
    DEFAULT_CSS = "KnowledgeBuildsPanel { height: auto; }"

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace
        self._operation_task: asyncio.Task[None] | None = None
        self._panel_closing = False

    def compose(self) -> ComposeResult:
        yield Label("Named immutable builds / 命名不可变构建：local receipts are not remote verification / 本地回执不等于远端核验")
        for key, hint, initial in (
            ("builds", "Build DB / 构建库", str(self.workspace / ".wagent" / "knowledge-builds.sqlite3")),
            ("plans", "Plan DB / 计划库", str(self.workspace / ".wagent" / "knowledge-plans.sqlite3")),
            ("name", "Build name / 构建名称", ""), ("version", "Exact version / 精确版本", ""),
            ("artifacts", "Create: JSON array of reviewed artifact digests / 创建：完整批次摘要 JSON 数组", ""),
            ("journal", "Journal DB: optional for review, required for execute / 查看可选、执行必填", ""),
            ("artifact", "Execute: one selected artifact SHA-256 / 执行：一个工件摘要", ""),
            ("approved-build", "Separately reviewed build SHA-256 / 独立审查的构建摘要", ""),
            ("approved-artifact", "Separately reviewed artifact SHA-256 / 独立审查的工件摘要", ""),
            ("previous-attempt", "Retry only: exact prior not-sent/not-applied attempt / 显式重试的前次尝试 ID", ""),
            ("host", "Host module:factory / 宿主工厂", ""), ("binding", "Named host binding / 宿主绑定", ""),
        ):
            yield Input(initial, placeholder=hint, id=f"kb-{key}")
        yield Label("Host Python executes locally WITHOUT isolation, only with explicit developer consent. / 宿主 Python 仅在明确授权下本地不隔离执行。")
        for key, word in _WORDS.items():
            yield Input(placeholder=word, id=f"kb-{key}")
        yield Button("Preview/save build / 预览或保存构建", id="kb-assemble")
        yield Button("Inspect build/progress / 查看构建与进度", id="kb-inspect")
        yield Button("List saved builds / 列出已保存构建", id="kb-list")
        yield Button("Execute ONE batch / 执行一个批次（远端覆盖写入）", id="kb-execute")
        yield Button("Cancel / 取消", id="kb-cancel", disabled=True)
        yield Static("Nothing loaded / 尚未读取", id="kb-result", markup=False)

    def _value(self, key: str) -> str:
        return self.query_one(f"#kb-{key}", Input).value

    def _path(self, key: str) -> Path:
        raw = self._value(key)
        if not raw.strip():
            raise ValueError("explicit path required")
        path = Path(raw)
        return path if path.is_absolute() else self.workspace / path

    def _capture(self, action: str) -> _Create | _Review | _Catalog | KnowledgeBuildExecuteRequest:
        consent = {key: self._value(key) for key in _WORDS}
        # Consume all action words, including invalid or unrelated confirmations.
        for key in _WORDS:
            self.query_one(f"#kb-{key}", Input).value = ""
        if (action not in {"assemble", "inspect", "execute", "list"}
                or any(consent[key] not in {"", word} for key, word in _WORDS.items())
                or consent["read"] != _WORDS["read"]):
            raise ValueError("build action confirmation invalid")
        if action == "list":
            if any(value for key, value in consent.items() if key != "read"):
                raise ValueError("catalog accepts only read consent")
            return _Catalog(self._path("builds"))
        name, version = self._value("name"), self._value("version")
        _label(name)
        _label(version)
        builds = self._path("builds")
        if action == "execute":
            if consent["save"] or consent["create"]:
                raise ValueError("execution does not create a build")
            return KnowledgeBuildExecuteRequest(
                host=KnowledgeIndexHostOptions(self._value("host"), self._value("binding"), bool(consent["code"])),
                build_database=builds, name=name, version=version,
                plan_database=self._path("plans"), journal_database=self._path("journal"),
                artifact_digest=self._value("artifact"), approved_build_digest=self._value("approved-build"),
                approved_artifact_digest=self._value("approved-artifact"), confirm_read=True,
                confirm_remote_write=bool(consent["write"]), confirm_record=bool(consent["record"]),
                confirm_create_journal=bool(consent["create-journal"]),
                previous_attempt_id=self._value("previous-attempt") or None,
            )
        if any(consent[key] for key in ("code", "write", "record", "create-journal")):
            raise ValueError("read/create does not accept execution consent")
        if action == "inspect":
            if consent["save"] or consent["create"]:
                raise ValueError("inspection does not accept save consent")
            journal = self._path("journal") if self._value("journal") else None
            return _Review(builds, name, version, journal)
        if consent["create"] and not consent["save"]:
            raise ValueError("creation requires save confirmation")
        raw = self._value("artifacts")
        if len(raw.encode("utf-8")) > 16384:
            raise ValueError("artifact selection too large")
        items = json.loads(raw)
        if not isinstance(items, list) or not 1 <= len(items) <= 128:
            raise ValueError("explicit artifact array required")
        for item in items:
            _digest(item)
        if len(set(items)) != len(items):
            raise ValueError("duplicate artifact selection")
        return _Create(self._path("plans"), builds, name, version, tuple(items),
                       bool(consent["save"]), bool(consent["create"]))

    def _busy(self, busy: bool) -> None:
        for widget in self.query("Input, Button"):
            widget.disabled = not busy if widget.id == "kb-cancel" else busy

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id not in {"kb-assemble", "kb-inspect", "kb-execute", "kb-cancel", "kb-list"}:
            return
        event.stop()
        if event.button.id == "kb-cancel":
            if self._operation_task is not None and not self._operation_task.done():
                self._operation_task.cancel()
            return
        if self._panel_closing or (self._operation_task is not None and not self._operation_task.done()):
            return
        try:
            request = self._capture(event.button.id.removeprefix("kb-"))
        except Exception:
            self.query_one("#kb-result", Static).update("Invalid options/consent / 参数或确认无效")
            return
        self._busy(True)
        self.query_one("#kb-result", Static).update("Working / 处理中")
        self._operation_task = asyncio.create_task(self._run(request))
        self._operation_task.add_done_callback(self._finished)

    async def _run(self, request: _Create | _Review | _Catalog | KnowledgeBuildExecuteRequest) -> None:
        try:
            if isinstance(request, _Catalog):
                result = await list_local_knowledge_builds(request.builds, confirm_read=True)
            elif isinstance(request, _Create):
                result = await create_local_knowledge_build(
                    request.plans, request.builds, request.name, request.version, request.artifacts,
                    confirm_read=True, confirm_save=request.save, confirm_create=request.create,
                )
            elif isinstance(request, _Review):
                result = await review_local_knowledge_build(
                    request.builds, request.name, request.version, confirm_read=True,
                    journal_database=request.journal,
                )
            else:
                result = await execute_local_knowledge_build_batch(request)
            output = json.dumps(result, ensure_ascii=True, indent=2)
        except (Exception, asyncio.CancelledError):
            output = "Stopped/failed; local saves or remote writes may already exist. Inspect before retry. / 已停止或失败，可能已保存或远端写入，请先核对状态。"
        if not self._panel_closing:
            self.query_one("#kb-result", Static).update(Text(output))

    def _finished(self, task: asyncio.Task[None]) -> None:
        cancelled = task.cancelled()
        error = None if cancelled else task.exception()
        if self._panel_closing or task is not self._operation_task:
            return
        if cancelled or error is not None:
            self.query_one("#kb-result", Static).update("Stopped; inspect before retry / 已停止，重试前请核对状态")
        self._busy(False)

    async def on_unmount(self) -> None:
        self._panel_closing = True
        if self._operation_task is not None and not self._operation_task.done():
            self._operation_task.cancel()
            try:
                await self._operation_task
            except asyncio.CancelledError:
                pass
