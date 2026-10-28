# Workflow 与节点恢复

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./workflows.en.md) | 简体中文

## 状态

`Implemented`：`2.0.0a1` 提供三种 Workflow 定义、统一引擎协议、确定性本地执行、节点事件、协作式取消、内存/JSONL 节点边界暂停恢复，以及 Agent/Workflow 双向适配器。`2.0.0a4` 另外提供脱敏 Checkpoint 汇总、显式 Workflow 入口加载和精确版本恢复；这些增量已纳入 2.0.0 源码，已随 2.0.0 发布。

`Experimental`（`2.0.0a4`）：`LocalWorkflowEngine(max_parallel_nodes=N)` 提供显式启用、有界的异步 DAG 前沿并行，默认 `N=1` 保持原顺序行为。

`2.0.0a4`另提供 `WorkflowNodeInvoker`，可单独替换节点调用方式；`ThreadedWorkflowNodeInvoker` 显式把同步处理器放入线程执行，异步处理器仍在事件循环运行。

`2.0.0a4`还提供按 Run ID 控制的 `WorkflowPauseController` 与可替换 `WorkflowPauseSource`，在节点或并行批边界响应外部暂停请求。

`Planned`：通用 Session 投影。反向工具续执行桥已加入`2.0.0a6`（针对性回归通过），见下文。`2.0.0a5`已补 Workflow 内 Agent 的显式审批恢复模板（`2.0.0a5`，针对性回归通过），详见下文。TUI 本界面恢复任务的后台运行、边界暂停与可选线程调用已进入`2.0.0a4`。

`Reserved`：嵌套或分布式 Workflow、多 Agent 编排和任意 Python 指令栈恢复。

## 公共组件

| 组件 | 作用 |
|---|---|
| `DagWorkflowDefinition` | 声明节点和依赖；构造时拒绝未知节点与环 |
| `StateGraphDefinition` | 声明入口、默认转移和最大步骤数；节点可动态选择下一节点 |
| `PythonWorkflowDefinition` | 把同步或异步 Python 处理器作为显式可恢复边界 |
| `WorkflowNodeResult` | 返回输出、状态增量、下一节点或暂停请求 |
| `WorkflowEngineProtocol` | 可替换引擎的 `start()` / `resume()` 协议 |
| `LocalWorkflowEngine` | 默认顺序执行；可显式开启有界 DAG 前沿并行 |
| `WorkflowNodeInvoker` | 可替换的单次节点调用协议，不承担调度、重试或状态提交 |
| `WorkflowPauseSource` / `WorkflowPauseController` | 可替换的暂停请求查询协议与线程安全的进程内控制器 |
| `InlineWorkflowNodeInvoker` / `ThreadedWorkflowNodeInvoker` | 默认原线程调用与可选同步线程执行模板 |
| `WorkflowRegistry` | 通过共享微内核 Registry 按名称、版本和 Scope 注册定义 |
| `WorkflowStore` | 可替换事件与 Checkpoint 存储协议 |
| `WorkflowCheckpointCatalog` | 与稳定 Store 分离的可选 Checkpoint 发现协议 |
| `InMemoryWorkflowStore` | 进程内开发与测试存储 |
| `JsonlWorkflowStore` | 单一本地所有者使用的持久化存储 |
| `WorkflowCheckpointSummary` | 不含输入、状态、输出、Scope 或 Metadata 值的恢复发现投影 |
| `load_workflow_entry()` / `load_workflow_entries()` | 在应用明确授权后导入 `module:attribute` Definition |
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

默认按定义顺序执行第一个依赖已满足的节点。需要并发执行相互独立的异步节点时，宿主可显式设置 `LocalWorkflowEngine(max_parallel_nodes=2)`；每批最多启动两个就绪节点，后继节点仅在整批结果提交后开始。默认同步处理器仍在事件循环线程运行；可通过下方调用策略启用线程执行。

同批处理器看到相同的已提交 `state` 与 `outputs` 快照；它们不能依赖同批兄弟节点的新输出。结果按 Definition 顺序合并，两个节点写入同一个状态键会以 `parallel-state-conflict` 失败，而不会暗中覆盖。处理器也应避免原地修改状态/输出中的嵌套可变对象。任一节点请求暂停时，其余已启动节点仍会完成，暂停发生在批边界。批中失败、冲突或取消均保留 `RESUMING` Checkpoint；因为无法确认各节点外部副作用，恢复不会自动重放该批。

## 可替换节点调用策略

```python
from w_agent import LocalWorkflowEngine, ThreadedWorkflowNodeInvoker

engine = LocalWorkflowEngine(
    max_parallel_nodes=2,
    node_invoker=ThreadedWorkflowNodeInvoker(),
)
```

