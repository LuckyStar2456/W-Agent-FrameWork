"""Cancellation must propagate only after owned lifecycle cleanup settles."""

import asyncio
import sys
import types

import pytest

from w_agent.kernel.loading import PluginReference, load_plugin_references
from w_agent.kernel.plugins import (
    CapabilityDeclaration, CapabilityRequirement, EffectScope, FunctionPlugin,
    PluginManager, PluginSpec, PluginState,
)
from w_agent.kernel.scope import ScopePath


class ControlledPlugin:
    def __init__(self, name="controlled", *, blocked=None, raises=None):
        self.spec = PluginSpec(name, "1", provides=(CapabilityDeclaration(name),))
        self.blocked, self.raises = blocked, raises
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.calls = []

    async def step(self, name):
        self.calls.append(name)
        if self.blocked == name:
            self.entered.set()
            await self.release.wait()
        if self.raises == name:
            raise asyncio.CancelledError("plugin requested cancellation")

    async def load(self, context):
        context.register(self.spec.name, self)
        context.on("test", lambda _: None)
        context.effect(lambda: self.calls.append("last-effect"))
        context.effect(lambda: self.step("effect"))
        await self.step("load")

    async def quiesce(self):
        await self.step("quiesce")

    async def unload(self):
        await self.step("unload")


async def cancel_repeatedly(task, entered, release):
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel("first external cancellation")
    await asyncio.sleep(0)
    task.cancel("second external cancellation")
    await asyncio.sleep(0)
    assert not task.done(), "cleanup must be drained, not detached"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)


def assert_clean(manager, plugin, state=PluginState.DISPOSED):
    assert manager.record(plugin.spec.name).state == state
    assert not manager.registry.list(plugin.spec.name, ScopePath.application())
    assert not manager.events.listeners("test")
    assert plugin.calls.count("unload") == 1
    assert plugin.calls.count("effect") == 1
    assert plugin.calls.count("last-effect") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["quiesce", "unload", "effect"])
async def test_repeated_external_cancel_during_unload_drains_every_effect(phase):
    manager = PluginManager()
    plugin = ControlledPlugin(blocked=phase)
    await manager.load(plugin)
    task = asyncio.create_task(manager.unload(plugin.spec.name))
    await cancel_repeatedly(task, plugin.entered, plugin.release)
    assert_clean(manager, plugin)
    await manager.close()
    assert_clean(manager, plugin)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["quiesce", "unload", "effect"])
async def test_callback_cancel_still_disposes_record_and_remaining_effects(phase):
    manager = PluginManager()
    plugin = ControlledPlugin(raises=phase)
    await manager.load(plugin)
    with pytest.raises(asyncio.CancelledError):
        await manager.unload(plugin.spec.name)
    assert_clean(manager, plugin)
    await manager.close()


@pytest.mark.asyncio
async def test_repeated_cancel_during_partial_load_cleanup_marks_failed():
    manager = PluginManager()
    plugin = ControlledPlugin(blocked="unload", raises="load")
    task = asyncio.create_task(manager.load(plugin))
    await cancel_repeatedly(task, plugin.entered, plugin.release)
    assert_clean(manager, plugin, PluginState.FAILED)


@pytest.mark.asyncio
async def test_cancel_batch_rolls_back_previous_handles_and_preserves_unrelated(monkeypatch):
    manager = PluginManager()
    unrelated = await manager.load(FunctionPlugin(PluginSpec("unrelated", "1"), lambda _: None))
    first = ControlledPlugin("first", blocked="unload")
    second = ControlledPlugin("second", blocked="load")
    module = types.ModuleType("cancellation_batch_fixture")
    module.first, module.second = first, second
    monkeypatch.setitem(sys.modules, module.__name__, module)
    task = asyncio.create_task(load_plugin_references(manager, (
        PluginReference(f"{module.__name__}:first"), PluginReference(f"{module.__name__}:second"))))
    await second.entered.wait()
    task.cancel()
    await first.entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    first.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert manager.record("first").state == PluginState.DISPOSED
    assert manager.record("second").state == PluginState.FAILED
    assert not manager.registry.list("first", ScopePath.application())
    assert not manager.registry.list("second", ScopePath.application())
    assert not manager.events.listeners("test")
    assert unrelated.state == PluginState.ACTIVE
    await manager.close()


