# Workflow 与节点恢复

[English](./workflows.en.md) | 简体中文

## 状态

`Implemented`：当前 `2.0.0a1` 源码提供三种 Workflow 定义、统一引擎协议、确定性本地执行、节点事件、协作式取消、内存/JSONL 节点边界暂停恢复，以及 Agent/Workflow 双向适配器。

`Planned`：并行 DAG 调度、Agent 审批与 Workflow 暂停的自动级联恢复、运行中的外部暂停句柄和通用 Session 投影。

`Reserved`：嵌套或分布式 Workflow、多 Agent 编排和任意 Python 指令栈恢复。

## 公共组件

| 组件 | 作用 |
|---|---|
| `DagWorkflowDefinition` | 声明节点和依赖；构造时拒绝未知节点与环 |
| `StateGraphDefinition` | 声明入口、默认转移和最大步骤数；节点可动态选择下一节点 |
| `PythonWorkflowDefinition` | 把同步或异步 Python 处理器作为显式可恢复边界 |
| `WorkflowNodeResult` | 返回输出、状态增量、下一节点或暂停请求 |
| `WorkflowEngineProtocol` | 可替换引擎的 `start()` / `resume()` 协议 |
| `LocalWorkflowEngine` | 内置的确定性顺序执行器 |
| `WorkflowRegistry` | 通过共享微内核 Registry 按名称、版本和 Scope 注册定义 |
| `WorkflowStore` | 可替换事件与 Checkpoint 存储协议 |
| `InMemoryWorkflowStore` | 进程内开发与测试存储 |
| `JsonlWorkflowStore` | 单一本地所有者使用的持久化存储 |
| `agent_workflow_node()` | 把固定 Agent Loop/Definition 适配为 Workflow 节点 |
| `workflow_start_tool()` / `workflow_resume_tool()` | 把固定 Workflow 适配为受治理的 Agent 工具 |

所有公共类型直接从 `w_agent` 导出，不使用 `w_agent.v2`。

`WorkflowRegistry` 使用 `workflow.definition` 能力，与模型和工具注册共用底层 `Registry`。注册版本必须与 Definition 的 `version` 一致；解析支持相同的版本约束和层级 Scope。

## DAG 示例

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

节点按照定义顺序中第一个依赖已满足的节点执行，因此结果可重复。当前引擎不会并行执行互不依赖的节点。

## 状态图

节点可以通过 `WorkflowNodeResult(next_node="name")` 覆盖静态转移。没有动态目标时，引擎使用 `transitions[current]`；没有转移表示完成。`max_steps` 对循环图提供硬边界。

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

## Python 入口和显式暂停

Python Workflow 不序列化函数帧。处理器返回 `pause=True` 后，引擎保存输入、状态、输出、元数据和 `resume_count`；恢复会从函数入口重新调用处理器。

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

# 进程重启后使用相同名称、版本和类型的定义：
resumed = await LocalWorkflowEngine(
    JsonlWorkflowStore(".wagent-state")
).resume(workflow, "review-1")
```

持久化输入、状态、输出和元数据必须是 JSON 可编码值。需要保存自定义类型时，应替换 `WorkflowStore`，或在节点边界显式编码。

## Checkpoint 安全语义

```text
READY / PAUSED → claim → RESUMING → 节点完成 → READY / PAUSED
                                  └→ 中断/失败 → 保持 RESUMING
```

- 执行节点前，Store 原子地把当前进程内 Checkpoint claim 为 `RESUMING`。
- 只有处理器返回并成功记录节点结果后，状态才回到 `READY` 或 `PAUSED`。
- 若进程在节点内部中断，框架无法判断外部副作用是否已经发生，因此 `resume()` 抛出 `WorkflowResumeConflictError`，不会静默重复节点。
- `JsonlWorkflowStore` 面向单一本地生命周期所有者；它不是分布式锁或多主调度器。
- Workflow 名称、版本或类型发生变化时，恢复被拒绝。行为变更应使用新的 `version`。

成功完成和达到步骤上限是终止状态，Checkpoint 会删除；显式暂停和边界取消保留可恢复 Checkpoint。节点失败会返回不含异常文本的稳定失败码，并保留 `RESUMING` 状态供人工诊断。

## 取消与事件

`CancellationToken` 在节点边界检查，并传入 `WorkflowNodeContext` 供异步节点协作检查。节点处理器应在发起昂贵操作前调用自己的取消检查。节点执行中的取消也按不确定执行处理，不自动重放。

事件按 Run 使用连续序号追加：

- `workflow-started` / `workflow-resumed`
- `node-started` / `node-completed` / `node-failed`
- `workflow-paused` / `workflow-completed`

事件数据不自动包含输入、输出或异常正文，避免默认记录 Prompt 和凭据。自定义 Store 和可观测插件仍必须遵守同一安全边界。

## 替换与组合

应用可以替换整个 `WorkflowEngineProtocol` 或 `WorkflowStore`，也可以让任意节点调用公开的 `AgentLoop`、模型、工具或其他应用服务。

`agent_workflow_node()` 默认把 Workflow 输入转为用户消息，只接受 `COMPLETED` Agent 结果，并返回 JSON 可持久化的输出、停止原因和 Token 用量；消息工厂、工具权限上下文、结果映射和可接受停止原因都可替换。非完成状态默认使节点失败，避免把审批或预算停止误当成功。

`workflow_start_tool()` 和 `workflow_resume_tool()` 固定绑定一个 Definition，默认只返回运行/Checkpoint 标识、公开输出和停止状态，不把内部 State 自动暴露给模型；需要时可替换结果映射。两者默认声明 `WRITE` 副作用并要求 `workflow.execute` 权限，所以仍需应用授予权限和逐调用批准；调用取消会传给 Workflow。暂停结果不会自动恢复，Agent 必须显式调用恢复工具或由应用接管。适配器不实现嵌套 Workflow，也不会自动串联 Agent Checkpoint 与 Workflow Checkpoint。
