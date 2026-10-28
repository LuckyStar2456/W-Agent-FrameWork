"""Explicit trusted project loading and common frontend invocation transport."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import importlib
import inspect
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .execution import ApplicationProject
from .planning import _identity


class ApplicationEntryError(ValueError):
    """An application entry or call document is invalid; payloads are redacted."""


@dataclass(frozen=True, slots=True)
class ApplicationCall:
    operation: str = "run"
    args: tuple[Any, ...] = field(default=(), repr=False)
    kwargs: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        _identity(self.operation, "operation name")
        if not isinstance(self.args, (tuple, list)) or not isinstance(self.kwargs, Mapping):
            raise ApplicationEntryError("call requires positional args and named kwargs")
        kwargs = dict(self.kwargs)
        if any(not isinstance(key, str) or not key.isidentifier() for key in kwargs):
            raise ApplicationEntryError("call argument names must be identifiers")
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "kwargs", MappingProxyType(kwargs))


def application_call_from_mapping(value: Mapping[str, Any]) -> ApplicationCall:
    """Interpret only transport fields; arbitrary user argument values remain intact."""
    if not isinstance(value, Mapping) or set(value) - {"operation", "args", "kwargs"}:
        raise ApplicationEntryError("call document accepts only operation, args and kwargs")
    try:
        return ApplicationCall(**value)
    except (TypeError, ValueError):
        raise ApplicationEntryError("invalid application call document") from None


def load_application_call(path: str | Path) -> ApplicationCall:
    """Read at most 1 MiB of JSON data. No imports or code evaluation."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("oversized")
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                           object_pairs_hook=_unique_fields)
        return application_call_from_mapping(value)
    except (OSError, ValueError, RecursionError):
        raise ApplicationEntryError("application call file is invalid, unavailable or oversized") from None


def _reject_constant(value):
    raise ValueError("non-finite JSON value")


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


async def load_application_entry(entry: str, *, confirmed: bool = False) -> ApplicationProject:
    """Load an explicit module:attribute only after unsandboxed-code authorization.

    The value may be a project or a no-argument sync/async factory returning one.
    Factories describe plans; they must clean up any resources they create before
    returning. Import authorization does not grant model/tool permissions.
    """
    if confirmed is not True:
        raise ApplicationEntryError("application loading requires explicit trusted-code confirmation")
    if not isinstance(entry, str) or len(entry) > 512 or entry.count(":") != 1:
        raise ApplicationEntryError("application entry must use module:attribute syntax")
    module, attribute = entry.split(":", 1)
    if (not all(part.isidentifier() for part in module.split("."))
            or not attribute.isidentifier() or attribute.startswith("_")):
        raise ApplicationEntryError("application entry needs an explicit module and public attribute")
    try:
        value = getattr(importlib.import_module(module), attribute)
        if not isinstance(value, ApplicationProject) and callable(value):
            value = value()
            if inspect.isawaitable(value):
                value = await value
    except Exception:
        raise ApplicationEntryError("application entry import or factory failed") from None
    if not isinstance(value, ApplicationProject):
        raise ApplicationEntryError("application entry must return ApplicationProject")
    return value


async def execute_application_entry(
    entry: str, call: ApplicationCall, *, confirmed: bool = False,
    on_item: Callable[[Any], Any] | None = None,
) -> Any:
    """Shared Python/CLI/TUI loading, execution and cleanup, with no output coercion."""
    if not isinstance(call, ApplicationCall):
        raise ApplicationEntryError("execution requires ApplicationCall")
    project = await load_application_entry(entry, confirmed=confirmed)
    operation = project.operations.get(call.operation)
    if operation is None:
        raise ApplicationEntryError("unknown application operation")
    if operation.kind == "stream" and not callable(on_item):
        raise ApplicationEntryError("stream execution requires an explicit consumer")
    async with project.open() as host:
        if operation.kind == "stream":
            return await host.consume(call.operation, on_item, *call.args, **call.kwargs)
        return await host.invoke(call.operation, *call.args, **call.kwargs)
