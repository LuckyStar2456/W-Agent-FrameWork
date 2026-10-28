"""Explicit assembly definitions, without imports or factory execution.

This is the common input for future decorator and configuration adapters.
It intentionally does not start an application or manage resource lifetime.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, TypeAlias

from w_agent.kernel.scope import BUILTIN_SCOPE_ORDER
from .aspects import AspectDefinition


class AssemblyDefinitionError(ValueError):
    """An assembly is invalid before component creation can begin."""


def _identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AssemblyDefinitionError(f"{label} must be a nonempty trimmed string")


@dataclass(frozen=True, slots=True)
class ComponentRef:
    """A direct dependency on one explicitly named component."""

    name: str

    def __post_init__(self) -> None:
        _identity(self.name, "dependency name")


@dataclass(frozen=True, slots=True)
class ComponentDefinition:
    """Describe a container-owned factory result, not a created instance.

    Arguments are trusted host values. Mappings are copied and read-only,
    but arbitrary values are neither deep-copied nor serialized. Hooks may
    be synchronous or asynchronous; the execution layer must await them.
    """

    name: str
    factory: Callable[..., Any] = field(repr=False)
    dependencies: Mapping[str, ComponentRef] = field(default_factory=dict)
    arguments: Mapping[str, Any] = field(default_factory=dict, repr=False)
    scope: str = "application"
    initialize: Callable[[Any], Any] | None = field(default=None, repr=False)
    dispose: Callable[[Any], Any] | None = field(default=None, repr=False)
    validate_arguments: Callable[[Mapping[str, Any]], None] | None = field(
        default=None, repr=False,
    )
    inject: Callable[[Any, Mapping[str, Any]], Any] | None = field(
        default=None, repr=False,
    )
    tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _identity(self.name, "component name")
        _identity(self.scope, "scope")
        object.__setattr__(self, "tags", _tags(self.tags))
        if not callable(self.factory):
            raise AssemblyDefinitionError("component factory must be callable")
        if not isinstance(self.dependencies, Mapping):
            raise AssemblyDefinitionError("dependencies must be a mapping")
        if not isinstance(self.arguments, Mapping):
            raise AssemblyDefinitionError("arguments must be a mapping")
        dependencies = dict(self.dependencies)
        arguments = dict(self.arguments)
        for parameter, reference in dependencies.items():
            self._parameter(parameter)
            if not isinstance(reference, ComponentRef):
                raise AssemblyDefinitionError("dependencies must use ComponentRef")
        for parameter in arguments:
            self._parameter(parameter)
        if dependencies.keys() & arguments.keys():
            raise AssemblyDefinitionError(
                "a parameter cannot be both a dependency and an argument"
            )
        for hook in (self.initialize, self.dispose, self.validate_arguments, self.inject):
            if hook is not None and not callable(hook):
                raise AssemblyDefinitionError("lifecycle hooks must be callable")
        object.__setattr__(self, "dependencies", MappingProxyType(dependencies))
        object.__setattr__(self, "arguments", MappingProxyType(arguments))

    @staticmethod
    def _parameter(name: str) -> None:
        if not isinstance(name, str) or not name.isidentifier():
            raise AssemblyDefinitionError("parameter names must be identifiers")


@dataclass(frozen=True, slots=True)
class BorrowedComponent:
    """An existing host/plugin-owned instance with no container cleanup hooks.

    Visibility does not transfer ownership. The external owner must keep the
    instance alive for the declared scope; a registry entry cannot prove that.
    """

    name: str
    instance: Any = field(repr=False)
    scope: str = "application"
    tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _identity(self.name, "component name")
        _identity(self.scope, "scope")
        object.__setattr__(self, "tags", _tags(self.tags))


def _tags(tags) -> frozenset[str]:
    if isinstance(tags, str):
        raise AssemblyDefinitionError("tags must be a collection of identities")
    result = frozenset(tags)
    for tag in result:
        _identity(tag, "tag")
    return result


AssemblyComponent: TypeAlias = ComponentDefinition | BorrowedComponent


@dataclass(frozen=True, slots=True)
class AssemblyPlan:
    """A validated dependency-first sequence, not runtime acceptance evidence.

    Construction validates as well: consumers must not accept forged plans
    whose order bypasses dependency or lifetime checks.
    """

    components: tuple[AssemblyComponent, ...]
    scope_order: tuple[str, ...] = BUILTIN_SCOPE_ORDER
    aspects: tuple[AspectDefinition, ...] = ()

    def __post_init__(self) -> None:
        components = tuple(self.components)
        scope_order = tuple(self.scope_order)
        aspects = _aspects(self.aspects)
        ordered = _order_components(components, scope_order, aspects)
        if tuple(item.name for item in components) != tuple(
            item.name for item in ordered
        ):
            raise AssemblyDefinitionError("plan must be in dependency-first order")
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "scope_order", scope_order)
        object.__setattr__(self, "aspects", aspects)

    @property
    def startup_order(self) -> tuple[str, ...]:
        return tuple(component.name for component in self.components)


def compile_assembly(
    components: Iterable[AssemblyComponent],
    *,
    scope_order: tuple[str, ...] = BUILTIN_SCOPE_ORDER,
    aspects: Iterable[AspectDefinition] = (),
) -> AssemblyPlan:
    """Validate names, direct references, scope capture and dependency order.

    This does not import modules, call component factories, inspect arbitrary
    model parameters, or initialize resources. Input iterables/mappings are
    trusted Python objects, not an execution sandbox. Factory signature and
    configuration-schema validation belong to the later application layer.
    """
    order = tuple(scope_order)
    bound_aspects = _aspects(aspects)
    return AssemblyPlan(_order_components(tuple(components), order, bound_aspects), order, bound_aspects)


def replace_components(
    plan: AssemblyPlan, replacements: Iterable[AssemblyComponent],
) -> AssemblyPlan:
    """Replace named definitions before startup and revalidate the full graph.

    Unknown or repeated names are errors, not implicit additions. Scope order
    and aspects are retained. No objects are created and no live context is
    mutated; this is composition, not hot replacement.
    """
    if not isinstance(plan, AssemblyPlan):
        raise AssemblyDefinitionError("replacement needs an AssemblyPlan")
    selected: dict[str, AssemblyComponent] = {}
    names = set(plan.startup_order)
    for component in replacements:
        if not isinstance(component, (ComponentDefinition, BorrowedComponent)):
            raise AssemblyDefinitionError("replacement must be a component definition")
        if component.name not in names:
            raise AssemblyDefinitionError(f"unknown replacement component: {component.name}")
        if component.name in selected:
            raise AssemblyDefinitionError(f"duplicate replacement component: {component.name}")
        selected[component.name] = component
    return compile_assembly(
        (selected.get(component.name, component) for component in plan.components),
        scope_order=plan.scope_order, aspects=plan.aspects,
    )


def _aspects(aspects) -> tuple[AspectDefinition, ...]:
    result = tuple(aspects)
    if any(not isinstance(item, AspectDefinition) for item in result):
        raise AssemblyDefinitionError("aspects must contain AspectDefinition")
    if len({item.name for item in result}) != len(result):
        raise AssemblyDefinitionError("duplicate aspect identity")
    return tuple(sorted(result, key=lambda item: (item.order, item.name)))


def _order_components(
    components: tuple[AssemblyComponent, ...], scope_order: tuple[str, ...],
    aspects: tuple[AspectDefinition, ...] = (),
) -> tuple[AssemblyComponent, ...]:
    if not scope_order or scope_order[0] != "application":
        raise AssemblyDefinitionError("scope order must begin with application")
    for scope in scope_order:
        _identity(scope, "scope")
    if len(set(scope_order)) != len(scope_order):
        raise AssemblyDefinitionError("scope order contains duplicate dimensions")
    builtin_positions = [
        BUILTIN_SCOPE_ORDER.index(scope)
        for scope in scope_order
        if scope in BUILTIN_SCOPE_ORDER
    ]
    if builtin_positions != sorted(builtin_positions):
        raise AssemblyDefinitionError("built-in scope order cannot be reversed")

    catalog: dict[str, AssemblyComponent] = {}
    for component in components:
        if not isinstance(component, (ComponentDefinition, BorrowedComponent)):
            raise AssemblyDefinitionError("unsupported assembly definition")
        if component.name in catalog:
            raise AssemblyDefinitionError(f"duplicate component: {component.name}")
        if component.scope not in scope_order:
            raise AssemblyDefinitionError(
                f"undeclared scope for component: {component.name}"
            )
        catalog[component.name] = component

    dependencies: dict[str, set[str]] = {}
    advice_owners = {name for aspect in aspects for name in aspect.dependencies}
    for owner in advice_owners:
        if owner not in catalog:
            raise AssemblyDefinitionError(f"missing advice component: {owner}")
    consumers: dict[str, list[str]] = {name: [] for name in catalog}
    for component in components:
        references = list(
            component.dependencies.values()
            if isinstance(component, ComponentDefinition)
            else ()
        )
        if component.name not in advice_owners:
            for aspect in aspects:
                if aspect.pointcut.matches_component(component.name, component.tags):
                    references.extend(ComponentRef(name) for name in aspect.dependencies)
        required: set[str] = set()
        for reference in references:
            dependency = catalog.get(reference.name)
            if dependency is None:
                raise AssemblyDefinitionError(
                    f"missing dependency: {component.name} -> {reference.name}"
                )
            if scope_order.index(dependency.scope) > scope_order.index(component.scope):
                raise AssemblyDefinitionError(
                    f"shorter-lived dependency: {component.name} -> {reference.name}"
                )
            if reference.name not in required:
                consumers[reference.name].append(component.name)
                required.add(reference.name)
        dependencies[component.name] = required

    ready = deque(name for name in catalog if not dependencies[name])
    ordered: list[AssemblyComponent] = []
    while ready:
        name = ready.popleft()
        ordered.append(catalog[name])
        for consumer in consumers[name]:
            dependencies[consumer].remove(name)
            if not dependencies[consumer]:
                ready.append(consumer)
    if len(ordered) != len(catalog):
        unresolved = ", ".join(name for name in catalog if dependencies[name])
        raise AssemblyDefinitionError(
            f"cyclic dependency graph; unresolved components: {unresolved}"
        )
    return tuple(ordered)
