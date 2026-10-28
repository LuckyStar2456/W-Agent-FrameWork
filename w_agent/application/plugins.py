"""Bridge the existing plugin registry to application-owned components."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass

from w_agent.kernel import (
    CapabilityDeclaration,
    CapabilityRequirement,
    PluginContext,
    PluginSpec,
    Registration,
    ScopePath,
)
from w_agent.kernel.scope import BUILTIN_SCOPE_ORDER

from .context import ApplicationContext, ApplicationLifecycleError, ApplicationState
from .aspects import AspectDefinition
from .planning import (
    AssemblyComponent,
    AssemblyDefinitionError,
    BorrowedComponent,
    ComponentRef,
    compile_assembly,
)


@dataclass(frozen=True, slots=True)
class CapabilityImport:
    """Borrow an existing registry contribution under a component identity.

    Required capabilities are also declared to PluginManager, so it can unload
    this consuming application before the plugin providing the capability.
    """

    component: str
    requirement: CapabilityRequirement

    def __post_init__(self) -> None:
        ComponentRef(self.component)
        if not isinstance(self.requirement, CapabilityRequirement):
            raise TypeError("capability import requires CapabilityRequirement")


@dataclass(frozen=True, slots=True)
class CapabilityExport:
    """Expose a started application component without transferring ownership."""

    component: str
    declaration: CapabilityDeclaration

    def __post_init__(self) -> None:
        ComponentRef(self.component)
        if not isinstance(self.declaration, CapabilityDeclaration):
            raise TypeError("capability export requires CapabilityDeclaration")


class ApplicationPlugin:
    """An ordinary plugin whose instances belong to ApplicationContext.

    Use PluginManager.load(), not direct load/unload calls. Definitions are
    supplied by trusted Python code and frozen before loading. Plugin JSON
    config is rejected rather than silently ignored; configuration adapters
    must first produce the same explicit definitions. Stop host-owned work
    before unloading: raw object references are not revocable execution leases.
    """

    def __init__(
        self,
        *,
        name: str,
        version: str,
        components: Iterable[AssemblyComponent],
        imports: Iterable[CapabilityImport] = (),
        exports: Iterable[CapabilityExport] = (),
        scope: ScopePath | None = None,
        api_version: str = "2",
        aspects: Iterable[AspectDefinition] = (),
        scope_order: tuple[str, ...] = BUILTIN_SCOPE_ORDER,
    ) -> None:
        self._components = tuple(components)
        self._aspects = tuple(aspects)
        self._scope_order = tuple(scope_order)
        self._imports = tuple(imports)
        self._exports = tuple(exports)
        if any(not isinstance(item, CapabilityImport) for item in self._imports):
            raise TypeError("imports must contain CapabilityImport")
        if any(not isinstance(item, CapabilityExport) for item in self._exports):
            raise TypeError("exports must contain CapabilityExport")
        self._spec = PluginSpec(
            name=name, version=version, api_version=api_version,
            scope=scope if scope is not None else ScopePath.application(),
            requires=tuple(item.requirement for item in self._imports),
            provides=tuple(item.declaration for item in self._exports),
        )
        # Check the static graph without querying a registry or creating objects.
        preview = compile_assembly([
            *self._components,
            *(BorrowedComponent(item.component, object()) for item in self._imports),
        ], aspects=self._aspects, scope_order=self._scope_order)
        catalog = {component.name: component for component in preview.components}
        exported_keys: set[tuple[str, str, str]] = set()
        for item in self._exports:
            definition = catalog.get(item.component)
            if definition is None or definition.scope != "application":
                raise AssemblyDefinitionError(
                    "capability exports require an application-scoped component"
                )
            declaration = item.declaration
            key = (declaration.capability, declaration.name, declaration.version)
            if key in exported_keys:
                raise AssemblyDefinitionError("duplicate capability export")
            exported_keys.add(key)
        self._application: ApplicationContext | None = None
        self._registrations: list[Registration] = []
        self._accepting = False
        self._loaded_once = False

    @property
    def spec(self) -> PluginSpec:
        return self._spec

    @property
    def application(self) -> ApplicationContext:
        if (not self._accepting or self._application is None
                or self._application.state is not ApplicationState.ACTIVE):
            raise ApplicationLifecycleError("application plugin is not active")
        return self._application

    async def load(self, context: PluginContext) -> None:
        """Resolve borrowed dependencies, start, then publish owned instances."""
        if self._loaded_once:
            raise ApplicationLifecycleError("create a new application plugin to reload")
        if context.spec != self.spec:
            raise ApplicationLifecycleError("plugin context does not match its definition")
        if context.config:
            raise AssemblyDefinitionError(
                "compile plugin configuration into component definitions before loading"
            )
        self._loaded_once = True
        borrowed = []
        for item in self._imports:
            requirement = item.requirement
            provider = context.registry.resolve(
                requirement.capability, context.scope,
                name=requirement.name, version=requirement.version,
            )
            borrowed.append(BorrowedComponent(item.component, provider))
        application = ApplicationContext(
            compile_assembly([*self._components, *borrowed], aspects=self._aspects,
                             scope_order=self._scope_order), name=self.spec.name,
        )
        self._application = application
        # The plugin effect is the sole owner of the application as a whole.
        # Register before startup, so failed/cancelled loading also closes it.
        context.effect(self._close_application)
        await application.start()
        for item in self._exports:
            declaration = item.declaration
            registration = context.register(
                declaration.capability, application.resolve(item.component),
                name=declaration.name, version=declaration.version,
                exclusive=declaration.exclusive,
            )
            self._registrations.append(registration)
        self._accepting = True

    def quiesce(self) -> None:
        """Withdraw discovery immediately; do not close exported objects here."""
        self._accepting = False
        for registration in reversed(self._registrations):
            registration.dispose()
        self._registrations.clear()

    async def unload(self) -> None:
        """Effects own cleanup, including failed loads with partial exports.

        A rejected load in a second manager must not quiesce the original
        owner's application. Only the registered effect owns that lifetime.
        """

    async def _close_application(self) -> None:
        self.quiesce()
        if self._application is None:
            return
        try:
            await self._application.close()
        except BaseExceptionGroup as failure:
            cancelled, remaining = failure.split(asyncio.CancelledError)
            # The existing plugin lifecycle knows Exception + CancelledError,
            # not a BaseExceptionGroup containing cancellation. Preserve that
            # full group as the cause while allowing its cleanup to continue.
            if cancelled is not None and (
                remaining is None or isinstance(remaining, Exception)
            ):
                raise asyncio.CancelledError(
                    "application plugin cleanup was cancelled"
                ) from failure
            raise
