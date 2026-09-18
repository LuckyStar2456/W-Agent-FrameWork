# Local testing, model replay, and evaluation

English | [简体中文](./testing-evaluation.md)

Status: scripted model providers, explicit recording/sequential replay, the sequential evaluation runner, JSON reports, versioned cost metrics, and CLI/TUI evaluation entry points are `Experimental` in `2.0.0a2`. Current main additionally includes versioned customer-support/coding suites, a replaceable suite registry, and declarative case-contract scoring.

## Deterministic model tests

`ScriptedModelProvider` consumes a finite sequence of `ScriptedModelTurn` values without network access. Each turn either returns standard `StreamEvent` values or raises a normalized `ModelFailure`, and it may validate the requested model and tool names. It is intended for agent-loop, routing-consumer, and failure-path tests and fails closed when the script is exhausted.

## Recording and replay

`RecordingModelProvider` wraps any model provider and appends to `JsonlModelCassette` only after a complete terminal event or a normalized model failure. `ReplayModelProvider` consumes records in order without network access and refuses a structurally mismatched request or an exhausted cassette.

Both recording and replay require `allow_sensitive_content=True`. This is an intentional safety boundary: a cassette may contain model text, tool arguments, tool results, and media bytes. Callers may provide `redact(str) -> str` for textual fields. Binary media is not automatically redacted, so developers must still protect the file itself.

The cassette request fingerprint stores only model name, message roles, content-block types, tool names, and configuration shape. It stores no prompt, credential, or extension values. Replay therefore checks structural compatibility, not semantic equality with the original prompt. Current replay is an in-process sequential consumer; it does not provide concurrent scheduling, arbitrary seeking, or cross-version migration.

## Local evaluation

`LocalEvaluationRunner` executes `EvaluationCase` values sequentially against a caller-supplied asynchronous target returning the public `RunResult`. Built-in `ExactTextScorer`, `ContainsTextScorer`, and `CaseContractScorer` implementations can be replaced or combined. `CaseContractScorer` reads only `metadata.contract` and can check required/any/forbidden tools, allowed stop reasons, all/any text fragments, and tool-call count bounds. Unknown fields or invalid types fail closed; no code is executed. Ordinary exceptions become failures by exception type, while cancellation propagates.

`EvaluationReport` aggregates:

- case pass rate, error count, total latency, and average latency;
- input, output, cached-input, and total tokens plus metering completeness;
- total cost, currency, price-table version, and pricing completeness when cases use one table version;
- tool successes, failures, and success rate from the final `TOOL_COMPLETED` event for each call ID;
- each scorer value, threshold, and pass state.

`JsonEvaluationReporter` omits prompts, metadata, model outputs, and exception bodies by default, retaining only exception types. Outputs are persisted only with explicit `include_outputs=True`. Evaluation aggregates only costs already calculated in `RunResult` with an explicit application-supplied table version. If any case is not fully priced or versions/currencies differ, aggregate cost remains unavailable instead of being inferred from tokens.

## CLI datasets

`load_evaluation_dataset()` reads bounded strict JSON while preserving optional name, version, and scorer recommendations; `load_evaluation_cases()` is the cases-only compatibility helper. Neither imports or executes code, and case names must be unique:

```json
{
  "schema_version": 1,
  "name": "smoke",
  "version": "1.0.0",
  "scorers": ["case-contract"],
  "cases": [
    {
      "name": "hello",
      "prompt": "Say hello",
      "expected_output": null,
      "accepted_stop_reasons": ["completed"],
      "metadata": {
        "contract": {
          "allowed_stop_reasons": ["completed"],
          "expected_contains_any": ["hello", "hi"],
          "max_tool_calls": 0
        }
      }
    }
  ]
}
```

`accepted_stop_reasons` defaults to `completed` only. A case that verifies an approval boundary may explicitly use `needs-approval`. The runner checks the stop reason before applying every scorer, so a declarative contract cannot bypass the case's own terminal condition.

The CLI executes cases sequentially. With no `--scorer`, it uses dataset recommendations (legacy files default to `exact-text`). Callers may repeat `exact-text`, `contains-text`, or `case-contract`, or use `none` alone to check only run completion. Potentially billable model calls require explicit authorization:

```text
wagent evaluate cases.json --config .wagent/config.json --confirm-model-call --report report.json
```

## Built-in support and coding suites

`EvaluationSuite` is ordinary immutable data; applications may create, extend, or replace `EvaluationSuiteRegistry`. Current main supplies `customer-support@1.0.0` and `coding@1.0.0`. They reference the starter agents' recommended tool names and check missing-identifier handling, evidence lookup, write approval, inspect-first behavior, approval-gated patches, and sandboxed verification. Approval cases explicitly set `accepted_stop_reasons=["needs-approval"]`, making a safe pause an expected result. They are not vendor-model leaderboards and bundle no tool implementation, authority, approval, or test data.

```text
wagent benchmark list --json
wagent benchmark export customer-support@1.0.0 support-suite.json
wagent evaluate builtin:customer-support@1.0.0 --config .wagent/config.json \
  --tool-entry my_tools:support_catalog --confirm-tool-code \
  --grant-permission tickets.read --confirm-model-call
```

`builtin:<name>[@version]` resolves only an in-process registered suite and performs no network access. Omitting the version selects the registry's last registered version; pin it for reproducible evaluation. `benchmark export` emits the same strict JSON and requires explicit `--force` before replacing an existing destination. Most built-in cases require host-supplied tools with matching names. Missing tools correctly fail the suite; nothing is downloaded or authorized automatically.

Disposable run state is the default, so session/run files that may contain prompts are deleted at exit. Pass `--state-root` only when persistence is intended. `--report` writes the privacy-safe default report; `--include-outputs` makes both the report and `--json` data include potentially sensitive model outputs. If any case fails, the command emits the report and exits with status 1. Tool-code loading and tool permissions still require separate `--confirm-tool-code`, `--tool-entry`, and `--grant-permission` authorization. Tool calls that need human approval currently fail the evaluation case and are never auto-approved.

The TUI Evaluation screen reads the same JSON or `builtin:` reference and runtime configuration and runs only after the user types `EVALUATE`. That confirmation is immediately cleared and never persisted. The screen uses disposable state and dataset-recommended scorers, may write a privacy-safe report, and shows only aggregate and per-case status. Developer tool entries and one-run permissions are separate inputs; tool code is imported only after the user also types `LOAD EVAL TOOLS`, so model-call authorization cannot authorize code import. Custom Python scorers and output persistence remain available through the Python API/CLI.

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
