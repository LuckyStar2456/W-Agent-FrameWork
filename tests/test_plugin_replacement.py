"""Offline replacement lifecycle acceptance; no package imports or installation."""

import asyncio
from dataclasses import replace

import pytest

from w_agent.kernel.plugins import (
    CapabilityDeclaration, CapabilityRequirement, FunctionPlugin, PluginManager,
    PluginReplacementError, PluginSpec, PluginState,
)
from w_agent.kernel.exceptions import PluginDependencyError, PluginLoadError, PluginUnloadError
from w_agent.kernel.registry import Contribution
from w_agent.kernel.scope import ScopePath


def provider(version="1", *, fail=False, cleanup=None, requires=()):
    async def setup(context):
        context.register("service", version, version=version)
        if cleanup:
            context.effect(cleanup)
        if fail:
            raise RuntimeError("setup failed")
    return FunctionPlugin(PluginSpec(
        "provider", version,
        provides=(CapabilityDeclaration("service", version=version),),
        requires=requires,
    ), setup)


@pytest.mark.asyncio
async def test_replacement_preserves_old_handle_identity_and_stops_consumers():
    manager = PluginManager()
    old = await manager.load(provider())
    consumer = await manager.load(FunctionPlugin(PluginSpec(
        "consumer", "1", requires=(CapabilityRequirement("service"),),
        provides=(CapabilityDeclaration("consumer"),),
    ), lambda context: context.register("consumer", object()) and None))
    leaf = await manager.load(FunctionPlugin(PluginSpec(
        "leaf", "1", requires=(CapabilityRequirement("consumer"),),
    ), lambda _: None))
    plan = await manager.plan_replacement(provider("2"))
    assert plan.unload_order == ("leaf", "consumer", "provider")
    assert (plan.previous.version, plan.replacement.version) == ("1", "2")
    new = await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True)
    assert new.state == PluginState.ACTIVE
    assert old.state == consumer.state == leaf.state == PluginState.DISPOSED
    assert manager.registry.resolve("service", ScopePath.application()) == "2"
    with pytest.raises(PluginUnloadError, match="stale"):
        await old.unload()
    assert new.state == PluginState.ACTIVE
    await new.unload()


@pytest.mark.asyncio
@pytest.mark.parametrize("quiescent", [False, None, 1, "yes"])
async def test_quiescence_is_explicit_boolean(quiescent):
    manager = PluginManager()
    old = await manager.load(provider())
    plan = await manager.plan_replacement(provider("2"))
    with pytest.raises(PluginReplacementError, match="quiescence"):
        await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=quiescent)
    assert old.state == PluginState.ACTIVE


@pytest.mark.asyncio
async def test_exact_plan_one_shot_and_latest_preview_only():
    manager = PluginManager()
    await manager.load(provider())
    stale = await manager.plan_replacement(provider("2"))
    plan = await manager.plan_replacement(provider("3"))
    for candidate, token in [(stale, stale.plan_id), (replace(plan), plan.plan_id), (plan, "bad")]:
        with pytest.raises(PluginReplacementError, match="plan"):
            await manager.replace(candidate, expected_plan_id=token, host_quiescent=True)
    await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True)
    with pytest.raises(PluginReplacementError, match="plan"):
        await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True)


@pytest.mark.asyncio
async def test_registry_drift_rejected_before_unload():
    manager = PluginManager()
    old = await manager.load(provider())
    plan = await manager.plan_replacement(provider("2"))
    manager.registry.register(Contribution("unrelated", object()))
    with pytest.raises(PluginReplacementError, match="changed"):
        await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True)
    assert old.state == PluginState.ACTIVE


@pytest.mark.asyncio
async def test_candidate_spec_drift_rejected():
    manager = PluginManager()
    old = await manager.load(provider())
    candidate = provider("2")
    plan = await manager.plan_replacement(candidate)
    candidate.spec = replace(candidate.spec, version="3")
    with pytest.raises(PluginReplacementError, match="changed"):
        await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True)
    assert old.state == PluginState.ACTIVE


@pytest.mark.asyncio
async def test_missing_post_unload_dependency_fails_during_preview():
    manager = PluginManager()
    old = await manager.load(provider())
    with pytest.raises(PluginDependencyError):
        await manager.plan_replacement(provider("2", requires=(CapabilityRequirement("service"),)))
    assert old.state == PluginState.ACTIVE


