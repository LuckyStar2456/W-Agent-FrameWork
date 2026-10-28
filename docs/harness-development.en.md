# Develop your own Harness

English | [简体中文](./harness-development.md)

This tutorial targets the 2.1.0 framework core, not the earlier 2.0.0 API. Use Python 3.11+ and `python -m pip install "wagent-framework==2.1.0"`, or add the optional TUI with `python -m pip install "wagent-framework[tui]==2.1.0"`. These examples require no network, API keys or real model calls and never execute generated code. See [release notes](./releases/2.1.0.en.md) and [core acceptance](./harness-acceptance.en.md).

## One development path

Declare ordinary Python components → compile an `AssemblyPlan` → expose operations in an `ApplicationProject` → invoke within `project.open()`. The container owns dependency resolution, scopes, initialization and cleanup; the Harness owns its algorithm. Explicit definitions, decorators and catalog-selected configuration compile into the same plan, not three containers.

The styles can mix. `compile_assembly` gives explicit factory control; `compile_decorated` supports typed injection and lifecycle annotations; `compile_configured` selects definitions already imported by the host, never imports Python paths from configuration. `scan_components` inspects explicitly supplied loaded modules without recursively importing directories.

## 1. Explicit assembly: custom model, tool and storage

Complete source: [custom_harness.py](../examples/custom_harness.py); input: [custom_harness_call.json](../examples/custom_harness_call.json). Run from the repository root:

```bash
python -m examples.custom_harness
python -m w_agent.cli application run --entry examples.custom_harness:create_project --input-file examples/custom_harness_call.json --confirm-code
```

The Python demo returns `LOCAL:HELLO`, a journal containing that result, and a closed flag. CLI output is `{"result": "LOCAL:HELLO"}`.

`CustomModel.compose(question, *, dialect)` is a user protocol, not converted to an OpenAI request. An ordinary tool normalizes text, `MemoryJournal` stores results, and a Run-scoped `CustomHarness` coordinates them. `ComponentDefinition.dependencies` declares connections; `dispose` declares cleanup. No framework Agent inheritance is required. Change your own interface and consumer for new model parameters without editing framework source.

Before startup, use `replace_components(plan, replacements)` to retain names while replacing implementations and revalidating dependencies. Submit a wholly new graph to `compile_assembly`. Replacement neither prunes unused defaults nor hot-swaps live objects. Represent host-owned resources with `BorrowedComponent`; cleanup stays with the host.

## 2. Annotated support: scanning, DI, AOP and lifecycle

Complete source: [support_harness.py](../examples/support_harness.py); input: [support_harness_call.json](../examples/support_harness_call.json).

```bash
python -m examples.support_harness
python -m w_agent.cli application run --entry examples.support_harness:create_project --input-file examples/support_harness_call.json --confirm-code
```

The module declares a model, FAQ tool, journal and Harness with constructor type injection. `Value("support.tone", required=True)` binds `Friendly` from assembly values. `@PostConstruct` initializes after dependencies are ready; `@PreDestroy` cleans up at scope close. The `@Aspect` Before/Finally advice records public `answer` calls without providing business authorization.

The shipping question produces `answer="Friendly: Demo orders ship within two working days."`, `source="local-faq"` and `handoff=false`. Unknown questions request human handoff instead of inventing FAQ answers. The complete demo records:

```text
store-open → harness-ready → reply-saved → harness-closed → store-closed
```

Aspect events are `before:answer` and `finally:success`. Replace FAQ or model components to extend behavior. Real models require separate authorization, credentials and budget boundaries. This is a framework-development template, not a production support quality assessment.

## 3. Configured coding: Bean factories and explicit approval

Complete source: [coding_harness.py](../examples/coding_harness.py); configuration: [coding_project.json](../examples/coding_project.json); input: [coding_harness_call.json](../examples/coding_harness_call.json). Configuration references only the code-authorized catalog keys `models/workspace/tool/harness/trace`.

