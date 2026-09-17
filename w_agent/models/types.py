"""Provider-neutral model messages, capabilities, and stream events."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, AsyncIterable, Mapping, TypeAlias

from .errors import ModelError, ModelFailure


def _frozen_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


class MessageRole(StrEnum):
    """Role of one model-facing message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ModelCapability(StrEnum):
    """Standard capabilities used for routing and validation."""

    TEXT_INPUT = "text-input"
    TEXT_OUTPUT = "text-output"
    IMAGE_INPUT = "image-input"
    IMAGE_OUTPUT = "image-output"
    AUDIO_INPUT = "audio-input"
    AUDIO_OUTPUT = "audio-output"
    STREAMING = "streaming"
    TOOL_CALLING = "tool-calling"
    PARALLEL_TOOL_CALLING = "parallel-tool-calling"
    STRUCTURED_OUTPUT = "structured-output"
    REASONING = "reasoning"
    PROMPT_CACHE = "prompt-cache"


@dataclass(frozen=True, slots=True)
class TextContent:
    """Text message content."""

    text: str
    type: str = field(default="text", init=False)


@dataclass(frozen=True, slots=True)
class ImageContent:
    """Image content referenced by URL or inline bytes."""

    url: str | None = None
    data: bytes | None = None
    media_type: str | None = None
    type: str = field(default="image", init=False)

    def __post_init__(self) -> None:
        if (self.url is None) == (self.data is None):
            raise ValueError("image content needs exactly one of url or data")
        if self.data is not None and not self.media_type:
            raise ValueError("inline image data needs a media_type")


@dataclass(frozen=True, slots=True)
class AudioContent:
    """Audio content referenced by URL or inline bytes."""

    url: str | None = None
    data: bytes | None = None
    media_type: str | None = None
    type: str = field(default="audio", init=False)

    def __post_init__(self) -> None:
        if (self.url is None) == (self.data is None):
            raise ValueError("audio content needs exactly one of url or data")
        if self.data is not None and not self.media_type:
            raise ValueError("inline audio data needs a media_type")


@dataclass(frozen=True, slots=True)
class ToolCallContent:
    """A complete tool call emitted by a model."""

    id: str
    name: str
    arguments: str
    type: str = field(default="tool-call", init=False)


@dataclass(frozen=True, slots=True)
class ToolResultContent:
    """A tool result sent back to a model."""

    call_id: str
    content: str
    is_error: bool = False
    type: str = field(default="tool-result", init=False)


