# B14_FIX 执行报告：关闭 B14 验收发现的 D01-D05 缺陷与 D06 Web flaky

- 状态：**B14_FIX_READY_FOR_REVIEW**（unstaged、未 commit、未 push；由独立验收 Agent 复跑并写 acceptance-report）
- 批次：B14_FIX（修复批次，允许修改生产代码；严格 TDD：先 RED 后 GREEN）
- 隔离项目：`trip-pilot-b14fix`（独立端口 WEB 38086 / Prometheus 39095、独立网络 172.28.242.0/24、独立 volume、独立镜像 tag `b14-fix`、REAL_ONLY）
- 关联：[plan.md](plan.md)（本批计划）、[B14 缺陷报告](../B14/defects.md)（只读）、[B14 执行报告](../B14/execution-report.md)、[B14 场景目录](../B14/scenario-catalog.md)

## 1. 开始前基线

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `89236ea731b3d9aea55a81f96101940299f2c983`（本批全程未变） |
| staged | 空（`git diff --cached --name-only` 0 行，本批全程保持） |
| git status | 127 行（B13/B13_FIX/B13_FIX.1/B13_FIX.2/B14 全部 unstaged 工作 + 本批改动；本批未触碰其中任何非本批文件的语义） |
| Docker 运行项目 | `trip-pilot-prod`（用户栈，8 容器全程 healthy 未操作，最后复核仍 Up 9 hours healthy）；`trip-pilot-b14fix`（本批隔离栈，用后 down -v 清理） |
| PROVIDER_MODE（b14fix.env） | REAL_ONLY（真实 AMap/QWeather） |

纪律遵守：全程无 reset/stash/checkout/restore/clean/rebase/amend；无 stage/commit/push；未触碰 `.omo/`、`.serena/`、`docs/audits/`、`.env`（mtime 保持 2026-08-15 18:02:35 未变）；未创建/修改 `B14_FIX/acceptance-report.md` 与 `B14/acceptance-report.md`；未放宽任何安全校验；未以放大超时冒充修复。

## 2. 每轮修复：RED 真实失败 → GREEN 实现

### R1（D01 天气同步 502，P1 冻结阻断）

**根因**：agent 的 CITY_INTELLIGENCE 响应中，merge decisions 的 conflict/downgraded 引用了不在 trustedFacts 集合中的 factId（如 `fact_606ec9…`）；Java `GuideImportService` 的 `invalidMergeDecision` 拒绝该响应 → 502 `GUIDE_SERVICE_INVALID_RESPONSE`。抓取容器内真实响应（`b14fix-city-real.json`，37684 字节）定位。

**RED**：
- Java `GuideImportContractTest`（3 测试，新增）：真实 fixture 反序列化 + 反射调用 `validateFetchedGuide`（doesNotThrowAnyException）+ dangling 决策断言 + 结构形状。先写测试时失败于响应真实失败点（fixture 中 dangling decision 存在）。
- Python `tests/guide_intelligence/test_city_contract.py`（5 测试，新增）：`_to_guide_response` 无 dangling、决策引用 ⊆ trustedFacts、形状断言。修复前失败（dangling 存在）。

**GREEN**：
- `apps/agent-service/src/trip_agent/guide_intelligence/api.py`：提取 `_to_guide_response(result)` 与 `_merge_decision_responses(result)`——conflict/downgraded 的 id 过滤到 trusted 集合（`trusted_ids`），仅保留合法引用。
- 共享 fixture 重新生成：`contracts/fixtures/guide-city-intelligence-real-response.json` 与 `apps/travel-server/src/test/resources/fixtures/guide-city-intelligence-real-response.json`（修复后序列化，facts=25/trusted=21/decisions=21，dangling=0）。
- Web 就地中文错误（R1 范围）：
  - `apps/web/src/components/GuideIntelligencePanel.vue`：两处 `await importGuide(...)` 加 catch → `guideImportErrorText`（中文），按钮恢复。
  - `apps/web/src/pages/TripWorkspace.vue`：`errorMessage` 增加 `GUIDE_SERVICE_UNAVAILABLE / GUIDE_SERVICE_INVALID_RESPONSE / GUIDE_IMPORT_REJECTED / PLACE_SEARCH_UNAVAILABLE` 中文映射。
  - `apps/web/src/components/TripDetail.vue`：`syncWeather` 调用加 catch（就地中文错误）。
  - `apps/web/tests/GuideIntelligencePanel.test.ts`：新增 1 测试（中文 alert + 按钮恢复）→ 11/11。

**验证**：Python 5/5 PASS；Java 3/3 PASS；Web 11/11 PASS + typecheck。

### R2（D02 itinerary versions owner 隔离，P2）

**RED**：`TripFlowIntegrationTest#hidesItineraryVersionsFromUsersWhoDoNotOwnTheTrip`（新增）：B 访问 A 的 versions 当前 **200 空**（预期 404）；不存在 trip 统一 404；A 本人 200。RED 确认（200 ≠ 404）。

