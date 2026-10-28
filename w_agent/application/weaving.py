"""Scope-owned interception, invocation draining and stream leases."""

from __future__ import annotations

import asyncio
import functools
import inspect
from contextvars import ContextVar
from dataclasses import replace

from .advice_execution import combine, drain, invoke_async, invoke_sync, stream_async, stream_sync
from .aspects import AdviceRef, AspectError, AspectMatch, Invocation


_invocation_owner = ContextVar("application_invocation_owner", default=None)


def invocation_owner():
    return _invocation_owner.get()


class InvocationRuntime:
    def __init__(self, scope):
        self.scope = scope
        self.closed = False
        self.tasks = set()
        self.streams = set()
        self.matches = []

    def check(self, component=None):
        self.scope._check_loop()
        if self.scope._inside_lifecycle() and self.scope.state.value != "closed":
            if component is not None and component not in self.scope._instances:
                raise AspectError("component has not started or is already disposed")
            return  # Awaited lifecycle calls can still use live dependencies.
        current = self.scope
        while current is not None:
            if current.state.value not in ("starting", "active") or self.closed:
                raise AspectError("component invocation scope is not active")
            current = current._parent

    def spawn(self, awaitable):
        token = _invocation_owner.set(self.scope)
        try:
            task = asyncio.create_task(awaitable)
        finally:
            _invocation_owner.reset(token)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def wait(self, task):
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            if not task.done():
                task.cancel()
            try:
                await drain(task)
            except asyncio.CancelledError:
                pass
            except BaseException as failure:
                combine(cancellation, [failure])
            raise cancellation

    async def call(self, invocation, method, advices):
        self.check(invocation.component)
        return await self.wait(self.spawn(invoke_async(invocation, method, advices)))

    async def close(self):
        self.closed = True
        tasks = tuple(self.tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        failures = []
        for task in tasks:
            try:
                await drain(task)
            except asyncio.CancelledError:
                pass  # Scope-owned cancellation is expected; hook errors are not.
            except BaseException as error:
                failures.append(error)
        for stream in tuple(self.streams):
            try:
                if isinstance(stream, ManagedAsyncStream):
                    await stream.aclose()
                else:
                    stream.close()
            except BaseException as error:
                failures.append(error)
        combine(None, failures)

    def weave(self, name, instance, definitions, lookup):
        if not definitions:
            return instance
        bindings = []
        for definition in definitions:
            hooks = {}
            for role in ("before", "around", "after", "on_error", "finally_"):
                hook = getattr(definition, role)
                if isinstance(hook, AdviceRef):
                    hook = getattr(lookup(hook.component), hook.method, None)
                    if not callable(hook):
                        raise AspectError("advice reference does not resolve to a method")
                if hook is not None:
                    try:
                        inspect.signature(hook).bind(*([object()] if role == "before" else [object(), object()]))
                    except (TypeError, ValueError):
                        raise AspectError(f"invalid advice signature: {definition.name}.{role}") from None
                hooks[role] = hook
            bindings.append(replace(definition, **hooks))
        methods = {}
        names = set(vars(instance)) if hasattr(instance, "__dict__") else set()
        for cls in type(instance).__mro__:
            names.update(vars(cls))
        if type(instance) is ComponentProxy:
            names.update(instance._woven_methods)
            for cls in instance.__class__.__mro__:
                names.update(vars(cls))
        if callable(instance):
            names.add("__call__")
        for method_name in sorted(names):
            selected = [item for item in bindings if item.pointcut.matches_method(method_name)]
            if not selected:
                continue
            descriptor = inspect.getattr_static(instance, method_name, None)
            if isinstance(descriptor, property):
                continue
            method = instance if method_name == "__call__" and inspect.isfunction(instance) else getattr(instance, method_name, None)
            if not callable(method):
                continue
            original = inspect.unwrap(method)
            kind = getattr(method, "__application_invocation_kind__", None) or (
                "stream" if inspect.isasyncgenfunction(original) else
                "sync_stream" if inspect.isgeneratorfunction(original) else
                "async" if inspect.iscoroutinefunction(original) else "sync")
            kinds = {item.pointcut.kind for item in selected if item.pointcut.kind != "auto"}
            if len(kinds) > 1:
                raise AspectError(f"conflicting invocation kinds: {name}.{method_name}")
            kind = next(iter(kinds), kind)
            for aspect in selected:
                for role, hook in zip(("before", "around", "after", "on_error", "finally_"), aspect.hooks):
                    if hook is None:
                        continue
                    if kind in ("sync", "sync_stream") and (inspect.iscoroutinefunction(hook) or inspect.isasyncgenfunction(hook)):
                        raise AspectError("sync methods require synchronous advice")
                    if (inspect.isgeneratorfunction(hook) or inspect.isasyncgenfunction(hook)) and not (
                        role == "around" and kind in ("stream", "sync_stream")
                    ):
                        raise AspectError("generator advice is only valid around a stream")
            methods[method_name] = self.wrapper(name, method_name, method, tuple(selected), kind)
            self.matches.append(AspectMatch(name, method_name, kind, tuple(a.name for a in selected)))
        return ComponentProxy(instance, methods) if methods else instance

    def wrapper(self, component, name, method, advices, kind):
        if kind == "async":
            @functools.wraps(method)
            async def call(*args, **kwargs):
                return await self.call(Invocation(component, name, kind, args, kwargs), method, advices)
        else:
            @functools.wraps(method)
            def call(*args, **kwargs):
                self.check(component)
                invocation = Invocation(component, name, kind, args, kwargs)
                if kind == "stream":
                    return ManagedAsyncStream(self, stream_async(invocation, method, advices))
                if kind == "sync_stream":
                    return ManagedSyncStream(self, stream_sync(invocation, method, advices))
                token = _invocation_owner.set(self.scope)
                try:
                    return invoke_sync(invocation, method, advices)
                finally:
                    _invocation_owner.reset(token)
        call.__application_invocation_kind__ = kind
        return call


class ComponentProxy:
    """Delegating view; lifecycle remains on the original object.

    Self-calls and special operators bypass interception. This is composition,
    not a transparent security membrane or class/identity replacement promise.
    """

    def __init__(self, target, methods):
        object.__setattr__(self, "_woven_target", target)
        object.__setattr__(self, "_woven_methods", methods)

    @property
    def __class__(self):
        return self._woven_target.__class__

    def __getattr__(self, name):
        return self._woven_methods[name] if name in self._woven_methods else getattr(self._woven_target, name)

    def __setattr__(self, name, value):
        setattr(self._woven_target, name, value)

    def __call__(self, *args, **kwargs):
        if "__call__" in self._woven_methods:
            return self._woven_methods["__call__"](*args, **kwargs)
        return self._woven_target(*args, **kwargs)


class ManagedSyncStream:
    def __init__(self, runtime, iterator):
        self.runtime, self.iterator, self.closed = runtime, iterator, False
        runtime.streams.add(self)

    def __iter__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.close()
        except BaseException as cleanup:
            combine(exc, [cleanup])

    def __next__(self):
        if self.closed:
            raise StopIteration
        self.runtime.check()
        token = _invocation_owner.set(self.runtime.scope)
        try:
            return next(self.iterator)
        except BaseException as primary:
            try:
                self.close()
            except BaseException as cleanup:
                combine(primary, [cleanup])
            raise
        finally:
            _invocation_owner.reset(token)

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.iterator.close()
        finally:
            self.runtime.streams.discard(self)


class ManagedAsyncStream:
    def __init__(self, runtime, iterator):
        self.runtime, self.iterator = runtime, iterator
        self.closed, self.busy = False, False
        self.next_task = self.close_task = None
        runtime.streams.add(self)

    def __aiter__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        try:
            await self.aclose()
        except BaseException as cleanup:
            combine(exc, [cleanup])

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        self.runtime.check()
        if self.busy:
            raise AspectError("concurrent stream iteration is unsupported")
        self.busy = True
        self.next_task = self.runtime.spawn(self.iterator.__anext__())
        try:
            return await self.runtime.wait(self.next_task)
        except BaseException as primary:
            try:
                await self.aclose()
            except BaseException as cleanup:
                combine(primary, [cleanup])
            raise
        finally:
            self.busy = False

    async def aclose(self):
        if self.next_task is asyncio.current_task():
            raise AspectError("a stream cannot close itself while advancing")
        if self.close_task is None:
            self.closed = True
            self.close_task = asyncio.create_task(self._close())
        await drain(self.close_task)

    async def _close(self):
        failures = []
        if self.next_task is not None and not self.next_task.done():
            self.next_task.cancel()
            try:
                await drain(self.next_task)
            except asyncio.CancelledError:
                pass
            except BaseException as error:
                failures.append(error)
        try:
            await self.iterator.aclose()
        except BaseException as error:
            failures.append(error)
        finally:
            self.runtime.streams.discard(self)
        combine(None, failures)
