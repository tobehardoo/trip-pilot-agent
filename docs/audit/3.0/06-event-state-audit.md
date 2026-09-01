# 06 · 事件 / Outbox / 状态机审计

> 审计性质：PROJECT-WIDE AUDIT ONLY · 2026-08-31

---

## 1. 消息拓扑（已核验）

### 1.1 交换机/队列（Java 声明：RabbitMessagingConfiguration.java:19-30）
- `trip.command.exchange`（Direct）→ queue：planning.create / planning.cancel / city-intelligence.refresh / agent.dialog.event
- `trip.event.exchange`（Direct）→ queue：planning.progress / planning.completed / planning.review / planning.failed
- `trip.dead-letter.exchange`（Topic）→ queue：planning.dead-letter.queue（:95）

### 1.2 生产方
| 命令/事件 | 生产方 | 发布方式 |
|---|---|---|
| planning.create / replan / candidate-validation | Java PlanningTaskService → PlanningCommandPublisher | Outbox → TransactionalOutboxPublicationAttempt（指数退避，上限 10 次 → DEAD）→ RabbitPlanningCommandPublisher（confirm 5s） |
| agent.start / agent.resume | Java AgentDialogCommandService.java:28-30 | Outbox 同链路 |
| planning.progress / completed / failed / review-required | Python worker/processor.py / agent_processor.py | aio-pika publisher confirms（amqp.py:694-701,840,908） |
| agent.step / ask-user / completed / run-finished | Python agent_processor.py:59-64 | 同上 |

### 1.3 消费方
- Java（6 个 @RabbitListener，**全部无 DLQ 消费者**）：PlanningCompleted / PlanningFailed / PlanningProgress / PlanningReviewRequired / AgentDialog / CityIntelligenceRefresh
- Python（amqp.py:1018-1023 仅 3 个队列）：command_queue（create/replan/candidate-validation）、cancel_queue、agent_queue（start/resume）

---

## 2. 可靠性机制盘点

| 机制 | 实现 | 证据 |
|---|---|---|
| Outbox 事务性 | 业务事务内写 outbox；SKIP LOCKED 轮询 | OutboxMapper.java:16-65 |
| 发布重试 | 指数退避，10 次上限 → DEAD | TransactionalOutboxPublicationAttempt.java:56-61 |
| 发布确认 | 等待 broker confirm 5s；unroutable 抛异常 | RabbitPlanningCommandPublisher.java:37-49 |
| 消费 ACK | Python：成功 ack / 业务异常 nack-requeue / 非法命令 reject | amqp.py:728,731,774 |
| 死信 | 所有 Java queue 配 DLX；Python 绑定 `planning.#`/`agent.#` | RabbitMessagingConfiguration.java:255-259 / amqp.py:1004-1005 |
| 幂等（完成/失败/评审） | eventId 查重 + 乐观锁 version | PlanningCompletionService.java:109-120 / PlanningFailureService.java:56-68 / PlanningReviewService.java:86-96 |
| 幂等（进度） | eventId + 单调 sequence | PlanningProgressService.java:78-82 |
| 幂等（Agent 事件） | **无显式幂等**（写 agent_dialog_message 表） | — |
| 任务级幂等 | PlanningTaskIdempotency（创建任务幂等键） | planning/PlanningTaskIdempotency.java |

---

## 3. 四个可靠性问题的答案

### Q1：如果事件重复发送怎么办？
- **planning.completed/failed/review**：eventId 查重（PlanningCompletionService.java:109-120），重复事件被忽略。✅
- **planning.progress**：eventId+sequence 单调检查（PlanningProgressService.java:78-82），乱序/重复拒绝。✅
- **agent 系列事件**：无幂等键，重复写入 agent_dialog_message（消息表按自增 id 追加，重复会造成 UI 重复消息）。⚠️ P2
- **底层兜底**：planning_task 更新用乐观锁 `version = version + 1 WHERE version=#{expectedVersion}`（PlanningTaskMapper.java:134），并发更新只赢一次。✅

### Q2：消费者处理成功但 ACK 失败怎么办？
- Java：@RabbitListener 默认 auto-ack；方法返回即 ack。若处理成功后 JVM 崩溃在 ack 前，broker 会重新投递 → eventId 查重兜底（**重复消费无害**）。✅
- Python：显式 ack（amqp.py:731）。若 ack 前崩溃 → requeue 重投 → 处理侧有幂等（candidate 发射按 fingerprint 校验，contracts 契约测试覆盖）⚠️ 部分。
- 结论：**整体设计是 at-least-once + 幂等收敛**，正确。

### Q3：如果 Python 成功但 Java 没收到完成事件怎么办？
- **没有补偿机制**。planning_task 停在 RUNNING，Java 无超时扫描、无状态恢复任务（P1，见 §5.3）。唯一出口：`InternalPlanningDiagnosticsController.java:42` 手动触发 FAILED 任务的 retry（且仅限 FAILED 状态，RUNNING 不可触发）。
- 死信队列无人消费，事件丢失 = 任务永久卡死。**这是全系统最显著的可靠性缺口**。

### Q4：如果任务一直 RUNNING 怎么恢复？
- **当前无自动恢复**。RUNNING 状态无 TTL、无 heartbeat、无补偿 Job。
- 手工路径：无。
- 建议：a) 为 RUNNING 加 `updated_at` 超时扫描 Job（如 10min 无进度 → 标记 FAILED/STALE）；b) 消费 DLQ 并把可识别任务转为 FAILED；c) 重放 outbox DEAD 记录。

