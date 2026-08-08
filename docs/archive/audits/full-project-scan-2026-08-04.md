# TripPilot 全盘工程审计报告

**审计基线**：分支 `codex/plan-evaluation-weather-integration` @ `6c663dc9fb476b6241bb69e94c16479636c1d0a2`｜PR #27｜日期 2026-08-04
**性质**：只读扫描，未修改任何代码/配置/文档/Git 历史，未做任何部署

---

## 1. 执行摘要

1. **真实状态**：代码与测试体系健康，5 项远端 CI 在当前精确 SHA 上全部通过；本地复跑 Python 547 通过、Java 43 单元 + 32 集成通过、Web 126 通过，均与文档数字一致。
2. **业务闭环**：创建规划、失败处理、编辑、局部重规划、回滚、PlanEvaluation、天气/城市情报、分享/导出、SSE 均有可追踪且被集成测试覆盖的调用链，**不是占位实现**。
3. **PR 状态**：#27 仍为 Open + Draft，head=`6c663dc` 与本地/远端分支一致，CI run 30879603024 运行在精确 head 上，之后无新提交；`MERGEABLE` / `CLEAN`，未合并。
4. **最大阻塞（非代码问题）**：staging 因**外部资源与配置缺失**而 BLOCKED——无 staging 主机/registry/七类镜像 digest/完整 staging env/域名 TLS/备份告警入口。当前 `.env` 仅 20 个变量，缺 10 项 staging 条件。
5. **S-01～S-13**：全部 BLOCKED，本轮无法获得任何 staging 验收证据。
6. **可观测性短板**：Java 服务**零应用日志**（无 Logger/MDC/request-id），异常只进 HTTP 响应不进日志；Python 仅纯文本日志。无法从日志定位"某请求为何失败 / 消息在哪丢失"。
7. **运营风险**：Outbox 重试**无上限、无死信**，毒消息会永久占用发布槽位。
8. **安全**：无 SQL 注入、无 v-html、SSRF 防护扎实、Git 历史无真实 Secret；但内部诊断 token 有默认值退化风险、compose.prod 默认 `AGENT_INTERNAL_TOKEN=JWT_SECRET` 凭据复用。
9. **功能缺口**：PlanEvaluation 的 `interestMatch` 维度返回固定基线 80（占位），兴趣匹配未真正实现；五维评分中有 1 维失真。
10. **完成度**：工程完成度高，但**产品完成度不是 100%**——见模块矩阵；天气不随版本绑定、评估 UX 缺口等为已知取舍。
11. **技术债**：集中在体积（ItineraryService 1547 行、TripDetail.vue 1611 行等 god class）而非正确性；无 TODO 堆积、无调试输出、无循环依赖。
12. **结论**：`LOCAL_CODE_HEALTHY`、`REMOTE_CI_VERIFIED` 为 YES；`READY_FOR_STAGING`/`READY_TO_MERGE`/转 Ready 均为 **NO/BLOCKED**（被外部资源阻断，且按项目自身门禁不可跳级）。
13. **建议**：保持 PR Draft、保持冻结；唯一优先动作是补齐 staging 前置资源并通过 `validate_staging_env.py`。

---

## 2. 精确仓库状态

| 项 | 值 | 依据 |
| --- | --- | --- |
| 工作目录 | 预期仓库 `trip-pilot-agent`（git 根） | remote = github.com/tobehardoo/trip-pilot-agent.git |
| 当前分支 | `codex/plan-evaluation-weather-integration` | `git rev-parse --abbrev-ref HEAD` |
| HEAD SHA | `6c663dc9fb476b6241bb69e94c16479636c1d0a2` | 与任务给定候选 SHA 完全一致 |
| 工作区 | 干净（0 变更、无未跟踪、无 stash） | `git status --porcelain` 为空 |
| 本地↔远端跟踪分支 | 一致（0 ahead / 0 behind，同一 SHA） | `git rev-list --left-right --count` |
| PR #27 | **Open + Draft**，base=`main`，head=`6c663dc`，未合并，`MERGEABLE`/`CLEAN` | `gh pr view 27`（baseRefOid=`2cbd766`） |
| PR head ↔ 远端分支 | 一致（`refs/pull/27/head` = `6c663dc`） | `git ls-remote origin refs/pull/27/head` |
| CI | run 30879603024，headSha=`6c663dc`，event=pull_request，5 job 全 SUCCESS | `gh run view` / `gh pr checks` |
| CI 之后的新提交 | 无（headRefOid 仍为 `6c663dc`；run 创建于 05:05:26Z，最后提交 05:05:07Z） | `gh pr view` commits |
| 分支相对 main | 30 commits ahead，157 文件，+15912/−467，无 merge commit | `git log --oneline --merges` 为空 |
| 本地 `main` | **7 个未推送提交**（`c256176` ahead origin/main） | `git branch -vv`（卫生项，非当前分支） |
| gitleaks 配置 | `.gitleaks.toml` + `.gitleaksignore`（3 条历史 UUID 误报）合理 | 文件核对 |
| 异常提交 | 分支内无调试/临时 commit；target/ 中残留**旧结构**的 surefire 报告（`LayeredArchitectureTest`、`share.api.*` 等，当前源码已不存在） | target 报告 vs 源码 diff |

