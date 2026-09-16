"""Configuration and entry-point discovery for W-Agent plugins."""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import yaml

from .plugins import Plugin, coerce_plugin


@dataclass(frozen=True, slots=True)
class PluginReference:
    """A declarative reference to a plugin and its validated raw config."""

    entry: str
    config: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self) -> None:
        if ":" not in self.entry:
            raise ValueError("plugin entry must use 'module:attribute' syntax")
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))


def load_yaml_references(path: str | Path) -> tuple[PluginReference, ...]:
    """Parse plugin references from a YAML file without importing code."""

    source = Path(path)
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("plugin config root must be a mapping")
    rows = data.get("plugins", [])
    if not isinstance(rows, list):
        raise ValueError("plugins must be a list")

    references: list[PluginReference] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"plugins[{index}] must be a mapping")
        entry = row.get("entry")
        if not isinstance(entry, str):
            raise ValueError(f"plugins[{index}].entry must be a string")
        config = row.get("config", {})
        if not isinstance(config, dict):
            raise ValueError(f"plugins[{index}].config must be a mapping")
        enabled = row.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"plugins[{index}].enabled must be a boolean")
        references.append(PluginReference(entry, config, enabled))
    return tuple(references)


def import_plugin(reference: PluginReference) -> Plugin:
    """Import one enabled plugin reference after configuration preview."""

    if not reference.enabled:
        raise ValueError(f"plugin reference {reference.entry!r} is disabled")
    module_name, attribute = reference.entry.split(":", 1)
    module = importlib.import_module(module_name)
    return coerce_plugin(getattr(module, attribute))


def discover_entrypoint_plugins(
    *,
    group: str = "w_agent.plugins",
    entry_points: Iterable[importlib.metadata.EntryPoint] | None = None,
) -> tuple[Plugin, ...]:
    """Load plugins declared through Python entry points."""

    if entry_points is None:
        discovered = importlib.metadata.entry_points()
        selected = discovered.select(group=group)
    else:
        selected = [entry for entry in entry_points if entry.group == group]
    return tuple(coerce_plugin(entry.load()) for entry in selected)
