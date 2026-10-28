"""Optional default recipes compiled into the public application container.

This module describes components; it never starts a context or a model call.
The local runtime recipe retains the existing typed-message/session contract.
Applications with different protocols can supply their own AssemblyPlan instead.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from w_agent.application import (
    ApplicationHost, ApplicationOperation, ApplicationProject,
    AspectDefinition, AssemblyComponent, AssemblyPlan, BorrowedComponent,
    ComponentDefinition, ComponentRef, compile_assembly, replace_components,
)
from w_agent.agents import (
    AgentDefinition, AgentLoop, CharacterTokenEstimator, JsonlRunStore,
    ReactAgentLoop, ToolResultEventEncoder,
)
from w_agent.local_runtime import (
    LocalAgentRuntime, LocalProviderAssembly, LocalRuntimeConfig,
    LocalRuntimeConfigError, LocalSharedBudgetBinding,
    _build_local_definition, _build_local_pricing, _build_local_tools,
    _observe_knowledge_binding, _select_knowledge_binding,
    _validate_runtime_bindings, assemble_local_provider,
)
from w_agent.knowledge_runtime import LocalKnowledgeBinding
from w_agent.models import (
    InvocationPolicy, ModelExecutor, ModelRegistry, ModelRouter,
    NativeCursorRecovery, PricingCatalog, ProviderTemplateRegistry,
    StreamRecoveryStrategy, WeightedRoutingPolicy,
)
from w_agent.service_usage_runtime import LocalServiceUsageBinding
from w_agent.sessions import JsonSessionStore, SessionManager
from w_agent.tools import ToolBinding, ToolExecutor, ToolRegistry
from w_agent.workflows import (
    InlineWorkflowNodeInvoker, JsonlWorkflowStore, LocalWorkflowEngine,
    WorkflowNodeInvoker, WorkflowPauseSource,
)


class LocalRuntimeApplication(ApplicationHost):
    """Compatibility-shaped facade executing exclusively through the public host.

    Startup is explicit. Host-owned budget/usage metadata remains readable after
    shutdown; component resolution does not. The old synchronous assembly API
    remains separate for basic compatibility.
    """

    def __init__(self, plan: AssemblyPlan) -> None:
        super().__init__(ApplicationProject(plan, {
            name: ApplicationOperation("runtime", name)
            for name in ("run", "run_messages", "resume", "shared_budget_snapshot", "service_usage_summary")
        }, name="local-runtime"))
        self._runtime_metadata: LocalAgentRuntime | None = None

    async def start(self) -> LocalRuntimeApplication:
        await super().start()
        self._runtime_metadata = self.context.resolve("runtime")
        return self

    @property
    def shared_budget(self) -> LocalSharedBudgetBinding | None:
        if self._runtime_metadata is None:
            raise RuntimeError("local runtime application has not started")
        return self._runtime_metadata.shared_budget

    @property
    def service_usage(self) -> LocalServiceUsageBinding | None:
        if self._runtime_metadata is None:
            raise RuntimeError("local runtime application has not started")
        return self._runtime_metadata.service_usage

    async def run(self, *args: Any, **kwargs: Any):
        return await self.invoke("run", *args, **kwargs)

    async def run_messages(self, *args: Any, **kwargs: Any):
        return await self.invoke("run_messages", *args, **kwargs)

    async def resume(self, *args: Any, **kwargs: Any):
        return await self.invoke("resume", *args, **kwargs)

    async def shared_budget_snapshot(self):
        return await self.invoke("shared_budget_snapshot")

    async def service_usage_summary(self):
        return await self.invoke("service_usage_summary")

    async def aclose(self) -> None:
        await self.close()


def open_local_runtime(
    config: LocalRuntimeConfig, state_root: str | Path = ".wagent", **options: Any,
) -> LocalRuntimeApplication:
    """Build an unstarted, context-managed runtime; no I/O until enter."""
    return LocalRuntimeApplication(compile_local_runtime(config, state_root, **options))


def open_local_workflow(state_root: str | Path = ".wagent", **options: Any) -> ApplicationHost:
    """Build an unstarted Workflow host exposing start/resume operations."""
    return ApplicationProject(compile_local_workflow(state_root, **options), {
        "start": ApplicationOperation("workflow", "start"),
        "resume": ApplicationOperation("workflow", "resume"),
    }, name="local-workflow").open()


def compile_local_runtime(
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
    replacements: Iterable[AssemblyComponent] = (),
    aspects: Iterable[AspectDefinition] = (),
) -> AssemblyPlan:
    """Describe a replaceable ReAct recipe without creating providers or stores.

    Start with ``async with ApplicationContext(plan) as app`` and resolve
    ``runtime``. Host catalogs are borrowed, not closed. The ``provider``
    component is a LocalProviderAssembly owning only its constructed provider;
    replacing it with a BorrowedComponent keeps cleanup with the host.
    """
    if not isinstance(config, LocalRuntimeConfig):
        raise LocalRuntimeConfigError("local assembly needs a LocalRuntimeConfig")
    state = Path(state_root)
    provider_options = dict(provider_options or {})
    catalog = dict(tool_bindings or {})
    budget_catalog = None if shared_budget_bindings is None else dict(shared_budget_bindings)
    usage_catalog = None if service_usage_bindings is None else dict(service_usage_bindings)
    knowledge = _select_knowledge_binding(config, knowledge_bindings)
    _validate_runtime_bindings(config, knowledge, stream_recovery, usage_catalog)
    # Read credentials only when the provider factory runs. An explicitly
    # supplied environment is snapshotted; no environment values appear in repr.
    environment = None if environ is None else dict(environ)
    provider_name = config.provider.name or config.provider.template
    invocation = config.invocation
    components: list[AssemblyComponent] = [
        ComponentDefinition(
            "provider", assemble_local_provider,
            arguments={
                "config": config, "templates": templates, "environ": environment,
                "provider_options": provider_options,
                "shared_budget_bindings": budget_catalog,
                "service_usage_bindings": usage_catalog,
            }, dispose=LocalProviderAssembly.aclose, tags=frozenset({"model"}),
        ),
        ComponentDefinition("models", _models, {"provider": ComponentRef("provider")}),
        ComponentDefinition(
            "routing_policy", WeightedRoutingPolicy,
            arguments={"allow_providers": frozenset({provider_name})},
        ),
        ComponentDefinition("router", ModelRouter, {
            "models": ComponentRef("models"), "policy": ComponentRef("routing_policy"),
        }),
        ComponentDefinition("invocation_policy", InvocationPolicy, arguments={
            "max_attempts_per_route": invocation.max_attempts_per_route,
            "max_routes": invocation.max_routes, "timeout": invocation.timeout,
        }),
        ComponentDefinition("model_executor", ModelExecutor, {
            "models": ComponentRef("models"), "router": ComponentRef("router"),
            "policy": ComponentRef("invocation_policy"),
        }),
        ComponentDefinition("tools", _build_local_tools,
                            arguments={"config": config, "tool_bindings": catalog}),
        ComponentDefinition("tool_executor", ToolExecutor,
                            {"tools": ComponentRef("tools")}),
        ComponentDefinition("run_store", JsonlRunStore, arguments={"root": state}),
        ComponentDefinition("session_store", JsonSessionStore,
                            arguments={"root": state / "sessions"}),
        ComponentDefinition("sessions", SessionManager,
                            {"store": ComponentRef("session_store")}),
        ComponentDefinition("definition", _definition, arguments={"config": config}),
        BorrowedComponent("knowledge", knowledge),
    ]
    if config.pricing is None:
        components.append(BorrowedComponent("pricing", None))
    else:
        components.append(ComponentDefinition("pricing", _pricing, arguments={"config": config}))
    if config.agent.token_estimator == "character":
        components.append(ComponentDefinition(
            "token_estimator", CharacterTokenEstimator,
            arguments={"characters_per_token": config.agent.estimator_characters_per_token},
        ))
    else:
        components.append(BorrowedComponent("token_estimator", None))
    components.extend((
        ComponentDefinition("loop", ReactAgentLoop, {
            "models": ComponentRef("model_executor"), "tools": ComponentRef("tools"),
            "tool_executor": ComponentRef("tool_executor"), "store": ComponentRef("run_store"),
            "pricing": ComponentRef("pricing"), "token_estimator": ComponentRef("token_estimator"),
        }, arguments={"stream_recovery": stream_recovery,
                      "tool_result_event_encoder": tool_result_event_encoder},
            tags=frozenset({"harness"})),
        ComponentDefinition("runtime", _runtime, {
            name: ComponentRef(name)
            for name in ("provider", "definition", "loop", "sessions", "models", "tools", "knowledge")
        }, arguments={"config": config}, dispose=LocalAgentRuntime.aclose,
            tags=frozenset({"harness"})),
    ))
    return replace_components(compile_assembly(components, aspects=aspects), replacements)


def compile_local_workflow(
    state_root: str | Path = ".wagent",
    *,
    max_parallel_nodes: int = 1,
    node_invoker: WorkflowNodeInvoker | None = None,
    pause_source: WorkflowPauseSource | None = None,
    replacements: Iterable[AssemblyComponent] = (),
    aspects: Iterable[AspectDefinition] = (),
) -> AssemblyPlan:
    """Compile an independent workflow recipe, without any model or ReAct.

    Resolve ``workflow`` and call its public start/resume methods. Explicit
    invokers and pause sources remain borrowed; custom owned definitions can
    instead provide lifecycle hooks through replacements.
    """
    invoker: AssemblyComponent = (
        ComponentDefinition("node_invoker", InlineWorkflowNodeInvoker)
        if node_invoker is None else BorrowedComponent("node_invoker", node_invoker)
    )
    return replace_components(compile_assembly((
        ComponentDefinition("workflow_store", JsonlWorkflowStore,
                            arguments={"root": Path(state_root)}),
        invoker,
        BorrowedComponent("pause_source", pause_source),
        ComponentDefinition("workflow", LocalWorkflowEngine, {
            "store": ComponentRef("workflow_store"),
            "node_invoker": ComponentRef("node_invoker"),
            "pause_source": ComponentRef("pause_source"),
        }, arguments={"max_parallel_nodes": max_parallel_nodes},
            tags=frozenset({"harness", "workflow"})),
    ), aspects=aspects), replacements)


def _models(provider: LocalProviderAssembly) -> ModelRegistry:
    models = ModelRegistry()
    models.register(provider.name, provider.provider)
    return models


def _pricing(config: LocalRuntimeConfig) -> PricingCatalog | None:
    return _build_local_pricing(config)[0]


def _definition(config: LocalRuntimeConfig) -> AgentDefinition:
    return _build_local_definition(config, _build_local_pricing(config)[1])


def _runtime(
    config: LocalRuntimeConfig,
    provider: LocalProviderAssembly,
    definition: AgentDefinition,
    loop: AgentLoop,
    sessions: SessionManager,
    models: ModelRegistry,
    tools: ToolRegistry,
    knowledge: LocalKnowledgeBinding | None,
) -> LocalAgentRuntime:
    return LocalAgentRuntime(
        config, definition, loop, sessions, models, tools,
        shared_budget=provider.shared_budget,
        knowledge=_observe_knowledge_binding(knowledge, provider.service_usage),
        service_usage=provider.service_usage, _manage_providers=False,
    )
