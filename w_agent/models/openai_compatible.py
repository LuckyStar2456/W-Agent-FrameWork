"""OpenAI Chat Completions compatible provider with replaceable HTTP transport."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from .errors import ModelError, ModelFailure, ModelFailureKind
from .provider import CancellationToken
from .types import (
    AudioContent,
    BlockEnd,
    BlockStart,
    FinishEvent,
    FinishReason,
    ImageContent,
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelRequest,
    StreamEvent,
    TextContent,
    TextDelta,
    TokenUsage,
    ToolCallContent,
    ToolCallDelta,
    ToolResultContent,
    UsageEvent,
)


class OpenAICompatibleTransport(Protocol):
    """Minimal replaceable transport used by the compatible provider."""

    async def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Mapping[str, Any]: ...

    def stream_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        timeout: float,
    ) -> AsyncIterator[Mapping[str, Any]]: ...

    async def aclose(self) -> None: ...


class HttpxOpenAICompatibleTransport:
    """Optional HTTPX transport; imported lazily to keep the core lightweight."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    def _httpx(self) -> Any:
        try:
            import httpx
        except ImportError as exc:
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.CONFIGURATION,
                    "missing-httpx",
                    "HTTPX is required; install wagent-framework[models]",
                )
            ) from exc
        return httpx

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._httpx().AsyncClient()
        return self._client

    async def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Mapping[str, Any]:
        httpx = self._httpx()
        try:
            response = await self._get_client().get(
                url, headers=dict(headers), timeout=timeout
            )
        except httpx.TimeoutException as exc:
            raise _transport_failure(ModelFailureKind.TIMEOUT, "timeout", exc, True)
        except httpx.HTTPError as exc:
            raise _transport_failure(
                ModelFailureKind.NETWORK, "network-error", exc, True
            )
        _raise_for_status(response.status_code, _response_message(response))
        try:
            value = response.json()
        except (TypeError, ValueError) as exc:
            raise _transport_failure(
                ModelFailureKind.PROTOCOL, "invalid-json", exc, False
            )
        if not isinstance(value, Mapping):
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.PROTOCOL,
                    "invalid-json-shape",
                    "provider response must be a JSON object",
                )
            )
        return value

    async def stream_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
        timeout: float,
    ) -> AsyncIterator[Mapping[str, Any]]:
        httpx = self._httpx()
        try:
            async with self._get_client().stream(
                "POST",
                url,
                headers=dict(headers),
                json=dict(body),
                timeout=timeout,
            ) as response:
                if response.status_code >= 400:
                    payload = (await response.aread()).decode(errors="replace")
                    _raise_for_status(response.status_code, payload[:1000])
                async for line in response.aiter_lines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith(":"):
                        continue
                    if stripped.startswith(("event:", "id:", "retry:")):
                        continue
                    if stripped.startswith("data:"):
                        stripped = stripped[5:].strip()
                    if stripped == "[DONE]":
                        return
                    try:
                        value = json.loads(stripped)
                    except ValueError as exc:
                        raise _transport_failure(
                            ModelFailureKind.PROTOCOL,
                            "invalid-stream-json",
                            exc,
                            False,
                        )
                    if not isinstance(value, Mapping):
                        raise ModelError(
                            ModelFailure(
                                ModelFailureKind.PROTOCOL,
                                "invalid-stream-shape",
                                "stream event must be a JSON object",
                            )
                        )
                    yield value
        except ModelError:
            raise
        except httpx.TimeoutException as exc:
            raise _transport_failure(ModelFailureKind.TIMEOUT, "timeout", exc, True)
        except httpx.HTTPError as exc:
            raise _transport_failure(
                ModelFailureKind.NETWORK, "network-error", exc, True
            )

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