---

## 3. 模块状态矩阵

> 完成度是工程估算（代码/测试/契约贯通度），**不是产品验收比例**。

| 模块 | 状态 | 完成度 | 测试 | 主要风险 | 证据 |
| --- | --- | ---: | --- | --- | --- |
| Web 前端 | PARTIAL | 90% | 126 通过（24 文件）+ e2e | 天气不随版本绑定；`queueRecommendedLongWalks` 自动预置草稿副作用；SharedItineraryPage 无竞态防护 | `apps/web/src/` 各组件；子代理报告 |
| Java 服务 | PARTIAL | 90% | 36 测试类 | **零应用日志**；Outbox 无界重试 | `GlobalApiExceptionHandler`、`TransactionalOutboxPublicationAttempt.java:43` |
| Python Agent | COMPLETE | 92% | 547 通过 | interestMatch 占位；无 broker 级消费测试 | `worker/processor.py`、`evaluation/rules.py` |
| 数据库迁移 | COMPLETE | 100% | 空库 V1→V27 干净迁移（本轮实测） | 无迁移 checksum/数量断言测试 | `db/migration/V1..V27` |
| 消息契约 | COMPLETE | 95% | 契约测试 + 共享 fixture | v7 草案无消费方；schema 与 parser 双轨漂移风险 | `contracts/messaging/` |
| RabbitMQ 拓扑 | COMPLETE | 95% | 解析/发布/死信集成测试 | 无 outbox 调度器端到端测试 | `RabbitMessagingConfiguration.java`（5 规划队列+refresh+DLQ） |
| Redis 使用 | COMPLETE | 90% | 2 测试（FakeRedisClient） | 无真实 Redis 集成测试；cache 读写逻辑两处重复 | `providers/redis_cache.py`、`map.py`、`_amap_route.py` |
| Provider 层 | COMPLETE | 95% | 71 函数（MockTransport） | 无真实 AMap 定时回归（`test_real_amap_provider` 需 key） | `providers/*` |
| 天气与城市情报 | COMPLETE | 95% | qweather 9 + service 13 | fxLink 已修复；无跨城市缓存污染（因无缓存） | `guide_intelligence/qweather.py`、`city_intelligence.py` |
| PlanEvaluation | PARTIAL | 88% | 19 函数 + benchmark 8/8 | **interestMatch=80 占位**；无 end-to-end 断言"回滚后新 evaluation 替换旧值" | `evaluation/rules.py:368-383` |
| 规划工作流 | COMPLETE | 95% | 26 worker + 24 context v2 | OR-Tools solver 无解分支未测试 | `workflow/planner_pipeline.py` |
| OR-Tools | PARTIAL | 85% | 3 测试（feasible 走求解器；2 个 infeasible 走短路） | 求解器 no-solution 解释路径未测 | `planning/optimization.py:140-141` |
| RAG / Knowledge | COMPLETE | 90% | 30 函数 + pgvector 集成 | CI 覆盖率覆盖此模块；CLI/registry 测试有 Windows 权限问题（非代码缺陷） | `retrieval/*` |
| 行程版本 | COMPLETE | 95% | 23 编辑集成测试 | 版本不可变性已确认（append-only） | `ItineraryVersionMapper.java`（仅 INSERT） |
| 编辑与局部重规划 | COMPLETE | 95% | 23 + replan 测试 | 编辑队列前端无界；SSE 完成重放触发重复拉取 | `ItineraryEditFlowIntegrationTest` |
| 回滚 | COMPLETE | 92% | 部分覆盖 | 无"回滚后 evaluation 替换"端到端断言 | `itinerary_rollback` 表 |
| 分享 | COMPLETE | 90% | 2 测试 | 限流被 X-Forwarded-For 伪造绕过 | `share/PublicShareRateLimiter.java` |
| PDF / ICS | COMPLETE | 80% | 1 测试（happy path） | 无失败/越权/版本校验测试 | `export/ItineraryExportFlowIntegrationTest` |
| SSE | COMPLETE | 92% | 事件流集成测试 + Web 重连测试 | Hub 无每任务订阅上限；流正常关闭未带终态会误报失败 | `PlanningTaskEventHub.java`、`TripWorkspace.vue:909` |
| 身份认证与授权 | COMPLETE | 95% | 6+4 测试 | 内部诊断 token 默认值退化 | `security/*`、`application.yml:36,38` |
| Outbox | COMPLETE | 88% | 4 unit + 发布集成 | **无死信、无 max attempts** | `TransactionalOutboxPublicationAttempt.java` |
| 幂等 | COMPLETE | 95% | 并发/重放测试 | — | `EditRequestFingerprintTest`、`PlanningTaskIdempotencyTest` |
| 缓存 | COMPLETE | 85% | 有 | 无真实 Redis 集成 | `providers/redis_cache.py` |
| 可观测性 | **PARTIAL/BROKEN** | 30% | PlanningMetrics | **Java 零日志**；无 trace 贯穿日志；无告警/dashboard | grep 结果 |
| 配置管理 | COMPLETE | 90% | validate_staging_env 12/12 | `.env.example` 死变量；AGENT_INTERNAL_TOKEN 复用 JWT_SECRET | `.env.example:92-95`、`compose.prod.yaml:69` |
| 部署 | COMPLETE（Compose） | 90% | CI infrastructure job | staging 未部署 | `compose.prod.yaml` |
| 备份/恢复 | SCAFFOLDED | 20% | `postgres_backup.py` 存在 | 无备份/恢复演练证据；S-11 BLOCKED | `scripts/postgres_backup.py` |
| 安全 | PARTIAL | 85% | security 测试 | 见 findings（token 默认值、限流伪造、凭据复用） | 安全代理报告 |
| CI | COMPLETE | 95% | 5 job 全绿 | Actions 未 SHA pin；覆盖率门禁未覆盖 Python 核心模块 | `.github/workflows/ci.yml` |
| 文档 | PARTIAL | 80% | markdown 链接 306 文件有效 | README 版本身份过期；多处计数/变量过时 | 文档代理报告 |

---

## 4. 核心链路检查

- **创建规划（场景 A）**：`TripService`（事务内建 trip）→ `PlanningTaskService.enqueue`（**同一 @Transactional 内**写 `planning_task` + `outbox_event`，`PlanningTaskService.java:200`）→ `OutboxPublisherJob` 轮询 → `TransactionalOutboxPublicationAttempt` 发布 → `RabbitPlanningCommandPublisher` → RabbitMQ `planning.create` → Python `worker.amqp` 消费 → `process_planning_create`（Provider→RAG→**PlanEvaluator**）→ 完成事件 v6（含 provenance+evaluation）→ Java `PlanningCompletedEventListener` → `PlanningCompletionService`（幂等/身份/日期/版本校验→ `itinerary_version` append-only 持久化 → SSE）→ Web `TripWorkspace` 渲染。**闭环成立**，集成测试 `PlanningCompletionFlowIntegrationTest`（32 例）本轮实测通过。
- **规划失败（场景 B）**：Python `planning_failed_event()` 生成 v2 结构化事件（category/provider/operation/retryable/fallback/safeMessage），Java `PlanningFailureService` 持久化 terminal + `PlanningProgressService` 丢弃 terminal 后的迟到 progress；不可重试不 requeue。前端可结束 loading。不泄露内部异常（safeMessage）。**成立**。
- **编辑（场景 C）**：SHA-256 请求指纹 + reserve-then-complete 幂等（`ON CONFLICT DO NOTHING`→有界 UPDATE）、`FOR UPDATE` 锁、不可变版本、Activity/Transit UUID 重映射、失败全量回滚（触发器测试）。**成立**，`ItineraryEditFlowIntegrationTest` 23 例。
- **局部重规划（场景 D）**：原版本引用校验（stale 版本拒绝）、新版本生成、Transit 重建、evaluation 重新计算（`process_planning_replan` 也调用 evaluator）。**成立**。
- **回滚（场景 E）**：生成新版本 + `itinerary_rollback` 记录；不修改旧版本。**成立**（但前端无"回滚后 evaluation 替换"端到端断言）。
- **PlanEvaluation（场景 G）**：生产闭环（evaluator 在 processor 中调用、经 v6 契约传输、Java 重映射 UUID 并持久化、Web `PlanEvaluationPanel` 展示、benchmark 8/8 确定性）。**部分接入的例外**：`score_interest_match` 固定返回 80（`rules.py:368-383`），即五维中一维为占位。
- **天气/城市情报（场景 F）**：QWeather GeoAPI/now/7d/historical 四接口 + `fxLink` 保留（经 `88028aa` 修复，允许域仅 `qweather.com`，非法/非字符串/非默认端口被忽略）→ AMap 城市情报合并 → 可信事实 → 前端天气时间轴/地图日期联动。无跨城市缓存污染（无缓存）。**成立**。
- **分享/PDF/ICS**：分享 token 32 字节高熵 + SHA-256 哈希存储 + 脱敏 + 过期/吊销；PDF/ICS 导出 happy path 有测试。**成立，但测试薄**。
- **SSE**：Last-Event-ID 重连 + eventId 去重 + 终态检查 + 请求序号过滤晚到事件；Web 端有重连/abort/越界测试。**成立**；残余风险为 Hub 每任务订阅无上限、正常关闭未带终态可能误判失败。

