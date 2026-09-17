import pytest

from w_agent import (
    CODING_AGENT_TEMPLATE,
    CUSTOMER_SUPPORT_AGENT_TEMPLATE,
    TokenBudget,
    coding_agent,
    customer_support_agent,
)


def test_customer_support_template_is_an_editable_definition():
    definition = customer_support_agent(
        name="my-support",
        model="provider/model",
        token_budget=TokenBudget(max_total_tokens=10_000),
    )

    assert definition.name == "my-support"
    assert definition.model == "provider/model"
    assert definition.max_steps == 8
    assert definition.token_budget == TokenBudget(max_total_tokens=10_000)
    assert "knowledge_search" in CUSTOMER_SUPPORT_AGENT_TEMPLATE.recommended_tools


def test_coding_template_does_not_grant_tools_or_local_execution():
    definition = coding_agent(max_steps=3, system_prompt="custom")

    assert definition.name == "coding"
    assert definition.max_steps == 3
    assert definition.system_prompt == "custom"
    assert definition.extensions == {}
    assert "sandbox_command" in CODING_AGENT_TEMPLATE.recommended_tools


def test_template_rejects_unknown_definition_fields():
    with pytest.raises(TypeError):
        coding_agent(unknown_option=True)
