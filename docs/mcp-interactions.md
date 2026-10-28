# MCP 显式交互与 stdio 订阅

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

简体中文 | [English](mcp-interactions.en.md)

工作区增量，已随 2.0.0 发布。`McpClient` 保持 2026-07-28 无状态生命周期；`McpLegacyClient` 显式使用 2025 初始化生命周期。两者不会静默切换协议。

## 显式 handler 与 MRTR

```python
from w_agent.tools.mcp_client import McpClient
from w_agent.tools.mcp_duplex import McpDuplexStdioTransport
from w_agent.tools.mcp_handlers import McpClientHandlers

async def decline(params):
    # 应用负责向用户呈现请求、取得批准与验证数据；示例直接拒绝。
    return {"action": "decline"}

async with McpClient(
    McpDuplexStdioTransport(("python", "-m", "your_mcp_server")),
    handlers=McpClientHandlers(elicitation=decline),
    max_input_rounds=10,
    max_input_requests=32,
) as client:
    result = await client.call_tool("your_tool", {})
```

`sampling`、`elicitation`、`roots` 参数只接受应用注册的异步 callable。handler 收到参数对象并返回协议结果对象。它们不会自动调用模型、打开 URL、读取目录、授予工具权限或批准操作。通过 `client_capabilities` 声明这些能力但未提供对应 handler 会失败。默认 elicitation 只声明 form；URL 模式必须显式声明 `client_capabilities={"elicitation": {"form": {}, "url": {}}}`。采样工具也必须显式声明 `sampling.tools`。应用负责请求/结果 schema 的业务校验，以及采样额度、审批、敏感信息过滤；这里只执行信封与已声明模式的校验。

2026 的 `tools/call`、`prompts/get`、`resources/read` 遇到 `input_required` 后，客户端先检查整批输入请求及 handler，再逐一执行，使用新请求 ID、原始调用参数、对应 `inputResponses` 和原样 `requestState` 续答。缺 handler、关闭自动续答（`max_input_rounds=0`）或轮数耗尽时返回 `McpInputRequiredError`，其中 `result` 保留未完成结果。取消会中断正在等待的 handler，不发送下一轮。

旧版客户端使用同一 handler 对象，配合支持双向消息的 `McpDuplexStdioTransport` 或显式 2025-11-25 的 `McpLegacyDuplexHttpTransport`。初始化完成前不执行交互 handler；未知方法返回 `-32601`，handler 异常返回不含异常细节的 `-32603`。原 buffered 旧版 HTTP 传输仍拒绝交互 handler；新传输见[持续 HTTP 交互](mcp-http-interactions.md)。`subscribe_resource(uri)` / `unsubscribe_resource(uri)` 要求服务器已协商 `resources.subscribe`。

## 持续通知

```python
from contextlib import aclosing

# client 为现代 McpClient，transport 为 McpDuplexStdioTransport。
async with aclosing(client.listen({"toolsListChanged": True})) as events:
    async for event in events:
        # 第一条是 acknowledged，声明服务器实际接受的订阅子集。
        if event["method"] == "notifications/tools/list_changed":
            tools = await client.list_tools()
            break
```

订阅可与工具请求并发；同一通道按 subscription ID 分发。确认必须先于变更通知，服务器不能扩张订阅范围。工具列表变更会先清除客户端 schema 缓存；通知本身不重新发现或注册工具。正常完成结束迭代，断连抛错。提前退出用 `aclosing` 或 `await events.aclose()`，发送针对该订阅的取消通知。重连及重新获取数据由应用显式决定。

`notification_handler` 可接收旧版 stdio 的普通通知；它在接收顺序内运行，应快速完成并把工作排入应用队列，不能在此回调内等待同一客户端的新请求。订阅迭代器中的消费者可发起请求。duplex transport 限制待处理请求、handler 并发及每条流的排队消息数；队列溢出或非法消息显式失败。关闭会清理 reader、handler 和子进程。子进程退出后不自动重启、不重放工具调用。

## 验收和边界

定向测试：`py -3.11 -m pytest tests/test_mcp_client.py tests/test_mcp_interactions.py -q`。测试覆盖 mock MRTR、真实本地 stdio 的旧版服务器请求、通知、资源订阅，以及现代订阅与工具并发、取消、断连和范围拒绝。没有调用外部模型或付费工具。

持续 2026 POST 订阅和显式 2025 GET/服务器请求已通过[持续 HTTP 传输](mcp-http-interactions.md)提供并有独立定向验收。2024 双端点 HTTP+SSE、自动恢复、Tasks 扩展和外部服务器互操作验收仍未覆盖。原 `McpStdioTransport` 仍是简易请求/响应传输；持续 stdio 通知必须选 duplex transport。Sampling/Roots 在 2026 已被官方弃用但仍保留兼容；新应用优先直接集成模型和显式资源参数。

协议依据：[2026 schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/schema.json)、[2026 subscriptions](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions)、[2025 transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[2026 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/)。