---

## 5. Findings

### Critical
**未发现**有直接证据的 Critical 级问题（无数据破坏、无真实 Secret 泄露、无已利用越权路径）。

### Important

- **I-1｜Java travel-server 零应用日志** — 影响：无法从服务端日志定位"规划请求为何失败 / 消息在哪丢失 / Provider 为何回退"，可观测性名存实亡。证据：全仓 `Logger`/`@Slf4j`/`log.*`/MDC/request-id 过滤器均 **0 命中**；`GlobalApiExceptionHandler` 不记录异常。验证：grep 全仓。阻塞 staging：否（staging 验收 S-10 需日志能力，实际会 FAIL）。建议：引入 SLF4J + 日志过滤器注入 traceId，异常处理器记录 WARN/ERROR。
- **I-2｜Outbox 重试无上限、无死信** — 影响：持续发布失败的消息永久 PENDING 并每 1s 轮询重试，占用 `BATCH_SIZE=50` 槽位；毒消息造成队列积压。证据：`TransactionalOutboxPublicationAttempt.java:43-49`（retryCount 无限 +1，仅延迟封顶 300s）；`outbox_event.status` 仅 `PENDING|SENT`（V4 migration）。验证：读代码 + 迁移约束。阻塞 staging：否，但建议 P0 前修复。建议：加 `max_attempts` + DEAD 态 + 指数退避封顶。
- **I-3｜内部诊断 token 默认值退化 + 端点 permitAll** — 影响：非 compose 直启（`java -jar`）漏配两个 internal token 时退化为公开已知值 `local-development-only`，且 `/api/internal/diagnostics/**` 匿名可达，可读取失败任务（含 error_message）并触发重试。证据：`SecurityConfig.java:36` permitAll；`application.yml:36,38` 默认 `local-development-only`（恰好 ≥16 字符，不 fail-fast）。阻塞 staging：否（compose.prod 用 `:?` 强制），但建议 P0 修复默认值为 fail-fast。
- **I-4｜PlanEvaluation `interestMatch` 为固定基线 80（占位）** — 影响：宣称的"兴趣匹配"维度未真正实现，五维综合分对偏好不敏感。证据：`evaluation/rules.py:368-383` 返回常量 80，注释明确"intentionally basic until rich activity tags are available"。验证：读代码。阻塞 staging：否；阻塞产品验收中"兴趣匹配"声明的可信度。建议：在产品需求明确前如实标注，或补做类别标签后实现。
- **I-5｜compose.prod 默认 `AGENT_INTERNAL_TOKEN=JWT_SECRET`（凭据复用）** — 影响：默认部署下内部 token 与 JWT 签名密钥相同；内部 token 经容器内网明文传输（`compose.prod.yaml:68`），泄露即伪造任意用户 JWT。证据：`compose.prod.yaml:69,149`；`.env.example:59-60` 要求 distinct。阻塞 staging：**建议** staging 前移除默认回退。
- **I-6｜CI 覆盖率门禁未覆盖 Python 核心模块** — 影响：`--cov-fail-under=80` 只作用于 retrieval/acquisition/guide_intelligence；**providers/worker/planning/evaluation** 等关键模块无机器化覆盖率底线。证据：`.github/workflows/ci.yml:66-68`。建议：扩展 cov 目标或拆分 job。
- **I-7｜Java 覆盖率门禁仅 LINE ≥80%，且绑定 verify** — 影响：无 branch/instruction 门槛；本地 `mvn test` 不触发 check，容易产生"绿但不达门禁"。证据：`pom.xml:117-164`。建议：加 branch 门槛并让 `test` 也校验。

### Normal

