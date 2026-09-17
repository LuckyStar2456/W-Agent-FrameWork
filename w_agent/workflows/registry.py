"""Scoped workflow definitions on the shared W-Agent registry."""

from __future__ import annotations

from w_agent.kernel import Contribution, Registration, Registry, ScopePath

from .types import WorkflowDefinition


WORKFLOW_DEFINITION_CAPABILITY = "workflow.definition"


class WorkflowRegistry:
    """Register replaceable, versioned workflow definitions by scope."""

    def __init__(self, registry: Registry | None = None) -> None:
        self.registry = registry or Registry()

    def register(
        self,
        definition: WorkflowDefinition,
        *,
        version: str | None = None,
        scope: ScopePath | None = None,
        owner: str | None = None,
    ) -> Registration:
        """Register one definition through the shared capability registry."""

        resolved_version = version or definition.version
        if resolved_version != definition.version:
            raise ValueError("workflow registry version must match definition version")
        return self.registry.register(
            Contribution(
                capability=WORKFLOW_DEFINITION_CAPABILITY,
                provider=definition,
                name=definition.name,
                version=resolved_version,
                scope=scope or ScopePath.application(),
                owner=owner,
                metadata={"kind": definition.kind.value},
            )
        )

    def definition(
        self,
        name: str,
        *,
        scope: ScopePath | None = None,
        version: str | None = None,
    ) -> WorkflowDefinition:
        """Resolve the highest matching visible definition."""

        return self.registry.resolve(
            WORKFLOW_DEFINITION_CAPABILITY,
            scope or ScopePath.application(),
            name=name,
            version=version,
        )

    def definitions(
        self,
        *,
        scope: ScopePath | None = None,
    ) -> tuple[WorkflowDefinition, ...]:
        """Return the highest visible version of each workflow name."""

        resolved_scope = scope or ScopePath.application()
        contributions = self.registry.list(
            WORKFLOW_DEFINITION_CAPABILITY,
            resolved_scope,
        )
        names = sorted({contribution.name for contribution in contributions})
        return tuple(self.definition(name, scope=resolved_scope) for name in names)
