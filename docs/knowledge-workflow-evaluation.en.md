# Knowledge assembly for Workflow and evaluation

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

Status: workspace Experimental, published in 2.0.0. Offline tests exercise the actual Workflow Engine → Agent Loop → mock provider and local evaluation runner. Explicit CLI/TUI evaluation wiring is described below; no automatic online service or persistence-backend discovery is added.

## Workflow

`knowledge_workflow_node` adapts an explicit retrieval binding into an ordinary Workflow node. `knowledge_workflow_messages` supplies the message factory for existing `agent_workflow_node`. Workflow input must be a query string by default. Structured inputs use a host callback such as `query=lambda context: context.input["question"]`; use the same callback for both adapters.

```python
from w_agent.knowledge_workflow import knowledge_workflow_node, knowledge_workflow_messages
from w_agent.workflows import (
    DagWorkflowDefinition, LocalWorkflowEngine, WorkflowContext, agent_workflow_node,
)

# binding: LocalKnowledgeBinding; loop/definition: an assembled Agent.
retrieve = knowledge_workflow_node("retrieve", binding)
answer = agent_workflow_node(
    "answer", loop, definition,
    messages=knowledge_workflow_messages("retrieve", binding),
)
workflow = DagWorkflowDefinition(
    "knowledge-answer", (retrieve, answer), {"answer": ("retrieve",)},
)
# await LocalWorkflowEngine().start(workflow, WorkflowContext("run-1", input="refund policy"))
```

Retrieval outputs use the JSON-serializable `wagent-workflow-knowledge-v1` format, preserving ID, title, body, and source. The message factory revalidates outputs, places evidence in a USER message labeled as untrusted reference data, then appends the current question. Documents never become system instructions. Empty retrieval sends only the question. Declare the retrieval dependency explicitly; missing outputs, invalid results, timeouts, and bounds failures prevent the dependent Agent from starting.

Workflow outputs, events, or checkpoints may retain full retrieved text. Hosts choose suitable storage and access policies. The adapters do not discover providers or grant permissions from input/metadata. Message preparation does not repeat retrieval. Existing Workflow approval, cancellation, storage, and node recovery continue to apply; hosts authorize external retrieval endpoints and costs before execution.

## Evaluation

`knowledge_evaluation_target` returns a target for existing `LocalEvaluationRunner`. Each case queries using `case.prompt`, creates a fresh Run ID and empty history, and never carries one case's answer into another. It does not persist Sessions.

```python
from w_agent.evaluation import EvaluationCase, ExactTextScorer, LocalEvaluationRunner
from w_agent.knowledge_evaluation import knowledge_evaluation_target

target = knowledge_evaluation_target(loop, definition, binding)
cases = (EvaluationCase("refund", "What is the refund deadline?", "Seven days"),)
# report = await LocalEvaluationRunner().run(cases, target, scorers=(ExactTextScorer(),))
```

Default tool permissions and approved call IDs are empty. Dataset metadata becomes neither authority nor Run metadata. Hosts can explicitly supply `scope`, `cancellation`, and a `tool_context(case)` factory. Target construction does not query; target execution invokes the injected retriever and Agent. Hosts retain lifecycle ownership of Agent/providers, retrievers, and stores.

Reports retain existing scoring, stop-reason, Agent token/cost accounting, and output-hidden serialization defaults. Retrieval failure records a failed case without starting the Agent; asyncio cancellation propagates. Agent token/cost totals exclude retrieval, embedding, and external reranker costs, which hosts must account for separately. The retriever can be replaced with [BM25/hybrid/reranking](knowledge-retrieval.en.md); no online calls are enabled by default.

Run `py -3.11 -m pytest tests/test_knowledge_workflow_evaluation.py tests/test_knowledge_retrieval.py`. Acceptance covers an actual offline model receiving USER evidence with sources, independent cases, metadata authority isolation, downstream Agent suppression on retrieval failure, checkpoint content revalidation, and cancellation cleanup.
## Knowledge evaluation CLI/TUI entry points

Included in 2.0.0 follow-up: the existing `evaluate` command and Evaluation page now accept a knowledge catalog. Keep `knowledge: {"binding": "manual"}` in configuration and use the existing [knowledge host](./knowledge-runtime.en.md).

```powershell
wagent evaluate cases.json --config .wagent/config.json --knowledge-entry my_host:knowledge --confirm-knowledge-code --confirm-knowledge-queries --confirm-model-call --json
```

Host Python code, all-case retrieval/evidence disclosure, and model calls require independent consent. Tool and shared-budget factories retain their own approvals. Every prompt is preflighted before any knowledge/tool factory import, with a 4096 UTF-8 byte limit per query. Dataset metadata cannot provide alternate queries, providers, permissions or grants. One catalog context serves the batch and closes on completion/error. Each case uses a fresh Session/Run with history disabled; retrieval failure becomes an error case without model-only fallback.

In TUI Evaluation, enter the Knowledge host and separate `LOAD KNOWLEDGE`, `QUERY ALL CASES`, then the existing `EVALUATE`. Knowledge approvals are consumed per attempt. Evaluation marks the app busy to block plugin replacement and resets on cancellation. Reports hide model outputs by default; media remains independently disclosed in Replay.

CLI JSON, saved reports (`accounting_scope`) and the TUI summary explicitly exclude retrieval/Embedding/external-reranker costs from model-Run totals. Optional `JsonEvaluationReporter(accounting_scope=...)` labels scope; it does not invent usage. `--state-root` persists sessions/run records under existing Runtime rules and may contain sensitive data; otherwise state is temporary. This differs from the Python `knowledge_evaluation_target` above, which does not persist sessions.

New `tests/test_knowledge_evaluation_ui.py` covers real offline Runtime/Provider CLI/TUI case isolation, batch preflight, independent approvals, retrieval-failure model suppression, cleanup, accounting scope and cancellation. This follow-up is not part of the earlier 1811-test result; focused results are recorded separately and do not establish live-service/retrieval-quality acceptance.