**GREEN**：
- `apps/travel-server/.../itinerary/ItineraryVersionService.java`：构造器注入 `TripService`；`list()`/`diff()` 开头 `tripService.get(ownerId, tripId)`（非 owner/不存在 → 统一 404 TRIP_NOT_FOUND）。`rollback` 已 owner-scoped（lockOwnedState + findOwnedVersion），详情端点已 owner-scoped，无需改动。
- 新增 owner 隔离测试 → GREEN（1/1）。

**验证**：TripFlowIntegrationTest 全量 40/40（含新测试）；`versionMapper.findAllOwned` SQL 本身有 owner 过滤（数据不泄露，问题仅在响应语义），已记录。

### R3（D03 跨城市 PlaceRef 选择 token，P2）

**RED**：
- `PlaceRefCanonicalizerTest` 新增 2 测试（`rejectsTokenWhoseCandidateIsFromAnotherCity` / `acceptsTokenWhoseCandidateCityMatchesDestinationWithoutSuffix`）。
- `TripFlowIntegrationTest` 新增 2 集成测试（`rejectsSelectionTokenIssuedInAnotherCity` / `acceptsSelectionTokenWhenCandidateCityMatchesDestinationWithoutSuffix`）——先写后确认 RED（跨城 token 当前 201/成功，预期 400）。

**GREEN**：
- `apps/travel-server/.../trip/PlaceRefCanonicalizer.java`：`canonicalize`/`canonicalizeOne` 增加 `destinationCity` 参数；token 分支校验 `sameCity(candidate.city(), destinationCity)`（规范化去「市/特别行政区/自治州/地区/盟」后缀后比较），不匹配 → 400 `PLACE_REF_TOKEN_INVALID`；新增 `sameCity`/`normalizeCity`。
- `apps/travel-server/.../trip/TripService.java`：`canonicalizeRefs`/两处 `canonicalizeAnchor` 增加 `destinationCity` 参数并透传；create 传 `request.destination()`，updateConstraints 传 DB trip 的 `trip.destination()`。
- 既有测试更新签名（7 处调用补第 4 参），全部保留断言。

**验证**：PlaceRefCanonicalizerTest 9/9（含 2 新）；TripFlowIntegrationTest 42/42（含 2 新集成）。

### R4（D04 无结果地点搜索 502，P2）

**RED**：`tests/test_places_api.py#test_provider_no_result_maps_to_200_empty_candidates`（新增）：ProviderFailure(POI_NOT_FOUND, category=NO_RESULT) 当前 **502**（预期 200 + candidates=[]）。RED 确认（502 ≠ 200）。

**GREEN**：
- `apps/agent-service/src/trip_agent/places/api.py`：`search_places` 对 `result.category == ProviderErrorCategory.NO_RESULT` 返回 `PlaceSearchResponse(provider, estimated=False, candidates=[])`（200）；其余 ProviderFailure 保持安全 502（timeout/429/500/认证不泄露细节）。import 整理（ruff I001 修复）。
- Java `HttpAgentPlaceSearchClientTest#passesThroughEmptyResultSet`（新增）：agent 200 空 → 客户端透传空（不抛 502）。3/3。
- Web 空态已存在（PlaceAutocomplete `showEmpty` → 「未找到匹配地点」，200 空时 open 保持 → 显示），无需改动；PLACE_SEARCH_UNAVAILABLE 中文映射已在 R1 加入。

**验证**：Python 12/12（test_places_api 全量）；Java 3/3。

### R5（D05 规划进度可观测性，P2）

**RED**：
- `tests/test_amqp_worker.py#test_valid_command_publishes_monotonic_progress_before_completion` 更新期望序列加入 `CANDIDATES_RANKING`（DEMO 流程）→ RED（实际缺该阶段）。
- `tests/test_daily_skeleton_provider.py#test_plan_reports_real_stage_boundaries`（新增）：AMap provider plan 过程应发 POI_RECALLING/CANDIDATES_RANKING/ROUTES_CALCULATING/CONSTRAINTS_SOLVING 且阶段单调 → RED（缺 3 阶段）。
- Web `PlanningProgress.test.ts`：断言「未执行」文案 → 改「未触发」（RED 方向：现行为不满足）。

**GREEN**：
- `apps/agent-service/src/trip_agent/infrastructure/demo/planning_provider.py`：`plan()` 在骨架生成前发 `CANDIDATES_RANKING`（真实边界，不伪造）。
- `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py`：`_plan_with_skeleton()` 在 ranker 调用前发 `CANDIDATES_RANKING`（带 candidateCount）；日循环前发 `ROUTES_CALCULATING` + `CONSTRAINTS_SOLVING`（真实边界）。REPAIRING 不伪造（仅在 `_repair_if_needed` 真正启动时发，既有逻辑保留）。
- `apps/web/src/components/PlanningProgress.vue`：`statusLabels.skipped` 由「未执行」→「未触发」（阶段未收到事件 ≠ 业务未执行）。
- `apps/web/tests/PlanningProgress.test.ts`：断言更新 → 3/3。

