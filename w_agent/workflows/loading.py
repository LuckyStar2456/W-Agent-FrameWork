"""Explicit loading of developer-owned workflow definitions."""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Sequence
from typing import Any

from .types import (
    DagWorkflowDefinition,
    PythonWorkflowDefinition,
    StateGraphDefinition,
    WorkflowDefinition,
)


class WorkflowEntryLoadError(RuntimeError):
    """An explicitly requested Python workflow entry could not be loaded."""


_DEFINITION_TYPES = (
    DagWorkflowDefinition,
    StateGraphDefinition,
    PythonWorkflowDefinition,
)


def load_workflow_entry(entry: str) -> tuple[WorkflowDefinition, ...]:
    """Import ``module:attribute`` and coerce it to workflow definitions.

    Importing an entry executes developer-owned Python code. Callers must put an
    explicit authorization boundary in front of this function; stored
    checkpoint/configuration data alone must never trigger an import.
    """

    if not isinstance(entry, str) or entry.count(":") != 1:
        raise WorkflowEntryLoadError(
            "workflow entry must use module:attribute syntax"
        )
    module_name, attribute = entry.split(":", 1)
    if not module_name.strip() or not attribute.strip():
        raise WorkflowEntryLoadError(
            "workflow entry module and attribute are required"
        )
    try:
        value: Any = getattr(importlib.import_module(module_name), attribute)
        if callable(value) and not isinstance(value, _DEFINITION_TYPES):
            value = value()
    except Exception as exc:
        raise WorkflowEntryLoadError(
            f"workflow entry {entry!r} could not be loaded"
        ) from exc
    if isinstance(value, _DEFINITION_TYPES):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        definitions = tuple(value)
        if definitions and all(
            isinstance(item, _DEFINITION_TYPES) for item in definitions
        ):
            return definitions
    raise WorkflowEntryLoadError(
        f"workflow entry {entry!r} must provide workflow definitions"
    )


def load_workflow_entries(
    entries: Sequence[str],
) -> dict[tuple[str, str], WorkflowDefinition]:
    """Load an authorized catalog keyed by exact workflow name and version."""

    catalog: dict[tuple[str, str], WorkflowDefinition] = {}
    for entry in entries:
        for definition in load_workflow_entry(entry):
            key = (definition.name, definition.version)
            if key in catalog:
                raise WorkflowEntryLoadError(
                    "duplicate loaded workflow identity: "
                    f"{definition.name}@{definition.version}"
                )
            catalog[key] = definition
    return catalog
