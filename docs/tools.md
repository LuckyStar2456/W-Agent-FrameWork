# 工具注册、策略与执行

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./tools.en.md) | 简体中文

工具结果事件记录（2.0.0a7；针对性回归通过）：ReAct 可显式记录送给模型的结果文本，编码器由 Agent Loop 注入，不要求工具实现更改。记录关闭不影响工具运行；编码失败不重放工具，待审批票据不作为结果正文。宿主可脱敏或省略，回放另外授权披露。详见[工具结果正文](./event-replay.md)。

状态：Python、HTTP、无 Shell 命令、Sandbox 命令模板、MCP 绑定、MCP 2026-07-28 stdio/Streamable HTTP 客户端、作用域注册、参数校验、权限/审批策略、超时、取消和审计为 `Implemented`。工作区已实现旧版 MCP 初始化、显式 handler、MRTR 有界交换与 duplex stdio 订阅；HTTP 持续订阅和旧版 HTTP 主动请求仍待实现。详见 [MCP 交互](mcp-interactions.md)。

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

`2.0.0a4`另提供显式选择的 `McpLegacyClient`，用于 2025-03-26、2025-06-18、2025-11-25 的 `initialize` / `notifications/initialized` 协商。它复用 `McpStdioTransport`，或搭配 `McpLegacyStreamableHttpTransport`；后者保存服务器在初始化响应中返回的 `Mcp-Session-Id`，并在后续请求发送协商版本头。旧版请求不附加 2026 的逐请求 `_meta`。不支持的协商版本或初始化失败会使该客户端实例不可继续使用；未协商工具能力则拒绝工具请求。它不会静默切换协议、重复有副作用的工具调用或自动批准发现的工具。示例：

```python
from w_agent import McpLegacyClient, McpLegacyStreamableHttpTransport

client = McpLegacyClient(
    McpLegacyStreamableHttpTransport("https://mcp.example/mcp")
)
bindings = await discover_mcp_bindings(client)
```

默认不声明任何需要服务器主动请求的客户端能力。应用可显式传入 `McpClientHandlers`，配合 `McpDuplexStdioTransport` 处理旧版服务器请求和通知；旧版 HTTP 主动请求、2024 HTTP+SSE 双端点、自动重连和完整互操作验收仍未实现。使用 `McpLegacyClient` 不改变统一工具权限及逐调用审批。

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

客户端接受 JSON-RPC 错误并保留错误码；远端 `isError: true` 会进入本地失败路径。2026 `input_required` 仅通过显式 handler 有界续答，缺少 handler 或超过轮数时抛出 `McpInputRequiredError` 并保留结构化结果。`subscriptions/listen` 已支持 duplex stdio，验证确认顺序、订阅范围和关联 ID，并区分正常关闭与断连。协议依据见 [MCP 2026-07-28 transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports) 与 [tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)。

## 默认安全语义

- 参数在调用处理器前校验；内置校验器覆盖对象、必填字段、额外字段、基础 JSON 类型和枚举。更完整的 Schema 校验可作为替换层接入。
- `PermissionPolicy` 在权限缺失时拒绝执行。
- `SideEffectApprovalPolicy` 默认要求 `WRITE`、`DESTRUCTIVE` 和 `EXTERNAL` 调用 ID 获得逐次批准；只读调用无需批准。
- 从装配编码、模型输出或工具参数中得到的值不会自动成为批准凭据。
- 超时与协作式取消返回标准 `ToolResult`；外部任务取消仍向上传播。
- `ToolAuditRecord` 记录工具名、调用 ID、参数名、结果、耗时和策略，但不记录参数值、输出或凭据。
- 处理器异常会归一化，不把异常正文直接暴露给模型。

应用可以替换整个 `ToolPolicy` 或审计 Sink。自定义策略与适配器必须继续在真实执行路径生效，不能只通过提示词隐藏工具。

## 类型化工具续执行（`2.0.0a6`，针对性回归通过）