ContentBlock: TypeAlias = (
    TextContent | ImageContent | AudioContent | ToolCallContent | ToolResultContent
)


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """One provider-neutral conversation message."""

    role: MessageRole
    content: tuple[ContentBlock, ...]
    name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("model message content must not be empty")
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))

    @classmethod
    def text(cls, role: MessageRole, text: str) -> "ModelMessage":
        """Create a single-block text message."""

        return cls(role=role, content=(TextContent(text),))


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """A model-visible tool schema."""

    name: str
    description: str
    input_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("tool name must not be empty")
        object.__setattr__(self, "input_schema", _frozen_mapping(self.input_schema))


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """Provider-neutral model request with namespaced extensions."""

    messages: tuple[ModelMessage, ...]
    model: str | None = None
    tools: tuple[ToolDefinition, ...] = ()
    response_schema: Mapping[str, Any] | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    stop: tuple[str, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("model request needs at least one message")
        if self.temperature is not None and self.temperature < 0:
            raise ValueError("temperature must not be negative")
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self.response_schema is not None:
            object.__setattr__(
                self, "response_schema", _frozen_mapping(self.response_schema)
            )
        object.__setattr__(self, "extensions", _frozen_mapping(self.extensions))

    def required_capabilities(self) -> frozenset[ModelCapability]:
        """Derive standard capabilities required by this request."""

        required = {ModelCapability.TEXT_OUTPUT}
        for message in self.messages:
            for block in message.content:
                if isinstance(block, TextContent):
                    required.add(ModelCapability.TEXT_INPUT)
                elif isinstance(block, ImageContent):
                    required.add(ModelCapability.IMAGE_INPUT)
                elif isinstance(block, AudioContent):
                    required.add(ModelCapability.AUDIO_INPUT)
                elif isinstance(block, (ToolCallContent, ToolResultContent)):
                    required.add(ModelCapability.TOOL_CALLING)
        if self.tools:
            required.add(ModelCapability.TOOL_CALLING)
        if self.response_schema is not None:
            required.add(ModelCapability.STRUCTURED_OUTPUT)
        return frozenset(required)


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    """Resolved identity and capabilities of one model."""

    provider: str
    model: str
    capabilities: frozenset[ModelCapability]
    context_window: int | None = None
    max_output_tokens: int | None = None
    reasoning_efforts: tuple[str, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider or not self.model:
            raise ValueError("model descriptor needs provider and model identifiers")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "extensions", _frozen_mapping(self.extensions))


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Normalized model token usage."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.cached_input_tokens) < 0:
            raise ValueError("token usage must not be negative")


class FinishReason(StrEnum):
    """Why a model stream ended."""

    STOP = "stop"
    TOOL_CALLS = "tool-calls"
    LENGTH = "length"
    CONTENT_FILTER = "content-filter"
    CANCELLED = "cancelled"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class BlockStart:
    index: int
    block_type: str
    type: str = field(default="block-start", init=False)


@dataclass(frozen=True, slots=True)
class TextDelta:
    index: int
    text: str
    type: str = field(default="text-delta", init=False)


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    index: int
    id: str
    name: str
    arguments_delta: str
    type: str = field(default="tool-call-delta", init=False)


@dataclass(frozen=True, slots=True)
class BlockEnd:
    index: int
    block: ContentBlock
    type: str = field(default="block-end", init=False)


@dataclass(frozen=True, slots=True)
class UsageEvent:
    usage: TokenUsage
    type: str = field(default="usage", init=False)


@dataclass(frozen=True, slots=True)
class ErrorEvent:
    failure: ModelFailure
    type: str = field(default="error", init=False)


@dataclass(frozen=True, slots=True)
class FinishEvent:
    reason: FinishReason
    type: str = field(default="finish", init=False)


StreamEvent: TypeAlias = (
    BlockStart
    | TextDelta
    | ToolCallDelta
    | BlockEnd
    | UsageEvent
    | ErrorEvent
    | FinishEvent
)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """Collected final response from a validated stream."""

    blocks: tuple[ContentBlock, ...]
    usage: TokenUsage
    finish_reason: FinishReason

    @property
    def text(self) -> str:
        """Join final text blocks in response order."""

        return "".join(
            block.text for block in self.blocks if isinstance(block, TextContent)
        )


class ModelStreamProtocolError(ValueError):
    """A provider emitted an invalid stream-event sequence."""


class ModelStreamValidator:
    """Incrementally validate events and expose a response after completion."""

    def __init__(self) -> None:
        self._open_blocks: dict[int, str] = {}
        self._completed: dict[int, ContentBlock] = {}
        self._usage = TokenUsage()
        self._finish: FinishReason | None = None

    def feed(self, event: StreamEvent) -> None:
        """Validate and consume one stream event."""

        if self._finish is not None:
            raise ModelStreamProtocolError("provider emitted an event after finish")
        if isinstance(event, BlockStart):
            if (
                event.index < 0
                or event.index in self._open_blocks
                or event.index in self._completed
            ):
                raise ModelStreamProtocolError(
                    f"invalid block start index {event.index}"
                )
            self._open_blocks[event.index] = event.block_type
        elif isinstance(event, (TextDelta, ToolCallDelta)):
            if event.index not in self._open_blocks:
                raise ModelStreamProtocolError(
                    f"delta references unopened block {event.index}"
                )
        elif isinstance(event, BlockEnd):
            if event.index not in self._open_blocks:
                raise ModelStreamProtocolError(
                    f"block {event.index} ended without start"
                )
            self._open_blocks.pop(event.index)
            self._completed[event.index] = event.block
        elif isinstance(event, UsageEvent):
            self._usage = event.usage
        elif isinstance(event, ErrorEvent):
            raise ModelError(event.failure)
        elif isinstance(event, FinishEvent):
            if self._open_blocks:
                raise ModelStreamProtocolError(
                    "provider finished with open content blocks"
                )
            self._finish = event.reason

    def finish(self) -> ModelResponse:
        """Validate terminal state and return the collected response metadata."""

        if self._finish is None:
            raise ModelStreamProtocolError("provider stream ended without finish")
        ordered = tuple(
            self._completed[index] for index in sorted(self._completed)
        )
        return ModelResponse(ordered, self._usage, self._finish)


async def collect_stream(events: AsyncIterable[StreamEvent]) -> ModelResponse:
    """Validate and collect a model stream into a final response."""

    validator = ModelStreamValidator()
    async for event in events:
        validator.feed(event)
    return validator.finish()
