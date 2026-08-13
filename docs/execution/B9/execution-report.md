# B9 规划输入与主动放置完善执行报告

状态：`READY_FOR_REVIEW`

## RED→GREEN 证据

### B9.1 统一验证投影边界

- RED：`tests/test_validation_projection.py` 7 用例（单日 0 overnight、多日 UNRESOLVED、confirmed 需 POI+坐标、无坐标住宿不 confirm、replan 重建投影、Demo 投影 UNRESOLVED+meal UNAVAILABLE、repair locator 重建）——实现前 Demo/replan/repair 无投影或复用旧 inputs，全部真实失败
- GREEN：新增 `src/trip_agent/planning/validation_projection.py`（共享投影：`project_validation_state` + `validated_fact_from_planning_fact`）；`candidate_validation.py` 改为复用共享投影（删除约 180 行重复逻辑）；`DemoPlanningProvider.plan` 接入投影（住宿 UNRESOLVED、无 opening evidence、meal UNAVAILABLE）；`LocalReplanningProvider.replan/repair` 重建投影（repair 不再复用旧 candidate inputs，locator 失效问题关闭）
- 旧测试更新（行为变化非断言删除）：`test_demo_provider_result_trip_skeleton_stays_none` → 断言 UNRESOLVED skeleton；`test_demo_chain_validates_unknown_and_unverified` 传投影；`test_demo_planning_result_has_no_validation_inputs` → 断言投影存在；`test_repair_provider_refreshes_only_requested_days_and_preserves_inputs` → 断言重建非复用

### B9.2 Opening-aware 主动放置

- RED：`tests/test_opening_placement.py` 7 用例（resolver 映射 only-eligible-verified、最早窗口+last-entry、多窗口确定性、closed 排除、must-visit closed 标记、UNKNOWN 不约束、跨午夜窗口）——实现前放置层无 opening 感知，全部真实失败
- GREEN：`daily_schedule.py` 新增 `OpeningAvailability`/`opening_availability_from_resolved`（仅 VERIFIED+eligible 约束）；`CandidateActivity.opening` 字段；`_fill_slots` 感知窗口（closed 排除、最早合法窗口放置、last-entry 上限、确定性 tie-break）；`_build_warnings` 区分 `MUST_VISIT_CLOSED`；AMap provider `_with_opening_availability`（resolver 解析 → 候选约束，provider evidence 不升级）接入 day_candidates 构建

### B9.3 Visit Duration Profile

- 既有实现已满足（profile recommended 放置、min/max 由硬规则判定、source/confidence/version 完整、system-default 不声称 provider）；B9.1 共享投影统一跨入口 duration binding 语义；补 `test_entry_matrix.py` 跨入口 characterization

### B9.4 显式 Meal Window

- RED：`tests/test_meal_window_placement.py` 4 用例（显式窗口优先默认、冲突不静默丢餐、无窗口默认锚点、跨午夜窗口）——实现前 `build_meal_demands` 固定 12:00/18:00，全部真实失败
- GREEN：`daily_schedule.py` 新增 `MealWindowConstraint`（独立于 Worker contract）；`build_meal_demands/_meal_demand` 显式窗口优先（最早可用窗口确定性放置）；`plan_day` 冲突检测（`MEAL_WINDOW_CONFLICT` warning 不静默丢餐）；Demo `_meal_placeholders`（LUNCH/DINNER 占位保留用餐时间）；AMap provider `_meal_window_constraints` 转换（BREAKFAST 过滤、跨午夜 +1440）

### B9.5 跨入口一致性与安全回归

- `tests/test_entry_matrix.py` 6 用例（表驱动：住宿 confirmed/unresolved/单日 × opening 无证据 × meal 无窗口/Demo UNAVAILABLE）——证明未确认住宿不产生 continuity PASS、opening 无证据不 PASS、Demo 投影不伪造证据、无显式窗口 NOT_APPLICABLE

## 门禁

- Python 全量：**1360 passed, 37 skipped**（B8 基线 1336 + 新增 24）
- Ruff：**All checks passed**；新增文件 ruff format 完成
- Java `mvn verify`（Java 21）：**424 tests, 0 failures, 0 errors**（无漂移）
- Web：**311 passed**（33 files）、coverage **96.04/82.20/95.52/96.04**、typecheck/build 通过、E2E **13 passed**
- Markdown links：**97 files valid**；`git diff --check` 通过；staged 空

## 修改文件

- M `application/candidate_validation.py`（复用共享投影）
- M `application/replan_service.py`（replan/repair 重建投影）
- M `infrastructure/amap/planning_provider.py`（opening availability + meal 窗口接入）
- M `infrastructure/demo/planning_provider.py`（投影接入 + meal placeholder）
- M `planning/daily_schedule.py`（OpeningAvailability/MealWindowConstraint/放置约束）
- A `planning/validation_projection.py`（共享投影）
- M `tests/feasibility/test_b5_characterization.py`、`tests/test_daily_skeleton_provider.py`、`tests/test_planning_worker.py`、`tests/test_repair_provider_boundary.py`（旧断言更新为 B9 语义）
- A `tests/test_validation_projection.py`、`tests/test_opening_placement.py`、`tests/test_meal_window_placement.py`、`tests/test_entry_matrix.py`

## 残留边界

- BREAKFAST meal window 在 planning 域外（LUNCH/DINNER only），AMap 转换时跳过——Worker contract 未改（契约无真实改变）
- 路线 forward-fit 推离营业窗口的最终 Hard Validation 抓取依赖既有 OPENING_HOURS 规则（B9.2 第 9 条），未新增规则
- 月末/闰日跨午夜由 opening_placement 测试的跨午夜窗口用例与既有 opening rule 测试覆盖
- Golden matrix、结构化日志属 B10
