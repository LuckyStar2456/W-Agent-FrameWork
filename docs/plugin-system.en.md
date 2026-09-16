# Plugin system

English | [简体中文](./plugin-system.md)

Status: `Planned`. This document defines the next-generation plugin system. Version 1.5.2 does not implement these APIs.

## Goal

The plugin system gives models, routers, agent loops, workflows, tools, storage, sandboxes, interfaces, and evaluation modules one composition and lifecycle mechanism. First-party and third-party plugins follow the same rules.

## Entry styles

Four entry styles converge on `PluginSpec`:

1. Explicit Python construction.
2. Decorator registration.
3. YAML configuration.
4. Python entry-point discovery.

Explicit Python construction is the behavioral baseline; other entry styles receive no additional semantics.

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

A plugin may provide several capabilities, but capability keys, versions, and conflicts are explicit. Configuration is schema-validated before loading.

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

When a required dependency disappears, a consumer stops accepting work and unloads. It may resolve and load again when the dependency returns. Optional dependencies are queried explicitly at use sites and do not create hidden hard dependencies.

A plugin update creates a new version instance. New runs use the new resolved snapshot; active runs keep the old snapshot until completion or an explicitly supported quiescent migration point. The first release does not hot-swap arbitrary execution positions.

## Scope

```text
Application → Workspace → Session → Agent → Run → Step
```

A child scope may override a parent provider. Destroying a scope removes all registrations and resources it owns. The framework has no tenant system; plugins that need another isolation dimension may extend `ScopePath`.

## Failure rules

- Missing required dependency: do not load.
- Incompatible version: do not load and report the conflict chain.
- Invalid configuration: fail during resolution.
- Partial load failure: roll back the load's effect scope.
- Cleanup failure: report the error, continue other cleanup, then report incomplete cleanup.
- Unknown plugin code: execute only after explicit installation and first-load confirmation.

## Relationship to compositions

A `CompositionManifest` references plugin names, version constraints, and configuration rather than mutating registry internals. Importing a code produces only a preview; installation and loading remain separate confirmed actions.
