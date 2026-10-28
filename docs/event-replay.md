# 事件回放与展示状态重建

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./event-replay.en.md) | 简体中文

本页 a8 增量为 Experimental，针对性回归通过；完整验证范围见 [a8 发布说明](./releases/2.0.0a8.md)。

a8 的 TUI Replay 新增显式受信缓存导入续读和新文件导出，复用本页 CLI 的 JSON envelope、来源绑定及快照校验。导入需 `VIEW CONTENT` + `TRUST CACHE`，导出需 `VIEW CONTENT` + `SAVE CACHE`；不覆盖文件，不自动保存。此增量属于 a8 Experimental，针对性回归通过；路径、取消、部分文件和缓存信任边界见 [TUI 缓存操作](./tui.md)。

状态：`Experimental`。a6 引入单 Run 只读累积快照；a7 新增可选工具结果正文、Session 投影及 CLI/TUI 累积视图，针对性回归通过。验证范围见 [a7 发布说明](./releases/2.0.0a7.md)。

## 累积视图 CLI（2.0.0a7；针对性回归通过）

### a8：输入消息字段披露（2.0.0a8 Experimental；针对性回归通过）

`wagent session view` 新增 `--include-input-name` 和 `--include-input-metadata`，仅展示先前显式保存的输入消息字段，不是 Session 顶层 metadata，也不会补齐未记录的助手字段。两个开关各自默认关闭，任一开启均需 `--confirm-sensitive-content`；原有文本、输入媒体和输出媒体披露仍独立。

```text
wagent session view existing-session --include-input-name --confirm-sensitive-content
wagent session view existing-session --include-input-metadata --confirm-sensitive-content
wagent session view existing-session --input-media metadata
```

内容投影通过共享 `build_session_message_projector()` 装配：无字段开关且未选输入媒体时保留旧文本投影及身份；选择输入媒体或字段时使用包装兼容投影器，识别新字段 envelope，但只返回明确选中的 `input_fields`。因此 `--input-media metadata` 能读取新包装中的块元数据而不公开 name/metadata。损坏或超限的包装会拒绝，不静默丢弃。

新包装投影的身份不同于 a7 的直接输入块投影：旧输入媒体缓存须重新生成；字段或媒体选项改变也会拒绝续读旧缓存。完整缓存仍需同时确认敏感内容与 `--trust-snapshot`，来源绑定不是真实性证明。Session 文本专属投影保持原身份。Run-only 视图不支持字段开关。输出仍为转义 JSON，不解释字段中的 ANSI/Rich 控制内容，不执行模型、工具或修改 Store。对应针对性回归通过。

```text
wagent run-view selected-run --state-root .wagent --limit 100
wagent run-view selected-run --state-root .wagent --include-text --include-tool-results --confirm-sensitive-content
wagent session view selected-session --root .wagent/sessions --state-root .wagent --run-limit 10 --event-limit 100
```

两个新命令固定输出 JSON，不需要 `--json`；不会运行模型、工具或 Workflow，不获取媒体，也不主动写缓存。原 `run-events` 和 TUI 安全分页不变。默认隐藏正文；`--include-text` 展示模型文本，`--include-tools` 展示工具身份和参数，`--include-tool-results` 独立展示已记录结果。`--media metadata|references|content` 默认仅元数据。Session 的 `--include-session-text` 独立于模型文本。任一内容开关均需 `--confirm-sensitive-content`，在读取缓存或检查 Store 目录之前确认。

响应包含 `cache`（版本、种类、规范化绝对来源目录、完整快照）和 `page`（本次读取信息）。如需续读，自行将成功响应完整保存为 **UTF-8 JSON**，例如 `page-1.json`，再执行：

```text
wagent run-view selected-run --state-root .wagent --snapshot page-1.json --trust-snapshot --confirm-sensitive-content
wagent session view selected-session --root .wagent/sessions --state-root .wagent --snapshot session-page-1.json --run-offset 10 --trust-snapshot --confirm-sensitive-content
```

每次续读保留相同的内容披露选项；改变配置须从头重建。仅页大小和 Session 成员偏移可调整。将新响应保存为另一文件，不要将输出重定向到正在读取的缓存文件；Shell 会先截断它。Windows PowerShell 保存时须显式选择 UTF-8，不能使用默认 UTF-16；允许 UTF-8 BOM。加载任何缓存均需上述两个确认，因为缓存中的已有状态不再自动脱敏，不能加载他人提供或被篡改的缓存。来源、Run/Session ID、投影配置不匹配会拒绝；目录绑定不等于签名、历史日志校验或文件系统隔离。

Run 每次读取 1–500 个事件；Session 每次读取 1–32 个已登记 Run、每 Run 1–500 个事件。`next_run_offset` 只遍历成员；为旧 Run 读取追加事件，携带最新快照从偏移 0 再扫。`pending_run_ids` 仅代表尚未访问或上次仍有事件的 Run；为空不证明执行结束。默认拒绝 Session ID 缺失的旧事件，显式 `--allow-unscoped-events` 可接受无 ID 事件，仍拒绝其他 Session ID。

