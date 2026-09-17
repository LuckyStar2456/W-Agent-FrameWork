# W-Agent API status and plan

English | [简体中文](./api.md)

This document separates stable 1.5.2 APIs, the current `2.0.0a1` microkernel/model APIs, and later planned protocols. Protocols marked `Planned` are design material and cannot be imported today.

## 1. Current top-level API

Status: `Implemented`. `w_agent.__init__` currently exports these primary types:

| Group | API |
|---|---|
| Agent | `BaseAgent`, `AgentDefinition`, `AgentLoop`, `ReactAgentLoop`, `RunContext`, `RunEvent`, `RunResult` |
| Container | `BeanFactory`, `BeanDefinition`, `Scope` |
| Configuration | `DynamicConfigManager` |
| Decorators | `AgentComponent`, `ServiceComponent`, `ToolComponent`, `Component`, `Autowired`, `Qualifier` |
| Lifecycle | `PostConstruct`, `PreDestroy`, `LifecycleManager`, `GracefulShutdownManager` |
| Events | `EventBus`, `Event`, `ConfigChangedEvent` |
| AOP/resilience | `Retry`, `CircuitBreaker`, `AspectJPointcut`, advice types, `ProxyFactory`, `ResilienceManager` |
| Observability | `global_tracer`, `CompositeHealthIndicator`, `HealthIndicator`, `LLMHealthIndicator` |
| Distributed | `RedisDistributedLock`, `LockRenewalPool` |
| Skills/sandbox | `Skill`, `WasmSkillSandbox`, `NsJailSkillSandbox` |
| Tools/scanning | `ToolRegistry`, `ToolExecutor`, `ToolCall`, `ToolResult`, `python_tool`, `LangChainToolAdapter`, `ParallelASTScanner`, `Doctor` |
| Microkernel | `PluginManager`, `Registry`, `ScopePath`, `EventDispatcher`, and related types |
| Models | `ModelProvider`, `ModelRegistry`, `ModelRequest`, `StreamEvent`, `OpenAICompatibleProvider`, `HttpModelProvider`, vendor mappings/templates, and related types |
| Routing/invocation/probing | `ModelRouter`, `ModelExecutor`, `InvocationPolicy`, `YamlRoutingPolicy`, `EndpointProbe`, `ModelProviderProbe`, and related types |

The only accurate current agent protocol is:

```python
class BaseAgent:
    async def arun(self, prompt: str) -> str:
        raise NotImplementedError
```

`BaseAgent` is not yet integrated with the new model protocol. The new ReAct/tool runtime is available independently, while durable sessions and checkpoints are not yet connected.

## 2. Next-generation export strategy

Status: `Implemented` / `Planned`. Microkernel, model, tool, and `AgentLoop` foundations are exported directly; `Application` and `WorkflowEngine` in the example remain planned.

Next-generation APIs are exported directly from `w_agent`; there is no `w_agent.v2` namespace:

```python
from w_agent import Application, AgentLoop, ModelProvider, WorkflowEngine
```

Until migration is complete, top-level exports avoid ambiguous behavior between old and new objects with the same name. Old objects remain through a compatibility module or adapter.

## 3. Microkernel protocols

Status: `Implemented` in `2.0.0a1`.

```python
class Plugin(Protocol):
    spec: PluginSpec

    async def load(self, context: PluginContext) -> None: ...
    async def unload(self) -> None: ...


class Registry(Protocol):
    def register(self, contribution: Contribution) -> Registration: ...
    def resolve(self, capability: CapabilityKey, scope: ScopePath) -> object: ...
```

`Registration.dispose()` is idempotent. When loading fails, the lifecycle manager removes every registration produced by that load attempt.

Current exports also include `PluginManager`, `PluginContext`, `FunctionPlugin`, `CapabilityDeclaration`, `CapabilityRequirement`, `Contribution`, `RegistryView`, `ScopePath`, `EventDispatcher`, YAML-reference loading, and entry-point discovery APIs.

## 4. Model protocols

Status: `Implemented` in Phase 2A.

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

`StreamEvent` covers content-block start/delta/end, text/tool-call deltas, usage, normalized errors, and finish. `collect_stream()` validates block ordering and an explicit terminal event. A provider reports unsupported standard fields and never silently ignores them.

`OpenAICompatibleProvider` implements `/models` and streaming `/chat/completions` with a replaceable `OpenAICompatibleTransport`. Generic `HttpModelProvider` exposes `HttpRequest`, `HttpStreamFrame`, `HttpProviderMapping`, `HttpStreamDecoder`, and `HttpProviderTransport`; the default `HttpxProviderTransport` supports JSON, SSE, and NDJSON.

`AnthropicMessagesMapping`, `GeminiGenerateContentMapping`, `OllamaChatMapping`, and `QwenDashScopeMapping` implement native protocols. `ProviderTemplateRegistry` includes Anthropic, Gemini, Ollama, Qwen-native, DeepSeek, GLM, Qwen-compatible, and Turbo AI/SIAM.AI templates. Dedicated OpenAI Responses and vLLM differences remain `Planned`. Default HTTPX implementations are in the `models` extra.

