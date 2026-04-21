import asyncio
import pytest
from pathlib import Path
import tempfile
from w_agent.skills.sandbox.nsjail_sandbox import NsJailSkillSandbox
from w_agent.skills.sandbox.wasm_sandbox import WasmSkillSandbox
from w_agent.skills.skill import Skill

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
        (self.skill_dir_path / "test.py").write_text("result = f'Hello, {args.get("name", "world")}!'")
        
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
        """测试nsjail沙箱"""
        sandbox = NsJailSkillSandbox()
        result = await sandbox.execute(self.skill, "test", {"name": "test"})
        assert "result" in result
    
    async def test_wasm_sandbox(self):
        """测试Wasm沙箱"""
        sandbox = WasmSkillSandbox()
        result = await sandbox.execute(self.skill, "test", {"name": "test"})
        assert "result" in result
    
    async def test_sandbox_fallback(self):
        """测试沙箱fallback机制"""
        # 测试nsjail不可用时的fallback
        sandbox = NsJailSkillSandbox()
        # 保存原始的nsjail_available
        original_available = sandbox.nsjail_available
        try:
            # 强制设置为不可用
            sandbox.nsjail_available = False
            result = await sandbox.execute(self.skill, "test", {"name": "test"})
            assert "result" in result
        finally:
            # 恢复原始值
            sandbox.nsjail_available = original_available

if __name__ == "__main__":
    test = TestSandbox()
    test.setup_method()
    asyncio.run(test.test_nsjail_sandbox())
    asyncio.run(test.test_wasm_sandbox())
    asyncio.run(test.test_sandbox_fallback())
    test.teardown_method()
    print("All sandbox tests passed!")
