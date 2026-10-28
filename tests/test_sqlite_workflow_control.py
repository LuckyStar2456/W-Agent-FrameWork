"""Cross-process request and CLI regression cases; no remote services needed."""

import asyncio
import json
import sqlite3
import subprocess
import sys

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli_module
from w_agent import (
    DagWorkflowDefinition,
    JsonlWorkflowStore,
    LocalWorkflowEngine,
    SQLiteWorkflowPauseController,
    WorkflowCheckpointStatus,
    WorkflowContext,
    WorkflowNode,
    WorkflowNodeResult,
    WorkflowPauseControlError,
    WorkflowStopReason,
)


def test_lazy_reads_exact_keys_and_explicit_clear(tmp_path):
    root = tmp_path / "new-state"
    control = SQLiteWorkflowPauseController(root)
    assert not control.is_pause_requested("run")
    control.clear("run")
    assert not root.exists()
    control.request_pause("run")
    control.request_pause("run")
    other = SQLiteWorkflowPauseController(root)
    assert other.is_pause_requested("run")
    assert not other.is_pause_requested("Run")
    assert not other.is_pause_requested("run-2")
    assert not SQLiteWorkflowPauseController(tmp_path / "other").is_pause_requested("run")
    # Run IDs are SQL parameters, never paths or interpolated statements.
    unusual = "../run'; DROP TABLE workflow_pause_requests_v1; --"
    control.request_pause(unusual)
    assert other.is_pause_requested(unusual)
    other.clear("run")
    assert not control.is_pause_requested("run")
    assert control.is_pause_requested(unusual)
    control.request_pause("run")
    assert other.is_pause_requested("run")


@pytest.mark.parametrize("method", ["request_pause", "clear", "is_pause_requested"])
@pytest.mark.parametrize("run_id", ["", " ", None, 12])
def test_invalid_ids_do_not_create_control_store(tmp_path, method, run_id):
    control = SQLiteWorkflowPauseController(tmp_path / "absent")
    with pytest.raises(ValueError):
        getattr(control, method)(run_id)
    assert not control.database_path.exists()


@pytest.mark.parametrize("method", ["request_pause", "clear", "is_pause_requested"])
def test_corrupt_store_fails_closed_without_private_error(tmp_path, method):
    control = SQLiteWorkflowPauseController(tmp_path)
    control.database_path.write_bytes(b"SECRET_INVALID_DATABASE")
    with pytest.raises(WorkflowPauseControlError) as caught:
        getattr(control, method)("run")
    assert "SECRET" not in str(caught.value)


def test_locked_store_does_not_silently_ignore_request(tmp_path):
    control = SQLiteWorkflowPauseController(tmp_path)
    control.request_pause("run")
    connection = sqlite3.connect(control.database_path)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        with pytest.raises(WorkflowPauseControlError):
            control.is_pause_requested("run")
    finally:
        connection.rollback()
        connection.close()
    assert control.is_pause_requested("run")


async def test_subprocess_request_pauses_after_committed_node_and_resumes(tmp_path):
    calls = []
    control = SQLiteWorkflowPauseController(tmp_path)

    async def first(context):
        calls.append("first")
        await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-c",
                "import sys; from w_agent import SQLiteWorkflowPauseController; "
                "SQLiteWorkflowPauseController(sys.argv[1]).request_pause(sys.argv[2])",
                str(tmp_path),
                context.run_id,
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
        return "first"

    def last(context):
        calls.append("last")
        return "last"

    definition = DagWorkflowDefinition(
        "external-control",
        (WorkflowNode("first", first), WorkflowNode("last", last)),
        {"last": ("first",)},
    )
    store = JsonlWorkflowStore(tmp_path)
    engine = LocalWorkflowEngine(store, pause_source=control)
    paused = await engine.start(definition, WorkflowContext("run"))
    assert paused.stop_reason is WorkflowStopReason.PAUSED
    assert paused.completed_nodes == ("first",)
    assert (await store.load_checkpoint("run")).status is WorkflowCheckpointStatus.PAUSED
    assert (await engine.resume(definition, "run")).stop_reason is WorkflowStopReason.PAUSED
    assert calls == ["first"]
    SQLiteWorkflowPauseController(tmp_path).clear("run")
    assert calls == ["first"]
    resumed = await LocalWorkflowEngine(
        JsonlWorkflowStore(tmp_path),
        pause_source=SQLiteWorkflowPauseController(tmp_path),
    ).resume(definition, "run")
    assert resumed.stop_reason is WorkflowStopReason.COMPLETED
    assert calls == ["first", "last"]


