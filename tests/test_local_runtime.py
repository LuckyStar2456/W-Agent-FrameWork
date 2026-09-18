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
    ToolCallContent,
    ToolSideEffect,
    assemble_local_provider,
    assemble_local_runtime,
    local_runtime_config_from_mapping,
    python_tool,
)


class FakeProvider:
    def __init__(self, name: str, model: str) -> None:
        self.name = name
        self.model = model
        self.closed = False
        self.close_calls = 0

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

    async def aclose(self) -> None:
        self.closed = True
        self.close_calls += 1


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
    events = []

    async def record_event(event):
        events.append(event)

    runtime = assemble_local_runtime(
        _config(),
        tmp_path / ".wagent",
        templates=_templates(captured),
        environ={"TEST_MODEL_KEY": "not-persisted"},
    )

    run = await runtime.run(
        "hi",
        session_title="Configured run",
        event_callback=record_event,
    )

    assert run.result.output == "hello"
    assert [event.type.value for event in events] == [
        "run-started",
        "model-started",
        "model-completed",
        "token-usage",
        "run-completed",
    ]
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


@pytest.mark.asyncio
async def test_local_runtime_loads_explicit_pricing_and_persists_cost(tmp_path):
    config = local_runtime_config_from_mapping(
        {
            "provider": {
                "template": "fake",
                "name": "test-provider",
                "model": "test-model",
            },
            "pricing": {
                "version": "prices-v1",
                "currency": "USD",
                "max_cost": "10",
                "prices": [
                    {
                        "provider": "test-provider",
                        "model": "test-model",
                        "input_per_million": "1000000",
                        "output_per_million": "1000000",
                    }
                ],
            },
        }
    )
    runtime = assemble_local_runtime(
        config,
        tmp_path / ".wagent",
        templates=_templates({}),
    )

    run = await runtime.run("priced")

    assert run.result.cost is not None
    assert run.result.cost.total == 5
    assert run.result.cost_complete is True
    assert run.session.runs[0].cost is not None
    assert run.session.runs[0].cost.total == 5
    persisted = next((tmp_path / ".wagent" / "sessions").glob("*.json")).read_text(
        encoding="utf-8"
    )
    assert '"price_table_version":"prices-v1"' in persisted


def test_local_runtime_pricing_requires_configured_provider_model_rate(tmp_path):
    config = local_runtime_config_from_mapping(
        {
            "provider": {
                "template": "fake",
                "name": "test-provider",
                "model": "test-model",
            },
            "pricing": {
                "version": "prices-v1",
                "currency": "USD",
                "max_cost": "1",
                "prices": [
                    {
                        "provider": "other",
                        "model": "test-model",
                        "input_per_million": "1",
                        "output_per_million": "2",
                    }
                ],
            },
        }
    )

    with pytest.raises(LocalRuntimeConfigError, match="configured provider"):
        assemble_local_runtime(
            config,
            tmp_path,
            templates=_templates({}),
        )


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


@pytest.mark.asyncio
async def test_local_provider_assembly_has_no_registration_or_network_side_effects():
    captured = {}

    assembly = assemble_local_provider(
        _config(),
        templates=_templates(captured),
        environ={"TEST_MODEL_KEY": "resolved-only-at-assembly"},
    )

    assert assembly.name == "test-provider"
    assert isinstance(assembly.provider, FakeProvider)
    assert captured["default_model"] == "test-model"
    assert assembly.provider.closed is False

    async with assembly:
        pass

    assert assembly.provider.closed is True
    assert assembly.provider.close_calls == 1


@pytest.mark.asyncio
async def test_local_runtime_closes_provider_once_and_rejects_reuse(tmp_path):
    runtime = assemble_local_runtime(
        _config(),
        tmp_path,
        templates=_templates({}),
        environ={"TEST_MODEL_KEY": "runtime-secret"},
    )
    provider = runtime.models.provider("test-provider")

    await runtime.aclose()
    await runtime.aclose()

    assert provider.closed is True
    assert provider.close_calls == 1
    with pytest.raises(RuntimeError, match="closed"):
        await runtime.run("must not run")


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


class ToolCallingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__("test-provider", "test-model")
        self.calls = 0

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        return (
            ModelDescriptor(
                self.name,
                self.model,
                frozenset(
                    {
                        ModelCapability.TEXT_INPUT,
                        ModelCapability.TEXT_OUTPUT,
                        ModelCapability.TOOL_CALLING,
                    }
                ),
            ),
        )

    async def stream(self, request, *, cancellation=None) -> AsyncIterator:
        del request, cancellation
        self.calls += 1
        if self.calls == 1:
            block = ToolCallContent("save-1", "save_note", '{"text":"value"}')
            yield BlockStart(0, block.type)
            yield BlockEnd(0, block)
            yield UsageEvent(TokenUsage(4, 1))
            yield FinishEvent(FinishReason.TOOL_CALLS)
            return
        yield BlockStart(0, "text")
        yield TextDelta(0, "saved")
        yield BlockEnd(0, TextContent("saved"))
        yield UsageEvent(TokenUsage(3, 1))
        yield FinishEvent(FinishReason.STOP)


@pytest.mark.asyncio
async def test_local_runtime_selects_catalog_tools_and_resumes_approval(tmp_path):
    provider = ToolCallingProvider()
    templates = ProviderTemplateRegistry(
        (
            ProviderTemplate(
                "fake",
                "Fake",
                "test",
                None,
                lambda **options: provider,
            ),
        )
    )
    writes = []

    def save_note(text: str) -> str:
        writes.append(text)
        return "saved"

    config = local_runtime_config_from_mapping(
        {
            "provider": {
                "template": "fake",
                "name": "test-provider",
                "model": "test-model",
            },
            "agent": {
                "name": "tools",
                "max_tool_calls": 1,
                "require_usage": True,
            },
            "tools": {"enabled": ["save_note"]},
        }
    )
    runtime = assemble_local_runtime(
        config,
        tmp_path / ".wagent",
        templates=templates,
        tool_bindings={
            "save_note": python_tool(
                save_note,
                side_effect=ToolSideEffect.WRITE,
                required_permissions=frozenset({"notes.write"}),
            )
        },
    )

    pending = await runtime.run(
        "save",
        permissions=frozenset({"notes.write"}),
    )

    assert pending.result.stop_reason.value == "needs-approval"
    assert pending.result.pending_tool_call is not None
    assert pending.result.pending_tool_call.id == "save-1"
    assert writes == []

    resumed_events = []
    completed = await runtime.resume(
        pending.session.session_id,
        pending.result.run_id,
        permissions=frozenset({"notes.write"}),
        approved_call_ids=frozenset({"save-1"}),
        event_callback=resumed_events.append,
    )

    assert completed.result.output == "saved"
    assert completed.result.stop_reason.value == "completed"
    assert writes == ["value"]
    assert completed.result.usage == TokenUsage(7, 2)
    assert resumed_events[0].type.value == "run-resumed"
    assert resumed_events[-1].type.value == "run-completed"


def test_local_runtime_tool_selection_requires_budget_and_authorized_catalog(tmp_path):
    with pytest.raises(LocalRuntimeConfigError, match="max_tool_calls"):
        local_runtime_config_from_mapping(
            {
                "provider": {"template": "fake", "model": "test-model"},
                "tools": {"enabled": ["lookup"]},
            }
        )

    config = local_runtime_config_from_mapping(
        {
            "provider": {"template": "fake", "model": "test-model"},
            "agent": {"max_tool_calls": 1},
            "tools": {"enabled": ["lookup"]},
        }
    )
    with pytest.raises(LocalRuntimeConfigError, match="authorized catalog"):
        assemble_local_runtime(
            config,
            tmp_path,
            templates=_templates({}),
        )
