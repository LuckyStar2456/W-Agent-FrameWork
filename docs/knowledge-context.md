# 可替换知识检索与 Agent 上下文

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-context.en.md) | 简体中文

[具名 Runtime/CLI/TUI 装配](./knowledge-runtime.md)可显式组合本策略；其独立知识查询入口支持仅知识模式。下文的 include_history=False 跳过策略描述针对直接底层策略注入，非这个组合入口。

状态：2.0.0 `Experimental`，已随 2.0.0 发布，不属于 `2.0.0a9`。`tests/test_knowledge_context.py` 的 36 项本地回归已通过；未进行真实模型/数据库验收或发布。

## 独立组件，不接管 Agent

- `KnowledgeDocument(document_id, text, source="", title="")` 是不可变文本记录，来源是引用标签，不自动打开 URL 或文件。ID 支持有界字符串或 uint64；正文/来源/标题分别最多 1 MiB/4096/1024 UTF-8 字节，repr 隐藏这三个字段。
- `AsyncKnowledgeDocumentStore.get_many(ids)` 按请求 ID 读取正文，必须返回全部且仅这些文档，顺序可不同。内存模板 `InMemoryKnowledgeDocumentStore` 最多 1024 篇、字段总计 16 MiB，不持久化、不负责授权。
- `KnowledgeRetriever.retrieve(query, limit=...)` 返回按相关性排序的唯一文档元组，可自行实现任何检索链路。
- `KeywordKnowledgeRetriever` 是可直接装配的本地模板：对空白分隔查询词做 casefold 子串匹配，按命中词数量排序，同分保留输入顺序；不提供中文分词或语义检索。
- `VectorKnowledgeRetriever` 组合宿主 Embedder、既有 `DenseVectorSearch` 和文档存储。只向 Embedder 传显式查询，向向量后端传向量/候选 ID，再用命中 ID 读取宿主正文，不采用向量服务的任意 payload。
- `AsyncKnowledgeContextPolicy` 组合检索器与同步/异步历史策略，通过既有 `history_policy` 接口提供上下文；不修改 Loop、不新增全局服务、不自动发现或导入插件。

## 无外部服务的装配示例

以下是工作区源码 API，不可假定已发布 a9 可以导入。宿主自行准备 `runtime`，由既有本地运行时装配函数创建。

```python
from w_agent import (
    AsyncKnowledgeContextPolicy, InMemoryKnowledgeDocumentStore,
    KnowledgeDocument, KeywordKnowledgeRetriever,
)

store = InMemoryKnowledgeDocumentStore((
    KnowledgeDocument("refund-v1", "退货期限为签收后七天。", "manual:refund-v1", "退货说明"),
))
retriever = KeywordKnowledgeRetriever(store)
question = "退货 期限"
policy = AsyncKnowledgeContextPolicy(question, retriever, limit=3)
result = await runtime.run(question, history_policy=policy)
```

每次 Run 显式构造当前查询策略，避免重复使用旧查询。空 Session 也会检索。上下文顺序为“历史 → 知识 USER 数据消息 → 本次输入”；无匹配时不附加空知识消息。`include_history=False` 会跳过整个策略，包含知识检索。恢复已有 Run 使用保存的检查点，不重新检索。

该模板只组合 USER/ASSISTANT 文本历史；默认历史策略忽略已记录媒体，复合策略也不重放 name/metadata。需要媒体、其他角色或自定义内容类型时替换策略，不假定此模板自动支持。

## 向量接线

```python
from w_agent import VectorKnowledgeRetriever
from my_application import authorized_embedder, authorized_vector_backend, document_store

retriever = VectorKnowledgeRetriever(
    authorized_embedder, authorized_vector_backend, document_store,
    point_ids=(101, 102),  # 宿主选定的检索范围
)
policy = AsyncKnowledgeContextPolicy(question, retriever)
```

可使用[Qdrant 只读模板](./vector-retrieval.md)或自定义后端。索引必须预先存在；ID 与文档存储精确一致，Qdrant UUID 使用规范字符串。不验证嵌入模型、维度和索引语义一致。`point_ids=None` 显式允许查询所配置集合的全部点；空元组不调用任何组件。有候选集时再次拒绝越界 ID，候选最多 1024，单次结果最多 128。重复命中、缺失/额外/重复正文、错误返回类型均失败，不静默丢弃。

正文存储的权限由宿主实现；候选列表不是 ACL，Python 插件不是沙箱。向量索引与文档存储没有原子快照协议，ID 一致不证明内容仍对应同一版本。需要版本绑定时使用宿主生成的版本化 ID，并管理两个存储。

## 内容、安全与费用边界

- 输出包含版本化 JSON 文档数组，每项保留 ID、source、title、text，以 USER 消息标为不可信参考数据，不提升为系统/开发者指令。JSON 转义和文字标签不保证消除提示注入；来源也未经真实性校验。工具权限、敏感操作批准与模型接收方审查仍由宿主负责。
- 宿主选用策略即授权其查询回调，以及将检索正文发往所选模型；模板不弹出授权窗口。自定义历史策略也可能调用外部服务。检索不自动写索引、下载来源或调用工具。
- 查询最多 4096 UTF-8 字节，结果最多 128 篇。向量检索正文总字段默认上限 1 MiB；上下文策略使用 `SessionHistoryLimits`：历史输入和检索正文分别受 `max_input_bytes` 限制，最终“历史+知识 JSON/标签”的文本总字节和消息数受 `max_output_bytes` / `max_messages` 限制。超限失败，不截断；不包括后续本次输入、系统提示及 Provider 编码开销，不是 Token 限额。
- 先检查原始历史，再执行历史回调与检索；已付费的准备阶段可能在最终上下文超限时失败，不会退款。默认 30 秒整体协程等待限制，错误不回显查询/正文/底层异常，也不自动重试；取消传播并等待协作式清理。不能强制终止阻塞或忽略取消的宿主代码。
- 借用的 Embedder、后端和存储由宿主管理生命周期。查询、向量及正文可敏感，repr 隐藏不等于加密，ID 不隐去；自定义日志仍可能泄露数据。
- 策略不改写 Session。SessionManager 不把合成知识消息作为新增用户输入记录，但模型回答可能复述知识，Run 结果/检查点及宿主观测也可能保留它，不能据此宣称无持久化。
- Embedding/检索准备费用不自动进入 Run TokenBudget、共享池或 Session 总量，需宿主显式计量；未知费用不是零。主模型收到知识后的实际输入 Token 仍走既有模型用量统计，不代替准备阶段账本。

## 本轮进度与剩余

文档协议、内存/关键词模板、向量正文解析、上下文接线及边界本地测试已通过。可与[知识工具](./knowledge-tools.md)、[版本快照](./knowledge-ingestion.md)、[快照向量](./knowledge-vectors.md)及独立[索引清单/回执日志](./knowledge-index-journal.md)组合；其他组件的验证状态以各自文档为准。现有通用工具入口不等于专用检索界面，真实服务验收与其余计划见[路线图](./roadmap.md)。

## 扩展检索与装配

本地 BM25、混合融合和可替换重排见 [知识检索](knowledge-retrieval.md)；专用 [Workflow 与评测装配](knowledge-workflow-evaluation.md) 复用既有检索器和上下文边界。

