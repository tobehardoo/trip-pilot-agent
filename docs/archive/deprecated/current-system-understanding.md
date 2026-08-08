# 当前系统理解（代码基线）

## 本轮收口：Provider 模式、错误与失败事件（2026-08-01）

- [已验证] `WorkerSettings` 以 `PROVIDER_MODE` 明确区分 `DEMO_ONLY`、`REAL_ONLY`、`REAL_WITH_EXPLICIT_FALLBACK`；旧 `DEMO_MODE=true/false` 仅兼容映射到 Demo/严格真实模式，冲突或非法值由 Pydantic 启动校验拒绝。
- [已验证] 构造链为 `WorkerSettings -> build_planning_provider -> AmapPlanningProvider/DemoPlanningProvider -> PlannerPipeline -> handle_delivery -> completion v6/failure v2`。`REAL_ONLY` 不构造 `FallbackPlanningProvider`、`DemoPlanningProvider` 或 `DemoRouteProvider`。
- [已验证] `ProviderErrorCategory`、`RetryingMapProvider`/`RetryingRouteProvider` 与 `ProviderFallbackPolicy` 分别集中错误分类、首次调用加最多两次重试、显式回退判定。鉴权、权限、配置、无效请求、Adapter 与内部错误永不回退；配额和畸形响应只有显式白名单才能回退。
- [已验证] 新 Python producer 只写 `planning-failed-event-v2`；Java `PlanningFailedEventParser` 兼容 v1/v2，任务错误 DTO、持久化事件与 SSE 暴露安全 Provider 字段。成功事件保持 v6，v7 继续拒绝。
- [已验证] completion v6 以可选 `providerProvenance` 承载 requested mode、primary/actual providers、fallback 状态与结构化 operations；`PlanningResult` 是唯一事实来源。局部 Route operation 通过消息内稳定 Activity/Transit ID 关联，Java 持久化后把 operation 重映射为数据库 UUID，任务 API 与 SSE 复用同一终态 JSONB。
- [已验证] 历史 v6 未携带 provenance 时仍可读取，但 Java 不扫描 Activity/Transit 补造 mode 或 fallback。旧版 `DEMO_ONLY` replan 若沿用 AMAP 活动而形成契约无法表达的组合，producer 保持成功但省略 provenance 并记录安全告警；这类结果属于“未记录”，不能称为纯 AMAP 或纯 Demo。

## 本轮收口：Transit、编辑事务与完成事件（2026-07-30）

- [已验证] Transit 的业务关联键是同一日内的 `(fromActivityIndex,toActivityIndex)`，而不是 Transit 数组位置：Java `PlanningCompletedEventParser` 与 Python `ItineraryDay` 允许乱序输入，但要求完整且唯一的相邻端点集合；Python `LocalReplanningProvider` 也按端点查找旧 mode。
- [已验证] 数据库 `V7__create_transit_legs.sql` 只约束 `(itinerary_day_id, leg_order)`，没有端点对唯一索引；因此 `ItineraryService.sourceTransitLocked` 对绕过入站校验写入的重复端点显式拒绝，避免 `findFirst()` 静默错配。正常创建、完成事件、重规划命令与版本复制均由合同保证端点唯一。
- [已验证] `ItineraryEditFlowIntegrationTest` 在 Testcontainers PostgreSQL 触发 activity 首写失败、第二条 Transit 写入失败后，均验证 itinerary version、day、activity、transit 与 idempotency 预留整体回滚；移除触发器后相同 key 可重试并完成绑定 `result_version_id`。
- [已验证] `PLANNING_COMPLETED` 运行时唯一版本是 v6。v7 schema（Transit 成本和扩展 mode）仍是未启用草案；Python v6 wire 排除成本字段，Java 只接受 v1-v6。

> 基线日期：2026-07-30。本文以当前工作区代码为准；工作区含未提交的天气/城市情报改动，因此测试结论不等同于 `HEAD` 的发布结论。置信度标记：`[已验证]`、`[高置信]`、`[文档声明]`、`[待确认]`。

## 项目定位与边界

