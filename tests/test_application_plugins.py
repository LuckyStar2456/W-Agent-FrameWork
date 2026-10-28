"""The application bridge uses existing plugin dependency/lifecycle behavior."""

import asyncio

import pytest

from w_agent import (
    ApplicationLifecycleError, ApplicationPlugin, ApplicationState,
    AssemblyDefinitionError, BorrowedComponent, CapabilityDeclaration,
    CapabilityExport, CapabilityImport, CapabilityNotFoundError,
    CapabilityRequirement, ComponentDefinition, ComponentRef, PluginLoadError,
    PluginManager, PluginState, PluginUnloadError, ScopePath, plugin,
)


def provider(events, value):
    @plugin(name="store-plugin", version="1", provides=(
        CapabilityDeclaration("storage", version="1"),
    ))
    async def setup(context):
        context.register("storage", value, version="1")
        return lambda: events.append("store-disposed")
    return setup


def application(events, *, initialize=None, dispose=None):
    return ApplicationPlugin(
        name="harness-plugin", version="1",
        components=[ComponentDefinition(
            "harness", lambda store: {"store": store},
            {"store": ComponentRef("store")}, initialize=initialize,
            dispose=dispose or (lambda obj: events.append("harness-disposed")),
        )],
        imports=[CapabilityImport("store", CapabilityRequirement("storage", ">=1"))],
        exports=[CapabilityExport("harness", CapabilityDeclaration("harness", version="1"))],
    )


async def test_registry_identity_and_provider_unload_disposes_consumer_first():
    events, store = [], object()
    manager = PluginManager()
    await manager.load(provider(events, store))
    app_plugin = application(events)
    handle = await manager.load(app_plugin)
    context = app_plugin.application
    harness = context.resolve("harness")
    assert harness["store"] is store
    assert manager.registry.resolve("harness", ScopePath.application()) is harness
    await manager.unload("store-plugin")
    assert events == ["harness-disposed", "store-disposed"]
    assert handle.state is PluginState.DISPOSED
    assert context.state is ApplicationState.CLOSED
    with pytest.raises(CapabilityNotFoundError):
        manager.registry.resolve("harness", ScopePath.application())
    with pytest.raises(ApplicationLifecycleError):
        app_plugin.application
    await manager.close()
    assert events == ["harness-disposed", "store-disposed"]


async def test_application_export_can_feed_another_application_plugin():
    events = []
    manager = PluginManager()
    first = ApplicationPlugin(
        name="first", version="1",
        components=[ComponentDefinition("owned", object, dispose=lambda obj: events.append("first"))],
        exports=[CapabilityExport("owned", CapabilityDeclaration("first-value", version="1"))],
    )
    second = ApplicationPlugin(
        name="second", version="1",
        imports=[CapabilityImport("borrowed", CapabilityRequirement("first-value"))],
        components=[ComponentDefinition(
            "consumer", lambda value: [value], {"value": ComponentRef("borrowed")},
            dispose=lambda obj: events.append("second"),
        )],
    )
    await manager.load(first)
    await manager.load(second)
    assert second.application.resolve("consumer")[0] is first.application.resolve("owned")
    await manager.unload("first")
    assert events == ["second", "first"]


async def test_missing_import_fails_before_factory():
    events = []
    app_plugin = application(events, initialize=lambda obj: events.append("initialized"))
    manager = PluginManager()
    with pytest.raises(PluginLoadError):
        await manager.load(app_plugin)
    assert events == []
    assert manager.record(app_plugin.spec.name).state is PluginState.FAILED


async def test_failed_initialization_rolls_back_without_closing_borrowed_provider():
    events = []

    def fail(value):
        raise ValueError("initialization")

    manager = PluginManager()
    await manager.load(provider(events, object()))
    app_plugin = application(events, initialize=fail)
    with pytest.raises(PluginLoadError):
        await manager.load(app_plugin)
    assert events == ["harness-disposed"]
    assert manager.record("store-plugin").state is PluginState.ACTIVE
    assert not manager.registry.list("harness", ScopePath.application())
    await manager.close()
    assert events == ["harness-disposed", "store-disposed"]


async def test_exports_are_withdrawn_before_object_disposal():
    events = []
    manager = PluginManager()

    def dispose(value):
        assert not manager.registry.list("harness", ScopePath.application())
        events.append("disposed")

    await manager.load(provider(events, object()))
    app_plugin = application(events, dispose=dispose)
    handle = await manager.load(app_plugin)
    await handle.unload()
    assert events == ["disposed"]
    await manager.close()


async def test_partial_export_conflict_cleans_all_registrations_and_instances():
    events = []
    manager = PluginManager()

    @plugin(name="occupied", version="1", provides=(CapabilityDeclaration("occupied"),))
    async def occupied(context):
        context.register("occupied", object(), exclusive=True)

    await manager.load(occupied)
    app_plugin = ApplicationPlugin(
        name="conflicting", version="1",
        components=[ComponentDefinition("value", object, dispose=lambda obj: events.append("disposed"))],
        exports=[
            CapabilityExport("value", CapabilityDeclaration("first")),
            CapabilityExport("value", CapabilityDeclaration("occupied", exclusive=True)),
        ],
    )
    with pytest.raises(PluginLoadError):
        await manager.load(app_plugin)
    assert events == ["disposed"]
    assert not manager.registry.list("first", ScopePath.application())
    assert manager.record("occupied").state is PluginState.ACTIVE
    await manager.close()


