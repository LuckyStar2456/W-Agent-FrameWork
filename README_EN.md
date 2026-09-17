# W-Agent

English | [简体中文](./README.md)

W-Agent is an open-source Python agent development framework for local developers. It is not a hosted platform or a fixed harness. It provides stable, extensible protocols and freely composable modules so developers can replace model, routing, agent-loop, workflow, tool, state, sandbox, and interface implementations.

The current stable release is `1.5.2`; the main branch is now developing `2.0.0a1`. The 1.x engineering foundation remains available, the Phase 1 microkernel and Phase 2A model foundation are implemented, and the remaining next-generation capabilities are delivered in roadmap phases. Documentation uses explicit status labels so planned capabilities are never presented as current features.

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

The following Phase 1 capabilities are `Implemented` in the current `2.0.0a1` source:

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
- An OpenAI-compatible Chat Completions provider with a replaceable transport for local or remote services that declare compatibility.
- A pluggable generic HTTP request-mapping layer with JSON/SSE/NDJSON transport.
- Native Anthropic, Gemini, Ollama, and Qwen templates, plus DeepSeek, GLM, Qwen-compatible, and Turbo AI/SIAM.AI template registration.
- A `ModelExecutor` with one call by default, explicitly enabled bounded retry/failover, timeouts, and prompt-free attempt records.

`BaseAgent` remains a minimal abstraction. Dedicated OpenAI Responses and vLLM differences, token-pass-through execution, a standard ReAct loop, workflows, checkpoints, a Docker coding sandbox, portable composition codes, and a TUI remain `Planned` and must not be treated as existing features. Vendor templates have fake-transport tests, not live validation for every remote model.

## Next-generation module map

```text
Applications        Customer support / Coding / User compositions
Runtime             Agent Loop / Workflow / Session / Checkpoint
Capabilities        Models / Router / Tools / RAG / Memory / Sandbox
Microkernel         Plugin / Registry / Lifecycle / Scope / Events
Infrastructure      Storage / Telemetry / CLI / TUI / Evaluation
```

Next-generation APIs will be exported directly from `w_agent`; no `w_agent.v2` namespace will be introduced. A minimal compatibility layer will keep essential 1.x APIs available.

## Install the current release

```bash
pip install wagent-framework
```

Optional dependencies:

```bash
pip install "wagent-framework[fastapi,langchain,opentelemetry]"
pip install "wagent-framework[models]"
pip install "wagent-framework[wasm]"
```

PyPI 1.x supports Python 3.9+. The current `2.0.0a1` source requires Python 3.11+.

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

This is a 1.x compatibility example; it does not imply that the next-generation agent runtime is implemented.

## Planned local developer experience

The following commands are `Planned` and are not all available in the current release:

```text
wagent init
wagent config validate
wagent plugins list
wagent profile resolve
wagent probe
wagent doctor
wagent run
wagent tui
wagent composition export
wagent composition import
```

The CLI and TUI will use only public Python APIs. The TUI is planned to cover model configuration and probing, plugin management, profile selection, interactive runs, workflow state, checkpoint recovery, sandbox approvals, and event inspection.

## Portable project compositions

`Planned`: developers will be able to name and version a framework composition, then export it as a copyable code. Import first previews, validates, and resolves dependencies, after which the user explicitly confirms installation or loading.

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
- [Sandbox and local execution](./docs/sandbox.en.md)
- [CLI and TUI](./docs/tui.en.md)
- [1.x migration](./docs/migration-1x.en.md)

## Explicit non-goals

- W-Agent does not provide a hosted service or cloud control plane.
- The first release does not include tenants, organizations, billing, or SaaS administration.
- No ReAct, workflow, or model protocol implementation is hard-coded as the only option.
- Third-party plugins are never installed, upgraded, or executed without confirmation.

## License

This project is licensed under the [MIT License](./LICENSE).