TripPilot 是一个约束驱动的旅行规划系统：用户约束、可信城市事实和攻略证据进入异步规划任务；Worker 以 AMap 或确定性 Demo Provider 生成多日活动与通勤；Java 服务把结果写成可回滚的行程版本，并向 Vue Web 提供编辑、进度、分享和导出能力。[已验证]

系统不覆盖真实预订、支付、多城市联程或多人协作。Demo 是受支持的本地/无凭据模式，但其 POI、路线和费用均为明确标记的估算；真实 AMap 的凭据、白名单和最终域名验收尚未在本轮运行。[高置信]

## 技术与模块地图

| 区域 | 实现与入口 | 职责 |
| --- | --- | --- |
| Web | `apps/web`；Vue 3、Vite、Pinia、Vue Router、TypeScript | 用户认证、旅行/行程页面、编辑草稿、SSE、地图、分享与导出入口 |
| 业务 API | `apps/travel-server`；Java 21、Spring Boot 3.5、MyBatis、Flyway | REST/SSE、鉴权、Trip/Itinerary/版本、Outbox、完成事件持久化 |
| 规划与知识 | `apps/agent-service`；Python 3.12、FastAPI、Pydantic、OR-Tools | RabbitMQ Worker、AMap/Demo Provider、路线缓存、知识采集与城市情报 API |
| 数据与消息 | PostgreSQL 16、RabbitMQ 4.1、Redis 7.4 | 业务事实/版本、可靠消息、Provider 路线与 POI 缓存 |
| 运维 | `compose.prod.yaml`、Prometheus、GitHub Actions | Compose 编排、健康检查、指标、构建和测试门禁 |

核心模块目录：`trip` 管理旅行与约束；`planning` 创建/追踪任务；`itinerary` 读取、编辑、版本、回滚；`cityintelligence` 和 `guide` 管理规划证据；`infrastructure/mq` 负责 Outbox/RabbitMQ。Flyway 迁移位于 `apps/travel-server/src/main/resources/db/migration`，当前代码可从 V1 升级至 V27。[已验证]

```text
Web 用户请求
  -> Spring REST API (Trip / PlanningTask / Itinerary)
  -> PostgreSQL transaction: trip/task/event/outbox
  -> OutboxPublisher -> RabbitMQ command
  -> Python worker: context + AMap/Demo POI/route + OR-Tools
  -> RabbitMQ progress/completed/failed event
  -> Java parser + PlanningCompletionService transaction
  -> immutable itinerary version + activities + transit legs
  -> persisted task event -> SSE -> Web
```

## 核心领域与持久化关系

`Trip` 属于用户并持有版本化约束；每个 Trip 最多一个 `Itinerary`。`Itinerary` 指向当前 `ItineraryVersion`，而每个版本完整持有 `ItineraryDay`、`Activity`、`TransitLeg`、知识证据和事实影响。活动及 Transit 在每次新版本中重新生成 UUID；版本间用 `parent_version_id` 和 `rollback_from_version_id` 追溯，不共享可变行程行。[已验证]

数据库约束为这一边界提供实际保护：`itinerary.trip_id` 唯一，`(itinerary_id, version_number)` 唯一；`transit_leg` 通过 `(itinerary_day_id, activity_id)` 外键绑定同日活动端点；Transit 顺序唯一；版本父子和当前版本均是同一 itinerary 内的外键。证据：`V5__create_itinerary_versions_and_task_events.sql`、`V7__create_transit_legs.sql`、`V22__add_fact_impacts_and_itinerary_rollback.sql`。[已验证]

## 核心业务链路

### 新建旅行与异步规划

1. `TripController` / `TripService` 保存旅行和约束。
2. `PlanningTaskController` 调用 `PlanningTaskService.create`。该服务校验最多 7 天、城市情报预热、活动锁，并在同一事务中写入 `planning_task`、首个事件、上下文快照和 Outbox 命令。
3. `OutboxPublisherJob` 经 `TransactionalOutboxPublicationAttempt` 将命令发布到 RabbitMQ；Python `worker/amqp.py` 消费后调用 AMap 或 Demo 规划 Provider。
4. Worker 发出进度、完成或失败事件。`PlanningCompletedEventListener` 解析完成消息，`PlanningCompletionService.handle` 校验任务/trace/日期/基线版本，随后在事务内创建首个行程版本或失败记录。
5. `PlanningTaskEventStreamService` 将已持久化事件作为 SSE 提供给前端。[已验证]

