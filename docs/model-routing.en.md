# Models, routing, and endpoint probing

English | [简体中文](./model-routing.md)

Status: `Planned`. Version 1.5.2 only contains an OpenAI call in the chat example; it has no unified model registry or router.

## Model protocol

Standard request fields cover messages, tools, structured output, sampling, stop conditions, maximum output, modalities, cache hints, and cancellation. Namespaced extensions express provider-specific capabilities.

Providers return unified stream events: content-block start, delta, and end; tool-call delta; usage; error; and finish. Every stream has an explicit terminal event; an incomplete stream is a protocol error.

## Capability declaration

`ModelDescriptor` declares:

- Text, image, audio, and other input/output modalities.
- Streaming, tool calling, parallel tool calling, and structured output.
- Reasoning parameters and selectable values.
- Context and output limits.
- Prompt caching and other provider features.

The core does not promote provider-private enums into global enums. A provider reports an error when a caller requests an unsupported standard capability; it never silently ignores the request.

## First-release providers

`Planned`: OpenAI, Anthropic, Gemini, OpenAI-compatible APIs, Ollama, and vLLM. Adapters share one protocol conformance test suite. Custom providers register through the public `ModelProvider` interface.

## Routing pipeline

```text
Candidate provider/models
  → user policy and safety filters
  → capability matching
  → health filtering
  → cost/latency/quality scoring
  → selection
  → invocation
  → retry or failover
```

Python `RoutingPolicy` implementations and YAML rules compile to the same decision interface. Each route emits a `RouteDecision` containing an input summary, candidates, rejection reasons, scores, selection, fallback list, and policy version.

A route decision stores neither prompt plaintext nor credentials. Session event policy determines whether model input is retained.

## Endpoint probing

Three trigger modes are supported:

- Manual: CLI, TUI, or Python API invocation.
- Registration-time: a provider optionally runs safe checks.
- Periodic: a health plugin runs on configured intervals.

Probe levels:

| Level | Content | May incur cost by default |
|---|---|---|
| L1 | DNS, TCP, TLS, and HTTP reachability | No |
| L2 | Authentication and base error format | No |
| L3 | API protocol and model catalog | No |
| L4 | Minimal text generation | Possible; confirmation required |
| L5 | Streaming response | Possible; confirmation required |
| L6 | Tool calling and structured output | Possible; confirmation required |
| L7 | Multimodal capabilities | Possible; confirmation required |

A probe result contains time, endpoint identity, probe version, latency, capabilities, failure class, and expiry. Periodic probing may temporarily remove a failed route and restore it after recovery, but it never edits user configuration.

## Errors and failover

Unified errors distinguish at least configuration, authentication, rate limit, timeout, network, protocol, content-policy, and provider-service failures. Routing policy uses stable error categories to retry, back off, switch models, or terminate.

After a tool call produces a side effect, a model retry cannot automatically replay that tool. Run records explain every attempt and why a fallback route was selected.
