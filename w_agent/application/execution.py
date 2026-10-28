"""Public execution of arbitrary application components, without model schemas."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import AsyncExitStack
from contextvars import ContextVar
from dataclasses import dataclass
import inspect
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from .context import ApplicationContext, ApplicationLifecycleError, ApplicationState, _settle
from .planning import AssemblyDefinitionError, AssemblyPlan, _identity


@dataclass(frozen=True, slots=True)
class ApplicationOperation:
    """An explicit public component method; stream operations are consumed in scope."""

    component: str
    method: str = "run"
    kind: str = "call"

    def __post_init__(self) -> None:
        _identity(self.component, "operation component")
        if (not isinstance(self.method, str) or not self.method.isidentifier()
                or (self.method.startswith("_") and self.method != "__call__")):
            raise AssemblyDefinitionError("operation method must be public or explicit __call__")
        if self.kind not in ("call", "stream"):
            raise AssemblyDefinitionError("operation kind must be call or stream")


@dataclass(frozen=True, slots=True)
class ApplicationProject:
    """An immutable plan and exposed operations, shared by Python and frontends."""

    plan: AssemblyPlan
    operations: Mapping[str, ApplicationOperation]
    name: str = "default"

    def __post_init__(self) -> None:
        if not isinstance(self.plan, AssemblyPlan):
            raise AssemblyDefinitionError("project needs an AssemblyPlan")
        _identity(self.name, "project name")
        if not isinstance(self.operations, Mapping) or not self.operations:
            raise AssemblyDefinitionError("project needs named operations")
        operations = dict(self.operations)
        for name, operation in operations.items():
            _identity(name, "operation name")
            if not isinstance(operation, ApplicationOperation):
                raise AssemblyDefinitionError("project operations need ApplicationOperation")
            if operation.component not in self.plan.startup_order:
                raise AssemblyDefinitionError(f"unknown operation component: {operation.component}")
        object.__setattr__(self, "operations", MappingProxyType(operations))

    def open(self) -> ApplicationHost:
        """Create a new, unstarted host. Borrowed objects remain host-owned."""
        return ApplicationHost(self)


_executing_hosts: ContextVar[tuple[ApplicationHost, ...]] = ContextVar(
    "w_agent_executing_hosts", default=(),
)


class ApplicationHost:
    """Own an application and only the calls explicitly submitted to this host.

    Call-scoped components receive fresh scope paths through their declared
    lifetime. Streams stay open through consumption and are closed before those
    scopes. Shutdown cancels/drains submitted calls before closing components.
    Uncooperative synchronous code and independently spawned tasks are not a
    sandbox or implicitly supervised background work.
    """

    def __init__(self, project: ApplicationProject) -> None:
        if not isinstance(project, ApplicationProject):
            raise TypeError("ApplicationHost needs an ApplicationProject")
        self.project = project
        self.context = ApplicationContext(project.plan, name=project.name)
        self._scopes = {component.name: component.scope for component in project.plan.components}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _check_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise ApplicationLifecycleError("application host belongs to another event loop")

    async def start(self) -> ApplicationHost:
        self._check_loop()
        if self._closing:
            raise ApplicationLifecycleError("application host is closing or closed")
        await self.context.start()
        return self

    async def __aenter__(self) -> ApplicationHost:
        return await self.start()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        try:
            await self.close()
        except BaseException as cleanup:
            if exc is not None:
                raise BaseExceptionGroup("application call and shutdown failed", [exc, cleanup]) from None
            raise

    def _operation(self, name: str, kind: str) -> ApplicationOperation:
        self._check_loop()
        if self._closing or self.context.state is not ApplicationState.ACTIVE:
            raise ApplicationLifecycleError("application host must be active")
        try:
            operation = self.project.operations[name]
        except (KeyError, TypeError):
            raise AssemblyDefinitionError("unknown application operation") from None
        if operation.kind != kind:
            raise AssemblyDefinitionError(f"operation requires {operation.kind} execution")
        return operation

    async def invoke(self, operation: str, /, *args: Any, **kwargs: Any) -> Any:
        """Run a value-returning method without interpreting its input or output."""
        target = self._operation(operation, "call")
        return await self._submit(target, args, kwargs, None)

    async def consume(
        self, operation: str, consumer: Callable[[Any], Any], /, *args: Any, **kwargs: Any,
    ) -> int:
        """Consume a sync/async stream with backpressure; return its delivered count."""
        target = self._operation(operation, "stream")
        if not callable(consumer):
            raise TypeError("stream consumer must be callable")
        return await self._submit(target, args, kwargs, consumer)

    async def _submit(self, target, args, kwargs, consumer):
        task = asyncio.create_task(self._execute(target, args, kwargs, consumer))
        self._tasks.add(task)
        try:
            # Shield the worker so repeated caller cancellation cannot truncate
            # its stream/scope cleanup. Send cancellation only once, then drain.
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            if not task.done() and not task.cancelling():
                task.cancel()
            try:
                await _settle(task)
            except asyncio.CancelledError:
                pass
            except BaseException as failure:
                raise BaseExceptionGroup("application call failed during cancellation", [cancellation, failure]) from None
            raise cancellation
        finally:
            self._tasks.discard(task)

    async def _execute(self, target, args, kwargs, consumer):
        token = _executing_hosts.set((*_executing_hosts.get(), self))
        try:
            async with AsyncExitStack() as stack:
                scope = self.context
                last = self.project.plan.scope_order.index(self._scopes[target.component])
                identity = f"call-{uuid4().hex}"
                for kind in self.project.plan.scope_order[1:last + 1]:
                    scope = await stack.enter_async_context(scope.scope(kind, identity))
                component = scope.resolve(target.component)
                method = getattr(component, target.method, None)
                if not callable(method):
                    raise AssemblyDefinitionError("application operation method is not callable")
                result = method(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                if consumer is None:
                    if hasattr(result, "__next__") or hasattr(result, "__anext__"):
                        await _close_stream(result)
                        raise AssemblyDefinitionError("iterator results require a stream operation")
                    return result
                return await _consume_stream(result, consumer)
        finally:
            _executing_hosts.reset(token)

    async def close(self) -> None:
        self._check_loop()
        if self in _executing_hosts.get():
            raise ApplicationLifecycleError("an invocation cannot close its own host")
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(self._shutdown())
        await _settle(self._close_task)

    async def _shutdown(self) -> None:
        failures: list[BaseException] = []
        tasks = tuple(self._tasks)
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        for outcome in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
                failures.append(outcome)
        try:
            await self.context.close()
        except BaseException as failure:
            failures.append(failure)
        if failures:
            raise BaseExceptionGroup("application host shutdown failed", failures)


async def _close_stream(stream: Any) -> None:
    close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
    if close is not None:
        result = close()
        if inspect.isawaitable(result):
            await result


async def _consume_stream(source: Any, consumer: Callable[[Any], Any]) -> int:
    iterator = None
    failure = None
    count = 0
    try:
        if hasattr(source, "__aiter__"):
            iterator = aiter(source)
            async for item in iterator:
                result = consumer(item)
                if inspect.isawaitable(result):
                    await result
                count += 1
        else:
            iterator = iter(source)
            for item in iterator:
                result = consumer(item)
                if inspect.isawaitable(result):
                    await result
                count += 1
        return count
    except BaseException as error:
        failure = error
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        resources = (source,) if iterator is None or iterator is source else (iterator, source)
        for resource in resources:
            try:
                await _close_stream(resource)
            except BaseException as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            errors = ([failure] if failure is not None else []) + cleanup_errors
            raise BaseExceptionGroup("application stream cleanup failed", errors) from None
