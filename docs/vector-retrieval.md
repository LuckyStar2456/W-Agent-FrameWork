# 外部向量检索与 Qdrant 历史选择

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./vector-retrieval.en.md) | 简体中文

状态：2.0.0 `Experimental`，已随 2.0.0 发布，不属于 `2.0.0a9`。`tests/test_vector_retrieval.py` 的 51 项离线回归已通过；没有进行真实 Qdrant/Embedding 服务验收，a9 的验证结论不覆盖此增量。

## 开放协议和首个模板

可显式接入工作区已通过本地回归的 [HTTP Embedding/预算包装器](./embeddings.md)。它不改变候选过滤、历史顺序或 Qdrant 读取边界；不自动授权发送查询正文。

- `AsyncTextEmbedder.embed(text)`：宿主明确授权的异步向量生成协议，返回有限数值的 tuple。框架不选择模型、不读取凭据、不推断查询词。用户可以使用本地模型、自己的模型 Provider 或其他服务，并独立核算费用。
- `DenseVectorSearch.search(vector, *, limit, point_ids=None)`：可替换向量检索协议。返回不可变 `VectorSearchMatch(point_id, score)`；只传匹配 ID/分数，不传远端正文或执行权限。通用匹配 ID 可为非空字符串或 uint64；Qdrant 模板另限制为 UUID/uint64。
- `QdrantVectorSearch`：Qdrant Query API 的只读稠密向量模板。支持默认/具名向量、阈值、候选 ID 过滤、API key 和可替换 `HttpToolTransport`。无 SDK 强依赖；默认惰性使用现有 HTTPX 传输（`models` extra），不会自行安装依赖。
- `QdrantSessionHistoryRetriever`：实现既有 `AsyncSessionHistoryRetriever`，只在当前候选历史中选择，不改变 Runtime 或 Agent Loop。它也接受其他 `DenseVectorSearch` 实现，但历史 ID 约定保持下述规则。

