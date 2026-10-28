"""M3 acceptance: component aspects and scope-owned invocation/stream lifetimes."""

import asyncio

import pytest

from w_agent import (
    AdviceRef, After, Around, Aspect, AspectDefinition, AspectError, Before,
    Finally, OnError, ApplicationContext, ApplicationPlugin, AssemblyDefinitionError,
    BorrowedComponent, CapabilityDeclaration, CapabilityExport, CapabilityImport,
    CapabilityRequirement, ComponentDefinition, ComponentRef, MethodPointcut,
    PluginManager, PostConstruct, PreDestroy, ServiceComponent, compile_assembly,
    compile_configured, compile_decorated,
)


def assembly(target, aspects, **options):
    return ApplicationContext(compile_assembly([
        ComponentDefinition("target", lambda: target, **options),
    ], aspects=aspects))


async def test_sync_method_stays_sync_inside_running_event_loop():
    events = []

    class Target:
        def call(self, value, *, suffix):
            events.append("body")
            return value + suffix

    def around(invocation, proceed):
        events.append("around-in")
        result = proceed()
        events.append("around-out")
        return result.upper()

    advice = AspectDefinition("trace", before=lambda inv: events.append("before"),
                              around=around, after=lambda inv, value: events.append(value),
                              finally_=lambda inv, outcome: events.append(outcome.status))
    async with assembly(Target(), [advice]) as app:
        assert app.resolve("target").call("a", suffix="b") == "AB"
        assert app.aspect_matches[0].method == "call"
    assert events == ["before", "around-in", "body", "around-out", "AB", "success"]


async def test_order_is_stable_by_order_then_identity_and_nested_on_exit():
    events = []

    class Target:
        async def call(self):
            events.append("body")
            return 3

    def advice(name, order):
        return AspectDefinition(name, order=order, before=lambda inv: events.append(name + "+"),
                                finally_=lambda inv, outcome: events.append(name + "-"))

    async with assembly(Target(), [advice("b", 1), advice("a", 1), advice("z", 0)]) as app:
        assert await app.resolve("target").call() == 3
    assert events == ["z+", "a+", "b+", "body", "b-", "a-", "z-"]


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_proceed_is_single_use_and_short_circuit_is_allowed(asynchronous):
    calls = []

    class Target:
        def sync(self):
            calls.append("body")
            return 1

        async def async_(self):
            return self.sync()

    async def around_async(invocation, proceed):
        await proceed()
        return await proceed()

    def around_sync(invocation, proceed):
        proceed()
        return proceed()

    method = "async_" if asynchronous else "sync"
    advice = AspectDefinition("twice", MethodPointcut(methods=(method,)),
                              around=around_async if asynchronous else around_sync)
    async with assembly(Target(), [advice]) as app:
        with pytest.raises(AspectError, match="single-use"):
            if asynchronous:
                await app.resolve("target").async_()
            else:
                app.resolve("target").sync()
    assert calls == ["body"]

    advice = AspectDefinition("cache", MethodPointcut(methods=(method,)), around=lambda inv, proceed: 9)
    async with assembly(Target(), [advice]) as app:
        result = await app.resolve("target").async_() if asynchronous else app.resolve("target").sync()
        assert result == 9
    assert calls == ["body"]


async def test_captured_continuation_expires_and_unawaited_proceed_is_rejected():
    captured = []

    class Target:
        async def call(self):
            return 1

    def around(invocation, proceed):
        captured.append(proceed)
        proceed()
        return 1

    async with assembly(Target(), [AspectDefinition("invalid", around=around)]) as app:
        with pytest.raises(AspectError, match="awaited"):
            await app.resolve("target").call()
        with pytest.raises(AspectError, match="expires"):
            captured[0]()


async def test_primary_error_and_finally_failures_are_preserved():
    errors = []

    class Target:
        async def call(self):
            raise ValueError("business")

    def final(invocation, outcome):
        assert outcome.status == "error"
        raise RuntimeError("cleanup")

    async with assembly(Target(), [AspectDefinition("errors", on_error=lambda inv, error: errors.append(error), finally_=final)]) as app:
        with pytest.raises(BaseExceptionGroup) as result:
            await app.resolve("target").call()
    assert isinstance(errors[0], ValueError)
    assert {type(error) for error in result.value.exceptions} == {ValueError, RuntimeError}


