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
from w_agent.models import CancellationToken, TokenUsage

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

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.prompt:
            raise ValueError("evaluation case name and prompt are required")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def load_evaluation_cases(path: str | Path) -> tuple[EvaluationCase, ...]:
    """Load a bounded strict JSON dataset without executing code."""

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
    unknown = set(data) - {"schema_version", "cases"}
    if unknown:
        raise EvaluationDatasetError("evaluation dataset has unsupported fields")
    if data.get("schema_version", 1) != 1:
        raise EvaluationDatasetError("unsupported evaluation dataset schema version")
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvaluationDatasetError("evaluation dataset needs a non-empty cases list")
    if len(raw_cases) > _MAX_DATASET_CASES:
        raise EvaluationDatasetError("evaluation dataset has too many cases")
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
        }
        if unknown:
            raise EvaluationDatasetError("evaluation case has unsupported fields")
        name = raw_case.get("name")
        prompt = raw_case.get("prompt")
        expected = raw_case.get("expected_output")
        metadata = raw_case.get("metadata", {})
        if not isinstance(name, str) or not isinstance(prompt, str):
            raise EvaluationDatasetError("evaluation case name/prompt must be strings")
        if expected is not None and not isinstance(expected, str):
            raise EvaluationDatasetError(
                "evaluation case expected_output must be a string or null"
            )
        if not isinstance(metadata, Mapping):
            raise EvaluationDatasetError("evaluation case metadata must be an object")
        if name in names:
            raise EvaluationDatasetError("evaluation case names must be unique")
        try:
            case = EvaluationCase(name, prompt, expected, metadata)
        except (TypeError, ValueError) as exc:
            raise EvaluationDatasetError("evaluation case is invalid") from exc
        names.add(name)
        cases.append(case)
    return tuple(cases)


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
                passed = result.stop_reason is StopReason.COMPLETED and all(
                    score.passed for score in scores
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
                **({"output": case.output} if include_outputs else {}),
            }
            for case in report.cases
        ],
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
