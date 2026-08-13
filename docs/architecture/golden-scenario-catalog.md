# Golden Scenario Catalog

TripPilot 跨层 Golden 场景的单一权威定义。Python（agent-service）、Java（travel-server）、Web（Playwright）三层测试通过稳定场景 ID 消费本矩阵，或逐字锁定其语义。任何一层不得复制、改写或漂移本矩阵的期望值。

## 权威位置

本文档是 Golden 场景 ID 与期望矩阵的唯一权威来源。各层测试文件以 `Gxx_` 前缀的测试名引用场景 ID；本矩阵更新时，各层消费方须同步。

## 锁定语义（全局不变式）

1. **VERIFIED 才能创建正式版本**：只有 `FeasibilityStatus.VERIFIED` 的 completion（schemaVersion 9）能创建/推进正式 itinerary version；`NEEDS_REPAIR`/`UNVERIFIED` 只能形成 review candidate，不触碰 current version。
2. **NEEDS_REPAIR/UNVERIFIED 只能形成 review candidate**：review event（v1）携带候选，UI 隔离展示，无接受/强制保存/跳过验证路径。
3. **UNKNOWN/STALE/CONFLICTING evidence 不得形成 hard PASS**：`hard_constraint_eligible` 仅当 `state == VERIFIED`；PASS/FAIL 必须有至少一条 VERIFIED eligible OPENING_HOURS 证据（否则模型层拒绝）。
4. **AREA_ESTIMATED/UNRESOLVED 住宿不得形成 confirmed continuity PASS**：跨日连续性需要 confirmed 住宿；area-estimated 与 unresolved 不能产生连续 PASS。
5. **Demo 主旅程可运行，但缺真实证据必须 UNVERIFIED**：Demo provider 不伪造 opening evidence、不伪造 confirmed 住宿；缺证据时报告为 UNVERIFIED，绝不 VERIFIED。
6. **repair 最多三轮，失败历史完整**：`repair_attempts` 索引从 1 连续，最多 3；每轮记录 triggering_rule_ids/action_codes/affected/before-after fingerprint/resulting_status。
7. **EDIT/ROLLBACK 不得绕过 candidate 门禁**：candidate 与 formal version 隔离；只有 candidate VERIFIED 才 `USER_EDIT`/`ROLLBACK`，否则 WAITING_USER 且 current 不变。
8. **stale baseline 不得覆盖 current**：trip/replan baseline 过期 → task FAILED（STALE_TRIP_VERSION / STALE_ITINERARY_VERSION），不覆盖 current。
9. **PlanEvaluation 只能在 VERIFIED 后执行**：`PlanningCompletedEventV9` 才携带 evaluation；review event 不携带。
10. **历史无 report 必须显示 null/无历史验证**：VersionSummary feasibility 为 null 时 UI 显示「无历史验证」，不得伪装「未验证」。

## 规则与状态词汇表

- 硬规则（11）：`TRIP_DATE_RANGE` `FIXED_SCHEDULE_COVERAGE` `BUDGET_LIMIT` `MUST_VISIT_COVERAGE` `DUPLICATE_POI` `ACTIVITY_OVERLAP` `ROUTE_ENDPOINT_CONTINUITY` `CROSS_DAY_CONTINUITY` `OPENING_HOURS` `VISIT_DURATION` `MEAL_WINDOW`
- `FeasibilityStatus`：`VERIFIED` / `NEEDS_REPAIR` / `UNVERIFIED`
- `RuleOutcome`：`PASS` / `FAIL` / `UNKNOWN` / `NOT_APPLICABLE`
- `EvidenceState`：`VERIFIED` / `UNKNOWN` / `STALE` / `CONFLICTING`
- 聚合：任一 `FAIL` → `NEEDS_REPAIR`；否则任一 `UNKNOWN` 或缺 required 规则 → `UNVERIFIED`；否则 `VERIFIED`
- FAIL 与 UNKNOWN 的语义边界：缺失必要 transit leg（`ROUTE_LEG_MISSING`）与 confirmed overnight 端点不匹配（`OVERNIGHT_ENDPOINT_MISMATCH`）是明确的 FAIL → `NEEDS_REPAIR`，绝不降级为 UNKNOWN；AREA_ESTIMATED / UNRESOLVED 住宿与缺失证据是证据缺口（UNKNOWN）→ `UNVERIFIED`
- `AccommodationState`：`CONFIRMED` / `AREA_ESTIMATED` / `UNRESOLVED`

## 场景矩阵

列含义：`scenarioId` | `entryPoint` | `providerMode` | `accommodationState` | `evidenceState` | `expectedStatus` | `blockingRule/reasonCode` | `formalVersionMutation` | `currentVersionMutation` | `repairAttempts` | `api/sseOutcome` | `planEvaluationAllowed` | `realProviderRequired`

| scenarioId | entryPoint | providerMode | accommodation | evidence | expectedStatus | blocking/reason | formalVersion | currentVersion | repair | outcome | eval | real |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G01_LATE_ARRIVAL | CREATE | AMAP | UNRESOLVED | VERIFIED | UNVERIFIED | CROSS_DAY_CONTINUITY / continuity unresolvable | none | none | 0 | REVIEW_REQUIRED | no | yes |
| G02_EARLY_DEPARTURE | CREATE | AMAP | UNRESOLVED | VERIFIED | UNVERIFIED | CROSS_DAY_CONTINUITY | none | none | 0 | REVIEW_REQUIRED | no | yes |
| G03_SINGLE_DAY_TRIP | CREATE | AMAP | n/a | VERIFIED | VERIFIED | none | create v1 | set v1 | 0 | COMPLETED | yes | yes |
| G04_CONFIRMED_HOTEL | CREATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | none | create v1 | set v1 | 0 | COMPLETED | yes | yes |
| G05_AREA_ESTIMATED_HOTEL | CREATE | AMAP | AREA_ESTIMATED | VERIFIED | UNVERIFIED | CROSS_DAY_CONTINUITY | none | none | 0 | REVIEW_REQUIRED | no | yes |
| G06_UNRESOLVED_HOTEL | CREATE | AMAP | UNRESOLVED | VERIFIED | UNVERIFIED | CROSS_DAY_CONTINUITY | none | none | 0 | REVIEW_REQUIRED | no | yes |
| G07_CROSS_DAY_CONTINUOUS | CREATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | none | create v1 | set v1 | 0 | COMPLETED | yes | yes |
| G08_CROSS_DAY_BROKEN | CREATE | AMAP | CONFIRMED | VERIFIED | NEEDS_REPAIR | CROSS_DAY_CONTINUITY / OVERNIGHT_ENDPOINT_MISMATCH | none | none | 0 | REVIEW_REQUIRED | no | yes |
| G09_OPENING_VERIFIED_WINDOW | CREATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | none | create v1 | set v1 | 0 | COMPLETED | yes | yes |
| G10_OPENING_VERIFIED_CLOSED | CREATE | AMAP | CONFIRMED | VERIFIED | NEEDS_REPAIR | OPENING_HOURS / VENUE_CLOSED | none | none | ≥1 | REVIEW_REQUIRED | no | yes |
| G11_OPENING_STALE | CREATE | AMAP | CONFIRMED | STALE | UNVERIFIED | OPENING_HOURS / UNKNOWN | none | none | 0 | REVIEW_REQUIRED | no | yes |
| G12_OPENING_CONFLICTING | CREATE | AMAP | CONFIRMED | CONFLICTING | UNVERIFIED | OPENING_HOURS / UNKNOWN | none | none | 0 | REVIEW_REQUIRED | no | yes |
| G13_OPENING_CROSS_MIDNIGHT | CREATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | none | create v1 | set v1 | 0 | COMPLETED | yes | yes |
| G14_LAST_ENTRY_BOUNDARY | CREATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | none | create v1 | set v1 | 0 | COMPLETED | yes | yes |
| G15_EXPLICIT_MEAL_WINDOWS | CREATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | none | create v1 | set v1 | 0 | COMPLETED | yes | yes |
| G16_IMPOSSIBLE_MEAL_WINDOW | CREATE | AMAP | CONFIRMED | VERIFIED | NEEDS_REPAIR | MEAL_WINDOW | none | none | ≥1 | REVIEW_REQUIRED | no | yes |
| G17_DURATION_MIN_MAX | CREATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | none | create v1 | set v1 | 0 | COMPLETED | yes | yes |
| G18_DUPLICATE_POI_REPAIR | CREATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | DUPLICATE_POI (repaired) | create v1 | set v1 | 1 | COMPLETED | yes | yes |
| G19_TRANSIT_REPAIR | CREATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | ROUTE_ENDPOINT_CONTINUITY (repaired) | create v1 | set v1 | 1 | COMPLETED | yes | yes |
| G20_REPAIR_EXHAUSTED | CREATE | AMAP | CONFIRMED | VERIFIED | NEEDS_REPAIR | DUPLICATE_POI | none | none | 3 | REVIEW_REQUIRED | no | yes |
| G21_PROVIDER_FAILURE_REAL_ONLY | CREATE | AMAP | n/a | n/a | n/a | PLANNING_FAILED | none | none | 0 | FAILED | no | yes |
| G22_PROVIDER_FALLBACK_DEMO | CREATE | AMAP→DEMO | n/a | UNKNOWN | UNVERIFIED | OPENING_HOURS / UNKNOWN | none | none | 0 | REVIEW_REQUIRED | no | yes |
| G23_EDIT_VERIFIED | EDIT_VALIDATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | none | USER_EDIT v+1 | set v+1 | 0 | COMPLETED | yes | yes |
| G24_EDIT_NEEDS_REPAIR | EDIT_VALIDATE | AMAP | CONFIRMED | VERIFIED | NEEDS_REPAIR | OPENING_HOURS | none | unchanged | ≥1 | REVIEW_REQUIRED | no | yes |
| G25_EDIT_STALE_BASELINE | EDIT_VALIDATE | AMAP | CONFIRMED | VERIFIED | n/a | STALE_ITINERARY_VERSION | none | unchanged | 0 | FAILED | no | yes |
| G26_ROLLBACK_VERIFIED | ROLLBACK_VALIDATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | none | ROLLBACK v+1 | set v+1 | 0 | COMPLETED | yes | yes |
| G27_ROLLBACK_UNVERIFIED | ROLLBACK_VALIDATE | AMAP | UNRESOLVED | UNKNOWN | UNVERIFIED | CROSS_DAY_CONTINUITY | none | unchanged | 0 | REVIEW_REQUIRED | no | yes |
| G28_DUPLICATE_OUTCOME | CREATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | none | create once | set once | 0 | COMPLETED (idempotent) | yes | yes |
| G29_SSE_RECONNECT_REPLAY | CREATE | AMAP | CONFIRMED | VERIFIED | VERIFIED | none | create v1 | set v1 | 0 | COMPLETED (Last-Event-ID) | yes | yes |
| G30_HISTORICAL_VERSION_WITHOUT_REPORT | n/a (read) | n/a | n/a | n/a | n/a | feasibility=null | none | none | 0 | 显示「无历史验证」 | n/a | no |

## 各层消费约定

- **Python**：orchestrator 级测试（`process_planning_create/replan/candidate_validation` + bounded repair + Demo/AMap 可控 fake），固定 UUID/时间/TZ，结构断言，`G01`–`G22` 覆盖 planning 域，`G23`–`G28` 覆盖 candidate 域。
- **Java**：Testcontainers 跨层测试，DB read-back + JSON 深比较，覆盖 `G23`–`G30` 的持久化/SSE/VersionSummary 语义与 completion v9 / review v1 门禁。
- **Web**：Playwright journey，覆盖 `G23`–`G30` 的 UI 权威 outcome、candidate 隔离、SSE 重连、历史 feasibility=null。

## 边界

- `realProviderRequired=yes` 的场景在单元层用可控 fake provider 模拟真实投影语义；真实网络验证属独立运维门禁，不在本 catalog 门禁内。
- 本 catalog 不引入 staging/TLS/registry/24h soak/生产告警；项目定位本地优先小型项目。
