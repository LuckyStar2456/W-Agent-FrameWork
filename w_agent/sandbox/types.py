"""Provider-neutral sandbox contracts for local agent development."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping, Protocol

from w_agent.models import CancellationToken


class SandboxNetwork(StrEnum):
    NONE = "none"
    BRIDGE = "bridge"


class WorkspaceAccess(StrEnum):
    READ_ONLY = "read-only"
    READ_WRITE = "read-write"


@dataclass(frozen=True, slots=True)
class SandboxSpec:
    workspace: Path
    image: str | None = None
    workspace_access: WorkspaceAccess = WorkspaceAccess.READ_WRITE
    network: SandboxNetwork = SandboxNetwork.NONE
    cpu_limit: float = 1.0
    memory_bytes: int = 512 * 1024 * 1024
    pids_limit: int = 128
    environment: Mapping[str, str] = field(default_factory=dict)
    inherit_host_environment: bool = False
    container_workdir: str = "/workspace"
    user: str | None = "65534:65534"
    keepalive_command: tuple[str, ...] = (
        "sh",
        "-c",
        "trap : TERM INT; sleep infinity & wait",
    )

    def __post_init__(self) -> None:
        workspace = Path(self.workspace).resolve()
        if not isinstance(self.container_workdir, str):
            raise ValueError("container workdir must be a string")
        if self.image is not None and (not isinstance(self.image, str) or "\0" in self.image):
            raise ValueError("sandbox image must be a safe string")
        if self.user is not None and (not isinstance(self.user, str) or not self.user or "\0" in self.user):
            raise ValueError("sandbox user must be a safe string")
        workdir = PurePosixPath(self.container_workdir)
        if (not workdir.is_absolute() or ".." in workdir.parts
                or any(char in self.container_workdir for char in "\0\n\r,:")):
            raise ValueError("container workdir must be an absolute safe path")
        _positive_number(self.cpu_limit, "cpu_limit")
        _positive_integer(self.memory_bytes, "memory_bytes")
        _positive_integer(self.pids_limit, "pids_limit")
        _validate_argv(self.keepalive_command, "sandbox keepalive command")
        if not isinstance(self.inherit_host_environment, bool):
            raise ValueError("inherit_host_environment must be a boolean")
        object.__setattr__(self, "network", SandboxNetwork(self.network))
        object.__setattr__(self, "workspace_access", WorkspaceAccess(self.workspace_access))
        _validate_environment(self.environment)
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(
            self,
            "environment",
            MappingProxyType(dict(self.environment)),
        )
        object.__setattr__(self, "keepalive_command", tuple(self.keepalive_command))


@dataclass(frozen=True, slots=True)
class SandboxCommand:
    argv: tuple[str, ...]
    timeout: float = 30
    max_output_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        _validate_argv(self.argv, "sandbox command argv")
        _positive_number(self.timeout, "timeout")
        _positive_integer(self.max_output_bytes, "max_output_bytes")
        object.__setattr__(self, "argv", tuple(self.argv))


@dataclass(frozen=True, slots=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str


class SandboxHandle(Protocol):
    async def execute(
        self,
        command: SandboxCommand,
        *,
        cancellation: CancellationToken | None = None,
    ) -> SandboxResult: ...

    async def close(self) -> None: ...


class SandboxProvider(Protocol):
    async def open(
        self,
        spec: SandboxSpec,
        *,
        cancellation: CancellationToken | None = None,
    ) -> SandboxHandle: ...


class SandboxError(RuntimeError):
    """A sandbox could not be created, used, or closed safely."""


class SandboxUnavailableError(SandboxError):
    """The selected isolation backend is unavailable."""


class SandboxExecutionError(SandboxError):
    """A sandbox command could not be executed safely."""


class SandboxTimeoutError(SandboxExecutionError):
    """A sandbox command exceeded its time limit."""


class SandboxOutputTooLarge(SandboxExecutionError):
    """A sandbox stream exceeded its byte limit."""


def _positive_number(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number")
    try:
        valid = math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a finite positive number")


def _positive_integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_argv(argv, name: str) -> None:
    if isinstance(argv, (str, bytes)) or not isinstance(argv, (tuple, list)) or not argv:
        raise ValueError(f"{name} must be a non-empty argument sequence")
    if any(not isinstance(value, str) or "\0" in value for value in argv) or not argv[0]:
        raise ValueError(f"{name} must contain safe strings")


def _validate_environment(environment: Mapping[str, str]) -> None:
    for name, value in environment.items():
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or not name
            or "=" in name
            or "\0" in name
            or "\0" in value
            or "\n" in name
            or "\n" in value
            or "\r" in name
            or "\r" in value
        ):
            raise ValueError("sandbox environment contains an invalid entry")
