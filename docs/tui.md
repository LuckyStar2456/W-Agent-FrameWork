# CLI 与 TUI

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./tui.en.md) | 简体中文

未发布 M4 新增 `wagent application run` 与 TUI 的 Application 页，用同一个 `ApplicationProject` 执行自定义 Harness。默认 Run/Resume/Evaluation 和普通 Workflow 恢复也已接入公开容器 Host。项目导入与执行必须明确授权非隔离 Python 代码；用法与 572 项阶段验收见[统一装配](./default-assembly.md)。

现提供 [Run/Session 用量持久关联](./service-usage-links.md)、[结构与重叠分块](./knowledge-splitting.md)、[原始归档 CLI](./knowledge-archive-entries.md)。关联在准备前写入，分块默认保持 v1，导出只创建新文件；均为Experimental（随 2.0.0 发布）。验证与剩余模块见[本轮记录](./acceptance-2026-10-01-links-splitting-archives.md)。

Run、审批恢复、Evaluation、Provider probe 四区均有 Usage host，使用一次性 `LOAD USAGE` / `RECORD USAGE` 独立确认。默认不加载、不记录；汇总失败不会重试模型。

现提供 [Knowledge sync 页](./knowledge-sync-tui.md)：默认 UTF-8 / 显式四格式导入预览、摘要锁定保存、差异计划准备、检查与独立批准执行，复用 CLI 管理服务。此前入口验收见[上一轮记录](./acceptance-2026-10-01-sync-usage.md)，四格式及用量接线见[本轮记录](./acceptance-2026-10-01-http-archives-runtime.md)；未人工验收真实服务场景。

后续工作区增量：[Replay 媒体预览与导出](./tui-media.md)、[Plugins 显式替换](./plugin-replacement.md)、[Evaluation 逐用例知识检索](./knowledge-workflow-evaluation.md)。均有本地/headless 定向验收，详见[后续记录](./acceptance-2026-10-01-followup.md)，不代表人工终端或生产场景验收。

[完整构建清单](./knowledge-builds.md) 已接创建/查看/单批执行 CLI 和独立 `Knowledge builds` TUI 页。执行分别批准构建/工件摘要及宿主代码、读取、远端写入和日志记录；不会自动执行全部批次。工作区本地回归通过、已随 2.0.0 发布，不属于 a9。

现提供[计划目录与覆盖查看](./knowledge-plan-catalog.md)：Index plans 页的 List plans and coverage 配合 `READ PLAN`，可按清单过滤；`SHOW TARGET` 另行披露目标/点 ID。同页新增 Suggest missing batches，以 `READ BATCH INPUTS` 读取精确快照与计划、按可调上限生成建议；`SHOW BATCH IDS` 单独披露文档/点 ID，不调用宿主或自动准备。界面未验收。

工作区 [Index plans 页与 CLI](./knowledge-plan-actions.md) 现包含查看、准备并保存、执行已审查计划三个动作。代码/读取/Embedding/保存/建库/覆盖写入/回执记录分别确认，审批摘要独立输入，不自动从预览批准或执行。本地回归通过，已随 2.0.0 发布，不属于 a9。

另有 [Index journal 页与 CLI](./knowledge-index-management.md)：查看精确清单日志并保存宿主已审查的对账决定，读取/写入/无迟到效果/详情展示分别确认，不探测或重发远端。本地回归通过，已随 2.0.0 发布，不属于 a9。

现提供 [Knowledge 管理页及 CLI](./knowledge-management.md)：本地导入预览/显式保存、版本目录、固定版本关键词检索，读取/写入/建库/正文展示独立确认。本地回归通过、已随 2.0.0 发布，不属于 a9。

另有 [Run 知识上下文入口](./knowledge-runtime.md)：Knowledge host、显式查询及逐次 `LOAD KNOWLEDGE` / `QUERY KNOWLEDGE` 确认；支持 history=none 仅知识模式，运行时捕获并锁定字段。与管理页独立，不自动选版或向模型发送知识；已纳入2.0.0，具名装配与本地界面回归见专题，不宣称真实服务验收。

本页 a8/a9 增量为 Experimental；a9 验证范围见 [a9 发布说明](./releases/2.0.0a9.md)。

## 共享预算入口（2.0.0a9 Experimental）

