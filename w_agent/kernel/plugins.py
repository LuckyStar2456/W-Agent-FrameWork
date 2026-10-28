"""Plugin specifications, lifecycle ownership, and dependency management."""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from builtins import ExceptionGroup
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Protocol, TypeVar

from packaging.version import InvalidVersion, Version

from .events import EventDispatcher, Listener
from .exceptions import PluginDependencyError, PluginLoadError, PluginUnloadError
from .registry import Contribution, Registration, Registry
from .scope import ScopePath


Disposer = Callable[[], None | Awaitable[None]]
Setup = Callable[["PluginContext"], Any]
logger = logging.getLogger(__name__)
_T = TypeVar("_T")


async def _drain_cleanup(operation: Awaitable[_T]) -> _T:
    """Finish owned cleanup despite repeated caller cancellation, then propagate it.

    This deliberately supplies no timeout: trusted plugin cleanup owns its I/O
    bounds. The task is always observed; cancellation never leaves it detached.
    """
    task = asyncio.ensure_future(operation)
    interrupted: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            interrupted = interrupted or error
        except BaseException:
            break
    try:
        result = task.result()
    except BaseException as error:
        if interrupted is not None:
            if error is not interrupted:
                interrupted.add_note(f"cleanup finished with {type(error).__name__}")
            raise interrupted from error
        raise
    if interrupted is not None:
        raise interrupted
    return result


class PluginState(StrEnum):
    """Lifecycle state of one plugin instance."""

    DISCOVERED = "discovered"
    RESOLVING = "resolving"
    LOADING = "loading"
    ACTIVE = "active"
    FAILED = "failed"
    QUIESCING = "quiescing"
    UNLOADING = "unloading"
    DISPOSED = "disposed"


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    """A capability a plugin promises to register when loaded."""

    capability: str
    name: str = "default"
    version: str = "0"
    exclusive: bool = False

    def __post_init__(self) -> None:
        if not self.capability or not self.capability.strip():
            raise ValueError("provided capability must not be empty")
        try:
            Version(self.version)
        except InvalidVersion as exc:
            raise ValueError(f"invalid capability version: {self.version}") from exc


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    """A required or optional capability used by a plugin."""

    capability: str
    version: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.capability or not self.capability.strip():
            raise ValueError("required capability must not be empty")


@dataclass(frozen=True, slots=True)
class PluginSpec:
    """Stable metadata used to resolve and load a plugin."""

    name: str
    version: str
    api_version: str = "2"
    provides: tuple[CapabilityDeclaration, ...] = ()
    requires: tuple[CapabilityRequirement, ...] = ()
    optional: tuple[CapabilityRequirement, ...] = ()
    conflicts: tuple[str, ...] = ()
    scope: ScopePath = field(default_factory=ScopePath.application)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("plugin name must not be empty")
        try:
            Version(self.version)
        except InvalidVersion as exc:
            raise ValueError(f"invalid plugin version: {self.version}") from exc
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class Plugin(Protocol):
    """Runtime plugin interface consumed by ``PluginManager``."""

    spec: PluginSpec

    async def load(self, context: "PluginContext") -> None:
        """Register services and effects."""

    async def unload(self) -> None:
        """Release plugin-owned state not registered as an effect."""


