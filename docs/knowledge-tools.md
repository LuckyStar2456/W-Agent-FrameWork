# 按需知识检索工具与显式装配

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-tools.en.md) | 简体中文

状态：2.0.0 `Experimental`，已随 2.0.0 发布，不属于 `2.0.0a9`。`tests/test_knowledge_tools.py` 的 34 项离线回归已通过，包括工具审批恢复与结果传入模型；未进行真实服务验收或发布。

## 两种独立使用方式

[知识上下文策略](./knowledge-context.md)由宿主在 Run 前显式检索。本模块导出的 `knowledge_search_tool(retriever, ...)` 则返回普通 `ToolBinding`，允许模型在工具循环中按需搜索。两者可单独使用或同时装配；框架不自动去重，重复查询可再次计费。

工厂只绑定宿主提供的 `KnowledgeRetriever`，不调用它、不创建索引、不导入宿主模块、不打开来源。遵循协议组合方式，可替换本地关键词、向量检索或自定义链路，不接管 Agent Loop。

## 注册与具名 Runtime 装配

```python
from w_agent import (
    InMemoryKnowledgeDocumentStore, KnowledgeDocument, KeywordKnowledgeRetriever,
    ToolSideEffect, assemble_local_runtime, knowledge_search_tool,
)

store = InMemoryKnowledgeDocumentStore((
    KnowledgeDocument("example-v1", "示例：退货期限为七天，并非真实业务政策。", "sample:refund"),
))
binding = knowledge_search_tool(
    KeywordKnowledgeRetriever(store),
    side_effect=ToolSideEffect.READ,  # 宿主明确选择纯本地、无外部调用的实现。
)
# config 是宿主已有 LocalRuntimeConfig，包含 tools.enabled=["knowledge_search"]。
runtime = assemble_local_runtime(config, tool_bindings={"knowledge_search": binding})
try:
    result = await runtime.run("查询退货期限", permissions=frozenset({"knowledge.read"}))
finally:
    await runtime.aclose()
```

也可使用 `ToolRegistry.register_binding(binding)`，获得既有统一注册表的作用域、版本和所有者能力。Runtime 按 `tools.enabled` 从宿主目录选择同名绑定，缺失或名称不符会失败；JSON 不携带可执行检索器、凭据、权限授予或模型可修改的检索后端。

默认 `side_effect=EXTERNAL`、`required_permissions=frozenset({"knowledge.read"})`。默认策略先检查权限，再要求精确 Call ID 审批；尚未授权时不调用检索器。宿主确认纯本地后才选择 `READ`；可自行替换权限与策略。效果声明不是运行时网络隔离，不能让恶意或误声明的 Python 自动变得安全。

## 既有 CLI/TUI 通道

仓库提供 [`examples/knowledge_tools.py`](../examples/knowledge_tools.py)，只包含示例记录和工厂。将其放入宿主项目可导入位置，例如 `my_knowledge_tools.py`。配置中的 `tools.enabled` 添加 `knowledge_search`，保留用户自行选定的 Provider/模型等字段，然后显式执行：

```powershell
wagent run "查询退货期限" `
  --config .wagent/config.json `
  --tool-entry my_knowledge_tools:build_tools `
  --confirm-tool-code `
  --grant-permission knowledge.read `
  --confirm-model-call `
  --json
```

该命令仅为使用说明，本轮没有执行。Python 入口导入是独立的、不隔离的本地代码执行授权，不由配置隐式触发。示例工厂本身只创建本地对象，不联网或读取文件；主模型仍需配置和授权，可能收费。

外部检索器保留默认 `EXTERNAL` 时，Run 可停在 `needs-approval`；核对待执行查询后，按[本地 Runtime](./local-runtime.md)的 `run-resume` 流程批准精确 Call ID，并再次提供模型/代码授权及权限。查询来源可能敏感，审批前应审查实际参数；脱敏的 checkpoint 列表只列参数名，不足以完成内容审查。固定可信的工具代码和检索配置版本，避免批准期间更换后端。

TUI 复用现有工具入口、`LOAD TOOLS`、权限、`RUN` / `RESUME` 操作，不新增隐藏导入或长期授权。通用工具通道和知识入口有本地/无头回归覆盖；[知识管理](./knowledge-management.md)与[知识上下文具名装配](./knowledge-runtime.md)提供独立入口。真实模型驱动的检索效果及人工布局、生产交互仍待验收。

## 参数、返回值与边界

- 默认名称 `knowledge_search`，可改名；使用具名 Runtime 时目录键、绑定名、`tools.enabled` 必须一致。工具描述可改，名称最多 64 个 ASCII 字母/数字/下划线/连字符，首字符为字母或下划线。
- 模型只传 `query` 和可选 `limit`。后端、文档存储、候选 ID、凭据、超时及上限由宿主绑定，不能经工具参数覆盖。未知参数拒绝；查询不得全空白。
- 默认查询最多 4096 UTF-8 字节；`max_results=4`，可设 1–128。省略 `limit` 使用宿主最大值，显式值必须是 1 至最大值的整数，不接受布尔值。通用 JSON Schema 验证器只支持部分关键字，因此适配器内再次校验数值和字节限制。
- 文档字段总大小默认最多 1 MiB，实际返回 JSON 默认最多 64 KiB，均可显式调整至 16 MiB。JSON 限额包含版本、提示标签、来源、标题、ID、正文和转义开销；不是 Token、全 Run、Provider 完整请求或进程内存预算。超限失败，不静默截断。
- 成功结果为 `{"format":"wagent-knowledge-search-v1","notice":"...","documents":[{"id":...,"source":...,"title":...,"text":...}]}`。`ToolResult.data` 保留结构，`content` 为紧凑 JSON，空结果是空数组。重复文档、错误形状或超量返回失败。来源不自动下载或验证，文本标签/JSON 不防止提示注入；结果由正常工具消息通道交给模型，不提升指令层级。
- 默认 30 秒检索超时，既有 Executor 自身的截止时间也有效。超时使用 `TIMED_OUT`，取消沿既有 Executor 通道处理并等待协作式清理；普通错误使用 `FAILED`，错误信息不输出正文/查询/底层异常。不自动重试，但模型下一步仍可能请求新调用，需宿主工具次数/费用策略限制。
- 默认审计记录不包含查询或正文；正常 ToolResult、Run 检查点、启用的事件记录、模型回答或宿主日志可包含这些数据。没有无持久化或隐私脱敏保证。
- 权限与逐调用审批由 `ToolExecutor` 执行，直接调用 `binding.handler` 会绕过策略；自定义 Executor/策略也由宿主负责。组件均为借用，Runtime 不自动关闭检索器或文档客户端，宿主负责资源清理。
- 返回内容进入主模型后的 Token 走既有模型统计；Embedding/检索调用本身的费用仍需显式计量，尚未自动合并共享池/Session 账本。输出字节限制不是累计费用控制。

## 进度与剩余

普通工具绑定、权限/审批、参数、JSON 限额、错误、取消和 Runtime 回传本地测试已通过。可选组合[版本快照](./knowledge-ingestion.md)、[快照向量](./knowledge-vectors.md)和独立[索引清单/回执日志](./knowledge-index-journal.md)；各组件验证状态以对应文档为准。工具调用不会自动触发索引写入。支持注入[BM25/混合/重排](./knowledge-retrieval.md)检索器；真实服务验收及其他计划见[路线图](./roadmap.md)。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。真实服务、费用、质量及人工生产界面仍待验收。