默认 `InlineWorkflowNodeInvoker` 保留原线程行为。线程模板通过 `asyncio.to_thread` 将同步函数和同步可调用对象交给事件循环的默认线程池，并复制 ContextVar 上下文；异步函数、异步 `__call__` 和同步工厂返回的 Awaitable 均在事件循环等待。`max_parallel_nodes` 限制单次 DAG Run 的批大小，不是多个 Run 共享的全局线程配额。状态图和 Python Workflow 也使用同一调用策略，但仍按自身顺序调度。

Python 无法强制终止已经运行的线程。Task 取消会等待同步调用退出，丢弃其结果并传播取消；取消后才返回的未启动 Coroutine 会被关闭。等待期间 Checkpoint 保持 `RESUMING`，取消不会让该节点变为可自动重放。如果同步调用永久阻塞，取消收尾也会一直等待；处理器应为外部 I/O 设置自身超时。原有 `CancellationToken` 的节点边界语义保持不变，并行批仍监听取消令牌；线程处理器不要直接调用事件循环对象的非线程安全方法。

线程模板在宿主进程执行，不提供沙箱隔离；节点内部需要隔离的操作仍应显式使用 SandboxProvider。处理器应通过返回值更新 Workflow 状态，不能原地修改共享嵌套对象。调用策略不序列化到 Checkpoint，恢复进程应重新装配所需策略；CLI/TUI 默认引擎继续采用 Inline 策略。应用自定义 `WorkflowNodeInvoker.invoke(node, context)` 应只调用一次处理器，等待其结果并传播错误/取消；结果规范化、状态合并和 Checkpoint 由引擎负责。

## 应用请求暂停

```python
from w_agent import WorkflowPauseController

control = WorkflowPauseController()
engine = LocalWorkflowEngine(pause_source=control)
running = asyncio.create_task(
    engine.start(workflow, WorkflowContext("run-controlled"))
)
# 宿主的按钮、命令处理器或其他线程可发出精确 Run 请求：
control.request_pause("run-controlled")
result = await running
if result.stop_reason.value == "paused":
    control.clear("run-controlled")
    result = await engine.resume(workflow, "run-controlled")
```

请求可以在启动前设置，也可以在运行中设置。控制器不会中断当前节点；并行 DAG 会等待本批全部节点完成并提交，再在下一批之前暂停。正常暂停保存 `PAUSED` Checkpoint 并追加 `workflow-paused` 事件，事件数据仅包含 `source=external-request`。恢复不会重复已提交节点。若已无后续节点则正常完成；步骤上限、取消或节点失败仍按原语义处理，不会被暂停掩盖。Python Workflow 只在函数调用边界响应，不能从函数中间恢复。

请求按精确 Run ID 隔离，在 `clear()` 前持续有效；清除只解除请求，不执行恢复。控制器不检查 Run 是否存在，不持久化请求，也不自动清除已结束 Run 的请求，生命周期由应用管理。同一控制器应只用于同一 Store 的 Run 命名空间。进程重启后持久化的 `PAUSED` Checkpoint 仍可由现有恢复入口恢复，但需要重新装配请求源。应用可实现快速、非阻塞的 `is_pause_requested(run_id) -> bool` 替换控制器；不修改稳定的执行协议或 Checkpoint 格式。

启用请求源时，引擎在调度边界让出一次事件循环，使宿主协程有机会设置请求；默认 Inline 同步节点仍可能阻塞事件循环，可按需选择线程调用模板。请求在边界检查之后才到达时，将在下一个边界生效。`2.0.0a4`的 TUI 恢复入口使用后台任务，并提供针对本次 State Root/Run ID 的暂停按钮和默认关闭的同步线程选项。界面区分“请求等待”与引擎返回的“已暂停”，任务结束时清理本次控制器；再次恢复仍需新的授权。`2.0.0a5`新增的 SQLite 与 CLI 跨进程请求入口见下文（`2.0.0a5`，针对性回归通过）；已有 Checkpoint 列表和恢复可以处理边界暂停结果。

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

## 脱敏发现与显式恢复

`WorkflowCheckpointCatalog.list_checkpoints()` 返回按 Run ID 稳定排序的 `WorkflowCheckpointSummary`。发现能力与稳定的 `WorkflowStore` 执行协议分离，因此旧自定义 Store 不会被迫实现新方法。摘要仅包含 Workflow 名称、版本、类型、状态、节点标识与计数；不包含持久化的 Input、State、Output、Scope 或 Metadata 值。`InMemoryWorkflowStore` 与 `JsonlWorkflowStore` 同时实现这两个协议。

