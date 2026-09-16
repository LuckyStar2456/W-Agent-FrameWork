# W-Agent API 状态与规划

[English](./api.en.md) | 简体中文

本文区分当前 1.5.2 公共 API 与下一代计划协议。计划协议用于设计评审，当前不能导入。

## 1. 当前顶层 API

状态：`Implemented`。`w_agent.__init__` 当前导出以下主要类型：

| 分组 | API |
|---|---|
| Agent | `BaseAgent` |
| 容器 | `BeanFactory`、`BeanDefinition`、`Scope` |
| 配置 | `DynamicConfigManager` |
| 装饰器 | `AgentComponent`、`ServiceComponent`、`ToolComponent`、`Component`、`Autowired`、`Qualifier` |
| 生命周期 | `PostConstruct`、`PreDestroy`、`LifecycleManager`、`GracefulShutdownManager` |
| 事件 | `EventBus`、`Event`、`ConfigChangedEvent` |
| AOP/弹性 | `Retry`、`CircuitBreaker`、`AspectJPointcut`、Advice、`ProxyFactory`、`ResilienceManager` |
| 观测 | `global_tracer`、`CompositeHealthIndicator`、`HealthIndicator`、`LLMHealthIndicator` |
| 分布式 | `RedisDistributedLock`、`LockRenewalPool` |
| 技能/沙箱 | `Skill`、`WasmSkillSandbox`、`NsJailSkillSandbox` |
| 工具/扫描 | `LangChainToolAdapter`、`ParallelASTScanner`、`Doctor` |

当前准确的 Agent 协议只有：

```python
class BaseAgent:
    async def arun(self, prompt: str) -> str:
        raise NotImplementedError
```

它没有统一模型、工具、Session、Checkpoint 或流式事件协议。

## 2. 下一代导出策略

状态：`Planned`。

下一代 API 直接从 `w_agent` 导出，不创建 `w_agent.v2`：

```python
from w_agent import Application, AgentLoop, ModelProvider, WorkflowEngine
```

在迁移完成前，顶层导出必须避免新旧同名对象产生模糊行为。旧对象通过兼容模块或适配器保留。

## 3. 微内核协议

状态：`Planned`。

```python
class Plugin(Protocol):
    spec: PluginSpec

    async def load(self, context: PluginContext) -> None: ...
    async def unload(self) -> None: ...


class Registry(Protocol):
    def register(self, contribution: Contribution) -> Registration: ...
    def resolve(self, capability: CapabilityKey, scope: ScopePath) -> object: ...
```

`Registration.dispose()` 必须幂等。加载失败时，生命周期管理器撤销该次加载已经产生的所有注册。

## 4. 模型协议

状态：`Planned`。

```python
class ModelProvider(Protocol):
    async def resolve(self, model: str) -> ModelDescriptor: ...

    def stream(
        self,
        request: ModelRequest,
        *,
        signal: CancelSignal,
    ) -> AsyncIterator[StreamEvent]: ...
```

`StreamEvent` 计划覆盖内容块开始/增量/结束、工具调用增量、Usage、错误和 Finish。Provider 必须完整报告不支持的标准字段，不得静默忽略。

## 5. 路由协议

状态：`Planned`。

```python
class RoutingPolicy(Protocol):
    async def route(self, request: RouteRequest) -> RouteDecision: ...
```

`RouteDecision` 包含候选模型、过滤原因、得分、最终路由、故障转移列表和策略版本。Python 策略与 YAML 规则产生同一类型。

## 6. Agent 协议

状态：`Planned`。

```python
class AgentLoop(Protocol):
    async def run(self, context: RunContext) -> RunResult: ...
    def stream(self, context: RunContext) -> AsyncIterator[RunEvent]: ...
```

默认 ReAct 是普通 Provider，可以被同协议的其他 Loop 替换。同步 `invoke()` 只作为边界包装器。

## 7. Workflow 协议

状态：`Planned`。

```python
class WorkflowEngine(Protocol):
    async def start(self, definition: WorkflowDefinition, context: RunContext) -> WorkflowHandle: ...


class WorkflowHandle(Protocol):
    async def pause(self) -> Checkpoint: ...
    async def resume(self) -> RunResult: ...
    async def cancel(self) -> None: ...
```

首版只承诺节点边界和显式 `checkpoint()` 的恢复。

## 8. 工具协议

状态：`Planned`。

```python
class ToolExecutor(Protocol):
    async def execute(self, call: ToolCall, context: RunContext) -> ToolResult: ...
```

工具 Definition 不持有执行策略；权限、审批、缓存、超时、审计和沙箱通过执行 Pipeline 组合。

## 9. 沙箱协议

状态：`Planned`。

```python
class SandboxProvider(Protocol):
    async def create(self, request: SandboxRequest) -> SandboxHandle: ...
```

首版计划提供 Docker/OCI 和显式授权的 `UnsafeLocalSandbox`。nsjail/Wasm 通过适配器接入同一能力定义，Remote Sandbox 为 `Reserved`。

## 10. 工程装配协议

状态：`Planned`。

```python
class CompositionCodec(Protocol):
    def encode(self, manifest: CompositionManifest) -> str: ...
    def decode(self, code: str) -> CompositionPreview: ...
```

解码只产生预览，不安装依赖、不加载插件、不执行代码。用户确认后由独立的安装与加载操作继续。

## 11. 兼容接口

状态：`Planned` / `Deprecated`。

`LegacyAgentAdapter` 将 1.x `BaseAgent.arun()` 包装为下一代 Agent 节点。兼容层只做参数和结果转换，不模拟不存在的流式、工具或 Checkpoint 能力。
