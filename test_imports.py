#!/usr/bin/env python3
"""
测试w_agent包的导入功能
"""

# 测试核心模块导入
print("测试核心模块导入...")
try:
    from w_agent import BaseAgent, BeanFactory, DynamicConfigManager
    print("OK 核心模块导入成功")
except ImportError as e:
    print(f"ERROR 核心模块导入失败: {e}")

# 测试装饰器导入
print("\n测试装饰器导入...")
try:
    from w_agent import AgentComponent, ServiceComponent, PostConstruct, PreDestroy, Autowired, Qualifier, Retry, CircuitBreaker
    print("OK 装饰器导入成功")
except ImportError as e:
    print(f"ERROR 装饰器导入失败: {e}")

# 测试事件总线导入
print("\n测试事件总线导入...")
try:
    from w_agent import EventBus, Event, ConfigChangedEvent
    print("OK 事件总线导入成功")
except ImportError as e:
    print(f"ERROR 事件总线导入失败: {e}")

# 测试生命周期导入
print("\n测试生命周期导入...")
try:
    from w_agent import LifecycleManager, LifecycleOrder
    print("OK 生命周期导入成功")
except ImportError as e:
    print(f"ERROR 生命周期导入失败: {e}")

# 测试AOP导入
print("\n测试AOP导入...")
try:
    from w_agent import AspectJPointcut, BeforeAdvice, AfterAdvice, AroundAdvice, ProxyFactory, JoinPoint, RetryAspect, CircuitBreakerAspect
    print("OK AOP导入成功")
except ImportError as e:
    print(f"ERROR AOP导入失败: {e}")

# 测试可观测性导入
print("\n测试可观测性导入...")
try:
    from w_agent import global_tracer, CompositeHealthIndicator, HealthIndicator, LLMHealthIndicator
    print("OK 可观测性导入成功")
except ImportError as e:
    print(f"ERROR 可观测性导入失败: {e}")

# 测试分布式锁导入
print("\n测试分布式锁导入...")
try:
    from w_agent import RedisDistributedLock, LockRenewalPool
    print("OK 分布式锁导入成功")
except ImportError as e:
    print(f"ERROR 分布式锁导入失败: {e}")

# 测试弹性管理导入
print("\n测试弹性管理导入...")
try:
    from w_agent import ResilienceManager
    print("OK 弹性管理导入成功")
except ImportError as e:
    print(f"ERROR 弹性管理导入失败: {e}")

# 测试沙箱导入
print("\n测试沙箱导入...")
try:
    from w_agent import WasmSkillSandbox, NsJailSkillSandbox, Skill
    print("OK 沙箱导入成功")
except ImportError as e:
    print(f"ERROR 沙箱导入失败: {e}")

# 测试异常导入
print("\n测试异常导入...")
try:
    from w_agent import BeanNotFoundError, InjectionError
    print("OK 异常导入成功")
except ImportError as e:
    print(f"ERROR 异常导入失败: {e}")

# 测试容器相关导入
print("\n测试容器相关导入...")
try:
    from w_agent import BeanDefinition, Scope
    print("OK 容器相关导入成功")
except ImportError as e:
    print(f"ERROR 容器相关导入失败: {e}")

print("\n所有导入测试完成！")
