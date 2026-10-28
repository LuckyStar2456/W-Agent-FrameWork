"""Metadata-only declarations for managed configuration factories."""

from dataclasses import dataclass, field
from typing import Any, Callable

from w_agent.core.decorators import Component

from .planning import AssemblyDefinitionError, ComponentRef


class Configuration(Component):
    """A managed component whose @Bean methods contribute owned definitions."""

    def __call__(self, target):
        if not isinstance(target, type):
            raise AssemblyDefinitionError("Configuration requires a class")
        super().__call__(target)
        target.__configuration__ = True
        return target


@dataclass(frozen=True, slots=True)
class _BeanOptions:
    name: str | None
    scope: str
    provides: type | None
    initialize: Callable[[Any], Any] | None = field(repr=False)
    dispose: Callable[[Any], Any] | None = field(repr=False)


def Bean(target=None, *, name=None, scope="application", provides=None,
         initialize=None, dispose=None):
    """Mark a module factory or configuration instance method, without calling it.

    Direct Python calls stay ordinary calls, not intercepted container lookups.
    Request another bean as an injected method parameter instead.
    """
    if name is not None:
        ComponentRef(name)
    ComponentRef(scope)
    if provides is not None and not isinstance(provides, type):
        raise AssemblyDefinitionError("Bean provides must be a runtime type")
    for hook in (initialize, dispose):
        if hook is not None and not callable(hook):
            raise AssemblyDefinitionError("Bean lifecycle hooks must be callable")

    def decorate(function):
        if not callable(function) or isinstance(function, type):
            raise AssemblyDefinitionError("Bean requires a function")
        function.__bean_options__ = _BeanOptions(name, scope, provides, initialize, dispose)
        return function

    return decorate if target is None else decorate(target)
