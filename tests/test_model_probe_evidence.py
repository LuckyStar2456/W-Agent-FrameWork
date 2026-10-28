"""Offline catalogs must not manufacture connectivity/authentication evidence."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from w_agent import (
    HealthStatus, ModelProviderProbe, ProbeCheck, ProbeHealthBridge, ProbeLevel,
    ProbeMode, ProbeResult, ProbeStatus, anthropic_provider, deepseek_provider,
    qwen_native_provider, turbo_provider,
    HttpModelProvider, HttpRequest,
)
from w_agent.service_usage import InMemoryServiceUsageLedger
from w_agent.service_usage_runtime import LocalServiceUsageBinding, ObservedModelProvider
from w_agent.shared_budget_provider import SharedBudgetModelProvider
from tests.test_http_provider_templates import FakeHttpTransport
from tests.test_model_probing import FakeProvider
from tests.test_openai_compatible_provider import FakeTransport
from tests.test_runtime_shared_budget import Ledger, Meter


def check(result, level):
    return next(item for item in result.checks if item.level == level)


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", ["qwen", "turbo", "compatible"])
async def test_local_catalog_with_unreachable_url_and_invalid_key_is_not_healthy(vendor):
    transport = FakeHttpTransport() if vendor == "qwen" else FakeTransport()
    options = dict(base_url="https://unreachable.invalid", api_key="invalid",
                   default_model="configured", transport=transport)
    if vendor == "qwen":
        provider = qwen_native_provider(**options)
    elif vendor == "turbo":
        provider = turbo_provider(**options)
    else:
        provider = deepseek_provider(**options, discover_models=False)
    result = await ModelProviderProbe().probe(vendor, provider)
    assert result.successful  # Only means no performed check failed.
    assert check(result, ProbeLevel.L1_REACHABILITY).status == ProbeStatus.SKIPPED
    assert check(result, ProbeLevel.L2_AUTHENTICATION).status == ProbeStatus.SKIPPED
    assert check(result, ProbeLevel.L3_CATALOG).status == ProbeStatus.PASS
    assert ProbeHealthBridge().health(result) == HealthStatus.UNKNOWN
    calls = transport.request_calls if vendor == "qwen" else transport.get_calls
    assert calls == transport.stream_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("wrapper", ["none", "usage", "budget"])
async def test_remote_catalog_evidence_survives_wrappers_without_claiming_auth(native, wrapper):
    transport = FakeHttpTransport(catalog={"data": [{"id": "model"}]}) if native else FakeTransport()
    provider = (anthropic_provider if native else deepseek_provider)(transport=transport)
    if wrapper == "usage":
        provider = ObservedModelProvider(provider, LocalServiceUsageBinding(InMemoryServiceUsageLedger(), "op"))
    elif wrapper == "budget":
        provider = SharedBudgetModelProvider(provider, Ledger(), Meter())
    result = await ModelProviderProbe().probe("provider", provider)
    assert check(result, ProbeLevel.L1_REACHABILITY).status == ProbeStatus.PASS
    assert check(result, ProbeLevel.L2_AUTHENTICATION).status == ProbeStatus.SKIPPED
    assert ProbeHealthBridge().health(result) == HealthStatus.HEALTHY
    calls = transport.request_calls if native else transport.get_calls
    assert len(calls) == 1 and not transport.stream_calls


@pytest.mark.asyncio
async def test_legacy_unknown_scope_still_supports_explicit_active_probe():
    provider = FakeProvider()
    safe = await ModelProviderProbe().probe("legacy", provider)
    assert ProbeHealthBridge().health(safe) == HealthStatus.UNKNOWN
    active = await ModelProviderProbe().probe("legacy", provider, mode=ProbeMode.ACTIVE, allow_active=True)
    assert ProbeHealthBridge().health(active) == HealthStatus.HEALTHY
    assert provider.stream_calls == 1


@pytest.mark.parametrize("level", [ProbeLevel.L3_CATALOG, ProbeLevel.L6_TOOLS_STRUCTURED, ProbeLevel.L7_MULTIMODAL])
def test_catalog_or_capability_declarations_alone_never_imply_health(level):
    now = datetime.now(UTC)
    result = ProbeResult("provider", ProbeMode.SAFE,
        (ProbeCheck(level, "declaration", ProbeStatus.PASS, "declared"),),
        now, now, now + timedelta(minutes=1))
    assert ProbeHealthBridge().health(result) == HealthStatus.UNKNOWN
    failed = replace(result, checks=(ProbeCheck(level, "failure", ProbeStatus.FAIL, "failed"),))
    assert ProbeHealthBridge().health(failed) == HealthStatus.UNHEALTHY


@pytest.mark.asyncio
async def test_stateful_mapping_is_called_once_per_catalog_and_records_actual_path():
    class Mapping:
        calls = 0
        def catalog_request(self):
            self.calls += 1
            return None if self.calls == 1 else HttpRequest("GET", "/models")
        def parse_catalog(self, payload):
            return ("model",)

    mapping, transport = Mapping(), FakeHttpTransport()
    provider = HttpModelProvider(name="stateful", base_url="https://example.invalid",
        mapping=mapping, default_model="model", transport=transport)
    assert provider.catalog_probe_scope == "unknown" and mapping.calls == 0
    first = await ModelProviderProbe().probe("stateful", provider)
    assert mapping.calls == 1 and not transport.request_calls
    assert ProbeHealthBridge().health(first) == HealthStatus.UNKNOWN
    second = await ModelProviderProbe().probe("stateful", provider)
    assert mapping.calls == 2 and len(transport.request_calls) == 1
    assert ProbeHealthBridge().health(second) == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_catalog_evidence_is_task_local_and_does_not_follow_mutated_config():
    entered, release = asyncio.Event(), asyncio.Event()
    class Transport(FakeTransport):
        async def get_json(self, url, *, headers, timeout):
            entered.set()
            await release.wait()
            return await super().get_json(url, headers=headers, timeout=timeout)

    provider = deepseek_provider(transport=Transport(), default_model="model")
    async def remote_call():
        result = await ModelProviderProbe().probe("remote", provider)
        # Let the other task finish its local read before examining evidence.
        await asyncio.sleep(0)
        return result, provider.catalog_probe_scope
    task = asyncio.create_task(remote_call())
    await asyncio.wait_for(entered.wait(), 3)
    provider.discover_models = False
    local = await ModelProviderProbe().probe("local", provider)
    assert provider.catalog_probe_scope == "local"
    release.set()
    remote, scope = await task
    assert scope == "remote"
    assert provider.catalog_probe_scope == "local"
    assert ProbeHealthBridge().health(local) == HealthStatus.UNKNOWN
    assert ProbeHealthBridge().health(remote) == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_failed_catalog_resets_old_evidence_to_unknown():
    transport = FakeTransport()
    provider = deepseek_provider(transport=transport)
    await provider.list_models()
    assert provider.catalog_probe_scope == "remote"
    async def fail(*args, **kwargs):
        raise RuntimeError("offline")
    transport.get_json = fail
    with pytest.raises(RuntimeError):
        await provider.list_models()
    assert provider.catalog_probe_scope == "unknown"
