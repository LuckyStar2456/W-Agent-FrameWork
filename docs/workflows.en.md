# Workflows and node-boundary recovery

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./workflows.md)

## Status

`Implemented`: `2.0.0a1` includes three workflow definitions, one engine protocol, deterministic local execution, node events, cooperative cancellation, in-memory/JSONL pause and recovery at node boundaries, and bidirectional agent/workflow adapters. `2.0.0a4` additionally provides privacy-safe checkpoint discovery, explicit workflow-entry loading, and exact-version recovery; these increments are included in the 2.0.0 source.

`Experimental` (`2.0.0a4` release): `LocalWorkflowEngine(max_parallel_nodes=N)` explicitly enables bounded concurrent asynchronous DAG frontiers; the default `N=1` retains sequential behavior.

The `2.0.0a4` release also adds `WorkflowNodeInvoker` for replacing node invocation independently. `ThreadedWorkflowNodeInvoker` explicitly offloads synchronous handlers while asynchronous handlers remain on the event loop.

The `2.0.0a4` release also provides `WorkflowPauseController` keyed by run ID and replaceable `WorkflowPauseSource`, responding to external pause requests at node or parallel-batch boundaries.

`Planned`: general session projections. The reverse tool-continuation bridge is now in the a6 release (focused regressions passed), described below. The `2.0.0a5` release adds explicit Agent approval continuation inside Workflow (`2.0.0a5`, focused regressions passed), described below. Background recovery, boundary pause, and optional threaded invocation for TUI-owned recovery tasks are now in the `2.0.0a4` release.

`Reserved`: nested or distributed workflows, multi-agent orchestration, and restoration of arbitrary Python instruction stacks.

## Public components

| Component | Purpose |
|---|---|
| `DagWorkflowDefinition` | Declares nodes and dependencies; rejects unknown nodes and cycles at construction |
| `StateGraphDefinition` | Declares an entry, default transitions, and a step bound; nodes may choose the next node dynamically |
| `PythonWorkflowDefinition` | Uses a synchronous or asynchronous Python handler as an explicit recovery boundary |
| `WorkflowNodeResult` | Returns output, state updates, a next node, or a pause request |
| `WorkflowEngineProtocol` | Replaceable `start()` / `resume()` engine contract |
| `LocalWorkflowEngine` | Sequential by default, with explicit bounded DAG-frontier concurrency |
| `WorkflowNodeInvoker` | Replaceable single-invocation contract, separate from scheduling, retries, and state commits |
| `WorkflowPauseSource` / `WorkflowPauseController` | Replaceable pause-query contract and thread-safe in-process controller |
| `InlineWorkflowNodeInvoker` / `ThreadedWorkflowNodeInvoker` | Default same-thread invocation and opt-in synchronous thread execution |
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

By default, the engine selects the first definition-order node whose dependencies are satisfied. A host can set `LocalWorkflowEngine(max_parallel_nodes=2)` to run independent asynchronous nodes concurrently. At most two ready nodes start in each batch; dependents wait until the entire batch commits. Synchronous handlers run on the event-loop thread by default; the invocation policy below enables thread execution.

Every handler in a batch sees the same committed `state` and `outputs` snapshot and cannot depend on a sibling's new output. Results merge in definition order; two nodes updating the same state key fail with `parallel-state-conflict` rather than silently overwriting. Handlers should also avoid mutating nested mutable objects in shared state or outputs in place. If one node requests a pause, other already-started nodes complete and the pause takes effect at the batch boundary. A batch failure, conflict, or cancellation leaves a `RESUMING` checkpoint; uncertain external side effects prevent automatic replay of that batch.

## Replaceable node invocation

```python
from w_agent import LocalWorkflowEngine, ThreadedWorkflowNodeInvoker

engine = LocalWorkflowEngine(
    max_parallel_nodes=2,
    node_invoker=ThreadedWorkflowNodeInvoker(),
)
```

The default `InlineWorkflowNodeInvoker` retains same-thread behavior. The threaded template uses `asyncio.to_thread` to dispatch synchronous functions and callable objects to the loop's default executor, copying ContextVar context. Async functions, async `__call__`, and awaitables returned by synchronous factories are awaited on the event loop. `max_parallel_nodes` bounds batches within one DAG run, not a global thread quota across runs. State graphs and Python workflows use the same invocation policy while retaining their own sequential scheduling.

