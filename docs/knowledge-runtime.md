# 知识库具名装配与 CLI/TUI 查询

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-runtime.en.md) | 简体中文

状态：2.0.0 `Experimental`，已随 2.0.0 发布，不属于 `2.0.0a9`。`tests/test_knowledge_runtime.py` 的 11 项离线回归已通过；未进行界面、真实服务验收或发布。

## 配置只选择，不授权

本地 Runtime 配置可增加 `"knowledge": {"binding": "manual"}`。`LocalKnowledgeConfig` 仅保存 1–128 字符的 `[A-Za-z0-9][A-Za-z0-9_.:-]*` 名称，不接受文件路径、凭据、工厂引用或查询。名称对应宿主提供的 `LocalKnowledgeBinding`，不是租户、平台资源或访问控制。

`LocalKnowledgeBinding(retriever, limit=4, limits=SessionHistoryLimits(), timeout=30)` 借用实现 `KnowledgeRetriever` 的对象。宿主可选内存关键词、固定快照向量或自己的检索实现；Embedding/预算/后端配置继续由宿主装配。创建 binding 和 Runtime 不执行检索、不初始化数据库、不自动关闭借用检索器。

```python
from w_agent import LocalKnowledgeBinding, assemble_local_runtime

# config.knowledge 已选择 manual；retriever 是宿主已构造的检索器。
runtime = assemble_local_runtime(
    config, ".wagent", knowledge_bindings={"manual": LocalKnowledgeBinding(retriever)},
)
async with runtime:
    run = await runtime.run(
        "请根据参考资料回答退货流程。",
        knowledge_query="退货流程", confirm_knowledge_query=True,
        include_history=False,  # 不发历史，但仍执行明确授权的知识查询。
    )
```

示例未执行。`run_messages()` 同样支持这两个知识参数，媒体输入不会自动变成检索词。未传 knowledge_query 时不检索，即使配置已经选择知识库。查询为空白、超过 4096 UTF-8 字节、未确认或缺少绑定时，在创建/读取 Session 前拒绝。确认必须是字面布尔 True，不能用整数 1 替代。

Python 装配时提供 catalog 会校验名称、最多 64 个类型化绑定，以及选中名称是否存在。不提供 catalog 仍可装配普通运行/检查点恢复路径；直到显式查询才要求绑定齐全。JSON 不自动导入代码、读取知识目录或取得外部访问许可。

## 上下文与历史

每次查询构造新的 `AsyncKnowledgeContextPolicy`：所选历史策略 → 带来源的不可信 USER 知识数据 → 当前输入。默认历史策略不变；有自定义历史策略时组合它，不将知识提升为 SYSTEM 指令。无历史的空 Session 也能检索。

`include_history=False` / CLI `--history none` 在这个显式知识入口表示“不调用历史投影、不发送历史，但仍查询知识”。Runtime 内部以空历史策略调用上下文接口；不会因此恢复历史授权。知识策略仍按现有限额检查 Session 原始历史大小，超限会失败而不是静默省略。没有知识查询的普通运行维持原有 include_history 语义。

知识上下文模板支持文本历史；recorded 模式含非文本块时会拒绝，不自动 OCR 或降级。返回结果仍受文档数、字节和上下文输出限额约束；检索失败不启动 Agent Loop、不返回部分上下文、不自动重试。失败前可能已创建 Session 或发生外部检索费用。`run-resume`/TUI 检查点恢复使用原先保存的请求，不重新打开本次知识工厂或重新检索。

独立使用 `AsyncKnowledgeContextPolicy` 的底层 Session 接口仍受它原来的 include_history 开关控制；上述“仅知识”组合是新的 Runtime 显式入口，不改变底层协议。

## CLI

宿主工厂是明确指定的 `module:factory`：零参数调用返回异步上下文管理器，进入后得到 `{name: LocalKnowledgeBinding}`。它是未隔离的受信 Python 代码，可在进入时加载固定版本快照、借用或创建客户端，并在退出时清理；不是自动安装插件，也不能由共享工程配置自行授予执行权限。

仓库提供无网络、无文件读取的内存演示工厂 `examples.knowledge_runtime:knowledge_catalog`，仅包含样例文本。将本地配置增加上述 knowledge 选择后，可使用以下未执行命令：

```powershell
py -3.11 -m w_agent run "Explain the sample returns guidance" --config .wagent/config.json --knowledge-entry examples.knowledge_runtime:knowledge_catalog --knowledge-query returns --confirm-knowledge-code --confirm-knowledge-query --confirm-model-call --history none
```

- `--confirm-knowledge-code` 允许执行工厂的 import、setup、cleanup；这些代码本身可能有副作用，需宿主审核。
- `--confirm-knowledge-query` 允许查询披露、可能收费的查询 Embedding/检索，以及向配置模型发送返回正文；不授权批量正文 Embedding、索引写入或保存原文件。
- `--confirm-model-call` 仍独立要求；输入记录、工具代码和预算代码继续沿用各自许可。
- 工厂与查询必须成对提供，两个知识确认独立；基本校验早于输入文件/工具/工厂加载。配置缺少 knowledge.binding 时不导入知识工厂。
- 当前只接入 `run`。Provider probe、evaluate、Workflow 和检查点恢复不自动加载知识工厂；需另行设计它们的专用装配。

## TUI

Run 页新增 Knowledge host、Explicit knowledge query 两个输入；每次运行分别填写 `LOAD KNOWLEDGE`、`QUERY KNOWLEDGE`，并保留原来的 `RUN`。history=none 可只用知识。确认词在捕获本次请求后清空，字段与其他运行参数一同锁定；进行中的任务不读取用户随后改动的查询。缺少许可时不进入输入文件或工厂加载。

Run 页只负责具名工厂/查询字段；独立 [Knowledge 管理页](./knowledge-management.md) 已补本地文件导入预览/保存、版本目录和固定版本检索浏览源码，不会自动选择 Run 版本。[索引日志查看/对账](./knowledge-index-management.md)及[计划准备/授权执行](./knowledge-plan-actions.md)另有入口，headless TUI 回归已通过，人工布局/生产交互仍待验收。

## 生命周期、费用与数据

工厂进入成功后，在 catalog 无效、运行失败或取消时都会尝试退出；工厂返回 True 不能吞掉 Runtime 异常。setup/cleanup 是受信代码，可能阻塞、失败或已有副作用；进入未完成前的资源清理由工厂负责，重复取消可能打断清理。清理失败不证明模型没运行，应查看持久状态，不能盲目重跑。

配置与绑定不授予文件、网络或模型工具权限；如需 OS 隔离，由宿主提供沙箱执行环境。知识检索并非普通工具调用，不套用 ToolExecutor 的逐调用审批；本入口的查询确认由调用方负责，检索器需自行落实其资源权限。

查询不自动从提示词、历史或输入文件推断，也不额外写入专用查询日志；但知识正文将成为模型输入，并可能进入既有 Run/检查点等持久记录，应按其存储策略处理敏感内容。引用标签不是 prompt-injection 防护。工厂借用的 Embedding 可显式使用[共享预算包装器](./embeddings.md)；不包装则不会自动纳入主 Run/Session 或池总量。

## 本轮进度与剩余

具名绑定、逐次 Runtime 查询及仅知识模式已通过本地回归。[Workflow/评测专用装配](./knowledge-workflow-evaluation.md) 已提供独立 API 和离线端到端测试。CLI/TUI 交互、真实服务验收及其他模块进展见各自文档与[路线图](./roadmap.md)。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
