# Session 生命周期与跨 Run 上下文

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./sessions.en.md) | 简体中文

现提供 [Qdrant 历史选择器](./vector-retrieval.md)：沿用异步检索协议，只选择当前本地候选段，按 namespace/Run/文本生成匹配 ID，不采用远端正文或上传历史；宿主预建索引并提供 Embedding。已随 2.0.0 发布，本地回归通过，不属于 a9。

a9 另新增 `SQLiteSessionSummaryObserver`，可替换下文摘要器的内存观察器，显式保存并重开摘要 Run 报告；不持久化主 Run 聚合、不自动修改 Session 统计。此增量2.0.0a9 Experimental，验证范围见 a9 发布说明，见[持久化计量](./context-accounting.md)。

本页 a8/a9 增量为 Experimental；a9 验证范围见 [a9 发布说明](./releases/2.0.0a9.md)。

状态：本地 Session 生命周期、JSON 持久化、文本历史和审批恢复为 `Implemented`（a1）；跨 Session 用量/费用汇总为 `Experimental`（a4）。a7 新增跨 Run 只读富内容视图、CLI/TUI Replay、schema 2 可选输入记录、标准解码与可替换历史策略，均为 `Experimental`。针对性回归通过，验证范围见 [a7 发布说明](./releases/2.0.0a7.md)。

## 公共 API

- `SessionManager`：协调生命周期、文本历史和普通 `AgentLoop`。
- `SessionRecord`：不可变 Session 快照，包含消息、Run 摘要和元数据。
- `SessionRunRecord`：保存停止原因、输出、步骤/工具计数和 Token 用量。
- `AgentUsageSummary`：不含 Prompt/输出的单 Agent 跨 Session 用量、费用与完整性摘要。
- `InMemorySessionStore`：测试和短期本地开发。
- `JsonSessionStore`：单一本地生命周期所有者使用的原子 JSON 存储。
- `RunEventCallback`：可选同步/异步应用投影；按 Agent Loop 的公开事件流顺序调用，内置 ReAct Loop 会先写 RunStore 再暴露事件。

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
wagent session usage --agent support --include-archived --json
wagent session archive case-1
wagent session unarchive case-1
```

CLI 与 TUI 使用相同的公开 `SessionManager`/`JsonSessionStore`，默认目录为 `.wagent/sessions`。`show` 返回消息、Run 摘要、模型尝试/用量/计价计数、输入/输出/缓存 Token、版本化费用及完整性，不会启动模型或产生费用。`SessionManager.agent_usage()` 与 `wagent session usage` 按精确 Agent 名称汇总多个 Session；默认排除归档 Session，可显式纳入。汇总不读取或输出 Prompt、消息、模型输出和工具结果。未上报的用量保持不完整，缺失费用以及价格表版本/币种不一致时费用保持不可用，不会被当作零或静默合并。TUI 的 Session 页面显示同一安全摘要，并继续提供创建、刷新、归档和恢复；Run 页面支持经独立确认的工具代码加载、权限输入和脱敏实时事件。CLI/TUI 均支持通过已知 Session/Run/Call ID 审批恢复。

下一次 `run_agent()` 默认把此前投影的文本消息放在本次消息之前。设置 `include_history=False` 可关闭自动上下文拼接，但本次输入与结果仍会记入 Session。

## 审批恢复

当 Run 以 `NEEDS_APPROVAL` 停止后，使用同一 Loop/RunStore 和本地应用提供的批准调用 `resume_agent()`。Manager 验证 Run 属于该 Session，更新原 Run 摘要而不是创建重复记录，也不会重复保存用户输入。

配置化入口可调用 `LocalAgentRuntime.resume()`；CLI 对应 `wagent run-resume`。两者都要求运行时重新提供权限与非空精确 Call ID 集合，不从 Session 或 Checkpoint 恢复授权。

`run_agent()`、`resume_agent()`、`LocalAgentRuntime.run()` 和 `resume()` 接受可选 `event_callback`。回调可以是同步或异步函数，按执行流顺序接收 `RunEvent`；内置 `ReactAgentLoop` 在回调可见前持久化事件。第三方 Loop 只有在请求恢复事件回调时才需要提供 `resume_stream()`；原有无回调的 `resume()` 保持兼容。回调异常会停止宿主调用，不会被静默吞掉。TUI 仅展示白名单字段，不显示模型文本、工具参数或工具结果。

## 检索与摘要上下文模板（2.0.0a8；针对性回归通过）

本节是 a7 之后的源码新增能力，不属于 PyPI a7。默认 `TextSessionHistoryPolicy` 不变；应用可逐次向 `SessionManager.conversation()` / `run_agent()` 或 `LocalAgentRuntime.run()` / `run_messages()` 传入策略。

```python
from w_agent import (
    RetrievedSessionHistoryPolicy, SummarizedSessionHistoryPolicy,
    ExtractiveSessionHistorySummarizer, SessionHistoryLimits,
)

