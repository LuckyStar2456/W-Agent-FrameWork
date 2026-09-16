"""Hierarchical runtime scopes used by the W-Agent registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator


BUILTIN_SCOPE_ORDER = (
    "application",
    "workspace",
    "session",
    "agent",
    "run",
    "step",
)


@dataclass(frozen=True, slots=True)
class ScopeSegment:
    """One named dimension in a scope path."""

    kind: str
    value: str

    def __post_init__(self) -> None:
        if not self.kind or not self.kind.strip():
            raise ValueError("scope segment kind must not be empty")
        if not self.value or not self.value.strip():
            raise ValueError("scope segment value must not be empty")


@dataclass(frozen=True, slots=True)
class ScopePath:
    """An immutable hierarchical path for scoped capability resolution."""

    segments: tuple[ScopeSegment, ...]

    def __post_init__(self) -> None:
        if not self.segments:
            raise ValueError("a scope path needs at least one segment")
        kinds = [segment.kind for segment in self.segments]
        if len(kinds) != len(set(kinds)):
            raise ValueError("a scope kind may appear only once in a path")
        builtin_positions = [
            BUILTIN_SCOPE_ORDER.index(kind)
            for kind in kinds
            if kind in BUILTIN_SCOPE_ORDER
        ]
        if builtin_positions != sorted(builtin_positions):
            raise ValueError("built-in scope kinds must follow the documented order")

    @classmethod
    def application(cls, name: str = "default") -> "ScopePath":
        """Create an application-root scope."""

        return cls((ScopeSegment("application", name),))

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[str, str]]) -> "ScopePath":
        """Create a path from ``(kind, value)`` pairs."""

        return cls(tuple(ScopeSegment(kind, value) for kind, value in pairs))

    def child(self, kind: str, value: str) -> "ScopePath":
        """Return a child path with one additional dimension."""

        return ScopePath((*self.segments, ScopeSegment(kind, value)))

    @property
    def parent(self) -> "ScopePath | None":
        """Return the direct parent, or ``None`` for the application root."""

        if len(self.segments) == 1:
            return None
        return ScopePath(self.segments[:-1])

    @property
    def depth(self) -> int:
        """Return the number of dimensions in this path."""

        return len(self.segments)

    def is_ancestor_of(self, other: "ScopePath") -> bool:
        """Return whether this path is visible from ``other``."""

        return other.segments[: self.depth] == self.segments

    def __iter__(self) -> Iterator[ScopeSegment]:
        return iter(self.segments)

    def __str__(self) -> str:
        return "/".join(f"{part.kind}:{part.value}" for part in self.segments)
