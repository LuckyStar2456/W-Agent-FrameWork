"""Shared-budget Runtime wiring source; execution requires user authorization."""

from dataclasses import replace

import pytest

from w_agent import (
    AgentSessionHistorySummarizer, AsyncSummarizedSessionHistoryPolicy,
    BlockEnd, BlockStart, FinishEvent, FinishReason, InMemorySessionSummaryObserver,
    InMemorySharedBudget, LocalRuntimeConfigError, LocalSharedBudgetBinding,
    LocalSharedBudgetConfig, ModelCapability, ModelDescriptor, ModelError,
    ModelFailure, ModelFailureKind, NativeCursorRecovery, ProviderTemplate,
    ProviderTemplateRegistry, SharedBudgetAmount, SharedBudgetError, SharedBudgetLimits,
    SharedBudgetModelProvider, SQLiteSharedBudget, StopReason, TextContent, TokenUsage,
    UsageEvent, assemble_local_provider, assemble_local_runtime, local_runtime_config_from_mapping,
)


class Meter:
    def __init__(self):
        self.bound_calls = self.actual_calls = self.close_calls = 0

    async def bound(self, request):
        self.bound_calls += 1
        # This bound belongs to the deterministic test fixture, not real text.
        return SharedBudgetAmount(TokenUsage(10, request.max_output_tokens))

    async def actual(self, request, usage):
        self.actual_calls += 1
        return SharedBudgetAmount(usage)

    async def aclose(self):
        self.close_calls += 1


class Ledger(InMemorySharedBudget):
    def __init__(self, total=100):
        super().__init__(SharedBudgetLimits(max_total_tokens=total))
        self.initialize_calls = self.close_calls = self.snapshot_calls = 0

    async def initialize(self):
        self.initialize_calls += 1

    async def aclose(self):
        self.close_calls += 1

    async def snapshot(self):
        self.snapshot_calls += 1
        return await super().snapshot()


class Provider:
    def __init__(self, name, model, *, failure=False):
        self.name, self.model, self.failure = name, model, failure
        self.calls = self.close_calls = 0

    async def list_models(self):
        return (await self.resolve(self.model),)

    async def resolve(self, model):
        return ModelDescriptor(self.name, self.model, frozenset({
            ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT,
        }))

    async def stream(self, request, *, cancellation=None):
        self.calls += 1
        if self.failure:
            raise ModelError(ModelFailure(ModelFailureKind.NETWORK, "offline", "PRIVATE_ERROR", True))
        yield BlockStart(0, "text")
        yield BlockEnd(0, TextContent("answer"))
        yield UsageEvent(TokenUsage(8, 2))
        yield FinishEvent(FinishReason.STOP)

    async def aclose(self):
        self.close_calls += 1


def templates(created, *, failure=False):
    def build(**options):
        result = Provider(options["name"], options["default_model"], failure=failure)
        created.append(result)
        return result

    return ProviderTemplateRegistry((ProviderTemplate("fake", "Fake", "test", None, build),))


def mapping():
    return {
        "provider": {"template": "fake", "model": "model", "name": "provider"},
        "agent": {"max_steps": 1, "max_tool_calls": 0, "max_output_tokens": 5, "max_total_tokens": 100},
        "invocation": {"max_attempts_per_route": 3},
        "shared_budget": {"binding": "development"},
    }


def config():
    return local_runtime_config_from_mapping(mapping())


@pytest.mark.parametrize("selection", [{}, "development", [], {"binding": True}, {"binding": ""},
    {"binding": "../file"}, {"binding": "x", "path": "budget.db"},
    {"binding": "x", "meter_import": "application.Meter"}, {"binding": "x", "max_cost": "100"}])
def test_json_selection_is_only_a_bounded_host_reference(selection):
    data = mapping()
    data["shared_budget"] = selection
    with pytest.raises(LocalRuntimeConfigError):
        local_runtime_config_from_mapping(data)


@pytest.mark.parametrize("cap", [None, True, 0, -1, "5"])
def test_selected_budget_requires_explicit_strict_output_cap(cap):
    data = mapping()
    data["agent"]["max_output_tokens"] = cap
    with pytest.raises(LocalRuntimeConfigError):
        local_runtime_config_from_mapping(data)