limits = SessionHistoryLimits(max_messages=512, max_output_bytes=32 * 1024)
retrieved = RetrievedSessionHistoryPolicy(
    query="退款 发票", max_retrieved_turns=4, recent_turns=2, limits=limits,
)
history = await manager.conversation(session_id, history_policy=retrieved)

summarized = SummarizedSessionHistoryPolicy(
    summarizer=ExtractiveSessionHistorySummarizer(max_chars=4096, chars_per_message=256),
    recent_turns=2, limits=limits,
)
# 真正运行仍由应用自行授权；以下只构建历史，不调用模型。
history = await manager.conversation(session_id, history_policy=summarized)
```

- `SessionHistoryTurn` 表示连续相同 Run ID 的消息段，不保证是完整对话轮次；同 Run ID 在其他 Run 之后再次出现时不合并。选择完整消息段，保留段内角色和原始顺序。
- `RetrievedSessionHistoryPolicy` 对近期尾部以外的消息段检索，再与保留的近期段合并，按时间顺序输出。`query` 由宿主按本次问题显式提供，不从旧记录猜测。`recent_turns=0` 不保留尾部；无匹配时只输出尾部。
- `KeywordSessionHistoryRetriever` 对空白分隔、大小写折叠后的查询词做子串匹配，按命中词数排序，同分优先较新段；中文可用空格分词。它不是语义搜索或向量数据库。自定义 `SessionHistoryRetriever.select(query, turns, *, limit)` 只返回唯一、界内的整数索引 tuple，不可返回新消息或变更角色；输出仍恢复原顺序。
- `SummarizedSessionHistoryPolicy` 将较早消息段交给 `SessionHistorySummarizer.summarize(turns)`，尾部原样保留。内置抽取式摘要仅保留各消息前缀与角色标签，受字符上限控制，不推断事实。摘要是明确标注可能不完整的 USER 数据消息，绝不提升为 SYSTEM 指令；标签不能防止提示注入，摘要也可能丢失关键事实。
- 内置模板仅处理已有 Session 文本，不解码媒体，不发送或下载 URL；媒体专属记录被忽略，媒体消息中的文本仍可参与。SYSTEM/TOOL 角色拒绝处理，不静默删除；有此需求可替换整个策略。自定义回调只接收文本消息段，不接收原始 Session 元数据或媒体记录。
- 默认最多 1,024 条原始消息、1 MiB 输入文本、64 KiB 输出文本及 4 KiB 查询，均按 UTF-8 字节计量；摘要器另有字符上限。输入超限在回调前拒绝，输出超限不返回部分结果。不是 Token 预算、总 I/O/内存沙箱，也不限制自定义回调内部开销。
- 上述同步策略不写 Store、不隐式调用模型/工具/网络。回调是显式注入的同步受信 Python，应无副作用；异步适配见下一节。模型生成摘要须另行授权、计量，可由宿主预计算或通过异步回调接入。框架不自动重试回调。错误不回显原始内容；`include_history=False` 跳过策略，审批恢复仍使用原检查点。

a8 另通过 `BuiltinSessionHistoryOptions` 将内置模板接入 CLI/TUI（同为 2.0.0a8 Experimental；针对性回归通过）：`retrieved` 要求显式检索词，`summarized` 使用本地抽取器，二者均需独立上下文变换确认。选项对象只构建内置策略，不加载自定义代码、不授予权限；Python 注入整个策略的能力保持不变。详见[运行入口](./local-runtime.md)和 [TUI](./tui.md)。针对性回归通过；具体外部检索已提供可注入的 Qdrant 模板，真实后端仍待验收；模型摘要 Python 适配器见下文。

### 异步历史准备（2.0.0a8；针对性回归通过）

新增 `AsyncSessionHistoryPolicy.project(session)`，与同步协议并存。`conversation()`、`run_agent()` 和 Runtime 两种运行入口均接受该策略，遇到 awaitable 会等待，再检查返回的消息 tuple。只通过 Python 显式注入；JSON 配置和 CLI/TUI 内置选项不会加载异步插件或隐式访问外部服务。

`AsyncRetrievedSessionHistoryPolicy` 要求注入 `AsyncSessionHistoryRetriever.select(query, turns, *, limit)`；`AsyncSummarizedSessionHistoryPolicy` 要求注入 `AsyncSessionHistorySummarizer.summarize(turns)`。没有外部客户端默认实现。两种模板沿用文本大小限制、近期段保留和角色限制，先校验输入再调用；仅传入较早文本段，不发送 Session 标题、元数据或媒体记录。检索仅接受唯一界内索引并恢复时间顺序；摘要作为不可信 USER 数据，无 SYSTEM 提权。没有较早段则不调用回调。

```python
from w_agent import AsyncRetrievedSessionHistoryPolicy, CancellationToken