Python cannot forcibly stop an already-running thread. Task cancellation waits for the synchronous call to exit, discards its result, and propagates cancellation; an unstarted coroutine returned after cancellation is closed. The checkpoint stays `RESUMING` during draining and the cancelled node cannot be replayed automatically. A permanently blocked synchronous call also blocks cancellation cleanup; handlers should set their own external I/O timeouts. Existing node-boundary `CancellationToken` semantics remain unchanged, and parallel batches still monitor the token. Threaded handlers must not call non-thread-safe event-loop methods directly.

The threaded template runs in the host process and provides no sandbox isolation; isolated operations inside nodes must still explicitly use a SandboxProvider. Handlers should return state updates rather than mutate shared nested objects. Invocation policy is not serialized into checkpoints, so a recovering process must assemble it again; CLI/TUI default engines continue using the inline policy. A custom `WorkflowNodeInvoker.invoke(node, context)` should invoke the handler once, await its result, and propagate errors/cancellation. The engine owns result normalization, state merging, and checkpoint commits.

## Application-requested pause

```python
from w_agent import WorkflowPauseController

control = WorkflowPauseController()
engine = LocalWorkflowEngine(pause_source=control)
running = asyncio.create_task(
    engine.start(workflow, WorkflowContext("run-controlled"))
)
# A host button, command handler, or another thread can target an exact run:
control.request_pause("run-controlled")
result = await running
if result.stop_reason.value == "paused":
    control.clear("run-controlled")
    result = await engine.resume(workflow, "run-controlled")
```

Requests may be set before starting or during execution. The controller does not interrupt a node; a parallel DAG completes and commits its whole current batch before pausing ahead of the next batch. A normal pause persists a `PAUSED` checkpoint and appends `workflow-paused` with only `source=external-request` in its event data. Recovery does not repeat committed nodes. With no remaining nodes, execution completes normally; step limits, cancellation, and node failure retain their original semantics and cannot be masked by pause. Python workflows respond only at function-call boundaries and cannot resume within a function.

Requests are isolated by exact run ID and remain active until `clear()`, which only removes the request and does not resume execution. The controller does not check run existence, persist requests, or automatically clear completed-run requests; the application owns its lifecycle. Share a controller only within one store's run namespace. After restart, a persisted `PAUSED` checkpoint can use the existing resume path, but the request source must be reassembled. Applications can replace the controller with a fast, nonblocking `is_pause_requested(run_id) -> bool` implementation without changing the stable execution contract or checkpoint format.

With a source enabled, the engine yields the event loop at scheduling boundaries so a host coroutine can set a request. Default inline synchronous nodes can still block the loop; select threaded invocation when appropriate. A request arriving after the boundary check takes effect at the following boundary. TUI recovery in the `2.0.0a4` release uses a background task, with a pause button bound to this invocation's state root/run ID and a synchronous-thread option that defaults off. The UI distinguishes pending requests from the engine's paused result and clears its controller when the operation ends; another recovery requires fresh authorization. The `2.0.0a5` release adds SQLite and CLI cross-process request controls below (`2.0.0a5`, focused regressions passed); existing checkpoint discovery and recovery support boundary-paused runs.

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

## Local cross-process pause (`2.0.0a5`, focused regressions passed)

The `2.0.0a5` release includes replaceable `SQLiteWorkflowPauseController`, with focused regressions passing. It uses standard-library SQLite without a server, tenants, or a background polling process.

```python
from w_agent import JsonlWorkflowStore, LocalWorkflowEngine, SQLiteWorkflowPauseController

control = SQLiteWorkflowPauseController(".wagent")
engine = LocalWorkflowEngine(JsonlWorkflowStore(".wagent"), pause_source=control)
# Use engine.start(...) or engine.resume(...); another process uses the same state root.
```

CLI recovery ignores cross-process requests by default. Explicitly enable them, then request a pause from another terminal:

