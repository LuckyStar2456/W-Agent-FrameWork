# 模型、路由与接口探测

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./model-routing.en.md) | 简体中文

状态：Phase 2A 基础，以及 Phase 2B 通用 HTTP 映射层、OpenAI-compatible Provider、OpenAI Responses/vLLM 专用适配、厂商模板、收集式/逐事件透传执行器、显式验证前缀的文本流恢复、显式注册安全探测服务和 CLI/TUI 探测入口为 `Implemented`/`Experimental`（`2.0.0a4`）。原生游标协议与执行器接线已有独立 Responses Provider 和 SQLite 跨进程事件恢复实现，普通模板及完整 Agent 会话尚未接入；详见[Responses 续流](responses-continuation.md)。

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
- OpenAI Responses `/responses` 请求/流事件映射，以及 vLLM Chat Completions 专用命名空间扩展。
- `ModelExecutor` 收集式与逐事件透传调用、逐尝试超时、显式有界重试/故障转移和不含 Prompt 的尝试记录。
- `ModelRegistrationProbeService` 注册安全探测路径，以及把未过期结果映射到外部 `CandidateState` 的 `ProbeHealthBridge`。

OpenAI Responses 与 vLLM 适配经过模拟传输一致性测试，但仓库测试不携带真实凭据，也不把某一远程型号或本机 GPU 服务的在线可用性当作已验证事实。完整模板、扩展字段和剩余限制见 [HTTP Provider 与厂商模板](./provider-templates.md)。

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

`ModelStreamValidator` 增量校验事件；`collect_stream()` 复用同一校验器并收集最终响应。它们拒绝未开始块的增量、重复块、存在未关闭块的 Finish、Finish 后事件以及没有 Finish 的不完整流。Provider 可抛出 `ModelError`，也可发送 `ErrorEvent`；两者携带同一 `ModelFailure` 分类。

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

内置 key 为 `openai-responses`、`anthropic`、`gemini`、`ollama`、`qwen-native`、`deepseek`、`glm`、`qwen`、`vllm` 和 `turbo`。`turbo` 指 Turbo AI/SIAM.AI，要求显式提供部署地址。Qwen 同时提供原生 DashScope 与 OpenAI-compatible 两条入口。OpenAI Responses 走 `/responses` 类型化事件；vLLM 保持 Chat Completions 并通过 `vllm.*` 扩展暴露专用参数。

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

`ModelExecutor.invoke()` 消费路由决定并返回 `ModelInvocationResult`，其中包含完整 `ModelResponse`、实际成功的 Provider/模型、原始 `RouteDecision` 和不可变 `AttemptRecord` 列表。`ModelExecutor.stream()` 返回单次消费的 `ModelStreamExecution`，实时暴露标准 `StreamEvent`；迭代完成后可读取 `response`、实际 Provider/模型和尝试记录。

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

execution = executor.stream(request)
async for event in execution:
    handle(event)

