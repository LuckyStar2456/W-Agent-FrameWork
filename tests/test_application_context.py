"""Application lifecycle cases using only in-memory user components."""

import asyncio

import pytest

from w_agent import (
    ApplicationContext,
    ApplicationLifecycleError,
    ApplicationState,
    AssemblyDefinitionError,
    BorrowedComponent,
    ComponentDefinition,
    ComponentRef,
    compile_assembly,
)


def component(name, events, *, scope="application", dependencies=None):
    def create(**kwargs):
        events.append(("create", name))
        return {"name": name, "dependencies": kwargs}

    return ComponentDefinition(
        name, create, dependencies or {}, scope=scope,
        initialize=lambda obj: events.append(("initialize", obj["name"])),
        dispose=lambda obj: events.append(("dispose", obj["name"])),
    )


def leaves(error):
    if isinstance(error, BaseExceptionGroup):
        return [leaf for item in error.exceptions for leaf in leaves(item)]
    return [error]


async def test_custom_harness_without_default_loop_provider_or_frontend():
    events = []
    store = {}

    class Harness:
        def __init__(self, store, vendor_options):
            self.store = store
            self.vendor_options = vendor_options

        async def run(self, message):
            self.store["last"] = message
            return self.vendor_options["prefix"] + message

    plan = compile_assembly([
        ComponentDefinition(
            "custom", Harness, {"store": ComponentRef("store")},
            {"vendor_options": {"prefix": "user-defined:"}},
            dispose=lambda value: events.append("closed"),
        ),
        BorrowedComponent("store", store),
    ])
    app = ApplicationContext(plan)
    async with app:
        harness = app.resolve("custom")
        assert harness.store is store
        assert await harness.run("hello") == "user-defined:hello"
    assert store == {"last": "hello"}
    assert events == ["closed"]
    assert app.state is ApplicationState.CLOSED


async def test_dependency_initialization_and_reverse_disposal():
    events = []
    app = ApplicationContext(compile_assembly([
        component("consumer", events, dependencies={"dep": ComponentRef("service")}),
        component("service", events),
    ]))
    async with app:
        assert app.resolve("consumer")["dependencies"]["dep"] is app.resolve("service")
    assert events == [
        ("create", "service"), ("initialize", "service"),
        ("create", "consumer"), ("initialize", "consumer"),
        ("dispose", "consumer"), ("dispose", "service"),
    ]


async def test_borrowed_instance_is_never_closed_or_initialized():
    class External:
        def close(self):
            raise AssertionError("closed borrowed instance")

        def post_construct(self):
            raise AssertionError("initialized borrowed instance")

    external = External()
    async with ApplicationContext(compile_assembly([
        BorrowedComponent("external", external),
    ])) as app:
        assert app.resolve("external") is external


async def test_async_factory_and_hooks():
    events = []

    async def create():
        await asyncio.sleep(0)
        return object()

    async def initialize(value):
        await asyncio.sleep(0)
        events.append("init")

    async def dispose(value):
        await asyncio.sleep(0)
        events.append("dispose")

    async with ApplicationContext(compile_assembly([
        ComponentDefinition("resource", create, initialize=initialize, dispose=dispose),
    ])):
        assert events == ["init"]
    assert events == ["init", "dispose"]


async def test_entire_plan_signatures_checked_before_any_factory():
    events = []

    def bad(required):
        raise AssertionError("factory ran")

    app = ApplicationContext(compile_assembly([
        component("first", events),
        ComponentDefinition("bad", bad, scope="run"),
    ]))
    with pytest.raises(AssemblyDefinitionError, match="signature"):
        await app.start()
    assert events == []
    assert app.state is ApplicationState.FAILED
    await app.close()


async def test_initialization_failure_disposes_partial_instance_and_dependencies():
    events = []
    failure = ValueError("init failed")

    def fail(value):
        raise failure

    app = ApplicationContext(compile_assembly([
        component("service", events),
        ComponentDefinition(
            "broken", lambda service: object(), {"service": ComponentRef("service")},
            initialize=fail, dispose=lambda value: events.append(("dispose", "broken")),
        ),
    ]))
    with pytest.raises(ValueError) as error:
        await app.start()
    assert error.value is failure
    assert events[-2:] == [("dispose", "broken"), ("dispose", "service")]
    await app.close()
    assert events.count(("dispose", "broken")) == 1


