# W-Agent

**Assemble your own agent execution system in Python with Spring-inspired dependency injection, aspects and lifecycle management.**

[简体中文](./README.md) · [Documentation](./docs/README.en.md) · [Quickstart](#quickstart) · [Extend W-Agent](./docs/developer.en.md) · [Roadmap](./docs/roadmap.en.md)

[![PyPI](https://img.shields.io/pypi/v/wagent-framework)](https://pypi.org/project/wagent-framework/)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](./setup.py)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](./LICENSE)

W-Agent is an open-source **Harness development framework** for Python developers. A harness is the code that coordinates model calls, tools, state and execution flow. Assemble your own implementations with decorators, configuration or explicit Python, and optionally use the built-in ReAct, Workflow and CLI/TUI implementations.

As a small application grows, model replacement, call logging and shared-client initialization and cleanup can spread through its business functions. W-Agent moves assembly, logging aspects and lifecycle handling into a container, leaving business methods focused on execution flow. The support-reply application below shows this change.

**For a first try, install `wagent-framework==2.1.0` and import `w_agent`. The complete example on this page targets that stable release.**

## Installation

Requires **Python 3.11+**. Use your project's virtual environment. These commands pin the stable 2.1.0 release:

```bash
python -m pip install "wagent-framework==2.1.0"
```

| What you need | Version and source |
|---|---|
| This page's example and the Harness framework core | [PyPI 2.1.0](https://pypi.org/project/wagent-framework/2.1.0/) · [Release notes](./docs/releases/2.1.0.en.md) |
| An existing 1.x / 2.0.0 project | Read the [1.x migration guide](./docs/migration-1x.en.md) or [2.0.0 building-block tutorial](./docs/basic-development.en.md), then check API differences |
| GitHub source development | `main` may contain unreleased changes; use the matching PyPI source distribution (sdist) to reproduce a release |

Use PyPI for installable versions and artifacts, and the repository's release notes for change scope. GitHub Releases entries do not determine whether a Python package is published. Running `python -m pip install -e .` uses the current checkout; it does not switch to PyPI 2.1.0.

Add only the dependencies you need:

```bash
# HTTP models and terminal UI
python -m pip install "wagent-framework[models,tui]==2.1.0"

# PDF / DOCX / XLSX / PPTX parsing
python -m pip install "wagent-framework[knowledge-documents]==2.1.0"
```

Other extras include `mcp`, `media-preview`, `testing`, `fastapi`, `langchain`, `opentelemetry` and platform-limited `wasm`. See the [installation guide](./docs/guide.en.md).

## Quickstart

### From manual management to container assembly

Suppose you already have a model adapter with `open()`, `answer()` and `close()` methods. Manual orchestration handles business logic, logging and resource cleanup together:

```python
# Comparison fragment: model is an adapter instance created by the caller.
async def reply_manually(model, question):
    model.open()
    try:
        print("call:run")
        answer = await model.answer(question)
        print("result:success")
        return answer
    finally:
        model.close()
```

With W-Agent, these responsibilities live in a business component, a logging aspect and lifecycle methods. Save this complete example as `support_app.py` and run `python support_app.py`. It needs only the base installation above: **no API key, network service or TUI**.

```python
import asyncio

from w_agent import (
    AgentComponent, ApplicationOperation, ApplicationProject, Aspect,
    Before, Finally, PostConstruct, PreDestroy, ServiceComponent,
    compile_decorated,
)


class ReplyModel:
    async def answer(self, question: str) -> str:
        raise NotImplementedError


@ServiceComponent("model")
class OfflineModel(ReplyModel):
    """Deterministic stand-in; no real LLM request."""

    @PostConstruct
    def open(self):
        print("model:open")

    async def answer(self, question: str) -> str:
        if "shipping" in question.casefold():
            return "Demo orders ship within two working days."
        return "Please contact a human teammate."

    @PreDestroy
    def close(self):
        print("model:close")


@AgentComponent("support", scope="run")
class SupportHarness:
    def __init__(self, model: ReplyModel):
        self.model = model

    async def run(self, question: str) -> str:
        return await self.model.answer(question)


@Aspect("trace", component="support", methods=("run",))
class CallLog:
    @Before
    def started(self, invocation):
        print(f"call:{invocation.method}")

    @Finally
    def finished(self, invocation, outcome):
        print(f"result:{outcome.status}")


async def main():
    plan = compile_decorated([OfflineModel, SupportHarness, CallLog])
    project = ApplicationProject(plan, {"reply": ApplicationOperation("support")})
    async with project.open() as host:
        print(await host.invoke("reply", "What is your shipping time?"))


asyncio.run(main())
```

Expected output:

```text
model:open
call:run
result:success
Demo orders ship within two working days.
model:close
```

`SupportHarness.run()` keeps only the reply flow. The container injects a model by type; the logging aspect records the call outcome. The model is shared within the application, initialized when the Host opens and cleaned up when it closes. `scope="run"` gives each call its own support component instance. Real adapters can create and close clients in the lifecycle methods; the prints here only demonstrate ordering.

### Replace the model without changing the business method

Add another adapter before `main()` in the same file. It follows the application's own `ReplyModel` interface:

```python
@ServiceComponent("model")
class AlternateModel(ReplyModel):
    async def answer(self, question: str) -> str:
        return "Alternative model: a human teammate will follow up."
```

Then replace only the assembly line inside `main()` and run the file again:

```python
plan = compile_decorated([AlternateModel, SupportHarness, CallLog])
```

The reply changes to `Alternative model: a human teammate will follow up.`, while `call:run` and `result:success` are still logged. Both models are offline stand-ins that demonstrate assembly, not real LLM understanding or generation quality. To use a real model, call a [Provider](./docs/provider-templates.en.md) inside the adapter, add the `models` extra as needed, and configure credentials and client lifecycle.

To remove logging, omit `CallLog` from the assembly list; the business method stays the same. See [AOP development](./docs/application-aspects.en.md) for aspects such as timing. Failed calls log `result:error` and pass the exception to the caller; this example does not retry automatically.

### Try complete applications

See [Develop your own Harness](./docs/harness-development.en.md) for three complete paths:

| Example | Primary style | Boundary demonstrated |
|---|---|---|
| [Custom Harness](./examples/custom_harness.py) | Explicit Python assembly | Custom model parameters, tools and storage without a default Loop |
| [Support](./examples/support_harness.py) | Decorator scanning, DI and AOP | Local FAQ, unknown-question handoff and lifecycle records |
| [Coding](./examples/coding_harness.py) | Configuration catalog, Bean factories and AOP | Preview/digest approval; memory edits only, no code execution |

Examples use deterministic offline model stand-ins, not real LLM quality evidence. ReAct, Workflow, Providers, tools and budgets remain optional; see [default assembly](./docs/default-assembly.en.md). `examples` is not included in the wheel: copy the scripts and accompanying JSON from matching source or sdist. Tutorial files are not library runtime dependencies.

## Compose it your way

These are responsibilities, not a mandatory fixed pipeline:

```text
Decorators / Explicit Python / Catalog-selected configuration
                          ↓
             AssemblyPlan (dependency/scope validation)
                          ↓
        ApplicationContext (instances, DI, AOP, lifecycle)
                          ↓
          Your Harness or optional ReAct / Workflow recipe
                          ↑
        ApplicationProject / Host ← Python / CLI / TUI
```

| What you want to do | Start here |
|---|---|
| Integrate a custom model, parameter or response format | [Provider templates](./docs/provider-templates.en.md) · [Routing/probes](./docs/model-routing.en.md) |
| Replace the reasoning loop | [Agent protocols and loops](./docs/agents.en.md) |
| Add Python, HTTP, command or MCP tools | [Tools](./docs/tools.en.md) · [MCP interactions](./docs/mcp-interactions.en.md) |
| Compose processes, state and approvals | [Workflows](./docs/workflows.en.md) |
| Add local knowledge, files or vector retrieval | [Knowledge retrieval](./docs/knowledge-context.en.md) · [Ingestion/sync](./docs/knowledge-sync-entries.en.md) |
| Manage usage and context | [Sessions](./docs/sessions.en.md) · [Shared budgets](./docs/shared-budget.en.md) |
| Write plugins and share named composition versions | [Plugins](./docs/plugin-system.en.md) · [Project sharing](./docs/project-sharing.en.md) |

## CLI and TUI

After installing the `tui` extra:

```bash
wagent --help
wagent init
wagent tui
```

`w-agent` is an alias of the same CLI. The TUI includes large character art and emoticons, run/approval controls, and session/usage views.

2.1.0 also provides `wagent application run --entry module:create_project --input-file call.json --confirm-code` and the TUI Application tab using the same public project execution entry. Projects are trusted Python code; import confirmation is not side-effect approval. See the [three tutorials](./docs/harness-development.en.md).

`wagent init` only creates the local `.wagent` layout and an empty `config.json`, preserving existing configuration; it **does not configure a model or send requests**. Fill in the [Runtime configuration](./docs/local-runtime.en.md#configuration) before explicitly authorizing a model call. The TUI does not bypass these boundaries.

## Capability status and safety

2.1.0 provides the Harness framework core; optional advanced capabilities may remain `Experimental`. See [release scope](./docs/releases/2.1.0.en.md) and the [roadmap](./docs/roadmap.en.md).

The pre-release M0–M5 acceptance record includes 259 related tests, isolated installation and three outside-repository Python/CLI/headless-TUI examples. See the [acceptance record](./docs/harness-acceptance.en.md) and [publication evidence](./docs/acceptance-2026-10-02-release-2.1.0.en.md). These historical checks cover a specific scope, not a full regression, real-model quality/billing or every platform.

Before upgrading, check the [release notes](./docs/releases/2.1.0.en.md) and [migration guide](./docs/migration-1x.en.md); legacy containers and synchronous Runtimes do not automatically adopt the new container semantics. Missing dependencies, ambiguous injection and invalid scopes fail assembly validation. See [Harness core](./docs/harness-core.en.md) for initialization and cleanup failure behavior.

- Ordinary Python tools/plugins are trusted host code, **not security sandboxes**. Isolate untrusted code.
- Tool permissions do not replace per-call approval; importing a sharing code does not install/execute code or grant authority.
- A declared model catalog does not prove connectivity, authentication or generation quality. Unknown usage/pricing is not zero.
- Recovery covers documented boundaries, not arbitrary Python stacks, and does not automatically replay effects with unknown outcomes.
- Multi-agent execution, distributed workflows and online plugin marketplaces remain reserved/planned, not ready-made capabilities. W-Agent does not provide a multi-tenant hosted service.

## Documentation and contributing

Start with the [user guide](./docs/guide.en.md), or browse the [documentation index](./docs/README.en.md), [architecture](./docs/architecture.en.md), [public API](./docs/api.en.md) and [1.x migration](./docs/migration-1x.en.md).

Use [Issues](https://github.com/LuckyStar2456/W-Agent-FrameWork/issues) for bugs and proposals. Include Python/W-Agent versions, a minimal reproduction and sanitized logs. For new capabilities, describe extension points and authorization boundaries and update both Chinese and English docs. See the [developer guide](./docs/developer.en.md).

## License

[MIT](./LICENSE)
