# Responses 原生续流与媒体输出

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

状态：本地实现与离线测试已完成，尚未单独发布；未使用真实凭据调用服务端。本能力属于 Python Provider API，尚未接入 CLI/TUI 配置或 Agent 会话恢复。

存储是公开可替换的 `ResponsesCheckpointStore` 协议（`create/append/cursor/load`）。Provider 不选择默认存储、不自动建库；宿主主动构造 `SqliteResponsesCheckpointStore(path)` 才会初始化指定数据库，这也是对本地保存原始响应内容的显式选择。自定义存储可以加密、内存化或接入自己的数据库，但必须遵守绑定检查、不可覆盖的帧日志与精确事件偏移约定。

SQLite 适配器使用专用 application ID、schema 版本与表结构校验，拒绝非空外来数据库。默认每次生成最多 100,000 帧、单帧 32 MiB、累计帧 JSON 256 MiB；可通过 `max_frames_per_stream`、`max_frame_bytes`、`max_stream_bytes` 调整。超过限额会失败而不追加超限帧，不会重新生成。它们限制单次生成的日志，历史生成的保留与清理由宿主管理。

## 显式启用后台保存

`OpenAIResponsesResumableProvider` 复用 HTTP 传输，增加原生游标接口。请求必须明确提供 `background=True` 与 `store=True`，否则游标接口在联网前拒绝调用；普通 `stream()` 保留原有行为。后台生成会改变服务端数据保存方式，不能用于要求零数据留存的场景。模型、账户与兼容端点是否支持后台模式需自行核实。

```python
from w_agent.models import (
    ModelMessage, ModelRequest, MessageRole,
    OpenAIResponsesResumableProvider, SqliteResponsesCheckpointStore,
)

store = SqliteResponsesCheckpointStore("responses-checkpoints.sqlite3")
provider = OpenAIResponsesResumableProvider(
    name="openai-resumable",
    base_url="https://api.openai.com/v1",
    default_model="your-supported-model",
    headers={"Authorization": f"Bearer {api_key}"},
    checkpoint_store=store,
)
request = ModelRequest(
    messages=(ModelMessage.text(MessageRole.USER, "Explain this design"),),
    extensions={"openai_responses.body": {"background": True, "store": True}},
)

# Host persists the cursor only after handling its event successfully.
async for item in provider.stream_with_cursor(request):
    await handle_event(item.event)
    await save_host_cursor(item.cursor)

# A later process reconstructs the same provider and request, using the same DB.
async for item in provider.resume_stream(request, saved_cursor):
    await handle_event(item.event)
    await save_host_cursor(item.cursor)
```

以上 `handle_event`、`save_host_cursor` 由宿主实现。恢复先重建已接收的解码状态，再交付当前厂商事件尚未交付的本地事件；随后只发出 `GET /responses/{response_id}?stream=true&starting_after=N`。一帧中的文本块开始、增量、块结束、用量和结束事件各有独立游标。工具参数与最终媒体块适用同一机制。终态帧的剩余本地事件可从日志恢复，无需联网；已经消费结束事件的游标返回空流。

检查点绑定 Provider 名、URL、实际请求体、Header 上下文与解码版本/图片限额的 SHA-256 摘要。提示、模型、参数、端点、凭据或图片限额变化会在联网前失败；密钥轮换后旧游标也会拒绝使用。凭据不会作为原始 Header 写入数据库。数据库包含原始响应帧，可能含输出、工具参数、指令回显或图片，未经加密，需要宿主保护。每帧只保存一份，恢复重建的耗时随历史帧数增加。`store.delete(cursor)` 显式删除该次生成的所有本地游标与帧，不会取消或删除远端响应。

宿主仍须原子协调事件处理与自己保存的游标；本实现不承诺工具副作用恰好执行一次，不保存 Agent、工具执行状态或流校验器，也不会自动恢复整段会话。没有拿到首个公开事件的游标时，不能靠本接口恢复。服务端响应过期、404、鉴权失败、事件序号倒退或响应 ID 变化不会降级为新生成。

`ModelExecutor.stream(request, stream_recovery=NativeCursorRecovery(...))` 可在同一进程自动续流；执行器不向宿主暴露游标。首个可见事件前的重试仍受显式 `InvocationPolicy` 控制，默认一次。失败尝试的未知用量不推断为零；共享预算包装器现有禁止原生恢复的边界保持不变。取消本地迭代不等于取消服务端后台任务。

## Responses 图片结果

普通与可恢复 Provider 均使用 `OpenAIResponsesMapping`。通过请求扩展 `openai_responses.image_generation={"output_format": "png"}` 显式追加官方图片生成工具，可与函数工具共存；支持的选项为 `model`、`size`、`quality`、`background`、`output_format`、`output_compression`、`partial_images`、`action`，具体型号的取值由厂商校验。

完成的 `image_generation_call.result` 映射为 `ImageContent`，支持 PNG/JPEG/WebP。`response.output_item.done` 和终态中的同一图片只输出一次；不一致结果报协议错误。默认每张图片限制 20 MiB，可用 `OpenAIResponsesMapping(max_image_bytes=...)` 调整；Base64 在解码前后均检查大小。无 URL 下载或本地文件写入。部分图片预览暂不映射成最终内容，其他内置托管工具、音频与 Reasoning 增量仍未实现。模型 Profile 的图片输出声明和线上可用性仍由应用核实。

官方依据：[后台模式](https://developers.openai.com/api/docs/guides/background)、[响应检索参数](https://developers.openai.com/api/reference/python/resources/responses/methods/retrieve)、[图片生成工具](https://developers.openai.com/api/docs/guides/tools-image-generation)。
