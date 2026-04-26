"""W-Agent 框架包"""

__version__ = "1.4.4"
__author__ = "LuckyStar2456"
__license__ = "MIT"

# 导出核心模块
from w_agent.core.agent import BaseAgent
from w_agent.container.bean_factory import BeanFactory, BeanDefinition, Scope
from w_agent.config.dynamic_config import DynamicConfigManager
from w_agent.core.decorators import (
    AgentComponent, ServiceComponent, ToolComponent,
    RepositoryComponent, ControllerComponent, Component,
    PostConstruct, PreDestroy, Autowired, Qualifier,
    Retry, CircuitBreaker
)
from w_agent.core.event_bus import EventBus, Event, ConfigChangedEvent
from w_agent.core.doctor import Doctor
from w_agent.lifecycle.manager import LifecycleManager
from w_agent.lifecycle.order import LifecycleOrder
from w_agent.aop.pointcut import AspectJPointcut, BeforeAdvice, AfterAdvice, AroundAdvice
from w_agent.aop.proxy_factory import ProxyFactory
from w_agent.aop.joinpoint import JoinPoint
from w_agent.aop.aspects import RetryAspect, CircuitBreakerAspect
from w_agent.observability.tracing import global_tracer
from w_agent.observability.health import CompositeHealthIndicator, HealthIndicator, LLMHealthIndicator
from w_agent.distributed.lock import RedisDistributedLock
from w_agent.distributed.lock_pool import LockRenewalPool
from w_agent.resilience.bulkhead import ResilienceManager
from w_agent.skills.sandbox.wasm_sandbox import WasmSkillSandbox
from w_agent.skills.sandbox.nsjail_sandbox import NsJailSkillSandbox
from w_agent.skills.skill import Skill
from w_agent.exceptions.framework_errors import BeanNotFoundError, InjectionError
from w_agent.scanner.parallel_scanner import ParallelASTScanner
from w_agent.lifecycle.graceful_shutdown import GracefulShutdownManager
from w_agent.tools.langchain_adapter import LangChainToolAdapter

__all__ = [
    "BaseAgent",
    "BeanFactory",
    "BeanDefinition",
    "Scope",
    "DynamicConfigManager",
    "AgentComponent",
    "ServiceComponent",
    "ToolComponent",
    "RepositoryComponent",
    "ControllerComponent",
    "Component",
    "PostConstruct",
    "PreDestroy",
    "Autowired",
    "Qualifier",
    "Retry",
    "CircuitBreaker",
    "EventBus",
    "Event",
    "ConfigChangedEvent",
    "Doctor",
    "LifecycleManager",
    "LifecycleOrder",
    "GracefulShutdownManager",
    "ResilienceManager",
    "AspectJPointcut",
    "BeforeAdvice",
    "AfterAdvice",
    "AroundAdvice",
    "ProxyFactory",
    "JoinPoint",
    "RetryAspect",
    "CircuitBreakerAspect",
    "global_tracer",
    "CompositeHealthIndicator",
    "HealthIndicator",
    "LLMHealthIndicator",
    "RedisDistributedLock",
    "LockRenewalPool",
    "WasmSkillSandbox",
    "NsJailSkillSandbox",
    "Skill",
    "BeanNotFoundError",
    "InjectionError",
    "ParallelASTScanner",
    "LangChainToolAdapter"
]