def test_missing_binding_and_native_recovery_fail_before_provider_construction(tmp_path):
    created = []
    for catalog in (None, {}, {"development": object()}):
        with pytest.raises(LocalRuntimeConfigError, match="binding"):
            assemble_local_runtime(config(), tmp_path, templates=templates(created), shared_budget_bindings=catalog)
    binding = LocalSharedBudgetBinding(Ledger(), Meter())
    with pytest.raises(LocalRuntimeConfigError, match="native cursor"):
        assemble_local_runtime(config(), tmp_path, templates=templates(created),
                               shared_budget_bindings={"development": binding},
                               stream_recovery=NativeCursorRecovery(max_resumes=1))
    assert created == []


@pytest.mark.asyncio
async def test_provider_assembly_wraps_without_budget_io_and_retains_client_ownership():
    created, ledger, meter = [], Ledger(), Meter()
    binding = LocalSharedBudgetBinding(ledger, meter)
    assembly = assemble_local_provider(config(), templates=templates(created),
                                       shared_budget_bindings={"development": binding})
    assert isinstance(assembly.provider, SharedBudgetModelProvider)
    assert assembly.provider.provider is created[0] and assembly.shared_budget is binding
    assert ledger.initialize_calls == ledger.snapshot_calls == meter.bound_calls == meter.actual_calls == 0
    assert created[0].calls == 0
    async with assembly:
        assert len(await assembly.provider.list_models()) == 1
    await assembly.aclose()
    assert created[0].close_calls == 1 and ledger.close_calls == meter.close_calls == 0
    with pytest.raises(RuntimeError, match="closed"):
        async with assembly:
            pass


@pytest.mark.asyncio
async def test_multiple_runtime_runs_share_budget_without_changing_per_run_totals(tmp_path):
    created, ledger, meter = [], Ledger(25), Meter()
    binding = LocalSharedBudgetBinding(ledger, meter)
    runtime = assemble_local_runtime(config(), tmp_path, templates=templates(created),
                                     shared_budget_bindings={"development": binding})
    try:
        assert runtime.shared_budget is binding
        first = await runtime.run("first")
        second = await runtime.run("second", session_id=first.session.session_id)
        rejected = await runtime.run("third", session_id=first.session.session_id)
        assert first.result.stop_reason == second.result.stop_reason == StopReason.COMPLETED
        assert first.result.usage.total_tokens == second.result.usage.total_tokens == 10
        assert rejected.result.stop_reason == StopReason.MODEL_ERROR
        view = await runtime.shared_budget_snapshot()
        assert view.known_usage.total_tokens == 20 and view.held_usage.total_tokens == 0
        assert len(view.entries) == 2 and created[0].calls == 2
    finally:
        await runtime.aclose()
        await runtime.aclose()
    assert created[0].close_calls == 1 and ledger.close_calls == meter.close_calls == 0
    with pytest.raises(RuntimeError, match="closed"):
        await runtime.shared_budget_snapshot()


@pytest.mark.asyncio
async def test_summary_history_and_main_runtime_share_pool_via_named_bindings(tmp_path):
    created, ledger = [], Ledger(35)
    catalog = {"development": LocalSharedBudgetBinding(ledger, Meter())}
    summary = assemble_local_runtime(config(), tmp_path / "summary", templates=templates(created),
                                     shared_budget_bindings=catalog)
    main = assemble_local_runtime(config(), tmp_path / "main", templates=templates(created),
                                  shared_budget_bindings=catalog)
    observer = InMemorySessionSummaryObserver()
    history = AsyncSummarizedSessionHistoryPolicy(
        AgentSessionHistorySummarizer(summary.loop, observer, summary.definition), recent_turns=0,
    )
    try:
        first = await main.run("earlier")
        result = await main.run("next", session_id=first.session.session_id, history_policy=history)
        assert result.result.stop_reason == StopReason.COMPLETED
        assert result.result.usage.total_tokens == 10  # Summary remains a distinct Run.
        reports = await observer.reports()
        assert len(reports) == 1 and reports[0].usage.total_tokens == 10
        assert (await main.shared_budget_snapshot()).known_usage.total_tokens == 30
        assert [provider.calls for provider in created] == [1, 2]
        refused = await main.run("again", include_history=False)
        assert refused.result.stop_reason == StopReason.MODEL_ERROR
        assert created[1].calls == 2
    finally:
        await main.aclose()
        await summary.aclose()
    assert [provider.close_calls for provider in created] == [1, 1]


