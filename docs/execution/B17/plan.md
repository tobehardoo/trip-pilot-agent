# B17 执行计划：事实影响契约修复（P0）+ 住宿行程时间不足修复（P1）

- 文档状态：**PLANNED（本批次规划，未开始实施）**
- 基线 branch：`codex/feasibility-foundation`；HEAD：`d10e70cf354d096300c4a348d6aef585b8d82dc8`（= BASELINE_HEAD，`feat(platform): complete local-first trip planning release` 提交）
- 已知在途改动：工作区含大量未提交改动（B15/B16 相关，55 文件 M + 未跟踪 docs/execution/B15、B16、contracts/fixtures/planning-completed-event-v10/、V37 迁移等）。**本批次必须叠加在当前工作区之上，禁止 reset/stash/checkout/restore/clean 来"恢复预期状态"**。
- 关联：B15/B16 acceptance-report（PASS，未收口提交）、总控计划 §4.1/§4.2
- 禁止：stage/commit/push（留给独立验收后的 Git 收口任务）；修改保护目录/`.env`；降低 coverage 门槛；操作用户 `trip-pilot-prod` 数据
- 不得创建：`docs/execution/B17/acceptance-report.md`（留给独立验收 Agent）

## 0. 批次目标（两问题，独立根因，禁止混为同一修复）

### 问题 2（P0）：completion/review 事件契约违约 → 任务永久 RUNNING（卡 95%）

**现象**：真实 AMAP 规划任务发布 PLANNING_COMPLETED 后被 RabbitMQ DLQ 拒收，Java 端 `PlanningCompletedEventParser.validateFactImpactTypes` 抛 `PlanningEventContractException`，任务无终态事件，前端永久停在 95% RUNNING。死信消息证据：factImpacts[0].targetName 为 JSON `null`。

### 问题 1（P1）：填写住宿锚点后真实行程"时间不足" → NO_FEASIBLE_ITINERARY

**现象**：用户填住宿（真实酒店坐标）后，末日"酒店→景点→机场"真实 AMAP 路线超出固定返程时间，`_capacity_repair_candidate` 删光可选 POI 仍不可行 → 规划失败，前端提示笼统（REST 快照路径只显示默认文案）。

## 1. Verified Findings（已确认 / 推测 / 待验证）

### 问题 2（已确认）

1. `apps/agent-service/src/trip_agent/worker/contracts.py:913-927`：`PlanningFactImpact._omit_none_target_poi`（`@model_serializer(mode="wrap")`）**只 omit `targetPoiId`**，对 `targetName`/`sourceUrl`/`date` 未做 None 处理。
2. `apps/agent-service/src/trip_agent/planning/trusted_context.py:70-80`：stale 事实分支构造 `PlanningFactImpact(..., effect="STALE_FACT_WARNING", target_name=None, ...)` → 序列化时 `target_name=None` 未被 omit，产出 `"targetName": null`。
3. `contracts/messaging/planning-completed-event-v10.schema.json`：factImpacts items 中 `date`/`targetPoiId`/`targetName`/`sourceUrl` 均为 **optional-not-nullable**（required 列表只含 factId/category/effect/reason/sourceName/sourceType/reliabilityLevel/checkedAt/evidence/stale/conflicted/refreshFailed；四个可选字段若出现则必须是 string/format，不能为 null）。
4. `apps/travel-server/.../infrastructure/mq/PlanningCompletedEventParser.java:196`：`validateFactImpactTypes` 对 `impact.has("targetName") && !impact.path("targetName").isTextual()` 抛错——**present-but-null 被拒绝**，与 schema 语义一致（Java 端不是 bug）。
5. `apps/travel-server/.../infrastructure/mq/PlanningReviewRequiredEventParser.java:193`：**review-required 事件同样校验 factImpacts** → 同一 Python serializer 缺陷同时污染 completion 与 review 两条链路。
6. `apps/agent-service/src/trip_agent/worker/amqp.py:658`：completion/review 事件发布用 `model_dump_json(by_alias=True, exclude_none=False)`（progress 198 / failed 802 / failed 870 均用 `exclude_none=True`）→ 但 Python 侧已由 `_omit_none_target_poi` 在序列化时 pop 掉 targetPoiId，`exclude_none` 仅影响未被 pop 的字段。**最小修复点在 contracts.py serializer，而非 amqp.py**（amqp.py 保持 exclude_none=False 亦可，因 serializer 已负责 pop）。
7. 死信消息实证（已确认）：DLQ 消息中 `factImpacts[0].targetName` 为 `null`，Java 拒收，任务 `2e1139d4-...` 永 RUNNING。
8. 现有测试缺口：`apps/agent-service/tests/test_messaging_contract_schemas.py:115` `test_fact_impact_omits_none_target_poi_id_on_the_wire` 只覆盖 targetPoiId omit；`test_planning_outcome_events.py` 的 v10 事件测试未覆盖"含 None targetName/sourceUrl/date 的 impact"；Java `PlanningCompletedEventParserTest` 无针对 None-optional 字段的 RED 用例。

