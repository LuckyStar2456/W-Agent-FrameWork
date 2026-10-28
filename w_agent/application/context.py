"""Execute explicit assembly plans with scoped, single-owner lifecycles."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from enum import StrEnum
import inspect
from typing import Any

from w_agent.kernel.scope import ScopePath

from .planning import (
    AssemblyDefinitionError,
    AssemblyPlan,
    BorrowedComponent,
    ComponentDefinition,
)
from .weaving import InvocationRuntime, invocation_owner


class ApplicationState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class ApplicationLifecycleError(RuntimeError):
    """An operation violates the context's lifecycle or ownership boundary."""


_lifecycle_scope: ContextVar[ApplicationScope | None] = ContextVar(
    "w_agent_application_lifecycle_scope", default=None
)


async def _settle(task: asyncio.Task[Any]) -> Any:
    """Drain one task despite repeated caller cancellation, then propagate it."""
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            cancellation = cancellation or error
        except BaseException:
            break  # Retrieve the original result/exception below.
    try:
        result = task.result()
    except BaseException as failure:
        if cancellation is not None and not isinstance(failure, asyncio.CancelledError):
            raise BaseExceptionGroup(
                "application cleanup failed during cancellation", [cancellation, failure]
            ) from None
        raise
    if cancellation is not None:
        raise cancellation
    return result


def _signature_preflight(plan: AssemblyPlan) -> None:
    """Validate all factory/hook call shapes before any instance is created."""
    placeholder = object()
    for component in plan.components:
        if isinstance(component, BorrowedComponent):
            continue
        parameters = {
            name: placeholder
            for name in (*component.arguments, *component.dependencies)
        }
        try:
            inspect.signature(component.factory).bind(**parameters)
            for hook in (component.initialize, component.dispose):
                if hook is not None:
                    if inspect.isgeneratorfunction(hook) or inspect.isasyncgenfunction(hook):
                        raise TypeError("lifecycle hook cannot be a generator")
                    inspect.signature(hook).bind(placeholder)
            if component.inject is not None:
                if (inspect.isgeneratorfunction(component.inject)
                        or inspect.isasyncgenfunction(component.inject)):
                    raise TypeError("injection hook cannot be a generator")
                inspect.signature(component.inject).bind(placeholder, {})
        except (TypeError, ValueError):
            # Do not include values or callable reprs in diagnostics.
            raise AssemblyDefinitionError(
                f"factory or hook signature is incompatible: {component.name}; "
                "use an explicit Python adapter for uninspectable callables"
            ) from None
    # Validate the complete plan (including unopened child scopes) before any
    # factory runs. Validators are synchronous, trusted host code, not coercers.
    for component in plan.components:
        if isinstance(component, BorrowedComponent) or component.validate_arguments is None:
            continue
        try:
            validator = component.validate_arguments
            if inspect.iscoroutinefunction(validator) or inspect.isasyncgenfunction(validator):
                raise TypeError("argument validators must be synchronous")
            result = validator(component.arguments)
            if inspect.iscoroutine(result):
                result.close()
            if result is not None:
                raise TypeError("argument validators must return None")
        except Exception:
            # Never include a custom validator's potentially secret-bearing error.
            raise AssemblyDefinitionError(
                f"configuration validation failed: {component.name}"
            ) from None


