# W-Agent API 状态与规划

[English](./api.en.md) | 简体中文

本文区分稳定版 1.5.2、当前 `2.0.0a1` 微内核/模型 API 与后续计划协议。标记 `Planned` 的协议用于设计评审，当前不能导入。

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
| 工具/扫描 | `ToolRegistry`、`ToolExecutor`、`ToolCall`、`ToolResult`、`python_tool`、`LangChainToolAdapter`、`ParallelASTScanner`、`Doctor` |
| 微内核 | `PluginManager`、`Registry`、`ScopePath`、`EventDispatcher` 等 |
| 模型 | `ModelProvider`、`ModelRegistry`、`ModelRequest`、`StreamEvent`、`OpenAICompatibleProvider`、`HttpModelProvider`、厂商映射与模板等 |
| 路由/调用/探测 | `ModelRouter`、`ModelExecutor`、`InvocationPolicy`、`YamlRoutingPolicy`、`EndpointProbe`、`ModelProviderProbe` 等 |

当前准确的 Agent 协议只有：

```python
class BaseAgent:
    async def arun(self, prompt: str) -> str:
        raise NotImplementedError
```

`BaseAgent` 尚未接入新的模型协议；统一工具执行基础已经独立提供，但 Session、Agent Loop 和 Checkpoint 运行时仍未接入。

## 2. 下一代导出策略

状态：`Implemented` / `Planned`。微内核和模型基础已经直接导出；示例中的 `Application`、`AgentLoop` 与 `WorkflowEngine` 仍为计划 API。

下一代 API 直接从 `w_agent` 导出，不创建 `w_agent.v2`：

```python
from w_agent import Application, AgentLoop, ModelProvider, WorkflowEngine
```

在迁移完成前，顶层导出必须避免新旧同名对象产生模糊行为。旧对象通过兼容模块或适配器保留。

## 3. 微内核协议

状态：`Implemented`（`2.0.0a1`）。

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

当前还导出 `PluginManager`、`PluginContext`、`FunctionPlugin`、`CapabilityDeclaration`、`CapabilityRequirement`、`Contribution`、`RegistryView`、`ScopePath`、`EventDispatcher`、YAML 引用加载和 entry point 发现 API。

## 4. 模型协议

状态：`Implemented`（Phase 2A）。

```python
class ModelProvider(Protocol):
    async def list_models(self) -> tuple[ModelDescriptor, ...]: ...
    async def resolve(self, model: str) -> ModelDescriptor: ...

    def stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[StreamEvent]: ...
```

`StreamEvent` 已覆盖内容块开始/增量/结束、文本/工具调用增量、Usage、标准错误和 Finish。`collect_stream()` 校验块顺序和明确终止事件。Provider 必须完整报告不支持的标准字段，不得静默忽略。

`OpenAICompatibleProvider` 已实现 `/models` 和流式 `/chat/completions`，其 `OpenAICompatibleTransport` 可以替换。通用 `HttpModelProvider` 公开 `HttpRequest`、`HttpStreamFrame`、`HttpProviderMapping`、`HttpStreamDecoder` 与 `HttpProviderTransport`；默认 `HttpxProviderTransport` 支持 JSON、SSE 和 NDJSON。

`AnthropicMessagesMapping`、`GeminiGenerateContentMapping`、`OllamaChatMapping` 与 `QwenDashScopeMapping` 为原生协议映射。`ProviderTemplateRegistry` 提供 Anthropic、Gemini、Ollama、Qwen-native、DeepSeek、GLM、Qwen-compatible 和 Turbo AI/SIAM.AI 模板。专用 OpenAI Responses 与 vLLM 差异适配仍为 `Planned`。默认 HTTPX 实现位于 `models` 可选依赖。

## 5. 路由协议

状态：`Implemented`（Phase 2A 策略与决策、Phase 2B 收集式与逐事件透传调用执行）。

```python
class RoutingPolicy(Protocol):
    def select(self, request: RouteRequest) -> RouteDecision: ...
```

