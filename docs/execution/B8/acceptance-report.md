# B8 编辑与回滚候选重验证验收报告

- 批次：B8（编辑与回滚候选重验证）
- 验收 Agent：B8 独立验收（未参与实现）
- 日期：2026-08-13
- Verdict：**PASS**

## 1. 基线

- branch=`codex/feasibility-foundation` ✓
- HEAD=`f429f7bfe8dd25db384e1e489e843d35ab11e53b` ✓
- staged 空 ✓；`git diff --check` 通过（仅 CRLF 提示）✓
- B8 未提交 ✓；保护目录 `.omo/`、`.serena/`、`docs/audits/` 保持 untracked ✓

## 2. 精确 diff 范围

B8 业务范围：Python 13 M + 2 A（`application/candidate_validation.py`、`tests/test_candidate_validation.py`）、Java 16 M + 1 A（`PlanningCandidateValidationCommandContractTest.java`）+ 1 A（`V34__add_candidate_validation_tasks.sql`）、Web 3 M、contracts 2 M + 1 A（`planning-candidate-validation-command-v1.schema.json`）+ fixtures A、B8 文档 2 A（plan/execution-report）、架构/产品文档 5 M。

**已排除的下一批次文件**（预声明，非 B8，不计入 B8 diff）：`docs/execution/B9/plan.md`、`docs/execution/B9/execution-report.md`。

无陌生范围改动。

## 3. A-G 逐项结论

### A. Candidate 边界 — PASS
- EDIT/ROLLBACK 均先形成 task-scoped immutable candidate：`ItineraryService.validateEditCandidate/validateEditCandidates` 与 `ItineraryVersionService.validateRollback` 均调用 `PlanningTaskService.createCandidateValidation`，生成 `EDIT_VALIDATE`/`ROLLBACK_VALIDATE` task（不写 itinerary_version）✓
- 未验证 candidate 不写 version：candidate 只存 task 行 + command payload ✓
- production controller 无 direct-write 绕过：`ItineraryController` 的 `/rollbacks`、`/edits`、`/edits/commit` 全部 `@ResponseStatus(ACCEPTED)` 返回 `PlanningTaskResponse` ✓
- 旧 direct-write 方法（`ItineraryService.applyEdit/applyEdits`、`ItineraryVersionService.rollback`）仅被 test 文件内的 `LegacyEditRegressionController`（`ItineraryEditFlowIntegrationTest` 静态嵌套 `@RestController`，路径 `/api/test/...`）调用，不进 production classpath ✓
- Candidate 保存 baseline/candidateType/sourceVersion/requestHash/changedDates/impactedDates：`PlanningTaskRecord` 新增 candidate 元数据字段，V34 落库 ✓

### B. 影响范围 — PASS
- N-1/N/N+1 扩展：`PlanningTaskService.expandCandidateDates`（`date.minusDays(1), date, date.plusDays(1)` 过滤在 trip 范围 + distinct sorted）✓
- changedDates 精确记录（`validateCandidateDates` 去重排序 + trip 范围校验），impactedDates 由 changedDates 扩展 ✓
- 跨日 MOVE 覆盖源/目标日 + 相邻边界（`impacted(source.day(), target, ...)` + N-1/N/N+1 扩展）✓
- ROLLBACK 按目标历史版本重验、不继承历史 report：`createCandidateVersion` 每次新建报告行 ✓

### C. 验证与正式版本门禁 — PASS
- 统一 Hard Validator 11/11 + B7 bounded repair（`CandidateValidationProvider.validate/repair` 复用 provider + validator）✓
- 仅 VERIFIED completion v9 创建正式版本：`PlanningCompletionService.handle` schemaVersion!=9 拒绝 + report 必须 VERIFIED + evaluation 必填 ✓
- EDIT→USER_EDIT / ROLLBACK→ROLLBACK：`ItineraryService.createCandidateVersion` 按 `task.candidateType()` 设 `versionSource` ✓
- 同事务：completion `@Transactional` 内 createCandidateVersion + persistFeasibilityReport + updateTaskToSucceeded + updateCurrentVersion ✓
- NEEDS_REPAIR/UNVERIFIED 走 review-required：`PlanningReviewService` 只 `markWaitingUser`，不建版本/不切 current/不写 report 行（candidate/report 仅存 task outcome）✓
- PlanEvaluation 仅最终 VERIFIED 后（completion 才带 evaluation）✓

### D. Stale 与并发安全 — PASS
- baseline fail closed：`createCandidateValidation` baselineVersionId != current.versionId → CONFLICT；`createCandidateVersion` 再次校验 baseline 匹配 current，否则 rejected ✓
- stale completion/review → `persistStaleFailure`（STALE_TRIP_VERSION/STALE_ITINERARY_VERSION）✓
- null baseline 拒绝 ✓；幂等：`findOwnedByIdempotencyKey` + `requireCandidateMatch` + eventId 幂等 ✓