Provider 失败只有在 `REAL_WITH_EXPLICIT_FALLBACK` 且集中策略允许时才能回退；`REAL_ONLY` 的 POI、Route 和内部异常均不会调用 Demo。真实 AMap 固定样例已在显式开关下验证 3/3，普通测试不会消耗配额。[已验证]

成功事件仍为 schema v6。新事件的 `providerProvenance.actualProviders` 来自最终 Activity/Transit 来源；纯 AMAP、纯 Demo、局部 mixed 和整单显式 fallback 均由显式字段决定版本 provider。旧 v6 缺少该对象时仅保留历史顶层 provider，不推断 requested mode、primary provider 或 fallback 布尔值。[已验证]

### 编辑、Transit 与局部重规划

`ItineraryController` 暴露预览、单编辑、批量提交和回滚。`ItineraryService.applyEdit`/`applyEdits` 在锁定 itinerary 当前行后加载 `EditableItinerary`；它以 `StoredTransitLeg.id` 定位用户选择的 Transit，并用 `fromActivityId`/`toActivityId` 映射到新版本活动 ID。未受影响的 Transit 原样复制 `polylineJson`、provider、lock、路线 ID、计算时间和 stale 状态；没有依赖列表下标来关联端点。[已验证]

删除或移动活动会将该日标记为 `transitNeedsRefresh`，并在该编辑版本中不复制该日 Transit；预览返回“需局部重规划”的警告。局部重规划任务在 `PlanningTaskService.createReplan` 冻结当前版本和日期范围；`ItineraryService.createReplanVersion` 为每个版本重新建立活动端点，受影响日写入 Worker 返回的 Transit，未受影响日按源端点映射复制。[已验证]

当前没有名为 `EditableTransitLeg`、`TransitLegPersistenceSnapshot` 或 Snapshot Bundle 的专用类型；职责由 `EditableDay`、不可变 `StoredTransitLeg`、端点映射和写入记录共同承担。这不是缺陷本身，但后续修改必须以完整“活动新 ID + Transit 端点重映射 + 原始 `polylineJson` 复制”作为原子边界。[高置信]

### 版本、回滚与事务

编辑、规划完成和回滚都写入新的 `itinerary_version`，最后才更新 `itinerary.current_version_id`；三条写入路径都由 `@Transactional` 包围。`ItineraryVersionService.rollback` 从旧版本复制完整日/活动/Transit/知识，并生成新的 `ROLLBACK` 版本，而非回写旧版本。`PlanningCompletionService` 在同一事务内更新任务终态并持久化完成事件，因此异常会回滚半成品版本。[已验证]

## 外部依赖、运行模式与工程能力

`compose.prod.yaml` 启动 PostgreSQL、Redis、RabbitMQ、Java API、Python Worker、Agent API、知识初始化、Web 和 Prometheus；所有核心服务有健康检查。Java 暴露 Actuator/Prometheus，规划任务有 Micrometer 计数和时长指标；消息携带 `traceId`，Worker 有超时、日志和 RabbitMQ 持久消息。[已验证]

本地无凭据配置默认 `PROVIDER_MODE=DEMO_ONLY`；生产 Compose 默认 `REAL_ONLY` 并要求 AMap Key。生产需要 PostgreSQL/Redis/RabbitMQ/JWT/诊断令牌，真实数据还需要 AMap、浏览器地图及可选天气/模型凭据。开发/生产 Compose 语法、生产冷启动、恢复演练和真实 AMap 固定样例均已有本机证据。[已验证]

## 尚未确认

- 当前 27 项迁移是否已经应用到某个长期运行环境。[待确认]
- 公网域名、HTTPS、AMap 正式白名单、公交路线及长期告警体验。[待确认]
- 当前未提交天气/城市情报改动的需求归属、代码审查和验收状态。[待确认]
- 浏览器 E2E 在本机因 `127.0.0.1:4173` 绑定被拒绝而未能复验；这不证明 E2E 代码失败。[已验证]
