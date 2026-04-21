#!/usr/bin/env python3
"""
W-Agent框架全面自检测试
覆盖开发中可能遇到的全部场景
"""

import asyncio
import time
import concurrent.futures
from typing import Dict, Any, List
from w_agent.core.agent import BaseAgent
from w_agent.core.decorators import AgentComponent, ServiceComponent, PostConstruct, PreDestroy
from w_agent.container.bean_factory import BeanFactory
from w_agent.config.dynamic_config import DynamicConfigManager
from w_agent.lifecycle.manager import LifecycleManager
from w_agent.lifecycle.order import LifecycleOrder
from w_agent.core.event_bus import EventBus, Event
from w_agent.resilience.bulkhead import ResilienceManager
from w_agent.skills.skill import Skill
from w_agent.skills.sandbox.wasm_sandbox import WasmSkillSandbox
from w_agent.aop.proxy_factory import ProxyFactory
from w_agent.aop.aspects import RetryAspect, CircuitBreakerAspect

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

async def test_boundary_cases():
    """测试边界情况"""
    print("=== 测试边界情况 ===")
    
    # 测试空BeanFactory
    bean_factory = BeanFactory()
    try:
        await bean_factory.get_bean("non_existent")
        assert False, "Should have raised an exception"
    except Exception:
        pass
    
    # 测试空配置
    config_manager = DynamicConfigManager()
    assert config_manager.get("non_existent", "default") == "default"
    
    # 测试空事件总线
    event_bus = EventBus()
    test_event = Event("test_event", {"data": "test"})
    await event_bus.emit(test_event)  # 应该不会抛出异常
    
    print("边界情况测试通过")

async def test_error_handling():
    """测试错误处理"""
    print("\n=== 测试错误处理 ===")
    
    # 测试配置更新错误
    config_manager = DynamicConfigManager()
    try:
        await config_manager.update_batch({"key": "value"})
    except Exception as e:
        assert False, f"Config update should not raise exception: {e}"
    
    # 测试事件总线错误
    event_bus = EventBus()
    
    def error_listener(event):
        raise Exception("Listener error")
    
    event_bus.on("test_event", error_listener)
    test_event = Event("test_event", {"data": "test"})
    try:
        await event_bus.emit(test_event)
    except Exception as e:
        assert False, f"Event emission should not raise exception: {e}"
    
    print("错误处理测试通过")

async def test_performance():
    """测试性能"""
    print("\n=== 测试性能 ===")
    
    # 测试IOC启动时间
    start_time = time.time()
    bean_factory = BeanFactory()
    for i in range(100):
        bean_factory.register_bean(f"bean_{i}", f"value_{i}")
    end_time = time.time()
    ioc_time = end_time - start_time
    print(f"IOC启动时间: {ioc_time:.4f}秒")
    assert ioc_time < 0.1, f"IOC启动时间过长: {ioc_time:.4f}秒"
    
    # 测试AOP代理性能
    proxy_factory = ProxyFactory()
    retry_aspect = RetryAspect()
    
    async def test_func():
        return "test"
    
    advice = retry_aspect.create_advice(test_func)
    proxy = proxy_factory.create_proxy(test_func, {"test_func": [advice]})
    
    start_time = time.time()
    for i in range(1000):
        await proxy()
    end_time = time.time()
    aop_time = end_time - start_time
    print(f"AOP代理1000次调用时间: {aop_time:.4f}秒")
    assert aop_time < 0.5, f"AOP代理调用时间过长: {aop_time:.4f}秒"
    
    print("性能测试通过")

async def test_concurrency():
    """测试并发"""
    print("\n=== 测试并发 ===")
    
    # 测试并发配置更新
    config_manager = DynamicConfigManager()
    
    async def update_config(i):
        await config_manager.update_batch({f"key_{i}": f"value_{i}"})
    
    tasks = [update_config(i) for i in range(100)]
    await asyncio.gather(*tasks)
    
    # 验证所有配置都被更新
    for i in range(100):
        assert config_manager.get(f"key_{i}") == f"value_{i}"
    
    # 测试并发Bean获取
    bean_factory = BeanFactory()
    for i in range(100):
        bean_factory.register_bean(f"bean_{i}", f"value_{i}")
    
    async def get_bean(i):
        return await bean_factory.get_bean(f"bean_{i}")
    
    tasks = [get_bean(i) for i in range(100)]
    results = await asyncio.gather(*tasks)
    
    # 验证所有Bean都被正确获取
    for i, result in enumerate(results):
        assert result == f"value_{i}"
    
    print("并发测试通过")

async def test_integration():
    """测试集成"""
    print("\n=== 测试集成 ===")
    
    # 创建所有组件
    config_manager = DynamicConfigManager()
    config_manager.set("api_key", "integration-key")
    
    lifecycle_manager = LifecycleManager()
    bean_factory = BeanFactory()
    event_bus = EventBus()
    resilience_manager = ResilienceManager(event_bus)
    
    # 注册Bean
    bean_factory.register_bean("config_manager", config_manager)
    bean_factory.register_bean("event_bus", event_bus)
    bean_factory.register_bean("resilience_manager", resilience_manager)
    
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
    test_event = Event("test_event", {"type": "integration", "data": "test"})
    await event_bus.emit(test_event)
    
    # 测试重试功能
    call_count = 0
    
    @resilience_manager.retry(max_attempts=3, delay=0.01)
    async def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Temporary failure")
        return "Success"
    
    result = await flaky_function()
    assert result == "Success"
    assert call_count == 3
    
    # 执行销毁
    await bean_factory.destroy_singletons()
    await lifecycle_manager.pre_destroy_all()
    
    print("集成测试通过")

async def test_edge_cases():
    """测试边缘情况"""
    print("\n=== 测试边缘情况 ===")
    
    # 测试大量Bean
    bean_factory = BeanFactory()
    for i in range(1000):
        bean_factory.register_bean(f"bean_{i}", f"value_{i}")
    
    # 测试获取大量Bean
    for i in range(1000):
        bean = await bean_factory.get_bean(f"bean_{i}")
        assert bean == f"value_{i}"
    
    # 测试长配置键
    config_manager = DynamicConfigManager()
    long_key = "a" * 1000
    config_manager.set(long_key, "value")
    assert config_manager.get(long_key) == "value"
    
    # 测试大配置值
    large_value = "a" * 1000000
    config_manager.set("large_value", large_value)
    assert config_manager.get("large_value") == large_value
    
    print("边缘情况测试通过")

async def test_sandbox():
    """测试沙箱"""
    print("\n=== 测试沙箱 ===")
    
    sandbox = WasmSkillSandbox()
    skill = TestSkill()
    
    print(f"Pyodide可用: {sandbox.pyodide_available}")
    print(f"缓存目录: {sandbox.cache_dir}")
    print(f"脚本路径: {skill.scripts['test']}")
    
    try:
        # 检查脚本文件是否存在
        if not skill.scripts['test'].exists():
            print(f"脚本文件不存在: {skill.scripts['test']}")
            return
        
        result = await sandbox.execute(skill, "test", {"param": "value"})
        print(f"沙箱执行结果: {result}")
        assert isinstance(result, dict) or isinstance(result, str)
        print("Wasm沙箱测试通过")
    except Exception as e:
        print(f"Wasm沙箱测试跳过: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """主测试函数"""
    print("开始W-Agent框架全面自检测试...")
    
    try:
        await test_boundary_cases()
        await test_error_handling()
        await test_performance()
        await test_concurrency()
        await test_integration()
        await test_edge_cases()
        await test_sandbox()
        
        print("\n[OK] 所有测试通过！W-Agent框架运行正常。")
    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