- **N-1｜分享限流可被伪造 `X-Forwarded-For` 绕过** — `ItineraryShareController.java:68-74` 取首段；nginx `$proxy_add_x_forwarded_for` 透传客户端头。建议从受信代理末段取 IP。
- **N-2｜CitySource 审核端点无角色控制** — `CitySourceController.java:37-44` 仅需登录，任意用户可 APPROVE/ENABLE 全局城市源。缺授权模型。
- **N-3｜GitHub Actions 未按 SHA pin**（`ci.yml` 中 checkout@v4、setup-java@v4 等）— 供应链风险。
- **N-4｜前端 `queueRecommendedLongWalks` 自动预置草稿副作用** — `TripDetail.vue:260-275` 每次行程加载/回滚都会暂存"推荐交通"草稿，覆盖用户步行选择；测试将其当作期望行为。
- **N-5｜版本切换时 evaluation 瞬时窗口与静默隐藏** — `TripWorkspace.vue:868-880` + `322-325`：重载期间版本并发变化时 evaluation 可能不显示；USER_EDIT/ROLLBACK 版本（planningTaskId=null）evaluation 直接置 undefined，无法回退展示父版本评估。
- **N-6｜SSE Hub 无每任务订阅上限** — `PlanningTaskEventHub.java:28` map 仅 30min 超时兜底；高并发下内存线性增长。
- **N-7｜Web DTO 重复声明** — `api.ts:526-536` 与 `ItineraryActionsPanel.vue:6-16` 定义相同接口对，易漂移。
- **N-8｜天气数据不随版本绑定** — 天气来自最新导入而非规划时版本；`TripWeatherTimeline.vue:42-48` 第三级回退 `observedAt.slice(0,10)` 可能把"当前天气"钉到抓取日。需确认产品意图。
- **N-9｜本地 `main` 7 个未推送提交** — `c256176` ahead origin/main；与审计无关但需人工确认是否有意。
- **N-10｜`planning-completed-event-v7` 无消费方草案** — 零代码引用，与 v6 双轨漂移风险。
- **N-11｜stale surefire 报告（`LayeredArchitectureTest` 等）** — target/ 含旧结构测试报告，证明架构曾从分层演变为扁平；当前无 ArchUnit。可清理 target/ 或补架构测试。
- **N-12｜文档偏差多项**（见第 10 节）。
- **N-13｜`@Transactional` 测试与基类 TRUNCATE 叠加**（`CitySourceRegistryFlowIntegrationTest`）— 数据隔离语义不纯。
- **N-14｜OR-Tools 求解器 no-solution 分支未测** — `optimization.py:140-141`；infeasible 解释仅测预求解短路。
- **N-15｜无 Outbox 调度器 + 真实 Rabbit/DB 端到端测试** — `PlanningCompletedRabbitIntegrationTest` 关闭了 outbox 调度；发布器重试/死信入队路径无联合测试。

### Minor

- **M-1** Dockerfile 基础镜像浮动 tag（由 prod digest 强制缓解）。
- **M-2** Web CSP `unsafe-inline/unsafe-eval` + 无 HSTS（`nginx.conf:19`）。
- **M-3** 开发 `compose.yaml` 端口全绑定 + 默认密码 `local-development-only`。
- **M-4** `TripDashboard.vue` 硬编码默认值（广州/3000）+ 唯一 `any`（`:110`）。
- **M-5** 内部 token 容器内网明文（叠加 I-5 升级）。
- **M-6** cache/HTTP helper 重复逻辑（`map.py:338-360` vs `_amap_route.py:149-171`；`city_intelligence.py` vs `qweather.py`）。
- **M-7** 多文件重复"事实类别"字符串常量（跨 Java/Python）。
- **M-8** `useItineraryDraft` 编辑队列无上限、SSE 订阅 map 无容量上限。

### 待验证问题（无直接证据，不作为正式 finding）
- PR #27 描述中"Markdown 链接覆盖 306"与 roadmap "297"为不同时点口径（文档代理已核实）。
- `workflow` 测试中一处 `assert provider is not None` 弱断言（`test_workflow_and_application.py:88`）。

---

## 6. 测试与验证结果（本轮实际执行）

| 命令（工作目录） | exit | 结果 | 说明 |
| --- | ---: | --- | --- |
| `uv run python -m pytest -q --basetemp=<隔离目录>`（agent-service） | 0 | **547 passed, 37 skipped** | 与文档声称一致；直接跑出现的 11 error 为 Windows pytest 临时目录权限问题（`_pytest/pathlib.py:176 PermissionError`），隔离 basetemp 后全部转绿 |
| `uv run python -m pytest -q`（同前，14 个 hermetic 文件子集） | 0 | 121 passed | evaluation/providers/qweather/contract schema |
| `mvn test -Dtest=PlanningCompletedEventParserTest,...`（travel-server） | 0 | 34+5+4=43 passed | 纯单元契约测试 |
| `mvn test -Dtest=PlanningCompletionFlowIntegrationTest`（travel-server） | 0 | 32 passed，Flyway **V1→V27 空库干净迁移** | Testcontainers + Docker，验证完成闭环与迁移完整性 |
| `./node_modules/.bin/vue-tsc --noEmit`（web） | 0 | 通过 | `pnpm` 命令被 Anaconda 坏 shim 劫持（`D:\Anaconda3\...pnpm.cjs` 不存在），**属本地环境问题**，非项目缺陷 |
| `./node_modules/.bin/vitest run`（web） | 0 | **24 files / 126 passed** | 与文档声称一致 |
| `python -m unittest discover -s scripts/tests` | 0 | 12/12 | release tooling |
| `python scripts/check_markdown_links.py` | 0 | 306 文件链接有效 | — |
| gitleaks | — | 未执行（本地未安装二进制；CI repository-safety job 已含 gitleaks 并通过） | — |
| 完整 Java 套件（`mvn verify`） | — | 未本地跑（CI java job 已在 head 上跑过，5/5 SUCCESS）；已实测代表性子集 | — |
| Playwright e2e | — | 未本地跑（需浏览器/服务器，CI web job 已含 `pnpm test:e2e` 并通过） | — |

