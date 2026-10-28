# Workflow 与评测知识装配

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

状态：2.0.0 Experimental，已随 2.0.0 发布。离线测试覆盖实际 Workflow Engine → Agent Loop → Mock Provider 及本地评测运行器。CLI/TUI 显式知识评测接线见下文；不会自动发现在线服务或新增持久化后端。

## Workflow

`knowledge_workflow_node` 将显式绑定的检索器装配为普通 Workflow 节点；`knowledge_workflow_messages` 为既有 `agent_workflow_node` 提供消息工厂。默认 Workflow input 必须是字符串查询。结构化输入使用宿主提供的 `query=lambda context: context.input["question"]`，两个适配器应使用同一查询函数。

```python
from w_agent.knowledge_workflow import knowledge_workflow_node, knowledge_workflow_messages
from w_agent.workflows import (
    DagWorkflowDefinition, LocalWorkflowEngine, WorkflowContext, agent_workflow_node,
)

# binding: LocalKnowledgeBinding；loop/definition: 已装配的 Agent。
retrieve = knowledge_workflow_node("retrieve", binding)
answer = agent_workflow_node(
    "answer", loop, definition,
    messages=knowledge_workflow_messages("retrieve", binding),
)
workflow = DagWorkflowDefinition(
    "knowledge-answer", (retrieve, answer), {"answer": ("retrieve",)},
)
# await LocalWorkflowEngine().start(workflow, WorkflowContext("run-1", input="退款政策"))
```

检索结果是 JSON 可序列化的 `wagent-workflow-knowledge-v1` 数据，保留 ID、标题、正文、来源。消息工厂重新验证输出，将证据放入标记为不可信参考的 USER 消息，随后追加本次问题；不把文档当作系统指令。不命中时只发送问题。必须声明检索节点依赖，缺失输出、错误结果、超时或超限会在 Agent 启动前失败。

Workflow 输出、事件或检查点可能保存完整检索正文，宿主需要选择适当的存储与数据权限。适配器不会从输入/元数据发现 provider 或授予权限，也不会再次执行检索。Workflow 原有审批、取消、存储和节点恢复机制保持有效；外部检索的端点与费用授权由宿主在启动前完成。

## 评测

`knowledge_evaluation_target` 返回既有 `LocalEvaluationRunner` 的 target。每个用例使用 `case.prompt` 查询，创建新的 Run ID 和空历史上下文，不将上一用例输出带入下一用例。不会持久化 Session。

```python
from w_agent.evaluation import EvaluationCase, ExactTextScorer, LocalEvaluationRunner
from w_agent.knowledge_evaluation import knowledge_evaluation_target

target = knowledge_evaluation_target(loop, definition, binding)
cases = (EvaluationCase("refund", "退款期限是多少？", "七天"),)
# report = await LocalEvaluationRunner().run(cases, target, scorers=(ExactTextScorer(),))
```

默认工具权限和已审批调用 ID 为空，数据集 metadata 不会成为权限或 Run metadata。宿主可显式传入 `scope`、`cancellation` 与 `tool_context(case)` 工厂。构造 target 不执行查询，执行 target 才调用已注入的检索器及 Agent。构造的 Agent/Provider、检索器和存储生命周期仍由宿主管理。

评测报告沿用既有评分、停止原因、Agent token/费用及默认隐藏输出的序列化规则。检索失败会成为失败用例且 Agent 不启动；asyncio 取消向上传播。Agent token/费用统计不包含检索、嵌入或外部重排费用，仍需宿主独立计量。检索器本身可替换为 [BM25/混合/重排](knowledge-retrieval.md)，没有默认在线调用。

验证入口：`py -3.11 -m pytest tests/test_knowledge_workflow_evaluation.py tests/test_knowledge_retrieval.py`。验收包括实际离线模型收到带来源 USER 证据、两用例隔离、无元数据权限提升、失败阻止下游 Agent、检查点内容复核及取消清理。

## CLI/TUI 知识评测入口

工作区继续增量（已随 2.0.0 发布）：既有 `evaluate` 命令和 Evaluation 页已接知识目录，无需用户另写评测循环。配置仍使用 `knowledge: {"binding": "manual"}`，目录工厂沿用[知识宿主](./knowledge-runtime.md)。

```powershell
wagent evaluate cases.json --config .wagent/config.json --knowledge-entry my_host:knowledge --confirm-knowledge-code --confirm-knowledge-queries --confirm-model-call --json
```

三种授权彼此独立：执行宿主 Python 代码、对整批每个 `case.prompt` 检索并向模型发送证据、调用模型。工具与共享预算工厂另用原有授权。整批问题在任何知识/工具工厂导入前预检，每条最多 4096 UTF-8 字节；数据集不能指定其他查询、Provider、权限或授权。目录对一批只打开一次，结束或异常时关闭；每例创建新 Session/Run、禁用历史，检索失败记录为错误用例，不静默转成无知识回答。

TUI Evaluation 填 Knowledge host，分别输入 `LOAD KNOWLEDGE`、`QUERY ALL CASES`，再按原入口输入 `EVALUATE`。知识确认在尝试时清除。评测运行中会置忙碌状态，禁止同时替换插件；取消会复位。模型结果默认不展示正文，图片/音频展示仍由 Replay 页的独立披露控制。

CLI JSON、持久报告的 `accounting_scope` 及 TUI 汇总明确标记：只统计模型 Run，不包含检索/Embedding/外部重排费用。`JsonEvaluationReporter(accounting_scope=...)` 是可选报告标签，不补造计量。指定 `--state-root` 会按既有 Runtime 规则持久化用例 Session/运行记录，可能含敏感数据；不指定时使用临时状态。与上面的 Python `knowledge_evaluation_target` 无持久 Session 模式不同。

本轮相关验证：`tests/test_knowledge_evaluation_ui.py` 覆盖实际离线 Provider/Runtime 的 CLI/TUI 两例独立检索、整批预检、三项授权、失败禁止模型调用、工厂清理、报告计量边界及取消复位。此新增入口不在此前 1811 项统一结果内；本轮定向结果另记，不代表真实服务/检索质量验收。
