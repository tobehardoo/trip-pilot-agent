# 01 · 系统架构与系统事实模型（System Map）

> 审计性质：PROJECT-WIDE AUDIT ONLY · 2026-08-31 · 本文件不修改任何代码
> 原则：所有节点基于真实调用链验证，标注 `file:line`；无法验证的标注 UNKNOWN / NEED_RUNTIME_VERIFY。

---

## 1. 仓库规模总览（量化基线）

| 模块 | 源码文件 | 源码 LOC | 测试文件 | 测试 LOC | 技术栈 |
|---|---|---|---|---|---|
| apps/travel-server（Java） | 181 main | 42,488 | 71 test | 39,044 | Java 21 + Spring Boot + MyBatis（注解 SQL）+ Flyway（V1–V42） |
| apps/agent-service（Python） | 143 src | 70,708 | 138 test | 86,036 | Python 3.12 + FastAPI + aio-pika + LangGraph + pydantic（另有 benchmarks 1,620） |
| apps/web（前端） | 60 src + 5 e2e | 36,834（vue 18,968 + ts 17,866） | 53 test | 21,778 | Vue 3 + TypeScript + Vite + Pinia |
| scripts / contracts / infra | 20+ py | 10,308 | — | — | 审计/验收/模拟脚本；JSON Schema 契约 37 个；Docker Compose |

全仓源码合计 ≈ **160K LOC**，测试 ≈ **147K LOC**，总量 ≈ **307K LOC**。这不是小项目：三个语言栈、两套消息契约族、42 版数据库迁移。

---

## 2. 系统事实模型（验证后的 System Map）

```
用户 (Browser)
  │  HTTPS (Bearer JWT, refresh cookie)
  ▼
Vue 3 Web  (apps/web/src/pages/TripWorkspace.vue:1314-1426 单页分发; router: apps/web/src/app/router/index.ts:17-35)
  │  fetch + ReadableStream SSE（api.ts:1269-1331，Last-Event-ID 重放 + 3 次重连）
  ▼
Java travel-server  (apps/travel-server/src/main/java/io/github/tobehardoo/trippilot)
  ├─ Controller 层（18 个 *Controller，全部只注入 Service，无跨层直连 Mapper — 已验证）
  ├─ Service 层（ItineraryService 2044 行 / PlanningTaskService 1051 行 等 25+ Service）
  ├─ MyBatis Mapper（32 个，纯 @Select/@Insert 注解 SQL）
  ├─ PostgreSQL（business schema 30 表；42 版 Flyway 迁移）
  ├─ Outbox（OutboxMapper.java:16-65 PENDING→SENT/DEAD + FOR UPDATE SKIP LOCKED; OutboxPublisherJob 1s 轮询）
  │        ▼ 事务性发布（TransactionalOutboxPublicationAttempt 指数退避，10 次上限→DEAD）
  ├─ RabbitMQ（RabbitMessagingConfiguration.java:19-30：trip.command.exchange / trip.event.exchange / trip.dead-letter.exchange）
  ▼
Python agent-service（apps/agent-service/src/trip_agent）
  ├─ worker/amqp.py:947-1023 消费 3 队列（planning.create / planning.cancel / agent.dialog）+ prefetch=1 + publisher confirms
  ├─ worker/processor.py —— 确定性规划管线（候选→骨架→日程→交通→可行性→修复→发射）
  ├─ worker/agent_processor.py —— LangGraph 有界 Agent 循环（agent/graph.py:365-378 decide→act 循环）
  ├─ dialog/service.py —— HTTP 槽位向导（创建模式，同步请求/响应，Redis 7 天）
  ├─ agent/tools.py:551-723 —— 9 个工具（由决策器按状态选择）
  ├─ feasibility/ —— 11 条硬规则 + repair 引擎（6 动作，MAX_REPAIR_ATTEMPTS=3）
  ├─ planning/ —— 纯确定性规则（transport_strategy 有序规则表、daily_schedule、cost_model）
  ├─ guide_intelligence/ —— 攻略导入/OCR/可信事实（LLM 抽取 + 确定性校验）
  ├─ acquisition/ —— 官方源离线采集 CLI（非请求路径）
  ├─ retrieval/ —— 知识库/向量检索（CLI + HTTP，非主链路）
  ▼  事件（planning.completed/failed/review-required/progress + agent.step/ask-user/completed/run-finished）
RabbitMQ (trip.event.exchange)
  ▼
Java 消费者（6 个 @RabbitListener：PlanningCompleted/Failed/Progress/ReviewRequired/AgentDialog/CityIntelligenceRefresh）
  ▼  eventId 幂等 + 乐观锁 version 更新 planning_task / itinerary 表
SSE（PlanningTaskEventHub / AgentDialogEventHub）→ Web
```

