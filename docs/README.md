# W-Agent 文档

[English](./README.en.md) | 简体中文

面向 **2.1.0** 开发，从 [README 快速入门](../README.md#快速入门)和[三条框架教程](./harness-development.md)开始。参阅[2.1.0 发布说明](./releases/2.1.0.md)、[PyPI](https://pypi.org/project/wagent-framework/2.1.0/)和[核心终验](./harness-acceptance.md)。此前[2.0.0 基础组件教程](./basic-development.md)仍保留；历史记录见文末。

`Implemented` 表示源码存在，不等于所有服务/环境通过验收；`Experimental` 保留明确限制；`Planned` / `Reserved` 是后续计划/保留设计，不能作为当前 API 使用。历史专题中的 alpha 版本号用于追溯，不代表 2.0.0 的完整验证范围。

## 开始使用

- [Harness 开发框架核心目标与 M0–M5 基线](./harness-core.md)
- [应用装配计划 M1 源码进展](./application-assembly.md)
- [注解式 Harness 开发 M2](./annotation-development.md)
- [应用切面与流生命周期 M3](./application-aspects.md)
- [默认组件装配与统一执行 M4](./default-assembly.md)
- [开发自己的 Harness：三条教程](./harness-development.md)
- [框架核心最终验收 M5](./harness-acceptance.md)
- [基础开发：客服与编码](./basic-development.md)
- [使用指南](./guide.md)
- [本地 Runtime](./local-runtime.md)
- [CLI / TUI](./tui.md)
- [架构设计](./architecture.md)
- [开发者指南](./developer.md)
- [公共 API](./api.md)
- [1.x 迁移](./migration-1x.md)

## 模型、工具与编排

- [模型路由与探测](./model-routing.md)
- [HTTP Provider 与厂商模板](./provider-templates.md)
- [Responses 续流](./responses-continuation.md)
- [Agent 与 ReAct Loop](./agents.md)
- [工具执行与权限](./tools.md)
- [Workflow 与恢复](./workflows.md)
- [MCP 主动交互](./mcp-interactions.md)
- [MCP HTTP 交互](./mcp-http-interactions.md)
- [沙箱与本地执行](./sandbox.md)

## 知识与索引

- [知识同步 CLI 主路径](./knowledge-sync-entries.md)
- [知识同步 TUI](./knowledge-sync-tui.md)
- [本地知识管理](./knowledge-management.md)
- [知识具名装配](./knowledge-runtime.md)
- [检索工具](./knowledge-tools.md)
- [正文检索与上下文](./knowledge-context.md)
- [文件与目录导入](./knowledge-files.md)
- [多格式解析与预览锁](./knowledge-import-extensions.md)
- [版本化快照](./knowledge-ingestion.md)
- [结构与重叠分块](./knowledge-splitting.md)
- [原始归档协议与存储](./knowledge-archives.md)
- [归档 CLI](./knowledge-archive-entries.md)
- [trace 持久化与增量同步](./knowledge-sync.md)
- [BM25、混合检索与重排](./knowledge-retrieval.md)
- [知识 Workflow 与评测](./knowledge-workflow-evaluation.md)
- [Embedding 与预算](./embeddings.md)
- [快照向量与检索](./knowledge-vectors.md)
- [历史向量检索](./vector-retrieval.md)
- [历史向量准备与写入](./vector-indexing.md)
- [索引清单与回执](./knowledge-index-journal.md)
- [索引日志管理](./knowledge-index-management.md)
- [精确向量计划](./knowledge-index-plans.md)
- [计划准备与执行](./knowledge-plan-actions.md)
- [计划目录与覆盖](./knowledge-plan-catalog.md)
- [完整构建与逐批继续](./knowledge-builds.md)
- [构建恢复与安全重试](./knowledge-build-recovery.md)

## 状态、用量与扩展

- [Session 与历史](./sessions.md)
- [事件回放](./event-replay.md)
- [媒体预览与导出](./tui-media.md)
- [上下文用量归集](./context-accounting.md)
- [共享预算](./shared-budget.md)
- [服务用量账本](./service-usage.md)
- [Runtime 服务用量](./service-usage-runtime.md)
- [Run/Session 用量关联](./service-usage-links.md)
- [插件系统](./plugin-system.md)
- [显式插件替换](./plugin-replacement.md)
- [工程分享](./project-sharing.md)
- [本地测试与评测](./testing-evaluation.md)

## 验证与历史

- [P1 文档验收与开发者 README](./acceptance-2026-10-01-p1-docs.md)
- [2.0.0 正式版验收与发布证据](./acceptance-2026-10-01-stable-release.md)
- [2.0.0 范围与验证说明](./releases/2.0.0.md)
- [基础发布清单 B01–B12](./stable-release-baseline.md)
- [路线图：已实现、计划与保留设计](./roadmap.md)
- [HTTP、归档与 Runtime 定向记录](./acceptance-2026-10-01-http-archives-runtime.md)
- [用量关联、分块与归档记录](./acceptance-2026-10-01-links-splitting-archives.md)
- [同步入口与用量记录](./acceptance-2026-10-01-sync-usage.md)
- [后续增量定向记录](./acceptance-2026-10-01-followup.md)
- [首轮统一记录](./acceptance-2026-10-01.md)
- [历史 alpha a9 发布说明](./releases/2.0.0a9.md)

历史记录仅证明各自代码与测试范围；重叠测试组不能相加，源码通过不等于包已上传、真实模型质量/计费或所有系统验收。剩余边界以各记录为准。
