"""Provider-neutral sandbox contracts for local agent development."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
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
        workdir = PurePosixPath(self.container_workdir)
        if not workdir.is_absolute() or ".." in workdir.parts:
            raise ValueError("container workdir must be an absolute safe path")
        if self.cpu_limit <= 0 or self.memory_bytes <= 0 or self.pids_limit <= 0:
            raise ValueError("sandbox resource limits must be positive")
        if not self.keepalive_command or any(
            not value or "\0" in value for value in self.keepalive_command
        ):
            raise ValueError("sandbox keepalive command is invalid")
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
        if not self.argv or any(
            not isinstance(value, str) or not value or "\0" in value
            for value in self.argv
        ):
            raise ValueError("sandbox command argv must contain safe strings")
        if self.timeout <= 0 or self.max_output_bytes <= 0:
            raise ValueError("sandbox command limits must be positive")
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