```sh
# Terminal A: recover an existing checkpoint with separate code/execution authority.
wagent checkpoint workflow-resume review-1 --state-root .wagent --workflow-entry my_workflows:definitions --confirm-workflow-code --confirm-resume --enable-pause-control
# Terminal B: request and inspect a pause without importing/executing workflow code.
wagent checkpoint workflow-pause review-1 --state-root .wagent --confirm-pause --json
wagent checkpoint workflow-pause-status review-1 --state-root .wagent --json
# Confirm the original executor exited and its checkpoint is recoverable, then clear.
# Run the Terminal A command again separately to resume.
wagent checkpoint workflow-pause-clear review-1 --state-root .wagent --confirm-clear --json
```

- Requests use exact run IDs in `workflow-control.sqlite3` under one state root. Repeated requests are idempotent; other runs/roots are unaffected. The CLI requires an existing checkpoint, while the Python template permits requests before starting.
- Success means only that the write committed, with `execution_acknowledged=false`; it does not modify a checkpoint. Only an engine observing this source pauses at the next committed node/batch boundary. Active nodes are not killed, and a final node may complete the run instead.
- Status returns the request flag and checkpoint state separately. They are not an atomic snapshot or proof of process liveness. `RESUMING` may mean active execution or a previous failure; it does not become recoverable through this command.
- Requests persist until explicitly cleared. Completion, recovery, and command exit do not automatically clear them and risk erasing later requests. Clearing neither executes code nor changes checkpoints. Recovery with observation enabled pauses again while the request remains set.
- Operations use separate connections and parameterized run IDs. SQLite transactions serialize request writes/clears. Boundary reads perform local file I/O with a 100 ms lock timeout. Lock conflicts, corruption, and read failures raise `WorkflowPauseControlError` instead of pretending no request exists and running the next node.
- This is for trusted local storage and one workflow execution owner, not a multi-primary execution lock, network-filesystem protocol, or security boundary against other same-account processes. Never recover the same run concurrently from multiple processes.

### TUI integration and source composition (`2.0.0a5`, focused regressions passed)

Checkpoints adds an off-by-default “Observe cross-process SQLite pause requests” option. When enabled, this recovery observes both the UI pause button and SQLite requests under the selected state root. The state root, run ID, and observation option are captured at launch and their controls locked during recovery; programmatic form edits cannot redirect the active recovery either.

The UI pause button sets only the current process's temporary request and never writes SQLite. Completion, failure, and cancellation clear only the UI-owned request, not persistent requests. With observation enabled, an uncleared persistent request pauses subsequent recovery again at a boundary. Use the CLI above to explicitly inspect and clear it, then provide fresh code-load and recovery authorization. With observation disabled, existing SQLite requests do not affect this TUI recovery.

Public template `AnyWorkflowPauseSource(*sources)` performs a read-only OR query in argument order, short-circuiting on the first `True`. Errors or non-`bool` responses from a queried source propagate instead of executing another node. It never calls `clear()` and does not own authorization, atomic cross-source snapshots, or execution ownership. All sources should address the same run namespace; custom implementations are composable:

```python
from w_agent import AnyWorkflowPauseSource, WorkflowPauseController

local = WorkflowPauseController()
combined = AnyWorkflowPauseSource(local, SQLiteWorkflowPauseController(".wagent"))
engine = LocalWorkflowEngine(JsonlWorkflowStore(".wagent"), pause_source=combined)
```

TUI status shows this recovery's observation mode, pending UI requests, and the engine's stop result. It does not continuously poll external requests or attribute a pause to a specific process. SQLite read failure ends the recovery with its checkpoint retained; it does not delete or repair the control file automatically.

## Agent approval cascading inside Workflow (`2.0.0a5`, focused regressions passed)

The `2.0.0a5` release adds `approval_agent_workflow_node()` without replacing `agent_workflow_node()`, which still accepts normal completion by default. The new template covers an Agent embedded in a Workflow node. Atomic cross-store transactions remain unimplemented; two-layer approval coordination services are now in the a6 release (focused regressions passed). a6 CLI/TUI explicit factory recovery is described below and is not part of a5.

The a6 release adds generic `ToolContinuation`, ReAct schema 2 ticket persistence, and the Workflow-specific reference bridge below (focused regressions passed). Two-layer authorization coordination services are now in the a6 release (focused regressions passed); UI guidance is also present in the a6 release (focused regressions passed). Existing `workflow_start_tool()` / `workflow_resume_tool()` behavior is unchanged; they do not automatically gain reverse suspension.

