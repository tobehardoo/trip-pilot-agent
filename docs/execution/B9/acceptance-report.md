# B9 规划输入与主动放置完善验收报告

- 批次：B9（规划输入与主动放置完善）
- 验收 Agent：B9 独立验收（未参与实现，对抗性审查）
- 日期：2026-08-13
- Verdict：**PASS**

## 1. 基线

- branch=`codex/feasibility-foundation` ✓
- HEAD=`f3f09f1be28f417454244cae068663e28cd6395e` ✓
- staged 空 ✓；`git diff --check` 通过（仅 CRLF 提示）✓
- 保护目录 `.omo/`、`.serena/`、`docs/audits/` 保持 untracked ✓

## 2. 精确 diff 范围

Python 9 M + 5 A：`application/candidate_validation.py`、`application/replan_service.py`、`infrastructure/amap/planning_provider.py`、`infrastructure/demo/planning_provider.py`、`planning/daily_schedule.py`、`tests/feasibility/test_b5_characterization.py`、`tests/test_daily_skeleton_provider.py`、`tests/test_planning_worker.py`、`tests/test_repair_provider_boundary.py`（M）；`planning/validation_projection.py`、`tests/test_validation_projection.py`、`tests/test_opening_placement.py`、`tests/test_meal_window_placement.py`、`tests/test_entry_matrix.py`（A）。

文档：`docs/execution/B9/plan.md`、`docs/execution/B9/execution-report.md`、`docs/execution/B9/acceptance-report.md`（A）；`docs/architecture/规划工作流.md`、`docs/architecture/行程真实性与旅行骨架.md`、`docs/product/项目路线图.md`、`docs/product/系统完善长期执行与验收总控计划.md`（M）。

无 contracts/Java/Web/Flyway/Rabbit 改动，无陌生范围改动。

## 3. 对抗性验收结论（逐项代码级证据）

1. **假 VERIFIED**：PASS。Demo 投影 `facts=()` → opening bindings 空 → OPENING_HOURS 规则 UNKNOWN；Demo 多活动无 transit → ROUTE 规则非 PASS；整体 report 保持 UNVERIFIED（`test_demo_chain_validates_unknown_and_unverified`、`test_entry_matrix.py` 结构化断言）。
2. **Demo 伪造证据/住宿**：PASS。`project_validation_state` 住宿仅从 ACCOMMODATION + provider_poi_id + coordinates 确认，否则 `UnresolvedAccommodation`；Demo 无 facts → 无 opening evidence；`test_demo_provider_result_projects_unresolved_skeleton` 断言 UNRESOLVED。
3. **stale/conflicting 升级**：PASS。`opening_availability_from_resolved` 仅接受 `state in {VERIFIED_WINDOW, VERIFIED_CLOSED} and hard_constraint_eligible`，其余映射 UNKNOWN（`test_opening_placement.py` 覆盖 UNKNOWN/STALE/CONFLICTING/ineligible）。AMap provider evidence `hard_constraint_eligible=False` 经 `validated_fact_from_planning_fact` 原样保留，永不升级。
4. **opening placement 与 validator 同源**：PASS。放置层 `OpeningAvailability` 与 OPENING_HOURS 规则都从 `resolve_opening_hours` 的 VERIFIED 结论派生；放置层只约束、不自行判定 PASS（validator 单独判定）；`_resolver_clock` 用 facts 最新 checked_at，两层一致。
5. **meal 真实参与**：PASS。`build_meal_demands`/`_meal_demand` 显式窗口优先（`test_meal_window_placement.py`）；`plan_day` 冲突检测 `MEAL_WINDOW_CONFLICT` 不静默丢餐；Demo `_meal_placeholders` 保留用餐占位（`test_planning_worker` 断言活动含 DEMO 占位）。
6. **repair locator 失效**：PASS。`LocalReplanningProvider.repair` 调 `self._project(request.command, itinerary)` 重建，不复用 `request.candidate.validation_inputs`（`test_repair_provider_boundary` 断言 `is not candidate.validation_inputs`）。
7. **replan 复用过期 inputs**：PASS。`replan` 同样重建投影（`test_validation_projection.py` 断言 replan 结果带投影）。
8. **all entry 一致**：PASS。candidate_validation/replan_service/demo 均走 `project_validation_state` 单点；AMap 保留 B5 专用投影边界（fetched_at、真实 POI evidence），其 opening 约束经同一 `opening_availability_from_resolved` 语义。
9. **scope leakage**：PASS。仅改 Python（agent-service）+ 文档；`opening_resolver.py` 的 tier/effective_date/Temporary Closure 语义未改（diff 范围确认无该文件）。
10. **contains 冒充结构断言**：PASS。新增测试用 `outcome is RuleOutcome.X`、`isinstance(accommodation, UnresolvedAccommodation)`、`skeleton.overnights == ()`、`MealWindowConstraint` 值断言等结构断言。

## 4. 门禁独立复跑

| 门禁 | 结果 |
| --- | --- |
| Python 全量（独立 basetemp） | **1360 passed, 37 skipped** |
| Ruff | **All checks passed** |
| Java verify（Java 21 + 显式 Maven） | **424 tests, 0 failures, 0 errors** |
| Web unit | **311 passed**（33 files） |
| Web coverage | **96.04 / 82.20 / 95.52 / 96.04** |
| Web typecheck / build | 通过 / 通过 |
| Playwright（CI=1） | **13 passed** |
| Markdown links | **97 files valid** |
| git diff --check | 通过（仅 CRLF 提示） |
| staged | 空 |

## 5. 发现清单

无 Critical/Important 问题。

非阻断观察：
- `_with_opening_availability` / `_meal_window_constraints` 内局部 import（每次调用重复 import，正确性无影响，性能可忽略）。
- BREAKFAST meal window 在 planning 域外（LUNCH/DINNER only），AMap 转换时跳过——与 Worker contract 现状一致，契约无真实改变。
- 路线 forward-fit 推离窗口的最终抓取依赖既有 OPENING_HOURS 规则（未新增规则），符合 B9.2 第 9 条语义。

## 6. 是否允许 Git 收口

**允许。** B9 实现与全门禁成立，无高置信度功能缺陷。

## 7. 声明

- 未修改任何业务代码/测试/契约（除本报告）
- 未 stage/commit/push；未 reset/stash/checkout/restore/clean/rebase/amend
- 保护目录未处理

---

## B9_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT
