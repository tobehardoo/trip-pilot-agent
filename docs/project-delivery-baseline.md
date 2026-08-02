# 项目交付基线

## Provider 策略基线（2026-08-01）

- [已验证] 本地默认 `DEMO_ONLY`、production 默认 `REAL_ONLY`；`REAL_ONLY` 缺 Key 启动失败且不会构造/调用任何 Demo Provider。显式 fallback 只在 `REAL_WITH_EXPLICIT_FALLBACK` 和集中白名单允许时发生。
- [已验证] 永久 Provider/内部规划失败统一发布 `planning-failed-event-v2`，Java 兼容 v1/v2 并复用 `planning_task.error_code/error_message` 与 `planning_task_event.payload`，未新增迁移。
- [已验证] completion v6 可选 provenance 已贯通 Python、Schema/共享 fixture、Java 持久化/API/SSE 与 Web；历史 v6 无字段时保持未记录，v7 继续拒绝，数据库仍为 V27。
- [已验证] 最终门禁：Java 195、Python 502（另 37 skipped）、Web 110、两套 Compose、typecheck/build、`git diff --check` 全部通过；显式真实 AMap 3 passed。
- [高置信] 发布策略结论为 `RC_BASELINE_READY_WITH_LIMITATIONS`；历史 `DEMO_MODE=false` 的 fallback 样例仅是旧策略证据，不代表当前 `REAL_ONLY`。当前工作区尚未形成授权提交。

## 真实 Provider 与发布候选基线（2026-07-31）

- [已验证] `DEMO_MODE=false` 的隔离 `trip-pilot-rc` 生产 Compose 可冷启动；8 个长期容器健康，`knowledge-init` 成功，Flyway V27。
- [已验证] 真实 AMap 样例 B 的完成版本、Activity 和 Transit 均带 AMAP 来源；Web 浏览器可见 4 个地点、2 段步行路线和高德地图。
- [已验证] 样例 C 以 `NO_FEASIBLE_ITINERARY`/`BUDGET_EXCEEDED` 失败且版本数为 0；样例 A 的真实链路回退到 DEMO，已归类为 `PASS_WITH_FALLBACK`。
- [已验证] RabbitMQ at-least-once 演练覆盖重复完成事件、Java Consumer 停机积压、Worker `TASK_ACCEPTED` 后停机回队；Redis 清空和整栈重启不改变 PostgreSQL 核心数据。
- [已验证] 备份 `output/backups/trip-pilot-rc-20260731.dump` 可恢复到隔离库，28 张业务表计数一致，恢复 API 可读取 AMAP 版本 5。

本基线是运行时 RC 证据，不是干净提交认证；工作区已有的天气、城市情报、Web、Compose、CI 和归档变更仍按归属处理。

## Transit、编辑事务与 MQ 契约基线（2026-07-30）

- [已验证] 同日 Transit 以活动端点对关联而非数组下标；乱序合法，重复端点非法，持久化层会拒绝被直接写入的歧义源数据。
- [已验证] 编辑写入在 PostgreSQL 单事务内完成：activity 首写失败或第二条 Transit 写入失败都会回滚版本、子记录和幂等预留；故障解除后原 idempotency key 生成一个 `COMPLETED` 结果版本。
- [已验证] 完成事件运行时版本固定为 v6，并已覆盖“含 Transit 的 Python wire -> v6 JSON Schema”；Java 拒绝 v7。v7 仅是未启用契约草案。

## 编辑与 Transit 稳定性基线（2026-07-30）

- [已验证] `POST /api/trips/{tripId}/itinerary/edits` 与 `/edits/commit` 现在将 `Idempotency-Key` 绑定到规范化请求哈希。相同语义的重试返回首次生成的版本，即使其后已有更新版本。
- [已验证] 重用 key 发送不同请求、以及命中历史空白哈希记录，均返回 `409 IDEMPOTENCY_KEY_CONFLICT`；客户端不能把它当作安全重试。
- [已验证] 失败请求不会残留 `COMPLETED` 幂等记录；同 key 并发只生成一个版本，异 key 的乐观并发竞争保留 `ITINERARY_VERSION_CONFLICT` 语义。
- [已验证] 局部重规划中的 Transit 锁绑定到活动端点身份而不是 Transit 数组位置；版本中的活动与 Transit 继续使用新 UUID，并保持外键同日约束。
- [待确认] 该基线仍不代表干净提交或生产发布认证：天气、城市情报、Web、Compose、CI 与归档文档的现有工作区变更未被本切片修改或验收。

