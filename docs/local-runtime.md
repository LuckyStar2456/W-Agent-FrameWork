# 本地配置化 Agent Runtime

[English](./local-runtime.en.md) | 简体中文

状态：`Experimental`。`2.0.0a3` 已包含严格本地 JSON 配置、环境变量凭据引用、Provider/路由/ReAct 装配、版本化价格与费用预算、Provider 单独装配与探测、显式工具选择、持久化 Run/Session、Python API/CLI/TUI 审批恢复、Agent Checkpoint 脱敏列表、应用事件回调，以及 CLI/TUI 文本运行入口。当前 main 另外实现 Workflow Checkpoint 脱敏汇总和显式恢复。

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
  },
  "pricing": {
    "version": "my-prices-2026-09-18",
    "currency": "USD",
    "max_cost": "0.25",
    "prices": [
      {
        "provider": "primary",
        "model": "deepseek-chat",
        "input_per_million": "1.00",
        "output_per_million": "2.00",
        "cached_input_per_million": "0.50"
      }
    ]
  }
}
```

`template` 可使用内置 `anthropic`、`gemini`、`ollama`、`qwen-native`、`deepseek`、`glm`、`qwen` 或 `turbo`。`turbo` 必须显式提供 `base_url`。配置拒绝未知字段、明文 `api_key` 与扩展中的凭据字段；凭据只在装配时从 `api_key_env` 读取，不写入 Run、Session 或工程装配编码。

`tools.enabled` 只从宿主明确提供的 `tool_bindings` Catalog 中选择名称。JSON 不导入代码、不注册未知工具，也不授予权限或审批；启用工具时 `agent.max_tool_calls` 必须大于零。未选择的 Catalog 工具不会进入本次 `ToolRegistry` 或模型上下文。

`pricing` 可选且完全由本地开发者提供；框架不内置可能过期的厂商价格。`version`、币种、最大 Run 费用和每个精确 Provider/Model 的百万 Token 单价必须显式给出，金额建议使用 JSON 字符串避免浮点歧义。示例价格仅演示结构，不代表厂商实际价格。缓存输入未单独给价时按普通输入价保守计算；缺少匹配价格或任一尝试用量时，启用费用预算的 Run 会以 `cost-unavailable` 失败关闭。

## CLI

先检查配置化 Provider 时可使用：

```powershell
wagent provider-probe --config .wagent/config.json --mode safe --json
wagent provider-probe --config .wagent/config.json --mode active `
  --confirm-active-probe --json
```

`safe` 不生成内容，但具体 Provider 的目录实现可能是远程请求或静态声明；`active` 才以最多 8 输出 Token 验证实际生成和流终止协议，因此需要独立明确授权。

```powershell
$env:DEEPSEEK_API_KEY = "..."
wagent run "Explain this repository" `
  --config .wagent/config.json `
  --confirm-model-call `
  --json
```

`--confirm-model-call` 是每次命令必需的显式授权。成功结果包含 Session ID、Run ID、停止原因、最终文本、步骤/工具计数、逐尝试账本，以及 Token/费用累计值与完整性标记。使用 `--session <id>` 可继续已有文本 Session。

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

不知道 Run/Call ID 时可先执行 `wagent checkpoint list --json`，也可用 `--session` 过滤。列表只含脱敏的 Agent、状态、工具名、Call ID、参数名与 Token/费用计量，不读取 Prompt、参数值、输出或凭据。

## TUI

Run 页面读取同一配置。用户必须输入 `RUN` 才会发起模型调用；成功后显示输出、Token 和费用计量，并把 Session ID 留在输入框中用于下一轮。界面不会把确认保存为长期授权。Checkpoint 页面可刷新 Agent 审批摘要，也可从指定 State Root 刷新 Workflow 摘要。开发者工具代码仅在输入 `LOAD TOOLS` 后导入，Workflow Definition 仅在输入 `LOAD WORKFLOW` 后导入；Agent 与 Workflow 恢复分别要求独立的 `RESUME` / `RESUME WORKFLOW` 一次性确认。

## 预算语义

- `max_output_tokens` 是单次模型请求的输出上限。
- `max_input_tokens`、`max_cumulative_output_tokens`、`max_total_tokens` 是一个 Run 内的累计上限。
- `require_usage=true` 时，只要某次模型尝试未报告用量（包括成功重试之前的失败尝试），Run 就以 `token-usage-unavailable` 停止。
- Provider 报告的用量只能在调用后核算；当前没有调用前 Token 估算器，因此首个调用仍可能越过累计上限。
- `pricing.max_cost` 是使用指定价格表版本计算的累计 Run 费用上限；费用使用十进制精确计算，超限时在执行本次响应中的工具前以 `cost-budget` 停止。
- 费用预算与 Token 预算一样依据调用后实际报告值，不能保证首个请求在网络调用前不越限；缺少用量或价格时不会按零费用继续。
- 将 `max_attempts_per_route` 或 `max_routes` 设为大于 1 会授权额外、可能计费的重试或故障转移。

## 开放装配边界

`load_local_runtime_config()`、`assemble_local_provider()` 与 `assemble_local_runtime()` 是便利层，不是新的封闭 Runtime。Provider 单独装配返回 `LocalProviderAssembly`，只解析凭据引用并构造对象，不注册、不访问网络；应用随后可选择任意探测或注册策略。完整 Runtime 公开 Definition、Loop、ModelRegistry、ToolRegistry 和 SessionManager；`run()`/`resume()` 可通过 `event_callback` 投影按持久化顺序产生的实时事件。两种装配都支持 `async with` 和幂等 `aclose()`；关闭后完整 Runtime 拒绝继续运行。CLI/TUI 自动在同一事件循环内完成使用与关闭。应用可替换模板注册表、Provider 传输、路由、工具与 Store。

应用将 `{name: ToolBinding}` 作为 `tool_bindings` 传给装配器；配置只能选择其中的子集。`LocalAgentRuntime.run()` 接收本次运行的权限和可选批准 ID，`resume()` 接收 Session/Run ID、权限与非空精确批准集合。配置、Session、Checkpoint 和工程装配编码都不能生成权限、批准或本地执行授权。
