"""Built-in native HTTP mappings for Anthropic, Gemini, Ollama, and Qwen."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote

from .errors import ModelError, ModelFailure, ModelFailureKind
from .http_provider import (
    HttpProviderMapping,
    HttpRequest,
    HttpStreamDecoder,
    HttpStreamFormat,
    HttpStreamFrame,
)
from .types import (
    AudioContent,
    BlockEnd,
    BlockStart,
    FinishEvent,
    FinishReason,
    ImageContent,
    MessageRole,
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


class AnthropicMessagesMapping(HttpProviderMapping):
    """Anthropic Messages API mapping."""

    def __init__(self, *, default_max_tokens: int = 1024) -> None:
        if default_max_tokens <= 0:
            raise ValueError("default_max_tokens must be positive")
        self.default_max_tokens = default_max_tokens

    def catalog_request(self) -> HttpRequest:
        return HttpRequest("GET", "/v1/models")

    def parse_catalog(self, payload: Mapping[str, Any]) -> tuple[str, ...]:
        return _catalog_ids(payload, "data", "id")

    def generation_request(self, request: ModelRequest, model: str) -> HttpRequest:
        system, messages = _anthropic_messages(request)
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_output_tokens or self.default_max_tokens,
            "stream": True,
        }
        if system:
            body["system"] = system
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.stop:
            body["stop_sequences"] = list(request.stop)
        if request.tools:
            body["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": dict(tool.input_schema),
                }
                for tool in request.tools
            ]
        if request.response_schema is not None:
            body["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": dict(request.response_schema),
                }
            }
        _merge_overrides(request, "anthropic.body", body)
        return HttpRequest(
            "POST",
            "/v1/messages",
            headers={"content-type": "application/json"},
            body=body,
            stream_format=HttpStreamFormat.SSE,
        )

    def stream_decoder(
        self, request: ModelRequest, model: str
    ) -> HttpStreamDecoder:
        return _AnthropicDecoder(model)


class GeminiGenerateContentMapping(HttpProviderMapping):
    """Google Gemini native generateContent mapping."""

    def catalog_request(self) -> HttpRequest:
        return HttpRequest("GET", "/v1beta/models")

    def parse_catalog(self, payload: Mapping[str, Any]) -> tuple[str, ...]:
        result: list[str] = []
        models = payload.get("models")
        if not isinstance(models, list):
            raise _protocol_error("Gemini model catalog needs a models array")
        for item in models:
            if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                result.append(item["name"].removeprefix("models/"))
        return tuple(dict.fromkeys(result))

    def generation_request(self, request: ModelRequest, model: str) -> HttpRequest:
        system, contents = _gemini_contents(request)
        body: dict[str, Any] = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if request.tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": dict(tool.input_schema),
                        }
                        for tool in request.tools
                    ]
                }
            ]
        generation: dict[str, Any] = {}
        if request.temperature is not None:
            generation["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            generation["maxOutputTokens"] = request.max_output_tokens
        if request.stop:
            generation["stopSequences"] = list(request.stop)
        if request.response_schema is not None:
            generation.update(
                {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": dict(request.response_schema),
                }
            )
        if generation:
            body["generationConfig"] = generation
        _merge_overrides(request, "gemini.body", body)
        encoded_model = quote(model.removeprefix("models/"), safe="")
        return HttpRequest(
            "POST",
            f"/v1beta/models/{encoded_model}:streamGenerateContent",
            headers={"content-type": "application/json"},
            query={"alt": "sse"},
            body=body,
            stream_format=HttpStreamFormat.SSE,
        )

    def stream_decoder(
        self, request: ModelRequest, model: str
    ) -> HttpStreamDecoder:
        return _GeminiDecoder(model)


class OllamaChatMapping(HttpProviderMapping):
    """Ollama native ``/api/chat`` mapping."""

    def catalog_request(self) -> HttpRequest:
        return HttpRequest("GET", "/api/tags")

    def parse_catalog(self, payload: Mapping[str, Any]) -> tuple[str, ...]:
        models = payload.get("models")
        if not isinstance(models, list):
            raise _protocol_error("Ollama model catalog needs a models array")
        result: list[str] = []
        for item in models:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name") or item.get("model")
            if isinstance(name, str):
                result.append(name)
        return tuple(dict.fromkeys(result))

    def generation_request(self, request: ModelRequest, model: str) -> HttpRequest:
        body: dict[str, Any] = {
            "model": model,
            "messages": _ollama_messages(request),
            "stream": True,
        }
        if request.tools:
            body["tools"] = _openai_tools(request)
        if request.response_schema is not None:
            body["format"] = dict(request.response_schema)
        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            options["num_predict"] = request.max_output_tokens
        if request.stop:
            options["stop"] = list(request.stop)
        if options:
            body["options"] = options
        _merge_overrides(request, "ollama.body", body)
        return HttpRequest(
            "POST",
            "/api/chat",
            headers={"content-type": "application/json"},
            body=body,
            stream_format=HttpStreamFormat.NDJSON,
        )

    def stream_decoder(
        self, request: ModelRequest, model: str
    ) -> HttpStreamDecoder:
        return _OllamaDecoder(model)


class QwenDashScopeMapping(HttpProviderMapping):
    """Qwen native DashScope text-generation mapping."""

    def catalog_request(self) -> None:
        return None

    def parse_catalog(self, payload: Mapping[str, Any]) -> tuple[str, ...]:
        return ()

    def generation_request(self, request: ModelRequest, model: str) -> HttpRequest:
        parameters: dict[str, Any] = {
            "result_format": "message",
            "stream": True,
            "incremental_output": True,
        }
        if request.temperature is not None:
            parameters["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            parameters["max_completion_tokens"] = request.max_output_tokens
        if request.stop:
            parameters["stop"] = list(request.stop)
        if request.tools:
            parameters["tools"] = _openai_tools(request)
        if request.response_schema is not None:
            parameters["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": dict(request.response_schema),
                    "strict": True,
                },
            }
        body: dict[str, Any] = {
            "model": model,
            "input": {"messages": _qwen_messages(request)},
            "parameters": parameters,
        }
        _merge_overrides(request, "qwen.body", body)
        return HttpRequest(
            "POST",
            "/api/v1/services/aigc/text-generation/generation",
            headers={
                "content-type": "application/json",
                "X-DashScope-SSE": "enable",
            },
            body=body,
            stream_format=HttpStreamFormat.SSE,
        )

    def stream_decoder(
        self, request: ModelRequest, model: str
    ) -> HttpStreamDecoder:
        return _QwenDecoder(model)


@dataclass(slots=True)
class _Block:
    kind: str
    id: str = ""
    name: str = ""
    value: str = ""


class _AnthropicDecoder:
    def __init__(self, model: str) -> None:
        self.model = model
        self.blocks: dict[int, _Block] = {}
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_tokens = 0
        self.reason: FinishReason | None = None
        self.stopped = False

    def feed(self, frame: HttpStreamFrame) -> tuple[StreamEvent, ...]:
        data = frame.data
        _raise_frame_error(data, self.model)
        event_type = str(data.get("type") or frame.event or "")
        events: list[StreamEvent] = []
        if event_type == "message_start":
            message = data.get("message") or {}
            if isinstance(message, Mapping):
                usage = message.get("usage") or {}
                self._update_usage(usage)
                events.append(UsageEvent(self._usage()))
        elif event_type == "content_block_start":
            index = _required_index(data)
            content = data.get("content_block") or {}
            if not isinstance(content, Mapping):
                raise _protocol_error("Anthropic content_block must be an object")
            kind = str(content.get("type") or "")
            if kind == "text":
                block = _Block("text", value=str(content.get("text") or ""))
                self.blocks[index] = block
                events.append(BlockStart(index, "text"))
                if block.value:
                    events.append(TextDelta(index, block.value))
            elif kind == "tool_use":
                block = _Block(
                    "tool-call",
                    id=str(content.get("id") or ""),
                    name=str(content.get("name") or ""),
                )
                self.blocks[index] = block
                events.append(BlockStart(index, "tool-call"))
            else:
                raise _protocol_error(f"unsupported Anthropic block type {kind!r}")
        elif event_type == "content_block_delta":
            index = _required_index(data)
            block = self.blocks.get(index)
            if block is None:
                raise _protocol_error("Anthropic delta references an unknown block")
            delta = data.get("delta") or {}
            if not isinstance(delta, Mapping):
                raise _protocol_error("Anthropic delta must be an object")
            if delta.get("type") == "text_delta":
                value = str(delta.get("text") or "")
                block.value += value
                events.append(TextDelta(index, value))
            elif delta.get("type") == "input_json_delta":
                value = str(delta.get("partial_json") or "")
                block.value += value
                events.append(ToolCallDelta(index, block.id, block.name, value))
        elif event_type == "content_block_stop":
            index = _required_index(data)
            block = self.blocks.pop(index, None)
            if block is None:
                raise _protocol_error("Anthropic stopped an unknown block")
            if block.kind == "text":
                events.append(BlockEnd(index, TextContent(block.value)))
            else:
                events.append(
                    BlockEnd(
                        index,
                        ToolCallContent(block.id, block.name, block.value or "{}"),
                    )
                )
        elif event_type == "message_delta":
            usage = data.get("usage") or {}
            self._update_usage(usage)
            events.append(UsageEvent(self._usage()))
            delta = data.get("delta") or {}
            if isinstance(delta, Mapping) and delta.get("stop_reason") is not None:
                self.reason = _finish_reason(str(delta["stop_reason"]))
        elif event_type == "message_stop":
            self.stopped = True
        return tuple(events)

    def finish(self) -> tuple[StreamEvent, ...]:
        if self.blocks:
            raise _protocol_error("Anthropic stream ended with open blocks")
        if not self.stopped:
            raise _protocol_error("Anthropic stream ended without message_stop")
        return (FinishEvent(self.reason or FinishReason.OTHER),)

    def _update_usage(self, usage: Any) -> None:
        if not isinstance(usage, Mapping):
            return
        if isinstance(usage.get("input_tokens"), int):
            self.input_tokens = usage["input_tokens"]
        if isinstance(usage.get("output_tokens"), int):
            self.output_tokens = usage["output_tokens"]
        cached = usage.get("cache_read_input_tokens")
        if isinstance(cached, int):
            self.cached_tokens = cached

    def _usage(self) -> TokenUsage:
        return TokenUsage(self.input_tokens, self.output_tokens, self.cached_tokens)


class _GeminiDecoder:
    def __init__(self, model: str) -> None:
        self.model = model
        self.text = ""
        self.text_started = False
        self.next_index = 1
        self.reason: FinishReason | None = None
        self.saw_candidate = False

    def feed(self, frame: HttpStreamFrame) -> tuple[StreamEvent, ...]:
        data = frame.data
        _raise_frame_error(data, self.model)
        events: list[StreamEvent] = []
        usage = data.get("usageMetadata")
        if isinstance(usage, Mapping):
            events.append(
                UsageEvent(
                    TokenUsage(
                        _integer(usage.get("promptTokenCount")),
                        _integer(usage.get("candidatesTokenCount")),
                        _integer(usage.get("cachedContentTokenCount")),
                    )
                )
            )
        candidates = data.get("candidates") or []
        if not isinstance(candidates, list):
            raise _protocol_error("Gemini candidates must be an array")
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            self.saw_candidate = True
            content = candidate.get("content") or {}
            parts = content.get("parts") if isinstance(content, Mapping) else []
            if not isinstance(parts, list):
                raise _protocol_error("Gemini content parts must be an array")
            for part in parts:
                if not isinstance(part, Mapping):
                    continue
                if isinstance(part.get("text"), str):
                    if not self.text_started:
                        self.text_started = True
                        events.append(BlockStart(0, "text"))
                    value = part["text"]
                    self.text += value
                    events.append(TextDelta(0, value))
                function = part.get("functionCall")
                if isinstance(function, Mapping):
                    index = self.next_index
                    self.next_index += 1
                    name = str(function.get("name") or "")
                    arguments = json.dumps(
                        function.get("args") or {}, separators=(",", ":")
                    )
                    call_id = str(function.get("id") or f"gemini-{index}")
                    events.extend(
                        (
                            BlockStart(index, "tool-call"),
                            ToolCallDelta(index, call_id, name, arguments),
                            BlockEnd(
                                index,
                                ToolCallContent(call_id, name, arguments),
                            ),
                        )
                    )
            if candidate.get("finishReason") is not None:
                self.reason = _finish_reason(str(candidate["finishReason"]))
        return tuple(events)

    def finish(self) -> tuple[StreamEvent, ...]:
        if not self.saw_candidate:
            raise _protocol_error("Gemini stream returned no candidate")
        events: list[StreamEvent] = []
        if self.text_started:
            events.append(BlockEnd(0, TextContent(self.text)))
        events.append(FinishEvent(self.reason or FinishReason.OTHER))
        return tuple(events)


class _OllamaDecoder:
    def __init__(self, model: str) -> None:
        self.model = model
        self.text = ""
        self.text_started = False
        self.next_index = 1
        self.reason: FinishReason | None = None
        self.done = False

    def feed(self, frame: HttpStreamFrame) -> tuple[StreamEvent, ...]:
        data = frame.data
        _raise_frame_error(data, self.model)
        events: list[StreamEvent] = []
        message = data.get("message") or {}
        if not isinstance(message, Mapping):
            raise _protocol_error("Ollama message must be an object")
        content = message.get("content")
        if isinstance(content, str) and content:
            if not self.text_started:
                self.text_started = True
                events.append(BlockStart(0, "text"))
            self.text += content
            events.append(TextDelta(0, content))
        tools = message.get("tool_calls") or []
        if not isinstance(tools, list):
            raise _protocol_error("Ollama tool_calls must be an array")
        for tool in tools:
            if not isinstance(tool, Mapping):
                continue
            function = tool.get("function") or {}
            if not isinstance(function, Mapping):
                continue
            index = self.next_index
            self.next_index += 1
            name = str(function.get("name") or "")
            arguments = function.get("arguments") or {}
            encoded = (
                arguments
                if isinstance(arguments, str)
                else json.dumps(arguments, separators=(",", ":"))
            )
            call_id = str(tool.get("id") or f"ollama-{index}")
            events.extend(
                (
                    BlockStart(index, "tool-call"),
                    ToolCallDelta(index, call_id, name, encoded),
                    BlockEnd(index, ToolCallContent(call_id, name, encoded)),
                )
            )
        if data.get("done") is True:
            self.done = True
            self.reason = _finish_reason(str(data.get("done_reason") or "stop"))
            events.append(
                UsageEvent(
                    TokenUsage(
                        _integer(data.get("prompt_eval_count")),
                        _integer(data.get("eval_count")),
                    )
                )
            )
        return tuple(events)

    def finish(self) -> tuple[StreamEvent, ...]:
        if not self.done:
            raise _protocol_error("Ollama stream ended without done=true")
        events: list[StreamEvent] = []
        if self.text_started:
            events.append(BlockEnd(0, TextContent(self.text)))
        events.append(FinishEvent(self.reason or FinishReason.OTHER))
        return tuple(events)


@dataclass(slots=True)
class _Tool:
    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


class _QwenDecoder:
    def __init__(self, model: str) -> None:
        self.model = model
        self.text = ""
        self.text_started = False
        self.tools: dict[int, _Tool] = {}
        self.reason: FinishReason | None = None

    def feed(self, frame: HttpStreamFrame) -> tuple[StreamEvent, ...]:
        data = frame.data
        _raise_frame_error(data, self.model)
        events: list[StreamEvent] = []
        usage = data.get("usage")
        if isinstance(usage, Mapping):
            details = usage.get("prompt_tokens_details") or {}
            events.append(
                UsageEvent(
                    TokenUsage(
                        _integer(usage.get("input_tokens")),
                        _integer(usage.get("output_tokens")),
                        _integer(
                            details.get("cached_tokens")
                            if isinstance(details, Mapping)
                            else None
                        ),
                    )
                )
            )
        output = data.get("output") or {}
        if not isinstance(output, Mapping):
            raise _protocol_error("Qwen output must be an object")
        choices = output.get("choices") or []
        if not isinstance(choices, list):
            raise _protocol_error("Qwen output.choices must be an array")
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            message = choice.get("message") or {}
            if not isinstance(message, Mapping):
                continue
            content = message.get("content")
            if isinstance(content, str) and content:
                if not self.text_started:
                    self.text_started = True
                    events.append(BlockStart(0, "text"))
                self.text += content
                events.append(TextDelta(0, content))
            for value in message.get("tool_calls") or []:
                if not isinstance(value, Mapping):
                    continue
                tool_index = _integer(value.get("index"))
                tool = self.tools.get(tool_index)
                if tool is None:
                    tool = _Tool(index=tool_index + 1)
                    self.tools[tool_index] = tool
                    events.append(BlockStart(tool.index, "tool-call"))
                function = value.get("function") or {}
                if isinstance(value.get("id"), str):
                    tool.id += value["id"]
                if isinstance(function, Mapping):
                    if isinstance(function.get("name"), str):
                        tool.name += function["name"]
                    delta = function.get("arguments") or ""
                    if not isinstance(delta, str):
                        delta = json.dumps(delta, separators=(",", ":"))
                    tool.arguments += delta
                    events.append(
                        ToolCallDelta(tool.index, tool.id, tool.name, delta)
                    )
            if choice.get("finish_reason") is not None:
                self.reason = _finish_reason(str(choice["finish_reason"]))
        return tuple(events)

    def finish(self) -> tuple[StreamEvent, ...]:
        if self.reason is None:
            raise _protocol_error("Qwen stream ended without finish_reason")
        events: list[StreamEvent] = []
        if self.text_started:
            events.append(BlockEnd(0, TextContent(self.text)))
        for key in sorted(self.tools):
            tool = self.tools[key]
            events.append(
                BlockEnd(
                    tool.index,
                    ToolCallContent(tool.id, tool.name, tool.arguments or "{}"),
                )
            )
        events.append(FinishEvent(self.reason))
        return tuple(events)


def _anthropic_messages(
    request: ModelRequest,
) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == MessageRole.SYSTEM:
            for block in message.content:
                if not isinstance(block, TextContent):
                    raise _protocol_error("Anthropic system messages must be text")
                system_parts.append(block.text)
            continue
        role = "user" if message.role == MessageRole.TOOL else message.role.value
        if role not in {"user", "assistant"}:
            raise _protocol_error("unsupported Anthropic message role")
        content: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, TextContent):
                content.append({"type": "text", "text": block.text})
            elif isinstance(block, ImageContent):
                content.append(_anthropic_image(block))
            elif isinstance(block, ToolCallContent):
                content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": _json_arguments(block.arguments),
                    }
                )
            elif isinstance(block, ToolResultContent):
                content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.call_id,
                        "content": block.content,
                        "is_error": block.is_error,
                    }
                )
            else:
                raise _protocol_error("unsupported Anthropic content block")
        messages.append({"role": role, "content": content})
    return "\n\n".join(system_parts), messages


def _anthropic_image(block: ImageContent) -> dict[str, Any]:
    if block.data is not None:
        source = {
            "type": "base64",
            "media_type": block.media_type,
            "data": base64.b64encode(block.data).decode("ascii"),
        }
    else:
        source = {"type": "url", "url": block.url}
    return {"type": "image", "source": source}


def _gemini_contents(
    request: ModelRequest,
) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == MessageRole.SYSTEM:
            for block in message.content:
                if not isinstance(block, TextContent):
                    raise _protocol_error("Gemini system messages must be text")
                system_parts.append(block.text)
            continue
        role = "model" if message.role == MessageRole.ASSISTANT else "user"
        parts: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, TextContent):
                parts.append({"text": block.text})
            elif isinstance(block, (ImageContent, AudioContent)):
                parts.append(_gemini_media(block))
            elif isinstance(block, ToolCallContent):
                parts.append(
                    {
                        "functionCall": {
                            "name": block.name,
                            "args": _json_arguments(block.arguments),
                        }
                    }
                )
            elif isinstance(block, ToolResultContent):
                parts.append(
                    {
                        "functionResponse": {
                            "name": message.name or block.call_id,
                            "response": {
                                "content": block.content,
                                "is_error": block.is_error,
                            },
                        }
                    }
                )
            else:
                raise _protocol_error("unsupported Gemini content block")
        contents.append({"role": role, "parts": parts})
    return "\n\n".join(system_parts), contents


def _gemini_media(block: ImageContent | AudioContent) -> dict[str, Any]:
    if block.data is not None:
        return {
            "inlineData": {
                "mimeType": block.media_type,
                "data": base64.b64encode(block.data).decode("ascii"),
            }
        }
    if not block.media_type:
        raise _protocol_error("Gemini URL media needs a media_type")
    return {"fileData": {"mimeType": block.media_type, "fileUri": block.url}}


def _ollama_messages(request: ModelRequest) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in request.messages:
        payload: dict[str, Any] = {"role": message.role.value}
        text: list[str] = []
        images: list[str] = []
        tools: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, TextContent):
                text.append(block.text)
            elif isinstance(block, ImageContent):
                if block.data is None:
                    raise _protocol_error("Ollama native images require inline data")
                images.append(base64.b64encode(block.data).decode("ascii"))
            elif isinstance(block, ToolCallContent):
                tools.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": _json_arguments(block.arguments),
                        },
                    }
                )
            elif isinstance(block, ToolResultContent):
                text.append(block.content)
                payload["tool_call_id"] = block.call_id
            else:
                raise _protocol_error("unsupported Ollama content block")
        payload["content"] = "\n".join(text)
        if images:
            payload["images"] = images
        if tools:
            payload["tool_calls"] = tools
        result.append(payload)
    return result


def _qwen_messages(request: ModelRequest) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in request.messages:
        payload: dict[str, Any] = {"role": message.role.value}
        text: list[str] = []
        calls: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, TextContent):
                text.append(block.text)
            elif isinstance(block, ToolCallContent):
                calls.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": block.arguments,
                        },
                    }
                )
            elif isinstance(block, ToolResultContent):
                text.append(block.content)
                payload["tool_call_id"] = block.call_id
            else:
                raise _protocol_error(
                    "Qwen DashScope text template only accepts text and tools"
                )
        payload["content"] = "\n".join(text)
        if calls:
            payload["tool_calls"] = calls
        result.append(payload)
    return result


def _openai_tools(request: ModelRequest) -> list[dict[str, Any]]:
    return [
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


def _merge_overrides(
    request: ModelRequest, namespace: str, body: dict[str, Any]
) -> None:
    overrides = request.extensions.get(namespace, {})
    if not isinstance(overrides, Mapping):
        raise ModelError(
            ModelFailure(
                ModelFailureKind.CONFIGURATION,
                "invalid-body-overrides",
                f"{namespace} must be a mapping",
                model=request.model,
            )
        )
    reserved = set(body) & set(overrides)
    if reserved:
        names = ", ".join(sorted(reserved))
        raise ModelError(
            ModelFailure(
                ModelFailureKind.CONFIGURATION,
                "reserved-body-overrides",
                f"cannot override reserved request fields: {names}",
                model=request.model,
            )
        )
    body.update(overrides)


def _catalog_ids(
    payload: Mapping[str, Any], collection: str, key: str
) -> tuple[str, ...]:
    values = payload.get(collection)
    if not isinstance(values, list):
        raise _protocol_error(f"model catalog needs a {collection} array")
    result = [
        item[key]
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get(key), str)
    ]
    return tuple(dict.fromkeys(result))


def _required_index(data: Mapping[str, Any]) -> int:
    value = data.get("index")
    if not isinstance(value, int) or value < 0:
        raise _protocol_error("stream event needs a non-negative index")
    return value


def _json_arguments(value: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(value)
    except ValueError as exc:
        raise _protocol_error("tool arguments must contain valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise _protocol_error("tool arguments must contain a JSON object")
    return parsed


def _raise_frame_error(data: Mapping[str, Any], model: str) -> None:
    error = data.get("error")
    if isinstance(error, Mapping):
        message = error.get("message")
        raise ModelError(
            ModelFailure(
                ModelFailureKind.PROVIDER,
                str(error.get("code") or "provider-stream-error"),
                str(message or "provider stream failed"),
                provider=None,
                model=model,
            )
        )
    code = data.get("code")
    if code and code not in {200, "200", ""}:
        raise ModelError(
            ModelFailure(
                ModelFailureKind.PROVIDER,
                str(code),
                str(data.get("message") or "provider stream failed"),
                model=model,
            )
        )


def _finish_reason(value: str) -> FinishReason:
    normalized = value.lower()
    return {
        "stop": FinishReason.STOP,
        "end_turn": FinishReason.STOP,
        "tool_use": FinishReason.TOOL_CALLS,
        "tool_calls": FinishReason.TOOL_CALLS,
        "length": FinishReason.LENGTH,
        "max_tokens": FinishReason.LENGTH,
        "content_filter": FinishReason.CONTENT_FILTER,
        "safety": FinishReason.CONTENT_FILTER,
        "cancelled": FinishReason.CANCELLED,
    }.get(normalized, FinishReason.OTHER)


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _protocol_error(message: str) -> ModelError:
    return ModelError(
        ModelFailure(
            ModelFailureKind.PROTOCOL,
            "invalid-provider-response",
            message,
        )
    )
