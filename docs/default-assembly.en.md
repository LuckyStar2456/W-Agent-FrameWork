# Container assembly for default components

English | [简体中文](./default-assembly.md)

> Release scope: the new framework core described here is included in 2.1.0. Earlier “unpublished” labels and candidate 2.0.0 metadata below record pre-release stages, not the 2.1.0 package status. See [2.1.0 notes](./releases/2.1.0.en.md); upload status is on [PyPI](https://pypi.org/project/wagent-framework/2.1.0/).

This is unpublished M4 implementation, **accepted at stage scope with 572 distinct passing cases**. Existing ReAct and Workflow become optional `ApplicationContext` recipes, not a mandatory Harness. Python and CLI/TUI default Run/Resume/Evaluation and ordinary Workflow recovery now use the public `ApplicationHost`; custom projects share the same loading and execution entry. Existing approval chains retain their public authorization adapters, without bypassing approval.

## Select a default recipe

`compile_local_runtime(config, state_root, ...)` returns an `AssemblyPlan` without creating Providers, reading credentials, creating storage directories or calling models. Factories run at `ApplicationContext.start()`; starting stores may create directories. The default Runtime retains the existing `ModelMessage`, `AgentDefinition` and `RunResult` contracts. For different data protocols, compile your own components without this recipe.

```python
from w_agent import ApplicationContext, compile_local_runtime

async def answer(config, prompt):
    plan = compile_local_runtime(config, ".wagent")
    async with ApplicationContext(plan) as app:
        runtime = app.resolve("runtime")
        return await runtime.run(prompt)
```

Executing `run()` calls the configured model. This is usage documentation, not offline acceptance evidence. Tools, knowledge, budgets and usage ledgers still come from explicit authorized host catalogs, with no module scanning or configuration-driven code imports.

## Replacement points

| Component name | Default instance and responsibility |
|---|---|
| `provider` | `LocalProviderAssembly`; owns the template-created Provider and its observation/budget wrapping relationship |
| `models` | `ModelRegistry`; manages visibility, without closing host Providers added later |
| `routing_policy`, `router` | Default routing policy and `ModelRouter` |
| `invocation_policy`, `model_executor` | Invocation policy and `ModelExecutor` |
| `tools`, `tool_executor` | Authorized tool catalog and `ToolExecutor` |
| `run_store`, `session_store`, `sessions` | Run store, Session store and `SessionManager` |
| `definition`, `pricing`, `token_estimator` | Agent definition, optional pricing and estimator |
| `knowledge` | Borrowed host knowledge binding, or `None` when unconfigured |
| `loop`, `runtime` | Default ReAct and local session-call adapter |

Pass definitions to `compile_local_runtime(..., replacements=(... ,))`, or use `replace_components(plan, replacements)` on a plan. Names must already exist. Duplicate names, missing dependencies, cycles and shorter-lived dependency capture are rejected; scope order and aspects are preserved. Replacement creates no instances, mutates no running context and does not prune unused components. To exclude defaults altogether, build a minimal plan with `compile_assembly`.

For example, with an existing host-owned `my_loop` implementing `AgentLoop`:

```python
from w_agent import BorrowedComponent, compile_local_runtime

def use_my_loop(config, my_loop):
    return compile_local_runtime(
        config, replacements=(BorrowedComponent("loop", my_loop),),
    )
```

`BorrowedComponent` retains host ownership. Use `ComponentDefinition` with an explicit `dispose` hook to create and close managed resources. The default Provider component contract is `LocalProviderAssembly`, not a raw Provider. A host can borrow `LocalProviderAssembly(name, provider)` without container cleanup of that resource.

## Shutdown and aspects

A container-managed Runtime no longer closes Providers found in its model registry; it only marks itself closed. The default `provider` component cleans up its created resource, while the context disposes components in reverse dependency order and handles startup rollback. Host knowledge, usage, budget and tool bindings do not transfer ownership on context exit.

`aspects=(...)` goes into the same assembly plan. Pointcuts can match public methods such as `runtime.run` and `router.route`. Callers must finish or cancel business tasks not tracked by aspects before closing the context; it does not infer ownership of external tasks.

## Independent Workflow assembly

`compile_local_workflow(state_root, node_invoker=..., pause_source=..., replacements=..., aspects=...)` creates no model or ReAct. It contributes four components: `workflow_store`, `node_invoker`, `pause_source` and `workflow`. Resolve `workflow` and use public `start()` / `resume()` methods. Explicit invokers and pause sources are borrowed; replacements may declare managed lifecycle hooks.

## Verification and remaining work

New `tests/test_local_application.py`, `tests/test_application_execution.py` and `tests/test_application_frontends.py` cover recipes, managed execution, streams, cancellation, loading authorization and the same custom project across all three frontends. The synchronous `assemble_local_runtime()` remains compatible; its cleanup behavior does not automatically acquire application-context semantics. CLI/TUI now use `open_local_runtime()`.

After completing M4 implementation, verification used the existing isolated Python 3.11.9 environment in batches. Core/recipe/frontend cases plus repair verification reported 194 passed / 4.61s. Adjacent runtime, approval, budget, knowledge and Workflow regression reported 378 passed / 150.39s, plus one failure in an outdated tab-list assertion; adding the new Application tab fixed it, with the rerun included in those 194 cases. This covers 572 distinct passing cases without adding older stage counts. TUI checks were headless Textual tests, Docker probing was replaced, and no real models or external services were contacted.

Verified files: all `test_application_*.py`, plus `test_local_application.py`; also `test_local_runtime`, `test_runtime_shared_budget`, `test_service_usage_runtime`, `test_knowledge_runtime`, `test_framework_acceptance`, `test_budget_evaluation_probe`, `test_cli`, `test_tui`, `test_history_options_cli`, `test_knowledge_evaluation_ui`, `test_knowledge_ui`, `test_message_fields_run`, `test_runtime_media_input`, `test_service_usage_frontends`, `test_service_usage_resume_frontends`, `test_shared_budget_ui`, `test_tui_history_templates`, `test_tui_media_run`, `test_tui_message_fields_run`, `test_tui_shared_budget`, `test_tui_approval_resume`, `test_tui_workflow_control`, `test_tui_workflow_tool_approval`, `test_cli_workflow_tool_approval`, `test_workflow_approval_resume`, `test_workflow_invocation` (all in `tests/` with `.py` extension). This was not a full-suite run.

The documented CLI example actually returned `{"result": "LOCAL:HELLO"}`. No installation, build, commit, push or publication occurred. M5 still needs three complete developer tutorials, migration docs and authorized installed-artifact/outside-repository acceptance. M4 acceptance does not complete the full H01–H08 scope.

Static evidence: 33 related Python files passed AST/in-memory compilation; 552 local link targets exist across 18 bilingual entry/topic documents. Scoped tracked-file `git diff --check` exited 0 with only LF-to-CRLF warnings; that command does not cover untracked files and is not presented as a complete workspace check.

## One project for Python and terminals

`ApplicationProject(plan, operations)` declares public operations, for example `{"run": ApplicationOperation("harness", "run")}`. Plans may come from `compile_assembly`, `compile_decorated` or `compile_configured`, without default Providers, Loops or model-message formats.

```python
from examples.custom_harness import create_project

async def custom_answer():
    async with create_project().open() as host:
        return await host.invoke("run", "hello")
```

From the repository root, the CLI uses the same offline example:

```bash
python -m w_agent.cli application run --entry examples.custom_harness:create_project --input-file examples/custom_harness_call.json --confirm-code
```

On the TUI **Application** page, enter the same entry and call file, then type `RUN APPLICATION`. Confirmation is consumed once; cancellation or exit waits for call cleanup. The call file accepts only `operation`, `args`, `kwargs`, is limited to 1 MiB, and rejects duplicate JSON fields and non-finite numbers. Python accepts arbitrary objects; CLI/TUI transport JSON only. Non-JSON output fails rather than coercing potentially secret-bearing `repr` values.

Only `load_application_entry(..., confirmed=True)` imports an explicit `module:attribute`, accepting a project or a no-argument sync/async project factory. `execute_application_entry(entry, call, confirmed=True, on_item=...)` provides shared loading, startup, invocation and shutdown. Authorization covers **unsandboxed import, startup and this operation**, which may access local files, services or models. It is unsuitable for untrusted code and does not automatically grant built-in tool approvals. Projects needing isolation must use sandbox components.

## Call and stream lifecycle

`host.invoke()` calls a sync/async value-returning method without coercion, rejecting iterator escape from its scope. Declare streams with `ApplicationOperation(..., kind="stream")`; `await host.consume("stream-name", consumer, ...)` consumes them and returns the delivered count. Consumers may be sync or async, with per-item backpressure. Completion, errors and cancellation close the source and iterator before releasing call scopes. CLI emits `{"item": ...}` lines and a final `{"result": ...}`; a stream result is the delivered count. TUI retains the last 20 lines and truncates each displayed line to 8192 characters.

A Host manages only calls submitted through it. Shutdown rejects new calls, cancels/drains existing calls, then closes the container; an invocation cannot close its own Host. A short-lived target such as Run gets a fresh ancestor scope chain per call, released on completion, without cross-call Session-scope reuse. Developers needing persistent workspace/session scopes may still manage `ApplicationContext` explicitly. Blocking synchronous code, swallowed cancellation and independently spawned tasks have no forced-termination guarantee.
