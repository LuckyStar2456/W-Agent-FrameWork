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
| CLI/TUI probe entry points | `Planned` | Phase 2B |
| Collecting invocation, timeout, retry, and failover executor | `Implemented` | Phase 2B / 2.0.0a1 |
| Safe event-pass-through executor | `Implemented` | Phase 2B / 2.0.0a1 |
| Cross-stream recovery and resume | `Planned` | Phase 2B |
| Single-agent ReAct/tool-loop template | `Implemented` | Phase 3 / 2.0.0a1 |
| In-process RunEvent stream and bounded budgets | `Implemented` | Phase 3 / 2.0.0a1 |
| Local JSONL RunEvents and approval-checkpoint resume | `Implemented` | Phase 3 / 2.0.0a1 |
| Separate tool definition, policy, and execution | `Implemented` | Phase 3 / 2.0.0a1 |
| Python-function tool template | `Implemented` | Phase 3 / 2.0.0a1 |
| HTTP and shell-free command tool adapters | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP client binding adapter | `Implemented` | Phase 3 / 2.0.0a1 |
| First-party MCP stdio/HTTP session clients and discovery | `Planned` | Phase 3/5 |
| Full session lifecycle and general replay | `Planned` | Phase 3 |
| DAG, state-graph, and Python workflows | `Implemented` | Phase 4 / 2.0.0a1 |
| Local node-level checkpoint, pause, and resume | `Implemented` | Phase 4 / 2.0.0a1 |
| Agent/workflow convenience adapters | `Planned` | Phase 4 |
| Docker/OCI coding sandbox | `Implemented` | Phase 5 / 2.0.0a1 |
| Explicit `UnsafeLocalSandbox` mode | `Implemented` | Phase 5 / 2.0.0a1 |
| Sandbox command-tool binding | `Implemented` | Phase 5 / 2.0.0a1 |
| Customer-support/RAG and coding profiles | `Planned` | Phase 5 |
| Portable composition codes and versioning | `Planned` | Phase 6 |
| CLI and Textual TUI | `Planned` | Phase 6 |
| Local mocks, record/replay, and evaluation metrics | `Planned` | Phase 6 |
| Minimal 1.x compatibility adapter | `Planned` | Maintained through every phase |

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
- 2B implements optional register-and-safe-probe through `ModelRegistrationProbeService` and `ProbeHealthBridge`; low-level `ModelRegistry.register()` keeps pure registration semantics.
- Later 2B work plans OpenAI Responses/vLLM differences, CLI/TUI entry points, and cross-stream recovery.

### Phase 3: agents and tools

- Status: the tool foundation, run contracts, single-agent ReAct, local event recording, and approval resume are `Implemented`; full session lifecycle remains `Planned`.
- Implemented replaceable loops, a default ReAct template, in-process/JSONL RunEvents, step/tool budgets, and approval resume without repeating the first model request.
- Later session listing/archival, general event projections, and agent token events.
- Implemented Python tools, unified registration, argument validation, permission/per-call approval, timeout/cancellation, normalized results, and prompt-free audit.
- Implemented fixed-endpoint HTTP, shell-free command tools, and transport-neutral MCP client binding; later work adds first-party MCP stdio/HTTP session clients, discovery, and sandbox binding.

### Phase 4: workflows

- Status: the local sequential engine and node-boundary recovery are `Implemented`; bidirectional convenience adapters and parallel execution are `Planned`.
- Implemented DAG, state-graph, and Python APIs sharing `WorkflowEngineProtocol`, events, and results.
- Implemented in-memory/JSONL node checkpoints, explicit pause, restart resume, and boundary cancellation.
- Uncertain node execution remains `RESUMING` and rejects automatic replay; arbitrary Python instruction stacks are not restored.
- Later work adds convenience adapters for agent-to-workflow and workflow-node-to-agent calls plus optional parallel DAG scheduling.

### Phase 5: local profiles and sandboxing

- Status: unified contracts, Docker provider, explicitly authorized local provider, and command-tool binding are `Implemented`; profiles and broader environment acceptance remain `Planned`.
- Implemented Docker/OCI lifecycle handles, network-off defaults, resource limits, least-privilege arguments, fixed-image policy, and cleanup.
- Implemented `UnsafeLocalSandboxProvider`, constructible only with a runtime authorization object; safe-backend failure never downgrades automatically.
- Implemented `sandbox_command_tool()` through the existing permission, per-call approval, cancellation, and audit pipeline.
- Later work adds customer-support/RAG and coding profiles, network allowlists, nsjail/Wasm adapters to the new contract, and broad Windows Docker Desktop/WSL2 validation.

### Phase 6: sharing, interfaces, and evaluation

- Named and versioned `CompositionManifest`.
- Composition-code import, preview, validation, and confirmation.
- CLI, Textual TUI, event inspection, and checkpoint recovery.
- Mocks, record/replay, and customer-support and coding benchmark tasks.

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