`RouteDecision` 包含候选模型、过滤原因、得分、最终路由、故障转移列表和策略版本，但不保存提示词明文。`WeightedRoutingPolicy` 与使用 `yaml.safe_load` 的 `YamlRoutingPolicy` 产生同一类型。`ModelRouter` 获取当前模型目录并应用策略，仍不直接执行调用。

`ModelExecutor.invoke()` 消费决定，通过 `InvocationPolicy` 控制逐尝试超时、重试次数、路由数和确定性退避，并返回 `ModelInvocationResult`。`ModelExecutor.stream()` 返回单次消费的 `ModelStreamExecution`，使用 `ModelStreamValidator` 实时校验和透传事件；首个事件可见前允许按策略重试/故障转移，之后禁止静默重放。默认只调用一次；提高上限会产生额外可能计费的请求。`AttemptRecord` 记录已输出事件数但不包含 Prompt 或凭据。执行失败抛出携带决定和全部已完成尝试的 `ModelInvocationError`。

## 6. 探测协议

状态：`Implemented`（Phase 2A 基础）。

- `EndpointProbe.probe()`：L1 URL、DNS、TCP、TLS 和 HTTP 可达性嗅探，目标标识会移除凭据、查询串和片段。
- `ModelProviderProbe.probe()`：L2/L3 Provider 访问和模型目录检查。
- `ProbeMode.ACTIVE`：只有 `allow_active=True` 时才执行 L4/L5 最小生成与流协议检查。
- `ProbeMode.CAPABILITY`：L6/L7 当前只报告 Provider 声明，明确标记 `SKIPPED`，不会伪装成主动验证。
- `ProbeCache` 与 `PeriodicProbeService`：为手动和周期探测提供公共构件。
- `ModelRegistrationProbeService` 与 `ProbeHealthBridge`：提供显式的注册安全探测和外部路由健康映射；直接 `ModelRegistry.register()` 不执行 I/O。CLI/TUI 入口仍为 `Planned`。

## 7. Agent 协议

状态：`Planned`。

```python
class AgentLoop(Protocol):
    async def run(self, context: RunContext) -> RunResult: ...
    def stream(self, context: RunContext) -> AsyncIterator[RunEvent]: ...
```

默认 ReAct 是普通 Provider，可以被同协议的其他 Loop 替换。同步 `invoke()` 只作为边界包装器。

## 8. Workflow 协议

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

## 9. 工具协议

状态：`Implemented`（Phase 3 工具执行基础）。

```python
class ToolPolicy(Protocol):
    async def evaluate(
        self,
        binding: ToolBinding,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolPolicyDecision: ...
```

`ToolRegistry` 在统一注册表中按版本和 Scope 注册 `ToolBinding`。`ToolExecutor.execute()` 依次解析、校验、执行策略、处理超时/取消并写入审计。默认 `PermissionPolicy` 检查本地授予的权限，`SideEffectApprovalPolicy` 对写入、破坏性和外部副作用要求调用 ID 逐次批准。工具 Definition 不持有执行策略，默认执行器不重试。`python_tool()` 是已实现的简单模板；HTTP/MCP/命令行适配与沙箱绑定仍为 `Planned`。详见[工具注册、策略与执行](./tools.md)。

## 10. 沙箱协议

状态：`Planned`。

```python
class SandboxProvider(Protocol):
    async def create(self, request: SandboxRequest) -> SandboxHandle: ...
```

首版计划提供 Docker/OCI 和显式授权的 `UnsafeLocalSandbox`。nsjail/Wasm 通过适配器接入同一能力定义，Remote Sandbox 为 `Reserved`。

## 11. 工程装配协议

状态：`Planned`。

```python
class CompositionCodec(Protocol):
    def encode(self, manifest: CompositionManifest) -> str: ...
    def decode(self, code: str) -> CompositionPreview: ...
```

解码只产生预览，不安装依赖、不加载插件、不执行代码。用户确认后由独立的安装与加载操作继续。

## 12. 兼容接口

状态：`Planned` / `Deprecated`。

`LegacyAgentAdapter` 将 1.x `BaseAgent.arun()` 包装为下一代 Agent 节点。兼容层只做参数和结果转换，不模拟不存在的流式、工具或 Checkpoint 能力。
