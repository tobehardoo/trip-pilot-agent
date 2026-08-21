# B17 执行报告：事实影响契约修复（P0）+ 有界修复松弛（P1）

- 状态：**B17_IMPLEMENTED**（unstaged，未 commit，未 push）
- 阶段：B17（Backend/Python + Java + Contract + Frontend 全链路）
- BASELINE_HEAD：`d10e70cf354d096300c4a348d6aef585b8d82dc8`（`feat(platform): complete local-first trip planning release`）
- 计划：见本目录 [plan.md](plan.md)（待独立验收 Agent 补写 acceptance-report.md）
- 交付物：本报告 + 代码改动 + 测试结果

## 1. 开始前 Git 状态

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `d10e70cf354d096300c4a348d6aef585b8d82dc8`（未变） |
| staged | 空（`git diff --cached --name-only` 0 行，全程保持） |
| `.env` | 未读、未修改 |
| 在途改动 | 工作区含 B15/B16 未提交改动（55+ 文件 M + 未跟踪 docs/execution/B15、B16、contracts/fixtures/planning-completed-event-v10/、V37 迁移等），本批次叠加其上，未 reset/stash/checkout/restore/clean |

约束遵守：未 stage/commit/push；未修改 `.env`；未改动 Flyway 迁移/既有 schema/Java parser 校验语义；未降低 coverage 门槛；未操作用户 `trip-pilot-prod` 数据（compose 冒烟仅重建镜像、新建测试账号与行程）。

## 2. 根因（审计结论）

### 问题 2（P0）——serializer 只 omit targetPoiId

`contracts.py` `_omit_none_target_poi`（`@model_serializer(mode="wrap")`）只 pop `targetPoiId`，`targetName`/`sourceUrl`/`date` 的 None 会产出 `null` → 违约 optional-not-nullable schema → Java `validateFactImpactTypes` 拒收（符合 schema，非 Java bug）→ DLQ → 任务永久 RUNNING。

### 问题 1（P1）——真实不可行 + repair 缺松弛 + REST 快照丢建议

住宿锚点参与真实路由后，"酒店→景点→机场"真实时长超固定返程 → `INSUFFICIENT_DAY_CAPACITY` + `EXTEND_AVAILABLE_TIME` 建议已生成，但 `_capacity_repair_candidate` 只删可选 POI，不执行"提前出发"松弛 → 删无可删仍失败；失败事件 conflicts/relaxations 已持久化且 SSE 已展示，但 **REST 快照路径（刷新后）** 丢失 conflicts/relaxationSuggestions（Java ReadModel 未映射、api.ts 类型缺失、readPlanningTaskOutcome 只读 errorMessage）。

### B 审计（用户门禁）：数据模型可区分 user-specified vs system-default

**结论：可靠可区分。** repair 调用点持有 `day_window_minutes` 全部输入（trip_date/start_date/end_date/arrival_boundary/departure_boundary/pace）与计算出的 DayPlan（window_start_minute/window_end_minute/items），可精确推导边界来源：

- start 可松弛 ⟺ `window_start_minute == DEFAULT_DAY_START_MINUTE(540)` **且**当日无 `ARRIVAL` item（消灭首日 arrival==09:00 的歧义）
- end 可松弛 ⟺ `window_end_minute == default_end(pace)`（1080/1200）**且**当日无 `DEPARTURE` item——但当前**没有任何错误触发面**（只有 DEPARTURE 锚定错误会 raise `INSUFFICIENT_DAY_CAPACITY`；中间日 ACCOMMODATION 返回槽 `time_fixed=False` 会移位而非报错），故 **end 松弛不实现**（YAGNI，plan.md §4.2 允许的最小增量）
- 用户显式约束（fixed_schedules、USER meal windows、arrival/departure 锚点）永不移动：`compute_free_windows` 在固定项周围分割窗口，松弛只扩展窗口前沿，餐食仍由 `_place_inside_windows` 在显式边界内放置

