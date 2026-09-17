# 工具注册、策略与执行

[English](./tools.en.md) | 简体中文

状态：Python 函数模板、作用域注册、参数校验、权限/审批策略、超时、取消和审计为 `Implemented`（Phase 3 / `2.0.0a1`）。HTTP、MCP、命令行与远程工具模板仍为 `Planned` 或 `Reserved`。

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

- HTTP、MCP、命令行和远程工具适配器。
- 沙箱绑定和 Docker/OCI 编码执行。
- 持久化审计、工具缓存、录制回放与结果流。
- TUI 审批页面及跨进程审批恢复。
