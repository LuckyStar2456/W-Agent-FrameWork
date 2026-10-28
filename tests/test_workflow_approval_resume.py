"""Regressions for explicit approval assembly."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli_module
import w_agent.workflows.approval_resume as resume_module
from w_agent import (
    AgentDefinition, AgentWorkflowApproval, DagWorkflowDefinition, JsonlRunStore,
    JsonlWorkflowStore, RunCheckpoint, ScopePath, ToolCall, WorkflowCheckpoint,
    WorkflowCheckpointStatus, WorkflowKind, WorkflowNode, WorkflowNodeContext,
    WorkflowApprovalResumeError, WorkflowPauseController, WorkflowStopReason,
    WorkflowStoreError,
    open_workflow_approval_entry, resume_workflow_approval,
)


async def _fixtures(root):
    scope = ScopePath.application()
    reference = AgentWorkflowApproval("parent", "answer", "child", "coding", "call", "write")
    parent = WorkflowCheckpoint(
        "parent", "workflow", "1", WorkflowKind.DAG, scope,
        "PRIVATE_INPUT", {"_w_agent_approval:answer": reference.to_dict()}, {}, (),
        remaining_nodes=("answer",), status=WorkflowCheckpointStatus.PAUSED,
    )
    child = RunCheckpoint(
        "child", AgentDefinition("coding"), scope, (),
        ToolCall("call", "write", {"value": "PRIVATE_ARGUMENT"}), (), 1, 0, "",
    )
    parents, agents = JsonlWorkflowStore(root), JsonlRunStore(root / "agents")
    await parents.save_checkpoint(parent)
    await agents.save_checkpoint(child)
    return parents, agents, parent, child, reference


def _node_context(context):
    return WorkflowNodeContext("parent", "answer", None, {}, {}, context.scope, None)


def _factory(seen, calls, *, fail=None):
    @asynccontextmanager
    async def factory(context):
        seen.append(context)
        async def handler(node_context):
            authority = context.grants(node_context, context.reference)
            calls.append(authority)
            return "PRIVATE_OUTPUT"
        try:
            if fail == "enter":
                context.grants.grant(context.reference, scope=context.scope)
                raise ValueError("PRIVATE_ENTER")
            if fail == "cancel":
                context.grants.grant(context.reference, scope=context.scope)
                raise asyncio.CancelledError()
            yield DagWorkflowDefinition("workflow", (WorkflowNode("answer", handler),))
        finally:
            if fail == "exit":
                context.grants.grant(context.reference, scope=context.scope)
                raise ValueError("PRIVATE_EXIT")
    return factory


async def test_service_passes_exact_stores_and_scoped_authority_then_clears(tmp_path):
    parents, agents, parent, child, reference = await _fixtures(tmp_path)
    seen, calls = [], []
    result = await resume_workflow_approval(
        parents, agents, reference, _factory(seen, calls), permissions={"write.allowed"},
    )
    assert result.stop_reason is WorkflowStopReason.COMPLETED
    assert seen[0].workflow_store is parents and seen[0].agent_store is agents
    assert seen[0].workflow_name == "workflow" and seen[0].workflow_version == "1"
    assert calls[0].approved_call_ids == frozenset({"call"})
    assert calls[0].permissions == frozenset({"write.allowed"})
    assert not seen[0].grants(_node_context(seen[0]), reference).approved_call_ids


@pytest.mark.parametrize("field", ["workflow_run_id", "workflow_node", "agent_run_id", "agent_name", "call_id", "tool_name"])
async def test_wrong_identity_fails_before_factory(tmp_path, field):
    parents, agents, parent, child, reference = await _fixtures(tmp_path)
    seen, calls = [], []
    with pytest.raises((WorkflowApprovalResumeError, WorkflowStoreError)):
        await resume_workflow_approval(
            parents, agents, replace(reference, **{field: "different"}), _factory(seen, calls),
        )
    assert seen == calls == []
    assert await parents.load_checkpoint("parent") == parent
    assert await agents.load_checkpoint("child") == child


@pytest.mark.parametrize("damage", ["parent", "arguments", "definition", "workflow-version"])
async def test_rechecks_full_snapshots_after_assembly_before_execution(tmp_path, damage):
    parents, agents, parent, child, reference = await _fixtures(tmp_path)
    seen, calls, closed = [], [], []
    @asynccontextmanager
    async def factory(context):
        seen.append(context)
        if damage == "parent":
            await parents.save_checkpoint(replace(parent, input="CHANGED"))
        elif damage == "arguments":
            await agents.save_checkpoint(replace(child, pending_tool_call=replace(
                child.pending_tool_call, arguments={"value": "CHANGED"},
            )))
        elif damage == "definition":
            await agents.save_checkpoint(replace(child, definition=AgentDefinition("coding", system_prompt="CHANGED")))
        try:
            yield DagWorkflowDefinition(
                "workflow", (WorkflowNode("answer", lambda _: calls.append("ran")),),
                version="other" if damage == "workflow-version" else "1",
            )
        finally:
            closed.append(True)
    with pytest.raises(WorkflowApprovalResumeError):
        await resume_workflow_approval(parents, agents, reference, factory)
    assert not calls and closed == [True]
    assert not seen[0].grants(_node_context(seen[0]), reference).approved_call_ids
    assert await parents.events("parent") == ()


@pytest.mark.parametrize("fail", ["enter", "exit", "cancel"])
async def test_grants_cleared_on_factory_failure_or_cancellation(tmp_path, fail):
    parents, agents, parent, child, reference = await _fixtures(tmp_path)
    seen, calls = [], []
    with pytest.raises(asyncio.CancelledError if fail == "cancel" else ValueError):
        await resume_workflow_approval(parents, agents, reference, _factory(seen, calls, fail=fail))
    assert not seen[0].grants(_node_context(seen[0]), reference).approved_call_ids
    if fail != "exit":
        assert await parents.load_checkpoint("parent") == parent
        assert not calls


async def test_external_pause_does_not_spend_grant_or_clear_request(tmp_path):
    parents, agents, parent, child, reference = await _fixtures(tmp_path)
    pause = WorkflowPauseController()
    pause.request_pause("parent")
    seen, calls = [], []
    result = await resume_workflow_approval(
        parents, agents, reference, _factory(seen, calls), pause_source=pause,
    )
    assert result.stop_reason is WorkflowStopReason.PAUSED and not calls
    assert pause.is_pause_requested("parent")
    assert not seen[0].grants(_node_context(seen[0]), reference).approved_call_ids
    assert await agents.load_checkpoint("child") == child


async def test_entry_import_is_deferred_until_context_entry(monkeypatch):
    imports, closed = [], []
    @asynccontextmanager
    async def factory(context):
        assert context == "context"
        try:
            yield "definition"
        finally:
            closed.append(True)
    def import_module(name):
        imports.append(name)
        return SimpleNamespace(factory=factory)
    monkeypatch.setattr(resume_module.importlib, "import_module", import_module)
    manager = open_workflow_approval_entry("demo:factory", "context")
    assert not imports
    async with manager as definition:
        assert definition == "definition" and imports == ["demo"]
    assert closed == [True]


def _command(root):
    return [
        "checkpoint", "workflow-approve-resume", "parent", "--workflow-factory", "demo:factory",
        "--node", "answer", "--agent-run", "child", "--agent-name", "coding",
        "--approve-tool-call", "call", "--tool-name", "write", "--state-root", str(root),
        "--agent-state-root", str(root / "agents"), "--json",
    ]


CONFIRMATIONS = ["--confirm-workflow-code", "--confirm-approval", "--confirm-resume"]


@pytest.mark.parametrize("missing", CONFIRMATIONS)
def test_cli_requires_three_independent_confirmations(tmp_path, monkeypatch, missing):
    def forbidden(*_args):
        pytest.fail("must not import a factory without all confirmations")
    monkeypatch.setattr(cli_module, "open_workflow_approval_entry", forbidden)
    root = tmp_path / "absent"
    result = CliRunner().invoke(cli_module.app, [
        *_command(root), *(flag for flag in CONFIRMATIONS if flag != missing),
    ])
    assert result.exit_code == 2 and not root.exists()


def test_cli_stale_call_does_not_import_and_success_hides_content(tmp_path, monkeypatch):
    asyncio.run(_fixtures(tmp_path))
    seen, calls = [], []
    factory = _factory(seen, calls)
    monkeypatch.setattr(cli_module, "open_workflow_approval_entry", lambda _entry, context: factory(context))
    command = [*_command(tmp_path), *CONFIRMATIONS, "--grant-permission", "write.allowed"]
    stale = list(command)
    stale[stale.index("--approve-tool-call") + 1] = "wrong-call"
    denied = CliRunner().invoke(cli_module.app, stale)
    assert denied.exit_code == 2 and not seen
    success = CliRunner().invoke(cli_module.app, command)
    assert success.exit_code == 0
    assert json.loads(success.stdout)["stop_reason"] == "completed"
    assert "PRIVATE" not in success.stdout
    assert calls[0].permissions == frozenset({"write.allowed"})


def test_cli_sanitizes_factory_errors(tmp_path, monkeypatch):
    asyncio.run(_fixtures(tmp_path))
    factory = _factory([], [], fail="enter")
    monkeypatch.setattr(cli_module, "open_workflow_approval_entry", lambda _entry, context: factory(context))
    result = CliRunner().invoke(cli_module.app, [*_command(tmp_path), *CONFIRMATIONS])
    assert result.exit_code == 2
    assert "PRIVATE" not in result.output
    assert "ValueError" in result.output