开发者 Definition 必须通过单独授权后调用 `load_workflow_entry()` / `load_workflow_entries()` 才会导入。Checkpoint 或配置文件不能自动触发 Python Import。加载器按 `(name, version)` 建立 Catalog，拒绝重复身份；恢复前引擎还会再次核对 Definition 的名称、版本和类型。

```python
store = JsonlWorkflowStore(".wagent")
summaries = await store.list_checkpoints()

# 只有宿主已经向用户确认执行开发者 Python 代码后才调用：
catalog = load_workflow_entries(("my_workflows:definitions",))
checkpoint = await store.load_checkpoint("review-1")
definition = catalog[(checkpoint.workflow_name, checkpoint.workflow_version)]
result = await LocalWorkflowEngine(store).resume(definition, checkpoint.run_id)
```

CLI 提供 `wagent checkpoint workflow-list` 和 `workflow-resume`。恢复必须同时传入 `--workflow-entry`、`--confirm-workflow-code` 与 `--confirm-resume`；TUI 使用独立的 `LOAD WORKFLOW` 和 `RESUME WORKFLOW` 一次性确认。两者都允许明确选择 State Root，因此可恢复不同本地 Store Root 中的 Run，但不会复制、合并或自动迁移 Store。CLI/TUI 结果默认隐藏运行时值。`RESUMING` 表示节点副作用不确定，仍会失败关闭并要求人工诊断。

## 本地跨进程暂停（`2.0.0a5`，针对性回归通过）

`2.0.0a5`新增可替换的 `SQLiteWorkflowPauseController`，已包含于该版本并通过针对性回归。它使用 Python 标准库 SQLite，不需要服务端、租户或后台轮询进程。

```python
from w_agent import JsonlWorkflowStore, LocalWorkflowEngine, SQLiteWorkflowPauseController

control = SQLiteWorkflowPauseController(".wagent")
engine = LocalWorkflowEngine(JsonlWorkflowStore(".wagent"), pause_source=control)
# 使用 engine.start(...) 或 engine.resume(...)；另一进程使用相同 State Root。
```

CLI 恢复默认不读取跨进程请求。显式启用后，可在另一终端写入请求：

```sh
# 终端 A：启动已有 Checkpoint 的恢复，授权仍须单独给出。
wagent checkpoint workflow-resume review-1 --state-root .wagent --workflow-entry my_workflows:definitions --confirm-workflow-code --confirm-resume --enable-pause-control
# 终端 B：请求暂停并读取当前状态，不导入或执行 Workflow 代码。
wagent checkpoint workflow-pause review-1 --state-root .wagent --confirm-pause --json
wagent checkpoint workflow-pause-status review-1 --state-root .wagent --json
# 确认原执行者已退出且 Checkpoint 可恢复后，清除请求；随后重新运行终端 A 命令。
wagent checkpoint workflow-pause-clear review-1 --state-root .wagent --confirm-clear --json
```

- 请求按精确 Run ID 写入同一 State Root 的 `workflow-control.sqlite3`，支持重复请求，其他 Run/Root 不受影响。CLI 拒绝对不存在 Checkpoint 的 Run 写入请求；底层 Python 模板允许启动前预设。
- 请求成功只表示事务已写入，返回 `execution_acknowledged=false`；不会修改 Checkpoint。只有监听该源的引擎才会在下个已提交节点/批边界暂停。正在执行的节点不会被强杀，最后一个节点完成后也可能直接终止。
- 状态命令分别返回请求标志和 Checkpoint 状态，二者不是原子快照，也不证明进程存活。`RESUMING` 可能正在执行，也可能遗留于故障；它不因此变得可恢复。
- 请求持久化到显式清除为止；引擎结束、恢复或命令退出不会自动清除，以免覆盖后来请求。清除不启动执行、不修改 Checkpoint；保留请求时再次启用监听恢复仍会在边界暂停。
- 每次操作使用独立连接和参数化 Run ID，SQLite 事务协调请求写入/清除。边界查询有本地文件 I/O，锁等待上限为 100 ms；锁冲突、损坏或读取失败抛出 `WorkflowPauseControlError`，不会假装没有暂停请求并执行下一节点。
- 仅面向可信本地目录和单一 Workflow 执行所有者，不是多主调度锁、网络文件系统协议或针对同账户其他进程的安全隔离。不要同时从多个进程恢复同一 Run。

### TUI 接入与请求源组合（`2.0.0a5`，针对性回归通过）

Checkpoints 页新增默认关闭的 “Observe cross-process SQLite pause requests” 选项。勾选后，本次恢复同时响应本界面暂停按钮与所选 State Root 下的 SQLite 请求。开始恢复时固定 State Root、Run ID 和监听选项，运行中锁定这些控件；程序化修改表单也不会重定向已开始的恢复。

本界面的暂停按钮只设置当前进程的临时请求，不写入 SQLite。后台任务结束、失败或取消时，只清理本界面请求；不会清理持久化请求。启用监听后，未清除的持久化请求会让再次恢复仍在边界暂停。用前述 CLI 明确查看并清除请求，再提供新的加载和恢复授权。禁用监听时，SQLite 中已有的请求不会改变此 TUI 恢复的执行行为。

公开模板 `AnyWorkflowPauseSource(*sources)` 按参数顺序执行只读 OR 查询，在第一个 `True` 处短路；实际访问到的源抛错或返回非 `bool` 时向上传播错误，不会继续节点。它不调用 `clear()`，也不负责授权、原子跨源快照或执行所有权。所有源应指向同一 Run 命名空间，可自由组合自定义实现：

```python
from w_agent import AnyWorkflowPauseSource, WorkflowPauseController

local = WorkflowPauseController()
combined = AnyWorkflowPauseSource(local, SQLiteWorkflowPauseController(".wagent"))
engine = LocalWorkflowEngine(JsonlWorkflowStore(".wagent"), pause_source=combined)
```

TUI 状态显示的是本次监听模式、界面请求是否待处理与引擎停止结果，不持续轮询外部请求，也不声称一次暂停来自哪个进程。SQLite 读取失败会结束当前恢复并保留 Checkpoint，不会自动删除或修复控制文件。

## Workflow 内的 Agent 审批级联（`2.0.0a5`，针对性回归通过）

`2.0.0a5`新增 `approval_agent_workflow_node()`，不替换原有 `agent_workflow_node()`。后者仍默认仅接受 Agent 正常完成。新模板面向 Workflow 节点内嵌 Agent 的方向；跨 Store 原子事务仍未实现；双层审批协调服务已加入`2.0.0a6`（针对性回归通过）。`2.0.0a6`的 CLI/TUI 显式工厂恢复入口见下文，不属于 a5。

`2.0.0a6`已补通用 `ToolContinuation`、ReAct schema 2 票据持久化，以及下述 Workflow 专用引用与续执行桥（针对性回归通过）；双层授权协调服务已加入`2.0.0a6`（针对性回归通过），TUI 引导亦已加入`2.0.0a6`（针对性回归通过）。原有 `workflow_start_tool()` / `workflow_resume_tool()` 行为不变，不会自动获得反向挂起能力。

### Agent 工具内的 Workflow 续执行（`2.0.0a6`，针对性回归通过）

`resumable_workflow_tool(engine, definition, store)` 返回独立的 `ToolBinding`，通过公开 `ToolExecutor` 与 ReAct 协议工作。Store 必须与 Engine 一致；已暴露 `engine.store` 时装配会核对其对象身份。自定义引擎没有该属性时由宿主保证一致性。

```python
from w_agent import JsonlWorkflowStore, LocalWorkflowEngine, resumable_workflow_tool

store = JsonlWorkflowStore(".w-agent/workflows")
engine = LocalWorkflowEngine(store)
# definition 是宿主明确装配的 DAG、状态图或 Python Workflow。
binding = resumable_workflow_tool(engine, definition, store)
tool_registry.register_binding(binding)
```

- 初次调用只生成 `WorkflowToolReference`，不启动子流程、不写入子 Store。默认 WRITE 策略可能先要求审批；准备完票据后仍需再次显式恢复，确保父检查点先落盘。
- 票据记录父 Run、Call ID、工具名、子 Run、Workflow 名称/版本/类型、Scope 和事件序号，不保存授权。ReAct 覆盖真实父 Run ID，执行器覆盖实际 `invocation`；输入和初始状态来自已保存的工具参数。
- 授权恢复后首次启动子流程。PAUSED 返回新票据；之后只恢复同一子流程，核对 PAUSED 状态、元数据所有权、Scope、定义身份和事件序号。已有执行痕迹的初始票据、过期边界和 RESUMING 子检查点均拒绝重放。
- 只有 COMPLETED 且子检查点已移除时，才映射成功结果并允许父 Agent 继续。失败、取消、超时或错配不伪报成功；父 ReAct 保留不确定的 RESUMING 检查点。
- 子流程中可使用 `approval_agent_workflow_node()`，由宿主独立查询并授予精确子工具权限。父工具的 `workflow.execute`/Call ID 授权不传入子工具；未授予内层权限时仍保持暂停。不能绕过父工具直接恢复子 Workflow，否则原票据会失效。

