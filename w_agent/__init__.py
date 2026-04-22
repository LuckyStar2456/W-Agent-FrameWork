"""W-Agent 框架包"""

__version__ = "1.4.1"
__author__ = "LuckyStar2456"
__license__ = "MIT"

# 导出核心模块
from w_agent.core.agent import BaseAgent
from w_agent.container.bean_factory import BeanFactory
from w_agent.config.dynamic_config import DynamicConfigManager
from w_agent.core.decorators import (
    AgentComponent, ServiceComponent, ToolComponent,
    RepositoryComponent, ControllerComponent,
    PostConstruct, PreDestroy, Autowired, Qualifier,
    Retry, CircuitBreaker
)
from w_agent.core.event_bus import EventBus, Event
from w_agent.aop.pointcut import AspectJPointcut
from w_agent.observability.tracing import global_tracer
from w_agent.observability.health import CompositeHealthIndicator, HealthIndicator, LLMHealthIndicator
from w_agent.distributed.lock import RedisDistributedLock
from w_agent.skills.sandbox.wasm_sandbox import WasmSkillSandbox
from w_agent.skills.sandbox.nsjail_sandbox import NsJailSkillSandbox

__all__ = [
    "BaseAgent",
    "BeanFactory",
    "DynamicConfigManager",
    "AgentComponent",
    "ServiceComponent",
    "ToolComponent",
    "RepositoryComponent",
    "ControllerComponent",
    "PostConstruct",
    "PreDestroy",
    "Autowired",
    "Qualifier",
    "Retry",
    "CircuitBreaker",
    "EventBus",
    "Event",
    "AspectJPointcut",
    "global_tracer",
    "CompositeHealthIndicator",
    "HealthIndicator",
    "LLMHealthIndicator",
    "RedisDistributedLock",
    "WasmSkillSandbox",
    "NsJailSkillSandbox"
]
