# 模型、路由与接口探测

[English](./model-routing.en.md) | 简体中文

状态：Phase 2A 基础，以及 Phase 2B 通用 HTTP 映射层、OpenAI-compatible Provider、首批厂商模板与收集式调用/重试/故障转移执行器为 `Implemented`（`2.0.0a1`）；OpenAI Responses、vLLM 专用适配、透传流执行、注册自动探测和 CLI/TUI 入口为 `Planned`。

## 已实现边界

- Provider 中立的消息、内容块、工具定义、请求、模型描述和响应。
- 文本、图像、音频、工具调用、结构化输出、Reasoning、Prompt Cache 等标准能力声明。
- 严格流事件：块开始、文本/工具增量、块结束、Usage、标准错误和 Finish。
- `ModelProvider`、`ModelRegistry`、`CancellationToken` 和标准错误分类。
- 可解释的 `WeightedRoutingPolicy`、安全 YAML 策略和 `ModelRouter`。
- L1 端点嗅探、L2/L3 Provider 检查、显式授权的 L4/L5 主动探测、缓存与周期调度。
- OpenAI-compatible `/models` 与 `/chat/completions` Provider，包括文本、图像/内联音频输入、工具、结构化输出和 SSE 流转换。
- 可替换的 `HttpModelProvider`、请求/流帧、映射器、流解码器与 HTTP 传输协议；默认传输支持 JSON、SSE 和 NDJSON。
- Anthropic Messages、Gemini `streamGenerateContent`、Ollama `/api/chat` 和 Qwen DashScope 原生模板。
- DeepSeek、GLM、Qwen OpenAI-compatible 和 Turbo AI/SIAM.AI 模板及独立模板注册表。
- `ModelExecutor` 收集式调用、逐尝试超时、显式有界重试/故障转移和不含 Prompt 的尝试记录。

当前仍未内置专用 OpenAI Responses 或 vLLM 差异适配器。模板经过模拟传输一致性测试，但仓库测试不携带真实凭据，也不把某一远程型号的在线可用性当作已验证事实。完整模板说明见 [HTTP Provider 与厂商模板](./provider-templates.md)。

## 模型协议

`ModelRequest` 使用类型化标准字段和 `extensions` 命名空间。请求会从消息内容、工具和响应 Schema 推导路由所需能力。`ModelDescriptor` 声明模型身份、能力、上下文窗口、输出上限、Reasoning 档位和 Provider 扩展。

Provider 实现同一公开协议：

```python
class ModelProvider(Protocol):
    async def list_models(self) -> tuple[ModelDescriptor, ...]: ...
    async def resolve(self, model: str) -> ModelDescriptor: ...

    def stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[StreamEvent]: ...
```

`collect_stream()` 拒绝未开始块的增量、重复块、存在未关闭块的 Finish、Finish 后事件以及没有 Finish 的不完整流。Provider 可抛出 `ModelError`，也可发送 `ErrorEvent`；两者携带同一 `ModelFailure` 分类。

## Provider 注册

`ModelRegistry` 建立在统一 `Registry` 上，因此继承版本与作用域解析规则：

```python
models = ModelRegistry(shared_registry)
registration = models.register(
    "my-provider",
    provider,
    version="1.0.0",
    scope=ScopePath.application(),
)

resolved = models.provider("my-provider")
registration.dispose()
```

第三方实现不需要继承框架基类；满足 `ModelProvider` 协议即可。

### OpenAI-compatible Provider

安装可选 HTTP 传输：

```bash
pip install "wagent-framework[models]"
```

```python
from w_agent import (
    ModelCapability,
    OpenAICompatibleModelProfile,
    OpenAICompatibleProvider,
)

provider = OpenAICompatibleProvider(
    name="local",
    base_url="http://127.0.0.1:11434/v1",
    default_model="my-model",
    profiles=(
        OpenAICompatibleModelProfile(
            "my-model",
            frozenset(
                {
                    ModelCapability.TEXT_INPUT,
                    ModelCapability.TEXT_OUTPUT,
                    ModelCapability.STREAMING,
                }
            ),
        ),
    ),
    discover_models=False,
)
```

能力不会根据模型名称猜测；开发者必须用 Profile 明确声明非默认能力。`openai_compatible.body` 扩展可加入厂商参数，但不能覆盖模型、消息、流、工具、结构化输出等核心字段。HTTP 传输通过 `OpenAICompatibleTransport` 可替换，核心不依赖具体 SDK。

### 通用 HTTP 映射层与模板

`HttpModelProvider` 组合 `HttpProviderMapping` 与 `HttpProviderTransport`。映射器生成模型目录/推理请求并把厂商帧转换为标准事件；传输只处理 HTTP、SSE 或 NDJSON。应用可以替换其中任意一层，也可以把自己的 `ProviderTemplate` 注册到独立 `ProviderTemplateRegistry`。

内置 key 为 `anthropic`、`gemini`、`ollama`、`qwen-native`、`deepseek`、`glm`、`qwen` 和 `turbo`。`turbo` 指 Turbo AI/SIAM.AI，要求显式提供部署地址。Qwen 同时提供原生 DashScope 与 OpenAI-compatible 两条入口。

## 可解释路由

路由管线为：

