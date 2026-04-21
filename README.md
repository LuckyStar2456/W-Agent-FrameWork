# W-Agent v1.4.0

完整技术架构方案，Python 企业级智能体框架。

## 功能特性

- **架构完整性**：明确模块边界、生命周期顺序、AOP 完整实现（支持AspectJ切点表达式）
- **可用性**：舱壁隔离、分段超时、健康探针、优雅关闭、资源管理
- **安全实现**：Wasm/nsjail 增强（真正的Python到Wasm编译、精细的seccomp策略）、签名校验、敏感信息脱敏、MCP 认证细化
- **性能优化**：并行 AST 扫描、增强的反射缓存、锁续期池
- **生态兼容**：LangChain 双向适配、FastAPI Depends 融合
- **可维护性**：细化异常、迁移工具、测试增强
- **RAG 集成**：向量检索（Redis和内存后端）、相似度搜索
- **依赖注入**：支持构造器注入、字段注入、setter注入，@Autowired和@Qualifier注解解析
- **异常处理**：EventBus重试和死信队列、RetryAspect fallback机制

## 目录结构

```
w_agent/
├── lifecycle/         # 生命周期管理
├── aop/               # 面向切面编程
├── config/            # 配置管理
├── resilience/        # 弹性和容错
├── security/          # 安全相关
├── scanner/           # AST 扫描
├── container/         # 依赖注入容器
├── distributed/       # 分布式功能
├── core/              # 核心功能
├── tools/             # 工具集成
├── deployment/        # 部署相关
├── exceptions/        # 异常体系
├── migration/         # 迁移工具
├── testing/           # 测试框架
├── observability/     # 可观测性
└── skills/            # 技能管理
```

## 安装

```bash
pip install -e .

# 安装可选依赖
pip install -e .[fastapi,langchain]
```

## 快速开始

### 示例 1：创建一个简单的 Agent

```python
from w_agent.core.agent import BaseAgent
from w_agent.container import BeanFactory

class MyAgent(BaseAgent):
    async def arun(self, prompt: str) -> str:
        return f"Hello, {prompt}!"

# 注册 Agent
bean_factory = BeanFactory()
bean_factory.register_bean("my_agent", MyAgent())

# 使用 Agent
agent = bean_factory.get_bean("my_agent")
result = await agent.arun("World")
print(result)  # 输出: Hello, World!
```

### 示例 2：使用配置热更新

```python
from w_agent.config.dynamic_config import DynamicConfigManager

config_manager = DynamicConfigManager()
config_manager.set("api_key", "your-api-key")

class MyService:
    def __init__(self):
        self.api_key = None
        config_manager.bind("api_key", self, "api_key")

    async def on_config_change(self, key, new_value, old_value):
        print(f"Config changed: {key} = {new_value}")

# 绑定配置
service = MyService()
print(service.api_key)  # 输出: your-api-key

# 动态更新配置
await config_manager.update_batch({"api_key": "new-api-key"})
print(service.api_key)  # 输出: new-api-key
```

## 可配置项

### 1. 日志配置

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `logging.level` | string | "INFO" | 日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `logging.format` | string | "json" | 日志格式：json, console |
| `logging.sensitive_keys` | list | ["password", "api_key"] | 需要过滤的敏感信息键名 |
| `logging.output` | string | "stdout" | 日志输出位置：stdout, file |
| `logging.file_path` | string | "w_agent.log" | 日志文件路径（当output为file时） |

### 2. 容器配置

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `container.scan_paths` | list | ["."] | 组件扫描路径 |
| `container.skip_paths` | list | ["__pycache__", ".git"] | 跳过扫描的路径 |
| `container.singleton_injection` | bool | true | 是否启用单例注入 |
| `container.cached_scan` | bool | true | 是否缓存扫描结果 |

### 3. 沙箱配置

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `sandbox.enabled` | bool | true | 是否启用沙箱 |
| `sandbox.type` | string | "wasm" | 沙箱类型：wasm, nsjail |
| `sandbox.wasm.precompiled_path` | string | null | 预编译Wasm模块路径 |
| `sandbox.wasm.memory_limit` | int | 100 | Wasm内存限制（MB） |
| `sandbox.nsjail.path` | string | "nsjail" | nsjail可执行文件路径 |
| `sandbox.nsjail.cpu_limit` | int | 1 | CPU限制（核心数） |
| `sandbox.nsjail.memory_limit` | int | 100 | 内存限制（MB） |

