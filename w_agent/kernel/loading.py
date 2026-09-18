"""Configuration and entry-point discovery for W-Agent plugins."""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import yaml

from .exceptions import PluginLoadError
from .plugins import Plugin, PluginHandle, PluginManager, coerce_plugin


@dataclass(frozen=True, slots=True)
class PluginReference:
    """A declarative reference to a plugin and its validated raw config."""

    entry: str
    config: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.entry.count(":") != 1:
            raise ValueError("plugin entry must use 'module:attribute' syntax")
        module_name, attribute = self.entry.split(":", 1)
        if not module_name.strip() or not attribute.strip():
            raise ValueError("plugin entry module and attribute are required")
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))


@dataclass(frozen=True, slots=True)
class PluginReferenceSummary:
    """Import-free projection suitable for review and confirmation screens."""

    entry: str
    enabled: bool
    config_keys: tuple[str, ...]


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
    try:
        module = importlib.import_module(module_name)
        return coerce_plugin(getattr(module, attribute))
    except Exception as exc:
        raise PluginLoadError(
            f"plugin reference {reference.entry!r} could not be imported"
        ) from exc


def preview_plugin_references(
    references: Iterable[PluginReference],
) -> tuple[PluginReferenceSummary, ...]:
    """Return a deterministic, config-value-free projection without imports."""

    values = tuple(references)
    entries = [reference.entry for reference in values]
    if len(entries) != len(set(entries)):
        raise ValueError("plugin references must be unique")
    return tuple(
        PluginReferenceSummary(
            reference.entry,
            reference.enabled,
            tuple(sorted(str(key) for key in reference.config)),
        )
        for reference in values
    )


async def load_plugin_references(
    manager: PluginManager,
    references: Iterable[PluginReference],
) -> tuple[PluginHandle, ...]:
    """Import and transactionally load one explicitly authorized batch.

    Importing and loading executes developer-owned Python code. Callers must
    present a confirmation boundary before invoking this function. If any entry
    fails, plugins loaded earlier by this batch are unloaded in reverse order.
    """

    values = tuple(references)
    preview_plugin_references(values)
    handles: list[PluginHandle] = []
    for reference in values:
        if not reference.enabled:
            continue
        try:
            plugin = import_plugin(reference)
            handles.append(await manager.load(plugin, config=reference.config))
        except Exception as exc:
            cleanup_failures: list[Exception] = []
            for handle in reversed(handles):
                try:
                    await handle.unload()
                except Exception as cleanup_error:
                    cleanup_failures.append(cleanup_error)
            error = PluginLoadError(
                f"plugin batch failed at reference {reference.entry!r}"
            )
            if cleanup_failures:
                error.add_note(
                    f"{len(cleanup_failures)} plugin rollback operation(s) failed"
                )
            raise error from exc
    return tuple(handles)


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