async def test_factory_failure_preserves_original_and_rolls_back_dependencies():
    events = []

    def fail(service):
        raise LookupError("factory")

    app = ApplicationContext(compile_assembly([
        component("service", events),
        ComponentDefinition("broken", fail, {"service": ComponentRef("service")}),
    ]))
    with pytest.raises(LookupError, match="factory"):
        await app.start()
    assert events[-1] == ("dispose", "service")


async def test_startup_and_cleanup_errors_are_both_preserved():
    primary, cleanup = ValueError("init"), LookupError("dispose")

    def init(value):
        raise primary

    def dispose(value):
        raise cleanup

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("resource", object, initialize=init, dispose=dispose),
    ]))
    with pytest.raises(ExceptionGroup) as error:
        await app.start()
    assert leaves(error.value) == [primary, cleanup]


async def test_disposal_failure_does_not_skip_other_components():
    events = []

    def dispose(value):
        events.append(("dispose", "bad"))
        raise ValueError("dispose")

    app = ApplicationContext(compile_assembly([
        component("first", events),
        ComponentDefinition("bad", object, dispose=dispose),
    ]))
    await app.start()
    with pytest.raises(ExceptionGroup):
        await app.close()
    assert events[-2:] == [("dispose", "bad"), ("dispose", "first")]
    with pytest.raises(ExceptionGroup):
        await app.close()
    assert events.count(("dispose", "bad")) == 1
    assert app.state is ApplicationState.CLOSED


async def test_body_exception_is_not_replaced_by_disposal_failure():
    body, cleanup = ValueError("body"), RuntimeError("cleanup")

    def dispose(value):
        raise cleanup

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("resource", object, dispose=dispose),
    ]))
    with pytest.raises(ExceptionGroup) as error:
        async with app:
            raise body
    assert leaves(error.value) == [body, cleanup]


async def test_concurrent_start_creates_once_and_resolves_same_object():
    events = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def create():
        events.append("create")
        entered.set()
        await release.wait()
        return object()

    app = ApplicationContext(compile_assembly([ComponentDefinition("value", create)]))
    first = asyncio.create_task(app.start())
    await asyncio.wait_for(entered.wait(), 2)
    second = asyncio.create_task(app.start())
    release.set()
    assert await asyncio.gather(first, second) == [app, app]
    assert events == ["create"]
    assert app.resolve("value") is app.resolve("value")
    await asyncio.gather(app.close(), app.close())


async def test_child_scope_instances_are_distinct_and_close_before_parent():
    events = []
    app = ApplicationContext(compile_assembly([
        component("shared", events),
        component("local", events, scope="run", dependencies={"shared": ComponentRef("shared")}),
    ]))
    await app.start()
    first, second = app.scope("run", "one"), app.scope("run", "two")
    await asyncio.gather(first.start(), second.start())
    assert first.resolve("local") is not second.resolve("local")
    assert first.resolve("shared") is second.resolve("shared") is app.resolve("shared")
    with pytest.raises(ApplicationLifecycleError, match="scope is not open"):
        app.resolve("local")
    await app.close()
    assert events[-3:] == [("dispose", "local"), ("dispose", "local"), ("dispose", "shared")]
    assert first.state is second.state is ApplicationState.CLOSED


async def test_missing_intermediate_scope_fails_before_local_creation():
    events = []
    app = ApplicationContext(compile_assembly([
        component("session", events, scope="session"),
        component("run", events, scope="run", dependencies={"session": ComponentRef("session")}),
    ]))
    async with app:
        run = app.scope("run", "missing-session")
        with pytest.raises(ApplicationLifecycleError, match="scope is not open"):
            await run.start()
        assert events == []
        async with app.scope("session", "s") as session:
            async with session.scope("run", "r") as valid:
                assert valid.resolve("run")["dependencies"]["session"] is session.resolve("session")


async def test_custom_scope_and_duplicate_names():
    plan = compile_assembly([
        ComponentDefinition("value", object, scope="conversation"),
    ], scope_order=("application", "conversation", "run"))
    async with ApplicationContext(plan) as app:
        child = app.scope("conversation", "one")
        with pytest.raises(ApplicationLifecycleError, match="already exists"):
            app.scope("conversation", "one")
        async with child:
            assert child.resolve("value") is not None
        async with app.scope("conversation", "one"):
            pass


