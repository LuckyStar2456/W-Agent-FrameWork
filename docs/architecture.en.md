# W-Agent architecture

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./architecture.md)

> Release scope: the new framework core described here is included in 2.1.0. Earlier “unpublished” labels and candidate 2.0.0 metadata below record pre-release stages, not the 2.1.0 package status. See [2.1.0 notes](./releases/2.1.0.en.md); upload status is on [PyPI](https://pypi.org/project/wagent-framework/2.1.0/).

## 1. Positioning

W-Agent is an open Harness development framework inspired by Spring IoC, DI, AOP and lifecycle management, not a hosted platform or a fixed Harness. Developers define their execution systems through decorators, explicit Python or configuration, retaining control over models, routing, agent loops, workflows, tools, state, sandboxes and interfaces.

The [Harness core baseline](./harness-core.en.md) governs architecture: M0–M4 completed stage acceptance, with IoC/DI/AOP as the new core rather than merely a 1.x compatibility layer. M5 [tutorials](./harness-development.en.md) and [final acceptance](./harness-acceptance.en.md) record developer delivery; the new core remains unpublished. The 2.0.0 module descriptions below retain their historical release boundary.

| New core | Responsibility | Non-responsibility |
|---|---|---|
| `AssemblyPlan` and three compilers | Unified dependency, argument, scope and aspect definitions | No configuration-selected imports or object construction |
| `ApplicationContext` | Factory ownership, DI, scopes, AOP, startup rollback and cleanup | No fixed Agent algorithm |
| `ApplicationPlugin` / Registry | Plugin lifecycle bridge and capability visibility, preserving custom `scope_order` | Registry is not a second object container |
| `ApplicationProject` / `ApplicationHost` | Public operations, call/stream tasks and invocation scopes | No supervision of unregistered background tasks or security isolation |
| `local_application.py` | Replaceable Runtime/Workflow recipes | No restriction on custom model/Harness protocols |
| CLI / TUI | Explicit loading of the same project and JSON/display adaptation | No authorization bypass or private assembly branch |

The 1.5.2 compatibility foundation implements IOC, AOP, configuration, lifecycle, resilience, security and observability. Version 2.0.0 is published; see the [release record](./acceptance-2026-10-01-stable-release.en.md) for artifact and verification evidence. This document covers implemented, experimental and planned architecture; the [roadmap](./roadmap.en.md) governs availability and acceptance boundaries. Experimental capabilities are not advertised as stable, and planned capabilities are not advertised as delivered.

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

The current `EventDispatcher` implements in-process extension events, with listener registrations owned by plugin lifecycle. Phase 3 adds a separate RunEvent stream, persisted before visibility through `RunStore`/`JsonlRunStore` and separate from live consumption. The `2.0.0a4` release adds read-only cursor paging, replaceable JSON redaction projection, declarative top-level/nested field policy, explicitly enabled tool-argument deltas, and explicit image/audio output projection; general new modalities remain `Planned`.

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

Implemented protocols include `PluginSpec`, `PluginHandle`, `Registry`, `RegistryView`, `ScopePath`, `Contribution`, `Registration`, `EventDispatcher`, model/routing and tool contracts, agent run/loop contracts, and workflow definition/engine/checkpoint contracts. Later `Planned` protocols include:

- General durable `AgentHandle` and arbitrary-position resume handles (local sessions plus approval/workflow-node resume are implemented).

## 6. Models, routing, and probing

Status: the Phase 2A protocols, registry, routing, and probe framework plus the Phase 2B OpenAI-compatible provider, generic HTTP mapping layer, dedicated OpenAI Responses/vLLM handling, vendor templates, collecting/pass-through executors, and explicit register-and-safe-probe service are `Implemented`; explicit text-prefix recovery is `Experimental`, while the provider-native cursor contract/executor wiring is in the `2.0.0a4` release and bundled vendor cursor adapters remain `Planned`.

The model protocol can express the capabilities needed by OpenAI, Anthropic, Gemini, OpenAI-compatible APIs, Ollama, vLLM, and custom providers. Current implementations include OpenAI-compatible Chat Completions, an OpenAI Responses mapping, vLLM-specific extensions, a generic HTTP provider with replaceable request mapping, stream decoding, and transport, and Anthropic, Gemini, Ollama, Qwen, DeepSeek, GLM, and Turbo templates. Multimodality, tool calling, structured output, reasoning, and prompt caching are exposed through capabilities rather than a lowest-common-denominator API; templates never infer capabilities from model names.

Routing applies user and safety filters, capability matching, health filtering, scoring, and selection. Python strategies and YAML rules compile to the same `RoutingPolicy`. Every selection emits an observable `RouteDecision` with candidates, rejection reasons, scores, and the final choice. Invocation belongs to a separate `ModelExecutor` consumer, which can collect a complete stream or pass events through in real time, applies explicit timeout/retry/failover policy, and prohibits silent replay after visibility without feeding execution rules back into routing.

Current probing implements L1 URL/DNS/TCP/TLS/HTTP, L2 provider access, L3 model catalog, and explicitly authorized L4/L5 generation/stream-protocol checks, plus caching and a generic periodic scheduler. `ModelRegistrationProbeService` supplies optional register-and-safe-probe assembly and projects fresh results into external route health; the low-level registry performs no I/O. CLI/TUI now expose credential-free L1 and configured safe/active provider entry points, with per-run confirmation for active mode. L6/L7 still report declarations and remain marked as not actively verified. Provider-only assembly performs no I/O, while whether `safe` accesses a remote catalog is defined by the provider catalog contract.

See [Models, routing, and endpoint probing](./model-routing.en.md).

## 7. Agent runtime

Status: public run/loop contracts, bounded single-agent ReAct, in-process/JSONL event storage, approval resume, and local session lifecycle are `Implemented`; read-only cursor paging, replaceable JSON redaction projection, declarative top-level/nested field policies, and explicit multimodal output projection are in the `2.0.0a4` release.

The runtime defines run lifecycle, context, events, cancellation, budgets, and results without prescribing one reasoning policy. The first release provides a usable ReAct template. Users can replace the entire loop, insert pipelines between phases, add step types, choose the next step dynamically, or invoke a workflow from an agent.

The current `ReactAgentLoop` uses public `ModelExecutor`, `ToolRegistry`, and `ToolExecutorProtocol` contracts to complete model → tool → result → model, enforce step/tool-call/run-token budgets plus cost budgets based on application-supplied versioned price tables, and stop safely for approval. A replaceable `TokenEstimator` sits between the neutral request and network call to provide pre-call estimates, output-allowance tightening, and soft-threshold events. The kernel binds no vendor tokenizer, and `TokenBudget.require_estimate` explicitly decides whether estimation failure stops the run. When enabled explicitly, a replaceable `CostEstimator` consumes only prompt-free route, replay-limit, and token-estimate inputs; the default `PricingCostEstimator` produces preferred-attempt and full retry/failover cost envelopes for warnings or hard stops before model-generation requests. Neither estimate replaces provider-reported reconciliation afterward. When `emit_text_deltas` is explicitly enabled, the loop uses the public safe model stream and projects text chunks as persisted-before-visible `MODEL_TEXT_DELTA`; collecting mode stays the default. `emit_output_blocks` independently controls persistence of completed media blocks. `RunStore` appends events before visibility; `JsonlRunStore` resumes from an approval boundary after restart without repeating the earlier model request, while checkpoints preserve cumulative tokens, costs, estimation policy, and attempt ledgers. Checkpoints are atomically claimed before side effects, and uncertain state rejects automatic replay. General cross-process model continuation remains later work. See [Agent runtime and ReAct loop](./agents.en.md).

The `2.0.0a4` release separately projects tool-argument deltas as raw `MODEL_TOOL_CALL_DELTA` only with an explicit flag. Default interfaces show safe metadata, not tool names or arguments. Image/audio output enters `MODEL_OUTPUT_BLOCK` through an independent explicit flag, replaceable encoder, and three disclosure levels. Nested structures can be copied, renamed, or fixed-masked through declarative path rules; arbitrary business transformations continue through custom projectors.

The `2.0.0a4` release also abstracts replay projection through `RunEventProjector`. Raw cursor pages and projected pages are separate; the safe default strips content and validates JSON compatibility inside the replay layer, so CLI/TUI no longer receive a raw page first. Applications may replace the projector but remain responsible for raw-store read authority and business-field disclosure policy.

Declarative `FieldPolicyRunEventProjector` builds a default-deny event-type/top-level-field allow and fixed-mask policy on that protocol. `NestedFieldRunEventProjector` additionally provides object/array source-path to object target-path copy, rename, and fixed-mask rules. Neither enters the kernel registry or replaces application authorization; arbitrary computation remains available through custom implementations.

`ModelOutputEventEncoder` is a replaceable boundary between the agent runtime and persisted representation. The default encodes neutral image/audio blocks only and bounds inline content; `MultimodalRunEventProjector` then separates metadata, reference, and body disclosure. External blob stores, new modalities, and business authorization need no loop-core change.

`SessionManager` sits outside the loop and uses public contracts to manage create/list/archive, cross-run text projection, and approval resume with memory/JSON stores. `agent_usage()` derives prompt/output-free cross-session usage, cost, and completeness views by agent name from immutable run summaries; callers explicitly choose whether archived sessions participate. It reads no private loop state and never presents tool or multimodal events as replayed content.

## 8. Workflow

Status: sequential local execution, all three frontends, node events, node-boundary recovery, and bidirectional agent adapters are `Implemented`; explicitly bounded concurrent asynchronous DAG frontiers are in the `2.0.0a4` release, while nesting is `Reserved`.

Agent loops and workflows use similar but separate context, event, cancellation, and result contracts so orchestration does not absorb the reasoning loop. `WorkflowRegistry` manages definitions by version and scope through the shared microkernel registry. `LocalWorkflowEngine` accepts static DAG, state-graph, and Python-handler `WorkflowDefinition` forms through one `WorkflowEngineProtocol`. `WorkflowStore` is replaceable; built-ins include `InMemoryWorkflowStore` and `JsonlWorkflowStore`.

`agent_workflow_node()` adapts a fixed agent definition into a node. `workflow_start_tool()` and `workflow_resume_tool()` adapt a fixed workflow definition into standard tools that reuse permission, per-call approval, cancellation, and audit pipelines. Both directions depend only on public protocols and receive no kernel privileges. Agent approval checkpoints and workflow pauses do not cascade recovery automatically; callers explicitly handle non-completed states.

Recovery is guaranteed only at node boundaries. A node checkpoint is claimed as `RESUMING` before execution and returns to `READY` or `PAUSED` only after completion. A process interruption inside a node therefore fails closed instead of silently replaying possible external side effects. The Python entry point calls the handler again with persisted state and `resume_count`; it does not restore arbitrary Python instruction positions or call stacks. The `2.0.0a4` release adds opt-in bounded asynchronous DAG-frontier concurrency; a batch reads one committed snapshot and cannot be automatically replayed after failure or conflict. Nested workflows, multi-agent orchestration, and distributed scheduling are not implemented. See [Workflows and node-boundary recovery](./workflows.en.md).

## 9. Tools

Status: Python, HTTP, shell-free command, sandbox-command templates, MCP binding, MCP 2026-07-28 stdio/Streamable HTTP clients, and the unified registration/policy/execution foundation are `Implemented`; MCP 2025 initialization negotiation is in the `2.0.0a4` release, while legacy server-initiated requests, automated MRTR exchange, and subscription streams are `Planned`.

Tool definition, execution, policy, and results are separate:

```text
ToolDefinition → Policy Pipeline → ToolExecutor → ToolResult
```

Current templates cover Python functions, fixed-endpoint HTTP, shell-free local commands, sandbox commands, arbitrary MCP client binding, and first-party MCP stdio/Streamable HTTP JSON/SSE clients. `McpClient` places current stable-protocol metadata on every request and supports bounded paginated discovery plus tool calls; `discover_mcp_bindings()` returns bindings without registering or authorizing them. HTTP uses a fixed endpoint, disables redirects, bounds response bytes, and safely generates standard and `x-mcp-header` headers. Stdio uses shell-free argv, newline JSON-RPC, cancellation notifications, and bounded shutdown. The `2.0.0a4` release additionally offers an explicitly selected `McpLegacyClient` and legacy HTTP session transport. Calls still pass through unified permission, per-call approval, timeout, cancellation, and prompt-free audit. Legacy server-initiated requests, automated MRTR input exchange, and subscription streams are not implemented.

See [Tool registration, policy, and execution](./tools.en.md).

## 10. Sandbox

Status: the unified contract/registry, Docker/OCI backend, and explicitly authorized local backend are `Implemented`; nsjail/Wasm adapters to the new contract are `Planned`, and remote sandbox is `Reserved`.

`DockerSandboxProvider` creates lifecycle-owned container handles. It defaults to no network, a read-only root filesystem, dropped capabilities, no privilege escalation, CPU/memory/PID limits, one explicit workspace mount, and container removal on close or uncertain execution. Images require a digest or non-`latest` tag by default. Network currently supports `none` and `bridge`; granular allowlists are not implemented.

`UnsafeLocalSandboxProvider` is a named dangerous development mode, not a security sandbox. It accepts only an explicit runtime object from `UnsafeLocalAuthorization.grant()` and cannot receive authorization by deserializing configuration, plugins, or composition codes. Safe-backend failure never switches to local mode. Local mode requires explicit `SandboxNetwork.BRIDGE` and read-write workspace settings and rejects no-network/read-only claims it cannot honor. It provides no container resource isolation, only shell-free argv, working directory, timeout, cancellation, and output bounds.

See [Sandbox and local execution](./sandbox.en.md).

## 11. Portable project compositions

Developers assemble plugins, version constraints, configuration, routing, workflow references, and sandbox policy into a named and versioned `CompositionManifest`, then export it as a copyable code with a schema version and integrity check.

Current code implements canonical manifests, deterministic encoding/decoding, size and integrity checks, safe preview, and a conflict-safe local version/alias store. Codes contain no secrets, absolute local paths, or arbitrary source and cannot grant local-execution authority. Preview, dependency planning, and install planning perform no network access or plugin import. The `2.0.0a4` release's separate installation layer reads a host-supplied exact wheel/SHA-256 closure plus source mapping and derives a request digest binding the composition, index, entry, versions, and hashes. Only explicit authorization lets a replaceable `PackageInstaller` execute in the selected sandbox. The revalidated install tree still requires a second plugin-code load authorization before entering the ordinary `PluginManager`. Online source discovery, automatic locking/updating, and hot migration are not current capabilities. See [Portable project compositions](./project-sharing.en.md).

## 12. CLI, TUI, and evaluation

The CLI and Textual TUI use public Python APIs and do not form a private control plane. The first release covers initialization, configuration validation, plugin inspection, model probing, profile resolution, runs, checkpoint recovery, sandbox authorization, and event inspection. The `2.0.0a4` release additionally exposes the same locked-install planning, exact install confirmation, and independent plugin-load confirmation without turning UI confirmations into kernel privilege.

The current `Experimental` local evaluation layer provides network-free scripted models, explicitly authorized JSONL model recording/sequential replay, replaceable scorers, and token/versioned-cost completeness, latency, error, and tool-success metrics. Recording is an ordinary replaceable model-provider decorator, and evaluation targets depend only on public `RunResult` values, so neither has kernel privilege. The CLI/TUI can run a configured agent from strict JSON or an in-process `builtin:` suite with disposable state and privacy-safe report defaults. Versioned support/coding suites come from a replaceable registry and declare only cases plus tool contracts; they bundle no tools, authority, or online service. An online evaluation platform is outside project scope. See [Local testing, model replay, and evaluation](./testing-evaluation.en.md).

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