class ApplicationScope:
    """A one-shot scope. Obtain child scopes from an active context/scope.

    Factories and hooks are trusted code. Lifecycle operations from a hook
    on the same context tree are rejected to avoid reentrant deadlocks.
    All operations on one tree must use the same asyncio event loop.
    """

    def __init__(
        self, root: ApplicationContext, parent: ApplicationScope | None,
        path: ScopePath,
    ) -> None:
        self._root = root
        self._parent = parent
        self._path = path
        self._state = ApplicationState.NEW
        self._instances: dict[str, Any] = {}
        self._created: list[tuple[ComponentDefinition, Any]] = []
        self._children: dict[tuple[str, str], ApplicationScope] = {}
        self._start_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._start_cancel_requested = False
        self._rollback_failure: BaseException | None = None
        self._invocations = InvocationRuntime(self)
        self._view_ids: list[tuple[int, bool]] = []

    @property
    def path(self) -> ScopePath:
        return self._path

    @property
    def state(self) -> ApplicationState:
        return self._state

    @property
    def kind(self) -> str:
        return self.path.segments[-1].kind

    def _check_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._root._event_loop is None:
            self._root._event_loop = loop
        elif self._root._event_loop is not loop:
            raise ApplicationLifecycleError("context belongs to another event loop")

    def _check_reentrancy(self, *, closing=False) -> None:
        active = _lifecycle_scope.get()
        if active is not None and active._root is self._root:
            raise ApplicationLifecycleError(
                "lifecycle hooks cannot start/close scopes in their own context tree"
            )
        if closing:
            current = invocation_owner()
            while current is not None:
                if current is self:
                    raise ApplicationLifecycleError(
                        "invocations cannot close their own context tree ancestors"
                    )
                current = current._parent

    @property
    def aspect_matches(self):
        """Resolved method matches for this scope, without arguments or values."""
        return tuple(self._invocations.matches)

    def _inside_lifecycle(self):
        active = _lifecycle_scope.get()
        return active is not None and active._root is self._root

    def _expose(self, component, instance):
        owners = {name for aspect in self._root.plan.aspects for name in aspect.dependencies}
        aspects = () if component.name in owners else tuple(
            aspect for aspect in self._root.plan.aspects
            if aspect.pointcut.matches_component(component.name, component.tags)
        )
        exposed = self._invocations.weave(component.name, instance, aspects, self._lookup)
        if exposed is not instance:
            borrowed = isinstance(component, BorrowedComponent)
            if borrowed:
                self._root._borrowed_ids.add(id(exposed))
            else:
                self._root._owned[id(exposed)] = (self, exposed)
            self._view_ids.append((id(exposed), borrowed))
        return exposed

    def _require_active(self) -> None:
        current: ApplicationScope | None = self
        while current is not None:
            if current.state is not ApplicationState.ACTIVE:
                raise ApplicationLifecycleError("scope and ancestors must be active")
            current = current._parent

    def scope(self, kind: str, name: str) -> ApplicationScope:
        """Declare a tracked child; use async with or await child.start()."""
        self._check_loop()
        self._check_reentrancy()
        self._require_active()
        order = self._root.plan.scope_order
        if kind not in order or order.index(kind) <= order.index(self.kind):
            raise ApplicationLifecycleError("child scope must have a shorter lifetime")
        path = self.path.child(kind, name)
        key = (kind, name)
        if key in self._children:
            raise ApplicationLifecycleError("child scope identity already exists")
        child = ApplicationScope(self._root, self, path)
        self._children[key] = child
        return child

    def _lookup(self, name: str) -> Any:
        definition = self._root._catalog.get(name)
        if definition is None:
            raise ApplicationLifecycleError(f"unknown component: {name}")
        owner: ApplicationScope | None = self
        while owner is not None:
            if owner.kind == definition.scope:
                if name not in owner._instances:
                    raise ApplicationLifecycleError(f"component is not initialized: {name}")
                return owner._instances[name]
            owner = owner._parent
        raise ApplicationLifecycleError(f"component scope is not open: {name}")

    def resolve(self, name: str) -> Any:
        """Return a started instance without implicit creation or authorization."""
        self._check_loop()
        self._require_active()
        return self._lookup(name)

    async def start(self) -> ApplicationScope:
        self._check_loop()
        self._check_reentrancy()
        if self._state is ApplicationState.ACTIVE:
            self._require_active()
            return self
        if self._state not in (ApplicationState.NEW, ApplicationState.STARTING):
            raise ApplicationLifecycleError("a closed or failed scope cannot restart")
        if self._parent is not None:
            self._parent._require_active()
        if self._start_task is None:
            self._state = ApplicationState.STARTING
            self._start_task = asyncio.create_task(self._startup())
        try:
            await asyncio.shield(self._start_task)
        except asyncio.CancelledError as cancellation:
            self._cancel_start()
            # Also close if cancellation raced with successful startup, or if
            # the startup task was cancelled before its coroutine first ran.
            cleanup_failure: BaseException | None = None
            try:
                await _settle(self._begin_close())
            except BaseException as cleanup:
                if not isinstance(cleanup, asyncio.CancelledError):
                    cleanup_failure = cleanup
            # A factory may translate cancellation into its own exception.
            # The cancelled waiter never received that result from shield().
            startup_failure = (
                None if self._start_task.cancelled()
                else self._start_task.exception()
            )
            if startup_failure is not None:
                raise BaseExceptionGroup(
                    "application start cancelled and startup failed",
                    [cancellation, startup_failure],
                ) from None
            if cleanup_failure is not None:
                raise BaseExceptionGroup(
                    "application start cancelled and shutdown failed",
                    [cancellation, cleanup_failure],
                ) from None
            raise cancellation
        self._require_active()
        return self

    def _cancel_start(self) -> None:
        if (self._start_task is not None and not self._start_task.done()
                and not self._start_cancel_requested):
            self._start_cancel_requested = True
            self._start_task.cancel()

    async def _startup(self) -> None:
        token = _lifecycle_scope.set(self)
        try:
            if self._parent is None:
                _signature_preflight(self._root.plan)
            local = [c for c in self._root.plan.components if c.scope == self.kind]
            visible = {part.kind for part in self.path}
            for component in local:
                if isinstance(component, ComponentDefinition):
                    for ref in component.dependencies.values():
                        if self._root._catalog[ref.name].scope not in visible:
                            raise ApplicationLifecycleError(
                                f"dependency scope is not open: {component.name} -> {ref.name}"
                            )
            for component in local:
                if self._state is not ApplicationState.STARTING:
                    raise asyncio.CancelledError()
                if isinstance(component, BorrowedComponent):
                    self._instances[component.name] = self._expose(component, component.instance)
                    continue
                arguments = dict(component.arguments)
                arguments.update({
                    parameter: self._lookup(ref.name)
                    for parameter, ref in component.dependencies.items()
                })
                instance = component.factory(**arguments)
                if inspect.isawaitable(instance):
                    instance = await instance
                identity = id(instance)
                if identity in self._root._borrowed_ids or identity in self._root._owned:
                    raise ApplicationLifecycleError(
                        f"factory returned an already owned or borrowed instance: {component.name}"
                    )
                self._root._owned[identity] = (self, instance)
                self._created.append((component, instance))
                # Cleanup responsibility precedes initialization, including failure.
                if self._state is not ApplicationState.STARTING:
                    # A factory may suppress cancellation and still return a
                    # resource. Own and release it, but do not initialize it.
                    raise asyncio.CancelledError()
                if component.inject is not None:
                    result = component.inject(instance, arguments)
                    if inspect.isawaitable(result):
                        await result
                if self._state is not ApplicationState.STARTING:
                    raise asyncio.CancelledError()
                if component.initialize is not None:
                    result = component.initialize(instance)
                    if inspect.isawaitable(result):
                        await result
                self._instances[component.name] = self._expose(component, instance)
            if self._state is not ApplicationState.STARTING:
                raise asyncio.CancelledError()
            self._state = ApplicationState.ACTIVE
        except BaseException as primary:
            if self._state is not ApplicationState.CLOSING:
                self._state = ApplicationState.FAILED
            cleanup = asyncio.create_task(self._dispose_created())
            try:
                await _settle(cleanup)
            except BaseException as secondary:
                self._rollback_failure = secondary
                raise BaseExceptionGroup(
                    "application startup and rollback failed", [primary, secondary]
                ) from None
            raise
        finally:
            _lifecycle_scope.reset(token)

    async def _dispose_created(self) -> None:
        failures: list[BaseException] = []
        try:
            await self._invocations.close()
        except BaseException as failure:
            failures.append(failure)
        while self._created:
            component, instance = self._created.pop()
            try:
                if component.dispose is not None:
                    result = component.dispose(instance)
                    if inspect.isawaitable(result):
                        await result
            except BaseException as failure:
                failures.append(failure)
            finally:
                self._root._owned.pop(id(instance), None)
                self._instances.pop(component.name, None)
        self._instances.clear()
        for identity, borrowed in self._view_ids:
            if borrowed:
                self._root._borrowed_ids.discard(identity)
            else:
                self._root._owned.pop(identity, None)
        self._view_ids.clear()
        if failures:
            raise BaseExceptionGroup("application component disposal failed", failures)

    def _begin_close(self) -> asyncio.Task[None]:
        if self._close_task is None:
            self._state = ApplicationState.CLOSING
            self._cancel_start()
            self._close_task = asyncio.create_task(self._shutdown())
        return self._close_task

    async def close(self) -> None:
        self._check_loop()
        self._check_reentrancy(closing=True)
        await _settle(self._begin_close())

    async def _shutdown(self) -> None:
        token = _lifecycle_scope.set(self)
        failures: list[BaseException] = []
        try:
            if self._start_task is not None:
                try:
                    await _settle(self._start_task)
                except BaseException:
                    # start() reports the primary error including rollback failures.
                    # Disposal still continues for children and remaining resources.
                    pass
            if self._rollback_failure is not None:
                failures.append(self._rollback_failure)
            try:
                await self._invocations.close()
            except BaseException as failure:
                failures.append(failure)
            children = tuple(reversed(tuple(self._children.values())))
            for child in children:
                try:
                    await _settle(child._begin_close())
                except BaseException as failure:
                    failures.append(failure)
            try:
                await self._dispose_created()
            except BaseException as failure:
                failures.append(failure)
        finally:
            self._state = ApplicationState.CLOSED
            if self._parent is not None:
                segment = self.path.segments[-1]
                self._parent._children.pop((segment.kind, segment.value), None)
            _lifecycle_scope.reset(token)
        if failures:
            raise BaseExceptionGroup("application scope shutdown failed", failures)

    async def __aenter__(self) -> ApplicationScope:
        return await self.start()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        try:
            await self.close()
        except BaseException as cleanup:
            if exc is not None:
                raise BaseExceptionGroup(
                    "application body and shutdown failed", [exc, cleanup]
                ) from None
            raise


class ApplicationContext(ApplicationScope):
    """A local application owning one immutable plan and its scope tree.

    Components are eager within each opened scope. No model, default Loop,
    frontend, plugin import, hidden task supervisor or automatic close-method
    discovery is required. Host code must await its own work before closing.
    """

    def __init__(self, plan: AssemblyPlan, *, name: str = "default") -> None:
        if not isinstance(plan, AssemblyPlan):
            raise TypeError("ApplicationContext requires an AssemblyPlan")
        self._plan = plan
        self._catalog = {component.name: component for component in plan.components}
        self._owned: dict[int, tuple[ApplicationScope, Any]] = {}
        self._borrowed_ids = {
            id(component.instance) for component in plan.components
            if isinstance(component, BorrowedComponent)
        }
        self._event_loop: asyncio.AbstractEventLoop | None = None
        super().__init__(self, None, ScopePath.application(name))

    @property
    def plan(self) -> AssemblyPlan:
        return self._plan
