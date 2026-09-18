# Workflows and node-boundary recovery

English | [简体中文](./workflows.md)

## Status

`Implemented`: `2.0.0a1` includes three workflow definitions, one engine protocol, deterministic local execution, node events, cooperative cancellation, in-memory/JSONL pause and recovery at node boundaries, and bidirectional agent/workflow adapters. Current main additionally provides privacy-safe checkpoint discovery, explicit workflow-entry loading, and exact-version recovery; these increments are not yet published to PyPI.

`Planned`: parallel DAG scheduling, automatic cascading recovery between agent approval and workflow pause, an external pause handle for a running workflow, and general session projections.

`Reserved`: nested or distributed workflows, multi-agent orchestration, and restoration of arbitrary Python instruction stacks.

## Public components

| Component | Purpose |
|---|---|
| `DagWorkflowDefinition` | Declares nodes and dependencies; rejects unknown nodes and cycles at construction |
| `StateGraphDefinition` | Declares an entry, default transitions, and a step bound; nodes may choose the next node dynamically |
| `PythonWorkflowDefinition` | Uses a synchronous or asynchronous Python handler as an explicit recovery boundary |
| `WorkflowNodeResult` | Returns output, state updates, a next node, or a pause request |
| `WorkflowEngineProtocol` | Replaceable `start()` / `resume()` engine contract |
| `LocalWorkflowEngine` | Built-in deterministic sequential executor |
| `WorkflowRegistry` | Registers definitions by name, version, and scope through the shared microkernel registry |
| `WorkflowStore` | Replaceable event and checkpoint storage contract |
| `WorkflowCheckpointCatalog` | Optional checkpoint-discovery contract kept separate from the stable store |
| `InMemoryWorkflowStore` | In-process development and test storage |
| `JsonlWorkflowStore` | Durable storage for one local lifecycle owner |
| `WorkflowCheckpointSummary` | Recovery-discovery projection without input, state, output, scope, or metadata values |
| `load_workflow_entry()` / `load_workflow_entries()` | Import `module:attribute` definitions after explicit application authorization |
| `agent_workflow_node()` | Adapts a fixed agent loop/definition into a workflow node |
| `workflow_start_tool()` / `workflow_resume_tool()` | Adapt a fixed workflow into governed agent tools |

All public types are exported directly from `w_agent`; there is no `w_agent.v2` namespace.

`WorkflowRegistry` uses the `workflow.definition` capability on the same underlying `Registry` as models and tools. A registration version must equal the definition's `version`; resolution supports the same version constraints and hierarchical scopes.

## DAG example

```python
import asyncio

from w_agent import (
    DagWorkflowDefinition,
    LocalWorkflowEngine,
    WorkflowContext,
    WorkflowNode,
    WorkflowNodeResult,
)


def load(context):
    return WorkflowNodeResult(
        output=context.input,
        state_updates={"text": context.input},
    )


async def summarize(context):
    return f"summary:{context.state['text']}"


workflow = DagWorkflowDefinition(
    "document",
    (
        WorkflowNode("summarize", summarize),
        WorkflowNode("load", load),
    ),
    dependencies={"summarize": ("load",)},
    version="1",
)


async def main():
    result = await LocalWorkflowEngine().start(
        workflow,
        WorkflowContext("run-001", input="hello"),
    )
    print(result.output)


asyncio.run(main())
```

The engine selects the first definition-order node whose dependencies are satisfied, making execution repeatable. Independent nodes are not currently run in parallel.

## State graph

A node can override a static transition with `WorkflowNodeResult(next_node="name")`. Without a dynamic target, the engine uses `transitions[current]`; no transition means completion. `max_steps` gives cyclic graphs a hard bound.

```python
def route(context):
    return WorkflowNodeResult(next_node=context.input["route"])


graph = StateGraphDefinition(
    "router",
    (
        WorkflowNode("route", route),
        WorkflowNode("fast", lambda context: "fast"),
        WorkflowNode("slow", lambda context: "slow"),
    ),
    entry="route",
    transitions={"fast": None, "slow": None},
    max_steps=10,
)
```

## Python entry point and explicit pause

A Python workflow never serializes function frames. When a handler returns `pause=True`, the engine stores input, state, outputs, metadata, and `resume_count`; recovery calls the handler again from its entry point.

```python
def review(context):
    if context.resume_count == 0:
        return WorkflowNodeResult(
            state_updates={"draft": "ready"},
            pause=True,
        )
    return f"published:{context.state['draft']}"


workflow = PythonWorkflowDefinition("review", review)
store = JsonlWorkflowStore(".wagent-state")
engine = LocalWorkflowEngine(store)

paused = await engine.start(workflow, WorkflowContext("review-1"))
assert paused.checkpoint_id == "review-1"

# In a restarted process, provide the same name, version, and definition kind:
resumed = await LocalWorkflowEngine(
    JsonlWorkflowStore(".wagent-state")
).resume(workflow, "review-1")
```

