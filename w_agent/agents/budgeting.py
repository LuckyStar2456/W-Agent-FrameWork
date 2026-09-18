"""Replaceable token and monetary estimation contracts for agent preflight."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import ceil
from typing import Protocol

from w_agent.models import (
    AudioContent,
    ImageContent,
    ModelCost,
    ModelRequest,
    PricingError,
    PricingResolver,
    TextContent,
    TokenUsage,
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


class CostEstimationError(ValueError):
    """A bounded monetary projection cannot be produced safely."""


@dataclass(frozen=True, slots=True)
class CostEstimateRoute:
    """One prompt-free route and its maximum configured attempt count."""

    provider: str
    model: str
    attempts: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.provider, str)
            or not isinstance(self.model, str)
            or not self.provider.strip()
            or not self.model.strip()
        ):
            raise ValueError("cost estimate route identity must not be empty")
        if (
            isinstance(self.attempts, bool)
            or not isinstance(self.attempts, int)
            or self.attempts < 1
        ):
            raise ValueError("cost estimate route attempts must be positive")


@dataclass(frozen=True, slots=True)
class CostEstimateRequest:
    """Prompt-free inputs for a replaceable monetary estimator."""

    routes: tuple[CostEstimateRoute, ...]
    estimated_input_tokens: int
    max_output_tokens: int
    price_table_version: str
    token_estimator: str
    input_exact: bool = False

    def __post_init__(self) -> None:
        routes = tuple(self.routes)
        if not routes or not all(isinstance(item, CostEstimateRoute) for item in routes):
            raise ValueError("cost estimate request needs at least one route")
        if (
            isinstance(self.estimated_input_tokens, bool)
            or not isinstance(self.estimated_input_tokens, int)
            or self.estimated_input_tokens < 0
        ):
            raise ValueError("estimated input tokens must be a non-negative integer")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise ValueError("cost estimation needs a positive output-token cap")
        if (
            not isinstance(self.price_table_version, str)
            or not isinstance(self.token_estimator, str)
            or not self.price_table_version.strip()
            or not self.token_estimator.strip()
        ):
            raise ValueError("cost estimate identities must not be empty")
        if not isinstance(self.input_exact, bool):
            raise ValueError("cost estimate input exactness must be a boolean")
        object.__setattr__(self, "routes", routes)


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Monetary projection for one primary attempt and the replay envelope."""

    primary_attempt: ModelCost
    replay_envelope: ModelCost
    route_count: int
    attempt_count: int
    estimator: str
    conservative: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.primary_attempt, ModelCost) or not isinstance(
            self.replay_envelope, ModelCost
        ):
            raise ValueError("cost estimate values must be ModelCost instances")
        if (
            isinstance(self.route_count, bool)
            or isinstance(self.attempt_count, bool)
            or not isinstance(self.route_count, int)
            or not isinstance(self.attempt_count, int)
            or self.route_count < 1
            or self.attempt_count < self.route_count
        ):
            raise ValueError("cost estimate route and attempt counts are invalid")
        if not isinstance(self.estimator, str) or not self.estimator.strip():
            raise ValueError("cost estimator identity must not be empty")
        if not isinstance(self.conservative, bool):
            raise ValueError("cost estimate conservatism must be a boolean")
        self.primary_attempt.add(self.replay_envelope)
        if self.replay_envelope.total < self.primary_attempt.total:
            raise ValueError("cost replay envelope cannot be below the primary attempt")


class CostEstimator(Protocol):
    """Application-replaceable prompt-free monetary projection strategy."""

    async def estimate(self, request: CostEstimateRequest) -> CostEstimate: ...


@dataclass(frozen=True, slots=True)
class PricingCostEstimator:
    """Estimate a bounded retry/failover envelope from explicit price tables."""

    pricing: PricingResolver

    async def estimate(self, request: CostEstimateRequest) -> CostEstimate:
        route_costs: list[tuple[CostEstimateRoute, ModelCost]] = []
        usage_uncached = TokenUsage(
            request.estimated_input_tokens,
            request.max_output_tokens,
        )
        usage_cached = TokenUsage(
            request.estimated_input_tokens,
            request.max_output_tokens,
            request.estimated_input_tokens,
        )
        try:
            for route in request.routes:
                uncached = self.pricing.quote(
                    request.price_table_version,
                    route.provider,
                    route.model,
                    usage_uncached,
                )
                cached = self.pricing.quote(
                    request.price_table_version,
                    route.provider,
                    route.model,
                    usage_cached,
                )
                route_costs.append(
                    (route, cached if cached.total > uncached.total else uncached)
                )
        except PricingError as error:
            raise CostEstimationError("route price is unavailable") from error

        primary = route_costs[0][1]
        envelope = self.pricing.table(request.price_table_version).zero()
        for route, cost in route_costs:
            for _ in range(route.attempts):
                envelope = envelope.add(cost)
        return CostEstimate(
            primary,
            envelope,
            len(route_costs),
            sum(route.attempts for route, _ in route_costs),
            "pricing-replay-envelope:v1",
            conservative=request.input_exact,
        )


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
