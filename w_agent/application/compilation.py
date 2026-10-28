"""Compile decorator and allowlisted configuration inputs into M1 definitions."""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, get_origin

from w_agent.core.decorators import Autowired, Qualifier, Value
from w_agent.kernel.scope import BUILTIN_SCOPE_ORDER

from .annotations import accepts_value, resolve_annotation, split_annotation
from .declarations import _BeanOptions
from .aspects import AdviceRef, AspectDefinition
from .planning import (
    AssemblyComponent, AssemblyDefinitionError, AssemblyPlan, BorrowedComponent,
    ComponentDefinition, ComponentRef, compile_assembly,
)

_EMPTY = inspect.Parameter.empty


@dataclass
class _Target:
    name: str
    factory: Any
    scope: str
    product_type: Any
    namespace: dict[str, Any]
    owner: str | None = None
    method: str | None = None
    options: _BeanOptions | None = None


def _members(cls):
    members = {}
    for base in reversed(cls.__mro__):
        members.update(vars(base))
    return members


def _namespace(target, types):
    function = target.__init__ if inspect.isclass(target) else target
    result = dict(getattr(function, "__globals__", {}))
    if inspect.isclass(target):
        result.update(vars(target))
        result[target.__name__] = target
    result.update(types)
    return result


def _annotation(value, namespace, label):
    if value is _EMPTY:
        return _EMPTY
    try:
        return resolve_annotation(value, namespace)
    except AssemblyDefinitionError:
        raise AssemblyDefinitionError(f"unresolved annotation: {label}") from None


def _describe(target, types, *, owner=None, method=None):
    metadata = vars(target)
    options = metadata.get("__bean_options__")
    namespace = _namespace(target, types)
    if options is not None:
        name = options.name or target.__name__
        result_type = options.provides
        if result_type is None:
            result_type = _annotation(inspect.signature(target).return_annotation, namespace, name)
        return _Target(name, target, options.scope, result_type, namespace, owner, method, options)
    if not metadata.get("__component__"):
        raise AssemblyDefinitionError("explicit targets must be declared components or definitions")
    name = metadata.get("__component_name__") or target.__name__.lower()
    scope = metadata.get("__component_kwargs__", {}).get("scope", "application")
    scope = "application" if scope == "singleton" else scope
    if scope == "prototype":
        raise AssemblyDefinitionError("prototype requires an explicit run/step scope")
    if not inspect.isclass(target):
        # Legacy decorated tool/service functions are callable values, not factories.
        return BorrowedComponent(name, target, scope)
    return _Target(name, target, scope, target, namespace)


def _expand(targets, types):
    definitions, described = [], []
    for target in targets:
        if isinstance(target, (ComponentDefinition, BorrowedComponent)):
            definitions.append(target)
            continue
        if not (inspect.isclass(target) or inspect.isfunction(target)):
            raise AssemblyDefinitionError("unsupported decorator target")
        description = _describe(target, types)
        if isinstance(description, BorrowedComponent):
            definitions.append(description)
            continue
        described.append(description)
        if inspect.isclass(target) and vars(target).get("__configuration__"):
            for name, member in sorted(_members(target).items()):
                unwrapped = member.__func__ if isinstance(member, (staticmethod, classmethod)) else member
                if getattr(unwrapped, "__bean_options__", None) is None:
                    continue
                if not inspect.isfunction(member):
                    raise AssemblyDefinitionError("configuration beans require instance methods")
                described.append(_describe(member, types, owner=description.name, method=name))
    names = [item.name for item in [*definitions, *described]]
    if len(set(names)) != len(names):
        raise AssemblyDefinitionError("duplicate component identity in decorator inputs")
    return definitions, described


def _compatible(candidate, requested):
    if candidate is requested:
        return True
    if not isinstance(candidate, type) or not isinstance(requested, type) or requested is Any:
        return False
    try:
        return issubclass(candidate, requested)
    except TypeError:
        return False


def _value(marker, values, annotation, label):
    if not isinstance(marker.key, str) or not marker.key or any(not part for part in marker.key.split(".")):
        raise AssemblyDefinitionError(f"invalid configuration key: {label}")
    current = values
    if marker.key in values:
        current = values[marker.key]
    else:
        for part in marker.key.split("."):
            if not isinstance(current, Mapping) or part not in current:
                if marker.required:
                    raise AssemblyDefinitionError(f"missing configuration value: {label}")
                current = marker.default
                break
            current = current[part]
    if annotation is not _EMPTY and not accepts_value(current, annotation):
        raise AssemblyDefinitionError(f"invalid configuration type: {label}")
    return current