### Workflow continuation inside an Agent tool (a6, focused regressions passed)

`resumable_workflow_tool(engine, definition, store)` returns a separate `ToolBinding` using public ToolExecutor and ReAct protocols. Supply the engine's exact store. Assembly checks object identity when `engine.store` is exposed; hosts ensure consistency for custom engines without that attribute.

```python
from w_agent import JsonlWorkflowStore, LocalWorkflowEngine, resumable_workflow_tool

store = JsonlWorkflowStore(".w-agent/workflows")
engine = LocalWorkflowEngine(store)
# definition is an explicitly assembled DAG, state graph, or Python Workflow.
binding = resumable_workflow_tool(engine, definition, store)
tool_registry.register_binding(binding)
```

- The first call only prepares `WorkflowToolReference`, without starting a child or writing its store. Default WRITE policy may require approval first; the prepared ticket still requires another explicit resume so the parent checkpoint is persisted first.
- Tickets contain parent Run, Call ID, tool name, child Run, Workflow name/version/kind, scope, and event sequence, never grants. ReAct overwrites the actual parent Run ID; the executor supplies the actual invocation. Input and initial state come from persisted tool arguments.
- Authorized continuation starts the child once. PAUSED returns a new ticket; subsequent continuation resumes that exact child, checking PAUSED status, ownership metadata, scope, definition identity, and event sequence. Prepared tickets with existing execution history, stale boundaries, and RESUMING child checkpoints cannot be replayed.
- Only COMPLETED with the child checkpoint removed maps a successful result and lets the parent Agent continue. Failure, cancellation, timeout, or mismatch never reports success; parent ReAct retains an uncertain RESUMING checkpoint.
- Child nodes may use `approval_agent_workflow_node()`, with hosts separately reviewing and granting exact child-tool authority. Parent `workflow.execute`/Call ID authority is not forwarded; missing inner grants retain suspension. Do not independently resume the child Workflow outside the parent tool, which would stale the parent ticket.

Use a persistent parent RunStore for recovery after process/binding reconstruction. Trusted-local single ownership is required; references and event sequences provide neither distributed locks, code-hash validation, nor cross-store atomic commit. A crash between child completion and parent persistence requires diagnosis, never automatic replay. Existing standalone Workflow recovery commands do not coordinate this chain; two-layer approval services and CLI are described below, while TUI guidance is documented in the CLI/TUI guide (focused regressions passed).

### Two-layer approval coordination (a6, focused regressions passed)

For `parent Agent → Workflow tool → child Agent → pending tool`, two separate APIs are available:

- `review_workflow_tool_approvals(parent_store, workflow_store, child_store, parent_run_id)` inspects the parent ticket, Workflow ownership/pause boundary, and inner links without code imports or grants. It returns `WorkflowToolApprovalReview`; `.to_dict()` contains identifiers/status only, excluding scope, arguments, messages, and state values. Missing, uncertain, or stale outer links raise; inner link statuses are returned. Empty output does not mean completion.
- `resume_workflow_tool_approval(..., selection, factory, parent_permissions=..., child_permissions=...)` explicitly authorizes the selected two calls and continuing the parent Run. Permission sets are independent and default empty. Each level receives only its selected Call ID, never merged permissions or authority for later calls. New calls require fresh review, selection, and approval.

```python
from w_agent import (
    review_workflow_tool_approvals, resume_workflow_tool_approval,
    open_workflow_tool_approval_entry,
)

reviews = await review_workflow_tool_approvals(
    parent_store, workflow_store, child_store, parent_run_id,
)
# selected must be an explicitly reviewed user selection, never the automatic first row.
result = await resume_workflow_tool_approval(
    parent_store, workflow_store, child_store, selected,
    lambda ctx: open_workflow_tool_approval_entry("my_application:approval_factory", ctx),
    parent_permissions={"workflow.execute"}, child_permissions={"write.allowed"},
)
```

The host implements `WorkflowToolApprovalFactory` as an async context factory. Its `WorkflowToolApprovalAssemblyContext` contains the selection, complete parent/child AgentDefinitions, three stores, and operation-scoped `WorkflowApprovalGrants`. Faithfully rebuild the same Workflow, inner approval nodes, continuation tool, and parent loop using these dependencies, then yield the parent `ResumableAgentLoop`. Inject `approval_context=ctx.grants` into child nodes; the factory owns resource cleanup. The example application factory is not bundled. Dynamic imports execute trusted local Python and require separate host approval to load code; they are not sandboxed.

The service checks links before entering the factory, then rechecks the boundary and value snapshots of all three complete checkpoints after assembly. It only calls the parent loop's `resume()`, allowing its claim to precede child effects, never directly resuming the middle Workflow. Temporary grants are cleared after entry failure, normal completion, exceptions, cancellation, and exit failure; cleanup also runs before developer resource exit. A paused result does not prove the selected tool executed; unused grants are not retained.

Snapshot rechecks are neither locks nor cross-store transactions. Trusted storage, a faithful factory, and local single ownership remain required. Never downgrade stale tickets or automatically restart. Prepared/unstarted tickets and ordinary boundary pauses without inner approvals still use normal parent Agent recovery. Arbitrarily deep recursive approval remains unimplemented; CLI operations follow below and TUI guidance is in the CLI/TUI guide (focused regressions passed).

### Two-layer approval CLI (a6, focused regressions passed)

`checkpoint workflow-tool-approvals` queries the outer Agent Run ID, not the middle Workflow Run ID:

```bash
wagent checkpoint workflow-tool-approvals outer-run --state-root .wagent --workflow-state-root .workflow-state --child-state-root .child-state --json
```

`--state-root` is the parent Agent root; omitted workflow/child roots default to it. All three existing directories (parent/child `runs`, middle `workflows`) are required; missing state is never initialized. Repeat `--state-key` for custom child-approval keys. Review never loads factories or grants authority. Returned `sequence` identifies the reviewed Workflow pause boundary; an empty list does not mean completion.

After reviewing the actual actions, use the complete returned identities:

```bash
wagent checkpoint workflow-tool-approve-resume outer-run \
  --agent-factory my_application:approval_factory \
  --parent-call outer-call --parent-tool run_child \
  --workflow-run workflow-run --workflow-name child --workflow-version 1 --workflow-kind dag \
  --sequence 8 --node agent --child-run inner-run --child-agent coder \
  --child-call inner-call --child-tool write \
  --state-root .wagent --workflow-state-root .workflow-state --child-state-root .child-state \
  --parent-permission workflow.execute --child-permission write.allowed \
  --confirm-agent-code --confirm-parent-approval --confirm-child-approval --confirm-resume --json
```

The example uses Bash continuation; use one line or PowerShell backticks on Windows. Replace every ID, name, version, kind and sequence with the reviewed values. Both permission options repeat and default empty. The four confirmations authorize trusted Python assembly, the parent call, the child call, and parent continuation (including possible subsequent nodes, tools and billable model calls), respectively. Matching identifiers is not a substitute for reviewing actual actions.

The command matches every identity and the boundary before invoking the factory, then delegates checkpoint rechecks and temporary grants to the coordinator. Supply the two-layer `WorkflowToolApprovalFactory`, not a single-layer factory yielding WorkflowDefinition. The factory explicitly assembles pause sources, threading and concurrency policies; this command neither enables nor clears external pauses implicitly.

Framework output contains only parent Run/checkpoint/stop reason, counts, next pending-call identifiers and token/cost accounting, excluding model output, arguments, scope and event bodies. Errors show types only. `selected_child_execution_confirmed: false` means execution was not inferred from the returned state, not that the child tool did not execute. Trusted factories can print their own content; the CLI is not an output-isolation sandbox. Query and confirm again after another pause. Two-layer TUI guidance is also present in the a6 release (focused regressions passed).

### Basic assembly for an Agent inside Workflow

`approval_agent_workflow_node()` requires optional `ResumableAgentLoop` and an explicit reference to that loop's Agent `RunStore`; the base `AgentLoop` contract is unchanged. Request sources, models, tool policies, and both stores remain replaceable.

```python
from w_agent import AgentDefinition, ToolExecutionContext, approval_agent_workflow_node

# loop uses agent_store. The host fills this set only after explicit review.
approved_calls = set()  # (agent_run_id, call_id), never bare IDs shared across runs

def approval_authority(context, reference):
    return ToolExecutionContext(
        permissions=frozenset({"files.write"}),
        approved_call_ids=(
            frozenset({reference.call_id})
            if (reference.agent_run_id, reference.call_id) in approved_calls
            else frozenset()
        ),
        cancellation=context.cancellation,
    )

node = approval_agent_workflow_node(
    "writer", loop, AgentDefinition("coding"), agent_store,
    tool_context=lambda context: ToolExecutionContext(
        permissions=frozenset({"files.write"}),
    ),
    approval_context=approval_authority,
)
# Put node in a DAG/state graph, or node.handler in PythonWorkflowDefinition.
# Use normal Workflow start/resume; review the Agent checkpoint before approval.
```

When the first Agent run reaches `NEEDS_APPROVAL`, the template verifies the actual child checkpoint and stores an `AgentWorkflowApproval` reference under a node-owned state key (default `_w_agent_approval:<name>`). It contains only parent run/node, child Agent run/name, and call ID/tool name, never prompts, arguments, credentials, or grants. Reserve that key against other nodes; an explicit alternative `state_key` is supported.

Recovery first checks reference ownership, the full Agent definition, scope, checkpoint status, and pending call. Missing/stale references, changed definitions, or a child already `RESUMING` stop recovery and retain uncertain parent state; they never create a replacement child run. Without a fresh grant for the exact pending call ID, the node stays suspended without calling Agent `resume()`, a model, or a tool. Even when the callback returns several approved IDs, only the current pending ID reaches the child loop; subsequent approval boundaries return to the host callback. The original executor still enforces permissions and approval policy.

### Link review and one-shot grants (`2.0.0a5`, focused regressions passed)

`review_workflow_approvals(workflow_store, agent_store, run_id, state_keys=...)` queries one explicitly selected parent run. Default discovery examines only top-level `_w_agent_approval:` references; custom keys must be named explicitly. Malformed references or duplicate child runs raise errors instead of disappearing as “no approvals.” `WorkflowApprovalReview` contains reference identities, parent/child status, and `link_status`, never prompts, argument values, state bodies, outputs, or credentials.

`matched` means only that the observed parent node remains unfinished, its checkpoint is paused, and the child is pending approval with matching identity, scope, and call. This is not an atomic snapshot, authorization, or validation of newly loaded definitions. Uncertain parents, reference mismatch, missing children, and claimed children have distinct statuses. Actual recovery revalidates the full Agent definition and current checkpoint.

```sh
wagent checkpoint workflow-approvals parent-run --state-root .wagent --json
# Explicitly select another Agent root and repeat --state-key for custom keys.
wagent checkpoint workflow-approvals parent-run --state-root .wagent --agent-state-root .agent-state --state-key my-approval --json
```

The CLI imports no definitions, calls no models/tools, and does not initialize absent state directories. TUI Checkpoints adds “Review linked Agent approvals (read only)” for the selected parent run/root, with optional separate Agent root and custom keys. It shows snapshots without consuming code-load/recovery confirmation text. All review payloads include `authorized=false`.

Hosts can explicitly inject `WorkflowApprovalGrants` as `approval_context` instead of maintaining bare call-ID sets:

```python
from w_agent import WorkflowApprovalGrants, WorkflowApprovalLinkStatus, review_workflow_approvals

grants = WorkflowApprovalGrants()  # One workspace/composition owner, never global state.
node = approval_agent_workflow_node(
    "writer", loop, AgentDefinition("coding"), agent_store,
    tool_context=lambda _: ToolExecutionContext(permissions=frozenset({"files.write"})),
    approval_context=grants,
)
# Assemble workflow from node and run it to an approval boundary first.
reviews = await review_workflow_approvals(workflow_store, agent_store, "parent-run")
review = reviews[0]
if review.link_status is WorkflowApprovalLinkStatus.MATCHED:
    # Execute only AFTER separately reviewing the actual action and explicit approval:
    parent = await workflow_store.load_checkpoint("parent-run")
    grants.grant(review.reference, scope=parent.scope,
                 permissions=frozenset({"files.write"}), ttl_seconds=300)
    try:
        result = await engine.resume(workflow, "parent-run")
    finally:
        grants.clear()
```

Grants bind parent run, node, child run, Agent name, call ID, tool name, and scope. They expire after 300 seconds by default with explicit lifetime, revoke, and clear controls. They exist only in memory and are consumed once under a thread lock before child execution; failure/cancellation never refunds a consumed grant. A mismatched callback does not consume another grant. This template is not store-identity isolation: never share an instance across unrelated workspaces, and retain normal tool permission policies.

The published a5 CLI/TUI provide read-only review. The a6 release adds the CLI and TUI approval-recovery wiring below (focused regressions passed). Do not bypass the parent by resuming a linked child through ordinary Agent recovery: that can stale the parent reference, which subsequent recovery rejects. Resume through the parent Workflow with its explicitly injected grant object.

### CLI approval and parent recovery (a6, focused regressions passed)

`resume_workflow_approval()` is an optional host coordinator, not a replacement for the Engine, Store, or authority callback. It accepts two stores, a complete `AgentWorkflowApproval` reference, and a developer factory. The factory receives `WorkflowApprovalAssemblyContext`: operation stores, parent identity/scope, reference, and fresh `WorkflowApprovalGrants`. It must return an async context manager yielding one Workflow definition with the exact name, version, and kind. The factory closes its model clients and other resources. Ordinary zero-argument `--workflow-entry` loading is unchanged.

```python
# my_workflows.py; myapp functions and definitions are application-owned.
from contextlib import asynccontextmanager
from w_agent import approval_agent_workflow_node
from myapp import open_model, build_agent_loop, agent_definition, build_workflow

@asynccontextmanager
async def approved(context):
    async with open_model() as provider:
        loop = build_agent_loop(provider, store=context.agent_store)
        node = approval_agent_workflow_node(
            context.reference.workflow_node, loop, agent_definition,
            context.agent_store, approval_context=context.grants,
        )
        yield build_workflow(node)
```

Reconstruct the original complete Workflow and Agent definitions, retaining the approval node's state key. Copying only a name/version while changing node behavior is not sufficient. Factories are explicitly trusted local Python and may have side effects; this is not a sandbox or permission-isolation boundary. The framework does not infer whether arbitrary factory code faithfully uses its supplied stores/grants.

Read the reference with `workflow-approvals`, separately review the actual tool action and arguments, then run:

```sh
wagent checkpoint workflow-approve-resume parent-run \
  --workflow-factory my_workflows:approved --node writer \
  --agent-run agent-child-id --agent-name coding \
  --approve-tool-call call-id --tool-name write_file \
  --state-root .wagent --grant-permission files.write \
  --confirm-workflow-code --confirm-approval --confirm-resume --json
```

The three confirmations independently authorize Python import/assembly, the exact current tool call, and parent execution including potentially billable model calls and subsequent nodes. Repeat `--grant-permission` as needed; no permissions are granted by default. Optional `--agent-state-root`, repeatable `--state-key`, and `--enable-pause-control` follow the review/recovery interfaces. Unknown or stale references fail before factory import; absent state directories are not initialized.

After assembly, the service compares complete parent/child checkpoint snapshots and link status again, then creates a one-shot grant with a default 300-second lifetime and resumes the parent. Completion, cancellation, and factory entry/exit failures clear residual authority; grants are also cleared before resource cleanup. A SQLite-requested pause clears unused authority without clearing the request. Output uses the Workflow summary without model content, state bodies, or tool arguments and does not claim the selected tool executed.

These checks are not a cross-store atomic transaction and do not defend against another process rewriting state concurrently. Trusted local storage and a single execution owner remain required. After errors, cleanup failures, or uncertain side effects, inspect checkpoints instead of retrying automatically. Python API hosts own code/action/execution authorization; CLI confirmations do not authorize other entry points implicitly.

### TUI approval and parent recovery (a6, focused regressions passed)

Checkpoints uses the same public factory service rather than introducing UI-owned authority semantics:

