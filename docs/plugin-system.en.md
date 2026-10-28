# Plugin system

English | [简体中文](./plugin-system.md)

Status: the microkernel plugin API is `Implemented` in `2.0.0a1`. `2.0.0a4` provides import-free YAML preview, explicitly confirmed batch loading, and TUI unload controls. Host-lock-catalog sandboxed package installation with independent load confirmation is included in `2.0.0a4`. Online source discovery, automatic locking, and automatic updates remain `Planned`.

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

## YAML references and explicit authorization

```yaml
plugins:
  - entry: my_plugins.router:setup
    enabled: true
    config:
      endpoint: https://example.test
  - entry: my_plugins.optional:setup
    enabled: false
```

`2.0.0a4` uses this safe operational sequence:

```text
wagent plugin inspect --config .wagent/plugins.yml
  → parse only entry, enabled, and configuration keys; import no module
wagent plugin validate-load --config .wagent/plugins.yml --confirm-plugin-code
  → import and load enabled entries, report an active snapshot, then unload before exit
```

The TUI Plugins screen uses the same `PluginManager` and loading API. After one-shot `LOAD PLUGINS` confirmation, plugins remain active in the current TUI process. Unload requires the name-bound `UNLOAD <name>` phrase and unloads active consumers before their provider. Configuration values reach plugin code, but preview and lifecycle projections show keys only.

For same-name local replacement, use the TUI replacement controls or the persistent-in-process `wagent plugin session` command. Both require import-free configuration review, independent import approval, and exact replacement/quiescence phrases; see [local replacement entry points](./plugin-replacement.en.md#cli-and-tui-entry-points). These controls do not update other processes or installed packages.

If any import or load in a batch fails, plugins loaded earlier by that batch are unloaded in reverse order. Plugins that were already active in the manager and are outside the batch are not part of this rollback. Duplicate references fail before import, and `enabled: false` references are never imported.

### Cancellation and cleanup

Cancellation also rolls back a loading batch. Once cleanup starts, repeated caller cancellation is deferred until that owned cleanup task has finished; `CancelledError` then propagates to the caller instead of being silently treated as success. Quiesce/unload/disposer callbacks that themselves raise cancellation do not skip the remaining owned effects. Records settle to `FAILED` after partial-load rollback or `DISPOSED` after unload, and registrations/listeners are removed. Concurrent effect-scope closes wait for the same single cleanup operation. Manager shutdown attempts remaining plugins even when one cleanup reports an error or cancellation.

A cancelled replacement does not start the new setup after the old-version cleanup boundary. If cancellation occurs while publishing a loaded lifecycle notification before a handle has been delivered, the just-loaded record is also unloaded. These guarantees concern framework-owned registrations and cleanup completion, not rollback of external plugin side effects. Trusted cleanup hooks must supply their own bounded I/O and eventually return: the framework does not abandon a cleanup task on a timeout or force-kill Python code. Dedicated cancellation and adjacent plugin regressions passed; no network/package installation is involved.

## Locked installation and loading

The installation chain and lifecycle chain use different protocols and authorizations:

```text
CompositionPlan + PluginInstallCatalog
  → plan_plugin_installations() (offline, no imports)
  → user confirms exact request digest, network, and package-code execution
  → PackageInstaller / SandboxPipPackageInstaller
  → PluginInstallResult (tree digest + local site + entry)
  → user separately confirms plugin-code loading
  → load_installed_plugin_references() → PluginManager
```

`PackageInstaller` is an open protocol, so an application may replace pip, the package format, internal registry, or remote builder. The default implementation accepts only a complete SHA-256 wheel closure, forbids sdists and implicit dependency resolution, and uses the caller-selected `SandboxProvider`. The offline plan shows the index scheme, host, and port so users can review the network destination. Docker is the CLI/TUI default; the installer mounts only a fresh empty staging directory into Docker and copies the verified site to its final location after closing the sandbox, avoiding exposure of the whole local state directory to package-install code. `UnsafeLocalSandboxProvider` is available only after explicit host-access acknowledgement and cannot be isolated by staging. The install-tree digest is recomputed before entering `PluginManager`; verification rejects symlinks, precompiled bytecode, and `__pycache__` instead of ignoring files Python might execute. After import but before setup, the entry module file must belong to the verified site and the plugin name/version must match the lock. Import itself can execute code, so independent load authorization is still required. Import-path leases are released with the installed-plugin batch. Loading fails closed when an entry module is already present in the process's `sys.modules`, avoiding code cached from another location. Normal Python imports cannot guarantee complete module unloading and may create bytecode caches during use, so a fresh process or reinstall may be required before loading again or switching a same-name version; hot migration is not an existing capability.

The default pip command uses `--isolated` to ignore pip environment variables and user configuration. Image-global/site configuration and network proxies remain host concerns, so the origin preview does not guarantee a single network destination. Private-index authentication needs a host-provided `PackageInstaller`.

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

The Registry supports several versions under one provider name, resolves version constraints, and creates immutable snapshots. `PluginManager` permits only one active plugin per plugin name. Current worktree adds [explicit local replacement](./plugin-replacement.en.md): preview the new instance and affected consumers, explicitly confirm host quiescence, then stop and replace under the lifecycle lock. Consumers are not automatically restarted and external effects are not rolled back. Run binding, automatic draining, and state migration remain `Planned`.

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
- Unknown package and plugin code: installation and loading require independent confirmations; a successful install does not import, register, or grant capabilities.

## Relationship to compositions

A `CompositionManifest` references plugin names, version constraints, and configuration rather than mutating registry internals. Importing a code produces only a preview; installation and loading remain separate confirmed actions.

## Current limitations

- One plugin name cannot have multiple active instances in one `PluginManager`.
- A Registry snapshot fixes resolution results but does not yet own provider lifecycle leases.
- Dependency recovery does not automatically reload consumers.
- YAML loads strict `module:attribute` references and configuration only; package installation uses a separate lock catalog and authorization protocol and is never triggered implicitly from YAML.
- CLI `validate-load` is an ephemeral validation; use the Python API or TUI for persistent in-process plugin state.
- The framework does not currently discover sources online, generate locks, auto-upgrade, or silently hot-migrate a same-name plugin.
