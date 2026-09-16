#!/usr/bin/env python3
"""Real wasmer-sdk smoke test for Linux/macOS integration environments."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from w_agent import Skill, SkillSandboxError, WasmSkillSandbox


def make_skill(root: Path, name: str, source: str) -> Skill:
    script_path = root / f"{name}.py"
    script_path.write_text(source, encoding="utf-8")
    skill = Skill(name, f"{name} integration skill", {name: script_path})
    skill.set_skill_dir(root)
    return skill


async def main() -> None:
    results = {}
    with tempfile.TemporaryDirectory(prefix="wagent-wasmer-smoke-") as temp_dir:
        skill_root = Path(temp_dir)
        sandbox = WasmSkillSandbox(
            cache_root=skill_root / "cache",
            max_execution_seconds=120,
        )
        try:
            normal = make_skill(
                skill_root,
                "normal",
                "def execute(params):\n"
                "    return {'echo': params['value'], 'isolated': True}\n",
            )
            results["normal"] = await sandbox.execute(
                normal, "normal", {"value": "ok"}
            )
            assert results["normal"] == {
                "result": {"echo": "ok", "isolated": True}
            }

            network = make_skill(
                skill_root,
                "network",
                "from urllib.request import urlopen\n"
                "def execute(params):\n"
                "    return urlopen('https://example.com', timeout=1).read().decode()\n",
            )
            sandbox.max_execution_seconds = 10
            try:
                await sandbox.execute(network, "network", {})
            except SkillSandboxError as exc:
                results["network"] = "blocked"
                results["network_error"] = str(exc)
            else:
                raise AssertionError("guest network access unexpectedly succeeded")

            slow = make_skill(
                skill_root,
                "slow",
                "import time\n"
                "def execute(params):\n"
                "    time.sleep(5)\n"
                "    return 'late'\n",
            )
            sandbox.max_execution_seconds = 0.2
            try:
                await sandbox.execute(slow, "slow", {})
            except SkillSandboxError as exc:
                assert "exceeded timeout" in str(exc)
                results["timeout"] = "blocked"
            else:
                raise AssertionError("guest timeout was not enforced")
        finally:
            await sandbox.close()

    print(json.dumps(results, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
