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
    
    async def test_wasm_sandbox(self):
        """Wasm工具链不完整时必须拒绝执行"""
        sandbox = WasmSkillSandbox()
        if not sandbox.available:
            with pytest.raises(SkillSandboxError, match="Wasm sandbox unavailable"):
                await sandbox.execute(self.skill, "test", {"name": "test"})
    
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
    test = TestSandbox()
    test.setup_method()
    asyncio.run(test.test_nsjail_sandbox())
    asyncio.run(test.test_wasm_sandbox())
    asyncio.run(test.test_sandbox_fallback())
    test.teardown_method()
    print("All sandbox tests passed!")
