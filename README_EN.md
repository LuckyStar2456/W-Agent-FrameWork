# W-Agent v1.5.0

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
| **AOP Aspect-Oriented Programming** | Supports AspectJ pointcut expressions (execution, within, @annotation, bean, args), provides retry, circuit breaker aspects |
| **IOC Dependency Injection** | Three-level caching, constructor/field/setter injection, @Autowired/@Qualifier annotations, component scanning |
| **Sandbox Security** | Wasm/nsjail sandbox, seccomp filtering, resource limits, ensures safe skill execution |
| **Resilience Patterns** | Retry (with backoff), Circuit Breaker (CLOSED/OPEN/HALF_OPEN states), timeout control |
| **Observability** | OpenTelemetry integration, distributed tracing, metrics monitoring, health checks |
| **RAG Integration** | Vector search (Redis/memory), similarity search, document storage and retrieval-augmented generation |
| **Hot Config Reload** | Dynamic configuration management, config change events, runtime config updates |
| **Event Bus** | Async event publish/subscribe, event-driven architecture |
| **Lifecycle Management** | Component lifecycle, graceful startup and shutdown, dependency order management |
| **Distributed Lock** | Redis distributed lock, lock renewal and timeout control |
| **Skills System** | Extensible skills system, skill registration and execution |

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
from w_agent import BaseAgent, BeanFactory, AgentComponent

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
from w_agent import DynamicConfigManager

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

### Using AOP Aspect-Oriented Programming

```python
import asyncio
from w_agent import Retry, CircuitBreaker

# Using retry decorator
@Retry(max_attempts=3, delay=0.1, backoff=2.0)
async def unreliable_operation():
    print("Executing unstable operation...")
    # Simulate failure
    raise Exception("Temporary failure")

# Using circuit breaker
@CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
async def protected_operation():
    print("Executing protected operation...")
    # Simulate failure
    raise Exception("Service unavailable")

async def main():
    try:
        await unreliable_operation()
    except Exception as e:
        print(f"Final failure: {e}")

asyncio.run(main())
```

### Using Event Bus

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
    # Publish user created event
    await event_bus.emit(Event("user.created", {"user_id": 123, "name": "John"}))

    # Publish user updated event
    await event_bus.emit(Event("user.updated", {"user_id": 123, "name": "John Doe"}))

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
│   ├── decorators.py      # Decorators
│   ├── doctor.py          # System check
│   └── event_bus.py       # Event bus
├── deployment/             # Deployment
│   └── fastapi_depends.py # FastAPI dependency injection
├── distributed/            # Distributed Features
│   ├── lock.py           # Distributed lock
│   └── lock_pool.py      # Lock pool management
├── exceptions/             # Exception Handling
│   └── framework_errors.py # Framework error definitions
├── lifecycle/              # Lifecycle Management
│   ├── graceful_shutdown.py # Graceful shutdown
│   ├── manager.py        # Lifecycle manager
│   └── order.py          # Lifecycle order
├── observability/          # Observability
│   ├── health.py         # Health check
│   ├── logging.py        # Logging management
│   ├── metrics.py        # Metrics monitoring
│   └── tracing.py        # Distributed tracing
├── resilience/             # Resilience Patterns
│   ├── bulkhead.py       # Bulkhead pattern
│   └── timeout.py        # Timeout control
├── scanner/                # Component Scanning
│   ├── cache.py          # Scan cache
│   └── parallel_scanner.py # Parallel scanning
├── security/               # Security
│   └── mcp_auth.py       # MCP authentication
├── skills/                # Skills System
│   ├── sandbox/           # Sandbox
│   │   ├── nsjail_sandbox.py
│   │   └── wasm_sandbox.py
│   ├── signature.py      # Skill signature
│   └── skill.py          # Skill base class
├── testing/                # Testing Tools
│   └── mock_utils.py      # Mock utilities
├── tools/                  # Utilities
│   └── langchain_adapter.py # LangChain adapter
├── __init__.py           # Package initialization
├── __main__.py           # Main entry
└── cli.py                # CLI tool
```

## 🔧 Core Modules

### AOP Aspect-Oriented Programming

AOP allows you to add cross-cutting concerns without modifying existing code.

```python
from w_agent import AspectJPointcut, BeforeAdvice, AfterAdvice, AroundAdvice, ProxyFactory

# Define target class
class Target:
    def do_something(self, value):
        return f"Result: {value}"

# Create advices
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

# Create proxy
proxy_factory = ProxyFactory()
target = Target()
advices = [
    BeforeAdvice(before_advice),
    AroundAdvice(around_advice),
    AfterAdvice(after_advice)
]
proxy = proxy_factory.create_proxy(target, {"do_something": advices})

