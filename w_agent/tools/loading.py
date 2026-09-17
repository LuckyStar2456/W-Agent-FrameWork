"""Explicit loading of developer-owned tool bindings."""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Sequence
from typing import Any

from .types import ToolBinding


class ToolEntryLoadError(RuntimeError):
    """An explicitly requested Python tool entry could not be loaded safely."""


def load_tool_entry(entry: str) -> tuple[ToolBinding, ...]:
    """Import ``module:attribute`` and coerce its value to tool bindings.

    Importing an entry executes developer-owned Python code. Callers must put an
    explicit authorization boundary in front of this function; configuration
    data alone must never trigger it.
    """

    if not isinstance(entry, str) or entry.count(":") != 1:
        raise ToolEntryLoadError("tool entry must use module:attribute syntax")
    module_name, attribute = entry.split(":", 1)
    if not module_name.strip() or not attribute.strip():
        raise ToolEntryLoadError("tool entry module and attribute are required")
    try:
        value: Any = getattr(importlib.import_module(module_name), attribute)
        if callable(value) and not isinstance(value, ToolBinding):
            value = value()
    except Exception as exc:
        raise ToolEntryLoadError(f"tool entry {entry!r} could not be loaded") from exc
    if isinstance(value, ToolBinding):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        bindings = tuple(value)
        if bindings and all(isinstance(item, ToolBinding) for item in bindings):
            return bindings
    raise ToolEntryLoadError(
        f"tool entry {entry!r} must provide ToolBinding values"
    )


def load_tool_entries(entries: Sequence[str]) -> dict[str, ToolBinding]:
    """Load an explicitly authorized catalog and reject duplicate names."""

    catalog: dict[str, ToolBinding] = {}
    for entry in entries:
        for binding in load_tool_entry(entry):
            name = binding.definition.name
            if name in catalog:
                raise ToolEntryLoadError(f"duplicate loaded tool name: {name}")
            catalog[name] = binding
    return catalog
