# B11 执行报告

- 状态：PASS / COMMITTED（B11 提交）
- 批次：B11 最终统一验收与本地交付收口

## 基线

- branch=codex/feasibility-foundation ✓
- HEAD=f2040f0（B10）✓
- staged 空 ✓；untracked 仅 .omo/ .serena/ docs/audits/ ✓
- 总控计划：B8=COMMITTED、B9=PASS/COMMITTED、B10=PASS/COMMITTED、B11=NOT_STARTED ✓
- 断点=B11 ✓；无 upstream、未 push ✓

## 审计进展

### 二、完成范围事实审计（18 项矩阵）

| # | 核心目标 | 结论 | 实现位置 | 关键测试 | 运行时入口 | 用户可见结果 | 残留限制 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hard Validation 11/11 | 已完成 | `feasibility/catalog.py`（REQUIRED=IMPLEMENTED=11，MISSING 空）、`feasibility/validator.py` `_RULE_DISPATCH` | `test_planning_outcome_flow.py`、`test_golden_matrix.py` | `process_planning_create/replan/candidate_validation` → `run_validation` | 报告列出全部 11 规则结果 | 无 |
| 2 | Feasibility Report 三态 | 已完成 | `feasibility/models.py`（VERIFIED/NEEDS_REPAIR/UNVERIFIED + 聚合规则） | `test_messaging_contract_schemas.py` 等；Java `FeasibilityReportContractTest` | 同上 | 权威状态徽章（已验证/待修复/未验证） | 无 |
| 3 | Trip Skeleton 与住宿三态 | 已完成 | `planning/trip_skeleton.py`、`planning/validation_projection.py` | `test_trip_skeleton.py`（816 行）、`test_accommodation_projection.py` | provider plan/replan/repair 投影 | 住宿待确认/区域估算/已确认语义 | 骨架是瞬态聚合，不入库 |
| 4 | 路线端点与跨日连续性 | 已完成 | `feasibility/rules/continuity.py` | `test_planning_outcome_flow.py`、`test_golden_matrix.py`（G04/G05/G06/G07） | 同上 | 跨日断档→NEEDS_REPAIR；未知住宿→UNVERIFIED | 无 |
| 5 | Opening evidence 与营业时间 | 已完成 | `guide_intelligence/opening_evidence.py`、`feasibility/rules/opening.py`、B9 `OpeningAvailability` 放置 | `test_opening_placement.py`、`test_amap_feasibility_projection.py` | 同上 | 营业窗口约束放置 + OPENING_HOURS 结论 | BREAKFAST 在规划域外（LUNCH/DINNER） |
| 6 | Visit Duration Profile | 已完成 | `planning/visit_duration.py`、`feasibility/rules/duration.py` | `test_visit_duration_profile.py`、`test_daily_schedule.py` | 同上 | 时长 min/max 硬校验 | 无 |
| 7 | 显式 Meal Window | 已完成 | `feasibility/rules/meal.py`、`planning/daily_schedule.py` `MealDemand` | `test_meal_window_placement.py` | 同上 | 显式用餐窗口 + 冲突显式化 | 无 |
| 8 | bounded repair/replan | 已完成 | `feasibility/repair/`（session/engine/catalog）+ `processor._repair_if_needed` | `test_planning_outcome_flow.py`（1/3 轮、fingerprint、action_codes） | 同上 | 最多三轮修复历史 | 无 |
| 9 | 编辑后重新验证 | 已完成 | `ItineraryService.validateEditCandidate(s)` + `candidate_validation.py` + V34 | `ItineraryEditFlowIntegrationTest`、`PlanningCandidateValidationCommandContractTest` | `POST /itinerary/edits`、`/edits/commit` | 编辑仅经 candidate 门禁生效 | 无 |
| 10 | 回滚重新验证 | 已完成 | `ItineraryVersionService.validateRollback` + ROLLBACK_VALIDATE | `ItineraryEditFlowIntegrationTest`、`PlanningCompletionFlowIntegrationTest` | `POST /itinerary/rollbacks` | 回滚不继承历史 report | 无 |
| 11 | Feasibility 前端 | 已完成 | `FeasibilityReportPanel.vue`、`PlanningReviewPanel.vue`、`lib/feasibility.ts` | `FeasibilityReportPanel.test.ts`、`PlanningReviewPanel.test.ts`、E2E 16 场景 | TripWorkspace outcome 状态机 | 权威面板/候选隔离/无历史验证 | 无 |
| 12 | Golden scenarios | 已完成 | `docs/architecture/golden-scenario-catalog.md`（30 场景）+ 三层消费 | `test_golden_matrix.py`、`golden-journeys.spec.ts`、Java integration | — | 跨层语义锁定 | realProviderRequired 场景的真实网络验证属可选运维门禁 |
| 13 | Java/Python 结构化日志 | 已完成 | `PlanningLogContext` + logback；`worker/structured_logging.py` | `PlanningLogContextTest`、`test_structured_logging.py` | listener/service/processor 边界 | 关联字段可跨层关联 | 无 |
| 14 | completion v9 / review v1 | 已完成 | `worker/contracts.py` + Java 两 parser fail-closed | `PlanningCompletedEventParserTest`（57）、`PlanningReviewRequiredEventParserTest`（23） | Rabbit 事件链 | VERIFIED→版本；其余→候选 | 无（B11_FIX_1 修复 null id 漂移） |
| 15 | Java 持久化/Task API/SSE/VersionSummary | 已完成 | `planning/` 服务层 + `PlanningTaskEventStreamService` | 433 Java tests（integration DB read-back） | REST/SSE | 六态任务、实时进度、版本历史 | 无 |
| 16 | Demo 与真实 Provider 安全边界 | 已完成 | `demo/planning_provider.py`（不伪造 evidence/住宿）、`amap/planning_provider.py`（provider evidence 不升级） | `test_entry_matrix.py`、`test_validation_projection.py` | DEMO_ONLY/REAL_ONLY 模式 | Demo 缺证据必 UNVERIFIED；must-visit 无法验证时 fail-closed | Demo 无法验证 must-visit（明确设计） |
| 17 | 本地 Compose 运行 | 已完成 | `compose.prod.yaml` + `.env.example` | B11 全栈验证 + b11_demo_smoke | `docker compose up` | DEMO_ONLY 主链全通（注册→规划→WAITING_USER→候选） | 无 |
| 18 | 契约/迁移/跨语言一致 | 已完成 | `contracts/` fixtures、Flyway V1–V34、三端枚举 | `test_messaging_contract_schemas.py`、parser tests、`TripPaceMigrationIntegrationTest` | — | 三端一致 | 无（B11_FIX_1 修复最后一处 null 语义漂移） |