### E. 字段与投影完整性 — PASS
- dayType/locked/transit locked/kind/providerPoiId/coordinates/provider/cost 经 `persistDay` 全量保留 ✓
- 住宿不伪造 confirmed：`_confirmed_overnight` 要求 ACCOMMODATION + provider_poi_id + coordinates，否则 UnresolvedAccommodation ✓
- opening evidence 不升级：`_validated_fact` 保留 hard_constraint_eligible 原值 ✓
- duration profile / meal binding / repair 后 locator 重建：`_project_validation_state` 从最终 itinerary 重投影（`CandidateValidationProvider.repair` 用 repaired.itinerary 重投影）✓

### F. 契约一致性 — PASS
- `planning-candidate-validation-command-v1.schema.json` + valid/invalid fixtures + Python `PlanningCandidateValidationCommand` + Java `PlanningCandidateValidationCommand` 字段一致（`PlanningCandidateValidationCommandContractTest`）✓
- Rabbit routing key `planning.candidate-validation`（amqp.py:86）与 worker consumer `process_candidate_validation` 对齐 ✓
- V34 CHECK 约束 `ck_planning_task_type`/`ck_planning_task_context` 拒绝非法 taskType/candidateType 组合（EDIT_VALIDATE 必须 candidate_type='EDIT'、ROLLBACK_VALIDATE 必须 'ROLLBACK'、CREATE/REPLAN 不得带 candidate 字段）✓
- completion v9/review v1 新增 locked 字段；v8/v2 旧契约未原地改语义 ✓

### G. Web 隔离 — PASS
- `api.ts` 的 `rollbackItinerary`/`applyItineraryEdit`/`commitItineraryEdits` 返回 `Promise<PlanningTask>`（非 Itinerary）✓
- Web 通过统一 task/SSE 状态机等待结果（TripWorkspace 复用 `attachPlanningStream`/`applyOutcomeState`）✓
- review candidate 不替换正式 itinerary（waiting_user 面板隔离）✓；completion VERIFIED 后刷新正式版本 ✓
- 取消/失败/连接异常清理旧 candidate（`clearPlanningOutcome` 全路径）✓；刷新后 latest task 恢复 WAITING_USER ✓

## 4. 对抗性检查（12 反例）

1. EDIT completion NEEDS_REPAIR → currentVersion 保持（review 不建版本）✓
2. ROLLBACK review UNVERIFIED → 历史 report 不复制（新建报告）✓
3. stale candidate completion → 拒绝（baseline 匹配 + persistStaleFailure）✓
4. candidateType/taskType 不匹配 → V34 CHECK 拒绝 ✓
5. sourceVersion 不属于 trip → validateRollback 校验 + 测试覆盖 ✓
6. 同 idempotency key + 不同 body → requireCandidateMatch 冲突 ✓
7. MOVE 跨日 → changedDates 含两端 + N-1/N/N+1 ✓
8. DELETE 后 locator 重算 → Python 重投影 ✓
9. locked activity/transit 经 completion 保留 → persistDay ✓
10. review candidate 不当作 current → Web 隔离 ✓
11. production context 不加载 test-only controller → 静态嵌套在 test 文件 ✓
12. completion 指纹绑定最终 candidate → createCandidateVersion 用 event.payload().itinerary() ✓

均以结构/DB 状态/事务断言为证据（集成测试 + V34 CHECK），非 containsString。

## 5. 门禁独立复跑

| 门禁 | 结果 |
| --- | --- |
| Python 全量 | **1336 passed, 37 skipped**（独立 basetemp） |
| Ruff | **All checks passed** |
| Java verify（Java 21 + 显式 Maven + Docker 28.5.1） | **424 tests, 0 failures, 0 errors**；JaCoCo 通过；Flyway 干净库迁移至 **V34** |
| Web unit | **311 passed** |
| Web coverage | **96.04% statements / 82.20% branches / 95.52% functions / 96.04% lines** |
| Web typecheck / build | 通过 / 通过 |
| Playwright（CI=1） | **13 passed** |
| Markdown links | **96 files valid** |
| git diff --check | 通过（仅 CRLF 提示） |
| staged | 空 |

全部与 execution-report 声明一致，无漂移。

## 6. 是否允许 Git 收口

**允许。** 未发现 Critical/Important 阻断问题。

## 7. 声明

- 未修改任何业务代码/测试/契约/migration/文档（除本报告）
- 未 stage/commit/push；未 reset/stash/checkout/restore/clean/rebase/amend
- 保护目录 `.omo/`、`.serena/`、`docs/audits/`、`.env` 未处理
- B9 文档（plan.md/execution-report.md）已排除出 B8 验收范围

---

## B8_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT
