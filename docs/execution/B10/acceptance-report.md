# B10 Golden Scenarios、结构化日志与最终质量收口验收报告

- 批次：B10
- 验收 Agent：B10 独立验收（未参与实现，对抗性审查）
- 日期：2026-08-13
- Verdict：**NEEDS_SMALL_FIX**（两处文档/测试名称级缺陷，无业务代码缺陷）

## 1. 基线

- branch=`codex/feasibility-foundation` ✓
- HEAD=`7c0da66024ac540652aac9b8f6a352fdf2984cc6`（B9 提交）✓
- staged 空 ✓
- 未跟踪仅保护目录（.omo/ .serena/ docs/audits/）与 B10 本批文件 ✓

## 2. 精确 diff 范围

Python：`worker/structured_logging.py`（A）、`worker/processor.py`（M）、`worker/amqp.py`（M）、`tests/test_golden_matrix.py`（A）、`tests/test_structured_logging.py`（A）。
Java：`planning/PlanningLogContext.java`（A）、`logback-spring.xml`（A）、3 listener（M）、`PlanningCompletionService`/`PlanningReviewService`/`PlanningFailureService`/`PlanningTaskService`（M）、`TransactionalOutboxPublicationAttempt`（M）、`PlanningLogContextTest.java`（A）。
Web：`e2e/golden-journeys.spec.ts`（A）。
文档：`docs/architecture/golden-scenario-catalog.md`（A）、规划工作流/事件契约/行程真实性与旅行骨架/测试策略/可观测性/项目路线图（M）。

无 contracts/Flyway/规则语义改动；`feasibility/rules/*`、`planning/daily_schedule.py`、`validation_projection.py`、`infrastructure/demo/*` 均未被触碰。

## 3. 15 项验收重点逐项结论

