# W-Agent v1.4.0

[English](./README_EN.md) | 简体中文

Python 企业级智能体框架，完整技术架构方案。

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/LuckyStar2456/W-Agent-FrameWork?style=social)](https://github.com/LuckyStar2456/W-Agent-FrameWork/stargazers)

## 📚 目录

- [功能特性](#-功能特性)
- [快速开始](#-快速开始)
- [项目结构](#-项目结构)
- [核心模块](#-核心模块)
- [配置指南](#-配置指南)
- [示例项目](#-示例项目)
- [文档](#-文档)
- [贡献指南](#-贡献指南)
- [许可证](#-许可证)

## ✨ 功能特性

| 特性 | 描述 |
|------|------|
| **AOP 面向切面编程** | 支持 AspectJ 切点表达式（execution、within、@annotation、bean、args） |
| **IOC 依赖注入** | 三级缓存、构造器/字段/setter 注入、@Autowired/@Qualifier 注解 |
| **沙箱安全** | Wasm/nsjail 沙箱、seccomp 过滤、资源限制 |
| **弹性模式** | 重试（带退避）、断路器（CLOSED/OPEN/HALF_OPEN 状态） |
| **可观测性** | OpenTelemetry 集成、链路追踪、指标监控 |
| **RAG 集成** | 向量检索（Redis/内存）、相似度搜索 |
| **配置热更新** | 动态配置管理、配置变更事件 |

## 🚀 快速开始

### 安装

```bash
# 基础安装
pip install -e .

# 安装可选依赖
pip install -e .[fastapi,langchain,redis]
```

### 创建你的第一个 Agent

```python
import asyncio
from w_agent.core.agent import BaseAgent
from w_agent.container.bean_factory import BeanFactory
from w_agent.core.decorators import AgentComponent

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
from w_agent.config.dynamic_config import DynamicConfigManager

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
│   ├── event_bus.py       # 事件总线
│   └── decorators.py      # 装饰器
├── observability/          # 可观测性
│   ├── tracing.py         # 链路追踪
│   ├── metrics.py         # 指标监控
│   └── health.py          # 健康检查
├── skills/                # 技能系统
│   └── sandbox/           # 沙箱
│       ├── wasm_sandbox.py
│       └── nsjail_sandbox.py
└── ...
```

## 🔧 核心模块

### AOP 切面编程

```python
from w_agent.core.decorators import Retry, CircuitBreaker
from w_agent.aop.pointcut import AspectJPointcut

# 使用重试装饰器
@Retry(max_attempts=3, delay=0.1, backoff=2.0)
async def unreliable_operation():
    pass

# 使用断路器
@CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
async def protected_operation():
    pass
```

### 依赖注入

```python
from w_agent.core.decorators import Autowired, Qualifier, ServiceComponent

@ServiceComponent(name="user_service")
class UserService:
    @Qualifier(name="redis_client")
    def set_cache(self, cache_client):
        self.cache = cache_client
```

### 事件总线

```python
from w_agent.core.event_bus import EventBus, Event

event_bus = EventBus()

@event_bus.on("user.created")
async def on_user_created(event):
    print(f"User created: {event.payload}")

await event_bus.emit(Event("user.created", {"user_id": 123}))
```

## ⚙️ 配置指南

### 可配置项一览

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `logging.level` | string | "INFO" | 日志级别 |
| `container.scan_paths` | list | ["."] | 组件扫描路径 |
| `sandbox.enabled` | bool | true | 是否启用沙箱 |
| `resilience.retry.max_attempts` | int | 3 | 最大重试次数 |
| `distributed.lock.redis.url` | string | "redis://localhost:6379" | Redis 连接 URL |

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
  }
}
```

### 环境变量

```bash
export W_AGENT_LOGGING_LEVEL=DEBUG
export W_AGENT_CONTAINER_SCAN_PATHS=src,components
```

## 📖 示例项目

查看 [chat-agent](./chat-agent/) 目录获取完整的聊天智能体示例项目，包含：

- Agent 实现
- Skill 系统
- RAG 检索增强
- Redis/MySQL 集成
- OpenTelemetry 可观测性

## 📄 文档

- [架构设计文档](./docs/architecture.md)
- [API 文档](./docs/api.md)
- [使用指南](./docs/guide.md)

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
