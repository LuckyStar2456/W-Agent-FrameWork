# W-Agent API status and plan

English | [简体中文](./api.md)

This document separates current 1.5.2 public APIs from planned next-generation protocols. Planned protocols are design material and cannot be imported today.

## 1. Current top-level API

Status: `Implemented`. `w_agent.__init__` currently exports these primary types:

| Group | API |
|---|---|
| Agent | `BaseAgent` |
| Container | `BeanFactory`, `BeanDefinition`, `Scope` |
| Configuration | `DynamicConfigManager` |
| Decorators | `AgentComponent`, `ServiceComponent`, `ToolComponent`, `Component`, `Autowired`, `Qualifier` |
| Lifecycle | `PostConstruct`, `PreDestroy`, `LifecycleManager`, `GracefulShutdownManager` |
| Events | `EventBus`, `Event`, `ConfigChangedEvent` |
| AOP/resilience | `Retry`, `CircuitBreaker`, `AspectJPointcut`, advice types, `ProxyFactory`, `ResilienceManager` |
| Observability | `global_tracer`, `CompositeHealthIndicator`, `HealthIndicator`, `LLMHealthIndicator` |
| Distributed | `RedisDistributedLock`, `LockRenewalPool` |
| Skills/sandbox | `Skill`, `WasmSkillSandbox`, `NsJailSkillSandbox` |
| Tools/scanning | `LangChainToolAdapter`, `ParallelASTScanner`, `Doctor` |

The only accurate current agent protocol is:

```python
class BaseAgent:
    async def arun(self, prompt: str) -> str:
        raise NotImplementedError
```

It has no unified model, tool, session, checkpoint, or streaming-event protocol.

## 2. Next-generation export strategy

Status: `Planned`.

Next-generation APIs are exported directly from `w_agent`; there is no `w_agent.v2` namespace:

```python
from w_agent import Application, AgentLoop, ModelProvider, WorkflowEngine
```

Until migration is complete, top-level exports avoid ambiguous behavior between old and new objects with the same name. Old objects remain through a compatibility module or adapter.

## 3. Microkernel protocols

Status: `Planned`.

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

## 4. Model protocols

Status: `Planned`.

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

`StreamEvent` is planned to cover content block start/delta/end, tool-call deltas, usage, errors, and finish. A provider reports unsupported standard fields and never silently ignores them.

## 5. Routing protocol

Status: `Planned`.

```python
class RoutingPolicy(Protocol):
    async def route(self, request: RouteRequest) -> RouteDecision: ...
```

`RouteDecision` contains candidates, rejection reasons, scores, the selected route, failover routes, and the policy version. Python policies and YAML rules produce the same type.

## 6. Agent protocol

Status: `Planned`.

```python
class AgentLoop(Protocol):
    async def run(self, context: RunContext) -> RunResult: ...
    def stream(self, context: RunContext) -> AsyncIterator[RunEvent]: ...
```

The default ReAct loop is an ordinary provider that another loop can replace through the same protocol. Synchronous `invoke()` is only a boundary wrapper.

## 7. Workflow protocol

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

## 8. Tool protocol

Status: `Planned`.

```python
class ToolExecutor(Protocol):
    async def execute(self, call: ToolCall, context: RunContext) -> ToolResult: ...
```

A tool definition does not own execution policy. Permission, approval, cache, timeout, audit, and sandbox behavior compose through the execution pipeline.

## 9. Sandbox protocol

Status: `Planned`.

```python
class SandboxProvider(Protocol):
    async def create(self, request: SandboxRequest) -> SandboxHandle: ...
```

The first release plans Docker/OCI and explicitly authorized `UnsafeLocalSandbox`. nsjail and Wasm join the same capability through adapters. A remote sandbox remains `Reserved`.

## 10. Composition protocol

Status: `Planned`.

```python
class CompositionCodec(Protocol):
    def encode(self, manifest: CompositionManifest) -> str: ...
    def decode(self, code: str) -> CompositionPreview: ...
```

Decode produces a preview only; it installs no dependency, loads no plugin, and executes no code. Separate install and load operations continue only after user confirmation.

## 11. Compatibility API

Status: `Planned` / `Deprecated`.

`LegacyAgentAdapter` wraps 1.x `BaseAgent.arun()` as a next-generation agent node. The adapter converts arguments and results only; it does not pretend that legacy agents support streaming, tools, or checkpoints.