async def test_repeated_cancellation_cannot_interrupt_finally():
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    events = []

    class Target:
        async def call(self):
            entered.set()
            await asyncio.Event().wait()

    async def final(invocation, outcome):
        assert outcome.status == "cancelled"
        cleaning.set()
        await release.wait()
        events.append("cleaned")

    async with assembly(Target(), [AspectDefinition("trace", finally_=final)]) as app:
        caller = asyncio.create_task(app.resolve("target").call())
        await asyncio.wait_for(entered.wait(), 2)
        caller.cancel()
        await asyncio.wait_for(cleaning.wait(), 2)
        caller.cancel()
        await asyncio.sleep(0)
        assert not caller.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, 2)
    assert events == ["cleaned"]


async def test_scope_close_cancels_invocation_before_disposing_target():
    entered = asyncio.Event()
    events = []

    class Target:
        async def call(self):
            entered.set()
            await asyncio.Event().wait()

    app = assembly(Target(), [AspectDefinition("trace", finally_=lambda inv, out: events.append("finally"))],
                   dispose=lambda obj: events.append("dispose"))
    await app.start()
    target = app.resolve("target")
    caller = asyncio.create_task(target.call())
    await asyncio.wait_for(entered.wait(), 2)
    await asyncio.wait_for(app.close(), 2)
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert events == ["finally", "dispose"]
    with pytest.raises(AspectError, match="not active"):
        await target.call()


@pytest.mark.parametrize("end", ["exhaust", "close", "scope", "error", "cancel"])
async def test_async_stream_lifetime_includes_consumption_and_all_exit_paths(end):
    events = []
    entered = asyncio.Event()

    class Target:
        async def stream(self):
            try:
                events.append("body")
                yield 1
                if end == "error":
                    raise ValueError("stream failed")
                if end == "cancel":
                    entered.set()
                    await asyncio.Event().wait()
                yield 2
            finally:
                events.append("source-close")

    async def around(inv, proceed):
        events.append("around-in")
        try:
            async for item in proceed():
                yield item * 2
        finally:
            events.append("around-close")

    advice = AspectDefinition("trace", before=lambda inv: events.append("before"), around=around,
                              after=lambda inv, out: events.append("after"),
                              finally_=lambda inv, out: events.append(out.status))
    app = assembly(Target(), [advice], dispose=lambda obj: events.append("dispose"))
    await app.start()
    stream = app.resolve("target").stream()
    assert events == []
    assert await anext(stream) == 2
    assert "around-close" not in events and "success" not in events
    if end == "exhaust":
        assert [item async for item in stream] == [4]
    elif end == "close":
        await stream.aclose()
        await stream.aclose()
    elif end == "error":
        with pytest.raises(ValueError, match="stream failed"):
            await anext(stream)
    elif end == "cancel":
        next_item = asyncio.create_task(anext(stream))
        await asyncio.wait_for(entered.wait(), 2)
        next_item.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(next_item, 2)
    await asyncio.wait_for(app.close(), 2)
    assert events.count("source-close") == events.count("around-close") == 1
    expected = {"exhaust": "success", "close": "closed", "scope": "closed", "error": "error", "cancel": "cancelled"}[end]
    assert events[-2:] == [expected, "dispose"]
    assert ("after" in events) == (end == "exhaust")


@pytest.mark.parametrize("exhaust", [False, True])
async def test_sync_streams_close_before_component_disposal(exhaust):
    events = []

    class Target:
        def stream(self):
            try:
                yield 1
                yield 2
            finally:
                events.append("source")

    async with assembly(Target(), [AspectDefinition("trace", finally_=lambda inv, out: events.append(out.status))],
                        dispose=lambda obj: events.append("dispose")) as app:
        stream = app.resolve("target").stream()
        assert next(stream) == 1
        if exhaust:
            assert list(stream) == [2]
    assert events == ["source", "success" if exhaust else "closed", "dispose"]