@pytest.mark.asyncio
async def test_manager_close_cancel_drains_all_plugins():
    manager = PluginManager()
    first, second = ControlledPlugin("first"), ControlledPlugin("second", blocked="effect")
    await manager.load(first)
    await manager.load(second)
    task = asyncio.create_task(manager.close())
    await cancel_repeatedly(task, second.entered, second.release)
    assert_clean(manager, first)
    assert_clean(manager, second)


@pytest.mark.asyncio
async def test_manager_close_internal_cancel_does_not_abandon_other_plugins():
    manager = PluginManager()
    first, second = ControlledPlugin("first"), ControlledPlugin("second", raises="unload")
    await manager.load(first)
    await manager.load(second)
    with pytest.raises(asyncio.CancelledError):
        await manager.close()
    assert_clean(manager, first)
    assert_clean(manager, second)


@pytest.mark.asyncio
async def test_replacement_cancel_during_old_cleanup_never_starts_candidate():
    manager = PluginManager()
    old = ControlledPlugin(blocked="effect")
    await manager.load(old)
    called = []
    candidate = FunctionPlugin(PluginSpec(old.spec.name, "2"), lambda _: called.append("new"))
    plan = await manager.plan_replacement(candidate)
    task = asyncio.create_task(manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True))
    await cancel_repeatedly(task, old.entered, old.release)
    assert_clean(manager, old)
    assert called == []
    assert manager.record(old.spec.name).spec.version == "1"


@pytest.mark.asyncio
async def test_effect_scope_concurrent_close_waits_for_same_cleanup():
    scope = EffectScope()
    entered, release, finished = asyncio.Event(), asyncio.Event(), []
    async def cleanup():
        entered.set()
        await release.wait()
        await scope.close()  # Reentrant idempotent close must not self-await.
        finished.append(True)
    scope.add(cleanup)
    first = asyncio.create_task(scope.close())
    await entered.wait()
    second = asyncio.create_task(scope.close())
    first.cancel()
    await asyncio.sleep(0)
    assert not first.done() and not second.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    assert finished == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("replace", [False, True])
async def test_cancelled_loaded_notification_does_not_orphan_successful_record(replace):
    manager = PluginManager()
    old = ControlledPlugin()
    if replace:
        await manager.load(old)
    entered = asyncio.Event()
    async def notice(record):
        entered.set()
        await asyncio.Event().wait()
    manager.events.on("plugin/loaded", notice)
    if replace:
        candidate = ControlledPlugin()
        candidate.spec = PluginSpec(candidate.spec.name, "2", provides=candidate.spec.provides)
        plan = await manager.plan_replacement(candidate)
        operation = manager.replace(plan, expected_plan_id=plan.plan_id, host_quiescent=True)
    else:
        candidate = old
        operation = manager.load(candidate)
    task = asyncio.create_task(operation)
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert_clean(manager, candidate)


@pytest.mark.asyncio
async def test_dependent_cleanup_cancel_then_manager_close_converges():
    manager = PluginManager()
    provider = ControlledPlugin("provider")
    consumer = ControlledPlugin("consumer", raises="effect")
    consumer.spec = PluginSpec("consumer", "1", provides=consumer.spec.provides,
                               requires=(CapabilityRequirement("provider"),))
    await manager.load(provider)
    await manager.load(consumer)
    with pytest.raises(asyncio.CancelledError):
        await manager.unload("provider")
    assert manager.record("consumer").state == PluginState.DISPOSED
    assert manager.record("provider").state == PluginState.ACTIVE
    await manager.close()
    assert_clean(manager, provider)
    assert_clean(manager, consumer)


@pytest.mark.asyncio
async def test_external_cancellation_wins_over_cleanup_error_after_drain():
    scope = EffectScope()
    entered, release, disposed = asyncio.Event(), asyncio.Event(), []
    async def fail():
        entered.set()
        await release.wait()
        raise RuntimeError("cleanup failed")
    scope.add(lambda: disposed.append(True))
    scope.add(fail)
    task = asyncio.create_task(scope.close())
    await cancel_repeatedly(task, entered, release)
    assert disposed == [True]


@pytest.mark.asyncio
async def test_failure_rollback_cancel_is_not_replaced_by_plugin_load_error():
    class FailedSetup(ControlledPlugin):
        async def load(self, context):
            await super().load(context)
            raise RuntimeError("setup failed")
    manager = PluginManager()
    plugin = FailedSetup(blocked="unload")
    task = asyncio.create_task(manager.load(plugin))
    await cancel_repeatedly(task, plugin.entered, plugin.release)
    assert_clean(manager, plugin, PluginState.FAILED)