## 3. 每轮 RED 的真实失败

| # | 测试 | 失败内容（修复前） |
| --- | --- | --- |
| 1 | `test_messaging_contract_schemas.py` 扩展：target_name/source_url/date=None 的 impact | wire JSON 仍含 `"targetName": null` 等（只 omit targetPoiId） |
| 2 | `test_planning_outcome_events.py` 扩展：stale 事实 → v10 completion 事件 | 事件 wire 含 null 可选字段，schema 校验失败 |
| 3 | `test_repair_window_relaxation.py::test_departure_day_relaxes_system_default_start_after_capacity_repair_exhausted` | 现 NO_FEASIBLE_ITINERARY（无松弛），期望成功 itinerary |
| 4 | `test_repair_window_relaxation.py::test_relaxation_never_moves_user_meal_hard_window` | 午餐被移位/失败（无松弛），期望午餐锁定 11:00-12:00 |
| 5 | `test_repair_window_relaxation.py::test_empty_address_poi_does_not_break_activity_construction` | **冒烟发现的真实缺陷**：AMAP 返回空 address 的 POI（如"广州南站"B00140VAP3）→ `ItineraryActivity.address`（AddressText min_length=1）校验失败 → `ValidationError` → INTERNAL_PLANNING_FAILED（B17 松弛路径未走到） |
| 6 | Java `PlanningTaskOutcomeReadModelTest`（扩展）：readFailed 输出 conflicts/relaxationSuggestions | readFailed 只写 errorCode/displayMessage，无 conflicts |
| 7 | Java `PlanningTaskService` 测试：FAILED REST response 含 conflicts/relaxationSuggestions | response 无该字段 |
| 8 | Web `feasibility.test.ts`：readPlanningTaskOutcome 对含 conflicts/relaxations 的 task 产出"建议：" | 只读 task.errorMessage，无建议拼接 |

> RED 反证（问题 1 有界性）：`test_departure_day_fails_closed_when_floor_window_is_still_insufficient`（8h 路线，floor 07:00 仍不够）在实现松弛**之前**即通过（无松弛 → 失败），实现后仍通过（有界松弛 → 失败）——证明松弛有界、真实不可行仍失败。实现中途临时禁用松弛分支复跑 #3/#5 确认转 RED，随后恢复 GREEN。

## 4. GREEN 实现与文件清单

### Python（`apps/agent-service`）

| 文件 | 修改 |
| --- | --- |
| `src/trip_agent/worker/contracts.py` | `_omit_none_target_poi` → `_omit_none_optional_fields`：pop `date`/`targetPoiId`/`targetName`/`sourceUrl`（None 时）；completion 与 review 双链路同受益；E501 换行 |
| `src/trip_agent/planning/daily_schedule.py` | `plan_day` 增加 `window_override: tuple[int, int] | None = None`（默认 None → 既有调用不变）；`day_window_minutes` 接受显式窗口覆盖（**唯一越出 plan.md §3 列表的文件，见 §8 说明**） |
| `src/trip_agent/infrastructure/amap/planning_provider.py` | 新增 `DEFAULT_DAY_START_MINUTE` import、`_WINDOW_RELAX_STEP_MINUTES=30`、`_WINDOW_RELAX_FLOOR_MINUTE=420`；`_can_relax_window_start(day_plan, error, *, steps_taken)`；repair 循环：`INSUFFICIENT_DAY_CAPACITY` 且 `_capacity_repair_candidate` 返回 None 时，按 30 分钟步长提前 start（最多 4 步至 07:00），`window_override` 传入 `plan_day`，重算仍失败则继续递减，floor 仍不可行 → 保持 `PlanningInfeasibleError`；`_activity_from_slot` address 空串回退 `poi.name`（冒烟缺陷修复） |
| `tests/test_messaging_contract_schemas.py` | 四可选字段 None → wire 全缺席、无 null；stale 事实事件过 Draft202012Validator |
| `tests/test_planning_outcome_events.py` | v10 completion fixture 含 None-optional impact → wire 无 null |
| `tests/test_repair_window_relaxation.py` | **新增**：3 个 B17 场景 + 1 个空地址回归（见 §3 #3/#4/#5） |

