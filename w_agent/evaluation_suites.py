"""Versioned, editable local evaluation suites for the starter agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from .evaluation import EvaluationCase, EvaluationDataset


@dataclass(frozen=True, slots=True)
class EvaluationSuite:
    """Named benchmark inputs and declarative scorer recommendations."""

    key: str
    version: str
    description: str
    agent_template: str
    cases: tuple[EvaluationCase, ...]
    scorers: tuple[str, ...] = ("case-contract",)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        identities = (self.key, self.version, self.description, self.agent_template)
        if any(not isinstance(value, str) or not value.strip() for value in identities):
            raise ValueError("evaluation suite identity must not be empty")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("evaluation suite metadata must be a mapping")
        dataset = EvaluationDataset(
            tuple(self.cases),
            name=self.key,
            version=self.version,
            scorers=tuple(self.scorers),
        )
        object.__setattr__(self, "cases", dataset.cases)
        object.__setattr__(self, "scorers", dataset.scorers)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def reference(self) -> str:
        return f"builtin:{self.key}@{self.version}"

    def dataset(self) -> EvaluationDataset:
        return EvaluationDataset(
            self.cases,
            name=self.key,
            version=self.version,
            scorers=self.scorers,
        )


class EvaluationSuiteRegistry:
    """Small replaceable registry; resolving a suite never executes code."""

    def __init__(self, suites: tuple[EvaluationSuite, ...] = ()) -> None:
        self._suites: dict[tuple[str, str], EvaluationSuite] = {}
        self._versions: dict[str, list[str]] = {}
        for suite in suites:
            self.register(suite)

    def register(self, suite: EvaluationSuite) -> None:
        if not isinstance(suite, EvaluationSuite):
            raise TypeError("evaluation suite registry accepts EvaluationSuite values")
        identity = (suite.key, suite.version)
        if identity in self._suites:
            raise ValueError("evaluation suite version is already registered")
        self._suites[identity] = suite
        self._versions.setdefault(suite.key, []).append(suite.version)

    def list(self) -> tuple[EvaluationSuite, ...]:
        return tuple(self._suites.values())

    def resolve(self, key: str, version: str | None = None) -> EvaluationSuite:
        versions = self._versions.get(key)
        if not versions:
            raise ValueError(f"evaluation suite {key!r} is unavailable")
        selected = version if version is not None else versions[-1]
        try:
            return self._suites[(key, selected)]
        except KeyError as error:
            raise ValueError(
                f"evaluation suite {key!r} version {selected!r} is unavailable"
            ) from error

    def resolve_reference(self, reference: str) -> EvaluationSuite:
        value = reference.strip()
        if not value or value.count("@") > 1:
            raise ValueError("built-in evaluation suite reference is invalid")
        key, separator, version = value.partition("@")
        if not key or (separator and not version):
            raise ValueError("built-in evaluation suite reference is invalid")
        return self.resolve(key, version if separator else None)


CUSTOMER_SUPPORT_EVALUATION_SUITE = EvaluationSuite(
    key="customer-support",
    version="1.0.0",
    description=(
        "Starter checks for identifier handling, evidence lookup, and approval-gated "
        "ticket writes."
    ),
    agent_template="customer-support",
    cases=(
        EvaluationCase(
            "missing-identifier",
            (
                "I need the status of my support ticket, but I have not supplied "
                "a ticket or customer identifier. Explain what you need next."
            ),
            metadata={
                "contract": {
                    "forbidden_tools": [
                        "customer_lookup",
                        "ticket_lookup",
                        "ticket_update",
                    ],
                    "allowed_stop_reasons": ["completed"],
                    "expected_contains_any": [
                        "ticket id",
                        "customer id",
                        "identifier",
                    ],
                    "max_tool_calls": 0,
                }
            },
        ),
        EvaluationCase(
            "policy-evidence",
            (
                "Use the registered knowledge source to answer: what is the refund "
                "policy? Do not invent a policy when evidence is unavailable."
            ),
            metadata={
                "contract": {
                    "required_tools": ["knowledge_search"],
                    "allowed_stop_reasons": ["completed"],
                    "min_tool_calls": 1,
                }
            },
        ),
        EvaluationCase(
            "ticket-write-approval",
            (
                "Update ticket T-100 to record that the customer requested a refund. "
                "Use the registered ticket write tool and do not treat this prompt as "
                "authorization."
            ),
            metadata={
                "contract": {
                    "required_tools": ["ticket_update"],
                    "allowed_stop_reasons": ["needs-approval"],
                    "min_tool_calls": 1,
                }
            },
            accepted_stop_reasons=("needs-approval",),
        ),
    ),
    metadata={"requires_tools": True, "language": "en"},
)


CODING_EVALUATION_SUITE = EvaluationSuite(
    key="coding",
    version="1.0.0",
    description=(
        "Starter checks for inspect-first analysis, approval-gated edits, and "
        "sandboxed verification."
    ),
    agent_template="coding",
    cases=(
        EvaluationCase(
            "inspect-only",
            (
                "Inspect the project entry point and summarize how it starts. This is "
                "analysis only: do not edit files or execute commands."
            ),
            metadata={
                "contract": {
                    "required_any_tools": ["workspace_read", "workspace_search"],
                    "forbidden_tools": ["workspace_patch", "sandbox_command"],
                    "allowed_stop_reasons": ["completed"],
                    "min_tool_calls": 1,
                }
            },
        ),
        EvaluationCase(
            "scoped-edit-approval",
            (
                "Make one scoped documentation correction after inspecting the target. "
                "Use the registered workspace tools and do not assume write approval."
            ),
            metadata={
                "contract": {
                    "required_any_tools": ["workspace_read", "workspace_search"],
                    "required_tools": ["workspace_patch"],
                    "allowed_stop_reasons": ["needs-approval"],
                    "min_tool_calls": 2,
                }
            },
            accepted_stop_reasons=("needs-approval",),
        ),
        EvaluationCase(
            "sandbox-verification",
            (
                "Inspect the project and run the smallest relevant verification using "
                "the registered sandbox command tool. Do not request host execution."
            ),
            metadata={
                "contract": {
                    "required_any_tools": ["workspace_read", "workspace_search"],
                    "required_tools": ["sandbox_command"],
                    "allowed_stop_reasons": ["completed"],
                    "min_tool_calls": 2,
                }
            },
        ),
    ),
    metadata={"requires_tools": True, "language": "en"},
)


def builtin_evaluation_suite_registry() -> EvaluationSuiteRegistry:
    """Return a fresh registry so callers may freely extend their copy."""

    return EvaluationSuiteRegistry(
        (CUSTOMER_SUPPORT_EVALUATION_SUITE, CODING_EVALUATION_SUITE)
    )


def evaluation_suite_to_dict(suite: EvaluationSuite) -> dict[str, Any]:
    """Export one suite as a strict JSON-dataset-compatible mapping."""

    return {
        "schema_version": 1,
        "name": suite.key,
        "version": suite.version,
        "scorers": list(suite.scorers),
        "cases": [
            {
                "name": case.name,
                "prompt": case.prompt,
                "expected_output": case.expected_output,
                "metadata": _plain_value(case.metadata),
                "accepted_stop_reasons": list(case.accepted_stop_reasons),
            }
            for case in suite.cases
        ],
    }


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    return value
