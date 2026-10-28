# HTTP embeddings, native templates and shared budgets

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./embeddings.md)

2.0.0 Experimental: local regressions pass; included in 2.0.0 and outside 2.0.0a9. Live services, billing, quality and manual production UI acceptance remain outstanding.

## Protocols and templates

`AsyncEmbeddingProvider.embed_result(text)` returns `EmbeddingResult(vector, model, usage)`. `HttpTextEmbedder` also implements `embed(text) -> tuple[float, ...]`, compatible with existing `AsyncTextEmbedder`, history selectors, document retrieval and `prepare_knowledge_vectors()`. The vector-only method discards metadata: use the structured interface or budget wrapper to retain usage, never treating discarded usage as zero.

`HttpEmbeddingMapping` exposes replaceable synchronous `build_body(text, model=...)` / `parse_response(payload)`. The adapter fixes endpoint, POST method and headers; mappings handle JSON bodies only. They are trusted host code and should remain pure transformations without hidden external calls. Their own side effects are neither isolated nor accounted for.

- `JsonEmbeddingMapping` configures top-level input/model fields, fixed JSON parameters and nested vector/model/input-token paths. Paths are tuples of string keys and nonnegative list indexes, not executable expressions. Fixed parameters cannot override input/model fields. Missing optional model/usage fields stay None; malformed values fail. It validates mapped values, not arbitrary service-specific success flags; replace the mapping to check those flags.
- `openai_compatible_text_embedder(base_url, model, dimensions, ...)` appends `/embeddings` to a base URL including its API prefix. It requests float encoding; only `request_dimensions=True` sends dimensions, otherwise dimensions validates output length. Model support remains service-dependent. Its single-result mapping reads prompt_tokens/total_tokens; see the [official OpenAI reference](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create).
- `ollama_text_embedder(base_url, model, dimensions, ...)` appends `/api/embed` to the server root, disables truncation, reads one vector plus prompt_eval_count and optionally requests dimensions. It does not use legacy `/api/embeddings` or install/start/download anything. See the [official Ollama reference](https://docs.ollama.com/api/embed).

Users select models and expected dimensions. There is no latest-model selection, built-in price or inferred capability. OpenAI-compatible requests do not guarantee that an arbitrary provider/model supports embeddings.

## Assembly and the knowledge chain

```python
from w_agent import (
    KnowledgeVectorIndex, SharedBudgetTextEmbedder,
    openai_compatible_text_embedder, prepare_knowledge_vectors,
)
from my_application import embedding_settings, embedding_meter, shared_controller

# my_application supplies host-owned settings/implementations, not framework code.
raw = openai_compatible_text_embedder(
    embedding_settings.base_url,
    embedding_settings.model,
    embedding_settings.dimensions,
    api_key=embedding_settings.api_key,
)
embedder = SharedBudgetTextEmbedder(raw, shared_controller, embedding_meter)

# Host explicitly loads/prepares snapshot and binds the actual model configuration.
index = KnowledgeVectorIndex(snapshot, embedding_settings.version_label,
                             embedding_settings.dimensions)
points = await prepare_knowledge_vectors(index, embedder, confirm_embedding=True)
# No index write here; review and confirm the separate Writer plan afterward.
```

Unexecuted example. Pass the same embedder to `SnapshotVectorKnowledgeRetriever` or `QdrantSessionHistoryRetriever`. Calling `embed()`/`embed_result()` itself can send one billable request: there is no extra confirmation argument, so hosts must obtain authorization beforehand. Preparation retains `confirm_embedding=True`; query authorization follows the caller/tool policy rather than granting network permission automatically.

Credentials are never implicitly read from the environment/configuration. The OpenAI factory adds an explicitly supplied api_key as a Bearer header; generic headers support other authentication without duplicate Authorization. Text, headers and raw HTTP request/response objects can contain secrets: do not log them. Adapter repr hides endpoint/model/headers/mapping; result repr hides vector/model. This is not a guarantee that external logging is redacted.

## Response, identity and failure boundaries

- Construction performs no request or optional HTTPX import. Default bounded `HttpxToolTransport` closes its per-call client and disables redirects. Injected transports are borrowed; hosts manage closure, proxies, redirects, logging and hidden retries.
- Only HTTP(S) endpoints are accepted, without URL userinfo, query, fragment or controls. Trusted hosts choose paths/headers; this is not SSRF isolation or target authorization. Extra headers permit at most 32 entries and 4096 printable ASCII characters per value, reject case-duplicate names and Host/Content-Length/Transfer-Encoding, and fix Content-Type to JSON.
- Defaults: 1 MiB input and 2 MiB each JSON request/response, with request/response ceilings configurable up to 16 MiB. Blank input is rejected. Request serialization and response bytes are bounded. Non-2xx, duplicate JSON keys, nonfinite numbers, invalid vectors and dimension mismatch fail. Native OpenAI/Ollama mappings additionally reject their error objects. Byte limits are not token limits; no tokenizer or token truncation is supplied.
- Returned model names are service assertions, not authentication. Aliases are allowed by default; `expected_response_model` optionally enforces an exact string without proving weights or endpoint identity. Hosts still own `KnowledgeVectorIndex.embedding_key` correctness.
- Vectors have 1–65536 finite numeric coordinates, rejecting booleans/empty vectors without padding/trimming. Native templates accept one text and reject multiple results. Batch reordering, Base64 vectors and multimodal embeddings are not implemented.
- Missing usage stays None. Present counters must be nonnegative integers below 2^63. Output tokens are zero because coordinates are not generated text tokens. The OpenAI mapping requires total_tokens equal prompt_tokens. Missing service counts are never converted from character lengths into claimed actual usage.
- Default 30-second coroutine timeout mainly bounds transport waiting. Blocking synchronous mappings or cancellation-ignoring extensions cannot be forcibly stopped. Cancellation propagates separately and cannot undo charges. Ordinary failures expose fixed `EmbeddingError`; `may_have_called=True` means transport was entered, including unsuccessful/malformed/timed-out calls. No automatic retry, fallback model or replay.

## Shared budgets and visible usage

Replaceable `EmbeddingBudgetMeter.bound(text)` supplies a reliable `SharedBudgetAmount` upper bound; `actual(text, result)` preserves reported usage and optionally prices it. Bind it to the exact provider/model/parameters and cover all billed units. No character-based token guarantee or fixed price is supplied, and callbacks must not recursively call paid models.

`SharedBudgetTextEmbedder(provider, controller, meter)` supports both embedding interfaces. It can share an existing `InMemorySharedBudget` or explicitly initialized `SQLiteSharedBudget` with summary/main-model calls, without tenants or a hosted service:

1. Validate input, estimate and reserve first; refused admission never calls the provider.
2. Price and settle valid reported usage before returning. Meters cannot replace usage. Actual usage above the bound is recorded, then rejected rather than returned as success.
3. Explicit HTTP pretransport failure releases the ticket. Missing usage, provider failure, cancellation or pricing/settlement failure attempts unknown settlement. Failed cleanup leaves conservative pending reservations, not a claimed release; inspect the ledger.

Hosts can display known/held usage, known/held costs and ticket states from `controller.snapshot()`. Existing Runtime pool displays may include embedding calls when configured to use that same pool. Individual Agent Run usage, Session history and summary reports are not automatically rewritten. Shared tickets contain no source files/text/model labels/task association; hosts retain those relationships separately. Unwrapped embedding/search/tool calls remain outside the pool.

Cancellation or storage errors may occur after a commit; never replay a request merely to repair accounting. Use existing [evidence-backed budget reconciliation](./shared-budget.en.md), without automatically assuming no charges. Hosts retain client ownership, unified task accounting and responsibility for real upper bounds/prices.

## Progress and remaining work

Local regressions pass for mappings, native templates, token parsing, budget wrappers and fake HTTP/knowledge/SQLite-budget integration. Other native embedding templates, batch/multimodal support, dedicated embedding Runtime/CLI/TUI configuration, automatic preparation/main-Run accounting, real provider/Qdrant integration and final acceptance remain incomplete. See the [roadmap](./roadmap.en.md).

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
