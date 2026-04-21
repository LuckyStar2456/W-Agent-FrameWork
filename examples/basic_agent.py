#!/usr/bin/env python3
"""
W-Agent 基本示例
"""

import asyncio
from w_agent.core.decorators import AgentComponent, ServiceComponent, PostConstruct, PreDestroy
from w_agent.container.bean_factory import BeanFactory
from w_agent.config.dynamic_config import DynamicConfigManager

# 配置管理器
config_manager = DynamicConfigManager()
config_manager.set("agent.name", "DemoAgent")
config_manager.set("greeting", "Hello")

@ServiceComponent(name="greeting_service")
class GreetingService:
    """问候服务"""
    def __init__(self):
        self.greeting = None
        # 绑定配置
        config_manager.bind("greeting", self, "greeting")
    
    def get_greeting(self, name: str) -> str:
        """获取问候语"""
        return f"{self.greeting}, {name}!"
    
    async def on_config_change(self, key, new_value, old_value):
        """配置变更回调"""
        print(f"Config changed: {key} = {new_value}")

@AgentComponent(name="demo_agent")
class DemoAgent:
    """示例Agent"""
    def __init__(self, greeting_service: GreetingService):
        self.greeting_service = greeting_service
        self.name = None
        # 绑定配置
        config_manager.bind("agent.name", self, "name")
    
    async def arun(self, prompt: str) -> str:
        """运行Agent"""
        return self.greeting_service.get_greeting(prompt)
    
    @PostConstruct
    def initialize(self):
        """初始化方法"""
        print(f"{self.name} is initializing...")
    
    @PreDestroy
    def cleanup(self):
        """销毁方法"""
        print(f"{self.name} is cleaning up...")

async def main():
    """主函数"""
    # 创建Bean工厂
    factory = BeanFactory()
    
    # 注册服务
    greeting_service = GreetingService()
    factory.register_bean("greeting_service", greeting_service)
    
    # 注册Agent
    agent = DemoAgent(greeting_service)
    factory.register_bean("demo_agent", agent)
    
    # 运行Agent
    result = await agent.arun("World")
    print(f"Agent result: {result}")
    
    # 动态更新配置
    print("\nUpdating config...")
    await config_manager.update_batch({"greeting": "Hi", "agent.name": "UpdatedAgent"})
    
    # 再次运行Agent
    result = await agent.arun("World")
    print(f"Agent result after config update: {result}")
    
    # 销毁单例
    print("\nDestroying singletons...")
    await factory.destroy_singletons()

if __name__ == "__main__":
    asyncio.run(main())