Run 与 Checkpoints 的审批恢复表单新增 `Budget host`，填写 `module:factory`；本次另外输入 `LOAD BUDGET` 才允许执行非沙箱宿主 Python。配置通过 `shared_budget.binding` 选择工厂目录中的绑定；模型执行仍需 `RUN` / `RESUME`，工具导入与权限独立确认。预算确认逐次消费，Run 入口会随本次请求捕获并锁定。

运行后独立面板显示共享池的输入/输出/缓存 Token、已用/预留金额、限额与状态计数；不显示票据 ID 或证据，不混入当前 Run 用量。读取失败显示 unavailable，不变成零、不重跑模型。工厂负责初始化/清理自己的预算资源；清理失败也可能发生在模型已执行之后，须检查账本。CLI `run` / `run-resume` 的对应参数为 `--budget-entry` 与 `--confirm-budget-code`。

工厂示例、持久池恢复和授权边界见[本地 Runtime](./local-runtime.md)。Evaluation 和 Models 配置化探测同样接入工厂，逐次要求 LOAD BUDGET 并保留 EVALUATE / ACTIVE 确认。安全探测不生成，但加载工厂仍需授权。整批评测只打开一次工厂，保存的报告格式不变。缺失绑定失败关闭；验证范围见 a9 发布说明。

## Run 媒体输入与历史策略（2.0.0a7 Experimental）

a8 还提供消息字段复选框（2.0.0a8 Experimental；针对性回归通过）：允许输入文件发送 name/metadata、分别保存名称/元数据、分别复用历史名称/元数据。全部默认关闭；保存要求同时启用字段输入和输入记录，历史字段仅用于 recorded 模式。沿用 `RUN`、`RECORD INPUTS`、`SEND HISTORY` 确认，选择在本次启动时捕获、运行中锁定；不会修改共享记录器的默认设置。Replay 展示开关不授权发送。输入文件字段也受大小与有限 JSON 校验，详见[字段运行选项](./local-runtime.md)。本增量针对性回归通过。

a8 另新增 `retrieved` / `summarized` 文本历史模板，2.0.0a8 Experimental；针对性回归通过。Run 页面提供显式检索词、近期段数、检索段数、摘要字符上限和输出字节上限；未使用的数字字段留空。两种模板另需逐次输入 `TRANSFORM HISTORY`，表明接受上下文筛选/摘要的损失性；它不授权媒体复用。五项确认在每次尝试时一并消费，新字段也包含在请求捕获、执行锁定和取消清理中。检索词不从 Prompt 自动推导，错误不回显词值；模式不适用的字段会被拒绝。详细示例和默认值见[本地 Runtime](./local-runtime.md)。现有媒体输入功能及其 a7 验证边界如下。

Run 表单支持 Prompt 或输入文件（二选一）；文件格式与 [CLI 结构化输入](./local-runtime.md) 相同，相对路径以 workspace 为基准。输入只接受用户消息的文本、图片、音频块，不隐式下载 URL。

- 每次运行输入 `RUN`；加载工具另需 `LOAD TOOLS`。
- `Record current input blocks` 默认关闭；开启后另需 `RECORD INPUTS`。
- History 为 `text`（默认）、`recorded` 或 `none`；重发已记录媒体的 `recorded` 模式另需 `SEND HISTORY`。展示、记录、发送是三种独立决策。
- a7 每次尝试消费四项确认；a8 连同变换确认共五项，包括被拒绝的尝试；全部确认通过后才读取文件、导入工具或装配 Runtime。捕获不可变参数后锁定表单，后台执行期间拒绝重复提交。
- `Request cancellation` 请求取消。取消或退出会清理 Runtime，不自动重放；已发生的模型调用或工具副作用不会撤销。文件解析线程可能完成只读工作，但取消后不会继续派发。同步用户代码仍可能阻塞界面；后台任务不是沙箱。

实时事件仅保留最近 200 条安全投影，不改变持久化日志。`record_inputs=False` 不关闭检查点或其他日志。欢迎页的大字符、颜文字和窄窗口适配保持不变。验证范围见 [a7 发布说明](./releases/2.0.0a7.md)。

## Replay 只读富内容页（2.0.0a7；针对性回归通过）