### 问题 1（已确认）

1. `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py:929-1110` `_emit_day`：`day_count > 1 and offset > 0` 时在首部插入 `ACCOMMODATION`"从{hotel}出发"slot（start_time-15min → start_time）；`day_count > 1 and offset < day_count-1` 时在尾部追加"返回{hotel}"slot（end_slot → end_slot+15min）。**首日（offset=0）无早晨住宿 slot、末日（offset=day_count-1）无晚间返回 slot** —— 与期望语义（首日 arrival→…→accommodation、末日 accommodation→…→departure）**一致**。
2. 单日行程（day_count==1）：**完全不插入 ACCOMMODATION slot** —— 住宿锚点在单日行程中不参与 routing（发现项，待验证是否为产品缺陷，本批次不修）。
3. ACCOMMODATION slot 属性（已确认）：`time_fixed=False`、duration 固定 15min（窗口外 15min）、`poi=hotel`（真实坐标）、cost=0 → **真实酒店坐标参与真实 AMAP 路由**，不降精度。
4. `apps/agent-service/src/trip_agent/planning/daily_schedule.py:293-324` `day_window_minutes`：默认 start 09:00、end 18:00（INTENSIVE 20:00）；首日 arrival 推后 start（max(start, arrival)）；末日 departure 提前 end（min(end, departure)）；**早 departure 会提前 start**（start = min(start, end - DEPARTURE_BUFFER_MINUTES)）。**没有"因容量不足而提前 start"的机制**。
5. `planning_provider.py:1114` `_fixed_slot_timing_error`：DEPARTURE slot → `INSUFFICIENT_DAY_CAPACITY` + relaxation `EXTEND_AVAILABLE_TIME`（"请提前出发、延后返程时间，或减少前序行程"）；其他固定 slot → `FIXED_SCHEDULE_OVERLAP` + `CHANGE_FIXED_SCHEDULE`。
6. `planning_provider.py:878-905` `_capacity_repair_candidate`：**只移除 scheduled 可选 ATTRACTION/EXPERIENCE 项**（`kind in {ATTRACTION, EXPERIENCE}` 且非 must_include），不触 ACCOMMODATION/MEAL/固定边界；删无可删仍超时 → 失败 → `PlanningInfeasibleError` → `NO_FEASIBLE_ITINERARY`。
7. 结论：**问题 1 不是 anchor 建模 bug**（首日/末日语义正确），而是"真实住宿坐标 + 固定返程 + 固定窗口"下的**真实不可行性**，且 repair 缺少"提前出发/延后返程"的真实松弛手段。`EXTEND_AVAILABLE_TIME` 的建议已生成，但 repair 未执行该松弛。
8. `apps/agent-service/src/trip_agent/worker/processor.py:496-575` `planning_failed_event`：`PlanningInfeasibleError` → PLANNING_FAILED v2，conflicts/relaxation_suggestions 完整映射（`PlanningConflict`/`PlanningRelaxation`）。
9. Java 失败链路（已确认）：`PlanningFailedEventParser` v2 解析 conflicts/relaxationSuggestions（有 size/字段校验）；`PlanningFailureService.handle` 持久化**完整 payload JSON**（writeJson(payload) 含 conflicts/relaxationSuggestions）→ `planning_task_event` → task FAILED + errorCode/displayMessage → `PlanningTaskEventHub` SSE 推送 payload tree。
10. 前端链路（已确认）：SSE 路径 `apps/web/src/lib/feasibility.ts:813-836` `readPlanningEventOutcome` **已解析 conflicts + relaxationSuggestions**（errorParts 拼接，含"建议：{suggestion.message}"）→ `outcome.errorMessage` → `TripWorkspace.vue:386` `planningError = outcome.errorMessage ?? '行程规划失败，请调整条件后重试'`。
11. **REST 快照路径（已确认丢层）**：`feasibility.ts:756-764` `readPlanningTaskOutcome` 只读 `task.errorMessage`（且 api.ts `PlanningTask` 类型无 errorMessage 字段，Java `PlanningTaskResponse` record 也无 errorMessage/conflicts/relaxationSuggestions 字段，`PlanningTaskOutcomeReadModel.readFailed` 未映射 conflicts）→ 刷新后 `readPlanningTaskOutcome` 只能得到默认文案，**conflicts/relaxation_suggestions 在 REST 快照路径丢失**。
12. 用户看到的"时间不足，请重新规划"（推测）：可能来自 SSE 路径已拼接的 conflict message（"实际交通时长无法在固定返程时间前完成"）或 safeMessage；**web 源码中不存在"时间不足"字样**，前端实际文案为"行程规划失败，请调整条件后重试"（待验证：需复现确认用户实际看到的文案来源）。