1. **Golden 测试真实跨层**：PASS。`test_golden_matrix.py` 经 `process_planning_create` 走完整 orchestrator（provider.plan → run_validation → _repair_if_needed → evaluator → outcome event），断言的是聚合事件类型 + report.status + 单条规则 outcome/reason_code 结构，非直接调用规则；固定 `_TS`/固定 UUID。golden-journeys 用真实 task↔version 关系（versionSummary.planningTaskId 指向对应 task，WAITING_USER 任务无版本）。
2. **VERIFIED/REVIEW 门禁**：PASS。`PlanningCompletionService` 的 schemaVersion==9、VERIFIED report、evaluation 必填 gate 全部保留（包装为 handleInScope 未删减）；`PlanningReviewService` 的 validateReport（非 VERIFIED）、validateCandidateIntegrity（raw snapshot + fingerprint + typed 一致性）全部保留。
3. **日志不泄密**：PASS。逐条检查 8 个 Java 落点与 Python processor/amqp/structured_logging：只记录 UUID、eventType、taskType、versionNumber、errorCode、errorCategory、retryCount、exception class simple name；无 payload/body/evidence/secret/JWT/Provider 原始响应。`test_log_messages_do_not_contain_secret_material` 以 forbidden 词表断言。
4. **MDC 生命周期**：PASS。`PlanningLogContext` 快照/恢复语义正确（嵌套不互清、无 unrelated key 干扰、异常路径恢复）；三个 listener 的 catch 均位于 try-with-resources 内（close 先于 catch 执行，MDC 已恢复）；`PlanningLogContextTest` 覆盖 success/exception/nested/blank/unrelated 五路径；reject/duplicate 路径同处 try 块内。
5. **字段无漂移**：PASS。Java `PlanningLogContext` 常量（camelCase）与 Python `structured_logging` 字段（snake_case）逐项对应：traceId/trace_id、eventId/event_id、taskId/task_id、tripId/trip_id、runId/run_id、taskType/task_type、candidateType/candidate_type、schemaVersion/schema_version、eventType/event_type、outcomeStatus/outcome_status、attemptIndex/attempt_index、provider、operation、retryable、fallbackAttempted/fallbackSucceeded、retryCount。Python 文档字符串列出的边界字段是 Java 字段集的子集，无冲突。
6. **Catalog 与测试漂移**：**NEEDS_SMALL_FIX**。发现 G08 行语义漂移：`G08_CROSS_DAY_BROKEN` 期望 `UNVERIFIED` + blocking `ROUTE_ENDPOINT_CONTINUITY`。按 `feasibility/rules/continuity.py` 代码语义：缺 transit leg 是 FAIL（ROUTE_LEG_MISSING）→ 聚合 NEEDS_REPAIR；overnight 端点不匹配也是 FAIL（OVERNIGHT_ENDPOINT_MISMATCH）→ NEEDS_REPAIR；仅"端点无坐标"才 UNKNOWN → UNVERIFIED。无论"跨日断裂"取哪种解释，expectedStatus 都不应为 UNVERIFIED。G04/G05/G06/G09/G11 的期望与测试断言逐字一致（已核对）。
7. **candidate 隔离**：PASS。G27 验证 review 面板出现且其内部不含"已验证"、formal itinerary 保持可见；G26 验证 VERIFIED 后 review 面板 0 个。见发现 2（G26 测试名夸大，不影响该语义本身已有 Java integration 测试锁定 USER_EDIT/ROLLBACK 版本创建）。
8. **Demo 假 VERIFIED 回归**：PASS。本批 diff 未触碰 `infrastructure/demo/*`、`validation_projection.py`；Python 全量 1370 通过含既有 demo unverified 锁定测试。
9. **repairAttempts 真实**：PASS。golden-journeys G20 断言「尝试 1/2/3」按顺序渲染 + DUPLICATE_POI 剩余问题可见；Python 侧 repair 精确断言已由既有 `test_planning_outcome_flow.py` 锁定（1/3 轮、fingerprint、action_codes），执行报告如实说明 5 个新用例未新增 repair 场景。
10. **coverage 包含本批文件**：PASS。Python `structured_logging.py` 实测 100%（12/12 stmts，独立复跑）；Java `PlanningLogContext` 由 5 用例全分支覆盖；Web coverage include 含 `feasibility.ts`、`FeasibilityReportPanel.vue`、`PlanningReviewPanel.vue`（E2E 不在 vitest 范围，属正常）。
11. **E2E 无虚假 DB 关系**：PASS。golden-journeys 的 version.planningTaskId↔task 关系真实：current 版本指向 oldTaskId 的 SUCCEEDED 任务，WAITING_USER 的 rollback 任务在 versions 中无版本，latest 端点 404。
12. **随机性/顺序依赖**：PASS。Python golden 用固定 `_TS` + `make_command()`（固定 COMMAND UUID）；Java 生产代码用注入 Clock（既有模式）；无 sleep、无全局状态共享。
13. **B9 opening/meal/duration 回归**：PASS。diff 未触碰三条规则及其语义文件；Python 全量与既有 B9 测试（opening placement/meal window/entry matrix）全部通过。
14. **文档无生产部署门禁重引入**：PASS。catalog 边界节、可观测性、测试策略均明确"本地优先、真实网络验证属独立运维门禁、Prometheus/外部日志平台可选"，未出现 staging/TLS/registry/24h soak。
15. **execution-report 真实性**：PASS。逐项核对：Python 1370/37 ✓（独立复跑一致）、Java 429 ✓、Web 311 ✓、coverage 96.04/82.20/95.52/96.04 ✓（独立复跑一致）、E2E 16 ✓、links 101 ✓。报告对"5 用例覆盖 6 个场景 ID（G07 由 G04 测试的 CROSS_DAY_ENDPOINTS_CONTINUOUS 断言承载）"表述属实。

## 4. 独立门禁复跑（真实数字）

| 门禁 | 结果 |
| --- | --- |
| Python 全量 | **1370 passed, 37 skipped**（6.94s） |
| Ruff | **All checks passed** |
| Java verify | **BUILD SUCCESS，429 tests，0 failures/errors**（TripPaceMigrationIntegrationTest 的 V3 失败属其预期拒绝非法 pace 用例，非门禁失败） |
| Web unit | **311 passed**（33 files） |
| Web coverage | **96.04 / 82.20 / 95.52 / 96.04** |
| Web typecheck | 通过（vue-tsc -b） |
| Playwright（CI=1） | **16 passed** |
| Markdown links | **101 files valid** |
| staged | 空 |