```text
当前模型目录
  → 指定模型与 Provider allow/deny 过滤
  → 标准能力匹配
  → 健康与成本过滤
  → 质量/延迟/成本/健康/偏好评分
  → 选择与有序备用列表
  → RouteDecision
```

`RouteDecision` 保存 Provider/模型、所有候选的接受或拒绝原因、得分、备用顺序、策略名/版本和请求计数摘要，但不保存提示词明文或密钥。

Python 代码可以实现任意 `RoutingPolicy.select()`。内置 `WeightedRoutingPolicy` 提供可调整权重；`YamlRoutingPolicy` 使用 `yaml.safe_load` 将声明规则编译到同一接口，不导入或执行 YAML 中的代码。

```yaml
name: local-first
version: 1
preferred_providers: [ollama]
deny_providers: [disabled-provider]
max_cost_per_million: 20
required_capabilities: [streaming]
weights:
  quality: 1.0
  latency: 0.5
  cost: 0.8
  health: 1.0
  preferred_provider: 0.5
```

`ModelRouter` 继续只负责产生决定；`ModelExecutor` 是独立 Consumer，按决定调用 Provider。两者可以分别替换，不把执行策略写入路由策略。

## 调用、重试与故障转移

`ModelExecutor.invoke()` 消费路由决定并返回 `ModelInvocationResult`，其中包含完整 `ModelResponse`、实际成功的 Provider/模型、原始 `RouteDecision` 和不可变 `AttemptRecord` 列表。

```python
from w_agent import InvocationPolicy, ModelExecutor

executor = ModelExecutor(
    models,
    router,
    InvocationPolicy(
        max_attempts_per_route=2,
        max_routes=2,
        timeout=30,
        initial_backoff=0.25,
    ),
)
result = await executor.invoke(request)
```

默认策略为每条路由一次、最多一条路由，即不会在未配置时产生额外可能计费的模型请求。把任一上限提高视为开发者对本次装配的显式重放授权。只有同时标记 `retryable=True` 且属于限流、超时、网络或 Provider 故障的标准错误才会重试；鉴权、配置、内容策略和协议错误默认立即停止。退避是确定、有上限且可替换的；自定义策略只需满足 `InvocationPolicyProtocol`。

当前执行器在返回前通过 `collect_stream()` 收集并校验整个 Provider 流。这允许在半截结果尚未暴露给调用者时安全切换路由，但不提供逐 Token 透传。低延迟透传模式需要“一旦输出事件就禁止自动重放”的独立执行语义，仍为 `Planned`。

调用者可传入 `replay_safe=False` 强制只执行选中路由一次，即使装配策略允许重试。尝试记录只保存 Provider、模型、序号、耗时、标准失败和下次退避，不保存消息、Prompt、请求体或凭据。执行器不会自动修改 `CandidateState`，健康反馈仍由显式观测插件负责。

## 接口探测

| 级别 | 当前行为 | 是否可能产生模型费用 |
|---|---|---|
| L1 | `EndpointProbe` 检查 URL、DNS、TCP、TLS、HTTP | 否 |
| L2 | Provider 是否接受模型目录请求，并归一化访问失败 | 否 |
| L3 | 读取模型目录与声明能力 | 否 |
| L4 | 最小文本生成 | 是；必须 `allow_active=True` |
| L5 | 验证完整流终止协议 | 是；必须 `allow_active=True` |
| L6 | 工具/结构化能力仅报告声明，状态为 `SKIPPED` | 当前不执行 |
| L7 | 多模态能力仅报告声明，状态为 `SKIPPED` | 当前不执行 |

`EndpointProbe` 不发送凭据和请求体，结果目标会移除 URL 用户信息、查询串和片段。HTTP 4xx/5xx 仍证明端点可达；鉴权语义由 Provider Probe 处理。

`ProbeResult` 包含模式、分项状态、时间、延迟、失败类别、探测器版本和过期时间。`ProbeCache` 不返回过期结果。`PeriodicProbeService` 可以周期运行任意探测回调，但只产生结果，不修改用户配置。

手动 Python API 和通用周期调度已经实现。插件可以在注册流程中显式调用同一 API；框架级注册自动挂接及 `wagent probe`/TUI 页面仍为 `Planned`。

## 错误与安全边界

稳定错误类别包括配置、鉴权、限流、超时、网络、协议、内容策略、Provider、取消。路由决策可消费健康状态但本身不执行重试；`ModelExecutor` 只按显式 `InvocationPolicy` 处理标准化失败。

主动探测必须由调用者显式设置 `allow_active=True`。此授权只覆盖当前调用，不会持久化，也不会从装配编码导入。模型执行器的 `replay_safe` 只描述模型请求；后续工具执行器仍不得自动重放已经产生副作用的工具调用。

## Phase 2B 后续计划

- 专用 OpenAI Responses 与 vLLM 差异适配器；扩展现有模板的 Reasoning 增量和更多厂商特性。
- 注册时自动安全探测、CLI/TUI 探测入口和健康状态桥接。
- 逐 Token 透传调用、跨流断点恢复以及与健康状态/限流器的可插拔反馈桥接。
- L6/L7 可插拔主动验证器；所有可能产生费用的验证继续要求显式授权。