```bash
python -m examples.coding_harness
python -m w_agent.cli application run --entry examples.coding_harness:create_project --input-file examples/coding_harness_call.json --confirm-code
```

`@Configuration`/`@Bean` creates the model. `PatchProposal` retains path/before/after and a content digest. CLI defaults to `preview`, returning the proposal and digest. The complete Python demo previews and explicitly passes that digest to `apply` in one Host. Memory content becomes `greeting = 'framework'\nprint(greeting)\n`, with one revision and closed storage after exit.

`PatchTool.apply` itself checks the digest and original content. Removing the trace aspect does not remove approval checks. Empty approval, changed previews or stale source cannot write. This digest binds approval to content; it is not an authentication system. A real application must obtain approval through a trusted user interaction, never model self-approval. The example **only edits a memory dictionary: no project files are written and no generated code executes**.

Separate CLI calls create separate Hosts and do not share memory. For persistence, replace the storage component and design approval identity, concurrency, sandbox and recovery contracts. This demonstration is not a complete code-execution sandbox.

## Python, CLI and TUI load the same project

Python uses `async with create_project().open() as host` and `await host.invoke(operation, ...)`; arguments and results retain their own types. Declare streams with `ApplicationOperation(..., kind="stream")` and consume through `host.consume`, keeping resources alive throughout consumption.

CLI uses `application run --entry module:create_project --input-file call.json --confirm-code`. JSON transports only `operation`, `args` and `kwargs`; arbitrary Python objects are not automatically serializable. Start the TUI with `python -m w_agent.cli tui`, select Application, fill the same entry/input file and enter the one-shot confirmation `RUN APPLICATION`. Cancellation waits for call cleanup. UI display support is not an arbitrary-object serialization protocol.

`--confirm-code` and TUI confirmation authorize trusted Python project import, **not isolation, tool permission or individual side-effect approval**. Module top-level code/factories can execute arbitrary host code: review before loading. Factories own resources created before handing off a project. The container does not supervise independently spawned business tasks or forcibly interrupt uncooperative synchronous code.

## Installed artifacts and out-of-repository execution

The wheel contains the library; matching source/sdist supplies the examples. Copy the three `*_harness.py` files, three `*_harness_call.json` files and `coding_project.json` into a fresh working directory. Use an isolated environment with the candidate wheel installed, no repository `PYTHONPATH`, and run there:

```bash
python custom_harness.py
python support_harness.py
python coding_harness.py
python -m w_agent.cli application run --entry support_harness:create_project --input-file support_harness_call.json --confirm-code
```

Remove the `examples.` entry prefix outside the repository, including in TUI. Copy the [standalone acceptance script](../tests/acceptance/harness_delivery.py) beside those files and run `python harness_delivery.py`: it verifies installed-package provenance and runs each project through Python, CLI and headless TUI. It requires the `tui` extra but no model or external service. Build/install commands do not imply authorization; M5 offline acceptance and the later 2.1.0 publication were separately authorized.

## Ownership, compatibility and reserved boundaries

Scopes clean up factory-created objects, never borrowed objects automatically; failed initialization still rolls back constructed objects. Custom scopes declare their order, including `scope_order` on plugin bridges. Long-lived objects cannot capture shorter-lived instances. Host calls create the child-scope chain needed by their target; manage `ApplicationContext` directly for persistent Session scopes instead of assuming two invokes share one.

ReAct/Workflow are optional [default recipes](./default-assembly.en.md). Legacy BeanFactory, ProxyFactory and manual Runtime behavior does not automatically upgrade; see [migration](./migration-1x.en.md). Multi-agent systems, distributed Workflow, remote sandboxes, plugin marketplaces, advanced hot migration, lazy dependency references and arbitrary Python stack recovery are outside this completion gate and remain recorded in the [roadmap](./roadmap.en.md).
