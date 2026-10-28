"""Local plugin CLI/TUI replacement integration; no external services."""

import json
import sys
import types

import pytest
import typer
from typer.testing import CliRunner

from w_agent.kernel.plugins import FunctionPlugin, PluginManager, PluginSpec, PluginState
from w_agent.plugin_replacement_session import PluginReplacementSession


@pytest.fixture
def plugins(tmp_path, monkeypatch):
    lifecycle = []
    module = types.ModuleType("replacement_session_fixture")
    module.old = FunctionPlugin(PluginSpec("demo", "1"), lambda _: lifecycle.append("old"))
    def setup(context):
        lifecycle.append(context.config["token"])
    module.new = FunctionPlugin(PluginSpec("demo", "2"), setup)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    initial = tmp_path / "initial.yml"
    source = tmp_path / "replacement.yml"
    initial.write_text(f"plugins:\n- entry: {module.__name__}:old\n", encoding="utf-8")
    source.write_text(f"plugins:\n- entry: {module.__name__}:new\n  config:\n    token: SECRET_TOKEN\n", encoding="utf-8")
    return module, initial, source, lifecycle


@pytest.mark.asyncio
async def test_review_to_execute_and_config_values_hidden(plugins):
    module, _, source, lifecycle = plugins
    manager = PluginManager()
    old = await manager.load(module.old)
    session = PluginReplacementSession(manager)
    preview = session.inspect(source)
    assert "SECRET_TOKEN" not in json.dumps(preview)
    assert lifecycle == ["old"]
    plan = await session.prepare(import_confirmation=preview["import_confirmation"])
    assert "SECRET_TOKEN" not in json.dumps(plan)
    result = await session.execute(replace_confirmation=plan["replace_confirmation"], quiescent_confirmation=plan["quiescent_confirmation"])
    assert lifecycle == ["old", "SECRET_TOKEN"]
    assert old.state == PluginState.DISPOSED
    assert result["scope"] == "current_process_only"
    assert result["other_processes_updated"] is False
    assert session.plan is None
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["prepare", "execute"])
async def test_file_drift_does_not_replace(plugins, stage):
    module, _, source, _ = plugins
    manager = PluginManager()
    old = await manager.load(module.old)
    session = PluginReplacementSession(manager)
    preview = session.inspect(source)
    if stage == "execute":
        plan = await session.prepare(import_confirmation=preview["import_confirmation"])
    source.write_text("plugins: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        if stage == "prepare":
            await session.prepare(import_confirmation=preview["import_confirmation"])
        else:
            await session.execute(replace_confirmation=plan["replace_confirmation"], quiescent_confirmation=plan["quiescent_confirmation"])
    assert old.state == PluginState.ACTIVE
    assert session.plan is None


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["import", "replace", "quiescent", "busy", "installed"])
async def test_authorization_and_host_boundaries(plugins, boundary):
    module, _, source, lifecycle = plugins
    manager = PluginManager()
    old = await manager.load(module.old)
    session = PluginReplacementSession(manager)
    preview = session.inspect(source)
    if boundary == "import":
        with pytest.raises(ValueError, match="import confirmation"):
            await session.prepare(import_confirmation="yes")
    else:
        plan = await session.prepare(import_confirmation=preview["import_confirmation"])
        with pytest.raises(ValueError):
            await session.execute(
                replace_confirmation="yes" if boundary == "replace" else plan["replace_confirmation"],
                quiescent_confirmation="yes" if boundary == "quiescent" else plan["quiescent_confirmation"],
                host_busy=boundary == "busy",
                blocked_names=frozenset({"demo"}) if boundary == "installed" else frozenset(),
            )
        assert session.plan is None
    assert old.state == PluginState.ACTIVE
    assert lifecycle == ["old"]


@pytest.mark.asyncio
async def test_cancel_old_review_cannot_cancel_new_manager_plan(plugins):
    module, _, source, _ = plugins
    manager = PluginManager()
    await manager.load(module.old)
    session = PluginReplacementSession(manager)
    preview = session.inspect(source)
    await session.prepare(import_confirmation=preview["import_confirmation"])
    newer = await manager.plan_replacement(FunctionPlugin(PluginSpec("demo", "3"), lambda _: None))
    session.cancel()
    handle = await manager.replace(newer, expected_plan_id=newer.plan_id, host_quiescent=True)
    assert handle.state == PluginState.ACTIVE


@pytest.mark.asyncio
async def test_cancel_discards_exact_retained_plan(plugins):
    from w_agent.kernel.plugins import PluginReplacementError
    module, _, source, _ = plugins
    manager = PluginManager()
    await manager.load(module.old)
    session = PluginReplacementSession(manager)
    preview = session.inspect(source)
    await session.prepare(import_confirmation=preview["import_confirmation"])
    plan = session.plan
    session.cancel()
    with pytest.raises(PluginReplacementError):
        await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True)


