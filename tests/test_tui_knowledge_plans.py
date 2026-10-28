"""Draft plan inspection consent/capture tests; unexecuted."""

import asyncio

import pytest

pytest.importorskip("textual")
from textual.app import App
from textual.widgets import Button

import w_agent.tui_knowledge_plans as panel_module
from w_agent.tui_knowledge_plans import KnowledgePlansPanel
from w_agent.tui_knowledge_plans import _ACTION_WORDS


class PanelApp(App):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace

    def compose(self):
        yield KnowledgePlansPanel(self.workspace)


def batch_fields(app):
    for key, value in {"source": "source.db", "namespace": "n", "version": "v1",
                       "manifest-filter": "a" * 64, "max-documents": "2"}.items():
        app.query_one(f"#kp-{key}").value = value


@pytest.mark.asyncio
async def test_batch_capture_is_frozen_and_requires_distinct_consent(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgePlansPanel)
        batch_fields(app)
        for wrong in ("", "READ PLAN", "READ SOURCE"):
            app.query_one("#kp-read").value = wrong
            app.query_one("#kp-ids").value = "SHOW BATCH IDS"
            with pytest.raises(ValueError):
                panel._capture_batches()
            assert app.query_one("#kp-read").value == app.query_one("#kp-ids").value == ""
        app.query_one("#kp-read").value = "READ BATCH INPUTS"
        request = panel._capture_batches()
        assert request.include_ids is False and request.max_documents == 2
        assert request.source_database == tmp_path / "source.db"
        app.query_one("#kp-version").value = "different"
        app.query_one("#kp-max-documents").value = "128"
        assert request.version == "v1" and request.max_documents == 2
        assert app.query_one("#kp-host").value == app.query_one("#kp-binding").value == ""


@pytest.mark.asyncio
async def test_batch_disclosure_cannot_authorize_other_actions(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgePlansPanel)
        batch_fields(app)
        for key in ("target", *_ACTION_WORDS):
            app.query_one("#kp-read").value = "READ BATCH INPUTS"
            app.query_one(f"#kp-{key}").value = "SHOW TARGET" if key == "target" else _ACTION_WORDS[key]
            with pytest.raises(ValueError):
                panel._capture_batches()
            assert app.query_one(f"#kp-{key}").value == ""
        app.query_one("#kp-read").value = "READ PLAN"
        app.query_one("#kp-ids").value = "SHOW BATCH IDS"
        with pytest.raises(ValueError):
            panel._capture(catalog=True)
        app.query_one("#kp-read").value = "READ SOURCE"
        app.query_one("#kp-ids").value = "SHOW BATCH IDS"
        with pytest.raises(ValueError):
            panel._capture_action("prepare")


@pytest.mark.asyncio
async def test_batch_capture_rejects_missing_identity_or_invalid_bounds(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgePlansPanel)
        batch_fields(app)
        for invalid in ("0", "129", "-1", "1.5", " 2", "２", "9" * 11):
            app.query_one("#kp-read").value = "READ BATCH INPUTS"
            app.query_one("#kp-max-documents").value = invalid
            with pytest.raises(ValueError):
                panel._capture_batches()
        app.query_one("#kp-max-documents").value = "2"
        app.query_one("#kp-manifest-filter").value = ""
        app.query_one("#kp-read").value = "READ BATCH INPUTS"
        with pytest.raises(ValueError):
            panel._capture_batches()


@pytest.mark.asyncio
async def test_batch_action_read_only_capture_lock_and_cancel(tmp_path, monkeypatch):
    calls, entered = [], asyncio.Event()

    async def advice(*args, **kwargs):
        calls.append((args, kwargs))
        entered.set()
        await asyncio.Event().wait()

    async def forbidden(*args, **kwargs):
        pytest.fail("batch advice must not prepare or execute")

    monkeypatch.setattr(panel_module, "review_missing_knowledge_batches", advice)
    monkeypatch.setattr(panel_module, "prepare_local_knowledge_plan", forbidden)
    monkeypatch.setattr(panel_module, "execute_local_knowledge_plan", forbidden)
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgePlansPanel)
        assert not calls
        batch_fields(app)
        app.query_one("#kp-read").value = "READ BATCH INPUTS"
        app.query_one("#kp-ids").value = "SHOW BATCH IDS"
        await panel.on_button_pressed(Button.Pressed(app.query_one("#kp-batches", Button)))
        await entered.wait()
        assert calls[0][0][2:] == ("n", "v1", "a" * 64)
        assert calls[0][1]["include_ids"] is True and calls[0][1]["max_documents"] == 2
        assert app.query_one("#kp-source").disabled and app.query_one("#kp-max-documents").disabled
        assert app.query_one("#kp-document-ids").value == app.query_one("#kp-approved").value == ""
        await panel.on_button_pressed(Button.Pressed(app.query_one("#kp-cancel", Button)))
        await panel._operation_task
        assert not app.query_one("#kp-source").disabled
        assert app.query_one("#kp-read").value == app.query_one("#kp-ids").value == ""


