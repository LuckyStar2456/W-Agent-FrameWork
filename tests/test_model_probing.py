import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from w_agent import (
    BlockEnd,
    BlockStart,
    CancellationToken,
    CandidateState,
    EndpointProbe,
    FinishEvent,
    FinishReason,
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelMessage,
    ModelProviderProbe,
    ModelRegistrationProbeService,
    ModelRegistry,
    PeriodicProbeService,
    ProbeCache,
    ProbeCheck,
    ProbeHealthBridge,
    ProbeLevel,
    ProbeMode,
    ProbeResult,
    ProbeStatus,
    HealthStatus,
    TextContent,
    TextDelta,
)


class FakeProvider:
    def __init__(self):
        self.stream_calls = 0

    async def list_models(self):
        return (
            ModelDescriptor(
                provider="fake",
                model="chat",
                capabilities=frozenset(
                    {
                        ModelCapability.TEXT_INPUT,
                        ModelCapability.TEXT_OUTPUT,
                        ModelCapability.STREAMING,
                        ModelCapability.TOOL_CALLING,
                    }
                ),
            ),
        )

    async def resolve(self, model):
        return (await self.list_models())[0]

    async def stream(self, request, *, cancellation=None):
        self.stream_calls += 1
        assert request.messages == (
            ModelMessage.text(MessageRole.USER, "Reply with OK."),
        )
        yield BlockStart(0, "text")
        yield TextDelta(0, "OK")
        yield BlockEnd(0, TextContent("OK"))
        yield FinishEvent(FinishReason.STOP)


class StubEndpointProbe(EndpointProbe):
    def _probe_sync(self, endpoint):
        return (
            ProbeCheck(
                ProbeLevel.L1_REACHABILITY,
                "http",
                ProbeStatus.PASS,
                endpoint,
            ),
        )


@pytest.mark.asyncio
async def test_endpoint_probe_redacts_credentials_query_and_fragment():
    result = await StubEndpointProbe().probe(
        "https://user:secret@example.test/v1?token=secret#fragment"
    )

    assert result.target == "https://example.test/v1"
    assert result.successful is True
    assert result.checks[0].status == ProbeStatus.PASS


@pytest.mark.asyncio
async def test_endpoint_probe_fails_closed_for_malformed_port():
    result = await EndpointProbe().probe("https://example.test:not-a-port/v1")

    assert result.target == "invalid-endpoint"
    assert result.successful is False
    assert result.checks[0].failure_kind is not None


@pytest.mark.asyncio
async def test_provider_safe_probe_never_calls_generation():
    provider = FakeProvider()
    result = await ModelProviderProbe().probe("fake", provider)

    assert result.mode == ProbeMode.SAFE
    assert result.successful is True
    assert provider.stream_calls == 0
    assert [check.level for check in result.checks] == [
        ProbeLevel.L2_AUTHENTICATION,
        ProbeLevel.L3_CATALOG,
    ]


@pytest.mark.asyncio
async def test_provider_probe_omits_unexpected_exception_messages():
    class BrokenProvider(FakeProvider):
        async def list_models(self):
            raise RuntimeError("secret credential in exception")

    result = await ModelProviderProbe().probe("broken", BrokenProvider())

    assert result.successful is False
    assert result.checks[0].message == "provider catalog raised RuntimeError"
    assert "secret" not in result.checks[0].message


@pytest.mark.asyncio
async def test_active_probe_requires_explicit_opt_in_and_validates_stream():
    provider = FakeProvider()
    skipped = await ModelProviderProbe().probe("fake", provider, mode=ProbeMode.ACTIVE)
    assert provider.stream_calls == 0
    assert skipped.checks[-1].status == ProbeStatus.SKIPPED

    active = await ModelProviderProbe().probe(
        "fake", provider, mode=ProbeMode.ACTIVE, allow_active=True
    )
    assert provider.stream_calls == 1
    assert [check.level for check in active.checks[-2:]] == [
        ProbeLevel.L4_GENERATION,
        ProbeLevel.L5_STREAMING,
    ]
    assert all(check.status == ProbeStatus.PASS for check in active.checks[-2:])

    missing = await ModelProviderProbe().probe(
        "fake",
        provider,
        mode=ProbeMode.ACTIVE,
        allow_active=True,
        model="missing",
    )
    assert provider.stream_calls == 1
    assert missing.checks[-1].status == ProbeStatus.FAIL


def test_probe_cache_discards_expired_results():
    now = datetime.now(UTC)
    result = ProbeResult(
        target="fake",
        mode=ProbeMode.SAFE,
        checks=(),
        started_at=now,
        completed_at=now,
        expires_at=now + timedelta(seconds=1),
    )
    cache = ProbeCache()
    cache.put(result)

    assert cache.get("fake", now=now) is result
    assert cache.get("fake", now=now + timedelta(seconds=2)) is None


@pytest.mark.asyncio
async def test_periodic_probe_service_runs_and_stops_idempotently():
    called = asyncio.Event()
    now = datetime.now(UTC)

    async def probe():
        called.set()
        return ProbeResult(
            target="fake",
            mode=ProbeMode.SAFE,
            checks=(),
            started_at=now,
            completed_at=now,
            expires_at=now + timedelta(minutes=1),
        )

    service = PeriodicProbeService(probe, interval=60)
    service.start()
    await asyncio.wait_for(called.wait(), timeout=1)
    await service.stop()
    await service.stop()

    assert service.running is False


@pytest.mark.asyncio
async def test_registration_service_runs_safe_probe_and_bridges_health():
    provider = FakeProvider()
    models = ModelRegistry()
    state = CandidateState()
    service = ModelRegistrationProbeService(models, state)

    outcome = await service.register("fake", provider, version="1")

    assert outcome.health == HealthStatus.HEALTHY
    assert outcome.probe_result.mode == ProbeMode.SAFE
    assert outcome.probe_result.routes == (("fake", "chat"),)
    assert state.health[("fake", "chat")] == HealthStatus.HEALTHY
    assert service.cache.get("fake") is outcome.probe_result
    assert models.provider("fake") is provider
    assert provider.stream_calls == 0

    outcome.dispose()
    assert outcome.disposed is True
    assert models.providers() == ()


@pytest.mark.asyncio
async def test_registration_probe_cancellation_rolls_back_registration():
    provider = FakeProvider()
    models = ModelRegistry()
    state = CandidateState()
    service = ModelRegistrationProbeService(models, state)
    cancellation = CancellationToken()
    cancellation.cancel()

    with pytest.raises(asyncio.CancelledError):
        await service.register("fake", provider, cancellation=cancellation)

    assert models.providers() == ()


def test_probe_health_bridge_expires_observations_to_unknown():
    now = datetime.now(UTC)
    result = ProbeResult(
        target="fake",
        mode=ProbeMode.SAFE,
        checks=(
            ProbeCheck(
                ProbeLevel.L3_CATALOG,
                "catalog",
                ProbeStatus.PASS,
                "ok",
            ),
        ),
        started_at=now,
        completed_at=now,
        expires_at=now + timedelta(seconds=1),
        routes=(("fake", "chat"),),
    )
    state = CandidateState()
    bridge = ProbeHealthBridge()

    health = bridge.apply(result, state, now=now + timedelta(seconds=2))

    assert health == HealthStatus.UNKNOWN
    assert state.health[("fake", "chat")] == HealthStatus.UNKNOWN
