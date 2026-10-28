"""Harness application planning and explicit scoped lifecycle."""

from .planning import (
    AssemblyComponent,
    AssemblyDefinitionError,
    AssemblyPlan,
    BorrowedComponent,
    ComponentDefinition,
    ComponentRef,
    compile_assembly,
    replace_components,
)
from .context import (
    ApplicationContext,
    ApplicationLifecycleError,
    ApplicationScope,
    ApplicationState,
)
from .execution import ApplicationHost, ApplicationOperation, ApplicationProject
from .loading import (
    ApplicationCall, ApplicationEntryError, application_call_from_mapping,
    execute_application_entry, load_application_call, load_application_entry,
)
from .plugins import ApplicationPlugin, CapabilityExport, CapabilityImport
from .configuration import ConfigurationField, ConfigurationSchema
from .legacy import borrow_legacy_singletons
from .declarations import Bean, Configuration
from .discovery import scan_components
from .compilation import compile_configured, compile_decorated
from .aspects import (
    AdviceRef, After, Around, Aspect, AspectDefinition, AspectError, AspectMatch,
    Before, Finally, Invocation, InvocationOutcome, MethodPointcut, OnError,
)

__all__ = [
    "ApplicationHost", "ApplicationOperation", "ApplicationProject",
    "ApplicationCall", "ApplicationEntryError", "application_call_from_mapping",
    "execute_application_entry", "load_application_call", "load_application_entry",
    "AdviceRef", "After", "Around", "Aspect", "AspectDefinition", "AspectError",
    "AspectMatch", "Before", "Finally", "Invocation", "InvocationOutcome",
    "MethodPointcut", "OnError",
    "Bean",
    "Configuration",
    "scan_components",
    "compile_decorated",
    "compile_configured",
    "ConfigurationField",
    "ConfigurationSchema",
    "borrow_legacy_singletons",
    "ApplicationPlugin",
    "CapabilityExport",
    "CapabilityImport",
    "ApplicationContext",
    "ApplicationLifecycleError",
    "ApplicationScope",
    "ApplicationState",
    "AssemblyComponent",
    "AssemblyDefinitionError",
    "AssemblyPlan",
    "BorrowedComponent",
    "ComponentDefinition",
    "ComponentRef",
    "compile_assembly",
    "replace_components",
]
