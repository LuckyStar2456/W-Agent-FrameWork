"""Small local evaluation runner over public agent results."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from types import MappingProxyType
from typing import Any, Protocol

from w_agent.agents import RunEventType, RunResult, StopReason
from w_agent.models import CancellationToken, ModelCost, PricingError, TokenUsage

_MAX_DATASET_BYTES = 8 * 1024 * 1024
_MAX_DATASET_CASES = 10_000


class EvaluationDatasetError(ValueError):
    """A local evaluation dataset is unreadable or violates its schema."""


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    name: str
    prompt: str
    expected_output: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    accepted_stop_reasons: tuple[str, ...] = (StopReason.COMPLETED.value,)

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.prompt:
            raise ValueError("evaluation case name and prompt are required")
        reasons = tuple(self.accepted_stop_reasons)
        known_reasons = {item.value for item in StopReason}
        if (
            not reasons
            or any(not isinstance(item, str) or item not in known_reasons for item in reasons)
            or len(set(reasons)) != len(reasons)
        ):
            raise ValueError("evaluation case accepted stop reasons are invalid")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "accepted_stop_reasons", reasons)


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    """Versioned cases plus scorer recommendations, never execution authority."""

    cases: tuple[EvaluationCase, ...]
    name: str | None = None
    version: str | None = None
    scorers: tuple[str, ...] = ("exact-text",)

    def __post_init__(self) -> None:
        cases = tuple(self.cases)
        raw_scorers = tuple(self.scorers)
        if not all(isinstance(case, EvaluationCase) for case in cases):
            raise ValueError("evaluation dataset cases are invalid")
        if not all(isinstance(item, str) for item in raw_scorers):
            raise ValueError("evaluation dataset scorers must be strings")
        if self.name is not None and not isinstance(self.name, str):
            raise ValueError("evaluation dataset name must be a string or null")
        if self.version is not None and not isinstance(self.version, str):
            raise ValueError("evaluation dataset version must be a string or null")
        scorers = tuple(item.strip().lower() for item in raw_scorers)
        if not cases:
            raise ValueError("evaluation dataset needs at least one case")
        if len(cases) > _MAX_DATASET_CASES:
            raise ValueError("evaluation dataset has too many cases")
        names = tuple(case.name for case in cases)
        if len(set(names)) != len(names):
            raise ValueError("evaluation case names must be unique")
        if not scorers or any(not item for item in scorers):
            raise ValueError("evaluation dataset needs scorer recommendations")
        if len(set(scorers)) != len(scorers):
            raise ValueError("evaluation dataset scorers must be unique")
        if (self.name is None) != (self.version is None):
            raise ValueError("evaluation dataset name/version must be paired")
        if self.name is not None and (not self.name.strip() or not self.version.strip()):
            raise ValueError("evaluation dataset name/version must not be empty")
        object.__setattr__(self, "cases", cases)
        object.__setattr__(self, "scorers", scorers)


def load_evaluation_dataset(path: str | Path) -> EvaluationDataset:
    """Load a bounded strict JSON or registered built-in dataset."""

    source_text = str(path)
    if source_text.startswith("builtin:"):
        from .evaluation_suites import builtin_evaluation_suite_registry

        reference = source_text.removeprefix("builtin:")
        try:
            suite = builtin_evaluation_suite_registry().resolve_reference(reference)
        except ValueError as exc:
            raise EvaluationDatasetError(
                "built-in evaluation suite is unavailable"
            ) from exc
        return suite.dataset()

    source = Path(path)
    try:
        if source.stat().st_size > _MAX_DATASET_BYTES:
            raise EvaluationDatasetError("evaluation dataset exceeds the size limit")
        data = json.loads(source.read_text(encoding="utf-8"))
    except EvaluationDatasetError:
        raise
    except OSError as exc:
        raise EvaluationDatasetError("evaluation dataset cannot be read") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationDatasetError("evaluation dataset is not valid JSON") from exc
    if not isinstance(data, Mapping):
        raise EvaluationDatasetError("evaluation dataset must be an object")
    unknown = set(data) - {"schema_version", "name", "version", "scorers", "cases"}
    if unknown:
        raise EvaluationDatasetError("evaluation dataset has unsupported fields")
    if data.get("schema_version", 1) != 1:
        raise EvaluationDatasetError("unsupported evaluation dataset schema version")
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvaluationDatasetError("evaluation dataset needs a non-empty cases list")
    if len(raw_cases) > _MAX_DATASET_CASES:
        raise EvaluationDatasetError("evaluation dataset has too many cases")
    dataset_name = data.get("name")
    dataset_version = data.get("version")
    raw_scorers = data.get("scorers", ["exact-text"])
    if dataset_name is not None and not isinstance(dataset_name, str):
        raise EvaluationDatasetError("evaluation dataset name must be a string or null")
    if dataset_version is not None and not isinstance(dataset_version, str):
        raise EvaluationDatasetError(
            "evaluation dataset version must be a string or null"
        )
    if not isinstance(raw_scorers, list) or not all(
        isinstance(item, str) for item in raw_scorers
    ):
        raise EvaluationDatasetError("evaluation dataset scorers must be strings")
    cases: list[EvaluationCase] = []
    names: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping):
            raise EvaluationDatasetError("evaluation case must be an object")
        unknown = set(raw_case) - {
            "name",
            "prompt",
            "expected_output",
            "metadata",
            "accepted_stop_reasons",
        }
        if unknown:
            raise EvaluationDatasetError("evaluation case has unsupported fields")
        name = raw_case.get("name")
        prompt = raw_case.get("prompt")
        expected = raw_case.get("expected_output")
        metadata = raw_case.get("metadata", {})
        accepted_stop_reasons = raw_case.get(
            "accepted_stop_reasons",
            [StopReason.COMPLETED.value],
        )
        if not isinstance(name, str) or not isinstance(prompt, str):
            raise EvaluationDatasetError("evaluation case name/prompt must be strings")
        if expected is not None and not isinstance(expected, str):
            raise EvaluationDatasetError(
                "evaluation case expected_output must be a string or null"
            )
        if not isinstance(metadata, Mapping):
            raise EvaluationDatasetError("evaluation case metadata must be an object")
        if not isinstance(accepted_stop_reasons, list) or not all(
            isinstance(item, str) for item in accepted_stop_reasons
        ):
            raise EvaluationDatasetError(
                "evaluation case accepted_stop_reasons must be strings"
            )
        if name in names:
            raise EvaluationDatasetError("evaluation case names must be unique")
        try:
            case = EvaluationCase(
                name,
                prompt,
                expected,
                metadata,
                tuple(accepted_stop_reasons),
            )
        except (TypeError, ValueError) as exc:
            raise EvaluationDatasetError("evaluation case is invalid") from exc
        names.add(name)
        cases.append(case)
    try:
        return EvaluationDataset(
            tuple(cases),
            name=dataset_name,
            version=dataset_version,
            scorers=tuple(raw_scorers),
        )
    except ValueError as exc:
        raise EvaluationDatasetError("evaluation dataset is invalid") from exc


def load_evaluation_cases(path: str | Path) -> tuple[EvaluationCase, ...]:
    """Compatibility helper returning only cases from an evaluation dataset."""

    return load_evaluation_dataset(path).cases


@dataclass(frozen=True, slots=True)
class EvaluationScore:
    name: str
    value: float
    threshold: float = 1.0

    def __post_init__(self) -> None:
        if not self.name.strip() or not 0 <= self.value <= 1:
            raise ValueError("evaluation score name/value is invalid")
        if not 0 <= self.threshold <= 1:
            raise ValueError("evaluation score threshold is invalid")

    @property
    def passed(self) -> bool:
        return self.value >= self.threshold


class EvaluationScorer(Protocol):
    def score(self, case: EvaluationCase, result: RunResult) -> EvaluationScore: ...


@dataclass(frozen=True, slots=True)
class ExactTextScorer:
    name: str = "exact-text"
    case_sensitive: bool = True

    def score(self, case: EvaluationCase, result: RunResult) -> EvaluationScore:
        if case.expected_output is None:
            return EvaluationScore(self.name, 0)
        actual = result.output.strip()
        expected = case.expected_output.strip()
        if not self.case_sensitive:
            actual, expected = actual.casefold(), expected.casefold()
        return EvaluationScore(self.name, float(actual == expected))


@dataclass(frozen=True, slots=True)
class ContainsTextScorer:
    name: str = "contains-text"
    case_sensitive: bool = True

    def score(self, case: EvaluationCase, result: RunResult) -> EvaluationScore:
        if case.expected_output is None:
            return EvaluationScore(self.name, 0)
        actual = result.output
        expected = case.expected_output
        if not self.case_sensitive:
            actual, expected = actual.casefold(), expected.casefold()
        return EvaluationScore(self.name, float(expected in actual))


@dataclass(frozen=True, slots=True)
class CaseContractScorer:
    """Evaluate declarative text, tool, and stop-reason rules from metadata."""

    name: str = "case-contract"
    case_sensitive: bool = False

    def score(self, case: EvaluationCase, result: RunResult) -> EvaluationScore:
        contract = case.metadata.get("contract")
        if not isinstance(contract, Mapping):
            return EvaluationScore(self.name, 0)
        allowed_fields = {
            "required_tools",
            "required_any_tools",
            "forbidden_tools",
            "allowed_stop_reasons",
            "expected_contains_all",
            "expected_contains_any",
            "min_tool_calls",
            "max_tool_calls",
        }
        if set(contract) - allowed_fields:
            return EvaluationScore(self.name, 0)
        try:
            required = _contract_strings(contract, "required_tools")
            required_any = _contract_strings(contract, "required_any_tools")
            forbidden = _contract_strings(contract, "forbidden_tools")
            allowed_reasons = _contract_strings(contract, "allowed_stop_reasons")
            contains_all = _contract_strings(contract, "expected_contains_all")
            contains_any = _contract_strings(contract, "expected_contains_any")
            minimum = _contract_count(contract, "min_tool_calls")
            maximum = _contract_count(contract, "max_tool_calls")
        except ValueError:
            return EvaluationScore(self.name, 0)
        if minimum is not None and maximum is not None and minimum > maximum:
            return EvaluationScore(self.name, 0)
        requested = {
            str(event.data["name"])
            for event in result.events
            if event.type is RunEventType.TOOL_REQUESTED
            and isinstance(event.data.get("name"), str)
        }
        output = result.output if self.case_sensitive else result.output.casefold()
        normalize = (lambda value: value) if self.case_sensitive else str.casefold
        checks: list[bool] = []
        if required:
            checks.append(set(required).issubset(requested))
        if required_any:
            checks.append(bool(set(required_any) & requested))
        if forbidden:
            checks.append(not bool(set(forbidden) & requested))
        if allowed_reasons:
            checks.append(result.stop_reason.value in allowed_reasons)
        if contains_all:
            checks.append(all(normalize(item) in output for item in contains_all))
        if contains_any:
            checks.append(any(normalize(item) in output for item in contains_any))
        if minimum is not None:
            checks.append(result.tool_calls >= minimum)
        if maximum is not None:
            checks.append(result.tool_calls <= maximum)
        return EvaluationScore(self.name, float(bool(checks) and all(checks)))


@dataclass(frozen=True, slots=True)
class EvaluationCaseResult:
    name: str
    passed: bool
    output: str
    stop_reason: str | None
    latency_ms: float
    usage: TokenUsage
    usage_complete: bool
    steps: int
    tool_calls: int
    tool_successes: int
    tool_failures: int
    scores: tuple[EvaluationScore, ...]
    error_type: str | None = None
    cost: ModelCost | None = None
    cost_complete: bool = False


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    cases: tuple[EvaluationCaseResult, ...]

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(case.passed for case in self.cases)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def usage(self) -> TokenUsage:
        return TokenUsage(
            sum(case.usage.input_tokens for case in self.cases),
            sum(case.usage.output_tokens for case in self.cases),
            sum(case.usage.cached_input_tokens for case in self.cases),
        )

    @property
    def latency_ms(self) -> float:
        return sum(case.latency_ms for case in self.cases)

    @property
    def average_latency_ms(self) -> float:
        return self.latency_ms / self.total if self.total else 0.0

    @property
    def errors(self) -> int:
        return sum(case.error_type is not None for case in self.cases)

    @property
    def tool_success_rate(self) -> float | None:
        total = self.tool_successes + self.tool_failures
        return self.tool_successes / total if total else None

    @property
    def tool_successes(self) -> int:
        return sum(case.tool_successes for case in self.cases)

    @property
    def tool_failures(self) -> int:
        return sum(case.tool_failures for case in self.cases)

    @property
    def usage_complete(self) -> bool:
        return all(case.usage_complete for case in self.cases)

    @property
    def cost(self) -> ModelCost | None:
        values = [case.cost for case in self.cases]
        if not values or any(value is None for value in values):
            return None
        total = values[0]
        assert total is not None
        try:
            for value in values[1:]:
                assert value is not None
                total = total.add(value)
        except PricingError:
            return None
        return total

    @property
    def cost_complete(self) -> bool:
        return self.cost is not None and all(case.cost_complete for case in self.cases)


EvaluationTarget = Callable[[EvaluationCase], Awaitable[RunResult]]


class LocalEvaluationRunner:
    """Run cases sequentially so local side effects remain deterministic."""

    async def run(
        self,
        cases: Sequence[EvaluationCase],
        target: EvaluationTarget,
        *,
        scorers: Sequence[EvaluationScorer] = (),
        cancellation: CancellationToken | None = None,
    ) -> EvaluationReport:
        results: list[EvaluationCaseResult] = []
        for case in cases:
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            started = monotonic()
            try:
                result = await target(case)
                scores = tuple(scorer.score(case, result) for scorer in scorers)
                tool_successes, tool_failures = _tool_outcomes(result)
                passed = (
                    result.stop_reason.value in case.accepted_stop_reasons
                    and all(score.passed for score in scores)
                )
                results.append(
                    EvaluationCaseResult(
                        case.name,
                        passed,
                        result.output,
                        result.stop_reason.value,
                        (monotonic() - started) * 1000,
                        result.usage,
                        result.usage_complete,
                        result.steps,
                        result.tool_calls,
                        tool_successes,
                        tool_failures,
                        scores,
                        cost=result.cost,
                        cost_complete=result.cost_complete,
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                results.append(
                    EvaluationCaseResult(
                        case.name,
                        False,
                        "",
                        None,
                        (monotonic() - started) * 1000,
                        TokenUsage(),
                        False,
                        0,
                        0,
                        0,
                        0,
                        (),
                        error_type=type(exc).__name__,
                        cost=None,
                        cost_complete=False,
                    )
                )
        return EvaluationReport(tuple(results))


class JsonEvaluationReporter:
    """Write an atomic report that excludes outputs unless explicitly enabled."""

    def __init__(self, *, include_outputs: bool = False) -> None:
        self.include_outputs = include_outputs

    async def write(self, report: EvaluationReport, path: str | Path) -> None:
        await asyncio.to_thread(
            self._write_sync,
            report,
            Path(path).resolve(),
        )

    def _write_sync(self, report: EvaluationReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        payload = json.dumps(
            evaluation_report_to_dict(
                report,
                include_outputs=self.include_outputs,
            ),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)


def evaluation_report_to_dict(
    report: EvaluationReport,
    *,
    include_outputs: bool = False,
) -> dict[str, Any]:
    usage = report.usage
    cost = report.cost
    return {
        "total": report.total,
        "passed": report.passed,
        "pass_rate": report.pass_rate,
        "latency_ms": report.latency_ms,
        "average_latency_ms": report.average_latency_ms,
        "errors": report.errors,
        "tool_successes": report.tool_successes,
        "tool_failures": report.tool_failures,
        "tool_success_rate": report.tool_success_rate,
        "usage_complete": report.usage_complete,
        "cost_complete": report.cost_complete,
        "cost": _cost_to_dict(cost),
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cached_input_tokens": usage.cached_input_tokens,
            "total_tokens": usage.total_tokens,
        },
        "cases": [
            {
                "name": case.name,
                "passed": case.passed,
                "stop_reason": case.stop_reason,
                "latency_ms": case.latency_ms,
                "usage": {
                    "input_tokens": case.usage.input_tokens,
                    "output_tokens": case.usage.output_tokens,
                    "cached_input_tokens": case.usage.cached_input_tokens,
                    "total_tokens": case.usage.total_tokens,
                    "complete": case.usage_complete,
                },
                "steps": case.steps,
                "tool_calls": case.tool_calls,
                "tool_successes": case.tool_successes,
                "tool_failures": case.tool_failures,
                "scores": [
                    {
                        "name": score.name,
                        "value": score.value,
                        "threshold": score.threshold,
                        "passed": score.passed,
                    }
                    for score in case.scores
                ],
                "error_type": case.error_type,
                "cost_complete": case.cost_complete,
                "cost": _cost_to_dict(case.cost),
                **({"output": case.output} if include_outputs else {}),
            }
            for case in report.cases
        ],
    }


def _cost_to_dict(cost: ModelCost | None) -> dict[str, str] | None:
    if cost is None:
        return None
    return {
        "currency": cost.currency,
        "price_table_version": cost.price_table_version,
        "input_cost": str(cost.input_cost),
        "output_cost": str(cost.output_cost),
        "cached_input_cost": str(cost.cached_input_cost),
        "total": str(cost.total),
    }


def _tool_outcomes(result: RunResult) -> tuple[int, int]:
    latest: dict[str, str] = {}
    for event in result.events:
        if event.type is not RunEventType.TOOL_COMPLETED:
            continue
        call_id = event.data.get("call_id")
        outcome = event.data.get("outcome")
        if isinstance(call_id, str) and isinstance(outcome, str):
            latest[call_id] = outcome
    successes = sum(outcome == "succeeded" for outcome in latest.values())
    return successes, len(latest) - successes


def _contract_strings(contract: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = contract.get(field, ())
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError("contract string list is invalid")
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        raise ValueError("contract string list contains duplicates")
    return normalized


def _contract_count(contract: Mapping[str, Any], field: str) -> int | None:
    value = contract.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("contract count is invalid")
    return value
