"""M4 recipe contracts. Run only after the entire M4 stage is ready."""

import pytest

from w_agent import (
    ApplicationContext, AssemblyDefinitionError, AspectDefinition,
    BlockEnd, BlockStart, BorrowedComponent, ComponentDefinition, ComponentRef,
    DagWorkflowDefinition, FinishEvent, FinishReason, LocalProviderAssembly,
    MethodPointcut, ModelCapability, ModelDescriptor, ProviderTemplate,
    ProviderTemplateRegistry, TextContent, TextDelta, TokenUsage, UsageEvent,
    WorkflowContext, WorkflowNode, compile_assembly, compile_local_runtime,
    compile_local_workflow, local_runtime_config_from_mapping, replace_components,
    open_local_runtime, open_local_workflow, RunResult, StopReason,
)


class OfflineProvider:
    def __init__(self, name="offline", model="test"):
        self.name, self.model = name, model
        self.closed = 0

    async def list_models(self):
        return (ModelDescriptor(self.name, self.model, frozenset({
            ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT,
        })),)

    async def resolve(self, model):
        return (await self.list_models())[0]

    async def stream(self, request, *, cancellation=None):
        yield BlockStart(0, "text")
        yield TextDelta(0, "managed")
        yield BlockEnd(0, TextContent("managed"))
        yield UsageEvent(TokenUsage(3, 2))
        yield FinishEvent(FinishReason.STOP)

    async def aclose(self):
        self.closed += 1


def config(**agent):
    return local_runtime_config_from_mapping({
        "provider": {"template": "offline", "model": "test"}, "agent": agent,
    })


def templates(created):
    def build(**options):
        provider = OfflineProvider(options["name"], options["default_model"])
        created.append(provider)
        return provider
    return ProviderTemplateRegistry((ProviderTemplate("offline", "Offline", "test", None, build),))


def test_planning_has_no_factories_files_or_credentials_read(tmp_path):
    created = []
    selected = local_runtime_config_from_mapping({
        "provider": {"template": "offline", "model": "test", "api_key_env": "MISSING"},
    })
    plan = compile_local_runtime(selected, tmp_path / "absent", templates=templates(created), environ={})
    assert not created
    assert not (tmp_path / "absent").exists()
    assert {"runtime", "router", "loop", "run_store", "sessions"} <= set(plan.startup_order)


@pytest.mark.asyncio
async def test_default_plan_runs_and_only_provider_component_closes(tmp_path):
    created = []
    plan = compile_local_runtime(config(), tmp_path, templates=templates(created))
    async with ApplicationContext(plan) as app:
        runtime = app.resolve("runtime")
        assert runtime.loop is app.resolve("loop")
        assert runtime.loop.models is app.resolve("model_executor")
        assert runtime.sessions.store is app.resolve("session_store")
        run = await runtime.run("hello")
        assert run.result.output == "managed"
        assert run.result.usage == TokenUsage(3, 2)
        await runtime.aclose()
        assert created[0].closed == 0
    assert created[0].closed == 1


@pytest.mark.asyncio
async def test_borrowed_provider_is_not_closed(tmp_path):
    provider = OfflineProvider()
    borrowed = LocalProviderAssembly("offline", provider)
    plan = compile_local_runtime(config(), tmp_path, replacements=(BorrowedComponent("provider", borrowed),))
    async with ApplicationContext(plan) as app:
        assert (await app.resolve("runtime").run("hi")).result.output == "managed"
    assert provider.closed == 0
    await borrowed.aclose()
    assert provider.closed == 1


@pytest.mark.asyncio
async def test_loop_router_and_executor_can_be_replaced_independently(tmp_path):
    provider = OfflineProvider()
    router, executor, loop = object(), object(), object()
    plan = compile_local_runtime(config(), tmp_path, replacements=(
        BorrowedComponent("provider", LocalProviderAssembly("offline", provider)),
        BorrowedComponent("router", router),
        BorrowedComponent("model_executor", executor),
        BorrowedComponent("loop", loop),
    ))
    async with ApplicationContext(plan) as app:
        assert app.resolve("runtime").loop is loop
        assert app.resolve("router") is router
        assert app.resolve("model_executor") is executor
    assert provider.closed == 0


@pytest.mark.asyncio
async def test_default_plan_rolls_back_provider_after_late_startup_failure(tmp_path):
    created = []

    def fail(models):
        raise ValueError("loop-start-failed")

    plan = compile_local_runtime(config(), tmp_path, templates=templates(created), replacements=(
        ComponentDefinition("loop", fail, {"models": ComponentRef("models")}),
    ))
    with pytest.raises(ValueError, match="loop-start-failed"):
        async with ApplicationContext(plan):
            pass
    assert len(created) == 1 and created[0].closed == 1


@pytest.mark.asyncio
async def test_preflight_failure_never_creates_provider(tmp_path):
    created = []
    plan = compile_local_runtime(config(), tmp_path, templates=templates(created), replacements=(
        ComponentDefinition("loop", lambda required: object()),
    ))
    with pytest.raises(AssemblyDefinitionError, match="signature"):
        async with ApplicationContext(plan):
            pass
    assert created == []


@pytest.mark.asyncio
async def test_borrowed_extra_model_registry_entries_are_not_closed(tmp_path):
    created, extra = [], OfflineProvider("external")
    plan = compile_local_runtime(config(), tmp_path, templates=templates(created))
    async with ApplicationContext(plan) as app:
        app.resolve("models").register("external", extra)
    assert created[0].closed == 1
    assert extra.closed == 0


