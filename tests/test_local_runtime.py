from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from w_agent import (
    BlockEnd,
    BlockStart,
    FinishEvent,
    FinishReason,
    LocalRuntimeConfigError,
    ModelCapability,
    ModelDescriptor,
    ProviderTemplate,
    ProviderTemplateRegistry,
    TextContent,
    TextDelta,
    TokenUsage,
    UsageEvent,
    assemble_local_runtime,
    local_runtime_config_from_mapping,
)


class FakeProvider:
    def __init__(self, name: str, model: str) -> None:
        self.name = name
        self.model = model

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        return (
            ModelDescriptor(
                self.name,
                self.model,
                frozenset(
                    {
                        ModelCapability.TEXT_INPUT,
                        ModelCapability.TEXT_OUTPUT,
                    }
                ),
            ),
        )

    async def resolve(self, model: str) -> ModelDescriptor:
        return (await self.list_models())[0]

    async def stream(self, request, *, cancellation=None) -> AsyncIterator:
        del request, cancellation
        yield BlockStart(0, "text")
        yield TextDelta(0, "hello")
        yield BlockEnd(0, TextContent("hello"))
        yield UsageEvent(TokenUsage(3, 2))
        yield FinishEvent(FinishReason.STOP)


def _config(**agent_overrides):
    agent = {
        "name": "configured",
        "max_total_tokens": 20,
        "require_usage": True,
        **agent_overrides,
    }
    return local_runtime_config_from_mapping(
        {
            "provider": {
                "template": "fake",
                "name": "test-provider",
                "model": "test-model",
                "api_key_env": "TEST_MODEL_KEY",
            },
            "agent": agent,
        }
    )


def _templates(captured):
    def build(**options):
        captured.update(options)
        return FakeProvider(options["name"], options["default_model"])

    return ProviderTemplateRegistry(
        (ProviderTemplate("fake", "Fake", "test", None, build),)
    )


@pytest.mark.asyncio
async def test_local_runtime_assembles_full_text_run_and_persists_session(tmp_path):
    captured = {}
    runtime = assemble_local_runtime(
        _config(),
        tmp_path / ".wagent",
        templates=_templates(captured),
        environ={"TEST_MODEL_KEY": "not-persisted"},
    )

    run = await runtime.run("hi", session_title="Configured run")

    assert run.result.output == "hello"
    assert run.result.usage == TokenUsage(3, 2)
    assert run.result.usage_complete is True
    assert len(run.result.attempts) == 1
    assert run.result.attempts[0].usage == TokenUsage(3, 2)
    assert run.session.runs[0].usage.total_tokens == 5
    assert run.session.runs[0].model_calls == 1
    assert run.session.runs[0].reported_usage_calls == 1
    assert captured["api_key"] == "not-persisted"
    records = list((tmp_path / ".wagent" / "sessions").glob("*.json"))
    assert len(records) == 1
    persisted = "".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / ".wagent").rglob("*")
        if path.is_file()
    )
    assert "not-persisted" not in persisted


def test_local_runtime_requires_env_reference_and_rejects_secret_fields(tmp_path):
    with pytest.raises(LocalRuntimeConfigError, match="environment variable"):
        assemble_local_runtime(
            _config(),
            tmp_path,
            templates=_templates({}),
            environ={},
        )

    with pytest.raises(LocalRuntimeConfigError, match="unsupported fields"):
        local_runtime_config_from_mapping(
            {
                "provider": {
                    "template": "fake",
                    "model": "test-model",
                    "api_key": "inline-secret",
                }
            }
        )

    with pytest.raises(LocalRuntimeConfigError, match="cannot contain credentials"):
        _config(extensions={"access_token": "inline-secret"})

    with pytest.raises(LocalRuntimeConfigError, match="valid variable name"):
        local_runtime_config_from_mapping(
            {
                "provider": {
                    "template": "fake",
                    "model": "test-model",
                    "api_key_env": "BAD-NAME",
                }
            }
        )

    with pytest.raises(LocalRuntimeConfigError, match="cannot override"):
        assemble_local_runtime(
            local_runtime_config_from_mapping(
                {"provider": {"template": "fake", "model": "test-model"}}
            ),
            tmp_path,
            templates=_templates({}),
            provider_options={"api_key": "inline-secret"},
        )


def test_local_runtime_rejects_unknown_schema_and_invalid_budget():
    with pytest.raises(LocalRuntimeConfigError, match="schema version"):
        local_runtime_config_from_mapping(
            {
                "schema_version": 2,
                "provider": {"template": "fake", "model": "test-model"},
            }
        )

    with pytest.raises(ValueError, match="positive"):
        _config(max_total_tokens=0)
