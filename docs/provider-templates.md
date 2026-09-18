# HTTP Provider 与厂商模板

[English](./provider-templates.en.md) | 简体中文

状态：`Implemented`（当前 main，尚未另行发布）。本页描述通用 HTTP 请求映射层、原生协议模板和 OpenAI-compatible 厂商模板。模板是可修改的本地装配起点，不是托管服务，也不是锁定厂商行为的隐藏配置。

## 分层

```text
ModelRequest / StreamEvent
          ↕
HttpProviderMapping + HttpStreamDecoder       厂商请求与响应语义
          ↕
HttpRequest / HttpStreamFrame                 HTTP 与 SSE/NDJSON 帧
          ↕
HttpProviderTransport                         可替换传输
```

- `HttpModelProvider` 只负责模型解析、能力校验、取消、调用映射器和输出标准事件。
- `HttpProviderMapping` 负责目录请求、目录解析、生成请求和创建有状态流解码器。
- `HttpProviderTransport` 负责 I/O。默认 `HttpxProviderTransport` 支持 JSON、SSE 和 NDJSON；测试或应用可以注入自己的传输。
- `HttpRequest`、`HttpStreamFrame` 与 `HttpStreamDecoder` 都是公开扩展点。自定义实现只需满足协议，不需要继承框架基类。

## 内置模板

| Key | 协议 | 默认地址 | 当前模板范围 |
|---|---|---|---|
| `openai-responses` | OpenAI Responses 原生协议 | `https://api.openai.com/v1` | `/models`、`/responses`、SSE、文本/图像、函数工具、结构化输出、Reasoning 请求与 Token 用量 |
| `anthropic` | Anthropic Messages 原生协议 | `https://api.anthropic.com` | 模型目录、SSE、文本/图像、工具、结构化输出 |
| `gemini` | Gemini `streamGenerateContent` 原生协议 | `https://generativelanguage.googleapis.com` | 模型目录、SSE、文本/图像/音频、工具、结构化输出 |
| `ollama` | Ollama `/api/chat` 原生协议 | `http://127.0.0.1:11434` | `/api/tags`、NDJSON、文本/内联图像、工具、结构化输出 |
| `qwen-native` | DashScope Generation 原生协议 | `https://dashscope-intl.aliyuncs.com` | SSE、文本、工具、结构化输出；模型必须显式配置 |
| `deepseek` | OpenAI-compatible Chat Completions | `https://api.deepseek.com` | 厂商默认地址与保守能力模板 |
| `glm` | OpenAI-compatible Chat Completions | `https://open.bigmodel.cn/api/paas/v4` | 厂商默认地址与保守能力模板 |
| `qwen` | DashScope OpenAI-compatible | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | 兼容入口；与 `qwen-native` 可并存 |
| `vllm` | vLLM OpenAI-compatible Chat Completions | `http://127.0.0.1:8000/v1` | 模型目录、Chat SSE、`structured_outputs`、优先级/请求/会话标识及任意非核心 vLLM 参数 |
| `turbo` | Turbo AI/SIAM.AI OpenAI-compatible | 无 | 部署地址必须由用户提供；默认只声明文本能力 |

这里的 `turbo` 明确指 Turbo AI/SIAM.AI。其文档示例使用部署实例地址，因此框架不会保存示例 IP 或猜测地址。如果所需的是另一个名为 Turbo 的服务，应复制模板并更换协议映射。

模板不会从模型名称猜测视觉、Reasoning、并行工具等能力。不同型号支持范围不一致时，使用 `HttpModelProfile` 或 `OpenAICompatibleModelProfile` 明确声明。声明代表路由可选能力，不等于框架已经对每个远程型号进行在线验证。

## 使用

安装可选传输：

```bash
pip install "wagent-framework[models]"
```

直接使用工厂：

```python
from w_agent import ModelMessage, ModelRequest, MessageRole, anthropic_provider

provider = anthropic_provider(
    api_key="...",
    default_model="your-model-id",
)

request = ModelRequest(
    messages=(ModelMessage.text(MessageRole.USER, "Hello"),),
)
```

