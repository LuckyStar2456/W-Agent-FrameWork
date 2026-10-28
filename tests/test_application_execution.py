"""Public project execution, lifecycle ownership and trusted-entry boundaries."""

import asyncio
from dataclasses import dataclass
from types import ModuleType
import sys

import pytest

from w_agent import (
    ApplicationCall, ApplicationEntryError, ApplicationLifecycleError,
    ApplicationOperation, ApplicationProject, AssemblyDefinitionError,
    BorrowedComponent, ComponentDefinition, compile_assembly,
    execute_application_entry, load_application_entry,
)


def project(factory, *, scope="application", dispose=None, kind="call"):
    return ApplicationProject(compile_assembly((
        ComponentDefinition("custom", factory, scope=scope, dispose=dispose),
    )), {"run": ApplicationOperation("custom", "run", kind)})


@pytest.mark.asyncio
async def test_custom_types_and_argument_names_are_not_coerced():
    @dataclass
    class CustomRequest:
        payload: bytes

    class Harness:
        def run(self, value, *, operation, consumer):
            assert operation == "domain-operation" and consumer == "domain-consumer"
            return value

    request = CustomRequest(b"not-model-messages")
    async with project(Harness).open() as host:
        assert await host.invoke("run", request, operation="domain-operation", consumer="domain-consumer") is request


@pytest.mark.asyncio
async def test_run_scopes_are_fresh_and_disposed_before_return():
    created, closed = [], []

    class Harness:
        def __init__(self):
            created.append(self)

        async def run(self):
            return id(self)

    async with project(Harness, scope="run", dispose=closed.append).open() as host:
        first = await host.invoke("run")
        second = await host.invoke("run")
        assert first != second
        assert closed == created
    assert len(closed) == 2


@pytest.mark.asyncio
async def test_shutdown_cancels_submitted_calls_before_component_cleanup():
    entered, released = asyncio.Event(), asyncio.Event()
    events = []

    class Harness:
        async def run(self):
            entered.set()
            try:
                await released.wait()
            finally:
                events.append("call-stopped")

    host = project(Harness, dispose=lambda obj: events.append("closed")).open()
    await host.start()
    task = asyncio.create_task(host.invoke("run"))
    await entered.wait()
    await host.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["call-stopped", "closed"]
    with pytest.raises(ApplicationLifecycleError):
        await host.invoke("run")


@pytest.mark.asyncio
async def test_repeated_caller_cancellation_drains_run_scope_cleanup():
    entered, cleaning, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
    closed = []

    class Harness:
        async def run(self):
            entered.set()
            await asyncio.Event().wait()

    async def dispose(obj):
        cleaning.set()
        await finish.wait()
        closed.append(obj)

    async with project(Harness, scope="run", dispose=dispose).open() as host:
        task = asyncio.create_task(host.invoke("run"))
        await entered.wait()
        task.cancel()
        await cleaning.wait()
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(closed) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [True, False])
async def test_stream_consumer_failure_closes_before_scope(asynchronous):
    events = []

    class Harness:
        def run(self):
            try:
                yield {"value": 1}
                yield {"value": 2}
            finally:
                events.append("stream-closed")

    if asynchronous:
        async def run(self):
            try:
                yield {"value": 1}
                yield {"value": 2}
            finally:
                events.append("stream-closed")
        Harness.run = run

    def consumer(item):
        assert item == {"value": 1}
        raise ValueError("consumer-failed")

    async with project(Harness, scope="run", kind="stream",
                       dispose=lambda obj: events.append("scope-closed")).open() as host:
        with pytest.raises(ValueError, match="consumer-failed"):
            await host.consume("run", consumer)
    assert events == ["stream-closed", "scope-closed"]


@pytest.mark.asyncio
async def test_async_consumer_has_backpressure_and_count():
    seen = []

    class Harness:
        async def run(self):
            yield 1
            assert seen == [1]
            yield 2

    async def consumer(value):
        await asyncio.sleep(0)
        seen.append(value)

    async with project(Harness, kind="stream").open() as host:
        assert await host.consume("run", consumer) == 2
    assert seen == [1, 2]


@pytest.mark.asyncio
async def test_value_calls_reject_iterator_escape():
    class Harness:
        def run(self):
            yield 1

    async with project(Harness).open() as host:
        with pytest.raises(AssemblyDefinitionError, match="stream operation"):
            await host.invoke("run")


@pytest.mark.asyncio
async def test_host_cannot_close_from_its_own_invocation():
    class Harness:
        async def run(self):
            await host.close()

    async with project(Harness).open() as host:
        with pytest.raises(ApplicationLifecycleError, match="own host"):
            await asyncio.wait_for(host.invoke("run"), 2)


@pytest.mark.asyncio
async def test_unknown_operation_and_wrong_mode_do_not_execute():
    class Harness:
        def run(self):
            pytest.fail("must not execute")

    async with project(Harness).open() as host:
        with pytest.raises(AssemblyDefinitionError):
            await host.invoke("absent")
        with pytest.raises(AssemblyDefinitionError):
            await host.consume("run", print)


def test_operation_rejects_private_and_unknown_components():
    with pytest.raises(AssemblyDefinitionError):
        ApplicationOperation("custom", "_private")
    with pytest.raises(AssemblyDefinitionError):
        ApplicationProject(compile_assembly(()), {"run": ApplicationOperation("missing")})


@pytest.mark.asyncio
async def test_loader_rejects_before_import(monkeypatch):
    import w_agent.application.loading as loading

    def forbidden(*args):
        pytest.fail("unconfirmed import")
    monkeypatch.setattr(loading.importlib, "import_module", forbidden)
    with pytest.raises(ApplicationEntryError, match="confirmation"):
        await load_application_entry("somewhere:factory")


@pytest.mark.asyncio
async def test_same_entry_supports_python_call_and_async_factory(monkeypatch):
    events = []

    class Harness:
        def run(self, query, *, dialect):
            events.append((query, dialect))
            return {"answer": f"{dialect}:{query}"}

    async def factory():
        return project(Harness, dispose=lambda obj: events.append("closed"))

    module = ModuleType("developer_application_test")
    module.create = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    result = await execute_application_entry(
        f"{module.__name__}:create", ApplicationCall(args=("hi",), kwargs={"dialect": "custom"}),
        confirmed=True,
    )
    assert result == {"answer": "custom:hi"}
    assert events == [("hi", "custom"), "closed"]


@pytest.mark.asyncio
async def test_borrowed_application_component_is_never_closed():
    class Harness:
        closed = False

        def run(self):
            return "borrowed"

        def close(self):
            self.closed = True

    harness = Harness()
    plan = compile_assembly((BorrowedComponent("custom", harness),))
    async with ApplicationProject(plan, {"run": ApplicationOperation("custom")}).open() as host:
        assert await host.invoke("run") == "borrowed"
    assert not harness.closed
