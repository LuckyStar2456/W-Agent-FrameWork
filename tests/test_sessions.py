import pytest

from w_agent import (
    AgentDefinition,
    JsonSessionStore,
    MessageRole,
    ModelMessage,
    RunResult,
    SessionError,
    SessionManager,
    SessionStatus,
    StopReason,
    TokenUsage,
    ToolExecutionContext,
)


class StubLoop:
    def __init__(self, outputs, reasons=None):
        self.outputs = list(outputs)
        self.reasons = list(reasons or [StopReason.COMPLETED] * len(outputs))
        self.contexts = []

    async def run(self, definition, context):
        self.contexts.append(context)
        return self._result(context.run_id, context.messages)

    async def resume(self, run_id, *, tool_context, cancellation=None):
        del tool_context, cancellation
        return self._result(run_id, ())

    def stream(self, definition, context):
        raise NotImplementedError

    def _result(self, run_id, messages):
        output = self.outputs.pop(0)
        reason = self.reasons.pop(0)
        return RunResult(
            run_id,
            reason,
            output,
            tuple(messages),
            (),
            1,
            0,
            checkpoint_id=run_id if reason is StopReason.NEEDS_APPROVAL else None,
            usage=TokenUsage(5, 2),
            model_calls=1,
            reported_usage_calls=1,
        )


@pytest.mark.asyncio
async def test_session_projects_text_history_across_agent_runs(tmp_path):
    manager = SessionManager(JsonSessionStore(tmp_path))
    session = await manager.create("Support", session_id="support-1")
    loop = StubLoop(["first answer", "second answer"])
    definition = AgentDefinition("support")

    first = await manager.run_agent(
        loop,
        definition,
        session.session_id,
        (ModelMessage.text(MessageRole.USER, "first question"),),
        run_id="run-1",
    )
    second = await manager.run_agent(
        loop,
        definition,
        session.session_id,
        (ModelMessage.text(MessageRole.USER, "second question"),),
        run_id="run-2",
    )

    assert first.output == "first answer"
    assert second.output == "second answer"
    assert [message.content[0].text for message in loop.contexts[1].messages] == [
        "first question",
        "first answer",
        "second question",
    ]
    reopened = SessionManager(JsonSessionStore(tmp_path))
    stored = await reopened.get("support-1")
    assert [item.run_id for item in stored.runs] == ["run-1", "run-2"]
    assert stored.runs[0].usage.total_tokens == 7
    assert [item.text for item in stored.messages] == [
        "first question",
        "first answer",
        "second question",
        "second answer",
    ]


@pytest.mark.asyncio
async def test_session_archive_filters_and_blocks_new_runs(tmp_path):
    manager = SessionManager(JsonSessionStore(tmp_path))
    await manager.create("Archived", session_id="archived-1")
    archived = await manager.archive("archived-1")

    assert archived.status is SessionStatus.ARCHIVED
    assert await manager.list() == ()
    assert [item.session_id for item in await manager.list(include_archived=True)] == [
        "archived-1"
    ]
    with pytest.raises(SessionError, match="read-only"):
        await manager.run_agent(
            StubLoop(["no"]),
            AgentDefinition("agent"),
            "archived-1",
            (ModelMessage.text(MessageRole.USER, "blocked"),),
        )

    active = await manager.archive("archived-1", archived=False)
    assert active.status is SessionStatus.ACTIVE


@pytest.mark.asyncio
async def test_session_resume_updates_existing_run_without_duplicate_input(tmp_path):
    manager = SessionManager(JsonSessionStore(tmp_path))
    await manager.create("Approval", session_id="approval-1")
    loop = StubLoop(
        ["waiting", "approved"],
        [StopReason.NEEDS_APPROVAL, StopReason.COMPLETED],
    )
    await manager.run_agent(
        loop,
        AgentDefinition("writer"),
        "approval-1",
        (ModelMessage.text(MessageRole.USER, "write this"),),
        run_id="run-approval",
    )

    resumed = await manager.resume_agent(
        loop,
        "approval-1",
        "run-approval",
        tool_context=ToolExecutionContext(
            approved_call_ids=frozenset({"call-1"})
        ),
    )

    stored = await manager.get("approval-1")
    assert resumed.stop_reason is StopReason.COMPLETED
    assert len(stored.runs) == 1
    assert stored.runs[0].output == "approved"
    assert [item.text for item in stored.messages] == [
        "write this",
        "waiting",
        "approved",
    ]


@pytest.mark.asyncio
async def test_session_store_rejects_unsafe_ids_and_corrupt_records(tmp_path):
    store = JsonSessionStore(tmp_path)
    with pytest.raises(ValueError, match="safe"):
        await store.get("../escape")

    (tmp_path / "broken.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(SessionError, match="corrupt"):
        await store.get("broken")
