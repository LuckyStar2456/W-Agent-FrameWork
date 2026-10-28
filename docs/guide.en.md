# W-Agent user guide

English | [简体中文](./guide.md)

This guide targets **2.0.0**, requiring Python 3.11+. Install the release from [PyPI](https://pypi.org/project/wagent-framework/2.0.0/); see the [release record](./acceptance-2026-10-01-stable-release.en.md) for verification evidence.

## 1. Install and run offline first

Install in your own virtual environment and run the [README quickstart](../README_EN.md#quickstart):

```bash
python -m pip install "wagent-framework==2.0.0"
wagent --help
```

For framework development or the complete repository support/coding examples, use an editable installation from the matching source root:

```powershell
python -m pip install -e .
python -m examples.basic_development support
python -m examples.basic_development coding
wagent --help
```

The examples use modern templates, registries and actual tool execution. Final text comes from tool results; no real model is called. Dependency installation may access the network and is separate from offline execution. See [basic development](./basic-development.en.md).

With a PyPI installation, you can also copy `examples/basic_development.py` from matching source into your own project and run `python basic_development.py support`; do not assume the wheel includes an `examples` package.

Choose extras as needed: `models` for HTTP models, `tui` for Textual, `knowledge-documents` for PDF/DOCX/XLSX/PPTX, `mcp` for HTTP MCP paths, and `media-preview` for character-image previews. Others include `fastapi`, `langchain`, `opentelemetry`, `testing` and platform-limited `wasm`. Example: `python -m pip install -e ".[models,tui]"`. Installation does not authorize service calls.

## 2. Choose the smallest development path

- Support/RAG: start with `customer_support_agent` and sample `support_tools()`, replace local documents and retain sources; then add [knowledge tools](./knowledge-tools.en.md) or [named assembly](./knowledge-runtime.en.md).
- Coding: start with `coding_agent` and `coding_tools(source)`. The example reads host-supplied text only; no implicit IDE, arbitrary file access, shell or writes.
- Single agent: compose a Provider, ModelRegistry/Router/Executor, ToolRegistry/Executor and ReactAgentLoop. Templates do not register tools or grant authority; see [agents](./agents.en.md) and [tools](./tools.en.md).
- Workflow: select DAG, state-graph or Python definitions and public Agent adapters. Recovery covers supported node boundaries, not arbitrary Python instruction stacks; see [workflows](./workflows.en.md).

## 3. Add a real model and durable Runtime

[Basic development](./basic-development.en.md) provides optional Ollama substitution; [provider templates](./provider-templates.en.md) cover other services. Supply your own endpoint, model and credentials, then authorize requests and potential costs. Declared catalogs/capabilities do not prove connectivity, authentication or generation quality; see [routing/probes](./model-routing.en.md).

Use [local Runtime](./local-runtime.en.md) for configuration, Sessions, durable Runs and approval recovery. First initialize directories and inspect the environment:

```text
wagent init
wagent doctor
wagent profile list
```

`wagent init` only creates directories and an empty `{}` configuration, not a runnable model configuration. Fill `.wagent/config.json` using the [local Runtime configuration example](./local-runtime.en.md), supplying a working Provider, model, endpoint and credentials. Then explicitly authorize execution:

```text
wagent run "hello" --config .wagent/config.json --confirm-model-call --json
```

`run` contacts the service and may incur costs. After installing the `tui` extra, use `wagent tui` to open the terminal interface; the interface does not replace valid model configuration. Factories belong on your project's normal import path, e.g. `my_project_tools:open_tools`; do not depend on repository `examples.*` in a wheel. Factory loading, tool selection, per-run permissions and exact-call approval are independent; configuration references are not authorization.

## 4. Knowledge, state and safety

The smallest knowledge path uses local keyword retrieval. The advanced path is [file preview/locked save → fixed trace → sync plan → independent execution approval](./knowledge-sync-entries.en.md). Parser and [structural/overlapping splitter](./knowledge-splitting.en.md) settings are bound to preview digests. [Raw archives](./knowledge-archive-entries.en.md) use explicit reads/writes/new-file exports, not automatic restoration over files. Read consent is not embedding, upsert or delete consent.

[Runs/Sessions](./sessions.en.md), [replay](./event-replay.en.md), [shared budgets](./shared-budget.en.md) and [service usage](./service-usage-runtime.en.md) have separate storage/accounting boundaries. Unknown prices/usage stay unknown; budgets are not exact invoices. The example helper owns and closes its Provider; real hosts must define shared-resource, task-cancellation and Store lifecycles.

Use [sandboxes](./sandbox.en.md) for untrusted code; unavailable isolation fails closed. Explicit unsafe-local provides no isolation guarantee. Ordinary Python handlers/plugins are trusted host code; WRITE/EXTERNAL permissions do not replace per-call approval, and unknown effects are not automatically replayed.

## 5. Testing, sharing and compatibility

- [Testing/evaluation](./testing-evaluation.en.md): start with scripted offline models/contracts, then authorize real-model tests. Local passes do not certify vendor quality or billing.
- [Project sharing](./project-sharing.en.md): preview configuration/plugin references offline; installation, imports and execution need separate authority.
- [1.x migration](./migration-1x.en.md): retain the engineering foundation and `BaseAgent.arun()`; `LegacyAgentAdapter` bridges text/final results only, not an implicit tool loop or durable Session.
- [Developer guide](./developer.en.md), [API](./api.en.md) and [documentation index](./README.en.md): replace modules and find complete interfaces.

The [roadmap](./roadmap.en.md) governs capability status. `Planned` / `Reserved` are not executable APIs; semantic chunking, cross-store transactions, advanced recovery and multi-agent enhancements are not prerequisites for basic use. See the [release record](./acceptance-2026-10-01-stable-release.en.md) for current release verification; historical alpha reports do not replace that evidence.