a8 另新增 `Recorded input names` / `Recorded input metadata` 两个复选框（2.0.0a8 Experimental；针对性回归通过），仅用于 Session 模式；分别默认关闭，开启任一项均需逐次 `VIEW CONTENT`。确认在读取前消费，执行期间字段锁定；修改任一开关会清空已显示内容和内存快照，正在进行的旧读取结果也会丢弃。展示字段不启用保存或向模型复用。输入媒体选择另行控制内容，新包装记录可在字段隐藏时展示块元数据。CLI/TUI 共用投影装配，字段配置变化进入快照身份；详见[输入消息字段披露](./event-replay.md)。针对性回归通过。

a7 新增第十二个 `Replay` 分区，独立于原 Checkpoints 安全事件列表，也不改变大字符/颜文字欢迎页。底层使用公开 `RunEventAccumulator` / `SessionEventReplay`，不加载开发者代码、调用模型、执行工具、批准恢复或下载媒体。

1. 填写 `run` / `session`、精确 ID、Run State Root；Session 模式另填 Session Root。相对目录以 TUI workspace 为基准，仅读取已有目录。
2. 默认只展示计数、状态与媒体元数据。模型文本、工具身份/参数、已记录工具结果、Session 文本分别勾选；媒体可选 `metadata` / `references` / `content`。任何正文或媒体引用/内容披露，每次读取均需输入 `VIEW CONTENT`，捕获请求后立即清空，不保存授权。
3. 点击 `Read next batch`。Run 每批 1–500 个事件；Session 每批 1–32 个成员、每 Run 1–500 个事件。成功后推进内存快照；Session 自动填入下一成员偏移，扫描到末尾时回到 0，下一次显式点击可刷新旧 Run 的追加事件。结束扫描或 pending 数为 0 均不代表 Agent 已完成。
4. `Previous/Next display slice` 只翻阅已授权的内存结果，每屏最多 16,000 个字符，不再读取事件。展示为结构化 JSON 文本，控制字符和非 ASCII 转义，不解释 Rich/ANSI，不渲染图片、播放音频或打开 URL。工具正文只能显示先前已记录的内容。
5. `Clear view` 丢弃快照、可见内容和确认；改变来源、ID、模式或内容开关也自动清空。失败保留原快照，不部分推进。清空期间仍未返回的读取结果会被丢弃。离开页面不会自动清空，离开前可使用 Clear。

读取在独立只读工作线程中执行，表单暂时锁定，重复点击不会并发读取。清空按钮仍可用；结束后解锁。退出丢弃投递和快照，但已进入底层读取的线程可能仍会完成；不声称取消能强制终止 I/O。清空是释放展示引用，不是敏感内存的安全擦除。

a7 的快照只保留在本次 TUI 内存，跨进程续读使用[累积视图 CLI](./event-replay.md)；a8 新增缓存操作，见下一节。单 Run / Session 快照限制为 8 / 32 MiB，转义展示另限 64 MiB；底层仍可能加载完整 Session 和扫描日志前缀，并非总 I/O/内存沙箱。`Legacy events` 只放行无 Session ID 的旧事件，不放行其他 Session 的事件。输入媒体记录已通过 [Session schema 2](./sessions.md) 加入 Python API（2.0.0a7，针对性回归通过）；Replay 已新增独立 Session input media 字段（默认 off，metadata/references/content），引用/内容需逐次 VIEW CONTENT；TUI 媒体录入和历史选择见上方 Run 表单；专用媒体播放器仍未实现。验证范围见 a7 发布说明。

### a8 缓存导入/导出（2.0.0a8 Experimental；针对性回归通过）

Replay 新增缓存路径输入和两个显式操作，不自动保存，不加载 Python，不发模型/工具请求，也不下载媒体。

1. 导入前手动选择相同 Kind、ID、Store 和披露选项，输入缓存路径、`VIEW CONTENT` 与 `TRUST CACHE`，点击 `Import + read batch`。读取现有 CLI/TUI JSON envelope，核对来源、ID、reducer/消息投影配置和大小，然后从该快照继续读取一批。不是离线查看；源 Store 必须可用。成员偏移使用表单的显式值，不从缓存 page 自动采纳；0 可重新扫描已有成员。
2. 导出前先读取快照，填写新的 `.json` 路径、`VIEW CONTENT` 与 `SAVE CACHE`，点击 `Export current snapshot`。只序列化捕获的当前快照，不再读取事件；兼容 CLI `--snapshot`。文件保留所选披露内容及绝对来源路径，须按敏感数据保护；它不是工程分享编码、执行检查点或权限凭据。
3. 导出仅允许已有父目录内的新文件，不创建目录、不覆盖已有文件，也不写入所选 Run/Session Store。完整输出上限 64 MiB。失败可能留下本次新建的部分文件，不自动重试、删除或回滚；再次导出应自行选择新路径。

