#!/usr/bin/env python3
"""
W-Agent 框架主入口
"""

import sys
import asyncio
from w_agent.core.agent import BaseAgent
from w_agent.container.bean_factory import BeanFactory
from w_agent.config.dynamic_config import DynamicConfigManager

class DefaultAgent(BaseAgent):
    """默认Agent"""
    async def arun(self, prompt: str) -> str:
        """运行Agent"""
        return f"W-Agent: {prompt}"

async def main():
    """主函数"""
    # 创建配置管理器
    config_manager = DynamicConfigManager()
    config_manager.set("agent.name", "default")

    # 创建Bean工厂
    bean_factory = BeanFactory()

    # 创建并注册默认Agent
    agent = DefaultAgent()
    bean_factory._singleton_objects["default_agent"] = agent

    # 处理命令行参数
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        result = await agent.arun(prompt)
        print(result)
    else:
        print("W-Agent v1.5.0")
        print("Usage: python -m w_agent <prompt>")

if __name__ == "__main__":
    asyncio.run(main())
