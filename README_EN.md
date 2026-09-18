# W-Agent

English | [简体中文](./README.md)

W-Agent is an open-source Python agent development framework for local developers. It is not a hosted platform or a fixed harness. It provides stable, extensible protocols and freely composable modules so developers can replace model, routing, agent-loop, workflow, tool, state, sandbox, and interface implementations.

The current stable release is `1.5.2`, the latest alpha is `2.0.0a3`, and repository main continues with unpublished post-`2.0.0a3` work. The 1.x engineering foundation remains available, while the microkernel, model, tool, single-agent, and local-workflow foundations are implemented. Remaining next-generation capabilities are delivered in roadmap phases. Documentation uses explicit status labels so planned or unreleased capabilities are never presented as published features.

## Status labels

| Label | Meaning |
|---|---|
| `Implemented` | Source exists with corresponding tests or an executable entry point |
| `Planned` | Accepted for implementation and assigned to the roadmap |
| `Reserved` | A protocol or extension point is reserved without a committed release |
| `Experimental` | Available for evaluation but not compatibility-stable |
| `Deprecated` | Retained only for migration and no longer extended |

## Positioning

W-Agent follows these principles:

- Core protocols are stable and extensible; concrete policies are replaceable.
- Built-in implementations use public extension APIs and receive no private privileges.
- Explicit Python composition, decorators, configuration, and Python entry points all converge on one registry.
- Agent loops and workflows interoperate without being forced into one abstraction.
- Local development comes first; tenancy, billing, and a hosted control plane are not built in.
- Untrusted execution uses a sandbox by default; host execution requires explicit user authorization.
- Implemented, planned, and reserved capabilities are distinguished in every document.

## Current capabilities

The following 1.5.2 source capabilities are `Implemented`:

- The basic `BaseAgent.arun()` abstraction.
- IOC container, component scanning, lifecycle handling, and dependency injection.
- AOP, retry, circuit breaker, timeout, and bulkhead helpers.
- Dynamic configuration, event bus, health checks, logging, metrics, and tracing.
- Wasm and nsjail skill sandboxes that fail closed when their backend is unavailable.
- Skill loading, signature verification, MCP JWT authentication, and Redis locks.
- LangChain tool adapters, a FastAPI integration example, and test helpers.

The following Phase 1 capabilities are `Implemented` on current main:

- `PluginSpec`, decorators, YAML references, and Python entry-point discovery.
- One version-aware, scoped capability registry with immutable snapshots.
- Plugin dependency resolution, lifecycle, failed-load rollback, cascading unload, and reversible registrations.
- `Application → Workspace → Session → Agent → Run → Step` scopes.
- `publish`, `first`, `serial`, and `pipeline` event modes.

The following Phase 2A capabilities are also `Implemented` in the current source:

- Provider-neutral messages, capabilities, requests, responses, and strict stream events.
- A unified `ModelRegistry`, replaceable `ModelProvider`, and cooperative cancellation token.
- Explainable weighted Python routing and safe YAML routing rules.
- L1 endpoint reachability sniffing, L2/L3 provider checks, explicitly authorized L4/L5 active probes, caching, and periodic scheduling.
- Side-effect-free provider-only assembly from strict configuration plus CLI/TUI safe-catalog and explicitly authorized active-generation probes.
- An OpenAI-compatible Chat Completions provider with a replaceable transport for local or remote services that declare compatibility.
- A pluggable generic HTTP request-mapping layer with JSON/SSE/NDJSON transport.
- Native Anthropic, Gemini, Ollama, and Qwen templates, plus DeepSeek, GLM, Qwen-compatible, and Turbo AI/SIAM.AI template registration.
- A `ModelExecutor` for both fully collected and event-pass-through execution, with one call by default, explicitly enabled bounded retry/failover, and prompt-free per-attempt token/failure records.
- `ModelRegistrationProbeService` for register-and-safe-probe workflows plus an external routing-health bridge; direct `ModelRegistry.register()` remains side-effect free.
- Tool definition/binding/registry separation, Python/HTTP/shell-free command templates, MCP binding and 2026-07-28 stdio/Streamable HTTP clients, argument validation, permission/per-call approval, timeout/cancellation, and prompt-free audit.
- A replaceable `AgentLoop` protocol and bounded single-agent `ReactAgentLoop` covering model → tool → result → model, pluggable pre-call token estimation, reported token/cost budgets, soft-threshold events, JSONL RunEvent/attempt-ledger recording, and approval-checkpoint resume.
- Application-supplied versioned price tables, normal/cached-input and output cost metering, fail-closed run cost budgets, and cost visibility across sessions, checkpoints, and evaluation.
- A unified `WorkflowRegistry`, replaceable `WorkflowEngineProtocol`, and `LocalWorkflowEngine` with static DAG, state-graph, and Python entry points, node events, cancellation, and in-memory/JSONL node-boundary pause and resume.
- Unified `SandboxProvider`/`SandboxRegistry` contracts, a Docker/OCI lifecycle backend, an explicitly runtime-authorized `UnsafeLocalSandboxProvider`, and policy-protected `sandbox_command_tool()`.
- Bidirectional agent/workflow adapters plus fully overridable customer-support/RAG and coding-agent templates.
- Deterministic `CompositionManifest` encoding, safe preview, and conflict-safe local version and alias management.
- Local session create/list/archive, JSON persistence, cross-run text context, and approval-resume coordination.
- A strict local-JSON text-agent CLI/TUI run entry point with environment credential references, per-call confirmation, and visible token/cost budgets and metering.
- Deterministic scripted model providers, explicitly authorized JSONL recording/sequential replay, a local evaluation runner, versioned support/coding suites, and privacy-safe JSON reports.

`BaseAgent` remains the minimal 1.x abstraction; `LegacyAgentAdapter` can now bridge it strictly into a text workflow node, while the new ReAct runtime is provided independently. Current main has replaceable offline composition dependency planning; safe preview, confirmed loading, and TUI unload for independent YAML plugin references; dedicated OpenAI Responses and vLLM differences; and explicit bounded replaceable text-prefix stream recovery. Online source catalogs/package installation, provider-native cursor continuation, general multimodal/tool event replay, and parallel or nested workflows remain `Planned` and must not be treated as existing features. The Docker backend has simulated CLI lifecycle tests, which do not prove Docker is installed or running on the current machine. Vendor templates likewise have fake-transport tests rather than live validation for every remote model.

## Next-generation module map

```text
Applications        Customer support / Coding / User compositions
Runtime             Agent Loop / Workflow / Session / Checkpoint
Capabilities        Models / Router / Tools / RAG / Memory / Sandbox
Microkernel         Plugin / Registry / Lifecycle / Scope / Events
Infrastructure      Storage / Telemetry / CLI / TUI / Evaluation
```

Next-generation APIs are exported directly from `w_agent`; no `w_agent.v2` namespace is introduced. The implemented minimal compatibility layer preserves the essential 1.x agent-reuse path.

## Install the current release

```bash
pip install wagent-framework
```

Install the latest alpha with:

```bash
pip install --pre wagent-framework==2.0.0a3
```

Optional dependencies:

```bash
pip install "wagent-framework[fastapi,langchain,opentelemetry]"
pip install "wagent-framework[models]"
pip install "wagent-framework[wasm]"
pip install "wagent-framework[tui]"
```

PyPI 1.x supports Python 3.9+. `2.0.0a3`, current main, and later 2.x releases require Python 3.11+.

## Minimal 1.x example

```python
import asyncio

from w_agent import AgentComponent, BaseAgent, BeanFactory


@AgentComponent(name="hello_agent")
class HelloAgent(BaseAgent):
    async def arun(self, prompt: str) -> str:
        return f"Hello, {prompt}!"


async def main() -> None:
    factory = BeanFactory()
    factory.register_bean("hello_agent", HelloAgent())
    agent = await factory.get_bean("hello_agent")
    print(await agent.arun("W-Agent"))


asyncio.run(main())
```

This is a 1.x compatibility example and does not automatically use the new ReAct, model, or tool runtime.

## Local developer experience

The current source provides:

```text
wagent init
wagent profile list
wagent probe <endpoint>
wagent provider-probe --mode safe|active|capability [--confirm-active-probe]
wagent doctor
wagent tui
wagent composition export
wagent composition inspect|save|list
wagent session create|list|show|archive|unarchive
wagent run "hello" --confirm-model-call --json
wagent evaluate cases.json --confirm-model-call --report report.json
```

The CLI and TUI use only public Python APIs. The current CLI/TUI foundation is `Experimental`: it covers initialization, template listing, safe/active endpoint probing, composition management/offline preview and dependency planning, local session lifecycle, per-call-confirmed configured agent runs with visible token totals, privacy-safe agent/workflow checkpoint listing, catalog tool selection, separate code-load confirmation, authority grants, exact-call-ID approval resume, exact-version workflow recovery, import-free general-plugin preview/confirmed loading/TUI unload, privacy-safe live RunEvents, and local evaluation with versioned built-in suites plus separate evaluation-tool loading confirmation. Workflow recovery, offline dependency planning, built-in evaluation suites, and general plugin operations are unpublished main capabilities; plugin package installation/upgrades remain `Planned`.

## Portable project compositions

`Implemented`: developers can name and version a framework composition, export it as a copyable code, and validate and preview risks without network access, imports, or execution. The local store keeps multiple versions and aliases while rejecting silent content conflicts. Current main can also build an offline environment/plugin plan through a replaceable resolver and explicit candidate inventory. A plan never installs packages, generates load references, or confirms code execution for the user.

A composition code carries a portable manifest, never secrets. It does not bundle arbitrary source by default and never executes untrusted plugins automatically during import. See [Portable project compositions](./docs/project-sharing.en.md).

## Documentation

- [Documentation index](./docs/README.en.md)
- [Architecture](./docs/architecture.en.md)
- [Roadmap and capability status](./docs/roadmap.en.md)
- [User guide](./docs/guide.en.md)
- [Developer guide](./docs/developer.en.md)
- [API status and plan](./docs/api.en.md)
- [Plugin system](./docs/plugin-system.en.md)
- [Models, routing, and endpoint probing](./docs/model-routing.en.md)
- [HTTP providers and vendor templates](./docs/provider-templates.en.md)
- [Tool registration, policy, and execution](./docs/tools.en.md)
- [Agent runtime and ReAct loop](./docs/agents.en.md)
- [Session lifecycle and cross-run context](./docs/sessions.en.md)
- [Locally configured agent runtime](./docs/local-runtime.en.md)
- [Workflows and node-boundary recovery](./docs/workflows.en.md)
- [Sandbox and local execution](./docs/sandbox.en.md)
- [CLI and TUI](./docs/tui.en.md)
- [Local testing, model replay, and evaluation](./docs/testing-evaluation.en.md)
- [1.x migration](./docs/migration-1x.en.md)

## Explicit non-goals

- W-Agent does not provide a hosted service or cloud control plane.
- The first release does not include tenants, organizations, billing, or SaaS administration.
- No ReAct, workflow, or model protocol implementation is hard-coded as the only option.
- Third-party plugins are never installed, upgraded, or executed without confirmation.

## License

This project is licensed under the [MIT License](./LICENSE).
