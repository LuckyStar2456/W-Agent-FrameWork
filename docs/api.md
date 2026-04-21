# W-Agent API 文档

## 核心组件

### Agent

#### BaseAgent

Agent 基类，所有 Agent 需要继承此类。

```python
from w_agent.core.agent import BaseAgent

class MyAgent(BaseAgent):
    async def arun(self, prompt: str) -> str:
        return f"Response to: {prompt}"
```

**方法**：
- `arun(prompt: str) -> str` - 异步执行 Agent

### 依赖注入容器

#### BeanFactory

Bean 工厂类，负责 Bean 的创建和管理。

```python
from w_agent.container.bean_factory import BeanFactory, BeanDefinition, Scope

bean_factory = BeanFactory()

# 注册 Bean
bean_factory.register_bean("my_service", MyService())

# 获取 Bean
service = await bean_factory.get_bean("my_service")
```

**方法**：
- `register_bean(name: str, instance: Any, scope: str = Scope.SINGLETON)` - 注册 Bean 实例
- `register_bean_definition(name: str, definition: BeanDefinition)` - 注册 Bean 定义
- `async get_bean(name: str) -> Any` - 获取 Bean
- `async destroy_singletons()` - 销毁所有单例

#### BeanDefinition

Bean 定义类。

```python
definition = BeanDefinition(
    name="user_service",
    bean_type=UserService,
    scope=Scope.SINGLETON,
    init_method="init",
    destroy_method="destroy",
    dependencies=["db_connection"]
)
```

### 装饰器

#### 组件装饰器

```python
from w_agent.core.decorators import (
    AgentComponent, ServiceComponent, ToolComponent,
    RepositoryComponent, ControllerComponent
)

@AgentComponent(name="my_agent")
class MyAgent:
    pass

@ServiceComponent(name="my_service")
class MyService:
    pass
```

#### 生命周期装饰器

```python
from w_agent.core.decorators import PostConstruct, PreDestroy

class MyService:
    @PostConstruct(order=1)
    async def init(self):
        print("Initialized")

    @PreDestroy(order=1)
    async def destroy(self):
        print("Destroyed")
```

#### 弹性装饰器

```python
from w_agent.core.decorators import Retry, CircuitBreaker

@Retry(max_attempts=3, delay=0.1, backoff=2.0)
async def unreliable_operation():
    pass

@CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
async def protected_operation():
    pass
```

#### 依赖注入装饰器

```python
from w_agent.core.decorators import Autowired, Qualifier

class UserService:
    @Qualifier(name="redis_client")
    def set_cache(self, cache_client):
        self.cache = cache_client
```

### 配置管理

#### DynamicConfigManager

动态配置管理器。

```python
from w_agent.config.dynamic_config import DynamicConfigManager

config = DynamicConfigManager()

# 设置配置
config.set("api_key", "your-api-key")

# 绑定配置到属性
config.bind("api_key", service, "api_key")

# 批量更新
await config.update_batch({"key1": "value1", "key2": "value2"})

# 监听配置变更
config.on_change(lambda key, old, new: print(f"{key} changed"))
```

**方法**：
- `set(key: str, value: Any)` - 设置配置
- `get(key: str, default: Any = None) -> Any` - 获取配置
- `bind(key: str, obj: Any, attr: str)` - 绑定配置到属性
- `async update_batch(updates: Dict[str, Any])` - 批量更新
- `on_change(callback: Callable)` - 注册配置变更监听器

### 事件总线

#### EventBus

事件总线，支持重试和死信队列。

```python
from w_agent.core.event_bus import EventBus, Event

event_bus = EventBus()

# 注册监听器
@event_bus.on("user.created")
async def on_user_created(event):
    print(f"User created: {event.payload}")

# 发布事件
await event_bus.emit(Event("user.created", {"user_id": 123}))
```

#### Event

事件类。

```python
event = Event(
    name="order.created",
    payload={"order_id": 123, "amount": 100.0},
    retry_count=3,
    max_retries=3
)
```

### AOP

#### AspectJPointcut

切点表达式解析器。

```python
from w_agent.aop.pointcut import AspectJPointcut

# 创建切点
pointcut = AspectJPointcut("execution(* com.example.*.*(..))")

# 匹配方法
matches = pointcut.matches(method, target_class, "bean_name")
```

#### 通知类

```python
from w_agent.aop.pointcut import BeforeAdvice, AfterAdvice, AroundAdvice

# 前置通知
before_advice = BeforeAdvice(lambda jp: print("Before"))

# 后置通知
after_advice = AfterAdvice(lambda jp, result: print(f"After: {result}"))

# 环绕通知
around_advice = AroundAdvice(lambda jp, proceed: proceed())
```

### 分布式锁

#### DistributedLock

分布式锁。

```python
from w_agent.distributed.lock import DistributedLock

lock = DistributedLock(redis_client, "my_lock", ttl=30)

async with lock.acquire():
    # 临界区操作
    pass
```

**方法**：
- `async acquire(timeout: float = None) -> bool` - 获取锁
- `async release()` - 释放锁
- `async renew()` - 续期锁

### 可观测性

#### 全局追踪器

```python
from w_agent.observability.tracing import global_tracer

# 创建_span
with global_tracer.start_span("operation") as span:
    # 执行操作
    span.set_attribute("key", "value")
```

#### 健康检查

```python
from w_agent.observability.health import HealthCheck

health = HealthCheck()

# 添加检查项
health.add_check("database", lambda: check_db())

# 获取健康状态
status = await health.check()
```

### 沙箱

#### WasmSkillSandbox

Wasm 沙箱。

```python
from w_agent.skills.sandbox.wasm_sandbox import WasmSkillSandbox

sandbox = WasmSkillSandbox(precompiled_path=Path("./wasm"))

result = await sandbox.execute(skill, "script_name", {"arg": "value"})
```

#### NsJailSkillSandbox

NsJail 沙箱。

```python
from w_agent.skills.sandbox.nsjail_sandbox import NsJailSkillSandbox

sandbox = NsJailSkillSandbox(
    max_cpu_seconds=5,
    max_memory_bytes=100 * 1024 * 1024
)

result = await sandbox.execute(skill, "script_name", {"arg": "value"})
```

## 异常类

### 框架异常

```python
from w_agent.exceptions.framework_errors import (
    BeanNotFoundError,
    CircularDependencyError,
    InjectionError,
    ConfigurationError
)
```

### 分布式异常

```python
from w_agent.distributed.lock import LockAcquisitionError, LockRenewalError
```