每次尝试都消费内容与缓存确认，读取/导入/导出共用执行锁；失败保留原视图。清空或修改来源/披露选择会丢弃旧投递，清空不删除已保存文件。尚未开始的缓存任务会被丢弃，但已开始的线程 I/O 可能在清空或退出后完成，包括文件写入；取消不是磁盘回滚。路径检查不是抵御本地并发目录替换的沙箱。

缓存必须来自你信任的来源；来源绑定和投影身份不是签名，也不能证明缓存正文经过脱敏、历史日志未被改写或来源目录未被替换。即便当前选择 metadata-only，缓存导入仍要求 `VIEW CONTENT`，不要用此入口查看陌生人发来的缓存。ASCII JSON 转义与 Rich Text 纯文本展示沿用原方案。已添加读写、互通、拒绝条件与界面并发回归已通过。

`2.0.0a6`（针对性回归通过）新增 CLI `checkpoint workflow-approve-resume` 及 TUI “Approve exact call and resume parent”：显式提供异步工厂和完整父节点/子 Run/Agent/Call/Tool 身份，独立确认代码、审批和父流程执行；装配前后复核并清理本次授权，详见 [工厂与授权边界](./workflows.md)。

TUI 中先只读查询并另行审阅真实动作，手动填写精确身份和权限，再输入 `LOAD WORKFLOW`、`APPROVE <Call ID>`、`RESUME WORKFLOW`。表单校验通过后逐次消费确认，普通恢复与审批恢复共用后台任务锁；执行中锁定两个表单，捕获参数不受后续输入修改影响。暂停按钮、可选同步节点线程和 SQLite 监听均复用已有机制。错误只展示类型；取消/退出释放工厂资源和授权，但不清除外部持久暂停请求。不自动选择待批项，不批量批准，不宣称暂停代表工具已执行。针对性回归已通过。

`2.0.0a5`（针对性回归通过）新增 `wagent checkpoint workflow-approvals <run-id>` 及 Checkpoints 页的只读审批关联查询。可选独立 Agent State Root 和自定义 State Key；只显示父子身份、检查点状态和匹配结果，始终标记 `authorized=false`。查询不导入 Definition、不运行模型或工具，不消费加载/恢复确认。Python 宿主可显式注入 `WorkflowApprovalGrants` 进行一次性精确授权；CLI/TUI 的批准并恢复接线属于针对性回归通过的`2.0.0a6`，详见 [Workflow 文档](./workflows.md)。

状态：Typer/Rich CLI、可启动 Textual TUI、本地 Session 生命周期、配置化 Agent 运行入口、Token/费用可见性、Agent Checkpoint 脱敏列表、CLI/TUI 工具选择/权限/审批恢复、脱敏实时 RunEvent 和本地评测在 `2.0.0a3` 为 `Experimental`。`2.0.0a4` 另外实现调用前费用包络的安全事件投影、按 Agent 跨 Session 用量/费用汇总、Workflow Checkpoint 引导恢复与通用插件确认生命周期；宿主锁目录驱动的 Sandbox 包安装与独立加载确认已包含于 `2.0.0a4`。在线来源发现、自动锁定和自动升级仍为 `Planned`。

`2.0.0a4`的 TUI 首页新增六行大字符 `W-AGENT` 欢迎图案、颜文字和版本信息；全部由终端字符绘制，不加载图片、字体或网络资源。窗口宽度不足时使用紧凑标题，调整窗口大小后自动重新排版。图案只占用 Home 页，不挤占其他操作页。

Workflow 恢复在`2.0.0a4`改为 Textual 管理的后台任务。Checkpoints 页新增 “Pause active workflow at next boundary”，只作用于当前 TUI 恢复中的 Workflow；运行时锁定 State Root、Run ID、入口和执行选项，重复恢复不会启动第二个任务。请求后显示等待状态，只有引擎返回 `paused` 才表示已保存暂停点。暂停后的再次恢复仍需重新输入代码加载与执行确认。同步节点线程选项默认关闭；启用时采用 `ThreadedWorkflowNodeInvoker`，否则同步阻塞代码仍可能占住界面。Python 导入仍在原线程执行。退出界面会取消后台任务，不等同于已完成边界暂停；不确定执行仍需检查 Checkpoint。`2.0.0a5`另提供 SQLite 跨进程请求源和 CLI 显式监听（`2.0.0a5`，针对性回归通过），本 TUI 新增默认关闭的 SQLite 监听复选框，同时保留进程内暂停按钮。恢复开始时固定监听选项与 Run/Root，结束时只清理本界面临时请求，不清理外部持久化请求。详见 [Workflow 请求源组合](./workflows.md)。