class HostRetriever:
    async def select(self, query, turns, *, limit):
        # host_search 由宿主提供并授权，负责超时、客户端资源和费用记录。
        indices = await host_search(query, turns, limit=limit)
        return tuple(indices)

policy = AsyncRetrievedSessionHistoryPolicy(
    query="退款 发票", retriever=HostRetriever(), recent_turns=2, timeout=20,
)
token = CancellationToken()
history = await manager.conversation(session_id, history_policy=policy, cancellation=token)
# 也可将同一 policy 和 token 逐次传给 runtime.run(..., history_policy=policy, cancellation=token)。
```

模板的 `timeout` 默认 30 秒，必须为有限正数，限制一次回调等待；不自动重试。取消 Token 或调用任务取消会取消正在等待的投影并等待其清理，`CancelledError` 不转换为普通失败。超时/取消依赖协作，不能强制停止阻塞同步代码或撤销已经发生的网络调用；客户端仍需自身 I/O 超时。不自动转线程或关闭宿主拥有的客户端。任意自定义异步策略须自行提供超时。

异步投影后会重新读取 Session，检测到内容/状态变化则拒绝启动 Agent，不自动重新调用回调；这不是跨进程事务或锁。输入额外记录的预校验在历史回调前完成。准备失败/取消不追加本次 Run，但已创建的新空 Session 可能保留，宿主回调已产生的副作用不会回滚。

**计量边界：异步准备发生在主 Agent Run 之前，其检索、嵌入、摘要模型费用不会自动进入主 Run 的 Token/费用预算、事件或 Session 汇总。** 宿主必须独立取得发送同意并计量；下节提供独立 Run 的模型摘要适配器，但不共享主 Run 预算。a8 已提供[显式摘要/主 Run 用量归集](./context-accounting.md)，向量检索与独立共享预算包装已有本地模板；统一准备/主 Run 费用归集和真实后端仍待验收。取消、超时、输入/输出限制、会话变化和 Runtime 接线测试已通过。

### 可计量的模型摘要（2.0.0a8 Experimental；针对性回归通过）

可直接使用 `InMemorySessionSummaryObserver` 代替下面的自定义内存列表观察器，随后 `snapshot(main_result)` 显式归集摘要与主 Run 的已知 Token/分组费用，详见[归集专题](./context-accounting.md)。此模块同为 2.0.0a8 Experimental；针对性回归通过增量，不提供统一硬预算或自动修改 Session 统计。

`AgentSessionHistorySummarizer` 实现异步摘要回调，注入宿主的 `AgentLoop` 和必需的 `SessionSummaryObserver`，可直接装配到 `AsyncSummarizedSessionHistoryPolicy`。每次生成独立的 `summary-...` Run ID，不继承主 Session ID、工具授权或历史策略，不改写 Session。需要宿主另行授权向所选模型发送旧文本。

```python
from w_agent import (
    AgentDefinition, AgentSessionHistorySummarizer,
    AsyncSummarizedSessionHistoryPolicy, ReactAgentLoop,
    ToolRegistry, ToolExecutor, TokenBudget,
)

