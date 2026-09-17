"""Safe local configuration and assembly for one practical agent runtime."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from w_agent.agents import (
    AgentDefinition,
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
    ModelRegistry,
    ModelRouter,
    ProviderTemplateRegistry,
    WeightedRoutingPolicy,
    builtin_provider_template_registry,
)
from w_agent.sessions import JsonSessionStore, SessionManager, SessionRecord
from w_agent.tools import ToolBinding, ToolExecutionContext, ToolExecutor, ToolRegistry

_COMPATIBLE_TEMPLATES = frozenset({"deepseek", "glm", "qwen", "turbo"})
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
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise LocalRuntimeConfigError("agent name must not be empty")
        if self.max_steps <= 0 or self.max_tool_calls < 0:
            raise LocalRuntimeConfigError("agent step and tool limits are invalid")
        if self.temperature is not None and self.temperature < 0:
            raise LocalRuntimeConfigError("agent temperature must not be negative")
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
        _reject_secrets(self.extensions, "agent.extensions")
        object.__setattr__(self, "extensions", MappingProxyType(dict(self.extensions)))


@dataclass(frozen=True, slots=True)
class LocalToolConfig:
    """Names selected from a host-supplied catalog, never authority grants."""

    enabled: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = tuple(self.enabled)
        if any(not isinstance(item, str) or not item.strip() for item in values):
            raise LocalRuntimeConfigError("enabled tool names must be non-empty strings")
        if len(set(values)) != len(values):
            raise LocalRuntimeConfigError("enabled tool names must be unique")
        object.__setattr__(self, "enabled", values)


@dataclass(frozen=True, slots=True)
class LocalRuntimeConfig:
    provider: LocalProviderConfig
    agent: LocalAgentConfig = field(default_factory=LocalAgentConfig)
    invocation: LocalInvocationConfig = field(default_factory=LocalInvocationConfig)
    tools: LocalToolConfig = field(default_factory=LocalToolConfig)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise LocalRuntimeConfigError("unsupported local runtime schema version")
        if self.tools.enabled and self.agent.max_tool_calls == 0:
            raise LocalRuntimeConfigError(
                "enabled tools require agent.max_tool_calls to be positive"
            )


@dataclass(frozen=True, slots=True)
class LocalRuntimeRun:
    session: SessionRecord
    result: RunResult


@dataclass(slots=True)
class LocalAgentRuntime:
    """One assembled local runtime whose replaceable parts remain public."""

    config: LocalRuntimeConfig
    definition: AgentDefinition
    loop: ReactAgentLoop
    sessions: SessionManager
    models: ModelRegistry
    tools: ToolRegistry

    async def run(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        session_title: str | None = None,
        permissions: frozenset[str] = frozenset(),
        approved_call_ids: frozenset[str] = frozenset(),
        cancellation: CancellationToken | None = None,
    ) -> LocalRuntimeRun:
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
    ) -> LocalRuntimeRun:
        """Resume one persisted approval checkpoint with explicit authority."""

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
        raise LocalRuntimeConfigError("local runtime config is not valid JSON") from error
    if not isinstance(data, Mapping):
        raise LocalRuntimeConfigError("local runtime config must be an object")
    return local_runtime_config_from_mapping(data)


def local_runtime_config_from_mapping(value: Mapping[str, Any]) -> LocalRuntimeConfig:
    """Validate parsed configuration and reject hidden or secret-bearing fields."""

    _known_keys(
        value,
        {"schema_version", "provider", "agent", "invocation", "tools"},
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
            "max_input_tokens",
            "max_cumulative_output_tokens",
            "max_total_tokens",
            "require_usage",
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
            schema_version=int(value.get("schema_version", 1)),
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, LocalRuntimeConfigError):
            raise
        raise LocalRuntimeConfigError("local runtime config has invalid values") from error


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
    loop = ReactAgentLoop(
        executor,
        tools,
        tool_executor,
        store=JsonlRunStore(state),
    )
    agent = config.agent
    definition = AgentDefinition(
        agent.name,
        system_prompt=agent.system_prompt,
        model=provider_config.model,
        max_steps=agent.max_steps,
        max_tool_calls=agent.max_tool_calls,
        temperature=agent.temperature,
        max_output_tokens=agent.max_output_tokens,
        extensions=agent.extensions,
        token_budget=TokenBudget(
            max_input_tokens=agent.max_input_tokens,
            max_output_tokens=agent.max_cumulative_output_tokens,
            max_total_tokens=agent.max_total_tokens,
            require_usage=agent.require_usage,
        ),
    )
    sessions = SessionManager(JsonSessionStore(state / "sessions"))
    return LocalAgentRuntime(config, definition, loop, sessions, models, tools)


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
