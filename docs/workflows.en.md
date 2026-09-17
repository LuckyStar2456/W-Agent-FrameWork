# Workflows and node-boundary recovery

English | [简体中文](./workflows.md)

## Status

`Implemented`: current `2.0.0a1` source includes three workflow definitions, one engine protocol, deterministic local execution, node events, cooperative cancellation, and in-memory/JSONL pause and recovery at node boundaries.

`Planned`: parallel DAG scheduling, bidirectional agent/workflow convenience adapters, an external pause handle for a running workflow, and general session projections.

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
| `InMemoryWorkflowStore` | In-process development and test storage |
| `JsonlWorkflowStore` | Durable storage for one local lifecycle owner |

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

## Cancellation and events

`CancellationToken` is checked at node boundaries and passed into `WorkflowNodeContext` for cooperative checks inside asynchronous nodes. A handler should check cancellation before starting expensive work. Cancellation during a node is also treated as uncertain execution and is never replayed automatically.

Events use a continuous per-run sequence:

- `workflow-started` / `workflow-resumed`
- `node-started` / `node-completed` / `node-failed`
- `workflow-paused` / `workflow-completed`

Event data does not automatically include inputs, outputs, or exception messages, avoiding default persistence of prompts and credentials. Custom stores and observability plugins must preserve the same safety boundary.

## Replacement and composition

Applications may replace the entire `WorkflowEngineProtocol` or `WorkflowStore`. Any node may also call the public `AgentLoop`, model, tool, or application-service APIs. Convenience adapters that turn an agent into a node or a workflow into a tool are not yet included; they are `Planned`, while manual composition through public APIs already works.
