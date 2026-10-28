"""M2 annotation execution and lifecycle equivalence, using in-memory hosts."""

import asyncio
from types import ModuleType
from typing import Annotated

import pytest

from w_agent import (
    AgentComponent, ApplicationContext, AssemblyDefinitionError, Autowired,
    Bean, BorrowedComponent, ComponentDefinition, ComponentRef, Configuration,
    PostConstruct, PreDestroy, Qualifier, ServiceComponent, ToolComponent, Value,
    compile_assembly, compile_configured, compile_decorated, scan_components,
)


async def test_python_decorator_and_configuration_have_equivalent_behavior():
    async def run(mode):
        events = []

        @ServiceComponent("store")
        class Store:
            @PostConstruct
            def initialize(self):
                events.append("store-start")

            @PreDestroy
            def close(self):
                events.append("store-close")

        @AgentComponent("harness", scope="run")
        class Harness:
            def __init__(self, store: Store, dialect: Annotated[str, Value("model.dialect", required=True)]):
                self.store, self.dialect = store, dialect

            @PostConstruct
            def initialize(self):
                events.append("harness-start")

            async def run(self, text):
                return self.dialect + ":" + text.upper()

            @PreDestroy
            async def close(self):
                events.append("harness-close")

        if mode == "python":
            plan = compile_assembly([
                ComponentDefinition("store", Store, initialize=Store.initialize, dispose=Store.close),
                ComponentDefinition("harness", Harness, {"store": ComponentRef("store")},
                                    {"dialect": "LOCAL"}, scope="run",
                                    initialize=Harness.initialize, dispose=Harness.close),
            ])
        elif mode == "decorator":
            plan = compile_decorated([Harness, Store], values={"model": {"dialect": "LOCAL"}})
        else:
            plan = compile_configured({"components": ["harness", "store"],
                                       "values": {"model": {"dialect": "LOCAL"}}},
                                      catalog={"store": Store, "harness": Harness})
        async with ApplicationContext(plan) as app:
            async with app.scope("run", "one") as scope:
                harness = scope.resolve("harness")
                assert harness.store is app.resolve("store")
                result = await harness.run("hello")
        return plan.startup_order, result, events

    results = [await run(mode) for mode in ("python", "decorator", "config")]
    assert results[0] == results[1] == results[2]
    assert results[0][2] == ["store-start", "harness-start", "harness-close", "store-close"]


async def test_fields_setters_qualifiers_and_values_are_injected_before_initialization():
    @ServiceComponent("store")
    class Store:
        pass

    @AgentComponent("harness")
    class Harness:
        store: Annotated[Store, Autowired()]
        alias: Store = Autowired("store")
        untyped = Autowired("store")
        count: int = Value("count", 3)

        @Autowired()
        @Qualifier("store")
        async def set_storage(self, store: Store):
            self.setter_store = store

        @Value("prefix", "ok")
        def set_prefix(self, value: str):
            self.prefix = value

        @PostConstruct
        def ready(self):
            assert self.alias is self.store is self.setter_store is self.untyped
            assert self.count == 3 and self.prefix == "ok"

    async with ApplicationContext(compile_decorated([Harness, Store])) as app:
        assert app.resolve("harness").store is app.resolve("store")


async def test_configuration_instance_and_async_factories_are_managed_once():
    events = []

    class Model:
        def __init__(self, dialect):
            self.dialect = dialect

        @PreDestroy
        def close(self):
            events.append("model-close")

    @Configuration("settings")
    class Settings:
        def __init__(self, dialect: str = Value("dialect", "CUSTOM")):
            self.dialect = dialect

        @PostConstruct
        def ready(self):
            events.append("config-start")

        @Bean(name="model")
        async def model(self) -> Model:
            events.append("model-create")
            return Model(self.dialect)

        @Bean(name="harness")
        def harness(self, model: Model):
            return [model]

        @PreDestroy
        def close(self):
            events.append("config-close")

    plan = compile_decorated([Settings])
    assert events == []
    async with ApplicationContext(plan) as app:
        assert app.resolve("harness")[0] is app.resolve("model")
        assert app.resolve("model").dialect == "CUSTOM"
    assert events == ["config-start", "model-create", "model-close", "config-close"]


