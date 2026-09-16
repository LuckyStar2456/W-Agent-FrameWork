"""Errors raised by the W-Agent plugin microkernel."""


class KernelError(Exception):
    """Base class for microkernel failures."""


class RegistrationError(KernelError):
    """A contribution could not be registered."""


class CapabilityNotFoundError(KernelError):
    """No visible provider satisfies a capability request."""


class AmbiguousCapabilityError(KernelError):
    """A capability request matches several equally specific providers."""


class PluginError(KernelError):
    """Base class for plugin lifecycle failures."""


class PluginDependencyError(PluginError):
    """A required plugin capability is unavailable or incompatible."""


class PluginLoadError(PluginError):
    """A plugin failed while loading and its effects were rolled back."""


class PluginUnloadError(PluginError):
    """A plugin failed to unload cleanly."""