@dataclass(frozen=True, slots=True)
class OpenAICompatibleModelProfile:
    """Explicit capabilities and limits for a compatible model."""

    model: str
    capabilities: frozenset[ModelCapability] = field(
        default_factory=lambda: frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.TEXT_OUTPUT,
                ModelCapability.STREAMING,
            }
        )
    )
    context_window: int | None = None
    max_output_tokens: int | None = None
    reasoning_efforts: tuple[str, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model profile needs a model identifier")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "extensions", MappingProxyType(dict(self.extensions)))


@dataclass(slots=True)
class _ToolAccumulator:
    block_index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


class OpenAICompatibleProvider:
    """Provider for OpenAI-compatible ``/models`` and ``/chat/completions`` APIs."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str | None = None,
        default_model: str | None = None,
        profiles: tuple[OpenAICompatibleModelProfile, ...] = (),
        default_capabilities: frozenset[ModelCapability] | None = None,
        discover_models: bool = True,
        timeout: float = 60.0,
        headers: Mapping[str, str] | None = None,
        max_tokens_field: str = "max_completion_tokens",
        include_stream_usage: bool = True,
        transport: OpenAICompatibleTransport | None = None,
    ) -> None:
        if not name:
            raise ValueError("provider name must not be empty")
        parsed_url = urlsplit(base_url)
        try:
            parsed_url.port
        except ValueError as exc:
            raise ValueError("base_url must be an absolute HTTP(S) URL") from exc
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_tokens_field not in {
            "max_completion_tokens",
            "max_tokens",
            "maxTokens",
        }:
            raise ValueError("unsupported max_tokens_field")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.discover_models = discover_models
        self.timeout = timeout
        self.headers = MappingProxyType(dict(headers or {}))
        self.max_tokens_field = max_tokens_field
        self.include_stream_usage = include_stream_usage
        self.transport = transport or HttpxOpenAICompatibleTransport()
        capabilities = default_capabilities or frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.TEXT_OUTPUT,
                ModelCapability.STREAMING,
            }
        )
        self.default_capabilities = frozenset(capabilities)
        self._profiles = {profile.model: profile for profile in profiles}
        self._descriptors: dict[str, ModelDescriptor] = {
            profile.model: self._descriptor(profile.model) for profile in profiles
        }
        if not discover_models and not self._profiles:
            raise ValueError("profiles are required when model discovery is disabled")

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        """Return configured profiles plus models discovered from ``/models``."""

        if self.discover_models:
            payload = await self.transport.get_json(
                f"{self.base_url}/models",
                headers=self._request_headers(),
                timeout=self.timeout,
            )
            data = payload.get("data")
            if not isinstance(data, list):
                raise ModelError(
                    ModelFailure(
                        ModelFailureKind.PROTOCOL,
                        "invalid-model-catalog",
                        "model catalog must contain a data array",
                        provider=self.name,
                    )
                )
            for item in data:
                if isinstance(item, Mapping) and isinstance(item.get("id"), str):
                    model = item["id"]
                    self._descriptors[model] = self._descriptor(model)
        return tuple(self._descriptors[key] for key in sorted(self._descriptors))

    async def resolve(self, model: str) -> ModelDescriptor:
        """Resolve a known model, refreshing discovery once when necessary."""

        descriptor = self._descriptors.get(model)
        if descriptor is None and self.discover_models:
            await self.list_models()
            descriptor = self._descriptors.get(model)
        if descriptor is None:
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.CONFIGURATION,
                    "unknown-model",
                    f"model {model!r} is not available",
                    provider=self.name,
                    model=model,
                )
            )
        return descriptor

    async def stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Translate a request and normalize Chat Completions SSE chunks."""

        if cancellation is not None:
            cancellation.raise_if_cancelled()
        model = request.model or self.default_model
        if model is None:
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.CONFIGURATION,
                    "model-required",
                    "request.model or provider default_model is required",
                    provider=self.name,
                )
            )
        descriptor = self._descriptors.get(model) or self._descriptor(model)
        missing = request.required_capabilities() - descriptor.capabilities
        if "openai.reasoning_effort" in request.extensions:
            if ModelCapability.REASONING not in descriptor.capabilities:
                missing = missing | {ModelCapability.REASONING}
        if missing:
            values = ", ".join(sorted(item.value for item in missing))
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.CONFIGURATION,
                    "unsupported-capability",
                    f"model {model!r} does not declare: {values}",
                    provider=self.name,
                    model=model,
                )
            )

        body = self._request_body(request, model)
        text_started = False
        text_parts: list[str] = []
        tools: dict[int, _ToolAccumulator] = {}
        finish_reason: FinishReason | None = None

        async for chunk in self.transport.stream_json(
            f"{self.base_url}/chat/completions",
            headers=self._request_headers(),
            body=body,
            timeout=self.timeout,
        ):
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            error = chunk.get("error")
            if isinstance(error, Mapping):
                message = error.get("message")
                raise ModelError(
                    ModelFailure(
                        ModelFailureKind.PROVIDER,
                        str(error.get("code") or "provider-stream-error"),
                        message
                        if isinstance(message, str)
                        else "provider stream failed",
                        provider=self.name,
                        model=model,
                    )
                )
            usage = chunk.get("usage")
            if isinstance(usage, Mapping):
                yield UsageEvent(_usage(usage))
            choices = chunk.get("choices", [])
            if not isinstance(choices, list):
                raise _protocol_error(
                    "stream choices must be an array", self.name, model
                )
            for choice in choices:
                if not isinstance(choice, Mapping):
                    raise _protocol_error(
                        "stream choice must be an object", self.name, model
                    )
                if choice.get("index", 0) != 0:
                    raise _protocol_error(
                        "provider returned multiple completion choices",
                        self.name,
                        model,
                    )
                delta = choice.get("delta") or {}
                if not isinstance(delta, Mapping):
                    raise _protocol_error(
                        "stream delta must be an object", self.name, model
                    )
                content = delta.get("content")
                if content is not None:
                    if not isinstance(content, str):
                        raise _protocol_error(
                            "text delta must be a string", self.name, model
                        )
                    if not text_started:
                        text_started = True
                        yield BlockStart(0, "text")
                    text_parts.append(content)
                    yield TextDelta(0, content)
                tool_deltas = delta.get("tool_calls", [])
                if not isinstance(tool_deltas, list):
                    raise _protocol_error(
                        "tool_calls delta must be an array", self.name, model
                    )
                for value in tool_deltas:
                    if not isinstance(value, Mapping) or not isinstance(
                        value.get("index"), int
                    ):
                        raise _protocol_error(
                            "tool call delta needs an integer index", self.name, model
                        )
                    tool_index = value["index"]
                    accumulator = tools.get(tool_index)
                    if accumulator is None:
                        accumulator = _ToolAccumulator(block_index=tool_index + 1)
                        tools[tool_index] = accumulator
                        yield BlockStart(accumulator.block_index, "tool-call")
                    function = value.get("function") or {}
                    if not isinstance(function, Mapping):
                        raise _protocol_error(
                            "tool function delta must be an object", self.name, model
                        )
                    if isinstance(value.get("id"), str):
                        accumulator.id += value["id"]
                    if isinstance(function.get("name"), str):
                        accumulator.name += function["name"]
                    arguments_delta = function.get("arguments", "")
                    if not isinstance(arguments_delta, str):
                        raise _protocol_error(
                            "tool arguments delta must be a string", self.name, model
                        )
                    accumulator.arguments += arguments_delta
                    yield ToolCallDelta(
                        accumulator.block_index,
                        accumulator.id,
                        accumulator.name,
                        arguments_delta,
                    )
                if choice.get("finish_reason") is not None:
                    finish_reason = _finish_reason(str(choice["finish_reason"]))

        if finish_reason is None:
            raise _protocol_error(
                "provider stream ended without finish_reason", self.name, model
            )
        if text_started:
            yield BlockEnd(0, TextContent("".join(text_parts)))
        for tool_index in sorted(tools):
            tool = tools[tool_index]
            if not tool.id or not tool.name:
                raise _protocol_error(
                    "completed tool call needs id and name", self.name, model
                )
            yield BlockEnd(
                tool.block_index,
                ToolCallContent(tool.id, tool.name, tool.arguments),
            )
        yield FinishEvent(finish_reason)

    async def aclose(self) -> None:
        """Close an owned or injected transport when it supports cleanup."""

        await self.transport.aclose()

    def _descriptor(self, model: str) -> ModelDescriptor:
        profile = self._profiles.get(model)
        return ModelDescriptor(
            provider=self.name,
            model=model,
            capabilities=(
                profile.capabilities if profile else self.default_capabilities
            ),
            context_window=profile.context_window if profile else None,
            max_output_tokens=profile.max_output_tokens if profile else None,
            reasoning_efforts=profile.reasoning_efforts if profile else (),
            extensions=profile.extensions if profile else {},
        )

    def _request_headers(self) -> Mapping[str, str]:
        headers = {"Accept": "application/json", **self.headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return MappingProxyType(headers)

    def _request_body(self, request: ModelRequest, model: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": _messages(request),
            "n": 1,
            "stream": True,
        }
        if self.include_stream_usage:
            body["stream_options"] = {"include_usage": True}
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            body[self.max_tokens_field] = request.max_output_tokens
        if request.stop:
            body["stop"] = list(request.stop)
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": dict(tool.input_schema),
                    },
                }
                for tool in request.tools
            ]
        if request.response_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": dict(request.response_schema),
                    "strict": True,
                },
            }
        reasoning_effort = request.extensions.get("openai.reasoning_effort")
        if reasoning_effort is not None:
            body["reasoning_effort"] = reasoning_effort
        overrides = request.extensions.get("openai_compatible.body", {})
        if not isinstance(overrides, Mapping):
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.CONFIGURATION,
                    "invalid-body-overrides",
                    "openai_compatible.body must be a mapping",
                    provider=self.name,
                    model=model,
                )
            )
        reserved = {
            "max_completion_tokens",
            "max_tokens",
            "maxTokens",
            "messages",
            "model",
            "n",
            "reasoning_effort",
            "response_format",
            "stop",
            "stream",
            "stream_options",
            "temperature",
            "tools",
        } & set(overrides)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.CONFIGURATION,
                    "reserved-body-overrides",
                    f"cannot override reserved request fields: {names}",
                    provider=self.name,
                    model=model,
                )
            )
        body.update(overrides)
        return body