## 当前可做什么

- 在 Demo 模式下创建旅行、提交结构化约束并发起异步规划；在显式真实配置下可运行受控 AMap 规划。
- 查看持久化进度/SSE、版本化活动与 Transit、知识/城市情报证据。
- 预览并提交活动与 Transit 编辑，生成新版本；可局部重规划、比较和回滚版本。
- 使用版本固定的匿名分享，以及 PDF/ICS 导出。
- 通过生产 Compose 定义部署 PostgreSQL、Redis、RabbitMQ、Java、Python、Web 与 Prometheus。

以上能力由当前代码、Flyway V1–V27、Python 502 项通过、Web 110 项通过以及 Java `verify` 195 项通过支持。[已验证]

## 当前不能承诺什么

- 不能把样例 A 的 DEMO 回退结果表述为纯 AMap 通过；必须看 itinerary/provider 与活动/Transit 来源。
- 不能在没有公网 HTTPS、凭据、白名单、真实地图域名和长期运行证据时承诺公开生产可用。
- 本轮只验证广州及步行/驾车路线，公交模式和其它城市仍未纳入真实验收。
- 不应把工作区未提交的天气/城市情报改动称作已交付功能。

## 测试与风险概览

| 链路 | 本轮证据 | 主要剩余风险 |
| --- | --- | --- |
| Python Worker/Provider/契约 | 502 passed，37 skipped；真实显式测试 3 passed | 兼容 mixed replan 缺 provenance 时只能标为未记录 |
| Java 编辑/版本/Transit | 195 passed；V1→V27；mixed 三 Transit/双 fallback/UUID 重映射通过 | 读路径 N+1 尚未测量 |
| Web 单测、类型、构建 | 110 passed；typecheck/build 通过 | 本切片仅增加最小来源标签，未做新浏览器 E2E |
| Compose 配置与 RC 运行 | 开发/生产 `config --quiet` 通过；独立生产栈健康 | 公网域名/证书未验 |

## 适用性判断

- **Demo：适合受控演示。** 代码和多层自动化支持这一结论，但当前工作区应先归属。
- **受控 RC：已验证。** 真实 AMap、异步链路、Compose、重启、消息幂等和备份恢复均有本机证据。
- **公开部署：有条件适合。** 还需完成公网 HTTPS、域名白名单、公交路线和长期运行告警验收。
- **继续新增功能：暂不适合。** 应先按下述提交计划冻结并审查跨主题工作区。

下一阶段完成后，预计达到：干净可识别提交基线、跨主题 diff 可独立回滚、关键 E2E 可在指定 staging 环境复跑。

## 2026-08-01 工作区逐文件归属审计

审计命令为 `git status --short --untracked-files=all`。当前共有 105 项：67 个 tracked 修改、38 个 untracked 正式代码/fixture/文档；无 `UNKNOWN`。状态是当前工作区事实，不表示已经授权提交。