通过模板注册表装配：

```python
from w_agent import builtin_provider_template_registry

templates = builtin_provider_template_registry()
provider = templates.build(
    "ollama",
    default_model="your-local-model",
)
```

`BUILTIN_PROVIDER_TEMPLATES` 是只读内置目录；`builtin_provider_template_registry()` 每次返回独立、可修改的注册表。应用可以替换同名模板，也可以注册全新的 `ProviderTemplate`，不会改变其他应用或进程全局状态。

## 自定义映射

最小映射实现四个方法：

```python
class MyMapping:
    def catalog_request(self) -> HttpRequest | None: ...
    def parse_catalog(self, payload) -> tuple[str, ...]: ...
    def generation_request(self, request, model) -> HttpRequest: ...
    def stream_decoder(self, request, model) -> HttpStreamDecoder: ...
```

映射器可以改变路径、Header、请求体、扩展字段和响应事件；传输可以改变认证、代理、连接池、录制回放或完全绕过 HTTPX。Provider 核心不导入任何厂商 SDK。

厂商专用附加请求放入命名空间：`anthropic.body`、`gemini.body`、`ollama.body` 或 `qwen.body`。附加字段不能覆盖模板已经生成的核心字段；要改变核心行为，应复制或替换映射器，避免产生表面配置与实际协议不一致的请求。

`openai-responses` 使用 `openai_responses.reasoning` 和 `openai_responses.body`；后者只能补充 `store`、`previous_response_id` 等非核心字段。它把系统文本映射到 `instructions`，把消息、函数调用/结果映射到类型化 `input`，并把文本/函数增量、终态与 `input_tokens`/`output_tokens`/缓存 Token 统一为稳定事件。当前不映射音频输入、内置托管工具或 Reasoning 内容增量；`ModelRequest.stop` 会明确报错而不是被静默忽略。

`vllm` 使用已有 Chat Completions 事件转换，并增加 `vllm.structured_outputs`、`vllm.priority`、`vllm.request_id`、`vllm.session_id` 和 `vllm.body`。`vllm.body` 可放 `top_k`、`min_p` 等非核心服务参数，不能覆盖框架生成的模型、消息、流、工具或结构化输出字段。vLLM 默认会读取模型仓库的 `generation_config.json`；这是服务端行为，框架不会假定采样默认值。模型是否真的支持 Chat 模板、工具、并行调用、视觉或 Reasoning 仍取决于服务启动参数和具体模型，应使用 Profile 收窄能力。

## 安全与当前限制

- API Key 只进入请求 Header，不进入模型描述、路由决定或模板目录。
- Base URL 拒绝用户信息、查询串、片段和无效端口；私有部署地址仍由用户自行信任。
- 当前测试使用模拟传输，不消耗远程额度；真实凭据和在线兼容性未在仓库测试中验证。
- OpenAI Responses 与 vLLM 差异适配已实现并可由严格本地配置、CLI/TUI 运行及探测链路装配；Reasoning 内容增量、OpenAI 托管工具事件、多模态输出和跨流断点恢复仍为 `Planned`。
- 厂商协议会变化。模板版本随 W-Agent 发布；应用可固定、复制或注册自己的版本。

协议依据： [OpenAI Responses](https://developers.openai.com/api/reference/typescript/resources/beta/subresources/responses/methods/create)、[vLLM OpenAI-Compatible Server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)、[Anthropic Messages](https://platform.claude.com/docs/en/api/overview)、[Gemini API](https://ai.google.dev/api/generate-content)、[Ollama Chat](https://docs.ollama.com/api/chat)、[Qwen DashScope](https://docs.qwencloud.com/api-reference/chat/dashscope)、[DeepSeek API](https://api-docs.deepseek.com/zh-cn/)、[GLM 快速开始](https://zhipu-ef7018ed.mintlify.app/cn/guide/start/quick-start)、[Turbo AI Endpoint](https://docs.turbo-ai.com/features/endpoint/)。