async def test_injection_failure_is_owned_and_cleanup_continues_after_hook_failure():
    events = []

    @ServiceComponent("failure")
    class Failure:
        @Value("x", 1)
        def set_value(self, value: int):
            raise ValueError("injection failed")

        @PostConstruct
        def never(self):
            events.append("initialized")

        @PreDestroy(order=2)
        def first(self):
            events.append("first")
            raise RuntimeError("cleanup failed")

        @PreDestroy(order=1)
        def second(self):
            events.append("second")

    with pytest.raises(BaseExceptionGroup):
        await ApplicationContext(compile_decorated([Failure])).start()
    assert events == ["first", "second"]


async def test_cancelled_injection_that_suppresses_cancel_does_not_initialize():
    entered = asyncio.Event()
    events = []

    @ServiceComponent("cancelled")
    class Cancelled:
        @Value("x", 1)
        async def set_value(self, value: int):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass

        @PostConstruct
        def initialize(self):
            events.append("initialized")

        @PreDestroy
        async def close(self):
            events.append("closed")

    app = ApplicationContext(compile_decorated([Cancelled]))
    starting = asyncio.create_task(app.start())
    await asyncio.wait_for(entered.wait(), 2)
    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(starting, 2)
    assert events == ["closed"]


async def test_inherited_hooks_use_override_semantics_and_order():
    events = []

    class Parent:
        @PostConstruct(order=2)
        def inherited(self):
            events.append("second")

        @PostConstruct(order=0)
        def replaced(self):
            raise AssertionError("overridden")

        @PreDestroy
        def close(self):
            events.append("closed")

    @ServiceComponent
    class Child(Parent):
        def replaced(self):
            pass

        @PostConstruct(order=1)
        async def own(self):
            events.append("first")

    async with ApplicationContext(compile_decorated([Child])):
        assert events == ["first", "second"]
    assert events == ["first", "second", "closed"]


async def test_function_component_is_a_tool_not_an_eager_factory():
    @ToolComponent("normalize")
    def normalize(text):
        return text.upper()

    async with ApplicationContext(compile_decorated([normalize])) as app:
        assert app.resolve("normalize") is normalize
        assert app.resolve("normalize")("hi") == "HI"


def test_scanning_requires_loaded_modules_and_excludes_imported_and_inherited_markers():
    module = ModuleType("local_components")

    @ServiceComponent
    class Local:
        pass

    class Child(Local):
        pass

    @ServiceComponent
    class Imported:
        pass

    Local.__module__ = Child.__module__ = module.__name__
    module.Local, module.Alias, module.Child, module.Imported = Local, Local, Child, Imported
    assert scan_components(module) == (Local,)
    with pytest.raises(AssemblyDefinitionError):
        scan_components("untrusted.module")


def test_ambiguous_type_requires_qualifier():
    class Store:
        pass

    @AgentComponent("harness")
    class Harness:
        def __init__(self, store: Store):
            pass

    with pytest.raises(AssemblyDefinitionError, match="ambiguous"):
        compile_decorated([Harness, BorrowedComponent("a", Store()), BorrowedComponent("b", Store())])
    plan = compile_decorated([Harness, BorrowedComponent("a", Store()), BorrowedComponent("b", Store())],
                             dependencies={"harness": {"store": "b"}})
    assert plan.components[-1].dependencies["store"] == ComponentRef("b")


@pytest.mark.parametrize("mode", ["missing", "wrong_type", "cycle", "scope"])
def test_invalid_injections_fail_at_compilation(mode):
    @ServiceComponent("store", scope="run" if mode == "scope" else "application")
    class Store:
        pass

    @AgentComponent("harness")
    class Harness:
        def __init__(self, store: Annotated[Store, Qualifier("store")]):
            pass

    items = [Harness]
    if mode == "wrong_type":
        items.append(BorrowedComponent("store", object()))
    elif mode == "cycle":
        items.append(ComponentDefinition("store", Store, {"x": ComponentRef("harness")}))
    elif mode == "scope":
        items.append(Store)
    with pytest.raises(AssemblyDefinitionError):
        compile_decorated(items)


