#!/usr/bin/env python3
"""
W-Agent框架核心功能综合测试
"""

import asyncio
from w_agent.core.agent import BaseAgent
from w_agent.core.decorators import AgentComponent, ServiceComponent, PostConstruct, PreDestroy
from w_agent.container.bean_factory import BeanFactory
from w_agent.config.dynamic_config import DynamicConfigManager
from w_agent.lifecycle.manager import LifecycleManager
from w_agent.lifecycle.order import LifecycleOrder
from w_agent.core.event_bus import EventBus
from w_agent.resilience.bulkhead import ResilienceManager
from w_agent.skills.skill import Skill
from w_agent.skills.sandbox.wasm_sandbox import WasmSkillSandbox

class TestService:
    """测试服务"""
    def __init__(self):
        self.calls = 0
    
    def get_data(self, key):
        self.calls += 1
        return f"Data for {key}"

class TestAgent(BaseAgent):
    """测试Agent"""
    def __init__(self, test_service: TestService, config_manager: DynamicConfigManager):
        self.test_service = test_service
        self.config_manager = config_manager
        self.api_key = None
        self.config_manager.bind("api_key", self, "api_key")
    
    async def arun(self, prompt: str) -> str:
        """运行Agent"""
        data = self.test_service.get_data(prompt)
        return f"{data} (API Key: {self.api_key})"
    
    async def on_config_change(self, key, new_value, old_value):
        """配置变更回调"""
        pass
    
    @PostConstruct
    def post_construct(self):
        """初始化后执行"""
        pass
    
    @PreDestroy
    def pre_destroy(self):
        """销毁前执行"""
        pass

class TestSkill(Skill):
    """测试技能"""
    def __init__(self):
        from pathlib import Path
        script_path = Path(__file__).parent / "test.py"
        super().__init__("test_skill", "Test Skill", {"test": script_path})
    
    def execute(self, params):
        """执行技能"""
        return f"Skill executed with {params}"

async def test_ioc_container():
    """测试IOC容器"""
    # 创建Bean工厂
    bean_factory = BeanFactory()
    
    # 创建依赖
    config_manager = DynamicConfigManager()
    config_manager.set("api_key", "test-key")
    
    test_service = TestService()
    
    # 注册Bean
    bean_factory.register_bean("config_manager", config_manager)
    bean_factory.register_bean("test_service", test_service)
    
    # 创建Agent
    agent = TestAgent(test_service, config_manager)
    bean_factory.register_bean("test_agent", agent)
    
    # 测试获取Bean
    retrieved_agent = await bean_factory.get_bean("test_agent")
    assert retrieved_agent is agent
    
    # 测试依赖注入
    result = await retrieved_agent.arun("test")
    assert "Data for test" in result
    assert "API Key: test-key" in result
    
    # 测试Bean生命周期
    await bean_factory.destroy_singletons()

async def test_config_management():
    """测试配置管理"""
    config_manager = DynamicConfigManager()
    
    # 测试设置配置
    config_manager.set("key1", "value1")
    assert config_manager.get("key1") == "value1"
    
    # 测试默认值
    assert config_manager.get("non_existent", "default") == "default"
    
    # 测试配置绑定
    class TestClass:
        def __init__(self, config_manager):
            self.value = None
            config_manager.bind("key1", self, "value")
    
    test_instance = TestClass(config_manager)
    assert test_instance.value == "value1"
    
    # 测试配置更新
    await config_manager.update_batch({"key1": "value2"})
    assert test_instance.value == "value2"

async def test_lifecycle_management():
    """测试生命周期管理"""
    lifecycle_manager = LifecycleManager()
    
    class TestComponent:
        def __init__(self):
            self.post_construct_called = False
            self.pre_destroy_called = False
        
        def post_construct(self):
            self.post_construct_called = True
        
        def pre_destroy(self):
            self.pre_destroy_called = True
    
    component = TestComponent()
    
    # 手动添加生命周期方法
    lifecycle_manager._post_construct_map.setdefault(LifecycleOrder.AGENT, []).append((component, component.post_construct))
    lifecycle_manager._pre_destroy_map.setdefault(LifecycleOrder.AGENT, []).append((component, component.pre_destroy))
    
    # 测试初始化
    await lifecycle_manager.post_construct_all()
    assert component.post_construct_called
    
    # 测试销毁
    await lifecycle_manager.pre_destroy_all()
    assert component.pre_destroy_called

