"""Draft independently metered summary regressions; execution requires approval."""

import asyncio
import json
from dataclasses import replace

import pytest

from w_agent import (
    AgentDefinition, AgentSessionHistorySummarizer, AsyncSummarizedSessionHistoryPolicy,
    BlockEnd, BlockStart, CostBudget, FinishEvent, FinishReason, InMemoryRunStore,
    MessageRole, ModelCapability, ModelCost, ModelDescriptor, ModelExecutor,
    ModelMessage, ModelPrice, ModelRegistry, ModelRouter, PriceTable, PricingCatalog, ReactAgentLoop, RunResult,
    ScriptedModelProvider, ScriptedModelTurn, SessionHistoryLimits, SessionHistoryTurn,
    SessionMessage, SessionRecord, SessionSummaryError, SessionSummaryRunReport,
    StopReason, TextContent, TextDelta, TokenBudget, TokenUsage, ToolExecutor,
    ToolRegistry, UsageEvent,
)


def turns():
    return (SessionHistoryTurn("PRIVATE_RUN_ID", (ModelMessage(
        MessageRole.USER, (TextContent("PRIVATE_INPUT"),), name="PRIVATE_NAME",
        metadata={"secret": "PRIVATE_METADATA"},
    ),)),)


class Observer:
    def __init__(self, fail_on=None):
        self.reports = []
        self.fail_on = fail_on

    async def record(self, report):
        if report.status == self.fail_on:
            raise RuntimeError("PRIVATE_OBSERVER_ERROR")
        self.reports.append(report)


class Loop:
    def __init__(self, **changes):
        self.changes = changes
        self.calls = []

    async def run(self, definition, context):
        self.calls.append((definition, context))
        result = RunResult(context.run_id, StopReason.COMPLETED, "PRIVATE_SUMMARY", (), (), 1, 0,
            usage=TokenUsage(5, 3, 1), model_calls=1, reported_usage_calls=1)
        return replace(result, **self.changes)


@pytest.mark.asyncio
async def test_summary_run_is_independent_and_observer_is_prompt_free():
    loop, observer = Loop(), Observer()
    summary = AgentSessionHistorySummarizer(loop, observer)
    assert await summary.summarize(turns()) == "PRIVATE_SUMMARY"
    definition, context = loop.calls[0]
    assert definition.max_tool_calls == 0 and definition.max_steps == 1
    assert definition.token_budget.require_usage
    assert context.session_id is None and not context.tool_context.permissions
    prompt = context.messages[0].content[0].text
    assert "PRIVATE_INPUT" in prompt
    assert all(value not in prompt for value in ("PRIVATE_NAME", "PRIVATE_METADATA", "PRIVATE_RUN_ID"))
    assert [report.status for report in observer.reports] == ["started", "completed"]
    first, final = observer.reports
    assert first.run_id == final.run_id == context.run_id and first.usage is None
    assert not first.usage_complete and final.usage_complete and not final.cost_complete
    assert final.to_dict()["usage"]["total_tokens"] == 8  # Cached input is not added again.
    assert "PRIVATE" not in json.dumps([report.to_dict() for report in observer.reports])
    await summary.summarize(turns())
    assert loop.calls[0][1].run_id != loop.calls[1][1].run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"stop_reason": StopReason.TOKEN_BUDGET}, {"stop_reason": StopReason.MODEL_ERROR},
    {"stop_reason": StopReason.NEEDS_APPROVAL}, {"output": ""},
    {"output": "x" * 70000}, {"tool_calls": 1}, {"reported_usage_calls": 0},
    {"checkpoint_id": "checkpoint"},
])
async def test_rejected_summary_still_reports_consumed_usage(changes):
    loop, observer = Loop(**changes), Observer()
    with pytest.raises(SessionSummaryError, match="output rejected"):
        await AgentSessionHistorySummarizer(loop, observer).summarize(turns())
    assert observer.reports[-1].status == "rejected"
    assert observer.reports[-1].usage == TokenUsage(5, 3, 1)
    assert len(loop.calls) == 1


@pytest.mark.asyncio
async def test_explicit_budget_and_cost_requirements_are_preserved():
    observer = Observer()
    definition = AgentDefinition("summary", max_tool_calls=0,
        token_budget=TokenBudget(max_total_tokens=7, require_usage=True))
    with pytest.raises(SessionSummaryError):
        await AgentSessionHistorySummarizer(Loop(), observer, definition).summarize(turns())
    assert observer.reports[-1].status == "rejected"
    cost = ModelCost("USD", "test-prices", "0.01", "0.02")
    definition = AgentDefinition("summary", max_tool_calls=0,
        cost_budget=CostBudget("0.10", "test-prices"))
    observer = Observer()
    loop = Loop(cost=cost, priced_usage_calls=1)
    assert await AgentSessionHistorySummarizer(loop, observer, definition).summarize(turns())
    assert loop.calls[0][0] is definition
    assert observer.reports[-1].cost_complete
    assert observer.reports[-1].to_dict()["cost"]["total"] == "0.03"
    with pytest.raises(SessionSummaryError):
        await AgentSessionHistorySummarizer(Loop(), Observer(), definition).summarize(turns())


