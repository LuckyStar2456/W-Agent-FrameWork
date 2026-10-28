# 2026-10-01 后续开发与定向验收

[English](./acceptance-2026-10-01-followup.en.md) | 简体中文

本页冻结记录当批结果；后续同步入口和跨服务观测已继续开发，最新状态见[下一批验收](./acceptance-2026-10-01-sync-usage.md)与路线图，不将下文历史剩余项当成当前全部状态。

本页记录[第一批七模块统一验收](./acceptance-2026-10-01.md)之后的改动。第一批的 1811 passed 不覆盖这些后续代码。本轮用户单独批准相关测试、编译和静态检查；不跑全量、不安装依赖、不调用外部服务、不发布。新增能力均为工作区 `Experimental`，版本未更改。

## 本轮增量

| 模块 | 用户可用入口 | 边界 |
|---|---|---|
| 知识增量同步 | 可替换 SQLite trace/向量缓存持久化，源绑定稳定 ID、差异 upsert/delete 与回执恢复 | Python API 已完成并通过定向验收；不自动迁移原快照索引、不保证删除后旧版本的远端检索 |
| 插件替换入口 | `wagent plugin session` 常驻会话；TUI Plugins 精确审批与当前 manager 替换 | 只影响本进程；不是在线包升级或跨进程热更新；消费者不自动重启 |
| TUI 媒体展示 | Replay 独立确认图片字符预览、WAV 元信息、原始字节新文件导出；可替换 renderer | 不联网、不播放、不打开；解码非沙箱，导出目录须由可信宿主管理 |
| 知识评测入口 | `evaluate --knowledge-entry ... --confirm-knowledge-code --confirm-knowledge-queries`；TUI Evaluation 同等确认 | 每例新 Session/Run、整批预检；检索费用不包含在模型统计中 |

## 验证状态

沿用现有干净 Python 3.11.9 虚拟环境，未继承全局依赖：

| 定向组 | 结果 | 覆盖 |
|---|---|---|
| 界面与入口集成 | 227 passed，54.89 秒 | 插件替换/加载/安装回归，CLI/TUI，媒体展示/回放，知识评测与报告计量边界 |
| 知识与跨模块集成 | 115 passed / 2 skipped，117 collected，4.78 秒 | 31 项同步回归、15 项真实格式解析、文件/向量 Writer、框架跨链路和公共导出 |

两个跳过为 Windows symlink/FIFO 限制，不是解析依赖缺失。两组共享 4 项包检查，不能把数量直接相加。JUnit 文件位于验收环境的 `reports/followup-ui.xml` 与 `reports/followup-knowledge.xml`。未重新跑全量测试；第一批 1811 passed 仍仅证明当时版本。

最终导出接入后，4 项 package integrity 再次通过；760 个公共导出存在且无重复，核心导入不加载 Pillow/Textual。相关实现、测试及 setup.py 的 compileall 和 `git diff --check` 通过；未运行全仓类型检查或额外 lint 工具。此处耗时使用 pytest 终端总耗时，JUnit 内部计时可能略小。

同步审查补齐 canonical endpoint 校验，以及明确 `not-sent` 的独立授权重试：保留旧代次记录，未知/未决结果仍拒绝重发。检索、Embedding 与 Qdrant 使用离线替身/注入传输，未证明真实服务连通性、质量或费用。TUI 为 headless 交互验收，不替代人工终端体验验收。

新增 `media-preview` extra 仅修改依赖声明，图片验收使用环境已有 Pillow 12.3.0，未重新安装；该 extra 的独立安装尚未验收。未构建、推送或发布，版本仍为 `2.0.0a9`。

## 仍需完成

本轮关闭上述四项具体入口/能力，后续按六组管理，不将组数视为等工作量：

1. 知识链路：增量同步专用 CLI/TUI、原始二进制归档、语义分块、未知结果的 not-applied/撤销恢复及跨库协调。
2. 计量：模型与检索/Embedding/Rerank 的统一账本及预算闭环；现有模型 Token/费用控制保留。
3. 模型与恢复：更多原生媒体模板和应用级/跨进程续流恢复。
4. MCP：持续 HTTP 订阅、旧版 HTTP 主动请求、Tasks 与 Sandbox 绑定。
5. 插件：在线来源发现/锁定/更新、执行租约与状态迁移；本轮替换只作用于当前 manager。
6. 隔离与交付验收：网络策略/通用 Wasm，以及真实外部服务、Docker/nsjail/Wasmer 和人工 TUI 验收。

细分状态见[路线图](./roadmap.md)和[知识同步边界](./knowledge-sync.md)。高分辨率彩色终端预览、音频播放等保留增强不额外冒充首版必做项；保留设计也不冒充已交付能力。
