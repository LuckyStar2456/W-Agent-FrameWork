# Local testing, model replay, and evaluation

English | [简体中文](./testing-evaluation.md)

Status: scripted model providers, explicit recording/sequential replay, the sequential evaluation runner, and JSON reports are `Experimental` in `2.0.0a1`. Built-in customer-support/coding benchmark suites, cost metrics, and CLI/TUI evaluation screens remain `Planned`.

## Deterministic model tests

`ScriptedModelProvider` consumes a finite sequence of `ScriptedModelTurn` values without network access. Each turn either returns standard `StreamEvent` values or raises a normalized `ModelFailure`, and it may validate the requested model and tool names. It is intended for agent-loop, routing-consumer, and failure-path tests and fails closed when the script is exhausted.

## Recording and replay

`RecordingModelProvider` wraps any model provider and appends to `JsonlModelCassette` only after a complete terminal event or a normalized model failure. `ReplayModelProvider` consumes records in order without network access and refuses a structurally mismatched request or an exhausted cassette.

Both recording and replay require `allow_sensitive_content=True`. This is an intentional safety boundary: a cassette may contain model text, tool arguments, tool results, and media bytes. Callers may provide `redact(str) -> str` for textual fields. Binary media is not automatically redacted, so developers must still protect the file itself.

The cassette request fingerprint stores only model name, message roles, content-block types, tool names, and configuration shape. It stores no prompt, credential, or extension values. Replay therefore checks structural compatibility, not semantic equality with the original prompt. Current replay is an in-process sequential consumer; it does not provide concurrent scheduling, arbitrary seeking, or cross-version migration.

## Local evaluation

`LocalEvaluationRunner` executes `EvaluationCase` values sequentially against a caller-supplied asynchronous target returning the public `RunResult`. Built-in `ExactTextScorer` and `ContainsTextScorer` implementations can be replaced or combined. Ordinary exceptions become failures by exception type, while cancellation propagates.

`EvaluationReport` aggregates:

- case pass rate, error count, total latency, and average latency;
- input, output, cached-input, and total tokens plus metering completeness;
- tool successes, failures, and success rate from the final `TOOL_COMPLETED` event for each call ID;
- each scorer value, threshold, and pass state.

`JsonEvaluationReporter` omits prompts, metadata, model outputs, and exception bodies by default, retaining only exception types. Outputs are persisted only with explicit `include_outputs=True`. There is no built-in price table yet, so the framework never silently converts tokens into cost; versioned pricing and cost budgets remain `Planned`.

## Minimal example

```python
from w_agent import EvaluationCase, ExactTextScorer, LocalEvaluationRunner

report = await LocalEvaluationRunner().run(
    [EvaluationCase("hello", "Say hello", "hello")],
    run_case,
    scorers=[ExactTextScorer(case_sensitive=False)],
)
print(report.pass_rate, report.usage.total_tokens, report.usage_complete)
```

`run_case` is a developer-supplied asynchronous function that accepts an `EvaluationCase` and returns a `RunResult`. The framework grants no model, tool, or local-execution authority implicitly.
