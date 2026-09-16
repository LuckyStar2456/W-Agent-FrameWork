"""Fail-closed Wasmer SDK sandbox for Python skill execution.

Skill source is copied into an isolated WASIX workspace and executed by the
Python package inside that sandbox. Host ``exec`` and subprocess fallbacks are
deliberately forbidden.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict

from w_agent.exceptions.framework_errors import SkillSandboxError


logger = logging.getLogger(__name__)


class SkillSandbox:
    """Skill sandbox interface."""

    async def execute(self, skill: Any, script_name: str, args: Dict) -> Any:
        raise NotImplementedError


class WasmSkillSandbox(SkillSandbox):
    """Run Python skills in an isolated Wasmer/WASIX sandbox."""

    _RUNNER_SOURCE = r'''
import asyncio
import contextlib
import inspect
import io
import json
import runpy


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False))


try:
    with open("/workspace/args.json", "r", encoding="utf-8") as args_file:
        args = json.load(args_file)

    captured_output = io.StringIO()
    with contextlib.redirect_stdout(captured_output), contextlib.redirect_stderr(captured_output):
        namespace = runpy.run_path(
            "/workspace/skill.py", init_globals={"args": args}
        )
        execute = namespace.get("execute")
        if callable(execute):
            result = execute(args)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
        else:
            result = namespace.get("result")

    emit({"ok": True, "result": result})
except BaseException as exc:
    emit({
        "ok": False,
        "error_type": type(exc).__name__,
        "error": str(exc),
    })
'''.lstrip()

    def __init__(
        self,
        precompiled_path: Path | None = None,
        *,
        cache_root: Path | None = None,
        python_package: str = "python/python@=3.13.18",
        max_execution_seconds: float = 30.0,
        client_factory: Callable[..., Any] | None = None,
    ):
        if precompiled_path is not None and cache_root is not None:
            raise ValueError("use either precompiled_path or cache_root, not both")
        if not python_package:
            raise ValueError("python_package must not be empty")
        if max_execution_seconds <= 0:
            raise ValueError("max_execution_seconds must be positive")

        configured_cache = cache_root or precompiled_path
        default_cache = Path(
            os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))
        ) / "w-agent" / "wasmer"
        self.cache_dir = Path(configured_cache or default_cache).resolve()
        # Compatibility alias for callers of the previous implementation.
        self.precompiled_path = Path(precompiled_path) if precompiled_path else None
        self.python_package = python_package
        self.max_execution_seconds = max_execution_seconds
        self._client = None
        self._client_lock = asyncio.Lock()
        self.backend_error: str | None = None

        if client_factory is not None:
            self._client_factory = client_factory
        else:
            self._client_factory = self._load_client_factory()

        self.wasmer_sdk_available = self._client_factory is not None
        # Compatibility attributes retained for existing diagnostics/users.
        self.wasmer_available = self.wasmer_sdk_available
        self.pyodide_available = False

    def _load_client_factory(self):
        try:
            from wasmer_sdk import Wasmer

            return Wasmer
        except Exception as exc:
            self.backend_error = f"{type(exc).__name__}: {exc}"
            return None

    @property
    def available(self) -> bool:
        """Whether the modern Wasmer Python SDK can be imported."""
        return self.wasmer_sdk_available

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
                raise SkillSandboxError(
                    "Skill script is outside its skill directory"
                ) from exc
        return script_path

    async def _get_client(self):
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                if self._client_factory is None:
                    raise SkillSandboxError("Wasmer SDK is unavailable")
                try:
                    self.cache_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
                    self._client = self._client_factory(
                        cache_root=str(self.cache_dir)
                    )
                except Exception as exc:
                    raise SkillSandboxError(
                        f"Wasmer SDK initialization failed: {exc}"
                    ) from exc
        return self._client

    async def execute(
        self, skill: Any, script_name: str, args: Dict
    ) -> Dict[str, Any]:
        script_path = self._validate_request(skill, script_name, args)
        if not self.available:
            detail = f" ({self.backend_error})" if self.backend_error else ""
            raise SkillSandboxError(
                "Wasm sandbox unavailable; missing wasmer-sdk" + detail
            )

        try:
            args_json = json.dumps(args, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise SkillSandboxError(f"Skill args are not JSON serializable: {exc}") from exc

        try:
            return await asyncio.wait_for(
                self._execute_once(script_path, args_json),
                timeout=self.max_execution_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise SkillSandboxError(
                f"Wasm skill exceeded timeout {self.max_execution_seconds}s"
            ) from exc
        except SkillSandboxError:
            raise
        except Exception as exc:
            raise SkillSandboxError(f"Wasm skill execution failed: {exc}") from exc

    async def _execute_once(
        self, script_path: Path, args_json: str
    ) -> Dict[str, Any]:
        client = await self._get_client()
        sandbox = None
        try:
            # Omitting ``network`` intentionally keeps guest networking disabled.
            sandbox = await client.sandboxes.create(
                packages=[self.python_package],
                files={
                    "skill.py": script_path.read_text(encoding="utf-8"),
                    "runner.py": self._RUNNER_SOURCE,
                    "args.json": args_json,
                },
            )
            output = await sandbox.command(
                "python", ["/workspace/runner.py"]
            ).run()
            return self._decode_output(output)
        finally:
            if sandbox is not None:
                try:
                    close_result = sandbox.close()
                    if inspect.isawaitable(close_result):
                        await close_result
                except Exception as exc:
                    logger.warning("Failed to close Wasmer sandbox: %s", exc)

    @staticmethod
    def _decode_output(output: Any) -> Dict[str, Any]:
        try:
            raw_output = output.text()
            payload = json.loads(raw_output.strip())
        except (AttributeError, TypeError, json.JSONDecodeError) as exc:
            raise SkillSandboxError("Wasmer sandbox returned invalid JSON") from exc
        if not isinstance(payload, dict) or "ok" not in payload:
            raise SkillSandboxError("Wasmer sandbox returned an invalid envelope")
        if not payload["ok"]:
            error_type = payload.get("error_type", "SkillError")
            error = payload.get("error", "unknown error")
            raise SkillSandboxError(f"Guest {error_type}: {error}")
        return {"result": payload.get("result")}

    async def close(self):
        """Close the shared Wasmer client and release runtime resources."""
        async with self._client_lock:
            client, self._client = self._client, None
        if client is not None:
            try:
                close_result = client.close()
                if inspect.isawaitable(close_result):
                    await close_result
            except Exception as exc:
                raise SkillSandboxError(
                    f"Wasmer SDK shutdown failed: {exc}"
                ) from exc

    async def __aenter__(self):
        if not self.available:
            raise SkillSandboxError("Wasm sandbox unavailable; missing wasmer-sdk")
        await self._get_client()
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self.close()