**关键**：以上数字与 release.md / audit 文档声称一致，且远端 CI 在当前精确 head 上全部成功，交叉验证通过。

---

## 7. 安全状态

- **认证**：JWT HS256 + secret 强制 ≥32 字符 + access 15min TTL + refresh 30d；refresh 轮换 + 服务端吊销 + SHA-256 哈希存储；cookie httpOnly/SameSite=Strict。**达标**。
- **授权**：所有业务端点从 JWT subject 取 userId，Mapper 层 `owner_id` 过滤；SSE 订阅前校验归属；分享 token 32 字节 + 哈希存储 + 脱敏。IDOR 被 SQL 层拦截。**达标**；例外见 I-3/N-2。
- **输入安全**：无 `${}` SQL 拼接（全 `#{}`）；无 `v-html`；SSRF 多层防护（HTTPS-only、禁 localhost、DNS 全公网校验、重定向逐跳重验、QWeather fxLink 白名单）；无 path traversal/zip bomb。**达标**。
- **配置**：CORS 未放行（同源反代）；actuator 仅 health/prometheus；prometheus 内网绑定。见 I-5/N-1/M-2。
- **Secret**：Git 历史无真实 secret（gitleaks 扫描 + `git log -p` 复核）；`.env` 从未入库；`.env.example` 为占位。**达标**。
- **供应链**：Python `==` 精确 pin + uv.lock；pnpm-lock 锁定；运行时均为当前支持版本；Actions 未 SHA pin（N-3）；Dockerfile 浮动 tag 由 prod digest 强制缓解。
- **网络边界**：compose.prod 中 DB/Redis/RabbitMQ 不暴露端口；web 绑定 127.0.0.1；prometheus 127.0.0.1。**达标**；开发 compose 端口全绑定为 Minor。

---

## 8. 数据与一致性状态

- **migration**：V1–V27 连续、无重复、无已发布修改；本轮在空库实测 V1→V27 全量干净迁移；老库升级路径有专项测试（`TripPaceMigrationIntegrationTest`）。**通过**。
- **事务**：创建任务+写 outbox 同事务；完成事件持久化 `@Transactional`；编辑/回滚失败有全量回滚触发器测试。**通过**。
- **幂等**：planning task（trip_id+idempotency_key 唯一 + 单活动任务部分索引）、编辑（指纹+reserve-then-complete）、completion/failure 事件按 eventId 去重。**通过**。
- **Outbox**：事务内写入 ✓、幂等发布 ✓（markSent 守卫）、重试 ✓（但**无上限**，I-2）、**无死信**、无状态恢复任务（重启后 PENDING 自动继续，符合设计）。**部分达标**。
- **版本不可变性**：`itinerary_version` 仅 INSERT（append-only），UPDATE 只移动 `current_version_id` 指针；父子版本 FK。**通过**。
- **Transit/Activity 引用**：completion 时 source UUID→DB 持久化 ID 重映射（含 fallback op、evaluation entity），歧义映射拒绝。**通过**。
- **并发**：编辑锁、planning 快照一致性、refresh 轮换并发均有测试。**通过**。
- **回滚安全性**：生成新版本不修改旧版本；未发现半完成状态残留（有 DB 失败回滚测试）。

---

## 9. 部署与 staging 状态

**已具备**：生产 Compose（`compose.prod.yaml`，7 服务 + knowledge-init + prometheus）；不可变镜像 digest 强制（CI `infrastructure` job 校验 9 个服务均解析 `@sha256`）；healthcheck/restart/network/volume 齐全；CI 构建并 smoke-test 生产 Compose（DEMO_ONLY）；`validate_staging_env.py` 强制 7 类 digest、REAL_ONLY、空 fallback、Secure Cookie、有界代理；备份脚本 `postgres_backup.py` 存在。

**未具备 / BLOCKED**：
- 无 staging 主机/集群/Docker context/SSH alias；无批准 registry 与认证；无七类完整 `registry/repo@sha256` 引用。
- 当前 `.env` 仅 20 个变量（缺 `POSTGRES_IMAGE`/`REDIS_IMAGE`/`RABBITMQ_IMAGE`/`TRAVEL_SERVER_IMAGE`/`AGENT_SERVICE_IMAGE`/`WEB_IMAGE`/`PROMETHEUS_IMAGE`、`PROVIDER_MODE`、`PROVIDER_FALLBACK_CATEGORIES`、`TRUSTED_PROXY_CIDR`）——audit 5 声明的 10 项缺失**已被本轮实测确认**。
- 无最终域名/TLS/固定出口 IP；无 QWeather/AMap 控制台 staging 项目签字/配额；无 Prometheus 告警、备份存储、监控入口。
- 无 GitHub Environment / Actions Secret / staging deployment workflow。

