# W-Agent v1.4.4

[English](./README_EN.md) | 简体中文

Python 企业级智能体框架，提供完整的技术架构方案，支持 AOP、IOC、沙箱安全、弹性模式、可观测性等企业级特性。

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/LuckyStar2456/W-Agent-FrameWork?style=social)](https://github.com/LuckyStar2456/W-Agent-FrameWork)

## 📚 目录

- [功能特性](#-功能特性)
- [快速开始](#-快速开始)
- [项目结构](#-项目结构)
- [核心模块](#-核心模块)
- [配置指南](#-配置指南)
- [示例项目](#-示例项目)
- [开发者指南](#-开发者指南)
- [文档](#-文档)
- [贡献指南](#-贡献指南)
- [许可证](#-许可证)

## ✨ 功能特性

| 特性 | 描述 |
|------|------|
| **AOP 面向切面编程** | 支持 AspectJ 切点表达式（execution、within、@annotation、bean、args），提供重试、断路器等切面实现 |
| **IOC 依赖注入** | 三级缓存、构造器/字段/setter 注入、@Autowired/@Qualifier 注解，支持组件扫描和自动装配 |
| **沙箱安全** | Wasm/nsjail 沙箱、seccomp 过滤、资源限制，确保技能执行安全 |
| **弹性模式** | 重试（带退避）、断路器（CLOSED/OPEN/HALF_OPEN 状态）、超时控制，提高系统稳定性 |
| **可观测性** | OpenTelemetry 集成、链路追踪、指标监控、健康检查，提供完整的可观测性解决方案 |
| **RAG 集成** | 向量检索（Redis/内存）、相似度搜索，支持文档存储和检索增强生成 |
| **配置热更新** | 动态配置管理、配置变更事件，支持运行时配置更新和属性绑定 |
| **事件总线** | 异步事件发布/订阅，支持事件驱动架构 |
| **生命周期管理** | 组件生命周期管理、优雅启动和关闭，支持依赖顺序管理 |
| **分布式锁** | Redis 分布式锁实现，支持锁续期和超时控制 |
| **技能系统** | 可扩展的技能系统，支持技能注册和执行 |

## 🚀 快速开始

### 安装

```bash
# 从 PyPI 安装
pip install wagent-framework

# 安装可选依赖
pip install wagent-framework[fastapi,langchain,redis,opentelemetry]

# 从源码安装
pip install -e .
```

### 创建你的第一个 Agent

```python
import asyncio
from w_agent import BaseAgent, BeanFactory, AgentComponent

@AgentComponent(name="hello_agent")
class HelloAgent(BaseAgent):
    async def arun(self, prompt: str) -> str:
        return f"Hello, {prompt}!"

async def main():
    # 创建 Bean 工厂
    bean_factory = BeanFactory()

    # 注册 Agent
    agent = HelloAgent()
    bean_factory.register_bean("hello_agent", agent)

    # 使用 Agent
    agent = await bean_factory.get_bean("hello_agent")
    result = await agent.arun("World")
    print(result)  # 输出: Hello, World!

asyncio.run(main())
```

### 使用配置热更新

```python
import asyncio
from w_agent import DynamicConfigManager

async def main():
    config_manager = DynamicConfigManager()

    # 设置配置
    config_manager.set("api_key", "your-api-key")

    # 绑定配置到属性
    class MyService:
        def __init__(self):
            self.api_key = None
            config_manager.bind("api_key", self, "api_key")

        async def on_config_change(self, key, new_value, old_value):
            print(f"Config changed: {key} = {new_value}")

    service = MyService()
    print(service.api_key)  # 输出: your-api-key

    # 动态更新配置
    await config_manager.update_batch({"api_key": "new-api-key"})
    print(service.api_key)  # 输出: new-api-key

asyncio.run(main())
```

### 使用 AOP 切面编程

```python
import asyncio
from w_agent import Retry, CircuitBreaker

# 使用重试装饰器
@Retry(max_attempts=3, delay=0.1, backoff=2.0)
async def unreliable_operation():
    print("执行不稳定操作...")
    # 模拟失败
    raise Exception("临时失败")

# 使用断路器
@CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
async def protected_operation():
    print("执行受保护操作...")
    # 模拟失败
    raise Exception("服务不可用")

async def main():
    try:
        await unreliable_operation()
    except Exception as e:
        print(f"最终失败: {e}")

asyncio.run(main())
```

### 使用事件总线

```python
import asyncio
from w_agent import EventBus, Event

event_bus = EventBus()

@event_bus.on("user.created")
async def on_user_created(event):
    print(f"User created: {event.payload}")

@event_bus.on("user.updated")
async def on_user_updated(event):
    print(f"User updated: {event.payload}")

async def main():
    # 发布用户创建事件
    await event_bus.emit(Event("user.created", {"user_id": 123, "name": "John"}))

    # 发布用户更新事件
    await event_bus.emit(Event("user.updated", {"user_id": 123, "name": "John Doe"}))

asyncio.run(main())
```

## 📁 项目结构

```
w_agent/
├── aop/                    # 面向切面编程
│   ├── aspects.py          # 切面实现（重试、断路器）
│   ├── joinpoint.py        # 连接点
│   ├── pointcut.py         # 切点表达式解析
│   └── proxy_factory.py    # 代理工厂
├── config/                 # 配置管理
│   └── dynamic_config.py   # 动态配置
├── container/              # 依赖注入容器
│   ├── bean_factory.py     # Bean 工厂
│   └── reflection_cache.py # 反射缓存
├── core/                   # 核心功能
│   ├── agent.py           # Agent 基类
│   ├── decorators.py      # 装饰器
│   ├── doctor.py          # 系统检查
│   └── event_bus.py       # 事件总线
├── deployment/             # 部署相关
│   └── fastapi_depends.py  # FastAPI 依赖注入
├── distributed/            # 分布式功能
│   ├── lock.py            # 分布式锁
│   └── lock_pool.py       # 锁池管理
├── exceptions/             # 异常处理
│   └── framework_errors.py # 框架错误定义
├── lifecycle/              # 生命周期管理
│   ├── graceful_shutdown.py # 优雅关闭
│   ├── manager.py         # 生命周期管理器
│   └── order.py           # 生命周期顺序
├── observability/          # 可观测性
│   ├── health.py          # 健康检查
│   ├── logging.py         # 日志管理
│   ├── metrics.py         # 指标监控
│   └── tracing.py         # 链路追踪
├── resilience/             # 弹性模式
│   ├── bulkhead.py        # 隔离舱模式
│   └── timeout.py         # 超时控制
├── scanner/                # 组件扫描
│   ├── cache.py           # 扫描缓存
│   └── parallel_scanner.py # 并行扫描
├── security/               # 安全相关
│   └── mcp_auth.py        # MCP 认证
├── skills/                # 技能系统
│   ├── sandbox/           # 沙箱
│   │   ├── nsjail_sandbox.py
│   │   └── wasm_sandbox.py
│   ├── signature.py       # 技能签名
│   └── skill.py           # 技能基类
├── testing/                # 测试工具
│   └── mock_utils.py       # 模拟工具
├── tools/                  # 工具类
│   └── langchain_adapter.py # LangChain 适配器
├── __init__.py            # 包初始化
├── __main__.py            # 主入口
└── cli.py                 # 命令行工具
```

## 🔧 核心模块

### AOP 切面编程

AOP (Aspect-Oriented Programming) 允许你在不修改原有代码的情况下，为代码添加横切关注点。

```python
from w_agent import AspectJPointcut, BeforeAdvice, AfterAdvice, AroundAdvice, ProxyFactory

# 定义目标类
class Target:
    def do_something(self, value):
        return f"Result: {value}"

# 创建通知
execution_order = []

async def before_advice(joinpoint):
    execution_order.append("before")

async def after_advice(joinpoint, result):
    execution_order.append("after")

async def around_advice(joinpoint, proceed):
    execution_order.append("around_before")
    result = await proceed()
    execution_order.append("around_after")
    return result

# 创建代理
proxy_factory = ProxyFactory()
target = Target()
advices = [
    BeforeAdvice(before_advice),
    AroundAdvice(around_advice),
    AfterAdvice(after_advice)
]
proxy = proxy_factory.create_proxy(target, {"do_something": advices})

# 调用方法
result = await proxy.do_something("test")
print(f"Result: {result}")
print(f"Execution order: {execution_order}")
```

### 依赖注入

IOC (Inversion of Control) 容器提供了依赖注入功能，简化了组件之间的依赖管理。

```python
from w_agent import BeanFactory, ServiceComponent, Autowired, Qualifier

@ServiceComponent(name="user_repository")
class UserRepository:
    def get_user(self, user_id):
        return {"id": user_id, "name": "John"}

@ServiceComponent(name="user_service")
class UserService:
    @Autowired
    @Qualifier(name="user_repository")
    def set_repository(self, repository):
        self.repository = repository

    def get_user(self, user_id):
        return self.repository.get_user(user_id)

async def main():
    # 创建 Bean 工厂
    bean_factory = BeanFactory()

    # 注册组件
    repository = UserRepository()
    bean_factory.register_bean("user_repository", repository)

    service = UserService()
    bean_factory.register_bean("user_service", service)

    # 自动注入依赖
    await bean_factory.autowire_all()

    # 使用服务
    user = service.get_user(123)
    print(f"User: {user}")

asyncio.run(main())
```

### 事件总线

事件总线提供了异步事件发布/订阅机制，支持事件驱动架构。

```python
from w_agent import EventBus, Event, ConfigChangedEvent

event_bus = EventBus()

# 订阅配置变更事件
@event_bus.on("config_changed")
async def on_config_changed(event):
    print(f"Config changed: {event.payload}")

async def main():
    # 发布自定义事件
    await event_bus.emit(Event("custom_event", {"data": "test"}))

    # 发布配置变更事件
    await event_bus.emit(ConfigChangedEvent(key="api_key", old_value="old", new_value="new"))

asyncio.run(main())
```

### 生命周期管理

生命周期管理器负责组件的初始化和销毁，支持依赖顺序管理。

```python
from w_agent import LifecycleManager, LifecycleOrder, PostConstruct, PreDestroy

class DatabaseService:
    @PostConstruct(order=1)
    async def init_db(self):
        print("初始化数据库连接")

    @PreDestroy(order=1)
    async def close_db(self):
        print("关闭数据库连接")

class UserService:
    @PostConstruct(order=2)
    async def init_service(self):
        print("初始化用户服务")

    @PreDestroy(order=2)
    async def cleanup_service(self):
        print("清理用户服务")

async def main():
    # 创建生命周期管理器
    lifecycle_manager = LifecycleManager()

    # 注册组件
    db_service = DatabaseService()
    lifecycle_manager.register(db_service, LifecycleOrder.INFRASTRUCTURE)

    user_service = UserService()
    lifecycle_manager.register(user_service, LifecycleOrder.SERVICE)

    # 执行初始化
    await lifecycle_manager.post_construct_all()

    # 执行销毁
    await lifecycle_manager.pre_destroy_all()

asyncio.run(main())
```

### 配置管理

动态配置管理器支持配置热更新和属性绑定。

```python
from w_agent import DynamicConfigManager

async def main():
    config_manager = DynamicConfigManager()

    # 加载配置文件
    await config_manager.load_from_file("config.json")

    # 设置配置
    config_manager.set("service.port", 8080)
    config_manager.set("service.host", "localhost")

    # 绑定配置到对象
    class ServiceConfig:
        def __init__(self):
            self.port = None
            self.host = None
            config_manager.bind("service.port", self, "port")
            config_manager.bind("service.host", self, "host")

        async def on_config_change(self, key, new_value, old_value):
            print(f"Config changed: {key} = {new_value}")

    service_config = ServiceConfig()
    print(f"Initial config: host={service_config.host}, port={service_config.port}")

    # 动态更新配置
    await config_manager.update_batch({"service.port": 8081, "service.host": "0.0.0.0"})
    print(f"Updated config: host={service_config.host}, port={service_config.port}")

asyncio.run(main())
```

### 沙箱安全

沙箱提供了安全的技能执行环境，支持 Wasm 和 nsjail 沙箱。

```python
from w_agent import WasmSkillSandbox, NsJailSkillSandbox, Skill
from pathlib import Path

# 创建技能
skill = Skill(
    name="test_skill",
    description="Test skill",
    scripts={"test": Path("test.py")}
)

# 使用 Wasm 沙箱
wasm_sandbox = WasmSkillSandbox()
result = await wasm_sandbox.execute(skill, "test", {"name": "World"})
print(f"Wasm sandbox result: {result}")

# 使用 nsjail 沙箱
nsjail_sandbox = NsJailSkillSandbox()
result = await nsjail_sandbox.execute(skill, "test", {"name": "World"})
print(f"NsJail sandbox result: {result}")
```

## ⚙️ 配置指南

### 可配置项一览

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `logging.level` | string | "INFO" | 日志级别 |
| `logging.format` | string | "json" | 日志格式 |
| `container.scan_paths` | list | ["."] | 组件扫描路径 |
| `container.skip_paths` | list | ["__pycache__", ".git"] | 跳过的扫描路径 |
| `sandbox.enabled` | bool | true | 是否启用沙箱 |
| `sandbox.type` | string | "wasm" | 沙箱类型：wasm/nsjail |
| `resilience.retry.max_attempts` | int | 3 | 最大重试次数 |
| `resilience.retry.delay` | float | 0.1 | 重试延迟（秒） |
| `resilience.retry.backoff` | float | 2.0 | 重试退避系数 |
| `resilience.circuit_breaker.failure_threshold` | int | 5 | 断路器失败阈值 |
| `resilience.circuit_breaker.recovery_timeout` | float | 30.0 | 断路器恢复超时（秒） |
| `distributed.lock.redis.url` | string | "redis://localhost:6379" | Redis 连接 URL |
| `distributed.lock.redis.db` | int | 0 | Redis 数据库编号 |
| `observability.tracing.enabled` | bool | true | 是否启用链路追踪 |
| `observability.tracing.exporter` | string | "otlp" | 追踪导出器 |
| `observability.metrics.enabled` | bool | true | 是否启用指标监控 |

### 配置文件

创建 `config.json`：

```json
{
  "logging": {
    "level": "INFO",
    "format": "json"
  },
  "container": {
    "scan_paths": ["src"],
    "skip_paths": ["__pycache__", ".git"]
  },
  "sandbox": {
    "enabled": true,
    "type": "wasm"
  },
  "resilience": {
    "retry": {
      "max_attempts": 3,
      "delay": 0.1,
      "backoff": 2.0
    },
    "circuit_breaker": {
      "failure_threshold": 5,
      "recovery_timeout": 30.0
    }
  }
}
```

### 环境变量

环境变量优先级高于配置文件：

```bash
export W_AGENT_LOGGING_LEVEL=DEBUG
export W_AGENT_CONTAINER_SCAN_PATHS=src,components
export W_AGENT_SANDBOX_ENABLED=true
export W_AGENT_RESILIENCE_RETRY_MAX_ATTEMPTS=5
```

## 📖 示例项目

### 基本 Agent 示例

查看 [examples/basic_agent.py](./examples/basic_agent.py) 获取基本 Agent 实现示例，展示了：

- Agent 和 Service 组件的创建
- 依赖注入
- 配置绑定和热更新
- 生命周期管理

### 聊天 Agent 示例

查看 [chat-agent](./chat-agent/) 目录获取完整的聊天智能体示例项目，包含：

- Agent 实现
- LLM 服务集成
- 技能系统
- RAG 检索增强
- Redis/MySQL 集成
- OpenTelemetry 可观测性
- 系统健康检查

## 👨‍💻 开发者指南

### 核心概念

1. **Agent**：智能体基类，所有智能体都继承自 `BaseAgent`
2. **Component**：组件，使用 `@AgentComponent`、`@ServiceComponent` 等注解标记
3. **Bean**：由容器管理的组件实例
4. **Aspect**：切面，用于横切关注点
5. **Event**：事件，用于组件间通信
6. **Lifecycle**：生命周期，管理组件的初始化和销毁
7. **Skill**：技能，可被 Agent 调用的功能模块

### 开发流程

1. **创建 Agent**：继承 `BaseAgent` 并实现 `arun` 方法
2. **创建服务**：使用 `@ServiceComponent` 标记服务类
3. **配置依赖**：使用 `@Autowired` 和 `@Qualifier` 注入依赖
4. **添加生命周期**：使用 `@PostConstruct` 和 `@PreDestroy` 标记生命周期方法
5. **添加 AOP 切面**：使用 `@Retry`、`@CircuitBreaker` 等注解添加切面
6. **注册 Bean**：使用 `BeanFactory` 注册组件
7. **启动应用**：执行 `post_construct_all` 初始化组件

### 最佳实践

1. **组件设计**：将功能拆分为小而专注的组件
2. **依赖管理**：使用依赖注入而非硬编码依赖
3. **错误处理**：使用 AOP 切面处理重试和断路器
4. **配置管理**：使用动态配置管理，避免硬编码配置
5. **可观测性**：添加适当的日志、指标和追踪
6. **安全性**：使用沙箱执行外部代码
7. **测试**：为组件编写单元测试和集成测试

### 常见问题

#### 依赖注入失败
- 确保组件已正确注册到 BeanFactory
- 确保依赖项已注册且名称正确
- 检查依赖类型是否匹配

#### 配置不生效
- 检查配置文件路径是否正确
- 检查环境变量是否覆盖了配置文件
- 检查配置键名是否正确

#### 沙箱执行失败
- 检查 Wasm 或 nsjail 是否已正确安装
- 检查技能脚本是否符合沙箱要求
- 检查资源限制是否合理

## 📄 文档

- [架构设计文档](./docs/architecture.md)：详细介绍框架架构和设计理念
- [API 文档](./docs/api.md)：完整的 API 参考
- [使用指南](./docs/guide.md)：详细的使用教程
- [开发者文档](./docs/developer.md)：开发者级别的使用说明

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

## 📄 许可证

本项目采用 [MIT 许可证](LICENSE)。

---

如果这个项目对你有帮助，请给我们一个 ⭐！

## 📦 PyPI 包

- **包名**: `wagent-framework`
- **版本**: 1.4.4
- **安装**: `pip install wagent-framework`
- **PyPI 地址**: [https://pypi.org/project/wagent-framework/](https://pypi.org/project/wagent-framework/)

## 📝 更新日志

### v1.4.4 (2026-04-26)
- **框架优化**: 完善了核心功能的稳定性和性能
- **代码质量**: 提升了代码的可维护性和可读性
- **文档更新**: 提供了更详细的框架说明和核心功能演示
- **开发者指南**: 添加了开发者级别的使用说明
- **示例项目**: 优化了示例代码和说明文档

### v1.4.2 (2026-04-22)
- **文档更新**: 提供更详细的框架说明和核心功能演示
- **开发者指南**: 添加了开发者级别的使用说明
- **示例项目**: 优化了示例代码和说明文档
- **代码质量**: 提升了代码的可维护性和可读性

### v1.4.1 (2026-04-22)
- **修复包结构**: 添加了缺失的 `__init__.py` 文件，确保包可以正常导入
- **修复导入错误**: 修正了 `w_agent/__init__.py` 中的导入错误
- **上传到 PyPI**: 成功发布到 PyPI
- **更新 GitHub**: 同步更新了 GitHub 仓库

### v1.4.0 (2026-04-21)
- **核心功能**: AOP、IOC、沙箱安全、弹性模式、可观测性、RAG 集成
- **配置管理**: 动态配置热更新
- **事件总线**: 支持事件发布/订阅
- **生命周期管理**: 支持组件生命周期
- **CLI 工具**: 提供命令行工具
