# Application assembly and lifecycle

English | [简体中文](./application-assembly.md)

> Release scope: the new framework core described here is included in 2.1.0. Earlier “unpublished” labels and candidate 2.0.0 metadata below record pre-release stages, not the 2.1.0 package status. See [2.1.0 notes](./releases/2.1.0.en.md); upload status is on [PyPI](https://pypi.org/project/wagent-framework/2.1.0/).

Status: M1 explicit assembly, application/child scopes, plugin registry bridging, legacy singleton borrowing and configuration preflight are implemented and passed focused stage acceptance. Unpublished and not included in 2.0.0. This is the explicit Python entry for the [Harness core baseline](./harness-core.en.md). M2 [decorator/configuration compilation](./annotation-development.en.md) also passed stage acceptance; M3 [application aspects](./application-aspects.en.md) also passed stage acceptance.

## Unified definitions

- `ComponentDefinition` describes a factory, named dependencies, host arguments, scope and optional lifecycle hooks. Runtime-created instances belong to their creating container scope.
- `BorrowedComponent` describes an existing host/plugin instance without initialization/disposal authority. The external owner must keep it valid for its declared scope.
- `ComponentRef` explicitly references another definition without importing modules, inferring types or contacting models.
- `compile_assembly()` returns a dependency-first `AssemblyPlan` without creating objects or invoking hooks. `ApplicationContext` executes the plan and manages instances only after explicit startup.

```python
from w_agent import (
    BorrowedComponent, ComponentDefinition, ComponentRef, compile_assembly,
)

class CustomHarness:
    def __init__(self, store, vendor_options):
        self.store = store
        self.vendor_options = vendor_options

host_store = {}
plan = compile_assembly([
    ComponentDefinition(
        "my-harness",
        CustomHarness,
        dependencies={"store": ComponentRef("store")},
        arguments={"vendor_options": {"custom_mode": "developer-defined"}},
    ),
    BorrowedComponent("store", host_store),
])
# Expected plan.startup_order: ("store", "my-harness").
# No CustomHarness is created or run; this example has not been executed.
```

Custom parameters need no OpenAI field mapping. Mapping structure is copied into read-only views, but values remain host objects, without promises of deep freezing, serialization or cross-process sharing. Object values, factories and hooks are excluded from default definition repr; component/dependency names remain visible and should not contain secrets.

## Plan validation

Currently rejects duplicate identities, missing dependencies, cycles, conflicting dependency/explicit parameters, invalid parameter names, undeclared scopes and longer-lived objects directly capturing shorter-lived dependencies. The default is the existing six-level scope order. Custom levels require explicit `scope_order`, without reversing built-in levels. A plan is neither authorization nor proof of managed instance lifetime.

Topological ordering is nonrecursive. Independent components enter the queue in input order; consumers follow when all dependencies are ready. Different input permutations need not have identical startup order; decorator/configuration adapters must later normalize ordering consistently. Direct `AssemblyPlan` construction also validates dependency order and cannot bypass these checks.

Compilation does not invoke component factories/hooks or dynamically import modules. Inputs are trusted Python objects; custom iterables/mappings can themselves execute host code, so this is not an untrusted-configuration parser.

## Remaining work and verification boundary

M1 implementation scope is complete; stage acceptance is recorded below. M2 now compiles [decorators, configuration and type/qualified injection](./annotation-development.en.md) into these definitions; remaining M4–M5 follow the baseline. Direct `ComponentDefinition` usage does not scan `@PostConstruct` / `@PreDestroy`: supply explicit hooks. M2 compilers generate those hooks. Existing legacy-container hooks remain that container's responsibility.

On 2026-10-01, unified M1 verification in the existing isolated Python 3.11.9 environment reported 137 passed / 1.72s: planning 15, context 32, configuration 13, legacy adaptation 5 and plugin bridging 16, totaling 81 core cases, plus 56 adjacent container/registry/plugin lifecycle and replacement regressions. The earlier 47 are included, not additive. AST and in-memory compilation checks passed for 14 Python files. Scoped `git diff --check` reported no whitespace errors in tracked files, only CRLF notices.

Tests executed the custom Harness example and a combined legacy singleton → registry → custom Harness → Run cleanup scenario, covering initialization failures, repeated cancellation, single cleanup ownership, export-conflict rollback and cross-manager misuse. No full-suite, installed-package/out-of-repository acceptance, installation, build, real external call or publication occurred. The user now authorizes relevant verification automatically after a complete stage, with no testing during implementation. Installation, builds, external calls and publication still require separate approval.

Reproduction scope: `python -m pytest tests/test_application_planning.py tests/test_application_context.py tests/test_application_configuration.py tests/test_application_legacy.py tests/test_application_plugins.py tests/test_container.py tests/test_kernel_registry.py tests/test_kernel_plugins.py tests/test_plugin_cancellation.py tests/test_plugin_replacement.py -q`.

## Plugins and the capability registry

`ApplicationPlugin` implements the existing plugin protocol and loads through `PluginManager.load()`, without introducing another manager or registry. `CapabilityImport("store", CapabilityRequirement("storage"))` resolves a capability by name, version and visible path into a borrowed component. `CapabilityExport("harness", CapabilityDeclaration("harness"))` exposes the identical application instance. Only application-scoped instances may be exported, avoiding stale run objects in the registry.

```python
from w_agent import (
    ApplicationPlugin, CapabilityDeclaration, CapabilityExport,
    ComponentDefinition, PluginManager, ScopePath,
)

async def plugin_example():
    manager = PluginManager()
    module = ApplicationPlugin(
        name="custom", version="1",
        components=[ComponentDefinition("service", lambda: {"custom": True})],
        exports=[CapabilityExport("service", CapabilityDeclaration("custom-service"))],
    )
    try:
        await manager.load(module)
        assert manager.registry.resolve("custom-service", ScopePath.application()) is module.application.resolve("service")
    finally:
        await manager.close()
```

The plugin effect scope owns the context as a whole; the context owns factory results. Revoking a registration removes discovery, not the object. Dependent consumers stop before exports and applications are disposed. Cascading uses the existing manager's conservative capability-based rules, not a minimal version-specific unload set. Direct registrations outside managed plugins retain host ownership.

A bridge instance is one-shot; reload with a fresh instance. Hosts must stop existing tasks/streams before unload; raw object references are not revocable leases. `scope` controls registry visibility, while the internal application root uses the plugin name; it does not claim the external path's lifecycle. Nonempty plugin `config` is rejected: trusted Python must first produce argument-bearing definitions rather than silently ignoring configuration.

## Legacy container compatibility

`BeanFactory.existing_singleton(name)` reads an already-created singleton without creating objects or exposing early references. `borrow_legacy_singletons(factory, {"store": "legacy-store"})` returns borrowed definitions accepted by `compile_assembly()` or `ApplicationPlugin`.

The host initializes the old container before building borrowed definitions and destroys it only after closing all new applications. This adapter neither takes ownership of the whole BeanFactory nor duplicates its cache or lifecycle hooks. Uncreated singletons and prototypes cannot be borrowed. Hosts must not destroy borrowed objects early. Legacy startup/cleanup failure semantics are not upgraded to new-context guarantees; migrate to explicit factories to obtain those guarantees. This is basic 1.x compatibility, not a second managed container.

## Configuration preflight

`ComponentDefinition(..., validate_arguments=validator)` validates after all factory signatures and before any factory runs, including unopened child scopes. A validator receives the read-only argument mapping and synchronously returns `None` or raises; it does not type-inject dependencies. Validators are trusted host code; nested mutable values are not deeply frozen. Avoid resource creation and other side effects.

`ConfigurationSchema({"count": ConfigurationField(int)})` provides required-field, strict-type and unknown-field checks; `required=False` allows omission and `allow_extra=True` allows additional fields. Strict types distinguish `bool` from `int`, with no coercion or default insertion. Supply your own validator for nested structures, ranges, subclasses or vendor-specific arguments. Errors identify the component without argument values or custom-validator exception text; keep credentials out of identity names. File selection, default binding and decorator-equivalent compilation belong to M2.

## Explicit application entry

Constructing `ApplicationContext(plan)` creates no components; `await start()` or `async with` starts it. Factory/hook signatures across the entire plan are checked before creation. Uninspectable host callables need explicit Python factory adapters. Once active, synchronous `resolve(name)` returns initialized instances without lazy loading or granting permissions.

```python
from w_agent import ApplicationContext

# Continue with plan above; call run_application() from your async entry.
async def run_application():
    async with ApplicationContext(plan) as app:
        harness = app.resolve("my-harness")
        assert harness.store is host_store
```

See [custom_harness.py](../examples/custom_harness.py) for a runnable source example: a custom model with `compose(..., dialect=...)`, an ordinary Python tool, custom Harness and memory Journal assembled through public APIs without default ReAct. It makes no real model requests, file writes or shell calls. Ordinary tools remain trusted code, not sandboxed/approval-managed merely because the container owns them. Source users can run `python -m examples.custom_harness`; published 2.0.0 lacks these APIs and is not claimed to support this example.

## Child scopes and cleanup rules

- Application startup creates only application components. `async with app.scope("run", "r1") as run:` creates run components; instances are reused in a scope, distinct across sibling scopes and shared from ancestors.
- Children require active parents and a shorter lifetime. Unneeded levels can be skipped, but a session dependency requires an actually open session ancestor, not merely a run path label.
- Cleanup responsibility is recorded after factory return and before initialization. Sync/async factories and hooks work; created objects still get disposed if initialization fails.
- Borrowed objects have no cleanup hooks and no guessed `close()`. Factories cannot return an already owned/borrowed instance. Use borrowed definitions or dependency references for shared constants/host objects.
- Close rejects new resolution/child-scope operations, closes all children, then disposes local instances in reverse dependency order. Repeated/concurrent close shares one result; cleanup failures do not retry disposal of the same object.
- Cancelling startup closes that scope, including races with successful startup. Cancelling any concurrent startup waiter cancels the shared startup, not just that waiter. Repeated cancellation does not truncate cleanup; primary and cleanup failures are retained in exception groups.
- Factories/lifecycle hooks must not start or close their own context tree, avoiding reentrant deadlocks. One tree belongs to one asyncio event loop. Closed/failed scopes cannot restart; create a new context.
- [M3 application aspects](./application-aspects.en.md) now own matched proxy calls and streams, draining them before scope disposal. Unmatched methods and independently started host tasks/streams still require host-managed shutdown. Nonreturning factories/cleanup hooks may block shutdown. Default-module and frontend execution wiring remains M4.