### 三、架构调用链最终审计

- **创建/重规划**：REST → PlanningTaskService（事务内 outbox）→ Rabbit command → Python provider → TripSkeleton/ValidationInputs → run_validation → bounded repair → completion v9 / review v1 → Java parser（fail-closed）→ service（事务）→ Task API/SSE → Web。B11 端到端 smoke 全链验证 ✓。
- **编辑**：draft → preview → validateEditCandidate(s)（candidate 不写版本）→ N-1/N/N+1 → validator/repair → VERIFIED→USER_EDIT 版本（仅 PlanningCompletionService 内部）/ 其余→review 候选且 current 不变 ✓。
- **回滚**：历史版本 → validateRollback → 当前约束与证据重验 → VERIFIED→ROLLBACK 版本（不复制历史 report）/ 其余→候选 ✓。
- **Feasibility**：TripSkeleton + ValidationInputs → 11 规则 → 四态 outcome → 三态聚合 → fingerprint → 版本/task outcome 持久化 → API/SSE/Web ✓。
- **绕过检查**：版本创建三入口（createInitialItinerary/createReplanVersion/createCandidateVersion）仅被 PlanningCompletionService 调用（全仓 grep 证实）；controller 编辑/回滚端点全部走 candidate 门禁；无第二套硬规则（PlanEvaluationPanel 明确标注"仅代表体验质量，不代表硬可行性验证"）；evaluation 仅在 VERIFIED 分支执行（test_evaluator_called_only_when_verified）；candidate 与 current 隔离；历史 report 不被 edit/rollback 继承；三端状态枚举一致（B10 验收复核）。
- **观察（非阻断技术债）**：`ItineraryService.applyEdit/applyEdits`（直接写 USER_EDIT 版本的历史方法）仅剩 `ItineraryEditFlowIntegrationTest` 调用，无生产 controller 入口；B8 已确认该测试 seam 保留。记录为技术债，不改（超出 B11 最小修复范围，无生产影响）。