Persisted input, state, outputs, and metadata must be JSON-encodable. Replace `WorkflowStore`, or encode values explicitly at node boundaries, when custom types must be retained.

## Checkpoint safety semantics

```text
READY / PAUSED → claim → RESUMING → node completes → READY / PAUSED
                                  └→ interruption/failure → stays RESUMING
```

- Before node execution, the store atomically claims the in-process checkpoint as `RESUMING`.
- State returns to `READY` or `PAUSED` only after the handler returns and its node result is recorded successfully.
- If a process stops inside a node, the framework cannot know whether external effects occurred. `resume()` therefore raises `WorkflowResumeConflictError` instead of silently repeating the node.
- `JsonlWorkflowStore` targets one local lifecycle owner. It is not a distributed lock or multi-primary scheduler.
- Recovery rejects a changed workflow name, version, or kind. Behavioral changes should use a new `version`.

Successful completion and reaching a step bound are terminal and delete the checkpoint. An explicit pause or boundary cancellation retains a resumable checkpoint. Node failure returns a stable failure code without exception text and keeps `RESUMING` for manual diagnosis.

## Privacy-safe discovery and explicit recovery

`WorkflowCheckpointCatalog.list_checkpoints()` returns `WorkflowCheckpointSummary` values in stable run-ID order. Discovery stays separate from the stable `WorkflowStore` execution contract, so existing custom stores are not forced to implement a new method. A summary contains only workflow name, version, kind, status, node identifiers, and counters; persisted input, state, output, scope, and metadata values are excluded. `InMemoryWorkflowStore` and `JsonlWorkflowStore` implement both contracts.

Developer definitions are imported through `load_workflow_entry()` / `load_workflow_entries()` only after a separate authorization. A checkpoint or configuration file cannot trigger Python imports. The loader builds a catalog keyed by `(name, version)` and rejects duplicate identities; the engine checks name, version, and kind again before recovery.

```python
store = JsonlWorkflowStore(".wagent")
summaries = await store.list_checkpoints()

# Call only after the host confirms execution of developer-owned Python code:
catalog = load_workflow_entries(("my_workflows:definitions",))
checkpoint = await store.load_checkpoint("review-1")
definition = catalog[(checkpoint.workflow_name, checkpoint.workflow_version)]
result = await LocalWorkflowEngine(store).resume(definition, checkpoint.run_id)
```

The CLI provides `wagent checkpoint workflow-list` and `workflow-resume`. Recovery requires `--workflow-entry`, `--confirm-workflow-code`, and `--confirm-resume` together. The TUI uses separate one-shot `LOAD WORKFLOW` and `RESUME WORKFLOW` confirmations. Both can target an explicitly selected state root, so a run in another local store root can be recovered without copying, merging, or automatically migrating stores. Runtime values stay hidden in default CLI/TUI results. A `RESUMING` checkpoint still fails closed because node side effects are uncertain and require manual diagnosis.

## Cancellation and events

`CancellationToken` is checked at node boundaries and passed into `WorkflowNodeContext` for cooperative checks inside asynchronous nodes. A handler should check cancellation before starting expensive work. Cancellation during a node is also treated as uncertain execution and is never replayed automatically.

Events use a continuous per-run sequence:

- `workflow-started` / `workflow-resumed`
- `node-started` / `node-completed` / `node-failed`
- `workflow-paused` / `workflow-completed`

Event data does not automatically include inputs, outputs, or exception messages, avoiding default persistence of prompts and credentials. Custom stores and observability plugins must preserve the same safety boundary.

## Replacement and composition

Applications may replace the entire `WorkflowEngineProtocol` or `WorkflowStore`. Any node may also call the public `AgentLoop`, model, tool, or application-service APIs.

`agent_workflow_node()` converts workflow input into a user message by default, accepts only `COMPLETED` agent results, and returns JSON-persistable output, stop reason, and token usage. Its message factory, tool-authority context, result mapping, and accepted stop reasons are replaceable. A non-completed result fails the node by default so approval or budget stops are not mistaken for success.

`workflow_start_tool()` and `workflow_resume_tool()` bind one fixed definition. By default they return run/checkpoint identifiers, public output, and stop status without exposing internal state to the model; callers can replace the result mapper. They declare `WRITE` effects and require `workflow.execute` by default, so application-granted permission and per-call approval still apply. Cancellation propagates into the workflow. A paused result is never resumed automatically; the agent explicitly invokes the resume tool or the application takes over. These adapters neither implement nested workflows nor automatically join agent and workflow checkpoints.