**S-01～S-13 状态**：全部 `BLOCKED`（audit 5 逐项判定已复核；真实 Provider 探测仅证明凭据当前可用，**不等于** S-03/S-04 通过——本轮未做任何外部 Provider 调用）。

**staging 前置逐项判断**：Compose 结构 PASS（已验证）；不可变镜像策略 PASS（CI 强制）；真实资源/配置 FAIL/BLOCKED；Provider 探测 UNKNOWN（未执行）；恢复/回滚演练 FAIL（无证据）；monitoring FAIL（无告警入口）。→ **整体 `READY_FOR_STAGING = NO`（BLOCKED）**。

---

## 10. 文档偏差（重要项）

1. **README.md:5 版本身份过期**：声称 "V2.5"，实际已含 PlanEvaluation/天气/评估面板（远超 V2.5）。
2. **`.env.example:92-95` 死变量**：`DEEPSEEK_API_KEY`/`OPENAI_API_KEY`/`DEFAULT_LLM_PROVIDER` 全仓库 0 处读取。
3. **`REFRESH_COOKIE_SECURE` 默认冲突**：`.env.example:58`/`compose.prod.yaml:67` 默认 `true`，但 `README.md:76` 要求本地 Demo 改 `false`。
4. **`docs/current-state-assessment.md:64` 测试计数过期**：Python 45→59、Web 22→24；`:94` 残留 "当前 V2.0" 旧结论。
5. **`docs/deployment.md:270` 队列数不精确**：称"四条"，实际 5 条规划队列 + refresh + DLQ。
6. **`docs/README.md:14` 对 release.md 定位过期**（描述为 V2.0，实为组合 RC）。
7. **代码读取但文档未列的变量**：`ROUTE_CACHE_TTL_SECONDS`、`ACCESS_TOKEN_TTL`、`REFRESH_TOKEN_TTL`。
8. **`56eee3c` 引用依赖 worktree 分支存在**：若删除 `.claude/worktrees/feature+plan-evaluation`，roadmap 中多处引用失效（脆弱引用）。
9. **确认一致项**：S-01~S-13 如实标注 BLOCKED（无虚假声明）；completion v6/v7 描述、Flyway V1–V27、端点清单、RabbitMQ 拓扑、`validate_staging_env.py` 行为均与代码一致。

---

## 11. 技术债 Top 10

1. Java 零日志（I-1）—— 可观测性债之首。
2. Outbox 无界重试/无死信（I-2）—— 唯一无界状态。
3. `ItineraryService.java` god class（1547 行，≈20 方法 + 9 record）。
4. `TripDetail.vue`（1611 行）巨型组件。
5. `worker/contracts.py`（1055 行）单文件承载全部契约 + 与 JSON Schema 双轨维护。
6. `interestMatch` 固定 80 占位（I-4）—— 产品级失真。
7. 5 个 600–1000 行模块（`PlanningTaskService` 715、`GuideImportService` 648、`amap/planning_provider.py` 894、`trusted_facts.py` 874、`worker/amqp.py` 860、`TripWorkspace.vue` 1075、`GuideIntelligencePanel.vue` 622）。
8. Web DTO 重复声明（`ItineraryShareStatus` 两处）。
9. SSE Hub 订阅 map 无每任务上限 + 前端编辑队列无上限。
10. 无 ArchUnit/架构规则测试（分层仅靠人工 review）。

---

## 12. 建议执行顺序

### P0：进入 staging 前必须完成
- 修复 I-5：移除 `compose.prod.yaml` 中 `AGENT_INTERNAL_TOKEN=${JWT_SECRET}` 默认回退，改为 `:?` 强制。
- 修复 I-3：`INTERNAL_DIAGNOSTICS_TOKEN`/`app.agent.internal-token` 默认值改为 fail-fast（删除 `local-development-only` 回退）。
- 修复 I-2：Outbox 加 `max_attempts` + DEAD 状态（或明确的 SENT-with-error 语义）。
- 补齐 staging 前置资源：staging 主机/registry/七类 digest/完整 env/域名 TLS/出口 IP（这是当前最大 BLOCKED）。

### P1：staging 验收期间完成
- I-1 Java 日志接入（SLF4J + traceId 过滤器 + 异常记录），否则 S-10（日志告警）不可验收。
- I-6/I-7 覆盖率门禁扩展（Python 核心模块 + Java branch）。
- N-5 版本切换 evaluation 展示缺口（回退展示父版本评估）。

