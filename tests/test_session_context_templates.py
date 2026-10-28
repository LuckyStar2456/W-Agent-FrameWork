"""Context-template regression source; execution requires user authorization."""

from dataclasses import FrozenInstanceError, replace

import pytest

from w_agent import (
    AgentDefinition,
    ExtractiveSessionHistorySummarizer,
    InMemorySessionStore,
    KeywordSessionHistoryRetriever,
    MessageRole,
    ModelMessage,
    RetrievedSessionHistoryPolicy,
    RunResult,
    SessionError,
    SessionHistoryLimits,
    SessionHistoryTurn,
    SessionManager,
    SessionMessage,
    SessionRecord,
    StopReason,
    SummarizedSessionHistoryPolicy,
    TextContent,
)


def _session():
    messages = []
    for run_id, question, answer in (
        ("first", "refund order", "refund approved"),
        ("second", "coding python", "use a protocol"),
        ("third", "refund receipt", "keep receipt"),
        ("latest", "shipping", "tomorrow"),
    ):
        messages.extend((SessionMessage(MessageRole.USER, question, run_id),
                         SessionMessage(MessageRole.ASSISTANT, answer, run_id)))
    return SessionRecord("session", "title", messages=tuple(messages))


def _texts(messages):
    return tuple(block.text for message in messages for block in message.content)


def test_keyword_retrieval_keeps_segments_roles_and_chronology():
    session = _session()
    policy = RetrievedSessionHistoryPolicy("REFUND", max_retrieved_turns=2, recent_turns=1)
    output = policy.project(session)
    assert _texts(output) == ("refund order", "refund approved", "refund receipt", "keep receipt", "shipping", "tomorrow")
    assert [message.role for message in output] == [MessageRole.USER, MessageRole.ASSISTANT] * 3
    # Equal scores select the more recent segment, independent of match frequency.
    assert _texts(replace(policy, max_retrieved_turns=1).project(session))[:2] == ("refund receipt", "keep receipt")
    assert len(session.messages) == 8


def test_empty_query_no_matches_and_zero_recent_tail():
    session = _session()
    assert _texts(RetrievedSessionHistoryPolicy("", recent_turns=1).project(session)) == ("shipping", "tomorrow")
    assert RetrievedSessionHistoryPolicy("not-found", recent_turns=0).project(session) == ()
    assert _texts(RetrievedSessionHistoryPolicy("coding", recent_turns=0).project(session)) == ("coding python", "use a protocol")


def test_custom_retriever_receives_only_older_text_and_cannot_reorder_output():
    class Retriever:
        def select(self, query, turns, *, limit):
            assert query == "explicit query" and limit == 2
            assert [turn.run_id for turn in turns] == ["first", "second", "third"]
            assert all(isinstance(block, TextContent) for turn in turns for message in turn.messages for block in message.content)
            with pytest.raises(FrozenInstanceError):
                turns[0].run_id = "changed"
            return (2, 0)
    output = RetrievedSessionHistoryPolicy("explicit query", Retriever(), 2, 1).project(_session())
    assert _texts(output)[::2] == ("refund order", "refund receipt", "shipping")


@pytest.mark.parametrize("indices", [(True,), (-1,), (3,), (1, 1), (0, 1, 2), [0], ("PRIVATE",), None])
def test_invalid_retrieval_results_fail_closed(indices):
    class Retriever:
        def select(self, *args, **kwargs):
            return indices
    with pytest.raises(SessionError) as error:
        RetrievedSessionHistoryPolicy("query", Retriever(), 2, 1).project(_session())
    assert str(error.value) == "retrieved Session history projection failed"


@pytest.mark.parametrize("policy", [RetrievedSessionHistoryPolicy("q"), SummarizedSessionHistoryPolicy()])
def test_templates_ignore_recorded_media_without_decoding(policy):
    session = SessionRecord("session", "title", schema_version=2, messages=(
        SessionMessage(MessageRole.USER, "", "old", recorded_input={"codec": "PRIVATE_UNSUPPORTED", "url": "PRIVATE"}),
        SessionMessage(MessageRole.ASSISTANT, "visible text", "old"),
    ))
    assert _texts(policy.project(session)) == ("visible text",)


