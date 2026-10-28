"""Draft preparation-accounting regressions; execution requires authorization."""

import asyncio
import json
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from w_agent import (
    AgentSessionHistorySummarizer, InMemorySessionSummaryObserver, MessageRole,
    ModelCost, ModelMessage, RunResult, SessionHistoryTurn, SessionSummaryError,
    SessionSummaryRunReport, SessionUsageError, StopReason, TokenUsage,
    aggregate_session_preparation_usage,
)


def report(run_id="summary", *, status="completed", priced=True):
    return SessionSummaryRunReport(run_id, status, StopReason.COMPLETED,
        TokenUsage(5, 3, 2), 1, 1, ModelCost("USD", "v1", "0.01", "0.02") if priced else None,
        1 if priced else 0)


def main():
    return RunResult("main", StopReason.COMPLETED, "PRIVATE_OUTPUT",
        (ModelMessage.text(MessageRole.USER, "PRIVATE_INPUT"),), (), 1, 0,
        usage=TokenUsage(20, 10, 4), model_calls=2, reported_usage_calls=2,
        cost=ModelCost("USD", "v1", "0.02", "0.04"), priced_usage_calls=2)


@pytest.mark.asyncio
async def test_started_to_terminal_duplicate_delivery_and_main_totals():
    observer = InMemorySessionSummaryObserver()
    started, terminal = SessionSummaryRunReport("summary", "started"), report()
    await observer.record(started)
    pending = await observer.snapshot(main())
    assert pending.pending_summary_run_ids == ("summary",)
    assert pending.known_usage == main().usage and not pending.usage_complete
    await observer.record(terminal)
    await observer.record(terminal)
    snapshot = await observer.snapshot(main())
    assert snapshot.known_usage == TokenUsage(25, 13, 6)
    assert snapshot.known_usage.total_tokens == 38
    assert snapshot.known_model_calls == snapshot.known_reported_usage_calls == 3
    assert snapshot.cost_totals[0].total == Decimal("0.09")
    assert snapshot.usage_complete and snapshot.cost_complete
    assert "PRIVATE" not in json.dumps(snapshot.to_dict())
    assert (await observer.reports()) == (terminal,)
    assert pending.pending_summary_run_ids == ("summary",)  # Prior view never mutates.
    with pytest.raises(FrozenInstanceError):
        snapshot.main_run_id = "changed"


@pytest.mark.asyncio
async def test_main_result_is_replaced_on_resume_not_accumulated():
    observer = InMemorySessionSummaryObserver()
    await observer.record(report())
    paused = replace(main(), stop_reason=StopReason.NEEDS_APPROVAL)
    first = await observer.snapshot(paused)
    resumed = replace(main(), usage=TokenUsage(30, 12), model_calls=3, reported_usage_calls=3,
                      priced_usage_calls=3, cost=ModelCost("USD", "v1", "0.04", "0.05"))
    final = await observer.snapshot(resumed)
    assert final.known_usage == TokenUsage(35, 15, 2)
    assert first.main_stop_reason == StopReason.NEEDS_APPROVAL
    assert final == await observer.snapshot(resumed)
    assert len(await observer.reports()) == 1


def test_unknown_and_partial_usage_are_not_reported_as_complete():
    records = (SessionSummaryRunReport("cancelled", "cancelled"),
               replace(report("partial", priced=False), reported_usage_calls=0), report("known"))
    snapshot = aggregate_session_preparation_usage(records, main())
    assert snapshot.known_usage.total_tokens == 46
    assert snapshot.incomplete_usage_run_ids == ("cancelled", "partial")
    assert snapshot.incomplete_cost_run_ids == ("cancelled", "partial")
    assert not snapshot.usage_complete and not snapshot.cost_complete
    absent = aggregate_session_preparation_usage((report(),))
    assert absent.known_usage.total_tokens == 8 and absent.main_run_id is None
    assert not absent.usage_complete and not absent.cost_complete
    assert not absent.to_dict()["main_result_supplied"]


def test_cost_versions_and_currencies_remain_separate():
    records = (report("a"), replace(report("b"), cost=ModelCost("USD", "v2", 1)),
               replace(report("c"), cost=ModelCost("CNY", "v1", 2)))
    snapshot = aggregate_session_preparation_usage(records, main())
    assert [(cost.currency, cost.price_table_version) for cost in snapshot.cost_totals] == [
        ("CNY", "v1"), ("USD", "v1"), ("USD", "v2"),
    ]
    assert snapshot.cost_complete and snapshot.cost_totals[1].total == Decimal("0.09")


@pytest.mark.asyncio
async def test_terminal_conflicts_and_capacity_fail_without_mutation():
    observer = InMemorySessionSummaryObserver(max_runs=1)
    await observer.record(SessionSummaryRunReport("summary", "started"))
    with pytest.raises(SessionUsageError, match="capacity"):
        await observer.record(report("other"))
    await observer.record(report())  # Finishing an existing Run remains possible at capacity.
    for conflict in (replace(report(), usage=TokenUsage(9, 3)), SessionSummaryRunReport("summary", "started")):
        with pytest.raises(SessionUsageError, match="conflict"):
            await observer.record(conflict)
    assert await observer.reports() == (report(),)


@pytest.mark.asyncio
async def test_concurrent_duplicate_deliveries_count_once():
    observer = InMemorySessionSummaryObserver()
    await asyncio.gather(*(observer.record(report()) for _ in range(12)))
    assert len(await observer.reports()) == 1
    assert (await observer.snapshot(main())).known_usage.total_tokens == 38


def test_duplicate_ids_and_invalid_main_accounting_are_rejected():
    for records, result in (((report(), report()), main()), ((report("main"),), main()),
                            ((report(),), replace(main(), model_calls=-1))):
        with pytest.raises(SessionUsageError) as error:
            aggregate_session_preparation_usage(records, result)
        assert "PRIVATE" not in str(error.value)


@pytest.mark.asyncio
async def test_observer_is_directly_composable_and_capacity_stops_generation():
    class Loop:
        def __init__(self):
            self.calls = 0

        async def run(self, definition, context):
            self.calls += 1
            return replace(main(), run_id=context.run_id, tool_calls=0)
    observer, loop = InMemorySessionSummaryObserver(max_runs=1), Loop()
    summarizer = AgentSessionHistorySummarizer(loop, observer)
    turns = (SessionHistoryTurn("old", (ModelMessage.text(MessageRole.USER, "PRIVATE"),)),)
    assert await summarizer.summarize(turns) == "PRIVATE_OUTPUT"
    snapshot = await observer.snapshot(main())
    assert snapshot.known_usage.total_tokens == 60 and snapshot.usage_complete
    with pytest.raises(SessionSummaryError, match="observer failed"):
        await summarizer.summarize(turns)
    assert loop.calls == 1


def test_empty_accounting_is_not_complete_main_operation():
    empty = aggregate_session_preparation_usage(())
    assert empty.known_usage == TokenUsage()
    assert not empty.usage_complete and not empty.cost_complete
    with pytest.raises(ValueError):
        InMemorySessionSummaryObserver(max_runs=True)