async def test_closed_or_unstarted_context_does_not_resolve_or_restart():
    app = ApplicationContext(compile_assembly([]))
    with pytest.raises(ApplicationLifecycleError):
        app.resolve("missing")
    await app.close()
    with pytest.raises(ApplicationLifecycleError, match="cannot restart"):
        await app.start()
    with pytest.raises(ApplicationLifecycleError):
        app.scope("run", "one")


async def test_factory_cannot_take_ownership_of_borrowed_object():
    value, disposed = object(), []
    app = ApplicationContext(compile_assembly([
        BorrowedComponent("borrowed", value),
        ComponentDefinition("owned", lambda: value, dispose=lambda obj: disposed.append(obj)),
    ]))
    with pytest.raises(ApplicationLifecycleError, match="already owned or borrowed"):
        await app.start()
    assert disposed == []


async def test_two_factories_cannot_own_one_instance():
    value, disposed = object(), []
    app = ApplicationContext(compile_assembly([
        ComponentDefinition("first", lambda: value, dispose=lambda obj: disposed.append("first")),
        ComponentDefinition("second", lambda: value, dispose=lambda obj: disposed.append("second")),
    ]))
    with pytest.raises(ApplicationLifecycleError, match="already owned or borrowed"):
        await app.start()
    assert disposed == ["first"]


async def test_cancelled_start_rolls_back_before_returning():
    entered = asyncio.Event()
    disposed = []

    async def initialize(value):
        entered.set()
        await asyncio.Event().wait()

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("resource", object, initialize=initialize,
                            dispose=lambda obj: disposed.append(obj)),
    ]))
    task = asyncio.create_task(app.start())
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert len(disposed) == 1
    assert app.state is ApplicationState.CLOSED


async def test_repeated_cancellation_does_not_interrupt_close_cleanup():
    entered, release = asyncio.Event(), asyncio.Event()
    disposed = []

    async def dispose(value):
        entered.set()
        await release.wait()
        disposed.append(value)

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("resource", object, dispose=dispose),
    ]))
    await app.start()
    closing = asyncio.create_task(app.close())
    await asyncio.wait_for(entered.wait(), 2)
    closing.cancel()
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(closing, 2)
    assert len(disposed) == 1
    await app.close()
    assert len(disposed) == 1


async def test_close_during_start_waits_for_rollback():
    entered = asyncio.Event()
    disposed = []

    async def initialize(value):
        entered.set()
        await asyncio.Event().wait()

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("resource", object, initialize=initialize,
                            dispose=lambda obj: disposed.append(obj)),
    ]))
    starting = asyncio.create_task(app.start())
    await asyncio.wait_for(entered.wait(), 2)
    await asyncio.wait_for(app.close(), 2)
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert len(disposed) == 1


async def test_reentrant_lifecycle_operation_fails_instead_of_deadlocking():
    async def initialize(value):
        await app.close()

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("resource", object, initialize=initialize),
    ]))
    with pytest.raises(ApplicationLifecycleError, match="lifecycle hooks"):
        await asyncio.wait_for(app.start(), 2)


async def test_disposer_cancellation_still_cleans_other_components():
    events = []

    async def dispose(value):
        raise asyncio.CancelledError()

    app = ApplicationContext(compile_assembly([
        component("first", events),
        ComponentDefinition("second", object, dispose=dispose),
    ]))
    await app.start()
    with pytest.raises(BaseExceptionGroup) as error:
        await app.close()
    assert isinstance(leaves(error.value)[0], asyncio.CancelledError)
    assert events[-1] == ("dispose", "first")


async def test_plan_and_scope_identity_are_read_only():
    app = ApplicationContext(compile_assembly([]))
    with pytest.raises(AttributeError):
        app.plan = compile_assembly([])
    with pytest.raises(AttributeError):
        app.path = app.path.child("run", "r")


async def test_custom_harness_example_with_model_tool_storage_and_vendor_option():
    from examples.custom_harness import run_demo

    assert await run_demo() == ("LOCAL:HELLO", ("LOCAL:HELLO",), True)


async def test_cancel_start_before_factory_task_runs():
    events = []
    app = ApplicationContext(compile_assembly([component("resource", events)]))
    starting = asyncio.create_task(app.start())
    await asyncio.sleep(0)
    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(starting, 2)
    assert app.state is ApplicationState.CLOSED
    assert events.count(("dispose", "resource")) == events.count(("create", "resource"))