@pytest.mark.asyncio
async def test_fresh_instance_required():
    manager = PluginManager()
    instance = provider()
    await manager.load(instance)
    with pytest.raises(PluginReplacementError, match="fresh"):
        await manager.plan_replacement(instance)


@pytest.mark.asyncio
async def test_cleanup_failure_never_loads_replacement():
    def fail():
        raise RuntimeError("cleanup failed")
    manager = PluginManager()
    old = await manager.load(provider(cleanup=fail))
    plan = await manager.plan_replacement(provider("2"))
    with pytest.raises(PluginUnloadError):
        await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True)
    assert old.state == PluginState.DISPOSED
    assert manager.record("provider").spec.version == "1"
    assert not manager.registry.list("service", ScopePath.application())


@pytest.mark.asyncio
async def test_setup_failure_cleans_new_effects_without_restarting_old():
    cleaned = []
    manager = PluginManager()
    old = await manager.load(provider())
    plan = await manager.plan_replacement(provider("2", fail=True, cleanup=lambda: cleaned.append(1)))
    with pytest.raises(PluginLoadError):
        await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True)
    assert old.state == PluginState.DISPOSED
    assert manager.record("provider").state == PluginState.FAILED
    assert cleaned == [1]
    assert not manager.registry.list("service", ScopePath.application())


@pytest.mark.asyncio
async def test_cancelled_new_setup_cleans_effects_and_consumes_plan():
    entered = asyncio.Event()
    manager = PluginManager()
    await manager.load(provider())
    async def setup(context):
        context.register("temporary", object())
        entered.set()
        await asyncio.Event().wait()
    candidate = FunctionPlugin(PluginSpec("provider", "2"), setup)
    plan = await manager.plan_replacement(candidate)
    task = asyncio.create_task(manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert manager.record("provider").state == PluginState.FAILED
    assert not manager.registry.list("temporary", ScopePath.application())
    with pytest.raises(PluginReplacementError):
        await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True)


@pytest.mark.asyncio
async def test_unrelated_plugin_retained_and_config_passed_explicitly():
    manager = PluginManager()
    await manager.load(provider())
    other = await manager.load(FunctionPlugin(PluginSpec("other", "1"), lambda _: None))
    observed = []
    candidate = FunctionPlugin(PluginSpec("provider", "2"), lambda ctx: observed.append(ctx.config["key"]))
    plan = await manager.plan_replacement(candidate)
    await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True, config={"key": "value"})
    assert observed == ["value"]
    assert other.state == PluginState.ACTIVE


@pytest.mark.asyncio
async def test_preview_never_executes_new_code_and_incompatible_api_preserves_old():
    manager = PluginManager()
    old = await manager.load(provider())
    ran = []
    candidate = FunctionPlugin(PluginSpec("provider", "2", api_version="99"), lambda _: ran.append(1))
    with pytest.raises(PluginDependencyError):
        await manager.plan_replacement(candidate)
    assert not ran
    assert old.state == PluginState.ACTIVE


@pytest.mark.asyncio
async def test_new_capability_cannot_break_existing_plugin_conflict():
    manager = PluginManager()
    old = await manager.load(provider())
    await manager.load(FunctionPlugin(PluginSpec("other", "1", conflicts=("new",)), lambda _: None))
    candidate = FunctionPlugin(PluginSpec(
        "provider", "2", provides=(CapabilityDeclaration("new"),),
    ), lambda _: None)
    with pytest.raises(PluginDependencyError):
        await manager.plan_replacement(candidate)
    assert old.state == PluginState.ACTIVE


@pytest.mark.asyncio
async def test_consumer_cleanup_failure_stops_before_provider_replacement():
    manager = PluginManager()
    old = await manager.load(provider())
    def fail():
        raise RuntimeError("consumer cleanup failed")
    await manager.load(FunctionPlugin(PluginSpec(
        "consumer", "1", requires=(CapabilityRequirement("service"),),
    ), lambda _: fail))
    plan = await manager.plan_replacement(provider("2"))
    with pytest.raises(PluginUnloadError):
        await manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True)
    assert old.state == PluginState.ACTIVE
    assert manager.record("consumer").state == PluginState.DISPOSED