def _method_marker(method):
    choices = []
    if getattr(method, "__autowired__", False):
        choices.append(Autowired(getattr(method, "__autowired_name__", None)))
    if hasattr(method, "__qualifier__"):
        # Qualifier refines an unnamed Autowired declaration, not two injections.
        if choices and choices[0].name is None:
            choices.clear()
        choices.append(Qualifier(method.__qualifier__))
    if hasattr(method, "__value_key__"):
        choices.append(Value(method.__value_key__, method.__value_default__,
                             required=getattr(method, "__value_required__", False)))
    if len(choices) > 1:
        raise AssemblyDefinitionError("conflicting method injection markers")
    return choices[0] if choices else None


def _lifecycle(cls, marker):
    if cls in (_EMPTY, Any) or not isinstance(cls, type):
        return None
    methods = []
    for name, method in _members(cls).items():
        raw = method.__func__ if isinstance(method, (staticmethod, classmethod)) else method
        if not getattr(raw, marker, False):
            continue
        if not inspect.isfunction(method) or inspect.isgeneratorfunction(method) or inspect.isasyncgenfunction(method):
            raise AssemblyDefinitionError("lifecycle declarations require ordinary instance methods")
        try:
            inspect.signature(method).bind(object())
        except TypeError:
            raise AssemblyDefinitionError(f"invalid lifecycle signature: {name}") from None
        order = getattr(method, marker[:-2] + "_order__", 0)
        if type(order) is not int:
            raise AssemblyDefinitionError("lifecycle order must be an integer")
        methods.append((order, name))
    if not methods:
        return None
    cleanup = marker == "__pre_destroy__"
    methods.sort(reverse=cleanup)

    async def invoke(instance):
        failures = []
        for _, name in methods:
            try:
                result = getattr(instance, name)()
                if inspect.isawaitable(result):
                    await result
            except BaseException as error:
                if not cleanup:
                    raise
                failures.append(error)
        if failures:
            raise BaseExceptionGroup("declared cleanup methods failed", failures)

    return invoke


