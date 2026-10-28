"""M1 configuration preflight executes before factories in any scope."""

import pytest

from w_agent import (
    ApplicationContext, AssemblyDefinitionError, ComponentDefinition,
    ConfigurationField, ConfigurationSchema, compile_assembly,
)


async def test_schema_accepts_explicit_arguments_without_coercion():
    schema = ConfigurationSchema({
        "count": ConfigurationField(int),
        "label": ConfigurationField((str, type(None)), required=False),
    })
    async with ApplicationContext(compile_assembly([
        ComponentDefinition("value", lambda count: [count], arguments={"count": 3},
                            validate_arguments=schema),
    ])) as app:
        assert app.resolve("value") == [3]


@pytest.mark.parametrize("arguments", [{}, {"count": True}, {"count": "secret"},
                                       {"count": 1, "other": "secret"}])
async def test_invalid_child_configuration_prevents_all_creation(arguments):
    events = []
    app = ApplicationContext(compile_assembly([
        ComponentDefinition("first", lambda: events.append("created")),
        ComponentDefinition("child", lambda **kw: kw, arguments=arguments, scope="run",
                            validate_arguments=ConfigurationSchema({
                                "count": ConfigurationField(int),
                            })),
    ]))
    with pytest.raises(AssemblyDefinitionError, match="child") as error:
        await app.start()
    assert "secret" not in str(error.value)
    assert events == []


async def test_custom_validator_can_validate_vendor_specific_nested_parameters():
    seen = []

    def validate(arguments):
        assert arguments["vendor"]["dialect"] == "custom"
        seen.append("validated")

    def factory(vendor):
        seen.append("created")
        return [vendor]

    async with ApplicationContext(compile_assembly([
        ComponentDefinition("model", factory, arguments={"vendor": {"dialect": "custom"}},
                            validate_arguments=validate),
    ])):
        assert seen == ["validated", "created"]


async def test_validator_errors_redact_secret_and_cannot_modify_argument_mapping():
    def validate(arguments):
        with pytest.raises(TypeError):
            arguments["secret"] = "changed"
        raise ValueError(arguments["secret"])

    app = ApplicationContext(compile_assembly([
        ComponentDefinition("secure", lambda secret: [secret], arguments={"secret": "token-123"},
                            validate_arguments=validate),
    ]))
    with pytest.raises(AssemblyDefinitionError) as error:
        await app.start()
    assert "token-123" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("as_wrapper", [False, True])
async def test_async_validators_are_rejected_without_running(as_wrapper):
    events = []

    async def validate(arguments):
        events.append("ran")

    validator = (lambda arguments: validate(arguments)) if as_wrapper else validate
    app = ApplicationContext(compile_assembly([
        ComponentDefinition("value", object, validate_arguments=validator),
    ]))
    with pytest.raises(AssemblyDefinitionError):
        await app.start()
    assert events == []


def test_schema_copies_fields_and_extra_is_opt_in():
    fields = {"count": ConfigurationField(int)}
    schema = ConfigurationSchema(fields, allow_extra=True)
    fields.clear()
    schema({"count": 1, "custom": object()})
    with pytest.raises(AssemblyDefinitionError):
        schema({})


@pytest.mark.parametrize("types", [(), "int", (int, "str")])
def test_invalid_schema_types_rejected(types):
    with pytest.raises(AssemblyDefinitionError):
        ConfigurationField(types)
