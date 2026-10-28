# 从 1.x 迁移

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./migration-1x.en.md) | 简体中文

> 版本说明：本页新框架核心纳入 2.1.0。下方“未发布”与候选 2.0.0 元数据属于发布前阶段记录，不代表 2.1.0 包状态。参见[2.1.0 发布说明](./releases/2.1.0.md)；上传状态以 [PyPI](https://pypi.org/project/wagent-framework/2.1.0/) 为准。

未发布的新核心保留既有装饰器名称，但需显式使用 `compile_decorated()` 与 `ApplicationContext` 才获得新生命周期语义。旧 BeanFactory 继续原有语义，可经 `borrow_legacy_singletons()` 借用已创建单例；不能在两边同时登记销毁。新容器仅执行标记的生命周期方法，不按普通方法名猜测；`prototype` 请改为明确 run/step 作用域。配置工厂、限定注入和 Value 绑定见[注解迁移用法](./annotation-development.md)。

状态：`Experimental`。`LegacyAgentAdapter` 已实现；EventBus、配置和旧沙箱到新协议的 Bridge 仍为 `Planned`。

## 策略

下一代公共 API 直接覆盖 `w_agent`，不创建 `w_agent.v2`。1.x 使用量有限，因此只保证基础迁移，不长期维护两套完整框架。

- 现有 1.x 在兼容窗口内继续安装和运行。
- 必要旧 API 移入兼容模块或由适配器导出。
- 新模型、Workflow、插件和沙箱能力只进入新协议。
- 弃用 API 使用 `Deprecated` 标记并给出替代路径。

## BaseAgent

当前：

```python
class BaseAgent:
    async def arun(self, prompt: str) -> str: ...
```

`LegacyAgentAdapter` 将旧 Agent 包装为普通 Workflow 节点。默认输入和输出必须是文本；非文本输入或结构化输出必须由应用显式提供映射函数。它不伪造流式事件、工具调用、Token 用量、Checkpoint 或能力声明，也无法强制中断正在执行且不协作取消的旧 `arun()`。

```python
from w_agent import (
    LegacyAgentAdapter,
    LocalWorkflowEngine,
    PythonWorkflowDefinition,
    WorkflowContext,
)

adapter = LegacyAgentAdapter(old_agent)
definition = PythonWorkflowDefinition(
    "legacy-task",
    adapter.workflow_node("legacy").handler,
)
result = await LocalWorkflowEngine().start(
    definition,
    WorkflowContext("workflow-1", input="hello"),
)
```

也可使用 `legacy_agent_workflow_node("legacy", old_agent)` 快速构造节点。适配器在旧调用前后检查 Workflow 的协作取消信号；旧 Agent 内部是否支持及时取消仍由旧实现决定。

## BeanFactory 与组件装饰器

旧 BeanFactory 保持原语义；新装配以 `AssemblyPlan` / `ApplicationContext` 为准，Registry 只负责能力索引。组件注解编译为 `ComponentDefinition`，并不自动变成 `PluginSpec`；需要插件边界时显式使用 `ApplicationPlugin`。借用旧单例不转移销毁权。

## 新核心迁移对照（未发布）

| 既有用法 | 新用法 | 注意 |
|---|---|---|
| 手动构造和清理对象 | `compile_assembly` + `ApplicationContext` | 工厂托管、外部实例借用；不要重复登记清理 |
| 装饰器 / BeanFactory | `compile_decorated` 或 `compile_configured` | 显式扫描已加载模块，配置只能选允许目录 |
| `ProxyFactory` 手工代理 | `Aspect` 与计划 `aspects` | 老代理不自动升级；自调用与未声明特殊方法不被新代理拦截 |
| `assemble_local_runtime` | `async with open_local_runtime(...) as runtime` | 旧同步函数仍保留；新入口在 enter 时启动并经 Host 执行 |
| 自定义业务入口 | `ApplicationProject(plan, operations)` | Python/CLI/TUI 复用项目，CLI/TUI 限 JSON 可表达输入输出 |

新语义是主动迁移，不在导入时改写旧容器。完整可运行迁移起点见[三条 Harness 教程](./harness-development.md)。插件的自定义作用域可通过 `ApplicationPlugin(..., scope_order=...)` 明确层级；借用导入仍遵守作用域捕获限制。

## EventBus

1.x `EventBus` 可以由 Bridge 转发普通通知。下一代类型化 Pipeline、持久化 RunEvent 和生命周期效果不能完全映射回旧 EventBus。

## 配置

`DynamicConfigManager` 的普通键值可以迁移到下一代配置 Provider。秘密值必须改为凭据引用；插件清单和工程装配编码不能保存密钥。

## Skill 沙箱

Wasm 和 nsjail 实现计划适配到 `SandboxProvider`。旧调用方式在兼容期保留，但编码 Agent 应迁移到统一 Sandbox Handle 和 Docker/OCI 默认后端。

## 顶层导出

当新 API 与旧 API 同名时，迁移版本必须在发行说明中逐项列出替换关系。禁止根据参数类型在运行时猜测用户想调用新还是旧 API。

下一代 CLI 使用 `wagent`，现有 `w-agent` 在兼容期作为别名保留。

## 迁移完成条件

- 现有基本 Agent 示例可以通过适配器运行。`Implemented`
- 旧容器和配置用法具有明确替代方案。
- 弃用警告包含目标 API 和删除版本。
- 中英文迁移文档、测试和发行说明同步。
