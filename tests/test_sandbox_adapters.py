"""Protocol regressions; fake backends do not assert real OS isolation."""

import asyncio
import json
from pathlib import Path

import pytest

from w_agent import CancellationToken, Skill, SkillSandboxError
from w_agent.sandbox import (
    DockerSandboxProvider, NsJailSandboxHandle, NsJailSandboxProvider,
    SandboxCommand, SandboxError, SandboxExecutionError, SandboxNetwork,
    SandboxResult, SandboxSpec, SandboxTimeoutError, SandboxUnavailableError,
    WorkspaceAccess,
)
from w_agent.skills.sandbox import ProviderSkillSandbox, WasmSkillSandbox


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -1, 0, "2", 10**400])
def test_numeric_limits_are_finite_positive_numbers(tmp_path, value):
    with pytest.raises(ValueError):
        SandboxSpec(tmp_path, cpu_limit=value)
    with pytest.raises(ValueError):
        SandboxCommand(("python",), timeout=value)


@pytest.mark.parametrize("value", [True, False, 1.5, float("nan"), float("inf"), "2", 0])
def test_count_limits_require_actual_positive_integers(tmp_path, value):
    for field in ("memory_bytes", "pids_limit"):
        with pytest.raises(ValueError):
            SandboxSpec(tmp_path, **{field: value})
    with pytest.raises(ValueError):
        SandboxCommand(("python",), max_output_bytes=value)


def test_enums_normalized_and_string_argv_rejected(tmp_path):
    spec = SandboxSpec(tmp_path, workspace_access="read-only", network="none")
    assert spec.workspace_access is WorkspaceAccess.READ_ONLY
    assert spec.network is SandboxNetwork.NONE
    with pytest.raises(ValueError):
        SandboxSpec(tmp_path, network="allowlist")
    with pytest.raises(ValueError):
        SandboxCommand("python")
    with pytest.raises(ValueError):
        SandboxSpec(tmp_path, keepalive_command="sh")
    assert SandboxCommand(("echo", "")).argv == ("echo", "")


class RecordingRunner:
    def __init__(self):
        self.calls = []
        self.error = None
        self.remove_failures = 0
        self.config_paths = []
        self.config_texts = []

    async def run(self, argv, **kwargs):
        self.calls.append((tuple(argv), kwargs))
        if "--config" in argv:
            path = Path(argv[argv.index("--config") + 1])
            self.config_paths.append(path)
            self.config_texts.append(path.read_text(encoding="utf-8"))
        if "version" in argv or "--help" in argv:
            return SandboxResult(0, "available", "")
        if "rm" in argv:
            if self.remove_failures:
                self.remove_failures -= 1
                return SandboxResult(1, "", "failed")
            return SandboxResult(0, "", "")
        if self.error:
            raise self.error
        return SandboxResult(0, "ok", "")


@pytest.mark.asyncio
async def test_docker_creation_timeout_cleans_named_container(tmp_path):
    runner = RecordingRunner()
    runner.error = SandboxTimeoutError("creation timed out")
    provider = DockerSandboxProvider(runner=runner)
    with pytest.raises(SandboxTimeoutError):
        await provider.open(SandboxSpec(tmp_path, image="python:3.11"))
    create = runner.calls[1][0]
    assert runner.calls[-1][0] == ("docker", "rm", "--force", create[create.index("--name") + 1])
    assert "cancellation" not in runner.calls[-1][1]


@pytest.mark.asyncio
async def test_docker_failed_remove_can_be_retried_but_handle_cannot_execute(tmp_path):
    runner = RecordingRunner()
    handle = await DockerSandboxProvider(runner=runner).open(SandboxSpec(tmp_path, image="python:3.11"))
    runner.remove_failures = 1
    with pytest.raises(SandboxError):
        await handle.close()
    with pytest.raises(SandboxExecutionError):
        await handle.execute(SandboxCommand(("echo",)))
    await handle.close()
    assert sum(call[0][1] == "rm" for call in runner.calls) == 2


@pytest.mark.asyncio
async def test_docker_precancellation_never_probes_or_creates(tmp_path):
    runner = RecordingRunner()
    token = CancellationToken()
    token.cancel()
    with pytest.raises(asyncio.CancelledError):
        await DockerSandboxProvider(runner=runner).open(
            SandboxSpec(tmp_path, image="python:3.11"), cancellation=token,
        )
    assert not runner.calls


