# Models, routing, and endpoint probing

English | [简体中文](./model-routing.md)

Status: the Phase 2A foundation plus the Phase 2B generic HTTP mapping layer, OpenAI-compatible provider, initial vendor templates, collecting/event-pass-through executors, and an explicit register-and-safe-probe service are `Implemented` in `2.0.0a1`; dedicated OpenAI Responses and vLLM handling, cross-stream recovery, and CLI/TUI entry points are `Planned`.

## Implemented boundary

- Provider-neutral messages, content blocks, tool definitions, requests, model descriptors, and responses.
- Standard capability declarations for text, image, audio, tool calling, structured output, reasoning, prompt caching, and related features.
- Strict stream events for block start, text/tool deltas, block end, usage, normalized error, and finish.
- `ModelProvider`, `ModelRegistry`, `CancellationToken`, and stable failure categories.
- Explainable `WeightedRoutingPolicy`, safe YAML policies, and `ModelRouter`.
- L1 endpoint sniffing, L2/L3 provider checks, explicitly authorized L4/L5 active probes, caching, and periodic scheduling.
- An OpenAI-compatible `/models` and `/chat/completions` provider with text, image/inline-audio input, tools, structured output, and SSE conversion.
- Replaceable `HttpModelProvider`, request/frame, mapper, stream-decoder, and transport protocols; the default transport supports JSON, SSE, and NDJSON.
- Native templates for Anthropic Messages, Gemini `streamGenerateContent`, Ollama `/api/chat`, and Qwen DashScope.
- DeepSeek, GLM, Qwen OpenAI-compatible, and Turbo AI/SIAM.AI templates plus an independent template registry.
- `ModelExecutor` collecting and event-pass-through invocation, per-attempt timeouts, explicit bounded retry/failover, and prompt-free attempt records.
- `ModelRegistrationProbeService` register-and-safe-probe wiring plus `ProbeHealthBridge` projection of fresh observations into external `CandidateState`.

Dedicated OpenAI Responses and vLLM-specific adapters are not built in yet. Templates have fake-transport conformance tests, but repository tests contain no live credentials and do not claim that any individual remote model has been validated online. See [HTTP providers and vendor templates](./provider-templates.en.md) for details.

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

`ModelStreamValidator` validates events incrementally; `collect_stream()` reuses it to build a final response. They reject deltas for unopened blocks, duplicate blocks, finish with open blocks, events after finish, and incomplete streams without finish. A provider may raise `ModelError` or send `ErrorEvent`; both carry the same `ModelFailure` categories.

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

### OpenAI-compatible provider

Install the optional HTTP transport:

```bash
pip install "wagent-framework[models]"
```

```python
from w_agent import (
    ModelCapability,
    OpenAICompatibleModelProfile,
    OpenAICompatibleProvider,
)

provider = OpenAICompatibleProvider(
    name="local",
    base_url="http://127.0.0.1:11434/v1",
    default_model="my-model",
    profiles=(
        OpenAICompatibleModelProfile(
            "my-model",
            frozenset(
                {
                    ModelCapability.TEXT_INPUT,
                    ModelCapability.TEXT_OUTPUT,
                    ModelCapability.STREAMING,
                }
            ),
        ),
    ),
    discover_models=False,
)
```

Capabilities are never guessed from model names; developers explicitly declare every non-default capability in a profile. The `openai_compatible.body` extension can add vendor parameters but cannot replace core model, message, stream, tool, or structured-output fields. The HTTP layer is replaceable through `OpenAICompatibleTransport`, so the core depends on no specific SDK.

### Generic HTTP mapping layer and templates

`HttpModelProvider` composes an `HttpProviderMapping` with an `HttpProviderTransport`. A mapper creates catalog/inference requests and converts vendor frames to standard events; a transport only handles HTTP, SSE, or NDJSON. Applications may replace either layer and register their own `ProviderTemplate` in an independent `ProviderTemplateRegistry`.

Built-in keys are `anthropic`, `gemini`, `ollama`, `qwen-native`, `deepseek`, `glm`, `qwen`, and `turbo`. `turbo` means Turbo AI/SIAM.AI and requires an explicit deployment URL. Qwen provides both native DashScope and OpenAI-compatible paths.

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