## 3. 实际请求链路（已逐段验证）

### 3.1 创建旅行（HTTP 同步）
1. `POST /api/trips` → `TripController.java:33` → `TripService`
2. `POST /api/trips/{tripId}/constraints`（PUT）→ `TripController.java:87` → `TripService` + `TripConstraintValidator`（trip/TripConstraintValidator.java）
3. 地点搜索 `POST /api/trips/places/search` → `PlaceSuggestionController.java:32` → `PlaceSuggestionService` → `HttpAgentPlaceSearchClient`（调用 Python agent-api）

### 3.2 创建规划任务（异步主链路）
1. `POST /api/trips/{tripId}/planning-tasks` → `PlanningTaskController.java:44` → `PlanningTaskService.create`
2. `PlanningTaskService` 写 `planning_task`（QUEUED）+ 事务性写 outbox（`PlanningCommandPublisher`）
3. `OutboxPublisherJob`（1s 轮询）→ `TransactionalOutboxPublicationAttempt`（重试上限 10 次）→ `RabbitPlanningCommandPublisher`（等待 confirm 5s，unroutable 抛异常）
4. RabbitMQ `planning.create.queue` → Python `worker/amqp.py:1018 command_queue.consume`
5. Python `worker/processor.py` 执行规划 → 发布 `planning.completed` / `planning.failed` / `planning.review-required` / `planning.progress`
6. Java 6 个监听器消费 → `PlanningCompletionService`（eventId 查重）→ 写 itinerary 版本 → SSE 推送
7. Web `fetch` SSE 流渲染进度/结果

### 3.3 行程编辑（异步候选验证）
1. `POST /itinerary/edits/preview|commit` → `ItineraryController.java:96,114` → `ItineraryService` → `ItineraryEditRoutingCoordinator.java`（AUTO 路由：本地可处理则同步，否则发 `planning-candidate-validation-command-v2` 到 MQ）
2. Python 验证候选 → `planning.completed`（candidate 语义）→ Java `PlanningCompletionService` → 新版本持久化
3. 回滚：`POST /itinerary/rollbacks` → `ItineraryVersionService`（版本快照恢复，`copyVersion` 逐行 insert）

## 4. 实际规划链路（Python 侧，全部确定性）

```
worker/processor.py handle_delivery
  → infrastructure/amap/planning_provider.py:378 plan()
    → _plan_with_skeleton (planning_provider.py:381-829, 449 行巨型函数)
      → _collect_pois (:1732) 候选召回
      → CandidateRanker.rank (planning/candidates.py:79) 确定性排序
      → build_context_view (planning/context_view.py:178) 上下文解析（天气/预算/出行能力）
      → _emit_day (planning_provider.py:1139) 逐日日程（daily_schedule.plan_day :527）
      → _recommend_transit_or_road (:2053) 交通模式（mode_recommendation.decide_transit_or_road :117）
      → 预算 cost_model / 时长 visit_duration / 天气 weather_policy —— 全部纯函数规则
  → feasibility/validator.py:62-74 11 条硬规则分发（营业时间/连续性/时长/餐食/覆盖/重复）
  → feasibility/repair/engine.py:71,181 有界修复（≤3 次：shift/收紧/删重/移餐/刷新交通腿）
  → worker/processor.py:371-426 _repair_if_needed 循环
  → 发射 planning.completed（确定性，graph 侧 validate_itinerary 一票否决）
```

**关键事实（已核验）**：
- 规划管线 **零 LLM**：所有候选排序、日程、交通、预算、可行性均为确定性代码。
- **OR-Tools 声明但零使用**：`apps/agent-service/pyproject.toml:12` 声明 `ortools==9.14.6206`，src+tests 全库 grep 无任何 `import ortools`/`from ortools`；`worker/amqp.py:151` 的 `CONSTRAINTS_SOLVING` 进度阶段是装饰性的。
- 交通策略由 `planning/transport_strategy.py:9-15` 有序规则表裁决（MOBILITY_SAFETY > WEATHER_SAFETY > BUDGET_CONSTRAINT > COMFORT_ALLOWS_ROAD > DEFAULT）。

## 5. 实际事件链路（Outbox → MQ → Python → 事件 → Java → DB → SSE）

