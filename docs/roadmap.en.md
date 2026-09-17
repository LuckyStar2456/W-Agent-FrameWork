# Roadmap and capability status

English | [简体中文](./roadmap.md)

This document is the single capability-status overview for W-Agent. Phases describe implementation order and do not promise release dates.

## Current 1.5.2

| Capability | Status | Notes |
|---|---|---|
| `BaseAgent.arun()` | `Implemented` | Minimal asynchronous agent abstraction |
| IOC, component scanning, lifecycle | `Implemented` | Existing 1.x engineering foundation |
| AOP, retry, circuit breaker, timeout, bulkhead | `Implemented` | General resilience capabilities |
| Dynamic configuration and event bus | `Implemented` | Not the next-generation plugin kernel |
| Logging, metrics, tracing, health | `Implemented` | Some backends are optional dependencies |
| Wasm and nsjail skill sandboxes | `Implemented` | 1.x interfaces; not yet adapted to the new SandboxProvider |
| LangChain adapter and FastAPI example | `Implemented` | 1.x integrations |

## First-release plan

| Capability | Status | Phase |
|---|---|---|
| Phase 1 microkernel public protocols | `Implemented` | 2.0.0a1 |
| Unified registry and plugin lifecycle | `Implemented` | 2.0.0a1 |
| Dependency resolution, reversible registration, scopes, event pipelines | `Implemented` | 2.0.0a1 |
| Unified model protocol and stream events | `Implemented` | Phase 2A / 2.0.0a1 |
| OpenAI-compatible Chat Completions adapter | `Implemented` | Phase 2B / 2.0.0a1 |
| Generic HTTP mapping layer and SSE/NDJSON transport | `Implemented` | Phase 2B / 2.0.0a1 |
| Native Anthropic, Gemini, Ollama, and Qwen templates | `Implemented` | Phase 2B / 2.0.0a1 |
| DeepSeek, GLM, Qwen-compatible, and Turbo template registry | `Implemented` | Phase 2B / 2.0.0a1 |
| Dedicated OpenAI Responses and vLLM differences | `Planned` | Phase 2B |
| Python and YAML routing | `Implemented` | Phase 2A / 2.0.0a1 |
| Manual probe API, cache, and periodic scheduler | `Implemented` | Phase 2A / 2.0.0a1 |
| Automatic safe probing and health bridging through the explicit registration service | `Implemented` | Phase 2B / 2.0.0a1 |
| CLI/TUI safe endpoint-probe entry points | `Implemented` | Phase 2B / 2.0.0a1 |
| CLI/TUI configured safe/active provider probes | `Experimental` | Phase 2B/6 / 2.0.0a1 |
| Collecting invocation, timeout, retry, and failover executor | `Implemented` | Phase 2B / 2.0.0a1 |
| Safe event-pass-through executor | `Implemented` | Phase 2B / 2.0.0a1 |
| Normalized provider input/output token metering | `Implemented` | Phase 2B / 2.0.0a1 |
| Cross-stream recovery and resume | `Planned` | Phase 2B |
| Single-agent ReAct/tool-loop template | `Implemented` | Phase 3 / 2.0.0a1 |
| In-process RunEvent stream and bounded budgets | `Implemented` | Phase 3 / 2.0.0a1 |
| Visible run-level token metering and hard budgets | `Implemented` | Phase 3 / 2.0.0a1 |
| Session totals and per-attempt token ledger | `Implemented` | Phase 3/6 / 2.0.0a1 |
| Cross-session agent aggregation, estimators, and cost budgets | `Planned` | Phase 3/6 |
| Local JSONL RunEvents and approval-checkpoint resume | `Implemented` | Phase 3 / 2.0.0a1 |
| Separate tool definition, policy, and execution | `Implemented` | Phase 3 / 2.0.0a1 |
| Python-function tool template | `Implemented` | Phase 3 / 2.0.0a1 |
| HTTP and shell-free command tool adapters | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP client binding adapter | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP 2026-07-28 stdio/Streamable HTTP clients and discovery | `Implemented` | Phase 3 / 2.0.0a1 |
| Legacy MCP initialization negotiation, MRTR, and subscriptions | `Planned` | Phase 3/5 |
| Local session lifecycle and cross-run text projection | `Implemented` | Phase 3 / 2.0.0a1 |
| General multimodal/tool/RunEvent replay | `Planned` | Phase 3/6 |
| DAG, state-graph, and Python workflows | `Implemented` | Phase 4 / 2.0.0a1 |
| Local node-level checkpoint, pause, and resume | `Implemented` | Phase 4 / 2.0.0a1 |
| Agent/workflow convenience adapters | `Implemented` | Phase 4 / 2.0.0a1 |
| Docker/OCI coding sandbox | `Implemented` | Phase 5 / 2.0.0a1 |
| Explicit `UnsafeLocalSandbox` mode | `Implemented` | Phase 5 / 2.0.0a1 |
| Sandbox command-tool binding | `Implemented` | Phase 5 / 2.0.0a1 |
| Customer-support/RAG and coding profiles | `Implemented` | Phase 5 / 2.0.0a1 |
| Portable composition codes, safe preview, and versioning | `Implemented` | Phase 6 / 2.0.0a1 |
| Typer/Rich CLI, Textual TUI, and session lifecycle UI | `Experimental` | Phase 6 / 2.0.0a1 |
| Locally configured text-agent run entry point | `Experimental` | Phase 6 / 2.0.0a1 |
| Configured tool selection, explicit code loading, and CLI approval resume | `Experimental` | Phase 3/6 / 2.0.0a1 |
| Prompt-free agent approval-checkpoint listing in API/CLI/TUI | `Implemented` | Phase 3/6 / 2.0.0a1 |
| Scripted model mocks, explicit record/replay, and local evaluation metrics | `Experimental` | Phase 6 / 2.0.0a1 |
| CLI local-evaluation entry point and privacy-safe reports | `Experimental` | Phase 6 / 2.0.0a1 |
| Built-in support/coding suites, pricing/cost metrics, and TUI evaluation | `Planned` | Phase 6 |
| Minimal 1.x `LegacyAgentAdapter` | `Implemented` | Phase 6 / 2.0.0a1 |

## Delivery phases

### Phase 0: design and documentation

- Status: `Implemented`.
- Freeze design principles, protocol boundaries, status labels, and non-goals.
- Update all Chinese and English documentation.
- Do not modify existing runtime code.

### Phase 1: microkernel

- Status: `Implemented` in `2.0.0a1`.
- Python 3.11+.
- `PluginSpec`, unified registry, lifecycle, dependency resolution, scopes, and event/pipeline dispatch.
- Four plugin entry styles converge on one registration process.
- Tests for unload, failure rollback, and run snapshots.

### Phase 2: models and routing

- Status: `Implemented` for the 2A foundation / `Planned` for 2B adapters and execution.
- 2A implements model requests, responses, stream events, capabilities, extensions, the provider registry, and stable error categories.
- 2A implements explainable route decisions, Python/YAML policies, endpoint sniffing, provider probes, caching, and periodic scheduling.
- 2B implements an OpenAI-compatible Chat Completions provider with replaceable HTTP transport.
- 2B implements the generic HTTP request-mapping layer, JSON/SSE/NDJSON transport, four native templates, and four compatible-vendor templates.
- 2B implements collecting and event-pass-through executors with one call by default, explicit bounded retry/failover, per-attempt timeout, and audit records. Pass-through execution prohibits silent replay after any event becomes visible.
- 2B normalizes provider-reported input, output, and cached-input tokens. `usage_reported` distinguishes a real zero-token report from missing provider metadata instead of presenting a zero value as complete metering.
- 2B implements optional register-and-safe-probe through `ModelRegistrationProbeService` and `ProbeHealthBridge`; low-level `ModelRegistry.register()` keeps pure registration semantics.
- 2B now includes credential-free L1 endpoint probes plus CLI/TUI provider probes assembled from strict local configuration. Provider-only assembly performs no registration or I/O; whether `safe` accesses a remote catalog is provider-defined, while explicitly authorized `active` verifies minimal generation and stream termination. Later work adds OpenAI Responses/vLLM differences and cross-stream recovery.

### Phase 3: agents and tools

- Status: the tool foundation, run contracts, single-agent ReAct, local event recording, approval resume, and local session lifecycle are `Implemented`; general event replay remains `Planned`.
- Implemented replaceable loops, a default ReAct template, in-process/JSONL RunEvents, step/tool budgets, and approval resume without repeating the first model request.
- Implemented run-level input, output, and total hard limits through `TokenBudget`; `RunResult.usage` and `TOKEN_USAGE` events expose cumulative values, and approval checkpoints preserve metering state. `max_output_tokens` remains a per-model-request generation cap.
- Current budgets reconcile provider-reported actual usage after each successful response and tighten the next request from the remaining output/total allowance. `require_usage=True` fails closed when a provider omits usage. Exact first-request input usage cannot be known without a tokenizer, and failed or interrupted retry attempts may already have incurred unreported usage.
- Implemented session totals, `AttemptRecord` token ledgers covering retry/failover, and RunEvent/CLI visibility. Missing usage for failed attempts remains unknown and makes strict accounting fail closed.
- Later work adds cross-session agent aggregation, a pluggable pre-call token estimator, soft-threshold actions, and cost budgets. Cost control will require an explicit versioned price table and will not silently infer money from token counts.
- Implemented `SessionManager`, memory/JSON stores, create/list/archive/unarchive, cross-run text projection, and session-bound agent start/approval resume.
- Later work adds general projection/replay for multimodal, tool, and arbitrary RunEvents plus per-token agent text events.
- Implemented Python tools, unified registration, argument validation, permission/per-call approval, timeout/cancellation, normalized results, and prompt-free audit.
- Implemented fixed-endpoint HTTP, shell-free command tools, transport-neutral MCP binding, and MCP 2026-07-28 stdio/Streamable HTTP JSON/SSE clients with paginated discovery, explicit binding, and `x-mcp-header`. Discovery never registers, authorizes, or approves a tool automatically.
- Later work adds 2025-era `initialize` compatibility negotiation, automated MRTR input exchange, subscription streams, and MCP sandbox binding.

### Phase 4: workflows

- Status: the local sequential engine, node-boundary recovery, and bidirectional agent adapters are `Implemented`; parallel execution is `Planned`.
- Implemented DAG, state-graph, and Python APIs sharing `WorkflowEngineProtocol`, events, and results.
- Implemented in-memory/JSONL node checkpoints, explicit pause, restart resume, and boundary cancellation.
- Uncertain node execution remains `RESUMING` and rejects automatic replay; arbitrary Python instruction stacks are not restored.
- Implemented `agent_workflow_node()` plus `workflow_start_tool()` / `workflow_resume_tool()` governed by the normal tool permission and per-call approval pipeline. The adapters depend only on public protocols and allow replacement of message, authority-context, and result mapping.
- Later work adds optional parallel DAG scheduling. Automatic cascading recovery between agent approval checkpoints and workflow pauses remains a later design.

### Phase 5: local profiles and sandboxing

- Status: unified contracts, Docker provider, explicitly authorized local provider, command-tool binding, and initial agent templates are `Implemented`; broader environment acceptance remains `Planned`.
- Implemented Docker/OCI lifecycle handles, network-off defaults, resource limits, least-privilege arguments, fixed-image policy, and cleanup.
- Implemented `UnsafeLocalSandboxProvider`, constructible only with a runtime authorization object; safe-backend failure never downgrades automatically.
- Implemented `sandbox_command_tool()` through the existing permission, per-call approval, cancellation, and audit pipeline.
- Implemented fully overridable customer-support/RAG and coding `AgentTemplate` values. Templates bind no model, register no tool, and grant neither permission nor local-execution authority.
- Later work adds network allowlists, nsjail/Wasm adapters to the new contract, and broad Windows Docker Desktop/WSL2 validation.

### Phase 6: sharing, interfaces, and evaluation

- Implemented named/versioned `CompositionManifest` values, deterministic encoding/decoding, size bounds, integrity checks, safe preview, and a conflict-safe local version/alias store.
- Preview performs no network access, installation, import, or plugin execution. Dependency resolution plus installation/load confirmations remain `Planned`.
- An initial `wagent` CLI (with the `w-agent` alias) and launchable Textual TUI now cover workspace initialization, template listing, safe endpoint probing, composition export/preview/save/list, local session create/show/archive/unarchive with visible token totals, and offline TUI composition inspection.
- Implemented strict local JSON assembly into provider/routing/ReAct/run/session components for text runs. CLI/TUI require explicit authorization for every call, and credentials resolve only through environment-variable references.
- Implemented host-catalog-bounded configured tool selection, per-command authority grants, separate Python tool-code load confirmation, and CLI approval resume by known session/run/call IDs. Configuration itself cannot import, authorize, or approve a tool.
- Implemented prompt-free agent approval-checkpoint listing in the API, CLI, and TUI. Summaries exclude prompts, argument values, outputs, and credentials.
- Implemented network-free scripted model providers, JSONL recording/sequential replay requiring explicit sensitive-content authorization, and a sequential evaluation runner with replaceable scorers. The CLI reads strict JSON datasets, uses disposable state by default, and reports token completeness, latency, errors, and tool success rate. JSON reports omit prompts, outputs, metadata, and exception bodies by default.
- TUI tool-approval execution, live RunEvent views, workflow-checkpoint aggregation/cross-store recovery, general plugin-install confirmation, and evaluation screens remain `Planned`.
- Built-in customer-support/coding benchmark tasks, a versioned price table, cost metrics, and the TUI evaluation screen remain `Planned`.
- Implemented a strict text-only bridge from legacy `BaseAgent.arun()` to workflow nodes; other old-API bridges remain demand-driven plans rather than a second runtime.

## Reserved without a release phase

The following capabilities are `Reserved`:

- Out-of-process multi-language plugin SDKs.
- A first-party remote-sandbox implementation.
- A complete MCP tool provider.
- Multi-agent, delegation, human-approval workflows, and agent communication.
- Nested and distributed workflows.
- Composition-code signing, publishing indexes, and trust networks.
- A complete online evaluation service.
- Specialized modality adapters such as voice; the core multimodal protocol is reserved in the model phase.

## Non-goals

- A hosted W-Agent platform.
- First-release tenancy, organizations, billing, or cloud-account administration.
- Automatically executing third-party code from an imported composition.
- Silently falling back to host execution when an isolated backend is unavailable.