请求采用 `POST /collections/{collection}/points/query`，显式关闭 payload/vector 返回，使用 `using`、`score_threshold` 和可选 `filter.must.has_id`；协议依据 [Qdrant Query API](https://api.qdrant.tech/api-reference/search/query-points) 与 [ID 过滤说明](https://qdrant.tech/documentation/search/filtering/#has-id)。模板不是完整 Qdrant 客户端，不暴露写入、任意查询参数或服务器推理接口。

## 历史索引由宿主准备

工作区现提供独立的[显式向量准备与写入模板](./vector-indexing.md)：历史 Embedding 授权与精确计划覆盖确认分开，检索不会自动调用它；同样已随 2.0.0 发布，本地回归通过，不属于 a9。下文的只读边界仍指检索模板本身。

模板只查询，不创建 collection、不上传历史、不更新向量。宿主应在已授权的索引流程中：

1. 为工程/Session/索引版本选择稳定且不含秘密的 `namespace`，并组织与历史策略相同的连续 Run 文本段 `SessionHistoryTurn`。
2. 调用 `qdrant_history_point_id(namespace, turn)` 生成索引 point ID，用宿主选定的 Embedding 模型生成该段向量并写入 Qdrant。索引与查询使用相同模型、维度和具名向量设置；本文不自动执行这些操作。
3. 用相同 namespace 构造选择器，显式传入查询词。选择器只给 embedder 查询文本；搜索端只收到查询向量及候选 ID，不收到历史正文、Session 标题、name/metadata。

ID 是版本标记、namespace、Run ID、有序角色及文本块的规范 JSON 的 SHA-256 前 128 位转换成 UUID。名称/元数据不参与。改变文本、顺序、Run ID 或 namespace 会得到不同 ID，需宿主重建索引。相同内容的重复段会造成歧义，选择器拒绝，而不是猜测位置。它不是租户标识、权限域、签名或秘密；可猜测内容可能被字典匹配。远端索引的向量是否确实对应此 ID 仍由宿主负责，哈希不证明相关性。

```python
import os
from w_agent import (
    AsyncRetrievedSessionHistoryPolicy, QdrantSessionHistoryRetriever,
    QdrantVectorSearch, load_local_runtime_config, assemble_local_runtime,
)
from my_application import authorized_embedder  # 宿主提供 embed(text) 异步实现。

backend = QdrantVectorSearch(
    base_url="http://127.0.0.1:6333", collection="support_history",
    api_key=os.environ.get("QDRANT_API_KEY"), vector_name="dense",
)
retriever = QdrantSessionHistoryRetriever("support-session-v1", authorized_embedder, backend)
history = AsyncRetrievedSessionHistoryPolicy(
    query="退款处理证据", retriever=retriever,
    max_retrieved_turns=4, recent_turns=2,
)
config = load_local_runtime_config("runtime.json")
async with assemble_local_runtime(config) as runtime:
    run = await runtime.run(
        "继续处理退款", session_id="existing-session-id", history_policy=history,
    )
```

示例要求工程/已有 Session、索引、Embedding 及模型调用均已得到宿主授权。最外层历史策略恢复历史时间顺序并保留近期段；后端得分只是候选选择信号。没有旧段时不调用 embedder/后端；有效但无命中的索引只留下近期段，不自动降级为全历史。HTTP 失败、缺失 collection 或无效结果则失败关闭，不自动重试。

也可以独立调用 `await backend.search((0.1, 0.2), limit=4)` 获得 ID/得分，由宿主自定义其他文档存储和内容策略。省略 `point_ids` 明确查询整个 collection；传空 tuple 则不发送请求，绝不解释为取消过滤。历史选择器始终传候选集，并再次校验自定义后端结果，不能借返回陌生 ID 引入远端文本。

## 边界、生命周期与计量

- 模板每次最多 128 个结果、1024 个候选 ID，向量 1–65536 维；拒绝 bool、NaN、Infinity、重复 ID 或非 tuple 向量。历史输入另受 `SessionHistoryLimits` 约束；单个 ID 输入最多 1024 条消息、4096 个文本块和 1 MiB 文本，Run ID 最多 512 UTF-8 字节。
- 请求/响应正文默认各限 1 MiB，可分别配置至 16 MiB。默认传输流式限制响应字节；自定义传输返回后再次校验大小。自定义传输自身的内存、解压缩、内部重试不受此检查控制。
- 端点只允许 HTTP(S)，拒绝 URL 用户密码、查询、fragment 和空白控制字符；collection 使用受限名称。默认不跟随重定向；HTTP 失败和重复 JSON 字段失败关闭。URL 校验不是 SSRF 防护、网络隔离或权限策略，宿主负责允许的目标、TLS、代理和文件/网络权限。API key 只应发给受信目的地。
- API key、端点、collection 不进入后端 repr；错误是固定消息，不回显查询、凭据、服务端错误正文。传输日志、网络追踪、自定义 callback 和应用主动打印 request 仍可能泄漏内容，宿主需自行处理。
- 默认传输按请求创建并关闭客户端；自定义传输/Embedder 是借用对象，不会被 Runtime 自动关闭。宿主应在所有调用结束后释放自己的连接，不把借用对象视作框架沙箱。
- 后端 timeout 覆盖请求等待，选择器 timeout 覆盖 Embedding 加检索；默认各 30 秒，历史策略另有独立 timeout。异步取消向上传播，不变成成功或空结果；同步回调阻塞或忽略取消的扩展无法被强制终止，取消也不能撤销已发生的外部费用。
- Embedding、Qdrant 资源使用与索引任务不自动进入 Agent `TokenBudget`、共享预算池或 Session 用量；Qdrant 响应的服务资源指标不冒充 LLM Token。付费 Embedder 必须由宿主在回调内接入相应预留/计量。本模板不宣称实现准备阶段/主 Run 统一账本。

## 后续与验证

请求映射、候选边界、隐私、异常、大小限制、取消及 Session 策略接线本地测试已通过。独立索引准备/写入见上文；[知识正文检索与上下文策略](./knowledge-context.md) 和新增 [BM25/混合/重排](./knowledge-retrieval.md) 已有离线回归。真实 Qdrant/Embedding 服务验收、其他后端与其余计划见[路线图](./roadmap.md)。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
