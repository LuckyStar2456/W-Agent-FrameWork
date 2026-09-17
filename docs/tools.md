# 工具注册、策略与执行

[English](./tools.en.md) | 简体中文

状态：Python、HTTP、无 Shell 命令、Sandbox 命令模板、MCP 绑定、MCP 2026-07-28 stdio/Streamable HTTP 客户端、作用域注册、参数校验、权限/审批策略、超时、取消和审计为 `Implemented`（Phase 3/5 / `2.0.0a1`）。旧版 MCP 协商、MRTR 自动交换和订阅流仍为 `Planned`。

## 分层

```text
ToolDefinition（模型可见 Schema）
        + ToolBinding（处理器、权限、副作用）
        ↓
ToolRegistry（统一 Registry、版本、Scope）
        ↓
ToolPolicy（权限与逐调用审批，可替换）
        ↓
ToolExecutor（校验、超时、取消、执行、审计）
        ↓
ToolResult
```

Definition 不持有执行策略。`ToolBinding` 只把公开定义与处理器绑定，权限、审批和审计仍由执行路径强制完成。默认执行器不重试工具调用，因为调用可能已经产生副作用。

## Python 工具

```python
from w_agent import (
    ToolCall,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
    ToolSideEffect,
    python_tool,
)


def save_note(text: str) -> dict[str, str]:
    return {"saved": text}


binding = python_tool(
    save_note,
    side_effect=ToolSideEffect.WRITE,
    required_permissions=frozenset({"notes.write"}),
)
tools = ToolRegistry()
tools.register_binding(binding, version="1.0.0")
executor = ToolExecutor(tools)

call = ToolCall("call-1", "save_note", {"text": "hello"})
pending = await executor.execute(
    call,
    ToolExecutionContext(permissions=frozenset({"notes.write"})),
)
assert pending.outcome == "needs-approval"

result = await executor.execute(
    call,
    ToolExecutionContext(
        permissions=frozenset({"notes.write"}),
        approved_call_ids=frozenset({"call-1"}),
    ),
)
```

`python_tool()` 从有限、具名的函数签名生成基础 JSON Schema，也允许调用者提供完整 `input_schema`。同步与异步函数都支持。底层 `ToolRegistry.register()` 也可直接接入任何满足公开 `ToolHandler` 协议的实现。

## HTTP 工具

`http_tool()` 的默认映射把 GET/HEAD 参数放入 Query，其余方法使用 JSON Body。URL、方法和 Header 来自本地配置，不从模型参数读取；需要自由映射时显式提供 `request_builder`。默认 `HttpxToolTransport` 校验 TLS、不跟随重定向并以流式方式执行响应字节上限，也可替换为私有传输。

```python
from w_agent import http_tool

binding = http_tool(
    "ticket_create",
    "Create one support ticket.",
    {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "additionalProperties": False,
    },
    url="https://support.example/api/tickets",
    headers={"authorization": "Bearer <local-secret>"},
)
```

默认权限为 `network.http`，副作用为 `EXTERNAL`，因此既需要权限又需要调用 ID 审批。固定 Header 不进入工具 Definition、结果或审计。

## 命令行工具

`command_tool()` 只调用 `asyncio.create_subprocess_exec()`，从不经过 Shell。`argument_builder` 必须返回独立字符串 argv；`;`、管道符和重定向字符不会被解释。stdout/stderr 分别受字节上限约束，超时或取消时终止子进程。

```python
from w_agent import command_tool

binding = command_tool(
    "git_status",
    "Read repository status.",
    {"type": "object", "additionalProperties": False},
    executable="git",
    base_arguments=("status", "--short"),
    argument_builder=lambda arguments: (),
)
```

默认权限为 `process.execute`，副作用为 `EXTERNAL`。命令默认继承当前进程环境以支持本地开发；处理不可信插件时应设置 `inherit_environment=False` 并只注入必要值。这个适配器只保证无 Shell、边界和策略执行，**不是沙箱**；不可信代码应使用 `sandbox_command_tool()` 与 `DockerSandboxProvider`。

`sandbox_command_tool()` 为每次工具调用打开一个 `SandboxProvider` Handle、执行 `SandboxCommand` 并在 `finally` 中关闭。它默认需要 `sandbox.execute` 权限并声明 `WRITE` 副作用。需要跨多个 Agent 步骤复用容器时，应由上层运行时直接持有 Handle，而不是使用单调用模板。

