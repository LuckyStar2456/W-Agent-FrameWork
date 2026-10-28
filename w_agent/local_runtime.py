"""Safe local configuration and assembly for one practical agent runtime."""

from __future__ import annotations

import json
import os
import re
import inspect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from w_agent.agents import (
    AgentDefinition,
    AgentLoop,
    CharacterTokenEstimator,
    CostBudget,
    JsonlRunStore,
    ReactAgentLoop,
    RunResult,
    TokenBudget,
    ToolResultEventEncoder,
)
from w_agent.models import (
    CancellationToken,
    InvocationPolicy,
    MessageRole,
    ModelExecutor,
    ModelMessage,
    ModelProvider,
    ModelPrice,
    ModelRegistry,
    ModelRouter,
    NativeCursorRecovery,
    ProviderTemplateRegistry,
    PriceTable,
    PricingCatalog,
    PricingError,
    StreamRecoveryStrategy,
    TokenUsage,
    WeightedRoutingPolicy,
    builtin_provider_template_registry,
)
from w_agent.session_inputs import SessionInputRecorder
from w_agent.shared_budget import SharedBudgetController, SharedBudgetError, SharedBudgetSnapshot
from w_agent.shared_budget_provider import SharedBudgetMeter, SharedBudgetModelProvider
from w_agent.knowledge_runtime import LocalKnowledgeBinding, LocalKnowledgeConfig
from w_agent.service_usage_runtime import LocalServiceUsageBinding, LocalServiceUsageConfig, ObservedModelProvider
from w_agent.service_usage_adapters import ObservedKnowledgeRetriever, ObservedSharedBudgetController
from w_agent.service_usage import ServiceUsageError
from w_agent.service_usage_links import ServiceUsageRunLink
from w_agent.sessions import (
    JsonSessionStore,
    RunEventCallback,
    SessionManager,
    SessionRecord,
    SessionHistoryPolicy,
    AsyncSessionHistoryPolicy,
)
from w_agent.tools import ToolBinding, ToolExecutionContext, ToolExecutor, ToolRegistry

_COMPATIBLE_TEMPLATES = frozenset(
    {"deepseek", "glm", "qwen", "turbo", "vllm"}
)
_SENSITIVE_PARTS = ("secret", "password", "api_key", "token", "credential")


class LocalRuntimeConfigError(ValueError):
    """A local runtime configuration is unsafe, missing, or unsupported."""


@dataclass(frozen=True, slots=True)
class LocalProviderConfig:
    template: str
    model: str
    name: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    timeout: float = 60.0

    def __post_init__(self) -> None:
        if not self.template.strip() or not self.model.strip():
            raise LocalRuntimeConfigError("provider template and model are required")
        if self.name is not None and not self.name.strip():
            raise LocalRuntimeConfigError("provider name must not be empty")
        if self.api_key_env is not None and not self.api_key_env.strip():
            raise LocalRuntimeConfigError("api_key_env must not be empty")
        if self.api_key_env is not None and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", self.api_key_env
        ):
            raise LocalRuntimeConfigError("api_key_env is not a valid variable name")
        if self.timeout <= 0:
            raise LocalRuntimeConfigError("provider timeout must be positive")


@dataclass(frozen=True, slots=True)
class LocalInvocationConfig:
    max_attempts_per_route: int = 1
    max_routes: int = 1
    timeout: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts_per_route < 1 or self.max_routes < 1:
            raise LocalRuntimeConfigError("invocation attempt limits must be positive")
        if self.timeout <= 0:
            raise LocalRuntimeConfigError("invocation timeout must be positive")


