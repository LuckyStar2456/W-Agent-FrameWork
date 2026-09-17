"""Explicitly authorized, non-isolated local development backend."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from w_agent.models import CancellationToken

from .process import LocalProcessRunner
from .types import (
    SandboxCommand,
    SandboxError,
    SandboxExecutionError,
    SandboxHandle,
    SandboxNetwork,
    SandboxProvider,
    SandboxResult,
    SandboxSpec,
    WorkspaceAccess,
)


_AUTHORIZATION_SENTINEL = object()


@dataclass(frozen=True, slots=True, init=False)
class UnsafeLocalAuthorization:
    """Runtime-only proof that the local developer acknowledged host access."""

    source: str
    granted_at: datetime

    def __init__(self, source: str, sentinel: object) -> None:
        if sentinel is not _AUTHORIZATION_SENTINEL:
            raise PermissionError(
                "use UnsafeLocalAuthorization.grant() for explicit authorization"
            )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "granted_at", datetime.now(UTC))

    @classmethod
    def grant(
        cls,
        source: str,
        *,
        acknowledge_host_access: bool,
    ) -> UnsafeLocalAuthorization:
        if not source or not source.strip():
            raise ValueError("unsafe local authorization source must not be empty")
        if not acknowledge_host_access:
            raise PermissionError(
                "unsafe local execution requires acknowledgement of host access"
            )
        return cls(source.strip(), _AUTHORIZATION_SENTINEL)


class UnsafeLocalSandboxProvider(SandboxProvider):
    """Dangerous host execution for an explicitly authorized development run."""

    warning = (
        "UnsafeLocalSandbox is not isolated and can access host files, "
        "processes, credentials, and network"
    )

    def __init__(self, authorization: UnsafeLocalAuthorization) -> None:
        if not isinstance(authorization, UnsafeLocalAuthorization):
            raise PermissionError(
                "UnsafeLocalSandbox requires explicit runtime authorization"
            )
        self.authorization = authorization

    async def open(
        self,
        spec: SandboxSpec,
        *,
        cancellation: CancellationToken | None = None,
    ) -> SandboxHandle:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        if not spec.workspace.is_dir():
            raise SandboxError("sandbox workspace must be an existing directory")
        if spec.network is not SandboxNetwork.BRIDGE:
            raise SandboxError(
                "unsafe local execution cannot enforce network isolation; "
                "select SandboxNetwork.BRIDGE explicitly"
            )
        if spec.workspace_access is not WorkspaceAccess.READ_WRITE:
            raise SandboxError(
                "unsafe local execution cannot enforce a read-only workspace"
            )
        return UnsafeLocalSandboxHandle(spec)


class UnsafeLocalSandboxHandle(SandboxHandle):
    def __init__(self, spec: SandboxSpec) -> None:
        self.spec = spec
        self._runner = LocalProcessRunner()
        self._closed = False
        self._lock = asyncio.Lock()

    async def execute(
        self,
        command: SandboxCommand,
        *,
        cancellation: CancellationToken | None = None,
    ) -> SandboxResult:
        async with self._lock:
            if self._closed:
                raise SandboxExecutionError("unsafe local sandbox handle is closed")
            return await self._runner.run(
                command.argv,
                cwd=self.spec.workspace,
                environment=self.spec.environment,
                inherit_environment=self.spec.inherit_host_environment,
                timeout=command.timeout,
                max_output_bytes=command.max_output_bytes,
                cancellation=cancellation,
            )

    async def close(self) -> None:
        async with self._lock:
            self._closed = True

    async def __aenter__(self) -> UnsafeLocalSandboxHandle:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()