## 5. 发现清单

### NEEDS_SMALL_FIX-1（文档语义漂移）
- 文件：`docs/architecture/golden-scenario-catalog.md:44`（G08 行）
- 问题：`G08_CROSS_DAY_BROKEN` 的 expectedStatus=UNVERIFIED 与 blocking=ROUTE_ENDPOINT_CONTINUITY 组合在代码语义下不成立。缺 leg 或 overnight 端点不匹配均为 FAIL → NEEDS_REPAIR；仅端点缺坐标才 UNKNOWN → UNVERIFIED。
- 修复方向：G08 行 expectedStatus 改 `NEEDS_REPAIR`，blocking 改 `ROUTE_ENDPOINT_CONTINUITY / ROUTE_LEG_MISSING`（或改注释明确"缺坐标才 UNVERIFIED"）。

### NEEDS_SMALL_FIX-2（E2E 测试名夸大）
- 文件：`apps/web/e2e/golden-journeys.spec.ts`（G26 测试）
- 问题：测试名声称 "creates a ROLLBACK version and shows a fresh report"，但 mock 中 `rollbackCompleted` 从未置 true（onRollback 为空操作），versions 端点永不返回 ROLLBACK 版本，测试无任何 ROLLBACK 版本断言。实际断言的是"VERIFIED completion 不进入 review 面板 + 权威 report 渲染"。
- 修复方向：onRollback 置 `rollbackCompleted = true` 并断言「历史回滚」badge 出现；或改名以反映实际断言。

## 6. 声明

- 未修改任何业务代码/测试/契约/文档（除本报告）
- 未 stage/commit/push；未 reset/stash/checkout/restore/clean/rebase/amend
- 保护目录未处理

## 7. Verdict

**NEEDS_SMALL_FIX**。两项均为文档/测试名称级修复，无业务代码缺陷，无门禁失败。修复后由执行 Agent 补充，验收 Agent 追加复验，复验通过后改判 PASS 并允许 Git 收口。

---

## B10.1 复验（2026-08-13）

| 复验项 | 结论 |
| --- | --- |
| 1. G08→NEEDS_REPAIR | PASS。catalog G08 行现为 NEEDS_REPAIR + blocking CROSS_DAY_CONTINUITY / OVERNIGHT_ENDPOINT_MISMATCH（行内证据） |
| 2. reasonCode 与实现一致 | PASS。easibility/rules/continuity.py:322/338 中 confirmed overnight 端点不匹配的真实 FAIL reasonCode 即为 OVERNIGHT_ENDPOINT_MISMATCH，未自行发明 |
| 3. G06 仍为 UNVERIFIED | PASS。G06 行 UNRESOLVED → UNVERIFIED 未变；G05 亦保持 UNVERIFIED，UNKNOWN 住宿未误改为 FAIL |
| 4. G26 名称与断言一致 | PASS。测试保留 creates a ROLLBACK version 名，新增断言：completion 前「版本 2」可见 + 「历史回滚」count 0；completion 后「版本 3」+「历史回滚」badge 可见；markCompleted 置位 fixture 使 versions 返回 v3 ROLLBACK 版本 |
| 5. execution-report 如实 | PASS。B10.1 章节如实记录 A 方案、RED→GREEN（test-failed-1.png 证据）、无夸大 |
| 6. 目标 E2E | PASS。独立复跑 **3 passed**（6.1s） |
| 7. 无业务代码范围泄漏 | PASS。B10.1 仅改 catalog + golden-journeys.spec.ts + execution-report 追加；业务代码 diff（10 个 M 文件，263+/24-）与首次验收时一致，无新增业务修改 |
| 8. staged 空 | PASS。git diff --cached --name-only 空；HEAD=7c0da66 未漂移 |

- 最终 verdict：8/8 全过。

## B10_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT
