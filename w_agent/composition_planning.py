"""Offline, non-executing dependency plans for portable compositions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Protocol

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from .compositions import (
    CompositionError,
    CompositionManifest,
    PluginRequirement,
    composition_digest,
)


class CompositionPluginAction(StrEnum):
    """A reviewable next action; no action executes package or plugin code."""

    USE_INSTALLED = "use-installed"
    INSTALL = "install"
    CHANGE_VERSION = "change-version"
    REVIEW_SOURCE = "review-source"
    SELECT_SOURCE = "select-source"
    SELECT_CANDIDATE = "select-candidate"


@dataclass(frozen=True, slots=True)
class PluginCandidate:
    """One caller-declared local candidate; discovery is intentionally external."""

    name: str
    version: str
    source: str | None = None
    entry: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not isinstance(self.version, str):
            raise CompositionError("plugin candidate name and version must be strings")
        if self.source is not None and not isinstance(self.source, str):
            raise CompositionError("plugin candidate source must be a string or null")
        if self.entry is not None and not isinstance(self.entry, str):
            raise CompositionError("plugin candidate entry must be a string or null")
        PluginRequirement(self.name, source=self.source)
        try:
            Version(self.version)
        except InvalidVersion as error:
            raise CompositionError("plugin candidate version is invalid") from error
        if self.entry is not None:
            if self.entry.count(":") != 1:
                raise CompositionError(
                    "plugin candidate entry must use 'module:attribute' syntax"
                )
            module_name, attribute = self.entry.split(":", 1)
            if not module_name.strip() or not attribute.strip():
                raise CompositionError(
                    "plugin candidate entry module and attribute are required"
                )


@dataclass(frozen=True, slots=True)
class PluginResolution:
    """Privacy-safe resolution result for one manifest requirement."""

    requirement: PluginRequirement
    action: CompositionPluginAction
    candidate: PluginCandidate | None = None
    available_versions: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.action is CompositionPluginAction.USE_INSTALLED


class CompositionDependencyResolver(Protocol):
    """Replaceable dependency resolver used by the offline planner."""

    def resolve(self, requirement: PluginRequirement) -> PluginResolution:
        """Resolve one requirement without installing or importing anything."""


class StaticCompositionDependencyResolver:
    """Resolve against an explicit, side-effect-free candidate inventory."""

    def __init__(self, candidates: Iterable[PluginCandidate] = ()) -> None:
        values = tuple(candidates)
        identities = [
            (item.name, item.version, item.source, item.entry) for item in values
        ]
        if len(identities) != len(set(identities)):
            raise CompositionError("plugin candidates must be unique")
        self._candidates = values

    def resolve(self, requirement: PluginRequirement) -> PluginResolution:
        named = tuple(
            item for item in self._candidates if item.name == requirement.name
        )
        available_versions = tuple(
            str(item)
            for item in sorted(
                {Version(candidate.version) for candidate in named},
                reverse=True,
            )
        )
        if not named:
            action = (
                CompositionPluginAction.INSTALL
                if requirement.source is not None
                else CompositionPluginAction.SELECT_SOURCE
            )
            return PluginResolution(
                requirement,
                action,
                available_versions=available_versions,
            )

        specifier = SpecifierSet(requirement.version)
        version_matches = tuple(
            item
            for item in named
            if specifier.contains(Version(item.version), prereleases=True)
        )
        if not version_matches:
            return PluginResolution(
                requirement,
                CompositionPluginAction.CHANGE_VERSION,
                available_versions=available_versions,
            )

        source_matches = tuple(
            item
            for item in version_matches
            if requirement.source is None or item.source == requirement.source
        )
        if not source_matches:
            return PluginResolution(
                requirement,
                CompositionPluginAction.REVIEW_SOURCE,
                available_versions=available_versions,
            )

        highest = max(Version(item.version) for item in source_matches)
        selected = tuple(
            item for item in source_matches if Version(item.version) == highest
        )
        if len(selected) != 1:
            return PluginResolution(
                requirement,
                CompositionPluginAction.SELECT_CANDIDATE,
                available_versions=available_versions,
            )
        return PluginResolution(
            requirement,
            CompositionPluginAction.USE_INSTALLED,
            selected[0],
            available_versions,
        )


@dataclass(frozen=True, slots=True)
class CompositionEnvironment:
    """Explicit versions used for deterministic compatibility checks."""

    python_version: str
    wagent_version: str

    def __post_init__(self) -> None:
        for label, value in (
            ("Python", self.python_version),
            ("W-Agent", self.wagent_version),
        ):
            if not isinstance(value, str):
                raise CompositionError(f"{label} environment version must be a string")
            try:
                Version(value)
            except InvalidVersion as error:
                raise CompositionError(
                    f"{label} environment version is invalid"
                ) from error


@dataclass(frozen=True, slots=True)
class CompositionPlan:
    """Offline plan that separates review from installation and code loading."""

    name: str
    version: str
    digest: str
    environment: CompositionEnvironment
    python_compatible: bool
    wagent_compatible: bool
    plugins: tuple[PluginResolution, ...]

    @property
    def ready(self) -> bool:
        return (
            self.python_compatible
            and self.wagent_compatible
            and all(item.ready for item in self.plugins)
        )

    @property
    def load_confirmation_required(self) -> bool:
        return bool(self.plugins)


def plan_composition(
    manifest: CompositionManifest,
    environment: CompositionEnvironment,
    resolver: CompositionDependencyResolver | None = None,
) -> CompositionPlan:
    """Build a deterministic plan without network, imports, or installation."""

    selected_resolver = resolver or StaticCompositionDependencyResolver()
    python_version = Version(environment.python_version)
    wagent_version = Version(environment.wagent_version)
    return CompositionPlan(
        name=manifest.name,
        version=manifest.version,
        digest=composition_digest(manifest),
        environment=environment,
        python_compatible=SpecifierSet(manifest.requires_python).contains(
            python_version,
            prereleases=True,
        ),
        wagent_compatible=SpecifierSet(manifest.requires_wagent).contains(
            wagent_version,
            prereleases=True,
        ),
        plugins=tuple(
            selected_resolver.resolve(requirement)
            for requirement in manifest.plugins
        ),
    )


def load_plugin_candidates(path: str | Path) -> tuple[PluginCandidate, ...]:
    """Load a strict JSON candidate inventory without importing plugin code."""

    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise CompositionError("plugin inventory is not valid JSON") from error
    if not isinstance(data, dict):
        raise CompositionError("plugin inventory root must be an object")
    if set(data) != {"plugins"}:
        raise CompositionError("plugin inventory must contain only 'plugins'")
    rows = data["plugins"]
    if not isinstance(rows, list):
        raise CompositionError("plugin inventory plugins must be a list")
    candidates: list[PluginCandidate] = []
    allowed = {"name", "version", "source", "entry"}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CompositionError(
                f"plugin inventory plugins[{index}] must be an object"
            )
        if not set(row).issubset(allowed):
            raise CompositionError(
                f"plugin inventory plugins[{index}] has unsupported fields"
            )
        try:
            candidates.append(PluginCandidate(**row))
        except TypeError as error:
            raise CompositionError(
                f"plugin inventory plugins[{index}] is malformed"
            ) from error
    return tuple(candidates)


def composition_plan_to_dict(plan: CompositionPlan) -> dict[str, object]:
    """Return a detached JSON projection with no plugin configuration values."""

    return {
        "name": plan.name,
        "version": plan.version,
        "digest": plan.digest,
        "environment": {
            "python_version": plan.environment.python_version,
            "wagent_version": plan.environment.wagent_version,
        },
        "python_compatible": plan.python_compatible,
        "wagent_compatible": plan.wagent_compatible,
        "ready": plan.ready,
        "load_confirmation_required": plan.load_confirmation_required,
        "plugins": [
            {
                "name": item.requirement.name,
                "version": item.requirement.version,
                "source": item.requirement.source,
                "action": item.action.value,
                "selected": (
                    {
                        "name": item.candidate.name,
                        "version": item.candidate.version,
                        "source": item.candidate.source,
                        "entry": item.candidate.entry,
                    }
                    if item.candidate is not None
                    else None
                ),
                "available_versions": list(item.available_versions),
            }
            for item in plan.plugins
        ],
    }