@pytest.mark.asyncio
async def test_observer_failures_never_retry_or_return_unaccounted_summary():
    for status, calls in (("started", 0), ("completed", 1)):
        loop, observer = Loop(), Observer(fail_on=status)
        with pytest.raises(SessionSummaryError) as error:
            await AgentSessionHistorySummarizer(loop, observer).summarize(turns())
        assert "PRIVATE" not in str(error.value) and len(loop.calls) == calls


@pytest.mark.asyncio
async def test_raised_loop_error_marks_unknown_usage_not_zero():
    class Failed:
        async def run(self, definition, context):
            raise RuntimeError("PRIVATE_PROVIDER_ERROR")
    observer = Observer()
    with pytest.raises(SessionSummaryError) as error:
        await AgentSessionHistorySummarizer(Failed(), observer).summarize(turns())
    assert "PRIVATE" not in str(error.value)
    report = observer.reports[-1]
    assert report.status == "failed" and report.usage is None
    assert report.model_calls is None and not report.usage_complete


@pytest.mark.asyncio
async def test_cancellation_reports_unknown_usage_and_propagates():
    entered, cleaned = asyncio.Event(), asyncio.Event()
    class Pending:
        async def run(self, definition, context):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
    observer = Observer()
    task = asyncio.create_task(AgentSessionHistorySummarizer(Pending(), observer).summarize(turns()))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert cleaned.is_set() and observer.reports[-1].status == "cancelled"
    assert observer.reports[-1].usage is None


@pytest.mark.asyncio
async def test_input_limit_rejects_before_observer_and_run():
    loop, observer = Loop(), Observer()
    with pytest.raises(SessionSummaryError, match="input rejected"):
        await AgentSessionHistorySummarizer(loop, observer,
            limits=SessionHistoryLimits(max_input_bytes=10)).summarize(turns())
    assert not loop.calls and not observer.reports
    with pytest.raises(ValueError, match="disable tool"):
        AgentSessionHistorySummarizer(loop, observer, AgentDefinition("unsafe"))


@pytest.mark.asyncio
async def test_malformed_accounting_and_wrong_identity_are_not_accepted():
    for changes in ({"model_calls": -1}, {"reported_usage_calls": 9}, {"run_id": "other"}):
        observer = Observer()
        with pytest.raises(SessionSummaryError):
            await AgentSessionHistorySummarizer(Loop(**changes), observer).summarize(turns())
        assert observer.reports[-1].status == "failed" and observer.reports[-1].usage is None


@pytest.mark.asyncio
async def test_builtin_react_summary_uses_separate_run_events_and_zero_tools():
    provider = ScriptedModelProvider(ModelDescriptor("scripted", "summary", frozenset({
        ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT, ModelCapability.STREAMING,
    })), (ScriptedModelTurn((BlockStart(0, "text"), TextDelta(0, "summary"), BlockEnd(0, TextContent("summary")),
                            UsageEvent(TokenUsage(5, 3)), FinishEvent(FinishReason.STOP)), expected_tools=()),))
    models, tools, store, observer = ModelRegistry(), ToolRegistry(), InMemoryRunStore(), Observer()
    models.register("scripted", provider)
    prices = PricingCatalog((PriceTable("test-prices", "USD", (ModelPrice("scripted", "summary", 1, 2),)),))
    loop = ReactAgentLoop(ModelExecutor(models, ModelRouter(models)), tools, ToolExecutor(tools), store=store, pricing=prices)
    definition = AgentDefinition("summary", max_steps=1, max_tool_calls=0,
        token_budget=TokenBudget(require_usage=True), cost_budget=CostBudget("0.10", "test-prices"))
    summarizer = AgentSessionHistorySummarizer(loop, observer, definition)
    policy = AsyncSummarizedSessionHistoryPolicy(summarizer, recent_turns=0)
    record = SessionRecord("session", "title", messages=(SessionMessage(MessageRole.USER, "old text", "old"),))
    history = await policy.project(record)
    report = observer.reports[-1]
    assert report.status == "completed" and report.usage == TokenUsage(5, 3)
    assert report.model_calls == report.reported_usage_calls == 1
    assert report.cost_complete and report.cost.total > 0
    assert history[0].role == MessageRole.USER and "summary" in history[0].content[0].text
    events = await store.events(report.run_id)
    assert events and all(event.session_id is None for event in events)
    assert provider.requests[0].tools == ()


def test_report_unknown_and_invalid_counter_contracts():
    report = SessionSummaryRunReport("summary", "cancelled")
    assert report.to_dict()["usage"] is None and not report.cost_complete
    with pytest.raises(ValueError):
        SessionSummaryRunReport("summary", "completed", usage=TokenUsage(), model_calls=True,
                                reported_usage_calls=0, priced_usage_calls=0)
