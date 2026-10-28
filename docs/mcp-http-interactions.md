# MCP 持续 HTTP 交互

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

简体中文 | [English](mcp-http-interactions.en.md)

工作区实现，已随 2.0.0 发布。协议由用户显式选择；两个传输都不发现新端点、不切换协议、不跟随重定向、不重连或重放请求。既有 buffered HTTP transport 保持不变。新实现依赖 HTTPX（`models` extra）；注入的 `httpx.AsyncClient` 为借用对象，传输不会关闭它。默认客户端禁用环境代理和重定向。端点凭据、TLS、代理和应用权限仍由宿主决定。

## 新版 POST 持续订阅

`McpStreamingHttpTransport` 实现 **2026-07-28** 的 POST JSON 与增量 SSE 响应。新版 HTTP 没有 GET 监听、session ID、服务器独立 request 或 Last-Event-ID 恢复；sampling/elicitation/roots 交互继续使用既有客户端 MRTR 路径。依据：[2026 HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)、[subscriptions](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions)。

```python
from contextlib import aclosing
from w_agent.tools import McpClient, McpStreamingHttpTransport

async with McpClient(McpStreamingHttpTransport(
    "http://127.0.0.1:8000/mcp",
    idle_timeout=60,
    max_stream_seconds=3600,
)) as client:
    async with aclosing(client.listen({"toolsListChanged": True})) as events:
        async for event in events:
            # 第一条确认服务器实际接受的过滤条件子集。
            if event["method"] == "notifications/tools/list_changed":
                tools = await client.list_tools()
                break
```

复用 `McpClient.listen` 的确认、过滤范围和关联 ID 校验。工具列表变更先使 schema 缓存失效，再通知应用。普通请求可通过独立 HTTP 流并发执行。协议版本、方法、名称/URI 和 schema 声明的工具参数头复用既有编码规则。关闭响应流即取消新版 HTTP 监听，**不**额外 POST cancellation 通知。断线或超出边界会抛错；再次显式建立订阅前应重新获取当前状态，不保证断线期间通知无缺口。

## 显式旧版回调与 GET 通知

`McpLegacyDuplexHttpTransport` 仅支持 **2025-11-25**：初始化生命周期、session 头传递、POST SSE 内服务器请求以及显式开启的 GET SSE 监听。它不实现更早的双端点 HTTP+SSE 发现。依据：[2025 transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)。

```python
from contextlib import aclosing
from w_agent.tools import (
    McpClientHandlers, McpLegacyClient, McpLegacyDuplexHttpTransport,
)

async def decline(params):
    return {"action": "decline"}  # 宿主负责呈现、授权和数据验证。

transport = McpLegacyDuplexHttpTransport("http://127.0.0.1:8000/mcp")
async with McpLegacyClient(
    transport, supported_versions=("2025-11-25",),
    handlers=McpClientHandlers(elicitation=decline),
) as client:
    await client.initialize()
    result = await client.call_tool("safe", {})
    await client.subscribe_resource("file:///safe")
    try:
        async with aclosing(transport.listen_notifications()) as events:
            async for event in events:
                if event["method"] == "notifications/resources/updated":
                    break
    finally:
        await client.unsubscribe_resource("file:///safe")
```

回调结果独立 POST 到同一固定端点，并要求空 HTTP 202 接受。未知方法返回协议错误；注册 handler 不意味着自动获得模型、文件系统、打开 URL 或审批权限。旧版客户端禁止初始化前交互回调。通知 handler 在向迭代器交付通知之前运行，应快速完成；回调可以发起独立 HTTP 请求，但共享并发流上限，回调响应本身也需要一个额外流名额。

session 头变化、非法头、404 会话失效、GET 拒绝、非法消息和提前断流均显式失败，不创建替代会话、不重试工具。旧版 POST 中断后会尝试一次有时限的 `notifications/cancelled` POST，不假定取消已获确认。关闭 GET 不会自动取消资源订阅或 DELETE 会话，需应用显式管理。服务器 request ID 在同一 transport 生命周期内必须唯一，避免重复回调副作用；达到 ID 数量上限时拒绝继续。这是有意采取的更严格不重放边界，不是跨 transport 实例持久去重。

## 资源边界和生命周期

默认请求期限 30 秒、空闲读取期限 60 秒、流读取总期限 3600 秒、请求体 4 MiB、单消息/SSE 行 1 MiB、流解码后累计 64 MiB、10,000 条 SSE 消息、16 个并发 HTTP 交换。参数均有有限值校验。每次继续网络读取时执行剩余总期限检查；宿主暂停迭代器时不会读取或自动保活，必须显式关闭。暂停迭代器仍占用并发名额。提前退出用 `aclosing`，宿主退出时关闭 client/transport。

拒绝重复 JSON 字段、非有限值、JSON batch、不匹配响应 ID、端点发现事件、不完整帧和新版独立服务器请求。SSE 注释和游标字段受字节上限约束，不启动恢复。取消会中断待完成读取及 handler。异常不包含响应正文或端点凭据。网络失败时远端操作结果可能未知，取消不代表远端副作用已回滚。

## 验收与剩余范围

在既有隔离 Python 3.11 环境执行 `python -m pytest tests/test_mcp_http_duplex.py tests/test_mcp_client.py tests/test_mcp_interactions.py -q`，**62 项通过**。其中新增 26 项，包含真实临时 **仅 127.0.0.1** HTTP 服务的新版增量订阅/并发普通请求，以及旧版 session/回调/GET 交互；测试清理关闭 server、socket 和连接 task。其他边界使用 HTTPX mock stream。没有访问外部或付费服务。

本轮未实现/未验收：自动重连、游标重放、2024 双端点发现、session DELETE、OAuth 发现、可恢复 Tasks、外部服务器互操作认证、平台 UI 通知呈现。没有新建自动授权策略或沙箱；这是可选的本地框架传输组件，不是托管服务。
