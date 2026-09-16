# 从 1.x 迁移

[English](./migration-1x.en.md) | 简体中文

状态：`Planned`。本文描述下一代实现期间的最小兼容原则；兼容适配器尚未实现。

## 策略

下一代公共 API 直接覆盖 `w_agent`，不创建 `w_agent.v2`。1.x 使用量有限，因此只保证基础迁移，不长期维护两套完整框架。

- 现有 1.x 在兼容窗口内继续安装和运行。
- 必要旧 API 移入兼容模块或由适配器导出。
- 新模型、Workflow、插件和沙箱能力只进入新协议。
- 弃用 API 使用 `Deprecated` 标记并给出替代路径。

## BaseAgent

当前：

```python
class BaseAgent:
    async def arun(self, prompt: str) -> str: ...
```

计划中的 `LegacyAgentAdapter` 将旧 Agent 包装成只能接受简单输入并返回最终文本的 Agent 节点。它不伪造流式事件、工具调用、Checkpoint 或能力声明。

## BeanFactory 与组件装饰器

现有 IOC 可以在过渡期作为插件构造后端。长期装配以统一 Registry 为准。装饰器仍可作为语法入口，但最终必须生成与显式 Python 构造相同的 `PluginSpec`。

## EventBus

1.x `EventBus` 可以由 Bridge 转发普通通知。下一代类型化 Pipeline、持久化 RunEvent 和生命周期效果不能完全映射回旧 EventBus。

## 配置

`DynamicConfigManager` 的普通键值可以迁移到下一代配置 Provider。秘密值必须改为凭据引用；插件清单和工程装配编码不能保存密钥。

## Skill 沙箱

Wasm 和 nsjail 实现计划适配到 `SandboxProvider`。旧调用方式在兼容期保留，但编码 Agent 应迁移到统一 Sandbox Handle 和 Docker/OCI 默认后端。

## 顶层导出

当新 API 与旧 API 同名时，迁移版本必须在发行说明中逐项列出替换关系。禁止根据参数类型在运行时猜测用户想调用新还是旧 API。

下一代 CLI 使用 `wagent`，现有 `w-agent` 在兼容期作为别名保留。

## 迁移完成条件

- 现有基本 Agent 示例可以通过适配器运行。
- 旧容器和配置用法具有明确替代方案。
- 弃用警告包含目标 API 和删除版本。
- 中英文迁移文档、测试和发行说明同步。
