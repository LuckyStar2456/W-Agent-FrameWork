#!/usr/bin/env python3
"""
W-Agent 基本示例

本示例展示了 W-Agent 框架的核心功能：
- Agent 和 Service 组件的创建
- 依赖注入
- 配置绑定和热更新
- 生命周期管理
- 事件总线使用
- AOP 切面编程
"""

import asyncio
from w_agent import (
    BaseAgent, BeanFactory, DynamicConfigManager, 
    AgentComponent, ServiceComponent, PostConstruct, PreDestroy,
    EventBus, Event, Retry, CircuitBreaker
)

# 配置管理器
config_manager = DynamicConfigManager()
config_manager.set("agent.name", "DemoAgent")
config_manager.set("greeting", "Hello")
config_manager.set("service.retry_attempts", 3)

# 事件总线
event_bus = EventBus()

@event_bus.on("agent.initialized")
async def on_agent_initialized(event):
    """Agent初始化事件处理"""
    print(f"Event: Agent {event.payload['name']} initialized")

@event_bus.on("config_changed")
async def on_config_changed(event):
    """配置变更事件处理"""
    print(f"Event: Config changed - {event.payload}")

@ServiceComponent(name="greeting_service")
class GreetingService:
    """问候服务"""
    def __init__(self):
        self.greeting = None
        # 绑定配置
        config_manager.bind("greeting", self, "greeting")
    
    @Retry(max_attempts=3, delay=0.1, backoff=2.0)
    def get_greeting(self, name: str) -> str:
        """获取问候语"""
        print(f"GreetingService: 生成问候语 for {name}")
        return f"{self.greeting}, {name}!"
    
    async def on_config_change(self, key, new_value, old_value):
        """配置变更回调"""
        print(f"GreetingService: Config changed: {key} = {new_value}")

@AgentComponent(name="demo_agent")
class DemoAgent(BaseAgent):
    """示例Agent"""
    def __init__(self, greeting_service: GreetingService):
        self.greeting_service = greeting_service
        self.name = None
        # 绑定配置
        config_manager.bind("agent.name", self, "name")
    
    @CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
    async def arun(self, prompt: str) -> str:
        """运行Agent"""
        print(f"DemoAgent: 处理请求: {prompt}")
        result = self.greeting_service.get_greeting(prompt)
        return result
    
    @PostConstruct(order=1)
    def initialize(self):
        """初始化方法"""
        print(f"DemoAgent: {self.name} is initializing...")
        # 发布初始化事件
        asyncio.create_task(event_bus.emit(Event("agent.initialized", {"name": self.name})))
    
    @PreDestroy(order=1)
    def cleanup(self):
        """销毁方法"""
        print(f"DemoAgent: {self.name} is cleaning up...")

async def main():
    """主函数"""
    print("=== W-Agent 基本示例 ===")
    
    # 创建Bean工厂
    factory = BeanFactory()
    
    # 注册服务
    greeting_service = GreetingService()
    factory.register_bean("greeting_service", greeting_service)
    
    # 注册Agent
    agent = DemoAgent(greeting_service)
    factory.register_bean("demo_agent", agent)
    
    # 执行初始化
    print("\n1. 初始化组件...")
    await factory.post_construct_all()
    
    # 运行Agent
    print("\n2. 运行Agent...")
    result = await agent.arun("World")
    print(f"Agent result: {result}")
    
    # 动态更新配置
    print("\n3. 动态更新配置...")
    await config_manager.update_batch({"greeting": "Hi", "agent.name": "UpdatedAgent"})
    
    # 再次运行Agent
    print("\n4. 再次运行Agent...")
    result = await agent.arun("World")
    print(f"Agent result after config update: {result}")
    
    # 测试重试功能
    print("\n5. 测试重试功能...")
    # 模拟失败
    original_get_greeting = greeting_service.get_greeting
    
    async def mock_failing_get_greeting(name):
        print("GreetingService: 模拟失败...")
        raise Exception("临时失败")
    
    # 替换方法以模拟失败
    greeting_service.get_greeting = mock_failing_get_greeting
    
    try:
        result = await agent.arun("Test")
        print(f"重试成功: {result}")
    except Exception as e:
        print(f"最终失败: {e}")
    
    # 恢复原始方法
    greeting_service.get_greeting = original_get_greeting
    
    # 销毁单例
    print("\n6. 销毁组件...")
    await factory.destroy_singletons()

if __name__ == "__main__":
    asyncio.run(main())
