"""Composable policies for tool permission and approval decisions."""

from __future__ import annotations

from collections.abc import Iterable

from .types import (
    ToolBinding,
    ToolCall,
    ToolExecutionContext,
    ToolPolicy,
    ToolPolicyAction,
    ToolPolicyDecision,
    ToolSideEffect,
)


class PermissionPolicy:
    """Deny execution when application-granted permissions are missing."""

    async def evaluate(
        self,
        binding: ToolBinding,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolPolicyDecision:
        del call
        missing = binding.required_permissions - context.permissions
        if missing:
            return ToolPolicyDecision(
                ToolPolicyAction.DENY,
                f"missing permissions: {', '.join(sorted(missing))}",
                type(self).__name__,
            )
        return ToolPolicyDecision(
            ToolPolicyAction.ALLOW,
            "required permissions are present",
            type(self).__name__,
        )


class SideEffectApprovalPolicy:
    """Require per-call approval for mutating or external effects."""

    def __init__(
        self,
        require_for: Iterable[ToolSideEffect] = (
            ToolSideEffect.WRITE,
            ToolSideEffect.DESTRUCTIVE,
            ToolSideEffect.EXTERNAL,
        ),
    ) -> None:
        self.require_for = frozenset(require_for)

    async def evaluate(
        self,
        binding: ToolBinding,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolPolicyDecision:
        if binding.side_effect not in self.require_for:
            action = ToolPolicyAction.ALLOW
            reason = "effect class does not require approval"
        elif call.id in context.approved_call_ids:
            action = ToolPolicyAction.ALLOW
            reason = "call id was explicitly approved"
        else:
            action = ToolPolicyAction.REQUIRE_APPROVAL
            reason = f"{binding.side_effect.value} effect requires approval"
        return ToolPolicyDecision(action, reason, type(self).__name__)


class ToolPolicyPipeline:
    """Evaluate ordered policies; the first non-allow decision stops execution."""

    def __init__(self, policies: Iterable[ToolPolicy] = ()) -> None:
        self.policies = tuple(policies)

    async def evaluate(
        self,
        binding: ToolBinding,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolPolicyDecision:
        for policy in self.policies:
            decision = await policy.evaluate(binding, call, context)
            if decision.action != ToolPolicyAction.ALLOW:
                return decision
        return ToolPolicyDecision(
            ToolPolicyAction.ALLOW,
            "all tool policies allowed execution",
            type(self).__name__,
        )


def default_tool_policy() -> ToolPolicyPipeline:
    return ToolPolicyPipeline((PermissionPolicy(), SideEffectApprovalPolicy()))