## 四、最终功能验收矩阵（Golden catalog 30 场景汇总）

以 `docs/architecture/golden-scenario-catalog.md` 为权威。消费层：Python `test_golden_matrix.py`（orchestrator 级 G04/G05/G06/G07/G09/G11 结构断言）、Java 433 integration tests（G23–G30 持久化/SSE/VersionSummary）、Web 16 E2E（G20/G26/G27 等 UI 权威 outcome）、B11 端到端 Compose smoke（DEMO_ONLY 主链）。

| 场景 | 期望可行性 | blocking/reason | repair | 版本变更 | outcome | 锁定层 |
| --- | --- | --- | --- | --- | --- | --- |
| G01 晚到 / G02 早离 | UNVERIFIED | CROSS_DAY_CONTINUITY | 0 | 无 | REVIEW_REQUIRED | catalog 语义 + Python 测试（G05/G06 同族） |
| G03 单日 | VERIFIED | 无 | 0 | 建 v1 | COMPLETED | Python（outcome_flow VERIFIED 族） |
| G04 confirmed hotel | VERIFIED | 无 | 0 | 建 v1 | COMPLETED | Python G04（CROSS_DAY_ENDPOINTS_CONTINUOUS） |
| G05 area-estimated | UNVERIFIED | ACCOMMODATION_AREA_ESTIMATED | 0 | 无 | REVIEW_REQUIRED | Python G05 |
| G06 unresolved | UNVERIFIED | ACCOMMODATION_UNRESOLVED | 0 | 无 | REVIEW_REQUIRED | Python G06 |
| G07 跨日连续 | VERIFIED | 无 | 0 | 建 v1 | COMPLETED | Python G04 测试承载 |
| G08 跨日断档 | NEEDS_REPAIR | OVERNIGHT_ENDPOINT_MISMATCH | ≥1 | 无 | REVIEW_REQUIRED | catalog（B10.1 S1 修正）+ continuity.py 语义 |
| G09 营业窗口 | VERIFIED | 无 | 0 | 建 v1 | COMPLETED | Python G09（OPENING_HOURS_VERIFIED） |
| G10 临时闭馆 | NEEDS_REPAIR | VENUE_CLOSED | ≥1 | 无 | REVIEW_REQUIRED | 规则语义 + Web review 面板 E2E |
| G11 stale opening | UNVERIFIED | OPENING_HOURS UNKNOWN | 0 | 无 | REVIEW_REQUIRED | Python G11（无 hard-eligible 断言） |
| G12 conflicting opening | UNVERIFIED | 同上 | 0 | 无 | REVIEW_REQUIRED | 规则语义 |
| G13 跨午夜 / G14 last-entry | VERIFIED | 无 | 0 | 建 v1 | COMPLETED | `test_opening_placement.py`（+1440/last-entry 秒级边界） |
| G15 显式 meal 窗口 | VERIFIED | 无 | 0 | 建 v1 | COMPLETED | `test_meal_window_placement.py` |
| G16 不可满足 meal | NEEDS_REPAIR | MEAL_WINDOW | ≥1 | 无 | REVIEW_REQUIRED | 同上 |
| G17 duration min/max | VERIFIED | 无 | 0 | 建 v1 | COMPLETED | `test_visit_duration_profile.py` + outcome_flow CLAMP_VISIT_DURATION |
| G18 duplicate POI repair / G19 transit repair | VERIFIED | （修复后） | 1 | 建 v1 | COMPLETED | `test_planning_outcome_flow.py`（action_codes/fingerprint） |
| G20 repair 耗尽 | NEEDS_REPAIR | DUPLICATE_POI | 3 | 无 | REVIEW_REQUIRED | Python 三轮测试 + Web G20 E2E（尝试 1/2/3 有序） |
| G21 REAL_ONLY 失败 / G22 Demo fallback | FAILED / UNVERIFIED | PLANNING_FAILED / OPENING UNKNOWN | 0 | 无 | FAILED / REVIEW_REQUIRED | `test_provider_fallback_policy.py`、`test_provider_error_mapping.py` |
| G23 edit verified | VERIFIED | 无 | 0 | USER_EDIT v+1 | COMPLETED | Java `verifiedEditCandidateAtomicallyBecomesCurrentWithFreshReport` |
| G24 edit needs repair | NEEDS_REPAIR | OPENING_HOURS | ≥1 | 无 | REVIEW_REQUIRED | Java + Web review 面板 |
| G25 edit stale baseline | FAILED | STALE_ITINERARY_VERSION | 0 | 无 | FAILED | Java `staleEditCandidateCompletionFailsWithoutCreatingAVersion` |
| G26 rollback verified | VERIFIED | 无 | 0 | ROLLBACK v+1 | COMPLETED | Web G26 E2E（版本 3 + 历史回滚 badge） |
| G27 rollback unverified | UNVERIFIED | CROSS_DAY_CONTINUITY | 0 | 无 | REVIEW_REQUIRED | Web G27 E2E（候选隔离、无"已验证"） |
| G28 duplicate outcome | VERIFIED（幂等） | 无 | 0 | 仅一次 | COMPLETED | Java `handlesTheSameCompletedEventMoreThanOnce...` |
| G29 SSE reconnect | VERIFIED | 无 | 0 | 建 v1 | COMPLETED（Last-Event-ID） | Web E2E（feasibility-outcomes reconnect 场景） |
| G30 历史无 report | feasibility=null | 无 | 0 | 无 | 显示"无历史验证" | Web E2E + Java `listsVersionSummaries...NullForHistory` |

