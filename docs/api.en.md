# W-Agent API status and plan

English | [简体中文](./api.md)

This document separates stable 1.5.2 APIs, the current `2.0.0a1` microkernel/model APIs, and later planned protocols. Protocols marked `Planned` are design material and cannot be imported today.

## 1. Current top-level API

Status: `Implemented`. `w_agent.__init__` currently exports these primary types:

| Group | API |
|---|---|
| Agent | `BaseAgent`, `LegacyAgentAdapter`, `AgentDefinition`, `AgentLoop`, `ReactAgentLoop`, `RunContext`, `RunEvent`, `RunResult`, `RunStore`, `RunCheckpointSummary`, `JsonlRunStore` |
| Session | `SessionManager`, `SessionRecord`, `SessionRunRecord`, `InMemorySessionStore`, `JsonSessionStore` |
| Local assembly | `LocalRuntimeConfig`, `LocalToolConfig`, `LocalAgentRuntime`, `load_local_runtime_config`, `assemble_local_runtime` |
| Container | `BeanFactory`, `BeanDefinition`, `Scope` |
| Configuration | `DynamicConfigManager` |
| Decorators | `AgentComponent`, `ServiceComponent`, `ToolComponent`, `Component`, `Autowired`, `Qualifier` |
| Lifecycle | `PostConstruct`, `PreDestroy`, `LifecycleManager`, `GracefulShutdownManager` |
| Events | `EventBus`, `Event`, `ConfigChangedEvent` |
| AOP/resilience | `Retry`, `CircuitBreaker`, `AspectJPointcut`, advice types, `ProxyFactory`, `ResilienceManager` |
| Observability | `global_tracer`, `CompositeHealthIndicator`, `HealthIndicator`, `LLMHealthIndicator` |
| Distributed | `RedisDistributedLock`, `LockRenewalPool` |
| Skills/sandbox | `Skill`, `WasmSkillSandbox`, `NsJailSkillSandbox`, `SandboxProvider`, `DockerSandboxProvider`, `UnsafeLocalSandboxProvider` |
| Tools/scanning | `ToolRegistry`, `ToolExecutor`, `ToolCall`, `ToolResult`, `python_tool`, `load_tool_entries`, `LangChainToolAdapter`, `ParallelASTScanner`, `Doctor` |
| Microkernel | `PluginManager`, `Registry`, `ScopePath`, `EventDispatcher`, and related types |
| Models | `ModelProvider`, `ModelRegistry`, `ModelRequest`, `StreamEvent`, `OpenAICompatibleProvider`, `HttpModelProvider`, vendor mappings/templates, and related types |
| Routing/invocation/probing | `ModelRouter`, `ModelExecutor`, `InvocationPolicy`, `YamlRoutingPolicy`, `EndpointProbe`, `ModelProviderProbe`, and related types |
| Workflow | `WorkflowEngineProtocol`, `LocalWorkflowEngine`, all three definitions, `WorkflowStore`, `JsonlWorkflowStore`, and related types |
| Testing/evaluation | `ScriptedModelProvider`, `RecordingModelProvider`, `ReplayModelProvider`, `LocalEvaluationRunner`, scorers, and the JSON reporter |

The only accurate current agent protocol is:

```python
class BaseAgent:
    async def arun(self, prompt: str) -> str:
        raise NotImplementedError
```

`BaseAgent` is not yet integrated with the new model protocol. The new ReAct/tool and workflow runtimes are available independently. ReAct approval checkpoints, workflow node checkpoints, and the local persistent session lifecycle/cross-run text context are implemented; general multimodal and tool-event replay is not yet connected.

Strict local JSON can be assembled by `load_local_runtime_config()` and `assemble_local_runtime()` into a built-in provider template, single-provider route, bounded invocation policy, selected ToolBindings, ReAct loop, RunStore, and SessionStore. Configuration accepts only `api_key_env` credential references and can only select from a host catalog; it cannot import, authorize, or approve tools. `LocalAgentRuntime.resume()` and `wagent run-resume` resume approval checkpoints by exact call ID. CLI import of developer tool code additionally requires independent `--confirm-tool-code` authorization. See [locally configured runtime](./local-runtime.en.md).

## 2. Next-generation export strategy

Status: `Implemented` / `Planned`. Microkernel, model, tool, `AgentLoop`, and `WorkflowEngineProtocol` foundations are exported directly; the aggregate `Application` facade remains planned.

Next-generation APIs are exported directly from `w_agent`; there is no `w_agent.v2` namespace:

```python
from w_agent import AgentLoop, LocalWorkflowEngine, ModelProvider
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

`StreamEvent` covers content-block start/delta/end, text/tool-call deltas, usage, normalized errors, and finish. `TokenUsage` normalizes input, output, and cached-input tokens and exposes `total_tokens` without double-counting the cached subset; `ModelResponse.usage_reported` distinguishes omitted metadata from a real zero report. `collect_stream()` validates block ordering and an explicit terminal event. A provider reports unsupported standard fields and never silently ignores them.

`OpenAICompatibleProvider` implements `/models` and streaming `/chat/completions` with a replaceable `OpenAICompatibleTransport`. Generic `HttpModelProvider` exposes `HttpRequest`, `HttpStreamFrame`, `HttpProviderMapping`, `HttpStreamDecoder`, and `HttpProviderTransport`; the default `HttpxProviderTransport` supports JSON, SSE, and NDJSON.

`AnthropicMessagesMapping`, `GeminiGenerateContentMapping`, `OllamaChatMapping`, and `QwenDashScopeMapping` implement native protocols. `ProviderTemplateRegistry` includes Anthropic, Gemini, Ollama, Qwen-native, DeepSeek, GLM, Qwen-compatible, and Turbo AI/SIAM.AI templates. Dedicated OpenAI Responses and vLLM differences remain `Planned`. Default HTTPX implementations are in the `models` extra.

## 5. Routing protocol

Status: `Implemented` for Phase 2A policy/decisions and Phase 2B collecting/event-pass-through invocation.

```python
class RoutingPolicy(Protocol):
    def select(self, request: RouteRequest) -> RouteDecision: ...
```

`RouteDecision` contains candidates, rejection reasons, scores, the selected route, fallback routes, and the policy version, but no prompt plaintext. `WeightedRoutingPolicy` and the `yaml.safe_load`-based `YamlRoutingPolicy` produce the same type. `ModelRouter` reads the current model catalog and applies a policy; it still does not execute providers directly.

`ModelExecutor.invoke()` consumes a decision and returns `ModelInvocationResult`; `InvocationPolicy` bounds per-attempt timeout, retry count, route count, and deterministic backoff. `ModelExecutor.stream()` returns a single-use `ModelStreamExecution` that validates and yields events with `ModelStreamValidator`; policy-driven retry/failover is allowed before the first visible event and silent replay is prohibited afterward. The default performs one call only; higher limits may create extra billable requests. `AttemptRecord` records emitted-event count plus provider-reported TokenUsage and completeness, but no prompt or credential. A final failure raises `ModelInvocationError` with the decision and every completed attempt.

## 6. Probe protocols

Status: `Implemented` as a Phase 2A foundation.

- `EndpointProbe.probe()`: L1 URL, DNS, TCP, TLS, and HTTP reachability sniffing; the target identifier strips credentials, query data, and fragments.
- `ModelProviderProbe.probe()`: L2/L3 provider access and model-catalog checks.
- `ProbeMode.ACTIVE`: runs an L4/L5 minimal generation and stream-protocol check only with `allow_active=True`.
- `ProbeMode.CAPABILITY`: currently reports L6/L7 declarations as `SKIPPED`; it never presents declarations as active verification.
- `ProbeCache` and `PeriodicProbeService`: shared building blocks for manual and periodic probes.
- `ModelRegistrationProbeService` and `ProbeHealthBridge`: explicit register-and-safe-probe wiring plus external routing-health projection; direct `ModelRegistry.register()` performs no I/O. Credential-free L1 CLI/TUI entry points are implemented; configured active provider probing remains `Planned`.

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

`ReactAgentLoop` is an ordinary implementation built only on public model/tool contracts and can be replaced as a whole through the same protocol. It runs a bounded model/tool cycle, appends through `RunStore` before event visibility, and returns `pending_tool_call` plus `checkpoint_id` when approval is required. `RunStore.list_checkpoints()` exposes `RunCheckpointSummary` without prompts, argument values, or outputs. `TokenBudget` adds cumulative run input/output/total limits; `TOKEN_USAGE`, `RunResult.usage`, `RunResult.attempts`, and `usage_complete` expose metering, and checkpoints preserve totals plus the attempt ledger through approval resume. `SessionManager` plus memory/JSON stores now provide local lifecycle, cross-run text context, and approval-resume coordination. `customer_support_agent()` and `coding_agent()` build fully overridable ordinary definitions and bind no model, tool, or authority. General multimodal/tool event replay and per-token text events remain `Planned`. See [Agent runtime](./agents.en.md) and [Session lifecycle](./sessions.en.md).

## 8. Workflow protocol

Status: `Implemented` for Phase 4 local sequential execution and node-boundary recovery.

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

`DagWorkflowDefinition`, `StateGraphDefinition`, and `PythonWorkflowDefinition` use the same engine and can be registered by version and scope through `WorkflowRegistry` on the shared microkernel. Nodes return `WorkflowNodeResult` to update state, select a next node, or request a pause. `LocalWorkflowEngine` supports boundary cancellation and writes events/checkpoints through a replaceable `WorkflowStore`; in-memory and JSONL implementations are included. Recovery guarantees completed node boundaries only and never restores an arbitrary Python instruction stack. An uncertain node remains `RESUMING` and rejects automatic replay. `agent_workflow_node()` and `workflow_start_tool()` / `workflow_resume_tool()` provide bidirectional public-protocol adapters. Parallel DAGs, automatic cascading recovery, and nested workflows are not implemented. See [Workflows and node-boundary recovery](./workflows.en.md).

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

`ToolRegistry` registers `ToolBinding` entries by version and scope in the unified registry. `ToolExecutor.execute()` resolves, validates, applies policy, handles timeout/cancellation, and records audit. The default `PermissionPolicy` checks locally granted authority; `SideEffectApprovalPolicy` requires per-call ID approval for write, destructive, and external effects. A definition owns no execution policy, and the default executor never retries. `python_tool()`, `http_tool()`, `command_tool()`, `mcp_tool()`, `sandbox_command_tool()`, `McpClient`, `McpStdioTransport`, `McpStreamableHttpTransport`, and `discover_mcp_bindings()` are implemented. Legacy MCP initialization negotiation, automated MRTR input exchange, and subscription streams remain `Planned`. See [Tool registration, policy, and execution](./tools.en.md).

## 10. Sandbox protocol

Status: `Implemented` for the unified local contract, Docker/OCI, and explicitly authorized local development mode.

```python
class SandboxProvider(Protocol):
    async def open(
        self,
        spec: SandboxSpec,
        *,
        cancellation: CancellationToken | None = None,
    ) -> SandboxHandle: ...