使用持久化父 RunStore 才能跨进程重建绑定后恢复。受信本地单执行者是前提；引用与事件序号不提供分布式锁、代码哈希验证或跨 Store 原子提交。子流程完成到父 Store 写入之间崩溃仍需人工诊断，不能自动重新执行。旧的独立 Workflow 恢复命令不负责协调此链路；双层审批服务与 CLI 见下文，TUI 引导见 CLI/TUI 文档（`2.0.0a6`，针对性回归通过）。

### 双层审批协调服务（`2.0.0a6`，针对性回归通过）

针对 `父 Agent → Workflow 工具 → 子 Agent → 待批工具`，新增两个独立入口：

- `review_workflow_tool_approvals(parent_store, workflow_store, child_store, parent_run_id)`：只读检查父票据、Workflow 所有权/暂停边界及内层引用，返回 `WorkflowToolApprovalReview`。不导入代码或授予权限；`.to_dict()` 仅输出标识和状态，不含 Scope、参数、消息或状态值。外层缺失、不确定或过期时拒绝；内层返回关联状态。空列表不代表流程完成。
- `resume_workflow_tool_approval(..., selection, factory, parent_permissions=..., child_permissions=...)`：宿主明确批准选中的两层调用并允许父 Run 继续。两个权限集合独立，默认均为空；批准的 Call ID 只包含各自选中的一个，不合并权限、不授权后续调用。新调用需要重新查询、选择和授权。

```python
from w_agent import (
    review_workflow_tool_approvals, resume_workflow_tool_approval,
    open_workflow_tool_approval_entry,
)

reviews = await review_workflow_tool_approvals(
    parent_store, workflow_store, child_store, parent_run_id,
)
# selected 必须是用户审阅并明确选择的条目；不自动选择第一项。
result = await resume_workflow_tool_approval(
    parent_store, workflow_store, child_store, selected,
    lambda ctx: open_workflow_tool_approval_entry("my_application:approval_factory", ctx),
    parent_permissions={"workflow.execute"}, child_permissions={"write.allowed"},
)
```

`WorkflowToolApprovalFactory` 是宿主实现的异步上下文工厂。它接收 `WorkflowToolApprovalAssemblyContext`，包含选中引用、父/子完整 `AgentDefinition`、三个 Store 和操作级 `WorkflowApprovalGrants`；必须用这些依赖重建同一 Workflow、内层审批节点、续执行工具和父 Loop，并 yield 父 `ResumableAgentLoop`。子节点注入 `approval_context=ctx.grants`；工厂负责资源关闭。上例的应用工厂不是内置实现。动态导入是受信本地 Python，调用者必须另行获得代码加载授权，不是沙箱执行。

协调服务先检查引用，再进入工厂；装配后重新检查边界和三个完整检查点的值快照，防止装配期间修改参数或定义。然后仅调用父 Loop 的 `resume()`，由其认领父检查点后驱动子层，不直接调用子 Workflow 恢复。临时授权在进入失败、正常返回、异常、取消和退出失败时清除；清理还先于开发者资源退出执行。暂停返回不证明选中工具已运行，未使用的授权不保留。

快照复核不是锁或跨 Store 事务；仍要求受信存储、忠实实现协议的工厂和本地单执行者。不可把已失效票据降级或自动重启。prepared（未启动）的票据、普通边界暂停而无子审批的情况仍走普通父 Agent 恢复；任意深度递归审批尚未实现；CLI 见下文，TUI 见 CLI/TUI 文档（`2.0.0a6`，针对性回归通过）。

### 双层审批 CLI（`2.0.0a6`，针对性回归通过）

`checkpoint workflow-tool-approvals` 以最外层 Agent Run ID 查询，不使用中间 Workflow Run ID：

```bash
wagent checkpoint workflow-tool-approvals outer-run --state-root .wagent --workflow-state-root .workflow-state --child-state-root .child-state --json
```

`--state-root` 指向父 Agent 状态根；其余两个根省略时使用同一根。三个已有目录（父/子 `runs`、中间 `workflows`）均需存在；命令不会替缺失目录初始化状态。重复的 `--state-key` 可指定自定义子审批状态键。查询不导入工厂、不授权；返回的 `sequence` 是选中 Workflow 暂停边界，空列表不表示完成。

审阅具体工具操作后，按查询返回的完整标识执行：

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

上例为 Bash 换行；PowerShell 请写成一行或使用反引号续行。所有 ID、名称、版本、类型和事件序号必须来自本次审阅，不可照抄示例值。两个权限选项可重复、默认均为空。四项确认分别允许受信 Python 装配、父调用授权、子调用授权和父 Run 继续执行（可能运行后续节点、工具及计费模型调用）。仅关联匹配不能代替审阅操作本身。