## MCP 工具

`McpRemoteTool` 描述远端名称、说明和输入 Schema；`mcp_tool()` 把实现 `McpToolClient.call_tool()` 的任意客户端绑定进统一工具运行时，并传播取消信号。它默认需要 `mcp.call` 权限和逐调用审批。

`McpClient` 实现当前稳定的 MCP `2026-07-28` 请求模型：每个请求携带协议版本、客户端身份和能力，不创建隐式协议会话。`list_tools()` 有界遍历 `nextCursor`；`discover_mcp_bindings()` 将发现结果转换为 Binding，但**不会自动注册、暴露、授权或批准**任何工具。调用方必须逐个或批量显式注册返回值。

```python
from w_agent import (
    McpClient,
    McpStdioTransport,
    ToolRegistry,
    discover_mcp_bindings,
)

transport = McpStdioTransport(("python", "-m", "my_mcp_server"))
client = McpClient(transport)
bindings = await discover_mcp_bindings(client, local_name_prefix="docs_")

registry = ToolRegistry()
for binding in bindings:
    registry.register_binding(binding, version="1.0.0")
```

`McpStdioTransport` 使用 `create_subprocess_exec()` 启动明确 argv，不经过 Shell；stdin/stdout 使用单行 UTF-8 JSON-RPC，忽略通知直到匹配响应，取消时发送 `notifications/cancelled`，关闭时先关闭 stdin 再有界终止进程。它默认继承环境以方便本地开发；不可信服务器应使用绝对可执行文件、`inherit_environment=False` 和最小环境，或放入 Sandbox。

`McpStreamableHttpTransport` 使用固定 HTTP(S) 端点、`POST`、JSON/SSE 响应和可替换 `McpHttpExchange`。默认 `HttpxMcpExchange` 不跟随重定向并限制响应大小。传输生成 `MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name` 及合法 `x-mcp-header` 参数头，必要时进行 UTF-8 Base64 编码；静态配置不能覆盖这些传输所有的头。凭据可放在固定 Header 中，但不会进入请求 Body、工具 Definition 或审计。

```python
from w_agent import McpClient, McpStreamableHttpTransport

client = McpClient(
    McpStreamableHttpTransport(
        "https://mcp.example/mcp",
        headers={"authorization": "Bearer <local-secret>"},
    )
)
tools = await client.list_tools()
```

客户端接受 JSON-RPC 错误并保留错误码；远端 `isError: true` 会进入本地失败路径。`input_required` 会抛出 `McpInputRequiredError` 并保留结构化结果，避免把尚未完成的 MRTR 调用误报为成功。旧版 `initialize`/`notifications/initialized` 协商、自动 MRTR 输入响应、`subscriptions/listen` 和旧 HTTP+SSE 传输尚未实现。协议依据见 [MCP 2026-07-28 transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports) 与 [tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)。

## 默认安全语义

- 参数在调用处理器前校验；内置校验器覆盖对象、必填字段、额外字段、基础 JSON 类型和枚举。更完整的 Schema 校验可作为替换层接入。
- `PermissionPolicy` 在权限缺失时拒绝执行。
- `SideEffectApprovalPolicy` 默认要求 `WRITE`、`DESTRUCTIVE` 和 `EXTERNAL` 调用 ID 获得逐次批准；只读调用无需批准。
- 从装配编码、模型输出或工具参数中得到的值不会自动成为批准凭据。
- 超时与协作式取消返回标准 `ToolResult`；外部任务取消仍向上传播。
- `ToolAuditRecord` 记录工具名、调用 ID、参数名、结果、耗时和策略，但不记录参数值、输出或凭据。
- 处理器异常会归一化，不把异常正文直接暴露给模型。

应用可以替换整个 `ToolPolicy` 或审计 Sink。自定义策略与适配器必须继续在真实执行路径生效，不能只通过提示词隐藏工具。

## 仍未实现

- 旧版 MCP 初始化协商、MRTR 自动输入交换、订阅流和旧 HTTP+SSE 兼容。
- 跨工具调用的持久 Sandbox Session 与编码 Agent 工作区写回审核。
- 持久化审计、工具缓存、录制回放与结果流。
- TUI 审批页面及跨进程审批恢复。