@pytest.mark.parametrize("values", [{}, {"count": True}, {"count": "secret"}])
def test_config_values_are_required_and_strict_without_value_leaks(values):
    @ServiceComponent
    class Service:
        def __init__(self, count: Annotated[int, Value("count", required=True)]):
            pass

    with pytest.raises(AssemblyDefinitionError) as error:
        compile_decorated([Service], values=values)
    assert "secret" not in str(error.value)


async def test_forward_annotated_types_are_resolved_without_eval():
    @ServiceComponent("store")
    class Store:
        pass

    @ServiceComponent("harness")
    class Harness:
        def __init__(self, store: "Annotated[Store, Qualifier('store')]",
                     count: "Annotated[int, Value('count', default=2)]"):
            self.store, self.count = store, count

    async with ApplicationContext(compile_decorated([Harness, Store], types={"Store": Store})) as app:
        assert app.resolve("harness").store is app.resolve("store")
        assert app.resolve("harness").count == 2


def test_annotation_calls_are_not_evaluated():
    events = []

    @ServiceComponent
    class Dangerous:
        def __init__(self, value: "execute()"):
            pass

    with pytest.raises(AssemblyDefinitionError):
        compile_decorated([Dangerous], types={"execute": lambda: events.append("executed")})
    assert events == []


async def test_factory_explicit_hooks_and_unannotated_product():
    events = []

    @Bean(name="plain", initialize=lambda obj: events.append("init"),
          dispose=lambda obj: events.append("dispose"))
    def plain():
        return {"plain": True}

    async with ApplicationContext(compile_decorated([plain])) as app:
        assert app.resolve("plain") == {"plain": True}
    assert events == ["init", "dispose"]


async def test_wrong_factory_return_type_gets_disposed_after_ownership():
    events = []

    @Bean(provides=list, dispose=lambda obj: events.append(obj))
    def wrong():
        return {"wrong": True}

    with pytest.raises(AssemblyDefinitionError, match="return type"):
        await ApplicationContext(compile_decorated([wrong])).start()
    assert events == [{"wrong": True}]


@pytest.mark.parametrize("document", [
    {"components": ["not-allowed"]}, {"components": ["item", "item"]},
    {"components": "item"}, {"components": ["item"], "import": "evil"},
    {"components": ["item"], "arguments": {"missing": {}}},
    {"components": ["item"], "arguments": {"item": {"unknown": 1}}},
    {"components": ["item"], "arguments": {"item": {"count": 1}},
     "dependencies": {"item": {"count": "item"}}},
])
def test_configuration_rejects_unknown_selection_and_overrides(document):
    @ServiceComponent("item")
    class Item:
        def __init__(self, count: int = 0):
            pass

    with pytest.raises(AssemblyDefinitionError):
        compile_configured(document, catalog={"item": Item})


async def test_configured_constructor_overrides_and_nested_values():
    @ServiceComponent("item")
    class Item:
        def __init__(self, count: int = 0, labels: list[str] = Value("labels", [])):
            self.count, self.labels = count, labels

    plan = compile_configured({"components": ["item"], "arguments": {"item": {"count": 4}},
                               "values": {"labels": ["a", "b"]}}, catalog={"item": Item})
    async with ApplicationContext(plan) as app:
        assert app.resolve("item").count == 4
        assert app.resolve("item").labels == ["a", "b"]


def test_duplicate_names_and_configuration_factory_scope_capture_rejected():
    @Configuration("config", scope="run")
    class Config:
        @Bean(name="product")
        def product(self):
            return object()

    with pytest.raises(AssemblyDefinitionError, match="shorter-lived"):
        compile_decorated([Config])
    with pytest.raises(AssemblyDefinitionError, match="duplicate"):
        compile_decorated([BorrowedComponent("x", object()), BorrowedComponent("x", object())])


async def test_constructor_qualifier_and_untyped_name_fallback():
    @ServiceComponent("consumer")
    class Consumer:
        @Qualifier("store")
        def __init__(self, value):
            self.value = value

    store = object()
    async with ApplicationContext(compile_decorated([Consumer, BorrowedComponent("store", store)])) as app:
        assert app.resolve("consumer").value is store


