# B17 独立验收报告：事实影响契约修复（P0）+ 有界修复松弛（P1）

- 文档状态：**验收完成**（独立验收 Agent 撰写，只读验证，未修改任何生产代码）
- 验收结论：**PASS**
- 验收基线：本目录 `plan.md`（PLANNED）、`execution-report.md`（B17_IMPLEMENTED）
- 验收 HEAD：`d10e70cf354d096300c4a348d6aef585b8d82dc8`（验收全程未变；staged 恒空）
- 验收方式：代码审读 + 全量/定向门禁独立复跑 + 临时只读场景脚本 + compose 全链路冒烟复跑（全部在仓库外临时目录执行，未触碰工作区）

## 1. Verdict

**PASS**

- 问题 2（P0）：serializer 泛化 omit 四字段独立验证成立；completion/review 双链路受益；Java parser 校验语义未放宽；DLQ 无新增。
- 问题 1（P1）：有界 start 松弛（540→510→480→450→420，30 分钟步长，最多 4 步，floor 07:00）独立验证成立；真实不可行仍 NO_FEASIBLE_ITINERARY；REST 快照补 conflicts/relaxationSuggestions 生效。
- 未发现"用户显式 09:00 约束被误识别为 system-default 540 后松弛"的路径（见 §6）。
- 无阻塞缺陷；无被放宽的校验；无 schema/迁移/compose/.env 改动。

## 2. Scope Reviewed（实际 diff 范围）

| 层 | 文件 | 验收复核 |
| --- | --- | --- |
| Python | `src/trip_agent/worker/contracts.py` | serializer `_omit_none_optional_fields`（L913-937）：None 时 pop `date`/`targetPoiId`/`targetName`/`sourceUrl`（camelCase + snake_case 双 pop）；completion（L1036）与 review（L1087/L1187）payload 共用 `tuple[PlanningFactImpact, ...]` → 模型级 serializer 双链路同受益；diff +68 行 |
| Python | `src/trip_agent/planning/daily_schedule.py` | `plan_day` 新增 `window_override: tuple[int,int]|None=None`（L536），默认 None 走既有 `day_window_minutes`（L293-325）；固定项经 `build_fixed_items` 独立注入；diff +16 行 |
| Python | `src/trip_agent/infrastructure/amap/planning_provider.py` | 常量 `_WINDOW_RELAX_STEP_MINUTES=30`/`_WINDOW_RELAX_FLOOR_MINUTE=420`（L105-106）；repair 循环（L461-529）；`_can_relax_window_start`（L934）；`_activity_from_slot` 空地址回退（L1245）；diff +245 行（含 B16 内容，见 §10） |
| Python | `tests/test_messaging_contract_schemas.py` | L115 四字段 None→omit + 非 None 保留；L165 stale 场景 Draft202012Validator |
| Python | `tests/test_planning_outcome_events.py` | v10 completion 事件 None-optional impact → wire 无 null |
| Python | `tests/test_repair_window_relaxation.py` | **新增**：4 个 B17 场景（有界松弛成功 / floor 仍不可行 fail-closed / 午餐 hard window 不动 / 空地址 POI 回归）+ `_poi`/`_MapProvider` helpers |
| Java | `planning/PlanningTaskOutcomeReadModel.java` | `readFailed` 映射 conflicts/relaxationSuggestions（array/object 校验 fail-closed）；diff +78 行 |
| Java | `planning/PlanningTaskService.java` | `toResponse` L569-586 透传 `metadata.conflicts()/relaxationSuggestions()`（L583）与 outcome 版本（L615）；`PlanningTaskResponse` L664-665、`ConflictResponse` L695、`RelaxationSuggestionResponse` L702；diff +26 行 |
| Java | `planning/PlanningTaskOutcomeReadModelTest.java` | **新增（未跟踪）**，B16 阶段已存在未跟踪版本，本批次扩展 FAILED 分支（断言 conflicts size/code/message/affected + relaxations size/code/message） |
| Java | `planning/PlanningTaskReadModelIntegrationTest.java` 等 | FAILED REST response 字段断言 |
| Web | `src/lib/api.ts` | `PlanningTask` + `conflicts`/`relaxationSuggestions`/`errorMessage` 可选字段 + `PlanningConflict`/`PlanningRelaxationSuggestion` 接口；diff +13 行 |
| Web | `src/lib/feasibility.ts` | `readPlanningTaskOutcome`（L756）与 `readPlanningEventOutcome`（L812）共用同一 errorParts 拼接模式；diff +39 行（含 B16 内容） |
| Web | `tests/feasibility.test.ts` | readPlanningTaskOutcome 含"建议："断言 |