### Java（`apps/travel-server`）

| 文件 | 修改 |
| --- | --- |
| `.../planning/PlanningTaskOutcomeReadModel.java` | `readFailed` 从 payload 解析 `conflicts`/`relaxationSuggestions` 到 Outcome |
| `.../planning/PlanningTaskService.java` | `PlanningTaskResponse` record 增加 `conflicts`/`relaxationSuggestions`/`errorMessage` 字段并透传 |
| `.../planning/PlanningTaskOutcomeReadModelTest.java` | **新增（未跟踪）**：readFailed 含 conflicts/relaxations |
| `.../planning/PlanningTaskReadModelIntegrationTest.java` | FAILED task REST response 含字段断言 |
| `.../support/PlanningCompletedEventFixture.java` 等既有测试 | 按需更新构造（字段同步） |

> 注：`PlanningTaskOutcomeReadModelTest.java` 在 B16 阶段已存在未跟踪版本，本批次扩展其 FAILED 分支用例。

### Frontend（`apps/web`）

| 文件 | 修改 |
| --- | --- |
| `src/lib/api.ts` | `PlanningTask` 增加 `conflicts`/`relaxationSuggestions`/`errorMessage` 可选字段 |
| `src/lib/feasibility.ts` | `readPlanningTaskOutcome` 解析 conflicts/relaxationSuggestions，与 `readPlanningEventOutcome` 同逻辑拼接 errorParts（含"建议："），无 conflicts 回落 safeMessage/默认文案 |
| `tests/feasibility.test.ts` | readPlanningTaskOutcome 含建议断言 |

## 5. 真值表与负向路径

| 场景 | 边界来源 | 松弛动作 | 结果 |
| --- | --- | --- | --- |
| 末日 start=540（默认）、无 ARRIVAL item、DEPARTURE 锚定容量不足 | SYSTEM-DEFAULT | start 540→510→…→420 | 有松弛空间 → SUCCEEDED（测试 1/4） |
| 同上但 07:00 仍放不下 8h 路线 | SYSTEM-DEFAULT | 4 步全部尝试 | NO_FEASIBLE_ITINERARY（测试 2） |
| 首日 start 被 arrival 推后（>540） | USER arrival | **不松弛** | 保持原窗口 |
| 当日有 ARRIVAL item（arrival==09:00 歧义） | 不可判定 | **不松弛**（fail-closed） | 保持原窗口 |
| USER 午餐 11:00-12:00 | USER meal window | 窗口前沿前移，餐食不动 | 午餐锁定（测试 3） |
| 空地址 POI | AMAP 数据 | 不涉及（构造层） | address 回退 name，行程正常（测试 5） |
| end 侧松弛 | — | 无触发面，不实现 | 无代码路径 |

负向路径：`_can_relax_window_start` 对非 `INSUFFICIENT_DAY_CAPACITY` 冲突、`_capacity_repair_candidate` 仍有候选、start 非默认值、含 ARRIVAL item、steps ≥ 4、floor 仍不可行——全部返回 False/保持失败，无越界松弛。

## 6. 门禁结果

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 定向 Python | `uv run python -m pytest tests/test_repair_window_relaxation.py tests/test_messaging_contract_schemas.py -q --basetemp ...` | **48 passed** |
| 全量 Python | `uv run python -m pytest -q --basetemp C:\Windows\Temp\opencode\pytest-basetemp` | **1535 passed, 37 skipped, 0 failed** |
| Lint | `uv run ruff check . --fix` | **0 errors**（修复 1 个 I001 import 排序 + 1 个 E501 行长的 B17 引入问题） |
| Java | `mvn --batch-mode -pl apps/travel-server test` | **EXIT=0（BUILD SUCCESS）** |
| Web unit | `pnpm test` | **42 files, 443 tests passed** |
| Web type | `pnpm typecheck`（vue-tsc -b） | **EXIT=0** |
| compose 冒烟-基础 | `scripts/smoke_test.py`（BASE=38080） | **PASS**：注册→建行程→规划→SUCCEEDED（2d 6a 2t，score 85） |
| compose 冒烟-住宿 | 自写 `b17_accommodation_chain.py`（REAL_ONLY，住宿锚"广州南站"+ 必去陈家祠 + 白云机场 10:00 固定返程） | **PASS**：任务 FAILED=`NO_FEASIBLE_ITINERARY`，REST 快照 `conflicts=[INSUFFICIENT_DAY_CAPACITY]` + `relaxationSuggestions=[EXTEND_AVAILABLE_TIME]`（含"建议："文案）——问题 1 双链路验收成立 |
| DLQ | `rabbitmqctl list_queues` | `planning.dead-letter.queue` = **0**（冒烟前后均无新增） |
| 契约拒收 | travel-server 日志 | 无 `PlanningEventContractException`/`RejectAndDontRequeue` |

> 环境注：全量 pytest 需 `--basetemp` 指向可写目录（`C:\Windows\Temp\pytest-of-xx` 权限受限，环境问题非代码问题，B16 同）；`uv run pytest` 入口在本机 venv 失效（EXIT=1 无输出），一律 `uv run python -m pytest`。

## 7. staged/commit/push 状态

- `git diff --cached --name-only`：0 行（全程 unstaged）
- 未 commit、未 push、未 amend/rebase
- 工作区仍含 B15/B16 在途改动，与 B17 改动混存；三份批次文档齐备后由独立 Git 收口任务统一提交

## 8. 残留边界与未决项登记

1. **单日行程（day_count==1）住宿锚点不参与 routing**（plan.md §1 发现项，产品级缺陷待验证）：本批次不修。
2. **end 松弛无触发面**：仅 start 侧松弛实现；末日 departure 是唯一 raise `INSUFFICIENT_DAY_CAPACITY` 的固定槽，中间日 ACCOMMODATION 返回槽 time_fixed=False 会移位而非报错。若未来引入"固定返回住宿"约束，需补 end 松弛（对称逻辑已在 `_can_relax_window_start` 设计内）。
3. **`daily_schedule.py` 越出 plan.md §3 允许列表**：plan.md 仅列 contracts.py 与 planning_provider.py，但 B 审计结论要求"显式窗口覆盖由调度器权威执行"，`window_override` 是 `plan_day` 最小参数化（默认 None 零影响），无此改动无法在不复制调度逻辑的前提下实现有界松弛。属审计结论驱动的必要最小增量，已在 §2 说明。
4. **空地址 POI 缺陷**（冒烟发现，plan.md 未预列）：`_activity_from_slot` 对 `poi.address` 空串回退 `poi.name`；真实 AMAP 数据可能缺 address，此前任何含空地址 POI 的行程都会 INTERNAL_PLANNING_FAILED。修复已在测试 5 锁定。
5. **`uv run pytest` 入口失效 + Windows Temp 权限**：环境问题，命令均以 `uv run python -m pytest --basetemp ...` 执行，非代码缺陷。
6. **B16 遗留文案**（PlanningReviewPanel.vue L70 "因此可能无法保存"）不可达，非本批次范围。
7. **web e2e（Playwright）未运行**：B16 同因（本机 Windows 会话 vite dev server 端口绑定 EACCES 环境限制）；unit/typecheck/build 与 compose 冒烟已覆盖全链路行为。

## 9. 完成标志核对

- [x] 实现代码 + 测试全部落盘且 unstaged
- [x] 8 项 RED 全绿（#1-#8，其中 #5 为冒烟新增）+ 分层/全量门禁通过
- [x] execution-report.md 已由执行 Agent 完成（本文件）
- [ ] 等待独立验收 Agent 写入 `docs/execution/B17/acceptance-report.md` 后收口