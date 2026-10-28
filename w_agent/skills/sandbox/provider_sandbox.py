"""Run the legacy skill API through a lifecycle-owned sandbox provider."""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from w_agent.exceptions.framework_errors import SkillSandboxError
from w_agent.models import CancellationToken
from w_agent.sandbox.types import (
    SandboxCommand, SandboxError, SandboxProvider, SandboxSpec, WorkspaceAccess,
)

from .wasm_sandbox import SkillSandbox, WasmSkillSandbox


class ProviderSkillSandbox(SkillSandbox):
    """Copy only the selected script and JSON arguments into a fresh workspace.

    The spec is a resource/environment template. Its workspace is replaced with
    a temporary read-only payload for each execution; arbitrary sibling files
    and the original project are not mounted. No provider fallback is attempted.
    """

    def __init__(
        self,
        provider: SandboxProvider,
        spec: SandboxSpec,
        *,
        python_executable: str = "python",
        timeout: float = 30,
        max_output_bytes: int = 1_048_576,
    ) -> None:
        self.command = SandboxCommand(
            (python_executable, "runner.py"),
            timeout=timeout,
            max_output_bytes=max_output_bytes,
        )
        self.provider = provider
        self.spec = spec

    async def execute(
        self, skill: Any, script_name: str, args: dict,
        *, cancellation: CancellationToken | None = None,
    ) -> dict[str, Any]:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        script = WasmSkillSandbox._validate_request(skill, script_name, args)
        try:
            serialized = json.dumps(args, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise SkillSandboxError("Skill args are not JSON serializable") from exc
        with tempfile.TemporaryDirectory(prefix="w-agent-skill-") as directory:
            # The outer directory stays private on the host. Only its payload
            # child is mounted, permitting guest uid traversal without exposing
            # argument files to unrelated host users.
            root = Path(directory) / "payload"
            root.mkdir()
            # A curated non-root guest user must be able to traverse/read this
            # otherwise private host staging directory through a bind mount.
            root.chmod(0o755)
            (root / "skill.py").write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
            (root / "args.json").write_text(serialized, encoding="utf-8")
            runner_source = WasmSkillSandbox._RUNNER_SOURCE.replace('"/workspace/', '"')
            (root / "runner.py").write_text(runner_source, encoding="utf-8")
            for path in root.iterdir():
                path.chmod(0o644)
            spec = replace(self.spec, workspace=root, workspace_access=WorkspaceAccess.READ_ONLY)
            try:
                handle = await self.provider.open(spec, cancellation=cancellation)
                try:
                    result = await handle.execute(self.command, cancellation=cancellation)
                    if result.exit_code != 0:
                        raise SkillSandboxError(
                            f"Sandbox skill command failed with status {result.exit_code}"
                        )
                    return _decode_result(result.stdout)
                finally:
                    await handle.close()
            except SandboxError as exc:
                raise SkillSandboxError(f"Sandbox skill execution failed: {exc}") from exc


def _decode_result(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SkillSandboxError("Sandbox skill returned invalid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        raise SkillSandboxError("Sandbox skill returned an invalid envelope")
    if not payload["ok"]:
        raise SkillSandboxError(
            f"Guest {payload.get('error_type', 'SkillError')}: {payload.get('error', 'unknown error')}"
        )
    return {"result": payload.get("result")}