async def test_repeated_start_cancellation_waits_for_rollback():
    initialized, disposing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    disposed = []

    async def initialize(value):
        initialized.set()
        await asyncio.Event().wait()

    async def dispose(value):
        disposing.set()
        await release.wait()
        disposed.append(value)

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("resource", object, initialize=initialize, dispose=dispose),
    ]))
    starting = asyncio.create_task(app.start())
    await asyncio.wait_for(initialized.wait(), 2)
    starting.cancel()
    await asyncio.wait_for(disposing.wait(), 2)
    starting.cancel()
    await asyncio.sleep(0)
    starting.cancel()
    await asyncio.sleep(0)
    assert not starting.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(starting, 2)
    assert len(disposed) == 1
    assert app.state is ApplicationState.CLOSED


async def test_child_disposal_failure_still_closes_parent():
    events = []

    def fail(value):
        raise ValueError("child close")

    app = ApplicationContext(compile_assembly([
        component("parent", events),
        ComponentDefinition("child", object, scope="run", dispose=fail),
    ]))
    await app.start()
    child = app.scope("run", "child")
    await child.start()
    with pytest.raises(ExceptionGroup) as error:
        await app.close()
    assert str(leaves(error.value)[0]) == "child close"
    assert events[-1] == ("dispose", "parent")
    assert app.state is child.state is ApplicationState.CLOSED


async def test_parent_close_rejects_new_child_and_resolve_immediately():
    entered, release = asyncio.Event(), asyncio.Event()

    async def dispose(value):
        entered.set()
        await release.wait()

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("resource", object, dispose=dispose),
    ]))
    await app.start()
    closing = asyncio.create_task(app.close())
    await asyncio.wait_for(entered.wait(), 2)
    with pytest.raises(ApplicationLifecycleError):
        app.scope("run", "late")
    with pytest.raises(ApplicationLifecycleError):
        app.resolve("resource")
    release.set()
    await closing


async def test_reentrant_child_hook_cannot_close_parent_tree():
    async def initialize(value):
        await app.close()

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("resource", object, scope="run", initialize=initialize),
    ]))
    async with app:
        child = app.scope("run", "child")
        with pytest.raises(ApplicationLifecycleError, match="lifecycle hooks"):
            await asyncio.wait_for(child.start(), 2)


async def test_cancellation_and_cleanup_failure_are_preserved_together():
    initialized = asyncio.Event()
    cleanup = ValueError("cleanup")

    async def initialize(value):
        initialized.set()
        await asyncio.Event().wait()

    def dispose(value):
        raise cleanup

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("resource", object, initialize=initialize, dispose=dispose),
    ]))
    starting = asyncio.create_task(app.start())
    await asyncio.wait_for(initialized.wait(), 2)
    starting.cancel()
    with pytest.raises(BaseExceptionGroup) as error:
        await asyncio.wait_for(starting, 2)
    assert cleanup in leaves(error.value)
    assert any(isinstance(item, asyncio.CancelledError) for item in leaves(error.value))


async def test_factory_suppressing_cancellation_does_not_start_initializer():
    entered = asyncio.Event()
    initialized, disposed = [], []

    async def create():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return object()

    app = ApplicationContext(compile_assembly([
        ComponentDefinition(
            "resource", create, initialize=lambda obj: initialized.append(obj),
            dispose=lambda obj: disposed.append(obj),
        ),
    ]))
    starting = asyncio.create_task(app.start())
    await asyncio.wait_for(entered.wait(), 2)
    await asyncio.wait_for(app.close(), 2)
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert initialized == []
    assert len(disposed) == 1


async def test_factory_translating_cancellation_keeps_its_error():
    entered = asyncio.Event()
    failure = ValueError("factory failed while cancelling")

    async def create():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise failure

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("resource", create),
    ]))
    starting = asyncio.create_task(app.start())
    await asyncio.wait_for(entered.wait(), 2)
    starting.cancel()
    with pytest.raises(BaseExceptionGroup) as error:
        await asyncio.wait_for(starting, 2)
    assert failure in leaves(error.value)
    assert any(isinstance(item, asyncio.CancelledError) for item in leaves(error.value))
    assert app.state is ApplicationState.CLOSED
