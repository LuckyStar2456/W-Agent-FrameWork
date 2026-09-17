import asyncio
import sys
from pathlib import Path

import pytest

from w_agent import (
    CancellationToken,
    DockerSandboxProvider,
    SandboxCommand,
    SandboxError,
    SandboxExecutionError,
    SandboxNetwork,
    SandboxOutputTooLarge,
    SandboxRegistry,
    SandboxResult,
    SandboxSpec,
    SandboxTimeoutError,
    SandboxUnavailableError,
    ToolCall,
    ToolExecutionContext,
    ToolExecutor,
    ToolOutcome,
    ToolRegistry,
    UnsafeLocalAuthorization,
    UnsafeLocalSandboxProvider,
    WorkspaceAccess,
    sandbox_command_tool,
)


class FakeDockerRunner:
    def __init__(self, *, available=True):
        self.available = available
        self.calls = []
        self.env_file_content = None
        self.exec_error = None

    async def run(
        self,
        argv,
        *,
        timeout=30,
        max_output_bytes=1_048_576,
        cancellation=None,
    ):
        argv = tuple(argv)
        self.calls.append((argv, timeout, max_output_bytes, cancellation))
        if "version" in argv:
            return SandboxResult(0 if self.available else 1, "25.0\n", "")
        if len(argv) > 1 and argv[1] == "run":
            if "--env-file" in argv:
                env_path = Path(argv[argv.index("--env-file") + 1])
                self.env_file_content = env_path.read_text(encoding="utf-8")
            return SandboxResult(0, "container-id\n", "")
        if len(argv) > 1 and argv[1] == "exec":
            if self.exec_error is not None:
                raise self.exec_error
            return SandboxResult(0, "inside\n", "")
        if len(argv) > 1 and argv[1] == "rm":
            return SandboxResult(0, "removed\n", "")
        raise AssertionError(f"unexpected Docker argv: {argv}")


