"""Safe local configuration and assembly for one practical agent runtime."""

from __future__ import annotations

import json
import os
import re
import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from w_agent.agents import (
    AgentDefinition,
    CharacterTokenEstimator,
    CostBudget,
    JsonlRunStore,
    ReactAgentLoop,
    RunResult,
    TokenBudget,
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
    ProviderTemplateRegistry,
    PriceTable,
    PricingCatalog,
    PricingError,
    TokenUsage,
    WeightedRoutingPolicy,
    builtin_provider_template_registry,
)
from w_agent.sessions import (
    JsonSessionStore,
    RunEventCallback,
    SessionManager,
    SessionRecord,
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

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise LocalRuntimeConfigError("agent name must not be empty")
        if self.max_steps <= 0 or self.max_tool_calls < 0:
            raise LocalRuntimeConfigError("agent step and tool limits are invalid")
        if self.temperature is not None and self.temperature < 0:
            raise LocalRuntimeConfigError("agent temperature must not be negative")
        if not isinstance(self.emit_text_deltas, bool):
            raise LocalRuntimeConfigError("emit_text_deltas must be a boolean")
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
class LocalRuntimeConfig:
    provider: LocalProviderConfig
    agent: LocalAgentConfig = field(default_factory=LocalAgentConfig)
    invocation: LocalInvocationConfig = field(default_factory=LocalInvocationConfig)
    tools: LocalToolConfig = field(default_factory=LocalToolConfig)
    pricing: LocalPricingConfig | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise LocalRuntimeConfigError("unsupported local runtime schema version")
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


@dataclass(frozen=True, slots=True)
class LocalProviderAssembly:
    """One configured provider built without registering it or performing I/O."""

    name: str
    provider: ModelProvider

    async def __aenter__(self) -> "LocalProviderAssembly":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        close = getattr(self.provider, "aclose", None)
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
    loop: ReactAgentLoop
    sessions: SessionManager
    models: ModelRegistry
    tools: ToolRegistry
    _closed: bool = field(default=False, init=False, repr=False)

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
        seen: set[int] = set()
        for _, provider in self.models.providers():
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
    ) -> LocalRuntimeRun:
        self._ensure_open()
        if not prompt:
            raise ValueError("agent prompt must not be empty")
        if session_id is None:
            session = await self.sessions.create(session_title or prompt[:80])
        else:
            session = await self.sessions.get(session_id)
        result = await self.sessions.run_agent(
            self.loop,
            self.definition,
            session.session_id,
            (ModelMessage.text(MessageRole.USER, prompt),),
            cancellation=cancellation,
            tool_context=ToolExecutionContext(
                permissions=permissions,
                approved_call_ids=approved_call_ids,
                cancellation=cancellation,
            ),
            event_callback=event_callback,
        )
        return LocalRuntimeRun(await self.sessions.get(session.session_id), result)

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
        return LocalRuntimeRun(await self.sessions.get(session_id), result)


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
        {"schema_version", "provider", "agent", "invocation", "tools", "pricing"},
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
    pricing_raw = value.get("pricing")
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
) -> LocalAgentRuntime:
    """Assemble public model, routing, tool, agent, run, and session components."""

    provider_assembly = assemble_local_provider(
        config,
        templates=templates,
        environ=environ,
        provider_options=provider_options,
    )
    provider_config = config.provider
    provider_name = provider_assembly.name
    provider = provider_assembly.provider

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
    tool_executor = ToolExecutor(tools)
    state = Path(state_root)
    pricing_catalog = None
    cost_budget = None
    if config.pricing is not None:
        table = config.pricing.price_table()
        try:
            table.quote(provider_name, provider_config.model, TokenUsage())
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
    )
    definition = AgentDefinition(
        agent.name,
        system_prompt=agent.system_prompt,
        model=provider_config.model,
        max_steps=agent.max_steps,
        max_tool_calls=agent.max_tool_calls,
        temperature=agent.temperature,
        max_output_tokens=agent.max_output_tokens,
        emit_text_deltas=agent.emit_text_deltas,
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
    sessions = SessionManager(JsonSessionStore(state / "sessions"))
    return LocalAgentRuntime(config, definition, loop, sessions, models, tools)


def assemble_local_provider(
    config: LocalRuntimeConfig,
    *,
    templates: ProviderTemplateRegistry | None = None,
    environ: Mapping[str, str] | None = None,
    provider_options: Mapping[str, Any] | None = None,
) -> LocalProviderAssembly:
    """Build only the configured provider without registration or network access."""

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
    return LocalProviderAssembly(provider_name, provider)


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
