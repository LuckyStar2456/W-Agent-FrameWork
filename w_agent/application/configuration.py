"""Small opt-in argument schemas; custom validators remain ordinary Python."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .planning import AssemblyDefinitionError, ComponentDefinition


@dataclass(frozen=True, slots=True)
class ConfigurationField:
    """Strict runtime types, without implicit coercion or evaluated annotations."""

    types: type | tuple[type, ...]
    required: bool = True

    def __post_init__(self) -> None:
        types = self.types if isinstance(self.types, tuple) else (self.types,)
        if not types or any(not isinstance(item, type) for item in types):
            raise AssemblyDefinitionError("configuration field requires runtime types")
        if not isinstance(self.required, bool):
            raise AssemblyDefinitionError("configuration required flag must be boolean")
        object.__setattr__(self, "types", types)


@dataclass(frozen=True, slots=True)
class ConfigurationSchema:
    """Validate explicit argument values, not dependency-injected objects.

    Exact types intentionally distinguish bool/int. For subclasses, nested
    structures, ranges or vendor-specific parameters supply a custom validator.
    This does not read files, apply defaults, import modules or mutate arguments.
    """

    fields: Mapping[str, ConfigurationField]
    allow_extra: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.fields, Mapping):
            raise AssemblyDefinitionError("schema fields must be a mapping")
        fields = dict(self.fields)
        for name, field in fields.items():
            ComponentDefinition._parameter(name)
            if not isinstance(field, ConfigurationField):
                raise AssemblyDefinitionError("schema requires ConfigurationField")
        if not isinstance(self.allow_extra, bool):
            raise AssemblyDefinitionError("allow_extra must be boolean")
        object.__setattr__(self, "fields", MappingProxyType(fields))

    def __call__(self, arguments: Mapping[str, Any]) -> None:
        if not self.allow_extra and arguments.keys() - self.fields.keys():
            raise AssemblyDefinitionError("unexpected configuration fields")
        for name, field in self.fields.items():
            if name not in arguments:
                if field.required:
                    raise AssemblyDefinitionError(f"missing configuration field: {name}")
            elif type(arguments[name]) not in field.types:
                raise AssemblyDefinitionError(f"invalid configuration type: {name}")