仅接受已有目录；Run 命令要求日志存在。沿用 API 的 8 MiB 单 Run / 32 MiB Session 快照上限，CLI 输入文件和完整转义输出另限 64 MiB。JSON 转义控制字符及非 ASCII 字符，不经 Rich 渲染正文；解析后仍能还原中文和媒体内容。错误不回显原始日志或异常正文，不输出部分新快照；缓存只读、不自动覆盖。底层 Session 仍加载完整记录，事件 Store 扫描前缀；这些限制不是整个日志的 I/O 或内存沙箱。[TUI Replay](./tui.md) 已提供只读内存视图（2.0.0a7，针对性回归通过），输入媒体记录另见 [Session schema 2](./sessions.md)，显式输入块投影与 CLI/TUI 披露见该文档；a7 针对性回归通过。

## 三种不同能力

- `RunEventReplay.page()`：读取已记录的原始事件，包含潜在敏感内容；游标按 Run 绑定，连续分页。
- `projected_page()`：逐事件投影，默认隐藏内容，允许应用选择自己的投影器。
- 新增 `RunEventAccumulator`：使用可替换 `RunEventReducer` 把连续分页累积成 `RunReplaySnapshot`，恢复客户端展示状态，不恢复 Agent 执行。

这些接口都不会重新调用模型、执行工具、下载媒体或批准检查点。Provider 断线续流、Agent 审批恢复、模型录制/回放是不同模块，不能混用其游标或授权。

## 默认隐藏内容的用法

```python
from w_agent import (
    JsonlRunStore, RunEventReplay, RunEventAccumulator,
    RunReplaySnapshot, TranscriptRunEventReducer,
)

replay = RunEventReplay(JsonlRunStore(".wagent"))
reader = RunEventAccumulator(replay, TranscriptRunEventReducer())
page = await reader.page("selected-run", limit=100)
payload = page.snapshot.to_dict()  # 由宿主选择是否、如何持久化。

# 新进程读取宿主保存的 JSON 后，使用相同 Run 和 reducer 配置继续。
restored = RunReplaySnapshot.from_dict(payload)
next_page = await reader.page("selected-run", snapshot=restored, limit=100)
```

`has_more` 仅表示当前读取时还有后续记录，不表示 Run 已结束。应用可稍后再次读取同一快照之后的新事件；本接口不后台轮询或订阅。快照状态与游标必须一起保存。整页失败不返回部分新快照，输入快照保持不变；成功页返回 `events_applied` 和新快照。不要单独推进游标后丢弃状态。

快照 schema 1 严格保存 `cursor`、`reducer` 和 JSON 状态，内存中深度只读；`to_dict()` 返回独立的可序列化副本。Run 或 reducer 标识不匹配时拒绝继续。内置 reducer 的标识包含版本、披露开关和大小限制；改变配置应从头重建，不可手工篡改标识绕过检查。

## 内置 transcript 模板

`TranscriptRunEventReducer` 默认 `include_text=False`、`include_tools=False`、`media_mode="metadata"`：

- `blocks` 按 `(step, block_index)` 累积文本/工具参数片段和图片/音频块。默认仅保留类型、位置、字符计数及媒体元数据。
- `models` 保存模型完成信息；显式 `include_text=True` 才保存最终文本。最终文本与增量块分开，不重复拼接。
- `tool_events` 保存请求和执行状态历史，包括多次 `needs-approval` 和后续结果。显式 `include_tools=True` 才保存 Call ID、工具名、参数片段及已记录的完整请求参数，不执行或自动解析这些参数。
- 媒体 `references` 模式允许记录中的 URL，`content` 还允许内联 Base64；标准内联内容会核对长度和 SHA-256。仅返回已存引用/内容，不读取 URL 或文件。
- `usage` 和 `cost` 替换为最新累计快照，不重复相加。`RUN_RESUMED` 清除之前的 `stop_reason`；`RUN_COMPLETED` 记录当次停止原因，`needs-approval` 不代表永远结束。

开启文本、工具或媒体内容披露必须由宿主先授予原始日志读取权限。更丰富的快照可能包含凭据、私有参数、图片或音频，须按原日志级别保护；默认 CLI/TUI 仍使用已有安全分页投影，未自动展示富内容快照。

## 扩展与限制

自定义 reducer 提供 `identity`、`initial_state()` 与 `reduce(state, event)`。identity 必须随状态 schema 和选项改变。状态输入是独立 JSON 副本，结果必须是有限 JSON 对象。内置模板不认识的新媒体格式、应用领域状态可通过替换 reducer 支持，无需修改核心分页协议。reducer 是受信 Python，不是插件沙箱；应保持无副作用。

