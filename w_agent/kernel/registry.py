"""Scoped, version-aware capability registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .exceptions import (
    AmbiguousCapabilityError,
    CapabilityNotFoundError,
    RegistrationError,
)
from .scope import ScopePath


@dataclass(frozen=True, slots=True)
class Contribution:
    """One provider contribution to the capability registry."""

    capability: str
    provider: Any
    name: str = "default"
    version: str = "0"
    scope: ScopePath = field(default_factory=ScopePath.application)
    exclusive: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    owner: str | None = None

    def __post_init__(self) -> None:
        if not self.capability or not self.capability.strip():
            raise ValueError("capability must not be empty")
        if not self.name or not self.name.strip():
            raise ValueError("provider name must not be empty")
        try:
            Version(self.version)
        except InvalidVersion as exc:
            raise ValueError(f"invalid provider version: {self.version}") from exc
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class Registration:
    """Idempotent handle that removes one registry contribution."""

    def __init__(self, dispose: Callable[[], None]) -> None:
        self._dispose = dispose
        self._disposed = False
        self._lock = RLock()

    @property
    def disposed(self) -> bool:
        """Return whether this handle has already been disposed."""

        with self._lock:
            return self._disposed

    def dispose(self) -> None:
        """Remove the contribution exactly once."""

        with self._lock:
            if self._disposed:
                return
            self._dispose()
            self._disposed = True

    def __enter__(self) -> "Registration":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.dispose()


class RegistryView:
    """Read-only capability resolution over a fixed contribution snapshot."""

    def __init__(self, contributions: Iterable[Contribution]) -> None:
        self._snapshot = tuple(contributions)

    def _items(self) -> tuple[Contribution, ...]:
        return self._snapshot

    def list(
        self,
        capability: str,
        scope: ScopePath,
        *,
        version: str | None = None,
    ) -> tuple[Contribution, ...]:
        """List visible providers ordered from most to least specific."""

        specifier = _parse_specifier(version)
        candidates = [
            contribution
            for contribution in self._items()
            if contribution.capability == capability
            and contribution.scope.is_ancestor_of(scope)
            and _matches_version(contribution.version, specifier)
        ]
        candidates.sort(
            key=lambda contribution: (
                contribution.scope.depth,
                Version(contribution.version),
                contribution.name,
            ),
            reverse=True,
        )
        return tuple(candidates)

    def resolve_contribution(
        self,
        capability: str,
        scope: ScopePath,
        *,
        name: str | None = None,
        version: str | None = None,
    ) -> Contribution:
        """Resolve one visible contribution."""

        candidates = list(self.list(capability, scope, version=version))
        if name is not None:
            candidates = [item for item in candidates if item.name == name]
        if not candidates:
            detail = f"capability {capability!r} is unavailable in scope {scope}"
            if name is not None:
                detail += f" for provider {name!r}"
            if version is not None:
                detail += f" matching {version!r}"
            raise CapabilityNotFoundError(detail)

        deepest = candidates[0].scope.depth
        candidates = [item for item in candidates if item.scope.depth == deepest]
        if name is None and len(candidates) > 1:
            names = {item.name for item in candidates}
            if len(names) == 1:
                return candidates[0]
            defaults = [item for item in candidates if item.name == "default"]
            if defaults:
                return defaults[0]
            provider_names = ", ".join(sorted(names))
            raise AmbiguousCapabilityError(
                f"capability {capability!r} has multiple providers in scope "
                f"{candidates[0].scope}: {provider_names}"
            )
        return candidates[0]

    def resolve(
        self,
        capability: str,
        scope: ScopePath,
        *,
        name: str | None = None,
        version: str | None = None,
    ) -> Any:
        """Resolve and return one provider object."""

        return self.resolve_contribution(
            capability,
            scope,
            name=name,
            version=version,
        ).provider


class Registry(RegistryView):
    """Mutable registry whose registrations can be disposed."""

    def __init__(self) -> None:
        self._entries: list[Contribution] = []
        self._lock = RLock()
        super().__init__(())

    def _items(self) -> tuple[Contribution, ...]:
        with self._lock:
            return tuple(self._entries)

    def register(self, contribution: Contribution) -> Registration:
        """Register a contribution and return its disposal handle."""

        with self._lock:
            same_slot = [
                item
                for item in self._entries
                if item.capability == contribution.capability
                and item.name == contribution.name
                and item.version == contribution.version
                and item.scope == contribution.scope
            ]
            if same_slot:
                raise RegistrationError(
                    f"provider {contribution.name!r} already supplies "
                    f"{contribution.capability!r} in scope {contribution.scope}"
                )
            same_capability = [
                item
                for item in self._entries
                if item.capability == contribution.capability
                and item.scope == contribution.scope
            ]
            if contribution.exclusive and same_capability:
                raise RegistrationError(
                    f"exclusive capability {contribution.capability!r} already has a provider"
                )
            if any(item.exclusive for item in same_capability):
                raise RegistrationError(
                    f"capability {contribution.capability!r} is exclusive in scope "
                    f"{contribution.scope}"
                )
            self._entries.append(contribution)

        def dispose() -> None:
            with self._lock:
                try:
                    self._entries.remove(contribution)
                except ValueError:
                    return

        return Registration(dispose)

    def snapshot(self) -> RegistryView:
        """Capture an immutable registry view for a run or other operation."""

        with self._lock:
            return RegistryView(tuple(self._entries))


def _parse_specifier(value: str | None) -> SpecifierSet | None:
    if value is None or not value.strip():
        return None
    try:
        return SpecifierSet(value)
    except InvalidSpecifier as exc:
        raise ValueError(f"invalid version specifier: {value}") from exc


def _matches_version(version: str, specifier: SpecifierSet | None) -> bool:
    return specifier is None or Version(version) in specifier