class Accounting:
    def __init__(self):
        self.reports = []  # 示例仅内存保存；生产宿主应提供自己的持久计量设施。

    async def record(self, report):
        self.reports.append(report.to_dict())

tools = ToolRegistry()  # 专用空目录，不向摘要模型暴露业务工具定义。
summary_loop = ReactAgentLoop(model_executor, tools, ToolExecutor(tools), store=summary_store)
accounting = Accounting()
summarizer = AgentSessionHistorySummarizer(
    summary_loop, accounting,
    definition=AgentDefinition(
        "history-summary", max_steps=1, max_tool_calls=0, max_output_tokens=1024,
        token_budget=TokenBudget(max_total_tokens=12000, require_usage=True),
    ),
)
policy = AsyncSummarizedSessionHistoryPolicy(summarizer, recent_turns=2, timeout=30)
# 宿主授权后再执行：await runtime.run(prompt, history_policy=policy)
```

默认 Definition 为一步、零工具调用、每请求最多 1,024 输出 Token、要求 Usage。可替换 Definition 的模型、系统提示、预算及其他设置；此模板要求 `max_tool_calls=0`，有其他行为需求可替换整个摘要器。零工具调用限制不会自动隐藏已注册的工具定义，所以使用专用空 ToolRegistry。自定义 Loop 是受信代码，不是沙箱。

旧消息以角色/文本 JSON 包装成一个 USER 请求，不发送原 Run ID、name/metadata 或媒体；标注“不可信数据”不是提示注入防护。`SessionHistoryLimits` 限制消息数、合成 USER 提示 UTF-8 字节数和摘要输出字节数；不包含宿主自定义 Definition 的系统提示/扩展，也不替代 Token 估算。空摘要、超限、非完成终态、工具调用/待审批结果被拒绝。

`SessionSummaryRunReport` 仅含 Run ID、状态、终止原因、输入/输出/缓存 Token、调用计数、费用和完整性，不含提示、摘要、异常正文或尝试详情。调用前报告 `started`，有合法结果后报告 `completed` 或 `rejected`；拒绝采用摘要仍保留实际报告的用量。异常或取消未得到合法结果时报告 `failed` / `cancelled`，用量与计数为 `None`，不冒充零；按 Run ID 对账，不把开始/终态重复累计。

观察器开始报告失败则不调用模型；终态报告失败则不返回摘要，不自动重试。取消仍传播；取消时的终态通知是尽力而为，观察器失败或进程退出可能只留下 started，需要按 Run ID 核对独立 Store/Provider。内置 ReAct Loop 的事件、预算、重试/路由策略沿用已有装配；适配器自身不重试、不关闭宿主客户端。内置 Loop 的原始事件可能包含敏感内容，观察器脱敏不等于 Store 脱敏。

指定 `CostBudget` 时需为摘要 Loop 配置对应 `PricingResolver`。摘要预算独立于主 Run、每次调用重新开始；默认仅有输出请求上限，没有默认总 Token/费用硬上限，按需显式配置。主 Agent 总消耗尚未自动合并，跨多次摘要的共享限额及 CLI/TUI 入口仍待实现。已补网络外的脚本化 Provider/ReAct 集成、预算拒绝、观察器失败、取消和未知用量测试已通过，未进行真实模型验证。

## 可选输入媒体记录（2.0.0a7；针对性回归通过）

### a8：可选 name/metadata（2.0.0a8 Experimental；针对性回归通过）

`MessageFieldsSessionInputRecorder` 包装已有输入记录器，`include_name` / `include_metadata` 默认均关闭。实际选中非空字段时使用 `w-agent.session-message/1` 包装 envelope，内含原 `content` codec 和独立 `fields`；Session 仍用 schema 2。不选字段、字段为空或委托记录器省略记录时，分别保留原格式或省略整个额外记录，不自动生成字段。

```python
from w_agent import (
    SessionManager, JsonSessionStore, MessageFieldsSessionInputRecorder,
    MessageFieldsSessionInputDecoder, RecordedSessionHistoryPolicy,
    MessageFieldsSessionMessageProjector,
)

