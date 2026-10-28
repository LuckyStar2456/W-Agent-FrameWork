# Decorator driven Harness development

English | [简体中文](./annotation-development.md)

> Release scope: the new framework core described here is included in 2.1.0. Earlier “unpublished” labels and candidate 2.0.0 metadata below record pre-release stages, not the 2.1.0 package status. See [2.1.0 notes](./releases/2.1.0.en.md); upload status is on [PyPI](https://pypi.org/project/wagent-framework/2.1.0/).

M2 compiles decorators and configuration selections into M1 `AssemblyPlan` objects. The same `ApplicationContext` creates, injects, initializes and closes instances. Focused stage acceptance passed 142 cases; unpublished and unavailable in installed 2.0.0. M3 [application aspects](./application-aspects.en.md) passed stage acceptance; public CLI/TUI assembly wiring remains M4.

## From declaration to execution

```python
from typing import Annotated
from w_agent import (
    AgentComponent, ApplicationContext, PostConstruct, PreDestroy,
    RepositoryComponent, Value, compile_decorated,
)

@RepositoryComponent("journal")
class Journal:
    def __init__(self):
        self.entries = []
        self.closed = False

    @PreDestroy
    def close(self):
        self.closed = True

@AgentComponent("harness", scope="run")
class MyHarness:
    def __init__(self, journal: Journal,
                 prefix: Annotated[str, Value("model.prefix", required=True)]):
        self.journal, self.prefix = journal, prefix

    @PostConstruct
    def ready(self):
        self.initialized = True

    async def run(self, text):
        result = self.prefix + text.upper()
        self.journal.entries.append(result)
        return result

async def main():
    plan = compile_decorated([Journal, MyHarness], values={"model": {"prefix": "LOCAL:"}})
    async with ApplicationContext(plan) as app:
        async with app.scope("run", "example") as run:
            result = await run.resolve("harness").run("hello")
    return result
```

The complete [annotated_harness.py](../examples/annotated_harness.py) source example adds a custom model and configuration factory. Run `python -m examples.annotated_harness` from the source checkout. No official ReAct, Provider, TUI or external model is required. Ordinary user components remain trusted host Python; decorators do not grant sandboxing, tool authorization or mandatory budget enforcement.

## Scanning and import boundaries

`scan_components(module_a, module_b)` inspects only module objects already loaded by the host. It does not recursively import packages, change `sys.path` or execute component factories. String module names are rejected. Only locally declared components are collected; aliases are deduplicated, re-exports and undecorated subclasses are excluded. Classes/functions can also be passed directly to `compile_decorated()` for intentional cross-module composition.

Loading Python modules executes their code and remains a separate host decision. The old `ParallelASTScanner` remains a source discovery tool; an AST result is not import authorization and is never automatically promoted into executable targets.

## Components and injection

Existing `@AgentComponent`, `@ServiceComponent`, `@RepositoryComponent`, `@ControllerComponent` and `@ToolComponent` declarations are reused. Classes default to lowercase class names and accept explicit `name`/`scope`. Legacy `singleton` maps to application; replace `prototype` with an explicit run/step lifetime. Function components are borrowed callable values, not eager factories. Use `@Bean` for object creation.

Constructor injection matches concrete runtime types and subclasses. Multiple candidates are an error, never a registration-order choice. Untyped parameters can match component names. An ordinary Python default is used when no candidate exists. Configuration requires explicit `Value` binding; files and environment variables are not read implicitly.

- Constructor: `store: Annotated[Store, Qualifier("primary")]` or `store: Store = Autowired("primary")`.
- Field: `store: Store = Autowired("primary")`, `store: Annotated[Store, Autowired()]`, or untyped `store = Autowired("primary")`.
- Setter: `@Autowired()` on a single-value method, optionally combined with `@Qualifier("primary")`; sync and async both work.
- Configuration: constructor/field `Value("model.limit", default=4)` or setter `@Value(...)`. `required=True` rejects missing values regardless of defaults. Legacy Value still defaults to `None`; a strict non-nullable annotation needs a supplied value or type-correct default.

The sequence is creation → ownership registration → field/setter injection → `PostConstruct`. Injection failures, initialization failures and cancellation therefore enter M1 cleanup. Every field/setter dependency participates in the same graph: cycles and longer-lived capture of shorter-lived components are rejected. Unmarked business fields are neither injected nor evaluated as type strings.

`from __future__ import annotations` uses a restricted grammar: names, public types from loaded modules, common containers, Union/Optional/Annotated and injection markers. No `eval` or arbitrary annotation calls occur; resolve local forward types with `types={"Store": Store}`. Complex generic dependencies, arbitrary annotation expressions and non-runtime protocol structural matching are not inferred automatically; adapt them with explicit `ComponentDefinition` and dependency references. Configuration values support common strict types and nested containers without string-to-number coercion.

## Configuration factories and lifecycle

```python
from w_agent import Bean, Configuration

@Configuration("models")
class Models:
    @Bean(name="model", provides=CustomModel)
    async def model(self):
        return CustomModel()
```

The host supplies `CustomModel`. Configuration classes are managed components with injection and lifecycle support. Bean methods run after their configuration instance is initialized, with the same parameter injection rules. Module-level `@Bean` factories also work. Return annotations or `provides` enable type matching and result checks; unnamed types require name-based references. Static/classmethod configuration factories are rejected; use a module-level factory instead.

Declared product `@PostConstruct`/`@PreDestroy` methods become lifecycle hooks. Explicit `@Bean` `initialize`/`dispose` callbacks replace the corresponding declaration hooks. Direct Python calls such as `self.model()` remain ordinary factory calls, not intercepted container lookups. Inject other beans through method parameters to avoid creating unmanaged objects yourself.

Initialization uses ascending `(order, method name)` order, disposal the reverse. Inheritance follows Python override semantics. A failed/cancelled disposal method does not skip remaining methods; errors are grouped. New contexts invoke only marked hooks, not methods merely named `close` or `post_construct`. Factories remain responsible for resources allocated before they return.

## Configuration selection and explicit assembly equivalence

The host parses JSON/YAML/TOML before calling `compile_configured(document, catalog=...)`. Configuration selects only from the supplied catalog, never executable filesystem/module paths; there is no environment expansion.

```python
from w_agent import compile_configured

plan = compile_configured(
    {
        "components": ["journal", "harness"],
        "values": {"model": {"prefix": "LOCAL:"}},
    },
    catalog={"journal": Journal, "harness": MyHarness},
)
```

Catalog values may be declared classes, configuration classes, function components, Bean factories or explicit definitions. Selecting a configuration includes its Beans. Unknown keys, duplicate selections, outside-catalog targets and duplicate identities are rejected. `arguments={component_name: {constructor_parameter: value}}` and `dependencies={component_name: {constructor_parameter: component_name}}` override constructor bindings explicitly and cannot overlap. Configuration cannot replace code or lifecycle hooks; host definitions can supply more complex parameters.

Decorator/configuration adapters normalize by component name, then call `compile_assembly()`. Their ordinary `AssemblyPlan` works with `ApplicationContext`, or its `.components` with `ApplicationPlugin`. Explicit Python preserves caller ordering; use the same ordering when comparing independent component startup order. All three share dependency, scope, rollback and cleanup rules without another execution container.

## Acceptance and remaining work

On 2026-10-01, unified stage verification in the existing isolated Python 3.11.9 environment reported 142 passed / 1.73s: 41 new M2 cases, 81 M1 regressions and 20 adjacent legacy container/scanner/lifecycle cases. Counts overlap the previous stage and are not additive. AST and in-memory compilation checks passed for 20 Python files.

Acceptance executed the complete decorator example and normal/failing-start ownership comparisons across Python, decorator and configuration entries. Cases cover fields, setters, configuration factories, qualifiers, forward types, no implicit imports, failed/cancelled cleanup and public exports. Initial collection found Value missing from top-level exports; after fixing it, the entire scoped run passed. No full-suite run, installation, build, real external call or publication occurred.

Reproduction: `python -m pytest tests/test_application_decorators.py tests/test_application_planning.py tests/test_application_context.py tests/test_application_configuration.py tests/test_application_legacy.py tests/test_application_plugins.py tests/test_container.py tests/test_scanner.py tests/test_lifecycle.py -q`.

The first complete code block from each bilingual tutorial was also extracted and executed; both returned `LOCAL:HELLO`. Tutorial local links passed existence checks. Scoped `git diff --check` found no whitespace errors in tracked files, only CRLF notices. Document rendering was not accepted.

M2 acceptance does not complete the final goal. [M3 application aspects](./application-aspects.en.md) now passed stage acceptance; M4 public default-module/CLI/TUI assembly and M5 installed-package developer acceptance outside the repository remain. H01/H04 have local core-path evidence; complete H01–H08 final acceptance is outstanding.
