"""Draft async context regression source."""

import asyncio
from types import SimpleNamespace

import pytest

from w_agent import (
    AgentDefinition, AsyncRetrievedSessionHistoryPolicy, AsyncSummarizedSessionHistoryPolicy,
    CancellationToken, LocalAgentRuntime, MessageRole, ModelMessage, RunResult,
    SessionError, SessionHistoryLimits, SessionManager, SessionMessage, SessionRecord,
    SessionInputRecordingError, SessionStatus, StopReason, TextSessionHistoryPolicy,
)


def session():
    return SessionRecord("session", "PRIVATE_TITLE", messages=tuple(
        SessionMessage(MessageRole.USER, f"text-{index}", f"run-{index}") for index in range(4)
    ), metadata={"private": "PRIVATE_METADATA"})


class Selector:
    def __init__(self, indices=(1, 0)):
        self.indices = indices
        self.calls = []

    async def select(self, query, turns, *, limit):
        await asyncio.sleep(0)
        self.calls.append((query, turns, limit))
        return self.indices


class Summarizer:
    def __init__(self, value="summary"):
        self.value = value
        self.calls = []

    async def summarize(self, turns):
        await asyncio.sleep(0)
        self.calls.append(turns)
        return self.value


class Loop:
    def __init__(self):
        self.contexts = []

    async def run(self, definition, context):
        self.contexts.append(context)
        return RunResult(context.run_id, StopReason.COMPLETED, "answer", context.messages, (), 1, 0)


@pytest.mark.asyncio
async def test_async_retrieval_restores_order_and_only_passes_older_text():
    selector = Selector()
    policy = AsyncRetrievedSessionHistoryPolicy("query", selector, recent_turns=1)
    result = await policy.project(session())
    assert [message.content[0].text for message in result] == ["text-0", "text-1", "text-3"]
    query, turns, limit = selector.calls[0]
    assert query == "query" and limit == 4 and len(turns) == 3
    assert all(message.name is None and not message.metadata for turn in turns for message in turn.messages)
    assert "PRIVATE" not in repr(turns)


@pytest.mark.asyncio
async def test_async_summary_uses_user_data_and_keeps_recent_tail():
    summarizer = Summarizer()
    result = await AsyncSummarizedSessionHistoryPolicy(summarizer, recent_turns=1).project(session())
    assert len(summarizer.calls[0]) == 3 and len(result) == 2
    assert result[0].role == MessageRole.USER
    assert "untrusted data" in result[0].content[0].text
    assert result[1].content[0].text == "text-3"


@pytest.mark.asyncio
async def test_no_older_segments_skip_callbacks_and_keep_sync_equivalence():
    selector, summarizer = Selector(), Summarizer()
    for policy in (AsyncRetrievedSessionHistoryPolicy("q", selector, recent_turns=4),
                   AsyncSummarizedSessionHistoryPolicy(summarizer, recent_turns=4)):
        assert await policy.project(session()) == TextSessionHistoryPolicy().project(session())
    assert not selector.calls and not summarizer.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("indices", [[0], (True,), (-1,), (8,), (0, 0), (0, 1, 2)])
async def test_invalid_retrieval_results_fail_closed(indices):
    with pytest.raises(SessionError, match="async retrieved"):
        await AsyncRetrievedSessionHistoryPolicy("q", Selector(indices), max_retrieved_turns=2).project(session())


@pytest.mark.asyncio
@pytest.mark.parametrize("summary", [None, "", " ", "x" * 1000])
async def test_summary_requires_nonempty_bounded_text(summary):
    with pytest.raises(SessionError, match="async summarized"):
        await AsyncSummarizedSessionHistoryPolicy(Summarizer(summary),
            limits=SessionHistoryLimits(max_output_bytes=200)).project(session())


@pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), float("nan"), "30"])
def test_timeout_is_strict_finite_positive(timeout):
    with pytest.raises(ValueError):
        AsyncSummarizedSessionHistoryPolicy(Summarizer(), timeout=timeout)
    with pytest.raises(ValueError):
        AsyncRetrievedSessionHistoryPolicy("q", Selector(), timeout=timeout)


@pytest.mark.asyncio
async def test_limits_fail_before_callback_and_timeout_drains_cleanup():
    summarizer = Summarizer()
    with pytest.raises(SessionError):
        await AsyncSummarizedSessionHistoryPolicy(summarizer,
            limits=SessionHistoryLimits(max_input_bytes=1)).project(session())
    assert not summarizer.calls
    selector = Selector()
    for policy in (AsyncSummarizedSessionHistoryPolicy(summarizer, limits=SessionHistoryLimits(max_output_bytes=1)),
                   AsyncRetrievedSessionHistoryPolicy("q", selector, limits=SessionHistoryLimits(max_output_bytes=1))):
        with pytest.raises(SessionError):
            await policy.project(session())
    assert not selector.calls and not summarizer.calls
    cleaned = asyncio.Event()
    class Slow:
        async def summarize(self, turns):
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
    with pytest.raises(SessionError, match="async summarized"):
        await AsyncSummarizedSessionHistoryPolicy(Slow(), timeout=0.01).project(session())
    assert cleaned.is_set()