@pytest.mark.asyncio
async def test_docker_sandbox_builds_hardened_container_and_cleans_up(tmp_path):
    runner = FakeDockerRunner()
    provider = DockerSandboxProvider(runner=runner, name_prefix="test")
    spec = SandboxSpec(
        tmp_path,
        image="python:3.11-slim",
        workspace_access=WorkspaceAccess.READ_ONLY,
        environment={"TOKEN": "local-secret"},
    )

    handle = await provider.open(spec)
    created = runner.calls[1][0]
    assert created[:3] == ("docker", "run", "--detach")
    assert created[created.index("--network") + 1] == SandboxNetwork.NONE.value
    assert created[created.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges:true" in created
    assert "--read-only" in created
    assert "readonly" in created[created.index("--mount") + 1]
    assert "local-secret" not in " ".join(created)
    assert runner.env_file_content == "TOKEN=local-secret\n"
    env_path = Path(created[created.index("--env-file") + 1])
    assert not env_path.exists()

    result = await handle.execute(SandboxCommand(("python", "-V")))
    assert result.stdout == "inside\n"
    await handle.close()
    await handle.close()
    assert [call[0][1] for call in runner.calls].count("rm") == 1
    with pytest.raises(SandboxExecutionError, match="closed"):
        await handle.execute(SandboxCommand(("python", "-V")))


@pytest.mark.asyncio
async def test_docker_sandbox_rejects_mutable_image_and_unavailable_daemon(tmp_path):
    provider = DockerSandboxProvider(runner=FakeDockerRunner())
    with pytest.raises(SandboxError, match="non-latest"):
        await provider.open(SandboxSpec(tmp_path, image="python:latest"))
    with pytest.raises(SandboxError, match="non-latest"):
        await provider.open(SandboxSpec(tmp_path, image="python"))

    unavailable = DockerSandboxProvider(runner=FakeDockerRunner(available=False))
    with pytest.raises(SandboxUnavailableError, match="unavailable"):
        await unavailable.open(SandboxSpec(tmp_path, image="python:3.11"))


@pytest.mark.asyncio
async def test_docker_sandbox_closes_after_uncertain_execution_error(tmp_path):
    runner = FakeDockerRunner()
    provider = DockerSandboxProvider(runner=runner)
    handle = await provider.open(SandboxSpec(tmp_path, image="python:3.11"))
    runner.exec_error = SandboxTimeoutError("timed out")

    with pytest.raises(SandboxTimeoutError):
        await handle.execute(SandboxCommand(("python", "-V")))

    assert any(call[0][1] == "rm" for call in runner.calls)
    with pytest.raises(SandboxExecutionError, match="closed"):
        await handle.execute(SandboxCommand(("python", "-V")))


def test_sandbox_spec_rejects_invalid_environment_and_resources(tmp_path):
    with pytest.raises(ValueError, match="environment"):
        SandboxSpec(tmp_path, environment={"BAD\nNAME": "value"})
    with pytest.raises(ValueError, match="positive"):
        SandboxSpec(tmp_path, cpu_limit=0)
    with pytest.raises(ValueError, match="workdir"):
        SandboxSpec(tmp_path, container_workdir="../escape")


def test_unsafe_local_requires_explicit_runtime_authorization():
    with pytest.raises(PermissionError, match="explicit runtime"):
        UnsafeLocalSandboxProvider(None)
    with pytest.raises(PermissionError, match="acknowledgement"):
        UnsafeLocalAuthorization.grant(
            "test",
            acknowledge_host_access=False,
        )


@pytest.mark.asyncio
async def test_unsafe_local_runs_only_after_acknowledgement(tmp_path):
    authorization = UnsafeLocalAuthorization.grant(
        "python-test",
        acknowledge_host_access=True,
    )
    provider = UnsafeLocalSandboxProvider(authorization)
    spec = SandboxSpec(
        tmp_path,
        network=SandboxNetwork.BRIDGE,
        inherit_host_environment=True,
    )
    handle = await provider.open(spec)
    result = await handle.execute(
        SandboxCommand(
            (
                sys.executable,
                "-c",
                "import pathlib; print(pathlib.Path.cwd())",
            )
        )
    )

    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()
    assert "not isolated" in provider.warning
    assert provider.authorization.source == "python-test"
    await handle.close()
    with pytest.raises(SandboxExecutionError, match="closed"):
        await handle.execute(SandboxCommand((sys.executable, "-V")))


@pytest.mark.asyncio
async def test_unsafe_local_enforces_output_limit(tmp_path):
    provider = UnsafeLocalSandboxProvider(
        UnsafeLocalAuthorization.grant(
            "output-test",
            acknowledge_host_access=True,
        )
    )
    handle = await provider.open(SandboxSpec(tmp_path, network=SandboxNetwork.BRIDGE))
    with pytest.raises(SandboxOutputTooLarge):
        await handle.execute(
            SandboxCommand(
                (sys.executable, "-c", "print('x' * 5000)"),
                max_output_bytes=100,
            )
        )
    await handle.close()


@pytest.mark.asyncio
async def test_unsafe_local_honors_pre_cancelled_token(tmp_path):
    provider = UnsafeLocalSandboxProvider(
        UnsafeLocalAuthorization.grant(
            "cancel-test",
            acknowledge_host_access=True,
        )
    )
    token = CancellationToken()
    token.cancel()
    with pytest.raises(asyncio.CancelledError):
        await provider.open(SandboxSpec(tmp_path), cancellation=token)


@pytest.mark.asyncio
async def test_unsafe_local_refuses_unenforceable_safe_flags(tmp_path):
    provider = UnsafeLocalSandboxProvider(
        UnsafeLocalAuthorization.grant(
            "flag-test",
            acknowledge_host_access=True,
        )
    )
    with pytest.raises(SandboxError, match="network isolation"):
        await provider.open(SandboxSpec(tmp_path))
    with pytest.raises(SandboxError, match="read-only"):
        await provider.open(
            SandboxSpec(
                tmp_path,
                network=SandboxNetwork.BRIDGE,
                workspace_access=WorkspaceAccess.READ_ONLY,
            )
        )


def test_sandbox_provider_uses_shared_registry():
    registry = SandboxRegistry()
    first = UnsafeLocalSandboxProvider(
        UnsafeLocalAuthorization.grant(
            "registry-test",
            acknowledge_host_access=True,
        )
    )
    second = DockerSandboxProvider(runner=FakeDockerRunner())
    registry.register("local", first, version="1")
    registry.register("docker", second, version="1")

    assert registry.provider("local") is first
    assert registry.providers() == (("docker", second), ("local", first))


@pytest.mark.asyncio
async def test_sandbox_command_tool_uses_policy_and_closes_handle(tmp_path):
    class FakeHandle:
        def __init__(self):
            self.commands = []
            self.closed = False

        async def execute(self, command, *, cancellation=None):
            self.commands.append((command, cancellation))
            return SandboxResult(0, "sandboxed", "")

        async def close(self):
            self.closed = True

    class FakeProvider:
        def __init__(self):
            self.handle = FakeHandle()

        async def open(self, spec, *, cancellation=None):
            assert spec.workspace == tmp_path.resolve()
            return self.handle

    provider = FakeProvider()
    binding = sandbox_command_tool(
        "sandbox_echo",
        "Execute in a sandbox.",
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        provider=provider,
        sandbox=SandboxSpec(tmp_path),
        command_builder=lambda arguments: SandboxCommand(("echo", arguments["value"])),
    )
    tools = ToolRegistry()
    tools.register_binding(binding)
    executor = ToolExecutor(tools)
    call = ToolCall("sandbox-1", "sandbox_echo", {"value": "hello"})

    pending = await executor.execute(
        call,
        ToolExecutionContext(permissions=frozenset({"sandbox.execute"})),
    )
    assert pending.outcome == ToolOutcome.NEEDS_APPROVAL
    result = await executor.execute(
        call,
        ToolExecutionContext(
            permissions=frozenset({"sandbox.execute"}),
            approved_call_ids=frozenset({"sandbox-1"}),
        ),
    )

    assert result.outcome == ToolOutcome.SUCCEEDED
    assert result.data["stdout"] == "sandboxed"
    assert provider.handle.commands[0][0].argv == ("echo", "hello")
    assert provider.handle.closed is True
