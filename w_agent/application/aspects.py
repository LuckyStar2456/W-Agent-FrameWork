"""Public component-oriented aspect contracts and metadata-only declarations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from types import MappingProxyType
from typing import Any

from w_agent.core.decorators import Component


class AspectError(RuntimeError):
    """Invalid weaving or invocation contract; never an authorization boundary."""


@dataclass(frozen=True, slots=True)
class MethodPointcut:
    component: str = "*"
    methods: tuple[str, ...] = ("*",)
    tags: frozenset[str] = frozenset()
    kind: str = "auto"

    def __post_init__(self):
        if not isinstance(self.component, str) or not self.component:
            raise ValueError("pointcut component must be a nonempty pattern")
        if isinstance(self.methods, str) or not self.methods:
            raise ValueError("methods must be a nonempty sequence of patterns")
        if any(not isinstance(item, str) or not item for item in self.methods):
            raise ValueError("invalid method pattern")
        if isinstance(self.tags, str) or any(not isinstance(t, str) or not t for t in self.tags):
            raise ValueError("tags must be string identities")
        if self.kind not in ("auto", "sync", "async", "stream", "sync_stream"):
            raise ValueError("unsupported invocation kind")
        object.__setattr__(self, "methods", tuple(self.methods))
        object.__setattr__(self, "tags", frozenset(self.tags))

    def matches_component(self, name: str, tags: frozenset[str]) -> bool:
        return fnmatchcase(name, self.component) and self.tags <= tags

    def matches_method(self, name: str) -> bool:
        return (not name.startswith("_") or (name == "__call__" and "__call__" in self.methods)) and any(
            fnmatchcase(name, pattern) for pattern in self.methods
        )


@dataclass(frozen=True, slots=True)
class AdviceRef:
    component: str
    method: str

    def __post_init__(self):
        if not isinstance(self.component, str) or not self.component.strip():
            raise ValueError("advice requires a component identity")
        if not isinstance(self.method, str) or not self.method.isidentifier() or self.method.startswith("_"):
            raise ValueError("advice requires a public method")


@dataclass(frozen=True, slots=True)
class AspectDefinition:
    name: str
    pointcut: MethodPointcut = field(default_factory=MethodPointcut)
    order: int = 0
    before: Callable | AdviceRef | None = field(default=None, repr=False)
    around: Callable | AdviceRef | None = field(default=None, repr=False)
    after: Callable | AdviceRef | None = field(default=None, repr=False)
    on_error: Callable | AdviceRef | None = field(default=None, repr=False)
    finally_: Callable | AdviceRef | None = field(default=None, repr=False)

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("aspect name must be nonempty")
        if not isinstance(self.pointcut, MethodPointcut) or type(self.order) is not int:
            raise ValueError("invalid pointcut or aspect order")
        for hook in self.hooks:
            if hook is not None and not isinstance(hook, AdviceRef) and not callable(hook):
                raise ValueError("advice must be callable or AdviceRef")
        if not any(hook is not None for hook in self.hooks):
            raise ValueError("aspect must declare at least one advice")

    @property
    def hooks(self):
        return self.before, self.around, self.after, self.on_error, self.finally_

    @property
    def dependencies(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(h.component for h in self.hooks if isinstance(h, AdviceRef)))


@dataclass(frozen=True, slots=True)
class Invocation:
    component: str
    method: str
    kind: str
    args: tuple[Any, ...] = field(repr=False)
    kwargs: Mapping[str, Any] = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, "kwargs", MappingProxyType(dict(self.kwargs)))


@dataclass(frozen=True, slots=True)
class InvocationOutcome:
    status: str
    result: Any = field(default=None, repr=False)
    error: BaseException | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class AspectMatch:
    component: str
    method: str
    kind: str
    aspects: tuple[str, ...]


class Aspect(Component):
    """A managed advice component; methods marked below share one pointcut."""

    def __init__(self, name=None, *, component="*", methods=("*",), tags=(),
                 kind="auto", order=0, scope="application"):
        super().__init__(name, component=component, methods=methods, tags=tags,
                         kind=kind, order=order, scope=scope)

    def __call__(self, target):
        if not isinstance(target, type):
            raise ValueError("Aspect requires a class")
        super().__call__(target)
        target.__aspect_options__ = {
            "pointcut": MethodPointcut(self.kwargs.get("component", "*"),
                                       self.kwargs.get("methods", ("*",)),
                                       frozenset(self.kwargs.get("tags", ())),
                                       self.kwargs.get("kind", "auto")),
            "order": self.kwargs.get("order", 0),
        }
        return target


def _advice(kind):
    def decorate(method):
        if hasattr(method, "__application_advice__"):
            raise ValueError("one advice role per method")
        method.__application_advice__ = kind
        return method
    return decorate


Before = _advice("before")
Around = _advice("around")
After = _advice("after")
OnError = _advice("on_error")
Finally = _advice("finally_")
