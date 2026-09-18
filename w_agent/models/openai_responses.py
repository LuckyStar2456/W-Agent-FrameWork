"""OpenAI Responses API mapping for the generic HTTP provider."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Mapping

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


class OpenAIResponsesMapping(HttpProviderMapping):
    """Translate stable model requests to the OpenAI Responses API."""

    def catalog_request(self) -> HttpRequest:
        return HttpRequest("GET", "/models")

    def parse_catalog(self, payload: Mapping[str, Any]) -> tuple[str, ...]:
        data = payload.get("data")
        if not isinstance(data, list):
            raise _protocol_error("OpenAI model catalog needs a data array")
        result: list[str] = []
        for item in data:
            if isinstance(item, Mapping) and isinstance(item.get("id"), str):
                result.append(item["id"])
        return tuple(dict.fromkeys(result))

    def generation_request(self, request: ModelRequest, model: str) -> HttpRequest:
        if request.stop:
            raise _configuration_error(
                "unsupported-stop",
                "OpenAI Responses does not expose stop sequences",
                model,
            )
        instructions, inputs = _responses_input(request)
        body: dict[str, Any] = {
            "model": model,
            "input": inputs,
            "stream": True,
        }
        if instructions:
            body["instructions"] = instructions
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            body["max_output_tokens"] = request.max_output_tokens
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": dict(tool.input_schema),
                    "strict": True,
                }
                for tool in request.tools
            ]
        if request.response_schema is not None:
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "response",
                    "schema": dict(request.response_schema),
                    "strict": True,
                }
            }
        reasoning = request.extensions.get("openai_responses.reasoning")
        if reasoning is not None:
            if not isinstance(reasoning, Mapping):
                raise _configuration_error(
                    "invalid-reasoning",
                    "openai_responses.reasoning must be a mapping",
                    model,
                )
            body["reasoning"] = dict(reasoning)
        overrides = request.extensions.get("openai_responses.body", {})
        if not isinstance(overrides, Mapping):
            raise _configuration_error(
                "invalid-body-overrides",
                "openai_responses.body must be a mapping",
                model,
            )
        reserved = {
            "input",
            "instructions",
            "max_output_tokens",
            "model",
            "reasoning",
            "stream",
            "temperature",
            "text",
            "tools",
        } & set(overrides)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise _configuration_error(
                "reserved-body-overrides",
                f"cannot override reserved request fields: {names}",
                model,
            )
        body.update(overrides)
        return HttpRequest(
            "POST",
            "/responses",
            headers={"content-type": "application/json"},
            body=body,
            stream_format=HttpStreamFormat.SSE,
        )

    def stream_decoder(self, request: ModelRequest, model: str) -> HttpStreamDecoder:
        return _OpenAIResponsesDecoder(model)


@dataclass(slots=True)
class _TextAccumulator:
    index: int
    value: str = ""
    closed: bool = False


@dataclass(slots=True)
class _ToolAccumulator:
    index: int
    call_id: str
    name: str
    arguments: str = ""
    closed: bool = False


class _OpenAIResponsesDecoder:
    def __init__(self, model: str) -> None:
        self.model = model
        self._next_index = 0
        self._texts: dict[tuple[int, int], _TextAccumulator] = {}
        self._tools: dict[int, _ToolAccumulator] = {}
        self._terminal = False
        self._saw_tool = False

    def feed(self, frame: HttpStreamFrame) -> tuple[StreamEvent, ...]:
        data = frame.data
        event_type = data.get("type") or frame.event
        if not isinstance(event_type, str):
            raise _protocol_error("OpenAI Responses event needs a type", self.model)
        if self._terminal:
            raise _protocol_error(
                "OpenAI Responses emitted an event after terminal state", self.model
            )
        if event_type in {
            "response.created",
            "response.in_progress",
            "response.content_part.done",
        }:
            return ()
        if event_type == "response.output_item.added":
            return self._output_item_added(data)
        if event_type == "response.content_part.added":
            return self._content_part_added(data)
        if event_type == "response.output_text.delta":
            return self._text_delta(data)
        if event_type == "response.output_text.done":
            return self._text_done(data)
        if event_type == "response.function_call_arguments.delta":
            return self._tool_delta(data)
        if event_type == "response.function_call_arguments.done":
            return self._tool_done(data)
        if event_type == "response.output_item.done":
            return self._output_item_done(data)
        if event_type in {
            "response.completed",
            "response.incomplete",
            "response.cancelled",
            "response.failed",
        }:
            return self._terminal_event(data, event_type)
        if event_type in {"error", "response.error"}:
            raise _response_error(data, self.model)
        # Responses adds event families over time. Unknown events are ignored so
        # optional built-in tools do not break text/function-call consumers.
        return ()

    def finish(self) -> tuple[StreamEvent, ...]:
        if not self._terminal:
            raise _protocol_error(
                "OpenAI Responses stream ended without a terminal event", self.model
            )
        return ()

    def _allocate(self) -> int:
        value = self._next_index
        self._next_index += 1
        return value

    def _ensure_text(
        self, output_index: int, content_index: int
    ) -> tuple[_TextAccumulator, tuple[StreamEvent, ...]]:
        key = (output_index, content_index)
        text = self._texts.get(key)
        if text is None:
            text = _TextAccumulator(self._allocate())
            self._texts[key] = text
            return text, (BlockStart(text.index, "text"),)
        if text.closed:
            raise _protocol_error("text delta followed a completed block", self.model)
        return text, ()

    def _output_item_added(self, data: Mapping[str, Any]) -> tuple[StreamEvent, ...]:
        item = _mapping(data.get("item"), "output item", self.model)
        if item.get("type") != "function_call":
            return ()
        output_index = _index(data.get("output_index"), "output_index", self.model)
        if output_index in self._tools:
            raise _protocol_error("duplicate function-call output item", self.model)
        call_id = item.get("call_id")
        name = item.get("name")
        arguments = item.get("arguments", "")
        if not isinstance(call_id, str) or not call_id:
            raise _protocol_error("function call needs call_id", self.model)
        if not isinstance(name, str) or not name:
            raise _protocol_error("function call needs name", self.model)
        if not isinstance(arguments, str):
            raise _protocol_error("function arguments must be a string", self.model)
        tool = _ToolAccumulator(self._allocate(), call_id, name, arguments)
        self._tools[output_index] = tool
        self._saw_tool = True
        return (
            BlockStart(tool.index, "tool-call"),
            ToolCallDelta(tool.index, call_id, name, arguments),
        )

    def _content_part_added(self, data: Mapping[str, Any]) -> tuple[StreamEvent, ...]:
        part = _mapping(data.get("part"), "content part", self.model)
        if part.get("type") != "output_text":
            return ()
        output_index, content_index = _content_indexes(data, self.model)
        _, events = self._ensure_text(output_index, content_index)
        return events

    def _text_delta(self, data: Mapping[str, Any]) -> tuple[StreamEvent, ...]:
        output_index, content_index = _content_indexes(data, self.model)
        delta = data.get("delta")
        if not isinstance(delta, str):
            raise _protocol_error("output text delta must be a string", self.model)
        text, starts = self._ensure_text(output_index, content_index)
        text.value += delta
        return (*starts, TextDelta(text.index, delta))

    def _text_done(self, data: Mapping[str, Any]) -> tuple[StreamEvent, ...]:
        output_index, content_index = _content_indexes(data, self.model)
        final = data.get("text")
        if not isinstance(final, str):
            raise _protocol_error("completed output text must be a string", self.model)
        text, starts = self._ensure_text(output_index, content_index)
        events: list[StreamEvent] = list(starts)
        if final != text.value:
            if final.startswith(text.value):
                remainder = final[len(text.value) :]
                if remainder:
                    events.append(TextDelta(text.index, remainder))
            else:
                raise _protocol_error(
                    "completed output text conflicts with streamed deltas", self.model
                )
        text.value = final
        text.closed = True
        events.append(BlockEnd(text.index, TextContent(final)))
        return tuple(events)

    def _tool_delta(self, data: Mapping[str, Any]) -> tuple[StreamEvent, ...]:
        output_index = _index(data.get("output_index"), "output_index", self.model)
        tool = self._tools.get(output_index)
        if tool is None or tool.closed:
            raise _protocol_error(
                "function argument delta references an unknown call", self.model
            )
        delta = data.get("delta")
        if not isinstance(delta, str):
            raise _protocol_error(
                "function argument delta must be a string", self.model
            )
        tool.arguments += delta
        return (ToolCallDelta(tool.index, tool.call_id, tool.name, delta),)

    def _tool_done(self, data: Mapping[str, Any]) -> tuple[StreamEvent, ...]:
        output_index = _index(data.get("output_index"), "output_index", self.model)
        tool = self._tools.get(output_index)
        if tool is None:
            raise _protocol_error(
                "completed function arguments reference an unknown call", self.model
            )
        if tool.closed:
            return ()
        final = data.get("arguments")
        if not isinstance(final, str):
            raise _protocol_error(
                "completed function arguments must be a string", self.model
            )
        events: list[StreamEvent] = []
        if final != tool.arguments:
            if final.startswith(tool.arguments):
                remainder = final[len(tool.arguments) :]
                if remainder:
                    events.append(
                        ToolCallDelta(tool.index, tool.call_id, tool.name, remainder)
                    )
            else:
                raise _protocol_error(
                    "completed function arguments conflict with streamed deltas",
                    self.model,
                )
        tool.arguments = final
        events.append(self._close_tool(tool))
        return tuple(events)

    def _output_item_done(self, data: Mapping[str, Any]) -> tuple[StreamEvent, ...]:
        item = _mapping(data.get("item"), "completed output item", self.model)
        if item.get("type") != "function_call":
            return ()
        output_index = _index(data.get("output_index"), "output_index", self.model)
        tool = self._tools.get(output_index)
        if tool is None:
            added = self._output_item_added(data)
            tool = self._tools[output_index]
            return (*added, self._close_tool(tool))
        if tool.closed:
            return ()
        final = item.get("arguments", tool.arguments)
        if not isinstance(final, str):
            raise _protocol_error("function arguments must be a string", self.model)
        events: list[StreamEvent] = []
        if final != tool.arguments:
            if final.startswith(tool.arguments):
                remainder = final[len(tool.arguments) :]
                if remainder:
                    events.append(
                        ToolCallDelta(tool.index, tool.call_id, tool.name, remainder)
                    )
            else:
                raise _protocol_error(
                    "completed function call conflicts with streamed deltas", self.model
                )
        tool.arguments = final
        events.append(self._close_tool(tool))
        return tuple(events)

    def _close_tool(self, tool: _ToolAccumulator) -> BlockEnd:
        tool.closed = True
        return BlockEnd(
            tool.index,
            ToolCallContent(tool.call_id, tool.name, tool.arguments or "{}"),
        )

    def _terminal_event(
        self, data: Mapping[str, Any], event_type: str
    ) -> tuple[StreamEvent, ...]:
        response = _mapping(data.get("response"), "response", self.model)
        status = response.get("status")
        if not isinstance(status, str):
            status = event_type.removeprefix("response.")
        if status == "failed":
            raise _response_error(response, self.model)
        events = self._finalize_open(response)
        usage = response.get("usage")
        if isinstance(usage, Mapping):
            events.append(UsageEvent(_usage(usage)))
        if status == "completed":
            reason = FinishReason.TOOL_CALLS if self._saw_tool else FinishReason.STOP
        elif status == "cancelled":
            reason = FinishReason.CANCELLED
        elif status == "incomplete":
            details = response.get("incomplete_details") or {}
            incomplete_reason = (
                details.get("reason") if isinstance(details, Mapping) else None
            )
            reason = (
                FinishReason.LENGTH
                if incomplete_reason == "max_output_tokens"
                else FinishReason.OTHER
            )
        else:
            raise _protocol_error(
                f"unexpected terminal response status {status!r}", self.model
            )
        events.append(FinishEvent(reason))
        self._terminal = True
        return tuple(events)

    def _finalize_open(self, response: Mapping[str, Any]) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        output = response.get("output") or []
        if not isinstance(output, list):
            raise _protocol_error("response output must be an array", self.model)

        # A terminal event may be the first frame from some compatible servers.
        # Materialize final output items only when they were not streamed already.
        for output_index, item in enumerate(output):
            if not isinstance(item, Mapping):
                continue
            if item.get("type") == "function_call":
                if output_index not in self._tools:
                    synthetic = {"output_index": output_index, "item": item}
                    events.extend(self._output_item_added(synthetic))
                    events.append(self._close_tool(self._tools[output_index]))
                else:
                    tool = self._tools[output_index]
                    final_call_id = item.get("call_id")
                    final_name = item.get("name")
                    final_arguments = item.get("arguments")
                    if (
                        final_call_id != tool.call_id
                        or final_name != tool.name
                        or not isinstance(final_arguments, str)
                    ):
                        raise _protocol_error(
                            "terminal function call conflicts with streamed identity",
                            self.model,
                        )
                    if final_arguments != tool.arguments:
                        if tool.closed or not final_arguments.startswith(
                            tool.arguments
                        ):
                            raise _protocol_error(
                                "terminal function call conflicts with streamed arguments",
                                self.model,
                            )
                        remainder = final_arguments[len(tool.arguments) :]
                        if remainder:
                            events.append(
                                ToolCallDelta(
                                    tool.index, tool.call_id, tool.name, remainder
                                )
                            )
                        tool.arguments = final_arguments
            if item.get("type") == "message":
                content = item.get("content") or []
                if not isinstance(content, list):
                    raise _protocol_error(
                        "message content must be an array", self.model
                    )
                for content_index, part in enumerate(content):
                    if (
                        not isinstance(part, Mapping)
                        or part.get("type") != "output_text"
                    ):
                        continue
                    key = (output_index, content_index)
                    final = part.get("text")
                    if not isinstance(final, str):
                        raise _protocol_error(
                            "output text must be a string", self.model
                        )
                    if key not in self._texts:
                        text, starts = self._ensure_text(output_index, content_index)
                        events.extend(starts)
                        if final:
                            text.value = final
                            events.append(TextDelta(text.index, final))
                        text.closed = True
                        events.append(BlockEnd(text.index, TextContent(final)))
                    else:
                        text = self._texts[key]
                        if final != text.value:
                            if text.closed or not final.startswith(text.value):
                                raise _protocol_error(
                                    "terminal output text conflicts with streamed deltas",
                                    self.model,
                                )
                            remainder = final[len(text.value) :]
                            if remainder:
                                events.append(TextDelta(text.index, remainder))
                            text.value = final

        for text in self._texts.values():
            if not text.closed:
                text.closed = True
                events.append(BlockEnd(text.index, TextContent(text.value)))
        for tool in self._tools.values():
            if not tool.closed:
                events.append(self._close_tool(tool))
        return events


def _responses_input(request: ModelRequest) -> tuple[str, list[dict[str, Any]]]:
    instructions: list[str] = []
    inputs: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == MessageRole.SYSTEM:
            if not all(isinstance(block, TextContent) for block in message.content):
                raise _protocol_error(
                    "OpenAI Responses system messages accept text only", request.model
                )
            instructions.extend(block.text for block in message.content)
            continue
        if message.role == MessageRole.TOOL:
            if not all(
                isinstance(block, ToolResultContent) for block in message.content
            ):
                raise _protocol_error(
                    "tool messages require ToolResultContent only", request.model
                )
            inputs.extend(
                {
                    "type": "function_call_output",
                    "call_id": block.call_id,
                    "output": block.content,
                }
                for block in message.content
            )
            continue

        content_blocks: list[dict[str, Any]] = []
        tool_calls: list[ToolCallContent] = []
        for block in message.content:
            if isinstance(block, TextContent):
                content_blocks.append({"type": "input_text", "text": block.text})
            elif isinstance(block, ImageContent):
                if message.role != MessageRole.USER:
                    raise _protocol_error(
                        "OpenAI Responses image history requires a user message",
                        request.model,
                    )
                image_url = block.url
                if block.data is not None:
                    encoded = base64.b64encode(block.data).decode("ascii")
                    image_url = f"data:{block.media_type};base64,{encoded}"
                content_blocks.append(
                    {"type": "input_image", "image_url": image_url, "detail": "auto"}
                )
            elif isinstance(block, ToolCallContent):
                tool_calls.append(block)
            elif isinstance(block, AudioContent):
                raise _protocol_error(
                    "OpenAI Responses template does not map audio input yet",
                    request.model,
                )
            else:
                raise _protocol_error(
                    "unsupported Responses input block", request.model
                )

        if tool_calls and message.role != MessageRole.ASSISTANT:
            raise _protocol_error(
                "function calls require an assistant message", request.model
            )
        if content_blocks:
            inputs.append(
                {
                    "role": message.role.value,
                    "content": content_blocks,
                }
            )
        for block in tool_calls:
            inputs.append(
                {
                    "type": "function_call",
                    "call_id": block.id,
                    "name": block.name,
                    "arguments": block.arguments,
                }
            )
    if not inputs:
        raise _protocol_error(
            "OpenAI Responses request needs at least one non-system input",
            request.model,
        )
    return "\n\n".join(instructions), inputs


def _content_indexes(data: Mapping[str, Any], model: str) -> tuple[int, int]:
    return (
        _index(data.get("output_index"), "output_index", model),
        _index(data.get("content_index"), "content_index", model),
    )


def _mapping(value: Any, label: str, model: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _protocol_error(f"{label} must be an object", model)
    return value


def _index(value: Any, label: str, model: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise _protocol_error(f"{label} must be a non-negative integer", model)
    return value


def _usage(value: Mapping[str, Any]) -> TokenUsage:
    details = value.get("input_tokens_details") or {}
    if not isinstance(details, Mapping):
        details = {}
    return TokenUsage(
        _integer(value.get("input_tokens")),
        _integer(value.get("output_tokens")),
        _integer(details.get("cached_tokens")),
    )


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _response_error(value: Mapping[str, Any], model: str) -> ModelError:
    error = value.get("error")
    if not isinstance(error, Mapping):
        error = value
    message = error.get("message")
    return ModelError(
        ModelFailure(
            ModelFailureKind.PROVIDER,
            str(error.get("code") or "response-failed"),
            message if isinstance(message, str) else "OpenAI response failed",
            provider="openai-responses",
            model=model,
        )
    )


def _configuration_error(code: str, message: str, model: str) -> ModelError:
    return ModelError(
        ModelFailure(
            ModelFailureKind.CONFIGURATION,
            code,
            message,
            provider="openai-responses",
            model=model,
        )
    )


def _protocol_error(message: str, model: str | None = None) -> ModelError:
    return ModelError(
        ModelFailure(
            ModelFailureKind.PROTOCOL,
            "invalid-provider-response",
            message,
            provider="openai-responses",
            model=model,
        )
    )
