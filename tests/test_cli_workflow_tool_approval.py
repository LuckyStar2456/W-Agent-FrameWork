"""CLI regressions for explicit two-layer approval."""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli_module
from w_agent import (
    AgentDefinition, AgentWorkflowApproval, JsonlRunStore, JsonlWorkflowStore,
    RunCheckpoint, RunResult, ScopePath, StopReason, TokenUsage, ToolCall,
    ToolContinuation, WorkflowCheckpoint, WorkflowCheckpointStatus, WorkflowEvent,
    WorkflowEventType, WorkflowKind, WorkflowNodeContext, WorkflowToolReference,
)


async def _seed(root, *, custom_key=False):
    scope = ScopePath.application("PRIVATE_SCOPE")
    outer = WorkflowToolReference("outer", "outer-call", "workflow", "wf-run", "flow", "1", WorkflowKind.DAG, scope)
    inner = AgentWorkflowApproval("wf-run", "node", "inner", "coder", "inner-call", "write")
    parents = JsonlRunStore(root / "parent")
    workflows = JsonlWorkflowStore(root / "workflow")
    children = JsonlRunStore(root / "child")
    await parents.save_checkpoint(RunCheckpoint(
        "outer", AgentDefinition("parent"), scope, (), ToolCall("outer-call", "workflow", {}, scope),
        (), 1, 1, "PRIVATE_OUTPUT", schema_version=2,
        tool_continuation=ToolContinuation("w-agent.workflow-tool", {"reference": outer.to_dict(), "sequence": 1}),
    ))
    await workflows.save_checkpoint(WorkflowCheckpoint(
        "wf-run", "flow", "1", WorkflowKind.DAG, scope, "PRIVATE_INPUT",
        {"custom" if custom_key else "_w_agent_approval:node": inner.to_dict()}, {}, (),
        remaining_nodes=("node",), status=WorkflowCheckpointStatus.PAUSED,
        metadata={"_w_agent_workflow_tool": outer.to_dict()},
    ))
    await workflows.append(WorkflowEvent(1, WorkflowEventType.WORKFLOW_PAUSED, "wf-run"))
    await children.save_checkpoint(RunCheckpoint(
        "inner", AgentDefinition("coder"), scope, (),
        ToolCall("inner-call", "write", {"value": "PRIVATE_ARGUMENT"}, scope), (), 1, 1, "",
    ))


def _roots(root):
    return ["--state-root", str(root / "parent"), "--workflow-state-root", str(root / "workflow"),
            "--child-state-root", str(root / "child"), "--json"]


def _command(root):
    return [
        "checkpoint", "workflow-tool-approve-resume", "outer", "--agent-factory", "app:factory",
        "--parent-call", "outer-call", "--parent-tool", "workflow", "--workflow-run", "wf-run",
        "--workflow-name", "flow", "--workflow-version", "1", "--workflow-kind", "dag",
        "--sequence", "1", "--node", "node", "--child-run", "inner", "--child-agent", "coder",
        "--child-call", "inner-call", "--child-tool", "write", *_roots(root),
    ]


CONFIRMATIONS = ["--confirm-agent-code", "--confirm-parent-approval", "--confirm-child-approval", "--confirm-resume"]


def _factory(seen, calls, *, fail=False):
    @asynccontextmanager
    async def factory(context):
        seen.append(context)
        if fail:
            raise ValueError("PRIVATE_FACTORY_ERROR")
        class Loop:
            store = context.parent_store
            async def resume(self, run_id, *, tool_context, cancellation):
                reference = context.selection.child.reference
                node_context = WorkflowNodeContext(reference.workflow_run_id, reference.workflow_node, None, {}, {},
                                                   context.selection.parent.scope, cancellation)
                calls.append((tool_context, context.grants(node_context, reference)))
                return RunResult(run_id, StopReason.NEEDS_APPROVAL, "PRIVATE_OUTPUT", (), (), 2, 1,
                                 pending_tool_call=ToolCall("next", "next-tool", {"private": "PRIVATE_ARGUMENT"}),
                                 checkpoint_id=run_id, usage=TokenUsage(7, 3))
        yield Loop()
    return factory


