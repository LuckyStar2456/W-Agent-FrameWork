"""Draft build panel capture/consent/lifecycle tests; not executed."""

import asyncio
import json

import pytest

pytest.importorskip("textual")
from textual.app import App
from textual.widgets import Button

import w_agent.tui_knowledge_builds as module
from w_agent.tui_knowledge_builds import KnowledgeBuildsPanel, _WORDS


class PanelApp(App):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace

    def compose(self):
        yield KnowledgeBuildsPanel(self.workspace)


def fields(app):
    for key, value in {
        "name": "manual", "version": "v1", "artifacts": json.dumps(["a" * 64, "b" * 64]),
        "host": "host:factory", "binding": "execute", "journal": "journal.db",
        "artifact": "a" * 64, "approved-artifact": "a" * 64, "approved-build": "c" * 64,
    }.items():
        app.query_one(f"#kb-{key}").value = value


def consent(app, *keys):
    for key in keys:
        app.query_one(f"#kb-{key}").value = _WORDS[key]


@pytest.mark.asyncio
async def test_build_capture_preview_and_consents_are_consumed(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeBuildsPanel)
        fields(app)
        with pytest.raises(ValueError):
            panel._capture("assemble")
        consent(app, "read", "create")
        with pytest.raises(ValueError):
            panel._capture("assemble")
        assert all(app.query_one(f"#kb-{key}").value == "" for key in _WORDS)
        consent(app, "read")
        request = panel._capture("assemble")
        app.query_one("#kb-artifacts").value = "[]"
        app.query_one("#kb-version").value = "changed"
        assert request.version == "v1" and request.artifacts == ("a" * 64, "b" * 64)
        assert not request.save and not request.create
        consent(app, "read", "write")
        with pytest.raises(ValueError):
            panel._capture("inspect")


@pytest.mark.asyncio
async def test_build_execute_exact_approval_and_no_implicit_save(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeBuildsPanel)
        fields(app)
        app.query_one("#kb-approved-artifact").value = "b" * 64
        consent(app, "read", "code", "write", "record")
        with pytest.raises(ValueError):
            panel._capture("execute")
        app.query_one("#kb-approved-artifact").value = "a" * 64
        consent(app, "read", "code", "write", "record", "save")
        with pytest.raises(ValueError):
            panel._capture("execute")
        consent(app, "read", "code", "write", "record")
        request = panel._capture("execute")
        app.query_one("#kb-approved-build").value = "d" * 64
        assert request.approved_build_digest == "c" * 64
        assert request.journal_database == tmp_path / "journal.db" and not request.confirm_create_journal


@pytest.mark.asyncio
async def test_build_action_no_mount_io_lock_cancel_and_fixed_error(tmp_path, monkeypatch):
    calls, entered = [], asyncio.Event()

    async def execute(request):
        calls.append(request)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(module, "execute_local_knowledge_build_batch", execute)
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeBuildsPanel)
        assert not calls
        fields(app)
        consent(app, "read", "code", "write", "record")
        await panel.on_button_pressed(Button.Pressed(app.query_one("#kb-execute", Button)))
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert app.query_one("#kb-name").disabled and len(calls) == 1
        await panel.on_button_pressed(Button.Pressed(app.query_one("#kb-execute", Button)))
        assert len(calls) == 1
        await panel.on_button_pressed(Button.Pressed(app.query_one("#kb-cancel", Button)))
        await panel._operation_task
        assert not app.query_one("#kb-name").disabled
        assert all(app.query_one(f"#kb-{key}").value == "" for key in _WORDS)


@pytest.mark.asyncio
async def test_cancel_before_task_starts_unlocks(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeBuildsPanel)
        fields(app)
        consent(app, "read")
        await panel.on_button_pressed(Button.Pressed(app.query_one("#kb-inspect", Button)))
        panel._operation_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await panel._operation_task
        assert not app.query_one("#kb-name").disabled
