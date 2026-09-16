import asyncio
import pytest
from pathlib import Path
import tempfile
import subprocess
from w_agent import NsJailSkillSandbox, WasmSkillSandbox, Skill, SkillSandboxError

class TestSandbox:
    """测试沙箱模块"""
    
    def setup_method(self):
        """设置测试环境"""
        # 创建测试技能
        self.skill_dir = tempfile.mkdtemp()
        self.skill_dir_path = Path(self.skill_dir)
        
        # 创建SKILL.md
        (self.skill_dir_path / "SKILL.md").write_text("# Test Skill\nDescription: A test skill")
        
        # 创建测试脚本
        (self.skill_dir_path / "test.py").write_text('result = f"Hello, {args.get("name", "world")}!"')
        
        # 创建Skill对象
        self.skill = Skill(
            name="test_skill",
            description="A test skill",
            scripts={"test": self.skill_dir_path / "test.py"}
        )
    
    def teardown_method(self):
        """清理测试环境"""
        import shutil
        shutil.rmtree(self.skill_dir)
    
    async def test_nsjail_sandbox(self):
        """nsjail不可用时必须拒绝不安全降级"""
        sandbox = NsJailSkillSandbox()
        if not sandbox.available:
            with pytest.raises(SkillSandboxError, match="refusing unsafe fallback"):
                await sandbox.execute(self.skill, "test", {"name": "test"})
    
    async def test_wasm_sandbox(self, monkeypatch):
        """wasmer-sdk不可用时必须拒绝执行"""
        monkeypatch.setattr(
            WasmSkillSandbox, "_load_client_factory", lambda _self: None
        )
        sandbox = WasmSkillSandbox()
        with pytest.raises(SkillSandboxError, match="missing wasmer-sdk"):
            await sandbox.execute(self.skill, "test", {"name": "test"})

    async def test_wasm_sdk_execution_and_cleanup(self, tmp_path):
        captured = {}

        class FakeOutput:
            def text(self):
                return '{"ok": true, "result": "Hello, test!"}'

        class FakeCommand:
            async def run(self):
                return FakeOutput()

        class FakeSandbox:
            def __init__(self):
                self.closed = False

            def command(self, executable, arguments):
                captured["command"] = (executable, arguments)
                return FakeCommand()

            async def close(self):
                self.closed = True

        fake_sandbox = FakeSandbox()

        class FakeSandboxes:
            async def create(self, **kwargs):
                captured["create"] = kwargs
                return fake_sandbox

        class FakeClient:
            def __init__(self, cache_root):
                captured["cache_root"] = cache_root
                self.sandboxes = FakeSandboxes()
                self.closed = False

            async def close(self):
                self.closed = True

        client_holder = {}

        def client_factory(**kwargs):
            client_holder["client"] = FakeClient(**kwargs)
            return client_holder["client"]

        sandbox = WasmSkillSandbox(
            cache_root=tmp_path / "cache",
            client_factory=client_factory,
        )
        result = await sandbox.execute(self.skill, "test", {"name": "test"})

        assert result == {"result": "Hello, test!"}
        assert captured["create"]["packages"] == ["python/python@=3.13.18"]
        assert set(captured["create"]["files"]) == {
            "skill.py", "runner.py", "args.json"
        }
        assert "network" not in captured["create"]
        assert captured["command"] == (
            "python", ["/workspace/runner.py"]
        )
        assert fake_sandbox.closed
        assert not client_holder["client"].closed

        await sandbox.close()
        assert client_holder["client"].closed

    async def test_wasm_guest_error_is_mapped(self, tmp_path):
        class FakeOutput:
            def text(self):
                return '{"ok": false, "error_type": "ValueError", "error": "bad"}'

        class FakeCommand:
            async def run(self):
                return FakeOutput()

        class FakeSandbox:
            def command(self, *_args):
                return FakeCommand()

            async def close(self):
                pass

        class FakeClient:
            def __init__(self, **_kwargs):
                self.sandboxes = self

            async def create(self, **_kwargs):
                return FakeSandbox()

            async def close(self):
                pass

        sandbox = WasmSkillSandbox(
            cache_root=tmp_path / "cache",
            client_factory=FakeClient,
        )
        with pytest.raises(SkillSandboxError, match="Guest ValueError: bad"):
            await sandbox.execute(self.skill, "test", {})
        await sandbox.close()

    def test_wasm_guest_runner_compiles(self):
        compile(WasmSkillSandbox._RUNNER_SOURCE, "<wasmer-runner>", "exec")

    async def test_wasm_timeout_closes_sandbox(self, tmp_path):
        class SlowCommand:
            async def run(self):
                await asyncio.sleep(10)

        class FakeSandbox:
            def __init__(self):
                self.closed = False

            def command(self, *_args):
                return SlowCommand()

            async def close(self):
                self.closed = True

        fake_sandbox = FakeSandbox()

        class FakeClient:
            def __init__(self, **_kwargs):
                self.sandboxes = self

            async def create(self, **_kwargs):
                return fake_sandbox

            async def close(self):
                pass

        sandbox = WasmSkillSandbox(
            cache_root=tmp_path / "cache",
            max_execution_seconds=0.01,
            client_factory=FakeClient,
        )
        with pytest.raises(SkillSandboxError, match="exceeded timeout"):
            await sandbox.execute(self.skill, "test", {})
        assert fake_sandbox.closed
        await sandbox.close()

    async def test_wasm_rejects_non_json_args_before_sdk_call(self, tmp_path):
        called = False

        def client_factory(**_kwargs):
            nonlocal called
            called = True
            raise AssertionError("client must not be created")

        sandbox = WasmSkillSandbox(
            cache_root=tmp_path / "cache",
            client_factory=client_factory,
        )
        with pytest.raises(SkillSandboxError, match="not JSON serializable"):
            await sandbox.execute(self.skill, "test", {"value": object()})
        assert not called
    
    async def test_sandbox_fallback(self):
        """显式验证普通子进程fallback已被移除"""
        sandbox = NsJailSkillSandbox()
        original_available = sandbox.nsjail_available
        try:
            sandbox.nsjail_available = False
            with pytest.raises(SkillSandboxError, match="refusing unsafe fallback"):
                await sandbox.execute(self.skill, "test", {"name": "test"})
        finally:
            sandbox.nsjail_available = original_available

    async def test_sandbox_rejects_unknown_script(self):
        sandbox = WasmSkillSandbox()
        with pytest.raises(SkillSandboxError, match="Unknown skill script"):
            await sandbox.execute(self.skill, "missing", {})

    async def test_nsjail_command_enforces_isolation_policy(
        self, tmp_path, monkeypatch
    ):
        rootfs = tmp_path / "rootfs"
        python_path = rootfs / "usr" / "bin" / "python3"
        python_path.parent.mkdir(parents=True)
        python_path.touch()
        sandbox_root = tmp_path / "payload"
        sandbox_root.mkdir()

        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            return subprocess.CompletedProcess(command, 0, '{"result": "ok"}', '')

        sandbox = NsJailSkillSandbox(rootfs_path=rootfs)
        sandbox.nsjail_available = True
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/nsjail")
        monkeypatch.setattr("subprocess.run", fake_run)

        result = await sandbox._execute_with_nsjail(sandbox_root, {})

        assert result == {"result": "ok"}
        command = captured["command"]
        assert command[command.index("--chroot") + 1] == str(rootfs.resolve())
        assert "--seccomp_string" in command
        assert "--rlimit_cpu" in command
        assert "--rlimit_as" in command
        assert "--rlimit_nofile" in command
        assert "--tmpfsmount" in command
        assert "--disable_clone_newnet" not in command

if __name__ == "__main__":
    raise SystemExit("Run this module with pytest")
