# 稀疏、混合检索与重排

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

状态：2.0.0 Experimental，已随 2.0.0 发布。实现与离线回归覆盖本地 BM25、RRF 融合、候选重排及 Workflow/评测装配；没有真实外部服务或检索质量基准验收。

`w_agent.knowledge_retrieval` 的组件均实现既有 `KnowledgeRetriever`，可以传给 `LocalKnowledgeBinding`、`knowledge_search_tool` 和 `AsyncKnowledgeContextPolicy`。构造不进行网络调用、不发现服务、不安装模型。宿主显式提供已授权的语料、dense retriever 和可选重排器。

```python
from w_agent.knowledge_context import InMemoryKnowledgeDocumentStore, KnowledgeDocument
from w_agent.knowledge_retrieval import BM25KnowledgeRetriever
from w_agent.knowledge_runtime import LocalKnowledgeBinding

store = InMemoryKnowledgeDocumentStore((
    KnowledgeDocument("refund", "退款申请须在七天内提交", "local:refund"),
    KnowledgeDocument("delivery", "配送通常需要三天", "local:delivery"),
))
sparse = BM25KnowledgeRetriever(store)
binding = LocalKnowledgeBinding(sparse, limit=2)
# 在 async 宿主中：await sparse.retrieve("退款", limit=2)
```

BM25 使用标题和正文，保留其他 Unicode 单词边界，对 CJK 逐字分词。无匹配返回空 tuple；同分按原始语料顺序。它是小语料本地基线，没有语言模型、中文词典或持久化倒排索引。默认 `k1=1.2`、`b=0.75`，支持显式替换。

混合检索通过 `HybridKnowledgeRetriever((dense, sparse), candidate_limit=32)` 装配；`dense` 可使用既有 `VectorKnowledgeRetriever`。每个来源最多获取 `candidate_limit` 条结果，以 `sum(weight / (rank_constant + rank))` 进行 reciprocal-rank fusion，rank 从 1 开始，默认常数 60、等权重。原始后端分数不直接比较。来源顺序和排名决定同分顺序。相同 ID 必须对应相同正文、标题和来源，否则失败；因此索引分支应使用相同的固定知识版本。两到八个来源按宿主顺序执行，共用总超时；任一失败不返回部分证据。

```python
from w_agent.knowledge_retrieval import (
    BM25KnowledgeReranker, HybridKnowledgeRetriever, RerankedKnowledgeRetriever,
)

# dense 是宿主预先装配、授权的 KnowledgeRetriever。
hybrid = HybridKnowledgeRetriever((dense, sparse), candidate_limit=32)
retriever = RerankedKnowledgeRetriever(
    hybrid, BM25KnowledgeReranker(), candidate_limit=32,
)
```

`KnowledgeReranker.rerank(query, documents, *, limit)` 是异步协议，返回候选位置的唯一整数 tuple。例如 `(2, 0)` 选择原候选的第 3 和第 1 项。允许空结果；不允许重复、越界位置或替换正文。`BM25KnowledgeReranker` 是可用的本地实现；语义/外部重排器由宿主实现及授权，其收到查询和完整候选正文。无词面匹配的候选仍按原顺序排在末尾。

融合与重排的请求 `limit` 不能超过 `candidate_limit`（最大 128）。候选与融合正文总量受 `max_document_bytes` 限制；超限失败，不静默截断。超时和 asyncio 取消会等待借用协程退出；不能证明外部服务停止执行或退款。各来源负责自身授权范围，融合不产生新访问权限。

验证入口：`py -3.11 -m pytest tests/test_knowledge_retrieval.py`。端到端装配见 [Workflow 与评测](knowledge-workflow-evaluation.md)。