@pytest.mark.asyncio
async def test_unknown_call_cannot_retry_or_fall_back_to_unwrapped_provider(tmp_path):
    created, ledger = [], Ledger()
    runtime = assemble_local_runtime(config(), tmp_path, templates=templates(created, failure=True),
                                     shared_budget_bindings={"development": LocalSharedBudgetBinding(ledger, Meter())})
    try:
        first, second = await runtime.run("one"), await runtime.run("two")
        assert first.result.stop_reason == second.result.stop_reason == StopReason.MODEL_ERROR
        assert created[0].calls == 1  # Configured max_attempts_per_route=3 cannot retry unknown billing.
        view = await runtime.shared_budget_snapshot()
        assert view.blocked and view.held_usage.total_tokens == 15 and len(view.entries) == 1
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_sqlite_binding_never_auto_initializes_and_reopening_keeps_pool(tmp_path):
    path = tmp_path / "budget.db"
    limits = SharedBudgetLimits(max_total_tokens=25)
    created = []
    for index in range(2):
        ledger = SQLiteSharedBudget(path, "local", limits)
        runtime = assemble_local_runtime(config(), tmp_path / str(index), templates=templates(created),
                                         shared_budget_bindings={"development": LocalSharedBudgetBinding(ledger, Meter())})
        try:
            if index == 0:
                assert not path.exists()
                with pytest.raises(SharedBudgetError):
                    await runtime.shared_budget_snapshot()
                assert (await runtime.run("before init")).result.stop_reason == StopReason.MODEL_ERROR
                assert not path.exists() and created[-1].calls == 0
                await ledger.initialize()
            assert (await runtime.run("authorized")).result.stop_reason == StopReason.COMPLETED
            assert (await runtime.shared_budget_snapshot()).known_usage.total_tokens == (index + 1) * 10
        finally:
            await runtime.aclose()


@pytest.mark.asyncio
async def test_no_selection_means_no_implicit_budget_and_raw_provider_compatibility(tmp_path):
    created, ledger = [], Ledger()
    data = mapping()
    data.pop("shared_budget")
    data["agent"].pop("max_output_tokens")
    runtime = assemble_local_runtime(local_runtime_config_from_mapping(data), tmp_path,
                                     templates=templates(created),
                                     shared_budget_bindings={"development": LocalSharedBudgetBinding(ledger, Meter())})
    try:
        assert runtime.models.provider("provider") is created[0]
        assert runtime.shared_budget is None and await runtime.shared_budget_snapshot() is None
        assert (await runtime.run("unbudgeted")).result.stop_reason == StopReason.COMPLETED
        assert ledger.snapshot_calls == 0 and (await ledger.snapshot()).entries == ()
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_owned_original_closed_even_when_registry_replaces_its_wrapper(tmp_path):
    created, ledger = [], Ledger()
    runtime = assemble_local_runtime(config(), tmp_path, templates=templates(created),
                                     shared_budget_bindings={"development": LocalSharedBudgetBinding(ledger, Meter())})
    replacement = Provider("provider", "model")
    runtime.models.register("provider", replacement, version="1")
    runtime.models.register("alias", replacement)
    await runtime.aclose()
    await runtime.aclose()
    assert created[0].close_calls == replacement.close_calls == 1


@pytest.mark.asyncio
async def test_snapshot_capability_is_optional_and_errors_never_echo_host_body():
    class Controller:
        async def reserve(self, amount):
            raise NotImplementedError

        async def settle(self, reservation, actual):
            raise NotImplementedError

        async def release(self, reservation):
            raise NotImplementedError

    binding = LocalSharedBudgetBinding(Controller(), Meter())
    with pytest.raises(SharedBudgetError, match="inspect its ledger"):
        await binding.snapshot()

    class BadSnapshot(Controller):
        async def snapshot(self):
            raise RuntimeError("PRIVATE_BODY")

    with pytest.raises(SharedBudgetError) as caught:
        await LocalSharedBudgetBinding(BadSnapshot(), Meter()).snapshot()
    assert "PRIVATE_BODY" not in str(caught.value)


def test_binding_types_and_typed_selection_are_validated():
    with pytest.raises(LocalRuntimeConfigError):
        LocalSharedBudgetBinding(object(), Meter())
    with pytest.raises(LocalRuntimeConfigError):
        LocalSharedBudgetBinding(Ledger(), object())
    with pytest.raises(LocalRuntimeConfigError):
        replace(config(), shared_budget={"binding": "development"})
    assert config().shared_budget == LocalSharedBudgetConfig("development")
