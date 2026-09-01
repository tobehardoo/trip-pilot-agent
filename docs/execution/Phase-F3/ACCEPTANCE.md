# F-3 验收记录 — 架构职责收敛

- 范围：F-0 收敛方案 §F-3（a/b/c/d 逐刀）
- 纪律：一刀一验收一提交；依赖方向以"架构图"为准（providers 契约层不得依赖 infrastructure 适配层）

## F-3a Python 依赖方向修复（`92304cf`）

### 修复内容

`providers/map.py`、`providers/_amap_route_failures.py`、`providers/_amap_transit_failures.py`
三个 providers 层文件从 `infrastructure/amap/errors.py` 导入 6 个错误码 frozenset——
**反向依赖**（providers 契约层依赖 infrastructure 适配层）。

处置：
1. 6 个 frozenset（AUTH/PERMISSION/RATE/QUOTA/UNAVAILABLE/INVALID_REQUEST_CODES）上提到
   `providers/amap_error_codes.py`（单一事实来源现在位于契约层）
2. 3 个消费者 import 改指新位置；docstring 同步更新
3. `infrastructure/amap/errors.py` 删除（grep 证实唯一消费者就是这 3 个 providers 文件；
   `infrastructure/amap/__init__.py` 无 re-export；tests/ 无引用）

依赖方向恢复为：`infrastructure（适配器） → providers（契约）`。

### 豁免评估（记录在案）

`domain/planning/protocols.py` 从 `worker/contracts` 导入 7 个类型
（FallbackOperation / Itinerary / KnowledgeEvidence / PlanningCandidateValidationCommand /
PlanningCreateCommand / PlanningReplanCommand / ProviderProvenance）。

**结论：豁免（成本 > 收益）**。依据：
- 这些类型全部继承 `worker/contracts` 内部的 `MessageModel` / `InboundMessageModel`
  基类体系（分布于 496–1670 行），与 RabbitMQ wire 契约深度耦合
- 下沉 domain 层 = 在 domain 复制消息类型（违反 F-2a "唯一"原则）或拖拽整个
  消息基类体系（等价于把 worker.contracts 搬到 domain，超出本刀职责）
- protocols.py 对 worker/contracts 的依赖是协议签名层面的类型标注，非运行时反向调用

### 验收

- `tests/test_map_provider.py` + `test_route_provider.py` + `test_amap_transit.py`
  + `test_provider_error_mapping.py`：**159 passed**
- 全量 pytest：**2063 passed / 42 skipped**（1 error 经双盲对照确认为既有测试隔离
  问题——单独重跑通过，且该测试与本次修改零依赖）
- ruff：全绿

---

## 附：git store corruption 事件记录（2026-09-01，F-3a 期间）

**现象**：`git stash push` 报 `not a valid object` → `git status` 报 `bad object HEAD` →
fsck 发现最近 7+ 个 commit 对象及部分 tree 对象缺失（reflog 中 20 个提交仅 4 个
commit 对象幸存，且无一个历史 tree 完整）。

**影响**：F-2b 刀4（`50a860f`）至 F-2d（`8604089`）共 7 个本地提交的 commit 对象
不可恢复（对象缺失且无任何引用；reflog 文本仍保留完整提交信息可追溯）。

**处置**（内容 100% 保全）：
1. 备份 `.git/logs`、index、main ref 到 `/tmp/git-backup-20260901/`
2. `git checkout-index -a -f` + `git add -A` 从工作树全量重建 index（996 文件）
3. 重建基线提交 `23fc612`（树 = F-2d 全量内容，message 注明恢复性质）
4. F-3a 修改单独提交为 `92304cf`（独立刀次粒度保留）

**注意**：本环境 git 对象库写入存在不稳定性（仓库初始化时即有
"after git store corruption" 基线记录），**强烈建议尽快 `git push` 到远端备份**
（本会话内 fetch 因代理隧道 502 失败，非仓库问题）。历史 broken link 均为
悬空对象，不影响当前 HEAD 链（`git rev-list --count HEAD` = 1 正常）。

---

## F-3b Worker 边界拆分（`b67fd7b`）

### 拆出内容

`worker/amqp.py`（1061 → 744 行）只保留**消费/投递**：队列/路由常量、
IncomingDelivery / EventExchange 协议、PlanningProgressPublisher、
CancellationRegistry、_is_cancelled、handle_delivery 家族、run_worker、_consume、
main。

新模块 `worker/runtime.py`（350 行，组合根）承载：
`CancellationOracle`（Protocol）+ `PsycopgCancellationOracle` +
`WorkerSettings` + `WorkerRuntime` + `build_planning_provider` +
`build_knowledge_provider` + `_configured_embedding_provider` +
`planning_provider_runtime` + `worker_runtime`。

### 关键设计决策

1. **落点是 `worker/runtime.py` 而非 `providers/`**：`build_knowledge_provider`
   依赖 `worker/knowledge.py` 的 4 个符号（RetrievalKnowledgeEvidenceProvider 等）。
   若把工厂下沉到 providers 层会制造 `providers → worker` 反向依赖——正好违反
   F-3a 刚修复的依赖方向纪律。Worker 进程的组装属于 worker 层内部职责，
   "Worker 边界" = 组装（runtime）与传输（amqp）分离。
2. **`CancellationOracle` + `PsycopgCancellationOracle` 随组合根迁移**：
   `worker_runtime` 构造 PsycopgCancellationOracle，若它留在 amqp.py 会产生
   runtime ↔ amqp 循环依赖。取消机制的端口与实现随 runtime 走；
   `CancellationRegistry`（进程内信号）留在消费侧，无循环。
3. **不保留 re-export 垫片**：amqp.py 顶部不 re-export runtime 符号，
   全部消费点显式改指 `trip_agent.worker.runtime`（5 个生产文件 + 4 个测试文件）。

### 消费点迁移

- `routes/api.py`、`agent/tool_capabilities.py`、`worker/agent_processor.py`
  （均为延迟 import，循环依赖风险已随迁移消除，注释同步更新）
- `tests/test_provider_modes.py`：from-import + monkeypatch 目标改指 runtime
  （spy 必须落在工厂所在模块的全局名上才真实生效）
- `tests/test_amqp_worker.py`：9 个函数改指 runtime 模块；修复
  `as runtime:` 与模块变量同名导致的 F823 遮蔽（内部绑定改名 `composed`）
- `tests/test_routes_internal.py`、`tests/test_real_amap_provider.py`：from-import

### 验收

- 针对性 5 文件：**48 passed / 3 skipped**
- 全量 pytest：**2064 passed / 42 skipped**
- ruff：全绿

### 排障记录（双坑相互掩盖）

① 删除 CancellationOracle 时误删 `PlanningProgressPublisher` 的
`@dataclass(slots=True)` 装饰器 → dataclass 构造器消失
（"takes no arguments"）；② 随后 ruff --fix 把已无用的 `dataclass` import
自动删除 → 修复装饰器后出现 `NameError: name 'dataclass' is not defined`。
两个错误叠加导致两轮失败。教训：**改完立即跑 ruff + 最小测试集**，
不要在修复中间态上继续叠加操作。