@dataclass(frozen=True, slots=True)
class LocalAgentConfig:
    name: str = "assistant"
    system_prompt: str | None = None
    max_steps: int = 8
    max_tool_calls: int = 0
    temperature: float | None = None
    max_output_tokens: int | None = None
    max_input_tokens: int | None = None
    max_cumulative_output_tokens: int | None = None
    max_total_tokens: int | None = None
    require_usage: bool = True
    token_estimator: str | None = None
    estimator_characters_per_token: int = 4
    require_estimate: bool = False
    soft_limit_ratio: Decimal | str | int | float | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)
    emit_text_deltas: bool = False
    emit_tool_call_deltas: bool = False
    emit_output_blocks: bool = False
    emit_tool_results: bool = False
    max_tool_result_event_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise LocalRuntimeConfigError("agent name must not be empty")
        if self.max_steps <= 0 or self.max_tool_calls < 0:
            raise LocalRuntimeConfigError("agent step and tool limits are invalid")
        if self.temperature is not None and self.temperature < 0:
            raise LocalRuntimeConfigError("agent temperature must not be negative")
        if not isinstance(self.emit_text_deltas, bool):
            raise LocalRuntimeConfigError("emit_text_deltas must be a boolean")
        if not isinstance(self.emit_tool_call_deltas, bool):
            raise LocalRuntimeConfigError("emit_tool_call_deltas must be a boolean")
        if not isinstance(self.emit_output_blocks, bool):
            raise LocalRuntimeConfigError("emit_output_blocks must be a boolean")
        if type(self.emit_tool_results) is not bool:
            raise LocalRuntimeConfigError("emit_tool_results must be a boolean")
        if type(self.max_tool_result_event_bytes) is not int or self.max_tool_result_event_bytes <= 0:
            raise LocalRuntimeConfigError("max_tool_result_event_bytes must be a positive integer")
        limits = (
            self.max_output_tokens,
            self.max_input_tokens,
            self.max_cumulative_output_tokens,
            self.max_total_tokens,
        )
        if any(item is not None and item <= 0 for item in limits):
            raise LocalRuntimeConfigError("agent token limits must be positive")
        if not isinstance(self.require_usage, bool):
            raise LocalRuntimeConfigError("require_usage must be a boolean")
        if self.token_estimator not in (None, "character"):
            raise LocalRuntimeConfigError(
                "agent token_estimator must be null or 'character'"
            )
        if (
            isinstance(self.estimator_characters_per_token, bool)
            or not isinstance(self.estimator_characters_per_token, int)
            or self.estimator_characters_per_token <= 0
        ):
            raise LocalRuntimeConfigError(
                "estimator_characters_per_token must be a positive integer"
            )
        if not isinstance(self.require_estimate, bool):
            raise LocalRuntimeConfigError("require_estimate must be a boolean")
        if self.require_estimate and self.token_estimator is None:
            raise LocalRuntimeConfigError(
                "require_estimate needs an explicit token_estimator"
            )
        try:
            normalized_budget = TokenBudget(
                max_input_tokens=self.max_input_tokens,
                max_output_tokens=self.max_cumulative_output_tokens,
                max_total_tokens=self.max_total_tokens,
                require_usage=self.require_usage,
                require_estimate=self.require_estimate,
                soft_limit_ratio=self.soft_limit_ratio,
            )
        except ValueError as error:
            raise LocalRuntimeConfigError("agent token budget is invalid") from error
        object.__setattr__(
            self,
            "soft_limit_ratio",
            normalized_budget.soft_limit_ratio,
        )
        _reject_secrets(self.extensions, "agent.extensions")
        object.__setattr__(self, "extensions", MappingProxyType(dict(self.extensions)))


@dataclass(frozen=True, slots=True)
class LocalToolConfig:
    """Names selected from a host-supplied catalog, never authority grants."""

    enabled: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = tuple(self.enabled)
        if any(not isinstance(item, str) or not item.strip() for item in values):
            raise LocalRuntimeConfigError(
                "enabled tool names must be non-empty strings"
            )
        if len(set(values)) != len(values):
            raise LocalRuntimeConfigError("enabled tool names must be unique")
        object.__setattr__(self, "enabled", values)


@dataclass(frozen=True, slots=True)
class LocalPricingConfig:
    """One explicit local price-table version and cumulative run limit."""

    version: str
    currency: str
    max_cost: Decimal | str | int | float
    prices: tuple[ModelPrice, ...]
    estimate_before_call: bool = False
    require_estimate: bool = False
    soft_limit_ratio: Decimal | str | int | float | None = None

    def __post_init__(self) -> None:
        try:
            budget = CostBudget(
                self.max_cost,
                self.version,
                self.currency,
                estimate_before_call=self.estimate_before_call,
                require_estimate=self.require_estimate,
                soft_limit_ratio=self.soft_limit_ratio,
            )
            table = PriceTable(self.version, self.currency, tuple(self.prices))
        except (TypeError, ValueError, PricingError) as error:
            raise LocalRuntimeConfigError("pricing configuration is invalid") from error
        object.__setattr__(self, "version", table.version)
        object.__setattr__(self, "currency", table.currency)
        object.__setattr__(self, "max_cost", budget.max_cost)
        object.__setattr__(self, "prices", table.prices)
        object.__setattr__(self, "soft_limit_ratio", budget.soft_limit_ratio)

    def price_table(self) -> PriceTable:
        return PriceTable(self.version, self.currency, self.prices)