def test_static_factory_method_is_rejected_instead_of_silently_ignored():
    @Configuration
    class Config:
        @staticmethod
        @Bean
        def value():
            return object()

    with pytest.raises(AssemblyDefinitionError, match="instance methods"):
        compile_decorated([Config])


async def test_complete_annotated_harness_example_executes():
    from examples.annotated_harness import run_demo
    assert await run_demo() == ("LOCAL:HELLO", ("LOCAL:HELLO",), True)


async def test_decorated_plan_can_be_loaded_by_application_plugin():
    from w_agent import ApplicationPlugin, CapabilityDeclaration, CapabilityExport, PluginManager, ScopePath

    @ServiceComponent("service")
    class Service:
        pass

    manager = PluginManager()
    module = ApplicationPlugin(name="decorated", version="1",
                               components=compile_decorated([Service]).components,
                               exports=[CapabilityExport("service", CapabilityDeclaration("service"))])
    await manager.load(module)
    assert manager.registry.resolve("service", ScopePath.application()) is module.application.resolve("service")
    await manager.close()


async def test_post_construct_failure_and_cancelled_cleanup_run_all_disposers():
    events = []

    @ServiceComponent("failing")
    class Failing:
        @PostConstruct
        async def initialize(self):
            raise ValueError("init")

        @PreDestroy(order=2)
        async def first(self):
            events.append("first")
            raise asyncio.CancelledError()

        @PreDestroy(order=1)
        def second(self):
            events.append("second")

    with pytest.raises(BaseExceptionGroup):
        await ApplicationContext(compile_decorated([Failing])).start()
    assert events == ["first", "second"]


def test_invalid_lifecycle_signature_fails_without_creating_any_objects():
    events = []

    @ServiceComponent
    class Invalid:
        def __init__(self):
            events.append("created")

        @PreDestroy
        def close(self, required):
            pass

    with pytest.raises(AssemblyDefinitionError, match="lifecycle signature"):
        compile_decorated([Invalid])
    assert events == []


def test_plain_business_field_annotation_is_not_evaluated_or_injected():
    @ServiceComponent
    class Service:
        payload: "VendorType[load_dynamic_schema()]"

    assert compile_decorated([Service]).startup_order == ("service",)


@pytest.mark.parametrize("mode", ["python", "decorator", "configuration"])
async def test_three_entries_preserve_ownership_during_failed_initialization(mode):
    events, external = [], object()

    @ServiceComponent("service")
    class Service:
        def __init__(self, external):
            self.external = external

        @PostConstruct
        def initialize(self):
            assert self.external is external
            raise ValueError("initialization failed")

        @PreDestroy
        def close(self):
            events.append("disposed")

    borrowed = BorrowedComponent("external", external)
    if mode == "python":
        plan = compile_assembly([
            borrowed, ComponentDefinition("service", Service, {"external": ComponentRef("external")},
                                          initialize=Service.initialize, dispose=Service.close),
        ])
    elif mode == "decorator":
        plan = compile_decorated([Service, borrowed])
    else:
        plan = compile_configured({"components": ["service", "external"]},
                                  catalog={"service": Service, "external": borrowed})
    app = ApplicationContext(plan)
    with pytest.raises(ValueError, match="initialization failed"):
        await app.start()
    await app.close()
    assert events == ["disposed"]


def test_public_decorator_api_is_in_package_exports():
    import w_agent
    for name in ("Bean", "Configuration", "Value", "scan_components",
                 "compile_decorated", "compile_configured"):
        assert name in w_agent.__all__
        assert getattr(w_agent, name) is not None


async def test_bare_typing_containers_and_nullable_configuration_bindings():
    import typing

    @ServiceComponent("configurable")
    class Configurable:
        def __init__(self, items: typing.List = Value("items", [1]),
                     index: typing.Dict = Value("index", {"key": 1}),
                     missing: None = Value("missing")):
            self.items, self.index, self.missing = items, index, missing

    async with ApplicationContext(compile_decorated([Configurable])) as app:
        component = app.resolve("configurable")
        assert component.items == [1] and component.index == {"key": 1}
        assert component.missing is None