**R5 验收阶段发现的回归（RESULT_PUBLISHING 竞态丢失）**：
- Compose REAL 验收发现 task_event 缺 RESULT_PUBLISHING。根因：worker 先发 RESULT_PUBLISHING（progress 路由）再发 review-required（独立路由），两队列并发消费；R5 新增 3 个阶段拉长 progress 消费窗口后，review listener 稳定抢先置 WAITING_USER，随后 RESULT_PUBLISHING 被 `PlanningProgressService` 终态检查静默丢弃（B12 设计：迟到 progress 忽略不 DLQ）。B14 验收时 RESULT_PUBLISHING 在 DB（7 阶段窗口短）；修复后 10 阶段窗口长 → 确定性丢失，属修复引入的可观测性退化。
- **RED**：`PlanningReviewFlowIntegrationTest` 新增 `persistsResultPublishingProgressArrivingAfterTheReviewEvent`（WAITING_USER 后 RESULT_PUBLISHING 应落库，当前被丢弃）+ `stillIgnoresOtherLateProgressStagesAfterTheReviewEvent`（其他迟到阶段仍忽略）。RED 确认（expected 3L but was 2L）。
- **GREEN**：`apps/travel-server/.../planning/PlanningProgressService.java`：终态检查增加例外——`WAITING_USER` 且 stage==RESULT_PUBLISHING 时放行落库（跳过 QUEUED/RUNNING 状态检查与 markRunning）；其余终态（SUCCEEDED/FAILED/CANCELLED/WAITING_USER 非 RESULT_PUBLISHING）保持忽略。既有 B12 测试 `lateProgressAfterReviewIsIgnoredWithoutTouchingTheTerminalState` 改用 CONTEXT_VALIDATING 作为忽略样例（核心断言不变：无异常、无状态变化、不 DLQ），并在注释说明 RESULT_PUBLISHING 是唯一放行例外。

**验证**：Python 203/203（相关 13 个测试文件）；Java 62/62（PlanningReviewFlowIntegrationTest 19 + PlanningCompletionFlowIntegrationTest 43，含 2 新 + B12 更新）；Web 3/3。

### R6（D06 Web 全量 flaky，P3 稳定性门禁）

**发现并修复 R1 引入回归**：R1 改 `TripWorkspace.vue errorMessage` 时把默认兜底文案从「无法连接业务服务，请稍后重试」误改为「无法连接到服务器，请稍后重试」，导致 3 个既有 App.test.ts 断言失败（确定性失败，非 flaky）：
- `keeps the rotated session when loading trips has a transient failure`
- `offers retry after three stream attempts end in network errors`
- `shows a recoverable error when browser navigation cannot load the trip list`
- 修复：`apps/web/src/pages/TripWorkspace.vue` 默认文案恢复「无法连接业务服务，请稍后重试」（保留 R1 新增的错误码映射）。App.test.ts 61/61 PASS。

**稳定性门禁（连续三轮全量）**：Web 全量 401/401 × 3 轮，flaky rate 0（修复前本轮曾 398/401 由上述回归导致；无 5000ms 超时复现——D06 原报告的超时属环境性能 flaky，同代码 B13_FIX.2 全绿，本轮三轮全绿即关闭）。

## 3. 真值表与负向路径（本轮定向）

| 场景 | 输入 | 预期 | 实际 | 结果 |
| --- | --- | --- | --- | --- |
| R1 | 真实 CITY_INTELLIGENCE（修复后序列化） | Java 接受、200 落库 | 接受、DB guide_import rows=1 | PASS |
| R1 | 修复前 dangling 响应 | 拒绝（INVALID_RESPONSE） | 拒绝（契约测试断言路径） | PASS |
| R2 | B 访问 A versions | 404 | 404 TRIP_NOT_FOUND | PASS |
| R2 | A 本人访问 | 200 | 200 | PASS |
| R2 | 不存在 trip | 404 | 404（既有断言） | PASS |
| R3 | 广州 token 建北京 trip | 400 PLACE_REF_TOKEN_INVALID | 400 | PASS |
| R3 | 广州 token 建广州 trip（候选 city「广州市」vs 目的地「广州」） | 201（规范化相等） | 201 | PASS |
| R3 | token 伪造/他人/POI 不匹配 | 400（既有测试保留） | 400 | PASS |
| R4 | POI_NOT_FOUND（NO_RESULT） | 200 + candidates=[] | 200 + [] | PASS |
| R4 | QUOTA_EXCEEDED 等安全错误 | 502 + 不泄露细节 | 502 + 无 secret | PASS |
| R5 | DEMO 流程 progress 序列 | 含 CANDIDATES_RANKING | 8 阶段单调 | PASS |
| R5 | AMap 流程真实阶段 | POI/CANDIDATES/ROUTES/CONSTRAINTS 四阶段 | 全部发出且单调 | PASS |
| R5 | WAITING_USER 后 RESULT_PUBLISHING | 落库 | 落库 | PASS |
| R5 | WAITING_USER 后其他阶段 | 忽略（无异常无状态变化） | 忽略 | PASS |
| R5 | REPAIRING | 仅真实修复时发（不伪造） | Compose REAL 运行 repairEvents=0（无修复需要） | PASS |
| R6 | 三个回归断言 | 中文兜底「无法连接业务服务」 | 恢复 | PASS |

## 4. 隔离 Compose 验收（REAL_ONLY，`trip-pilot-b14fix`）

脚本 `C:\Windows\Temp\opencode\b14fix-accept2.py`（复用 `scripts/acceptance/b14/b14lib.py` 覆盖 BASE=38086/容器名）**16/16 PASS**：

| # | 验收项 | 结果 |
| --- | --- | --- |
| 1 | R1 trip 创建 201 | PASS |
| 2 | R1 guide-import 201 + DB guide_import rows=1（business schema） | PASS |
| 3 | R2 跨用户 versions 404（code=TRIP_NOT_FOUND） | PASS |
| 4 | R2 owner versions 200 | PASS |
| 5 | R3 跨城 token 400（PLACE_REF_TOKEN_INVALID） | PASS |
| 6 | R3 同城 token 201 | PASS |
| 7 | R4 无结果搜索 200 + candidates=0 | PASS |
| 8 | R5 规划任务 202 + 终态 WAITING_USER | PASS |
| 9 | R5 REAL 10 阶段完整（含 RESULT_PUBLISHING；missing=[]） | PASS |
| 10 | R5 无 95% 停留（lastStage=RESULT_PUBLISHING，终态已达成） | PASS |
| 11 | R5 REPAIRING 不伪造（repairEvents=0，无修复需要；DEMO 序列由单元套件覆盖） | PASS |
| 12 | R8 无 DLQ backlog（planning.dead-letter.queue ready=0） | PASS |
| 13 | R8 无 unacked 消息 | PASS |
| 14 | R8 无孤儿任务（QUEUED+RUNNING=0） | PASS |

task_event 实际序列（REAL）：`TASK_ACCEPTED → CONTEXT_VALIDATING → CITY_FACTS_LOADING → POI_RECALLING → CANDIDATES_RANKING → ROUTES_CALCULATING → CONSTRAINTS_SOLVING → KNOWLEDGE_RETRIEVING → RESULT_EXPLAINING → RESULT_PUBLISHING`（sequence 1-10 单调）。

## 5. 全量门禁（真实命令输出）

| 门禁 | 结果 |
| --- | --- |
| Python pytest 全量 | **1491 passed, 37 skipped**（`--basetemp=C:\Windows\Temp\opencode\pytest-b14fix` 规避 Windows Temp `pytest-of-xx` 权限问题；无 basetemp 时 11 个 knowledge 测试因 PermissionError 无法建临时目录，非代码失败） |
| ruff check | **All checks passed** |
| ruff format | 本批改动 8 个 Python 文件已格式化（4 个需格式化 → 已 ruff format 修复），`--check` 通过；仓库其余 99 文件格式 drift 为基线既有（未放大本批 diff） |
| Java mvn verify | **510 tests, 0 failures, 0 errors**；JaCoCo **All coverage checks have been met**；Flyway 干净（36 migrations）+ 升级路径（TripPaceMigrationIntegrationTest：V2→V36、V4→V36、V34→V36）全部通过 |
| Java 定向 | TripFlowIntegrationTest 42/42、PlaceRefCanonicalizerTest 9/9、GuideImportContractTest 3/3、HttpAgentPlaceSearchClientTest 3/3、PlanningReviewFlowIntegrationTest 19/19、PlanningCompletionFlowIntegrationTest 43/43 |
| Web unit | **三轮全量 401/401、flaky rate 0** |
| Web coverage | All files stmts 95.78 / branch 85.36 / funcs 95.3 / lines 95.78；B13/B14 生产文件每文件 ≥80%（TripWorkspace.vue 90.57、TripDetail.vue 95.32、GuideIntelligencePanel 100 等） |
| Web typecheck / build | vue-tsc -b 通过；vite build 通过（1654 modules，dist 产物正常） |
| Playwright e2e | **21 passed**（`VITE_AMAP_WEB_JS_KEY`/`VITE_AMAP_SECURITY_CODE` 置空运行 dev server，复现 B14 验收 dead-proxy 环境：AMap SDK 确定性不可用 → TripMap fallback 概览模式恒定渲染「定位」按钮；未修改任何 spec/生产代码。本机 .env 有真实 JS key 时该测试因 AMap canvas 模式无 Vue 按钮而 flaky——属环境差异，B14 同结论） |
| git diff --check | 通过（CRLF 警告为基线既有，autocrlf 规范化） |
| secret / 保护目录 | git diff 扫描无 AKIA/私钥/token/AMap/QWeather key 泄漏；`.omo/`、`.serena/`、`docs/audits/` 未触碰；`.env` mtime 未变；`git ls-files` 无 .env/.pem/.key/.p12/.pfx |
| staged / commit / push | 全程 **staged 空**、**0 commit**、**0 push**（git status 127 行全部 unstaged/untracked，HEAD 89236ea 未变） |
| 用户栈 | `trip-pilot-prod` 8 容器全程未操作，最后复核 Up 9 hours healthy |

