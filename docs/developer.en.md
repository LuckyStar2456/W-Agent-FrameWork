# W-Agent developer guide

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./developer.md)

> Release scope: the new framework core described here is included in 2.1.0. Earlier “unpublished” labels and candidate 2.0.0 metadata below record pre-release stages, not the 2.1.0 package status. See [2.1.0 notes](./releases/2.1.0.en.md); upload status is on [PyPI](https://pypi.org/project/wagent-framework/2.1.0/).

Start with [Develop your own Harness](./harness-development.en.md): explicit custom assembly, annotated support and configured coding. These use the unpublished framework core. [Contexts](./application-assembly.en.md), [decorators](./annotation-development.en.md), [aspects](./application-aspects.en.md) and [default recipes](./default-assembly.en.md) share one plan and lifecycle. Delivery evidence and remaining boundaries live in [M5 acceptance](./harness-acceptance.en.md). Released component extensions remain below.

Available in 2.0.0: [durable Run/Session usage links](./service-usage-links.en.md), [structural/overlapping splitting](./knowledge-splitting.en.md) and [raw-archive CLI entries](./knowledge-archive-entries.en.md). Links precede preparation, default splitting preserves v1, and export only creates new files. All are Experimental features included in 2.0.0; see [acceptance and remaining modules](./acceptance-2026-10-01-links-splitting-archives.en.md).

## 1. Development baseline

This guide targets the published `2.0.0` release. See the [release record](./acceptance-2026-10-01-stable-release.en.md) for verification evidence, the [stable baseline](./stable-release-baseline.en.md) for basic scope, and the [roadmap](./roadmap.en.md) for capability status. Historical alpha records cover only their corresponding versions. The Phase 1 microkernel, Phase 2 model foundation, Phase 3 agent/tool foundation, and Phase 4 local-workflow foundation are implemented, while 1.x APIs remain available. Every new capability updates both Chinese and English documentation and receives both a release-boundary note and a status label.

Development constraints:

- Python 3.11+.
- An asynchronous kernel with synchronous convenience only at user boundaries.
- Public APIs exported directly from `w_agent`, with no `w_agent.v2` namespace.
- First-party defaults use only public protocols and the public registry.
- Every registration, task, and resource has an explicit lifecycle owner.

## 2. Current repository layout

Status: `Implemented`.

```text
w_agent/
├── application/     # Unified assembly, context, decorators, aspects and execution
├── local_application.py # Optional default Runtime/Workflow recipes
├── aop/             # Pointcuts, advice, and proxies
├── agents/          # Run contracts and replaceable ReAct loop
├── config/          # Dynamic configuration
├── container/       # IOC and bean lifecycle
├── core/            # 1.x Agent, decorators, events, and Doctor
├── deployment/      # FastAPI example integration
├── distributed/     # Redis locks
├── lifecycle/       # Initialization and disposal
├── kernel/          # Plugins, registry, scopes, and event pipelines
├── models/          # Model protocols, registry, routing, and probing
├── observability/   # Logs, metrics, tracing, health
├── resilience/      # Timeouts and bulkheads
├── sandbox/         # Next-generation contracts, registry, Docker, and explicit local backend
├── scanner/         # AST component scanning
├── security/        # MCP authentication
├── skills/          # Skills and sandboxes
├── testing/         # Test helpers
├── tools/           # Tool registry, policy, execution, Python template, and LangChain compatibility
└── workflows/       # DAG, state graph, Python workflow, stores, and local engine
```

The ReAct runtime and local workflow engine are independent of `BaseAgent.arun()`. Implemented durable sessions and composition adapters also build on public contracts.

## 3. Plugin design rules

Status: `Implemented` in `2.0.0a1`.

Every capability distinguishes Definition, Provider, and Consumer roles. Plugins depend on stable definitions rather than concrete providers.

A plugin manifest contains:

```yaml
name: example-router
version: 1.0.0
api_version: "2"
provides:
  - model.router
requires:
  - model.registry >=2.0
optional:
  - telemetry.tracer
scope: application
```

Implementation requirements:

- Validate dependencies, versions, conflicts, and configuration before loading.
- Return disposable handles for registrations.
- Roll back registrations when loading fails.
- Quiesce before releasing resources during unload.
- Never silently skip a plugin because configuration is missing.
- Plugin updates do not alter an active run's resolved snapshot by default.

See [Plugin system](./plugin-system.en.md).

## 4. Choosing an extension point

| Goal | Extension |
|---|---|
| New model or private parameters | `ModelProvider` and namespaced extensions |
| New routing algorithm | `RoutingPolicy` |
| New reasoning path | `AgentLoop` |
| Intercept a loop phase | Event/pipeline plugin |
| New workflow execution | `WorkflowEngine` |
| New tool source | `ToolBinding` / `ToolRegistry` / `ToolExecutor` |
| New isolation environment | `SandboxProvider` |
| New storage | Session, checkpoint, or memory provider |
| New interface | Public runtime APIs and event streams |

Do not modify the default agent loop for a new capability unless the public protocol cannot express that capability.

## 5. Configuration and composition

Four entry styles produce the same `PluginSpec`:

1. Explicit Python construction is the behavioral baseline.
2. Decorators are a syntax convenience.
3. YAML configuration is parsed and validated into the same specification.
4. Python entry points discover independently distributed plugins.

Configuration does not evaluate arbitrary Python expressions. Secrets enter through environment variables or credential references and never appear in composition codes.

When distributing plugins, a manifest declares portable constraints only. A separate host lock catalog pins the plugin version, `module:attribute`, complete wheel dependency closure, and artifact SHA-256 values. Custom source resolution implements `CompositionDependencyResolver`; a custom package format or installation backend implements `PackageInstaller`. Offline planning, package installation, and plugin loading remain three independent stages. A resolver or configuration parser must never access the network or execute code implicitly.

## 6. Types and extension fields

Stable protocols use dataclasses, Protocols, Enums, and Pydantic boundary models. Trusted in-process values are not redundantly parsed; file, network, plugin-configuration, persistence, and model-output boundaries are validated.

Extensions use namespaces:

```python
extensions={
    "vendor.reasoning_effort": "high",
    "my_plugin.cache_key": "...",
}
```

A plugin cannot modify another plugin's namespace. Core fields change only through formal state-transition APIs.

## 7. Concurrency, cancellation, and shutdown

- One lifecycle owner represents each asynchronous operation.
- `asyncio.TaskGroup` owns child tasks of the same operation.
- Cancellation propagates to model streams, tools, workflows, and sandboxes.
- Shutdown rejects new work, waits for quiescence, then releases resources.
- Assemblies that own providers/transports expose idempotent asynchronous cleanup; short-lived CLI/TUI paths run and close them in the same event loop.
- Dependency removal and plugin updates wait for affected work to reach a safe point.
- Background tasks cannot outlive their owner and continue mutating an unloaded service.

## 8. Security rules

- Docker/OCI is the default execution backend for coding agents, with no-network and bounded fail-closed defaults.
- `UnsafeLocalSandboxProvider` requires a process-local `UnsafeLocalAuthorization` created explicitly by the user.
- A composition import cannot carry or grant local-execution permission.
- Sandboxes fail closed when unavailable.
- Plugin installation, upgrade, and first execution require explicit actions.
- Default package installation accepts only exact versions, a complete hashed wheel closure, and an explicit source. Install authorization binds the request digest and cannot replace plugin-load authorization.
- Logs, events, and exported manifests contain no credentials.

## 9. Test requirements

First-release capabilities cover at least:

- Protocol and configuration unit tests.
- Provider/Consumer composition tests.
- Registration disposal and plugin unload tests.
- Missing dependency, version conflict, and failed-load rollback tests.
- Cancellation, timeout, and shutdown tests.
- Event recording and replay tests.
- Real composition tests for customer-support or coding profiles.

Model tests prefer deterministic mocks such as `ScriptedModelProvider`. Real-API tests are opt-in and never expose credentials. Model record/replay requires explicit sensitive-content authorization and protected cassette files; evaluation reports omit prompts, outputs, and exception bodies by default. See [Local testing, model replay, and evaluation](./testing-evaluation.en.md).

## 10. Documentation rules

- Update a Chinese file and its `.en.md` English counterpart together.
- README files describe verifiable current behavior and clearly labeled plans.
- New capabilities update architecture, roadmap, API, and the owning topic page.
- A `Reserved` capability is not written as an implementation commitment or current API.
- Planned API examples are explicitly marked as non-executable design examples.

## 11. Compatibility policy

Because 1.x adoption is limited, only basic compatibility is retained. Next-generation APIs take the top-level `w_agent` namespace. The implemented `LegacyAgentAdapter` strictly bridges old `BaseAgent.arun()` calls into text workflow nodes. New capabilities are not added to 1.x abstractions, and other bridges receive demand-driven review.

See [1.x migration](./migration-1x.en.md).
