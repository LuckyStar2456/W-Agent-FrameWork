# Runtime 具名跨服务用量观察

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](service-usage-runtime.en.md)

状态：2.0.0 Experimental。配置只选择宿主目录中的观察绑定；不会从 JSON 自动导入 Python、打开数据库、创建预算或猜测价格。观察记录与准入预算是两件事。

## 组装 API

```python
from w_agent.local_runtime import assemble_local_runtime, local_runtime_config_from_mapping
from w_agent.service_usage import InMemoryServiceUsageLedger
from w_agent.service_usage_runtime import LocalServiceUsageBinding

ledger = InMemoryServiceUsageLedger()
binding = LocalServiceUsageBinding(
    ledger, operation_id="local-development-operation",
    model_source_ref="main-model", meter_version="host-v1",
    # None (默认) 不观察检索；以下选择整个 retriever 调用。
    retrieval_source_ref="knowledge-search",
    retrieval_token_scope="not-applicable",  # 仅当宿主确认该检索没有token计量时
)
config = local_runtime_config_from_mapping({
    "provider": {"template": "ollama", "model": "host-selected-model"},
    "service_usage": {"binding": "usage"},
})
runtime = assemble_local_runtime(config, service_usage_bindings={"usage": binding})
```

以上仅展示组装，不会发请求。要使用检索，还需原来的 `knowledge.binding`、借用的 `knowledge_bindings` 和每次调用的独立 query 授权。`assemble_local_provider` 同样接受 `service_usage_bindings`，可用于实际探测/评测，不需要手工包裹模型控制器。

绑定持有可替换的 `ServiceUsageLedger` 协议实现；Runtime 不初始化、关闭或调解宿主 ledger。SQLite 目录/建库及生命周期由受信宿主显式负责。`retrieval_measurement(result)` 可返回 `ServiceUsageMeasurement`，报告独立费用/单位；未提供计量时，不把未知费用/token当作零。

## 关联与可见性

`operation_id` 是宿主选择的有界本地标识，不是租户、凭证、query、endpoint，也不自动等于 Run ID。同一绑定可横跨多个 Run。每次 `run` / `run_messages` / `resume` 返回 `LocalRuntimeRun.service_usage_operation_id`。可选 `LocalServiceUsageBinding.links` 在准备前持久关联 Run/Session，恢复时拒绝缺失/冲突关联；默认不启用。详见[关联与重开查询](service-usage-links.md)。关联不把 operation 汇总变成逐 Run 账本。

`await runtime.service_usage_summary()`，或在工厂关闭前调用 `_service_usage_ui.service_usage_summary(binding)`，返回 `scope=host-operation-not-this-run` 的安全摘要：已观察调用、各服务计数、已知 token 小计、按货币/价格表版本分组的费用、不完整/未决记录数量。不会展示 record IDs、source labels、证据引用或正文。读取失败返回 `status=unavailable` 警告，不改变已完成 Run，不授权重跑。

原 `RunResult.usage` / `cost` 的模型语义不变，不把检索 token 混进主模型结果。摘要完整性仅覆盖已提交观察的记录，不证明其他宿主代码、工具内部服务、压缩模型或未包裹子服务已计量。`runtime_observers` 说明 Runtime 配置为观察模型，及是否观察整个检索调用；它不是系统全覆盖承诺。

## 模型与预算组合

- 没有共享预算时，`ObservedModelProvider` 每次实际 `stream` 建立独立 attempt。先记录 started 再调用模型，验证完整事件序列及 EOF、关闭内层 stream、保存完成观察后才转交 Finish。多次 Usage 更新只使用最终累计值，不相加。
- 完整成功但没有 Usage：完成调用的 token 未知，不记录已知零。中断、无效流、异常或提前关闭：记录 unknown；在确认未进入 Provider 前取消可记录 not-incurred。失败的物理 attempt 与后续正常重试分别保存。观察本身不新增重试策略。
- 未配置共享预算时，不自动套用价格、不假定图片/音频等其他计费单位完整。费用与额外单位保持未知。
- 同时配置 `shared_budget.binding` 时，Runtime 在**同一个** controller 上使用 `ObservedSharedBudgetController`，复用 reservation ID、实际 settle/unknown/release，而非再装一层模型观察器。只预留一次，保留既有 meter 的实际费用与准入行为；`runtime.shared_budget` 保持原 binding，原池级 snapshot 不变。
- 已知的二次包裹（预观察 controller、预观察 retriever、已包裹 Provider）会拒绝。自定义深层封装属于受信宿主，不能一般性检测所有重复计量。不要同时给整个复合检索和同成本子调用都计入总额。

原始 Provider 由 Runtime 关闭一次；ledger、meter、retriever 仍归宿主管理。`service_usage` 与 native cursor recovery 的组合当前显式拒绝，不会绕开观察器后声称完整计量。观察写失败为不可自动重试错误，双库预算/usage写入不是原子事务，可能需要分别核对。

## CLI/TUI 宿主工厂协议

`ServiceUsageOptions(entry, confirm_code, confirm_record)` 是纯预检；工厂仅在 `LOAD USAGE` / `RECORD USAGE` 两个独立授权齐备、配置有 `service_usage.binding` 时导入。

```python
from contextlib import asynccontextmanager
from w_agent.service_usage import InMemoryServiceUsageLedger
from w_agent.service_usage_runtime import LocalServiceUsageBinding

@asynccontextmanager
async def usage_factory():
    yield {"usage": LocalServiceUsageBinding(InMemoryServiceUsageLedger(), "explicit-operation")}
```

前端调用 `service_usage_binding_scope(entry, selected=..., confirmed=True, confirm_record=True)` 借用该目录。宿主是用户明确授权的不隔离 Python；不能把执行权限理解为沙箱。上下文退出不能吞掉 Runtime 错误；清理失败提示已执行动作可能成功，不应重跑。

CLI `run`、`run-resume`、`evaluate`、`provider-probe` 使用 `--usage-entry host_module:usage_factory --confirm-usage-code --confirm-usage-recording`，并要求配置选择 `service_usage.binding`。TUI 对应的 Run、Resume、Evaluation、Provider probe 四个区域各自提供宿主入口和单次 `LOAD USAGE` / `RECORD USAGE` 确认。启用观察不替代模型调用、检索、工具或真实探测的其他授权；评测中的同一工厂 operation 可以聚合多案例，不能标成每案例用量。

## 验证与保留

定向测试使用真实 SQLite reopen 与模拟 Provider/retriever：配置预检、无副作用组装、两次Run共operation、shared reservation不双计、独立检索、缺失/多次Usage、重试attempt、提前close、观察写失败不发布Finish、安全摘要、工厂独立授权与清理。未调用收费模型或外部服务。

保留：逐 attempt 的 Run 归属、native cursor 持久恢复观察、任意工具内部与复合子服务自动覆盖、自动供应商定价、usage与预算跨库原子事务。它们不是当前实现或完整性承诺。