### 待验证（本批次需要实证）

- 用户实际看到的前端失败文案到底来自哪条路径（SSE errorMessage vs REST 默认文案）。
- 死信消息中除 targetName 外是否还存在其他 None optional 字段（sourceUrl/date）被拒的实例。
- 单日行程（day_count==1）住宿锚点完全不参与 routing 是否为产品级缺陷（本批次仅记录，不修复）。

## 2. Root Cause（分问题）

### 问题 2（P0）Root Cause

```
trusted_context.py  stale 事实 target_name=None
        ↓
contracts.py  _omit_none_target_poi 只 pop targetPoiId，不 pop targetName/sourceUrl/date
        ↓
序列化产出 "targetName": null（optional-not-nullable 违约）
        ↓
Java validateFactImpactTypes 拒收（符合 schema 语义，非 Java bug）
        ↓
DLQ → 任务无终态事件 → 永久 RUNNING（95%）
```

**修复方向（用户指定优先方案 A）**：在 Python serializer 泛化 omit 所有 optional-not-nullable 字段（date/targetPoiId/targetName/sourceUrl），不改 Java validator，不破坏 schema。

### 问题 1（P1）Root Cause

```
用户填写真实住宿锚点
        ↓
_emit_day 首/末/中间日插入 ACCOMMODATION slot（真实酒店坐标，time_fixed=False，15min）
        ↓
末日：酒店→景点→机场真实 AMAP 路线超固定返程时间
        ↓
_fixed_slot_timing_error → INSUFFICIENT_DAY_CAPACITY + EXTEND_AVAILABLE_TIME（建议已生成）
        ↓
_capacity_repair_candidate 只删可选 ATTRACTION/EXPERIENCE，不执行"提前出发/延后返程"
        ↓
删无可删仍超时 → NO_FEASIBLE_ITINERARY（真实不可行，但松弛手段缺失）
        ↓
失败事件 conflicts/relaxations 已生成、已持久化、SSE 已展示
        ↓
REST 快照路径（刷新后）丢失 conflicts/relaxations → 前端只剩默认文案
```

**结论**：根因是"真实约束下的不可行 + repair 缺松弛手段 + REST 快照丢建议"，不是 anchor 建模语义错误。

## 3. Scope（允许修改路径与禁止路径）

### 允许修改

- `apps/agent-service/src/trip_agent/worker/contracts.py`（serializer 泛化）
- `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py`（repair 松弛：提前出发/延后返程，仅当无用户固定约束冲突）
- `apps/agent-service/tests/test_messaging_contract_schemas.py`、`tests/test_planning_outcome_events.py`、新增 provider repair 测试
- `apps/travel-server/.../planning/PlanningTaskOutcomeReadModel.java`、`PlanningTaskService.java`（REST 快照补 conflicts/relaxationSuggestions 映射）
- `apps/travel-server/.../infrastructure/mq/PlanningFailedEventParser.java`（仅测试验证，不改校验语义；若 REST 映射需要新 record 字段则加 DTO 字段）
- `apps/web/src/lib/api.ts`、`apps/web/src/lib/feasibility.ts`（REST 快照解析 conflicts/relaxationSuggestions）
- 对应测试文件（Python/Java/Web vitest）

### 禁止

- 禁止修改 `PlanningCompletedEventParser`/`PlanningReviewRequiredEventParser` 的校验语义（Java 端不是 bug）。
- 禁止修改 `contracts/messaging/*.schema.json`（schema 语义正确）。
- 禁止"假修复"问题 1：忽略住宿重规划、住宿 POI 改 `poi=None`、降低真实路线精度、把 ACCOMMODATION 移出路由。
- 禁止修改 `amqp.py` 的 exclude_none 策略（serializer 层已负责；改动发布策略风险大且非必需）。
- 禁止 unrelated refactor（B15/B16 在途改动、死代码清理等一律不动）。
- 禁止改动 Flyway 迁移、compose、`.env`、RabbitMQ 配置。

## 4. Proposed Changes（逐文件）

### 4.1 问题 2（P0）—— contracts.py serializer 泛化

**文件**：`apps/agent-service/src/trip_agent/worker/contracts.py:913-927`