async def test_cancelled_load_waits_for_application_rollback():
    entered = asyncio.Event()
    events = []

    async def initialize(value):
        entered.set()
        await asyncio.Event().wait()

    manager = PluginManager()
    await manager.load(provider(events, object()))
    loading = asyncio.create_task(manager.load(application(events, initialize=initialize)))
    await asyncio.wait_for(entered.wait(), 2)
    loading.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(loading, 2)
    assert events == ["harness-disposed"]
    assert manager.record("harness-plugin").state is PluginState.FAILED
    await manager.close()
    assert events == ["harness-disposed", "store-disposed"]


async def test_disposer_cancellation_does_not_strand_plugin_state():
    events = []

    async def dispose(value):
        events.append("harness-disposed")
        raise asyncio.CancelledError()

    manager = PluginManager()
    await manager.load(provider(events, object()))
    app_plugin = application(events, dispose=dispose)
    handle = await manager.load(app_plugin)
    context = app_plugin.application
    with pytest.raises(asyncio.CancelledError):
        await handle.unload()
    assert handle.state is PluginState.DISPOSED
    assert context.state is ApplicationState.CLOSED
    assert not manager.registry.list("harness", ScopePath.application())
    await manager.close()
    assert events == ["harness-disposed", "store-disposed"]


async def test_cleanup_failure_does_not_unload_provider_in_same_attempt():
    events = []

    def fail(value):
        events.append("harness-disposed")
        raise ValueError("dispose")

    manager = PluginManager()
    await manager.load(provider(events, object()))
    await manager.load(application(events, dispose=fail))
    with pytest.raises(PluginUnloadError):
        await manager.unload("store-plugin")
    assert manager.record("store-plugin").state is PluginState.ACTIVE
    assert events == ["harness-disposed"]
    await manager.close()
    assert events == ["harness-disposed", "store-disposed"]


async def test_configuration_is_rejected_instead_of_ignored():
    manager = PluginManager()
    app_plugin = ApplicationPlugin(name="plain", version="1", components=[])
    with pytest.raises(PluginLoadError):
        await manager.load(app_plugin, config={"unknown": "secret"})
    assert manager.record("plain").state is PluginState.FAILED


@pytest.mark.parametrize("component", ["missing", "run-value"])
def test_exports_require_known_application_scope(component):
    with pytest.raises(AssemblyDefinitionError):
        ApplicationPlugin(
            name="bad", version="1",
            components=[ComponentDefinition("run-value", object, scope="run")],
            exports=[CapabilityExport(component, CapabilityDeclaration("value"))],
        )


def test_import_identity_cannot_shadow_a_local_definition():
    with pytest.raises(AssemblyDefinitionError, match="duplicate"):
        ApplicationPlugin(
            name="bad", version="1", components=[BorrowedComponent("store", object())],
            imports=[CapabilityImport("store", CapabilityRequirement("storage"))],
        )


async def test_reuse_in_another_manager_cannot_close_original_application():
    events = []
    first, second = PluginManager(), PluginManager()
    app_plugin = ApplicationPlugin(
        name="one-owner", version="1",
        components=[ComponentDefinition("value", object, dispose=lambda obj: events.append("closed"))],
        exports=[CapabilityExport("value", CapabilityDeclaration("value"))],
    )
    await first.load(app_plugin)
    original = app_plugin.application.resolve("value")
    with pytest.raises(PluginLoadError):
        await second.load(app_plugin)
    assert app_plugin.application.resolve("value") is original
    assert first.registry.resolve("value", ScopePath.application()) is original
    assert events == []
    await second.close()
    await first.close()
    assert events == ["closed"]


async def test_borrowed_export_does_not_transfer_ownership():
    class External:
        def close(self):
            raise AssertionError("borrowed value must not be closed")

    value = External()
    manager = PluginManager()
    await manager.load(ApplicationPlugin(
        name="borrower", version="1", components=[BorrowedComponent("external", value)],
        exports=[CapabilityExport("external", CapabilityDeclaration("external"))],
    ))
    assert manager.registry.resolve("external", ScopePath.application()) is value
    await manager.close()


async def test_m1_custom_harness_uses_legacy_registry_configuration_and_run_scope():
    from w_agent import (
        BeanFactory, ConfigurationField, ConfigurationSchema, borrow_legacy_singletons,
    )

    events, store = [], []
    legacy = BeanFactory()
    legacy.register_bean("store", store)
    manager = PluginManager()
    storage = ApplicationPlugin(
        name="storage", version="1",
        components=borrow_legacy_singletons(legacy, {"store": "store"}),
        exports=[CapabilityExport("store", CapabilityDeclaration("storage"))],
    )

    class Harness:
        def __init__(self, store, dialect):
            self.store, self.dialect = store, dialect

        async def run(self, text):
            self.store.append(f"{self.dialect}:{text.upper()}")
            return self.store[-1]

    custom = ApplicationPlugin(
        name="custom", version="1",
        imports=[CapabilityImport("store", CapabilityRequirement("storage"))],
        components=[ComponentDefinition(
            "harness", Harness, {"store": ComponentRef("store")}, {"dialect": "CUSTOM"},
            scope="run", validate_arguments=ConfigurationSchema({"dialect": ConfigurationField(str)}),
            dispose=lambda value: events.append("run-disposed"),
        )],
    )
    await manager.load(storage)
    await manager.load(custom)
    async with custom.application.scope("run", "one") as run:
        assert await run.resolve("harness").run("hello") == "CUSTOM:HELLO"
    await manager.close()
    assert events == ["run-disposed"]
    assert legacy.existing_singleton("store") is store
    assert store == ["CUSTOM:HELLO"]
