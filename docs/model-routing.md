# 模型、路由与接口探测

[English](./model-routing.en.md) | 简体中文

状态：Phase 2A 基础为 `Implemented`（`2.0.0a1`）；首方 Provider 适配、自动重试/故障转移、注册自动探测和 CLI/TUI 入口为 `Planned`。

## 已实现边界

- Provider 中立的消息、内容块、工具定义、请求、模型描述和响应。
- 文本、图像、音频、工具调用、结构化输出、Reasoning、Prompt Cache 等标准能力声明。
- 严格流事件：块开始、文本/工具增量、块结束、Usage、标准错误和 Finish。
- `ModelProvider`、`ModelRegistry`、`CancellationToken` 和标准错误分类。
- 可解释的 `WeightedRoutingPolicy`、安全 YAML 策略和 `ModelRouter`。
- L1 端点嗅探、L2/L3 Provider 检查、显式授权的 L4/L5 主动探测、缓存与周期调度。

当前未内置 OpenAI、Anthropic、Gemini、OpenAI-compatible、Ollama 或 vLLM 适配器。协议可以承载这些适配器，但这不代表已经接入。

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

当前 `ModelRouter` 只产生决定，不调用 Provider，也不自动执行备用路由。重试、退避、幂等边界和故障转移执行器属于 Phase 2B `Planned`。

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

稳定错误类别包括配置、鉴权、限流、超时、网络、协议、内容策略、Provider、取消。路由决策可消费健康状态，但当前不会据此自动重试。

主动探测必须由调用者显式设置 `allow_active=True`。此授权只覆盖当前调用，不会持久化，也不会从装配编码导入。后续故障转移不得自动重放已经产生副作用的工具调用。

## Phase 2B 计划

- OpenAI、Anthropic、Gemini、OpenAI-compatible、Ollama 和 vLLM 首方适配器及一致性测试。
- 注册时自动安全探测、CLI/TUI 探测入口和健康状态桥接。
- Provider 调用器、超时、限流、退避、重试、自动故障转移和尝试记录。
- L6/L7 可插拔主动验证器；所有可能产生费用的验证继续要求显式授权。
