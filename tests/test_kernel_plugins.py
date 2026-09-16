import pytest

from w_agent import (
    CapabilityDeclaration,
    CapabilityRequirement,
    PluginLoadError,
    PluginManager,
    PluginSpec,
    PluginState,
    ScopePath,
    plugin,
)


@pytest.mark.asyncio
async def test_plugin_load_dependency_and_cascading_unload():
    lifecycle = []

    @plugin(
        name="provider",
        version="1.0.0",
        provides=(CapabilityDeclaration("greeting", version="1.0.0"),),
    )
    async def provider(context):
        context.register("greeting", "hello", version="1.0.0")
        lifecycle.append("provider:load")
        return lambda: lifecycle.append("provider:dispose")

    @plugin(
        name="consumer",
        version="1.0.0",
        requires=(CapabilityRequirement("greeting", version=">=1"),),
    )
    async def consumer(context):
        assert context.registry.resolve("greeting", context.scope) == "hello"
        lifecycle.append("consumer:load")
        return lambda: lifecycle.append("consumer:dispose")

    manager = PluginManager()
    provider_handle = await manager.load(provider)
    consumer_handle = await manager.load(consumer)

    assert provider_handle.state == PluginState.ACTIVE
    assert consumer_handle.state == PluginState.ACTIVE

    await provider_handle.unload()

    assert provider_handle.state == PluginState.DISPOSED
    assert consumer_handle.state == PluginState.DISPOSED
    assert lifecycle == [
        "provider:load",
        "consumer:load",
        "consumer:dispose",
        "provider:dispose",
    ]


@pytest.mark.asyncio
async def test_missing_dependency_fails_before_setup():
    called = False

    @plugin(
        name="consumer",
        version="1.0.0",
        requires=(CapabilityRequirement("missing"),),
    )
    async def consumer(_context):
        nonlocal called
        called = True

    manager = PluginManager()

    with pytest.raises(PluginLoadError) as error:
        await manager.load(consumer)

    assert "failed to load" in str(error.value)
    assert called is False
    assert manager.record("consumer").state == PluginState.FAILED


@pytest.mark.asyncio
async def test_failed_plugin_load_rolls_back_registrations_and_effects():
    cleanup = []

    @plugin(name="broken", version="1.0.0")
    async def broken(context):
        context.register("temporary", object())
        context.effect(lambda: cleanup.append("custom"))
        raise RuntimeError("boom")

    manager = PluginManager()

    with pytest.raises(PluginLoadError):
        await manager.load(broken)

    assert manager.registry.list("temporary", ScopePath.application()) == ()
    assert cleanup == ["custom"]


@pytest.mark.asyncio
async def test_declared_capability_must_be_registered_by_its_owner():
    @plugin(
        name="incomplete",
        version="1.0.0",
        provides=(CapabilityDeclaration("declared", version="1.0.0"),),
    )
    async def incomplete(_context):
        return None

    manager = PluginManager()

    with pytest.raises(PluginLoadError):
        await manager.load(incomplete)
    assert manager.record("incomplete").state == PluginState.FAILED


@pytest.mark.asyncio
async def test_plugin_owned_event_listener_is_removed_on_unload():
    heard = []

    @plugin(name="listener", version="1.0.0")
    async def listener(context):
        context.on("message", lambda payload: heard.append(payload))

    manager = PluginManager()
    handle = await manager.load(listener)
    await manager.events.publish("message", "before")
    await handle.unload()
    await manager.events.publish("message", "after")

    assert heard == ["before"]


@pytest.mark.asyncio
async def test_partial_custom_plugin_load_calls_unload_and_rolls_back():
    lifecycle = []

    class BrokenPlugin:
        spec = PluginSpec(name="custom-broken", version="1.0.0")

        async def load(self, context):
            context.effect(lambda: lifecycle.append("effect"))
            raise RuntimeError("load failed")

        async def unload(self):
            lifecycle.append("unload")

    manager = PluginManager()

    with pytest.raises(PluginLoadError):
        await manager.load(BrokenPlugin())

    assert lifecycle == ["unload", "effect"]


@pytest.mark.asyncio
async def test_plugin_manager_async_context_closes_active_plugins():
    cleanup = []

    @plugin(name="managed", version="1.0.0")
    async def managed(_context):
        return lambda: cleanup.append("closed")

    async with PluginManager() as manager:
        handle = await manager.load(managed)
        assert handle.state == PluginState.ACTIVE

    assert handle.state == PluginState.DISPOSED
    assert cleanup == ["closed"]
