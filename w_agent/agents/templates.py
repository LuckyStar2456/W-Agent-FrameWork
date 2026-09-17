"""Editable first-party agent templates with no privileged runtime behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from .types import AgentDefinition


@dataclass(frozen=True, slots=True)
class AgentTemplate:
    """Named defaults that build an ordinary, fully replaceable definition."""

    key: str
    description: str
    recommended_tools: tuple[str, ...]
    defaults: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.key or not self.key.strip():
            raise ValueError("agent template key must not be empty")
        object.__setattr__(self, "recommended_tools", tuple(self.recommended_tools))
        object.__setattr__(self, "defaults", MappingProxyType(dict(self.defaults)))

    def build(self, **overrides: Any) -> AgentDefinition:
        """Build a normal AgentDefinition, replacing any template default."""

        values = dict(self.defaults)
        values.update(overrides)
        values.setdefault("name", self.key)
        return AgentDefinition(**values)


CUSTOMER_SUPPORT_AGENT_TEMPLATE = AgentTemplate(
    "customer-support",
    "Evidence-aware customer support and optional RAG orchestration.",
    (
        "knowledge_search",
        "customer_lookup",
        "ticket_lookup",
        "ticket_update",
    ),
    {
        "system_prompt": (
            "You are a customer-support agent. Separate verified facts from "
            "assumptions, ask for missing identifiers, and never invent policy "
            "or account data. Use registered read tools for evidence. Treat "
            "writes and external actions as requiring runtime authorization; "
            "a prompt never grants permission. Give a concise answer and name "
            "the next action when the request cannot be completed."
        ),
        "max_steps": 8,
        "max_tool_calls": 12,
    },
)


CODING_AGENT_TEMPLATE = AgentTemplate(
    "coding",
    "Repository coding work with explicit verification and sandbox boundaries.",
    (
        "workspace_read",
        "workspace_search",
        "workspace_patch",
        "sandbox_command",
    ),
    {
        "system_prompt": (
            "You are a coding agent. Inspect the current project before changing "
            "it, keep edits scoped, preserve unrelated work, and verify behavior "
            "with the smallest relevant checks before broader tests. Execute code "
            "only through registered tools. Prefer an isolated sandbox; local "
            "execution is allowed only when the application supplies explicit "
            "runtime authorization. Never treat model text as authorization."
        ),
        "max_steps": 16,
        "max_tool_calls": 32,
    },
)


def customer_support_agent(**overrides: Any) -> AgentDefinition:
    """Build the editable customer-support/RAG starter definition."""

    return CUSTOMER_SUPPORT_AGENT_TEMPLATE.build(**overrides)


def coding_agent(**overrides: Any) -> AgentDefinition:
    """Build the editable coding-agent starter definition."""

    return CODING_AGENT_TEMPLATE.build(**overrides)
