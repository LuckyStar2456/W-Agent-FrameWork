# W-Agent 使用指南

## 一、快速入门

### 1.1 安装

```bash
pip install -e .
```

### 1.2 创建第一个 Agent

```python
import asyncio
from w_agent import BaseAgent, BeanFactory, AgentComponent

@AgentComponent(name="hello_agent")
class HelloAgent(BaseAgent):
    async def arun(self, prompt: str) -> str:
        return f"Hello, {prompt}!"

async def main():
    bean_factory = BeanFactory()
    agent = HelloAgent()
    bean_factory.register_bean("hello_agent", agent)

    agent = await bean_factory.get_bean("hello_agent")
    result = await agent.arun("World")
    print(result)

asyncio.run(main())
```

## 二、依赖注入

### 2.1 构造器注入

```python
from w_agent import BeanFactory, BeanDefinition

class UserService:
    def __init__(self, db_connection):
        self.db = db_connection

bean_factory = BeanFactory()
bean_factory.register_bean_definition("user_service", BeanDefinition(
    name="user_service",
    bean_type=UserService,
    dependencies=["db_connection"]
))
```

### 2.2 字段注入

```python
from w_agent import Autowired

class UserService:
    @Autowired(name="redis_client")
    redis_client = None
```

### 2.3 Setter 注入

```python
from w_agent import Qualifier

class UserService:
    @Qualifier(name="cache_client")
    def set_cache(self, cache):
        self.cache = cache
```

## 三、AOP 切面编程

### 3.1 使用重试装饰器

```python
from w_agent import Retry

@Retry(max_attempts=3, delay=1.0, backoff=2.0)
async def unreliable_api_call():
    # 可能失败的操作
    pass
```

### 3.2 使用断路器

```python
from w_agent import CircuitBreaker

@CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
async def protected_operation():
    # 需要保护的操作
    pass
```

### 3.3 自定义切点

```python
from w_agent import AspectJPointcut

# 匹配 com.example 包下所有类的所有方法
pointcut = AspectJPointcut("within(com.example..*)")

if pointcut.matches(method, target_class, "bean_name"):
    print("Method matched!")
```

## 四、配置管理

### 4.1 基础配置

```python
from w_agent import DynamicConfigManager

config = DynamicConfigManager()

# 设置配置
config.set("app.name", "MyApp")
config.set("app.debug", True)

# 获取配置
name = config.get("app.name")
debug = config.get("app.debug", default=False)
```

### 4.2 配置绑定

```python
class MyService:
    def __init__(self):
        self.api_key = None
        config.bind("api_key", self, "api_key")

    async def on_config_change(self, key, new_value, old_value):
        print(f"Config {key} changed from {old_value} to {new_value}")
```

### 4.3 配置文件

创建 `config.json`：

```json
{
  "logging": {
    "level": "INFO"
  },
  "database": {
    "host": "localhost",
    "port": 3306
  }
}
```

## 五、事件总线

### 5.1 发布订阅

```python
from w_agent import EventBus, Event

event_bus = EventBus()

# 订阅事件
@event_bus.on("order.created")
async def handle_order_created(event):
    print(f"Order created: {event.payload}")

# 发布事件
await event_bus.emit(Event("order.created", {"order_id": 123}))
```

### 5.2 死信队列

```python
# 获取死信队列
dlq = event_bus.get_dead_letter_queue()

# 处理死信
await event_bus.process_dead_letter_queue()
```

## 六、分布式锁

### 6.1 基本使用

```python
from w_agent import RedisDistributedLock

lock = RedisDistributedLock(redis_client, "my_resource", ttl=30)

async with lock.acquire():
    # 临界区操作
    pass
```

### 6.2 锁续期

```python
from w_agent import LockRenewalPool

pool = LockRenewalPool(redis_client)
pool.start()

lock = await pool.acquire_lock("resource", ttl=30, renew_interval=10)

# 锁会自动续期

await pool.release_lock(lock)
pool.stop()
```

## 七、沙箱执行

### 7.1 Wasm 沙箱

```python
from w_agent import WasmSkillSandbox
from pathlib import Path

sandbox = WasmSkillSandbox(precompiled_path=Path("./wasm"))

result = await sandbox.execute(skill, "script_name", {"arg": "value"})
```

### 7.2 NsJail 沙箱

```python
from w_agent import NsJailSkillSandbox

sandbox = NsJailSkillSandbox(
    max_cpu_seconds=5,
    max_memory_bytes=100 * 1024 * 1024
)

result = await sandbox.execute(skill, "script_name", {"arg": "value"})
```

## 八、可观测性

### 8.1 链路追踪

```python
from w_agent import global_tracer

with global_tracer.start_span("my_operation") as span:
    span.set_attribute("key", "value")
    span.add_event("event_name")

    # 执行操作
    pass
```

### 8.2 健康检查

```python
from w_agent import CompositeHealthIndicator, HealthIndicator

health = CompositeHealthIndicator()

health.add_check("database", check_database_connection)
health.add_check("redis", check_redis_connection)

status = await health.check()
print(f"Health status: {status}")
```

## 九、最佳实践

### 9.1 项目结构

```
my_project/
├── w_agent/              # 框架代码
├── src/                  # 业务代码
│   ├── agents/          # Agent 实现
│   ├── services/        # 服务实现
│   └── models/          # 数据模型
├── config/              # 配置文件
│   └── config.json
├── skills/              # 技能脚本
└── tests/               # 测试代码
```

### 9.2 组件扫描

```python
from w_agent import ParallelASTScanner

scanner = ParallelASTScanner(
    scan_paths=["src"],
    skip_paths=["__pycache__", "tests"]
)

components = await scanner.scan()
```

### 9.3 优雅关闭

```python
from w_agent import GracefulShutdownManager

shutdown = GracefulShutdownManager(timeout=30)

@shutdown.on_shutdown
async def cleanup():
    await bean_factory.destroy_singletons()

shutdown.register_signal_handlers()
```

## 十、常见问题

### Q1: 如何处理循环依赖？

A: W-Agent 使用三级缓存机制自动处理循环依赖。确保使用 `BeanDefinition` 注册依赖关系，而不是直接实例化。

### Q2: 如何配置多环境？

A: 使用环境变量或创建多个配置文件：

```bash
export W_AGENT_ENV=production
export W_AGENT_LOGGING_LEVEL=WARNING
```

### Q3: 如何扩展自定义组件？

A: 继承框架基类并使用组件装饰器：

```python
from w_agent import Component

@Component(name="custom")
class CustomComponent:
    pass
```