class EffectScope:
    """Own a LIFO collection of sync or async cleanup effects."""

    def __init__(self) -> None:
        self._disposers: list[Disposer] = []
        self._closed = False
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    def add(self, disposer: Disposer) -> None:
        """Add a disposer while the scope is active."""

        if self._closed:
            raise RuntimeError("effect scope is already closed")
        if not callable(disposer):
            raise TypeError("disposer must be callable")
        self._disposers.append(disposer)

    async def close(self) -> None:
        """Run every disposer once in reverse registration order."""

        async with self._lock:
            if self._cleanup_task is None:
                self._closed = True
                disposers = tuple(reversed(self._disposers))
                self._disposers.clear()
                self._cleanup_task = asyncio.create_task(self._dispose(disposers))
            task = self._cleanup_task
        if task is asyncio.current_task():
            return  # A disposer may idempotently close its own scope.
        await _drain_cleanup(task)

    @staticmethod
    async def _dispose(disposers: tuple[Disposer, ...]) -> None:
        failures: list[Exception] = []
        cancelled: asyncio.CancelledError | None = None
        for disposer in disposers:
            try:
                result = disposer()
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError as error:
                cancelled = cancelled or error
            except Exception as exc:  # noqa: BLE001 - continue cleanup
                failures.append(exc)
        if cancelled is not None:
            if failures:
                cancelled.add_note(f"{len(failures)} other disposer(s) failed")
            raise cancelled
        if failures:
            raise ExceptionGroup("plugin effect cleanup failed", failures)