B11 端到端补充：DEMO_ONLY 主链（注册→行程→排队→WAITING_USER→UNVERIFIED report+candidate→versions 空→latest 一致）在 Compose 全栈下全通；修复 B11_FIX_1/2 后 Java parser 与 Python Demo 输出在真实 Rabbit 链上互相接受。

## B11_FIX 清单

### B11_FIX_1：Java parser 拒绝合法 null activityId/transitId（跨语言契约漂移）

- 发现：DEMO_ONLY 端到端 smoke 中，review 事件被 Java 拒绝（`activityId must be a UUID string`），任务永远 RUNNING。
- 根因：Python 契约 `ItineraryActivity.activity_id: UUID | None`、`TransitLeg.transit_id: UUID | None` 明确允许 null（占位活动无解析 POI id 是合法状态）；Java `PlanningReviewRequiredEventParser` 的 activityId 校验与 `PlanningCompletedEventParser` 的 activityId/transitId 校验缺 null 特判（同文件 transitId 已有特判，内部不一致）。
- 修复：三处校验补 `!isNull()` 特判（review activityId、completion activityId、completion transitId）。非文本非 null 值仍 fail-closed。
- TDD：先写 4 个 RED 测试（review parser +2、completion parser +2），确认原实现拒绝 null；修复后 GREEN（review parser 23 用例、completion parser 57 用例全过）。
- 未触碰：Python 契约、规则语义、其他 schema。

### B11_FIX_2：Demo provider 活动未按时间排序