### P2：合并前完成
- N-4 长步行自动预置草稿副作用（增加显式选择/去自动）。
- N-1 分享限流取受信代理末段 IP。
- N-2 CitySource 审核角色控制。
- N-6 SSE Hub 订阅上限。
- N-7 Web DTO 去重。
- M-4 `TripDashboard` 硬编码默认值 + `any`。
- 清理 stale surefire 报告 / 决定是否补 ArchUnit。

### P3：后续优化
- 拆分 god class/组件（ItineraryService、TripDetail.vue、contracts.py）。
- v7 schema 启用或归档；cache/HTTP helper 去重。
- N-14 OR-Tools solver no-solution 分支测试。
- 文档偏差修正（README 版本、.env.example 死变量、计数）。

---

## 13. 最终状态判定表

| 状态 | 结论 | 依据 | 下一条件 |
| --- | --- | --- | --- |
| `LOCAL_CODE_HEALTHY` | **YES** | 工作区干净；Python 547/Java 43+32/Web 126 本地实测通过；版本不可变、事务/幂等/回滚有测试 | — |
| `REMOTE_CI_VERIFIED` | **YES** | CI run 30879603024 运行在精确 head `6c663dc`，5 job 全 SUCCESS，之后无新提交 | 新提交后须重跑五项 CI |
| `RC_TECHNICALLY_CLOSED` | **YES** | 契约一致、共享 fixture 双端消费、benchmark 8/8、release tooling 12/12；**但** interestMatch 占位（I-4）与零日志（I-1）使"技术闭环"带保留 | 修正 I-4/I-1 或如实标注 |
| `READY_FOR_STAGING` | **NO（BLOCKED）** | 缺 staging 主机/registry/digest/env/域名/TLS/告警/备份入口；`.env` 缺 10 项；S-01~S-13 无证据 | 补齐全部外部资源且 `validate_staging_env.py` PASS |
| `STAGING_DEPLOYED` | **NO** | 未部署任何 staging 资源（本轮亦未部署） | staging 资源就绪后执行不可变镜像部署 |
| `STAGING_ACCEPTED_AWAITING_SIGNOFF` | **NO** | S-01~S-13 全部 BLOCKED | 逐项完成 S-01~S-13 并留存证据 |
| `READY_FOR_REVIEW` | **NO（保持 Draft）** | 项目策略：staging 预检前保持 Open Draft（audit 5 明确"首次不可变镜像部署尚未开始"） | staging 预检通过后再评估转 Ready |
| `READY_TO_MERGE` | **NO** | 按项目自身门禁，CI 成功≠可发布；staging 未验收不可合并 | staging 验收 + 用户 signoff |
| `PRODUCTION_APPROVED` | **NO** | 距 production 还有 staging 验收、发布演练、回滚演练 | 完整发布流程 |

---

## 14. 下一步唯一建议

**保持 PR #27 为 Open Draft、保持冻结；唯一优先动作是补齐 staging 外部资源并让 `validate_staging_env.py --env-file <staging env>` 达到 PASS（staging 主机/registry/七类 digest/完整 env/域名 TLS/出口 IP/告警备份入口），随后以 REAL_ONLY + 不可变镜像部署并逐项验收 S-01~S-13。** 在此之前不合并、不转 Ready、不部署。

---

## 结束要求声明

1. **是否修改文件**：未修改任何源码/配置/文档/Git 历史。测试运行仅产生 gitignored 构建产物（`target/`、`__pycache__`、`.pytest_cache`、`node_modules/.vite` 等）。
2. **工作区是否干净**：是（`git status --porcelain` 为空，已复核）。
3. **外部 Provider 调用**：**未执行任何** QWeather/AMap/DashScope 等外部调用（审计全程只读本地 + GitHub 元数据只读查询）。
4. **Secret 接触**：未读取 `.env` 值（仅统计变量名）；未输出/记录/提交任何 Secret；Git 历史 gitleaks + 手动复核无真实 Secret。
5. **staging/production 操作**：未执行任何部署、推送、合并、转 Ready 操作。
6. **有直接证据的结论**：Git/PR/CI 状态、模块闭环（代码+测试）、Flyway V1–V27、Python 547/Java 43+32/Web 126/scripts 12、Markdown 链接、staging 资源缺失、Java 零日志、Outbox 无界重试、安全配置项——以上均有代码/命令输出直接佐证。
7. **仍为 BLOCKED/UNKNOWN**：S-01~S-13 全部 BLOCKED；staging 部署与验收状态 UNKNOWN（未执行）；真实 Provider 行为 UNKNOWN（未调用）；完整 Java 套件与 Playwright e2e 未本地复跑（以 CI 为准）；v7 契约未来行为 UNKNOWN。
8. **当前建议**：**保持冻结**。不建议继续开发新功能、不建议进入 staging（资源未备）、不建议转 Ready、不建议合并。唯一动作是推进 staging 资源准备与预检。
