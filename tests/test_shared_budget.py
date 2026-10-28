"""Shared budget regression source; execution requires user authorization."""

import asyncio
from dataclasses import replace
from decimal import Decimal

import pytest

from w_agent import (
    AgentDefinition, AgentSessionHistorySummarizer, BlockEnd, BlockStart,
    InMemorySessionSummaryObserver, ReactAgentLoop, RunContext, SessionHistoryTurn,
    TextContent, ToolExecutor, ToolRegistry,
    CancellationToken, FinishEvent, FinishReason, InMemorySharedBudget, InvocationPolicy,
    MessageRole, ModelCapability, ModelCost, ModelDescriptor, ModelError, ModelExecutor,
    ModelFailure, ModelFailureKind, ModelInvocationError, ModelMessage, ModelRegistry,
    ModelRequest, SharedBudgetAmount, SharedBudgetError, SharedBudgetLimits,
    SharedBudgetModelProvider, TokenUsage, UsageEvent,
)
from w_agent.models import collect_stream


def amount(input_tokens=10, output_tokens=5, cost=None):
    return SharedBudgetAmount(TokenUsage(input_tokens, output_tokens), cost)


def request():
    return ModelRequest((ModelMessage.text(MessageRole.USER, "PRIVATE_INPUT"),),
                        model="test", max_output_tokens=5)


class Meter:
    async def bound(self, request):
        return amount()

    async def actual(self, request, usage):
        return SharedBudgetAmount(usage)


class Provider:
    def __init__(self, usage=TokenUsage(8, 2), failure=False):
        self.usage, self.failure, self.calls = usage, failure, 0

    async def list_models(self):
        return (await self.resolve("test"),)

    async def resolve(self, model):
        return ModelDescriptor("test", "test", frozenset({ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT}))

    async def stream(self, request, *, cancellation=None):
        self.calls += 1
        if self.failure:
            raise ModelError(ModelFailure(ModelFailureKind.NETWORK, "network", "PRIVATE_ERROR", True))
        yield BlockStart(0, "text")
        yield BlockEnd(0, TextContent("answer"))
        if self.usage is not None:
            yield UsageEvent(self.usage)
        yield FinishEvent(FinishReason.STOP)


@pytest.mark.asyncio
async def test_concurrent_admission_atomic_settlement_and_duplicate_delivery():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20))
    results = await asyncio.gather(*(ledger.reserve(amount()) for _ in range(8)), return_exceptions=True)
    tickets = [item for item in results if not isinstance(item, Exception)]
    assert len(tickets) == 1
    ticket = tickets[0]
    assert (await ledger.snapshot()).held_usage.total_tokens == 15
    await ledger.settle(ticket, amount(8, 2))
    await ledger.settle(ticket, amount(8, 2))
    assert (await ledger.snapshot()).known_usage.total_tokens == 10
    with pytest.raises(SharedBudgetError):
        await ledger.settle(ticket, amount(8, 3))
    with pytest.raises(SharedBudgetError):
        await ledger.release(ticket)
    await ledger.reserve(amount(5, 5))  # Equality with the budget is admissible.
    with pytest.raises(SharedBudgetError):
        await ledger.reserve(amount(1, 0))


@pytest.mark.asyncio
async def test_cost_identity_and_unknown_usage_block_new_calls():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_cost="1", currency="USD", price_table_version="v1"))
    for cost in (None, ModelCost("CNY", "v1", 1), ModelCost("USD", "v2", 1)):
        with pytest.raises(SharedBudgetError):
            await ledger.reserve(amount(cost=cost))
    ticket = await ledger.reserve(amount(cost=ModelCost("USD", "v1", "0.80")))
    with pytest.raises(SharedBudgetError):
        await ledger.reserve(amount(cost=ModelCost("USD", "v1", "0.30")))
    await ledger.settle(ticket, None)
    await ledger.settle(ticket, None)
    view = await ledger.snapshot()
    assert view.blocked and view.held_cost == Decimal("0.80") and view.known_cost == 0
    with pytest.raises(SharedBudgetError):
        await ledger.reserve(amount(cost=ModelCost("USD", "v1", "0.01")))
    with pytest.raises(SharedBudgetError):
        await ledger.settle(ticket, amount(cost=ModelCost("USD", "v1", "0.60")))


@pytest.mark.asyncio
async def test_actual_exceeding_bound_is_preserved_and_latches_breach():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=100))
    ticket = await ledger.reserve(amount())
    await ledger.settle(ticket, amount(50, 50))
    view = await ledger.snapshot()
    assert view.known_usage.total_tokens == 100 and view.breached and view.blocked
    with pytest.raises(SharedBudgetError):
        await ledger.reserve(amount(0, 0))


