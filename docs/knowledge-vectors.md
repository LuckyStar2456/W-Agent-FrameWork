# 知识快照向量准备与固定版本检索

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-vectors.en.md) | 简体中文

2.0.0 Experimental：本地回归通过，已随 2.0.0 发布，不属于 2.0.0a9；真实服务、费用、质量及人工生产界面仍待验收。

## 组合既有组件

工作区已有通过本地回归的 [HTTP Embedding 与共享预算模板](./embeddings.md)，可作为本页 embedder；需要预算时显式包装，共用 controller 不等于自动归入 Run/Session 用量。

本模块连接[知识版本快照](./knowledge-ingestion.md)、宿主 `AsyncTextEmbedder`、已有 `DenseVectorPoint` / [显式 Qdrant Writer](./vector-indexing.md)及[知识检索接口](./knowledge-context.md)。索引身份、向量准备、写入与检索保持独立，不绑定某个模型 SDK，不接管 Agent Loop。

1. `KnowledgeVectorIndex(snapshot, embedding_key, dimensions)` 只构造身份映射，无模型、文件或网络操作。
2. `prepare_knowledge_vectors(index, embedder, confirm_embedding=True)` 显式向宿主 Embedder 披露所选文档标题/正文，返回向量点；不会写入远端。
3. 宿主另外创建 Writer 计划、审查目标与覆盖风险，再使用已审查摘要执行 upsert。正文嵌入许可不代替写入许可。
4. `SnapshotVectorKnowledgeRetriever(index, embedder, backend)` 查询相同的点 ID 集，解析本地快照正文，返回原始文档 ID、来源、标题和内容。可传入 `knowledge_search_tool()` 或 `AsyncKnowledgeContextPolicy`。

```python
from w_agent import (
    KnowledgeVectorIndex, QdrantVectorSearch, QdrantVectorWriter,
    SnapshotVectorKnowledgeRetriever, prepare_knowledge_vectors, knowledge_search_tool,
)
from my_application import authorized_embedder, review_exact_upsert

# snapshot 由宿主创建或从 SQLite 明确加载版本。
# 标签由宿主维护，涵盖模型/权重/预处理版本；1536 仅为示例维度。
index = KnowledgeVectorIndex(snapshot, "my-embedding-pipeline-v1", dimensions=1536)
points = await prepare_knowledge_vectors(index, authorized_embedder, confirm_embedding=True)

# collection 及维度/距离配置须预先准备；不自动创建。
backend = QdrantVectorSearch("http://127.0.0.1:6333", "support_knowledge")
writer = QdrantVectorWriter(backend)
plan = writer.plan(points)
reviewed_digest = await review_exact_upsert(plan)  # 宿主真实审查，不自动相信计划自报摘要。
receipt = await writer.upsert(plan, confirm_digest=reviewed_digest)
if not receipt.applied:
    raise RuntimeError("Index operation is not confirmed completed; inspect remote state")

retriever = SnapshotVectorKnowledgeRetriever(index, authorized_embedder, backend)
binding = knowledge_search_tool(retriever)  # 默认仍需要权限和逐调用审批。
```

本例适用于非空、最多 128 篇且满足请求上限的单批快照。空快照准备返回空元组，不应拿它创建非空 upsert 计划。更大快照由宿主显式传 `document_ids=(...)` 选择最多 128 个原始 ID，每批分别准备、审查和保存回执；不是自动批处理/断点续传或跨批原子写入。

## 文档身份与向量身份