# 1. 选择保存字段；真正记录仍需本次 record_inputs=True。
manager = SessionManager(JsonSessionStore(".wagent/sessions"), input_recorder=
    MessageFieldsSessionInputRecorder(include_name=True, include_metadata=True))
# await manager.run_agent(loop, definition, session_id, messages, record_inputs=True)

# 2. 只解码内容不会发送字段。额外 fields_decoder 才启用所选字段复用。
decoder = MessageFieldsSessionInputDecoder(include_name=True, include_metadata=True)
content_only = RecordedSessionHistoryPolicy(decoder=decoder)
with_fields = RecordedSessionHistoryPolicy(decoder=decoder, fields_decoder=decoder)
history = await manager.conversation(session_id, history_policy=with_fields)

# 3. 展示另行选择，不改变发送策略；文本和媒体仍由内层投影器控制。
projector = MessageFieldsSessionMessageProjector(include_name=True)
```

字段总 JSON UTF-8 大小默认至多 64 KiB；name 必须为非空字符串，最多 256 个字符；metadata 必须为字符串键的有限 JSON 对象，不允许对象实例、NaN/Infinity 或过深嵌套。包装后的整个记录仍受 16 MiB 上限和 Session 批量预算约束。选中字段会被分离复制并随 Session 深度冻结；恢复到模型消息时再复制，不共享持久记录的嵌套对象。字段不启用时，不额外校验被忽略的消息元数据。

新解码器可包装自定义内容解码器；无字段包装的旧记录委托原解码器处理。`SessionMessageFieldsDecoder.decode_fields()` 是独立可替换协议，历史策略再次验证只含 name/metadata，并将字段 JSON 计入总体内容预算。`max_message_field_bytes` 默认 64 KiB。不允许通过此返回值覆盖角色或授予工具权限；metadata 中即使含类似权限的键，也只是数据。宿主必须审查所选 Provider/扩展如何使用这些字段，以及其中是否包含敏感值。

`MessageFieldsSessionMessageProjector` 默认隐藏字段；`include_name` / `include_metadata` 独立选择，值位于 `input_fields`。其身份包含内层投影身份、字段开关与上限，改变披露配置需重建快照。包装结构/字段损坏、超限或嵌套包装会失败，即使字段未展示也不跳过验证。记录器、内容解码器和内层投影器均可替换，不从 codec 导入 Python。

兼容边界：a7 可存取 schema 2 中的未知记录，但其标准内容解码器不认识新包装 codec；读取新包装内容需a8 的新解码器/投影器，旧文本投影不变。a8 CLI/TUI Replay 已接入字段披露和包装内容展示，详见 [Replay](./event-replay.md)；Run 输入文件默认拒绝 name/metadata，现可显式选择字段发送、保存与历史复用，见[运行选项](./local-runtime.md)。上述 a8 针对性回归通过，不扩大历史 a7 的验收范围。此开关不关闭既有 Checkpoint、RunEvent 或 Provider 日志，也不自动记录最终助手消息的 name/metadata。

### 展示、解码与模型历史策略（2.0.0a7；针对性回归通过）

新增 `SessionInputDecoder` / `StandardSessionInputDecoder`、`SessionHistoryPolicy`、`TextSessionHistoryPolicy` 和 `RecordedSessionHistoryPolicy`。记录、展示、再次发送给模型各自独立；仅记录或打开回放页面，不会启用媒体历史。

```python
from w_agent import RecordedSessionHistoryPolicy, RecordedSessionMessageProjector

# 此选择代表宿主本次明确允许将记录的输入用于模型历史；不保存为未来授权。
policy = RecordedSessionHistoryPolicy(max_messages=128, max_content_bytes=16 * 1024 * 1024)
history = await manager.conversation(session_id, history_policy=policy)  # 只构建，不调用模型
result = await manager.run_agent(
    loop, definition, session_id, current_messages, history_policy=policy,
)

