# 本地配置化 Agent Runtime

[English](./local-runtime.en.md) | 简体中文

状态：`Experimental`（`2.0.0a1`）。严格本地 JSON 配置、环境变量凭据引用、Provider/路由/ReAct 装配、持久化 Run/Session，以及 CLI/TUI 文本运行入口已实现。配置化工具选择、审批恢复界面与实时 RunEvent 查看仍为 `Planned`。

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
    "max_tool_calls": 0,
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
  }
}
```

`template` 可使用内置 `anthropic`、`gemini`、`ollama`、`qwen-native`、`deepseek`、`glm`、`qwen` 或 `turbo`。`turbo` 必须显式提供 `base_url`。配置拒绝未知字段、明文 `api_key` 与扩展中的凭据字段；凭据只在装配时从 `api_key_env` 读取，不写入 Run、Session 或工程装配编码。

## CLI

```powershell
$env:DEEPSEEK_API_KEY = "..."
wagent run "Explain this repository" `
  --config .wagent/config.json `
  --confirm-model-call `
  --json
```

`--confirm-model-call` 是每次命令必需的显式授权。成功结果包含 Session ID、Run ID、停止原因、最终文本、步骤/工具计数，以及输入、输出、缓存输入、总 Token 与完整性标记。使用 `--session <id>` 可继续已有文本 Session。

## TUI

Run 页面读取同一配置。用户必须输入 `RUN` 才会发起模型调用；成功后显示输出和 Token 计量，并把 Session ID 留在输入框中用于下一轮。界面不会把确认保存为长期授权。

## 预算语义

- `max_output_tokens` 是单次模型请求的输出上限。
- `max_input_tokens`、`max_cumulative_output_tokens`、`max_total_tokens` 是一个 Run 内的累计上限。
- `require_usage=true` 时，只要某次模型响应未报告用量，Run 就以 `token-usage-unavailable` 停止。
- Provider 报告的用量只能在调用后核算；当前没有调用前 Token 估算器，因此首个调用仍可能越过累计上限。
- 将 `max_attempts_per_route` 或 `max_routes` 设为大于 1 会授权额外、可能计费的重试或故障转移。

## 开放装配边界

`load_local_runtime_config()` 与 `assemble_local_runtime()` 是便利层，不是新的封闭 Runtime。返回的 `LocalAgentRuntime` 公开 Definition、Loop、ModelRegistry、ToolRegistry 和 SessionManager。应用可替换模板注册表、Provider 传输、路由、工具与 Store。

配置入口当前不自动加载任何工具，也不授予权限、审批或本地执行权。需要工具的应用应使用公开 Python API 注册 `ToolBinding`，并显式提供策略与 `ToolExecutionContext`；后续配置化工具选择也必须保留同一权限边界。