@pytest.mark.asyncio
async def test_default_components_participate_in_aop(tmp_path):
    seen = []
    aspect = AspectDefinition("trace", MethodPointcut(component="runtime", methods=("run",)),
                              before=lambda invocation: seen.append(invocation.method))
    plan = compile_local_runtime(config(), tmp_path, templates=templates([]), aspects=(aspect,))
    async with ApplicationContext(plan) as app:
        await app.resolve("runtime").run("hello")
    assert seen == ["run"]


@pytest.mark.asyncio
async def test_character_estimator_is_a_replaceable_component(tmp_path):
    plan = compile_local_runtime(config(token_estimator="character"), tmp_path, templates=templates([]))
    async with ApplicationContext(plan) as app:
        assert app.resolve("loop").token_estimator is app.resolve("token_estimator")


@pytest.mark.asyncio
async def test_workflow_recipe_needs_no_model_and_borrows_invoker(tmp_path):
    class Invoker:
        def __init__(self):
            self.calls = 0
            self.closed = 0

        async def invoke(self, node, context):
            self.calls += 1
            return node.handler(context)

        async def aclose(self):
            self.closed += 1

    invoker = Invoker()
    plan = compile_local_workflow(tmp_path, node_invoker=invoker)
    assert "provider" not in plan.startup_order and "loop" not in plan.startup_order
    definition = DagWorkflowDefinition("custom", (WorkflowNode("value", lambda ctx: 42),))
    async with ApplicationContext(plan) as app:
        result = await app.resolve("workflow").start(definition, WorkflowContext("workflow-test"))
        assert result.outputs == {"value": 42}
        assert app.resolve("workflow").store is app.resolve("workflow_store")
    assert invoker.calls == 1 and invoker.closed == 0


def test_replacements_preserve_aspects_scope_order_and_revalidate():
    aspect = AspectDefinition("trace", before=lambda invocation: None)
    plan = compile_assembly((ComponentDefinition("service", object),), aspects=(aspect,))
    replacement = BorrowedComponent("service", object())
    result = replace_components(plan, (replacement,))
    assert result.components == (replacement,)
    assert result.scope_order == plan.scope_order and result.aspects == plan.aspects
    with pytest.raises(AssemblyDefinitionError, match="unknown replacement"):
        replace_components(plan, (BorrowedComponent("typo", object()),))
    with pytest.raises(AssemblyDefinitionError, match="duplicate replacement"):
        replace_components(plan, (replacement, replacement))
    with pytest.raises(AssemblyDefinitionError):
        replace_components(plan, (ComponentDefinition("service", object,
                                   {"missing": ComponentRef("missing")}),))


def test_recipe_rejects_short_lived_loop_capture(tmp_path):
    with pytest.raises(AssemblyDefinitionError):
        compile_local_runtime(config(), tmp_path, replacements=(
            ComponentDefinition("loop", object, scope="run"),
        ))


@pytest.mark.asyncio
async def test_public_runtime_host_executes_replacement_loop_without_react(tmp_path):
    class CustomLoop:
        async def run(self, definition, context):
            return RunResult(context.run_id, StopReason.COMPLETED, "custom-loop",
                             context.messages, (), 1, 0)

    created = []
    async with open_local_runtime(config(), tmp_path, templates=templates(created), replacements=(
        ComponentDefinition("loop", CustomLoop),
    )) as runtime:
        run = await runtime.run("hello")
        assert run.result.output == "custom-loop"
        assert runtime.context.resolve("runtime").loop is runtime.context.resolve("loop")
    assert created[0].closed == 1
    assert runtime.shared_budget is None and runtime.service_usage is None


@pytest.mark.asyncio
async def test_public_workflow_host_executes_default_recipe(tmp_path):
    definition = DagWorkflowDefinition("managed", (WorkflowNode("value", lambda ctx: "ok"),))
    async with open_local_workflow(tmp_path) as host:
        result = await host.invoke("start", definition, WorkflowContext("managed-workflow"))
    assert result.outputs == {"value": "ok"}


@pytest.mark.asyncio
async def test_replacement_router_and_executor_receive_real_default_loop_calls(tmp_path):
    from w_agent import ModelExecutor, ModelRouter

    calls = []

    class CustomRouter:
        def __init__(self, models, policy):
            self.delegate = ModelRouter(models, policy)

        async def route(self, request, **kwargs):
            calls.append("route")
            return await self.delegate.route(request, **kwargs)

    class CustomExecutor:
        def __init__(self, models, router, policy):
            self.router, self.policy = router, policy
            self.delegate = ModelExecutor(models, router, policy)

        async def invoke(self, request, **kwargs):
            calls.append("invoke")
            return await self.delegate.invoke(request, **kwargs)

        def stream(self, request, **kwargs):
            calls.append("stream")
            return self.delegate.stream(request, **kwargs)

    created = []
    async with open_local_runtime(config(), tmp_path, templates=templates(created), replacements=(
        ComponentDefinition("router", CustomRouter, {
            "models": ComponentRef("models"), "policy": ComponentRef("routing_policy"),
        }),
        ComponentDefinition("model_executor", CustomExecutor, {
            "models": ComponentRef("models"), "router": ComponentRef("router"),
            "policy": ComponentRef("invocation_policy"),
        }),
    )) as runtime:
        run = await runtime.run("hello")
        assert run.result.output == "managed"
        assert "route" in calls
        assert any(method in calls for method in ("invoke", "stream"))
    assert created[0].closed == 1