def _messages(request: ModelRequest) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in request.messages:
        tool_results = [
            block for block in message.content if isinstance(block, ToolResultContent)
        ]
        if tool_results:
            if message.role != MessageRole.TOOL:
                raise _protocol_error(
                    "tool results require a tool message", None, request.model
                )
            if len(tool_results) != len(message.content):
                raise _protocol_error(
                    "tool-result messages cannot mix other content", None, request.model
                )
            result.extend(
                {
                    "role": "tool",
                    "tool_call_id": block.call_id,
                    "content": block.content,
                }
                for block in tool_results
            )
            continue

        if message.role == MessageRole.TOOL:
            raise _protocol_error(
                "tool messages require ToolResultContent", None, request.model
            )

        tool_calls = [
            block for block in message.content if isinstance(block, ToolCallContent)
        ]
        content_blocks = [
            block for block in message.content if not isinstance(block, ToolCallContent)
        ]
        payload: dict[str, Any] = {"role": message.role.value}
        if content_blocks:
            payload["content"] = _content(content_blocks)
        elif tool_calls:
            payload["content"] = None
        if tool_calls:
            if message.role != MessageRole.ASSISTANT:
                raise _protocol_error(
                    "tool calls require an assistant message", None, request.model
                )
            payload["tool_calls"] = [
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": block.arguments,
                    },
                }
                for block in tool_calls
            ]
        if message.name is not None:
            payload["name"] = message.name
        result.append(payload)
    return result


