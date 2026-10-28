"""Draft read-only review and one-shot host-authority regression coverage."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from typer.testing import CliRunner

import w_agent.workflows.approval_review as review_module
from w_agent import (
    AgentDefinition, AgentWorkflowAdapterError, AgentWorkflowApproval,
    CheckpointStatus, JsonlRunStore, JsonlWorkflowStore, MessageRole, ModelMessage,
    RunCheckpoint, ScopePath, ToolCall, WorkflowApprovalGrants,
    WorkflowApprovalLinkStatus, WorkflowCheckpoint, WorkflowCheckpointStatus,
    WorkflowKind, WorkflowNodeContext, review_workflow_approvals,
)
from w_agent.cli import app


async def _fixtures(root, *, custom_key=False, separate_agents=False):
    scope = ScopePath.application()
    reference = AgentWorkflowApproval("parent", "answer", "child", "coding", "call", "write")
    key = "custom-key" if custom_key else "_w_agent_approval:answer"
    parent = WorkflowCheckpoint(
        "parent", "workflow", "1", WorkflowKind.DAG, scope,
        "PRIVATE_INPUT", {key: reference.to_dict(), "other": "PRIVATE_STATE"},
        {"before": "PRIVATE_OUTPUT"}, ("before",), remaining_nodes=("answer",),
        status=WorkflowCheckpointStatus.PAUSED,
    )
    child = RunCheckpoint(
        "child", AgentDefinition("coding", system_prompt="PRIVATE_SYSTEM"), scope,
        (ModelMessage.text(MessageRole.USER, "PRIVATE_MESSAGE"),),
        ToolCall("call", "write", {"secret": "PRIVATE_ARGUMENT"}), (), 1, 0,
        "PRIVATE_LATEST",
    )
    parents = JsonlWorkflowStore(root)
    agents = JsonlRunStore(root / "separate" if separate_agents else root)
    await parents.save_checkpoint(parent)
    await agents.save_checkpoint(child)
    return parents, agents, parent, child, reference, key


async def test_review_is_prompt_free_and_does_not_modify_checkpoints(tmp_path):
    parents, agents, parent, child, reference, _key = await _fixtures(tmp_path)
    reviews = await review_workflow_approvals(parents, agents, "parent")
    assert len(reviews) == 1
    assert reviews[0].reference == reference
    assert reviews[0].link_status is WorkflowApprovalLinkStatus.MATCHED
    data = reviews[0].to_dict()
    assert data["authorized"] is False
    assert "PRIVATE" not in json.dumps(data)
    assert "secret" not in json.dumps(data)
    assert await parents.load_checkpoint("parent") == parent
    assert await agents.load_checkpoint("child") == child
    assert await parents.events("parent") == ()
    assert await agents.events("child") == ()


@pytest.mark.parametrize("damage,expected", [
    ("uncertain", "parent-uncertain"), ("ready", "parent-not-paused"),
    ("owner", "reference-mismatch"), ("inactive", "reference-mismatch"),
    ("missing", "child-missing"), ("claimed", "child-not-pending"),
    ("call", "child-mismatch"), ("scope", "child-mismatch"),
    ("agent", "child-mismatch"),
])
async def test_review_classifies_broken_links_without_claiming(tmp_path, damage, expected):
    parents, agents, parent, child, reference, key = await _fixtures(tmp_path)
    if damage == "uncertain":
        parent = replace(parent, status=WorkflowCheckpointStatus.RESUMING)
    elif damage == "ready":
        parent = replace(parent, status=WorkflowCheckpointStatus.READY)
    elif damage == "owner":
        parent = replace(parent, state={key: replace(reference, workflow_run_id="other").to_dict()})
    elif damage == "inactive":
        parent = replace(parent, remaining_nodes=("other",))
    elif damage == "missing":
        await agents.delete_checkpoint("child")
    elif damage == "claimed":
        child = replace(child, status=CheckpointStatus.RESUMING)
    elif damage == "call":
        child = replace(child, pending_tool_call=replace(child.pending_tool_call, id="new-call"))
    elif damage == "scope":
        child = replace(child, scope=ScopePath.application("other"))
    else:
        child = replace(child, definition=AgentDefinition("other"))
    await parents.save_checkpoint(parent)
    if damage != "missing":
        await agents.save_checkpoint(child)
    reviews = await review_workflow_approvals(parents, agents, "parent")
    assert reviews[0].link_status.value == expected
    assert reviews[0].to_dict()["authorized"] is False
    assert await parents.load_checkpoint("parent") == parent


async def test_review_custom_keys_and_malformed_or_duplicate_references(tmp_path):
    parents, agents, parent, child, reference, key = await _fixtures(tmp_path, custom_key=True)
    assert await review_workflow_approvals(parents, agents, "parent") == ()
    assert len(await review_workflow_approvals(parents, agents, "parent", state_keys=(key,))) == 1
    with pytest.raises(AgentWorkflowAdapterError):
        await review_workflow_approvals(parents, agents, "parent", state_keys=("missing",))
    with pytest.raises(ValueError):
        await review_workflow_approvals(parents, agents, "parent", state_keys="custom-key")
    parent = replace(parent, state={key: reference.to_dict(), "duplicate": reference.to_dict()})
    await parents.save_checkpoint(parent)
    with pytest.raises(AgentWorkflowAdapterError, match="duplicate"):
        await review_workflow_approvals(parents, agents, "parent", state_keys=(key, "duplicate"))
    await parents.save_checkpoint(replace(parent, state={key: {"secret": "PRIVATE_BAD"}}))
    with pytest.raises(AgentWorkflowAdapterError) as caught:
        await review_workflow_approvals(parents, agents, "parent", state_keys=(key,))
    assert "PRIVATE_BAD" not in str(caught.value)


def _context(scope=None):
    return WorkflowNodeContext(
        "parent", "answer", None, {}, {}, scope or ScopePath.application(), None
    )


def _reference():
    return AgentWorkflowApproval("parent", "answer", "child", "coding", "call", "write")


def test_grants_bind_all_reference_fields_and_scope_and_are_one_shot():
    grants = WorkflowApprovalGrants()
    reference = _reference()
    context = _context()
    assert not grants(context, reference).approved_call_ids
    grants.grant(reference, scope=context.scope, permissions={"write.allowed"})
    for field in ("workflow_run_id", "workflow_node", "agent_run_id", "agent_name", "call_id", "tool_name"):
        assert not grants(context, replace(reference, **{field: "other"})).approved_call_ids
    assert not grants(replace(context, run_id="other"), reference).approved_call_ids
    assert not grants(_context(ScopePath.application("other")), reference).approved_call_ids
    authority = grants(context, reference)
    assert authority.approved_call_ids == frozenset({"call"})
    assert authority.permissions == frozenset({"write.allowed"})
    assert not grants(context, reference).approved_call_ids


def test_grants_expire_revoke_clear_and_allow_only_one_concurrent_consumer(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(review_module, "monotonic", lambda: now[0])
    grants, reference, context = WorkflowApprovalGrants(), _reference(), _context()
    grants.grant(reference, scope=context.scope, ttl_seconds=1)
    now[0] = 101.0
    assert not grants(context, reference).approved_call_ids
    grants.grant(reference, scope=context.scope)
    grants.revoke(reference)
    assert not grants(context, reference).approved_call_ids
    grants.grant(reference, scope=context.scope)
    grants.clear()
    assert not grants(context, reference).approved_call_ids
    grants.grant(reference, scope=context.scope)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: grants(context, reference), range(8)))
    assert sum(bool(item.approved_call_ids) for item in results) == 1


@pytest.mark.parametrize("ttl", [True, 0, -1, float("inf"), float("nan"), "30"])
def test_grants_reject_invalid_lifetime(ttl):
    with pytest.raises(ValueError):
        WorkflowApprovalGrants().grant(_reference(), scope=_context().scope, ttl_seconds=ttl)


def test_cli_reviews_selected_roots_without_loading_definitions(tmp_path):
    asyncio.run(_fixtures(tmp_path, separate_agents=True))
    result = CliRunner().invoke(app, [
        "checkpoint", "workflow-approvals", "parent", "--state-root", str(tmp_path),
        "--agent-state-root", str(tmp_path / "separate"), "--json",
    ])
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["link_status"] == "matched"
    assert json.loads(result.stdout)[0]["authorized"] is False
    assert "PRIVATE" not in result.stdout


def test_cli_review_does_not_create_absent_workspace(tmp_path):
    root = tmp_path / "absent"
    result = CliRunner().invoke(app, [
        "checkpoint", "workflow-approvals", "parent", "--state-root", str(root), "--json",
    ])
    assert result.exit_code == 2
    assert not root.exists()


async def test_tui_read_only_review_uses_public_service_without_consuming_authority(tmp_path, monkeypatch):
    pytest.importorskip("textual")
    import w_agent.tui as tui_module

    async def unavailable():
        return False

    def forbidden_load(_entries):
        pytest.fail("read-only review must not load workflow definitions")

    monkeypatch.setattr(tui_module.DockerSandboxProvider, "available", staticmethod(unavailable))
    monkeypatch.setattr(tui_module, "load_workflow_entries", forbidden_load)
    parents, agents, parent, child, _reference_value, _key = await _fixtures(tmp_path / ".wagent")
    tui = tui_module.WAgentTui(tmp_path)
    async with tui.run_test(size=(160, 90)):
        tui.query_one("#workflow-checkpoint-run").value = "parent"
        tui.query_one("#workflow-checkpoint-load-confirm").value = "LOAD WORKFLOW"
        tui.query_one("#workflow-checkpoint-resume-confirm").value = "RESUME WORKFLOW"
        await tui._review_workflow_approvals()
        output = str(tui.query_one("#workflow-approval-result").content)
        assert '"link_status": "matched"' in output
        assert '"authorized": false' in output
        assert "PRIVATE" not in output
        assert tui.query_one("#workflow-checkpoint-load-confirm").value == "LOAD WORKFLOW"
        assert tui.query_one("#workflow-checkpoint-resume-confirm").value == "RESUME WORKFLOW"
        assert tui._active_workflow is None
        assert await parents.load_checkpoint("parent") == parent
        assert await agents.load_checkpoint("child") == child
