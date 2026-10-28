# Migrating from 1.x

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./migration-1x.md)

> Release scope: the new framework core described here is included in 2.1.0. Earlier “unpublished” labels and candidate 2.0.0 metadata below record pre-release stages, not the 2.1.0 package status. See [2.1.0 notes](./releases/2.1.0.en.md); upload status is on [PyPI](https://pypi.org/project/wagent-framework/2.1.0/).

The unpublished new core preserves decorator names but requires explicit `compile_decorated()` and `ApplicationContext` to obtain new lifecycle semantics. Legacy BeanFactory keeps its old behavior; `borrow_legacy_singletons()` can borrow created singletons without registering disposal in both containers. New contexts invoke only marked lifecycle methods, not guessed names; replace `prototype` with an explicit run/step scope. See [decorator migration usage](./annotation-development.en.md) for configuration factories, qualifiers and Value binding.

Status: `Experimental`. `LegacyAgentAdapter` is implemented; bridges from EventBus, configuration, and legacy sandboxes into current protocols remain `Planned`.

## Strategy

Next-generation public APIs replace `w_agent` directly; there is no `w_agent.v2`. Because 1.x adoption is limited, the project guarantees basic migration rather than maintaining two complete frameworks indefinitely.

- Existing 1.x releases remain installable and runnable during the compatibility window.
- Essential old APIs move to a compatibility module or are exported through adapters.
- New model, workflow, plugin, and sandbox capabilities exist only in the new protocols.
- Deprecated APIs carry the `Deprecated` label and an explicit replacement path.

## BaseAgent

Current:

```python
class BaseAgent:
    async def arun(self, prompt: str) -> str: ...
```

`LegacyAgentAdapter` wraps an old agent as an ordinary workflow node. Input and output are text by default; non-text input or structured output requires an explicit application mapper. It does not fabricate streaming events, tool calls, token usage, checkpoints, or capability declarations, and it cannot forcibly interrupt an in-flight legacy `arun()` that does not cooperate with cancellation.

```python
from w_agent import (
    LegacyAgentAdapter,
    LocalWorkflowEngine,
    PythonWorkflowDefinition,
    WorkflowContext,
)

adapter = LegacyAgentAdapter(old_agent)
definition = PythonWorkflowDefinition(
    "legacy-task",
    adapter.workflow_node("legacy").handler,
)
result = await LocalWorkflowEngine().start(
    definition,
    WorkflowContext("workflow-1", input="hello"),
)
```

`legacy_agent_workflow_node("legacy", old_agent)` is the convenience constructor. The adapter checks the workflow's cooperative cancellation token before and after the legacy call; timely cancellation inside the old agent remains the responsibility of that implementation.

## BeanFactory and component decorators

Legacy BeanFactory retains its semantics. New assembly uses `AssemblyPlan` / `ApplicationContext`; Registry only indexes capabilities. Component decorators compile into `ComponentDefinition`, not automatically into `PluginSpec`. Use `ApplicationPlugin` explicitly for a plugin boundary. Borrowing old singletons does not transfer disposal ownership.

## New-core migration map (unpublished)

| Existing usage | New usage | Boundary |
|---|---|---|
| Manual construction and cleanup | `compile_assembly` + `ApplicationContext` | Owned factories versus borrowed external instances; no duplicate cleanup |
| Decorators / BeanFactory | `compile_decorated` or `compile_configured` | Explicit loaded-module scans and allowlisted configuration catalogs |
| Manual `ProxyFactory` proxies | `Aspect` and plan `aspects` | No automatic upgrade; self-calls and undeclared special methods bypass new proxies |
| `assemble_local_runtime` | `async with open_local_runtime(...) as runtime` | Old synchronous function remains; new entry starts on enter and executes through Host |
| Custom business entry | `ApplicationProject(plan, operations)` | Python/CLI/TUI reuse the project; CLI/TUI inputs/results must be JSON-expressible |

Migration is opt-in, never an import-time rewrite of old containers. Start with the runnable [three Harness tutorials](./harness-development.en.md). Declare custom plugin scope hierarchies with `ApplicationPlugin(..., scope_order=...)`; borrowed imports retain scope-capture checks.

## EventBus

A bridge can forward ordinary notifications from the 1.x `EventBus`. Next-generation typed pipelines, durable RunEvent values, and lifecycle effects cannot map completely to the old event bus.

## Configuration

Ordinary `DynamicConfigManager` values can migrate to a next-generation configuration provider. Secrets become credential references; plugin manifests and composition codes never persist keys.

## Skill sandboxes

Wasm and nsjail implementations are planned to adapt to `SandboxProvider`. Old calls remain during the compatibility window, but coding agents migrate to unified sandbox handles and the Docker/OCI default backend.

## Top-level exports

When a new API and old API share a name, migration release notes list the replacement explicitly. Runtime code never guesses whether the caller intended the old or new API based on argument types.

The next-generation CLI uses `wagent`; the existing `w-agent` command remains a compatibility alias during migration.

## Migration completion criteria

- Existing basic agent examples run through an adapter. `Implemented`
- Old container and configuration usages have documented replacements.
- Deprecation warnings name the target API and removal release.
- Chinese and English migration docs, tests, and release notes stay synchronized.