命令在匹配全部标识与边界前不调用工厂，再交给协调服务复核检查点和管理临时授权。工厂必须是前述双层 `WorkflowToolApprovalFactory`，不能直接复用返回 WorkflowDefinition 的单层工厂。暂停源、同步线程或并发策略由工厂显式装配，本命令不默认开启或清除外部暂停。

框架输出仅包含父 Run/Checkpoint/停止原因、计数、下一个待批调用标识以及 Token/费用，不包含模型输出、参数、Scope 或事件正文；异常只显示类型。`selected_child_execution_confirmed: false` 表示命令没有从返回状态推断子工具执行，不等于“子工具未执行”。工厂是受信代码，可自行打印内容，CLI 不构成输出隔离沙箱。再次暂停后需重新查询和确认；TUI 双层审批引导已加入`2.0.0a6`（针对性回归通过），见 [CLI/TUI 文档](./tui.md)。

### Workflow 内 Agent 的基础装配

`approval_agent_workflow_node()` 依赖可选 `ResumableAgentLoop` 协议和明确传入的同一 Agent `RunStore`，不修改基础 `AgentLoop`。请求源、模型、工具策略和两套 Store 仍可替换。

```python
from w_agent import AgentDefinition, ToolExecutionContext, approval_agent_workflow_node

# loop 使用 agent_store；由宿主在审阅后填入当前明确批准的 Call ID。
approved_calls = set()  # (agent_run_id, call_id)，不按裸 Call ID 跨 Run 授权

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
# 把 node 放入 DAG/状态图，或把 node.handler 放入 PythonWorkflowDefinition。
# 按原有 Workflow start/resume API 执行；审批前须独立审阅 Agent 检查点。
```

首次运行 Agent 停在 `NEEDS_APPROVAL` 时，模板验证真实 Agent 检查点后，把 `AgentWorkflowApproval` 引用保存在节点专属 State Key（默认 `_w_agent_approval:<name>`）。引用只包含父 Run/节点、子 Agent Run/名称及 Call ID/工具名，不复制 Prompt、工具参数、凭据或授权。宿主应保留该 Key，不允许其他节点覆盖；可显式选择其他 `state_key`。

恢复会先核对引用归属、Agent 完整定义、Scope、检查点状态和待批调用。缺失、过期、定义变化或子检查点已为 `RESUMING` 都停止并保留父级不确定状态，不创建替代 Agent Run。没有当前 Call ID 的新授权时，继续挂起，不调用 Agent `resume()`，也不请求模型或工具。授权回调即使返回多个批准 ID，模板也只向子循环传递当前待批 ID；下一次审批再次回到宿主回调。工具权限与审批策略仍由原执行器检查。

### 关联查询与一次性授权（`2.0.0a5`，针对性回归通过）

`review_workflow_approvals(workflow_store, agent_store, run_id, state_keys=...)` 只查询一个明确选择的父 Run。默认仅识别 `_w_agent_approval:` 顶层引用，其他自定义 Key 必须显式指定。格式错误和重复子 Run 引用报错，不跳过为“无审批”。返回 `WorkflowApprovalReview`：引用身份、父/子检查点状态与 `link_status`，不包含 Prompt、工具参数值、状态正文、输出或凭据。

`matched` 仅说明本次读到的父节点仍未完成、父检查点已暂停、子检查点待审批且身份/Scope/待批调用匹配；不是原子快照、执行授权或新 Definition 校验。父状态不确定、引用错配、子检查点缺失或已被 claim 都有独立状态。实际恢复仍由适配器重新校验完整 Agent 定义与当前检查点。

```sh
wagent checkpoint workflow-approvals parent-run --state-root .wagent --json
# 两套 Store 不在同一 Root 时显式指定；自定义 Key 可重复传入。
wagent checkpoint workflow-approvals parent-run --state-root .wagent --agent-state-root .agent-state --state-key my-approval --json
```

CLI 不导入 Definition、不调用模型/工具，也不创建缺失的状态目录。TUI 的 Checkpoints 页新增 “Review linked Agent approvals (read only)”，使用所选父 Run/Root，可填写单独的 Agent Root 和自定义 Key；只显示快照，不消费加载/恢复确认文本。所有查询数据都带 `authorized=false`。

宿主可以显式注入 `WorkflowApprovalGrants` 作为 `approval_context`，不需要自行维护裸 Call ID 集合：

