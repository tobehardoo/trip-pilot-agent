# TripPilot 发布候选验证报告

## 2026-08-01 RC 基线与 completion v6 provenance 增补

- **结论：`RC_BASELINE_READY_WITH_LIMITATIONS`。** 三种显式模式、严格真实零 Demo、错误分类、有限重试、集中 fallback、failure v2 和 completion v6 成功 provenance 全链路均已验证。
- 旧样例 A（Trip `9c5e8a4d-a43f-45b3-b3bc-e2198088c0ed`，Task `53126f21-ed19-470b-8d68-69d7a53dcedc`）是 2026-07-31 旧 `DEMO_MODE=false` 自动回退行为的历史证据；当前 `DEMO_MODE=false` 映射 `REAL_ONLY`，同类失败不得生成 Demo 版本。
- 样例 B 的可追踪 ID 保持不变：Trip `c0f4f199-b4a2-43ad-88ff-e6684d2c0fb0`、Task `ef7e4fc6-0026-4cd9-8cbc-5f85fa9b28df`、Trace `a76eaeed-4f9a-4ba8-be37-e299a2d9bb79`、Outbox `9ed72f2f-2705-4efd-b5e1-4d176df19d9f`、Completion `f428f4bf-8531-463e-ac34-288d3596d21e`、Version `935ee389-efb8-4c19-8be0-4b0b9b56dd52`。
- completion v6 通过可选严格对象表达 pure Demo、pure AMap、未触发 fallback、局部 mixed 与整单 fallback。共享 fixture 的多 Transit 数组故意按 C/A/B 排列；Java 仍按端点语义写为 A/B/C，并把 fallback operation 的消息 ID 重映射为对应数据库 UUID。重复 completion 只产生一个版本/终态事件，API 与 SSE 返回同一结构化 evidence。
- 历史 v6 fixture 不含 provenance 时仍合法；任务 API 的 requested/primary/fallback 字段保持 `null`/缺失，不能补造为纯 AMAP。兼容 `DEMO_ONLY` replan 若保留 AMAP 历史 Activity，同样省略无法合法表达的 provenance。
- 最终自动化：Java 195 passed、Python 502 passed/37 skipped、Web 110 passed；JaCoCo、Flyway V1-V27、两套 Compose、typecheck/build 和 `git diff --check` 通过。真实 AMap 显式运行 3 passed。
- 限制：限流/配额/5xx/非法响应使用 Mock；公交、公网 HTTPS/白名单与长期告警未真实验证；工作区有 105 个跨主题未提交状态项，提交拆分见 `project-delivery-baseline.md`。

日期：2026-07-31

结论：**RC_BASELINE_READY_WITH_LIMITATIONS**

本报告记录运行时工作区和独立 `trip-pilot-rc` Compose 项目的验收证据。它不是干净提交、正式公网部署或长期稳定性认证。报告不包含任何真实密钥、Token、Cookie 或密码。

## 1. 验收环境

- Windows 工作站，Docker Desktop Engine 28.5.1，Docker Compose 2.40.3，Docker Desktop 可用内存约 7.8 GB。
- Java 21、Maven、Python 3.13.9、Node/pnpm；生产镜像标签为 `rc-validation-20260731`。
- RC 项目：`trip-pilot-rc`；Web `http://127.0.0.1:18080`；Prometheus `http://127.0.0.1:19090`。
- 既有 `trip-pilot-prod` 同时存在且未停止、未删除、未使用其卷。

## 2. Git 基线

- 基线 HEAD：`2cbd766 docs: refresh README for V2.5`。
- 开始前工作区已有 36 个已跟踪修改文件和 15 组未跟踪路径；`git diff --check` 通过。
- 本轮只修改真实验收测试/日志可观测性、Web AMap CSP 和直接相关文档；没有 reset、clean、stash、commit 或 push。
- 当前工作区仍然不干净，既有天气、城市情报、Web、Compose、CI 和归档内容按原样保留。

## 3. 服务版本与契约

- PostgreSQL 16.9；生产数据库 Flyway 当前 V27，恢复库验证 27/27 migration 成功。
- Python Worker 的运行完成事件为 v6；Java `PlanningCompletedEventParser` 接受 v1-v6，v7 仍未启用草案。
- Java `mvn --batch-mode -pl apps/travel-server verify` 通过，JaCoCo 门槛满足。
- Web 使用 Vite 生产构建；Compose 镜像为 `rc-validation-20260731`。

## 4. Provider 配置方式

- 生产使用 `PROVIDER_MODE=REAL_ONLY`；旧 `DEMO_MODE=false` 只兼容映射到该严格模式。
- 服务端读取 `AMAP_WEB_SERVICE_KEY`；浏览器地图读取独立的 `VITE_AMAP_WEB_JS_KEY` 和 `VITE_AMAP_SECURITY_CODE`。本报告只记录变量名称和是否配置，不记录值。
- 普通 Provider 测试不消耗外部配额；真实测试必须显式设置 `RUN_REAL_PROVIDER_TESTS=true`。
- 日志审计确认 AMap URL 中的 `key` 被脱敏，未发现完整 AMap Key、浏览器 Key、JWT、内部 Token、密码或 Cookie。

## 5. 固定验收样例

- 样例 A：`apps/agent-service/tests/fixtures/real_provider/guangzhou_day_a.json`，广州一日、4 个固定 POI 查询、步行/驾车路线检查、宽松预算。
- 样例 B：`apps/agent-service/tests/fixtures/real_provider/guangzhou_two_day_b.json`，广州两日、固定安排、必去广东博物馆、预算和交通约束。
- 样例 C：`apps/agent-service/tests/fixtures/real_provider/guangzhou_infeasible_c.json`，预算 50 元，期望 `BUDGET_EXCEEDED`/`NO_FEASIBLE_ITINERARY` 且无部分结果。
- Fixture 只包含非敏感测试输入；Key 只从本地环境变量读取。

## 6. AMap POI 验收

结果：**PASS**。

命令：

```powershell
Set-Location apps/agent-service
python -X utf8 -c "import os,pytest; os.environ['RUN_REAL_PROVIDER_TESTS']='true'; raise SystemExit(pytest.main(['tests/test_real_amap_provider.py','-q']))"
```

结果为 `3 passed in 9.84s`。样例 A 直接真实调用返回 AMap POI、地址和坐标；样例 B 的真实规划使用 AMap 候选；样例 C 使用真实 Provider 规划后明确返回不可行约束。

## 7. AMap 路线验收

结果：**PASS**。

样例 A 直接验证 WALKING 和 DRIVING，距离、时长和 polyline 均为非空正值，`provider=AMAP`、`estimated=false`。样例 B 的完成结果写入 2 段 AMap 步行 Transit，Web 端显示 `1.4km` 和高德地图。公交路线没有纳入本轮真实证据。

## 8. 完整异步 E2E

结果：**PASS**。

样例 B 的 API/数据库证据：

| 字段 | 值 |
| --- | --- |
| `tripId` | `c0f4c4ed-2269-4626-9e75-db6f9a36ce55` |
| `taskId` | `ef7c6841-994c-4099-b9f4-4b3f844f3439` |
| `traceId` | `a76becf5-1d08-4d57-bf31-321ca0fab37a` |
| Outbox `eventId` | `9ed3adce-cb48-4398-a67c-45e20ec8f82c` |
| Completion `eventId` | `f42879f7-f545-56ad-94f3-4518e17c93a2` |
| Result `versionId` | `935ee389-efb8-4c19-8be0-4b0b9b56dd52` |
| SSE | 12 个事件，`TASK_ACCEPTED` 到 `RESULT_PUBLISHING`，终态 `PLANNING_COMPLETED` |
| 最终状态 | `SUCCEEDED`，Worker retry 0，Outbox `SENT` retry 0 |

实际链路为 Web/API → Java → Outbox → RabbitMQ → Python Worker → AMap → completion → Java/PostgreSQL → SSE → Web。

浏览器重新注册并规划的独立 Trip 为 `be20e3e9-acde-4c6e-b378-3dad2e07f6e2`，截图位于 `output/playwright/rc-real-amap-itinerary.png`；CSP 修复后页面没有 AMap 动态脚本阻断。

## 9. Activity 与 Transit 持久化

样例 B 版本 `935ee389-efb8-4c19-8be0-4b0b9b56dd52`：4 个 Activity、2 个 Transit，Activity 和 Transit 来源均为 AMAP；Transit 端点属于同一版本活动，距离、时长、polyline 均存在且非估算。

浏览器 Trip 最终版本 `062e5031-afcb-4a1a-8e7a-df1f8740ce3c` 为版本 5，API 读取结果为 AMAP、4 个 Activity、2 个 Transit。版本历史保持不可变。

## 10. 失败与降级

- 样例 A 全异步结果：**PASS_WITH_FALLBACK**。Trip `9c5e8a4d-a43f-45b3-b3bc-e2198088c0ed`，Task `53126f21-ed19-470b-8d68-69d7a53dcedc` 终态完成，但结果 Provider 为 DEMO，仅 1 个 Activity、0 个 Transit，不计为 AMap 样例通过。
- 样例 C：**PASS**。Trip `51ad9866-c529-4272-b52d-d94216f5126d`，Task `1440c69e-1ea7-4f76-8013-1c2b8913d10b` 终态 `PLANNING_FAILED`，错误 `NO_FEASIBLE_ITINERARY`，冲突 `BUDGET_EXCEEDED`，版本数为 0，行程读取为 404。
- 新增 `planning_provider_fallback` WARNING 日志，包含回退原因和关联 ID；占位命令也通过 `getattr` 容错，不破坏既有回退单测。
- 未消耗无效 Key 或主动触发外部配额故障；Key 缺失、无效 Key、超时、限流、配额、5xx、畸形响应和内部异常均由确定性 fault injection 覆盖，统一进入 failure v2 或显式策略允许的回退路径。

## 11. 生产 Compose 冷启动

结果：**PASS**。

命令：

```powershell
docker compose --env-file .env -p trip-pilot-rc -f compose.prod.yaml up -d --build --wait --wait-timeout 300
docker compose --env-file .env -p trip-pilot-rc -f compose.prod.yaml ps
```

PostgreSQL、RabbitMQ、Redis、Agent API、Agent Worker、Java、Web、Prometheus 全部健康；`knowledge-init` 退出码 0。独立项目使用独立端口、网络和卷，没有清理既有项目数据。

## 12. 服务重启

结果：**PASS**。

- RabbitMQ 重启后 `planning.create.queue`、`planning.completed.queue`、`planning.failed.queue`、`planning.progress.queue` 均 durable，ready/unacked 为 0，各有 1 个消费者。
- Redis `FLUSHDB` 后重启，DBSIZE 从 11 到 0；PostgreSQL 核心计数保持 `trip=6`、`planning_task=6`、`itinerary_version=5`、`activity=17`、`transit_leg=8`、`task_event=51`、`outbox=13`（该快照取自 Redis 演练前后）。
- 整个 `trip-pilot-rc` Compose 重启后 8 个长期服务健康，`knowledge-init` 退出码 0，Flyway 失败记录为 0，浏览器刷新仍读回 AMAP 行程。

## 13. 重复消息与消费幂等

结果：**PASS**。

捕获并重新投递同一完成消息后：重复事件 ID `6850fb75-5815-573f-a019-27ee52e53f2a`，Task `7959dd18-cdb6-416c-b0ac-81c2a3ae6631` 保持 `SUCCEEDED`、retry 0；SQL 查询得到该 Task 版本数 1、重复事件持久化记录数 1。没有生成第二个 itinerary version。

## 14. Worker / Consumer 中断

结果：**PASS**。

- Worker 中断：Task `4299a2a8-0254-48ad-9e54-cb69003336c4` 已写入 `TASK_ACCEPTED`，版本数仍为 0 时停止 Worker；Rabbit 观察到 `planning.create.queue ready=1, unacked=0`。Worker 恢复后 Task `SUCCEEDED` retry 0，最终版本 `062e5031-afcb-4a1a-8e7a-df1f8740ce3c` 为 AMAP，completion event 1，队列归零。
- Java Consumer 中断：Task `7959dd18-cdb6-416c-b0ac-81c2a3ae6631` 在 Worker 运行时停止 Java，`planning.completed.queue ready=1, unacked=0`；Java 恢复后最终版本 `67ee75af-ea61-40b0-8ee1-e728eb76ac47` 持久化成功，队列归零。

## 15. Redis 丢失

结果：**PASS**。只清空 RC Redis 缓存并重启，PostgreSQL 核心数据没有变化；浏览器强制刷新后仍能读取 `be20e3e9-acde-4c6e-b378-3dad2e07f6e2` 的 AMAP 版本和 4 个真实地点。既有 `trip-pilot-prod` 未触碰。

