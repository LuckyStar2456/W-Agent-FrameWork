"""Focused TUI authority, frozen-request and asynchronous dispatch coverage."""

import asyncio
import json

import pytest

pytest.importorskip("textual")
from textual.app import App
from textual.widgets import Button, Checkbox, Input, Static

import w_agent.tui_knowledge_sync as ui
from w_agent.tui_knowledge_sync import KnowledgeSyncPanel, _CONFIRMATIONS
from w_agent.knowledge_import_store import SQLiteKnowledgeImportStore


class PanelApp(App):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace

    def compose(self):
        yield KnowledgeSyncPanel(self.workspace)


def fields(app, **values):
    for key, value in values.items():
        app.query_one("#ks-" + key.replace("_", "-"), Input).value = value


def consent(app, *names):
    for name in names:
        app.query_one(f"#ks-{name}", Input).value = _CONFIRMATIONS[name]


def base_fields(app):
    fields(app, journal="sync.db", plan="a" * 64, host="trusted.factory:open_host", binding="dedicated",
           trace="trace.db", namespace="manual", version="v2", trace_digest="b" * 64)


@pytest.mark.asyncio
async def test_optional_document_format_captured_and_real_docx_saved(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("optional sync document")
    document.save(tmp_path / "source.docx")
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        base_fields(app)
        fields(app, paths='["source.docx"]')
        assert not app.query_one("#ks-document-formats", Checkbox).value
        app.query_one("#ks-document-formats", Checkbox).value = True
        consent(app, "read")
        await press(panel, "preview")
        await panel._operation_task
        preview = json.loads(panel._display)
        fields(app, preview_digest=preview["preview_digest"])
        consent(app, "read", "record", "create")
        await press(panel, "import")
        await panel._operation_task
        assert json.loads(panel._display)["recorded"]
        trace = await SQLiteKnowledgeImportStore(tmp_path / "trace.db").load("manual", "v2")
        assert trace.snapshot.documents[0].text == "optional sync document"


async def press(panel, action):
    await panel.on_button_pressed(Button.Pressed(panel.query_one(f"#ks-{action}", Button)))


@pytest.mark.asyncio
async def test_no_automatic_io_and_inspect_has_no_host_request(tmp_path, monkeypatch):
    calls = []

    async def inspect(request):
        calls.append(request)
        return {"state": "ready", "sensitive": "\x1b[2J\u202e[red]"}

    monkeypatch.setattr(ui, "inspect_local_knowledge_sync", inspect)
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        assert not calls
        base_fields(app)
        await press(panel, "inspect")
        assert not calls
        consent(app, "read")
        await press(panel, "inspect")
        await panel._operation_task
        assert len(calls) == 1 and calls[0].journal_database == tmp_path / "sync.db"
        assert not hasattr(calls[0], "host")
        assert app.query_one("#ks-read", Input).value == ""
        output = str(app.query_one("#ks-result", Static).render())
        assert "\x1b" not in output and "\u202e" not in output
        assert r"\u001b" in output and r"\u202e" in output
        assert not app.query_one("#ks-approved-plan", Input).value
        await press(panel, "inspect")
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_inspection_rejects_unrelated_confirmation_and_consumes_all(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        base_fields(app)
        for name in set(_CONFIRMATIONS) - {"read"}:
            consent(app, "read", name)
            with pytest.raises(ValueError):
                panel._capture("inspect")
            assert all(not app.query_one(f"#ks-{key}", Input).value for key in _CONFIRMATIONS)


@pytest.mark.asyncio
async def test_prepare_separate_consents_and_frozen_capture(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        base_fields(app)
        consent(app, "read", "code", "embed")
        with pytest.raises(ValueError):
            panel._capture("prepare")
        consent(app, "read", "code", "embed", "record", "create")
        captured = panel._capture("prepare")
        fields(app, version="changed", trace="other.db")
        assert captured.version == "v2" and captured.trace_database == tmp_path / "trace.db"
        assert captured.confirm_embedding and captured.confirm_record and captured.confirm_create
        assert captured.expected_trace_digest == "b" * 64
        assert captured.previous_plan_digest is None and captured.approved_reuse_digest is None
        assert all(not app.query_one(f"#ks-{key}", Input).value for key in _CONFIRMATIONS)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,word", [("approved_upsert", "upsert"), ("approved_delete", "delete")])
async def test_write_digest_requires_independent_action_consent(tmp_path, field, word):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        base_fields(app)
        fields(app, approved_plan="a" * 64, **{field: "c" * 64})
        consent(app, "read", "code", "record")
        with pytest.raises(ValueError):
            panel._capture("execute")
        consent(app, "read", "code", "record", word)
        request = panel._capture("execute")
        assert getattr(request, field + "_digest") == "c" * 64
        fields(app, **{field: ""})
        consent(app, "read", "code", "record", word)
        with pytest.raises(ValueError):
            panel._capture("execute")


@pytest.mark.asyncio
async def test_plan_approval_mismatch_rejected_before_dispatch(tmp_path, monkeypatch):
    async def forbidden(request):
        pytest.fail("mismatched approval reached execution")
    monkeypatch.setattr(ui, "execute_local_knowledge_sync", forbidden)
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        base_fields(app)
        fields(app, approved_plan="c" * 64)
        consent(app, "read", "code", "record")
        await press(panel, "execute")
        assert panel._operation_task is None


@pytest.mark.asyncio
async def test_locks_controls_single_dispatch_and_cancel_warning(tmp_path, monkeypatch):
    entered, calls = asyncio.Event(), []

    async def execute(request):
        calls.append(request)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(ui, "execute_local_knowledge_sync", execute)
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        base_fields(app)
        fields(app, approved_plan="a" * 64, approved_upsert="c" * 64, approved_delete="d" * 64)
        consent(app, "read", "code", "record", "upsert", "delete")
        await press(panel, "execute")
        await asyncio.wait_for(entered.wait(), 5)
        assert app.query_one("#ks-plan", Input).disabled
        assert app.query_one("#ks-inspect", Button).disabled
        assert not app.query_one("#ks-cancel", Button).disabled
        await press(panel, "execute")
        assert len(calls) == 1
        await press(panel, "cancel")
        await panel._operation_task
        await asyncio.sleep(0)
        assert not app.query_one("#ks-plan", Input).disabled
        assert "Unknown outcomes" in str(app.query_one("#ks-result", Static).render())
        await press(panel, "execute")
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_prepare_and_unknown_result_do_not_autofill_or_retry(tmp_path, monkeypatch):
    calls = []
    async def prepare(request):
        calls.append(request)
        return {"plan_digest": "a" * 64, "upsert_digest": "c" * 64, "outcomes": ["unknown"]}
    monkeypatch.setattr(ui, "prepare_local_knowledge_sync", prepare)
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        base_fields(app)
        consent(app, "read", "code", "embed", "record")
        await press(panel, "prepare")
        await panel._operation_task
        assert len(calls) == 1
        assert "unknown" in str(app.query_one("#ks-result", Static).render())
        assert app.query_one("#ks-approved-plan", Input).value == ""
        assert app.query_one("#ks-approved-upsert", Input).value == ""
        await press(panel, "prepare")
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_oversized_result_paging_never_dispatches(tmp_path, monkeypatch):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        panel._show("A" * 16000 + "B" * 4)
        await press(panel, "next")
        assert str(app.query_one("#ks-result", Static).render()) == "BBBB"
        await press(panel, "prev")
        assert panel._display_offset == 0
        assert panel._operation_task is None


@pytest.mark.asyncio
async def test_real_trace_preview_then_digest_locked_save_without_host(tmp_path):
    (tmp_path / "manual.md").write_text("local sync fixture", encoding="utf-8")
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        base_fields(app)
        fields(app, paths='["manual.md"]')
        consent(app, "read")
        await press(panel, "preview")
        await panel._operation_task
        preview = json.loads(panel._display)
        assert preview["recorded"] is False
        assert not (tmp_path / "trace.db").exists()
        assert not app.query_one("#ks-preview-digest", Input).value
        fields(app, preview_digest=preview["preview_digest"])
        consent(app, "read", "record", "create")
        await press(panel, "import")
        await panel._operation_task
        saved = json.loads(panel._display)
        assert saved["recorded"] is True
        loaded = await SQLiteKnowledgeImportStore(tmp_path / "trace.db").load("manual", "v2")
        assert loaded.digest == saved["trace_digest"]
        assert loaded.snapshot.documents[0].text == "local sync fixture"
        assert not (tmp_path / "sync.db").exists()


@pytest.mark.asyncio
async def test_changed_trace_rejects_locked_save_before_database_creation(tmp_path):
    source = tmp_path / "manual.md"
    source.write_text("before", encoding="utf-8")
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        base_fields(app)
        fields(app, paths='["manual.md"]')
        consent(app, "read")
        await press(panel, "preview")
        await panel._operation_task
        digest = json.loads(panel._display)["preview_digest"]
        source.write_text("after", encoding="utf-8")
        fields(app, preview_digest=digest)
        consent(app, "read", "record", "create")
        await press(panel, "import")
        await panel._operation_task
        assert not (tmp_path / "trace.db").exists()
        assert "Stopped/failed" in panel._display


@pytest.mark.asyncio
async def test_import_requires_save_digest_and_preview_rejects_write_consent(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        base_fields(app)
        consent(app, "read", "record", "create")
        with pytest.raises(ValueError):
            panel._capture("import")
        consent(app, "read", "record")
        with pytest.raises(ValueError):
            panel._capture("preview")
        fields(app, paths='[]')
        consent(app, "read")
        assert panel._capture("preview").paths == ()
        for invalid in ('"not-array"', '[true]', '{"path": "manual.md"}'):
            fields(app, paths=invalid)
            consent(app, "read")
            with pytest.raises(ValueError):
                panel._capture("preview")
