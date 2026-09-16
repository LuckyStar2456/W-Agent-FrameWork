"""Fail-closed nsjail-backed skill sandbox."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict

from w_agent.exceptions.framework_errors import SkillSandboxError
from w_agent.skills.sandbox.wasm_sandbox import SkillSandbox


class NsJailSkillSandbox(SkillSandbox):
    def __init__(
        self,
        max_cpu_seconds: int = 5,
        max_memory_bytes: int = 100 * 1024 * 1024,
        rootfs_path: Path | None = None,
        python_executable: str = "/usr/bin/python3",
    ):
        if max_cpu_seconds <= 0 or max_memory_bytes <= 0:
            raise ValueError("sandbox resource limits must be positive")
        python_path = PurePosixPath(python_executable)
        if not python_path.is_absolute() or ".." in python_path.parts:
            raise ValueError("python_executable must be an absolute path inside rootfs")
        self.max_cpu_seconds = max_cpu_seconds
        self.max_memory_bytes = max_memory_bytes
        configured_rootfs = rootfs_path or os.getenv("W_AGENT_NSJAIL_ROOTFS")
        self.rootfs_path = (
            Path(configured_rootfs).resolve() if configured_rootfs else None
        )
        self.python_executable = str(python_path)
        self.nsjail_available = self._check_nsjail_availability()

    @property
    def available(self) -> bool:
        return self.nsjail_available and self.rootfs_available

    @property
    def rootfs_available(self) -> bool:
        """Whether a curated, non-host-root filesystem contains Python."""
        if self.rootfs_path is None or not self.rootfs_path.is_dir():
            return False
        if self.rootfs_path == Path(self.rootfs_path.anchor):
            return False
        python_path = self.rootfs_path / self.python_executable.lstrip("/")
        return python_path.is_file()

    @staticmethod
    def _check_nsjail_availability() -> bool:
        executable = shutil.which("nsjail")
        if not executable:
            return False
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                check=False,
                timeout=5,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    async def execute(self, skill: Any, script_name: str, args: Dict) -> Dict[str, Any]:
        script_path = self._validate_request(skill, script_name, args)
        if not self.available:
            missing = []
            if not self.nsjail_available:
                missing.append("nsjail executable")
            if not self.rootfs_available:
                missing.append(
                    f"curated rootfs containing {self.python_executable}"
                )
            raise SkillSandboxError(
                "nsjail sandbox unavailable; refusing unsafe fallback; missing "
                + " and ".join(missing)
            )

        with tempfile.TemporaryDirectory(prefix="w_agent_nsjail_") as sandbox_root:
            root = Path(sandbox_root)
            (root / "skill.py").write_text(
                script_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            (root / "runner.py").write_text(
                "import json\n"
                "import runpy\n"
                "import sys\n"
                "namespace = runpy.run_path('/sandbox/skill.py')\n"
                "if 'execute' not in namespace:\n"
                "    raise RuntimeError('skill must define execute(args)')\n"
                "print(json.dumps({'result': namespace['execute'](json.loads(sys.argv[1]))}))\n",
                encoding="utf-8",
            )
            return await self._execute_with_nsjail(root, args)

    @staticmethod
    def _validate_request(skill: Any, script_name: str, args: Dict) -> Path:
        if skill is None or not script_name:
            raise SkillSandboxError("skill and script_name are required")
        if not isinstance(args, dict):
            raise SkillSandboxError("args must be a dictionary")
        scripts = getattr(skill, "scripts", None)
        if not isinstance(scripts, dict) or script_name not in scripts:
            raise SkillSandboxError(f"Unknown skill script: {script_name}")
        script_path = Path(scripts[script_name]).resolve()
        if not script_path.is_file():
            raise SkillSandboxError(f"Skill script does not exist: {script_path}")
        skill_dir = getattr(skill, "get_skill_dir", lambda: None)()
        if skill_dir is not None:
            try:
                script_path.relative_to(Path(skill_dir).resolve())
            except ValueError as exc:
                raise SkillSandboxError("Skill script is outside its skill directory") from exc
        return script_path

    async def _execute_with_nsjail(self, sandbox_root: Path, args: Dict) -> Dict[str, Any]:
        executable = shutil.which("nsjail")
        if not executable:
            raise SkillSandboxError("nsjail executable disappeared before execution")
        if not self.rootfs_available:
            raise SkillSandboxError("curated nsjail rootfs is unavailable")

        seccomp_policy = (
            "KILL { clone, clone3, fork, vfork, ptrace, process_vm_readv, "
            "process_vm_writev, open_by_handle_at, mount, umount2, pivot_root, "
            "kexec_load, init_module, finit_module, delete_module, bpf, "
            "userfaultfd, socket, socketpair, connect, accept, accept4, bind, "
            "listen } DEFAULT ALLOW"
        )

        cmd = [
            executable,
            "--mode", "o",
            "--chroot", str(self.rootfs_path),
            "--time_limit", str(self.max_cpu_seconds),
            "--rlimit_cpu", str(self.max_cpu_seconds),
            "--rlimit_as", str(self.max_memory_bytes // (1024 * 1024)),
            "--rlimit_nofile", "64",
            "--tmpfsmount", "/tmp",
            "--seccomp_string", seccomp_policy,
            "--bindmount_ro", f"{sandbox_root}:/sandbox",
            "--cwd", "/sandbox",
            "--",
            self.python_executable,
            "/sandbox/runner.py",
            json.dumps(args),
        ]

        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.max_cpu_seconds + 2,
            )

        try:
            result = await asyncio.to_thread(run)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SkillSandboxError(f"nsjail execution failed: {exc}") from exc
        if result.returncode != 0:
            raise SkillSandboxError(
                f"nsjail rejected skill execution: {result.stderr.strip()}"
            )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SkillSandboxError("nsjail returned invalid JSON") from exc
