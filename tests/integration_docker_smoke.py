"""Explicit real Docker smoke; uses a cached image with POSIX shell utilities."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

from w_agent import (
    DockerSandboxProvider,
    SandboxCommand,
    SandboxSpec,
    SandboxTimeoutError,
    WorkspaceAccess,
)


async def main(image: str) -> None:
    provider = DockerSandboxProvider(name_prefix="wagent-release-smoke")
    assert await provider.available(), "Docker must be running"
    with tempfile.TemporaryDirectory(prefix="wagent-docker-smoke-") as directory:
        handle = await provider.open(
            SandboxSpec(
                Path(directory), image=image,
                workspace_access=WorkspaceAccess.READ_ONLY,
                environment={"WAGENT_SMOKE": "visible"},
            )
        )
        try:
            inspection = subprocess.run(
                ["docker", "inspect", handle.container_name],
                check=True, capture_output=True, text=True, timeout=10,
            )
            config = json.loads(inspection.stdout)[0]
            assert config["HostConfig"]["NetworkMode"] == "none"
            assert config["HostConfig"]["ReadonlyRootfs"] is True
            assert "ALL" in config["HostConfig"]["CapDrop"]
            assert config["HostConfig"]["Memory"] == 512 * 1024 * 1024
            assert config["Config"]["User"] == "65534:65534"
            uid = await handle.execute(SandboxCommand(("id", "-u")))
            assert uid.exit_code == 0 and uid.stdout.strip() == "65534"
            status = await handle.execute(SandboxCommand(("cat", "/proc/self/status")))
            fields = dict(line.split(":", 1) for line in status.stdout.splitlines() if ":" in line)
            assert int(fields["CapEff"].strip(), 16) == 0
            assert fields["NoNewPrivs"].strip() == "1"
            root_write = await handle.execute(SandboxCommand(("touch", "/blocked")))
            mount_write = await handle.execute(SandboxCommand(("touch", "/workspace/blocked")))
            temp_write = await handle.execute(SandboxCommand(("touch", "/tmp/allowed")))
            assert root_write.exit_code != 0 and mount_write.exit_code != 0
            assert temp_write.exit_code == 0
            environment = await handle.execute(SandboxCommand(("printenv", "WAGENT_SMOKE")))
            assert environment.stdout.strip() == "visible"
            try:
                await handle.execute(SandboxCommand(("sleep", "5"), timeout=0.3))
            except SandboxTimeoutError:
                pass
            else:
                raise AssertionError("sandbox timeout was not enforced")
        finally:
            await handle.close()
        removed = subprocess.run(
            ["docker", "inspect", handle.container_name],
            capture_output=True, text=True, timeout=10,
        )
        assert removed.returncode != 0, "owned container was not removed"
    print(json.dumps({
        "image": image, "network": "none", "non_root": True,
        "capabilities_dropped": True, "read_only_root_and_workspace": True,
        "temporary_write": True, "explicit_environment": True,
        "timeout": "enforced", "cleanup": "confirmed",
    }))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Cached tagged image; never pulled")
    asyncio.run(main(parser.parse_args().image))