# Call method
result = await proxy.do_something("test")
print(f"Result: {result}")
print(f"Execution order: {execution_order}")
```

### Dependency Injection

IOC container provides dependency injection to simplify component dependency management.

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
    # Create Bean factory
    bean_factory = BeanFactory()

    # Register components
    repository = UserRepository()
    bean_factory.register_bean("user_repository", repository)

    service = UserService()
    bean_factory.register_bean("user_service", service)

    # Auto-wire dependencies
    await bean_factory.autowire_all()

    # Use service
    user = service.get_user(123)
    print(f"User: {user}")

asyncio.run(main())
```

### Event Bus

Event bus provides async event publish/subscribe for event-driven architecture.

```python
from w_agent import EventBus, Event, ConfigChangedEvent

event_bus = EventBus()

# Subscribe to config changed events
@event_bus.on("config_changed")
async def on_config_changed(event):
    print(f"Config changed: {event.payload}")

async def main():
    # Publish custom event
    await event_bus.emit(Event("custom_event", {"data": "test"}))

    # Publish config changed event
    await event_bus.emit(ConfigChangedEvent(key="api_key", old_value="old", new_value="new"))

asyncio.run(main())
```

### Lifecycle Management

Lifecycle manager handles component initialization and destruction with dependency ordering.

```python
from w_agent import LifecycleManager, LifecycleOrder, PostConstruct, PreDestroy

class DatabaseService:
    @PostConstruct(order=1)
    async def init_db(self):
        print("Initializing database connection")

    @PreDestroy(order=1)
    async def close_db(self):
        print("Closing database connection")

class UserService:
    @PostConstruct(order=2)
    async def init_service(self):
        print("Initializing user service")

    @PreDestroy(order=2)
    async def cleanup_service(self):
        print("Cleaning up user service")

async def main():
    # Create lifecycle manager
    lifecycle_manager = LifecycleManager()

    # Register components
    db_service = DatabaseService()
    lifecycle_manager.register(db_service, LifecycleOrder.INFRASTRUCTURE)

    user_service = UserService()
    lifecycle_manager.register(user_service, LifecycleOrder.SERVICE)

    # Execute initialization
    await lifecycle_manager.post_construct_all()

    # Execute destruction
    await lifecycle_manager.pre_destroy_all()

asyncio.run(main())
```

### Configuration Management

Dynamic configuration manager supports hot config reload and property binding.

```python
from w_agent import DynamicConfigManager

async def main():
    config_manager = DynamicConfigManager()

    # Load config file
    await config_manager.load_from_file("config.json")

    # Set config
    config_manager.set("service.port", 8080)
    config_manager.set("service.host", "localhost")

    # Bind config to object
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

    # Dynamically update config
    await config_manager.update_batch({"service.port": 8081, "service.host": "0.0.0.0"})
    print(f"Updated config: host={service_config.host}, port={service_config.port}")

asyncio.run(main())
```

### Sandbox Security

Sandbox provides secure skill execution environment, supporting Wasm and nsjail sandbox.

```python
from w_agent import WasmSkillSandbox, NsJailSkillSandbox, Skill
from pathlib import Path

# Create skill
skill = Skill(
    name="test_skill",
    description="Test skill",
    scripts={"test": Path("test.py")}
)

# Use Wasm sandbox
wasm_sandbox = WasmSkillSandbox()
result = await wasm_sandbox.execute(skill, "test", {"name": "World"})
print(f"Wasm sandbox result: {result}")

# Use nsjail sandbox
nsjail_sandbox = NsJailSkillSandbox()
result = await nsjail_sandbox.execute(skill, "test", {"name": "World"})
print(f"NsJail sandbox result: {result}")
```

## ⚙️ Configuration Guide

### Configuration Options

| Config | Type | Default | Description |
|--------|------|---------|-------------|
| `logging.level` | string | "INFO" | Log level |
| `logging.format` | string | "json" | Log format |
| `container.scan_paths` | list | ["."] | Component scan paths |
| `container.skip_paths` | list | ["__pycache__", ".git"] | Skip scan paths |
| `sandbox.enabled` | bool | true | Enable sandbox |
| `sandbox.type` | string | "wasm" | Sandbox type: wasm/nsjail |
| `resilience.retry.max_attempts` | int | 3 | Max retry attempts |
| `resilience.retry.delay` | float | 0.1 | Retry delay (seconds) |
| `resilience.retry.backoff` | float | 2.0 | Retry backoff factor |
| `resilience.circuit_breaker.failure_threshold` | int | 5 | Circuit breaker failure threshold |
| `resilience.circuit_breaker.recovery_timeout` | float | 30.0 | Circuit breaker recovery timeout (seconds) |
| `distributed.lock.redis.url` | string | "redis://localhost:6379" | Redis connection URL |
| `distributed.lock.redis.db` | int | 0 | Redis database number |
| `observability.tracing.enabled` | bool | true | Enable tracing |
| `observability.tracing.exporter` | string | "otlp" | Tracing exporter |
| `observability.metrics.enabled` | bool | true | Enable metrics |

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

