# B16 执行报告：信息不足非阻塞规划机制改造（Information Missing != Planning Failed）

- 状态：**B16_IMPLEMENTED**（unstaged，未 commit，未 push）
- 阶段：B16（Backend/Python + Java + Contract + Frontend 全链路）
- BASELINE_HEAD：`d10e70cf354d096300c4a348d6aef585b8d82dc8`（`feat(platform): complete local-first trip planning release`）
- 计划：见同目录 [验收报告](acceptance-report.md)（本批次无独立 plan.md，计划与验收结论见该报告）
- 交付物：本报告 + 代码改动 + 测试结果

## 1. 开始前 Git 状态

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `d10e70cf354d096300c4a348d6aef585b8d82dc8`（未变） |
| staged | 空（`git diff --cached --name-only` 0 行，全程保持） |
| `.env` | 未读、未修改 |

约束遵守：未 reset/stash/checkout/restore/clean/rebase/amend；未 stage/commit/push；未修改 `.env`；未改动既有 Flyway 迁移（仅新增 V37）；未改动 Compose/RabbitMQ；未改动既有 coverage 门槛。

> 注：工作区存在 B15 遗留的未提交改动（`feasibility/rules/core.py`、`test_core_rules.py`、`AuthView.vue`、`TripDashboard.vue`、`places/api.py` 等），非本次 B16 产生，未触碰。

## 2. 根因（审计结论）

「信息不完整 → 规划失败」的完整根因链：

1. `feasibility/models.py` 聚合：`unknown_count > 0 → UNVERIFIED`（语义正确）。
2. Python `worker/contracts.py` v9 completion 强制要求 `VERIFIED`，否则只能发 `PLANNING_REVIEW_REQUIRED`（WAITING_USER）。
3. Java `PlanningCompletionService.handleInScope` L89-92 硬门槛：「v9 completion 需要 VERIFIED feasibilityReport」。
4. Java Parser `validateFeasibilityReport` 同样强制 `status == VERIFIED`。
5. 数据库 V33 `ck_ifr_status_verified_only CHECK (status = 'VERIFIED')` 拒绝入库。
6. 前端 `readTerminalOutcome`：`SUCCEEDED` 分支要求 `report.status === 'VERIFIED'`，否则 `malformed`；FeasibilityReportPanel 对非 VERIFIED 一律显示「暂无行程验证结果」。

**fallback 已存在（无需新建）**：`planning/poi_quality.py` 的 `_LIGHT/_NORMAL/_HALF_DAY/_FULL_DAY/_DEFAULT` profiles（`DurationProfileSource`：PROVIDER/OFFICIAL_FACT 可硬约束；CATEGORY_PROFILE/CATEGORY_FALLBACK/SYSTEM_DEFAULT 非硬约束 + confidence 标识）；营业时间 UNKNOWN 容忍（仅 VERIFIED 证据可 FAIL）；Provider 部分失败 → evaluation warning（`PROVIDER_FALLBACK_USED` 等）。

## 3. 业务规则（最终版）

**WARNING（不阻止保存）**——满足任一：
- 营业时间 UNKNOWN（无 VERIFIED 证据）
- 游玩时长估算（CATEGORY/SYSTEM fallback，非硬约束）
- 路线端点/住宿未核实（UNKNOWN）
- Provider 部分 fallback（evaluation warning）

**BLOCKER（阻止保存 → REVIEW_REQUIRED）**——满足任一：
- 任意硬规则 FAIL（如活动重叠、营业时间与行程冲突且证据 VERIFIED）
- 缺失必选规则（missingRequiredRuleIds 非空）

**判定函数**：`has_blocker = fail_count > 0 or missing_required非空`；`can_save = not has_blocker`。UNKNOWN 永不产生 blocker。

## 4. 契约升级：v10（非破坏性）

| 项 | 内容 |
| --- | --- |
| 新 schema | `contracts/messaging/planning-completed-event-v10.schema.json` |
| 变更点 | `schemaVersion` const=10；payload 增加 `hasBlocker: boolean`（required）；`feasibilityReport.status` 放宽为 `enum [VERIFIED, UNVERIFIED, DRAFT]`（原 const VERIFIED） |
| 兼容性 | v9 schema 原样保留；v9 事件仍被 Java 接受（行为不变）；数据库仅放宽 CHECK（V37），非破坏性迁移 |
| 共享 fixture | `contracts/fixtures/planning-completed-event-v10/completion-v10-unverified-savable.json`（过 schema 校验） |

## 5. 分层修改（TDD：RED → GREEN）

### Python（`apps/agent-service`）

| 文件 | 修改 |
| --- | --- |
| `feasibility/models.py` | `FeasibilityReport` 增加派生属性 `has_blocker`/`can_save`（property，从 `summary.fail_count` + `missing_required_rule_ids` 推导；**不进 wire**，report wire 结构保持 v1 稳定） |
| `worker/contracts.py` | 新增 `PlanningCompletedPayloadV10(PlanningCompletedPayloadV9)` + `PlanningCompletedEventV10`（schema_version=10，`has_blocker` 与 report 一致性 validator，禁止 blocker） |
| `worker/processor.py` | `process_planning_create`/`process_planning_replan`/`process_candidate_validation` 三处发布决策：`if not report.has_blocker → v10 COMPLETED`，否则 REVIEW_REQUIRED |
| 测试 | `test_feasibility_models.py` 真值表（8 组）+ 3 专项；`test_planning_outcome_events.py` 4 个 v10 测试；更新 8 个既有测试文件的断言（v9→v10、review→completed 语义） |

### Java（`apps/travel-server`）

| 文件 | 修改 |
| --- | --- |
| `PlanningCompletedEvent.java` | `Payload` 增加 `boolean hasBlocker` 字段（第 9 参）+ 兼容构造器 |
| `PlanningCompletedEventParser.java` | 接受 schema 9/10；v10 校验 `hasBlocker` boolean + 与 report 一致性（blocker report 拒收，`feasibilityReport status must be VERIFIED`）；activityId/transitId/provenance/evaluation/feasibilityReport 版本白名单加 10；transit 相邻性 v10 同 v8/v9 放宽 |
| `PlanningCompletionService.java` | fail-closed 门槛：v9 仍要求 VERIFIED；v10 接受非 VERIFIED 但 `hasBlocker=false` |
| `V37__relax_feasibility_report_status.sql` | 新迁移：`ck_ifr_status_verified_only` → `ck_ifr_status_supported (status IN ('VERIFIED','UNVERIFIED','NEEDS_REPAIR'))`（仅放宽，非破坏） |
| 测试 | ParserTest +4（v10 接受 savable UNVERIFIED / 拒 blocker / 拒 mismatch / 拒非 boolean）；集成测试 +2（保存 UNVERIFIED 无 blocker v10 / parser 拒 blocker） |

### 前端（`apps/web`）

| 文件 | 修改 |
| --- | --- |
| `lib/feasibility.ts` | `readTerminalOutcome` SUCCEEDED 分支：接受「VERIFIED 或（非 VERIFIED 且 failCount=0 且 missingRequiredRuleIds 空）」 |
| `components/FeasibilityReportPanel.vue` | 新增 PASS_WITH_WARNINGS 分支：「行程已生成，部分信息仍待确认」+ 已保存徽标 + 出发前确认提示 |
| `lib/feasibility-presentation.ts` | UNKNOWN 文案改为「采用系统建议/估算时长，建议出发前确认」 |
| 测试 | `feasibility.test.ts` +2（blocker-free UNVERIFIED completed / missing-required malformed）；`FeasibilityReportPanel.test.ts` 更新 B16 语义；`feasibility-presentation.test.ts` 文案更新；e2e 文案更新（2 处） |

## 6. 真实测试结果

| 层 | 命令 | 结果 |
| --- | --- | --- |
| Python | `uv run pytest -q --basetemp .pytest-tmp` | **1529 passed, 37 skipped, 0 failed** |
| Python | `uv run ruff check .` | **All checks passed** |
| Java | `mvn --batch-mode -pl apps/travel-server verify` | **528 tests, 0 failures, BUILD SUCCESS**（含 Testcontainers Postgres + Flyway V37） |
| 前端 unit | `pnpm test` | **442 passed, 0 failed**（42 files） |
| 前端 | `pnpm typecheck` + `pnpm build` | **OK / OK** |
| 前端 e2e | `pnpm test:e2e` | **未运行**（环境限制：本 Windows 会话 vite dev server 无法绑定端口 EACCES，非代码问题；unit/typecheck/build 已覆盖） |

> 注：全量 pytest 需 `--basetemp` 指向工作区目录，因 `C:\Windows\Temp\pytest-of-xx` 在当前环境有权限限制（环境问题，非代码问题）。

## 7. Case 1-10 覆盖矩阵

| Case | 场景 | 结果 | 覆盖测试 |
| --- | --- | --- | --- |
| 1 | VERIFIED → v10 completed，hasBlocker=false | PASS | test_v10_accepts_verified_report / g04 / g09 |
| 2 | UNVERIFIED 无 blocker → v10 completed 可保存 | PASS | test_v10_accepts_unverified_no_blocker_report / g05 / g06 / g11 / 集成测试 |
| 3 | 有 FAIL（blocker）→ 拒发 completed → review | PASS | test_v10_rejects_blocker_report / v10RejectsBlocker / test_hard_fail_emits_needs_repair_review |
| 4 | 缺失必选规则（missing required）→ blocker | PASS | test_missing_required_rule_keeps_can_save_false_when_unknown |
| 5 | hasBlocker 与 report 不一致 → 拒收 | PASS | test_v10_payload_rejects_has_blocker_mismatch / v10RejectsHasBlockerMismatch |
| 6 | 营业时间 UNKNOWN（无证据）→ UNVERIFIED 可保存 | PASS | test_opening_unknown_with_no_evidence_accepted_unverified / Case 8 实证 |
| 7 | 营业时间 FAIL（VERIFIED 证据冲突）→ blocker | PASS | test_opening_fail_requires_verified_eligible_evidence |
| 8 | 广州两日游：营业时间未知 + 时长估算 → 仍保存 | PASS | **实证脚本**：UNVERIFIED，has_blocker=False，v10 completed，schema 0 错误 |
| 9 | 前端 SUCCEEDED+UNVERIFIED 无 blocker → completed 渲染 PASS_WITH_WARNINGS | PASS | feasibility.test.ts / FeasibilityReportPanel.test.ts |
| 10 | 前端 SUCCEEDED+blocker（FAIL/missing）→ malformed fail-closed | PASS | feasibility.test.ts（+2 新增） |

## 8. 遗留与说明

- e2e 因本环境 vite 端口绑定 EACCES 无法运行（非代码问题）；B16 相关文案断言已在 e2e spec 中更新，CI 环境可跑。
- 工作区存在 B15 遗留未提交改动（与本任务无关，未触碰）。
- 数据库迁移 V37 仅放宽约束，生产数据无破坏；若需回滚，删除约束即可（数据不受影响）。
- 独立验收 Agent 应补充 `docs/execution/B16/acceptance-report.md`。
