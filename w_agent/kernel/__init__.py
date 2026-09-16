"""Public W-Agent plugin microkernel."""

from .events import EventDispatcher, EventStop
from .exceptions import (
    AmbiguousCapabilityError,
    CapabilityNotFoundError,
    KernelError,
    PluginDependencyError,
    PluginError,
    PluginLoadError,
    PluginUnloadError,
    RegistrationError,
)
from .loading import (
    PluginReference,
    discover_entrypoint_plugins,
    import_plugin,
    load_yaml_references,
)
from .plugins import (
    CapabilityDeclaration,
    CapabilityRequirement,
    EffectScope,
    FunctionPlugin,
    Plugin,
    PluginContext,
    PluginHandle,
    PluginManager,
    PluginRecord,
    PluginSpec,
    PluginState,
    coerce_plugin,
    plugin,
)
from .registry import Contribution, Registration, Registry, RegistryView
from .scope import BUILTIN_SCOPE_ORDER, ScopePath, ScopeSegment

__all__ = [
    "AmbiguousCapabilityError",
    "BUILTIN_SCOPE_ORDER",
    "CapabilityDeclaration",
    "CapabilityNotFoundError",
    "CapabilityRequirement",
    "Contribution",
    "EffectScope",
    "EventDispatcher",
    "EventStop",
    "FunctionPlugin",
    "KernelError",
    "Plugin",
    "PluginContext",
    "PluginDependencyError",
    "PluginError",
    "PluginHandle",
    "PluginLoadError",
    "PluginManager",
    "PluginRecord",
    "PluginReference",
    "PluginSpec",
    "PluginState",
    "PluginUnloadError",
    "Registration",
    "RegistrationError",
    "Registry",
    "RegistryView",
    "ScopePath",
    "ScopeSegment",
    "coerce_plugin",
    "discover_entrypoint_plugins",
    "import_plugin",
    "load_yaml_references",
    "plugin",
]