反向 Agent→Workflow 暂停链路使用以下可选底层协议；`2.0.0a6`另有 `resumable_workflow_tool()` 专用桥（见 [Workflow 文档](./workflows.md)），双层审批协调服务已加入`2.0.0a6`（针对性回归通过），TUI 引导亦已加入`2.0.0a6`（针对性回归通过）：

- `ToolContinuation(kind, payload, version=1)` 是只包含有限 JSON 数据的引用票据，不是授权，不保存回调或可执行对象。具体类型、版本和引用归属由适配器验证。
- `ToolBinding.resume_handler(arguments, continuation, context)` 为可选恢复处理器。显式返回 `ToolContinuation` 后，执行器返回 `NEEDS_APPROVAL`，不把票据序列化为模型可见成功结果；普通字典返回值仍是普通工具结果。
- `ToolExecutor.resume()` / 可替换 `ResumableToolExecutorProtocol` 只走恢复处理器，绝不回退到初始 `handler`。每次恢复重新校验参数、权限与策略，并要求宿主提供精确 Call ID；缺少权限或批准时保留票据、等待授权。
- `ToolExecutionContext.invocation` 由内置执行器绑定为本次实际 `ToolCall`，覆盖调用者传入的同名字段。`ToolRegistry.register_binding()` 保留原始绑定及其恢复处理器/元数据。
- ReAct 把票据保存到 `RunCheckpoint.tool_continuation`。含票据时使用 schema 2；无票据仍写原 schema 1。旧读取器必须拒绝 schema 2，不能忽略票据后重跑初始工具。升级读取端后再使用；不得手工降级或移除票据。
- 工具未完成时不向模型追加工具结果，不执行同一响应中的后续工具，不重复计入工具调用数。完成后才追加一次结果并继续模型循环。票据不进入默认事件/检查点摘要。

```python
from w_agent import ToolBinding, ToolContinuation, ToolDefinition

async def prepare(arguments, context):
    # 只生成引用；真正副作用放到票据持久化后的 resume 中。
    return ToolContinuation("my-workflow", {"phase": "prepared", "child": "host-owned-id"})

async def resume(arguments, ticket, context):
    # 应用验证类型、版本、子检查点及所有权，再执行一次明确授权的继续操作。
    # 再次等待时返回新的 ToolContinuation；完成时返回普通结果。
    return await continue_owned_child(ticket, context)

binding = ToolBinding(
    ToolDefinition("workflow", "Prepare a workflow", {"type": "object"}),
    prepare, resume_handler=resume,
)
```

`continue_owned_child` 由应用实现；此示例不是内置 Workflow 桥。初始处理器应只准备引用，避免在票据落盘前启动不可重放副作用。票据不能保护任意处理器在首次返回前的崩溃；不存在跨 Store 原子提交保证。恢复处理器失败、超时、取消或协议不支持时，ReAct 保留含票据的 `RESUMING` 并抛出安全错误，不清除待办或向模型伪报完成。工具执行器直接调用不提供持久 claim；宿主自行管理所有权、过期引用与防重放。批准仅授权这一层调用，不能隐式批准子 Agent/Workflow 的内部写操作。

`ToolExecutionContext.agent_run_id` 为可选宿主身份；ReAct 在每次调用时用真实 Run ID 覆盖它。专用 Workflow 桥同时校验该身份、`invocation`、Scope 和子流程引用；自定义 Loop 必须自行提供可信身份。该字段不是授权，也不是沙箱安全边界。

## 仍未实现

- HTTP 持续订阅、旧版 HTTP 服务器主动请求和旧 HTTP+SSE 兼容；MCP 2025 初始化、显式 MRTR 续答与 duplex stdio 订阅已实现。
- 跨工具调用的持久 Sandbox Session 与编码 Agent 工作区写回审核。
- 持久化审计、工具缓存、录制回放与结果流。
- Agent→Workflow 任意深度的递归审批协调；普通 Agent 的 TUI 审批已提供，`2.0.0a6`另有 Workflow 内 Agent 的 CLI/TUI 显式工厂恢复（针对性回归通过）。
