#!/usr/bin/env python3
"""Serverless Lambda处理程序"""

import asyncio
import contextvars
from pathlib import Path
from w_agent.container.bean_factory import BeanFactory

# 请求级上下文
request_context = contextvars.ContextVar("request_context", default={})

# 全局BeanFactory
bean_factory = None

async def initialize_bean_factory():
    """初始化BeanFactory"""
    global bean_factory
    
    # 检查是否有快照
    snapshot_path = Path("/tmp/bean_factory.snapshot")
    if snapshot_path.exists():
        # 从快照恢复
        bean_factory = BeanFactory.from_snapshot(snapshot_path)
    else:
        # 创建新的BeanFactory
        bean_factory = BeanFactory()
        
        # 注册组件（需要根据实际应用替换）
        # 示例：
        # from my_app.services import MyService
        # from my_app.agents import MyAgent
        # 
        # service = MyService()
        # bean_factory.register_bean("my_service", service)
        # 
        # agent = MyAgent(service)
        # bean_factory.register_bean("default_agent", agent)
        
        # 创建快照
        bean_factory.create_snapshot(snapshot_path)

async def handle_request(event, context):
    """处理Lambda请求"""
    try:
        # 初始化请求上下文
        request_id = context.aws_request_id
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