1. Select the parent Workflow run/state root, optional separate Agent root and custom state keys, then review links read-only. Review does not automatically select a pending call.
2. Separately review the actual action and arguments. Fill in the factory `module:attribute`, exact node, child run, Agent name, call ID, tool name, and operation permissions. Ordinary Workflow Entries are not used by this path.
3. Enter `LOAD WORKFLOW`, `APPROVE <Call ID>`, and `RESUME WORKFLOW` independently, then click “Approve exact call and resume parent”. A matched snapshot replaces none of these confirmations.

After local form validation, all three confirmations are consumed, even if later checkpoint validation, import, or execution fails. The UI reuses the ordinary recovery worker, task lock, and pause button. Both recovery forms are locked while active; captured root/run/call/permissions cannot be redirected by later form changes. Factory import/initialization is still developer Python: an async background worker cannot make arbitrary blocking synchronous code responsive.

Optional synchronous-node threading and SQLite-source composition still apply. Cancellation/exit follows factory and grant cleanup; UI-owned requests are cleared, external durable requests are not. Failures display exception types only; results/events hide tool arguments, model content, and state bodies. A pause does not prove the selected tool executed. Review remaining approvals again and enter fresh confirmations for each recovery. The UI does not batch-approve, resume children independently, or retry uncertain execution automatically.

### Unfinished-node execution semantics

New `WorkflowNodeResult(pause=True, suspend=True, state_updates=...)` commits recoverable state without new output, completing the node, or choosing a successor. Output and transition targets are prohibited on this result. It emits `node-suspended`, not `node-completed`. Existing ordinary `pause=True` semantics are unchanged.

- DAG recovery revisits the unfinished node; a state graph stays on its current node; Python Workflow invokes the same handler again and increments `resume_count`, still bounded by `max_resumes`.
- Concurrent DAG batches drain all nodes. Successful siblings commit normally; suspended nodes remain unfinished and do not unlock dependents. State-key conflicts, sibling failure, or cancellation still leave the whole batch `RESUMING` without automatic replay.
- Only a completed child Agent reaches the result mapper and commits node output. Its reference key becomes `None`, allowing a later state-graph visit to start a new child run.
- The stores do not commit atomically. A child checkpoint saved before a failed parent commit, or interruption after a child tool side effect, still requires manual diagnosis. Recovery never repairs/deletes child checkpoints or retries uncertain effects. Reaching a parent execution limit does not automatically clean up child runs either.
- Checkpoint JSON retains existing fields, but the new `node-suspended` event requires a reader supporting this increment. Do not read or recover new logs with old versions. Focused regressions have passed.

## Cancellation and events

`CancellationToken` is checked at node boundaries and passed into `WorkflowNodeContext` for cooperative checks inside asynchronous nodes. A handler should check cancellation before starting expensive work. Cancellation during a node is also treated as uncertain execution and is never replayed automatically.

Events use a continuous per-run sequence:

- `workflow-started` / `workflow-resumed`
- `node-started` / `node-completed` / `node-failed`
- `node-suspended` (`2.0.0a5`)
- `workflow-paused` / `workflow-completed`

Event data does not automatically include inputs, outputs, or exception messages, avoiding default persistence of prompts and credentials. Custom stores and observability plugins must preserve the same safety boundary.

## Replacement and composition

Applications may replace the entire `WorkflowEngineProtocol` or `WorkflowStore`. Any node may also call the public `AgentLoop`, model, tool, or application-service APIs.

`agent_workflow_node()` converts workflow input into a user message by default, accepts only `COMPLETED` agent results, and returns JSON-persistable output, stop reason, and token usage. Its message factory, tool-authority context, result mapping, and accepted stop reasons are replaceable. A non-completed result fails the node by default so approval or budget stops are not mistaken for success.

`workflow_start_tool()` and `workflow_resume_tool()` bind one fixed definition. By default they return run/checkpoint identifiers, public output, and stop status without exposing internal state to the model; callers can replace the result mapper. They declare `WRITE` effects and require `workflow.execute` by default, so application-granted permission and per-call approval still apply. Cancellation propagates into the workflow. A paused result is never resumed automatically; the agent explicitly invokes the resume tool or the application takes over. These adapters neither implement nested workflows nor automatically join agent and workflow checkpoints.
