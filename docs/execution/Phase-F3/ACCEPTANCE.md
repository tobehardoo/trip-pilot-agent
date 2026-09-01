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

---

## F-3c 事件代际终结（`224520a`）

### 范围（收敛计划 §6.1 清单，`docs/execution/Phase-F0/01-system-inventory.md` L127-133）

**Python 侧删除 8 个旧代事件类**（`worker/contracts.py`）：

| 删除类 | 代际 | 说明 |
|---|---|---|
| `PlanningCompletedPayload` | v6/8 | 双分支（amap/demo）payload 根类 |
| `PlanningCompletedEvent` | v6/8 | 双分支事件 |
| `PlanningCompletedPayloadV9` | v9 | V9 payload 基类 |
| `PlanningCompletedEventV9` | v9 | V9 事件 |
| `PlanningCompletedEventV10` | v10 | 事件壳（V10 payload 复用，壳本身死代码） |
| `PlanningReviewRequiredEvent` | v1 | 无权威报告时代 |
| `PlanningFailedPayloadV1` | v1 | 扁平失败 payload |
| `PlanningFailedEventV1` | v1 | 扁平失败事件 |

**契约侧**：`contracts/messaging/` 下 v4–v8 五个 schema `git mv` 入 `legacy/`；
两份 README 同步（v1–v8 全部标注为 legacy，Java runtime fail closed）。

### 关键设计决策

1. **V10 payload 内联重构而非再继承**：`PlanningCompletedPayloadV10`
   原本继承 `PlanningCompletedPayloadV9`，删除基类后将 7 字段
   （provider/itinerary/knowledge/fact_impacts/provider_provenance/evaluation/
   feasibility_report/has_blocker）+ 3 校验器（_normalize_evaluation /
   validate_activity_sources / validate_report_fingerprint / blocker_consistent）
   全部内联，去继承。
2. **replan-command v1/v2 的 `$ref` 迁移**（F-3c 迁移暴露的隐藏依赖）：
   v4–v8 移入 legacy 后，`_local_schema_registry` 只扫 messaging 顶层，
   replan v1/v2 对 v5 `$defs` 的引用全部断裂（Unresolvable）。
   比对确认 v9+ 的 knowledgeEvidence/money 与 v5 逐字节一致，其余
   amapActivity/demoActivity/transitLeg 为 v5 超集（新增 Java 快照字段）
   ——改指 v11 只放宽不收紧，v1/v2 共 7 处 `$ref` 统一改指 v11
   （v2 本已引用 v11 的其余 $defs，此次补齐漏改的 2 处）。
3. **v11 fixture 数据漂移修复**（F-3c 重验模型时暴露的存量问题）：
   - `summary` 计数陈旧：声称 passCount=4，实际 ruleResults 8 条
     NOT_APPLICABLE + 3 条 UNKNOWN → 修正为 0/3/8（模型校验
     "summary counts must match rule results and missing rules"）
   - `itineraryFingerprint` 陈旧：stored `e8e68b07...` 是 v10 时代的
     序列化级指纹，v11 itinerary（TRANSIT leg）复制后未重算。回填为
     序列化级 `82a79af4...`——与 v9/v10 fixture 既有口径一致
     （stored = raw itinerary canonical JSON 的 SHA-256，Java
     `ItineraryFingerprintVerifier.matches` 即校验 raw wire tree）。
     v10 的 stored 指纹经核对与其序列化级输出一致（未动）。
4. **跨语言消费点复核**：Java 测试只读 `contracts/fixtures/`（不读 messaging
   schema 路径），schema 移动零影响；`PlanningCompletedEventParser` 门只
   放行 9/10/11（v1–v8 死分支早已清空），无 Java 改动需求。

### 验收

- 针对性 3 文件：**69 passed**
- 全量 pytest：**2051 passed / 42 skipped**
- ruff：全绿（8 处未使用 import 经 --fix 清理）
- Java `mvn test`：**626 passed / 0 failures / 0 errors**
  （本机 mvn 需绕过 Git Bash 路径转换：用 Windows 路径 + LibericaJDK-21
   手工启动 classworlds；`MAVEN_HOME` 指向 mvnd 的旧配置会干扰 wrapper）
- 提交：`224520a`（14 文件，+115/−399），跨语言单 commit，无半绿窗口

---

## F-3d compose 收敛（`ab6209d`）

### 处置

废弃 `compose.yaml`（删除），CI 与文档统一收敛到 `compose.prod.yaml`。

依据（inventory §6.1 L139 确认）：
1. **重复定义**：postgres/redis/rabbitmq 三服务与 compose.prod 完全重复
2. **唯一消费者死亡**：全仓仅 ci.yml:100 `docker compose --env-file .env.example
   config --quiet` 引用默认 compose；README 及全部运行文档只用 compose.prod
3. **本地构建即失败**：compose.yaml postgres build context 为
   `./infra/docker/postgres`，而 Dockerfile 内 `COPY infra/docker/postgres/init.sql`
   相对仓库根解析——context 内找不到该路径（compose.prod 用仓库根 context 才正确）

### 变更

- 删除 `compose.yaml`（git rm）
- ci.yml 删除默认-compose 校验步骤（L100）；`Validate production Compose`
  + `Validate immutable image overrides` 步骤保留，已覆盖剩余基础设施校验

### 影响面复核

- 全仓 `compose.yaml` 引用：仅 ci.yml:100（已删）+ `docs/archive/acceptance-b14/
  matrix_fault.py:95`（归档字符串，不执行）+ F-0 三份分析文档（记录本刀决策，不改）
- `.env.example` 保留（开发者本地 `.env` 模板；CI prod 校验走 env: 块）
- `.dockerignore` 扩列不在本刀范围（inventory L140 另项，待 F-4+）

### 验收

- `docker compose -f compose.prod.yaml config --quiet`：exit 0（本机 docker 实测）
- ci.yml YAML 解析合法
- 提交：`ab6209d`（2 文件，−55 行）