@pytest.mark.asyncio
async def test_release_never_started_capacity_and_foreign_reservations():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20), max_reservations=1)
    ticket = await ledger.reserve(amount())
    other = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20))
    with pytest.raises(SharedBudgetError):
        await other.release(ticket)
    await ledger.release(ticket)
    await ledger.release(ticket)
    view = await ledger.snapshot()
    assert not view.blocked and view.held_usage.total_tokens == view.known_usage.total_tokens == 0
    with pytest.raises(SharedBudgetError):
        await ledger.reserve(amount())  # Terminal tombstones also count toward capacity.


@pytest.mark.asyncio
async def test_summary_and_main_provider_wrappers_share_one_pool():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=25))
    summary, main = Provider(), Provider()
    first = SharedBudgetModelProvider(summary, ledger, Meter())
    second = SharedBudgetModelProvider(main, ledger, Meter())
    assert (await collect_stream(first.stream(request()))).usage.total_tokens == 10
    assert (await collect_stream(second.stream(request()))).usage.total_tokens == 10
    with pytest.raises(SharedBudgetError):
        await collect_stream(second.stream(request()))
    assert summary.calls == main.calls == 1
    assert (await ledger.snapshot()).known_usage.total_tokens == 20
    assert len(await first.list_models()) == 1
    assert not hasattr(first, "resume_stream")


@pytest.mark.asyncio
@pytest.mark.parametrize("usage", [None, TokenUsage(10, 6), TokenUsage(True, 0)])
async def test_missing_invalid_or_overbound_usage_never_publishes_success(usage):
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=100))
    provider = Provider(usage)
    wrapper = SharedBudgetModelProvider(provider, ledger, Meter())
    events = []
    with pytest.raises(SharedBudgetError):
        async for event in wrapper.stream(request()):
            events.append(event)
    assert not any(isinstance(event, FinishEvent) for event in events)
    assert (await ledger.snapshot()).blocked
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_executor_cannot_retry_unknown_billable_failure():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=100))
    provider = Provider(failure=True)
    registry = ModelRegistry()
    registry.register("test", SharedBudgetModelProvider(provider, ledger, Meter()))
    executor = ModelExecutor(registry, policy=InvocationPolicy(max_attempts_per_route=3))
    with pytest.raises(ModelInvocationError) as error:
        await executor.invoke(request())
    assert provider.calls == 1
    assert not error.value.failure.retryable
    assert "PRIVATE_ERROR" not in str(error.value)
    assert (await ledger.snapshot()).blocked


@pytest.mark.asyncio
async def test_react_summary_and_main_run_use_same_provider_admission():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=25))
    provider = Provider()
    registry = ModelRegistry()
    registry.register("test", SharedBudgetModelProvider(provider, ledger, Meter()))
    tools = ToolRegistry()
    loop = ReactAgentLoop(ModelExecutor(registry), tools, ToolExecutor(tools))
    observer = InMemorySessionSummaryObserver()
    definition = AgentDefinition("summary", max_steps=1, max_tool_calls=0, max_output_tokens=5)
    summarizer = AgentSessionHistorySummarizer(loop, observer, definition)
    summary = await summarizer.summarize((SessionHistoryTurn("old", request().messages),))
    assert summary == "answer"
    main_result = await loop.run(definition, RunContext("main", request().messages))
    assert main_result.output == "answer"
    assert provider.calls == 2
    assert (await ledger.snapshot()).known_usage.total_tokens == 20
    assert len(await observer.reports()) == 1  # Report observer and admission ledger are distinct.


@pytest.mark.asyncio
async def test_cancel_before_call_and_early_close_do_not_refund_started_work():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=100))
    provider = Provider()
    wrapper = SharedBudgetModelProvider(provider, ledger, Meter())
    token = CancellationToken()
    token.cancel()
    with pytest.raises(asyncio.CancelledError):
        await collect_stream(wrapper.stream(request(), cancellation=token))
    assert provider.calls == 0 and not (await ledger.snapshot()).entries
    stream = wrapper.stream(request())
    await anext(stream)
    await stream.aclose()
    assert (await ledger.snapshot()).blocked
    assert (await ledger.snapshot()).held_usage.total_tokens == 15


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", [None, True])
async def test_missing_or_invalid_output_cap_rejected_before_meter(cap):
    class ForbiddenMeter(Meter):
        async def bound(self, request):
            pytest.fail("invalid output cap reached estimator")

    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=100))
    provider = Provider()
    wrapper = SharedBudgetModelProvider(provider, ledger, ForbiddenMeter())
    with pytest.raises(SharedBudgetError):
        await collect_stream(wrapper.stream(replace(request(), max_output_tokens=cap)))
    assert provider.calls == 0 and not (await ledger.snapshot()).entries


@pytest.mark.parametrize("kwargs", [{}, {"max_total_tokens": True}, {"max_input_tokens": -1},
    {"max_cost": "NaN", "currency": "USD", "price_table_version": "v1"},
    {"max_cost": 1}, {"max_total_tokens": 10, "currency": "USD"}])
def test_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        SharedBudgetLimits(**kwargs)