- 将 `_omit_none_target_poi` 重命名为 `_omit_none_optional_fields`（或保留原名但扩展行为），在 `handler(self)` 后对所有 optional-not-nullable 字段做 None pop：
  - `targetPoiId` / `target_poi_id`
  - `targetName` / `target_name`
  - `sourceUrl` / `source_url`
  - `date`
- 保持 `@model_serializer(mode="wrap")` 机制不变，确保 completion 与 review 两条链路同时受益。

**测试（RED）**：
- `tests/test_messaging_contract_schemas.py:115` 现有测试扩展：构造 `target_name=None`、`source_url=None`、`date=None` 的 impact，断言 wire JSON 中四个字段全部缺席、无任何 null。
- 新增：stale 事实场景（trusted_context 产出 STALE_FACT_WARNING，target_name=None）→ 全事件序列化后 schema 校验通过（Draft202012Validator）。
- `tests/test_planning_outcome_events.py`：v10 completion 事件 fixture 含 None-optional impact → wire 无 null。

### 4.2 问题 1（P1）—— repair 松弛 + REST 快照补建议

**文件 A**：`apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py`

- `_capacity_repair_candidate`（:878）保持"删可选 POI"第一优先级。
- 新增/扩展 repair 循环：当 `INSUFFICIENT_DAY_CAPACITY` 且无可删可选 POI 时，尝试**有界窗口松弛**（对应 EXTEND_AVAILABLE_TIME 建议）：
  - 末日：若 departure 固定且 `start > end - DEPARTURE_BUFFER - 所需时长`，允许把当日 start 提前到更早时刻（受 `day_window_minutes` 现有"早 departure 提前 start"逻辑约束，或显式放宽一个增量步长，如 09:00 → 08:00 → 07:30，且不早于最早合理出发时刻）。
  - 中间日：住宿 slot 为软边界（time_fixed=False），允许对称松弛（提前出发/延后返回），但**不得跨越用户固定约束**（fixed_schedules、meal_windows、arrival/departure 锚点）。
  - 松弛后仍不可行 → 维持 `NO_FEASIBLE_ITINERARY`（真实不可行必须失败）。
- 不降低路线精度：所有路由仍用真实 AMAP 坐标与时长。

**文件 B**：`apps/travel-server/.../planning/PlanningTaskOutcomeReadModel.java`

- `readFailed`：从 payload 解析 `conflicts`/`relaxationSuggestions` 到 Outcome（新增字段或携带原始 JsonNode）。

**文件 C**：`apps/travel-server/.../planning/PlanningTaskService.java`

- `PlanningTaskResponse` record 增加 `conflicts`/`relaxationSuggestions` 字段（从 Outcome 透传）；`TerminalMetadata` 同步扩展；`toResponse` 透传。

**文件 D**：`apps/web/src/lib/api.ts`

- `PlanningTask` 接口增加 `conflicts?: Array<{code, message, affected}>`、`relaxationSuggestions?: Array<{code, message}>`、`errorMessage?: string | null`（可选，与后端对齐）。

**文件 E**：`apps/web/src/lib/feasibility.ts`

- `readPlanningTaskOutcome`（:756）：解析 `task.conflicts`/`task.relaxationSuggestions`，与 `readPlanningEventOutcome` 相同逻辑拼接 errorParts → errorMessage；无 conflicts 时回落 safeMessage/默认文案。

**测试（RED）**：
- Python：provider repair 测试——末日"酒店→机场"超时但有松弛空间 → 成功产出 itinerary（start 提前）；无松弛空间（最早时刻仍不可行）→ 仍 NO_FEASIBLE_ITINERARY；中间日松弛不越过 fixed_schedules/meal_windows。
- Java：`PlanningTaskOutcomeReadModelTest`（已存在未跟踪文件）扩展——FAILED payload 含 conflicts/relaxationSuggestions → readFailed 输出包含。
- Java：`PlanningTaskService` 测试——FAILED task 的 REST response 包含 conflicts/relaxationSuggestions。
- Web：`feasibility.test.ts`——readPlanningTaskOutcome 对含 conflicts/relaxationSuggestions 的 task 产出 errorMessage（含"建议："）。

## 5. Problem 1 Design Decision（A/B/C/D 比较）

| 方案 | 内容 | 判定 |
| --- | --- | --- |
| **A** | 假修复：忽略住宿重规划 / 住宿 POI 改 `poi=None` / 住宿不参与路由 | **禁止**（违反真实性底线，用户已明确排除） |
| **B** | 仅 Python repair 松弛（提前出发/延后返程），不动 Java/Web | 修复了"可行但被误判不可行"的 case，但刷新后用户仍看不到具体建议（REST 快照仍丢） |
| **C** | 仅链路修复：Java REST 快照补 conflicts/relaxationSuggestions + 前端解析 | 不可行场景下用户能看懂失败原因，但"可提前出发"的 case 仍失败，治标不治本 |
| **D** | **B + C 组合（本批次默认推荐）**：真实松弛 + 全链路建议可达 | 真实不可行仍 NO_FEASIBLE_ITINERARY；可行 case 不再误失败；失败时用户看到冲突与建议（SSE + REST 双路径） |

**默认决策：D**。若验收阶段发现 B 引入 golden 变化过多，可降级为 C（仅链路修复）并重新评估。

## 6. Test Plan（RED 清单 + 门禁）

### RED 测试清单（先写测试、确认失败）

1. `tests/test_messaging_contract_schemas.py`：None optional 四字段全部 omit（RED：当前只 omit targetPoiId → 失败）。
2. `tests/test_planning_outcome_events.py` 或新增：stale 事实 → v10 事件 wire 无 null，schema 校验通过（RED：现产出 targetName:null → 失败）。
3. Python provider repair：末日可提前出发 case → 成功（RED：现 NO_FEASIBLE_ITINERARY → 失败）。
4. Python provider repair：最早时刻仍不可行 case → 保持 NO_FEASIBLE_ITINERARY（RED：需保证松弛有界 → 若实现无限松弛则该测试失败）。
5. Python provider repair：中间日松弛不越过 fixed_schedules/meal_windows（RED：现无松弛 → 失败）。
6. Java `PlanningTaskOutcomeReadModelTest`：readFailed 输出 conflicts/relaxationSuggestions（RED：现无 → 失败）。
7. Java `PlanningTaskService`：FAILED response 含 conflicts/relaxationSuggestions（RED：现无 → 失败）。
8. Web `feasibility.test.ts`：readPlanningTaskOutcome 解析 conflicts/relaxations（RED：现只读 errorMessage → 失败）。

### 门禁

- 定向：上述 8 个测试文件全绿。
- 分层：`apps/agent-service` pytest 全量；`apps/travel-server` mvn test；`apps/web` vitest run + vue-tsc。
- 全量：docker compose 冒烟（trip-pilot-prod 复现问题 2：stale 天气事实场景不再 DLQ；问题 1：住宿场景刷新后 REST 快照显示建议）；不得降低现有 coverage。

## 7. Risks

1. **工作区在途改动大**（B15/B16 55 文件未提交）：本批次叠加修改有冲突风险 → 逐文件小改、只碰本批次目标文件、禁止 stash/checkout。
2. **repair 松弛改变行程结果**：提前出发可能影响 golden matrix / 既有测试 → 松弛必须有界且受用户固定约束限制；全量测试验证。
3. **REST 响应新增字段**：前端类型与后端 record 同步，缺失时前端保持回落默认文案，不破坏既有行为。
4. **serializer 泛化影响面**：completion 与 review 双链路同时变化 → 两链路测试都要过；wire 契约不变（schema 本就允许缺席）。
5. **Java 端只加字段不改校验**：避免触碰 parser 语义，降低回归面。
6. **CRLF 换行警告**：现有工作区已有 CRLF 警告，本批次新增编辑保持与目标文件一致，不做全文件换行转换。

## 8. Acceptance Criteria

- [ ] 问题 2：含 None optional 字段的事实影响（stale 天气）不再产出 null；completion 与 review 双链路 wire 通过 schema；死信队列不再新增；任务正常终态（SUCCEEDED/FAILED）。
- [ ] 问题 1：住宿场景在"有松弛空间"时成功规划（真实住宿仍参与路由、精度不降）；"真实不可行"仍返回 NO_FEASIBLE_ITINERARY；失败时前端 SSE 与 REST 快照均展示 conflicts + relaxation_suggestions（含"建议："）。
- [ ] 全部 RED 测试先红后绿；分层/全量门禁通过；coverage 不降。
- [ ] 本批次实现保持 unstaged，不 stage/commit/push；三份批次文档（plan 本文件 + execution-report + acceptance-report 由验收 Agent 生成）齐备后由独立 Git 收口。

## 9. 完成标志

- 实现代码 + 测试全部落盘且 unstaged；
- 8 项 RED 全绿 + 分层/全量门禁通过；
- `docs/execution/B17/execution-report.md` 已由执行 Agent 完成（含每轮 RED 真实失败记录、GREEN 文件清单、门禁结果）；
- 等待独立验收 Agent 写入 `docs/execution/B17/acceptance-report.md` 后收口。