## 原则

- CLI、TUI 和 Python API 使用同一个 Application 与 Registry。
- TUI 不依赖 W-Agent 托管服务或后台云控制面。
- 界面不拥有框架专用能力；所有操作可以通过公开 Python API 完成。
- 可能安装代码、产生模型费用或访问宿主机的操作必须确认。

## 当前 CLI

```text
wagent init
wagent profile list
wagent probe <endpoint>
wagent doctor
wagent plugin inspect --config <plugins.yml> [--json]
wagent plugin validate-load --config <plugins.yml> --confirm-plugin-code [--json]
wagent plugin validate-installed <installed-path> --confirm-plugin-code [--json]
wagent composition export|inspect|save|list
wagent composition plan <code> [--inventory <plugins.json>] [--json]
wagent composition install-plan <code> --catalog <install-lock.json> [--json]
wagent composition install <code> <request-digest> --catalog <install-lock.json> --confirm-network --confirm-package-code [--json]
wagent session create|list|show|usage|archive|unarchive
wagent checkpoint list [--session <id>]
wagent checkpoint workflow-list [--state-root <path>]
wagent checkpoint workflow-resume <run-id> --workflow-entry <module:attribute> --confirm-workflow-code --confirm-resume
wagent provider-probe --mode safe|active|capability [--confirm-active-probe]
wagent run <prompt> --confirm-model-call
wagent run-events <run-id> [--after-sequence <n>] [--limit <n>] [--json]
wagent run-resume <session-id> <run-id> --approve-tool-call <call-id> --confirm-model-call
wagent evaluate <cases.json> --confirm-model-call [--report <report.json>]
wagent tui
```

以上命令的源码入口已存在；锁定安装与 `run-events` 已包含于 `2.0.0a4`。CLI 默认输出适合人阅读的文本；模板、初始化、探测、装配检查、列表、Session 生命周期和评测提供结构化 JSON。`run-events` 只读指定 Run 的持久化事件，按序号游标分页，默认投影严格白名单状态/计数/费用，不显示模型正文、工具参数/结果、媒体 URL 或内联正文，不执行模型与工具；原始事件只可由应用通过 Python API 在自行授权后读取。`session show` 与 `evaluate` 展示输入、输出与缓存输入 Token，以及可用时的版本化费用，并明确标记计量是否完整。`session usage` 按 Agent 汇总多个 Session 的计量，不输出 Prompt、消息、模型输出或工具结果；归档数据必须显式选择。评测默认使用一次性状态，报告默认不含 Prompt 与输出。失败返回稳定非零退出码。`probe` 执行不带凭据和请求体的 L1 探测；`provider-probe` 从严格配置装配 Provider，主动模式必须额外传入 `--confirm-active-probe`。

兼容期继续保留 `w-agent` 命令名以及基础 `config`、`bean` 子命令；规范入口为 `wagent`。

`run` 使用严格的 `.wagent/config.json` 与环境变量凭据引用；每次都必须显式传入 `--confirm-model-call`。可选版本化价格配置为 CLI/TUI Run、Session、Checkpoint 和评测提供费用与完整性。配置可从显式 Catalog 选择工具；CLI 仅在 `--tool-entry` 与独立的 `--confirm-tool-code` 同时出现时导入开发者 Python 工具，并通过 `--grant-permission` 授予本次权限。TUI 使用独立的 `RUN`、`LOAD TOOLS`、权限输入和 `RESUME` 确认，且精确绑定 Session/Run/Call ID；确认立即清空。Workflow 恢复同样要求独立的代码加载与执行确认，并按 Checkpoint 的名称、版本和类型选择 Definition。RunEvent 面板只展示白名单事件类型、状态、Token 和费用字段，不显示任意错误正文、工具/模型正文或媒体内容。TUI Models 页也提供配置化安全/主动 Provider 探测，主动生成必须输入 `ACTIVE` 且确认不会持久化。