final_response = execution.response
```

默认策略为每条路由一次、最多一条路由，即不会在未配置时产生额外可能计费的模型请求。把任一上限提高视为开发者对本次装配的显式重放授权。只有同时标记 `retryable=True` 且属于限流、超时、网络或 Provider 故障的标准错误才会重试；鉴权、配置、内容策略和协议错误默认立即停止。退避是确定、有上限且可替换的；自定义策略只需满足 `InvocationPolicyProtocol`。

收集模式在返回前通过 `collect_stream()` 校验整个 Provider 流，因此失败发生在结果暴露前，可以按策略安全切换路由。透传模式使用增量校验器逐事件输出：首个事件可见前仍可按策略重试或切换路由；任何事件一旦可见，后续失败立即结束本次执行，绝不静默重放，避免重复文本或工具调用增量。透传模式的 `timeout` 约束等待 Provider 下一帧的时间，不把调用者处理事件所用时间计入超时。

需要恢复已经可见的纯文本流时，调用者必须同时配置正数 `InvocationPolicy.max_stream_replays` 并向 `stream()` 传入 `VerifiedTextPrefixRecovery()`（或自定义 `StreamRecoveryStrategy`）。内置策略只接受单个文本块且拒绝工具、多块、Usage 后失败等情况；它在同一 Provider/模型上重新发起请求，按文本语义校验已公开前缀，并只输出未见后缀。分歧或不完整重放是不可重试的协议错误。每次重放都进入 `AttemptRecord`，可能重复计费，不会切换路由，也不等同于 Provider 原生游标续传或跨进程恢复。默认 `max_stream_replays=0`，因此现有安全边界不变。

`2.0.0a4`另外提供 `CursorResumableModelProvider`、`CursorStreamItem` 与 `NativeCursorRecovery(max_resumes=N)`。开发者须实现返回“紧接当前事件之后”的不重复游标的 `stream_with_cursor()`，以及从同一次生成中该游标之后继续输出的 `resume_stream()`；调用时还须显式传入 `NativeCursorRecovery`。执行器沿用同一个流校验器跨连接处理文本、工具或多模态事件，拒绝重复游标，并把初始请求和每次续传分别记入尝试账本。游标只在进程内传给原 Provider，不进入公开事件、审计记录或装配编码；`replay_safe=False` 禁止续传。

```python
execution = executor.stream(
    request,
    stream_recovery=NativeCursorRecovery(max_resumes=2),
)
```

这条路径不重发完整模型请求，也不使用文本前缀猜测去重；同一次生成、游标精确位置及不重复内容的真实性由 Provider 实现负责。核心只能检测游标复用，不能证明不同游标没有重复语义内容。普通模板未自动启用续流；独立 `OpenAIResponsesResumableProvider` 可显式装配，要求请求开启后台保存，通过 SQLite 帧日志与事件内偏移恢复原响应。宿主可保存 Provider API 返回的游标并在新进程恢复，但执行器本身不持久化游标或 Agent 状态。失败尝试若无独立用量报告仍计为未知，严格 Token/费用预算不会将其当作零。ReAct Loop 的 `stream_recovery` 仅用于已启用文本或工具参数增量流的 Agent；调用前估算包含续流连接的保守上界，共享预算包装器继续禁止原生恢复。默认不启用；[详见边界与示例](responses-continuation.md)。

调用者可传入 `replay_safe=False` 强制只执行选中路由一次，即使装配策略允许重试。`AttemptRecord` 保存 Provider、模型、序号、耗时、已输出事件数、标准失败、下次退避，以及 Provider 明确报告时的 TokenUsage/`usage_reported`；它不保存消息、Prompt、请求体或凭据。失败尝试未报告用量时保持未知，不推断为零。普通模型执行不会自动修改 `CandidateState`；健康反馈必须通过显式观测或注册探测服务接入。

## 接口探测

| 级别 | 当前行为 | 是否可能产生模型费用 |
|---|---|---|
| L1 | `EndpointProbe` 检查 URL、DNS、TCP、TLS、HTTP | 否 |
| L2 | 归一化访问失败；目录成功不证明鉴权或生成权限，保持 `SKIPPED` | 否 |
| L3 | 读取模型目录与声明能力 | 否 |
| L4 | 最小文本生成 | 是；必须 `allow_active=True` |
| L5 | 验证完整流终止协议 | 是；必须 `allow_active=True` |
| L6 | 工具/结构化能力仅报告声明，状态为 `SKIPPED` | 当前不执行 |
| L7 | 多模态能力仅报告声明，状态为 `SKIPPED` | 当前不执行 |

`EndpointProbe` 不发送凭据和请求体，结果目标会移除 URL 用户信息、查询串和片段。HTTP 4xx/5xx 仍证明端点可达，但不证明鉴权或模型生成权限。

Provider 可选声明只读 `catalog_probe_scope` 属性（`remote` / `local` / `unknown`），不改变必需的 `ModelProvider` 协议。`remote` 是适配器承诺本次 `list_models()` 通过传输请求目录，而非读缓存；仅请求成功后产生 L1 `catalog-connectivity=PASS`。自定义缓存 Provider 必须返回 `local` 或 `unknown`。缺失、异常或不认识的值按未知处理。内置 HTTP 与 OpenAI-compatible 适配器按目录行为声明，预算/用量包装器透传声明；Qwen 原生配置目录、Turbo 默认本地 profiles、关闭 discovery 的兼容模板不会假称连通。传输本身是可替换的；注入模拟传输只证明该模拟调用，不代表真实联网验收。

L3 的 `PASS` 只代表模型清单读取成功。即使远端目录请求成功，L2 仍 `SKIPPED`，因为公开目录不一定校验凭据，也不能证明生成权限。只有 L1/L2/L4/L5 的实际通过观察参与 `HEALTHY` 判定；只有本地清单/能力声明时为 `UNKNOWN`。`ProbeResult.successful=True` 只表示已执行项目没有失败，不表示所有检查已执行或远端可用。旧 Provider 无须新增属性，但其仅目录的安全探测将保守地变为 `UNKNOWN`。默认不会为消除未知而额外请求或执行付费生成。

`ProbeResult` 包含模式、分项状态、时间、延迟、失败类别、探测器版本、过期时间和实际发现的 Provider/模型路由。`ProbeCache` 不返回过期结果。`PeriodicProbeService` 可以周期运行任意探测回调，但只产生结果，不修改用户配置。

手动 Python API 和通用周期调度已经实现。需要“注册即安全探测”的装配使用 `ModelRegistrationProbeService.register()`：它始终运行 `ProbeMode.SAFE`、不会调用生成接口，把结果写入缓存，并通过 `ProbeHealthBridge` 只更新本次发现的路由；过期结果映射为 `UNKNOWN`。取消或未处理异常会撤销刚完成的注册。直接调用 `ModelRegistry.register()` 仍是无 I/O 的纯注册操作。`wagent probe` 与 TUI 提供无凭据 L1 检查；`wagent provider-probe` 与 TUI Models 页从严格配置装配 Provider，提供安全目录检查和需单次明确授权的 L4/L5 主动检查。L6/L7 厂商专用主动验证器仍为 `Planned`。

内置适配器每次进入 `list_models()` 先重置证据为 `unknown`，仅在成功返回时按实际执行路径记录 `local` / `remote`，读取属性不会重新调用请求映射。记录使用每个实例的任务上下文隔离，避免并发本地读取与远端请求互相覆盖；预算/用量包装器在同一任务直接委托。自定义跨任务或缓存包装器须自行维持这一证据契约，否则应返回 `unknown`，不得转发其他请求留下的旧 `remote`。

## 错误与安全边界

稳定错误类别包括配置、鉴权、限流、超时、网络、协议、内容策略、Provider、取消。路由决策可消费健康状态但本身不执行重试；`ModelExecutor` 只按显式 `InvocationPolicy` 处理标准化失败。

主动探测必须由调用者显式设置 `allow_active=True`。此授权只覆盖当前调用，不会持久化，也不会从装配编码导入。模型执行器的 `replay_safe` 只描述模型请求；后续工具执行器仍不得自动重放已经产生副作用的工具调用。

## Phase 2B 后续计划

- 扩展 Reasoning 内容增量、图片生成之外的 OpenAI 托管工具和更多厂商特性。
- Responses 线上验收、CLI/TUI 装配、完整 Agent 跨进程恢复、其他厂商原生续流，以及与限流器的可插拔反馈桥接。
- L6/L7 可插拔主动验证器；所有可能产生费用的验证继续要求显式授权。
