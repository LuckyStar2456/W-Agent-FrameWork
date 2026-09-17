"""Python-function tool template built only on public tool protocols."""

from __future__ import annotations

import inspect
import types
from collections.abc import Callable, Mapping
from typing import Any, Union, get_args, get_origin

from w_agent.models import ToolDefinition

from .types import ToolBinding, ToolExecutionContext, ToolSideEffect


def python_tool(
    function: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
    input_schema: Mapping[str, Any] | None = None,
    side_effect: ToolSideEffect = ToolSideEffect.READ,
    required_permissions: frozenset[str] = frozenset(),
) -> ToolBinding:
    """Adapt a sync or async Python function into a registry-ready binding."""

    definition = ToolDefinition(
        name or function.__name__,
        description if description is not None else (inspect.getdoc(function) or ""),
        input_schema or _schema_from_signature(function),
    )

    async def handler(arguments, context: ToolExecutionContext):
        del context
        value = function(**dict(arguments))
        if inspect.isawaitable(value):
            return await value
        return value

    return ToolBinding(
        definition,
        handler,
        side_effect,
        required_permissions,
    )


def _schema_from_signature(function: Callable[..., Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in inspect.signature(function).parameters.values():
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.POSITIONAL_ONLY,
        ):
            raise TypeError("python tools require named, finite parameters")
        properties[parameter.name] = _schema_for_annotation(parameter.annotation)
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter.name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _schema_for_annotation(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}
    direct = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        dict: "object",
        list: "array",
        tuple: "array",
        type(None): "null",
    }
    if annotation in direct:
        return {"type": direct[annotation]}
    origin = get_origin(annotation)
    if origin in (list, tuple):
        return {"type": "array"}
    if origin in (dict, Mapping):
        return {"type": "object"}
    if origin in (types.UnionType, Union):
        options = [
            _schema_for_annotation(item).get("type")
            for item in get_args(annotation)
        ]
        return {"type": [item for item in options if item is not None]}
    return {}