`ModelRouter` continues to produce decisions only. `ModelExecutor` is a separate consumer that invokes providers according to a decision. Either part can be replaced without embedding execution rules in routing policy.

## Invocation, retry, and failover

`ModelExecutor.invoke()` consumes a route decision and returns `ModelInvocationResult`, containing the complete `ModelResponse`, the provider/model that succeeded, the original `RouteDecision`, and immutable `AttemptRecord` entries. `ModelExecutor.stream()` returns a single-use `ModelStreamExecution` that exposes standard `StreamEvent` objects as they arrive; after iteration completes, its `response`, actual provider/model, and attempt records are available.

```python
from w_agent import InvocationPolicy, ModelExecutor

executor = ModelExecutor(
    models,
    router,
    InvocationPolicy(
        max_attempts_per_route=2,
        max_routes=2,
        timeout=30,
        initial_backoff=0.25,
    ),
)
result = await executor.invoke(request)

execution = executor.stream(request)
async for event in execution:
    handle(event)

final_response = execution.response
```

The default policy permits one attempt on one route, so it never creates extra potentially billable calls without configuration. Raising either limit is explicit replay authorization by the developer assembling that executor. A failure is replayed only when it has `retryable=True` and its normalized kind is rate limit, timeout, network, or provider failure. Authentication, configuration, content-policy, and protocol errors stop immediately by default. Backoff is deterministic, bounded, and replaceable; custom policies only need to satisfy `InvocationPolicyProtocol`.

Collecting mode validates the complete provider stream through `collect_stream()` before returning, so policy-driven route switching remains safe before results become visible. Pass-through mode validates and yields each event incrementally: retry or failover is allowed before the first event becomes visible, but any later failure terminates the execution without silent replay, preventing duplicated text or tool-call deltas. In pass-through mode, `timeout` bounds waiting for the provider's next frame and excludes time spent by the caller processing an event.

Callers may set `replay_safe=False` to force one attempt on the selected route even when the assembled policy permits retries. `AttemptRecord` contains provider/model identity, indexes, duration, emitted-event count, normalized failure, next delay, and TokenUsage/`usage_reported` when explicitly supplied by the provider—never messages, prompts, bodies, or credentials. Missing usage for a failed attempt remains unknown rather than being inferred as zero. Ordinary model execution does not mutate `CandidateState`; health feedback must be attached through an explicit observation or registration-probe service.

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

`ProbeResult` contains the mode, individual statuses, timestamps, latency, failure category, probe version, expiry, and discovered provider/model routes. `ProbeCache` never returns expired results. `PeriodicProbeService` can run any probe callback periodically, but it only emits results and never edits user configuration.

The manual Python API and generic periodic scheduler are implemented. Compositions that need register-and-safe-probe use `ModelRegistrationProbeService.register()`: it always runs `ProbeMode.SAFE`, never calls generation, caches the result, and uses `ProbeHealthBridge` to update only routes found by that probe; expired observations map to `UNKNOWN`. Cancellation or an unexpected exception rolls back the new registration. Direct `ModelRegistry.register()` remains pure and performs no I/O. The `wagent probe` command and TUI surfaces remain `Planned`.

## Errors and safety boundary

Stable error categories cover configuration, authentication, rate limiting, timeout, network, protocol, content policy, provider failure, and cancellation. A route decision may consume health state but performs no retry itself; `ModelExecutor` handles normalized failures only according to an explicit `InvocationPolicy`.

An active probe requires the caller to pass `allow_active=True`. That authorization covers only the current call, is not persisted, and cannot arrive through a composition code. The model executor's `replay_safe` flag applies only to model requests; a future tool executor still must not replay a tool call that has already produced side effects.

## Remaining Phase 2B plan

- Dedicated OpenAI Responses and vLLM differences, plus reasoning deltas and more vendor-specific features in existing templates.
- CLI/TUI probe entry points.
- Cross-stream recovery and pluggable feedback bridges to rate limiters.
- Pluggable L6/L7 active verifiers; every potentially billable verification continues to require explicit authorization.
