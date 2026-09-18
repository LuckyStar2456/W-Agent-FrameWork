# HTTP providers and vendor templates

English | [简体中文](./provider-templates.md)

Status: `Implemented` on current main and not separately released yet. This page describes the generic HTTP request-mapping layer, native protocol templates, and OpenAI-compatible vendor templates. A template is an editable local assembly starting point, not a hosted service or hidden vendor lock-in.

## Layers

```text
ModelRequest / StreamEvent
          ↕
HttpProviderMapping + HttpStreamDecoder       vendor request/response semantics
          ↕
HttpRequest / HttpStreamFrame                 HTTP and SSE/NDJSON frames
          ↕
HttpProviderTransport                         replaceable transport
```

- `HttpModelProvider` handles model resolution, capability checks, cancellation, mapping calls, and normalized events only.
- `HttpProviderMapping` defines catalog requests, catalog parsing, generation requests, and stateful stream-decoder creation.
- `HttpProviderTransport` owns I/O. The default `HttpxProviderTransport` supports JSON, SSE, and NDJSON; tests and applications may inject another transport.
- `HttpRequest`, `HttpStreamFrame`, and `HttpStreamDecoder` are public extension points. Custom implementations satisfy protocols and need not inherit a framework base class.

## Built-in templates

| Key | Protocol | Default base URL | Current template scope |
|---|---|---|---|
| `openai-responses` | Native OpenAI Responses | `https://api.openai.com/v1` | `/models`, `/responses`, SSE, text/images, function tools, structured output, reasoning requests, and token usage |
| `anthropic` | Native Anthropic Messages | `https://api.anthropic.com` | Catalog, SSE, text/images, tools, structured output |
| `gemini` | Native Gemini `streamGenerateContent` | `https://generativelanguage.googleapis.com` | Catalog, SSE, text/images/audio, tools, structured output |
| `ollama` | Native Ollama `/api/chat` | `http://127.0.0.1:11434` | `/api/tags`, NDJSON, text/inline images, tools, structured output |
| `qwen-native` | Native DashScope Generation | `https://dashscope-intl.aliyuncs.com` | SSE, text, tools, structured output; configure models explicitly |
| `deepseek` | OpenAI-compatible Chat Completions | `https://api.deepseek.com` | Vendor URL and conservative capability defaults |
| `glm` | OpenAI-compatible Chat Completions | `https://open.bigmodel.cn/api/paas/v4` | Vendor URL and conservative capability defaults |
| `qwen` | DashScope OpenAI-compatible | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | Compatible entry point; can coexist with `qwen-native` |
| `vllm` | vLLM OpenAI-compatible Chat Completions | `http://127.0.0.1:8000/v1` | Catalog, Chat SSE, `structured_outputs`, priority/request/session IDs, and arbitrary non-core vLLM parameters |
| `turbo` | Turbo AI/SIAM.AI OpenAI-compatible | None | User supplies the deployment URL; text-only by default |

Here, `turbo` explicitly means Turbo AI/SIAM.AI. Its documentation uses deployment-instance URLs, so the framework stores no example IP and never guesses an endpoint. For another service named Turbo, copy the template and replace its protocol mapping.

Templates do not infer vision, reasoning, parallel tools, or similar capabilities from model names. Where model variants differ, declare them with `HttpModelProfile` or `OpenAICompatibleModelProfile`. A declaration makes a capability routable; it does not mean that W-Agent has validated every remote model online.

## Usage

Install the optional transport:

```bash
pip install "wagent-framework[models]"
```

Use a factory directly:

```python
from w_agent import ModelMessage, ModelRequest, MessageRole, anthropic_provider

provider = anthropic_provider(
    api_key="...",
    default_model="your-model-id",
)

request = ModelRequest(
    messages=(ModelMessage.text(MessageRole.USER, "Hello"),),
)
```

Or assemble through the template registry:

```python
from w_agent import builtin_provider_template_registry

templates = builtin_provider_template_registry()
provider = templates.build(
    "ollama",
    default_model="your-local-model",
)
```

`BUILTIN_PROVIDER_TEMPLATES` is the immutable built-in catalog. Each `builtin_provider_template_registry()` call returns an independent mutable registry. Applications can replace a key or register a new `ProviderTemplate` without changing another application or process-global state.

## Custom mappings

A minimal mapping implements four methods:

```python
class MyMapping:
    def catalog_request(self) -> HttpRequest | None: ...
    def parse_catalog(self, payload) -> tuple[str, ...]: ...
    def generation_request(self, request, model) -> HttpRequest: ...
    def stream_decoder(self, request, model) -> HttpStreamDecoder: ...
```

A mapper may change paths, headers, bodies, extensions, and response events. A transport may change authentication, proxies, pools, record/replay, or replace HTTPX entirely. Provider core imports no vendor SDK.

Vendor-specific request additions use `anthropic.body`, `gemini.body`, `ollama.body`, or `qwen.body`. Additions cannot overwrite core fields generated by a template. To change core behavior, copy or replace the mapper so configuration cannot silently diverge from wire semantics.

`openai-responses` uses `openai_responses.reasoning` and `openai_responses.body`; the latter may only add non-core fields such as `store` or `previous_response_id`. It maps system text to `instructions`, messages plus function calls/results to typed `input`, and text/function deltas, terminal states, and input/output/cached token counts to stable events. Audio input, hosted built-in tools, and reasoning-content deltas are not mapped yet. `ModelRequest.stop` fails explicitly instead of being silently ignored.

`vllm` reuses the Chat Completions event converter and adds `vllm.structured_outputs`, `vllm.priority`, `vllm.request_id`, `vllm.session_id`, and `vllm.body`. The last accepts non-core server fields such as `top_k` and `min_p` but cannot replace framework-generated model, message, stream, tool, or structured-output fields. vLLM applies a model repository's `generation_config.json` by default; that is server behavior, and the framework does not assume sampling defaults. Actual chat-template, tool, parallel-call, vision, and reasoning support remains model- and server-configuration-dependent, so profiles should narrow capabilities.

## Security and current limits

- API keys enter request headers only; they are absent from model descriptors, route decisions, and the template catalog.
- Base URLs reject user information, query strings, fragments, and invalid ports. Users still decide whether to trust a private deployment URL.
- Repository tests use fake transports and spend no remote quota. Real credentials and live compatibility are not validated in the repository suite.
- OpenAI Responses and vLLM-specific differences are implemented and can be assembled by strict local configuration and the CLI/TUI run and probe paths; the model execution layer separately provides explicit text-prefix replay recovery. Reasoning-content deltas, OpenAI hosted-tool events, multimodal output, and provider-native cursor continuation remain `Planned`.
- Vendor protocols change. Templates version with W-Agent; applications may pin, copy, or register their own versions.

Protocol references: [OpenAI Responses](https://developers.openai.com/api/reference/typescript/resources/beta/subresources/responses/methods/create), [vLLM OpenAI-Compatible Server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/), [Anthropic Messages](https://platform.claude.com/docs/en/api/overview), [Gemini API](https://ai.google.dev/api/generate-content), [Ollama Chat](https://docs.ollama.com/api/chat), [Qwen DashScope](https://docs.qwencloud.com/api-reference/chat/dashscope), [DeepSeek API](https://api-docs.deepseek.com/zh-cn/), [GLM quick start](https://zhipu-ef7018ed.mintlify.app/cn/guide/start/quick-start), and [Turbo AI Endpoint](https://docs.turbo-ai.com/features/endpoint/).