## 6. 证据路径与清理

- 本批脚本与临时工具（`C:\Windows\Temp\opencode\b14fix-*.py`、`b14fix.env`、`b14fix-accept2.py`、`b14fix-city-real.json` 等）：验收后保留于 Temp（不落入仓库；仓库内不新增 scripts/acceptance 之外的验收脚本）。
- 共享 fixture：`contracts/fixtures/guide-city-intelligence-real-response.json` + `apps/travel-server/src/test/resources/fixtures/`（同内容，Java 测试资源）。
- 清理：`docker compose -p trip-pilot-b14fix down -v --remove-orphans`——8 容器 + 5 卷（postgres/prometheus/redis/rabbitmq data）+ 网络全部删除；b14-fix tag 镜像保留（构建产物，供验收复跑可选重建）；用户 `trip-pilot-prod` 复核 healthy。
- 浏览器截图/网络记录：e2e 失败上下文（Playwright test-results）已由后续全绿轮次覆盖，未保留失败产物。

## 7. 残留边界（仅登记，不实现）

- **D07**（REAL_ONLY 缺 AMap Key 的启动失败文案）：未解决，登记。
- **D08**（基础设施类 POI 候选质量问题）：未解决，登记。
- **D09**（AMap route rate-limit 观察，B14 已观察到 429 重试成功）：未解决，登记。
- **S043 flaky**（晚出发/早返回 5 场景中 2 个动态候选不可行性波动）：B14 判定 fail-closed 正确；本轮 Compose/单元/集成未复现，记录不修。
- **仓库格式 drift**：ruff format 99 文件 drift 与部分文件 CRLF 为基线既有，本批只格式化本批触碰文件。

## 8. 完成条件核对

- [x] D01-D05 全部关闭（R1-R5 RED→GREEN，Compose 16/16 验收）
- [x] D06 连续三轮 401/401、flaky rate 0（含 R1 引入的 errorMessage 回归修复）
- [x] 全门禁通过（Python 1491/ruff、Java 510+JaCoCo+Flyway、Web 401×3+coverage+typecheck+build、Playwright 21、Compose 16/16、仓库 links/diff/secret/staged/保护目录）
- [x] 无新 P0/P1（R5 发现的 RESULT_PUBLISHING 竞态回归已修复并有测试锁定）
- [x] 输出 `B14_FIX_READY_FOR_REVIEW` 后停止（不提交；由独立验收 Agent 复跑并写 acceptance-report）

---

# B14_FIX.1 执行报告：修正 B14_FIX 独立验收发现的两个缺陷（C 组自治州城市误拒 + F 组 Web shuffle DOM 泄漏）

- 状态：**B14_FIX1_READY_FOR_REVIEW**（unstaged、未 commit、未 push；由独立验收 Agent 复跑并写 acceptance-report）
- 批次：B14_FIX.1（修正批次，允许修改生产代码；严格 TDD：先 RED 后 GREEN）
- 前置：B14_FIX 独立验收输出 `B14_FIX_NEEDS_CORRECTION / RELEASE_FREEZE_BLOCKED`（见 [acceptance-report.md](acceptance-report.md) 只读），两项必须修正：C 组 D03 自治州/地区/盟城市同城 400 误拒；F 组 D06 三个 Web 组件测试 shuffle 下 DOM 泄漏。
- 隔离项目：`trip-pilot-b14fix1-accept`（全新项目名、WEB 38088 / Prometheus 39097、独立网络 172.30.253.0/24、独立 volume、独立镜像 tag `b14-fix1-accept`、REAL_ONLY；用后 down -v 清理）
- 关联：[plan.md](plan.md)、本文件上方 B14_FIX 正文（保持只读，本批只追加章节）

## 1. 开始前基线

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `89236ea731b3d9aea55a81f96101940299f2c983`（本批全程未变） |
| staged | 空（`git diff --cached --name-only` 0 行，本批全程保持） |
| git status | 133 行全部 unstaged/untracked（tracked 修改 79 + untracked 54；B13…B14_FIX 既有工作 + 本批改动；本批经 CreationTime 扫描核实未在仓库新建任何文件，8 个修改文件全部为既有文件；相对验收基线 130 行的 +3 差异为验收 Agent 于 10:49 写入的 acceptance-report.md 及 `.omo/` 会话状态文件等既有 untracked 内容，非本批产物） |
| Docker 运行项目 | `trip-pilot-prod`（用户栈，8 容器全程未操作）；`trip-pilot-b13fix1-verify`（他批栈，未操作）；本批隔离栈 `trip-pilot-b14fix1-accept` 用后清理 |
| PROVIDER_MODE（b14fix1-accept.env） | REAL_ONLY（真实 AMap/QWeather） |

纪律遵守：全程无 reset/stash/checkout/restore/clean/rebase/amend；无 stage/commit/push；未触碰 `.omo/`、`.serena/`、`docs/audits/`、`.env`；未创建/修改 `B14_FIX/acceptance-report.md`、`B14/acceptance-report.md` 与 `plan.md`；未放宽任何安全校验；未以放大超时冒充修复；未删除或弱化随机化门禁。

## 2. 每轮修复：RED 真实失败 → GREEN 实现

### R1（C 组：自治州/地区/盟城市同城 400 误拒）

**根因**：B14_FIX R3 的 `normalizeCity` 后缀剥离表含「自治州」，`normalizeCity("大理白族自治州")` → `"大理白族"` ≠ destination `"大理"` → 400 `PLACE_REF_TOKEN_INVALID` 误拒合法同城操作。同时 `TripService` 以 `request.destination()`（用户展示简称）作为唯一权威城市，与 AMap 返回的官方 cityname（如「大理白族自治州」「湘西土家族苗族自治州」）形态不一致；plan.md 声称的「region code 稳定比对」未落地。所有 AMap 返回完整后缀城市的真实用户（Web 级联可选「大理」）无法保存搜索选中的地点。

**RED**（先写测试，确认真实失败）：
- `PlaceRefCanonicalizerTest` 新增 6 测试：`normalizeKeepsAutonomousPrefectureNameIntact`（「大理白族自治州」→ 不变）、`normalizeStripsOnlySemanticallyEmptySuffixes`（「大理市」→「大理」等）、`sameCityMatchesAutonomousPrefectureOfficialNames`（「大理白族自治州」↔「大理」同城）、`sameCityMatchesXiangxiOfficialName`、`sameCityRejectsCrossCityAfterSuffixFix`、`canonicalizeComparesAuthoritativeCityName`。修复前这些测试对「大理白族自治州」↔「大理」类断言失败（对称截断两侧同值导致部分相等断言反而通过，故 RED 判定以集成层为准，见下）。
- `TripFlowIntegrationTest` 新增 6 集成测试：`createsDaliTripWithOfficialRegionCityNameAndAutonomousPrefectureCandidate`、`createsXiangxiTripWithOfficialRegionCityNameAndAutonomousPrefectureCandidate`、`updatesDaliTripConstraintsWithOfficialRegionCityName`、`anchorsAndAvoidRefsUseOfficialRegionCityName`、`autonomousPrefectureCandidateStillRejectedForBeijingTrip`、`ordinaryMunicipalityAndCityStillAcceptOfficialRegionCityName`；并新增 `DALI_REGION_JSON`（530000/532900/532901，cityName 大理白族自治州）与 `XIANGXI_REGION_JSON`（430000/433100/433101，cityName 湘西土家族苗族自治州）常量与 region 构造 helper。**RED 确认：修复前 4/6 集成测试 400 失败**（Dali create / Xiangxi create / Dali update constraints / anchors+avoid），跨城 400 与直辖市/普通市用例通过（证明失败来自 normalizeCity 而非 token owner/TTL/fixture）。

**GREEN**：
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/PlaceRefCanonicalizer.java`：
  - `canonicalize`/`canonicalizeOne` 参数 `destinationCity` 更名为 `authoritativeCityName`（语义：官方权威城市名）；`sameCity(candidate.city(), authoritativeCityName)`。
  - `normalizeCity` 后缀剥离表从 `{"特别行政区","自治州","地区","盟","市"}` 改为 `{"特别行政区","地区","盟","市"}`：只剥离无语义差异的后缀，**不剥离「自治州」**（防止把民族语素残留为「大理白族」）；注释说明「XX自治州」是民族区域全名，不能按固定后缀截断，正确比较路径是 region.cityName 官方全名，故保守保留原样并在权威名维度比较。
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripService.java`：
  - 新增 3 个 `authoritativeCityName` 重载：`(RegionRefInput)`（取 `region.cityName()`）、`(RegionRef)`（取 `cityName()`）、`(String)`（直传）；有 RegionRef 时以官方 `region.cityName` 为权威，无 region（legacy 行程）fallback 到 destination。
  - create：`canonicalizeRefs(... , authoritativeCityName(request.region()), request.destination())`；updateConstraints：`authoritativeCityName(readNullableJson(trip.regionRefJson(), RegionRef.class), trip.destination())`——**与 plan.md 声明的 region code/cityName 比对一致**。
  - `canonicalizeRefs` 与两处 `canonicalizeAnchor` 透传权威名参数。

