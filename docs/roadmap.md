# 路线图与能力状态

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./roadmap.en.md) | 简体中文

> 版本说明：本页新框架核心纳入 2.1.0。下方“未发布”与候选 2.0.0 元数据属于发布前阶段记录，不代表 2.1.0 包状态。参见[2.1.0 发布说明](./releases/2.1.0.md)；上传状态以 [PyPI](https://pypi.org/project/wagent-framework/2.1.0/) 为准。

本文是 W-Agent 能力状态的唯一总览。路线图表达实现顺序，不承诺发布日期。

[Harness 核心基线 M0–M5](./harness-core.md)已按固定范围验收：Spring 式 IoC/DI/AOP、注解、生命周期与可替换公开执行已贯通。M5 通过 259 项相关测试、离线候选制品构建/安装和三示例仓库外 Python/CLI/无显示 TUI 验收，见[最终记录](./harness-acceptance.md)。当前核心阶段无必做剩余项；源码未发布，版本与发布另行决定。下方保留/暂缓功能不自动成为新的完成门槛。

发布策略已调整：不再新增 alpha；按[正式版基础清单 B01–B12](./stable-release-baseline.md)闭环并验收后发布正式版，再优化增强项。下表的 Planned/Reserved 不全部构成基础版阻塞。

当前状态：2.0.0 正式版已发布，基本门禁、制品检查、隔离安装、实际包 CLI/TUI 与真实 Docker 通过，远端摘要一致，见[发布验收](./acceptance-2026-10-01-stable-release.md)。以下 a4–a9 和各批计数保留为历史来源，后续推进增强项，不再新增 alpha。

本轮补 Run/Session 用量持久关联与只读查询、结构/重叠分块以及原始归档 CLI；验收与剩余模块见[本轮记录](./acceptance-2026-10-01-links-splitting-archives.md)。均为Experimental（随 2.0.0 发布）。此前 MCP HTTP、四格式与 Runtime 接线的 375 项仅覆盖[上一轮代码](./acceptance-2026-10-01-http-archives-runtime.md)，不代表完整框架或真实服务已验收。

2026-10-01 切换为模块子代理并行实现与主代理统一验收，详见[本轮验收记录](./acceptance-2026-10-01.md)。工作区新能力不属于已发布 a9；本地回归与真实厂商/沙箱验收分别记录。

第一批之后继续补知识同步、知识评测入口、插件替换入口和媒体展示；后续代码只引用[单独授权的定向验收](./acceptance-2026-10-01-followup.md)，不沿用此前全量通过数。

## 1.x 兼容底座（1.5.2）

| 能力 | 状态 | 说明 |
|---|---|---|
| `BaseAgent.arun()` | `Implemented` | 最小异步 Agent 抽象 |
| IOC、组件扫描和生命周期 | `Implemented` | 现有 1.x 工程底座 |
| AOP、重试、断路器、超时、舱壁 | `Implemented` | 通用弹性能力 |
| 动态配置和事件总线 | `Implemented` | 尚不是下一代插件内核 |
| 日志、指标、追踪、健康检查 | `Implemented` | 可选后端依赖 |
| Wasm 与 nsjail 技能沙箱 | `Implemented` | 1.x 接口保留；新版 nsjail 与 ProviderSkillSandbox 桥为2.0.0 Experimental，Wasm 通用硬资源接口尚未实现 |
| LangChain 适配和 FastAPI 示例 | `Implemented` | 1.x 集成 |

## 首版计划

| 能力 | 状态 | 阶段 |
|---|---|---|
| Phase 1 微内核公共协议 | `Implemented` | 2.0.0a1 |
| 统一注册表与插件生命周期 | `Implemented` | 2.0.0a1 |
| 依赖解析、可撤销注册、作用域与事件管线 | `Implemented` | 2.0.0a1 |
| 统一模型协议与流事件 | `Implemented` | Phase 2A / 2.0.0a1 |
| OpenAI-compatible Chat Completions 适配 | `Implemented` | Phase 2B / 2.0.0a1 |
| 通用 HTTP 映射层与 SSE/NDJSON 传输 | `Implemented` | Phase 2B / 2.0.0a1 |
| Anthropic、Gemini、Ollama、Qwen 原生模板 | `Implemented` | Phase 2B / 2.0.0a1 |
| Gemini 图像/音频输出 Part 映射与可替换 Mapper | `Experimental`（`2.0.0a4`） | Phase 2B/3 |
| Responses 图片生成工具与最终 PNG/JPEG/WebP 输出 | `Experimental`（离线映射回归通过，未在线验收） | Phase 2B/3 |
| 其余内置厂商多模态输出、音频/Reasoning 增量与图片预览映射 | `Planned` | Phase 2B/3 |
| DeepSeek、GLM、Qwen-compatible、Turbo 模板注册表 | `Implemented` | Phase 2B / 2.0.0a1 |
| 专用 OpenAI Responses 与 vLLM 差异适配 | `Implemented` | Phase 2B / `2.0.0a4` |
| Python/YAML 模型路由 | `Implemented` | Phase 2A / 2.0.0a1 |
| 手动探测 API、缓存与周期调度 | `Implemented` | Phase 2A / 2.0.0a1 |
| 显式注册服务的自动安全探测与健康桥接 | `Implemented` | Phase 2B / 2.0.0a1 |
| CLI/TUI 安全端点探测入口 | `Implemented` | Phase 2B / 2.0.0a1 |
| CLI/TUI 配置化 Provider 安全/主动探测 | `Experimental` | Phase 2B/6 / 2.0.0a1 |
| 收集式调用、超时、重试与故障转移执行器 | `Implemented` | Phase 2B / 2.0.0a1 |
| 安全逐事件透传执行器 | `Implemented` | Phase 2B / 2.0.0a1 |
| Provider 输入/输出 Token 规范化计量 | `Implemented` | Phase 2B / 2.0.0a1 |
| 显式验证前缀的文本跨流恢复 | `Experimental` | Phase 2B / `2.0.0a4` |
| Provider 原生游标续传协议与执行器接线 | `Experimental`（`2.0.0a4`） | Phase 2B |
| Responses 后台生成原生续流、可替换检查点协议与 SQLite 跨进程游标恢复 | `Experimental`（Python API 离线回归通过，未在线验收） | Phase 2B/6 |
| 其他厂商原生游标、CLI/TUI 配置与完整 Agent 会话/计量恢复 | `Planned` | Phase 2B/6 |
| 单 Agent ReAct/tool loop 模板 | `Implemented` | Phase 3 / 2.0.0a1 |
| 进程内 RunEvent 流与有界预算 | `Implemented` | Phase 3 / 2.0.0a1 |
| Run 级 Token 可见计量与硬预算 | `Implemented` | Phase 3 / 2.0.0a1 |
| Session 累计与逐尝试 Token 账本 | `Implemented` | Phase 3/6 / 2.0.0a1 |
| Agent 显式可选文本增量 RunEvent | `Experimental`（`2.0.0a4`） | Phase 3/6 |
| 版本化价格表、费用计量与 Run 费用硬预算 | `Implemented` | Phase 3/6 / 2.0.0a2 |
| 可插拔调用前 Token 预估器与软阈值事件 | `Experimental`（`2.0.0a4`） | Phase 3/6 |
| Agent 跨 Session 用量/费用汇总 | `Experimental`（`2.0.0a4`） | Phase 3/6 |
| 可替换调用前费用预估与重放包络 | `Experimental`（`2.0.0a4`） | Phase 3/6 |
| 本地 JSONL RunEvent 与审批断点恢复 | `Implemented` | Phase 3 / 2.0.0a1 |
| 已持久化 RunEvent 的只读游标分页 | `Experimental`（`2.0.0a4`） | Phase 3/6 |
| 可替换 JSON RunEvent 脱敏投影与投影分页 | `Experimental`（`2.0.0a4`） | Phase 3/6 |
| 可替换事件 reducer、只读累积快照与文本/工具/媒体展示重建 | `Experimental`（`2.0.0a6`；针对性回归通过） | Phase 3/6 |
| 工具结果正文可选事件记录、可替换编码器与累积器独立披露 | `Experimental`（2.0.0a7；针对性回归通过） | Phase 3/6 |
| Session 跨 Run 富内容只读投影、独立披露和版本化快照 | `Experimental`（2.0.0a7；针对性回归通过） | Phase 3/6 |
| Run/Session 累积视图 CLI、显式敏感披露与绑定来源的缓存续读 | `Experimental`（2.0.0a7；针对性回归通过） | Phase 3/6 |
| Run/Session TUI Replay 内存快照、独立内容确认与分屏展示 | `Experimental`（2.0.0a7；针对性回归通过） | Phase 3/6 |
| 可替换 Session 输入记录器、有序文本/图片/音频持久化、schema 2 | `Experimental`（2.0.0a7；针对性回归通过） | Phase 3/6 |
| 标准输入解码器、可替换文本/记录媒体历史策略、独立输入块投影及 CLI/TUI 披露 | `Experimental`（2.0.0a7；针对性回归通过） | Phase 3/6 |
| Runtime 类型化消息运行、严格输入清单、CLI 媒体录入与独立记录/历史确认 | `Experimental`（2.0.0a7；针对性回归通过） | Phase 3/6 |
| TUI 媒体运行录入、独立记录/历史确认、后台任务与取消 | `Experimental`（`2.0.0a7`；针对性回归通过） | Phase 3/6 |
| 可替换本地关键词检索/抽取式摘要策略、近期消息段保留与文本大小限制 | `Experimental`（2.0.0a8；针对性回归通过） | Phase 3/6 |
| 内置上下文模板 CLI/TUI 接线、共享不可变选项与独立变换确认 | `Experimental`（2.0.0a8；针对性回归通过） | Phase 3/6 |
| 异步历史协议、受信检索/摘要回调模板、Runtime 等待/取消与准备后 Session 变化检测 | `Experimental`（2.0.0a8；针对性回归通过） | Phase 3/6 |
| Agent-backed 模型摘要、独立 Run 预算与无正文计量观察器 | `Experimental`（2.0.0a8；针对性回归通过） | Phase 3/6 |
| 摘要报告幂等观察器、显式主 Run 累计用量归集、完整性与分组费用 | `Experimental`（2.0.0a8；针对性回归通过） | Phase 3/6 |
| SQLite 摘要报告观察器、显式初始化、事务内幂等/容量检查与重开读取 | `Experimental`（2.0.0a9；验证范围见发布说明） | Phase 3/6 |
| 进程内共享 Token/费用预留协议、原子入场、实耗结算与 Provider 包装器 | `Experimental`（2.0.0a9；验证范围见发布说明） | Phase 3/6 |
| SQLite 共享预算、显式配置绑定、事务入场/结算、持久票据与重开读取 | `Experimental`（2.0.0a9；验证范围见发布说明） | Phase 3/6 |
| 共享预算可选显式对账协议、宿主无活跃调用确认、状态匹配与内存/SQLite 不可覆盖回执 | `Experimental`（2.0.0a9；验证范围见发布说明） | Phase 3/6 |
| Runtime/Provider 共享预算具名绑定、JSON 引用宿主目录、显式池快照与原客户端关闭职责 | `Experimental`（2.0.0a9；验证范围见发布说明） | Phase 3/6 |
| CLI run/run-resume/evaluate/provider-probe 与 TUI 运行/审批恢复/评测/探测预算工厂、独立代码确认、生命周期清理与池级用量展示 | `Experimental`（2.0.0a9；验证范围见发布说明） | Phase 3/6 |
| 评测/探测入口的共享预算工厂接线、整批共池与独立池展示 | `Experimental`（2.0.0a9；验证范围见发布说明） | Phase 3/6 |
| 可替换 Embedding/稠密向量协议、只读 Qdrant 查询模板与本地候选历史选择 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| 通用 HTTP 单文本 Embedding、可替换 JSON 映射、OpenAI 兼容/Ollama 原生模板、固定维度检查和结构化服务用量 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| Embedding 显式共享预算包装、宿主上界/计价、入场预留、已知用量结算、未知用量占额及内存/SQLite 同池接线 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| 显式历史向量准备、独立正文嵌入确认、精确计划绑定的 Qdrant upsert、已接收/已应用和未知结果区分 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| 文档存储/知识检索协议、内存与关键词模板、向量 ID 正文解析、带来源的 USER 数据上下文策略 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| knowledge_search 普通工具绑定、权限/外部调用审批、查询与 JSON 限额、本地示例工厂及既有具名 Runtime/CLI/TUI 工具入口复用 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| 宿主纯文本准备、可替换 UTF-8 分块、确定性块 ID、不可变快照与 SQLite 具名版本、显式建库/写入和固定版本检索 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| 快照/Embedding 标签/维度绑定的向量点 ID、显式正文嵌入批次、既有 Writer 接线与原文档身份恢复的固定候选检索 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| 显式本地文本文件/目录导入、可替换解析器、UTF-8 模板、限额与链接拒绝、原始/解析摘要来源清单和快照接线 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| knowledge.binding 具名目录、Runtime 逐次查询/仅知识上下文、CLI/TUI run 独立代码/查询确认及宿主工厂生命周期 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| 本地知识管理 API/CLI/TUI、导入预览/显式保存、独立建库/读写/正文确认、只读版本目录与固定版本关键词浏览 | `Experimental`（本地/模拟回归通过、已随 2.0.0 发布，不属于 a9） | Phase 3/6 |
| 索引日志管理 API/CLI/TUI、本地原始/有效状态查看、敏感详情确认、精确身份绑定的宿主证据对账 | `Experimental`（本地/模拟回归通过、已随 2.0.0 发布，不属于 a9） | Phase 3/6 |
| 精确向量计划工件/严格编解码、可替换暂存协议/独立 SQLite、准备与审批后执行 API、CLI/TUI 只读计划查看（执行不重嵌入） | `Experimental`（本地/模拟回归通过、已随 2.0.0 发布，不属于 a9） | Phase 3/6 |
| 知识计划具名宿主工厂、准备保存/授权执行管理 API 与 CLI/TUI、独立代码/读取/嵌入/保存/覆盖写入/日志确认 | `Experimental`（本地/模拟回归通过、已随 2.0.0 发布，不属于 a9） | Phase 3/6 |
| 可选计划目录协议、完整工件校验/一致读取、准备覆盖与重叠分析、CLI/TUI 目录、缺失批次纯规划及 API/CLI/TUI 可调限额建议 | `Experimental`（本地/模拟回归通过、已随 2.0.0 发布，不属于 a9） | Phase 3/6 |
| 已准备完整集合的不可变具名构建、严格编解码/独立 SQLite、创建查看与单批执行 API/CLI/TUI、宿主生命周期/双摘要独立批准、稳定批次尝试 ID/日志恢复分析（不自动重发） | `Experimental`（本地/模拟回归通过、已随 2.0.0 发布，不属于 a9） | Phase 3/6 |
| 可选 PDF/DOCX/XLSX/PPTX 解析、增量解析复用/差异、解析原文与字符/UTF-8 块偏移、CLI/TUI 预览摘要锁定提交 | `Experimental`（真实四种格式样例和本地回归通过，已随 2.0.0 发布） | Phase 3/6 |
| BM25、RRF 混合检索、可替换重排、Workflow 知识节点/证据消息、逐用例隔离知识评测 | `Experimental`（离线端到端回归通过，真实质量未验收） | Phase 3/6 |
| 构建/回执目录 API/CLI/TUI、同日志库原子冲突协调、明确前序身份重试、准备 ready 检查点免重算恢复 | `Experimental`（本地回归通过，已随 2.0.0 发布；不是跨库租约） | Phase 3/6 |
| 显式 SQLite 导入 trace/解析缓存、文件级稳定向量 ID 与增量复用、精确 upsert/delete 同步、同库 head/回执屏障及保留旧记录的 not-sent 重试 | `Experimental`（工作区 Python API；真实本地库/模拟传输回归通过，未真实 Qdrant 验收） | Phase 3/6 |
| 现有 evaluate CLI/TUI 逐用例知识查询、整批预检、独立代码/查询授权和计量范围声明 | `Experimental`（实际离线 Runtime/Provider 与 headless UI 回归通过） | Phase 3/6 |
| 增量同步管理 API/CLI/TUI：UTF-8 trace 预览锁定保存、具名工厂准备/暂存、独立增删批准、持久计划查看/执行；CLI 显式重试/对账 | `Experimental`（本轮独立定向验收见同步与计量记录） | Phase 3/6 |
| 显式 PDF/DOCX/XLSX/PPTX trace 同步 CLI/TUI；可替换原始归档协议、SQLite 原始字节与 trace 关联 | `Experimental`（真实离线格式解析与归档验证，已随 2.0.0 发布） | Phase 3/6 |
| 段落/句尾结构分块与有界字符重叠、精确来源 span、trace v2 与旧 v1 兼容、同步 CLI/TUI 配置锁 | `Experimental`（确定性文本规则，不是模型语义理解） | Phase 3/6 |
| 原始归档管理 API/CLI：版本预览、来源批准保存、回执校验及独立授权单 blob 新文件导出 | `Experimental`（不覆盖、不执行、不自动目录还原） | Phase 3/6 |
| 目录还原/GC、模型语义分块、自定义分块持久解码注册、跨存储同步、准备逐文档部分检查点、跨库执行租约、其他后端计划模板 | `Planned` | Phase 3/6 |
| 绑定快照/目标的知识索引清单、独立 SQLite pending/最终回执日志、显式带日志写入、重复尝试拒绝与本地全点覆盖率 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| 可选知识索引宿主证据对账、无迟到效果双确认、不可覆盖决定与原始观察保留、v1/v2 日志读取及派生覆盖率 | `Experimental`（已随 2.0.0 发布，本地/模拟回归通过，不属于 a9） | Phase 3/6 |
| 外部 collection 创建、远端证据采集/核对与操作/点状态查询、错误对账决定修订、旧 snapshot 索引迁移、其他原生/批量 Embedding 模板与专用装配、外部重排和其他检索后端、真实服务/检索质量验收 | `Planned` | Phase 3/6 |
| 跨模型/Embedding/检索/重排用量协议、内存/SQLite 统一观测账本、复用预算的显式包装器、只读 service-usage CLI | `Experimental`（显式接线，不替代预算或供应商账单） | Phase 3/6 |
| Runtime/Provider 具名用量观察绑定、真实模型 attempt/共享票据去重、可选检索观察及四类 CLI/TUI 入口 | `Experimental`（宿主 operation 级，不是每个 Run 独占费用） | Phase 3/6 |
| 可选 Run/Session→operation 内存/SQLite 关联、准备前保存、恢复身份核对、只读 CLI 查询与操作汇总查找 | `Experimental`（关联不证明 Run 已启动/完成，不是跨库事务） | Phase 3/6 |
| 原生游标计量、每笔准备/服务观察的 Run 归属与全链路自动归集、检索/重排服务级统一预算接线 | `Planned` | Phase 3/6 |
| 可选输入 name/metadata 包装记录、独立字段展示与模型历史复用 | `Experimental`（2.0.0a8；针对性回归通过） | Phase 3/6 |
| 输入消息字段 CLI/TUI Replay 独立披露、包装内容展示与共享投影装配 | `Experimental`（2.0.0a8；针对性回归通过） | Phase 3/6 |
| 消息字段 CLI/TUI 显式输入、逐次保存与历史发送配置 | `Experimental`（2.0.0a8；针对性回归通过） | Phase 3/6 |
| TUI 受信缓存导入续读、显式新文件导出与 CLI 缓存互通 | `Experimental`（2.0.0a8；针对性回归通过） | Phase 3/6 |
| TUI Replay PNG/JPEG/WebP 字符预览、WAV 元信息与独立确认导出、可替换展示协议 | `Experimental`（实际离线解码与 headless UI 回归通过） | Phase 3/6 |
| 彩色高分辨率终端媒体、音频播放/波形、更多编解码器与隔离解码 | `Reserved` | 后续可选增强，不额外扩大首版验收门槛 |
| 工具定义、策略和执行器分离 | `Implemented` | Phase 3 / 2.0.0a1 |
| Python 函数工具模板 | `Implemented` | Phase 3 / 2.0.0a1 |
| HTTP 与无 Shell 命令工具适配器 | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP 客户端绑定适配器 | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP 2026-07-28 stdio/Streamable HTTP 客户端与发现 | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP 2025 初始化协商与 HTTP Session | `Experimental`（`2.0.0a4`） | Phase 3/5 |
| MCP 显式 handler、2026 有界 MRTR、双工 stdio 与现代/旧版资源订阅 | `Experimental`（本地子进程与模拟回归通过，未外部互操作验收） | Phase 3/5 |
| MCP 2026 POST 持续订阅、2025-11-25 HTTP 主动请求/显式 GET 通知及有界取消/关闭 | `Experimental`（真实本机回环 HTTP 验证，未外部服务验收） | Phase 3/5 |
| MCP 2024 HTTP+SSE、Tasks、自动恢复/重连、OAuth 与完整 Sandbox 绑定 | `Planned` | Phase 3/5 |
| 本地 Session 生命周期与跨 Run 文本投影 | `Implemented` | Phase 3 / 2.0.0a1 |
| 显式工具参数增量 RunEvent | `Experimental`（`2.0.0a4`） | Phase 3 |
| 声明式顶层字段允许/掩码投影模板 | `Experimental`（`2.0.0a4`） | Phase 3/6 |
| 显式多模态输出事件与三档披露投影 | `Experimental`（`2.0.0a4`） | Phase 3/6 |
| 嵌套路径复制/重命名/固定掩码投影模板 | `Experimental`（`2.0.0a4`） | Phase 3/6 |
| DAG、状态图、Python Workflow | `Implemented` | Phase 4 / 2.0.0a1 |
| 有界异步 DAG 前沿并行 | `Experimental`（`2.0.0a4`） | Phase 4 |
| 可替换节点调用与显式同步线程执行 | `Experimental`（`2.0.0a4`） | Phase 4 |
| 按 Run ID 的外部边界暂停与可替换请求源 | `Experimental`（`2.0.0a4`） | Phase 4 |
| TUI 恢复任务后台运行、边界暂停与可选线程调用 | `Experimental`（`2.0.0a4`） | Phase 4/6 |
| CLI 与跨进程 Workflow 暂停入口 | `Experimental`（`2.0.0a5`；针对性回归通过） | Phase 4/6 |
| 只读暂停源组合与 TUI 显式跨进程监听 | `Experimental`（`2.0.0a5`；针对性回归通过） | Phase 4/6 |
| TUI 大字符欢迎标识、颜文字与窄窗口适配 | `Experimental`（`2.0.0a4`） | Phase 6 |
| 本地节点级 Checkpoint、暂停和恢复 | `Implemented` | Phase 4 / 2.0.0a1 |
| Agent/Workflow 双向便捷适配器 | `Implemented` | Phase 4 / 2.0.0a1 |
| 节点挂起与 Workflow 内 Agent 精确审批恢复 | `Experimental`（`2.0.0a5`；针对性回归通过） | Phase 3/4 |
| 审批关联查询、CLI/TUI 只读视图与宿主一次性授权 | `Experimental`（`2.0.0a5`；针对性回归通过） | Phase 3/4/6 |
| 显式装配与 CLI 精确审批后恢复父流程 | `Experimental`（`2.0.0a6`；针对性回归通过） | Phase 3/4/6 |
| TUI 精确审批、后台父流程恢复与逐次确认 | `Experimental`（`2.0.0a6`；针对性回归通过） | Phase 3/4/6 |
| Agent→Workflow 引用优先续执行桥与父子暂停关联 | `Experimental`（`2.0.0a6`；针对性回归通过） | Phase 3/4 |
| 双层审批只读关联、独立授权与父 Agent 恢复服务 | `Experimental`（`2.0.0a6`；针对性回归通过） | Phase 3/4 |
| 双层审批 CLI 只读查询与四项确认恢复 | `Experimental`（`2.0.0a6`；针对性回归通过） | Phase 3/4/6 |
| 双层审批 TUI 只读查询、显式选行与四项确认恢复 | `Experimental`（`2.0.0a6`；针对性回归通过） | Phase 3/4/6 |
| 类型化工具续执行、可选恢复协议与 ReAct schema 2 检查点 | `Experimental`（`2.0.0a6`；针对性回归通过） | Phase 3/4 |
| 跨 Store 原子提交 | `Reserved` | 后续设计 |
| Workflow Checkpoint 脱敏汇总、显式 Definition 加载与 CLI/TUI 恢复 | `Experimental` | Phase 4/6 / 2.0.0a4 |
| Docker/OCI 编码沙箱 | `Implemented` | Phase 5 / 2.0.0a1 |
| `UnsafeLocalSandbox` 显式授权模式 | `Implemented` | Phase 5 / 2.0.0a1 |
| Sandbox 命令工具绑定 | `Implemented` | Phase 5 / 2.0.0a1 |
| nsjail cgroup v2 Provider 与旧技能 ProviderSkillSandbox 桥 | `Experimental`（本地参数/生命周期回归；真实 Linux 隔离未验收） | Phase 5 |
| Wasm 通用硬资源 Provider、网络域名/IP 白名单策略与跨平台真实验收 | `Planned` | Phase 5 |
| 客服/RAG 与编码 Agent 模板 | `Implemented` | Phase 5 / 2.0.0a1 |
| 工程装配编码、安全预览与版本管理 | `Implemented` | Phase 6 / 2.0.0a1 |
| 可替换的装配离线环境/插件依赖计划 | `Experimental` | Phase 6 / 2.0.0a4 |
| 宿主锁目录、Sandbox 包安装与独立插件加载确认 | `Experimental`（`2.0.0a4`） | Phase 1/5/6 |
| 通用插件无导入预览、确认批量加载与 TUI 卸载 | `Experimental` | Phase 1/6 / 2.0.0a4 |
| 进程内插件替换预览、明确静止确认、一次性精确计划及旧句柄隔离 | `Experimental`（实际本地管理器/注册表回归通过） | Phase 1/6 |
| 常驻 plugin session CLI 与 TUI 当前管理器替换、独立导入授权、精确双确认/漂移检查 | `Experimental`（本地会话与 headless UI 回归通过） | Phase 1/6 |
| 插件在线发现/锁生成/包升级、自动排空/消费者重建/状态迁移与持久审计 | `Planned` | Phase 1/6 |
| Typer/Rich CLI、Textual TUI 与 Session 生命周期界面 | `Experimental` | Phase 6 / 2.0.0a1 |
| 本地配置化文本 Agent 运行入口 | `Experimental` | Phase 6 / 2.0.0a1 |
| 配置化工具选择、显式代码加载与 CLI 审批恢复 | `Experimental` | Phase 3/6 / 2.0.0a1 |
| Agent 审批 Checkpoint 脱敏列表（API/CLI/TUI） | `Implemented` | Phase 3/6 / 2.0.0a1 |
| TUI 工具加载/权限/精确审批恢复与脱敏实时 RunEvent | `Experimental` | Phase 3/6 / 2.0.0a3 |
| 脚本化模型 Mock、显式录制/回放和本地评测指标 | `Experimental` | Phase 6 / 2.0.0a1 |
| CLI/TUI 本地评测入口与安全报告 | `Experimental` | Phase 6 / 2.0.0a1 |
| 评测价格/费用指标 | `Experimental` | Phase 6 / 2.0.0a2 |
| 版本化客服/编码内置基准集与用例契约评分 | `Experimental`（`2.0.0a4`） | Phase 6 |
| 1.x 最小 `LegacyAgentAdapter` | `Implemented` | Phase 6 / 2.0.0a1 |

## 实施阶段

### Phase 0：设计和文档

- 状态：`Implemented`。
- 固化设计原则、协议边界、状态标记和非目标。
- 更新全部中英文文档。
- 不改变现有运行时代码。

### Phase 1：微内核

- 状态：`Implemented`（`2.0.0a1`）。
- Python 3.11+。
- `PluginSpec`、统一注册表、生命周期、依赖解析、Scope 和事件/Pipeline。
- 四种插件接入方式汇聚到同一注册流程。
- 插件卸载、失败回滚和 Run 快照测试。

### Phase 2：模型与路由

- 状态：`Implemented`（2A 基础与 2B 适配/执行）；显式文本前缀恢复为 `Experimental`，Provider 原生游标协议与执行器接线位于`2.0.0a4`。
- 2A 已实现模型请求、响应、流事件、能力声明、扩展参数、Provider 注册表和稳定错误分类。
- 2A 已实现可解释路由决策、Python/YAML 策略、端点嗅探、Provider 探测、缓存和周期调度。
- 2B 已实现带可替换 HTTP 传输的 OpenAI-compatible Chat Completions Provider。
- 2B 已实现通用 HTTP 请求映射层、JSON/SSE/NDJSON 传输、四种原生模板和四种兼容厂商模板。
- 2B 已实现默认单次调用、显式有界重试/故障转移、逐尝试超时与审计记录的收集式和逐事件透传执行器；透传一旦暴露任何事件便禁止静默重放。
- 2B 已统一 Provider 上报的输入、输出和缓存输入 Token；`usage_reported` 明确区分真实零用量与 Provider 未上报，不用零值伪装完整计量。
- 2B 已实现可选的 `ModelRegistrationProbeService` 注册安全探测路径和 `ProbeHealthBridge`；底层 `ModelRegistry.register()` 保持纯注册语义。
- 2B 已提供 OpenAI Responses/vLLM 专用适配、CLI/TUI 的无凭据 L1 安全端点探测，以及从严格本地配置装配 Provider 的安全目录/显式授权主动生成探测。Provider 单独装配不注册、不发起 I/O；`safe` 是否访问远程目录由具体 Provider 决定，`active` 才验证最小生成与流终止协议。
- 2B `2.0.0a4` 新增 `StreamRecoveryStrategy` 与 `VerifiedTextPrefixRecovery`。只有调用者显式传入策略且配置正数 `max_stream_replays` 才会在同一路由重放；已公开文本按语义前缀校验并只暴露未见后缀，分歧、工具/多块事件或不完整重放都会失败关闭。每次重放进入 Attempt 账本且可能再次计费。`2.0.0a4`另外增加 `CursorResumableModelProvider`、事件后游标与显式有界 `NativeCursorRecovery`；它沿用同一流校验器，不重发完整请求，Provider 自行保证同次生成与精确游标。ReAct Loop 和本地 Runtime 装配现可显式注入续流策略，默认关闭；调用前费用包络计入续流连接。内置厂商适配和跨进程恢复仍为后续能力。

### Phase 3：Agent 与工具

- 状态：工具执行基础、Run 协议、单 Agent ReAct、本地事件记录、审批恢复与本地 Session 生命周期为 `Implemented`；只读游标分页、可替换 JSON 脱敏投影、声明式顶层/嵌套字段策略、显式工具参数增量和显式多模态输出投影处于`2.0.0a4`。
- 已实现可替换 Agent Loop、默认 ReAct 模板、进程内/JSONL RunEvent、步骤/工具预算和不重复首轮模型调用的审批恢复。
- 已实现 `TokenBudget` 的 Run 级输入、输出、总量硬限制，`RunResult.usage` 与 `TOKEN_USAGE` 事件公开累计值；审批 Checkpoint 保存计量状态。`max_output_tokens` 仍只表示单次模型生成上限。
- 当前预算依据成功响应中 Provider 返回的实际用量在响应后核算，并用剩余输出/总量收紧下一次请求上限；可用 `require_usage=True` 在 Provider 不上报时失败关闭。可注入 `TokenEstimator` 在调用前估算输入、收紧本次输出额度并阻止明显越限请求；`require_estimate=True` 可在估算不可用时失败关闭，`soft_limit_ratio` 产生不改变停止策略的可观察警告。估算无法预知重试/故障转移，最终仍以 Provider 实报为准。
- 已实现 Session 级累计、覆盖重试/故障转移的 `AttemptRecord` Token 账本，以及 RunEvent/CLI 可见性；未报告的失败尝试保持未知并使严格计量失败关闭。
- 已实现应用提供的版本化价格表、普通/缓存输入与输出费用计量、费用完整性、审批断点持久化和 Run 费用硬预算；缺少价格或用量时失败关闭，不从 Token 数静默推断金额。
- `2.0.0a4` 已实现 `SessionManager.agent_usage()`、CLI/TUI 按 Agent 跨 Session 汇总，以及未知用量/费用不伪装为零的完整性语义。
- `2.0.0a4` 已实现显式调用前 `CostEstimator`、默认版本化价格/路由/重试故障转移包络、费用软阈值事件和模型生成请求前硬停止；Provider 实报费用仍在调用后权威核算。后续提供由应用策略消费软阈值事件的更多动作模板。
- 已实现 `SessionManager`、内存/JSON Store、创建/列表/归档/取消归档、跨 Run 文本投影，以及 Session 内 Agent 启动和审批恢复。
- `2.0.0a4` 已实现显式 `emit_text_deltas` 的 Agent 文本增量 RunEvent。`2.0.0a4`新增独立的 `emit_tool_call_deltas`、`RunEventReplay`、可替换 `RunEventProjector` 与默认拒绝的 `FieldPolicyRunEventProjector`：回放从可替换事件源读取绑定 Run ID 的有序分页，投影页默认移除内容并校验 JSON 兼容性；声明式模板可按精确事件类型或 `*` 回退允许/固定掩码顶层字段，应用也可完全替换投影器。`NestedFieldRunEventProjector` 通过显式对象/数组源路径、对象目标路径和复制/固定掩码动作提供嵌套选择及重命名，缺失路径跳过、目标冲突失败关闭。内置内存/JSONL Store 提供可选有界页读取；旧自定义 Store 可继续使用整日志接口。不重执行模型/工具，原始事件读取授权和自定义字段公开策略仍由调用者负责。相同工作区还新增显式 `emit_output_blocks`、可替换 `ModelOutputEventEncoder`、有大小上限的标准图片/音频编码器和 `MultimodalRunEventProjector` 三档披露；默认界面仍隐藏媒体 URL/正文。
- 已实现 Python 工具模板、统一注册表、参数校验、权限/逐调用审批、超时/取消、标准结果和 Prompt-free 审计。
- 已实现固定端点 HTTP、无 Shell 命令工具、传输中立的 MCP 绑定，以及 MCP 2026-07-28 stdio/Streamable HTTP JSON/SSE 客户端、分页发现、显式绑定与 `x-mcp-header`。发现不会自动注册、授权或批准工具。
- `2.0.0a4`新增可显式选择的 2025 版 `initialize` / `initialized` 协商客户端，覆盖 stdio 与 Streamable HTTP Session/版本头；不自动回退或重放工具调用。工作区另实现显式 handler、MRTR 与双工 stdio 订阅，见[MCP 交互](./mcp-interactions.md)；新[实时 HTTP](./mcp-http-interactions.md)分别覆盖 2026 POST 订阅与 2025-11-25 主动请求/显式 GET。Tasks、自动重连、OAuth 与完整 MCP Sandbox 绑定仍待实现。

### Phase 4：Workflow

- 状态：本地顺序执行引擎、节点边界恢复与 Agent 双向适配为 `Implemented`；显式有界异步 DAG 并行为`2.0.0a4`的 `Experimental` 能力。
- 已实现 DAG、状态图和 Python API，共用 `WorkflowEngineProtocol`、事件和结果协议。
- 已实现内存/JSONL 节点 Checkpoint、显式暂停、重启恢复和边界取消。
- `2.0.0a4` 已实现 `WorkflowCheckpointSummary`、与稳定 Store 分离的 `WorkflowCheckpointCatalog` 查询协议、显式 `module:attribute` Definition 加载，以及按名称/版本/类型精确校验的 CLI/TUI 恢复；运行时值默认隐藏，代码加载与执行分别确认。
- 节点执行状态不确定时保留 `RESUMING` 并拒绝自动重放；不恢复任意 Python 指令栈。
- 已实现 `agent_workflow_node()`，以及受工具权限/逐调用审批管线保护的 `workflow_start_tool()` / `workflow_resume_tool()`；适配器只依赖公开协议且允许替换消息、权限上下文和结果映射。
- `2.0.0a4`新增 `max_parallel_nodes`，同批就绪节点并发运行、按定义顺序合并，状态键冲突失败关闭，失败/取消保留 `RESUMING` 防止副作用重放；默认仍顺序执行。另新增可替换 `WorkflowNodeInvoker` 与显式 `ThreadedWorkflowNodeInvoker`，覆盖所有内置前端和恢复入口；取消等待已启动同步调用退出，不强制终止线程或提交取消结果。`2.0.0a5`新增节点挂起和 `approval_agent_workflow_node()`，以精确子 Run/Call 引用与新宿主授权恢复 Workflow 内 Agent（针对性回归通过）；`2.0.0a6`已补反向工具续执行桥，双层授权协调服务亦已加入工作区（针对性回归通过），CLI/TUI 接线亦已通过针对性回归，跨 Store 原子提交为保留设计。

- `2.0.0a4`增加 `WorkflowPauseSource` 与线程安全的 `WorkflowPauseController`：按精确 Run ID 在已提交节点/批边界暂停，保留 `PAUSED` Checkpoint；恢复前显式清除请求，已完成节点不重跑。请求源可替换，执行协议与 Checkpoint 格式不变。TUI 已接入本界面恢复任务的后台运行、精确绑定暂停与可选线程调用，结束时清理本次请求；`2.0.0a5`新增 `SQLiteWorkflowPauseController` 与 CLI 请求/状态/清除及显式恢复监听，针对性回归通过；沿用边界暂停，不增加执行所有权或多主恢复能力，TUI 通过默认关闭的选项组合本界面控制器与 SQLite 源；新增 `AnyWorkflowPauseSource` 提供只读 OR 组合，任务结束不清除外部持久化请求。

### Phase 5：本地模板与沙箱

- 状态：统一协议、Docker Provider、显式授权本地 Provider、命令工具绑定和首批 Agent 模板为 `Implemented`；更广环境验收为 `Planned`。
- 已实现 Docker/OCI 生命周期 Handle、默认断网、资源限制、最小权限参数、固定镜像策略和清理。
- 已实现仅能通过运行时授权对象创建的 `UnsafeLocalSandboxProvider`；安全后端失败不会自动降级。
- 已实现 `sandbox_command_tool()`，通过现有权限、逐调用审批、取消和审计管线执行。
- 已实现完全可覆盖的客服/RAG 与编码 `AgentTemplate`；模板不绑定模型、不自动注册工具，也不授予权限或本地执行权。
- 工作区新增 nsjail cgroup v2 Provider 与旧技能桥；Wasm 通用硬资源 Provider、网络 allowlist 和 Windows Docker Desktop/WSL2/Linux 广泛验证仍待完成，见[沙箱](./sandbox.md)。

### Phase 6：分享、界面与评测

- 已实现命名和版本化的 `CompositionManifest`、确定性编码/解码、大小限制、完整性校验、安全预览与冲突安全的本地版本/别名库。
- 装配预览阶段不访问网络、不安装、不导入也不执行插件。`2.0.0a4` 已实现显式候选清单上的 Python/W-Agent 兼容性与插件依赖计划，以及独立 YAML 引用的无导入预览、明确确认后的事务化批量加载和 TUI 持久进程内卸载。`2.0.0a4`新增宿主提供的精确 wheel/SHA-256 闭包目录、可见 Index 来源的脱敏安装请求、请求摘要绑定授权、仅挂载空白暂存目录的 Docker/显式授权本地 Sandbox 安装、内容树复验，以及导入后、setup 前的入口来源与名称/版本核对；插件加载仍需独立确认。在线来源发现、自动锁定、自动升级和同名插件静默热迁移仍为 `Planned`。
- 已提供 `wagent` CLI（保留 `w-agent` 别名）和可启动的 Textual TUI 基础；覆盖工作区初始化、模板列表、安全端点探测、装配导出/预览/保存/列表、本地 Session 创建/查看/归档/恢复、按 Agent 跨 Session 的安全用量/费用汇总，以及 TUI 离线装配检查。
- 已实现严格本地 JSON 到 Provider/路由/ReAct/Run/Session 的文本运行装配；CLI/TUI 每次调用均要求显式授权，凭据只从环境变量引用读取。
- 已实现由宿主 Catalog 限定的配置化工具选择、逐次权限授予、独立 Python 工具代码加载确认，以及已知 Session/Run/Call ID 的 CLI 审批恢复；配置本身不能导入、授权或批准工具。
- 已实现 Agent 审批 Checkpoint 的 API/CLI/TUI 脱敏列表；摘要不含 Prompt、参数值、输出或凭据。
- 已实现无网络的脚本化 Model Provider、需显式敏感内容授权的 JSONL 录制/顺序回放，以及可替换 Scorer 的顺序评测运行器；CLI 可读取严格 JSON 用例集，默认使用一次性状态，并输出 Token 完整性、延迟、错误与工具成功率。JSON 报告默认排除 Prompt、输出、Metadata 和异常正文。
- 已实现 TUI 顺序评测页面：严格 JSON 用例、一次性状态、`EVALUATE` 单次授权、汇总指标和可选安全报告；不默认展示 Prompt 或输出。
- 已实现 TUI 工具入口独立加载确认、本次权限、精确 Session/Run/Call ID 审批恢复和脱敏实时 RunEvent；确认不持久化，界面不展示 Prompt、模型文本、工具参数或工具结果。
- 已实现从显式选择的本地 State Root 汇总和恢复 Workflow Checkpoint；不会自动复制、合并或迁移 Store。
- `2.0.0a4` 已实现配置值脱敏的插件引用预览、`--confirm-plugin-code` 短生命周期 CLI 验证，以及绑定 `LOAD PLUGINS` / `UNLOAD <name>` 的 TUI 生命周期操作。`2.0.0a4`另外提供 `composition install-plan/install`、`plugin validate-installed` 和 TUI 的锁定安装/独立加载入口；无人确认的安装、在线来源发现和自动升级仍为 `Planned`。
- `2.0.0a4` 已实现可替换 `CompositionDependencyResolver`、严格 JSON 候选清单、环境约束检查和逐插件离线动作计划；CLI/TUI 的依赖计划，以及`2.0.0a4`的安装计划入口，都不会查询网络、安装包或把 Ready/Installable 视为代码加载授权，只有后续精确确认的安装操作才允许网络和包代码执行。
- 已实现评测报告、CLI 与 TUI 的版本化费用汇总；`2.0.0a4` 新增可替换 `EvaluationSuiteRegistry`、版本化客服/编码套件、声明式 `CaseContractScorer`、`builtin:` 解析与无网络 CLI 导出。套件不附带工具实现或权限；CLI/TUI 的模型调用、工具代码导入与本次权限仍分别授权。
- 已实现旧 `BaseAgent.arun()` 到 Workflow 节点的严格文本兼容桥；其他旧 API Bridge 仍按需规划，不建立第二套运行时。

## 保留但未排期

以下能力为 `Reserved`：

- 进程外多语言插件 SDK。
- Remote Sandbox 官方实现。
- MCP 完整工具 Provider。
- 多 Agent 协作中的委派、人工审批协调与 Agent 间通信；不包括已经提供的单 Agent/本地 Workflow 审批与恢复。
- 嵌套及分布式 Workflow。
- 工程装配编码签名、发布索引和信任网络。
- 完整在线评测服务。
- 语音等专用模态适配器；核心多模态协议将在模型阶段保留。

## 非目标

- 托管 W-Agent 平台。
- 首版租户、组织、计费、云账户管理。
- 自动运行导入装配中的第三方代码。
- 在隔离后端不可用时静默使用宿主机执行。
