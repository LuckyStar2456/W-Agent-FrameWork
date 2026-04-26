# W-Agent 开发者指南

[English](../README_EN.md) | 简体中文

本指南旨在帮助开发者深入理解 W-Agent 框架的架构和使用方法，以便能够高效地构建基于框架的应用。

## 📚 目录

- [框架架构](#-框架架构)
- [核心概念](#-核心概念)
- [开发流程](#-开发流程)
- [组件开发](#-组件开发)
- [高级特性](#-高级特性)
- [性能优化](#-性能优化)
- [测试策略](#-测试策略)
- [部署指南](#-部署指南)
- [常见问题](#-常见问题)

## 🏗️ 框架架构

W-Agent 框架采用模块化、分层架构设计，提供了完整的企业级智能体开发能力。

### 架构层次

1. **核心层**：提供基础功能和核心抽象
   - `core/`：核心功能，包括 Agent 基类、装饰器、事件总线等
   - `container/`：依赖注入容器，管理组件生命周期
   - `config/`：配置管理，支持动态配置更新

2. **功能层**：提供各种企业级功能
   - `aop/`：面向切面编程，支持重试、断路器等
   - `lifecycle/`：生命周期管理，支持组件的初始化和销毁
   - `resilience/`：弹性模式，提高系统稳定性
   - `observability/`：可观测性，支持链路追踪和指标监控

3. **服务层**：提供特定领域的服务
   - `skills/`：技能系统，支持技能注册和执行
   - `distributed/`：分布式功能，包括分布式锁
   - `scanner/`：组件扫描，自动发现和注册组件

4. **工具层**：提供各种工具和适配器
   - `tools/`：工具类，如 LangChain 适配器
   - `testing/`：测试工具，支持单元测试和集成测试
   - `deployment/`：部署相关，如 FastAPI 依赖注入

### 核心流程

1. **初始化流程**：
   - 创建 `BeanFactory` 实例
   - 注册组件和服务
   - 执行 `post_construct_all` 初始化组件
   - 启动应用

2. **请求处理流程**：
   - 接收用户输入
   - 调用 Agent 的 `arun` 方法
   - Agent 分析意图并调用相应服务
   - 服务处理并返回结果
   - Agent 生成回复并返回

3. **销毁流程**：
   - 执行 `pre_destroy_all` 销毁组件
   - 释放资源

## 📝 核心概念

### 1. Agent

**定义**：智能体基类，所有智能体都继承自 `BaseAgent`

**核心方法**：
- `arun(prompt: str) -> str`：异步运行 Agent，处理用户输入并返回结果

**使用示例**：

```python
from w_agent import BaseAgent, AgentComponent

@AgentComponent(name="my_agent")
class MyAgent(BaseAgent):
    async def arun(self, prompt: str) -> str:
        return f"Hello, {prompt}!"
```

### 2. Component

**定义**：组件，使用 `@AgentComponent`、`@ServiceComponent` 等注解标记

**类型**：
- `@AgentComponent`：标记 Agent 组件
- `@ServiceComponent`：标记服务组件
- `@ToolComponent`：标记工具组件
- `@RepositoryComponent`：标记仓库组件
- `@ControllerComponent`：标记控制器组件

**使用示例**：

```python
from w_agent import ServiceComponent

@ServiceComponent(name="user_service")
class UserService:
    def get_user(self, user_id):
        return {"id": user_id, "name": "John"}
```

### 3. Bean

**定义**：由容器管理的组件实例

**作用域**：
- `Singleton`：单例，默认作用域
- `Prototype`：原型，每次获取都会创建新实例

**使用示例**：

```python
from w_agent import BeanFactory, Scope

# 创建 Bean 工厂
factory = BeanFactory()

# 注册单例 Bean
factory.register_bean("user_service", UserService())

# 注册原型 Bean
from w_agent import BeanDefinition

definition = BeanDefinition(
    name="prototype_bean",
    bean_type=MyClass,
    scope=Scope.PROTOTYPE
)
factory.register_bean_definition("prototype_bean", definition)
```

### 4. Aspect

**定义**：切面，用于横切关注点

**类型**：
- `@Retry`：重试切面，处理临时失败
- `@CircuitBreaker`：断路器切面，防止系统雪崩
- 自定义切面：通过 `BeforeAdvice`、`AfterAdvice`、`AroundAdvice` 实现

**使用示例**：

```python
from w_agent import Retry, CircuitBreaker

@Retry(max_attempts=3, delay=0.1, backoff=2.0)
async def unreliable_operation():
    # 可能失败的操作
    pass

@CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
async def protected_operation():
    # 需要保护的操作
    pass
```

### 5. Event

**定义**：事件，用于组件间通信

**类型**：
- `Event`：通用事件
- `ConfigChangedEvent`：配置变更事件
- 自定义事件：继承 `Event` 类

**使用示例**：

```python
from w_agent import EventBus, Event

event_bus = EventBus()

@event_bus.on("user.created")
async def on_user_created(event):
    print(f"User created: {event.payload}")

# 发布事件
await event_bus.emit(Event("user.created", {"user_id": 123}))
```

### 6. Lifecycle

**定义**：生命周期，管理组件的初始化和销毁

**注解**：
- `@PostConstruct`：组件初始化后执行
- `@PreDestroy`：组件销毁前执行

**使用示例**：

```python
from w_agent import PostConstruct, PreDestroy

class DatabaseService:
    @PostConstruct(order=1)
    async def init_db(self):
        print("初始化数据库连接")
    
    @PreDestroy(order=1)
    async def close_db(self):
        print("关闭数据库连接")
```

### 7. Skill

**定义**：技能，可被 Agent 调用的功能模块

**沙箱**：
- `WasmSkillSandbox`：Wasm 沙箱，安全执行技能
- `NsJailSkillSandbox`：nsjail 沙箱，提供更强的隔离

**使用示例**：

```python
from w_agent import Skill, WasmSkillSandbox
from pathlib import Path

# 创建技能
skill = Skill(
    name="test_skill",
    description="Test skill",
    scripts={"test": Path("test.py")}
)

# 执行技能
sandbox = WasmSkillSandbox()
result = await sandbox.execute(skill, "test", {"name": "World"})
```

## 🔧 开发流程

### 1. 环境搭建

```bash
# 安装 W-Agent 框架
pip install wagent-framework

# 安装可选依赖
pip install wagent-framework[fastapi,langchain,redis,opentelemetry]
```

### 2. 创建项目结构

```
my-agent-app/
├── app.py                  # 应用入口
├── config/
│   └── config.json        # 配置文件
├── src/
│   ├── agents/            # Agent 实现
│   ├── services/          # 服务实现
│   ├── skills/            # 技能实现
│   └── utils/             # 工具类
└── requirements.txt       # 依赖文件
```

### 3. 实现 Agent

```python
# src/agents/my_agent.py
from w_agent import BaseAgent, AgentComponent, Autowired, Qualifier

@AgentComponent(name="my_agent")
class MyAgent(BaseAgent):
    @Autowired
    @Qualifier(name="user_service")
    def set_user_service(self, user_service):
        self.user_service = user_service
    
    async def arun(self, prompt: str) -> str:
        # 处理用户输入
        if "用户" in prompt:
            user_id = prompt.split(" ")[-1]
            user = self.user_service.get_user(user_id)
            return f"用户信息: {user}"
        return f"你说: {prompt}"
```

### 4. 实现服务

```python
# src/services/user_service.py
from w_agent import ServiceComponent, PostConstruct

@ServiceComponent(name="user_service")
class UserService:
    def __init__(self):
        self.users = {}
    
    @PostConstruct
    def init(self):
        # 初始化用户数据
        self.users["1"] = {"id": "1", "name": "John"}
        self.users["2"] = {"id": "2", "name": "Jane"}
    
    def get_user(self, user_id):
        return self.users.get(user_id, {"error": "User not found"})
```

### 5. 配置管理

```json
// config/config.json
{
  "system": {
    "name": "My Agent App",
    "version": "1.0.0"
  },
  "logging": {
    "level": "INFO"
  }
}
```

### 6. 应用入口

```python
# app.py
import asyncio
from w_agent import BeanFactory, DynamicConfigManager, LifecycleManager
from src.agents.my_agent import MyAgent
from src.services.user_service import UserService

async def main():
    # 加载配置
    config_manager = DynamicConfigManager()
    await config_manager.load_from_file("config/config.json")
    
    # 创建组件
    user_service = UserService()
    my_agent = MyAgent()
    
    # 注册组件
    bean_factory = BeanFactory()
    bean_factory.register_bean("user_service", user_service)
    bean_factory.register_bean("my_agent", my_agent)
    
    # 初始化组件
    lifecycle_manager = LifecycleManager()
    lifecycle_manager.register(user_service)
    lifecycle_manager.register(my_agent)
    await lifecycle_manager.post_construct_all()
    
    # 运行 Agent
    agent = await bean_factory.get_bean("my_agent")
    result = await agent.arun("用户 1")
    print(f"Agent: {result}")
    
    # 销毁组件
    await lifecycle_manager.pre_destroy_all()

if __name__ == "__main__":
    asyncio.run(main())
```

## 🧩 组件开发

### 1. 依赖注入

#### 构造器注入

```python
from w_agent import ServiceComponent

@ServiceComponent(name="order_service")
class OrderService:
    def __init__(self, user_service):
        self.user_service = user_service
```

#### Setter 注入

```python
from w_agent import ServiceComponent, Autowired, Qualifier

@ServiceComponent(name="order_service")
class OrderService:
    @Autowired
    @Qualifier(name="user_service")
    def set_user_service(self, user_service):
        self.user_service = user_service
```

#### 字段注入

```python
from w_agent import ServiceComponent, Autowired

@ServiceComponent(name="order_service")
class OrderService:
    @Autowired
    user_service = None
```

### 2. 配置绑定

```python
from w_agent import ServiceComponent

@ServiceComponent(name="api_service")
class ApiService:
    def __init__(self, config_manager):
        self.api_key = None
        self.api_url = None
        
        # 绑定配置
        config_manager.bind("api.key", self, "api_key")
        config_manager.bind("api.url", self, "api_url")
    
    async def on_config_change(self, key, new_value, old_value):
        print(f"配置变更: {key} = {new_value}")
```

### 3. 事件处理

```python
from w_agent import ServiceComponent, PostConstruct

@ServiceComponent(name="notification_service")
class NotificationService:
    def __init__(self, event_bus):
        self.event_bus = event_bus
    
    @PostConstruct
    def init(self):
        # 订阅事件
        self.event_bus.on("user.created", self.on_user_created)
        self.event_bus.on("order.placed", self.on_order_placed)
    
    async def on_user_created(self, event):
        print(f"发送用户创建通知: {event.payload}")
    
    async def on_order_placed(self, event):
        print(f"发送订单通知: {event.payload}")
```

### 4. AOP 切面

#### 自定义切面

```python
from w_agent import AspectJPointcut, BeforeAdvice, AfterAdvice, ProxyFactory

# 定义目标类
class UserService:
    def get_user(self, user_id):
        return {"id": user_id, "name": "John"}

# 创建通知
async def before_advice(joinpoint):
    print(f"调用方法: {joinpoint.method_name}")

async def after_advice(joinpoint, result):
    print(f"方法返回: {result}")

# 创建切点
pointcut = AspectJPointcut("execution(* UserService.get_user(*))")

# 创建代理
proxy_factory = ProxyFactory()
target = UserService()
advices = [BeforeAdvice(before_advice), AfterAdvice(after_advice)]
proxy = proxy_factory.create_proxy(target, {"get_user": advices})

# 调用方法
result = await proxy.get_user(123)
```

## ⚡ 高级特性

### 1. 分布式锁

```python
from w_agent import RedisDistributedLock, LockRenewalPool

# 创建 Redis 客户端
import redis
redis_client = redis.Redis(host="localhost", port=6379, db=0)

# 创建分布式锁
lock = RedisDistributedLock(redis_client, "resource_lock", timeout=60)

# 获取锁
acquired = await lock.acquire()
if acquired:
    try:
        # 执行需要锁定的操作
        print("获取锁成功，执行操作")
    finally:
        # 释放锁
        await lock.release()

# 使用锁续期池
pool = LockRenewalPool()
pool.start_renewal("resource_lock", lock)

# 停止续期
await pool.stop_renewal("resource_lock")

# 关闭池
await pool.shutdown()
```

### 2. 可观测性

```python
from w_agent import global_tracer, CompositeHealthIndicator, HealthIndicator

# 使用链路追踪
with global_tracer().start_as_current_span("user_service.get_user") as span:
    span.set_attribute("user_id", "123")
    # 执行操作

# 健康检查
class DatabaseHealthIndicator(HealthIndicator):
    def __init__(self, db_client):
        self.db_client = db_client
    
    async def health_check(self):
        try:
            # 测试数据库连接
            await self.db_client.ping()
            return {"status": "UP", "details": {"database": "healthy"}}
        except Exception as e:
            return {"status": "DOWN", "details": {"database": str(e)}}

# 创建复合健康指示器
health_indicator = CompositeHealthIndicator()
health_indicator.add_indicator("database", DatabaseHealthIndicator(db_client))

# 执行健康检查
health_status = await health_indicator.health()
print(f"健康状态: {health_status}")
```

### 3. 技能系统

```python
from w_agent import Skill, WasmSkillSandbox
from pathlib import Path

# 创建技能
skill = Skill(
    name="weather_skill",
    description="天气查询技能",
    scripts={"query": Path("weather.py")}
)

# 执行技能
sandbox = WasmSkillSandbox()
result = await sandbox.execute(skill, "query", {"city": "北京"})
print(f"技能执行结果: {result}")
```

### 4. LangChain 集成

```python
from w_agent import LangChainAdapter

# 创建 LangChain 适配器
adapter = LangChainAdapter()

# 使用 LangChain 组件
from langchain.llms import OpenAI
llm = OpenAI(api_key="your-api-key")

# 适配 LangChain LLM 到 W-Agent
w_agent_llm = adapter.adapt_llm(llm)

# 使用适配后的 LLM
result = await w_agent_llm.generate("Hello, world!")
print(f"LLM 生成结果: {result}")
```

## 🚀 性能优化

### 1. 缓存策略

```python
from w_agent import ServiceComponent, PostConstruct

@ServiceComponent(name="user_service")
class UserService:
    def __init__(self, redis_service):
        self.redis_service = redis_service
        self.cache_ttl = 3600  # 缓存过期时间（秒）
    
    async def get_user(self, user_id):
        # 尝试从缓存获取
        cache_key = f"user:{user_id}"
        cached_user = self.redis_service.get(cache_key)
        if cached_user:
            return cached_user
        
        # 从数据库获取
        user = await self._fetch_user_from_db(user_id)
        
        # 存入缓存
        if user:
            self.redis_service.set(cache_key, user, expire=self.cache_ttl)
        
        return user
    
    async def _fetch_user_from_db(self, user_id):
        # 从数据库获取用户
        pass
```

### 2. 异步处理

```python
from w_agent import ServiceComponent
import asyncio

@ServiceComponent(name="data_service")
class DataService:
    async def process_batch(self, items):
        # 并行处理多个项目
        tasks = [self.process_item(item) for item in items]
        results = await asyncio.gather(*tasks)
        return results
    
    async def process_item(self, item):
        # 处理单个项目
        pass
```

### 3. 连接池

```python
from w_agent import ServiceComponent, PostConstruct, PreDestroy
import aiohttp

@ServiceComponent(name="http_service")
async def HttpService:
    def __init__(self):
        self.session = None
    
    @PostConstruct
    async def init(self):
        # 创建连接池
        self.session = aiohttp.ClientSession()
    
    @PreDestroy
    async def cleanup(self):
        # 关闭连接池
        if self.session:
            await self.session.close()
    
    async def get(self, url):
        async with self.session.get(url) as response:
            return await response.json()
```

## 🧪 测试策略

### 1. 单元测试

```python
import pytest
from w_agent import BeanFactory
from src.services.user_service import UserService

@pytest.mark.asyncio
async def test_user_service():
    # 创建服务实例
    user_service = UserService()
    
    # 初始化服务
    user_service.init()
    
    # 测试获取用户
    user = user_service.get_user("1")
    assert user["id"] == "1"
    assert user["name"] == "John"
    
    # 测试获取不存在的用户
    user = user_service.get_user("999")
    assert "error" in user
```

### 2. 集成测试

```python
import pytest
import asyncio
from w_agent import BeanFactory, LifecycleManager
from src.agents.my_agent import MyAgent
from src.services.user_service import UserService

@pytest.mark.asyncio
async def test_agent_integration():
    # 创建组件
    user_service = UserService()
    my_agent = MyAgent()
    
    # 注册组件
    bean_factory = BeanFactory()
    bean_factory.register_bean("user_service", user_service)
    bean_factory.register_bean("my_agent", my_agent)
    
    # 初始化组件
    lifecycle_manager = LifecycleManager()
    lifecycle_manager.register(user_service)
    lifecycle_manager.register(my_agent)
    await lifecycle_manager.post_construct_all()
    
    # 自动注入依赖
    await bean_factory.autowire_all()
    
    # 测试 Agent
    agent = await bean_factory.get_bean("my_agent")
    result = await agent.arun("用户 1")
    assert "John" in result
    
    # 清理
    await lifecycle_manager.pre_destroy_all()
```

### 3. 模拟工具

```python
from w_agent import mock_utils

# 模拟服务
mock_user_service = mock_utils.create_mock_service(
    "user_service",
    get_user=lambda user_id: {"id": user_id, "name": "Mock User"}
)

# 使用模拟服务
user = mock_user_service.get_user("123")
print(f"模拟用户: {user}")
```

## 📦 部署指南

### 1. 容器化部署

```dockerfile
# Dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "app.py"]
```

### 2. Serverless 部署

```python
# serverless/lambda_handler.py
import asyncio
from w_agent import BeanFactory, LifecycleManager
from src.agents.my_agent import MyAgent
from src.services.user_service import UserService

async def handle_event(event, context):
    # 初始化组件
    user_service = UserService()
    my_agent = MyAgent()
    
    # 注册组件
    bean_factory = BeanFactory()
    bean_factory.register_bean("user_service", user_service)
    bean_factory.register_bean("my_agent", my_agent)
    
    # 初始化
    lifecycle_manager = LifecycleManager()
    lifecycle_manager.register(user_service)
    lifecycle_manager.register(my_agent)
    await lifecycle_manager.post_construct_all()
    
    # 处理请求
    prompt = event.get("prompt", "Hello")
    agent = await bean_factory.get_bean("my_agent")
    result = await agent.arun(prompt)
    
    # 清理
    await lifecycle_manager.pre_destroy_all()
    
    return {"response": result}

def lambda_handler(event, context):
    return asyncio.run(handle_event(event, context))
```

### 3. FastAPI 集成

```python
from fastapi import FastAPI
from w_agent import BeanFactory, LifecycleManager
from src.agents.my_agent import MyAgent
from src.services.user_service import UserService

# 创建 FastAPI 应用
app = FastAPI()

# 全局组件
bean_factory = None
lifecycle_manager = None

@app.on_event("startup")
async def startup():
    global bean_factory, lifecycle_manager
    
    # 创建组件
    user_service = UserService()
    my_agent = MyAgent()
    
    # 注册组件
    bean_factory = BeanFactory()
    bean_factory.register_bean("user_service", user_service)
    bean_factory.register_bean("my_agent", my_agent)
    
    # 初始化
    lifecycle_manager = LifecycleManager()
    lifecycle_manager.register(user_service)
    lifecycle_manager.register(my_agent)
    await lifecycle_manager.post_construct_all()
    
    # 自动注入依赖
    await bean_factory.autowire_all()

@app.on_event("shutdown")
async def shutdown():
    global lifecycle_manager
    if lifecycle_manager:
        await lifecycle_manager.pre_destroy_all()

@app.post("/chat")
async def chat(prompt: str):
    agent = await bean_factory.get_bean("my_agent")
    result = await agent.arun(prompt)
    return {"response": result}
```

## ❓ 常见问题

### 1. 依赖注入失败

**症状**：`BeanNotFoundError` 或 `InjectionError`

**原因**：
- 组件未注册到 BeanFactory
- 依赖项名称不匹配
- 依赖类型不匹配

**解决**：
- 确保所有组件都已正确注册
- 检查依赖项名称是否正确
- 确保依赖类型匹配

### 2. 配置不生效

**症状**：配置值未更新或使用默认值

**原因**：
- 配置文件路径错误
- 环境变量覆盖了配置文件
- 配置键名错误

**解决**：
- 检查配置文件路径是否正确
- 检查环境变量是否覆盖了配置
- 检查配置键名是否正确

### 3. 沙箱执行失败

**症状**：`SkillExecutionError` 或执行超时

**原因**：
- Wasm 或 nsjail 未安装
- 技能脚本有错误
- 资源限制过严

**解决**：
- 确保 Wasm 或 nsjail 已正确安装
- 检查技能脚本是否正确
- 调整沙箱资源限制

### 4. 性能问题

**症状**：响应缓慢或内存占用高

**原因**：
- 缓存未使用
- 同步操作阻塞
- 连接未池化

**解决**：
- 实现缓存策略
- 使用异步操作
- 使用连接池

### 5. 可观测性问题

**症状**：日志缺失或指标不完整

**原因**：
- 日志配置错误
- 指标收集未启用
- 追踪未配置

**解决**：
- 检查日志配置
- 启用指标收集
- 配置追踪导出器

## 📄 许可证

本项目采用 [MIT 许可证](../LICENSE)。