| 文件 | 状态 | 所属主题 | 是否与其他主题混合 | 是否适合提交 | 推荐提交 |
| --- | --- | --- | --- | --- | --- |
| `.env.example` | `M` | Provider/QWeather/部署配置 | 是 | 是（拆 hunk 后） | C1/C4/C7 |
| `.github/workflows/ci.yml` | `M` | 跨端 CI 门禁 | 是 | 是（独立审查） | C7 |
| `.gitignore` | `M` | 备份与测试生成物规则 | 是 | 是（拆 hunk 后） | C2/C7 |
| `apps/agent-service/src/trip_agent/application/replan_service.py` | `M` | Transit 重规划 + completion provenance | 是 | 是（拆 hunk 后） | C2/C5 |
| `apps/agent-service/src/trip_agent/domain/planning/protocols.py` | `M` | PlanningResult provenance | 否 | 是 | C2 |
| `apps/agent-service/src/trip_agent/guide_intelligence/city_intelligence.py` | `M` | QWeather/城市情报 | 否 | 是（本切片未改） | C4 |
| `apps/agent-service/src/trip_agent/guide_intelligence/service.py` | `M` | QWeather/城市情报 | 否 | 是（本切片未改） | C4 |
| `apps/agent-service/src/trip_agent/infrastructure/amap/errors.py` | `M` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py` | `M` | Provider 策略 + completion provenance | 是 | 是（拆 hunk 后） | C1/C2 |
| `apps/agent-service/src/trip_agent/infrastructure/demo/planning_provider.py` | `M` | Provider 策略 + completion provenance | 是 | 是（拆 hunk 后） | C1/C2 |
| `apps/agent-service/src/trip_agent/providers/_amap_route.py` | `M` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/src/trip_agent/providers/_amap_route_failures.py` | `M` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/src/trip_agent/providers/map.py` | `M` | Provider 策略 + completion provenance | 是 | 是（拆 hunk 后） | C1/C2 |
| `apps/agent-service/src/trip_agent/worker/amqp.py` | `M` | Provider failure + completion provenance | 是 | 是（拆 hunk 后） | C1/C2 |
| `apps/agent-service/src/trip_agent/worker/contracts.py` | `M` | Provider failure + completion provenance | 是 | 是（拆 hunk 后） | C1/C2 |
| `apps/agent-service/src/trip_agent/worker/processor.py` | `M` | Provider failure + completion provenance | 是 | 是（拆 hunk 后） | C1/C2 |
| `apps/agent-service/src/trip_agent/workflow/planner_pipeline.py` | `M` | Provider failure + completion provenance | 是 | 是（拆 hunk 后） | C1/C2 |
| `apps/agent-service/tests/guide_intelligence/test_city_intelligence.py` | `M` | QWeather/城市情报 | 否 | 是（本切片未改） | C4 |
| `apps/agent-service/tests/test_amqp_worker.py` | `M` | Provider failure + completion provenance | 是 | 是（拆 hunk 后） | C1/C2 |
| `apps/agent-service/tests/test_local_replanning.py` | `M` | Provider failure + completion provenance | 是 | 是（拆 hunk 后） | C1/C2 |
| `apps/agent-service/tests/test_map_provider.py` | `M` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/test_messaging_contract_schemas.py` | `M` | Provider failure + completion provenance | 是 | 是（拆 hunk 后） | C1/C2 |
| `apps/agent-service/tests/test_planning_context_v2.py` | `M` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/test_planning_worker.py` | `M` | Provider failure + completion provenance | 是 | 是（拆 hunk 后） | C1/C2 |
| `apps/agent-service/tests/test_route_provider.py` | `M` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/test_workflow_and_application.py` | `M` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/cityintelligence/CityIntelligencePlanningPreflightService.java` | `M` | QWeather/城市情报 | 否 | 是（本切片未改） | C4 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/infrastructure/mq/PlanningCompletedEvent.java` | `M` | Java completion v6 parser/event model | 否 | 是 | C2 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/infrastructure/mq/PlanningCompletedEventParser.java` | `M` | Java completion v6 parser/event model | 否 | 是 | C2 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/infrastructure/mq/PlanningFailedEvent.java` | `M` | Provider failure v2 | 否 | 是 | C1 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/infrastructure/mq/PlanningFailedEventParser.java` | `M` | Provider failure v2 | 否 | 是 | C1 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/itinerary/ItineraryController.java` | `M` | 编辑幂等/Transit 版本安全 | 否 | 是（本切片未改） | C5 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/itinerary/ItineraryMapper.java` | `M` | 编辑幂等/Transit 版本安全 | 否 | 是（本切片未改） | C5 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/itinerary/ItineraryService.java` | `M` | 编辑/Transit + provenance 版本写入 | 是 | 是（拆 hunk 后） | C3/C5 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningCompletionService.java` | `M` | completion 持久化/UUID 重映射 | 否 | 是 | C3 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningFailureService.java` | `M` | Provider failure v2 | 否 | 是 | C1 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningProgressService.java` | `M` | Provider failure API/SSE/进度 | 否 | 是 | C1 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskController.java` | `M` | Provider failure API/SSE/进度 | 否 | 是 | C1 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskEventMapper.java` | `M` | Provider failure API/SSE/进度 | 否 | 是 | C1 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskService.java` | `M` | failure DTO + success provenance API | 是 | 是（拆 hunk 后） | C1/C3 |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/cityintelligence/CityIntelligencePlanningPreflightServiceTest.java` | `M` | QWeather/城市情报 | 否 | 是（本切片未改） | C4 |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/infrastructure/mq/PlanningCompletedEventParserTest.java` | `M` | Java completion v6 parser/event model | 否 | 是 | C2 |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/infrastructure/mq/PlanningFailedEventParserTest.java` | `M` | Provider failure v2 | 否 | 是 | C1 |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/itinerary/ItineraryEditFlowIntegrationTest.java` | `M` | 编辑幂等/Transit 版本安全 | 否 | 是（本切片未改） | C5 |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/itinerary/ItineraryServiceTransitEditTest.java` | `M` | 编辑幂等/Transit 版本安全 | 否 | 是（本切片未改） | C5 |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningCompletionFlowIntegrationTest.java` | `M` | failure/完成/Transit 集成回归 | 是 | 是（拆测试方法后） | C1/C3/C5 |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/support/PlanningCompletedEventFixture.java` | `M` | Java completion v6 parser/event model | 否 | 是 | C2 |
| `apps/web/nginx.conf` | `M` | Web 地图/运行配置 | 否 | 是（本切片未改） | C6 |
| `apps/web/src/components/GuideIntelligencePanel.vue` | `M` | QWeather/城市情报 | 否 | 是（本切片未改） | C4 |
| `apps/web/src/components/PlanningProgress.vue` | `M` | Provider failure API/SSE/进度 | 否 | 是 | C1 |
| `apps/web/src/components/TripDetail.vue` | `M` | 来源标签 + 编辑/天气 UI | 是 | 是（拆 hunk 后） | C3/C4/C5/C6 |
| `apps/web/src/components/TripMap.vue` | `M` | Web 地图/运行配置 | 否 | 是（本切片未改） | C6 |
| `apps/web/src/lib/api.ts` | `M` | Provider/API + 编辑/天气 Web 类型 | 是 | 是（拆 hunk 后） | C1/C3/C4/C5 |
| `apps/web/tests/GuideIntelligencePanel.test.ts` | `M` | QWeather/城市情报 | 否 | 是（本切片未改） | C4 |
| `apps/web/tests/PlanningProgress.test.ts` | `M` | Provider failure API/SSE/进度 | 否 | 是 | C1 |
| `apps/web/tests/TripDetailItineraryEditing.test.ts` | `M` | 来源标签 + 编辑/天气 UI | 是 | 是（拆 hunk 后） | C3/C4/C5/C6 |
| `apps/web/tests/TripMap.test.ts` | `M` | Web 地图/运行配置 | 否 | 是（本切片未改） | C6 |
| `apps/web/tests/nginx-config.test.ts` | `M` | Web 地图/运行配置 | 否 | 是（本切片未改） | C6 |
| `compose.prod.yaml` | `M` | Provider/QWeather/生产 Compose | 是 | 是（拆 hunk 后） | C1/C4/C7 |
| `contracts/messaging/planning-completed-event-v6.schema.json` | `M` | completion v6 provenance/共享 fixture | 否 | 是 | C2 |
| `docs/README.md` | `M` | 跨主题当前基线/RC 文档 | 是 | 是（功能提交后） | C8 |
| `docs/api.md` | `M` | 跨主题当前基线/RC 文档 | 是 | 是（功能提交后） | C8 |
| `docs/architecture.md` | `M` | 跨主题当前基线/RC 文档 | 是 | 是（功能提交后） | C8 |
| `docs/archive/README.md` | `M` | 历史证据/归档索引 | 否 | 是（本切片未改） | C8 |
| `docs/decision-record.md` | `M` | 跨主题当前基线/RC 文档 | 是 | 是（功能提交后） | C8 |
| `docs/deployment.md` | `M` | 跨主题当前基线/RC 文档 | 是 | 是（功能提交后） | C8 |
| `docs/release.md` | `M` | 跨主题当前基线/RC 文档 | 是 | 是（功能提交后） | C8 |
| `apps/agent-service/src/trip_agent/guide_intelligence/qweather.py` | `??` | QWeather/城市情报 | 否 | 是（本切片未改） | C4 |
| `apps/agent-service/src/trip_agent/providers/errors.py` | `??` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/src/trip_agent/providers/retry.py` | `??` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/fixtures/real_provider/guangzhou_day_a.json` | `??` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/fixtures/real_provider/guangzhou_infeasible_c.json` | `??` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/fixtures/real_provider/guangzhou_two_day_b.json` | `??` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/guide_intelligence/test_qweather.py` | `??` | QWeather/城市情报 | 否 | 是（本切片未改） | C4 |
| `apps/agent-service/tests/test_planner_pipeline_observability.py` | `??` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/test_planning_failed_event_v2.py` | `??` | Provider failure v2 | 否 | 是 | C1 |
| `apps/agent-service/tests/test_provider_error_mapping.py` | `??` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/test_provider_fallback_policy.py` | `??` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/test_provider_modes.py` | `??` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/test_provider_provenance.py` | `??` | completion v6 provenance/共享 fixture | 否 | 是 | C2 |
| `apps/agent-service/tests/test_provider_retry_policy.py` | `??` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/agent-service/tests/test_real_amap_provider.py` | `??` | Provider mode/retry/fallback/真实验收 | 否 | 是 | C1 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/itinerary/EditRequestFingerprint.java` | `??` | 编辑幂等/Transit 版本安全 | 否 | 是（本切片未改） | C5 |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/itinerary/EditRequestFingerprintTest.java` | `??` | 编辑幂等/Transit 版本安全 | 否 | 是（本切片未改） | C5 |
| `apps/web/src/components/TripWeatherTimeline.vue` | `??` | QWeather/城市情报 | 否 | 是（本切片未改） | C4 |
| `apps/web/src/composables/useItineraryDraft.test.ts` | `??` | 编辑幂等/Transit 版本安全 | 否 | 是（本切片未改） | C5 |
| `apps/web/src/composables/useItineraryDraft.ts` | `??` | 编辑幂等/Transit 版本安全 | 否 | 是（本切片未改） | C5 |
| `apps/web/tests/TripWeatherTimeline.test.ts` | `??` | QWeather/城市情报 | 否 | 是（本切片未改） | C4 |
| `contracts/fixtures/planning-completed-event-v6/completion-v6-demo.json` | `??` | completion v6 provenance/共享 fixture | 否 | 是 | C2 |
| `contracts/fixtures/planning-completed-event-v6/completion-v6-explicit-fallback-mixed.json` | `??` | completion v6 provenance/共享 fixture | 否 | 是 | C2 |
| `contracts/fixtures/planning-completed-event-v6/completion-v6-legacy-amap.json` | `??` | completion v6 provenance/共享 fixture | 否 | 是 | C2 |
| `contracts/fixtures/planning-completed-event-v6/completion-v6-multi-transit-mixed.json` | `??` | completion v6 provenance/共享 fixture | 否 | 是 | C2 |
| `contracts/fixtures/planning-completed-event-v6/completion-v6-real-only-amap.json` | `??` | completion v6 provenance/共享 fixture | 否 | 是 | C2 |
| `contracts/fixtures/planning-failed-event-v2/provider-authentication-failed.json` | `??` | Provider failure v2 | 否 | 是 | C1 |
| `contracts/messaging/README.md` | `??` | failure v2 + completion v6 契约索引 | 是 | 是（拆 hunk 后） | C1/C2 |
| `contracts/messaging/planning-failed-event-v2.schema.json` | `??` | Provider failure v2 | 否 | 是 | C1 |
| `docs/adr/provider-mode-failure-and-fallback-policy.md` | `??` | Provider policy + completion provenance ADR | 是 | 是（随对应提交拆 hunk） | C1/C2 |
| `docs/archive/p0-execution-evidence.md` | `??` | 历史证据/归档索引 | 否 | 是（本切片未改） | C8 |
| `docs/archive/p0-local-amap-validation.md` | `??` | 历史证据/归档索引 | 否 | 是（本切片未改） | C8 |
| `docs/archive/post-v2.5-p0-p2-execution-plan.md` | `??` | 历史证据/归档索引 | 否 | 是（本切片未改） | C8 |
| `docs/current-state-assessment.md` | `??` | 跨主题当前基线/RC 文档 | 是 | 是（功能提交后） | C8 |
| `docs/current-system-understanding.md` | `??` | 跨主题当前基线/RC 文档 | 是 | 是（功能提交后） | C8 |
| `docs/next-stage-execution-plan.md` | `??` | 跨主题当前基线/RC 文档 | 是 | 是（功能提交后） | C8 |
| `docs/project-delivery-baseline.md` | `??` | 跨主题当前基线/RC 文档 | 是 | 是（功能提交后） | C8 |
| `docs/release-candidate-validation-report.md` | `??` | 跨主题当前基线/RC 文档 | 是 | 是（功能提交后） | C8 |
| `apps/agent-service/output/pytest-provenance-baseline/` | ignored/generated | 修改前 pytest 可再生成输出 | 否 | 否 | 不提交 |
| `apps/agent-service/output/pytest-provider-provenance/` | ignored/generated | 最终 pytest 可再生成输出 | 否 | 否 | 不提交 |

被忽略输出仍保留在磁盘；新增 `**/output/pytest-*/` 只修正追踪规则，没有清理文件。敏感检查未读取根 `.env` 的值；该文件已被忽略。未发现可提交的私钥、明文生产凭据或 `*.dump`；磁盘上的 1 个已验证备份和 63 个日志均被忽略并继续保留，不纳入提交。

## 精确提交拆分方案

1. **C1 Provider policy/failure v2**：Provider mode、错误映射、retry/fallback、failure v2 Schema/fixture、Java failure consumer、任务失败 API/SSE 与对应测试。
2. **C2 completion v6 contract/provenance**：`PlanningResult`、producer、v6 Schema、五个共享 fixture、Java event/parser、兼容/非法组合测试和 pytest 输出规则的对应 hunk。
3. **C3 completion persistence/API/Web**：`PlanningCompletionService`、`ItineraryService` 中 provider/ID remap hunk、`PlanningTaskService` success DTO hunk、mixed 集成测试、Web 结构化类型与来源标签。
4. **C4 QWeather/city intelligence**：所有天气、城市来源与 Guide Intelligence 代码/测试；本轮只回归，不混入 C1-C3。
5. **C5 itinerary idempotency/transit safety**：指纹、编辑事务、draft、Transit lock/identity 与对应测试；从 `ItineraryService`、`TripDetail.vue`、`api.ts` 按 hunk 拆出。
6. **C6 Web map/runtime**：地图、天气时间线之外的 nginx/CSP 和 Web 独立测试。
7. **C7 production config/CI**：`.env.example`、`compose.prod.yaml`、CI 与非 pytest 的生成物/备份规则；按 Provider/QWeather hunk复核后提交。
8. **C8 docs/audit**：当前文档、归档索引、RC 报告与本审计，最后提交，确保引用的 commit SHA/测试计数与前七个提交一致。

跨主题文件必须使用 `git add -p` 或等价的非交互 patch 拆分：`.env.example`、`.gitignore`、`compose.prod.yaml`、`worker/amqp.py`、`worker/contracts.py`、`worker/processor.py`、`planner_pipeline.py`、`replan_service.py`、`test_messaging_contract_schemas.py`、`ItineraryService.java`、`PlanningTaskService.java`、`PlanningCompletionFlowIntegrationTest.java`、`api.ts`、`TripDetail.vue` 及跨主题文档。当前未 stage、未 commit、未 push。
