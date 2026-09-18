# 本地测试、模型回放与评测

[English](./testing-evaluation.en.md) | 简体中文

状态：脚本化 Model Provider、显式录制/顺序回放、顺序评测运行器、JSON 报告、版本化费用指标和 CLI/TUI 评测入口为 `Experimental`（`2.0.0a2`）；当前 main 另含版本化客服/编码内置基准集、可替换套件注册表与声明式用例契约评分。

## 确定性模型测试

`ScriptedModelProvider` 使用有限的 `ScriptedModelTurn` 序列，不访问网络。每个 Turn 可以返回一组标准 `StreamEvent`，或抛出标准化 `ModelFailure`，并可校验请求模型和工具名。它适合测试 Agent Loop、路由消费者和失败分支；脚本耗尽时失败关闭。

## 录制与回放

`RecordingModelProvider` 包装任意 Model Provider，只在看到完整终止事件或标准模型失败后向 `JsonlModelCassette` 追加一条记录。`ReplayModelProvider` 按原顺序消费记录，不访问网络，并在请求结构不匹配或记录耗尽时拒绝继续。

录制和回放都要求 `allow_sensitive_content=True`。这是刻意的安全边界：Cassette 可包含模型文本、工具参数、工具结果和多媒体字节。可传入 `redact(str) -> str` 处理文本字段；二进制媒体不会被自动脱敏，文件本身仍需由开发者保护。

Cassette 的请求指纹只保存模型名、消息角色、内容块类型、工具名和配置形状，不保存 Prompt、凭据或扩展值。因此回放校验的是结构兼容性，不证明新 Prompt 与原请求语义相同。当前回放是进程内顺序消费，不提供并发调度、任意位置跳转或跨版本迁移。

## 本地评测

`LocalEvaluationRunner` 顺序执行 `EvaluationCase`，目标函数返回公开 `RunResult`。内置 `ExactTextScorer`、`ContainsTextScorer` 和 `CaseContractScorer` 可替换或组合；普通异常按异常类型记为失败，取消继续向上传播。`CaseContractScorer` 只读取 `metadata.contract`，可检查必需/任选/禁止工具、允许的停止原因、全部/任一文本片段和工具调用数量范围；未知字段或非法类型失败关闭，不执行代码。

`EvaluationReport` 汇总：

- 用例通过率、错误数、总延迟与平均延迟；
- 输入、输出、缓存输入和总 Token，以及计量是否完整；
- 使用同一版本价格表时的总费用、币种、版本及计价是否完整；
- 基于每个 Call ID 最终 `TOOL_COMPLETED` 事件的工具成功数、失败数和成功率；
- 每个 Scorer 的值、阈值和通过状态。

`JsonEvaluationReporter` 默认不写 Prompt、Metadata、模型输出或异常正文，只保留异常类型。只有显式设置 `include_outputs=True` 才写输出。评测只聚合 `RunResult` 已按应用提供的明确价格表版本计算出的费用；任一用例未完整计价或版本/币种不一致时，总费用保持 unavailable，不会从 Token 静默推断。

## CLI 用例集

`load_evaluation_dataset()` 读取有大小和数量上限的严格 JSON，保留可选的名称、版本和推荐 Scorer；`load_evaluation_cases()` 是只返回 Cases 的兼容便捷函数。两者都不导入或执行代码，用例名必须唯一：

```json
{
  "schema_version": 1,
  "name": "smoke",
  "version": "1.0.0",
  "scorers": ["case-contract"],
  "cases": [
    {
      "name": "hello",
      "prompt": "Say hello",
      "expected_output": null,
      "accepted_stop_reasons": ["completed"],
      "metadata": {
        "contract": {
          "allowed_stop_reasons": ["completed"],
          "expected_contains_any": ["hello", "hi"],
          "max_tool_calls": 0
        }
      }
    }
  ]
}
```

`accepted_stop_reasons` 默认只有 `completed`；需要验证审批边界的用例可显式设为 `needs-approval`。Runner 先检查停止原因，再应用所有 Scorer，因此声明式契约不能绕过用例自己的终止条件。

CLI 顺序运行用例；未传 `--scorer` 时使用数据集推荐值（普通旧格式默认为 `exact-text`），也可重复传入 `exact-text`、`contains-text`、`case-contract`，或单独使用 `none` 只检查 Run 是否完成。命令必须显式授权可能计费的模型调用：

```text
wagent evaluate cases.json --config .wagent/config.json --confirm-model-call --report report.json
```

## 内置客服/编码套件

`EvaluationSuite` 是普通不可变数据；`EvaluationSuiteRegistry` 可由应用新建、注册或完全替换。当前 main 提供 `customer-support@1.0.0` 与 `coding@1.0.0`，分别引用首批 Agent 模板推荐的工具名，验证缺失标识符处理、知识证据、写入审批，以及 inspect-first、受审批补丁和沙箱验证。审批用例通过显式 `accepted_stop_reasons=["needs-approval"]` 把安全暂停视为预期结果。它们不是厂商模型排行榜，也不内置工具实现、权限、审批或测试数据。

```text
wagent benchmark list --json
wagent benchmark export customer-support@1.0.0 support-suite.json
wagent evaluate builtin:customer-support@1.0.0 --config .wagent/config.json \
  --tool-entry my_tools:support_catalog --confirm-tool-code \
  --grant-permission tickets.read --confirm-model-call
```

`builtin:<name>[@version]` 只解析进程内已注册套件，不访问网络。省略版本使用该注册表最后注册的版本；需要可复现评测时应固定版本。`benchmark export` 产生同一严格 JSON 格式，目标已存在时必须显式 `--force`。内置用例多数要求宿主提供同名工具；未提供时失败是正确结果，不会自动下载或授予工具。

默认使用一次性运行状态，结束后删除可能包含 Prompt 的 Session/Run 文件。只有传入 `--state-root` 才持久化它们。`--report` 写入安全默认报告；`--include-outputs` 会同时让报告与 `--json` 输出包含潜在敏感模型输出。只要任一用例失败，命令在输出报告后以状态码 1 结束。工具代码加载与工具权限继续使用 `--confirm-tool-code`、`--tool-entry` 和 `--grant-permission` 独立授权；需要人工批准的工具调用当前记为未通过，不会由评测命令自动批准。

TUI Evaluation 页读取相同 JSON 或 `builtin:` 引用与 Runtime 配置，输入 `EVALUATE` 后才运行；确认立即清空，不会持久化。它使用一次性状态和数据集推荐 Scorer，可选写入默认脱敏报告，只展示汇总和逐用例状态。开发者工具条目与本次权限可单独填写；只有再次输入 `LOAD EVAL TOOLS` 才导入工具代码，模型调用确认不能替代代码导入授权。自定义 Python Scorer 与输出持久化仍使用 Python API/CLI。

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
