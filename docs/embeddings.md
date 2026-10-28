# HTTP Embedding、原生模板与共享预算

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./embeddings.en.md) | 简体中文

2.0.0 Experimental：本地回归通过，已随 2.0.0 发布，不属于 2.0.0a9；真实服务、费用、质量及人工生产界面仍待验收。

## 协议与模板

`AsyncEmbeddingProvider.embed_result(text)` 返回 `EmbeddingResult(vector, model, usage)`。`HttpTextEmbedder` 同时提供 `embed(text) -> tuple[float, ...]`，兼容已有 `AsyncTextEmbedder`、历史选择器、正文检索及 `prepare_knowledge_vectors()`。`embed()` 只返回向量；需保留用量时调用结构化接口或使用下述预算包装器，不能把丢弃的用量当作零。

`HttpEmbeddingMapping` 的同步 `build_body(text, model=...)` / `parse_response(payload)` 可整体替换。适配器固定 endpoint、POST 方法和 headers，映射只处理 JSON 正文。映射是受信宿主代码，应保持纯转换，不在其中隐藏外部调用；框架不隔离它，也不计量它自行产生的副作用。

- `JsonEmbeddingMapping` 支持自定义顶层 input/model 字段、固定参数 JSON、嵌套向量/模型/输入 Token 路径。路径用字符串键和非负整数列表下标组成的元组，不执行表达式。固定参数不能覆盖 input/model 字段。配置的可选用量/模型字段缺失时为 None，非法类型失败；它校验映射值，不推断服务自定义成功标志；需校验这些标志时替换整个 mapping。
- `openai_compatible_text_embedder(base_url, model, dimensions, ...)` 使用 `OpenAIEmbeddingMapping`，base_url 包含 API 前缀（例如 `/v1`），末尾追加 `/embeddings`。请求 `encoding_format="float"`；`request_dimensions=True` 才发送 dimensions 参数，否则 dimensions 只校验返回长度。维度参数的模型支持范围由服务决定，参见 [OpenAI 官方接口](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create)。模板只接收一个 index=0 的向量，并读取 prompt_tokens/total_tokens。
- `ollama_text_embedder(base_url, model, dimensions, ...)` 使用 `OllamaEmbeddingMapping`，服务根地址末尾追加 `/api/embed`，不是旧 `/api/embeddings`。显式 `truncate=false`，从 embeddings 单元素数组和 prompt_eval_count 读取结果；可显式请求维度，参见 [Ollama 官方接口](https://docs.ollama.com/api/embed)。不会自动拉取模型、安装或启动服务。

两类模板都由用户指定模型与预期维度，不内置“最新模型”、自动选择、价格或模型能力推断。兼容 OpenAI 请求格式不保证任意供应商模型支持 Embedding。

## 装配与知识链路

```python
from w_agent import (
    KnowledgeVectorIndex, SharedBudgetTextEmbedder,
    openai_compatible_text_embedder, prepare_knowledge_vectors,
)
from my_application import embedding_settings, embedding_meter, shared_controller

# my_application 为宿主配置/实现，不是框架内置模块。
raw = openai_compatible_text_embedder(
    embedding_settings.base_url,
    embedding_settings.model,
    embedding_settings.dimensions,
    api_key=embedding_settings.api_key,
)
embedder = SharedBudgetTextEmbedder(raw, shared_controller, embedding_meter)

# snapshot 由宿主显式读取/准备；标签须描述实际模型、参数与版本。
index = KnowledgeVectorIndex(snapshot, embedding_settings.version_label,
                             embedding_settings.dimensions)
points = await prepare_knowledge_vectors(index, embedder, confirm_embedding=True)
# 这里没有远端索引写入；随后仍需独立审查 Writer 计划并确认。
```

示例未执行。相同 embedder 可交给 `SnapshotVectorKnowledgeRetriever` 或 `QdrantSessionHistoryRetriever` 查询。调用 `embed()`/`embed_result()` 本身即可发出一次可能收费的请求，没有额外确认参数；宿主必须在调用前取得所需授权。批次准备保留既有 `confirm_embedding=True` 边界，查询则沿用调用方/工具审批，不自动授予网络权限。

不读取环境变量或配置里的隐式凭据。OpenAI 工厂的显式 api_key 加入 Bearer header；通用 headers 可用于其他认证，不能同时指定两份 Authorization。原始文本、headers、HTTP request/response 对象可能含秘密，禁止直接记录它们；适配器 repr 隐藏 endpoint/model/headers/mapping，结果 repr 隐藏向量和模型，但这不是日志系统脱敏保证。

## 响应、身份与失败边界

- 构造不发请求、不导入可选 HTTPX；默认沿用有界 `HttpxToolTransport`，每次调用关闭自己的客户端，默认不跟随重定向。自定义传输是借用资源，由宿主管理关闭、代理、重定向、日志和隐含重试。
- 仅接受 HTTP(S) endpoint，拒绝 URL 用户名/密码、query、fragment 和控制字符；路径/头仍由可信宿主选择，不做 SSRF 沙箱或目标权限核验。额外 headers 最多 32 个、每值最多 4096 个可打印 ASCII 字符，拒绝重复大小写键、Host/Content-Length/Transfer-Encoding，Content-Type 固定 JSON。
- 默认单次输入最多 1 MiB，JSON 请求/响应各 2 MiB；请求/响应上限可调至 16 MiB。输入不能全空白。请求序列化后限制大小，响应解码前限制字节，拒绝非 2xx、重复 JSON 键、非有限数字、非法向量、维度不符。OpenAI/Ollama 原生映射另行拒绝其错误对象。字节限制不是 Token 上限；没有 Token 截断或 tokenizer。
- 返回模型名是服务声明，不是认证。默认允许服务解析模型别名；可设 `expected_response_model` 精确匹配返回字符串，但不能证明权重或服务身份。`KnowledgeVectorIndex.embedding_key` 仍由宿主保证正确。
- 向量为 1–65536 维有限实数，不接受布尔值、空向量或自动补齐/裁剪。默认模板只发单文本，拒绝多结果，未实现批量排序、Base64 向量或多模态 Embedding。
- 用量缺失保留 None；有值时要求非负整数且小于 2^63。输入 Token 按服务报告，输出 Token 为 0（向量坐标不是输出 Token）；OpenAI 模板要求 total_tokens 与 prompt_tokens 相等。没有服务端用量时不从字符长度估算成“实耗”。
- 默认 30 秒协程超时主要约束等待传输；同步映射/阻塞或忽略取消的自定义代码不能被强行停止。取消独立传播，不能撤销远端费用。普通失败返回固定 `EmbeddingError`；`may_have_called=True` 表示已进入传输，非成功、坏响应或超时也可能收费。没有自动重试、备用模型或网络请求回放。

## 共享预算与可见用量

`EmbeddingBudgetMeter` 是可替换宿主协议：`bound(text)` 返回可靠上界 `SharedBudgetAmount`，`actual(text, result)` 返回保留服务用量的实耗及可选计价。需绑定精确 Provider/模型/参数，覆盖全部计费单位；没有内置字符转 Token 上界或固定价格，回调不得递归调用付费模型。

`SharedBudgetTextEmbedder(provider, controller, meter)` 兼容两个 Embedding 接口。可与摘要/主模型使用同一 `InMemorySharedBudget` 或同一个已显式初始化的 `SQLiteSharedBudget`，不新建租户或独立平台。行为如下：

1. 先校验输入、取得上界并 reserve；拒绝入场不调用 Provider。
2. 有合法服务端用量时计价、settle，然后才返回结果。meter 不能改写服务用量。实耗超过预留仍记录实耗并报错，不将超额结果当成功返回。
3. 明确的 HTTP 传输前失败释放票据；用量缺失、Provider 错误、取消或计价/结算失败尝试标记 unknown。若清理失败，pending 仍保留预留，不宣称已释放；需 inspect/snapshot 对账。

`controller.snapshot()` 的 known_usage/held_usage、known_cost/held_cost 和票据状态可供宿主展示。若同一池已通过现有 Runtime 预算绑定展示，其池级总量可包含这些调用；不会自动加入某个 Agent Run 的 Usage、Session 历史或摘要报告。来源文件、文本、请求模型标签和调用任务关联不写入共享票据；宿主需另外保管对应关系。未包装的 Embedding/检索/工具调用不会自动纳入。

取消或存储返回失败可能发生在提交之后；不能盲目重跑以“补记账”。沿用[共享预算的证据对账](./shared-budget.md)，不自动认定未收费。借用客户端、统一任务账本、真实上界和价格维护仍由宿主管理。

## 进度与剩余

映射、原生模板、Token 解析、共享预算包装及模拟 HTTP/知识库/SQLite 预算本地回归通过。其他原生 Embedding 模板、批量/多模态、Embedding 专用 Runtime/CLI/TUI 配置、准备阶段与主 Run 自动关联账本、真实厂商/Qdrant 联调和最终验收仍未完成。见[路线图](./roadmap.md)。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