# 与模型历史不同的只读展示策略，显式装配到 SessionEventReplay。
projector = RecordedSessionMessageProjector(include_text=False, media_mode="metadata")
```

默认仍为 `TextSessionHistoryPolicy`，忽略额外媒体记录。富内容策略以解码块替换该消息的文本投影，保留原角色与顺序；没有额外记录的旧消息使用文本，有记录但 codec 未知、字段损坏或超限则失败，不静默回退。每次 `run_agent` 必须重新选择策略；`include_history=False` 跳过策略。策略不写 Store，不下载 URL、不重放工具；后续 Provider 可能自行获取 URL，宿主仍须控制目的地、能力、费用及发送同意。审批恢复沿用已有 Checkpoint，不重新应用历史策略。

标准解码器只接受 `w-agent.session-input/1` 的严格 text/image/audio envelope，检查 Base64、字节数和 SHA-256；摘要不是签名，不能证明来源可信。默认单消息 256 块、每文本块 1,000,000 字符、单媒体 8 MiB、引用 16,384 字符，记录格式仍限 16 MiB。富历史默认至多 1,024 条消息、32 MiB 内容（UTF-8 文本/URL、内联原始字节及 MIME 字符串），不静默截断；该预算不是 Token、请求 JSON 大小或全流程内存上限。自定义 decoder 显式注入 `RecordedSessionHistoryPolicy(decoder=...)`，不能靠记录中的 codec 导入代码；新增块类型或检索、摘要、选择规则可替换整个 `SessionHistoryPolicy.project(session)`。自定义组件是受信 Python，必须自行保证无副作用。

`RecordedSessionMessageProjector` 独立展示有序输入块，默认隐藏文本、URL 和内联正文；可选 `references` / `content`，文字另由 `include_text` 控制。未知 codec 拒绝本页，可替换消息投影器支持自定义编码。配置与大小限制进入投影身份，改变策略须重建快照；任何消息失败不返回部分新 Session 快照。旧 `TextSessionMessageProjector` 保持原行为。`text` 和 `input_blocks` 是同条消息的两种视图，不能拼接成两次输入。

CLI：`wagent session view <id> --input-media metadata` 展示输入块元数据；引用/正文须加 `--confirm-sensitive-content`，与输出 `--media` 分开。`--include-session-text` 控制 Session 文本，默认不输出。TUI Replay 对应独立 `Session input media` 字段（默认 `off`）；引用/正文需逐次 `VIEW CONTENT`，改变选项清空旧快照。两种界面均不改变模型上下文策略，也不下载或渲染媒体。TUI 媒体输入与历史选择已接入 Run 表单；a7 入口针对性回归通过。检索/摘要模板是本节前述 a8 Experimental 增量，针对性回归通过。

### 保存输入

`SessionManager.run_agent(..., record_inputs=True)` 显式保存本次输入；默认 `False`，保持既有文本行为。宿主须先取得用户对原始输入持久化的同意。以下假定宿主已装配 `loop`、`definition`：

```python
from w_agent import (
    SessionManager, JsonSessionStore, ModelMessage, MessageRole,
    TextContent, ImageContent, StandardSessionInputRecorder, session_input_to_dict,
)

manager = SessionManager(
    JsonSessionStore(".wagent/sessions"),
    input_recorder=StandardSessionInputRecorder(max_inline_bytes=4 * 1024 * 1024),
)
session = await manager.create("Inspect an image")
await manager.run_agent(
    loop, definition, session.session_id,
    (ModelMessage(MessageRole.USER, (
        TextContent("Describe this image"),
        ImageContent(url="https://example.test/private-image.png"),
    )),), record_inputs=True,
)
stored = await manager.get(session.session_id)
payload = session_input_to_dict(stored.messages[0].recorded_input)
```

内置模板保留有序 text/image/audio 块，URL 原样保存但不下载；内联媒体保存 Base64、字节数和 SHA-256。默认 StandardSessionInputRecorder 不保存消息 name/metadata；显式包装记录器见上文a8 Experimental 增量。工具调用/结果等其他块报错，不静默丢弃；可替换 `SessionInputRecorder.record(message)`，返回带非空版本化 `codec` 的有限 JSON 对象，或以 `None` 省略额外记录。自定义记录器是受信 Python；框架不自动导入 codec、获取 blob 或执行记录。记录器仅控制额外字段，原 `SessionMessage.text` 仍保存原文本，不能仅靠替换记录器完成整个 Session 脱敏。

在 Agent 执行前编码、检查大小并深度冻结所有当前输入；失败以无敏感正文错误拒绝启动。默认每批 256 消息 / 32 MiB（含文本副本），可在 Manager 配置。每条记录格式上限 16 MiB、JSON 深度 32；标准模板默认每消息 256 块、每文本块 1,000,000 字符、每内联媒体 8 MiB、每引用 16,384 字符，可调小。限制不包含整个历史 Session，Store 文件和读取内存仍需宿主治理。

`SessionMessage.recorded_input` 深度只读；`session_input_to_dict()` 返回独立副本。首次实际保存记录时升级 schema 2，后续纯文本运行/归档不降级。未开启或全部返回 `None` 的已有 Session 保持 schema 1。新读端接受 schema 1/2，拒绝未知版本及 schema 1 夹带新字段；a6 等旧读端不支持 schema 2。保留备份，不可手改版本号绕过不兼容。

沿用运行返回后才保存输入和摘要的生命周期，不是运行前持久日志。崩溃、取消或模型失败不保证留下输入；保存失败可能发生在真实动作之后，不自动重跑。审批恢复不重复记录输入。`conversation()` 和默认历史仍只使用文本，媒体-only 消息不伪造成空文本；保存不授权再次向 Provider 发送媒体。

默认 Session 消息投影与 CLI/TUI 不自动展示该字段；原始 Python Store 可读取它，须按敏感数据保护。输入媒体独立展示和历史策略见上文；TUI 媒体录入与历史选择已接入，可选 name/metadata 保存已作为 a8 Experimental 包装记录器加入 a8，CLI/TUI 保存/发送接线和只读字段披露均已接入 a8，a8 针对性回归通过。

## 跨 Run 富内容展示（2.0.0a7；针对性回归通过）

`SessionEventReplay` 从 `SessionRecordSource.get()` 读取已登记的 Run 顺序，再从 `SessionRunReplaySource.page()` 分别累积日志。可直接传入现有 Session Store（或 `SessionManager`）和 `RunEventReplay`，也可替换两种只读数据源、`RunEventReducer` 与 `SessionMessageProjector`。不扩充持久化 Session schema，不修改 `conversation()` 或自动上下文注入，不启动 Agent/Workflow，也不授予权限。

```python
from w_agent import (
    JsonSessionStore, JsonlRunStore, RunEventReplay, SessionEventReplay,
    SessionReplaySnapshot, TextSessionMessageProjector, TranscriptRunEventReducer,
)

reader = SessionEventReplay(
    JsonSessionStore(".wagent/sessions"),
    RunEventReplay(JsonlRunStore(".wagent")),
)
page = await reader.page("case-1", run_limit=10, event_limit=100)
saved = page.snapshot.to_dict()  # 宿主保护并自行保存；不会写回 Session Store。
restored = SessionReplaySnapshot.from_dict(saved)
if page.next_run_offset is not None:
    page = await reader.page("case-1", snapshot=restored, run_offset=page.next_run_offset)