- 发现：修复 FIX_1 后 smoke 再报 `activities must be ordered without overlap`——Demo 每天输出 meal 占位（12:00）在前、探索块（09:00）在后。
- 根因：`infrastructure/demo/planning_provider.py` 的 `_day_skeleton` 先 extend meal placeholders 再 append 探索块，未按 start_time 排序；Java parser 的 fail-closed 排序校验拒绝。
- 修复：`return ItineraryDay(...)` 前 `sorted(activities, key=lambda a: a.start_time)`。不改活动内容/语义。
- TDD：新增 `tests/test_demo_ordering.py`，断言每天活动 start_time 非降序且无重叠；修复前 RED（12:00 在 09:00 前），修复后 GREEN。

### 端到端验证（DEMO_ONLY，Compose 全栈）

- 8 容器全部 healthy（postgres/redis/rabbitmq/agent-service/agent-api/travel-server/web/prometheus），knowledge-init exit 0。
- 修复后主链 smoke：注册→健康→创建行程→排队→WAITING_USER 终态→report=UNVERIFIED+candidate→versions 空→latest 一致，全部通过。
- golden_scenarios_http.py 在 DEMO_ONLY 下：场景 1-3 因 must-visit 无法验证而 FAILED（Demo fail-closed 安全行为，非缺陷）；场景 4 到达 WAITING_USER 合法终态（脚本按 REAL_ONLY 期望 SUCCEEDED 故报 TIMEOUT）。该脚本属 REAL_ONLY 可选项；真实 AMap 验证未运行 → OPTIONAL_PROVIDER_NOT_RUN，不判失败。


## 门禁结果

（随实施更新。）

## 五、完整门禁结果（B11 真实数字）

| 门禁 | 结果 |
| --- | --- |
| Python 全量 | **1371 passed, 37 skipped**（B10 基线 1370 + 1 新增 demo ordering 测试） |
| Ruff | All checks passed；format --check 通过 |
| Java verify | **BUILD SUCCESS，433 tests，0 failures/errors**（B10 基线 429 + 4 parser 测试） |
| Web unit | **311 passed**（33 files） |
| Web coverage | **96.04 / 82.20 / 95.52 / 96.04** |
| Web typecheck / build | 通过 / 通过 |
| Playwright（CI=1） | **16 passed** |
| Markdown links | **105 files valid** |
| gitleaks | 181 commits 扫描，**no leaks found** |
| .env | 未跟踪且 gitignored ✓ |
| staged | 空 |

## 六、本地运行验收

- `docker compose -f compose.prod.yaml --env-file .env config`：exit 0。
- 独立项目名（trip-pilot-b11，避开用户现有卷/端口）+ DEMO_ONLY 覆盖启动：8 容器全部 healthy，knowledge-init exit 0。
- DEMO_ONLY 主链 smoke（注册→健康→创建行程→排队→终态 WAITING_USER→report=UNVERIFIED+candidate→versions 空→latest 一致）：**PASS**（修复 B11_FIX_1/2 后）。
- golden_scenarios_http.py：场景 1-3 因 Demo 无法验证 must-visit 而正确 FAILED（fail-closed）；场景 4 到达 WAITING_USER 合法终态。该脚本按 REAL_ONLY 编写，真实 AMap 验证未运行 → **OPTIONAL_PROVIDER_NOT_RUN**（不判失败）。
- 测试容器已 down 清理，无遗留资源；未修改用户既有容器/卷/数据库。

## 七、安全与日志验收

- gitleaks 无泄漏；`.env` 未跟踪且 gitignored；AGENT_INTERNAL_TOKEN / INTERNAL_DIAGNOSTICS_TOKEN 均 `:?required` 独立，不回退 JWT_SECRET。
- 日志（B10 已验收 + B11 复核）：无完整 payload/secret/Provider body；Java MDC 快照/恢复测试覆盖异常/duplicate/reject；Outbox SENT/RESCHEDULED/DEAD 日志在位（MAX_ATTEMPTS=10 不变）；traceId/taskId/eventId 跨层一致（Compose 日志实测 traceId=taskId 关联可见）。

## 收口状态

（随实施更新。）