@dataclass(frozen=True, slots=True)
class LocalSharedBudgetConfig:
    """Select a host-supplied binding; no paths, imports, credentials or grants."""

    binding: str

    def __post_init__(self) -> None:
        if (not isinstance(self.binding, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", self.binding)):
            raise LocalRuntimeConfigError("shared_budget.binding must be a bounded opaque name")


@dataclass(frozen=True, slots=True)
class LocalSharedBudgetBinding:
    """Host-owned shared controller and reliable per-Provider meter.

    Construction/assembly never initializes, snapshots, closes or reconciles
    these objects. Independent bindings may use one controller with different
    Provider-specific meters. Their methods are trusted host code.
    """

    controller: SharedBudgetController
    meter: SharedBudgetMeter

    def __post_init__(self) -> None:
        if any(not callable(getattr(self.controller, name, None)) for name in ("reserve", "settle", "release")):
            raise LocalRuntimeConfigError("shared budget controller needs reserve, settle and release")
        if any(not callable(getattr(self.meter, name, None)) for name in ("bound", "actual")):
            raise LocalRuntimeConfigError("shared budget meter needs bound and actual")

    async def snapshot(self) -> SharedBudgetSnapshot:
        """Optional controller capability, not a per-Run or per-Session total."""
        reader = getattr(self.controller, "snapshot", None)
        if not callable(reader):
            raise SharedBudgetError("shared-budget-snapshot-unavailable")
        try:
            result = await reader()
            if not isinstance(result, SharedBudgetSnapshot):
                raise ValueError("typed shared snapshot required")
            return result
        except SharedBudgetError:
            raise
        except Exception:
            raise SharedBudgetError("shared-budget-snapshot-failed") from None


@dataclass(frozen=True, slots=True)
class LocalRuntimeConfig:
    provider: LocalProviderConfig
    agent: LocalAgentConfig = field(default_factory=LocalAgentConfig)
    invocation: LocalInvocationConfig = field(default_factory=LocalInvocationConfig)
    tools: LocalToolConfig = field(default_factory=LocalToolConfig)
    pricing: LocalPricingConfig | None = None
    schema_version: int = 1
    shared_budget: LocalSharedBudgetConfig | None = None
    knowledge: LocalKnowledgeConfig | None = None
    service_usage: LocalServiceUsageConfig | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise LocalRuntimeConfigError("unsupported local runtime schema version")
        if self.knowledge is not None and not isinstance(self.knowledge, LocalKnowledgeConfig):
            raise LocalRuntimeConfigError("knowledge needs a typed binding selection")
        if self.service_usage is not None and not isinstance(self.service_usage, LocalServiceUsageConfig):
            raise LocalRuntimeConfigError("service_usage needs a typed binding selection")
        if self.shared_budget is not None:
            if not isinstance(self.shared_budget, LocalSharedBudgetConfig):
                raise LocalRuntimeConfigError("shared_budget needs a typed binding selection")
            if type(self.agent.max_output_tokens) is not int or self.agent.max_output_tokens <= 0:
                raise LocalRuntimeConfigError("shared_budget requires explicit positive agent.max_output_tokens")
        if self.tools.enabled and self.agent.max_tool_calls == 0:
            raise LocalRuntimeConfigError(
                "enabled tools require agent.max_tool_calls to be positive"
            )
        if self.pricing is not None and self.pricing.estimate_before_call:
            if self.agent.token_estimator is None:
                raise LocalRuntimeConfigError(
                    "pricing preflight needs an explicit token_estimator"
                )
            if all(
                value is None
                for value in (
                    self.agent.max_output_tokens,
                    self.agent.max_cumulative_output_tokens,
                    self.agent.max_total_tokens,
                )
            ):
                raise LocalRuntimeConfigError(
                    "pricing preflight needs an output or total token limit"
                )


@dataclass(frozen=True, slots=True)
class LocalRuntimeRun:
    session: SessionRecord
    result: RunResult
    service_usage_operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class LocalProviderAssembly:
    """One configured provider built without registering it or performing I/O."""

    name: str
    provider: ModelProvider
    shared_budget: LocalSharedBudgetBinding | None = field(default=None, repr=False)
    _owned_provider: ModelProvider | None = field(default=None, repr=False, compare=False)
    service_usage: LocalServiceUsageBinding | None = field(default=None, repr=False)
    _closed: bool = field(default=False, init=False, repr=False, compare=False)

    async def __aenter__(self) -> "LocalProviderAssembly":
        if self._closed:
            raise RuntimeError("local provider assembly is closed")
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        object.__setattr__(self, "_closed", True)
        owned = self.provider if self._owned_provider is None else self._owned_provider
        close = getattr(owned, "aclose", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result


@dataclass(slots=True)
class LocalAgentRuntime:
    """One assembled local runtime whose replaceable parts remain public."""

    config: LocalRuntimeConfig
    definition: AgentDefinition
    loop: AgentLoop
    sessions: SessionManager
    models: ModelRegistry
    tools: ToolRegistry
    shared_budget: LocalSharedBudgetBinding | None = field(default=None, repr=False)
    _owned_providers: tuple[ModelProvider, ...] = field(default=(), repr=False)
    knowledge: LocalKnowledgeBinding | None = field(default=None, repr=False)
    service_usage: LocalServiceUsageBinding | None = field(default=None, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _manage_providers: bool = field(default=True, repr=False)

    async def __aenter__(self) -> "LocalAgentRuntime":
        self._ensure_open()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close each assembled provider once when it exposes cleanup."""

        if self._closed:
            return
        self._closed = True
        if not self._manage_providers:
            # In an ApplicationContext, provider resources belong to their own
            # component. The runtime is only a consumer, never a second owner.
            return
        seen: set[int] = set()
        providers = (*self._owned_providers, *(provider for _, provider in self.models.providers()))
        for provider in providers:
            identity = id(provider)
            if identity in seen:
                continue
            seen.add(identity)
            close = getattr(provider, "aclose", None)
            if close is None:
                continue
            result = close()
            if inspect.isawaitable(result):
                await result

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("local agent runtime is closed")

    async def shared_budget_snapshot(self) -> SharedBudgetSnapshot | None:
        """Explicit shared-pool read, without merging it into historical Run usage."""
        self._ensure_open()
        if self.shared_budget is None:
            return None
        return await self.shared_budget.snapshot()

    async def service_usage_summary(self) -> dict | None:
        """Explicit host-operation view; does not merge retrieval into Run usage."""
        self._ensure_open()
        from w_agent._service_usage_ui import service_usage_summary
        return await service_usage_summary(self.service_usage)

    async def run(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        session_title: str | None = None,
        permissions: frozenset[str] = frozenset(),
        approved_call_ids: frozenset[str] = frozenset(),
        cancellation: CancellationToken | None = None,
        event_callback: RunEventCallback | None = None,
        record_inputs: bool = False,
        include_history: bool = True,
        history_policy: SessionHistoryPolicy | AsyncSessionHistoryPolicy | None = None,
        input_recorder: SessionInputRecorder | None = None,
        knowledge_query: str | None = None,
        confirm_knowledge_query: bool = False,
    ) -> LocalRuntimeRun:
        self._ensure_open()
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("agent prompt must not be empty")
        return await self.run_messages(
            (ModelMessage.text(MessageRole.USER, prompt),),
            session_id=session_id, session_title=session_title or prompt[:80],
            permissions=permissions, approved_call_ids=approved_call_ids,
            cancellation=cancellation, event_callback=event_callback,
            record_inputs=record_inputs, include_history=include_history, history_policy=history_policy,
            input_recorder=input_recorder,
            knowledge_query=knowledge_query, confirm_knowledge_query=confirm_knowledge_query,
        )

    async def run_messages(
        self, messages: Iterable[ModelMessage], *,
        session_id: str | None = None,
        session_title: str | None = None,
        permissions: frozenset[str] = frozenset(),
        approved_call_ids: frozenset[str] = frozenset(),
        cancellation: CancellationToken | None = None,
        event_callback: RunEventCallback | None = None,
        record_inputs: bool = False,
        include_history: bool = True,
        history_policy: SessionHistoryPolicy | AsyncSessionHistoryPolicy | None = None,
        input_recorder: SessionInputRecorder | None = None,
        knowledge_query: str | None = None,
        confirm_knowledge_query: bool = False,
    ) -> LocalRuntimeRun:
        """Run typed content with explicit, per-call recording and history policy."""
        self._ensure_open()
        current = tuple(messages)
        if not current or not all(isinstance(message, ModelMessage) for message in current):
            raise ValueError("run_messages needs a nonempty sequence of ModelMessages")
        if type(record_inputs) is not bool or type(include_history) is not bool:
            raise ValueError("recording/history switches must be booleans")
        if history_policy is not None and not callable(getattr(history_policy, "project", None)):
            raise ValueError("history policy needs a project method")
        if input_recorder is not None and (
            not record_inputs or not callable(getattr(input_recorder, "record", None))
        ):
            raise ValueError("per-call recorder requires record_inputs=True and a record method")
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        if type(confirm_knowledge_query) is not bool:
            raise ValueError("knowledge confirmation must be boolean")
        if knowledge_query is not None:
            if confirm_knowledge_query is not True:
                raise ValueError("knowledge context requires explicit query confirmation")
            if self.config.knowledge is None or self.knowledge is None:
                raise ValueError("knowledge query requires a selected authorized binding")
            history_policy = self.knowledge.context_policy(knowledge_query, history_policy=history_policy,
                                                           include_history=include_history)
            # The wrapper may retrieve knowledge while projecting zero history.
            include_history = True
        elif confirm_knowledge_query:
            raise ValueError("knowledge confirmation requires an explicit query")
        if session_id is None:
            session = await self.sessions.create(session_title or "Agent run")
        else:
            session = await self.sessions.get(session_id)
        link_options = {}
        if self.service_usage is not None and self.service_usage.links is not None:
            # Commit correlation before SessionManager prepares async history or
            # retrieval. A failed preparation may leave only this preassociation.
            run_id = f"run-{uuid4().hex}"
            link = ServiceUsageRunLink(session.session_id, run_id, self.service_usage.operation_id)
            await self.service_usage.links.bind(link, confirm_write=True)
            link_options["run_id"] = run_id
        result = await self.sessions.run_agent(
            self.loop,
            self.definition,
            session.session_id,
            current,
            **link_options,
            record_inputs=record_inputs,
            **({"input_recorder": input_recorder} if input_recorder is not None else {}),
            include_history=include_history,
            history_policy=history_policy,
            cancellation=cancellation,
            tool_context=ToolExecutionContext(
                permissions=permissions,
                approved_call_ids=approved_call_ids,
                cancellation=cancellation,
            ),
            event_callback=event_callback,
        )
        return LocalRuntimeRun(await self.sessions.get(session.session_id), result,
                               self.service_usage.operation_id if self.service_usage is not None else None)

    async def resume(
        self,
        session_id: str,
        run_id: str,
        *,
        permissions: frozenset[str] = frozenset(),
        approved_call_ids: frozenset[str],
        cancellation: CancellationToken | None = None,
        event_callback: RunEventCallback | None = None,
    ) -> LocalRuntimeRun:
        """Resume one persisted approval checkpoint with explicit authority."""

        self._ensure_open()
        if not approved_call_ids:
            raise ValueError("resume requires at least one approved tool call ID")
        if self.service_usage is not None and self.service_usage.links is not None:
            expected = ServiceUsageRunLink(session_id, run_id, self.service_usage.operation_id)
            stored = await self.service_usage.links.get(run_id)
            if not isinstance(stored, ServiceUsageRunLink) or stored != expected:
                raise ServiceUsageError("service-usage-resume-link-missing-or-conflicting")
        result = await self.sessions.resume_agent(
            self.loop,
            session_id,
            run_id,
            tool_context=ToolExecutionContext(
                permissions=permissions,
                approved_call_ids=approved_call_ids,
                cancellation=cancellation,
            ),
            cancellation=cancellation,
            event_callback=event_callback,
        )
        return LocalRuntimeRun(await self.sessions.get(session_id), result,
                               self.service_usage.operation_id if self.service_usage is not None else None)


def load_local_runtime_config(path: str | Path) -> LocalRuntimeConfig:
    """Load strict JSON configuration without resolving credentials."""

    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise LocalRuntimeConfigError("local runtime config cannot be read") from error
    except json.JSONDecodeError as error:
        raise LocalRuntimeConfigError(
            "local runtime config is not valid JSON"
        ) from error
    if not isinstance(data, Mapping):
        raise LocalRuntimeConfigError("local runtime config must be an object")
    return local_runtime_config_from_mapping(data)


def local_runtime_config_from_mapping(value: Mapping[str, Any]) -> LocalRuntimeConfig:
    """Validate parsed configuration and reject hidden or secret-bearing fields."""

    _known_keys(
        value,
        {"schema_version", "provider", "agent", "invocation", "tools", "pricing", "shared_budget", "knowledge", "service_usage"},
        "config",
    )
    provider_value = _mapping(value.get("provider"), "provider")
    _known_keys(
        provider_value,
        {"template", "model", "name", "base_url", "api_key_env", "timeout"},
        "provider",
    )
    agent_value = _mapping(value.get("agent", {}), "agent")
    _known_keys(
        agent_value,
        {
            "name",
            "system_prompt",
            "max_steps",
            "max_tool_calls",
            "temperature",
            "max_output_tokens",
            "emit_text_deltas",
            "emit_tool_call_deltas",
            "emit_output_blocks",
            "emit_tool_results",
            "max_tool_result_event_bytes",
            "max_input_tokens",
            "max_cumulative_output_tokens",
            "max_total_tokens",
            "require_usage",
            "token_estimator",
            "estimator_characters_per_token",
            "require_estimate",
            "soft_limit_ratio",
            "extensions",
        },
        "agent",
    )
    invocation_value = _mapping(value.get("invocation", {}), "invocation")
    _known_keys(
        invocation_value,
        {"max_attempts_per_route", "max_routes", "timeout"},
        "invocation",
    )
    tools_value = _mapping(value.get("tools", {}), "tools")
    _known_keys(tools_value, {"enabled"}, "tools")
    shared_budget_raw = value.get("shared_budget")
    shared_budget = None
    if shared_budget_raw is not None:
        shared_budget_value = _mapping(shared_budget_raw, "shared_budget")
        _known_keys(shared_budget_value, {"binding"}, "shared_budget")
        if "binding" not in shared_budget_value:
            raise LocalRuntimeConfigError("shared_budget.binding is required")
        shared_budget = LocalSharedBudgetConfig(shared_budget_value["binding"])
    pricing_raw = value.get("pricing")
    service_usage = None
    if value.get("service_usage") is not None:
        usage_value = _mapping(value["service_usage"], "service_usage")
        _known_keys(usage_value, {"binding"}, "service_usage")
        try:
            service_usage = LocalServiceUsageConfig(**usage_value)
        except (TypeError, ValueError):
            raise LocalRuntimeConfigError("service_usage requires a bounded binding name") from None
    knowledge = None
    if value.get("knowledge") is not None:
        knowledge_value = _mapping(value["knowledge"], "knowledge")
        _known_keys(knowledge_value, {"binding"}, "knowledge")
        try:
            knowledge = LocalKnowledgeConfig(**knowledge_value)
        except (TypeError, ValueError):
            raise LocalRuntimeConfigError("knowledge requires a bounded binding name") from None
    pricing = None
    if pricing_raw is not None:
        pricing_value = _mapping(pricing_raw, "pricing")
        _known_keys(
            pricing_value,
            {
                "version",
                "currency",
                "max_cost",
                "prices",
                "estimate_before_call",
                "require_estimate",
                "soft_limit_ratio",
            },
            "pricing",
        )
        raw_prices = pricing_value.get("prices")
        if not isinstance(raw_prices, list):
            raise LocalRuntimeConfigError("pricing.prices must be a list")
        prices: list[ModelPrice] = []
        for index, raw_price in enumerate(raw_prices):
            price = _mapping(raw_price, f"pricing.prices[{index}]")
            _known_keys(
                price,
                {
                    "provider",
                    "model",
                    "input_per_million",
                    "output_per_million",
                    "cached_input_per_million",
                },
                f"pricing.prices[{index}]",
            )
            try:
                prices.append(ModelPrice(**price))
            except (TypeError, ValueError, PricingError) as error:
                raise LocalRuntimeConfigError(
                    f"pricing.prices[{index}] is invalid"
                ) from error
        try:
            pricing = LocalPricingConfig(
                version=str(pricing_value.get("version", "")),
                currency=str(pricing_value.get("currency", "")),
                max_cost=pricing_value.get("max_cost", ""),
                prices=tuple(prices),
                estimate_before_call=pricing_value.get(
                    "estimate_before_call",
                    False,
                ),
                require_estimate=pricing_value.get("require_estimate", False),
                soft_limit_ratio=pricing_value.get("soft_limit_ratio"),
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, LocalRuntimeConfigError):
                raise
            raise LocalRuntimeConfigError("pricing configuration is invalid") from error
    try:
        provider = LocalProviderConfig(**provider_value)
        agent = LocalAgentConfig(**agent_value)
        invocation = LocalInvocationConfig(**invocation_value)
        tools = LocalToolConfig(**tools_value)
        return LocalRuntimeConfig(
            provider=provider,
            agent=agent,
            invocation=invocation,
            tools=tools,
            pricing=pricing,
            schema_version=int(value.get("schema_version", 1)),
            shared_budget=shared_budget,
            knowledge=knowledge,
            service_usage=service_usage,
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, LocalRuntimeConfigError):
            raise
        raise LocalRuntimeConfigError(
            "local runtime config has invalid values"
        ) from error


def assemble_local_runtime(
    config: LocalRuntimeConfig,
    state_root: str | Path = ".wagent",
    *,
    templates: ProviderTemplateRegistry | None = None,
    environ: Mapping[str, str] | None = None,
    provider_options: Mapping[str, Any] | None = None,
    tool_bindings: Mapping[str, ToolBinding] | None = None,
    stream_recovery: StreamRecoveryStrategy | NativeCursorRecovery | None = None,
    tool_result_event_encoder: ToolResultEventEncoder | None = None,
    shared_budget_bindings: Mapping[str, LocalSharedBudgetBinding] | None = None,
    knowledge_bindings: Mapping[str, LocalKnowledgeBinding] | None = None,
    service_usage_bindings: Mapping[str, LocalServiceUsageBinding] | None = None,
) -> LocalAgentRuntime:
    """Compatibility assembly; use compile_local_runtime for managed composition."""

    knowledge = _select_knowledge_binding(config, knowledge_bindings)
    _validate_runtime_bindings(config, knowledge, stream_recovery, service_usage_bindings)
    provider_assembly = assemble_local_provider(
        config,
        templates=templates,
        environ=environ,
        provider_options=provider_options,
        shared_budget_bindings=shared_budget_bindings,
        service_usage_bindings=service_usage_bindings,
    )
    provider_name = provider_assembly.name
    provider = provider_assembly.provider
    usage_binding = provider_assembly.service_usage
    knowledge = _observe_knowledge_binding(knowledge, usage_binding)

    models = ModelRegistry()
    models.register(provider_name, provider)
    router = ModelRouter(
        models,
        WeightedRoutingPolicy(allow_providers=frozenset({provider_name})),
    )
    invocation = config.invocation
    executor = ModelExecutor(
        models,
        router,
        InvocationPolicy(
            max_attempts_per_route=invocation.max_attempts_per_route,
            max_routes=invocation.max_routes,
            timeout=invocation.timeout,
        ),
    )
    tools = _build_local_tools(config, tool_bindings)
    tool_executor = ToolExecutor(tools)
    state = Path(state_root)
    pricing_catalog, cost_budget = _build_local_pricing(config)
    agent = config.agent
    loop = ReactAgentLoop(
        executor,
        tools,
        tool_executor,
        store=JsonlRunStore(state),
        pricing=pricing_catalog,
        token_estimator=(
            CharacterTokenEstimator(agent.estimator_characters_per_token)
            if agent.token_estimator == "character"
            else None
        ),
        stream_recovery=stream_recovery,
        tool_result_event_encoder=tool_result_event_encoder,
    )
    definition = _build_local_definition(config, cost_budget)
    sessions = SessionManager(JsonSessionStore(state / "sessions"))
    owned = provider if provider_assembly._owned_provider is None else provider_assembly._owned_provider
    return LocalAgentRuntime(
        config, definition, loop, sessions, models, tools,
        shared_budget=provider_assembly.shared_budget, _owned_providers=(owned,), knowledge=knowledge,
        service_usage=usage_binding,
    )


def _select_knowledge_binding(
    config: LocalRuntimeConfig,
    knowledge_bindings: Mapping[str, LocalKnowledgeBinding] | None,
) -> LocalKnowledgeBinding | None:
    knowledge = None
    if knowledge_bindings is not None:
        if not isinstance(knowledge_bindings, Mapping) or len(knowledge_bindings) > 64:
            raise LocalRuntimeConfigError("knowledge catalog must be a bounded mapping")
        for name, binding in knowledge_bindings.items():
            try:
                LocalKnowledgeConfig(name)
            except ValueError:
                raise LocalRuntimeConfigError("knowledge catalog name is invalid") from None
            if not isinstance(binding, LocalKnowledgeBinding):
                raise LocalRuntimeConfigError("knowledge catalog entries must be typed bindings")
        if config.knowledge is not None:
            knowledge = knowledge_bindings.get(config.knowledge.binding)
            if knowledge is None:
                raise LocalRuntimeConfigError("selected knowledge binding is absent from the authorized catalog")
    return knowledge


def _validate_runtime_bindings(
    config: LocalRuntimeConfig,
    knowledge: LocalKnowledgeBinding | None,
    stream_recovery: StreamRecoveryStrategy | NativeCursorRecovery | None,
    service_usage_bindings: Mapping[str, LocalServiceUsageBinding] | None,
) -> None:
    if (config.shared_budget is not None or config.service_usage is not None) and isinstance(stream_recovery, NativeCursorRecovery):
        raise LocalRuntimeConfigError("shared_budget/service_usage does not support native cursor recovery")
    if knowledge is not None and config.service_usage is not None and isinstance(service_usage_bindings, Mapping):
        selected_usage = service_usage_bindings.get(config.service_usage.binding)
        if (isinstance(selected_usage, LocalServiceUsageBinding) and selected_usage.retrieval_source_ref is not None
                and isinstance(knowledge.retriever, ObservedKnowledgeRetriever)):
            raise LocalRuntimeConfigError("retrieval is already observed; do not instrument the same call twice")


def _observe_knowledge_binding(
    knowledge: LocalKnowledgeBinding | None,
    usage_binding: LocalServiceUsageBinding | None,
) -> LocalKnowledgeBinding | None:
    if knowledge is not None and usage_binding is not None and usage_binding.retrieval_source_ref is not None:
        knowledge = replace(knowledge, retriever=ObservedKnowledgeRetriever(
            knowledge.retriever, usage_binding.ledger, usage_binding.operation_id,
            usage_binding.retrieval_source_ref, usage_binding.meter_version,
            usage_binding.retrieval_measurement, usage_binding.retrieval_token_scope,
        ))

    return knowledge


def _build_local_tools(
    config: LocalRuntimeConfig, tool_bindings: Mapping[str, ToolBinding] | None,
) -> ToolRegistry:
    tools = ToolRegistry()
    catalog = dict(tool_bindings or {})
    for name in config.tools.enabled:
        binding = catalog.get(name)
        if binding is None:
            raise LocalRuntimeConfigError(
                f"enabled tool {name!r} is unavailable in the authorized catalog"
            )
        if not isinstance(binding, ToolBinding) or binding.definition.name != name:
            raise LocalRuntimeConfigError(
                f"tool catalog entry {name!r} does not match its binding"
            )
        tools.register_binding(binding)
    return tools


def _build_local_pricing(
    config: LocalRuntimeConfig,
) -> tuple[PricingCatalog | None, CostBudget | None]:
    provider_name = config.provider.name or config.provider.template
    pricing_catalog = None
    cost_budget = None
    if config.pricing is not None:
        table = config.pricing.price_table()
        try:
            table.quote(provider_name, config.provider.model, TokenUsage())
        except PricingError as error:
            raise LocalRuntimeConfigError(
                "pricing needs a rate for the configured provider and model"
            ) from error
        pricing_catalog = PricingCatalog((table,))
        cost_budget = CostBudget(
            config.pricing.max_cost,
            config.pricing.version,
            config.pricing.currency,
            estimate_before_call=config.pricing.estimate_before_call,
            require_estimate=config.pricing.require_estimate,
            soft_limit_ratio=config.pricing.soft_limit_ratio,
        )
    return pricing_catalog, cost_budget


def _build_local_definition(
    config: LocalRuntimeConfig, cost_budget: CostBudget | None,
) -> AgentDefinition:
    agent = config.agent
    return AgentDefinition(
        agent.name,
        system_prompt=agent.system_prompt,
        model=config.provider.model,
        max_steps=agent.max_steps,
        max_tool_calls=agent.max_tool_calls,
        temperature=agent.temperature,
        max_output_tokens=agent.max_output_tokens,
        emit_text_deltas=agent.emit_text_deltas,
        emit_tool_call_deltas=agent.emit_tool_call_deltas,
        emit_output_blocks=agent.emit_output_blocks,
        emit_tool_results=agent.emit_tool_results,
        max_tool_result_event_bytes=agent.max_tool_result_event_bytes,
        extensions=agent.extensions,
        token_budget=TokenBudget(
            max_input_tokens=agent.max_input_tokens,
            max_output_tokens=agent.max_cumulative_output_tokens,
            max_total_tokens=agent.max_total_tokens,
            require_usage=agent.require_usage,
            require_estimate=agent.require_estimate,
            soft_limit_ratio=agent.soft_limit_ratio,
        ),
        cost_budget=cost_budget,
    )


def assemble_local_provider(
    config: LocalRuntimeConfig,
    *,
    templates: ProviderTemplateRegistry | None = None,
    environ: Mapping[str, str] | None = None,
    provider_options: Mapping[str, Any] | None = None,
    shared_budget_bindings: Mapping[str, LocalSharedBudgetBinding] | None = None,
    service_usage_bindings: Mapping[str, LocalServiceUsageBinding] | None = None,
) -> LocalProviderAssembly:
    """Build only the configured provider without registration or network access."""

    usage_binding = None
    if service_usage_bindings is not None:
        if not isinstance(service_usage_bindings, Mapping) or len(service_usage_bindings) > 64:
            raise LocalRuntimeConfigError("service usage catalog must be a bounded mapping")
        for name, candidate in service_usage_bindings.items():
            try:
                LocalServiceUsageConfig(name)
            except (TypeError, ValueError):
                raise LocalRuntimeConfigError("service usage binding name is invalid") from None
            if not isinstance(candidate, LocalServiceUsageBinding):
                raise LocalRuntimeConfigError("service usage catalog requires typed bindings")
    if config.service_usage is not None:
        usage_binding = None if service_usage_bindings is None else service_usage_bindings.get(config.service_usage.binding)
        if not isinstance(usage_binding, LocalServiceUsageBinding):
            raise LocalRuntimeConfigError("selected service usage binding is unavailable in the authorized catalog")
    binding = None
    if config.shared_budget is not None:
        selected = config.shared_budget.binding
        binding = None if shared_budget_bindings is None else shared_budget_bindings.get(selected)
        if not isinstance(binding, LocalSharedBudgetBinding):
            raise LocalRuntimeConfigError("selected shared budget binding is unavailable in the host catalog")
        if usage_binding is not None and isinstance(binding.controller, ObservedSharedBudgetController):
            raise LocalRuntimeConfigError("shared budget is already observed; do not instrument the same attempt twice")
    provider_config = config.provider
    environment = os.environ if environ is None else environ
    api_key = None
    if provider_config.api_key_env is not None:
        api_key = environment.get(provider_config.api_key_env)
        if not api_key:
            raise LocalRuntimeConfigError(
                f"credential environment variable {provider_config.api_key_env!r} is missing"
            )
    provider_name = provider_config.name or provider_config.template
    extra_options = dict(provider_options or {})
    reserved_options = {
        "name",
        "default_model",
        "timeout",
        "api_key",
        "base_url",
        "discover_models",
    }
    conflict = reserved_options & set(extra_options)
    if conflict:
        raise LocalRuntimeConfigError(
            "provider_options cannot override configured identity or credentials"
        )
    options: dict[str, Any] = {
        "name": provider_name,
        "default_model": provider_config.model,
        "timeout": provider_config.timeout,
        "api_key": api_key,
    }
    if provider_config.base_url is not None:
        options["base_url"] = provider_config.base_url
    if provider_config.template in _COMPATIBLE_TEMPLATES:
        options["discover_models"] = False
    options.update(extra_options)
    registry = templates or builtin_provider_template_registry()
    try:
        provider = registry.build(provider_config.template, **options)
    except (KeyError, TypeError, ValueError) as error:
        raise LocalRuntimeConfigError("provider template assembly failed") from error
    if usage_binding is not None and isinstance(provider, (ObservedModelProvider, SharedBudgetModelProvider)):
        raise LocalRuntimeConfigError("provider already has observation/budget wrapping; use raw provider with named bindings")
    wrapped = provider
    if binding is not None:
        controller = binding.controller
        if usage_binding is not None:
            controller = ObservedSharedBudgetController(
                controller, usage_binding.ledger, operation_id=usage_binding.operation_id,
                service="model", source_ref=usage_binding.model_source_ref, meter_version=usage_binding.meter_version,
            )
        wrapped = SharedBudgetModelProvider(provider, controller, binding.meter)
    elif usage_binding is not None:
        wrapped = ObservedModelProvider(provider, usage_binding)
    return LocalProviderAssembly(provider_name, wrapped, shared_budget=binding,
                                 service_usage=usage_binding, _owned_provider=provider)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LocalRuntimeConfigError(f"{name} must be an object")
    return value


def _known_keys(value: Mapping[str, Any], keys: set[str], name: str) -> None:
    unknown = set(value) - keys
    if unknown:
        raise LocalRuntimeConfigError(
            f"{name} contains unsupported fields: {', '.join(sorted(unknown))}"
        )


def _reject_secrets(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in _SENSITIVE_PARTS):
                raise LocalRuntimeConfigError(
                    f"{path} cannot contain credentials; use api_key_env"
                )
            _reject_secrets(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_secrets(item, f"{path}[{index}]")