```python
from w_agent import WorkflowApprovalGrants, WorkflowApprovalLinkStatus, review_workflow_approvals

grants = WorkflowApprovalGrants()  # 每个工作区/装配单独持有，不是全局状态。
node = approval_agent_workflow_node(
    "writer", loop, AgentDefinition("coding"), agent_store,
    tool_context=lambda _: ToolExecutionContext(permissions=frozenset({"files.write"})),
    approval_context=grants,
)
# 由 node 装配 workflow，并先运行到审批边界。
reviews = await review_workflow_approvals(workflow_store, agent_store, "parent-run")
review = reviews[0]
if review.link_status is WorkflowApprovalLinkStatus.MATCHED:
    # 仅在宿主另行审阅真实动作，并取得用户明确批准之后执行：
    parent = await workflow_store.load_checkpoint("parent-run")
    grants.grant(review.reference, scope=parent.scope,
                 permissions=frozenset({"files.write"}), ttl_seconds=300)
    try:
        result = await engine.resume(workflow, "parent-run")
    finally:
        grants.clear()
```

授权同时绑定父 Run、节点、子 Run、Agent 名、Call ID、工具名和 Scope，默认 300 秒到期，可显式设置时限、撤销或清空。它只存在内存中，线程安全地消费一次，并且在子执行前消费；失败或取消也不会退回授权。回调不匹配不会消耗其他授权。该模板不建立 Store 身份隔离，不能跨无关工作区共享同一对象，也不替代工具权限策略。

已发布的 a5 CLI/TUI 只提供关联查询。`2.0.0a6`新增下述 CLI 与 TUI 授权恢复接线（针对性回归通过）。不要绕过父节点直接使用普通 Agent 恢复入口推进关联的子 Run，否则父引用可能过期并在下次恢复时被拒绝。宿主应通过显式注入授权对象的父 Workflow 恢复。

### CLI 批准并恢复父流程（`2.0.0a6`，针对性回归通过）

`resume_workflow_approval()` 是可选的宿主协调服务，不替换原有 Engine、Store 或审批回调。它接收两个 Store、完整 `AgentWorkflowApproval` 引用和开发者工厂。工厂接收 `WorkflowApprovalAssemblyContext`，其中包含本次 Store、父流程身份/Scope、引用与新建的 `WorkflowApprovalGrants`；必须返回异步上下文管理器，产出一个精确名称/版本/类型的 Workflow Definition。模型客户端等资源由工厂负责关闭。普通 `--workflow-entry` 的零参数加载协议不变。

```python
# my_workflows.py；myapp 中的函数与定义由应用提供。
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

必须重建原始完整 Workflow 与 Agent 定义，并沿用审批节点的 State Key；不能只复制流程名称/版本后替换节点行为。工厂是显式信任的本地 Python，可以产生副作用，不是沙箱或权限隔离边界。框架不推断工厂是否忠实使用传入的 Store/授权对象。

先通过 `workflow-approvals` 取得引用，另行审阅真实工具动作与参数，再执行：

```sh
wagent checkpoint workflow-approve-resume parent-run \
  --workflow-factory my_workflows:approved --node writer \
  --agent-run agent-child-id --agent-name coding \
  --approve-tool-call call-id --tool-name write_file \
  --state-root .wagent --grant-permission files.write \
  --confirm-workflow-code --confirm-approval --confirm-resume --json
