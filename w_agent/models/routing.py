"""Explainable model routing policies and router orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol

import yaml

from w_agent.kernel import ScopePath

from .errors import RoutingError
from .provider import ModelRegistry
from .types import ModelCapability, ModelDescriptor, ModelRequest


class HealthStatus(StrEnum):
    """Health state used by routing without mutating user configuration."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CandidateMetrics:
    """Optional normalized observations for one provider/model route."""

    latency_ms: float | None = None
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    quality: float | None = None

    def __post_init__(self) -> None:
        numeric = (
            self.latency_ms,
            self.input_cost_per_million,
            self.output_cost_per_million,
        )
        if any(value is not None and value < 0 for value in numeric):
            raise ValueError("latency and cost metrics must not be negative")
        if self.quality is not None and not 0 <= self.quality <= 1:
            raise ValueError("quality must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    """One provider/model candidate presented to a routing policy."""

    descriptor: ModelDescriptor
    health: HealthStatus = HealthStatus.UNKNOWN
    metrics: CandidateMetrics = field(default_factory=CandidateMetrics)

    @property
    def provider(self) -> str:
        return self.descriptor.provider

    @property
    def model(self) -> str:
        return self.descriptor.model


@dataclass(frozen=True, slots=True)
class RouteRequest:
    """A model request plus the candidate snapshot used for one decision."""

    request: ModelRequest
    candidates: tuple[RouteCandidate, ...]
    required_capabilities: frozenset[ModelCapability] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        required = self.request.required_capabilities() | self.required_capabilities
        object.__setattr__(self, "required_capabilities", frozenset(required))


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """Explain why one candidate was accepted or rejected."""

    provider: str
    model: str
    accepted: bool
    reasons: tuple[str, ...]
    score: float | None = None


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """Auditable result of one routing decision, without prompt content."""

    provider: str
    model: str
    fallbacks: tuple[tuple[str, str], ...]
    evaluations: tuple[CandidateEvaluation, ...]
    policy_name: str
    policy_version: str
    required_capabilities: frozenset[ModelCapability]
    message_count: int
    tool_count: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class RoutingPolicy(Protocol):
    """Public policy interface implemented by Python or compiled YAML rules."""

    name: str
    version: str

    def select(self, route_request: RouteRequest) -> RouteDecision: ...


@dataclass(frozen=True, slots=True)
class RoutingWeights:
    """Weights applied to quality, latency, cost, health, and preference."""

    quality: float = 1.0
    latency: float = 0.3
    cost: float = 0.3
    health: float = 0.5
    preferred_provider: float = 0.2

    def __post_init__(self) -> None:
        if (
            min(
                self.quality,
                self.latency,
                self.cost,
                self.health,
                self.preferred_provider,
            )
            < 0
        ):
            raise ValueError("routing weights must not be negative")


@dataclass(slots=True)
class WeightedRoutingPolicy:
    """Deterministic filter-and-score policy with explainable decisions."""

    name: str = "weighted"
    version: str = "1"
    weights: RoutingWeights = field(default_factory=RoutingWeights)
    allow_providers: frozenset[str] = field(default_factory=frozenset)
    deny_providers: frozenset[str] = field(default_factory=frozenset)
    preferred_providers: tuple[str, ...] = ()
    max_cost_per_million: float | None = None
    required_capabilities: frozenset[ModelCapability] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        self.allow_providers = frozenset(self.allow_providers)
        self.deny_providers = frozenset(self.deny_providers)
        self.preferred_providers = tuple(self.preferred_providers)
        self.required_capabilities = frozenset(self.required_capabilities)
        if self.max_cost_per_million is not None and self.max_cost_per_million < 0:
            raise ValueError("max_cost_per_million must not be negative")

    def select(self, route_request: RouteRequest) -> RouteDecision:
        """Filter candidates, score accepted routes, and return a stable order."""

        required = route_request.required_capabilities | self.required_capabilities
        evaluations: list[CandidateEvaluation] = []
        accepted: list[tuple[float, RouteCandidate]] = []

        for candidate in route_request.candidates:
            reasons = self._rejection_reasons(
                candidate, route_request.request, required
            )
            if reasons:
                evaluations.append(
                    CandidateEvaluation(
                        provider=candidate.provider,
                        model=candidate.model,
                        accepted=False,
                        reasons=tuple(reasons),
                    )
                )
                continue
            score = self._score(candidate)
            accepted.append((score, candidate))
            evaluations.append(
                CandidateEvaluation(
                    provider=candidate.provider,
                    model=candidate.model,
                    accepted=True,
                    reasons=("eligible",),
                    score=score,
                )
            )

        if not accepted:
            summary = "; ".join(
                f"{item.provider}/{item.model}: {', '.join(item.reasons)}"
                for item in evaluations
            )
            raise RoutingError(f"no model route satisfies the request ({summary})")

        accepted.sort(key=lambda item: (-item[0], item[1].provider, item[1].model))
        selected = accepted[0][1]
        return RouteDecision(
            provider=selected.provider,
            model=selected.model,
            fallbacks=tuple(
                (candidate.provider, candidate.model) for _, candidate in accepted[1:]
            ),
            evaluations=tuple(evaluations),
            policy_name=self.name,
            policy_version=self.version,
            required_capabilities=frozenset(required),
            message_count=len(route_request.request.messages),
            tool_count=len(route_request.request.tools),
        )

    def _rejection_reasons(
        self,
        candidate: RouteCandidate,
        request: ModelRequest,
        required: frozenset[ModelCapability],
    ) -> list[str]:
        reasons: list[str] = []
        requested_model = request.model
        qualified_model = f"{candidate.provider}/{candidate.model}"
        if requested_model and requested_model not in {
            candidate.model,
            qualified_model,
        }:
            reasons.append(f"model does not match {requested_model!r}")
        if self.allow_providers and candidate.provider not in self.allow_providers:
            reasons.append("provider is not allowed")
        if candidate.provider in self.deny_providers:
            reasons.append("provider is denied")
        missing = required - candidate.descriptor.capabilities
        if missing:
            values = ", ".join(sorted(capability.value for capability in missing))
            reasons.append(f"missing capabilities: {values}")
        if candidate.health == HealthStatus.UNHEALTHY:
            reasons.append("route is unhealthy")
        if self.max_cost_per_million is not None:
            costs = (
                candidate.metrics.input_cost_per_million,
                candidate.metrics.output_cost_per_million,
            )
            if any(
                cost is not None and cost > self.max_cost_per_million for cost in costs
            ):
                reasons.append("route exceeds maximum cost")
        return reasons

    def _score(self, candidate: RouteCandidate) -> float:
        metrics = candidate.metrics
        quality = metrics.quality if metrics.quality is not None else 0.5
        latency = (
            0.5 if metrics.latency_ms is None else 1 / (1 + metrics.latency_ms / 1000)
        )
        known_costs = [
            value
            for value in (
                metrics.input_cost_per_million,
                metrics.output_cost_per_million,
            )
            if value is not None
        ]
        cost = 0.5 if not known_costs else 1 / (1 + sum(known_costs) / len(known_costs))
        health = {
            HealthStatus.HEALTHY: 1.0,
            HealthStatus.DEGRADED: 0.4,
            HealthStatus.UNKNOWN: 0.5,
            HealthStatus.UNHEALTHY: 0.0,
        }[candidate.health]
        preference = 0.0
        if candidate.provider in self.preferred_providers:
            index = self.preferred_providers.index(candidate.provider)
            preference = 1 / (index + 1)
        score = (
            self.weights.quality * quality
            + self.weights.latency * latency
            + self.weights.cost * cost
            + self.weights.health * health
            + self.weights.preferred_provider * preference
        )
        return round(score, 8)


class YamlRoutingPolicy(WeightedRoutingPolicy):
    """A safe YAML rule compiled into the same weighted policy interface."""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "YamlRoutingPolicy":
        """Compile a parsed YAML mapping without importing or executing code."""

        if not isinstance(value, Mapping):
            raise ValueError("routing policy YAML must contain a mapping")
        weights_value = value.get("weights", {})
        if not isinstance(weights_value, Mapping):
            raise ValueError("routing policy weights must be a mapping")
        known_keys = {
            "quality",
            "latency",
            "cost",
            "health",
            "preferred_provider",
        }
        unknown = set(weights_value) - known_keys
        if unknown:
            raise ValueError(f"unknown routing weight(s): {', '.join(sorted(unknown))}")
        try:
            required = frozenset(
                ModelCapability(item) for item in value.get("required_capabilities", [])
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid required model capability") from exc
        return cls(
            name=str(value.get("name", "yaml-weighted")),
            version=str(value.get("version", "1")),
            weights=RoutingWeights(**dict(weights_value)),
            allow_providers=frozenset(value.get("allow_providers", [])),
            deny_providers=frozenset(value.get("deny_providers", [])),
            preferred_providers=tuple(value.get("preferred_providers", [])),
            max_cost_per_million=value.get("max_cost_per_million"),
            required_capabilities=required,
        )

    @classmethod
    def from_yaml(cls, source: str | Path) -> "YamlRoutingPolicy":
        """Load policy text or a caller-explicit Path using ``safe_load``."""

        text = (
            source.read_text(encoding="utf-8") if isinstance(source, Path) else source
        )
        value = yaml.safe_load(text)
        if value is None:
            value = {}
        return cls.from_mapping(value)


class CandidateState:
    """Mutable observation store kept outside immutable route decisions."""

    def __init__(self) -> None:
        self._health: dict[tuple[str, str], HealthStatus] = {}
        self._metrics: dict[tuple[str, str], CandidateMetrics] = {}

    def update(
        self,
        provider: str,
        model: str,
        *,
        health: HealthStatus | None = None,
        metrics: CandidateMetrics | None = None,
    ) -> None:
        """Update health and/or metrics for one route."""

        key = (provider, model)
        if health is not None:
            self._health[key] = health
        if metrics is not None:
            self._metrics[key] = metrics

    def candidate(self, descriptor: ModelDescriptor) -> RouteCandidate:
        """Build an immutable candidate snapshot for a descriptor."""

        key = (descriptor.provider, descriptor.model)
        return RouteCandidate(
            descriptor=descriptor,
            health=self._health.get(key, HealthStatus.UNKNOWN),
            metrics=self._metrics.get(key, CandidateMetrics()),
        )

    @property
    def health(self) -> Mapping[tuple[str, str], HealthStatus]:
        return MappingProxyType(dict(self._health))


class ModelRouter:
    """Resolve current model catalogs and apply one replaceable policy."""

    def __init__(
        self,
        models: ModelRegistry,
        policy: RoutingPolicy | None = None,
        state: CandidateState | None = None,
    ) -> None:
        self.models = models
        self.policy = policy or WeightedRoutingPolicy()
        self.state = state or CandidateState()

    async def route(
        self,
        request: ModelRequest,
        *,
        scope: ScopePath | None = None,
        required_capabilities: frozenset[ModelCapability] = frozenset(),
    ) -> RouteDecision:
        """Create a decision from a current immutable provider/model snapshot."""

        descriptors = await self.models.list_models(scope=scope)
        candidates = tuple(self.state.candidate(item) for item in descriptors)
        return self.policy.select(
            RouteRequest(
                request=request,
                candidates=candidates,
                required_capabilities=required_capabilities,
            )
        )