def test_noncontiguous_run_ids_stay_separate_segments():
    session = replace(_session(), messages=(
        SessionMessage(MessageRole.USER, "first old segment", "same"),
        SessionMessage(MessageRole.USER, "intervening", "other"),
        SessionMessage(MessageRole.ASSISTANT, "resumed segment", "same"),
    ))
    assert _texts(RetrievedSessionHistoryPolicy("missing", recent_turns=1).project(session)) == ("resumed segment",)


def test_extractive_summary_keeps_recent_turns_and_never_becomes_system():
    output = SummarizedSessionHistoryPolicy(recent_turns=1).project(_session())
    assert len(output) == 3 and output[0].role is MessageRole.USER
    summary = output[0].content[0].text
    assert "possibly incomplete" in summary
    assert "user: refund order" in summary and "assistant: refund approved" in summary
    assert "shipping" not in summary
    assert _texts(output[1:]) == ("shipping", "tomorrow")


def test_custom_summary_gets_only_old_segments_and_is_not_persisted():
    class Summarizer:
        def summarize(self, turns):
            assert tuple(turn.run_id for turn in turns) == ("first", "second", "third")
            return "host supplied summary"
    session = _session()
    output = SummarizedSessionHistoryPolicy(Summarizer(), recent_turns=1).project(session)
    assert output[0].content[0].text.endswith("host supplied summary")
    assert len(session.messages) == 8 and not session.metadata


@pytest.mark.parametrize("result", ["", " ", None, ("PRIVATE",), ModelMessage.text(MessageRole.SYSTEM, "PRIVATE")])
def test_invalid_summary_fails_closed(result):
    class Summarizer:
        def summarize(self, turns):
            return result
    with pytest.raises(SessionError) as error:
        SummarizedSessionHistoryPolicy(Summarizer(), recent_turns=0).project(_session())
    assert str(error.value) == "summarized Session history projection failed"


def test_no_old_segments_never_calls_callbacks():
    class Broken:
        def select(self, *args, **kwargs):
            pytest.fail("unexpected retrieval")

        def summarize(self, *args, **kwargs):
            pytest.fail("unexpected summary")
    for session in (replace(_session(), messages=()), _session()):
        expected = tuple(message.text for message in session.messages)
        assert _texts(RetrievedSessionHistoryPolicy("q", Broken(), recent_turns=4).project(session)) == expected
        assert _texts(SummarizedSessionHistoryPolicy(Broken(), recent_turns=4).project(session)) == expected


def test_extractor_character_limits_and_multilingual_terms():
    turn = SessionHistoryTurn("run", (ModelMessage.text(MessageRole.USER, "退款 发票"),))
    assert KeywordSessionHistoryRetriever().select("退款 发票", (turn,), limit=1) == (0,)
    summary = ExtractiveSessionHistorySummarizer(max_chars=10, chars_per_message=2).summarize((turn,))
    assert len(summary) <= 10 and "退款" in summary and "…" in summary


