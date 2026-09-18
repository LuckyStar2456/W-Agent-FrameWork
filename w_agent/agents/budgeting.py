"""Replaceable, explicit token-estimation contracts for agent preflight checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import ceil
from typing import Protocol

from w_agent.models import (
    AudioContent,
    ImageContent,
    ModelRequest,
    TextContent,
    ToolCallContent,
    ToolResultContent,
)


class TokenEstimationError(ValueError):
    """A request cannot be estimated without making an unsafe assumption."""


@dataclass(frozen=True, slots=True)
class TokenEstimate:
    """Prompt-safe input-token estimate returned before a model call."""

    input_tokens: int
    estimator: str
    exact: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.input_tokens, bool) or self.input_tokens < 0:
            raise ValueError("estimated input tokens must be a non-negative integer")
        if not isinstance(self.input_tokens, int):
            raise ValueError("estimated input tokens must be a non-negative integer")
        if not self.estimator.strip():
            raise ValueError("token estimator identity must not be empty")
        if not isinstance(self.exact, bool):
            raise ValueError("token estimate exactness must be a boolean")


class TokenEstimator(Protocol):
    """Application-replaceable tokenizer or conservative estimation service."""

    async def estimate(self, request: ModelRequest) -> TokenEstimate: ...


@dataclass(frozen=True, slots=True)
class CharacterTokenEstimator:
    """Transparent text/tool heuristic for explicitly opted-in local use.

    It counts visible text, tool calls/results, tool schemas, response schemas,
    and stop strings. Image and audio inputs fail closed because a character
    heuristic cannot estimate their provider-specific tokenization.
    """

    characters_per_token: int = 4
    tokens_per_message: int = 4
    base_tokens: int = 2

    def __post_init__(self) -> None:
        values = (
            self.characters_per_token,
            self.tokens_per_message,
            self.base_tokens,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) for value in values
        ):
            raise ValueError("character estimator settings must be integers")
        if (
            self.characters_per_token <= 0
            or min(self.tokens_per_message, self.base_tokens) < 0
        ):
            raise ValueError("character estimator settings are invalid")

    async def estimate(self, request: ModelRequest) -> TokenEstimate:
        characters = 0
        for message in request.messages:
            characters += len(message.role.value)
            characters += len(message.name or "")
            for block in message.content:
                if isinstance(block, TextContent):
                    characters += len(block.text)
                elif isinstance(block, ToolCallContent):
                    characters += len(block.id) + len(block.name) + len(block.arguments)
                elif isinstance(block, ToolResultContent):
                    characters += len(block.call_id) + len(block.content) + 1
                elif isinstance(block, (ImageContent, AudioContent)):
                    raise TokenEstimationError(
                        "character estimator does not support image or audio input"
                    )
                else:  # pragma: no cover - closed union defensive boundary
                    raise TokenEstimationError("unsupported model content block")
        for tool in request.tools:
            characters += len(tool.name) + len(tool.description)
            characters += len(_canonical_json(dict(tool.input_schema)))
        if request.response_schema is not None:
            characters += len(_canonical_json(dict(request.response_schema)))
        characters += sum(len(item) for item in request.stop)
        input_tokens = (
            self.base_tokens
            + len(request.messages) * self.tokens_per_message
            + ceil(characters / self.characters_per_token)
        )
        return TokenEstimate(
            input_tokens,
            (
                "character-heuristic:v1"
                f":{self.characters_per_token}:{self.tokens_per_message}"
                f":{self.base_tokens}"
            ),
            exact=False,
        )


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise TokenEstimationError("schema is not JSON serializable") from error