---

## 4. 状态机审计

### 4.1 planning_task 状态全集（实测）
**Java 写入**：QUEUED → RUNNING → WAITING_USER / SUCCEEDED / FAILED / CANCELLED
| 转换 | 证据 |
|---|---|
| QUEUED → RUNNING | PlanningProgressService.java:83-85 + PlanningTaskMapper.java:156-157（乐观锁 version） |
| QUEUED/RUNNING → WAITING_USER | PlanningReviewService.java:119（:145-149 UPDATE） |
| QUEUED/RUNNING → SUCCEEDED/FAILED | PlanningTaskMapper.java:135 updateTerminalStatus |
| QUEUED/RUNNING/CANCELLING → CANCELLED | :163-170 |
| WAITING_USER → CANCELLED | :184-191（B12 显式放弃） |

**SQL 中存在但 Java 从不写入的死状态**：CREATED / RETRYING / CANCELLING / STALE
- `existsActiveByTripId` 活跃集含 CREATED/RETRYING/CANCELLING（PlanningTaskMapper.java:199）→ **活跃判断与实际状态机不一致**（P1 DEFECT：可能放行并发任务或误判活跃）
- `findRecentFailures` 过滤 `IN ('FAILED','STALE')`（:217）→ STALE 永不出现，诊断查询失效（P2）
- `WAITING_USER` 无 SUCCEEDED 路径（updateTerminalStatus :135 仅 QUEUED/RUNNING 可转终态）→ **评审候选被接受后任务如何到 SUCCEEDED？** UNKNOWN / NEED_RUNTIME_VERIFY（疑点：WAITING_USER 后接受评审可能走独立路径）。

### 4.2 状态与事件一致性
- 终态元数据双源：status 在表，错误码/provider/评估从 outcome 事件重建（PlanningTaskService.java:725-754）→ 若事件落库失败，元数据与状态脱节（P2）。
- Agent run 状态（AgentRunFinishedStatus：STOPPED/FAILED/EXPIRED/ANSWERED，worker/contracts.py:1827）与 planning_task 状态是两个独立状态机，前端需分别处理（OBSERVATION）。

### 4.3 状态机判定
| 问题 | 判定 |
|---|---|
| 非法状态转换 | 有（活跃集包含永不写入的状态；WAITING_USER 终态路径存疑） |
| 双重状态来源 | 有（表 + outcome 事件重建） |
| Java/Python 状态定义不一致 | 大体一致（六值对齐），Python 契约只引用其中部分 |
| 永久 RUNNING | **是**（无超时/补偿，P0-P1 级可靠性风险） |
| 状态与事件/DB 不一致 | 可能（无一致性校验 Job） |

---

## 5. 核心发现（带证据）

| # | 发现 | 证据 | 级别 |
|---|---|---|---|
| 1 | **死信队列双向声明、无人消费**：Java 6 监听器无 DLQ；Python 声明绑定 DLQ 但不 consume | RabbitMessagingConfiguration.java:95 / amqp.py:989-1005 vs 1018-1023 | **P1** |
| 2 | **任务永久 RUNNING 无恢复**：无超时扫描/补偿 Job | PlanningProgressService.java:83-85（仅置 RUNNING） | **P1** |
| 3 | **agent.start/resume 路由键无 Java 本地绑定声明**，依赖外部 Python 消费者 | AgentDialogCommandService.java:28-30 vs RabbitMessagingConfiguration.java:138-176 | **P1** |
| 4 | 活跃状态集与实际状态机不一致（死状态参与活跃判断） | PlanningTaskMapper.java:199 | **P1** |
| 5 | WAITING_USER → SUCCEEDED 路径缺失（updateTerminalStatus 仅 QUEUED/RUNNING） | PlanningTaskMapper.java:135 | P2/NEED_VERIFY |
| 6 | 进度乱序被直接拒绝进 DLQ（可修复事件被丢弃） | PlanningProgressService.java:80-81 | P2 |
| 7 | Agent 事件无幂等 | agentdialog/ 无查重逻辑 | P2 |
| 8 | STALE 死状态污染诊断查询 | PlanningTaskMapper.java:217 | P2 |
| 9 | 终态元数据双源（表 + 事件重建） | PlanningTaskService.java:725-754 | P2 |
| 10 | Python 取消协作双通道：DB oracle（amqp.py:232）+ 进程内 registry（:269） | amqp.py:232,269 | P2 |

## 6. 建议（3.0 方向）

1. **DLQ 消费者（P0）**：Java 或 Python 任一侧消费 `planning.dead-letter.queue`，按任务 id 转 FAILED + 记录错误码；不自动重放（避免风暴），提供手动重放端点。
2. **RUNNING 超时扫描（P1）**：每 5min 扫描 `status=RUNNING AND updated_at < now()-10min` → 置 FAILED(ERROR_STUCK)，保证状态机收敛。
3. **统一活跃状态集（P1）**：从 SQL 删除 CREATED/RETRYING/CANCELLING/STALE 死值或补齐写入。
4. **agent.start/resume 绑定声明（P1）**：在 RabbitMessagingConfiguration 显式声明队列绑定，消除对隐式约定的依赖。
5. **Agent 事件幂等（P2）**：消息表加 (run_id, seq) 唯一键。
