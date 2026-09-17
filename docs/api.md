# W-Agent API 状态与规划

[English](./api.en.md) | 简体中文

本文区分稳定版 1.5.2、当前 `2.0.0a1` 微内核/模型 API 与后续计划协议。标记 `Planned` 的协议用于设计评审，当前不能导入。

## 1. 当前顶层 API

状态：`Implemented`。`w_agent.__init__` 当前导出以下主要类型：

| 分组 | API |
|---|---|
| Agent | `BaseAgent`、`LegacyAgentAdapter`、`AgentDefinition`、`AgentLoop`、`ReactAgentLoop`、`RunContext`、`RunEvent`、`RunResult`、`RunStore`、`JsonlRunStore` |
| Session | `SessionManager`、`SessionRecord`、`SessionRunRecord`、`InMemorySessionStore`、`JsonSessionStore` |
| 本地装配 | `LocalRuntimeConfig`、`LocalAgentRuntime`、`load_local_runtime_config`、`assemble_local_runtime` |
| 容器 | `BeanFactory`、`BeanDefinition`、`Scope` |
| 配置 | `DynamicConfigManager` |
| 装饰器 | `AgentComponent`、`ServiceComponent`、`ToolComponent`、`Component`、`Autowired`、`Qualifier` |
| 生命周期 | `PostConstruct`、`PreDestroy`、`LifecycleManager`、`GracefulShutdownManager` |
| 事件 | `EventBus`、`Event`、`ConfigChangedEvent` |
| AOP/弹性 | `Retry`、`CircuitBreaker`、`AspectJPointcut`、Advice、`ProxyFactory`、`ResilienceManager` |
| 观测 | `global_tracer`、`CompositeHealthIndicator`、`HealthIndicator`、`LLMHealthIndicator` |
| 分布式 | `RedisDistributedLock`、`LockRenewalPool` |
| 技能/沙箱 | `Skill`、`WasmSkillSandbox`、`NsJailSkillSandbox`、`SandboxProvider`、`DockerSandboxProvider`、`UnsafeLocalSandboxProvider` |
| 工具/扫描 | `ToolRegistry`、`ToolExecutor`、`ToolCall`、`ToolResult`、`python_tool`、`LangChainToolAdapter`、`ParallelASTScanner`、`Doctor` |
| 微内核 | `PluginManager`、`Registry`、`ScopePath`、`EventDispatcher` 等 |
| 模型 | `ModelProvider`、`ModelRegistry`、`ModelRequest`、`StreamEvent`、`OpenAICompatibleProvider`、`HttpModelProvider`、厂商映射与模板等 |
| 路由/调用/探测 | `ModelRouter`、`ModelExecutor`、`InvocationPolicy`、`YamlRoutingPolicy`、`EndpointProbe`、`ModelProviderProbe` 等 |
| Workflow | `WorkflowEngineProtocol`、`LocalWorkflowEngine`、三种 Definition、`WorkflowStore`、`JsonlWorkflowStore` 等 |

当前准确的 Agent 协议只有：

```python
class BaseAgent:
    async def arun(self, prompt: str) -> str:
        raise NotImplementedError
```

`BaseAgent` 尚未接入新的模型协议；新的 ReAct/工具和 Workflow 运行时独立提供。ReAct 审批 Checkpoint、Workflow 节点 Checkpoint，以及本地持久化 Session 生命周期/跨 Run 文本上下文已经实现；通用多模态与工具事件回放仍未接入。

严格本地 JSON 配置可通过 `load_local_runtime_config()` 和 `assemble_local_runtime()` 装配内置 Provider 模板、单 Provider 路由、受限调用策略、ReAct Loop、RunStore 与 SessionStore。配置只接受 `api_key_env` 凭据引用且不自动加载工具；CLI/TUI 调用入口要求逐次显式授权。详见[本地配置化 Runtime](./local-runtime.md)。

## 2. 下一代导出策略

状态：`Implemented` / `Planned`。微内核、模型、工具、`AgentLoop` 与 `WorkflowEngineProtocol` 已经直接导出；`Application` 聚合门面仍为计划 API。

下一代 API 直接从 `w_agent` 导出，不创建 `w_agent.v2`：