| 事件 | Schema 版本 | 生产方 | 消费方 | 幂等机制 | 失败路径 |
|---|---|---|---|---|---|
| planning-create-command | v4（契约现存 v2/v3/v4） | Java PlanningTaskService | Python command_queue | Java 端任务幂等（PlanningTaskIdempotency） | unroutable→事务回滚；Python 非法命令 reject→DLQ |
| planning-completed-event | **v9/v10/v11 共存**（v1-v8 冻结） | Python processor | PlanningCompletedEventListener→PlanningCompletionService | eventId 查重（PlanningCompletionService.java:109-120） | 解析失败→AmqpRejectAndDontRequeue→DLQ |
| planning-failed-event | v1/v2 | Python | PlanningFailedEventListener→PlanningFailureService | eventId+status 查重（:56-68） | 同上 |
| planning-review-required | v1/v2 | Python | PlanningReviewRequiredEventListener→PlanningReviewService | eventId 查重（:86-96） | 同上 |
| planning-progress-event | v1/v2 | Python | PlanningProgressEventListener→PlanningProgressService | eventId+单调 sequence（:78-82） | 乱序→拒绝→DLQ |
| agent-start/resume-command | v1 | Java AgentDialogCommandService | Python agent_queue | runId 幂等 | **routing-key 无本地绑定声明（依赖外部）** |
| agent-step/ask-user/completed/run-finished | v1 | Python | AgentDialogEventListener | **无显式幂等**（写消息表） | DLQ |
| city-intelligence-refresh-command | v1 | Java 内部 | CityIntelligenceRefreshCommandListener | refreshId 状态机 | DLQ |

**Dead-letter 事实（已核验）**：Java 侧 6 个 @RabbitListener 均无 DLQ 消费者（RabbitMessagingConfiguration.java:95 声明 `planning.dead-letter.queue` 但无监听器）；Python 侧声明+绑定 DLQ（amqp.py:989-1005 `planning.#` / `agent.#`）但 `_consume` 只 attach 了 3 个队列（amqp.py:1018-1023）——**死信队列双向声明、无人消费，死消息只堆积**（P1）。

## 6. 实际数据流（概念到存储）

```
Trip（trip 表）─┬─> planning_task（任务状态机）
                ├─> trip_snapshot（规划上下文快照，PlanningContextSnapshotService）
                ├─> itinerary_version（不可变版本树，parent_version_id）
                │     └─ day ─ activity ─ transit_leg（表：itinerary_day/activity/transit_leg）
                ├─> itinerary_feasibility_report（V33+）
                ├─> itinerary_share（V24 分享 token）
                ├─> guide_fact / guide_source / guide_import（V9/V10/V18 攻略情报）
                ├─> city_source_registry（V20 城市资料源）
                └─> agent_dialog_message（V41 Agent 事件落库）
agent 侧：agent_run/agent_step/agent_checkpoint（持久化）、user_travel_profile（记忆表）
```

## 7. 实际 Agent 执行链（详情见 04-agent-audit.md）

```
用户消息 → AgentDialogCommandService（Outbox）→ agent.dialog.queue → Python handle_agent_delivery（agent_processor.py:534）
  → AgentLoop.build (graph.py:365-378)：decide →(条件边)→ act → decide … ≤8 steps
  → StructuredOutputDecider.decide（LLM 决策：选工具/给答案，graph.py:287-329；失败降级 AskingDecider 规则决策）
  → ToolRegistry.invoke（tools.py:745）→ 9 个工具
  → validate_itinerary 通过 → EMITTED（graph.py:417-420 确定性发射，模型无 emit 工具）
  → AGENT_STEP/AGENT_ASK_USER/AGENT_COMPLETED/AGENT_RUN_FINISHED 事件 → Java 落库 → SSE
```

## 8. 未经运行时验证的部分（UNKNOWN / NEED_RUNTIME_VERIFY）

| 项 | 原因 |
|---|---|
| agent.start/agent.resume 命令实际可达性 | routing-key 未在 Java 配置类声明（AgentDialogCommandService.java:28-30 vs RabbitMessagingConfiguration），仅靠 Python 消费者存在性 | 
| DLQ 堆积规模 | 无监控指标/无消费者，实际堆积量 NEED_RUNTIME_VERIFY |
| 生产环境真实 Provider 链路 | 本地为 DEMO_ONLY 模式；REAL_ONLY 行为基于代码推断 |
| planning_task 永久 RUNNING 的实发频率 | 无超时扫描代码，实发频率 UNKNOWN |

## 9. 架构总结（一句话）

**三栈一体的约束驱动规划系统**：Java 承担可靠性边界（Outbox/幂等/SSE/版本），Python 承担规划智能（确定性内核 + 有界 Agent 外圈），Web 是单页外壳；RabbitMQ 是唯一跨语言解耦点；PostgreSQL 是全系统唯一事实源。