- `KnowledgeVectorIndex.snapshot_digest` 取整个快照的规范内容摘要。每个向量 UUID 绑定格式、快照摘要、`embedding_key`、维度、原文档 ID。快照版本、内容、顺序、引用或 Embedding 标签/维度变化均会改变点 ID；不同快照不会主动复用旧点。
- `index.point_ids` 顺序与快照文档一致；`index.point_id(original_id)` 做本地精确映射。原始字符串 ID 与整数 ID 区别保留，布尔值拒绝。即便宿主直接构造快照并跨版本复用原文档 ID，此映射仍根据快照摘要生成不同向量 ID。
- 从 SQLite 重开相同快照，并使用相同格式/Embedding 标签/维度，可重建相同映射，不依赖“最新版本”或临时进程状态。可另外选用已通过本地回归的[索引清单与持久回执](./knowledge-index-journal.md)，仍不会自动重新执行写入。
- `embedding_key` 是宿主声明，不会自动传给或验证 Embedder 的模型身份。准备与查询必须使用兼容模型/预处理，框架只检查有限数值和声明维度。相同维度不证明语义兼容；更换模型时应更新标签并重新准备索引。
- `KnowledgeVectorIndex` 不是索引存在性、远端完整性或成功写入回执。摘要/点 ID 不是授权、签名、秘密或匿名化；UUID 为摘要前 128 位，无法承诺数学上零碰撞。后端/collection 不纳入此身份映射，具体目标由独立 Writer 计划绑定。

## 披露、限制与失败

- `knowledge_document_embedding_text(document)` 仅在本地渲染版本化 JSON 的 title/text，不加入 source、原 ID、namespace/version；这些字符串若本来就在正文中，不会被脱敏。该输出包含知识正文，不应自动记录日志。
- `confirm_embedding` 必须为布尔 True。所有批次 ID、重复/范围检查、实际渲染文本总大小和声明维度的向量数量预算，在第一个 Embedding 回调前验证。未指定 `document_ids` 选择整个快照，但超过 128 篇直接拒绝，不截断；空选择不调用 Embedder。
- 默认每批实际输入 JSON 最多 1 MiB，可设至 32 MiB；`max_vector_values` 默认 1,048,576 个坐标，可设至 8,388,608。声明维度为 1–65,536。坐标数量/字节限制不是 Token、费用或 Python 进程内存的精确限制。
- 默认 30 秒超时覆盖整批顺序嵌入，向量必须为有限数值元组且维度精确一致。失败不返回部分点，不自动重试；此前 Embedding 调用仍可能已收费。取消传播并依赖协作式清理，不能强制终止阻塞或忽略取消的回调。
- Writer 的请求大小限制在生成向量后才可精确检查，计划被拒绝不代表此前嵌入免费。沿用已有完整 upsert 覆盖语义、精确计划确认、已接收/已应用区分及未知结果处理；不自动回滚、清理旧版本、轮询或重试。
- 检索只发送当前快照/Embedding 绑定的候选点 ID，空快照不调用 Embedder 或后端；查询向量维度不符时在调用搜索后端前拒绝。继承现有检索器的超时、唯一/候选 ID 检查和文档总大小限制，恢复原始文档 ID 后再次计入字段限额，保持后端排序。
- 后端没有找到某点不等于没有相关文档，也可能是索引尚未完整写入。普通检索返回命中子集，不校验所有候选点的远端存在性或向量内容。宿主应在公布可用版本前核对所有批次回执及检索效果。
- 正文来自本地快照，不采用远端 payload，不自动打开来源或执行文本。候选过滤不是 ACL，数据标签不是提示注入防护；宿主负责权限、模型接收方、工具批准及敏感数据管理。
- Embedder、后端及相关客户端由宿主拥有和关闭。Embedding/检索费用未自动归集到 Agent/Session/共享预算；不能以未知为零。索引准备与远端写入也不会由知识工具、Session 保存或 Agent Run 自动触发。

## 本轮进度与剩余

绑定 ID、批次准备、检索、原 ID 恢复及准备→写入→重开→检索接线的本地模拟传输回归通过。[计划动作](./knowledge-plan-actions.md)、[构建恢复](./knowledge-build-recovery.md)和日志目录已提供显式本地生命周期管理。更多 Embedding 模板、远端证据/查询、差异同步、跨存储一致性、统一准备费用账本和真实 Qdrant 验收仍未完成。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
