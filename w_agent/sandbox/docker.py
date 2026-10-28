"""Docker/OCI sandbox provider with fail-closed lifecycle management."""

from __future__ import annotations

import asyncio
import os
import secrets
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from w_agent.models import CancellationToken

from .process import LocalProcessRunner
from .types import (
    SandboxCommand,
    SandboxError,
    SandboxExecutionError,
    SandboxHandle,
    SandboxProvider,
    SandboxResult,
    SandboxSpec,
    SandboxUnavailableError,
    WorkspaceAccess,
)


class OciCliRunner(Protocol):
    async def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 30,
        max_output_bytes: int = 1_048_576,
        cancellation: CancellationToken | None = None,
    ) -> SandboxResult: ...


class DockerSandboxProvider(SandboxProvider):
    """Create hardened, lifecycle-owned containers through the Docker CLI."""

    def __init__(
        self,
        *,
        executable: str = "docker",
        runner: OciCliRunner | None = None,
        allow_mutable_images: bool = False,
        name_prefix: str = "wagent",
        pull_policy: str = "never",
    ) -> None:
        if not executable.strip() or not name_prefix.strip():
            raise ValueError("Docker executable and name prefix must not be empty")
        if pull_policy not in {"never", "missing", "always"}:
            raise ValueError("Docker pull policy must be never, missing, or always")
        self.executable = executable
        self.runner = runner or _DockerCliRunner()
        self.allow_mutable_images = allow_mutable_images
        self.name_prefix = name_prefix
        self.pull_policy = pull_policy

    async def available(self) -> bool:
        try:
            result = await self.runner.run(
                (self.executable, "version", "--format", "{{.Server.Version}}"),
                timeout=5,
                max_output_bytes=16_384,
            )
        except (OSError, SandboxError):
            return False
        return result.exit_code == 0 and bool(result.stdout.strip())

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
        if any(char in str(spec.workspace) for char in ",\r\n"):
            raise SandboxError("Docker workspace contains unsupported mount delimiters")
        if spec.inherit_host_environment:
            raise SandboxError("Docker requires explicit environment entries")
        if spec.image is None or not spec.image.strip():
            raise SandboxError("Docker sandbox requires an image")
        if spec.image.startswith("-") or any(char.isspace() for char in spec.image):
            raise SandboxError("Docker image reference is invalid")
        if not self.allow_mutable_images and not _is_fixed_image(spec.image):
            raise SandboxError(
                "Docker image needs a non-latest tag or digest; mutable images "
                "require explicit provider opt-in"
            )
        if not await self.available():
            raise SandboxUnavailableError("Docker daemon is unavailable")

        name = f"{self.name_prefix}-{secrets.token_hex(8)}"
        arguments = self._run_arguments(name, spec)
        environment_path = None
        creation_attempted = False
        try:
            if spec.environment:
                environment_path = _write_environment_file(spec.environment)
                arguments.extend(("--env-file", str(environment_path)))
            arguments.extend((spec.image, *spec.keepalive_command))
            creation_attempted = True
            result = await self.runner.run(
                (self.executable, *arguments),
                timeout=30,
                max_output_bytes=65_536,
                cancellation=cancellation,
            )
            if result.exit_code != 0:
                raise SandboxUnavailableError(
                    f"Docker container creation failed with status {result.exit_code}"
                )
        except BaseException:
            if creation_attempted:
                # A timed-out CLI may already have created the named container.
                # Cleanup intentionally does not reuse the cancelled token.
                try:
                    await self.runner.run(
                        (self.executable, "rm", "--force", name),
                        timeout=10,
                        max_output_bytes=65_536,
                    )
                except Exception:
                    pass
            raise
        finally:
            if environment_path is not None:
                environment_path.unlink(missing_ok=True)
        return DockerSandboxHandle(self.executable, name, self.runner)

    def _run_arguments(self, name: str, spec: SandboxSpec) -> list[str]:
        mount = f"type=bind,source={spec.workspace},target={spec.container_workdir}"
        if spec.workspace_access is WorkspaceAccess.READ_ONLY:
            mount += ",readonly"
        arguments = [
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "--pull",
            self.pull_policy,
            "--network",
            spec.network.value,
            "--cpus",
            str(spec.cpu_limit),
            "--memory",
            str(spec.memory_bytes),
            "--pids-limit",
            str(spec.pids_limit),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=67108864",
            "--mount",
            mount,
            "--workdir",
            spec.container_workdir,
        ]
        if spec.user is not None:
            arguments.extend(("--user", spec.user))
        return arguments


class DockerSandboxHandle(SandboxHandle):
    def __init__(
        self,
        executable: str,
        container_name: str,
        runner: OciCliRunner,
    ) -> None:
        self.executable = executable
        self.container_name = container_name
        self.runner = runner
        self._closed = False
        self._removed = False
        self._lock = asyncio.Lock()

    async def execute(
        self,
        command: SandboxCommand,
        *,
        cancellation: CancellationToken | None = None,
    ) -> SandboxResult:
        async with self._lock:
            if self._closed:
                raise SandboxExecutionError("Docker sandbox handle is closed")
            try:
                return await self.runner.run(
                    (
                        self.executable,
                        "exec",
                        self.container_name,
                        *command.argv,
                    ),
                    timeout=command.timeout,
                    max_output_bytes=command.max_output_bytes,
                    cancellation=cancellation,
                )
            except BaseException:
                try:
                    await self._close_locked()
                except Exception:
                    pass
                raise

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        if self._removed:
            return
        self._closed = True
        try:
            result = await self.runner.run(
                (self.executable, "rm", "--force", self.container_name),
                timeout=10,
                max_output_bytes=65_536,
            )
            if result.exit_code != 0:
                raise SandboxError("Docker remove returned a failure status")
            self._removed = True
        except Exception as exc:
            raise SandboxError("failed to remove Docker sandbox") from exc

    async def __aenter__(self) -> DockerSandboxHandle:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()


class _DockerCliRunner:
    def __init__(self) -> None:
        self._runner = LocalProcessRunner()

    async def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 30,
        max_output_bytes: int = 1_048_576,
        cancellation: CancellationToken | None = None,
    ) -> SandboxResult:
        return await self._runner.run(
            argv,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
            cancellation=cancellation,
        )


def _is_fixed_image(image: str) -> bool:
    if "@sha256:" in image:
        return True
    last = image.rsplit("/", 1)[-1]
    return ":" in last and not last.endswith(":latest")


def _write_environment_file(environment) -> Path:
    descriptor, name = tempfile.mkstemp(prefix="wagent-env-", suffix=".list")
    path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            for key, value in environment.items():
                stream.write(f"{key}={value}\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise
