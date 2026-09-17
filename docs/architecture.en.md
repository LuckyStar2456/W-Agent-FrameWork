# W-Agent architecture

English | [简体中文](./architecture.md)

## 1. Positioning

W-Agent is an open agent framework for local developers, not a hosted platform or a fixed harness. It provides stable protocols, lifecycle management, and default templates required for composition while leaving models, routing, agent loops, workflows, tools, state, sandboxes, and interfaces under developer control.

Stable version 1.5.2 implements the IOC, AOP, configuration, lifecycle, resilience, security, and observability foundation. The current `2.0.0a1` source implements the Phase 1 microkernel and Phase 2A model foundation. The remainder of this document covers both implemented capabilities and the `Planned` architecture; capabilities not marked `Implemented` must not be presented as available.

## 2. Design principles

1. **Stable protocols, open policies**: public protocols remain compatible while implementations stay replaceable and extensible.
2. **No privileged defaults**: first-party plugins use the same extension APIs as third-party plugins.
3. **Composition over inheritance**: agents are assembled from capabilities instead of inheriting one large framework base class.
4. **Explicit over implicit**: dependencies, scopes, versions, failure modes, and side effects are visible.
5. **Async first**: model streams, tools, workflows, and runtime protocols are asynchronous; synchronous APIs are boundary conveniences.
6. **Fail closed**: unavailable sandboxes, permissions, or dependencies reject high-risk work instead of silently reducing safety.
7. **Local first**: tenant, billing, and cloud control-plane concepts are excluded; remote capabilities connect as ordinary plugins.
8. **Honest status**: documentation distinguishes implemented, planned, reserved, experimental, and deprecated capabilities.

## 3. Layered architecture

```text
┌────────────────────────────────────────────────────────────┐
│ Applications: CustomerSupport / Coding / User Composition  │
├────────────────────────────────────────────────────────────┤
│ Runtime: Agent Loop / Workflow / Session / Checkpoint      │
├────────────────────────────────────────────────────────────┤
│ Capabilities: Model / Router / Tool / RAG / Sandbox        │
├────────────────────────────────────────────────────────────┤
│ Microkernel: Plugin / Registry / Lifecycle / Scope / Event │
├────────────────────────────────────────────────────────────┤
│ Adapters: Storage / Telemetry / CLI / TUI / Evaluation     │
└────────────────────────────────────────────────────────────┘
```

Higher-level modules depend on stable protocols or lower-level service definitions, never a concrete provider. Composition templates may select concrete implementations, but those implementations do not become part of the core protocol.

## 4. Microkernel boundary

The microkernel owns only five responsibilities, `Implemented` in `2.0.0a1`.

### 4.1 Plugin lifecycle

Plugins use one lifecycle:

```text
DISCOVERED → RESOLVING → LOADING → ACTIVE
                         ↘ FAILED
ACTIVE → QUIESCING → UNLOADING → DISPOSED
```

- `RESOLVING` validates API versions, dependencies, conflicts, and scope.
- `LOADING` creates services and registration effects.
- `QUIESCING` rejects new work and waits for affected operations to reach a safe point.
- `UNLOADING` deterministically removes registrations and releases resources.
- A failed load cannot leave partially registered services.

### 4.2 Unified registry

Explicit Python composition, decorators, YAML configuration, and Python entry points all produce one `PluginSpec` and enter one registry. Registration returns a disposable handle; unloading a plugin removes all registrations owned by that plugin.

A plugin manifest contains at least a name, version, core API version, provided capabilities, required and optional dependencies, conflicts, and default scope. Version incompatibility, missing dependencies, and capability conflicts fail as early as possible.

### 4.3 Dependency resolution

A capability has three roles:

- **Definition**: stable protocols and data types.
- **Provider**: a concrete protocol implementation.
- **Consumer**: an agent, tool, or plugin that uses the protocol.

Consumers depend on definitions, not concrete providers. The current `PluginManager` unloads active consumers before unloading a provider plugin. Automatic unload after an arbitrary registration is disposed and automatic reload after provider recovery remain `Planned`.

### 4.4 Scope

Built-in scopes are:

```text
Application → Workspace → Session → Agent → Run → Step
```

W-Agent does not include a tenant system. `ScopePath` lets plugins add custom dimensions without forcing local developers to understand tenancy. A child scope may override a parent registration, but scoped services cannot leak implicitly into a parent.

The current Registry creates immutable `RegistryView` snapshots. Binding snapshots to runs, applying plugin updates only to new runs, and migrating active runs at quiescent points remain `Planned`.

### 4.5 Events and pipelines

Events provide loose-coupled notification, while pipelines provide composable interception. The first release plans:

- `publish`: broadcast notification.
- `first`: the first explicit result wins.
- `serial`: ordered execution with optional early termination.
- `pipeline`: listeners explicitly delegate, wrap, or stop execution.

The current `EventDispatcher` implements in-process extension events, with listener registrations owned by plugin lifecycle. Phase 3 adds the separate durable RunEvent stream.

## 5. Stable and extensible protocols

Public protocols combine typed core fields with namespaced extensions:

```python
ModelRequest(
    messages=messages,
    temperature=0.2,
    extensions={"vendor.reasoning_effort": "high"},
)
```

An adapter declares whether each extension is consumed, forwarded, or rejected. Unsupported standard fields fail by default and are never silently discarded. Runtime context is controlled-mutable: formal transitions update core fields, while plugins directly write only their own namespace.

Implemented protocols include `PluginSpec`, `PluginHandle`, `Registry`, `RegistryView`, `ScopePath`, `Contribution`, `Registration`, `EventDispatcher`, `ModelRequest`, `ModelResponse`, `StreamEvent`, `ModelCapability`, `RouteRequest`, `RouteDecision`, and `RoutingPolicy`. Later `Planned` protocols include:

- `RunContext`, `RunEvent`, `RunResult`, and `StopReason`.
- `ToolDefinition`, `ToolCall`, `ToolResult`, and `ToolExecutor`.
- `AgentDefinition`, `AgentLoop`, and `AgentHandle`.
- `WorkflowDefinition`, `WorkflowEngine`, and `Checkpoint`.
- `SandboxRequest`, `SandboxHandle`, and `SandboxProvider`.

## 6. Models, routing, and probing

Status: the Phase 2A protocols, registry, routing, and probe framework plus the Phase 2B OpenAI-compatible provider, generic HTTP mapping layer, initial vendor templates, collecting/pass-through executors, and explicit register-and-safe-probe service are `Implemented`; OpenAI Responses/vLLM differences and cross-stream recovery are `Planned`.

The model protocol can express the capabilities needed by OpenAI, Anthropic, Gemini, OpenAI-compatible APIs, Ollama, vLLM, and custom providers. Current implementations include OpenAI-compatible Chat Completions, a generic HTTP provider with replaceable request mapping, stream decoding, and transport, and Anthropic, Gemini, Ollama, Qwen, DeepSeek, GLM, and Turbo templates. Multimodality, tool calling, structured output, reasoning, and prompt caching are exposed through capabilities rather than a lowest-common-denominator API; templates never infer capabilities from model names.

Routing applies user and safety filters, capability matching, health filtering, scoring, and selection. Python strategies and YAML rules compile to the same `RoutingPolicy`. Every selection emits an observable `RouteDecision` with candidates, rejection reasons, scores, and the final choice. Invocation belongs to a separate `ModelExecutor` consumer, which can collect a complete stream or pass events through in real time, applies explicit timeout/retry/failover policy, and prohibits silent replay after visibility without feeding execution rules back into routing.

Current probing implements L1 URL/DNS/TCP/TLS/HTTP, L2 provider access, L3 model catalog, and explicitly authorized L4/L5 generation/stream-protocol checks, plus caching and a generic periodic scheduler. `ModelRegistrationProbeService` supplies optional register-and-safe-probe assembly and projects fresh results into external route health; the low-level registry performs no I/O. L6/L7 currently report declarations and remain marked as not actively verified, while CLI/TUI entry points are `Planned`. Potentially billable probes require `allow_active=True`.

See [Models, routing, and endpoint probing](./model-routing.en.md).

## 7. Agent runtime

The runtime defines run lifecycle, context, events, cancellation, budgets, and results without prescribing one reasoning policy. The first release provides a usable ReAct template. Users can replace the entire loop, insert pipelines between phases, add step types, choose the next step dynamically, or invoke a workflow from an agent.

Model-visible content must be reconstructable from durable events. Default events cover runs, model requests, stream output, tool calls, state changes, and stop reasons. Custom loops may add event types, but those events remain serializable.

## 8. Workflow

Agent loops and workflows share run context, events, cancellation, and result protocols while retaining separate implementations. Workflows accept static DAG, state-graph, and Python-control-flow frontends through one workflow-engine protocol.

First-release checkpoints recover only at node boundaries and explicit `checkpoint()` calls; arbitrary Python instruction positions are not resumable. Pause, resume, cancellation, and node-completion persistence are planned. Nested workflows, multi-agent orchestration, and distributed scheduling are `Reserved`.

## 9. Tools

Tool definition, execution, policy, and results are separate:

```text
ToolDefinition → Policy Pipeline → ToolExecutor → ToolResult
```

The first release provides Python-function and HTTP templates while reserving protocols for MCP, command-line, and remote executors. Calls carry stable IDs, arguments, scope, cancellation, and side-effect classification. Approval, audit, and sandbox checks are enforced in the execution path rather than only in prompts or visibility filters.

## 10. Sandbox

Docker/OCI is the default first-release coding environment. nsjail and Wasm retain their appropriate use cases, while a remote-sandbox protocol is reserved. Windows uses Docker Desktop or WSL2 for isolated backends.

`UnsafeLocalSandbox` is an explicitly named development mode. Users must enable it directly; the CLI and TUI display host-execution risk, and an imported project composition can never grant that authorization. Safe backends fail closed when unavailable.

See [Sandbox and local execution](./sandbox.en.md).

## 11. Portable project compositions

Developers assemble plugins, version constraints, configuration, routing, workflow references, and sandbox policy into a named and versioned `CompositionManifest`, then export it as a copyable code with a schema version and integrity check.

The code contains no secrets, does not embed arbitrary source by default, and never grants local-execution authority. Import decodes, validates, previews dependencies and risk, then requires user confirmation before installation and loading. See [Portable project compositions](./project-sharing.en.md).

## 12. CLI, TUI, and evaluation

The CLI and Textual TUI use public Python APIs and do not form a private control plane. The first release covers initialization, configuration validation, plugin inspection, model probing, profile resolution, runs, checkpoint recovery, sandbox authorization, and event inspection.

Local evaluation provides mocks, test contexts, event recording and replay, profile benchmark tasks, and token, cost, latency, and tool-success metrics. An online evaluation platform is outside project scope.

## 13. 1.x compatibility

Next-generation public APIs replace the top-level `w_agent` exports directly; there is no `w_agent.v2` namespace. Essential 1.x APIs such as `BaseAgent.arun()` continue through a minimal adapter but receive no new model, workflow, or plugin features. See [1.x migration](./migration-1x.en.md).

## 14. Non-goals and reserved capabilities

Explicit non-goals:

- Hosted agent services, a cloud control plane, tenants, organizations, or billing.
- Installing, updating, or running third-party code without confirmation.
- Making a first-party ReAct or workflow implementation an irreplaceable kernel component.

`Reserved`:

- Out-of-process multi-language plugin SDKs.
- A first-party remote-sandbox provider.
- Multi-agent, delegation, and human-collaboration protocols.
- Distributed workflow scheduling.
- Composition-code signing and trust networks.
- Full online evaluation and remote run dashboards.