async def test_around_that_stops_stream_early_closes_downstream():
    events = []

    class Target:
        async def stream(self):
            try:
                yield 1
                yield 2
            finally:
                events.append("closed")

    async def first(inv, proceed):
        yield await anext(proceed())

    async with assembly(Target(), [AspectDefinition("one", around=first)]) as app:
        assert [x async for x in app.resolve("target").stream()] == [1]
        assert events == ["closed"]


async def test_managed_aspect_dependency_and_component_tags_work_for_all_entries():
    async def execute(mode):
        events = []

        @Aspect("trace", component="service", methods=("run",), tags=("measured",))
        class Trace:
            @PostConstruct
            def ready(self):
                events.append("trace-start")

            @Before
            def before(self, invocation):
                events.append("before")

            @Around
            async def around(self, invocation, proceed):
                return 1 + await proceed()

            @After
            def after(self, invocation, result):
                events.append(result)

            @Finally
            def final(self, invocation, outcome):
                events.append(outcome.status)

            @PreDestroy
            def close(self):
                events.append("trace-close")

        @ServiceComponent("service", tags=("measured",))
        class Service:
            async def run(self):
                return 2

            @PreDestroy
            def close(self):
                events.append("service-close")

        if mode == "python":
            plan = compile_assembly([
                ComponentDefinition("service", Service, dispose=Service.close, tags=frozenset({"measured"})),
                ComponentDefinition("trace", Trace, initialize=Trace.ready, dispose=Trace.close),
            ], aspects=[AspectDefinition("trace", MethodPointcut("service", ("run",), frozenset({"measured"})),
                                         before=AdviceRef("trace", "before"), around=AdviceRef("trace", "around"),
                                         after=AdviceRef("trace", "after"), finally_=AdviceRef("trace", "final"))])
        elif mode == "decorator":
            plan = compile_decorated([Service, Trace])
        else:
            plan = compile_configured({"components": ["s", "t"]}, catalog={"s": Service, "t": Trace})
        async with ApplicationContext(plan) as app:
            assert await app.resolve("service").run() == 3
            assert len(app.aspect_matches) == 1
        return events

    traces = [await execute(mode) for mode in ("python", "decorator", "config")]
    assert traces[0] == traces[1] == traces[2] == ["trace-start", "before", 3, "success", "service-close", "trace-close"]


async def test_sync_async_mismatch_is_rejected_and_created_object_is_released():
    events = []

    class Target:
        def sync(self):
            events.append("body")

    async def before(inv):
        pass

    with pytest.raises(AspectError, match="synchronous"):
        await assembly(Target(), [AspectDefinition("bad", before=before)],
                       dispose=lambda obj: events.append("disposed")).start()
    assert events == ["disposed"]


def test_advice_dependency_cycles_and_short_scope_capture_fail_before_creation():
    advice = AspectDefinition("trace", MethodPointcut("target"), before=AdviceRef("advice", "before"))
    with pytest.raises(AssemblyDefinitionError, match="shorter-lived"):
        compile_assembly([ComponentDefinition("target", object),
                          ComponentDefinition("advice", object, scope="run")], aspects=[advice])
    with pytest.raises(AssemblyDefinitionError, match="cyclic"):
        compile_assembly([ComponentDefinition("target", object),
                          ComponentDefinition("advice", lambda target: [], {"target": ComponentRef("target")})], aspects=[advice])


async def test_borrowed_objects_are_not_mutated_or_closed_and_proxies_are_not_reowned():
    calls = []

    class External:
        def run(self):
            return 1

        def close(self):
            raise AssertionError("borrowed")

    raw = External()
    advice = AspectDefinition("trace", MethodPointcut("external", ("run",)), before=lambda inv: calls.append("trace"))
    async with ApplicationContext(compile_assembly([BorrowedComponent("external", raw)], aspects=[advice])) as app:
        exposed = app.resolve("external")
        assert isinstance(exposed, External)
        assert exposed.run() == raw.run() == 1
    assert calls == ["trace"]

    app = ApplicationContext(compile_assembly([
        BorrowedComponent("external", raw),
        ComponentDefinition("alias", lambda external: external, {"external": ComponentRef("external")}),
    ], aspects=[advice]))
    with pytest.raises(RuntimeError, match="already owned or borrowed"):
        await app.start()


