"""Contracts for assembly planning; no model, subprocess or network calls."""

from dataclasses import FrozenInstanceError

import pytest

from w_agent.application import (
    AssemblyDefinitionError,
    AssemblyPlan,
    BorrowedComponent,
    ComponentDefinition,
    ComponentRef,
    compile_assembly,
)


def test_planning_does_not_execute_factories_or_hooks():
    def forbidden(*args, **kwargs):
        raise AssertionError("planning executed user code")

    plan = compile_assembly([
        ComponentDefinition(
            "loop", forbidden, {"store": ComponentRef("store")},
            initialize=forbidden, dispose=forbidden,
        ),
        ComponentDefinition("store", forbidden),
    ])
    assert plan.startup_order == ("store", "loop")


def test_borrowed_instance_identity_and_private_values_are_preserved():
    resource = object()
    private = object()
    plan = compile_assembly([
        BorrowedComponent("host-store", resource),
        ComponentDefinition("loop", object, arguments={"vendor_parameter": private}),
    ])
    assert plan.components[0].instance is resource
    assert plan.components[1].arguments["vendor_parameter"] is private
    assert repr(resource) not in repr(plan)
    assert repr(private) not in repr(plan)


def test_definition_copies_mappings_and_rejects_mutation():
    dependencies = {"store": ComponentRef("store")}
    arguments = {"temperature": 0.5}
    definition = ComponentDefinition("loop", object, dependencies, arguments)
    dependencies.clear()
    arguments["temperature"] = 1.0
    assert definition.dependencies == {"store": ComponentRef("store")}
    assert definition.arguments["temperature"] == 0.5
    with pytest.raises(TypeError):
        definition.arguments["temperature"] = 2.0
    with pytest.raises(FrozenInstanceError):
        definition.name = "other"


@pytest.mark.parametrize("components, message", [
    ([BorrowedComponent("same", object()), BorrowedComponent("same", object())], "duplicate"),
    ([ComponentDefinition("loop", object, {"store": ComponentRef("missing")})], "missing"),
    ([ComponentDefinition("loop", object, {"self": ComponentRef("loop")})], "cyclic"),
    ([ComponentDefinition("a", object, {"b": ComponentRef("b")}),
      ComponentDefinition("b", object, {"a": ComponentRef("a")})], "cyclic"),
    ([BorrowedComponent("short", object(), scope="run"),
      ComponentDefinition("long", object, {"short": ComponentRef("short")})], "shorter-lived"),
    ([BorrowedComponent("unknown", object(), scope="custom")], "undeclared"),
])
def test_invalid_assemblies_fail_before_execution(components, message):
    with pytest.raises(AssemblyDefinitionError, match=message):
        compile_assembly(components)


def test_short_scope_can_depend_on_long_scope_and_reuse_reference():
    plan = compile_assembly([
        ComponentDefinition("run-loop", object, {
            "store": ComponentRef("store"), "other": ComponentRef("store"),
        }, scope="run"),
        BorrowedComponent("store", object()),
    ])
    assert plan.startup_order == ("store", "run-loop")


def test_custom_scope_order_is_explicit():
    plan = compile_assembly([
        BorrowedComponent("custom", object(), scope="conversation"),
    ], scope_order=("application", "conversation", "run"))
    assert plan.scope_order == ("application", "conversation", "run")
    with pytest.raises(AssemblyDefinitionError, match="reversed"):
        compile_assembly([], scope_order=("application", "run", "session"))
    with pytest.raises(AssemblyDefinitionError, match="duplicate"):
        compile_assembly([], scope_order=("application", "run", "run"))


def test_arguments_cannot_shadow_dependency_injection():
    with pytest.raises(AssemblyDefinitionError, match="both"):
        ComponentDefinition(
            "loop", object, {"store": ComponentRef("store")}, {"store": "secret"},
        )


def test_invalid_parameters_and_references_are_rejected():
    with pytest.raises(AssemblyDefinitionError, match="identifiers"):
        ComponentDefinition("loop", object, arguments={"invalid-key": "secret"})
    with pytest.raises(AssemblyDefinitionError, match="ComponentRef"):
        ComponentDefinition("loop", object, dependencies={"store": "store"})


def test_direct_plan_construction_cannot_bypass_dependency_order():
    with pytest.raises(AssemblyDefinitionError, match="dependency-first"):
        AssemblyPlan((
            ComponentDefinition("loop", object, {"store": ComponentRef("store")}),
            BorrowedComponent("store", object()),
        ))


def test_large_dependency_chain_uses_no_recursive_walk():
    components = [BorrowedComponent("root", object())]
    previous = "root"
    for index in range(1500):
        name = f"component-{index}"
        components.append(ComponentDefinition(name, object, {"parent": ComponentRef(previous)}))
        previous = name
    plan = compile_assembly(reversed(components))
    assert plan.startup_order[0] == "root"
    assert plan.startup_order[-1] == previous