@pytest.mark.asyncio
async def test_plan_capture_is_explicit_and_no_automatic_read(tmp_path, monkeypatch):
    calls = []
    entered = asyncio.Event()

    async def inspect(path, digest, **kwargs):
        calls.append((path, digest, kwargs))
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(panel_module, "inspect_stored_knowledge_plan", inspect)
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgePlansPanel)
        assert not calls
        app.query_one("#kp-digest").value = "a" * 64
        with pytest.raises(ValueError):
            panel._capture()
        app.query_one("#kp-read").value = "READ PLAN"
        app.query_one("#kp-target").value = "SHOW TARGET"
        await panel.on_button_pressed(Button.Pressed(app.query_one("#kp-inspect", Button)))
        await entered.wait()
        assert app.query_one("#kp-digest").disabled
        assert app.query_one("#kp-read").value == app.query_one("#kp-target").value == ""
        assert calls[0][1] == "a" * 64 and calls[0][2]["include_target"] is True
        await panel.on_button_pressed(Button.Pressed(app.query_one("#kp-cancel", Button)))
        await panel._operation_task
        assert not app.query_one("#kp-digest").disabled


@pytest.mark.asyncio
async def test_prepare_capture_needs_separate_consents_and_freezes_request(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgePlansPanel)
        for key, value in {"host": "host:factory", "binding": "manual", "source": "source.db",
                           "namespace": "n", "version": "v1", "document-ids": '["doc"]'}.items():
            app.query_one(f"#kp-{key}").value = value
        app.query_one("#kp-read").value = "READ SOURCE"
        for key in ("code", "embed"):
            app.query_one(f"#kp-{key}").value = _ACTION_WORDS[key]
        with pytest.raises(ValueError):
            panel._capture_action("prepare")
        assert app.query_one("#kp-read").value == ""
        app.query_one("#kp-read").value = "READ SOURCE"
        for key in ("code", "embed", "save"):
            app.query_one(f"#kp-{key}").value = _ACTION_WORDS[key]
        request = panel._capture_action("prepare")
        app.query_one("#kp-version").value = "changed"
        assert request.version == "v1" and request.source_database == tmp_path / "source.db"
        assert request.document_ids == ("doc",) and not request.confirm_create
        assert all(app.query_one(f"#kp-{key}").value == "" for key in _ACTION_WORDS)


@pytest.mark.asyncio
async def test_execute_capture_requires_exact_approval_and_no_embedding_consent(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgePlansPanel)
        for key, value in {"host": "host:factory", "binding": "write-only", "journal": "journal.db",
                           "digest": "a" * 64, "approved": "b" * 64, "attempt": "attempt-1"}.items():
            app.query_one(f"#kp-{key}").value = value

        def consent():
            app.query_one("#kp-read").value = "READ PLAN"
            for key in ("code", "write", "record"):
                app.query_one(f"#kp-{key}").value = _ACTION_WORDS[key]

        consent()
        with pytest.raises(ValueError):
            panel._capture_action("execute")
        app.query_one("#kp-approved").value = "a" * 64
        consent()
        request = panel._capture_action("execute")
        assert request.approved_digest == request.artifact_digest
        assert request.confirm_remote_write and request.confirm_record
        consent()
        app.query_one("#kp-embed").value = _ACTION_WORDS["embed"]
        with pytest.raises(ValueError):
            panel._capture_action("execute")


@pytest.mark.asyncio
async def test_catalog_capture_does_not_need_artifact_digest_and_never_loads_host(tmp_path, monkeypatch):
    calls = []

    async def review(path, **options):
        calls.append((path, options))
        return {"plans": [], "coverage": [], "remote_state_verified": False}

    monkeypatch.setattr(panel_module, "review_knowledge_plan_catalog", review)
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgePlansPanel)
        app.query_one("#kp-read").value = "READ PLAN"
        assert app.query_one("#kp-digest").value == ""
        await panel.on_button_pressed(Button.Pressed(app.query_one("#kp-list", Button)))
        await panel._operation_task
        assert calls[0][1]["manifest_digest"] is None
        assert calls[0][1]["include_target"] is False
        assert not app.query_one("#kp-database").disabled