@pytest.mark.parametrize("missing", CONFIRMATIONS)
def test_all_four_confirmations_precede_any_factory_or_directory_creation(tmp_path, monkeypatch, missing):
    def forbidden(*args):
        pytest.fail("factory may not load before all four confirmations")
    monkeypatch.setattr(cli_module, "open_workflow_tool_approval_entry", forbidden)
    root = tmp_path / "missing"
    result = CliRunner().invoke(cli_module.app, [*_command(root), *(flag for flag in CONFIRMATIONS if flag != missing)])
    assert result.exit_code == 2 and missing in result.output and not root.exists()


@pytest.mark.parametrize("review", [False, True])
def test_missing_roots_are_not_initialized(tmp_path, review):
    root = tmp_path / "missing"
    command = (["checkpoint", "workflow-tool-approvals", "outer", *_roots(root)] if review
               else [*_command(root), *CONFIRMATIONS])
    result = CliRunner().invoke(cli_module.app, command)
    assert result.exit_code == 2 and not root.exists()


def test_review_is_read_only_and_supports_explicit_custom_keys(tmp_path, monkeypatch):
    asyncio.run(_seed(tmp_path, custom_key=True))
    def forbidden(*args):
        pytest.fail("review must not load a factory")
    monkeypatch.setattr(cli_module, "open_workflow_tool_approval_entry", forbidden)
    command = ["checkpoint", "workflow-tool-approvals", "outer", *_roots(tmp_path)]
    empty = CliRunner().invoke(cli_module.app, command)
    assert empty.exit_code == 0 and json.loads(empty.stdout) == []
    result = CliRunner().invoke(cli_module.app, [*command, "--state-key", "custom"])
    assert result.exit_code == 0 and "PRIVATE" not in result.stdout
    row, = json.loads(result.stdout)
    assert row["authorized"] is False and row["sequence"] == 1
    assert row["parent"]["agent_run_id"] == "outer" and row["child"]["reference"]["call_id"] == "inner-call"


@pytest.mark.parametrize("option,value", [
    ("--parent-call", "other"), ("--parent-tool", "other"), ("--workflow-run", "other"),
    ("--workflow-name", "other"), ("--workflow-version", "2"), ("--workflow-kind", "python"),
    ("--sequence", "2"), ("--node", "other"), ("--child-run", "other"),
    ("--child-agent", "other"), ("--child-call", "other"), ("--child-tool", "other"),
])
def test_every_selected_identity_and_boundary_must_match_before_import(tmp_path, monkeypatch, option, value):
    asyncio.run(_seed(tmp_path))
    seen, calls = [], []
    factory = _factory(seen, calls)
    monkeypatch.setattr(cli_module, "open_workflow_tool_approval_entry", lambda entry, ctx: factory(ctx))
    command = [*_command(tmp_path), *CONFIRMATIONS]
    command[command.index(option) + 1] = value
    result = CliRunner().invoke(cli_module.app, command)
    assert result.exit_code == 2 and not seen and not calls


def test_success_separates_permissions_and_hides_output_and_arguments(tmp_path, monkeypatch):
    asyncio.run(_seed(tmp_path))
    seen, calls = [], []
    factory = _factory(seen, calls)
    monkeypatch.setattr(cli_module, "open_workflow_tool_approval_entry", lambda entry, ctx: factory(ctx))
    result = CliRunner().invoke(cli_module.app, [*_command(tmp_path), *CONFIRMATIONS,
        "--parent-permission", "workflow.execute", "--child-permission", "write.allowed"])
    assert result.exit_code == 0 and "PRIVATE" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["stop_reason"] == "needs-approval" and payload["pending_call_id"] == "next"
    assert payload["usage"]["input_tokens"] == 7 and payload["usage"]["output_tokens"] == 3
    assert payload["selected_child_execution_confirmed"] is False
    outer, inner = calls[0]
    assert outer.permissions == {"workflow.execute"} and outer.approved_call_ids == {"outer-call"}
    assert inner.permissions == {"write.allowed"} and inner.approved_call_ids == {"inner-call"}


def test_factory_error_message_is_sanitized(tmp_path, monkeypatch):
    asyncio.run(_seed(tmp_path))
    factory = _factory([], [], fail=True)
    monkeypatch.setattr(cli_module, "open_workflow_tool_approval_entry", lambda entry, ctx: factory(ctx))
    result = CliRunner().invoke(cli_module.app, [*_command(tmp_path), *CONFIRMATIONS])
    assert result.exit_code == 2 and "ValueError" in result.output and "PRIVATE" not in result.output
