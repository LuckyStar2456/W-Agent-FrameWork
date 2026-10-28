"""Legacy singleton borrowing preserves the original owner and identity."""

import pytest

from w_agent import (
    ApplicationContext, BeanDefinition, BeanFactory, BeanNotFoundError,
    ComponentDefinition, ComponentRef, PreDestroy, Scope,
    borrow_legacy_singletons, compile_assembly,
)


async def test_host_initializes_and_closes_legacy_singletons_after_application():
    events = []

    class Store:
        def initialize(self):
            events.append("legacy-start")

        @PreDestroy
        def close(self):
            events.append("legacy-close")

    factory = BeanFactory()
    factory.register_bean_definition("legacy-store", BeanDefinition(
        "legacy-store", Store, init_method="initialize",
    ))
    await factory.initialize_singletons()
    borrowed = borrow_legacy_singletons(factory, {"store": "legacy-store"})
    async with ApplicationContext(compile_assembly([
        *borrowed,
        ComponentDefinition("harness", lambda store: [store], {"store": ComponentRef("store")},
                            dispose=lambda value: events.append("harness-close")),
    ])) as app:
        assert app.resolve("harness")[0] is await factory.get_bean("legacy-store")
    assert events == ["legacy-start", "harness-close"]
    await factory.destroy_singletons()
    assert events == ["legacy-start", "harness-close", "legacy-close"]


@pytest.mark.parametrize("scope", [Scope.SINGLETON, Scope.PROTOTYPE])
def test_borrowing_never_creates_missing_legacy_objects(scope):
    factory = BeanFactory()
    factory.register_bean_definition("pending", BeanDefinition("pending", object, scope=scope))
    with pytest.raises(BeanNotFoundError):
        borrow_legacy_singletons(factory, {"dependency": "pending"})


async def test_application_failure_does_not_destroy_host_owned_legacy_object():
    factory = BeanFactory()
    value = []
    factory.register_bean("value", value)

    def fail(value):
        raise ValueError("failed")

    app = ApplicationContext(compile_assembly([
        *borrow_legacy_singletons(factory, {"borrowed": "value"}),
        ComponentDefinition("failure", fail, {"value": ComponentRef("borrowed")}),
    ]))
    with pytest.raises(ValueError):
        await app.start()
    assert factory.existing_singleton("value") is value


def test_existing_singleton_excludes_early_references():
    factory = BeanFactory()
    factory._early_singleton_objects["early"] = object()
    with pytest.raises(BeanNotFoundError):
        factory.existing_singleton("early")