## 5. Routing protocol

Status: `Implemented` for Phase 2A policy/decisions and Phase 2B collecting/event-pass-through invocation.

```python
class RoutingPolicy(Protocol):
    def select(self, request: RouteRequest) -> RouteDecision: ...
```

`RouteDecision` contains candidates, rejection reasons, scores, the selected route, fallback routes, and the policy version, but no prompt plaintext. `WeightedRoutingPolicy` and the `yaml.safe_load`-based `YamlRoutingPolicy` produce the same type. `ModelRouter` reads the current model catalog and applies a policy; it still does not execute providers directly.

`ModelExecutor.invoke()` consumes a decision and returns `ModelInvocationResult`; `InvocationPolicy` bounds per-attempt timeout, retry count, route count, and deterministic backoff. `ModelExecutor.stream()` returns a single-use `ModelStreamExecution` that validates and yields events with `ModelStreamValidator`; policy-driven retry/failover is allowed before the first visible event and silent replay is prohibited afterward. The default performs one call only; higher limits may create extra billable requests. `AttemptRecord` records emitted-event count but no prompt or credential. A final failure raises `ModelInvocationError` with the decision and every completed attempt.

## 6. Probe protocols

Status: `Implemented` as a Phase 2A foundation.

- `EndpointProbe.probe()`: L1 URL, DNS, TCP, TLS, and HTTP reachability sniffing; the target identifier strips credentials, query data, and fragments.
- `ModelProviderProbe.probe()`: L2/L3 provider access and model-catalog checks.
- `ProbeMode.ACTIVE`: runs an L4/L5 minimal generation and stream-protocol check only with `allow_active=True`.
- `ProbeMode.CAPABILITY`: currently reports L6/L7 declarations as `SKIPPED`; it never presents declarations as active verification.
- `ProbeCache` and `PeriodicProbeService`: shared building blocks for manual and periodic probes.
- `ModelRegistrationProbeService` and `ProbeHealthBridge`: explicit register-and-safe-probe wiring plus external routing-health projection; direct `ModelRegistry.register()` performs no I/O. CLI/TUI entry points remain `Planned`.

## 7. Agent protocol

Status: `Implemented` for the run contracts and single-agent ReAct foundation.

```python
class AgentLoop(Protocol):
    async def run(
        self, definition: AgentDefinition, context: RunContext
    ) -> RunResult: ...

    def stream(
        self, definition: AgentDefinition, context: RunContext
    ) -> AgentExecution: ...
```

`ReactAgentLoop` is an ordinary implementation built only on public model/tool contracts and can be replaced as a whole through the same loop protocol. It runs a bounded model/tool cycle, exposes a single-use in-process RunEvent stream, and returns `pending_tool_call` when approval is required. Durable sessions, resume handles, and agent token events are not implemented yet. See [Agent runtime and ReAct loop](./agents.en.md).

## 8. Workflow protocol

Status: `Planned`.

```python
class WorkflowEngine(Protocol):
    async def start(self, definition: WorkflowDefinition, context: RunContext) -> WorkflowHandle: ...


class WorkflowHandle(Protocol):
    async def pause(self) -> Checkpoint: ...
    async def resume(self) -> RunResult: ...
    async def cancel(self) -> None: ...
```

The first release guarantees recovery only at node boundaries and explicit `checkpoint()` calls.

## 9. Tool protocol

Status: `Implemented` as the Phase 3 tool-execution foundation.

```python
class ToolPolicy(Protocol):
    async def evaluate(
        self,
        binding: ToolBinding,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolPolicyDecision: ...
```

`ToolRegistry` registers `ToolBinding` entries by version and scope in the unified registry. `ToolExecutor.execute()` resolves, validates, applies policy, handles timeout/cancellation, and records audit. The default `PermissionPolicy` checks locally granted authority; `SideEffectApprovalPolicy` requires per-call ID approval for write, destructive, and external effects. A definition owns no execution policy, and the default executor never retries. `python_tool()` is the implemented simple template; HTTP/MCP/command adapters and sandbox binding remain `Planned`. See [Tool registration, policy, and execution](./tools.en.md).

## 10. Sandbox protocol

Status: `Planned`.

```python
class SandboxProvider(Protocol):
    async def create(self, request: SandboxRequest) -> SandboxHandle: ...
```

The first release plans Docker/OCI and explicitly authorized `UnsafeLocalSandbox`. nsjail and Wasm join the same capability through adapters. A remote sandbox remains `Reserved`.

## 11. Composition protocol

Status: `Planned`.

```python
class CompositionCodec(Protocol):
    def encode(self, manifest: CompositionManifest) -> str: ...
    def decode(self, code: str) -> CompositionPreview: ...
```

Decode produces a preview only; it installs no dependency, loads no plugin, and executes no code. Separate install and load operations continue only after user confirmation.

## 12. Compatibility API

Status: `Planned` / `Deprecated`.

`LegacyAgentAdapter` wraps 1.x `BaseAgent.arun()` as a next-generation agent node. The adapter converts arguments and results only; it does not pretend that legacy agents support streaming, tools, or checkpoints.
