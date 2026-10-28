# Application aspects and stream lifecycle

English | [简体中文](./application-aspects.md)

> Release scope: the new framework core described here is included in 2.1.0. Earlier “unpublished” labels and candidate 2.0.0 metadata below record pre-release stages, not the 2.1.0 package status. See [2.1.0 notes](./releases/2.1.0.en.md); upload status is on [PyPI](https://pypi.org/project/wagent-framework/2.1.0/).

M3 compiles aspects into `AssemblyPlan`. `ApplicationContext` weaves matching components using the same dependency and disposal rules. Sync calls, async calls, sync streams and async streams have distinct execution paths; stream aspects cover consumption. Focused stage acceptance passed 207 cases; unpublished and absent from installed 2.0.0.

## Declare an independent aspect

```python
from w_agent import (
    ApplicationContext, Aspect, Before, Finally, ServiceComponent,
    compile_decorated,
)

@Aspect("trace", component="harness", methods=("run",))
class Trace:
    def __init__(self):
        self.events = []

    @Before
    def before(self, invocation):
        self.events.append("start:" + invocation.method)

    @Finally
    def finished(self, invocation, outcome):
        self.events.append(outcome.status)

@ServiceComponent("harness")
class Harness:
    async def run(self, text):
        return text.upper()

async def main():
    async with ApplicationContext(compile_decorated([Harness, Trace])) as app:
        result = await app.resolve("harness").run("hello")
        events = app.resolve("trace").events
    return result, events
```

Business methods need no tracing code. The complete stream example is [aspected_harness.py](../examples/aspected_harness.py), runnable from source with `python -m examples.aspected_harness`. It makes no real model requests, starts no services and installs no dependencies.

## Pointcuts and ordering

`MethodPointcut(component="harness*", methods=("run", "stream"), tags=frozenset({"metered"}))` matches component/method globs and requires all specified tags on the target definition. Use `ComponentDefinition(..., tags=...)` or class component decorator `tags`. Only public callable attributes and callable objects' `__call__` are eligible; properties are not executed to discover methods. No ReAct private names are required.

Lower `order` is outermost; ties sort by aspect name, with reverse stack order on exit. `app.aspect_matches` and its child-scope equivalent expose `AspectMatch(component, method, kind, aspects)` without arguments. These are actual matches for started scopes, not promises about unopened ones. Unmatched aspects do not run.

Aspect classes are managed components with M2 injection/lifecycle. Targets referencing advice components start after them and stop before them. Cycles and longer-lived capture of shorter advice scopes are rejected. Dependency edges conservatively use component matches; actual methods are checked at startup. All AdviceRef source components are excluded from automatic weaving to avoid recursive infrastructure proxies.

## Advice contracts

| Declaration | Signature | Behavior |
|---|---|---|
| `@Before` | `(invocation)` | Runs upon layer entry; failure skips deeper work but still runs this layer's Finally |
| `@Around` | `(invocation, proceed)` | May short-circuit or advance once; may transform results/streams, with no implicit retry |
| `@After` | `(invocation, result)` | Runs on success; streams only after normal exhaustion, with result None; return value ignored |
| `@OnError` | `(invocation, error)` | Observes errors/cancellation; returning does not suppress them |
| `@Finally` | `(invocation, outcome)` | Cleans entered layers with success/error/cancelled/closed status |

Each aspect class declares one method per role; split additional processing into ordered aspects. `Invocation` exposes component, method, kind, args and a read-only kwargs mapping, without deep-copying arbitrary business objects. `InvocationOutcome` carries results/errors but hides them from default repr. Advice can access sensitive values; log redaction remains the host's responsibility.

Sync methods require sync advice and preserve ordinary sync returns, without `asyncio.run()`. Async methods accept sync/async advice. `proceed()` is single-use and expires with its advice; async advice must fully await it, without dispatching it into another task. Around may handle business exceptions; caller/scope cancellation still requires cleanup and propagation. Primary and cleanup failures are retained together in exception groups.

## Streams and scope shutdown

Coroutines and sync/async generator functions are detected automatically. For ordinary methods returning awaitables/iterators, explicitly set `kind="async"`, `"stream"` or `"sync_stream"`. Conflicting kind declarations are rejected.

Streaming Around should be a sync/async generator that transforms and yields items from `for`/`async for item in proceed()`. This keeps its code alive across consumption. A plain async function that merely returns an iterator still executes its own finally at function return, per Python semantics. Framework Before/After/OnError/Finally always surround consumption.

Streams start on first consumption. Exhaustion, failure, cancellation, `close()`/`aclose()` and scope shutdown all clean up; short-circuiting Around also closes downstream. Concurrent async iteration is rejected and repeated close shares one cleanup. Closing an unconsumed stream starts neither business code nor advice. Use `with stream` / `async with stream`; early break should explicitly close or rely on scope shutdown, not garbage collection.

Scopes reject new external calls, cancel/wait their managed async invocations, close streams, then dispose business/advice components. Consumer disposal hooks may still await live dependency methods. Repeated cancellation cannot truncate registered cleanup. Blocking sync code, uncooperative async code or permanently suspended cleanup can still block shutdown; Python threads are not forcibly terminated.

Only matched proxy calls and their managed tasks/streams are owned by this boundary. Independently spawned host tasks, self-calls, unmatched methods and special operators are not automatically supervised. Lifecycle hooks execute on the original object; exposed objects are delegating views, not promises of identical `type`, identity or fully transparent proxies. Borrowed objects are not mutated or re-owned. Aspects are not isolation, mandatory-budget or permission security boundaries.

## Explicit code and configuration selection

Use `compile_assembly(components, aspects=[AspectDefinition(...)])` for explicit assembly. Advice may be a callable or `AdviceRef("trace", "before")` referencing a component in the same plan. `compile_decorated(..., aspects=...)` also accepts explicit declarations. Configuration selects host-catalog `@Aspect` classes or `AspectDefinition` objects without importing unknown modules. All entries produce the same plan.

For plugins, pass `ApplicationPlugin(..., components=plan.components, aspects=plan.aspects)` rather than dropping the aspect declarations. Exports expose the same woven view; borrowing across plugins does not transfer original resource ownership.

Legacy `AspectJPointcut`, `ProxyFactory` and `BeforeAdvice`/`AroundAdvice`/`AfterAdvice` retain their paths and old behavior, without silently adopting new semantics. New applications should use component aspects above. Legacy proxy internals, event notifications and new context-managed calls are not the same execution entry.

## Acceptance and remaining work

AST/in-memory compilation checks passed for 25 Python files. The first complete code block in each bilingual tutorial executed and returned `("HELLO", ["start:run", "success"])`; local links passed existence checks. Document rendering was not accepted.

On 2026-10-01, focused stage verification in the existing isolated Python 3.11.9 environment reported 207 passed / 1.99s: 34 new M3 cases and 173 M1/M2/adjacent compatibility regressions. Counts overlap historical stages and are not additive. Coverage includes three-entry aspect equivalence, sync/async calls, errors/repeated cancellation, stream exits, cross-plugin borrowing, match diagnostics, child scopes, shutdown ordering and self-close deadlock prevention.

Command: `python -m pytest tests/test_application_aspects.py tests/test_application_decorators.py tests/test_application_planning.py tests/test_application_context.py tests/test_application_configuration.py tests/test_application_legacy.py tests/test_application_plugins.py tests/test_container.py tests/test_scanner.py tests/test_lifecycle.py tests/test_aop.py tests/test_kernel_plugins.py tests/test_plugin_cancellation.py -q`.

No full-suite run occurred. M4 default-module/CLI/TUI public assembly and M5 installed-package acceptance outside the repository remain incomplete. No installation, build, external-service call or publication occurred; M3 acceptance does not complete H01–H08 final acceptance.