async def test_self_close_from_intercepted_call_is_rejected_without_deadlock():
    class Target:
        async def run(self):
            await app.close()

    app = assembly(Target(), [AspectDefinition("trace", before=lambda inv: None)])
    async with app:
        with pytest.raises(RuntimeError, match="own context tree"):
            await asyncio.wait_for(app.resolve("target").run(), 2)


async def test_explicit_stream_kind_for_coroutine_returning_iterator():
    class Target:
        async def open(self):
            async def source():
                yield 1
            return source()

    advice = AspectDefinition("trace", MethodPointcut(kind="stream"), before=lambda inv: None)
    async with assembly(Target(), [advice]) as app:
        async with app.resolve("target").open() as stream:
            assert await anext(stream) == 1


async def test_plugin_export_uses_woven_instance_and_unloads_after_stream_cleanup():
    events = []

    class Target:
        async def stream(self):
            try:
                yield 1
                yield 2
            finally:
                events.append("stream-close")

    manager = PluginManager()
    module = ApplicationPlugin(name="woven", version="1",
        components=[ComponentDefinition("target", Target, dispose=lambda obj: events.append("dispose"))],
        aspects=[AspectDefinition("trace", finally_=lambda inv, out: events.append(out.status))],
        exports=[CapabilityExport("target", CapabilityDeclaration("service"))])
    await manager.load(module)
    stream = module.application.resolve("target").stream()
    assert await anext(stream) == 1
    await manager.close()
    assert events == ["stream-close", "closed", "dispose"]


def test_public_aspect_exports_are_present():
    import w_agent
    for name in ("Aspect", "Before", "Around", "After", "OnError", "Finally", "AspectDefinition",
                 "AdviceRef", "MethodPointcut", "Invocation", "InvocationOutcome", "AspectMatch", "AspectError"):
        assert name in w_agent.__all__ and getattr(w_agent, name) is not None


async def test_nested_plugin_borrowing_preserves_stream_kind_and_single_disposal():
    events = []

    class Source:
        async def stream(self):
            yield 1

    manager = PluginManager()
    first = ApplicationPlugin(name="source", version="1",
        components=[ComponentDefinition("source", Source, dispose=lambda obj: events.append("dispose"))],
        aspects=[AspectDefinition("inner", finally_=lambda inv, out: events.append("inner"))],
        exports=[CapabilityExport("source", CapabilityDeclaration("stream-source"))])
    second = ApplicationPlugin(name="consumer", version="1", components=[],
        imports=[CapabilityImport("borrowed", CapabilityRequirement("stream-source"))],
        aspects=[AspectDefinition("outer", finally_=lambda inv, out: events.append("outer"))])
    await manager.load(first)
    await manager.load(second)
    assert [value async for value in second.application.resolve("borrowed").stream()] == [1]
    await manager.close()
    assert events == ["inner", "outer", "dispose"]


async def test_concurrent_stream_close_cancels_active_next_once():
    entered = asyncio.Event()
    events = []

    class Target:
        async def stream(self):
            try:
                entered.set()
                await asyncio.Event().wait()
                yield 1
            finally:
                events.append("source")

    async with assembly(Target(), [AspectDefinition("trace", finally_=lambda inv, out: events.append(out.status))]) as app:
        stream = app.resolve("target").stream()
        next_item = asyncio.create_task(anext(stream))
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(AspectError, match="concurrent"):
            await anext(stream)
        await asyncio.wait_for(asyncio.gather(stream.aclose(), stream.aclose()), 2)
        with pytest.raises(asyncio.CancelledError):
            await next_item
    assert events == ["source", "cancelled"]