```

`SandboxHandle.execute()` takes a shell-free `SandboxCommand` and returns `SandboxResult`; `close()` converges the container or local handle. `DockerSandboxProvider` defaults to no network, a read-only root filesystem, dropped capabilities, no privilege escalation, CPU/memory/PID limits, and container removal on close or uncertain execution failure. `UnsafeLocalSandboxProvider` is not a security sandbox and accepts only a runtime object created through `UnsafeLocalAuthorization.grant(..., acknowledge_host_access=True)`; Docker failure never selects it as fallback. Providers join the shared registry through `SandboxRegistry`. New-contract adapters for nsjail/Wasm remain `Planned`; remote sandbox is `Reserved`. See [Sandbox and local execution](./sandbox.en.md).

## 11. Composition protocol

Status: encoding, decoding, safe preview, and the local version store are `Implemented`; dependency installation and plugin-load confirmers remain `Planned`.

```python
code = encode_composition(manifest)
manifest = decode_composition(code)
preview = inspect_composition(code)
CompositionStore(".wagent/compositions").save(manifest, alias="stable")
```

Decode and preview perform no network access, install no dependency, load no plugin, and execute no code. Manifests reject secrets, absolute local paths, embedded code, and `UnsafeLocalSandbox` authority; the codec bounds compressed and expanded sizes. Separate post-confirmation install and load operations are not implemented yet.

## 12. Testing and evaluation API

Status: `Experimental` in `2.0.0a1`.

`ScriptedModelProvider` supplies finite deterministic network-free model turns. `RecordingModelProvider` and `ReplayModelProvider` use `JsonlModelCassette` for complete-turn recording and sequential replay behind explicit sensitive-content authorization. `load_evaluation_cases()` loads uniquely named `EvaluationCase` values from bounded strict JSON. `LocalEvaluationRunner` executes cases sequentially against asynchronous targets returning the public `RunResult`, with `ExactTextScorer`, `ContainsTextScorer`, or custom `EvaluationScorer` implementations. `EvaluationReport`/`JsonEvaluationReporter` aggregate pass rate, token usage and completeness, latency, errors, and tool outcomes; reports do not persist prompts, metadata, outputs, or exception bodies by default. The `wagent evaluate` CLI runs only after explicit model-call authorization and uses disposable state by default. See [Local testing, model replay, and evaluation](./testing-evaluation.en.md).

## 13. Compatibility API

Status: `Implemented` (`LegacyAgentAdapter`) / `Deprecated` (1.x abstraction).

`LegacyAgentAdapter` wraps 1.x `BaseAgent.arun()` as a workflow node. It performs explicit text argument/result conversion only and does not pretend that legacy agents support streaming, tools, token usage, or checkpoints; non-text input requires a caller-supplied `prompt_mapper`.
