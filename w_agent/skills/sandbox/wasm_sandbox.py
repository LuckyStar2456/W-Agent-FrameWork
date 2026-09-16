"""Fail-closed WebAssembly sandbox for skill execution.

Python source is executed only after compilation to a real Wasm module and
only when a Wasm runtime is available. Host-interpreter ``exec`` fallback is
deliberately forbidden.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict

from w_agent.exceptions.framework_errors import SkillSandboxError


class SkillSandbox:
    """Skill sandbox interface."""

    async def execute(self, skill: Any, script_name: str, args: Dict) -> Any:
        raise NotImplementedError


class WasmSkillSandbox(SkillSandbox):
    """Execute a Python skill only through a real Wasm toolchain/runtime."""

    def __init__(self, precompiled_path: Path | None = None):
        self.forbidden_modules = ("os", "subprocess", "ctypes")
        self.cache_dir = Path(tempfile.gettempdir()) / "w_agent_wasm_cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.precompiled_path = Path(precompiled_path) if precompiled_path else None
        self.pyodide_available = self._check_pyodide_available()
        self.wasmer_available = self._check_wasmer_available()

    @property
    def available(self) -> bool:
        """Whether both compilation and execution backends are available."""
        return self.pyodide_available and self.wasmer_available

    def _check_pyodide_available(self) -> bool:
        if importlib.util.find_spec("pyodide") is not None:
            try:
                from pyodide import compile_python  # noqa: F401
                return True
            except (ImportError, AttributeError):
                pass
        try:
            result = subprocess.run(
                ["pyodide", "--version"],
                capture_output=True,
                check=False,
                timeout=5,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _check_wasmer_available() -> bool:
        return (
            importlib.util.find_spec("wasmer") is not None
            and importlib.util.find_spec("wasmer_compiler_cranelift") is not None
        )

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

    async def execute(self, skill: Any, script_name: str, args: Dict) -> Dict[str, Any]:
        script_path = self._validate_request(skill, script_name, args)
        if not self.available:
            missing = []
            if not self.pyodide_available:
                missing.append("Pyodide compiler")
            if not self.wasmer_available:
                missing.append("Wasmer runtime")
            raise SkillSandboxError(
                "Wasm sandbox unavailable; missing " + " and ".join(missing)
            )

        wasm_path: Path | None = None
        try:
            wasm_path = await self._compile_to_wasm(script_path)
            return await self._execute_wasm(wasm_path, args)
        except SkillSandboxError:
            raise
        except Exception as exc:
            raise SkillSandboxError(f"Wasm skill execution failed: {exc}") from exc
        finally:
            if wasm_path and wasm_path.exists() and wasm_path.parent == self.cache_dir:
                wasm_path.unlink(missing_ok=True)

    async def _compile_to_wasm(self, script_path: Path) -> Path:
        script_content = script_path.read_text(encoding="utf-8")
        wrapper = f"""
import builtins
import json

builtins.eval = None
builtins.exec = None
original_import = builtins.__import__
def safe_import(name, *args, **kwargs):
    forbidden = {self.forbidden_modules!r}
    if name.split('.')[0] in forbidden:
        raise ImportError(f"Module {{name}} forbidden")
    return original_import(name, *args, **kwargs)
builtins.__import__ = safe_import

args = json.loads(input())
{script_content}
if 'execute' in locals():
    result = execute(args)
print(json.dumps({{"result": result if 'result' in locals() else None}}))
"""
        content_hash = hashlib.sha256(wrapper.encode("utf-8")).hexdigest()
        cached_wasm = self.cache_dir / f"skill_{content_hash}.wasm"

        if self.precompiled_path:
            precompiled = self.precompiled_path / cached_wasm.name
            if precompiled.is_file():
                return precompiled
        if cached_wasm.is_file():
            return cached_wasm

        try:
            from pyodide import compile_python

            cached_wasm.write_bytes(compile_python(wrapper))
        except (ImportError, AttributeError):
            temp_py = self.cache_dir / f"skill_{content_hash}.py"
            try:
                temp_py.write_text(wrapper, encoding="utf-8")
                result = subprocess.run(
                    ["pyodide", "build", str(temp_py), "--output", str(cached_wasm)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode != 0 or not cached_wasm.is_file():
                    raise SkillSandboxError(
                        f"Pyodide compilation failed: {result.stderr.strip()}"
                    )
            finally:
                temp_py.unlink(missing_ok=True)
        return cached_wasm

    async def _execute_wasm(self, wasm_path: Path, args: Dict) -> Dict[str, Any]:
        try:
            from wasmer import Instance, Module, Store, engine
            from wasmer_compiler_cranelift import Compiler
        except ImportError as exc:
            raise SkillSandboxError("Wasmer runtime is unavailable") from exc

        try:
            store = Store(engine.JIT(Compiler))
            module = Module(store, wasm_path.read_bytes())
            instance = Instance(module)
            if not hasattr(instance.exports, "main"):
                raise SkillSandboxError("Wasm module does not export main")
            result = instance.exports.main(json.dumps(args))
            return {"result": result}
        except SkillSandboxError:
            raise
        except Exception as exc:
            raise SkillSandboxError(f"Wasm runtime failed: {exc}") from exc
