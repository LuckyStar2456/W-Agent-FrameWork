# Session 生命周期与跨 Run 上下文

[English](./sessions.en.md) | 简体中文

状态：本地 Session 创建、列表、归档/取消归档、JSON 持久化、跨 Run 文本投影，以及 Agent Run 启动/审批恢复为 `Implemented`（Phase 3 / `2.0.0a1`）。多模态、工具事件和任意 RunEvent 的通用回放仍为 `Planned`。

## 公共 API

- `SessionManager`：协调生命周期、文本历史和普通 `AgentLoop`。
- `SessionRecord`：不可变 Session 快照，包含消息、Run 摘要和元数据。
- `SessionRunRecord`：保存停止原因、输出、步骤/工具计数和 Token 用量。
- `InMemorySessionStore`：测试和短期本地开发。
- `JsonSessionStore`：单一本地生命周期所有者使用的原子 JSON 存储。

```python
from w_agent import (
    AgentDefinition,
    JsonSessionStore,
    MessageRole,
    ModelMessage,
    SessionManager,
)

sessions = SessionManager(JsonSessionStore(".wagent/sessions"))
session = await sessions.create("Support case")

result = await sessions.run_agent(
    react_loop,
    AgentDefinition("support"),
    session.session_id,
    (ModelMessage.text(MessageRole.USER, "我的订单在哪里？"),),
)
```

## CLI 与 TUI

```text
wagent session create "Support case" --id case-1 --json
wagent session list --include-archived --json
wagent session show case-1 --json
wagent session archive case-1
wagent session unarchive case-1
```

CLI 与 TUI 使用相同的公开 `SessionManager`/`JsonSessionStore`，默认目录为 `.wagent/sessions`。`show` 返回消息、Run 摘要、模型尝试/用量/计价计数、输入/输出/缓存 Token、版本化费用及完整性，不会启动模型或产生费用。不同价格表版本或币种不会被静默合并。TUI 当前提供创建、刷新、归档和恢复；配置化 Agent 可在 Run 页面启动。CLI 已支持通过已知 Session/Run/Call ID 审批恢复；TUI 工具与审批界面仍为 `Planned`。

下一次 `run_agent()` 默认把此前投影的文本消息放在本次消息之前。设置 `include_history=False` 可关闭自动上下文拼接，但本次输入与结果仍会记入 Session。

## 审批恢复

当 Run 以 `NEEDS_APPROVAL` 停止后，使用同一 Loop/RunStore 和本地应用提供的批准调用 `resume_agent()`。Manager 验证 Run 属于该 Session，更新原 Run 摘要而不是创建重复记录，也不会重复保存用户输入。

配置化入口可调用 `LocalAgentRuntime.resume()`；CLI 对应 `wagent run-resume`。两者都要求运行时重新提供权限与非空精确 Call ID 集合，不从 Session 或 Checkpoint 恢复授权。

## 数据与边界

- 归档 Session 为只读，取消归档后才可启动或恢复 Run。
- 当前对话投影只保存文本块与最终 Agent 输出；工具参数、工具结果、多模态内容和任意内部事件不自动跨 Run 注入。
- JSON Store 保存的内容可能包含用户文本和模型输出，不加密；目录访问控制属于本地应用。
- 元数据必须是有限 JSON 值，并在记录中递归冻结。
- Store 使用安全 Session ID 和原子文件替换，但不是分布式或多主数据库。
