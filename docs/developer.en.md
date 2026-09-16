# W-Agent developer guide

English | [简体中文](./developer.md)

## 1. Development baseline

The current repository version is `2.0.0a1`: the Phase 1 microkernel is implemented and 1.x APIs remain available. Every new capability updates both Chinese and English documentation and receives a status label.

Next-generation targets:

- Python 3.11+.
- An asynchronous kernel with synchronous convenience only at user boundaries.
- Public APIs exported directly from `w_agent`, with no `w_agent.v2` namespace.
- First-party defaults use only public protocols and the public registry.
- Every registration, task, and resource has an explicit lifecycle owner.

## 2. Current repository layout

Status: `Implemented`.

```text
w_agent/
├── aop/             # Pointcuts, advice, and proxies
├── config/          # Dynamic configuration
├── container/       # IOC and bean lifecycle
├── core/            # 1.x Agent, decorators, events, and Doctor
├── deployment/      # FastAPI example integration
├── distributed/     # Redis locks
├── lifecycle/       # Initialization and disposal
├── observability/   # Logs, metrics, tracing, health
├── resilience/      # Timeouts and bulkheads
├── scanner/         # AST component scanning
├── security/        # MCP authentication
├── skills/          # Skills and sandboxes
├── testing/         # Test helpers
└── tools/           # LangChain adapter
```

The planned microkernel and runtime will progressively refactor this foundation; they cannot be delivered by continuing to add behavior to `BaseAgent.arun()`.

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
| New tool source | `ToolProvider` / `ToolExecutor` |
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
- Dependency removal and plugin updates wait for affected work to reach a safe point.
- Background tasks cannot outlive their owner and continue mutating an unloaded service.

## 8. Security rules

- Docker/OCI is the default execution backend for coding agents.
- `UnsafeLocalSandbox` requires explicit authorization by the local user.
- A composition import cannot carry or grant local-execution permission.
- Sandboxes fail closed when unavailable.
- Plugin installation, upgrade, and first execution require explicit actions.
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

Model tests prefer deterministic mocks. Real-API tests are opt-in and never expose credentials.

## 10. Documentation rules

- Update a Chinese file and its `.en.md` English counterpart together.
- README files describe verifiable current behavior and clearly labeled plans.
- New capabilities update architecture, roadmap, API, and the owning topic page.
- A `Reserved` capability is not written as an implementation commitment or current API.
- Planned API examples are explicitly marked as non-executable design examples.

## 11. Compatibility policy

Because 1.x adoption is limited, only basic compatibility is retained. Next-generation APIs take the top-level `w_agent` namespace, while a compatibility adapter carries old interfaces such as `BaseAgent`. New capabilities are not added to 1.x abstractions.

See [1.x migration](./migration-1x.en.md).