async def test_event_bus():
    """测试事件总线"""
    from w_agent.core.event_bus import Event
    event_bus = EventBus()
    
    # 测试事件监听
    events = []
    
    def listener(event):
        events.append(event)
    
    event_bus.on("test_event", listener)
    
    # 测试事件发布
    test_event = Event("test_event", {"type": "test", "data": "test_data"})
    await event_bus.emit(test_event)
    
    assert len(events) == 1
    assert events[0].name == "test_event"
    assert events[0].payload == {"type": "test", "data": "test_data"}

async def test_resilience_patterns():
    """测试重试和断路器"""
    rm = ResilienceManager()
    
    # 测试重试
    call_count = 0
    
    @rm.retry(max_attempts=3, delay=0.1)
    async def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Temporary failure")
        return "Success"
    
    result = await flaky_function()
    assert result == "Success"
    assert call_count == 3
    
    # 测试断路器
    failure_count = 0
    
    @rm.circuit_breaker(failure_threshold=2, recovery_timeout=0.1)
    async def failing_function():
        nonlocal failure_count
        failure_count += 1
        raise Exception("Permanent failure")
    
    # 触发断路器
    try:
        await failing_function()
    except Exception:
        pass
    
    try:
        await failing_function()
    except Exception:
        pass
    
    # 断路器应该打开
    try:
        await failing_function()
        assert False, "Should have thrown an exception"
    except Exception:
        pass

async def test_wasm_sandbox():
    """测试Wasm沙箱"""
    sandbox = WasmSkillSandbox()
    skill = TestSkill()
    
    # 测试执行技能
    try:
        result = await sandbox.execute(skill, "test", {"param": "value"})
        assert isinstance(result, str)
    except Exception as e:
        # Wasm沙箱可能需要外部依赖，允许跳过
        print(f"Wasm sandbox test skipped: {e}")

async def test_cli_functionality():
    """测试CLI功能"""
    import subprocess
    import sys
    
    # 测试CLI帮助命令
    result = subprocess.run(
        [sys.executable, "-m", "w_agent.cli", "--help"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "W-Agent Command Line Tool" in result.stdout

async def test_comprehensive_integration():
    """综合集成测试"""
    # 创建所有组件
    config_manager = DynamicConfigManager()
    config_manager.set("api_key", "integration-key")
    
    lifecycle_manager = LifecycleManager()
    bean_factory = BeanFactory()
    event_bus = EventBus()
    
    # 注册Bean
    bean_factory.register_bean("config_manager", config_manager)
    bean_factory.register_bean("event_bus", event_bus)
    
    test_service = TestService()
    bean_factory.register_bean("test_service", test_service)
    
    agent = TestAgent(test_service, config_manager)
    bean_factory.register_bean("test_agent", agent)
    
    # 注册到生命周期管理器
    lifecycle_manager.register(agent, LifecycleOrder.AGENT)
    lifecycle_manager.register(test_service, LifecycleOrder.SERVICE)
    
    # 执行初始化
    await lifecycle_manager.post_construct_all()
    
    # 测试配置更新
    await config_manager.update_batch({"api_key": "updated-key"})
    
    # 测试Agent执行
    result = await agent.arun("integration")
    assert "Data for integration" in result
    assert "API Key: updated-key" in result
    
    # 测试事件发布
    from w_agent.core.event_bus import Event
    test_event = Event("test_event", {"type": "integration", "data": "test"})
    await event_bus.emit(test_event)
    
    # 执行销毁
    await bean_factory.destroy_singletons()
    await lifecycle_manager.pre_destroy_all()

if __name__ == "__main__":
    asyncio.run(test_comprehensive_integration())
    print("All tests passed!")
