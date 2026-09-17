# 本地配置化 Agent Runtime

[English](./local-runtime.en.md) | 简体中文

状态：`Experimental`（`2.0.0a1`）。严格本地 JSON 配置、环境变量凭据引用、Provider/路由/ReAct 装配、显式工具选择、持久化 Run/Session、Python API/CLI 审批恢复，以及 CLI/TUI 文本运行入口已实现。TUI 工具加载/审批页面、Checkpoint 浏览与实时 RunEvent 查看仍为 `Planned`。

## 配置

`.wagent/config.json` 示例：

```json
{
  "schema_version": 1,
  "provider": {
    "template": "deepseek",
    "name": "primary",
    "model": "deepseek-chat",
    "api_key_env": "DEEPSEEK_API_KEY",
    "timeout": 60
  },
  "agent": {
    "name": "local-assistant",
    "system_prompt": "Answer clearly and cite uncertainty.",
    "max_steps": 4,
    "max_tool_calls": 4,
    "max_output_tokens": 1024,
    "max_input_tokens": 12000,
    "max_cumulative_output_tokens": 3000,
    "max_total_tokens": 15000,
    "require_usage": true
  },
  "invocation": {
    "max_attempts_per_route": 1,
    "max_routes": 1,
    "timeout": 60
  },
  "tools": {
    "enabled": ["repository_search", "save_note"]
  }
}
```

`template` 可使用内置 `anthropic`、`gemini`、`ollama`、`qwen-native`、`deepseek`、`glm`、`qwen` 或 `turbo`。`turbo` 必须显式提供 `base_url`。配置拒绝未知字段、明文 `api_key` 与扩展中的凭据字段；凭据只在装配时从 `api_key_env` 读取，不写入 Run、Session 或工程装配编码。

`tools.enabled` 只从宿主明确提供的 `tool_bindings` Catalog 中选择名称。JSON 不导入代码、不注册未知工具，也不授予权限或审批；启用工具时 `agent.max_tool_calls` 必须大于零。未选择的 Catalog 工具不会进入本次 `ToolRegistry` 或模型上下文。

## CLI

```powershell
$env:DEEPSEEK_API_KEY = "..."
wagent run "Explain this repository" `
  --config .wagent/config.json `
  --confirm-model-call `
  --json
```

`--confirm-model-call` 是每次命令必需的显式授权。成功结果包含 Session ID、Run ID、停止原因、最终文本、步骤/工具计数、逐尝试账本，以及输入、输出、缓存输入、总 Token 与完整性标记。使用 `--session <id>` 可继续已有文本 Session。

开发者自有工具可由明确的 `module:attribute` 入口返回一个 `ToolBinding` 或其可迭代集合。导入 Python 工具代码是独立风险，CLI 只有同时传入 `--tool-entry` 与 `--confirm-tool-code` 才会执行；配置文件本身不能触发导入。权限也必须逐次通过 `--grant-permission` 授予：

```powershell
wagent run "Save this note" `
  --config .wagent/config.json `
  --tool-entry my_agent_tools:build_tools `
  --confirm-tool-code `
  --grant-permission notes.write `
  --confirm-model-call `
  --json
```

若策略要求逐调用审批，Run 以 `needs-approval` 停止，并返回 `checkpoint_id` 及仅含 `call_id`、工具名和参数名的 `pending_tool`；参数值不会打印。检查后以同一配置、工具入口和权限恢复，并批准精确 Call ID：

```powershell
wagent run-resume <session-id> <run-id> `
  --config .wagent/config.json `
  --tool-entry my_agent_tools:build_tools `
  --confirm-tool-code `
  --grant-permission notes.write `
  --approve-tool-call <call-id> `
  --confirm-model-call `
  --json
```

每次恢复都会重新要求模型调用授权、工具代码授权与精确 Call ID。工具入口可能在两次进程间发生变化，生产用法应由应用固定包版本并验证来源。

## TUI

Run 页面读取同一配置。用户必须输入 `RUN` 才会发起模型调用；成功后显示输出和 Token 计量，并把 Session ID 留在输入框中用于下一轮。界面不会把确认保存为长期授权。TUI 当前不导入自有 Python 工具，也没有审批恢复表单；带 `tools.enabled` 的配置会安全失败，需使用 Python API/CLI。

## 预算语义

- `max_output_tokens` 是单次模型请求的输出上限。
- `max_input_tokens`、`max_cumulative_output_tokens`、`max_total_tokens` 是一个 Run 内的累计上限。
- `require_usage=true` 时，只要某次模型尝试未报告用量（包括成功重试之前的失败尝试），Run 就以 `token-usage-unavailable` 停止。
- Provider 报告的用量只能在调用后核算；当前没有调用前 Token 估算器，因此首个调用仍可能越过累计上限。
- 将 `max_attempts_per_route` 或 `max_routes` 设为大于 1 会授权额外、可能计费的重试或故障转移。

## 开放装配边界

`load_local_runtime_config()` 与 `assemble_local_runtime()` 是便利层，不是新的封闭 Runtime。返回的 `LocalAgentRuntime` 公开 Definition、Loop、ModelRegistry、ToolRegistry 和 SessionManager。应用可替换模板注册表、Provider 传输、路由、工具与 Store。

应用将 `{name: ToolBinding}` 作为 `tool_bindings` 传给装配器；配置只能选择其中的子集。`LocalAgentRuntime.run()` 接收本次运行的权限和可选批准 ID，`resume()` 接收 Session/Run ID、权限与非空精确批准集合。配置、Session、Checkpoint 和工程装配编码都不能生成权限、批准或本地执行授权。
