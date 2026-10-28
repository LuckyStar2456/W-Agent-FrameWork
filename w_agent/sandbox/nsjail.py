"""Linux nsjail provider requiring cgroup v2 resource enforcement."""

from __future__ import annotations

import asyncio
import math
import tempfile
from pathlib import Path

from w_agent.models import CancellationToken

from .docker import OciCliRunner
from .process import LocalProcessRunner
from .types import (
    SandboxCommand, SandboxError, SandboxExecutionError, SandboxHandle,
    SandboxNetwork, SandboxResult, SandboxSpec, SandboxUnavailableError,
    WorkspaceAccess,
)


_SECCOMP_POLICY = (
    "KILL { ptrace, process_vm_readv, process_vm_writev, open_by_handle_at, "
    "mount, umount2, pivot_root, kexec_load, init_module, finit_module, "
    "delete_module, bpf, userfaultfd, socket, socketpair, connect, accept, "
    "accept4, bind, listen } DEFAULT ALLOW"
)

# The MountPt fields come from google/nsjail config.proto. The CLI --mount
# options string is filesystem-specific data, NOT a mount(2) flag parser.
# Keep this static: caller-controlled paths, argv and environment never enter
# protobuf text, and --config precedes all CLI overrides (parseFile CopyFrom).
_MOUNT_CONFIG = '''mount_proc: true
mount {
  dst: "/tmp"
  fstype: "tmpfs"
  options: "size=67108864,mode=1777"
  rw: true
  is_dir: true
  mandatory: true
  nosuid: true
  nodev: true
  noexec: true
}
'''

# nsjail's uint32 cgroup_cpu_ms_per_sec is multiplied by 1000U when
# writing cpu.max; bound the converted quota as well as the CLI value.
_MAX_CPU_MILLISECONDS = (2**32 - 1) // 1000


class NsJailSandboxProvider:
    """One fresh jail per command, with a shared explicit workspace.

    The host must provision a curated rootfs and delegated cgroup v2 directory.
    nsjail failure is returned to the caller; no limits or isolation are retried
    with weaker settings. An injected runner is trusted host code.
    """

    def __init__(
        self,
        rootfs: Path,
        *,
        cgroup_path: Path = Path("/sys/fs/cgroup"),
        executable: str = "nsjail",
        runner: OciCliRunner | None = None,
    ) -> None:
        self.rootfs = Path(rootfs).resolve()
        self.cgroup_path = Path(cgroup_path).resolve()
        if self.rootfs == Path(self.rootfs.anchor):
            raise ValueError("nsjail requires a curated rootfs, not the host root")
        if not executable or "\0" in executable:
            raise ValueError("nsjail executable is invalid")
        self.executable = executable
        self.runner = runner or LocalProcessRunner()

    async def available(self) -> bool:
        if not self.rootfs.is_dir() or not self.cgroup_path.is_dir():
            return False
        try:
            result = await self.runner.run(
                (self.executable, "--help"), timeout=5, max_output_bytes=65_536,
            )
        except (OSError, SandboxError):
            return False
        return result.exit_code == 0

    async def open(
        self, spec: SandboxSpec, *, cancellation: CancellationToken | None = None,
    ) -> SandboxHandle:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        if not spec.workspace.is_dir():
            raise SandboxError("sandbox workspace must be an existing directory")
        if spec.network is not SandboxNetwork.NONE:
            raise SandboxError("nsjail provider only enforces network=none")
        if spec.image is not None or spec.inherit_host_environment:
            raise SandboxError("nsjail uses curated rootfs and explicit environment")
        if not 0.001 <= spec.cpu_limit <= _MAX_CPU_MILLISECONDS / 1000:
            raise SandboxError("nsjail CPU limit must fit millisecond cgroup quota")
        if any(char in str(spec.workspace) for char in ":\r\n"):
            raise SandboxError("nsjail workspace contains unsupported mount delimiters")
        if spec.user is None or not _numeric_user(spec.user):
            raise SandboxError("nsjail requires an explicit numeric uid:gid")
        if not await self.available():
            raise SandboxUnavailableError("nsjail, curated rootfs, or cgroup directory unavailable")
        return NsJailSandboxHandle(self, spec)

    def command_arguments(
        self, spec: SandboxSpec, command: SandboxCommand, *, config_path: Path,
    ) -> tuple[str, ...]:
        uid, gid = spec.user.split(":")
        mount_flag = "--bindmount_ro" if spec.workspace_access is WorkspaceAccess.READ_ONLY else "--bindmount"
        arguments = [
            self.executable, "--config", str(config_path),
            "--mode", "o", "--chroot", str(self.rootfs),
            "--cwd", spec.container_workdir, "--user", uid, "--group", gid,
            "--use_cgroupv2", "--cgroupv2_mount", str(self.cgroup_path),
            "--cgroup_cpu_ms_per_sec", str(math.floor(spec.cpu_limit * 1000)),
            "--cgroup_mem_max", str(spec.memory_bytes),
            "--cgroup_pids_max", str(spec.pids_limit),
            "--time_limit", str(math.ceil(command.timeout)),
            "--rlimit_cpu", str(math.ceil(command.timeout)),
            "--rlimit_as", str(max(1, spec.memory_bytes // (1024 * 1024))),
            "--rlimit_nofile", "64", "--iface_no_lo",
            "--seccomp_string", _SECCOMP_POLICY,
            mount_flag, f"{spec.workspace}:{spec.container_workdir}",
        ]
        for key, value in spec.environment.items():
            arguments.extend(("--env", f"{key}={value}"))
        return (*arguments, "--", *command.argv)


class NsJailSandboxHandle:
    def __init__(self, provider: NsJailSandboxProvider, spec: SandboxSpec) -> None:
        self.provider = provider
        self.spec = spec
        self._closed = False
        self._lock = asyncio.Lock()

    async def execute(
        self, command: SandboxCommand, *, cancellation: CancellationToken | None = None,
    ) -> SandboxResult:
        async with self._lock:
            if self._closed:
                raise SandboxExecutionError("nsjail sandbox handle is closed")
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            try:
                # An exclusive private directory prevents collisions with user
                # configs. It stays alive until the runner has exited, including
                # its timeout/cancellation cleanup, and is then always removed.
                with tempfile.TemporaryDirectory(prefix="w-agent-nsjail-config-") as directory:
                    config_path = Path(directory) / "mounts.cfg"
                    with config_path.open("x", encoding="utf-8", newline="\n") as stream:
                        config_path.chmod(0o600)
                        stream.write(_MOUNT_CONFIG)
                    return await self.provider.runner.run(
                        self.provider.command_arguments(
                            self.spec, command, config_path=config_path,
                        ),
                        timeout=command.timeout,
                        max_output_bytes=command.max_output_bytes,
                        cancellation=cancellation,
                    )
            except BaseException:
                self._closed = True
                raise

    async def close(self) -> None:
        async with self._lock:
            self._closed = True

    async def __aenter__(self) -> NsJailSandboxHandle:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.close()


def _numeric_user(user: str) -> bool:
    parts = user.split(":")
    return len(parts) == 2 and all(part.isascii() and part.isdecimal() for part in parts)
