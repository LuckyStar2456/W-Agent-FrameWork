#!/usr/bin/env python3
"""Serverless Lambda处理程序"""

import asyncio
import contextvars
import os
import tempfile
from pathlib import Path
from w_agent.container.bean_factory import BeanDefinition, BeanFactory
from w_agent.core.agent import BaseAgent

# 请求级上下文
request_context = contextvars.ContextVar("request_context", default={})

# 全局BeanFactory
bean_factory = None


class ServerlessDefaultAgent(BaseAgent):
    async def arun(self, prompt: str) -> str:
        return f"W-Agent: {prompt}"

async def initialize_bean_factory():
    """初始化BeanFactory"""
    global bean_factory
    
    # 检查是否有快照
    snapshot_path = Path(
        os.environ.get(
            "W_AGENT_SNAPSHOT_PATH",
            str(Path(tempfile.gettempdir()) / "w_agent_bean_factory.snapshot"),
        )
    )
    if snapshot_path.exists():
        # 从快照恢复
        bean_factory = BeanFactory.from_snapshot(snapshot_path)
    else:
        # 创建新的BeanFactory
        bean_factory = BeanFactory()
        
        bean_factory.register_bean_definition(
            "default_agent",
            BeanDefinition("default_agent", ServerlessDefaultAgent),
        )
        
        # 创建快照
        bean_factory.create_snapshot(snapshot_path)

async def handle_request(event, context):
    """处理Lambda请求"""
    try:
        global bean_factory
        if bean_factory is None:
            await initialize_bean_factory()
        # 初始化请求上下文
        request_id = getattr(context, "aws_request_id", "local")
        request_context.set({"request_id": request_id})
        
        # 获取Agent
        agent = await bean_factory.get_bean("default_agent")
        
        # 处理请求
        prompt = event.get("prompt", "World")
        result = await agent.arun(prompt)
        
        # 返回结果
        return {
            "statusCode": 200,
            "body": {
                "response": result
            }
        }
    finally:
        # 清理请求上下文
        request_context.set({})

def lambda_handler(event, context):
    """Lambda处理程序入口"""
    # 初始化BeanFactory（首次调用时）
    global bean_factory
    if bean_factory is None:
        asyncio.run(initialize_bean_factory())
    
    # 处理请求
    return asyncio.run(handle_request(event, context))
