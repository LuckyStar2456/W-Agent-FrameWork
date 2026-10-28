# 默认组件的容器装配

[English](./default-assembly.en.md) | 简体中文

> 版本说明：本页新框架核心纳入 2.1.0。下方“未发布”与候选 2.0.0 元数据属于发布前阶段记录，不代表 2.1.0 包状态。参见[2.1.0 发布说明](./releases/2.1.0.md)；上传状态以 [PyPI](https://pypi.org/project/wagent-framework/2.1.0/) 为准。

这部分是未发布的 M4 实现，**已完成阶段相关验收，合计 572 个用例通过**。它把现有 ReAct 和 Workflow 变成 `ApplicationContext` 的可选装配方案，而不是增加一个强制 Harness。Python、CLI/TUI 的默认 Run/Resume/Evaluation 与普通 Workflow 恢复已经接入公开 `ApplicationHost`；自定义项目使用同一个加载和执行入口。已有审批链继续调用其公开授权适配器，不绕过批准。

## 选择默认装配

`compile_local_runtime(config, state_root, ...)` 返回 `AssemblyPlan`，不会创建 Provider、读取凭据、创建存储目录或调用模型。`ApplicationContext.start()` 才执行工厂；启动存储可能创建目录。默认 Runtime 仍采用现有 `ModelMessage`、`AgentDefinition` 和 `RunResult` 协议。自定义其他数据协议时，直接编译自己的组件计划，无需采用此方案。

```python
from w_agent import ApplicationContext, compile_local_runtime

async def answer(config, prompt):
    plan = compile_local_runtime(config, ".wagent")
    async with ApplicationContext(plan) as app:
        runtime = app.resolve("runtime")
        return await runtime.run(prompt)
```

此片段会在执行 `run()` 时调用配置中的模型；它是用法说明，不是离线验收证据。工具、知识、预算与用量账本仍由宿主显式提供授权 catalog，不扫描模块，也不通过配置导入代码。

## 组件替换点

| 组件名 | 默认实例与职责 |
|---|---|
| `provider` | `LocalProviderAssembly`；拥有模板创建的 Provider 及其观察/预算包装关系 |
| `models` | `ModelRegistry`；只管理可见性，不关闭后来加入的宿主 Provider |
| `routing_policy`、`router` | 默认路由策略与 `ModelRouter` |
| `invocation_policy`、`model_executor` | 调用策略与 `ModelExecutor` |
| `tools`、`tool_executor` | 授权工具目录与 `ToolExecutor` |
| `run_store`、`session_store`、`sessions` | Run 存储、Session 存储和 `SessionManager` |
| `definition`、`pricing`、`token_estimator` | Agent 定义、可选价格与估算器 |
| `knowledge` | 借用宿主知识绑定；没有配置时为 `None` |
| `loop`、`runtime` | 默认 ReAct 与本地会话调用适配器 |

将替换定义传入 `compile_local_runtime(..., replacements=(... ,))`，或对已有计划使用 `replace_components(plan, replacements)`。名称必须已存在，重复名称、缺失依赖、循环依赖与跨越生命周期的捕获均拒绝；保留原计划的作用域顺序和切面。替换不创建对象，不修改已经运行的上下文，也不自动删除不再被引用的组件。完全退出默认模块时，使用 `compile_assembly` 构造精简计划。

例如，宿主已有符合 `AgentLoop` 协议的 `my_loop` 时：

```python
from w_agent import BorrowedComponent, compile_local_runtime

def use_my_loop(config, my_loop):
    return compile_local_runtime(
        config, replacements=(BorrowedComponent("loop", my_loop),),
    )
```

`BorrowedComponent` 保留宿主所有权。希望框架创建并销毁实例时，改用带显式 `dispose` 的 `ComponentDefinition`。替换 Provider 时默认组件协议是 `LocalProviderAssembly`，不是裸 Provider；使用宿主资源可借用 `LocalProviderAssembly(name, provider)`，不触发容器清理该资源。

## 关闭与切面

受容器管理的 Runtime 不再关闭模型注册表中的 Provider；它仅标记自己已关闭。默认 `provider` 组件负责清理其创建的资源，容器按反向依赖顺序关闭组件并处理启动回滚。宿主知识、用量、预算、工具绑定不因容器退出而转移所有权。

`aspects=(...)` 直接进入同一个装配计划。切点可匹配 `runtime.run`、`router.route` 等公开方法。调用方必须结束或取消未由切面追踪的业务任务，再关闭上下文；容器不会猜测外部任务的所有权。

## 独立 Workflow 装配

`compile_local_workflow(state_root, node_invoker=..., pause_source=..., replacements=..., aspects=...)` 不创建模型或 ReAct。它贡献 `workflow_store`、`node_invoker`、`pause_source` 与 `workflow` 四个组件。解析 `workflow` 后使用公开 `start()` / `resume()`。显式提供的 invoker、pause source 是借用资源；替换定义可以自行声明托管生命周期。

## 验证和剩余工作

新增 `tests/test_local_application.py`、`tests/test_application_execution.py` 和 `tests/test_application_frontends.py` 覆盖默认装配、托管执行、流关闭、取消、加载授权及三个前端的同一自定义项目。旧同步 `assemble_local_runtime()` 保留兼容，其原有清理行为不自动升级为应用上下文语义；CLI/TUI 已改用 `open_local_runtime()`。

M4 实现收齐后，在现有隔离 Python 3.11.9 环境分批验证。应用核心/装配/前端用例及修复复验为 194 passed / 4.61s；相邻运行、审批、预算、知识和 Workflow 回归为 378 passed / 150.39s，另有一处旧页签清单断言失败，补入新增 Application 页后已包含在 194 项复验中。因此最终覆盖 572 个不同用例，不累加更早阶段结果。TUI 为 Textual 无界面验证，Docker 探测被替换，未连接真实模型或外部服务。

验证文件范围：全部 `test_application_*.py`、`test_local_application.py`；另含 `test_local_runtime`、`test_runtime_shared_budget`、`test_service_usage_runtime`、`test_knowledge_runtime`、`test_framework_acceptance`、`test_budget_evaluation_probe`、`test_cli`、`test_tui`、`test_history_options_cli`、`test_knowledge_evaluation_ui`、`test_knowledge_ui`、`test_message_fields_run`、`test_runtime_media_input`、`test_service_usage_frontends`、`test_service_usage_resume_frontends`、`test_shared_budget_ui`、`test_tui_history_templates`、`test_tui_media_run`、`test_tui_message_fields_run`、`test_tui_shared_budget`、`test_tui_approval_resume`、`test_tui_workflow_control`、`test_tui_workflow_tool_approval`、`test_cli_workflow_tool_approval`、`test_workflow_approval_resume`、`test_workflow_invocation`（均位于 `tests/`，扩展名 `.py`）。这不是全量测试。

文档中的 CLI 示例实际输出 `{"result": "LOCAL:HELLO"}`。未安装、构建、提交、推送或发布。M5 仍需完成三条完整开发者教程、迁移文档和授权后的安装制品/仓库外验收；M4 通过不等于最终 H01–H08 完整范围验收。

静态检查：33 个相关 Python 文件通过 AST 与内存编译；18 份双语入口/专题文档的 552 个本地链接目标存在。指定范围已跟踪文件的 `git diff --check` 退出 0，仅有 LF→CRLF 提示；未跟踪文件不由该命令覆盖，不将其计作完整工作区检查。

## 同一个项目用于 Python 和终端

`ApplicationProject(plan, operations)` 指定公开操作，例如 `{"run": ApplicationOperation("harness", "run")}`。计划可以来自 `compile_assembly`、`compile_decorated` 或 `compile_configured`，不要求默认 Provider、Loop 或模型消息格式。

```python
from examples.custom_harness import create_project

async def custom_answer():
    async with create_project().open() as host:
        return await host.invoke("run", "hello")
```

在仓库根目录，CLI 使用同一离线示例：

```bash
python -m w_agent.cli application run --entry examples.custom_harness:create_project --input-file examples/custom_harness_call.json --confirm-code
```

TUI 的 **Application** 页填写相同入口和参数文件，输入 `RUN APPLICATION` 后执行。确认只用一次；取消或退出会等待该调用的清理。参数文件仅有 `operation`、`args`、`kwargs`，限制 1 MiB，拒绝重复 JSON 字段与非有限数值。Python 可传入任意对象；CLI/TUI 仅传输 JSON，结果不可 JSON 序列化时报告失败，不用 `repr` 强行输出潜在秘密。

`load_application_entry(..., confirmed=True)` 才会导入明确的 `module:attribute`，接受项目对象或返回项目的无参同步/异步工厂。`execute_application_entry(entry, call, confirmed=True, on_item=...)` 是三个入口共用的加载、启动、调用和关闭流程。授权包含**非隔离的导入、启动和本次操作执行**，可能访问本地文件、外部服务或模型；不能给不可信代码使用，也不自动授予内置工具审批。需要隔离时由项目使用沙箱组件。

## 调用与流的生命周期

`host.invoke()` 调用普通同步/异步方法，原样返回业务值；返回迭代器时拒绝其逃逸出作用域。流方法显式声明 `ApplicationOperation(..., kind="stream")`，通过 `await host.consume("stream-name", consumer, ...)` 完整消费，返回成功交付条数。消费者可为同步或异步，逐条等待形成背压；完成、异常与取消均关闭源及其迭代器，再释放本次作用域。CLI 逐条输出 `{"item": ...}`，最终输出 `{"result": ...}`；流的最终结果为交付条数。TUI 只保留最近 20 条，单条显示截断到 8192 字符。

Host 仅管理通过自身提交的调用。关闭时拒绝新调用，取消并等待已有调用，再关闭容器；同一个调用不能关闭自己的 Host。目标组件如果是 Run 等短作用域，每次调用建立独立的祖先作用域链并在结束时释放，不承诺跨调用复用 Session 作用域。需要长期工作区/会话作用域时，开发者仍可显式管理 `ApplicationContext`。同步代码阻塞、吞掉取消或自行启动未登记任务时，不提供强制终止保证。