## 16. PostgreSQL 备份与恢复

备份结果：**PASS**。

```powershell
docker exec trip-pilot-rc-postgres-1 pg_dump -U trip_pilot -d trip_pilot -Fc -f /tmp/trip-pilot-rc-20260731.dump
docker cp trip-pilot-rc-postgres-1:/tmp/trip-pilot-rc-20260731.dump output/backups/trip-pilot-rc-20260731.dump
```

- PostgreSQL：16.9；格式：custom `-Fc`；文件：209287 字节；SHA-256：`6f7474bf2acda497abf2164a4a922fc04568e50d0bcc93905007c488cf1bbfdd`。
- 恢复目标：临时空库 `trip_pilot_restore_rc`；`pg_restore --exit-on-error` 成功。
- 恢复 API 使用临时容器、独立端口 18081、仅禁用 Outbox 发布和事件消费；健康为 UP，历史 Trip 与 itinerary API 均返回 200。验证完成后已删除临时容器和恢复库，dump 保留但不应提交 Git。

## 17. 恢复前后数据对比

恢复前后 28 张 `business` 表逐表计数完全一致，无 mismatch。关键计数如下：

| 表 | 原库 | 恢复库 |
| --- | ---: | ---: |
| `trip` | 6 | 6 |
| `planning_task` | 10 | 10 |
| `planning_task_event` | 95 | 95 |
| `outbox_event` | 21 | 21 |
| `itinerary_version` | 9 | 9 |
| `activity` | 33 | 33 |
| `transit_leg` | 16 | 16 |

恢复库还验证了 Flyway `27/27`、未验证外键 0、无效索引 0，并能读取版本 `935ee389-efb8-4c19-8be0-4b0b9b56dd52`。

## 18. 可观测性改动

- `apps/agent-service/src/trip_agent/workflow/planner_pipeline.py` 与 `providers/errors.py` 只在显式模式和集中策略允许时回退，并记录 `planning_provider_fallback`、operation、primary/fallback、reason、retry_count 和 event/trace/task/trip ID。
- `apps/agent-service/tests/test_planner_pipeline_observability.py` 验证回退日志包含原因和关联字段；Web Nginx CSP 测试验证 AMap 动态脚本域名。
- 运行链路可用 `tripId`、`taskId`、`traceId`、Outbox event、completion event 和 result version 追踪；完整 payload 和密钥不进入日志。

## 19. 自动化测试

- Java：`mvn --batch-mode -pl apps/travel-server -am verify`，195 passed，0 failed，JaCoCo 通过。
- Python：`python -m pytest tests -q --basetemp output/pytest-provider-provenance`，502 passed，37 skipped。
- Python 真实：显式 `RUN_REAL_PROVIDER_TESTS=true`，3 passed。
- Python 关注文件 Ruff：通过；全库 Ruff 仍有此前 QWeather 文件的 12 项 E501/UP047，属于未由本轮创建的既有天气改动，未修改。
- Web：`pnpm test` 110 passed；`pnpm typecheck` 通过；`pnpm build` 通过。
- Compose：开发/生产 `docker compose ... config -q` 通过。

## 20. 未通过场景与限制

- **PASS_WITH_FALLBACK**：样例 A 的完整异步结果回退到 DEMO，不能作为纯 AMap 验收通过。
- **NOT_EXECUTED**：公网 HTTPS、正式域名/证书/白名单、长期 soak/告警、真实公交路线。
- **已收口**：AMap 永久错误、Key 无效、超时等 Provider 异常使用稳定分类和 failure v2；规划内部不可恢复异常发布终态后 ack，只有失败事件发布基础设施故障才 nack/requeue。
- **既有工程问题**：全库 Ruff 的 QWeather 12 项规则问题未处理，避免扩大本轮无关天气改动。

## 21. RC 判断与下一步

**RC_BASELINE_READY_WITH_LIMITATIONS**：真实 Provider E2E、生产 Compose 冷启动、恢复/幂等证据和 completion v6 provenance 均满足；工作区仍未拆成授权提交，外部环境限制已明确且没有已证实 P0。

下一推荐切片：先按交付基线的 C1-C8 计划形成可审查提交，再在具备公网 HTTPS 和 AMap 域名白名单的 staging 环境复验，增加真实公交路线、长期运行和告警证据。不要先扩展新的旅行功能，也不要启用 completion v7。