`plugin inspect` 只解析引用、启用状态和配置键，不导入代码。`plugin validate-load` 必须传入 `--confirm-plugin-code`，在临时 `PluginManager` 中事务化加载，输出不含配置值的 active 快照，并在进程退出前卸载。`composition install-plan` 读取显式锁目录并离线输出请求摘要及 Index 来源（协议/主机/端口，不含完整路径或凭据）；`composition install` 绑定精确摘要，另需确认网络与包代码执行，默认使用 Docker，`--backend unsafe-local --confirm-unsafe-local` 才允许不隔离本地开发。`plugin validate-installed` 在安装树复验后执行第二次加载确认，并在插件 setup 前核对入口模块来源及名称/版本。TUI Plugins 页用持久的进程内 Manager；YAML 加载需 `LOAD PLUGINS`，已安装站点加载需 `LOAD INSTALLED`，卸载需精确 `UNLOAD <name>`。`config validate`、在线来源发现、自动锁定和自动升级仍为 `Planned`。

TUI Evaluation 页要求输入 `EVALUATE` 才顺序运行严格 JSON 用例集；默认一次性状态，确认立即清空，只显示 Token/费用/延迟/工具结果和通过状态，并可写默认脱敏报告。自定义 Scorer、输出持久化和开发者工具入口使用 Python API/CLI。

## TUI 技术

TUI 使用 Textual，通过 `wagent-framework[tui]` 可选依赖安装。基础 CLI 使用 Typer/Rich。TUI 采用进程内模式启动框架，不要求常驻守护进程；远程连接能力为 `Reserved`。a7 含十二个分区（Replay 2.0.0a7，针对性回归通过）、真实的 Session 创建/列表/归档/恢复、离线装配检查、安全端点探测、模板信息和 Docker 可用性检查；尚未实现的分区会明确显示 Planned，而不伪装可操作。

下一代 CLI 的规范命令为 `wagent`；现有 `w-agent` 在兼容期作为别名保留。

## 首版页面

### Home

显示当前 Workspace、Python/W-Agent 版本、活动 Profile、插件错误和最近 Run。

### Models

管理 Provider 配置引用、模型目录和探测结果。主动探测前展示潜在费用和将发送的最小测试类型。

### Plugins

`2.0.0a4` 可从本地 YAML 显示 `module:attribute` 来源、启用状态和配置键，且预览不导入模块。经 `LOAD PLUGINS` 确认后，页面显示名称、版本、API 兼容性、提供能力、依赖和生命周期状态；配置值、插件异常正文和 Metadata 不进入投影。锁定安装完成后，用户必须在此页选择安装目录并输入 `LOAD INSTALLED`，才会复验内容树并加载入口。用户可用名称绑定确认卸载插件及其活跃依赖者；安装站点的进程导入路径租约随批次卸载释放。首版不在线发现来源或自动更新。

### Composition

查看解析后的 Profile，比较两个命名版本，导出编码，导入时预览依赖、配置差异和安全风险。`2.0.0a4` 可用显式 JSON 候选清单生成完全离线的环境/插件依赖计划，并用宿主锁目录生成完全离线的安装请求。未提供候选清单时只参考当前 TUI 活跃插件的名称和版本。计划不查询网络、不导入代码、不安装包，也不代替后续确认。安装要求精确 `INSTALL <digest>`；不隔离本地模式要求不同的 `INSTALL LOCAL <digest>`，避免把 Docker 确认误用于宿主执行。安装结果明确显示“未加载”，并转交 Plugins 页完成第二次确认。

### Run

当前可读取严格本地配置并启动文本 Agent，显示最终输出、输入/输出 Token 与版本化费用；用户必须输入 `RUN` 才会发起模型调用。显式启用费用预估时，事件面板显示估算器、路由/尝试计数、费用包络和预计累计费用，不显示 Prompt。工具入口仅在另行输入 `LOAD TOOLS` 后导入，权限仅对本次运行有效。界面通过公开 `RunEventCallback` 实时投影已持久化事件，不读取 Loop 私有状态，也不显示 Prompt、模型文本或工具参数。

### Sessions

使用与 Python API 相同的 `JsonSessionStore` 创建、列出、归档和恢复本地 Session。详情显示每个 Session 的 Run 数、累计 Token 和同版本/币种时的累计费用，并显示不含 Prompt/输出的跨 Session Agent 汇总；配置化 Agent 启动属于 Run 页面。