def _content(blocks: list[Any]) -> str | list[dict[str, Any]]:
    if len(blocks) == 1 and isinstance(blocks[0], TextContent):
        return blocks[0].text
    result: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, TextContent):
            result.append({"type": "text", "text": block.text})
        elif isinstance(block, ImageContent):
            url = block.url
            if block.data is not None:
                encoded = base64.b64encode(block.data).decode("ascii")
                url = f"data:{block.media_type};base64,{encoded}"
            result.append({"type": "image_url", "image_url": {"url": url}})
        elif isinstance(block, AudioContent):
            if block.data is None:
                raise _protocol_error(
                    "OpenAI-compatible audio input must use inline data", None, None
                )
            encoded = base64.b64encode(block.data).decode("ascii")
            audio_format = (block.media_type or "audio/wav").split("/")[-1]
            result.append(
                {
                    "type": "input_audio",
                    "input_audio": {"data": encoded, "format": audio_format},
                }
            )
        else:
            raise _protocol_error("unsupported message content", None, None)
    return result


def _usage(value: Mapping[str, Any]) -> TokenUsage:
    details = value.get("prompt_tokens_details") or {}
    if not isinstance(details, Mapping):
        details = {}
    return TokenUsage(
        input_tokens=_integer(value.get("prompt_tokens")),
        output_tokens=_integer(value.get("completion_tokens")),
        cached_input_tokens=_integer(details.get("cached_tokens")),
    )


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _finish_reason(value: str) -> FinishReason:
    return {
        "stop": FinishReason.STOP,
        "tool_calls": FinishReason.TOOL_CALLS,
        "length": FinishReason.LENGTH,
        "content_filter": FinishReason.CONTENT_FILTER,
    }.get(value, FinishReason.OTHER)


def _response_message(response: Any) -> str:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return str(getattr(response, "text", ""))[:1000]
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping) and isinstance(error.get("message"), str):
            return error["message"]
    return str(payload)[:1000]


def _raise_for_status(status: int, message: str) -> None:
    if status < 400:
        return
    if status in {401, 403}:
        kind, retryable = ModelFailureKind.AUTHENTICATION, False
    elif status == 429:
        kind, retryable = ModelFailureKind.RATE_LIMIT, True
    elif status in {408, 504}:
        kind, retryable = ModelFailureKind.TIMEOUT, True
    elif status >= 500:
        kind, retryable = ModelFailureKind.PROVIDER, True
    else:
        kind, retryable = ModelFailureKind.PROTOCOL, False
    raise ModelError(
        ModelFailure(
            kind,
            f"http-{status}",
            message or f"provider returned HTTP {status}",
            retryable,
        )
    )


def _transport_failure(
    kind: ModelFailureKind,
    code: str,
    error: Exception,
    retryable: bool,
) -> ModelError:
    return ModelError(ModelFailure(kind, code, str(error), retryable))


def _protocol_error(
    message: str, provider: str | None, model: str | None
) -> ModelError:
    return ModelError(
        ModelFailure(
            ModelFailureKind.PROTOCOL,
            "invalid-provider-response",
            message,
            provider=provider,
            model=model,
        )
    )
