import tempfile
from pathlib import Path
from w_agent.scanner.parallel_scanner import ParallelASTScanner

class TestASTScanner:
    """测试AST扫描器"""
    
    def test_scan_agent_component(self):
        """测试扫描AgentComponent注解"""
        # 创建临时文件
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建测试文件
            test_file = Path(temp_dir) / "test_agent.py"
            test_file.write_text("""
from w_agent.core.decorators import AgentComponent

@AgentComponent(name="test_agent")
class TestAgent:
    pass
""")
            
            # 扫描文件
            scanner = ParallelASTScanner()
            result = scanner.scan_package(Path(temp_dir))
            
            # 验证结果
            assert len(result.components) == 1
            component = result.components[0]
            assert component.name == "test_agent"
            assert component.component_type == "agent"
            assert component.class_name == "TestAgent"
    
    def test_scan_service_component(self):
        """测试扫描ServiceComponent注解"""
        # 创建临时文件
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建测试文件
            test_file = Path(temp_dir) / "test_service.py"
            test_file.write_text("""
from w_agent.core.decorators import ServiceComponent

@ServiceComponent
class TestService:
    pass
""")
            
            # 扫描文件
            scanner = ParallelASTScanner()
            result = scanner.scan_package(Path(temp_dir))
            
            # 验证结果
            assert len(result.components) == 1
            component = result.components[0]
            assert component.name == "testservice"
            assert component.component_type == "service"
            assert component.class_name == "TestService"
    
    def test_scan_tool_component(self):
        """测试扫描ToolComponent注解"""
        # 创建临时文件
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建测试文件
            test_file = Path(temp_dir) / "test_tool.py"
            test_file.write_text("""
from w_agent.core.decorators import ToolComponent

@ToolComponent(name="test_tool")
def test_tool():
    pass
""")
            
            # 扫描文件
            scanner = ParallelASTScanner()
            result = scanner.scan_package(Path(temp_dir))
            
            # 验证结果
            assert len(result.components) == 1
            component = result.components[0]
            assert component.name == "test_tool"
            assert component.component_type == "tool"
            assert component.function_name == "test_tool"

if __name__ == "__main__":
    test = TestASTScanner()
    test.test_scan_agent_component()
    test.test_scan_service_component()
    test.test_scan_tool_component()
    print("All tests passed!")