class PluginContext:
    """Public capabilities available while a plugin is loading."""

    def __init__(
        self,
        *,
        spec: PluginSpec,
        registry: Registry,
        events: EventDispatcher,
        effects: EffectScope,
        config: Mapping[str, Any],
    ) -> None:
        self.spec = spec
        self.registry = registry
        self.events = events
        self.scope = spec.scope
        self.config = MappingProxyType(dict(config))
        self._effects = effects

    def effect(self, disposer: Disposer) -> None:
        """Bind an arbitrary cleanup operation to the plugin lifecycle."""

        self._effects.add(disposer)

    def register(
        self,
        capability: str,
        provider: Any,
        *,
        name: str = "default",
        version: str = "0",
        scope: ScopePath | None = None,
        exclusive: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> Registration:
        """Register a provider and bind its removal to plugin unload."""

        registration = self.registry.register(
            Contribution(
                capability=capability,
                provider=provider,
                name=name,
                version=version,
                scope=scope or self.scope,
                exclusive=exclusive,
                metadata=metadata or {},
                owner=self.spec.name,
            )
        )
        self.effect(registration.dispose)
        return registration

    def on(self, event: str, listener: Listener) -> Registration:
        """Register an event listener owned by this plugin."""

        registration = self.events.on(event, listener)
        self.effect(registration.dispose)
        return registration


class FunctionPlugin:
    """Adapt a setup function to the plugin lifecycle protocol."""

    def __init__(self, spec: PluginSpec, setup: Setup) -> None:
        self.spec = spec
        self._setup = setup
        self._returned_disposer: Disposer | None = None

    async def load(self, context: PluginContext) -> None:
        result = self._setup(context)
        if inspect.isawaitable(result):
            result = await result
        if result is not None:
            if not callable(result):
                raise TypeError("plugin setup must return a disposer or None")
            self._returned_disposer = result
            context.effect(result)

    async def unload(self) -> None:
        # The returned disposer is owned and called by EffectScope.
        self._returned_disposer = None


@dataclass(slots=True)
class PluginRecord:
    """Observable lifecycle record for one loaded plugin instance."""

    plugin: Plugin
    state: PluginState = PluginState.DISCOVERED
    error: BaseException | None = None
    effects: EffectScope | None = None

    @property
    def spec(self) -> PluginSpec:
        return self.plugin.spec


class PluginHandle:
    """Handle for an installed plugin instance."""

    def __init__(
        self, manager: "PluginManager", name: str, *, _record: PluginRecord | None = None
    ) -> None:
        self._manager = manager
        self.name = name
        self._record = _record if _record is not None else manager.record(name)

    @property
    def state(self) -> PluginState:
        return self._record.state

    async def unload(self) -> None:
        await self._manager.unload(self.name, _expected_record=self._record)


@dataclass(frozen=True, slots=True)
class PluginReplacementPlan:
    """Process-local preview; approval does not authorize imports or installation."""

    plan_id: str
    previous: PluginSpec
    replacement: PluginSpec
    unload_order: tuple[str, ...]


class PluginReplacementError(RuntimeError):
    """A replacement was rejected or could not finish; inspect manager records."""


class PluginManager:
    """Resolve dependencies and own plugin lifecycle transitions."""

    def __init__(
        self,
        registry: Registry | None = None,
        events: EventDispatcher | None = None,
        *,
        api_version: str = "2",
    ) -> None:
        self.registry = registry or Registry()
        self.events = events or EventDispatcher()
        self.api_version = api_version
        self._records: dict[str, PluginRecord] = {}
        self._lock = asyncio.Lock()
        self._replacement_plans: dict[str, tuple[Any, ...]] = {}

    def record(self, name: str) -> PluginRecord:
        """Return the current lifecycle record for ``name``."""

        try:
            return self._records[name]
        except KeyError as exc:
            raise KeyError(f"plugin {name!r} is unknown") from exc

    def records(self) -> tuple[PluginRecord, ...]:
        """Return a stable snapshot of known plugin records."""

        return tuple(self._records.values())

    async def __aenter__(self) -> "PluginManager":
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close()

    async def load(
        self,
        plugin_instance: Plugin | Setup,
        *,
        config: Mapping[str, Any] | None = None,
    ) -> PluginHandle:
        """Load a plugin transactionally after resolving dependencies."""

        plugin_object = coerce_plugin(plugin_instance)
        spec = plugin_object.spec
        async with self._lock:
            record = await self._load_locked(plugin_object, config=config)

        try:
            await self._publish_lifecycle("plugin/loaded", record)
        except asyncio.CancelledError as cancellation:
            # No handle was delivered; release the committed record as well.
            try:
                await _drain_cleanup(self.unload(spec.name, _expected_record=record))
            except (Exception, asyncio.CancelledError) as cleanup_error:
                cancellation.add_note(f"load notification cleanup finished with {type(cleanup_error).__name__}")
            raise cancellation
        return PluginHandle(self, spec.name, _record=record)

    async def _load_locked(
        self, plugin_object: Plugin, *, config: Mapping[str, Any] | None = None
    ) -> PluginRecord:
        spec = plugin_object.spec
        current = self._records.get(spec.name)
        if current and current.state not in {
            PluginState.DISPOSED,
            PluginState.FAILED,
        }:
            raise PluginLoadError(f"plugin {spec.name!r} is already loaded")

        record = PluginRecord(plugin_object)
        self._records[spec.name] = record
        try:
            record.state = PluginState.RESOLVING
            self._resolve_dependencies(spec)
            record.state = PluginState.LOADING
            effects = EffectScope()
            record.effects = effects
            context = PluginContext(
                spec=spec,
                registry=self.registry,
                events=self.events,
                effects=effects,
                config=config or {},
            )
            await plugin_object.load(context)
            self._verify_provides(spec)
            record.state = PluginState.ACTIVE
        except BaseException as exc:  # cleanup also on task cancellation
            record.error = exc
            try:
                await _drain_cleanup(self._rollback_load(record))
            except asyncio.CancelledError as cancellation:
                if not isinstance(exc, asyncio.CancelledError):
                    cancellation.add_note(f"plugin load failed with {type(exc).__name__}")
                    raise cancellation from exc
            except Exception as cleanup_error:  # noqa: BLE001
                exc.add_note(f"partial plugin cleanup failed: {type(cleanup_error).__name__}")
            if not isinstance(exc, Exception):
                raise
            raise PluginLoadError(f"plugin {spec.name!r} failed to load") from exc
        return record

    @staticmethod
    async def _rollback_load(record: PluginRecord) -> None:
        failures: list[Exception] = []
        cancelled: asyncio.CancelledError | None = None
        try:
            try:
                await record.plugin.unload()
            except asyncio.CancelledError as error:
                cancelled = error
            except Exception as error:
                failures.append(error)
            if record.effects is not None:
                try:
                    await record.effects.close()
                except asyncio.CancelledError as error:
                    cancelled = cancelled or error
                except Exception as error:
                    failures.append(error)
        finally:
            record.state = PluginState.FAILED
        if cancelled is not None:
            if failures:
                cancelled.add_note(f"{len(failures)} other partial cleanup operation(s) failed")
            raise cancelled
        if failures:
            raise ExceptionGroup("partial plugin cleanup failed", failures)

    async def unload(
        self, name: str, *, _expected_record: PluginRecord | None = None
    ) -> None:
        """Unload active dependents, then the requested plugin."""

        unloaded: list[PluginRecord] = []
        try:
            async with self._lock:
                if _expected_record is not None and self.record(name) is not _expected_record:
                    raise PluginUnloadError("stale plugin handle cannot unload a replacement")
                await _drain_cleanup(self._unload_locked(name, visiting=set(), unloaded=unloaded))
        finally:
            for record in unloaded:
                await _drain_cleanup(self._publish_lifecycle("plugin/unloaded", record))

    def _replacement_snapshot(self) -> tuple[Any, ...]:
        return (
            self.api_version,
            tuple((id(record), record.state, id(record.spec)) for record in self.records()),
            tuple(id(item) for item in self.registry._items()),
        )

    def _replacement_unload_order(self, name: str) -> tuple[str, ...]:
        ordered: list[str] = []
        visiting: set[str] = set()

        def visit(current: str) -> None:
            if current in visiting:
                raise PluginReplacementError("cyclic replacement dependency")
            if current in ordered:
                return
            visiting.add(current)
            provided = {item.capability for item in self.record(current).spec.provides}
            for candidate in self.records():
                if (
                    candidate.state == PluginState.ACTIVE
                    and candidate.spec.name != current
                    and any(item.capability in provided for item in candidate.spec.requires)
                ):
                    visit(candidate.spec.name)
            visiting.remove(current)
            ordered.append(current)

        visit(name)
        return tuple(ordered)

    def _preflight_replacement(self, spec: PluginSpec, removed: tuple[str, ...]) -> None:
        # Simulate post-unload resolution and declared registration without running code.
        registry = Registry()
        for contribution in self.registry._items():
            if contribution.owner not in removed:
                registry.register(contribution)
        checker = PluginManager(registry, api_version=self.api_version)
        checker._resolve_dependencies(spec)
        for declaration in spec.provides:
            registry.register(Contribution(
                capability=declaration.capability, provider=None,
                name=declaration.name, version=declaration.version,
                scope=spec.scope, exclusive=declaration.exclusive, owner=spec.name,
            ))
        for record in self.records():
            if record.state == PluginState.ACTIVE and record.spec.name not in removed:
                checker._resolve_dependencies(record.spec)

    async def plan_replacement(self, replacement: Plugin | Setup) -> PluginReplacementPlan:
        """Preview an already constructed same-name plugin without executing setup.

        Consumers in unload_order stay disposed after replacement. The host must
        stop runs and retain no live snapshots before approving this plan.
        """
        candidate = coerce_plugin(replacement)
        async with self._lock:
            current = self.record(candidate.spec.name)
            if current.state != PluginState.ACTIVE:
                raise PluginReplacementError("replacement requires an active previous plugin")
            if candidate is current.plugin:
                raise PluginReplacementError("replacement requires a fresh plugin instance")
            order = self._replacement_unload_order(candidate.spec.name)
            self._preflight_replacement(candidate.spec, order)
            plan = PluginReplacementPlan(uuid.uuid4().hex, current.spec, candidate.spec, order)
            # Only the latest preview is executable; avoids retaining arbitrary code forever.
            self._replacement_plans.clear()
            self._replacement_plans[plan.plan_id] = (
                plan, candidate, self._replacement_snapshot(),
                (*self.records(), *self.registry._items()),
            )
            return plan

    async def replace(
        self, plan: PluginReplacementPlan, *, expected_plan_id: str,
        host_quiescent: bool = False, config: Mapping[str, Any] | None = None,
    ) -> PluginHandle:
        """Consume an approved plan while holding the lifecycle lock.

        This is not hot migration or transactional rollback of external effects.
        On cleanup failure no new setup runs; on setup failure the old version and
        consumers remain stopped. Explicit host recovery is required.
        """
        if host_quiescent is not True:
            raise PluginReplacementError("host must explicitly confirm quiescence")
        unloaded: list[PluginRecord] = []
        loaded: PluginRecord | None = None
        try:
            async with self._lock:
                approved = self._replacement_plans.get(expected_plan_id)
                if approved is None or approved[0] is not plan:
                    raise PluginReplacementError("unknown, stale, or unapproved replacement plan")
                _, candidate, snapshot, _retained = approved
                if snapshot != self._replacement_snapshot() or candidate.spec != plan.replacement:
                    raise PluginReplacementError("plugin or registry changed; create a new plan")
                self._preflight_replacement(candidate.spec, plan.unload_order)
                self._replacement_plans.clear()
                await _drain_cleanup(self._unload_locked(plan.previous.name, set(), unloaded))
                loaded = await self._load_locked(candidate, config=config)
        finally:
            try:
                for record in unloaded:
                    await self._publish_lifecycle("plugin/unloaded", record)
                if loaded is not None:
                    await self._publish_lifecycle("plugin/loaded", loaded)
            except asyncio.CancelledError as cancellation:
                if loaded is not None:
                    try:
                        await _drain_cleanup(self.unload(loaded.spec.name, _expected_record=loaded))
                    except (Exception, asyncio.CancelledError) as cleanup_error:
                        cancellation.add_note(f"replacement notification cleanup finished with {type(cleanup_error).__name__}")
                raise cancellation
        return PluginHandle(self, plan.replacement.name, _record=loaded)

    def discard_replacement(self, plan: PluginReplacementPlan) -> None:
        """Release only this exact pending preview; never invalidate a newer plan."""
        pending = self._replacement_plans.get(plan.plan_id)
        if pending is not None and pending[0] is plan:
            del self._replacement_plans[plan.plan_id]

    async def close(self) -> None:
        """Unload every active plugin and release all owned effects."""

        await _drain_cleanup(self._close_all())

    async def _close_all(self) -> None:
        failures: list[Exception] = []
        cancelled: asyncio.CancelledError | None = None
        blocked: set[str] = set()

        while True:
            active = [
                record.spec.name
                for record in reversed(self.records())
                if record.state == PluginState.ACTIVE and record.spec.name not in blocked
            ]
            if not active:
                break
            name = active[0]
            before = tuple((id(record), record.state) for record in self.records())
            try:
                await self.unload(name)
            except asyncio.CancelledError as error:
                cancelled = cancelled or error
            except Exception as error:
                failures.append(error)
            # A malformed dependency cycle must not cause an infinite cleanup loop.
            if before == tuple((id(record), record.state) for record in self.records()):
                blocked.add(name)
        if cancelled is not None:
            if failures:
                cancelled.add_note(f"{len(failures)} other plugin close operation(s) failed")
            raise cancelled
        if failures:
            failures[0].add_note(f"manager cleanup completed with {len(failures)} failure(s)")
            raise failures[0]

    async def _unload_locked(
        self,
        name: str,
        visiting: set[str],
        unloaded: list[PluginRecord],
    ) -> None:
        record = self.record(name)
        if record.state in {PluginState.DISPOSED, PluginState.FAILED}:
            return
        if name in visiting:
            raise PluginUnloadError(f"cyclic plugin unload dependency at {name!r}")
        visiting.add(name)

        provided = {item.capability for item in record.spec.provides}
        dependents = [
            candidate.spec.name
            for candidate in self._records.values()
            if candidate.state == PluginState.ACTIVE
            and candidate.spec.name != name
            and any(
                requirement.capability in provided
                for requirement in candidate.spec.requires
            )
        ]
        for dependent in dependents:
            await self._unload_locked(dependent, visiting, unloaded)

        failures: list[Exception] = []
        cancelled: asyncio.CancelledError | None = None
        record.state = PluginState.QUIESCING
        quiesce = getattr(record.plugin, "quiesce", None)
        if quiesce is not None:
            try:
                result = quiesce()
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError as error:
                cancelled = error
            except Exception as exc:  # noqa: BLE001
                failures.append(exc)

        record.state = PluginState.UNLOADING
        try:
            await record.plugin.unload()
        except asyncio.CancelledError as error:
            cancelled = cancelled or error
        except Exception as exc:  # noqa: BLE001
            failures.append(exc)
        if record.effects is not None:
            try:
                await record.effects.close()
            except asyncio.CancelledError as error:
                cancelled = cancelled or error
            except Exception as exc:  # noqa: BLE001
                failures.append(exc)
        record.state = PluginState.DISPOSED
        visiting.remove(name)
        unloaded.append(record)

        if cancelled is not None:
            if failures:
                cancelled.add_note(f"{len(failures)} other unload operation(s) failed")
            record.error = cancelled
            raise cancelled
        if failures:
            error = PluginUnloadError(f"plugin {name!r} did not unload cleanly")
            error.__cause__ = ExceptionGroup("plugin unload failures", failures)
            record.error = error
            raise error

    async def _publish_lifecycle(self, event: str, record: PluginRecord) -> None:
        try:
            await self.events.publish(event, record)
        except ExceptionGroup:
            logger.exception("plugin lifecycle listener failed", extra={"event": event})

    def _resolve_dependencies(self, spec: PluginSpec) -> None:
        if spec.api_version != self.api_version:
            raise PluginDependencyError(
                f"plugin {spec.name!r} requires kernel API {spec.api_version!r}; "
                f"running API is {self.api_version!r}"
            )
        for conflict in spec.conflicts:
            if self.registry.list(conflict, spec.scope):
                raise PluginDependencyError(
                    f"plugin {spec.name!r} conflicts with capability {conflict!r}"
                )
        for requirement in spec.requires:
            try:
                self.registry.resolve_contribution(
                    requirement.capability,
                    spec.scope,
                    name=requirement.name,
                    version=requirement.version,
                )
            except Exception as exc:  # noqa: BLE001 - normalize dependency error
                raise PluginDependencyError(
                    f"plugin {spec.name!r} requires {requirement.capability!r}"
                ) from exc

    def _verify_provides(self, spec: PluginSpec) -> None:
        for declaration in spec.provides:
            contribution = self.registry.resolve_contribution(
                declaration.capability,
                spec.scope,
                name=declaration.name,
                version=f"=={declaration.version}",
            )
            if contribution.owner != spec.name:
                raise PluginDependencyError(
                    f"plugin {spec.name!r} did not register declared capability "
                    f"{declaration.capability!r}"
                )


def plugin(
    *,
    name: str,
    version: str,
    api_version: str = "2",
    provides: tuple[CapabilityDeclaration, ...] = (),
    requires: tuple[CapabilityRequirement, ...] = (),
    optional: tuple[CapabilityRequirement, ...] = (),
    conflicts: tuple[str, ...] = (),
    scope: ScopePath | None = None,
) -> Callable[[Setup], Setup]:
    """Attach a ``PluginSpec`` to a setup function."""

    spec = PluginSpec(
        name=name,
        version=version,
        api_version=api_version,
        provides=provides,
        requires=requires,
        optional=optional,
        conflicts=conflicts,
        scope=scope or ScopePath.application(),
    )

    def decorate(setup: Setup) -> Setup:
        setattr(setup, "__w_agent_plugin_spec__", spec)
        return setup

    return decorate


def coerce_plugin(candidate: Plugin | Setup) -> Plugin:
    """Convert a plugin object or decorated setup function into ``Plugin``."""

    if (
        isinstance(getattr(candidate, "spec", None), PluginSpec)
        and callable(getattr(candidate, "load", None))
        and callable(getattr(candidate, "unload", None))
    ):
        return candidate
    spec = getattr(candidate, "__w_agent_plugin_spec__", None)
    if callable(candidate) and isinstance(spec, PluginSpec):
        return FunctionPlugin(spec, candidate)
    raise TypeError("expected a Plugin or a function decorated with @plugin")