@pytest.mark.asyncio
async def test_runtime_accepts_async_policy_and_does_not_persist_it():
    manager, loop = SessionManager(), Loop()
    original = session()
    await manager.store.save(original)
    host = LocalAgentRuntime(SimpleNamespace(), AgentDefinition("agent"), loop, manager,
                             SimpleNamespace(providers=lambda: ()), SimpleNamespace())
    summarizer = Summarizer()
    first = await host.run("new", session_id="session",
        history_policy=AsyncSummarizedSessionHistoryPolicy(summarizer, recent_turns=1))
    assert "summary" in loop.contexts[0].messages[0].content[0].text
    assert first.session.messages[:4] == original.messages
    await host.run("again", session_id="session")
    assert loop.contexts[1].messages[0].content[0].text == "text-0"
    assert len(summarizer.calls) == 1
    await host.aclose()


@pytest.mark.asyncio
async def test_failure_does_not_start_agent_or_mutate_session_and_history_off_skips():
    manager, loop = SessionManager(), Loop()
    await manager.store.save(session())
    original = await manager.get("session")
    class Broken:
        async def project(self, record):
            raise RuntimeError("PRIVATE_SECRET")
    with pytest.raises(SessionError) as error:
        await manager.run_agent(loop, AgentDefinition("agent"), "session",
            (ModelMessage.text(MessageRole.USER, "new"),), history_policy=Broken())
    assert "PRIVATE" not in str(error.value) and not loop.contexts
    assert await manager.get("session") == original
    await manager.run_agent(loop, AgentDefinition("agent"), "session",
        (ModelMessage.text(MessageRole.USER, "new"),), history_policy=Broken(), include_history=False)
    assert len(loop.contexts[0].messages) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("use_token", [True, False])
async def test_cancellation_during_async_preparation_stops_agent_and_drains_callback(use_token):
    manager, loop = SessionManager(), Loop()
    await manager.store.save(session())
    original = await manager.get("session")
    entered, cleaned = asyncio.Event(), asyncio.Event()
    token = CancellationToken()
    class Pending:
        async def project(self, record):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
    task = asyncio.create_task(manager.run_agent(loop, AgentDefinition("agent"), "session",
        (ModelMessage.text(MessageRole.USER, "new"),), history_policy=Pending(), cancellation=token))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if use_token:
            token.cancel()
        else:
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert cleaned.is_set() and not loop.contexts
    assert await manager.get("session") == original


@pytest.mark.asyncio
async def test_changed_session_rejected_after_async_projection():
    manager, loop = SessionManager(), Loop()
    await manager.store.save(session())
    class Changed:
        async def project(self, record):
            await manager.archive(record.session_id)
            return TextSessionHistoryPolicy().project(record)
    with pytest.raises(SessionError):
        await manager.run_agent(loop, AgentDefinition("agent"), "session",
            (ModelMessage.text(MessageRole.USER, "new"),), history_policy=Changed())
    assert not loop.contexts
    assert (await manager.get("session")).status == SessionStatus.ARCHIVED


@pytest.mark.asyncio
async def test_precancelled_runtime_creates_no_session():
    manager, loop = SessionManager(), Loop()
    host = LocalAgentRuntime(SimpleNamespace(), AgentDefinition("agent"), loop, manager,
                             SimpleNamespace(providers=lambda: ()), SimpleNamespace())
    token = CancellationToken()
    token.cancel()
    with pytest.raises(asyncio.CancelledError):
        await host.run("new", cancellation=token)
    assert await manager.list() == () and not loop.contexts


@pytest.mark.asyncio
async def test_recording_preflight_precedes_external_history_callback():
    manager, loop = SessionManager(), Loop()
    await manager.store.save(session())
    class InvalidRecorder:
        def record(self, message):
            raise ValueError("PRIVATE_RECORDING_ERROR")
    class External:
        async def project(self, record):
            pytest.fail("external context invoked before recording preflight")
    with pytest.raises(SessionInputRecordingError):
        await manager.run_agent(loop, AgentDefinition("agent"), "session",
            (ModelMessage.text(MessageRole.USER, "new"),), history_policy=External(),
            record_inputs=True, input_recorder=InvalidRecorder())
    assert not loop.contexts
