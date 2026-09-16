import pytest

from w_agent import (
    CandidateMetrics,
    CandidateState,
    HealthStatus,
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelMessage,
    ModelRegistry,
    ModelRequest,
    ModelRouter,
    RouteCandidate,
    RouteRequest,
    RoutingError,
    WeightedRoutingPolicy,
    YamlRoutingPolicy,
)


class CatalogProvider:
    def __init__(self, *descriptors):
        self.descriptors = descriptors

    async def list_models(self):
        return self.descriptors

    async def resolve(self, model):
        return next(item for item in self.descriptors if item.model == model)

    async def stream(self, request, *, cancellation=None):
        if False:
            yield request


def _request(model=None):
    return ModelRequest(
        model=model,
        messages=(ModelMessage.text(MessageRole.USER, "hello"),),
    )


def _descriptor(provider, model, *capabilities):
    return ModelDescriptor(
        provider=provider,
        model=model,
        capabilities=frozenset(capabilities),
    )


def test_weighted_policy_filters_capabilities_and_explains_selection():
    text = {ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT}
    candidates = (
        RouteCandidate(
            _descriptor("fast", "chat", *text),
            health=HealthStatus.HEALTHY,
            metrics=CandidateMetrics(latency_ms=50, quality=0.8),
        ),
        RouteCandidate(
            _descriptor("vision", "chat", *text, ModelCapability.IMAGE_INPUT),
            health=HealthStatus.UNHEALTHY,
            metrics=CandidateMetrics(latency_ms=10, quality=1.0),
        ),
        RouteCandidate(
            _descriptor("slow", "chat", *text),
            health=HealthStatus.HEALTHY,
            metrics=CandidateMetrics(latency_ms=2000, quality=0.7),
        ),
    )

    decision = WeightedRoutingPolicy().select(RouteRequest(_request(), candidates))

    assert (decision.provider, decision.model) == ("fast", "chat")
    assert decision.fallbacks == (("slow", "chat"),)
    rejected = next(item for item in decision.evaluations if item.provider == "vision")
    assert rejected.accepted is False
    assert rejected.reasons == ("route is unhealthy",)
    assert decision.message_count == 1


def test_yaml_policy_is_safe_and_matches_python_policy_interface():
    policy = YamlRoutingPolicy.from_yaml(
        """
name: local-policy
version: 2
allow_providers: [local]
preferred_providers: [local]
required_capabilities: [streaming]
weights:
  quality: 2
  latency: 0
  cost: 0
  health: 1
  preferred_provider: 1
"""
    )
    capabilities = {
        ModelCapability.TEXT_INPUT,
        ModelCapability.TEXT_OUTPUT,
        ModelCapability.STREAMING,
    }
    decision = policy.select(
        RouteRequest(
            _request(),
            (RouteCandidate(_descriptor("local", "one", *capabilities)),),
        )
    )

    assert decision.policy_name == "local-policy"
    assert decision.policy_version == "2"
    assert ModelCapability.STREAMING in decision.required_capabilities

    with pytest.raises(ValueError, match="unknown routing weight"):
        YamlRoutingPolicy.from_yaml("weights: {surprise: 1}")


@pytest.mark.asyncio
async def test_router_uses_registry_catalog_and_external_candidate_state():
    text = {ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT}
    registry = ModelRegistry()
    registry.register(
        "remote",
        CatalogProvider(_descriptor("remote", "chat", *text)),
        version="1",
    )
    state = CandidateState()
    state.update(
        "remote",
        "chat",
        health=HealthStatus.HEALTHY,
        metrics=CandidateMetrics(latency_ms=20, quality=0.9),
    )

    decision = await ModelRouter(registry, state=state).route(_request("remote/chat"))

    assert (decision.provider, decision.model) == ("remote", "chat")


def test_policy_reports_when_no_route_is_eligible():
    candidate = RouteCandidate(
        _descriptor("provider", "text-only", ModelCapability.TEXT_OUTPUT)
    )
    with pytest.raises(RoutingError, match="missing capabilities: text-input"):
        WeightedRoutingPolicy().select(RouteRequest(_request(), (candidate,)))
