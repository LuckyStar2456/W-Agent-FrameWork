import json

import pytest

from w_agent import (
    ContainsTextScorer,
    EvaluationCase,
    ExactTextScorer,
    JsonEvaluationReporter,
    LocalEvaluationRunner,
    MessageRole,
    ModelMessage,
    RunEvent,
    RunEventType,
    RunResult,
    StopReason,
    TokenUsage,
    evaluation_report_to_dict,
)


def _result(name, output, *, reason=StopReason.COMPLETED, events=()):
    return RunResult(
        f"run-{name}",
        reason,
        output,
        (ModelMessage.text(MessageRole.ASSISTANT, output or "empty"),),
        events,
        steps=1,
        tool_calls=0,
        usage=TokenUsage(4, 2),
        model_calls=1,
        reported_usage_calls=1,
    )


@pytest.mark.asyncio
async def test_local_evaluation_scores_cases_and_aggregates_usage():
    cases = (
        EvaluationCase("exact", "secret prompt one", "hello"),
        EvaluationCase("contains", "secret prompt two", "world"),
    )

    async def target(case):
        return _result(case.name, "hello" if case.name == "exact" else "no match")

    report = await LocalEvaluationRunner().run(
        cases,
        target,
        scorers=(ExactTextScorer(), ContainsTextScorer()),
    )

    assert report.total == 2
    assert report.passed == 1
    assert report.pass_rate == 0.5
    assert report.usage == TokenUsage(8, 4)
    assert report.usage_complete is True
    assert report.tool_successes == 0
    assert report.tool_failures == 0
    assert report.tool_success_rate is None
    assert report.cases[0].passed is True
    assert report.cases[1].passed is False


@pytest.mark.asyncio
async def test_evaluation_report_omits_prompts_outputs_and_exception_messages(tmp_path):
    cases = (EvaluationCase("failure", "secret prompt", "unused"),)

    async def target(case):
        raise RuntimeError("secret exception body")

    report = await LocalEvaluationRunner().run(cases, target)
    path = tmp_path / "report.json"
    await JsonEvaluationReporter().write(report, path)
    persisted = path.read_text(encoding="utf-8")
    payload = json.loads(persisted)

    assert report.cases[0].error_type == "RuntimeError"
    assert "secret" not in persisted
    assert "output" not in payload["cases"][0]
    assert payload["cases"][0]["error_type"] == "RuntimeError"
    assert payload["usage_complete"] is False
    assert payload["tool_successes"] == 0
    assert payload["tool_failures"] == 0


def test_evaluation_report_output_requires_explicit_option():
    case_result = _result("one", "visible output")

    async def target(case):
        return case_result

    async def build():
        return await LocalEvaluationRunner().run(
            (EvaluationCase("one", "prompt", "visible output"),),
            target,
            scorers=(ExactTextScorer(),),
        )

    import asyncio

    report = asyncio.run(build())
    hidden = evaluation_report_to_dict(report)
    visible = evaluation_report_to_dict(report, include_outputs=True)

    assert "output" not in hidden["cases"][0]
    assert visible["cases"][0]["output"] == "visible output"


@pytest.mark.asyncio
async def test_evaluation_uses_final_tool_outcome_per_call_id():
    events = (
        RunEvent(
            1,
            RunEventType.TOOL_COMPLETED,
            "run-tools",
            {"call_id": "retry", "outcome": "failed"},
        ),
        RunEvent(
            2,
            RunEventType.TOOL_COMPLETED,
            "run-tools",
            {"call_id": "retry", "outcome": "succeeded"},
        ),
        RunEvent(
            3,
            RunEventType.TOOL_COMPLETED,
            "run-tools",
            {"call_id": "failed", "outcome": "failed"},
        ),
    )

    async def target(case):
        return _result(case.name, "done", events=events)

    report = await LocalEvaluationRunner().run(
        (EvaluationCase("tools", "prompt"),),
        target,
    )

    assert report.tool_successes == 1
    assert report.tool_failures == 1
    assert report.tool_success_rate == 0.5