### 4. 弹性模式配置

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `resilience.retry.max_attempts` | int | 3 | 最大重试次数 |
| `resilience.retry.delay` | float | 0.1 | 重试延迟（秒） |
| `resilience.retry.backoff` | float | 2.0 | 退避系数 |
| `resilience.circuit_breaker.failure_threshold` | int | 5 | 失败阈值 |
| `resilience.circuit_breaker.recovery_timeout` | float | 30.0 | 恢复超时（秒） |
| `resilience.bulkhead.max_concurrent` | int | 10 | 最大并发数 |

### 5. 分布式配置

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `distributed.lock.enabled` | bool | true | 是否启用分布式锁 |
| `distributed.lock.redis.url` | string | "redis://localhost:6379" | Redis连接URL |
| `distributed.lock.redis.db` | int | 0 | Redis数据库编号 |
| `distributed.lock.ttl` | int | 30 | 锁TTL（秒） |
| `distributed.lock.renew_interval` | int | 10 | 锁续期间隔（秒） |

### 6. 可观测性配置

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `observability.tracing.enabled` | bool | false | 是否启用追踪 |
| `observability.tracing.exporter` | string | "otlp" | 追踪导出器：otlp, jaeger |
| `observability.tracing.endpoint` | string | "http://localhost:4317" | 追踪端点 |
| `observability.metrics.enabled` | bool | false | 是否启用指标 |
| `observability.metrics.exporter` | string | "prometheus" | 指标导出器：prometheus |
| `observability.metrics.port` | int | 8000 | 指标端口 |

### 7. 部署配置

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `deployment.mode` | string | "standard" | 部署模式：standard, serverless |
| `deployment.serverless.snapshot_path` | string | "./bean_factory.snapshot" | 快照路径 |
| `deployment.serverless.request_timeout` | int | 30 | 请求超时（秒） |
| `deployment.serverless.memory_limit` | int | 512 | 内存限制（MB） |

### 8. 技能系统配置

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `skills.path` | string | "./skills" | 技能目录路径 |
| `skills.load_level` | int | 3 | 技能加载级别：1(元数据), 2(指令), 3(完整) |
| `skills.timeout` | int | 30 | 技能执行超时（秒） |
| `skills.max_output_size` | int | 1024 | 最大输出大小（KB） |

## 可用注解

### 1. 组件注解

| 注解 | 描述 | 示例 |
|------|------|------|
| `@AgentComponent` | 标记Agent组件 | `@AgentComponent(name="my_agent")` |
| `@ServiceComponent` | 标记Service组件 | `@ServiceComponent(name="my_service")` |
| `@ToolComponent` | 标记Tool组件 | `@ToolComponent(name="my_tool", description="My tool")` |
| `@RepositoryComponent` | 标记Repository组件 | `@RepositoryComponent(name="my_repository")` |
| `@ControllerComponent` | 标记Controller组件 | `@ControllerComponent(name="my_controller")` |

### 2. 生命周期注解

| 注解 | 描述 | 示例 |
|------|------|------|
| `@PostConstruct` | 初始化后执行 | `@PostConstruct(order=1)` |
| `@PreDestroy` | 销毁前执行 | `@PreDestroy(order=1)` |

### 3. 配置注解

| 注解 | 描述 | 示例 |
|------|------|------|
| `@Value` | 配置值注入 | `@Value(key="api_key", default="default")` |
| `@Autowired` | 自动注入 | `@Autowired(name="my_service")` |
| `@Qualifier` | 指定Bean名称 | `@Qualifier(name="my_service")` |

### 4. 弹性注解

| 注解 | 描述 | 示例 |
|------|------|------|
| `@Retry` | 重试装饰器 | `@Retry(max_attempts=3, delay=0.1)` |
| `@CircuitBreaker` | 断路器装饰器 | `@CircuitBreaker(failure_threshold=5)` |

## 配置方式

### 1. 配置文件
在项目根目录创建 `config.json` 文件：

```json
{
  "logging": {
    "level": "INFO",
    "format": "json"
  },
  "container": {
    "scan_paths": ["src"],
    "skip_paths": ["__pycache__", ".git", "tests"]
  }
}
```

### 2. 环境变量
使用 `W_AGENT_` 前缀的环境变量：

```bash
export W_AGENT_LOGGING_LEVEL=DEBUG
export W_AGENT_CONTAINER_SCAN_PATHS=src,components
```

### 3. 代码配置
通过 `DynamicConfigManager` 动态配置：

```python
from w_agent.config.dynamic_config import DynamicConfigManager

config_manager = DynamicConfigManager()
config_manager.set("logging.level", "DEBUG")
config_manager.set("container.scan_paths", ["src", "components"])
```

## 文档

- [架构设计](./W-Agent-v1.4.0.txt)
- [API 文档](./docs/api.md)
- [使用指南](./docs/guide.md)

## 许可证

MIT