### Checkpoints

当前可刷新本地 Agent 审批 Checkpoint 的脱敏摘要，显示 Run/Session、状态、工具名、Call ID、参数名、Token 和费用，不显示 Prompt、参数值或输出。`2.0.0a4`还增加按 Run ID 和序号只读查看下一页持久化 RunEvent；界面直接请求 `RunEventReplay.projected_page()` 的安全默认投影，不先接收原始事件页，并把下一游标写回输入框。这不恢复执行。用户重新提供配置、工具入口、权限和精确 Call ID，并输入 `LOAD TOOLS`/`RESUME` 后才可恢复执行；授权不从 Checkpoint 继承。

`2.0.0a4` 还能从用户指定的本地 State Root 刷新 Workflow Checkpoint 摘要，显示 Workflow 名称/版本/类型、状态、节点标识与计数，不显示 Input、State、Output、Scope 或 Metadata 值。恢复要求用户提供 `module:attribute` Definition 入口并分别输入 `LOAD WORKFLOW` 与 `RESUME WORKFLOW`；加载结果必须与 Checkpoint 的名称、版本和类型完全一致。完成结果和事件也使用脱敏投影。界面不会自动复制或迁移 Store，`RESUMING` 不确定状态不会被强制重放。

### Approval chains（`2.0.0a6`，针对性回归通过）

独立页面用于 `父 Agent → Workflow 工具 → 子 Agent → 待批工具`，复用公开双层审批服务，不替代 Checkpoints 页的单层恢复。

1. 填写父 Agent State Root、最外层 Run ID，以及可选的独立 Workflow/子 Agent Root、自定义审批 State Key。三个 Store 目录须已存在。
2. 点击 **Review chain**。后台只读查询显示从 1 开始的行号和完整调用关联、暂停事件序号；隐藏 Scope、输入、参数和模型输出，不选择任何待批项。
3. 手动填写行号并点击 **Select reviewed row**。仅可选匹配的待批项；查询输入变更后必须重新查询，行号变更后必须重新选择。每次查询/选行均清除旧确认。
4. 另行审阅真实工具动作，填写异步父 Loop 工厂 `module:attribute` 与独立父/子权限（逗号分隔，默认空）。该工厂遵循 `WorkflowToolApprovalFactory`，不是返回 WorkflowDefinition 的单层工厂。
5. 输入四项精确确认：`LOAD AGENT`、`APPROVE PARENT <父 Call ID>`、`APPROVE CHILD <子 Call ID>`、`RESUME AGENT <父 Run ID>`，再点击恢复。

恢复开始即捕获请求、清空确认和选中快照；执行期间锁定链路表单和其他恢复按钮。查询/恢复与现有 Workflow 恢复共享后台任务互斥，重复点击不会启动第二个任务。停止、失败或取消后均需重新查询，不自动填入或批准下一调用。结果仅显示状态、待批标识、计数与 Token/费用；不根据停止状态推断子工具已执行。

退出界面会取消并等待任务清理；协调服务负责清除临时授权，工厂负责关闭资源，不进行自动重放。取消不代表副作用未发生，应检查不确定检查点。后台任务不隔离 Python：同步工厂导入或节点仍可能阻塞界面，线程/暂停/并发策略由宿主工厂显式装配。Checkpoints 页的暂停按钮不控制此链路，框架不替此操作清除外部持久暂停请求。

配套 CLI 为 `checkpoint workflow-tool-approvals` 和 `workflow-tool-approve-resume`，详见 [双层审批操作](./workflows.md)。以上 UI 已在 a6 针对性回归中通过，仍为 Experimental。

### Sandbox

显示 Docker/OCI 可用性、镜像、挂载、网络和资源限制。启用 `UnsafeLocalSandbox` 时显示持续风险标识，并要求明确确认。

### Evaluation

运行本地客服和编码基准，比较模型或装配版本的成功率、延迟、Token、估算费用和工具错误。

## 安全交互

以下操作不能由模型或导入配置替用户确认：

- 安装或升级插件。
- 首次运行未知第三方插件。
- 导入并执行开发者 Python 工具入口。
- 启用 `UnsafeLocalSandbox`。
- 放宽 Docker 挂载或网络策略。
- 执行可能产生模型费用的主动能力探测。

确认记录绑定具体操作、版本和配置摘要，配置改变后不能复用旧确认。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