```python
from w_agent import AgentLoop, LocalWorkflowEngine, ModelProvider
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

`StreamEvent` 已覆盖内容块开始/增量/结束、文本/工具调用增量、Usage、标准错误和 Finish。`TokenUsage` 统一输入、输出和缓存输入 Token，并提供不重复计算缓存子集的 `total_tokens`；`ModelResponse.usage_reported` 区分 Provider 未上报与真实零值。`collect_stream()` 校验块顺序和明确终止事件。Provider 必须完整报告不支持的标准字段，不得静默忽略。

`OpenAICompatibleProvider` 已实现 `/models` 和流式 `/chat/completions`，其 `OpenAICompatibleTransport` 可以替换。通用 `HttpModelProvider` 公开 `HttpRequest`、`HttpStreamFrame`、`HttpProviderMapping`、`HttpStreamDecoder` 与 `HttpProviderTransport`；默认 `HttpxProviderTransport` 支持 JSON、SSE 和 NDJSON。

`AnthropicMessagesMapping`、`GeminiGenerateContentMapping`、`OllamaChatMapping` 与 `QwenDashScopeMapping` 为原生协议映射。`ProviderTemplateRegistry` 提供 Anthropic、Gemini、Ollama、Qwen-native、DeepSeek、GLM、Qwen-compatible 和 Turbo AI/SIAM.AI 模板。专用 OpenAI Responses 与 vLLM 差异适配仍为 `Planned`。默认 HTTPX 实现位于 `models` 可选依赖。

## 5. 路由协议

状态：`Implemented`（Phase 2A 策略与决策、Phase 2B 收集式与逐事件透传调用执行）。

```python
class RoutingPolicy(Protocol):
    def select(self, request: RouteRequest) -> RouteDecision: ...
```

`RouteDecision` 包含候选模型、过滤原因、得分、最终路由、故障转移列表和策略版本，但不保存提示词明文。`WeightedRoutingPolicy` 与使用 `yaml.safe_load` 的 `YamlRoutingPolicy` 产生同一类型。`ModelRouter` 获取当前模型目录并应用策略，仍不直接执行调用。

`ModelExecutor.invoke()` 消费决定，通过 `InvocationPolicy` 控制逐尝试超时、重试次数、路由数和确定性退避，并返回 `ModelInvocationResult`。`ModelExecutor.stream()` 返回单次消费的 `ModelStreamExecution`，使用 `ModelStreamValidator` 实时校验和透传事件；首个事件可见前允许按策略重试/故障转移，之后禁止静默重放。默认只调用一次；提高上限会产生额外可能计费的请求。`AttemptRecord` 记录已输出事件数、Provider 明确报告的 TokenUsage 和完整性标记，但不包含 Prompt 或凭据。执行失败抛出携带决定和全部已完成尝试的 `ModelInvocationError`。

## 6. 探测协议

状态：`Implemented`（Phase 2A 基础）。

- `EndpointProbe.probe()`：L1 URL、DNS、TCP、TLS 和 HTTP 可达性嗅探，目标标识会移除凭据、查询串和片段。
- `ModelProviderProbe.probe()`：L2/L3 Provider 访问和模型目录检查。
- `ProbeMode.ACTIVE`：只有 `allow_active=True` 时才执行 L4/L5 最小生成与流协议检查。
- `ProbeMode.CAPABILITY`：L6/L7 当前只报告 Provider 声明，明确标记 `SKIPPED`，不会伪装成主动验证。
- `ProbeCache` 与 `PeriodicProbeService`：为手动和周期探测提供公共构件。
- `ModelRegistrationProbeService` 与 `ProbeHealthBridge`：提供显式的注册安全探测和外部路由健康映射；直接 `ModelRegistry.register()` 不执行 I/O。无凭据 L1 CLI/TUI 入口已实现，配置化 Provider 主动探测仍为 `Planned`。

## 7. Agent 协议

状态：`Implemented`（Run 协议与单 Agent ReAct 基础）。

```python
class AgentLoop(Protocol):
    async def run(
        self, definition: AgentDefinition, context: RunContext
    ) -> RunResult: ...

    def stream(
        self, definition: AgentDefinition, context: RunContext
    ) -> AgentExecution: ...