@pytest.mark.asyncio
async def test_cli_session_performs_real_replacement_then_unloads(plugins, monkeypatch):
    from w_agent.plugin_session_cli import run_plugin_session
    module, initial, source, lifecycle = plugins
    output = []
    commands = iter([f"inspect {source}", "prepare", "replace", "status", "exit"])
    monkeypatch.setattr(typer, "echo", lambda value: output.append(str(value)))
    def prompt(label):
        if label == "plugin-session":
            return next(commands)
        payload = next(json.loads(item) for item in reversed(output) if item.startswith("{"))
        key = {"Exact IMPORT REPLACEMENT confirmation": "import_confirmation", "Exact REPLACE confirmation": "replace_confirmation", "Exact QUIESCENT confirmation": "quiescent_confirmation"}[label]
        return payload[key]
    monkeypatch.setattr(typer, "prompt", prompt)
    await run_plugin_session(initial)
    assert lifecycle == ["old", "SECRET_TOKEN"]
    assert any('"version": "2"' in item and '"state": "active"' in item for item in output)
    assert "SECRET_TOKEN" not in "\n".join(output)
    assert any("Exit unloads" in item for item in output)


def test_cli_session_requires_initial_code_authorization():
    from w_agent.cli import app
    result = CliRunner().invoke(app, ["plugin", "session"])
    assert result.exit_code != 0
    assert "--confirm-plugin-code" in result.output


@pytest.mark.asyncio
async def test_tui_live_manager_replacement(plugins, tmp_path):
    from w_agent.tui import WAgentTui
    module, _, source, lifecycle = plugins
    app = WAgentTui(tmp_path)
    async with app.run_test(size=(140, 60)):
        old = await app.plugin_manager.load(module.old)
        app.query_one("#plugin-replace-config").value = str(source)
        app._inspect_plugin_replacement()
        preview = json.loads(str(app.query_one("#plugin-replace-result").content))
        app.query_one("#plugin-replace-import-confirm").value = preview["import_confirmation"]
        await app._prepare_plugin_replacement()
        plan = json.loads(str(app.query_one("#plugin-replace-result").content))
        app.query_one("#plugin-replace-confirm").value = plan["replace_confirmation"]
        app.query_one("#plugin-replace-quiescent").value = plan["quiescent_confirmation"]
        await app._execute_plugin_replacement()
        assert old.state == PluginState.DISPOSED
        assert app.plugin_manager.record("demo").state == PluginState.ACTIVE
        assert lifecycle == ["old", "SECRET_TOKEN"]
        assert app.query_one("#plugin-replace-confirm").value == ""
        assert "SECRET_TOKEN" not in str(app.query_one("#plugin-replace-result").content)


@pytest.mark.asyncio
async def test_tui_busy_evaluation_rejects_replacement(plugins, tmp_path):
    from w_agent.tui import WAgentTui
    module, _, source, _ = plugins
    app = WAgentTui(tmp_path)
    async with app.run_test(size=(140, 60)):
        old = await app.plugin_manager.load(module.old)
        app.query_one("#plugin-replace-config").value = str(source)
        app._inspect_plugin_replacement()
        preview = json.loads(str(app.query_one("#plugin-replace-result").content))
        app.query_one("#plugin-replace-import-confirm").value = preview["import_confirmation"]
        await app._prepare_plugin_replacement()
        plan = app._plugin_replacement.plan
        app.query_one("#plugin-replace-confirm").value = f"REPLACE {plan.plan_id}"
        app.query_one("#plugin-replace-quiescent").value = f"QUIESCENT {plan.plan_id}"
        app._evaluation_busy = True
        await app._execute_plugin_replacement()
        app._evaluation_busy = False
        assert old.state == PluginState.ACTIVE
        assert app._plugin_replacement.plan is None
        assert "failed" in str(app.query_one("#plugin-replace-result").content)


@pytest.mark.asyncio
async def test_tui_changed_path_discards_review_before_import(plugins, tmp_path):
    from w_agent.tui import WAgentTui
    module, _, source, lifecycle = plugins
    app = WAgentTui(tmp_path)
    async with app.run_test(size=(140, 60)):
        old = await app.plugin_manager.load(module.old)
        app.query_one("#plugin-replace-config").value = str(source)
        app._inspect_plugin_replacement()
        preview = json.loads(str(app.query_one("#plugin-replace-result").content))
        app.query_one("#plugin-replace-import-confirm").value = preview["import_confirmation"]
        app.query_one("#plugin-replace-config").value = str(tmp_path / "other.yml")
        await app._prepare_plugin_replacement()
        assert old.state == PluginState.ACTIVE
        assert lifecycle == ["old"]
        assert app._plugin_replacement.plan is None