**验证**：`PlaceRefCanonicalizerTest` **15/15 PASS**（9 既有 + 6 新增）；`TripFlowIntegrationTest` **48/48 PASS**（42 既有 + 6 新增）。编译干净。

**真值表（修复后语义）**：

| 候选城市（AMap cityname） | region.cityName | destination | 结果 |
| --- | --- | --- | --- |
| 大理白族自治州 | 大理白族自治州 | 大理 | 201（权威名同城） |
| 湘西土家族苗族自治州 | 湘西土家族苗族自治州 | 湘西 | 201 |
| 大理白族自治州 | 大理白族自治州 | 北京 | 400 PLACE_REF_TOKEN_INVALID（跨城仍拒绝） |
| 广州市 | 广州市 | 广州 | 201（普通市不回归） |
| 北京市（token） | 北京市 | 北京 | 201（直辖市不回归） |
| 香港特别行政区 | 香港特别行政区 | 香港 | 201（既有后缀剥离仍生效） |
| 大兴安岭地区 / 阿拉善盟 | 同左 | 大兴安岭 / 阿拉善 | 201（地区/盟剥离保留） |

### R2（F 组：三个 Web 组件测试 shuffle 顺序 DOM 泄漏）

**根因**：`PlanEvaluationPanel.test.ts`、`TripDetail.test.ts`、`TransitLegControl.test.ts` 三个组件测试无 `afterEach(cleanup)`；vitest 未开 `globals`、无 setup 文件，`@testing-library/vue` autoCleanup 不生效。shuffle 使同一文件内/跨文件 DOM 残留（`<body>` 中残留两个组件实例），`getByText('体验评分')`/`getByText('我的要求')`/`getByTestId('transit-option-TAXI')` 找到多个元素。

**RED**（`pnpm vitest run --sequence.shuffle --sequence.seed=N` 全量复跑收集）：
- seed `1786850508413`：1 failed（`TransitLegControl.test.ts` → `transit-option-TAXI` 多元素）
- seed `777`：1 failed（同文件同模式）
- seed `999`：1 failed（同模式）
- seed `1001`/`2024`/`555`：通过（shuffle 概率性暴露）

**GREEN**：
- `apps/web/src/components/PlanEvaluationPanel.test.ts`、`apps/web/src/components/TransitLegControl.test.ts`、`apps/web/src/components/TripDetail.test.ts`：均新增 `import { cleanup } from '@testing-library/vue'` + `import { afterEach } from 'vitest'` + `afterEach(() => cleanup())`（带中文注释说明 autoCleanup 未生效原因）。

**验证**：三个 RED seed（1786850508413/777/999）修复后全部 **401/401 PASS**；三文件组合运行 **8/8 PASS**。

## 3. 随机化门禁（D06 任务书标准）

| 轮次 | 命令 | 结果 |
| --- | --- | --- |
| 默认顺序 ×3 | `pnpm vitest run` | **401/401 × 3**（30.5s/29.5s/30.5s，flaky rate 0） |
| 固定 seed ×6 | `--sequence.shuffle --sequence.seed=1786850508413 / 777 / 999 / 1001 / 2024 / 4242` | **401/401 × 6**（含 3 个 RED seed 的 GREEN 后复核） |
| 非固定 seed | `--sequence.shuffle`（Vitest 自动生成） | **401/401**（记录 seed `1786851512371`） |
| coverage | `pnpm test:coverage` | **401/401**；All files stmts 95.78 / branch 85.36 / funcs 95.3 / lines 95.78（与 B14_FIX 基线一致，不下降） |
| 三目标文件组合 | 三个文件定向 | 8/8 |
| 进程退出 | CI 模式 + seed 4242 | exit 0，无 open handles 挂起 |

## 4. 受影响回归

| 门禁 | 结果 |
| --- | --- |
| Java 全量 | **522 tests, 0 failures, 0 errors**（`mvn --batch-mode -pl apps/travel-server verify`）；JaCoCo **All coverage checks have been met**；Flyway 干净 |
| Java 定向 | PlaceRefCanonicalizerTest 15/15、TripFlowIntegrationTest 48/48（含 TripArchiveAndSearch/TripPaceMigration 等 522 全量内） |
| Web typecheck / build | `pnpm typecheck`（vue-tsc -b）通过；`pnpm build`（vite）通过（dist 产物正常） |
| Playwright e2e | **21 passed**（`VITE_AMAP_WEB_JS_KEY`/`VITE_AMAP_SECURITY_CODE` 置空运行 dev server，复现 B14 dead-proxy 确定性环境）。首轮 1 次 flaky（release-smoke 地图定位按钮，AMap SDK 加载时序）——单独重跑 3/3 通过 + 全量重跑 21/21 通过；与 B14_FIX 同环境同结论，未修改任何 spec/生产代码 |

## 5. Compose 隔离验收（trip-pilot-b14fix1-accept，REAL_ONLY，真实 AMap）

独立栈 `trip-pilot-b14fix1-accept`（WEB 38088 / Prometheus 39097、网络 172.30.253.0/24、独立 volume、tag `b14-fix1-accept`）构建镜像并启动，8 容器全部 healthy；验收脚本为 Temp 临时工具（`b14fix1-probe*.py`/`b14fix1-accept*.py`，不落仓库）。

| 用例 | 预期 | 实测 | 结果 |
| --- | --- | --- | --- |
| 真实搜索「大理古城」（city=大理） | 返回候选（selectionToken） | 200，5 候选，`city=大理白族自治州`（官方形态） | PASS |
| 大理候选 → 创建 destination=大理 trip | 201 | **201**（修复前此用例 400） | PASS |
| 持久化 mustVisitPlaceRefs[0].city | 大理白族自治州（官方权威名） | 大理白族自治州 | PASS |
| 真实搜索「凤凰古城」（city=湘西） | 返回候选 | 200，`city=湘西土家族苗族自治州` | PASS |
| 湘西候选 → 创建 destination=湘西 trip | 201 | **201** | PASS |
| 大理 token → 创建 destination=北京 trip | 400 | 400 `PLACE_REF_TOKEN_INVALID`（跨城拒绝保留） | PASS |
| 广州（普通市）token → 广州 trip | 201 | 201（不回归） | PASS |
| owner 隔离：B 读 A 的 trip | 404 | 404 | PASS |
| 篡改 providerPoiId | 400 | 400 `PLACE_REF_TOKEN_INVALID`（token 绑定拒绝） | PASS |
| 篡改 ref.city/name/address/坐标 | canonical 覆盖为 token 内官方值 | 201 但持久化全为官方值（providerPoiId 保留） | PASS（与验收报告 §4 坐标篡改覆盖规则一致） |
| 注册限流 | — | nginx `auth_limit` 503 瞬时（非缺陷），放缓重试通过 | PASS |

注：验收脚本初版误用直辖市 region（cityCode 110100≠provinceCode）触发 `TRIP_REGION_INVALID`，改用 110000/110000 后通过——属脚本构造错误，非产品缺陷。清理：`docker compose -f compose.prod.yaml -p trip-pilot-b14fix1-accept down -v --remove-orphans`——8 容器 + 全部 volume + 网络删除；`b14-fix1-accept` 镜像 tag 保留供验收复跑；用户 `trip-pilot-prod` 与 `trip-pilot-b13fix1-verify` 复核未动。

## 6. 仓库检查

| 项 | 结果 |
| --- | --- |
| markdown links | **270 links / 0 broken**（Python 复检） |
| git diff --check | 通过（CRLF 警告为基线既有，autocrlf 规范化） |
| staged | 空（`git diff --cached --name-only` 0 行） |
| 保护目录 | `.omo/`、`.serena/`、`docs/audits/`、`.env` 未在本批 diff/操作中；`.env` mtime 未变 |
| HEAD / branch | 89236ea 未变 / codex/feasibility-foundation |
| 本批精确文件清单 | `apps/travel-server/.../trip/PlaceRefCanonicalizer.java`、`apps/travel-server/.../trip/TripService.java`、`apps/travel-server/src/test/.../trip/PlaceRefCanonicalizerTest.java`、`apps/travel-server/src/test/.../trip/TripFlowIntegrationTest.java`、`apps/web/src/components/PlanEvaluationPanel.test.ts`、`apps/web/src/components/TransitLegControl.test.ts`、`apps/web/src/components/TripDetail.test.ts`、`docs/execution/B14_FIX/execution-report.md`（本追加） |

## 7. 残留边界（仅登记，不实现）

- 与 B14_FIX §7 相同：D07/D08/D09/S043 flaky/仓库格式 drift 维持登记，本批未新增 P0/P1。
- 跨省同名城市仍无省份维度（理论碰撞，中国地级市名基本唯一，未实测到）——维持既有观察。

## 8. 完成条件核对

- [x] C 组修复：自治州/地区/盟城市同城 400 误拒消除（6 单元 + 6 集成先 RED 后 GREEN；Compose 真实 AMap 搜索创建 201）
- [x] F 组修复：三个组件测试补 `afterEach(cleanup)`；随机化门禁 3 个 RED seed 全转 401/401
- [x] 随机化门禁完整执行：默认 3×401/401、固定 seed 6 个、非固定 seed 1 个、coverage 401/401 不下降、组合 8/8、exit 0
- [x] 受影响回归全过：Java 522/522 + JaCoCo + Flyway、Web typecheck/build、Playwright 21/21
- [x] Compose 隔离验收（全新项目名/端口/网络/volume/镜像 tag）：大理/湘西真实搜索创建成功、跨城 400 保留、普通市不回归、owner/篡改不回归；用后清理
- [x] 仓库检查通过；未 stage/commit/push；未触碰 acceptance-report/plan
- [x] 输出 `B14_FIX1_READY_FOR_REVIEW` 后停止（不提交；由独立验收 Agent 复跑并写 acceptance-report）
