"""Explicit loaded-module scanning; importing code is a separate host action."""

import inspect
from types import ModuleType

from .planning import AssemblyDefinitionError


def scan_components(*modules: ModuleType) -> tuple[object, ...]:
    """Find locally declared components/configurations/beans without importing.

    No package walking, sys.path changes, AST-to-import promotion or implicit
    scanning of re-exported names. Pass classes/functions directly to the
    compiler when intentional cross-module composition is desired.
    """
    found = {}
    for module in modules:
        if not isinstance(module, ModuleType):
            raise AssemblyDefinitionError("scan_components requires loaded modules")
        for name, target in sorted(vars(module).items()):
            if not (inspect.isclass(target) or inspect.isfunction(target)):
                continue
            metadata = vars(target)
            if target.__module__ != module.__name__:
                continue
            if metadata.get("__component__") or "__bean_options__" in metadata:
                found.setdefault(id(target), (module.__name__, name, target))
    return tuple(item[2] for item in sorted(found.values(), key=lambda item: item[:2]))
