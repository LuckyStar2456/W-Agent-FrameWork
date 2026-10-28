# Run / Session 与服务用量关联

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](service-usage-links.en.md)

这是可选的本地宿主关联，不是租户设计，也不是逐 Run 计费账本。`ServiceUsageRunLink(session_id, run_id, operation_id)` 只保存三个有界标识；不保存 prompt、工具参数、证据、endpoint、价格或用量记录内容。

## 显式装配

```python
from pathlib import Path
from w_agent.service_usage_links import SQLiteServiceUsageLinkStore
from w_agent.service_usage_runtime import LocalServiceUsageBinding
from w_agent.service_usage_sqlite import SQLiteServiceUsageLedger

async def prepare_binding():
    # 仅在宿主已获得本地建库/写入授权时执行初始化；重开无需初始化。
    # 用户先建立 .wagent 父目录；下面两个初始化不是一个原子事务。
    ledger = SQLiteServiceUsageLedger(Path(".wagent/service-usage.sqlite3"))
    links = SQLiteServiceUsageLinkStore(Path(".wagent/service-usage-links.sqlite3"))
    await ledger.initialize(confirm_create=True)
    await links.initialize(confirm_create=True)
    return LocalServiceUsageBinding(ledger, "my-operation-v1", links=links)

# 将返回的 binding 置于 service_usage_bindings={"observations": binding}，
# 配置只选择 service_usage.binding = "observations"。
```

`links=None` 是兼容默认值，不创建或读取关联数据库。配置文件只选择具名绑定；不会导入宿主代码或决定数据库路径。宿主将 `links` 放入授权的 binding，表示允许 Runtime 为新 Run 写关联；CLI/TUI 的代码加载与用量记录仍分别需要确认。Runtime 借用 store，不初始化、不删除、不关闭宿主资源。

可直接改写 [examples/service_usage_host.py](../examples/service_usage_host.py)：它只借用已初始化的两个数据库，导入/工厂不自动建库。该示例选择名为 `local-usage` 的绑定，入口为 `examples.service_usage_host:usage_factory`；必填环境变量 `WAGENT_USAGE_OPERATION`，可选 `WAGENT_USAGE_ROOT`（默认 `.wagent`）。使用示例时配置 `service_usage.binding = "local-usage"`，并分别授权 `--confirm-usage-code` 与 `--confirm-usage-recording`。恢复时必须复用原 operation 标签和关联库，不能随机生成新的标签。

## 生命周期与失败边界

新 Run 先创建/读取 Session，再生成 Run ID 并 `bind(..., confirm_write=True)`，然后才进入历史投影、知识检索、模型/工具循环。因此检索或准备失败前也有可查询的关联。关联失败或任务取消不会继续调用模型；已经开始的 SQLite 工作线程会排空后传播取消。

提前关联可能留下孤立记录：它不证明 Run 已启动、完成、写入 Session 的 Run 列表或消耗了任何费用。Session、关联数据库、usage ledger 之间没有跨库原子事务；取消时应查库，而不是假定写入没有发生。

恢复已存在的审批断点时，启用了 links 的 Runtime 在领取 checkpoint、执行工具或调用模型前读取原关联。Run、Session、operation 必须精确匹配；缺失、冲突、读失败一律拒绝，不自动补写历史 Run。正确绑定重新打开后仍可恢复。未配置 links 的老调用保留原行为。

这个检查仅约束选择了同一可信关联 store 的参与宿主；它不是防止宿主关闭观察、替换数据库或修改数据库的安全沙箱。旧 Run 的人工迁移/关联必须由宿主另行审查授权，框架不会根据 prompt 推断归属。

## 可替换协议与查询

`ServiceUsageLinkStore` 提供异步 `bind(link, *, confirm_write=False)`、`get(run_id)`、`for_session(session_id)` 和 `for_operation(operation_id)`。`get` 返回 link 或 `None`；列表返回按 run_id 排序的 tuple，不静默截断。内置 `InMemoryServiceUsageLinkStore` 与 `SQLiteServiceUsageLinkStore` 使用相同语义：同一 Run 的完全相同关联幂等，改 Session 或 operation 拒绝，无覆盖/删除接口。

默认 `max_links=10000`，可在构造时选择 1–100000。SQLite 将容量持久化，重开必须一致；达到容量拒绝新关联，不能通过清理历史隐式释放。SQLite 使用专用数据库、严格版本/结构检查、只读查询连接、参数绑定、有限字段读取和事务写入。读/bind 不自动建库；`initialize(confirm_create=True)` 不接管已有其他结构的数据库。路径是宿主信任输入，不是路径沙箱。

```python
links = SQLiteServiceUsageLinkStore(Path("usage-links.db"))
link = await links.get("run-example")  # 没有找到时为 None
related = await links.for_session("session-example")
```

离线 CLI 查询无需加载 Provider 或宿主工厂：

```text
w-agent service-usage-link --links-database usage-links.db --run run-example --confirm-read
w-agent service-usage-link --links-database usage-links.db --session session-example --confirm-read
w-agent service-usage-link --links-database usage-links.db --operation my-operation-v1 --confirm-read
```

三个选择器必须且只能选择一个。自定义容量用 `--max-links`，须与建库时一致。`service-usage` 可通过 Run 关联读取 operation 汇总：

```text
w-agent service-usage --database usage.db --run run-example --links-database usage-links.db --confirm-read
```

该结果明确包含 `resolved_link`、`association_only`、`run_state=not-inferred`，并仍标记 `scope=host-operation-not-this-run`。usage 容量如非默认值，还需传与建库一致的 `--max-records`。示例命令中的路径应替换为宿主实际使用的两个数据库。

## 不应误解的统计范围

多个 Run 可指向同一 operation；准备阶段、其他 Run、宿主手工记录也可能在该 operation 中。查询 Run 后显示的依然是 `host-operation-not-this-run` 汇总，不能把几个 Run 的汇总再次相加；关联不是 usage record 的归属证明。外部宿主自行调用的服务不会因此自动获得 Run 标签，Provider 探针等无 Run 的操作也不创建关联。

当前提供关联与重开检索，不提供逐 attempt 的 Run 归属、自动计价、跨库原子事务、关联删除/迁移工具或不可篡改审计。它们仍是保留设计。
