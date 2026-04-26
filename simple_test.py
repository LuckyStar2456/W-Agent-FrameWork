#!/usr/bin/env python3
"""
简单测试w_agent包的导入功能
"""

print("开始测试w_agent包导入...")

# 测试核心模块导入
try:
    from w_agent import BaseAgent, BeanFactory, DynamicConfigManager
    print("核心模块导入成功")
except ImportError as e:
    print(f"核心模块导入失败: {e}")

# 测试装饰器导入
try:
    from w_agent import AgentComponent, ServiceComponent, PostConstruct, PreDestroy
    print("装饰器导入成功")
except ImportError as e:
    print(f"装饰器导入失败: {e}")

# 测试事件总线导入
try:
    from w_agent import EventBus, Event
    print("事件总线导入成功")
except ImportError as e:
    print(f"事件总线导入失败: {e}")

# 测试生命周期导入
try:
    from w_agent import LifecycleManager
    print("生命周期导入成功")
except ImportError as e:
    print(f"生命周期导入失败: {e}")

print("测试完成！")