### Environment Variables

Environment variables take precedence over config files:

```bash
export W_AGENT_LOGGING_LEVEL=DEBUG
export W_AGENT_CONTAINER_SCAN_PATHS=src,components
export W_AGENT_SANDBOX_ENABLED=true
export W_AGENT_RESILIENCE_RETRY_MAX_ATTEMPTS=5
```

## 📖 Example Project

### Basic Agent Example

Check [examples/basic_agent.py](./examples/basic_agent.py) for a basic Agent implementation example, demonstrating:

- Agent and Service component creation
- Dependency injection
- Config binding and hot reload
- Lifecycle management

### Chat Agent Example

Check the [chat-agent](./chat-agent/) directory for a complete chat agent example project, including:

- Agent implementation
- LLM service integration
- Skills system
- RAG retrieval augmentation
- Redis/MySQL integration
- OpenTelemetry observability
- System health checks

## 👨‍💻 Developer Guide

### Core Concepts

1. **Agent**: Base class for all agents, inherit from `BaseAgent`
2. **Component**: Marked with `@AgentComponent`, `@ServiceComponent`, etc.
3. **Bean**: Component instance managed by the container
4. **Aspect**: For cross-cutting concerns
5. **Event**: For component communication
6. **Lifecycle**: Manages component initialization and destruction
7. **Skill**: Callable function module by Agent

### Development Flow

1. **Create Agent**: Inherit `BaseAgent` and implement `arun` method
2. **Create Service**: Mark service class with `@ServiceComponent`
3. **Configure Dependencies**: Inject dependencies using `@Autowired` and `@Qualifier`
4. **Add Lifecycle**: Mark lifecycle methods with `@PostConstruct` and `@PreDestroy`
5. **Add AOP Aspects**: Add aspects using `@Retry`, `@CircuitBreaker`, etc.
6. **Register Bean**: Register components using `BeanFactory`
7. **Start Application**: Execute `post_construct_all` to initialize components

### Best Practices

1. **Component Design**: Split functionality into small, focused components
2. **Dependency Management**: Use dependency injection instead of hardcoding
3. **Error Handling**: Use AOP aspects for retry and circuit breaker
4. **Configuration Management**: Use dynamic config to avoid hardcoded values
5. **Observability**: Add appropriate logging, metrics, and tracing
6. **Security**: Use sandbox to execute external code
7. **Testing**: Write unit and integration tests for components

### FAQ

#### Dependency Injection Failed
- Ensure components are registered to BeanFactory
- Ensure dependencies are registered and names are correct
- Check if dependency types match

#### Config Not Effective
- Check if config file path is correct
- Check if environment variables override config file
- Check if config key names are correct

#### Sandbox Execution Failed
- Check if Wasm or nsjail is installed correctly
- Check if skill scripts meet sandbox requirements
- Check if resource limits are reasonable

## 📄 Documentation

- [Architecture Documentation](./docs/architecture.md): Detailed framework architecture and design philosophy
- [API Documentation](./docs/api.md): Complete API reference
- [User Guide](./docs/guide.md): Detailed usage tutorial
- [Developer Documentation](./docs/developer.md): Developer-level usage instructions

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
- **Version**: 1.5.0
- **Installation**: `pip install wagent-framework`
- **PyPI URL**: [https://pypi.org/project/wagent-framework/](https://pypi.org/project/wagent-framework/)

## 📝 Changelog

### v1.4.4 (2026-04-26)
- **Framework Optimization**: Improved stability and performance of core features
- **Code Quality**: Enhanced code maintainability and readability
- **Documentation Update**: Provided more detailed framework documentation and core feature demos
- **Developer Guide**: Added developer-level usage instructions
- **Example Project**: Optimized example code and documentation

### v1.4.2 (2026-04-22)
- **Documentation Update**: Provided more detailed framework documentation and core feature demos
- **Developer Guide**: Added developer-level usage instructions
- **Example Project**: Optimized example code and documentation
- **Code Quality**: Enhanced code maintainability and readability

### v1.4.1 (2026-04-22)
- **Fixed Package Structure**: Added missing `__init__.py` files to ensure package can be imported normally
- **Fixed Import Errors**: Corrected import errors in `w_agent/__init__.py`
- **Uploaded to PyPI**: Successfully published to PyPI
- **Updated GitHub**: Synchronized updates to GitHub repository

### v1.4.0 (2026-04-21)
- **Core Features**: AOP, IOC, Sandbox Security, Resilience Patterns, Observability, RAG Integration
- **Configuration Management**: Dynamic config hot reload
- **Event Bus**: Event publish/subscribe support
- **Lifecycle Management**: Component lifecycle support
- **CLI Tool**: Provided command-line tool
