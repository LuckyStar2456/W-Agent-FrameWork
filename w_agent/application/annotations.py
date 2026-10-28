"""Resolve a restricted type/marker grammar without eval or module imports."""

import ast
import builtins
import types
import typing
from collections.abc import Mapping

from w_agent.core.decorators import Autowired, Qualifier, Value

from .planning import AssemblyDefinitionError


def resolve_annotation(annotation, namespace: Mapping[str, object]):
    if annotation is None:
        return type(None)
    if not isinstance(annotation, str):
        return annotation
    symbols = {name: vars(builtins)[name] for name in (
        "str", "int", "float", "bool", "bytes", "list", "dict", "tuple", "set", "object",
    )}
    symbols.update({"None": type(None), "Annotated": typing.Annotated,
                    "Optional": typing.Optional, "Union": typing.Union,
                    "Any": typing.Any, "Value": Value, "Autowired": Autowired,
                    "Qualifier": Qualifier})
    symbols.update(namespace)

    def visit(node):
        if isinstance(node, ast.Name):
            return symbols[node.id]
        if isinstance(node, ast.Constant):
            if node.value is None:
                return type(None)
            if isinstance(node.value, str):
                return visit(ast.parse(node.value, mode="eval").body)
        if isinstance(node, ast.Attribute):
            parent = visit(node.value)
            if isinstance(parent, (types.ModuleType, type)) and not node.attr.startswith("_"):
                return vars(parent)[node.attr]
        if isinstance(node, ast.Call):
            marker = visit(node.func)
            if marker not in (Value, Autowired, Qualifier):
                raise ValueError("only injection marker constructors are allowed")
            return marker(*[ast.literal_eval(arg) for arg in node.args], **{
                kw.arg: ast.literal_eval(kw.value) for kw in node.keywords
                if kw.arg is not None
            }) if all(kw.arg is not None for kw in node.keywords) else _invalid()
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return typing.Union[visit(node.left), visit(node.right)]
        if isinstance(node, ast.Subscript):
            base = visit(node.value)
            if base not in (list, dict, tuple, set, typing.List, typing.Dict,
                            typing.Tuple, typing.Set, typing.Annotated, typing.Optional,
                            typing.Union):
                raise ValueError("unsupported generic annotation")
            parts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            args = tuple(Ellipsis if isinstance(part, ast.Constant) and part.value is Ellipsis
                         else visit(part) for part in parts)
            return base[args[0] if len(args) == 1 else args]
        return _invalid()

    try:
        return visit(ast.parse(annotation, mode="eval").body)
    except (KeyError, TypeError, ValueError, SyntaxError, RecursionError):
        raise AssemblyDefinitionError(
            "unsupported or unresolved annotation; supply an explicit type namespace"
        ) from None


def _invalid():
    raise ValueError("unsupported annotation expression")


def split_annotation(annotation):
    if typing.get_origin(annotation) is typing.Annotated:
        base, *metadata = typing.get_args(annotation)
        markers = [item for item in metadata if isinstance(item, (Value, Autowired, Qualifier))]
        if len(markers) > 1:
            raise AssemblyDefinitionError("conflicting injection markers")
        return base, markers[0] if markers else None
    return annotation, None


def accepts_value(value, annotation) -> bool:
    """Strict common configuration types, without arbitrary conversion."""
    if annotation in (typing.Any, object):
        return True
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        return any(accepts_value(value, item) for item in args)
    if origin in (list, set, tuple, dict):
        if type(value) is not origin:
            return False
        if not args:
            return True
        if origin is dict:
            return all(accepts_value(k, args[0]) and accepts_value(v, args[1])
                       for k, v in value.items())
        if origin is tuple and not (len(args) == 2 and args[1] is Ellipsis):
            return len(value) == len(args) and all(accepts_value(v, t) for v, t in zip(value, args))
        return all(accepts_value(item, args[0]) for item in value)
    if annotation in (str, int, float, bool, bytes, list, dict, tuple, set, type(None)):
        return type(value) is annotation
    try:
        return isinstance(value, annotation)
    except TypeError:
        raise AssemblyDefinitionError("configuration annotation is not a runtime type") from None