## 3. Verified Findings（生产链路追踪）

**P0 链路（问题 2）**：`trusted_context.py` stale 事实 `target_name=None` → `contracts.py` serializer pop 四可选字段 → wire 无 null（`model_dump_json(by_alias=True)`）→ Java `PlanningCompletedEventParser.validateFactImpactTypes`（L164+）校验（present-but-null 仍拒绝：`impact.has("date") && !impact.path("date").isTextual()`）→ 终态事件 → 任务正常终态。`PlanningReviewRequiredEventParser`（L193）同调 `validateFactImpactTypes`，review 链路同步受保护。**Java 校验语义零改动**（diff 仅测试）。

**P1 链路（问题 1）**：住宿锚点真实坐标参与 AMAP 路由 → 末日 DEPARTURE 锚定超时 → `_fixed_slot_timing_error`（DEPARTURE → `INSUFFICIENT_DAY_CAPACITY` + `EXTEND_AVAILABLE_TIME`；非 DEPARTURE 固定槽 → `FIXED_SCHEDULE_OVERLAP` + `CHANGE_FIXED_SCHEDULE`，L1174-1194）→ `_capacity_repair_candidate` 删可选 POI 优先 → 删无可删 → `_can_relax_window_start` 判可松弛 → `window_override` 传入 `plan_day` 重算 → 成功或 floor 仍失败 → `PlanningInfeasibleError` → PLANNING_FAILED v2（conflicts/relaxation_suggestions 完整映射）→ Java 持久化 payload → FAILED + errorCode/displayMessage → SSE payload tree + REST 快照（`readFailed` 映射 + `toResponse` 透传）。

**修复后链路交叉验证**（compose 冒烟复跑，见 §9）：基础链 SUCCEEDED 正常终态；住宿链 FAILED=`NO_FEASIBLE_ITINERARY` 且 REST 快照含 conflicts/relaxations；DLQ=0。

## 4. P0 Contract Acceptance

- `_omit_none_optional_fields` 独立代码验证：对 4 字段 None→pop、非 None 保留；双链路（completion/review）同享（共用 payload 构造路径）。
- 契约测试断言质量：L115 断言 wire 四字段全部缺席且无 null；L165 用 Draft202012Validator 校验 stale 场景全事件。
- Java parser 未放宽：present-but-null（`has && !isTextual()`）仍拒绝，与 schema optional-not-nullable 语义一致。
- 生产实证：compose 冒烟前后 `planning.dead-letter.queue` 恒 0；travel-server 无 `PlanningEventContractException`/`RejectAndDontRequeue`。
- **结论：P0 验收通过。**

## 5. Capacity Repair Acceptance

- 有界性：步长 30 分钟、最多 4 步（start-30 至 floor 420 检查）、floor 仍不可行保持 NO_FEASIBLE_ITINERARY——由 `test_departure_day_fails_closed_when_floor_window_is_still_insufficient`（8h 路线，floor 07:00 不够）锁定；独立代码验证 `_can_relax_window_start` 的 floor 判断 `start - 30 >= 420`。
- 零回归：`window_override` 默认 None → 既有 `day_window_minutes` 路径逐字未动（diff +16 行仅参数化）；全量 1535 pytest 通过佐证。
- end 侧松弛未实现：无错误触发面（仅 DEPARTURE 锚定错误 raise；中间日 ACCOMMODATION 返回槽 `time_fixed=False` 移位而非报错）——与 execution-report §8.2 一致，YAGNI 成立。
- **结论：P1 有界修复验收通过。**

