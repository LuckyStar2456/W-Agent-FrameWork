# Models, routing, and endpoint probing

English | [简体中文](./model-routing.md)

Status: the Phase 2A foundation is `Implemented` in `2.0.0a1`; first-party provider adapters, automatic retry/failover, automatic registration probes, and CLI/TUI entry points are `Planned`.

## Implemented boundary

- Provider-neutral messages, content blocks, tool definitions, requests, model descriptors, and responses.
- Standard capability declarations for text, image, audio, tool calling, structured output, reasoning, prompt caching, and related features.
- Strict stream events for block start, text/tool deltas, block end, usage, normalized error, and finish.
- `ModelProvider`, `ModelRegistry`, `CancellationToken`, and stable failure categories.
- Explainable `WeightedRoutingPolicy`, safe YAML policies, and `ModelRouter`.
- L1 endpoint sniffing, L2/L3 provider checks, explicitly authorized L4/L5 active probes, caching, and periodic scheduling.

No OpenAI, Anthropic, Gemini, OpenAI-compatible, Ollama, or vLLM adapter is built in yet. The protocol can carry such adapters, but that does not mean they are connected today.

## Model protocol

`ModelRequest` combines typed standard fields with a namespaced `extensions` map. It derives routing requirements from message content, tools, and the response schema. `ModelDescriptor` declares identity, capabilities, context and output limits, reasoning efforts, and provider extensions.

Providers implement one public protocol:

```python
class ModelProvider(Protocol):
    async def list_models(self) -> tuple[ModelDescriptor, ...]: ...
    async def resolve(self, model: str) -> ModelDescriptor: ...

    def stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[StreamEvent]: ...
```

`collect_stream()` rejects deltas for unopened blocks, duplicate blocks, finish with open blocks, events after finish, and incomplete streams without finish. A provider may raise `ModelError` or send `ErrorEvent`; both carry the same `ModelFailure` categories.

## Provider registration

`ModelRegistry` is built on the unified `Registry`, so it inherits version and scope resolution:

```python
models = ModelRegistry(shared_registry)
registration = models.register(
    "my-provider",
    provider,
    version="1.0.0",
    scope=ScopePath.application(),
)

resolved = models.provider("my-provider")
registration.dispose()
```

A third-party implementation does not inherit a framework base class; satisfying the `ModelProvider` protocol is sufficient.

## Explainable routing

The routing pipeline is:

```text
Current model catalog
  → requested-model and provider allow/deny filters
  → standard capability matching
  → health and cost filters
  → quality/latency/cost/health/preference score
  → selection and ordered fallbacks
  → RouteDecision
```

`RouteDecision` stores provider/model identity, acceptance or rejection reasons for every candidate, scores, fallback order, policy identity/version, and request-count summaries. It stores neither prompt plaintext nor credentials.

Python code can implement any `RoutingPolicy.select()`. The built-in `WeightedRoutingPolicy` exposes adjustable weights. `YamlRoutingPolicy` uses `yaml.safe_load` to compile declarative rules into the same interface and never imports or executes code from YAML.

```yaml
name: local-first
version: 1
preferred_providers: [ollama]
deny_providers: [disabled-provider]
max_cost_per_million: 20
required_capabilities: [streaming]
weights:
  quality: 1.0
  latency: 0.5
  cost: 0.8
  health: 1.0
  preferred_provider: 0.5
```

The current `ModelRouter` only produces decisions. It does not invoke a provider or automatically execute fallback routes. Retry, backoff, idempotency boundaries, and failover execution are Phase 2B `Planned` work.

## Endpoint probing

| Level | Current behavior | May incur model cost |
|---|---|---|
| L1 | `EndpointProbe` checks URL, DNS, TCP, TLS, and HTTP | No |
| L2 | Checks whether a provider accepts the catalog request and normalizes access failures | No |
| L3 | Reads the model catalog and declared capabilities | No |
| L4 | Minimal text generation | Yes; requires `allow_active=True` |
| L5 | Validates complete stream termination | Yes; requires `allow_active=True` |
| L6 | Reports tool/structured declarations as `SKIPPED` | Not executed today |
| L7 | Reports multimodal declarations as `SKIPPED` | Not executed today |

`EndpointProbe` sends no credentials or request body. Its result target strips URL user information, query data, and fragments. HTTP 4xx/5xx still proves reachability; provider probes handle authentication semantics.

`ProbeResult` contains the mode, individual statuses, timestamps, latency, failure category, probe version, and expiry. `ProbeCache` never returns expired results. `PeriodicProbeService` can run any probe callback periodically, but it only emits results and never edits user configuration.

The manual Python API and generic periodic scheduler are implemented. A plugin can explicitly call the same API during registration. Framework-level automatic registration wiring and `wagent probe`/TUI surfaces remain `Planned`.

## Errors and safety boundary

Stable error categories cover configuration, authentication, rate limiting, timeout, network, protocol, content policy, provider failure, and cancellation. Routing decisions can consume health status, but the current layer does not automatically retry based on it.

An active probe requires the caller to pass `allow_active=True`. That authorization covers only the current call, is not persisted, and cannot arrive through a composition code. Future failover execution must not replay a tool call that has already produced side effects.

## Phase 2B plan

- First-party OpenAI, Anthropic, Gemini, OpenAI-compatible, Ollama, and vLLM adapters with conformance tests.
- Automatic safe registration probes, CLI/TUI probe entry points, and health-state bridging.
- Provider invocation, timeout, rate limiting, backoff, retry, automatic failover, and attempt records.
- Pluggable L6/L7 active verifiers; every potentially billable verification continues to require explicit authorization.