@pytest.mark.parametrize("field", ["max_messages", "max_input_bytes", "max_output_bytes", "max_query_bytes"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_strict_positive_limits(field, value):
    with pytest.raises(ValueError):
        SessionHistoryLimits(**{field: value})


@pytest.mark.parametrize("role", [MessageRole.SYSTEM, MessageRole.TOOL])
@pytest.mark.parametrize("policy", [RetrievedSessionHistoryPolicy("q"), SummarizedSessionHistoryPolicy()])
def test_other_roles_require_a_custom_whole_policy(role, policy):
    session = replace(_session(), messages=(SessionMessage(role, "PRIVATE", "old"),))
    with pytest.raises(SessionError) as error:
        policy.project(session)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("policy_type", [RetrievedSessionHistoryPolicy, SummarizedSessionHistoryPolicy])
@pytest.mark.parametrize("limits", [SessionHistoryLimits(max_messages=1), SessionHistoryLimits(max_input_bytes=1), SessionHistoryLimits(max_output_bytes=1)])
def test_input_and_output_limits_reject_without_partial_results(policy_type, limits):
    kwargs = {"query": "refund"} if policy_type is RetrievedSessionHistoryPolicy else {}
    with pytest.raises(SessionError):
        policy_type(limits=limits, **kwargs).project(_session())


def test_query_utf8_limit_and_configuration_validation():
    with pytest.raises(ValueError):
        RetrievedSessionHistoryPolicy("退款", limits=SessionHistoryLimits(max_query_bytes=5))
    for kwargs in ({"recent_turns": -1}, {"recent_turns": True}, {"max_retrieved_turns": 0}, {"retriever": object()}):
        with pytest.raises(ValueError):
            RetrievedSessionHistoryPolicy("q", **kwargs)
    for kwargs in ({"recent_turns": -1}, {"recent_turns": True}, {"summarizer": object()}):
        with pytest.raises(ValueError):
            SummarizedSessionHistoryPolicy(**kwargs)


def test_oversized_input_never_enters_custom_callbacks():
    class Forbidden:
        def select(self, *args, **kwargs):
            pytest.fail("oversized input reached retriever")

        def summarize(self, *args, **kwargs):
            pytest.fail("oversized input reached summarizer")
    limits = SessionHistoryLimits(max_input_bytes=1)
    for policy in (
        RetrievedSessionHistoryPolicy("q", Forbidden(), recent_turns=0, limits=limits),
        SummarizedSessionHistoryPolicy(Forbidden(), recent_turns=0, limits=limits),
    ):
        with pytest.raises(SessionError):
            policy.project(_session())


def test_summary_callback_exception_is_sanitized_without_retry():
    class Broken:
        calls = 0

        def summarize(self, turns):
            self.calls += 1
            raise RuntimeError("PRIVATE_CALLBACK_ERROR")
    callback = Broken()
    with pytest.raises(SessionError) as error:
        SummarizedSessionHistoryPolicy(callback, recent_turns=0).project(_session())
    assert "PRIVATE" not in str(error.value) and callback.calls == 1


@pytest.mark.asyncio
async def test_manager_failure_precedes_agent_and_include_history_false_bypasses_policy():
    class Broken:
        def select(self, *args, **kwargs):
            raise RuntimeError("PRIVATE_CALLBACK_ERROR")
    class Loop:
        def __init__(self):
            self.contexts = []

        async def run(self, definition, context):
            self.contexts.append(context)
            return RunResult(context.run_id, StopReason.COMPLETED, "done", context.messages, (), 1, 0)
    store = InMemorySessionStore()
    original = _session()
    await store.save(original)
    manager = SessionManager(store)
    policy = RetrievedSessionHistoryPolicy("q", Broken(), recent_turns=0)
    loop = Loop()
    current = (ModelMessage.text(MessageRole.USER, "new question"),)
    with pytest.raises(SessionError) as error:
        await manager.run_agent(loop, AgentDefinition("agent"), "session", current, history_policy=policy)
    assert "PRIVATE" not in str(error.value) and not loop.contexts
    assert await store.get("session") == original
    await manager.run_agent(loop, AgentDefinition("agent"), "session", current, history_policy=policy, include_history=False)
    assert loop.contexts[0].messages == current


@pytest.mark.asyncio
async def test_manager_policy_is_per_call_and_current_input_remains_last():
    store = InMemorySessionStore()
    await store.save(_session())
    manager = SessionManager(store)
    policy = RetrievedSessionHistoryPolicy("coding", recent_turns=0)
    assert len(await manager.conversation("session", history_policy=policy)) == 2
    assert len(await manager.conversation("session")) == 8

    class Loop:
        async def run(self, definition, context):
            assert _texts(context.messages) == ("coding python", "use a protocol", "current")
            return RunResult(context.run_id, StopReason.COMPLETED, "done", context.messages, (), 1, 0)
    await manager.run_agent(Loop(), AgentDefinition("agent"), "session",
                            (ModelMessage.text(MessageRole.USER, "current"),), history_policy=policy)