```

三项确认分别授权 Python 导入/装配、当前精确工具调用和父流程继续执行（包括可能计费的模型调用及后继节点）。`--grant-permission` 可重复；不默认赋予任何权限。可选 `--agent-state-root`、重复 `--state-key` 和 `--enable-pause-control` 与查询/恢复入口一致。未知或过期引用在工厂导入前拒绝，缺失状态目录不自动创建。

服务在装配后重新比对完整父/子检查点与匹配状态，再建立默认 300 秒的一次性授权并恢复父流程。结束、取消及工厂进入/退出失败均清空剩余授权；清理资源前也先清空。SQLite 请求导致继续暂停时，未使用授权同样清空，请求保持不变。输出沿用不含模型正文、状态正文或工具参数的 Workflow 摘要，不宣称指定工具已经执行。

这些检查不是跨 Store 原子事务，也不防御同时改写状态的其他进程；仍需可信本地存储与单执行所有者。发生异常、清理失败或不确定副作用时，应检查检查点而非自动重试。Python API 调用者自行负责代码、动作与执行授权；CLI 的三个确认不会自动适用于其他入口。

### TUI 批准并恢复（`2.0.0a6`，针对性回归通过）

Checkpoints 页使用相同公开工厂服务，不在界面里另建授权系统。操作顺序：

1. 选择父 Workflow Run/State Root，可选独立 Agent Root 和自定义 State Key，点击只读关联查询；查询不自动选择任何待批调用。
2. 另行审阅真实动作及参数，填写工厂 `module:attribute`、精确节点、子 Run、Agent 名、Call ID、工具名及本次权限。普通 Workflow Entries 字段不用于此入口。
3. 分别输入 `LOAD WORKFLOW`、`APPROVE <Call ID>`、`RESUME WORKFLOW`，点击 “Approve exact call and resume parent”。只读匹配结果不能代替其中任何确认。

请求通过本地表单校验后立即消费三项确认，之后即使检查点过期、导入失败或执行失败也不复用。界面复用普通恢复的后台 Worker、同一任务锁和暂停按钮；执行期间锁定普通恢复与审批恢复表单，捕获的 Root/Run/Call/权限不会被后续表单修改重定向。工厂导入与初始化仍是开发者 Python，后台异步任务不保证任意同步阻塞代码都不会卡住界面。

可选同步节点线程策略与 SQLite 请求源组合继续生效。取消/退出会走工厂和授权清理；本界面请求会清空，外部持久请求不清空。失败只显示异常类型，结果和事件不展示工具参数、模型正文或状态正文；暂停不证明指定工具已执行。恢复后再次查询剩余审批，再逐次填写新的确认；界面不批量授权、不自动恢复子 Run，也不自动重试不确定执行。

### 未完成节点的执行语义

新增 `WorkflowNodeResult(pause=True, suspend=True, state_updates=...)`：保存可恢复状态，但不提交新输出、不把当前节点加入已完成列表，也不选择下一节点。它不允许同时给出输出或跳转目标。事件为 `node-suspended`，不是 `node-completed`。普通 `pause=True` 的原有语义不变。

- DAG 恢复同一个未完成节点；状态图停留于当前节点；Python Workflow 再次调用同一处理器并递增 `resume_count`，仍受 `max_resumes` 限制。
- 并行 DAG 批次等待全部节点返回；成功兄弟节点照常提交，挂起节点保留未完成，其后继不会解锁。状态键冲突、兄弟失败或取消仍让整批保持 `RESUMING`，不自动重放。
- 子 Agent 完成后才应用结果 Mapper、提交节点输出，并把引用 Key 置为 `None`；状态图下次再次进入节点时可以开启新的 Agent Run。
- 父子 Store 没有原子提交：子检查点已写入而父提交失败、子工具执行后进程中断等窗口仍需人工诊断。恢复入口不修补、不删除子检查点，也不重试不确定副作用。父 Run 达到自身限制时也不会自动清理子 Run。
- Checkpoint JSON 仍沿用现有字段，但新增 `node-suspended` 事件要求读取方使用支持此增量的版本；不要用旧版读取或恢复新日志。针对性回归已通过。

## 取消与事件

`CancellationToken` 在节点边界检查，并传入 `WorkflowNodeContext` 供异步节点协作检查。节点处理器应在发起昂贵操作前调用自己的取消检查。节点执行中的取消也按不确定执行处理，不自动重放。

事件按 Run 使用连续序号追加：

- `workflow-started` / `workflow-resumed`
- `node-started` / `node-completed` / `node-failed`
- `node-suspended`（`2.0.0a5`）
- `workflow-paused` / `workflow-completed`

事件数据不自动包含输入、输出或异常正文，避免默认记录 Prompt 和凭据。自定义 Store 和可观测插件仍必须遵守同一安全边界。

## 替换与组合

应用可以替换整个 `WorkflowEngineProtocol` 或 `WorkflowStore`，也可以让任意节点调用公开的 `AgentLoop`、模型、工具或其他应用服务。

`agent_workflow_node()` 默认把 Workflow 输入转为用户消息，只接受 `COMPLETED` Agent 结果，并返回 JSON 可持久化的输出、停止原因和 Token 用量；消息工厂、工具权限上下文、结果映射和可接受停止原因都可替换。非完成状态默认使节点失败，避免把审批或预算停止误当成功。

`workflow_start_tool()` 和 `workflow_resume_tool()` 固定绑定一个 Definition，默认只返回运行/Checkpoint 标识、公开输出和停止状态，不把内部 State 自动暴露给模型；需要时可替换结果映射。两者默认声明 `WRITE` 副作用并要求 `workflow.execute` 权限，所以仍需应用授予权限和逐调用批准；调用取消会传给 Workflow。暂停结果不会自动恢复，Agent 必须显式调用恢复工具或由应用接管。适配器不实现嵌套 Workflow，也不会自动串联 Agent Checkpoint 与 Workflow Checkpoint。
