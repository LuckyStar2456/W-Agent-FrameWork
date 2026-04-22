# W-Agent v1.4.1

[English](./README_EN.md) | [简体中文](./README.md)

Python Enterprise Agent Framework, Complete Technical Architecture Solution.

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/LuckyStar2456/W-Agent-FrameWork?style=social)](https://github.com/LuckyStar2456/W-Agent-FrameWork)

## 📚 Table of Contents

- [Features](#-features)
- [Quick Start](#-quick-start)
- [Project Structure](#-project-structure)
- [Core Modules](#-core-modules)
- [Configuration Guide](#-configuration-guide)
- [Example Project](#-example-project)
- [Documentation](#-documentation)
- [Contributing](#-contributing)
- [License](#-license)

## ✨ Features

| Feature | Description |
|---------|-------------|
| **AOP Aspect-Oriented Programming** | Supports AspectJ pointcut expressions (execution, within, @annotation, bean, args) |
| **IOC Dependency Injection** | Three-level caching, constructor/field/setter injection, @Autowired/@Qualifier annotations |
| **Sandbox Security** | Wasm/nsjail sandbox, seccomp filtering, resource limits |
| **Resilience Patterns** | Retry (with backoff), Circuit Breaker (CLOSED/OPEN/HALF_OPEN states) |
| **Observability** | OpenTelemetry integration, distributed tracing, metrics monitoring |
| **RAG Integration** | Vector search (Redis/memory), similarity search |
| **Hot Config Reload** | Dynamic configuration management, config change events |

## 🚀 Quick Start

### Installation

```bash
# Install from PyPI
pip install wagent-framework

# Install optional dependencies
pip install wagent-framework[fastapi,langchain,redis,opentelemetry]

# Install from source
pip install -e .
```

### Create Your First Agent

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
    # Create Bean factory
    bean_factory = BeanFactory()

    # Register Agent
    agent = HelloAgent()
    bean_factory.register_bean("hello_agent", agent)

    # Use Agent
    agent = await bean_factory.get_bean("hello_agent")
    result = await agent.arun("World")
    print(result)  # Output: Hello, World!

asyncio.run(main())
```

### Using Hot Config Reload

```python
import asyncio
from w_agent.config.dynamic_config import DynamicConfigManager

async def main():
    config_manager = DynamicConfigManager()

    # Set config
    config_manager.set("api_key", "your-api-key")

    # Bind config to property
    class MyService:
        def __init__(self):
            self.api_key = None
            config_manager.bind("api_key", self, "api_key")

        async def on_config_change(self, key, new_value, old_value):
            print(f"Config changed: {key} = {new_value}")

    service = MyService()
    print(service.api_key)  # Output: your-api-key

    # Dynamically update config
    await config_manager.update_batch({"api_key": "new-api-key"})
    print(service.api_key)  # Output: new-api-key

asyncio.run(main())
```

## 📁 Project Structure

```
w_agent/
├── aop/                    # Aspect-Oriented Programming
│   ├── aspects.py          # Aspect implementations (retry, circuit breaker)
│   ├── joinpoint.py       # Join point
│   ├── pointcut.py        # Pointcut expression parser
│   └── proxy_factory.py   # Proxy factory
├── config/                 # Configuration Management
│   └── dynamic_config.py  # Dynamic configuration
├── container/              # Dependency Injection Container
│   ├── bean_factory.py    # Bean factory
│   └── reflection_cache.py # Reflection cache
├── core/                   # Core Features
│   ├── agent.py           # Agent base class
│   ├── event_bus.py       # Event bus
│   └── decorators.py      # Decorators
├── observability/          # Observability
│   ├── tracing.py         # Distributed tracing
│   ├── metrics.py         # Metrics monitoring
│   └── health.py          # Health check
├── skills/                # Skills System
│   └── sandbox/           # Sandbox
│       ├── wasm_sandbox.py
│       └── nsjail_sandbox.py
└── ...
```

## 🔧 Core Modules

### AOP Aspect-Oriented Programming

```python
from w_agent.core.decorators import Retry, CircuitBreaker
from w_agent.aop.pointcut import AspectJPointcut

# Using retry decorator
@Retry(max_attempts=3, delay=0.1, backoff=2.0)
async def unreliable_operation():
    pass

# Using circuit breaker
@CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
async def protected_operation():
    pass
```

### Dependency Injection

```python
from w_agent.core.decorators import Autowired, Qualifier, ServiceComponent

@ServiceComponent(name="user_service")
class UserService:
    @Qualifier(name="redis_client")
    def set_cache(self, cache_client):
        self.cache = cache_client
```

### Event Bus

```python
from w_agent.core.event_bus import EventBus, Event

event_bus = EventBus()

@event_bus.on("user.created")
async def on_user_created(event):
    print(f"User created: {event.payload}")

await event_bus.emit(Event("user.created", {"user_id": 123}))
```

## ⚙️ Configuration Guide

### Configuration Options

| Config | Type | Default | Description |
|--------|------|---------|-------------|
| `logging.level` | string | "INFO" | Log level |
| `container.scan_paths` | list | ["."] | Component scan paths |
| `sandbox.enabled` | bool | true | Enable sandbox |
| `resilience.retry.max_attempts` | int | 3 | Max retry attempts |
| `distributed.lock.redis.url` | string | "redis://localhost:6379" | Redis connection URL |

### Configuration File

Create `config.json`:

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

### Environment Variables

```bash
export W_AGENT_LOGGING_LEVEL=DEBUG
export W_AGENT_CONTAINER_SCAN_PATHS=src,components
```

## 📖 Example Project

Check the [chat-agent](./chat-agent/) directory for a complete chat agent example project, including:

- Agent implementation
- Skills system
- RAG retrieval augmentation
- Redis/MySQL integration
- OpenTelemetry observability

## 📄 Documentation

- [Architecture Documentation](./docs/architecture.md)
- [API Documentation](./docs/api.md)
- [User Guide](./docs/guide.md)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

If you find this project helpful, please give us a ⭐!

## 📦 PyPI Package

- **Package Name**: `wagent-framework`
- **Version**: 1.4.1
- **Installation**: `pip install wagent-framework`
- **PyPI URL**: [https://pypi.org/project/wagent-framework/](https://pypi.org/project/wagent-framework/)
