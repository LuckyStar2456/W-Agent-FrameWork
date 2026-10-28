"""One developer project through Python, real CLI and the headless TUI panel."""

import asyncio
import json
from types import ModuleType
import sys

import pytest
from typer.testing import CliRunner

from w_agent import (
    ApplicationCall, ApplicationOperation, ApplicationProject, ComponentDefinition,
    compile_assembly, execute_application_entry, load_application_call,
    ApplicationEntryError,
)


@pytest.fixture
def developer_project(tmp_path, monkeypatch):
    events = []

    class Harness:
        def run(self, text, *, suffix):
            events.append("run")
            return {"custom": text + suffix}

    def factory():
        return ApplicationProject(compile_assembly((ComponentDefinition(
            "harness", Harness, scope="run",
            initialize=lambda obj: events.append("init"), dispose=lambda obj: events.append("close"),
        ),)), {"answer": ApplicationOperation("harness")})

    module = ModuleType("frontend_developer_project")
    module.create = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    path = tmp_path / "call.json"
    path.write_text(json.dumps({"operation": "answer", "args": ["hello"], "kwargs": {"suffix": "!"}}), encoding="utf-8")
    return f"{module.__name__}:create", path, events


def test_real_cli_and_python_share_custom_project(developer_project):
    from w_agent.cli import app
    entry, path, events = developer_project
    call = load_application_call(path)
    expected = asyncio.run(execute_application_entry(entry, call, confirmed=True))
    result = CliRunner().invoke(app, ["application", "run", "--entry", entry,
                                     "--input-file", str(path), "--confirm-code"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"result": expected}
    assert events == ["init", "run", "close"] * 2


def test_cli_confirmation_precedes_read_and_import(developer_project):
    from w_agent.cli import app
    entry, path, events = developer_project
    result = CliRunner().invoke(app, ["application", "run", "--entry", entry,
                                     "--input-file", str(path.parent / "missing.json")])
    assert result.exit_code == 2 and "--confirm-code" in result.output
    assert events == []


@pytest.mark.asyncio
async def test_tui_panel_uses_same_project_and_consumes_authorization(developer_project):
    pytest.importorskip("textual")
    from textual.app import App
    from textual.widgets import Input, Static
    from w_agent.tui_application import ApplicationPanel
    entry, path, events = developer_project

    class TestApp(App):
        def compose(self):
            yield ApplicationPanel(path.parent)

    app = TestApp()
    async with app.run_test():
        panel = app.query_one(ApplicationPanel)
        app.query_one("#application-entry", Input).value = entry
        app.query_one("#application-input", Input).value = path.name
        panel._begin()
        assert events == []
        app.query_one("#application-confirm", Input).value = "RUN APPLICATION"
        panel._begin()
        await panel._operation_task
        assert app.query_one("#application-confirm", Input).value == ""
        assert '"hello!"' in str(app.query_one("#application-result", Static).content)
    assert events == ["init", "run", "close"]


@pytest.mark.parametrize("contents", [
    '{"args":[],"args":[]}', '{"args":[NaN]}', '{"import":"forbidden"}',
    '{"kwargs":{"bad-key":1}}', '{"args":"not-array"}',
])
def test_call_documents_are_data_only_and_reject_ambiguity(tmp_path, contents):
    path = tmp_path / "invalid.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ApplicationEntryError):
        load_application_call(path)


@pytest.mark.asyncio
async def test_tui_cancel_before_worker_starts_releases_controls(developer_project):
    pytest.importorskip("textual")
    from textual.app import App
    from textual.widgets import Button, Input
    from w_agent.tui_application import ApplicationPanel
    entry, path, events = developer_project

    class TestApp(App):
        def compose(self):
            yield ApplicationPanel(path.parent)

    app = TestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(ApplicationPanel)
        app.query_one("#application-entry", Input).value = entry
        app.query_one("#application-input", Input).value = path.name
        app.query_one("#application-confirm", Input).value = "RUN APPLICATION"
        panel._begin()
        panel._cancel()
        with pytest.raises(asyncio.CancelledError):
            await panel._operation_task
        await pilot.pause()
        assert not app.query_one("#application-run", Button).disabled
    assert events == []