## 6. Constraint Safety（用户显式约束误松弛路径专项）

验收重点 5 专项核查（用户显式 09:00 不得被误判为 system-default 540 后松弛）：

- **代码层三重守卫**（`_can_relax_window_start`，planning_provider.py L934）：① 仅 `INSUFFICIENT_DAY_CAPACITY` 冲突才考虑松弛（FIXED_SCHEDULE_OVERLAP 等一律不松弛）；② `steps==0` 时要求 `window_start_minute == DEFAULT_DAY_START_MINUTE(540)` 且当日无 `ARRIVAL` item（消灭首日 arrival==09:00 歧义，fail-closed）；③ floor 检查。
- **数据模型无"用户显式最早出发时间"字段**：arrival=09:00 锚点 → 当日含 ARRIVAL item → fail-closed；早 departure → `start = min(start, end - DEPARTURE_BUFFER_MINUTES)` → start < 540 → 不满足"==540" → 不松弛；固定预约 09:00 → `time_fixed=True` 时间戳不动，预约前冲突走 `FIXED_SCHEDULE_OVERLAP`（不松弛）。
- **临时只读场景脚本独立验证**（`C:\Windows\Temp\opencode\b17_acc_fixed_schedule_check.py`，复用测试 helpers，未触碰仓库）：
  - 场景 A：固定预约 11:00-12:00 + 5h 机场路线 + 18:00 返程 → 预约 11:00-12:00 原位（`time_fixed=True`）、陈家祠 09:00-10:30 在预约前、无重叠、DEPARTURE 17:00-18:00 buffer 完整。
  - 场景 B：固定预约 09:00-10:00（恰在系统默认起点）+ 5h 路线 → 预约 09:00-10:00 分毫未移（`time_fixed=True`）、陈家祠被安排在预约后 10:12-11:42、DEPARTURE buffer 完整——**预约绝未被误判为 system-default 并松弛**。
  - 中间实验反证：预约 12:00-13:00/10:00-11:00 与 5h 路线真实不可行 → fail-closed（FIXED_SCHEDULE_OVERLAP 或 INSUFFICIENT_DAY_CAPACITY），预约永不移动、永不跳过。
- 既有测试锁定：`test_relaxation_never_moves_user_meal_hard_window`（USER 午餐 11:00-12:00 锁定，窗口前沿前移餐食不动）。
- **结论：无用户显式约束误松弛路径；约束安全验收通过。**

## 7. Failure Snapshot Acceptance

- Java：`readFailed` 从 payload 解析 conflicts/relaxationSuggestions（fail-closed 校验，数组/对象结构不符即拒绝）；`toResponse` 透传；`PlanningTaskResponse` 记录含两字段；无事件/无冲突回退 null/空列表。
- Web：`readPlanningTaskOutcome`（REST 快照）与 `readPlanningEventOutcome`（SSE）errorParts 拼接逻辑逐行比对一致（primaryError → conflicts 去重 → "建议：{suggestion.message}" → join）；无 conflicts 回落 safeMessage/默认文案。
- 生产实证：住宿链 compose 冒烟 FAILED 后 REST 快照 `errorCode=NO_FEASIBLE_ITINERARY`、`conflicts=1`（INSUFFICIENT_DAY_CAPACITY）、`relaxationSuggestions=1`（EXTEND_AVAILABLE_TIME）。
- **结论：REST 快照补建议验收通过（SSE/REST 语义一致）。**

## 8. AMAP Empty Address Regression