async def test_unreadable_control_prevents_node_execution(tmp_path):
    control = SQLiteWorkflowPauseController(tmp_path)
    control.database_path.write_bytes(b"invalid")
    calls = []
    definition = DagWorkflowDefinition(
        "unreadable", (WorkflowNode("first", lambda _: calls.append("first")),)
    )
    store = JsonlWorkflowStore(tmp_path)
    with pytest.raises(WorkflowPauseControlError):
        await LocalWorkflowEngine(store, pause_source=control).start(
            definition, WorkflowContext("run")
        )
    assert calls == []
    assert (await store.load_checkpoint("run")).status is WorkflowCheckpointStatus.READY


def _paused_definition(tmp_path, calls):
    def first(context):
        calls.append("first")
        return WorkflowNodeResult(output="SECRET_OUTPUT", pause=True)

    def last(context):
        calls.append("last")
        return "SECRET_LAST"

    definition = DagWorkflowDefinition(
        "cli-control",
        (WorkflowNode("first", first), WorkflowNode("last", last)),
        {"last": ("first",)},
    )
    asyncio.run(LocalWorkflowEngine(JsonlWorkflowStore(tmp_path)).start(
        definition, WorkflowContext("run", input="SECRET_INPUT")
    ))
    return definition


def test_cli_requires_authority_and_never_claims_pause_ack(tmp_path):
    runner = CliRunner()
    control = SQLiteWorkflowPauseController(tmp_path)
    common = ["run", "--state-root", str(tmp_path), "--json"]
    denied = runner.invoke(cli_module.app, ["checkpoint", "workflow-pause", *common])
    assert denied.exit_code == 2
    assert not control.database_path.exists()
    absent = runner.invoke(cli_module.app, [
        "checkpoint", "workflow-pause", *common, "--confirm-pause"
    ])
    assert absent.exit_code == 2
    assert not control.database_path.exists()
    calls = []
    _paused_definition(tmp_path, calls)
    requested = runner.invoke(cli_module.app, [
        "checkpoint", "workflow-pause", *common, "--confirm-pause"
    ])
    assert requested.exit_code == 0
    assert json.loads(requested.stdout) == {
        "run_id": "run", "request_recorded": True, "execution_acknowledged": False,
    }
    status = runner.invoke(cli_module.app, [
        "checkpoint", "workflow-pause-status", *common
    ])
    assert status.exit_code == 0
    assert json.loads(status.stdout) == {
        "run_id": "run", "pause_requested": True, "checkpoint_status": "paused",
    }
    assert "SECRET" not in requested.stdout + status.stdout
    denied_clear = runner.invoke(cli_module.app, [
        "checkpoint", "workflow-pause-clear", *common
    ])
    assert denied_clear.exit_code == 2
    assert control.is_pause_requested("run")
    cleared = runner.invoke(cli_module.app, [
        "checkpoint", "workflow-pause-clear", *common, "--confirm-clear"
    ])
    assert cleared.exit_code == 0
    assert json.loads(cleared.stdout)["resumed"] is False
    assert not control.is_pause_requested("run")
    assert calls == ["first"]


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_resume_observes_requests_only_when_opted_in(tmp_path, monkeypatch, enabled):
    calls = []
    definition = _paused_definition(tmp_path, calls)
    monkeypatch.setattr(cli_module, "load_workflow_entries", lambda _: {
        (definition.name, definition.version): definition,
    })
    control = SQLiteWorkflowPauseController(tmp_path)
    control.request_pause("run")
    command = [
        "checkpoint", "workflow-resume", "run", "--state-root", str(tmp_path),
        "--workflow-entry", "example:workflow", "--confirm-workflow-code",
        "--confirm-resume", "--json",
    ]
    if enabled:
        command.append("--enable-pause-control")
    result = CliRunner().invoke(cli_module.app, command)
    assert result.exit_code == 0
    assert json.loads(result.stdout)["stop_reason"] == (
        "paused" if enabled else "completed"
    )
    assert calls == (["first"] if enabled else ["first", "last"])
    assert control.is_pause_requested("run")
    assert "SECRET" not in result.stdout