```

快照包含 `session_id`、投影配置身份、按登记顺序排列的 `run_ids` 和已读取的 `SessionRunView`。每个 view 分开保存 Session `messages`、Run 累积 `replay` 与最近一次读取的 `has_more`。Session 保存的最终助手文本与 Run 的模型块不是两次生成，展示端应选择视图而不是直接重复拼接。Token/费用保持每 Run 的累积值，不重复求和或从内容推断。

默认 `TextSessionMessageProjector()` 仅显示角色与字符数；默认 `TranscriptRunEventReducer()` 隐藏模型文本、工具参数/结果和媒体 URL/正文。标题、metadata、Run 输出摘要不复制到展示快照。显式开启 Session 文本与 Run 内容是不同决策：

```python
reader = SessionEventReplay(
    session_store, RunEventReplay(run_store),
    message_projector=TextSessionMessageProjector(include_text=True),
    reducer=TranscriptRunEventReducer(
        include_text=True, include_tools=True,
        include_tool_results=True, media_mode="content",
    ),
)
```

宿主先授权读取原始存储，再选择披露。自定义消息投影器提供 `identity` 和 `project(message)`，返回有限 JSON 对象或 `None`；身份必须随配置/输出结构变化。自定义 Run reducer 可以支持新的块类型。这些是可信 Python，不是隔离环境，不应产生副作用。引用只作为数据返回，不请求 URL、不读取媒体文件。

### 分页、刷新与一致性

- `run_offset` / `run_limit` 选择 Session 成员切片；每个选中 Run 只消费一页、最多 `event_limit` 条事件。事件位置由各自 Run 快照持有。
- `next_run_offset=None` 仅表示这轮成员扫描结束，不等于 Run 完成或所有日志已读完。`pending_run_ids` 是未访问或最近观测到仍有尾部的 Run。可定位这些 Run 再读；要发现旧 Run 审批恢复后的追加事件，应保留快照，从 `run_offset=0` 开始新一轮扫描。
- 新 Run 只能追加到旧成员列表之后；删除或重排会拒绝旧快照，需明确重建。孤立消息、重复 Run ID、混入其他 Session 的事件会失败关闭。默认要求每个事件的 `session_id` 精确匹配；兼容旧日志可显式 `allow_unscoped_events=True`，只接受缺失标识，绝不接受另一个非空标识。
- 读取前后复核完整 Session 记录以及投影身份，变化时拒绝本页；任何源/投影失败不返回部分推进，不修改输入快照，异常正文不暴露。归档 Session 允许只读展示，不取消归档。
- 默认最多 1024 个 Run、每 Run 4096 条 Session 消息、每页 32 个 Run/每 Run 1000 个事件、每 Run 快照 8 MiB、完整快照 32 MiB。消息投影器默认每条最多 100 万字符；超限拒绝，不静默截断。现有 `SessionStore.get()` 仍读取完整记录，这不是底层存储 I/O 或可信自定义代码内存的硬隔离保证。
- 快照深度冻结，`to_dict()` 返回独立 JSON 数据，envelope 为 schema 1。跨配置/Session 快照被拒绝；它仍是可信缓存，不证明历史日志未变，也不绑定具体 Store 身份。宿主必须固定数据源并保护缓存；复核不是跨 Store 事务或执行锁。

### 未实现的边界

只覆盖 Session 中已登记的 Run。当前 `SessionManager` 在一次运行返回结果后登记摘要；首次仍运行中、尚未登记的 Run 不会自动出现在此读视图。默认 Session 只持久化输入文本；可选 schema 2 输入记录见上文，默认消息投影仍只处理文本；显式替换为 RecordedSessionMessageProjector 可展示记录的输入块，仍不能补齐缺失媒体。输入块与 Run 输出块分开。CLI 已提供 `wagent session view`，支持独立内容确认、绑定来源的受信 JSON 缓存和成员/事件分页，见[累积视图 CLI](./event-replay.md)。[TUI Replay](./tui.md) 已提供内存快照与显式内容确认。具体外部检索后端与模型摘要的 CLI/TUI 自动接线仍待实现；消息字段 CLI/TUI 保存/发送已作为 a8 Experimental 增量接入；本地检索/抽取式摘要模板见前述 a8 Experimental 增量。TUI Run 历史选择已接入；a7 针对性回归通过。

## 原有数据边界

- 归档 Session 为只读，取消归档后才可启动或恢复 Run。
- 当前对话投影只保存文本块与最终 Agent 输出；工具参数、工具结果、多模态内容和任意内部事件不自动跨 Run 注入。
- JSON Store 保存的内容可能包含用户文本和模型输出，不加密；目录访问控制属于本地应用。
- 元数据必须是有限 JSON 值，并在记录中递归冻结。
- Store 使用安全 Session ID 和原子文件替换，但不是分布式或多主数据库。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