- 修复面：`_activity_from_slot`（L1245）`address=poi.address or poi.name`——**仅 address 字段**；`provider_poi_id`/`coordinates`/`type`/routing identity 均未触碰（代码比对确认）。
- 测试锁定：`test_empty_address_poi_does_not_break_activity_construction`（empty_address_ids 场景）。
- **结论：空地址回退安全，无 routing 语义变更。**

## 9. Test Evidence（独立复跑结果，全部由验收 Agent 重跑）

| 门禁 | 命令 | 独立复跑结果 |
| --- | --- | --- |
| Python 定向 | `uv run python -m pytest tests/test_repair_window_relaxation.py tests/test_messaging_contract_schemas.py tests/test_planning_outcome_events.py -q --basetemp ...` | **64 passed**（EXIT=0） |
| Lint | `uv run ruff check .`（只读，未 `--fix`） | **All checks passed**（EXIT=0） |
| Python 全量 | `uv run python -m pytest -q --basetemp C:\Windows\Temp\opencode\pytest-basetemp` | **1535 passed, 37 skipped, 0 failed**（EXIT=0） |
| Java 定向 | `mvn -pl apps/travel-server -Dtest=PlanningTaskOutcomeReadModelTest,PlanningTaskReadModelIntegrationTest,PlanningCompletedEventParserTest test` | **94 tests, 0 failures, BUILD SUCCESS** |
| Java 全量 | `mvn --batch-mode -pl apps/travel-server test` | **533 tests, 0 failures, BUILD SUCCESS** |
| Web unit | `pnpm test` | **42 files / 443 tests passed** |
| Web type | `pnpm typecheck`（vue-tsc -b） | **EXIT=0** |
| compose 冒烟-基础 | `smoke_test_38080.py`（BASE=38080） | **PASS**：注册→建行程→规划→SUCCEEDED（2d 6a 2t，score 85） |
| compose 冒烟-住宿 | `b17_accommodation_chain.py`（REAL_ONLY：住宿锚"广州南站"B00140VAP3 + 必去陈家祠 + 白云机场 B00140NZIQ） | **PASS**：任务 FAILED=`NO_FEASIBLE_ITINERARY`，REST 快照 conflicts=[INSUFFICIENT_DAY_CAPACITY] + relaxationSuggestions=[EXTEND_AVAILABLE_TIME] |
| DLQ | `rabbitmqctl list_queues`（8 队列） | **planning.dead-letter.queue = 0**（冒烟前后无新增） |
| 栈健康 | `docker ps` | 8 个 trip-pilot-prod 容器全部 healthy |

错误 fixture / 事务 / 历史兼容检查：Java `PlanningCompletedEventFixture` 等既有测试按需更新构造并全绿；`PlanningFailedEventParser` 校验语义未改动；wire schema 未改动（可选字段缺席本就合法）；无 Flyway 迁移改动。

## 10. Workspace & Scope Audit

- HEAD 未变、staged 恒空；未 stage/commit/push；`.env` 未读未改。
- 绕过检查：无对 `PlanningCompletedEventParser`/`PlanningReviewRequiredEventParser` 校验语义的改动；无 schema.json 改动；无 `amqp.py` exclude_none 策略改动；无住宿 POI `poi=None` 假修复；无路线精度降级；无 Flyway/compose/RabbitMQ 配置改动。
- 历史兼容：REST 响应新增可选字段，前端类型同步（缺失时回落默认文案），既有行为不破坏。
- CRLF 警告存在但无全文件换行重写（diff 均小改动：contracts.py +68、daily_schedule.py +16、api.ts +13、feasibility.ts +39、PlanningTaskService.java +26、PlanningTaskOutcomeReadModel.java +78、planning_provider.py +245）。
- **归属限制（如实声明）**：工作区含 B15/B16/B17 混存未提交改动（55+ 文件 M + 未跟踪），**无法从 unstaged 状态完全证明每个文件每行的批次归属**。planning_provider.py 的 +245 与 feasibility.ts 的 +39 均含 B16 内容（V10 事件类/has_blocker 等，B16 acceptance-report 佐证）。本报告结论基于：B17 目标文件 diff 小且聚焦 + 8 项 RED 测试语义 + 全量门禁 + compose 冒烟交叉验证，未发现 B17 改动越出 execution-report §4 清单。Git 收口时的精确归属拆分属独立收口任务，本验收不替其断言。

## 11. Defects

无阻塞缺陷（无 P0/P1 级问题）。

观察项（不阻塞，记录备查）：
1. fixed schedule 槽在产出活动中 `kind` 被映射为 `ATTRACTION`（`time_fixed=True` 为真实约束标志，行为正确；仅影响前端展示分类语义，见验收场景 B 观测）。
2. `uv run pytest` 入口在本机 venv 失效（EXIT=1 无输出），一律 `uv run python -m pytest`；Windows Temp 权限需 `--basetemp` 指向可写目录——环境问题，非代码缺陷（B16 同因）。

## 12. Follow-ups

- 单日行程（day_count==1）住宿锚点不参与 routing（产品级缺陷待验证，plan.md §1 发现项，非 B17 范围）。
- ACCOMMODATION slot duration=15min 语义（窗口外 15min 固定）待产品确认。
- web e2e（Playwright）未运行：本机 Windows 会话 vite dev server 端口绑定 EACCES 环境限制（B16 同因）；unit/typecheck/build + compose 冒烟已覆盖全链路行为。
- 观察项 1（fixed schedule kind 分类）如需修正，建议独立批次评估。

## 13. Acceptance Criteria Matrix

| plan.md §8 标准 | 结果 |
| --- | --- |
| 问题 2：含 None optional 字段的事实影响不再产出 null；completion/review 双链路 wire 过 schema | ✅ 测试 + 代码双验证（§4） |
| 死信队列不再新增；任务正常终态（SUCCEEDED/FAILED） | ✅ DLQ=0；基础链 SUCCEEDED、住宿链 FAILED（§4/§9） |
| 问题 1：有松弛空间时成功规划（真实住宿参与路由、精度不降） | ✅ 定向测试 + 代码验证（§5） |
| 真实不可行仍 NO_FEASIBLE_ITINERARY | ✅ 负向测试 + 住宿冒烟（§5/§9） |
| 失败时 SSE 与 REST 快照均展示 conflicts + relaxation_suggestions（含"建议："） | ✅ 代码比对 + 住宿冒烟 REST 快照（§7/§9） |
| 全部 RED 测试先红后绿；分层/全量门禁通过；coverage 不降 | ✅ execution-report §3 RED 记录 + 本报告独立复跑全绿（§9） |
| 实现保持 unstaged，不 stage/commit/push | ✅ HEAD 未变、staged 恒空（§10） |

## 14. Final Recommendation

**验收结论：PASS。**

允许提交的 B17 范围文件清单（与 execution-report §4 一致）：

- `apps/agent-service/src/trip_agent/worker/contracts.py`
- `apps/agent-service/src/trip_agent/planning/daily_schedule.py`
- `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py`
- `apps/agent-service/tests/test_messaging_contract_schemas.py`
- `apps/agent-service/tests/test_planning_outcome_events.py`
- `apps/agent-service/tests/test_repair_window_relaxation.py`（新增）
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskOutcomeReadModel.java`
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskService.java`
- `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningTaskOutcomeReadModelTest.java`（新增未跟踪）
- `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningTaskReadModelIntegrationTest.java`
- `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/support/PlanningCompletedEventFixture.java` 等既有测试的同步构造改动
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/feasibility.ts`
- `apps/web/src/tests/feasibility.test.ts`（或对应测试路径）
- `docs/execution/B17/plan.md`、`docs/execution/B17/execution-report.md`、`docs/execution/B17/acceptance-report.md`（本文件）

收口提醒：工作区与 B15/B16 改动混存，实际 `git add` 时应按上表逐文件核对，且本批次验收不替 B15/B16 批次的收口归属做断言（建议由独立 Git 收口任务统一处理三批次合并提交）。