默认限制为 1,024 个块/模型完成记录、4,096 条工具状态、每块 1,000,000 字符、单媒体 8 MiB 和 16,384 字符引用。累积器还限制整个序列化快照为 8 MiB（包含 Base64 膨胀和其他字段）；需要更大快照时必须显式调整。超限、块类型冲突、工具增量身份改变或媒体校验失败会拒绝本页，不静默截断。

快照是受信展示缓存，不是密码学证明或跨进程执行所有权。不会验证快照来自哪个 Store，也不会发现旧事件被外部篡改；宿主必须固定 Store 来源并保护缓存。重传旧页、从中间开始却没有对应状态、缺失的事件均不能自动补齐。

文本/工具增量和媒体只有先前启用对应记录选项才存在；模型最终文本和工具请求按现有 RunEvent 记录可重建。a6 的 `TOOL_COMPLETED` 不保存工具结果正文；a7 提供下述可选记录，以及 [Session 跨 Run 只读视图](./sessions.md)（2.0.0a7，针对性回归通过）。不能凭状态还原未记录的正文。CLI 接线见下文；TUI 已接入只读内存快照（2.0.0a7，针对性回归通过），输入媒体记录已纳入 a7（见 [Session 文档](./sessions.md)），可独立选择输入块展示；任意执行栈恢复不在此功能范围。

a7 的 `RunEventAccumulator` 读取端接受 `RunEventPageSource.page()` 协议，兼容原 `RunEventReplay`；第三方读端须返回满足连续性约束的 `RunEventPage`。累积器另核对返回游标和请求上限，拒绝错误 Run/位置或超量页面，不把错误页应用到快照。

## 工具结果正文（2.0.0a7；针对性回归通过）

写入与展示分别显式开启，`include_tools=True` 不自动公开结果正文：

```python
from w_agent import AgentDefinition, RunEventAccumulator, RunEventReplay, TranscriptRunEventReducer

definition = AgentDefinition(
    "assistant", emit_tool_results=True, max_tool_result_event_bytes=65536,
)
# 将 definition 传给你装配的 loop；store 是该 loop 实际使用的 RunStore。
reader = RunEventAccumulator(
    RunEventReplay(store),
    TranscriptRunEventReducer(include_tool_results=True, max_tool_result_bytes=65536),
)
page = await reader.page("selected-run")
```

ReAct 只在产生实际模型可见 `ToolResultContent` 后，向同一个 `TOOL_COMPLETED` 追加 `result_recording`：`recorded` 携带 `result` 对象，`omitted` 表示应用编码器主动返回 `None`，`failed` 表示编码异常、非 JSON 或超限。关闭记录时两个字段都不存在；待审批（包括续执行票据）不会记录正文或标记。

默认 `TextToolResultEventEncoder` 编码为 `{"kind":"text","text":"…","is_error":false}`，不截断、不脱敏、不访问文件或 URL。错误工具记录的是原本送给模型的标准错误内容，而不是 executor 的原始异常或 `data` 对象。两级大小限制分别为标准编码器文本 UTF-8 字节数，以及整个 `result` 的 JSON UTF-8 字节数（包括键、转义与分隔符），默认 64 KiB；因此正文略小于 64 KiB 仍可能被外层大小限制拒绝。自定义对象也必须是深度不超过 32 的有限 JSON，并受外层上限约束。

可向 `ReactAgentLoop(..., tool_result_event_encoder=encoder)` 或 `assemble_local_runtime(..., tool_result_event_encoder=encoder)` 注入 `ToolResultEventEncoder.encode(result, *, name)`。它接收不可变的模型可见结果与工具名，可脱敏、使用应用自定义 JSON 结构或返回 `None`；没有授予工具执行权，也不能改变已经返回给模型的内容。编码器是可信同步 Python，宿主自行保证其纯函数行为；此接口不是沙箱。配置文件只能选择记录开关与上限，不自动导入编码器。检查点不保存 Python 编码器，重启后宿主必须重新注入所需脱敏策略；未注入时使用默认明文编码器。

编码失败仅产生固定状态，隐藏异常正文和部分内容，继续既有循环，不把已完成工具变成重试；进程级中断与事件持久化失败不被此辅助记录层吞掉。已有恢复路径在存储失败时保留不确定状态，不自动重放，也没有新增跨 Store 原子保证。关闭事件正文记录不意味着其他消息、Checkpoint 或原始日志不含敏感内容。

累积器只有在 `include_tool_results=True` 时读取 `result`，检查状态/正文一致性与大小上限；自定义 JSON 原样作为展示数据保留，不解析为命令、不读取引用。损坏页失败且不推进快照。旧日志无正文时不伪造内容；默认安全投影只公开固定 `result_recording` 状态，不公开正文。结果开关与 `include_tools`（身份/参数）彼此独立。

不开启结果展示时保持 a6 的 reducer 身份，原有快照可继续使用；开启后使用新的 `/2/` 身份并绑定结果上限，不能直接沿用旧配置快照，须从日志起点重建。快照 envelope 仍为 schema 1。正文只在记录后才可回放，历史缺失内容不会自动补齐。
