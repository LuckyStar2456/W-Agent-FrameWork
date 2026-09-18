# 本地测试、模型回放与评测

[English](./testing-evaluation.en.md) | 简体中文

状态：脚本化 Model Provider、显式录制/顺序回放、顺序评测运行器、JSON 报告、版本化费用指标和 CLI/TUI 评测入口为 `Experimental`（`2.0.0a2`）。客服/编码内置基准集仍为 `Planned`。

## 确定性模型测试

`ScriptedModelProvider` 使用有限的 `ScriptedModelTurn` 序列，不访问网络。每个 Turn 可以返回一组标准 `StreamEvent`，或抛出标准化 `ModelFailure`，并可校验请求模型和工具名。它适合测试 Agent Loop、路由消费者和失败分支；脚本耗尽时失败关闭。

## 录制与回放

`RecordingModelProvider` 包装任意 Model Provider，只在看到完整终止事件或标准模型失败后向 `JsonlModelCassette` 追加一条记录。`ReplayModelProvider` 按原顺序消费记录，不访问网络，并在请求结构不匹配或记录耗尽时拒绝继续。

录制和回放都要求 `allow_sensitive_content=True`。这是刻意的安全边界：Cassette 可包含模型文本、工具参数、工具结果和多媒体字节。可传入 `redact(str) -> str` 处理文本字段；二进制媒体不会被自动脱敏，文件本身仍需由开发者保护。

Cassette 的请求指纹只保存模型名、消息角色、内容块类型、工具名和配置形状，不保存 Prompt、凭据或扩展值。因此回放校验的是结构兼容性，不证明新 Prompt 与原请求语义相同。当前回放是进程内顺序消费，不提供并发调度、任意位置跳转或跨版本迁移。

## 本地评测

`LocalEvaluationRunner` 顺序执行 `EvaluationCase`，目标函数返回公开 `RunResult`。内置 `ExactTextScorer` 和 `ContainsTextScorer` 可替换或组合；普通异常按异常类型记为失败，取消继续向上传播。

`EvaluationReport` 汇总：

- 用例通过率、错误数、总延迟与平均延迟；
- 输入、输出、缓存输入和总 Token，以及计量是否完整；
- 使用同一版本价格表时的总费用、币种、版本及计价是否完整；
- 基于每个 Call ID 最终 `TOOL_COMPLETED` 事件的工具成功数、失败数和成功率；
- 每个 Scorer 的值、阈值和通过状态。

`JsonEvaluationReporter` 默认不写 Prompt、Metadata、模型输出或异常正文，只保留异常类型。只有显式设置 `include_outputs=True` 才写输出。评测只聚合 `RunResult` 已按应用提供的明确价格表版本计算出的费用；任一用例未完整计价或版本/币种不一致时，总费用保持 unavailable，不会从 Token 静默推断。

## CLI 用例集

`load_evaluation_cases()` 读取有大小和数量上限的严格 JSON，不导入或执行代码。用例名必须唯一：

```json
{
  "schema_version": 1,
  "cases": [
    {
      "name": "hello",
      "prompt": "Say hello",
      "expected_output": "hello",
      "metadata": {"suite": "smoke"}
    }
  ]
}
```

CLI 顺序运行用例；默认使用 `exact-text`，可重复传入 `--scorer exact-text` / `--scorer contains-text`，或单独使用 `--scorer none` 只检查 Run 是否完成。命令必须显式授权可能计费的模型调用：

```text
wagent evaluate cases.json --config .wagent/config.json --confirm-model-call --report report.json
```

默认使用一次性运行状态，结束后删除可能包含 Prompt 的 Session/Run 文件。只有传入 `--state-root` 才持久化它们。`--report` 写入安全默认报告；`--include-outputs` 会同时让报告与 `--json` 输出包含潜在敏感模型输出。只要任一用例失败，命令在输出报告后以状态码 1 结束。工具代码加载与工具权限继续使用 `--confirm-tool-code`、`--tool-entry` 和 `--grant-permission` 独立授权；需要人工批准的工具调用当前记为未通过，不会由评测命令自动批准。

TUI Evaluation 页读取同一用例集与 Runtime 配置，输入 `EVALUATE` 后才运行；确认立即清空，不会持久化。它始终使用一次性状态与 `exact-text` Scorer，可选写入默认脱敏报告，只展示汇总和逐用例状态。自定义 Scorer、输出持久化与开发者工具入口目前使用 Python API/CLI。

## 最小示例

```python
from w_agent import EvaluationCase, ExactTextScorer, LocalEvaluationRunner

report = await LocalEvaluationRunner().run(
    [EvaluationCase("hello", "Say hello", "hello")],
    run_case,
    scorers=[ExactTextScorer(case_sensitive=False)],
)
print(report.pass_rate, report.usage.total_tokens, report.usage_complete)
```

`run_case` 是开发者提供的异步函数，接收 `EvaluationCase` 并返回 `RunResult`。框架不隐式创建模型权限、工具权限或本地执行授权。
