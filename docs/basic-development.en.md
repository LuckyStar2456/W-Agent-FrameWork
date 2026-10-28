# Basic development: support and coding agents

English | [简体中文](./basic-development.md)

Start with “template → registered tool → permission check → tool result → final answer,” then replace the model and business data. The [modern example](../examples/basic_development.py) is fully offline by default: no workspace file reads, code execution, service startup or model downloads. The legacy `basic_agent.py` remains unchanged.

## Shortest runnable path

From a source checkout with the current project's dependencies installed:

```powershell
python -m examples.basic_development support
python -m examples.basic_development coding
```

On Windows with multiple Python versions, select your configured virtual environment's Python, or `py -3.11` if that environment has the dependencies.

Both commands return JSON with `stop_reason="completed"`, `steps=2`, and `tool_calls=1`. Support returns the sample returns policy with its `sample:returns` source. Coding returns host-supplied `add()` source text without executing or modifying it. The policy is demonstration data, not a business commitment.

`examples` contains source assets, not a Python package promised in the wheel. Wheel-only users should obtain `examples/basic_development.py` from the matching source version, copy it into their own project root, and run:

```powershell
python basic_development.py support
python basic_development.py coding
```

Do not rely on `examples.basic_development` in a wheel-installed project. Import your own module instead, such as `from basic_development import support_tools`.

## What to customize

| Purpose | Template | Actual tool | Per-run permission |
| --- | --- | --- | --- |
| Support | `customer_support_agent(model="demo")` | `support_tools()` registers `knowledge_search_tool` over an in-memory document store and keyword retriever | `knowledge.read` |
| Coding | `coding_agent(model="demo")` | `coding_tools(source)` registers read-only `read_sample_module`, returning explicitly host-supplied text | `workspace.read` |

For support, replace the sample documents in `support_tools()` and retain source identifiers. Inject an authorized retriever when moving to file/vector knowledge; see [knowledge tools](./knowledge-tools.en.md) and [knowledge sync entries](./knowledge-sync-entries.en.md). A prompt is not a substitute for source evidence.

For coding, pass a small source snippet to `coding_tools(source)`, or explicitly implement bounded project tools. This example supplies no built-in IDE, arbitrary path reader, shell execution or file writer. `python_tool` executes host code, not a sandbox: the host owns path boundaries, input validation and side-effect classification.

`OfflineToolModel` is a deterministic two-turn test fixture. It requests a tool first, then derives its response from the actual `ToolResultContent`. This verifies composition, not language-model understanding, retrieval quality or task-solving ability. Its token counts are synthetic and are not billing evidence.

## Explicit real-model integration (optional; not exercised against a service)

After authorizing model access, data disclosure and potential costs, add the following script beside your copied example. Replace the placeholder with an actually configured tool-capable model. This code contacts local Ollama; it does not install or start the service.

```python
import asyncio
from basic_development import run_with_provider, support_tools
from w_agent import customer_support_agent, ollama_provider

async def main():
    model = "YOUR_INSTALLED_TOOL_CAPABLE_MODEL"
    provider = ollama_provider(default_model=model)
    result = await run_with_provider(
        provider, customer_support_agent(model=model), support_tools(),
        "What is the sample returns rule?", frozenset({"knowledge.read"}),
        provider_name="ollama",
    )
    print(result.stop_reason.value, result.output)

asyncio.run(main())
```

For coding, substitute `coding_agent`, `coding_tools()`, the corresponding prompt and `workspace.read`. Inspect `stop_reason`: a limit, failure or `needs-approval` is not a successful answer.

## Permissions and resource ownership

`run_with_provider()` creates per-call registries, registers the provider/tools, and uses `ReactAgentLoop` / `ToolExecutor`. Permissions come from the explicit `frozenset`, never the prompt. The sample read tools declare `READ`; a missing permission prevents handler execution. `WRITE` / `EXTERNAL` still require independent approval of the exact call ID even with permission; this helper never grants that approval.

The helper owns the passed Provider. It disposes established registrations and calls an available `aclose()` on return, registration failure or cancellation. Do not pass a Provider still shared by other runs; adapt lifecycle ownership in your host for shared clients. Async task cancellation propagates rather than manufacturing a successful result.

This is a one-shot in-memory example, with no persistent RunStore. Invoking the helper again creates a new Run and cannot resume an old approval checkpoint. For durable sessions, approval recovery or CLI/TUI project entry points, use [local Runtime](./local-runtime.en.md) and [tool execution](./tools.en.md). When supplying a factory to CLI, use your own module path (such as `basic_development:support_tools`) and follow that entry point's code-load consent, enabled-tools selection, permissions and per-call approvals. Importing a factory does not grant authority.

## Validation for this change

Executed in the existing clean Python environment:

```powershell
python -m pytest -q tests/test_basic_development.py tests/test_agent_templates.py tests/test_framework_acceptance.py
```

Result: `12 passed`. Both offline example commands above also returned successfully. New tests cover support source/coding text reaching the final answer, denied handlers, independent write approval, and Provider closure after registration failure or cancellation. No real model or knowledge service was called; this is not model-quality, deployment or formal-release acceptance.
