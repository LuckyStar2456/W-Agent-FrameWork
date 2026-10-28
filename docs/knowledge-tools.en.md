# On-demand knowledge tools and explicit assembly

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-tools.md)

Status: 2.0.0 `Experimental`, included in 2.0.0 and not part of `2.0.0a9`. All 34 offline regressions in `tests/test_knowledge_tools.py` pass, including tool approval resume and delivery of results to the model. Live-service acceptance and publication have not been performed.

## Two independent entry points

The [knowledge context policy](./knowledge-context.en.md) performs host-selected retrieval before a Run. `knowledge_search_tool(retriever, ...)` instead returns an ordinary `ToolBinding`, letting the model request searches during its tool loop. Either or both can be assembled; there is no implicit deduplication and repeated queries may incur repeated charges.

The factory binds a host-supplied `KnowledgeRetriever` without invoking it, creating indexes, importing host modules or opening citations. Protocol composition supports local keyword, vector or custom retrieval without taking ownership of the Agent Loop.

## Registry and named Runtime assembly

```python
from w_agent import (
    InMemoryKnowledgeDocumentStore, KnowledgeDocument, KeywordKnowledgeRetriever,
    ToolSideEffect, assemble_local_runtime, knowledge_search_tool,
)

store = InMemoryKnowledgeDocumentStore((
    KnowledgeDocument("example-v1", "Sample returns window: seven days. Not a real policy.", "sample:refund"),
))
binding = knowledge_search_tool(
    KeywordKnowledgeRetriever(store),
    side_effect=ToolSideEffect.READ,  # Host explicitly selects purely local retrieval.
)
# Host-supplied LocalRuntimeConfig includes tools.enabled=["knowledge_search"].
runtime = assemble_local_runtime(config, tool_bindings={"knowledge_search": binding})
try:
    result = await runtime.run("Search returns policy", permissions=frozenset({"knowledge.read"}))
finally:
    await runtime.aclose()
```

Alternatively use `ToolRegistry.register_binding(binding)` for existing unified-registry scope, version and ownership support. Runtime selects matching host-catalog entries through `tools.enabled`, rejecting missing or mismatched names. JSON does not carry executable retrievers, credentials, permission grants or model-editable backends.

Defaults are `side_effect=EXTERNAL` and `required_permissions=frozenset({"knowledge.read"})`. Default policy checks permission, then exact-call approval, before retrieval. Select `READ` only after confirming purely local execution; hosts may replace policies/permissions. Effect declarations are not network isolation and cannot make malicious or misdeclared Python safe.

## Existing CLI/TUI channels

[`examples/knowledge_tools.py`](../examples/knowledge_tools.py) contains sample records and a local factory. Place it on the host project's import path, for example as `my_knowledge_tools.py`. Add `knowledge_search` to `tools.enabled`, keeping your chosen Provider/model configuration, then explicitly invoke:

```powershell
wagent run "Search returns policy" `
  --config .wagent/config.json `
  --tool-entry my_knowledge_tools:build_tools `
  --confirm-tool-code `
  --grant-permission knowledge.read `
  --confirm-model-call `
  --json
```

This is documentation, not a command executed this increment. Python entry loading independently authorizes unsandboxed local code execution; configuration alone does not trigger it. The sample factory constructs local objects without network/file access, but the main model still needs configuration/authorization and may incur charges.

External retrievers retaining `EXTERNAL` may stop at `needs-approval`. Inspect the pending query, then use the [local Runtime](./local-runtime.en.md) `run-resume` flow with the exact Call ID and renewed model/code authorization and permissions. Queries may be sensitive: inspect actual argument values before approval; sanitized checkpoint listings only show argument names and are insufficient content review. Pin trusted tool/configuration versions to avoid swapping backends while approval is pending.

TUI uses its existing tool entry, `LOAD TOOLS`, permission, `RUN` and `RESUME` controls. No hidden imports or durable grants are added. The generic tool channel and knowledge entries have local/headless regression coverage; [knowledge management](./knowledge-management.en.md) and [named context assembly](./knowledge-runtime.en.md) provide separate entry points. Real model-driven retrieval quality, manual layout and production interaction remain unverified.

## Parameters, results and boundaries

- Default name is `knowledge_search`; it can be renamed. Named Runtime assembly requires matching catalog key, binding name and `tools.enabled`. Descriptions are customizable; names allow at most 64 ASCII letters/digits/underscores/hyphens, starting with a letter/underscore.
- Model arguments are only `query` and optional `limit`. Backend/store/candidate IDs/credentials/deadlines/ceilings are host-bound and cannot be overridden by tool arguments. Unknown arguments and blank-only queries are rejected.
- Queries default to at most 4096 UTF-8 bytes. `max_results=4` is configurable from 1–128. Omitted `limit` uses the host maximum; explicit limits must be integers in range, not booleans. Since generic JSON Schema validation supports only a subset, the adapter independently checks numeric and byte bounds.
- Document fields default to a combined 1 MiB limit and serialized output to 64 KiB; both can be explicitly raised to 16 MiB. JSON bounds include version, notice, sources, titles, IDs, bodies and escaping. They are not token, whole-Run, whole-Provider-request or process-memory limits. Oversized results fail without truncation.
- Success returns `{"format":"wagent-knowledge-search-v1","notice":"...","documents":[{"id":...,"source":...,"title":...,"text":...}]}`. `ToolResult.data` retains the structure and `content` is compact JSON; no matches return an empty array. Duplicate documents, bad shapes and excess results fail. Sources are not downloaded or authenticated, and labels/JSON do not prevent prompt injection. Normal tool-result messages deliver content without promoting its authority.
- Retrieval defaults to a 30-second deadline; the existing Executor deadline also applies. Timeouts use `TIMED_OUT`, cancellation uses the existing Executor path with cooperative cleanup, and ordinary errors use `FAILED` without query/body/underlying-error disclosure. No automatic retry occurs, but models can request new calls; host tool-call/expense policies must constrain them.
- Default audits omit queries/bodies. Normal ToolResults, Run checkpoints, enabled event recording, model answers and host logs may retain them. There is no no-persistence or redaction guarantee.
- `ToolExecutor` enforces permission and approval. Calling `binding.handler` directly bypasses policy; custom Executors/policies remain host-owned. Components are borrowed: Runtime does not close retrievers/document clients, so hosts manage cleanup.
- Content included in main-model requests follows normal model token accounting. Embedding/retrieval charges still require explicit metering and are not automatically merged into shared pools/Session ledgers. Output-byte bounds are not cumulative expense controls.

## Progress and remaining work

Local regressions pass for bindings, permissions/approval, arguments, JSON bounds, errors, cancellation, and Runtime feedback. Optionally compose [versioned snapshots](./knowledge-ingestion.en.md), [snapshot vectors](./knowledge-vectors.en.md), and separate [index manifests/receipt journals](./knowledge-index-journal.en.md); consult each component's validation status. Tool calls never automatically write indexes. [BM25/hybrid/reranking](./knowledge-retrieval.en.md) retrievers can be injected. Live-service acceptance and remaining plans are tracked in the [roadmap](./roadmap.en.md).

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). Live-service, billing, quality and manual production UI acceptance remain outstanding.