async def test_unconsumed_stream_is_closed_without_starting_business_or_advice():
    events = []

    class Target:
        async def stream(self):
            events.append("body")
            yield 1

    async with assembly(Target(), [AspectDefinition("trace", before=lambda inv: events.append("before"))]) as app:
        stream = app.resolve("target").stream()
    assert events == []
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_aspected_harness_example_runs_through_public_api():
    from examples.aspected_harness import run_demo
    assert await run_demo() == (["HELLO", "HARNESS"], ["start:stream", "finish:success"], True)


async def test_disposer_can_await_a_still_live_advised_dependency():
    events = []

    class Store:
        async def flush(self):
            events.append("flush")

    async def dispose(consumer):
        await consumer[0].flush()

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("store", Store, dispose=lambda obj: events.append("store-close")),
        ComponentDefinition("consumer", lambda store: [store], {"store": ComponentRef("store")}, dispose=dispose),
    ], aspects=[AspectDefinition("trace", MethodPointcut("store", ("flush",)),
                                 finally_=lambda inv, out: events.append("finally"))]))
    await app.start()
    await app.close()
    assert events == ["flush", "finally", "store-close"]


async def test_intercepted_harness_can_create_and_close_child_scopes():
    events = []

    class Harness:
        async def run(self):
            async with app.scope("run", "child") as child:
                return child.resolve("value")

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("harness", Harness),
        ComponentDefinition("value", lambda: {"result": 1}, scope="run",
                            dispose=lambda obj: events.append("child-close")),
    ], aspects=[AspectDefinition("trace", MethodPointcut("harness"), finally_=lambda inv, out: events.append("finally"))]))
    async with app:
        assert await asyncio.wait_for(app.resolve("harness").run(), 2) == {"result": 1}
    assert events == ["child-close", "finally"]


async def test_parent_invocation_is_cancelled_before_child_resources_are_disposed():
    entered = asyncio.Event()
    events = []

    class Harness:
        async def run(self):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                events.append("call-close")

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("harness", Harness),
        ComponentDefinition("value", object, scope="run", dispose=lambda obj: events.append("child-close")),
    ], aspects=[AspectDefinition("trace", MethodPointcut("harness"), before=lambda inv: None)]))
    await app.start()
    await app.scope("run", "open").start()
    task = asyncio.create_task(app.resolve("harness").run())
    await asyncio.wait_for(entered.wait(), 2)
    await asyncio.wait_for(app.close(), 2)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["call-close", "child-close"]


async def test_callable_tool_uses_explicit_call_pointcut_without_mutating_function():
    events = []

    def tool(value):
        return value.upper()

    app = ApplicationContext(compile_assembly([BorrowedComponent("tool", tool)], aspects=[
        AspectDefinition("trace", MethodPointcut("tool", ("__call__",)), before=lambda inv: events.append(inv.method)),
    ]))
    async with app:
        assert app.resolve("tool")("hi") == tool("hi") == "HI"
    assert events == ["__call__"]


async def test_stream_cleanup_failure_does_not_skip_component_disposal():
    events = []

    class Target:
        async def stream(self):
            try:
                yield 1
                yield 2
            finally:
                events.append("source-close")

    def final(invocation, outcome):
        events.append("finally")
        raise ValueError("cleanup failed")

    app = assembly(Target(), [AspectDefinition("trace", finally_=final)],
                   dispose=lambda obj: events.append("disposed"))
    await app.start()
    assert await anext(app.resolve("target").stream()) == 1
    with pytest.raises(BaseExceptionGroup):
        await app.close()
    with pytest.raises(BaseExceptionGroup):
        await app.close()
    assert events == ["source-close", "finally", "disposed"]


async def test_stream_cannot_close_itself_during_advancement():
    class Target:
        async def stream(self):
            await stream.aclose()
            yield 1

    async with assembly(Target(), [AspectDefinition("trace", before=lambda inv: None)]) as app:
        stream = app.resolve("target").stream()
        with pytest.raises(AspectError, match="close itself"):
            await asyncio.wait_for(anext(stream), 2)