```

`ReactAgentLoop` 是只使用公开模型与工具协议的普通实现，可以被同协议 Loop 整体替换。它执行有界模型/工具循环，通过 `RunStore` 在事件可见前追加记录，并在需要审批时返回 `pending_tool_call` 与 `checkpoint_id`。`TokenBudget` 提供 Run 级累计输入/输出/总量限制；`TOKEN_USAGE`、`RunResult.usage`、`RunResult.attempts` 和 `usage_complete` 提供可见计量，Checkpoint 在审批恢复间保留累计值与尝试账本。`SessionManager` 与内存/JSON Store 已提供本地生命周期、跨 Run 文本上下文和审批恢复协调。`customer_support_agent()` 和 `coding_agent()` 只构建可完全覆盖的普通 Definition，不绑定模型、工具或权限。多模态/工具事件通用回放和文本逐 Token 事件仍为 `Planned`。详见[Agent Runtime](./agents.md)与[Session](./sessions.md)。

## 8. Workflow 协议

状态：`Implemented`（Phase 4 本地顺序执行与节点边界恢复）。

```python
class WorkflowEngineProtocol(Protocol):
    async def start(
        self, definition: WorkflowDefinition, context: WorkflowContext
    ) -> WorkflowResult: ...


    async def resume(
        self,
        definition: WorkflowDefinition,
        run_id: str,
        *,
        cancellation: CancellationToken | None = None,
    ) -> WorkflowResult: ...
```

`DagWorkflowDefinition`、`StateGraphDefinition` 和 `PythonWorkflowDefinition` 使用相同引擎，并可通过共享微内核上的 `WorkflowRegistry` 按版本和 Scope 注册。节点返回 `WorkflowNodeResult` 以更新状态、选择下一节点或请求暂停。`LocalWorkflowEngine` 支持边界取消，并通过可替换 `WorkflowStore` 写入事件和检查点；内置内存与 JSONL 实现。恢复只承诺已完成节点边界，不恢复任意 Python 指令栈。不确定节点执行保留 `RESUMING` 并拒绝自动重放。`agent_workflow_node()` 与 `workflow_start_tool()` / `workflow_resume_tool()` 已提供双向公共协议适配；并行 DAG、自动级联恢复和嵌套 Workflow 尚未实现。详见[Workflow 与节点恢复](./workflows.md)。

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

`ToolRegistry` 在统一注册表中按版本和 Scope 注册 `ToolBinding`。`ToolExecutor.execute()` 依次解析、校验、执行策略、处理超时/取消并写入审计。默认 `PermissionPolicy` 检查本地授予的权限，`SideEffectApprovalPolicy` 对写入、破坏性和外部副作用要求调用 ID 逐次批准。工具 Definition 不持有执行策略，默认执行器不重试。`python_tool()`、`http_tool()`、`command_tool()`、`mcp_tool()` 和 `sandbox_command_tool()` 已实现；MCP stdio/HTTP 会话客户端和发现仍为 `Planned`。详见[工具注册、策略与执行](./tools.md)。

## 10. 沙箱协议

状态：`Implemented`（统一本地协议、Docker/OCI 与显式授权本地开发模式）。

```python
class SandboxProvider(Protocol):
    async def open(
        self,
        spec: SandboxSpec,
        *,
        cancellation: CancellationToken | None = None,
    ) -> SandboxHandle: ...
```

`SandboxHandle.execute()` 接收无 Shell 的 `SandboxCommand` 并返回 `SandboxResult`，`close()` 收敛容器或本地 Handle。`DockerSandboxProvider` 默认断网、只读根文件系统、drop capabilities、禁止提权、限制 CPU/内存/PID，并在关闭或不确定执行错误后删除容器。`UnsafeLocalSandboxProvider` 不是安全沙箱，只接受 `UnsafeLocalAuthorization.grant(..., acknowledge_host_access=True)` 产生的运行时对象；它不会成为 Docker 失败后的回退。Provider 通过 `SandboxRegistry` 进入共享注册表。nsjail/Wasm 的新协议适配仍为 `Planned`，Remote Sandbox 为 `Reserved`。详见[沙箱与本地执行](./sandbox.md)。

## 11. 工程装配协议

状态：编码、解码、安全预览和本地版本库为 `Implemented`；依赖安装与插件加载确认器为 `Planned`。

```python
code = encode_composition(manifest)
manifest = decode_composition(code)
preview = inspect_composition(code)
CompositionStore(".wagent/compositions").save(manifest, alias="stable")
```

解码与预览不访问网络、不安装依赖、不加载插件、不执行代码。Manifest 拒绝秘密值、绝对本地路径、内嵌代码和 `UnsafeLocalSandbox` 授权；Codec 设有压缩与解压大小边界。用户确认后的独立安装与加载操作仍未实现。

## 12. 兼容接口

状态：`Implemented`（`LegacyAgentAdapter`）/ `Deprecated`（1.x 抽象）。

`LegacyAgentAdapter` 将 1.x `BaseAgent.arun()` 包装为 Workflow 节点。兼容层只做显式文本参数和结果转换，不模拟不存在的流式、工具、Token 或 Checkpoint 能力；非文本输入必须由调用方提供 `prompt_mapper`。
