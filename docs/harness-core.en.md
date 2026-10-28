# Harness framework core baseline

English | [简体中文](./harness-core.md)

> Release scope: the new framework core described here is included in 2.1.0. Earlier “unpublished” labels and candidate 2.0.0 metadata below record pre-release stages, not the 2.1.0 package status. See [2.1.0 notes](./releases/2.1.0.en.md); upload status is on [PyPI](https://pypi.org/project/wagent-framework/2.1.0/).

W-Agent targets a Python Harness development framework inspired by Spring IoC, DI, AOP and lifecycle management, not a fixed Harness. Developers assemble their execution systems through decorators, explicit Python or configuration. Official ReAct, Workflow, model templates and CLI/TUI are optional implementations.

This baseline was fixed on 2026-10-01 for M0–M5 implementation and acceptance. The 2.0.0 release record and previous B01–B12 baseline remain valid but do not prove this baseline complete. Source implementation, executed verification and publication must be tracked separately. Target interfaces below are not claims of published APIs.

## Current gaps and reuse decisions

| Current source | Existing responsibility | Decision |
|---|---|---|
| `container/bean_factory.py` | Definitions, constructor/some setter injection, scanning and lifecycle | Preserve legacy semantics; use explicit adapters, without sharing private caches or registering disposal twice |
| `core/decorators.py` | Component/lifecycle metadata; Retry/CircuitBreaker wrappers | Preserve names; compile declarations to unified definitions and implement missing configuration injection, not just metadata |
| `kernel/registry.py` | Capability/name/version/path lookup and revocable registrations | Retain as capability index, not an object constructor or destructor; no second object container |
| `kernel/plugins.py` | Plugin dependencies, loading/unloading and effect cleanup | Bridge component definitions or borrowed objects explicitly; each resource has exactly one disposal owner |
| `kernel/scope.py` | Hierarchical paths and visibility | Reuse paths and add lifecycle scopes; labels alone do not implement isolation or object lifetime |
| `aop/proxy_factory.py` and `kernel/events.py` | Method proxies, events and pipelines | Reuse suitable contracts and add container-managed matching/weaving; notification is not interception |
| `local_runtime.py` | Manual router/executor/ReAct construction | Migrate to a default assembly adapter while preserving the function as a compatibility entry, not another core |

These findings come from source inspection, not runtime verification this round. Existing component-chain tests are available, but do not certify the new architecture.

## Responsibilities and ownership

```text
Decorator scanning / explicit Python / configuration selection
                            ↓
          Component definitions → validation and dependency graph
                            ↓
          ApplicationContext → scoped instances and lifecycle
                  ↕                        ↓
      Plugin bridge and capability index   Default or user Harness
                                           ↑
                               Python / CLI / TUI public entries
```

The target public `ApplicationContext` assembles, starts, resolves, opens scopes and closes; it does not own a fixed agent algorithm. The registry resolves capabilities and the object container resolves dependencies. They share explicit identity mappings, not separate caches constructing the same object.

| Resource origin | Lifecycle owner | Closing rule |
|---|---|---|
| Component factory | Creating container scope | Record cleanup responsibility before initialization; release once in reverse dependency order on failure/close |
| Host-supplied instance | Host | Borrow only; do not initialize, close or guess a `close` method |
| Instance created and effect-managed by a plugin | Plugin | Container borrows; stop dependent consumers before plugin disposal |
| Component factory contributed by a plugin | Instance's container scope | No duplicate plugin disposer; unload consumers/instances before withdrawing definitions and capability references |
| Capability registration handle | Creating assembly/plugin scope | Removal changes discoverability, not Provider lifetime |

No implicit ownership transfer. A bridged legacy BeanFactory is either host-owned or managed as a whole by one cleanup hook; do not separately register its objects for the same destruction.

## Fixed assembly contracts

1. All three entry styles compile to the same component definitions. Configuration selects host-allowed definitions; strings cannot import arbitrary Python. Module loading remains an independent explicit action.
2. Definitions contain identity, factory, arguments/dependency references, lifecycle scope and optional initialization/disposal behavior. Borrowed instances have a separate definition and no implicit cleanup authority. User objects need no framework base class.
3. Before startup, reject duplicate definitions, missing/ambiguous dependencies, cycles, conflicting arguments and scope capture. Diagnostics identify component paths without configuration values, credentials or prompts.
4. No implicit same-name overrides. Select alternatives explicitly before assembly; definitions are immutable after startup. Hot replacement of active instances is outside this baseline.
5. Lifetime hierarchy follows Application → Workspace → Session → Agent → Run → Step; custom hierarchies require explicit ordering. Longer-lived components cannot directly capture shorter-lived instances. Deferred provider/factory references need separate contracts, not a validation bypass.
6. Start dependencies first and close consumers first. Initialization failures still clean created instances; resources acquired before a factory returns remain that factory's rollback responsibility. Factories return instances, not hidden unregistered background tasks.
7. Cancellation must not truncate registered cleanup. Concurrent closing shares one cleanup operation; one failure cannot prevent other disposals. Preserve primary failures and cleanup errors without silently swallowing cancellation.
8. Shutdown first rejects new runs, then waits for or explicitly cancels owned runs/streams, closes child scopes/components and finally plugins still needed by dependents. Do not guess ownership of business tasks.

## Decorator and aspect contracts

Existing `@AgentComponent`, `@ServiceComponent`, `@ToolComponent`, `@RepositoryComponent`, `@ControllerComponent`, `@PostConstruct` and `@PreDestroy` paths are preserved. M2 now compiles them into unified definitions and connects `@Configuration`/`@Bean`, qualified injection, Value binding and explicit module scanning. See [decorator development](./annotation-development.en.md) for usage, boundaries and 142 passing stage cases.

M3 pointcuts use component identity, public methods and optional tags, not private ReAct method names. Specify Before/Around/After/error/final-cleanup semantics, stable ordering and diagnostic matching. The default continuation proceeds once; retries require a separate explicit mechanism constrained by safety policy.

Define synchronous, coroutine and asynchronous-stream behavior separately. A stream's lifetime covers consumption, not just returning an iterator. Completion, failure, cancellation, explicit `aclose()` and scope close all trigger cleanup. Events notify; they do not silently replace authorization, interception or budget admission.

Ordinary Python modules and aspects are trusted host code, not isolation. Untrusted code still requires a sandbox. Business permissions, per-call approval and mandatory budget boundaries cannot live solely in removable aspects.

## Compatibility and migration

- Python 3.11+, package `w_agent`, no `w_agent.v2`.
- Preserve essential `BaseAgent.arun()`, existing decorators and BeanFactory usage. Legacy containers do not silently acquire new semantics; adapters state the boundary.
- Existing Providers/HTTP mappings, routing, tools, MCP, ReAct, Workflow, knowledge, Sessions, budgets, sharing and sandboxes migrate to unified assembly without rewriting their business protocols.
- Custom model parameters/message types use custom contracts, capabilities and adapters, not mandatory OpenAI request conversion.
- ReAct/Workflow are defaults. CLI/TUI load the same public assembly/execution entry. A frontend can display only supported content, but cannot introduce different execution semantics.
- No tenants, hosted accounts or cloud billing platform; Docker and explicitly authorized non-isolated local execution boundaries remain unchanged.

## Fixed acceptance checklist

Every item requires evidence matching its scope. Prior release tests, symbol existence or example syntax checks cannot replace new architecture acceptance.

| ID | Required behavior | Final evidence |
|---|---|---|
| H01 | Decorator scanning, injection, initialization, running and destruction connect | Instance identity and ordered lifecycle traces; failed-startup cleanup cases |
| H02 | Custom Loop, model parameters, tools and storage without core edits | Actual out-of-repository developer example, without delegating execution to default ReAct |
| H03 | Aspects handle sync/async, failures, cancellation and stream close | Behavioral tests including cleanup counts and exception propagation |
| H04 | Decorators, Python and configuration share assembly rules | Equivalent plans/traces; consistent errors and ownership outcomes |
| H05 | Official Loop, Provider and TUI are optional | User-only application starts, runs and closes without live model calls |
| H06 | No private Python/CLI/TUI assembly branch | Same public assembly through all three; nondefault Loop and approval-boundary cases |
| H07 | Reproducible bilingual tutorials | Installed-package examples outside the repository for custom Harness, support and coding; bilingual review |
| H08 | One owner per resource; safe scopes and plugin unloading | Borrowed objects untouched, owned objects closed once, repeated cancellation, dependency disposal and scope-capture cases |

H08 is a shared H01–H06 invariant, not an additional peripheral feature. Track each as not implemented / implemented but unverified / accepted; awaiting authorization is never a pass.

## Milestones and order

| Stage | Deliverable | Current state |
|---|---|---|
| M0 | Responsibilities, ownership, compatibility and fixed acceptance checklist | Baseline complete; new assembly implements single ownership |
| M1 | Context, definition compilation, instance/scope lifecycle and plugin bridge | Focused stage acceptance complete: 137 passing cases; includes [plugin bridging, legacy borrowing and configuration preflight](./application-assembly.en.md), unpublished |
| M2 | Unified decorator/configuration-factory/configuration-binding compilation | Focused stage acceptance complete: 142 passing cases; scanning, injection, lifecycle and configuration selection use M1, unpublished |
| M3 | Container-managed aspect weaving and async-stream semantics | Focused stage acceptance complete: 207 passing cases; see [application aspects](./application-aspects.en.md), unpublished |
| M4 | Existing modules and Python/CLI/TUI default assembly migration | Stage acceptance complete: 572 distinct passing cases; [default recipes, generic execution and frontend migration](./default-assembly.en.md), unpublished |
| M5 | Three tutorials, migration docs and authorized final acceptance | Accepted: 259 related tests plus offline artifacts, isolated installation and three outside-repository Python/CLI/headless-TUI examples; [final gate](./harness-acceptance.en.md), unpublished |

Order: M0 → M1 → M2/M3 → M4 → M5. Writing tests is development. Under the user's latest rule, relevant tests and static checks run automatically after completing a whole stage, not during implementation and not as a full-suite run. Installation, builds, external calls and publication still require separate approval. Each round reports implementation, evidence, unverified scope and remaining stages. No more alpha releases.

Defer additional vendor templates, advanced knowledge strategies and media/TUI decoration. Multi-agent collaboration, distributed Workflow, remote sandboxes, plugin marketplaces and advanced hot migration remain reserved, not new gates for this effort. The existing roadmap retains those capabilities, subordinate in priority to this core baseline.

## Evidence this round and next step

M5 is accepted against H01–H08. Three tutorials, migration guidance and the offline installed-artifact gate pass; [the final record](./harness-acceptance.en.md) lists commands, provenance and boundaries. No required core milestone remains. No network calls, global-environment changes, commit/push or publication occurred. Decide release/versioning separately; reserved enhancements are not automatically resumed.

## Historical stage records (not current outstanding work)

M4 connects default recipes, generic `ApplicationProject`/`ApplicationHost` execution and trusted project loading. The same custom Harness actually runs through Python, CLI and TUI; default Run/Resume/Evaluation and ordinary Workflow recovery use public assembly/execution. Batched acceptance covers 572 distinct passing cases, fixing one outdated TUI tab-list assertion; see [default assembly](./default-assembly.en.md) for scope. M5 follows with three developer tutorials, migration guidance and authorized installed-artifact/outside-repository acceptance. No installation, build, external-service access or publication occurred. M3/M2/M1 counts below are historical, not additive.

M3 now completes component aspects, sync/async calls and streams, and scope-owned cleanup, with 207 passing stage-related cases. Legacy AOP keeps its compatibility paths; new applications use the same assembly plan. M4 follows with default modules and public Python/CLI/TUI execution wired to this core. Complete developer delivery and final acceptance remain M5. Earlier stage evidence below is retained for provenance, not additive test counts.

M2 now completes decorator/configuration compilation and unified lifecycle wiring. Stage verification reported 142 passed / 1.73s (41 new M2 cases, 81 M1 regressions and 20 adjacent cases). The [bilingual decorator tutorial](./annotation-development.en.md) and source example are updated. M3 follows: component-based aspect matching/ordering and sync, async, error, cancellation and stream-close semantics. M1 evidence is retained below for provenance, not additive counts. Installed-package external acceptance and final-goal acceptance remain outstanding.

The previous round added ApplicationContext, child scopes, signature preflight, single instance ownership, startup rollback, concurrent close and cancellation cleanup after M0 decisions and plan compilation. Authorized verification reported 47 passed / 1.09s, including the earlier 15; these are included in this round's 137. Tests call the [custom Harness example](../examples/custom_harness.py), executing a user-model contract, ordinary tool and storage without official ReAct. No full regression, installed-artifact or out-of-repository acceptance, installation, build, external-service call, commit, push or publication occurred.

M1 now includes shared-registry plugin bridging, host-owned legacy singleton borrowing and configuration-schema preflight. Unified verification after completing the stage reported 137 passed / 1.72s (81 M1 cases and 56 adjacent regressions), with AST/in-memory compilation checks passing for 14 Python files. See the [stage record](./application-assembly.en.md) for commands and limits. Whole-container ownership transfer is not a compatibility promise: the host retains ownership and legacy failure semantics are not automatically upgraded. M2 decorator/configuration-equivalent compilation follows. H02/H05/H08 have partial source-runtime evidence, but H01–H08 remain unaccepted at their full scope; M1 acceptance does not complete the final goal.
