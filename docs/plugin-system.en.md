# Plugin system

English | [简体中文](./plugin-system.md)

Status: `Implemented` in `2.0.0a1`. This document defines the current microkernel plugin API. Higher-level model, agent, and workflow plugins remain on the roadmap.

## Goal

The plugin system gives models, routers, agent loops, workflows, tools, storage, sandboxes, interfaces, and evaluation modules one composition and lifecycle mechanism. First-party and third-party plugins follow the same rules.

## Entry styles

Four entry styles converge on `PluginSpec`:

1. Explicit Python construction.
2. Decorator registration.
3. YAML configuration.
4. Python entry-point discovery.

Explicit Python construction is the behavioral baseline; other entry styles receive no additional semantics.

Minimal example:

```python
from w_agent import CapabilityDeclaration, PluginManager, ScopePath, plugin


@plugin(
    name="hello-provider",
    version="1.0.0",
    provides=(CapabilityDeclaration("example.hello", version="1.0.0"),),
)
async def hello_provider(context):
    context.register("example.hello", "hello", version="1.0.0")


manager = PluginManager()
handle = await manager.load(hello_provider)
value = manager.registry.resolve("example.hello", ScopePath.application())
await handle.unload()
```

## Manifest

```yaml
name: my-model-router
version: 1.3.0
api_version: "2"
provides:
  - model.router
requires:
  - model.registry >=2.0,<3.0
optional:
  - telemetry.tracer
conflicts:
  - model.router:exclusive
scope: application
```

A plugin may provide several capabilities, but capability keys, versions, and conflicts are explicit. The current YAML loader validates reference and configuration-container structure; plugin-specific configuration-schema validation remains `Planned`.

## Lifecycle

```text
DISCOVERED → RESOLVING → LOADING → ACTIVE
                         ↘ FAILED
ACTIVE → QUIESCING → UNLOADING → DISPOSED
```

Each load owns an effect scope. Services, event handlers, background tasks, file watchers, and connections register in that scope. A failed load or unload removes resources owned by that load.

Cleanup ordering belongs to one explicit resource owner; it never depends on accidental destructor ordering between plugins.

## Registry

One capability may have multiple named providers. Resolution considers capability key, name, version, scope, and selection policy. Exclusive capability conflicts fail directly; a router or caller selects among multi-provider capabilities.

Registration returns an idempotent `Registration`. Repeated disposal succeeds, and new resolutions cannot see a removed contribution.

## Dependency changes and updates

When a provider is unloaded through `PluginManager`, the manager unloads active consumers first. Automatic unload after an arbitrary provider registration is disposed and automatic reload after dependency recovery remain `Planned`. Optional dependencies are queried explicitly at use sites and do not create hidden hard dependencies.

The Registry supports several versions under one provider name, resolves version constraints, and creates immutable snapshots. `PluginManager` currently permits only one active plugin per plugin name. Coordinated version replacement, run binding, and quiescent migration remain `Planned`.

## Scope

```text
Application → Workspace → Session → Agent → Run → Step
```

A child scope may override a parent provider. Scoped resolution is implemented; automatically destroying a scope and all resources it owns remains `Planned`. The framework has no tenant system; plugins that need another isolation dimension may extend `ScopePath`.

## Failure rules

- Missing required dependency: do not load.
- Incompatible version: do not load and report the conflict chain.
- Invalid configuration: fail during resolution.
- Partial load failure: roll back the load's effect scope.
- Cleanup failure: report the error, continue other cleanup, then report incomplete cleanup.
- Unknown plugin code: execute only after explicit installation and first-load confirmation.

## Relationship to compositions

A `CompositionManifest` references plugin names, version constraints, and configuration rather than mutating registry internals. Importing a code produces only a preview; installation and loading remain separate confirmed actions.

## Current limitations

- One plugin name cannot have multiple active instances in one `PluginManager`.
- A Registry snapshot fixes resolution results but does not yet own provider lifecycle leases.
- Dependency recovery does not automatically reload consumers.
- YAML loads `module:attribute` references and configuration only; it does not install third-party packages.