def _compile_target(target, catalog, values, explicit_args, explicit_deps):
    dependencies, arguments = {}, {}
    constructor_keys, injections = [], []
    used_args, used_deps = set(), set()

    def bind(key, logical_name, annotation, default=_EMPTY, marker=None, overrides=False):
        base, annotated_marker = split_annotation(annotation)
        default_marker = default if isinstance(default, (Value, Autowired, Qualifier)) else None
        markers = [item for item in (marker, annotated_marker, default_marker) if item is not None]
        if len(markers) == 2:
            unnamed = [item for item in markers if isinstance(item, Autowired) and item.name is None]
            qualified = [item for item in markers if isinstance(item, Qualifier)]
            if unnamed and qualified:
                markers = qualified
        if len(markers) > 1:
            raise AssemblyDefinitionError(f"conflicting injection markers: {target.name}.{logical_name}")
        selected = markers[0] if markers else None
        label = f"{target.name}.{logical_name}"
        if overrides and logical_name in explicit_args:
            used_args.add(logical_name)
            argument = explicit_args[logical_name]
            if base is not _EMPTY and not accepts_value(argument, base):
                raise AssemblyDefinitionError(f"invalid argument type: {label}")
            arguments[key] = argument
            return
        if overrides and logical_name in explicit_deps:
            used_deps.add(logical_name)
            selected = Qualifier(explicit_deps[logical_name])
        if isinstance(selected, Value):
            arguments[key] = _value(selected, values, base, label)
            return
        name = getattr(selected, "name", None)
        if name is not None:
            ComponentRef(name)
            if name not in catalog:
                raise AssemblyDefinitionError(f"missing qualified dependency: {label} -> {name}")
            actual = catalog[name]
            if base is not _EMPTY and actual is not _EMPTY and not _compatible(actual, base):
                raise AssemblyDefinitionError(f"qualified dependency type mismatch: {label}")
        else:
            matches = [name for name, kind in catalog.items()
                       if base is not _EMPTY and _compatible(kind, base)]
            if len(matches) > 1:
                raise AssemblyDefinitionError(f"ambiguous dependency: {label}")
            name = matches[0] if matches else None
            if base is _EMPTY and logical_name in catalog:
                name = logical_name
            if name is None:
                if default is not _EMPTY and default_marker is None and selected is None:
                    if base is not _EMPTY and not accepts_value(default, base):
                        raise AssemblyDefinitionError(f"invalid default type: {label}")
                    arguments[key] = default
                    return
                raise AssemblyDefinitionError(f"missing dependency: {label}")
        dependencies[key] = ComponentRef(name)

    signature = inspect.signature(target.factory)
    parameters = list(signature.parameters.values())
    if target.owner is not None:
        if not parameters or parameters[0].kind not in (
            inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            raise AssemblyDefinitionError("configuration bean must accept self")
        parameters = parameters[1:]
        dependencies["_configuration"] = ComponentRef(target.owner)
    constructor = target.factory.__init__ if inspect.isclass(target.factory) else target.factory
    constructor_marker = _method_marker(constructor)
    if constructor_marker is not None and len(parameters) != 1:
        raise AssemblyDefinitionError("constructor-wide marker requires exactly one parameter")
    for parameter in parameters:
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            raise AssemblyDefinitionError("injection requires keyword-capable parameters")
        if parameter.name.startswith("_wagent_") or parameter.name == "_configuration":
            raise AssemblyDefinitionError("reserved injection parameter name")
        annotation = _annotation(parameter.annotation, target.namespace, target.name)
        constructor_keys.append(parameter.name)
        bind(parameter.name, parameter.name, annotation, parameter.default,
             marker=constructor_marker, overrides=True)
    if used_args != explicit_args.keys() or used_deps != explicit_deps.keys():
        raise AssemblyDefinitionError(f"unknown constructor override: {target.name}")

    cls = target.product_type
    if cls not in (_EMPTY, Any) and isinstance(cls, type):
        members, annotations = _members(cls), {}
        for base in reversed(cls.__mro__):
            annotations.update(vars(base).get("__annotations__", {}))
        for name, member in members.items():
            if isinstance(member, (Value, Autowired, Qualifier)):
                annotations.setdefault(name, _EMPTY)
        namespace = {**_namespace(cls, {}), **target.namespace}
        fields = set()
        for name, raw_annotation in sorted(annotations.items()):
            member = members.get(name)
            marker = member if isinstance(member, (Value, Autowired, Qualifier)) else None
            if marker is None and inspect.isfunction(member):
                marker = _method_marker(member)
            if (marker is None and get_origin(raw_annotation) is not Annotated
                    and not (isinstance(raw_annotation, str) and "Annotated[" in raw_annotation)):
                continue  # Ordinary business field annotations are not injections.
            annotation = _annotation(raw_annotation, namespace, f"{target.name}.{name}")
            _, annotated_marker = split_annotation(annotation)
            if marker is None and annotated_marker is None:
                continue
            key = f"_wagent_field_{name}"
            bind(key, name, annotation, marker=marker)
            injections.append(("field", name, key))
            fields.add(name)
        for name, method in sorted(members.items()):
            if name in fields or name == "__init__":
                continue
            raw = method.__func__ if isinstance(method, (staticmethod, classmethod)) else method
            marker = _method_marker(raw)
            if marker is None:
                continue
            if not inspect.isfunction(method) or inspect.isgeneratorfunction(method) or inspect.isasyncgenfunction(method):
                raise AssemblyDefinitionError("injection setters require ordinary instance methods")
            params = list(inspect.signature(method).parameters.values())
            if len(params) != 2 or params[1].kind not in (
                inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                raise AssemblyDefinitionError(f"setter must accept one value: {target.name}.{name}")
            key = f"_wagent_setter_{name}"
            annotation = _annotation(params[1].annotation, namespace, target.name)
            bind(key, params[1].name, annotation, marker=marker)
            injections.append(("setter", name, key))

    def factory(**resolved):
        kwargs = {name: resolved[name] for name in constructor_keys}
        if target.owner is not None:
            return getattr(resolved["_configuration"], target.method)(**kwargs)
        return target.factory(**kwargs)

    async def inject(instance, resolved):
        if target.options is not None and cls is not _EMPTY and not accepts_value(instance, cls):
            raise AssemblyDefinitionError(f"factory return type mismatch: {target.name}")
        for kind, name, key in injections:
            if kind == "field":
                setattr(instance, name, resolved[key])
            else:
                result = getattr(instance, name)(resolved[key])
                if inspect.isawaitable(result):
                    await result

    initialize = target.options.initialize if target.options is not None else None
    dispose = target.options.dispose if target.options is not None else None
    return ComponentDefinition(
        target.name, factory, dependencies, arguments, target.scope,
        initialize=initialize or _lifecycle(cls, "__post_construct__"),
        dispose=dispose or _lifecycle(cls, "__pre_destroy__"),
        inject=inject if injections or target.options is not None else None,
        tags=getattr(target.factory, "__component_kwargs__", {}).get("tags", ()),
    )


def compile_decorated(
    targets: Iterable[object], *, values: Mapping[str, Any] | None = None,
    arguments: Mapping[str, Mapping[str, Any]] | None = None,
    dependencies: Mapping[str, Mapping[str, str]] | None = None,
    types: Mapping[str, Any] | None = None,
    scope_order: tuple[str, ...] = BUILTIN_SCOPE_ORDER,
    aspects: Iterable[AspectDefinition] = (),
) -> AssemblyPlan:
    """Compile loaded declarations, never instantiate or import them.

    `values` supplies Value bindings. Explicit arguments/dependencies override
    constructor bindings by component name. Type namespaces resolve local forward
    annotations without eval. Factory results remain owned by ApplicationContext.
    """
    values = {} if values is None else values
    arguments = {} if arguments is None else arguments
    dependencies = {} if dependencies is None else dependencies
    types = {} if types is None else types
    if any(not isinstance(item, Mapping) for item in (values, arguments, dependencies, types)):
        raise AssemblyDefinitionError("compiler options must be mappings")
    inputs = tuple(targets)
    aspect_definitions = list(aspects) + [item for item in inputs if isinstance(item, AspectDefinition)]
    definitions, targets = _expand(tuple(item for item in inputs if not isinstance(item, AspectDefinition)), types)
    for target in targets:
        if not inspect.isclass(target.factory):
            continue
        options = vars(target.factory).get("__aspect_options__")
        if options is None:
            continue
        hooks = {}
        for name, method in _members(target.factory).items():
            raw = method.__func__ if isinstance(method, (staticmethod, classmethod)) else method
            role = getattr(raw, "__application_advice__", None)
            if role is None:
                continue
            if not inspect.isfunction(method) or role in hooks:
                raise AssemblyDefinitionError("declare one ordinary instance method per advice role")
            hooks[role] = AdviceRef(target.name, name)
        aspect_definitions.append(AspectDefinition(target.name, **options, **hooks))
    catalog = {item.name: item.product_type for item in targets}
    for item in definitions:
        catalog[item.name] = (type(item.instance) if isinstance(item, BorrowedComponent)
                              else item.factory if inspect.isclass(item.factory) else _EMPTY)
    managed_names = {item.name for item in targets}
    if (arguments.keys() | dependencies.keys()) - managed_names:
        raise AssemblyDefinitionError("overrides require a declared managed component")
    for target in targets:
        args, deps = arguments.get(target.name, {}), dependencies.get(target.name, {})
        if not isinstance(args, Mapping) or not isinstance(deps, Mapping):
            raise AssemblyDefinitionError("component overrides must be mappings")
        if args.keys() & deps.keys():
            raise AssemblyDefinitionError("argument and dependency overrides overlap")
        definitions.append(_compile_target(target, catalog, values, args, deps))
    return compile_assembly(sorted(definitions, key=lambda item: item.name), scope_order=scope_order,
                            aspects=aspect_definitions)


def compile_configured(
    document: Mapping[str, Any], *, catalog: Mapping[str, object],
    types: Mapping[str, Any] | None = None,
    scope_order: tuple[str, ...] = BUILTIN_SCOPE_ORDER,
) -> AssemblyPlan:
    """Select only host-allowlisted declarations from an already parsed document.

    The host reads JSON/YAML/TOML; this function performs no filesystem access,
    imports, environment expansion or code evaluation. Unknown keys fail closed.
    """
    if not isinstance(document, Mapping) or not isinstance(catalog, Mapping):
        raise AssemblyDefinitionError("configuration and catalog must be mappings")
    if document.keys() - {"components", "values", "arguments", "dependencies"}:
        raise AssemblyDefinitionError("unknown assembly configuration fields")
    for key in ("values", "arguments", "dependencies"):
        if key in document and not isinstance(document[key], Mapping):
            raise AssemblyDefinitionError("configuration options must be mappings")
    selections = document.get("components")
    if not isinstance(selections, (list, tuple)) or any(not isinstance(name, str) for name in selections):
        raise AssemblyDefinitionError("components must be a list of catalog keys")
    if len(set(selections)) != len(selections):
        raise AssemblyDefinitionError("duplicate catalog selection")
    if any(name not in catalog for name in selections):
        raise AssemblyDefinitionError("component is not in the host catalog")
    return compile_decorated(
        [catalog[name] for name in selections], values=document.get("values"),
        arguments=document.get("arguments"), dependencies=document.get("dependencies"),
        types=types, scope_order=scope_order,
    )