@pytest.mark.asyncio
async def test_nsjail_maps_hard_limits_and_closes_on_uncertain_execution(tmp_path):
    runner = RecordingRunner()
    provider = NsJailSandboxProvider(tmp_path, cgroup_path=tmp_path, runner=runner)
    spec = SandboxSpec(tmp_path, cpu_limit=0.5, pids_limit=8, workspace_access="read-only")
    # Direct handle construction permits command-generation tests on Windows;
    # production open() rejects Windows drive-colon mounts.
    handle = NsJailSandboxHandle(provider, spec)
    command = SandboxCommand(("/usr/bin/python3", "-V"), timeout=2.5, max_output_bytes=123)
    result = await handle.execute(command)
    assert result.stdout == "ok"
    argv, kwargs = runner.calls[-1]
    for flag, value in {
        "--cgroup_cpu_ms_per_sec": "500", "--cgroup_mem_max": str(spec.memory_bytes),
        "--cgroup_pids_max": "8", "--time_limit": "3", "--rlimit_nofile": "64",
    }.items():
        assert argv[argv.index(flag) + 1] == value
    assert "--use_cgroupv2" in argv
    assert "--mount" not in argv
    assert argv[1] == "--config"  # upstream config::parseInternal uses CopyFrom
    assert not runner.config_paths[-1].exists()
    assert "--iface_no_lo" in argv
    assert "--bindmount_ro" in argv
    assert "--disable_clone_newnet" not in argv
    assert "--keep_env" not in argv
    assert kwargs["timeout"] == 2.5
    assert kwargs["max_output_bytes"] == 123
    runner.error = SandboxTimeoutError("limit")
    with pytest.raises(SandboxTimeoutError):
        await handle.execute(command)
    with pytest.raises(SandboxExecutionError, match="closed"):
        await handle.execute(command)


@pytest.mark.asyncio
async def test_nsjail_tmpfs_config_matches_official_protobuf_schema(tmp_path):
    """Parse with protobuf, independently of our builder and runner.

    Field numbers/types below are the relevant subset of upstream config.proto:
    https://github.com/google/nsjail/blob/master/config.proto#L26-L58
    and NsJailConfig.mount_proc (66), mount (67). The native nsjail dependency
    is deliberately not installed by this test. protobuf is an optional QA tool.
    """
    pytest.importorskip("google.protobuf")
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, text_format

    schema = descriptor_pb2.FileDescriptorProto(name="nsjail-mount-qa.proto", package="nsjail", syntax="proto2")
    mount = schema.message_type.add(name="MountPt")
    for name, number, kind in (
        ("dst", 4, 9), ("fstype", 6, 9), ("options", 7, 9),
        ("rw", 9, 8), ("is_dir", 10, 8), ("mandatory", 11, 8),
        ("nosuid", 13, 8), ("nodev", 14, 8), ("noexec", 15, 8),
    ):
        mount.field.add(name=name, number=number, type=kind, label=1)
    config = schema.message_type.add(name="NsJailConfig")
    config.field.add(name="mount_proc", number=66, type=8, label=1)
    config.field.add(name="mount", number=67, type=11, label=3, type_name=".nsjail.MountPt")
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    config_class = message_factory.GetMessageClass(pool.FindMessageTypeByName("nsjail.NsJailConfig"))
    runner = RecordingRunner()
    provider = NsJailSandboxProvider(tmp_path, runner=runner)
    await NsJailSandboxHandle(provider, SandboxSpec(tmp_path)).execute(SandboxCommand(("/bin/true",)))
    parsed = text_format.Parse(runner.config_texts[-1], config_class())
    assert parsed.mount_proc is True
    assert len(parsed.mount) == 1
    tmpfs = parsed.mount[0]
    assert tmpfs.dst == "/tmp"
    assert tmpfs.fstype == "tmpfs"
    assert tmpfs.options == "size=67108864,mode=1777"
    assert tmpfs.rw and tmpfs.is_dir and tmpfs.mandatory
    # Upstream mnt_legacy.cc maps these BOOLEAN fields to mount(2) flags;
    # filesystem options are passed separately and cannot replace them.
    assert tmpfs.nosuid and tmpfs.nodev and tmpfs.noexec


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [None, SandboxTimeoutError("timeout"), asyncio.CancelledError()])
async def test_nsjail_private_config_is_removed_on_success_failure_and_cancel(tmp_path, error):
    runner = RecordingRunner()
    runner.error = error
    provider = NsJailSandboxProvider(tmp_path, runner=runner)
    handle = NsJailSandboxHandle(provider, SandboxSpec(tmp_path))
    if error is None:
        await handle.execute(SandboxCommand(("/bin/true",)))
    else:
        with pytest.raises(type(error)):
            await handle.execute(SandboxCommand(("/bin/true",)))
    assert len(runner.config_paths) == 1
    assert not runner.config_paths[0].parent.exists()


@pytest.mark.asyncio
async def test_nsjail_dynamic_values_cannot_inject_or_overwrite_protobuf_config(tmp_path):
    user_config = tmp_path / "mounts.cfg"
    user_config.write_text("user-owned", encoding="utf-8")
    runner = RecordingRunner()
    provider = NsJailSandboxProvider(tmp_path, runner=runner)
    payload = '" } clone_newnet: false # \\ $(echo injected)'
    spec = SandboxSpec(tmp_path, environment={"PAYLOAD": payload})
    handle = NsJailSandboxHandle(provider, spec)
    await handle.execute(SandboxCommand(("/bin/echo", payload, "--config", str(user_config))))
    argv = runner.calls[-1][0]
    delimiter = argv.index("--")
    assert argv[delimiter + 1:] == ("/bin/echo", payload, "--config", str(user_config))
    assert f"PAYLOAD={payload}" in argv[:delimiter]
    assert payload not in runner.config_texts[-1]
    assert str(tmp_path) not in runner.config_texts[-1]
    assert runner.config_paths[-1] != user_config
    assert user_config.read_text(encoding="utf-8") == "user-owned"


