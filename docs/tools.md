# 工具注册、策略与执行

[English](./tools.en.md) | 简体中文

状态：Python、HTTP、无 Shell 命令模板、MCP 客户端绑定、作用域注册、参数校验、权限/审批策略、超时、取消和审计为 `Implemented`（Phase 3 / `2.0.0a1`）。官方 MCP 会话客户端、沙箱绑定和远程工具仍为 `Planned` 或 `Reserved`。

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

默认权限为 `process.execute`，副作用为 `EXTERNAL`。命令默认继承当前进程环境以支持本地开发；处理不可信插件时应设置 `inherit_environment=False` 并只注入必要值。这个适配器只保证无 Shell、边界和策略执行，**不是沙箱**；不可信代码仍应使用后续 Docker/OCI Sandbox。

## MCP 工具

`McpRemoteTool` 描述远端名称、说明和输入 Schema；`mcp_tool()` 把实现 `McpToolClient.call_tool()` 的任意客户端绑定进统一工具运行时，并传播取消信号。它默认需要 `mcp.call` 权限和逐调用审批。

当前适配层不限定 MCP 传输，因而自定义 stdio、HTTP 或进程内客户端都能接入；框架尚未内置官方会话管理、发现和连接生命周期。客户端返回值仍经过 `ToolExecutor` 的标准结果、异常归一化、超时与审计路径。

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

- 官方 MCP stdio/HTTP 会话客户端、工具发现和连接生命周期。
- 沙箱绑定和 Docker/OCI 编码执行。
- 持久化审计、工具缓存、录制回放与结果流。
- TUI 审批页面及跨进程审批恢复。