@pytest.mark.asyncio
async def test_nsjail_native_task_cancellation_cleans_configuration(tmp_path):
    started = asyncio.Event()
    runner = RecordingRunner()
    original_run = runner.run

    async def blocking_run(argv, **kwargs):
        await original_run(argv, **kwargs)
        started.set()
        await asyncio.Event().wait()

    runner.run = blocking_run
    provider = NsJailSandboxProvider(tmp_path, runner=runner)
    handle = NsJailSandboxHandle(provider, SandboxSpec(tmp_path))
    task = asyncio.create_task(handle.execute(SandboxCommand(("/bin/true",))))
    await asyncio.wait_for(started.wait(), timeout=2)
    assert runner.config_paths[-1].is_file()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not runner.config_paths[-1].parent.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("quota", [4294.968, 4_294_967.295, 1e308, 0.0001])
async def test_nsjail_cpu_quota_rejects_upstream_uint32_conversion_overflow(tmp_path, quota):
    runner = RecordingRunner()
    provider = NsJailSandboxProvider(tmp_path, runner=runner)
    with pytest.raises(SandboxError, match="CPU limit"):
        await provider.open(SandboxSpec(tmp_path, cpu_limit=quota))
    assert not runner.calls


@pytest.mark.asyncio
async def test_nsjail_rejects_unenforceable_requests_without_execution(tmp_path):
    runner = RecordingRunner()
    provider = NsJailSandboxProvider(tmp_path, cgroup_path=tmp_path, runner=runner)
    for fields in ({"network": "bridge"}, {"image": "python:3.11"}, {"inherit_host_environment": True}):
        with pytest.raises(SandboxError):
            await provider.open(SandboxSpec(tmp_path, **fields))
    assert not runner.calls
    with pytest.raises(ValueError, match="host root"):
        NsJailSandboxProvider(Path(tmp_path.anchor))


class SkillProvider:
    def __init__(self, *, result=None, error=None):
        self.result = result or SandboxResult(0, '{"ok":true,"result":"success"}', "")
        self.error = error
        self.closed = False
        self.spec = None

    async def open(self, spec, *, cancellation=None):
        self.spec = spec
        self.files = {path.name: path.read_text(encoding="utf-8") for path in spec.workspace.iterdir()}
        return self

    async def execute(self, command, *, cancellation=None):
        self.command = command
        if self.error:
            raise self.error
        return self.result

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_legacy_skill_bridge_mounts_only_payload_and_preserves_result(tmp_path):
    script = tmp_path / "skill.py"
    script.write_text("result = args['text']", encoding="utf-8")
    (tmp_path / "private.env").write_text("secret", encoding="utf-8")
    provider = SkillProvider()
    bridge = ProviderSkillSandbox(provider, SandboxSpec(tmp_path, image="python:3.11"))
    assert await bridge.execute(Skill("test", "test", {"run": script}), "run", {"text": "你好"}) == {"result": "success"}
    assert provider.spec.workspace != tmp_path
    assert provider.spec.workspace_access is WorkspaceAccess.READ_ONLY
    assert set(provider.files) == {"skill.py", "args.json", "runner.py"}
    assert json.loads(provider.files["args.json"]) == {"text": "你好"}
    compile(provider.files["runner.py"], "<skill-runner>", "exec")
    assert '"/workspace/' not in provider.files["runner.py"]
    assert provider.closed
    assert not provider.spec.workspace.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [SandboxTimeoutError("timeout"), asyncio.CancelledError()])
async def test_skill_bridge_closes_and_removes_payload_on_failure(tmp_path, error):
    script = tmp_path / "skill.py"
    script.write_text("result = 1", encoding="utf-8")
    provider = SkillProvider(error=error)
    bridge = ProviderSkillSandbox(provider, SandboxSpec(tmp_path))
    expected = asyncio.CancelledError if isinstance(error, asyncio.CancelledError) else SkillSandboxError
    with pytest.raises(expected):
        await bridge.execute(Skill("test", "test", {"run": script}), "run", {})
    assert provider.closed
    assert not provider.spec.workspace.exists()


@pytest.mark.asyncio
async def test_skill_bridge_rejects_nonfinite_args_before_open(tmp_path):
    script = tmp_path / "skill.py"
    script.write_text("result = 1", encoding="utf-8")
    provider = SkillProvider()
    bridge = ProviderSkillSandbox(provider, SandboxSpec(tmp_path))
    with pytest.raises(SkillSandboxError, match="JSON"):
        await bridge.execute(Skill("test", "test", {"run": script}), "run", {"n": float("nan")})
    assert provider.spec is None


@pytest.mark.parametrize("timeout", [True, float("nan"), float("inf"), "1"])
def test_wasm_timeout_validation(timeout):
    with pytest.raises(ValueError):
        WasmSkillSandbox(max_execution_seconds=timeout)
