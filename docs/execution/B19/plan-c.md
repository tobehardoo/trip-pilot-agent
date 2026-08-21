# B19-C Multi-mode Recommendation Plan（真实三模式推荐）

- 计划日期：2026-08-19
- 基线：`docs/execution/B19/audit.md`（架构审计）、`plan-b.md`（TRANSIT 能力计划）、`execution-report-b.md` + `acceptance-report-b.md`（B19-B **PASS_WITH_DEFECT**，D1 非阻塞）、`docs/execution/B18/plan.md` + `acceptance-report-b.md`（B18-A/B 已 PASS）
- 分支 / HEAD：`codex/feasibility-foundation` @ `d10e70c`
- 工作区：102 项在途修改（B15/B16/B17/B18-A/B18-B/B19-A/B19-B 混合）保持原样；**本阶段未修改任何生产代码 / contract / DB / UI**
- 状态：**计划阶段，未开始实施**。本计划形成后可进入 RED→GREEN 实施

---

## 1. Executive Summary

> B19-C 将把 B18-B 的"walkable→WALKING，否则→DRIVING"二元阈值，演进为**在真实 WALKING / TRANSIT / DRIVING route facts 之上的 staged、确定性、可解释、受 API budget 约束的每-leg 三模式推荐**——walking 优先短路（保持 B18-B 产品语义"不是最快获胜"），其余 leg 比较 TRANSIT 与 DRIVING（真实 provider duration + 换乘/步行负担），推荐结果以单一 RoutePlan 返回并直接进入 forward-fit / fixed-slot / capacity 链路，全程不触碰 contract v11 / DB / Java / Web。

---

## 2. Verified Baseline（复核后的关键代码事实）

| 事实 | 证据 |
| --- | --- |
| `RouteMode = Literal["WALKING","DRIVING","TRANSIT"]`；`RouteRequest` 含 city/destination_city/strategy/nightflag/departure_at；`RoutePlan` 含 walking_distance_meters/transfer_count | `_route_contracts.py:16, 24-48` |
| `_route_for_pair(origin_poi, destination_poi, departure_at, route_cache, route_calls)` — **无 city 参数**；决策流：`straight=haversine` → `should_try_walking(≤1500m)` → `_try_walking_route(WALKING)` → `is_walkable(≤1200s)` → WALKING，否则 `_route_cached(DRIVING)` | `planning_provider.py:1650-1698` |
| walking 可恢复失败（TIMEOUT/NETWORK/PROVIDER_UNAVAILABLE/RATE_LIMITED/NO_RESULT/UNSUPPORTED_MODE）→ 降级 DRIVING；非可恢复（INTERNAL/AUTH/PERMISSION/INVALID_REQUEST/MALFORMED/QUOTA）→ re-raise | `_RECOVERABLE_WALKING_CATEGORIES` `planning_provider.py:108-118`；`_try_walking_route:1700-1721` |
| 所有 planner route query 经 `_route_cached`（统一计数 `MAX_ROUTE_CALLS_PER_PLAN=96` + 内存 cache）；TRANSIT key = `("TRANSIT", city, strategy, nightflag, origin, destination, 15min+日期 bucket)`；W/D key = `(poi×2, mode, departure_at.isoformat())` | `planning_provider.py:1723-1760`；`domain/shared.py:41` |
| provider 选择：`_route` 按 mode 分流（TRANSIT→transit provider；否则 route provider）+ 既有 FallbackPolicy | `planning_provider.py:1603-1648` |
| `_emit_day` 持有 `command`（可访问 `trip.destination` 城市与 `guide_evidence.facts` 天气）；`departure_at = origin["end"]`（forward-fit 后的真实离开时刻） | `planning_provider.py:1006-1020, 1114-1120` |
| forward-fit / fixed-slot / monotonic sweep 使用**选中** `route.data.duration_seconds` | `planning_provider.py:1121-1161` |
| DRIVING cost = AMAP `cost.toll_cost`（**过路费**；市区通常 0 或 None）；WALKING = 0；TRANSIT cost = AMAP `transit.cost`（真实票价） | `_amap_route.py:214-227`；`_transit_cost:1578-1589` |
| `TripConstraints`：mobility_level（STANDARD/REDUCED/STEP_FREE）、pace（RELAXED/BALANCED/INTENSIVE）；**无** transportPreference/selfDriving/vehicle/weather/luggage | `contracts.py:167-190` |
| mobility_level 当前仅 `_mobility_repair_candidate`（REDUCED 时按 leg>3000m 剔除候选）；pace 仅影响 day buffer/end；**两者均不参与 mode 决策** | `planning_provider.py:488, 902-917`；`daily_schedule.py:62-67, 315` |
| Web AUTO：walking≤20min→WALKING；transit≤taxi×1.6→TRANSIT；taxi→TAXI；driving→DRIVING（**估算值**，非真实 route） | `web/src/lib/transit.ts:65-76` |
| 活动 kind 含 ARRIVAL/DEPARTURE/ACCOMMODATION/MEAL/ATTRACTION/EXPERIENCE；`_resolve_travel_anchors` 解析 arrival/departure/accommodation POI | `domain/shared.py:26-28`；`planning_provider.py:1434` |
| evaluation 现有 `routeEfficiency`（权重 15%）+ `route_warnings` LONG_WALKING；**无 per-mode 质量分** | `evaluation/rules.py:48, 340-364`；`scoring.py:12` |
| replan 走 `LocalReplanningProvider._route`（不经 `_route_cached` 计数，B18-B 既有设计）；existing TRANSIT leg → `RouteRequest(mode="TRANSIT", city=trip.destination, departure_at=origin.end_time)` | `replan_service.py:262-285`；acceptance-report-b §13 |
| **D1**（B19-B 唯一非阻塞缺陷）：全段/单段 polyline 缺失时 fail-closed `PROVIDER_SCHEMA_CHANGED`，未实现 plan-b §4.4"跳段+2点退化"；真实 G1 与全部 fixture 均带 polyline，真实数据未触发；**不影响 duration/distance/cost/walking_distance/transfer_count** | `acceptance-report-b.md` §19 |
| 真实基线数据（B19-A）：正佳→广州塔 TRANSIT 1250s/¥2/654m/0换乘 vs DRIVING 1632s vs WALKING 3602s；正佳→机场 TRANSIT 12139s/5段/2981m vs DRIVING 3682s | `audit.md` 附：真实数据采集证据 |

---

## 3. Scope / Non-scope

### 做什么（B19-C 唯一目标）

> 让普通 planner 在真实 route facts 基础上，为每条 TransitLeg 推荐合理的 WALKING / TRANSIT / DRIVING（staged、确定性、可解释、有 budget）。

| # | 内容 |
| --- | --- |
| 1 | staged route querying（walking 短路 → transit+driving 比较） |
| 2 | ordered-rule recommendation（duration 比 + transfer + walking burden） |
| 3 | recommendation 输入模型（RoutePlan facts + reason） |
| 4 | route call budget 模型 + 预算耗尽降级策略 |
| 5 | timing integration（selected duration → forward-fit / fixed-slot / capacity） |
| 6 | 结构化 recommendation reason / trace（logging/evaluation 层，不持久化） |
| 7 | Golden 校准（真实广州 OD + 反例） |
| 8 | fallback / provider failure matrix |
| 9 | D1 影响评估与处置 |
| 10 | RED 测试矩阵 C1-C16 + 真实城市验证方案 |

### 明确不做（B19-D 或后续批次）

```text
ROAD enum migration、PUBLIC_TRANSIT enum、TAXI provider、SELF_DRIVING、自驾约束
驾车/打车按钮合并、manual edit TRANSIT 真实化、完整公交 segments 持久化、线路/站点复杂 UI
天气推荐、行李偏好正式建模、用户交通偏好 constraint、LLM recommendation
B18-C diversity、B18-D parent/complex dedup、OR-Tools 全局 mode 优化、mode 占比 KPI
```

---

## 4. Current Recommendation Flow（现状）

```
_emit_day（每相邻 activity pair）
  │ departure_at = origin["end"]
  ▼
_route_for_pair(origin_poi, destination_poi, departure_at, cache, calls)
  │ straight = haversine
  ├─ straight ≤ 1500m → 查真实 WALKING（1 call）
  │     ├─ duration ≤ 1200s → WALKING（返回 walking RoutePlan）
  │     ├─ duration > 1200s → 查 DRIVING（+1 call）→ DRIVING
  │     └─ walking 可恢复失败 → 查 DRIVING → DRIVING
  └─ straight > 1500m → 只查 DRIVING（1 call）→ DRIVING
  ▼
selected RoutePlan（单一对象）→ forward-fit（duration_seconds）→ _leg_from_route → TransitLeg
```

**当前问题**：TRANSIT 已是真实 provider 能力，但 `_route_for_pair` 从不查询它——B18-B baseline 对"地铁 21min vs 汽车 27min"（正佳→广州塔）仍产出 DRIVING。

---

## 5. Target Recommendation Flow（未来 staged querying）

```
_route_for_pair(origin_poi, destination_poi, departure_at, city, cache, calls)
  │ Stage 1 — WALKING 短路（复用 B18-B 语义，零回归）
  ├─ straight ≤ 1500m → 查真实 WALKING（1 call）
  │     ├─ duration ≤ 1200s → WALKING（reason=WALKABLE；不再比较其它 mode——
  │     │     "walking 8min / road 4min → WALKING"是产品语义，不是最快获胜）
  │     └─ duration > 1200s 或 walking 可恢复失败 → 进入 Stage 2
  │
  │ Stage 2 — TRANSIT vs DRIVING（walking 不合适时）
  ├─ 若 city 可确定（trip.destination）且 budget 未接近耗尽 → 查 TRANSIT（+1 call）
  │     └─ TRANSIT 可恢复失败/NO_RESULT → 视为 TRANSIT 不可用（reason=TRANSIT_UNAVAILABLE）
  ├─ 查 DRIVING（+1 call）
  │     └─ DRIVING 可恢复失败 → 视为 DRIVING 不可用（reason=ROAD_UNAVAILABLE）
  │
  │ Stage 3 — 规则比较（ordered rules，见 §8）
  ├─ 只有 DRIVING 可用 → DRIVING
  ├─ 只有 TRANSIT 可用 → TRANSIT
  ├─ 两者可用 → 按 R/N/W 阈值规则选 TRANSIT 或 DRIVING
  └─ 两者都不可用 → 沿用既有 provider error policy（raise / DEMO fallback，不伪造）
  ▼
selected RoutePlan（单一对象，facts 同源）+ ModeRecommendation(reason, alternatives)
  → forward-fit / fixed-slot / capacity（duration_seconds 为最终推荐 mode 的真实值）
  → _leg_from_route → TransitLeg（v11 已支持三种 mode，无 contract 变更）
```

**关键不变式**：① `_route_for_pair` 仍是唯一出口，返回单一 `ProviderSuccess[RoutePlan]`，facts 同源；② 所有查询仍经 `_route_cached`（budget+cache）；③ walking 短路优先保持 B18-B 语义；④ **不修改已验收的 `is_walkable`/`should_try_walking` 语义**，仅在 `_route_for_pair` 内部扩展分支。

---

## 6. Recommendation Inputs（能力 Matrix）

| Input | 当前存在 | Source | B19-C v1 使用 |
| --- | --- | --- | --- |
| walking duration | ✅ | AMAP walking route | ✅（短路判定） |
| transit duration | ✅ | AMAP transit | ✅（比较） |
| driving duration | ✅ | AMAP driving route | ✅（比较） |
| transit cost | ✅ | AMAP transit.cost | ⚠️ 仅 trace，不参与跨 mode 比较（见 §7） |
| driving cost | ⚠️ 过路费语义 | AMAP toll_cost（市区常 0/None） | ❌ 不参与比较（不可比，见 §7） |
| walking distance | ✅ | transit.walking_distance | ✅（walking burden W） |
| transfer count | ✅ | vehicle segments - 1 | ✅（transfer burden N） |
| mobilityLevel | ✅ | constraints | ⚠️ 仅 REDUCED/STEP_FREE 收紧 W/N 容忍（见下） |
| pace | ✅ | constraints | ❌（只影响日程 buffer，不表达交通偏好） |
| weather | ✅ 架构可获取 | guide_evidence.facts | ❌（B19-C future input） |
| luggage | ❌ 无字段 | — | ❌ |
| self-driving / transportPreference | ❌ 无字段 | — | ❌（B19-D） |
| 出行场景（酒店→景点 / 景点→机场） | ✅ | ActivityKind + anchors | ⚠️ 仅观测（G7），不加入 v1 规则 |

**mobilityLevel 决定**：**参与，但仅作为容忍度修正量**——`REDUCED`/`STEP_FREE` 时收紧 `MAX_TRANSIT_WALKING_METERS` 与 `MAX_TRANSFERS`（如 W×0.5、N 上限 1）。理由：字段语义是"身体行动能力"，直接关联步行/换乘负担是合理复用；但它**不是**交通偏好，不得改变"WALKING 优先"或引入打车倾向。若实施中发现语义不清则回退为不参与（决策点记录在实施报告中）。

**pace / weather / luggage / 用户偏好决定**：**不进入 v1**。pace 是日程节奏概念（buffer），天气/行李/自驾/偏好需要产品验证与新增 constraint（B19-D 或后续），不在本批编造用户偏好。

---

## 7. Cost Semantics Audit（DRIVING cost 能否参与比较？）

| Mode | cost 语义 | 值示例 | 可比性 |
| --- | --- | --- | --- |
| WALKING | 固定 0（RULE_ESTIMATE） | 0 | — |
| DRIVING | AMAP `cost.toll_cost`（**过路费**）；缺失→None | 市区常 0 / None | **与 TRANSIT 票价不可比**：过路费≠燃油费≠打车费 |
| TRANSIT | AMAP `transit.cost`（真实票价） | ¥2 / ¥4 / ¥9 | — |
| TAXI（未来 B19-D） | 本地估算 12+km×2.6 | ¥25+ | 与 DRIVING 同路线不同费用语义 |

**结论**：**第一版 recommendation 不比较 cost**。DRIVING 的"过路费"与 TRANSIT 票价维度不同（且市区 driving toll 通常为 0/None，若直接比较会产生"DRIVING 免费"的错误推荐）。规则基于 **duration 比 + transfer 负担 + walking 负担**；`transit.cost` 仅写入 recommendation trace（供未来 B19-D Road/Taxi 费用语义收敛后启用）。**禁止**在 B19-C 中把"TRANSIT ¥2 vs DRIVING ¥0 过路费"作为选择依据。

---

## 8. Recommendation Algorithm Options

### Option A — Ordered Rules（**推荐 v1**）

```
if walkable(≤1200s 真实 walking duration) → WALKING                     [WALKABLE]
if transit unavailable（可恢复失败/NO_RESULT/city 缺失/budget 降级）→ DRIVING [TRANSIT_UNAVAILABLE]
if driving unavailable（可恢复失败）→ TRANSIT                            [ROAD_UNAVAILABLE]
if transit.duration ≤ driving.duration × R
   AND transit.transfer_count ≤ N
   AND transit.walking_distance ≤ W
   → TRANSIT                                                           [TRANSIT_PREFERRED]
else → DRIVING                                                         [ROAD_PREFERRED]
```

- 子 reason 细分（可解释）：`TRANSIT_FASTER_THAN_ROAD`（duration 显著优）、`TRANSIT_COMPETITIVE_LOW_TRANSFER`（稍慢但负担低）、`ROAD_SIGNIFICANTLY_FASTER`（duration 劣）、`TRANSIT_TOO_MANY_TRANSFERS`（N 超标）、`TRANSIT_EXCESSIVE_WALKING`（W 超标）。
- 优势：简单、可解释、每个分支可独立 RED；与 B18-B 阈值风格一致。
- 劣势：无法表达连续偏好（用 R/N/W 组合近似）。

### Option B — Weighted Score（不推荐 v1）

```
score(mode) = α·normalized_duration + β·normalized_cost + γ·transfer_penalty + δ·walking_penalty
```

- 风险：权重难校准（缺 cost 可比性）、行为难解释、RED 断言脆弱、与"确定性/可解释"目标冲突。

**决定：v1 采用 Option A（ordered rules）**；若真实 Golden 校准发现 ordered rules 无法表达（如 G5 需要 walking 与 duration 的连续权衡），执行期可局部扩展为"多条件 AND/OR 组合"，但**不引入加权 score**。

---

## 9. Staged Query Strategy（每-leg route calls）

| 情形 | 查询序列 | calls |
| --- | --- | --- |
| 短距（≤1500m）且 walking ≤20min | `[WALKING]` | **1** |
| 短距但 walking >20min | `[WALKING, TRANSIT, DRIVING]` | **3** |
| 短距且 walking 可恢复失败 | `[WALKING, TRANSIT, DRIVING]` | **3** |
| 长距（>1500m） | `[TRANSIT, DRIVING]` | **2** |
| 长距且 city 缺失 / budget 降级 | `[DRIVING]` | **1** |

- **不做**"每 leg 无脑三查"：walking 短路使约 40% leg 保持 1 call（沿用 B18-B 语义）。
- TRANSIT 查询前置条件：`city` 可确定（`command.payload.trip.destination` 非空）且 `route_calls[0] < BUDGET_DEGRADE_THRESHOLD`（见 §13）。
- 极端边界（机场/车站/极长距离）第一版不特判——统一走"TRANSIT+DRIVING 比较"，由真实 facts 决定（G7 观测）。后续可在校准后引入"超长距跳过 TRANSIT"优化（记录为候选，不承诺）。

---

## 10. Failure Matrix（W/T/D provider 失败组合）

复用 B18-B 的可恢复分类原则（`_RECOVERABLE_WALKING_CATEGORIES` 白名单），推广到推荐阶段任一候选 mode：

| WALKING | TRANSIT | DRIVING | 期望 |
| --- | --- | --- | --- |
| good（≤20min） | — | — | **WALKING** |
| too long | good | good | 规则比较（R/N/W） |
| too long | NO_RESULT / 可恢复失败 | good | **DRIVING** |
| 可恢复失败 | good | good | 规则比较（walking 退出） |
| 可恢复失败 | 可恢复失败 | good | **DRIVING** |
| 可恢复失败 | good | 可恢复失败 | **TRANSIT**（reason=ROAD_UNAVAILABLE） |
| 可恢复失败 | 可恢复失败 | 可恢复失败 | 沿用既有 provider error policy（raise / DEMO fallback，**不伪造 transit**） |
| — | **非可恢复失败**（MALFORMED/INTERNAL/AUTH/PERMISSION/INVALID_REQUEST/QUOTA） | — | **raise**（与 B18-B walking 政策一致：编程/契约错误不是不可用信号，不吞） |
| — | — | **非可恢复失败** | **raise**（同上） |

**关键分离**：provider 层 fail-closed（B19-B 语义不变）≠ 推荐层 fallback（B19-C 新增）：推荐在**比较期间**把可恢复失败的候选 mode 视为不可用，但**不会**把非可恢复错误静默吞掉；若最终无可用 mode，走既有 error policy，绝不返回假 TRANSIT 或假 DRIVING。

---

## 11. Timing / Feasibility Integration

- **推荐发生在 timing 之前/之中**：`_route_for_pair` 返回的 selected RoutePlan（含最终 mode 的 `duration_seconds`）直接进入 `_emit_day` 的 forward-fit（`planning_provider.py:1121-1136`）与 fixed-slot / monotonic sweep（`:1148-1161`）——**无需改时序代码**，因为 B18-B 已建立"选中 route 的真实 duration 驱动 timing"。
- 必须验证（C13/C14）：选 TRANSIT 后其真实 duration（常长于 DRIVING）进入 forward-fit → gap 不足时 shift 后续活动或 fail-closed（`time_fixed` 边界不移动）；fixed-slot conflict → 既有 `_fixed_slot_timing_error`。
- capacity repair（B17）：在真实 selected duration 下重新判断；修复机制（drop optional / shift）不变。
- **不得**先按 DRIVING 排表最后"改"成 TRANSIT——本设计天然避免（决策即产出最终 route）。

---

## 12. Feasibility Override Decision

**决定：B19-C v1 不做 feasibility override（Option A — mode 一旦推荐即固定）。**

- 理由：① mode 推荐基于真实 facts，forward-fit/fixed-slot 会如实反映其可行性并走既有 repair/fail-closed；② "TRANSIT→DRIVING 恢复可行性"会引入"feasibility 触发 mode 再决策"的循环，破坏确定性（§34 用户要求 bounded/deterministic，禁止反复振荡）；③ 该语义涉及产品判断（赶固定预约是否值得改打车），属 B19-D 或后续独立批次。
- **登记为 future work**：`feasibility override（bounded：仅当 fixed-slot infeasible 且 faster alternative 可恢复时，单次升级，不循环）`。v1 行为：mode 固定 → infeasible 走既有 capacity repair / fixed-slot failure。

---

## 13. Route Budget Model

### 每-leg calls 估算（staged）

| 场景 | legs | B18-B 现状（1-2/leg） | B19-C staged（平均 ~1.8/leg） | 3-mode 全查（对比，禁止） |
| --- | --- | --- | --- | --- |
| 2 日 | ~6-9 | ~7-10 | ~11-16 | 18-27 |
| 3 日 | ~10-15 | ~12-18 | ~18-27 | 30-45 |
| 5 日 | ~15-25 | ~17-30 | ~27-45 | 45-75 |
| 7 日（MAX_TRIP_DAYS） | ~22-35 | ~25-42 | ~40-63 | 66-105 |

（leg 数取自 audit §9；混合比例假设 ~40% 短距 walkable / ~20% 短距超阈值 / ~40% 长距，实施时用真实 smoke 校准。）

### 硬策略

- `MAX_ROUTE_CALLS_PER_PLAN = 96` **保持不变**（不调整）。
- 新增 **`BUDGET_DEGRADE_THRESHOLD = 80`**（初值）：当 `route_calls[0] >= 80` 时，剩余 leg **跳过 TRANSIT 查询**（仅 DRIVING baseline，1 call/leg），reason=`BUDGET_DEGRADED`，trace 记录。保证 worst-case（35 legs × 3 = 105）也不会击穿 96：80 次后剩余 leg 单查 DRIVING，总 calls ≤ 88。
- 超 96 仍由 `_route_cached` raise `ROUTE_CALL_BUDGET_EXHAUSTED`（既有行为）。
- **禁止**伪造推荐：budget 降级只意味着"不再比较 transit"，不是"声称 transit 更差"。
- replan 不经 `_route_cached` 计数（B18-B 既有设计，保持不变，所有 mode 一致）。

---

## 14. Cache Reuse

- 现成能力（B19-B）：TRANSIT key 含 `mode/city/strategy/nightflag/日期+15min bucket`；W/D key 含 mode——三 mode 天然隔离，同 pair 同参数命中。
- B19-C 复用：Stage 2 的 TRANSIT 与 DRIVING 查询同走 `_route_cached`；同一 pair 在 forward-fit / repair / 同 day 重复经过时命中内存 cache，**不重复 provider call**。
- 新增验证（C11）：同一 pair 两次 `_route_for_pair`（不同调用点）→ provider 调用次数不重复（cache 命中）。
- 不变项：walking/driving key 与 15min bucket 定义不动；`departure_at` 用 `origin["end"]`（真实离开时刻），保证 time-dependent transit 缓存身份正确。

---

## 15. Recommendation Trace

**设计 `ModeRecommendation` 结果对象（planner 层，非 provider contract）：**

```
ModeRecommendation:
  selected_route: ProviderSuccess[RoutePlan]
  reason: Literal[WALKABLE, TRANSIT_PREFERRED, TRANSIT_FASTER_THAN_ROAD,
                  TRANSIT_COMPETITIVE_LOW_TRANSFER, ROAD_PREFERRED,
                  ROAD_SIGNIFICANTLY_FASTER, TRANSIT_TOO_MANY_TRANSFERS,
                  TRANSIT_EXCESSIVE_WALKING, TRANSIT_UNAVAILABLE,
                  ROAD_UNAVAILABLE, BUDGET_DEGRADED, ...]
  alternatives: dict[mode, {duration, distance, cost?, walking_distance, transfer_count, available}]
```

- **v1 不持久化**：reason/alternatives 只进 `logger.info` + 测试断言 + evaluation trace（如未来扩展），**不进 TransitLeg / event v11 / DB**（避免 contract 变更与跨层扩散）。
- 若实施期评估显示 reason 有验收价值，可扩展 `test_golden_matrix` 风格断言锁定 reason——但仍不落 DB。
- 质量指标（§57 用户要求，非 KPI）：Golden expected-match rate、mode distribution（仅观测）、avg route calls/leg、provider failures——由测试与 trace 统计，不设占比目标。

---

## 16. D1 Disposition

**决定：`NON_BLOCKING_FOLLOW_UP`**（不阻塞 B19-C 推荐正确性）。

- **原因**：D1 只影响"polyline 几何缺失"边界（缺几何 → fail-closed `PROVIDER_SCHEMA_CHANGED`，不伪造几何、不把 fallback 误标为真实）；**不产生错误 route facts**——duration/distance/cost/walking_distance/transfer_count 在 polyline 正常时全部正确（acceptance-report-b §5/§19）。
- **影响**：按 §10 failure matrix，若某 leg 的 TRANSIT 查询触发 D1（PROVIDER_SCHEMA_CHANGED，非可恢复）→ raise（走既有 policy）。真实数据从未触发（G1 与全部 fixture 均带 polyline）。
- **暴露面说明**：B19-C 使 TRANSIT 成为默认候选（多数非 walkable leg 都会查），D1 触发面相对 B19-B（仅显式查询）扩大。**建议**在 B19-C 执行期顺带完成 plan-b §4.4 的"跳段 + 全缺退化 2 点"补丁（小、独立、有测试）作为低风险硬化——**但作为可选执行项，不设为本批 RED 前置，不改变验收标准**；若执行期未做，登记 B19-D。
- **是否影响 recommendation facts**：否（facts 不受影响；D1 仅在几何缺失时 fail-closed）。

---

## 17. RED Test Matrix（C1-C16）

测试文件（预计）：`tests/test_mode_recommendation.py`（新，规则纯函数）+ `tests/test_transit_mode.py` 扩展（阈值不回归）+ `tests/test_planning_worker.py`/`tests/test_planning_context_v3.py` 扩展（timing/链路）。

| ID | 断言 | baseline（修复前） | GREEN 后 |
| --- | --- | --- | --- |
| C1 | walking ≤20min（road 更快，如 walk 8min/road 4min）→ **WALKING**（不是 fastest wins） | **baseline GREEN**（B18-B 短路已满足；锁定语义防回归） | WALKING，reason=WALKABLE，且不查询 TRANSIT/DRIVING |
| C2 | walking >20min，TRANSIT 明显更好（duration 优 + 0 换乘 + 步行低）→ **TRANSIT** | **RED**（B18-B 产出 DRIVING，无 transit 查询） | TRANSIT，reason=TRANSIT_FASTER_THAN_ROAD 或 TRANSIT_PREFERRED |
| C3 | TRANSIT 慢很多 / 换乘超标 → **DRIVING** | **RED** | DRIVING，reason=ROAD_SIGNIFICANTLY_FASTER / TRANSIT_TOO_MANY_TRANSFERS |
| C4 | TRANSIT 稍慢但低换乘、低步行 → 按校准规则（R/N/W） | **RED**（无规则） | 按校准阈值断言（G5/G6 校准后定值） |
| C5 | TRANSIT walking burden 超标（如 1800m）→ **DRIVING** | **RED** | DRIVING，reason=TRANSIT_EXCESSIVE_WALKING |
| C6 | TRANSIT NO_RESULT（`transits=[]`）→ **DRIVING** | **RED**（无 transit 查询路径） | DRIVING，reason=TRANSIT_UNAVAILABLE |
| C7 | TRANSIT 可恢复失败（RATE_LIMITED/PROVIDER_UNAVAILABLE/TIMEOUT/NETWORK/UNSUPPORTED_MODE）→ **DRIVING** | **RED** | DRIVING，reason=TRANSIT_UNAVAILABLE |
| C8 | DRIVING 可恢复失败 + TRANSIT 可用 → **TRANSIT** | **RED** | TRANSIT，reason=ROAD_UNAVAILABLE |
| C9 | WALKING 可恢复失败 → 推荐继续（进入 T+D 比较），规划不失败 | baseline 部分 GREEN（B18-B 降级 DRIVING）；RED（B19-C 期望继续比较） | 规则比较照常 |
| C10 | route budget 计数：TRANSIT/DRIVING 全部经 `_route_cached`；超 96 raise；≥80 降级跳 TRANSIT | **RED**（无降级逻辑） | calls 计数断言 + BUDGET_DEGRADED reason |
| C11 | cache 复用：同 pair 重复推荐不重复 provider call（三 mode 各自 key 隔离） | **RED**（无推荐场景测试） | 断言 provider calls 不重复 |
| C12 | selected RoutePlan facts 同源：mode/duration/distance/polyline/cost 均来自被选中的同一次 route 响应 | **RED** | 断言无混用路径（如 TRANSIT duration + DRIVING polyline） |
| C13 | selected TRANSIT duration 进入 forward-fit（shift 后续活动 / time_fixed fail-closed） | **RED** | 断言 gap 计算使用 TRANSIT duration |
| C14 | fixed-slot feasibility：推荐 mode 导致 fixed window conflict → 既有 `_fixed_slot_timing_error`/capacity repair，不用旧 DRIVING duration | **RED** | 断言正确 infeasible/repair |
| C15 | B18 WALKING Golden 不回归（短距 → WALKING，1 call） | baseline GREEN | 原样通过 |
| C16 | B18 long road Golden 不回归（长距 → DRIVING，1 call，无 walking 查询） | baseline GREEN | 原样通过 |

**baseline already GREEN 项**（如实记录）：C1、C15、C16（B18-B 语义锁定）；其余 C2-C14 为 RED。**不人为破坏既有 GREEN**。

---

## 18. Golden Matrix（G1-G8）

脚本放 `C:\Windows\Temp\opencode\`（不提交）。**校准在前，常量在后**（§19）。

| ID | 场景 | 期望 mode | 依据 |
| --- | --- | --- | --- |
| **G1** | 正佳广场 → 广州塔（真实 T2：TRANSIT 1250s/¥2/654m/0换乘 vs DRIVING 1632s vs WALKING 3602s） | **TRANSIT** | transit 更快 + 0 换乘 + 步行可接受（reason=TRANSIT_FASTER_THAN_ROAD） |
| **G2** | 体育中心 → 正佳（~623m，WALKING 218s vs road ~120s） | **WALKING** | walking ≤20min 优先，road 更快也不翻转（产品语义，非 fastest wins） |
| **G3** | 正佳广场 → 白云机场（真实 T5：TRANSIT 12139s/5段/2981m vs DRIVING 3682s） | **DRIVING** | transit 显著慢 + 换乘负担高（reason=ROAD_SIGNIFICANTLY_FASTER） |
| **G4** | TRANSIT 换乘惩罚（真实广州 3+ 换乘 pair，或确定性 fixture：transit 24min/3换乘 vs road 22min） | **DRIVING** | transfer 超标（N 校准值） |
| **G5** | TRANSIT walking burden（真实或 fixture：transit 25min/步行 1800m vs road 24min） | **DRIVING** | walking burden 超标（W 校准值） |
| **G6** | TRANSIT NO_RESULT（fixture `transits=[]`） | **DRIVING** | reason=TRANSIT_UNAVAILABLE，无假路线 |
| **G7** | 市区 → 广州南站（地铁合理的真实 pair） | **由真实 facts 决定**（观测 case：期望 TRANSIT 或 DRIVING 都需与 facts 一致） | 不预设"有行李必须 road"（§54） |
| **G8** | 同一 OD：白天 vs 23:30（深夜） | **推荐使用对应 departure_at**（不强制 mode 不同） | 断言请求 date/time 与 cache bucket 正确区分（§29 深夜场景）；若深夜 transit 存在则正常比较，否则 DRIVING |

**G1-G3 为 B19-A 已实测真实数据的第一轮校准锚点**（G1/G2/G3 分别对应 TRANSIT/WALKING/DRIVING 三类）。G4-G8 在实施期收集（真实广州 pair 或 fixture）。

---

## 19. Threshold Calibration Plan

**流程（先数据后常量，禁止先写死再找测试）：**

```
1. 收集 Golden route facts（真实 AMAP：广州 ~10 对 OD × 每对相关 mode 查询；总真实调用 ≤30 次）
2. 人工判定每对 expected mode（G1-G8 语义）
3. 在候选规则上扫描阈值（R, N, W 网格），求 Golden expected-match 最大化
4. 对边界 case（G4/G5/G6）人工复核"阈值边上的选择是否可接受"
5. 将校准后的常量写入生产代码（集中定义，测试显式注入，不散落 magic number）
```

**候选常量（初值范围，非结论，由 Golden 决定）：**

| 常量 | 语义 | 候选范围 | 校准锚点 |
| --- | --- | --- | --- |
| `MAX_TRANSIT_DURATION_RATIO`（R） | transit.duration ≤ driving.duration × R 才考虑 TRANSIT | 1.0 ~ 1.3 | G1（R 需 ≥1250/1632≈0.77，留余量）、G3（R 需 <12139/3682≈3.3）→ 实际区间会远小于此，以 G4/G5 边界为准 |
| `MAX_TRANSFERS`（N） | transfer_count ≤ N | 1 ~ 2 | G4（3 换乘 → DRIVING，N≤2） |
| `MAX_TRANSIT_WALKING_METERS`（W） | transit.walking_distance ≤ W | 800 ~ 1500 | G5（1800m → DRIVING，W<1800）；G1（654m 通过） |
| mobility 修正 | REDUCED/STEP_FREE 时 W×0.5、N 上限 1 | 修正系数 | G6（mobility Golden 可后续补） |

**不采用 Web AUTO 的 1.6**（`web/src/lib/transit.ts:74` 的 transit≤taxi×1.6 基于**估算** duration 且比较对象是 TAXI）：Python 侧用**真实 AMAP route** 重新校准；1.6 仅作为候选参考值之一，不作为结论。

---

## 20. Real Provider Validation

| 项 | 方案 |
| --- | --- |
| 城市 | 校准主力：**广州**（已有真实锚点）；配额允许时补 **深圳/北京/杭州/成都** 各 1-2 对（用于验证规则跨城市不漂移，非必须） |
| 规模 | 广州 ~10 对 OD × 每对 2-3 个 mode ≈ **20-30 次真实调用**；加其它城市 ≈ 总 **≤50 次**。远低于"上百次"红线 |
| 纪律 | 优先复用 B19-A/B 已缓存证据与现有 fixture；真实调用只用于 G1-G8 高价值点；RATE_LIMITED/QUOTA 时不暴力重试，按 taxonomy 记录 |
| 记录 | endpoint success/latency/rate limit/quota（与 B19-B 同款纪律） |
| smoke | 实施后跑 2-3 日真实广州规划，观测 TransitLeg mode distribution（仅观测，不设占比 KPI）与 avg route calls/leg |

---

## 21. Regression（实施后执行）

```
Python targeted:  pytest tests/test_mode_recommendation.py tests/test_transit_mode.py
                  tests/test_amap_transit.py tests/test_b19_transit_chain.py
Python B18-B:     pytest tests/test_transit_mode.py（B1-B9 调用序列不变）
Python B17/B18:   fixed-slot / capacity / departure / replan / worker 相关套件
Python full:      pytest -q --basetemp=%LOCALAPPDATA%\Temp\pytest-b19c-tmp（Windows ACL 规避）
ruff:             ruff check src/trip_agent tests
Contract:         v10/v11 + review v1/v2 schema 测试（无 contract 变更，回归锁定）
Java:             mvn -pl apps/travel-server test（预期 0 生产修改，全量回归）
Web:              vitest run + vue-tsc -b（预期 0 生产修改）
```

重点：① B18-B 14 项调用序列测试**必须原样通过**（C1/C15/C16 门禁）；② B19-B 51 项 targeted 不回归；③ B17 None-omit 不回归（v1 不触碰 event）。

---

## 22. Files To Change（预计，实施前复核）

**Python（apps/agent-service/src/trip_agent/）**
- `planning/transit_mode.py` — **保持 B18-B 两个阈值与语义不动**；`_route_for_pair` 内新增 staged 分支的常量定义可放此处或新模块（实施时定）
- `planning/mode_recommendation.py`（**新**）— ordered rules + `ModeRecommendation` 结果对象 + reason 枚举 + 阈值常量（集中定义，测试显式注入）
- `infrastructure/amap/planning_provider.py` — `_route_for_pair` 扩展 staged 查询（walking 短路 → transit+driving 比较）、`city` 透传（`command.payload.trip.destination`）、budget 降级、recommendation trace 日志
- （不改）`providers/_route_contracts.py`、`providers/_amap_transit.py`、`replan_service.py`、`worker/contracts.py`、`worker/processor.py`

**测试（apps/agent-service/tests/）**
- `test_mode_recommendation.py`（**新**，C1-C14 规则/集成）
- `test_transit_mode.py` 扩展（C15/C16 回归锁定 + 常量注入）
- `test_planning_worker.py` / `test_planning_context_v3.py` 扩展（C13/C14 timing 链路）
- 可选：Golden 校准脚本（`C:\Windows\Temp\opencode\`，不提交）

**Contract / DB / Java / Web**：零修改（见 §23）。

**文档**：`docs/execution/B19/execution-report-c.md`（实施后）+ 本计划。

---

## 23. Contract / DB / Java / Web Decision

| 层 | 决定 | 理由 |
| --- | --- | --- |
| Contract / event version | **NO（不升 v12）** | v11 已支持 WALKING/TRANSIT/DRIVING；recommendation reason 不持久化 → 无需新版本 |
| DB | **NO（无 migration）** | 三种 mode 已全部在 V23 CHECK；只改变"哪个 mode 被选中" |
| Java | **NO（0 生产修改）** | 推荐全在 Python；Java 继续消费 mode/duration/distance/cost/polyline |
| Web | **NO（0 生产修改）** | planner 可能输出 TRANSIT，Web 已显示"公交/地铁"；仅可补 mode-mix 显示测试（如必要） |
| replan | **NO（不改）** | 已支持 existing TRANSIT 真实查询（B19-B）；B19-C 不改 replan 路径 |
| manual edit | **NO（仍延期，B19-D）** | planner-generated TRANSIT 真实 vs manual edit DEMO 估算；B19-C 后用户更常见真实 TRANSIT → 该一致性 gap 严重度上升，**登记为 B19-D 必做 follow-up** |

---

## 24. Risks

| # | 风险 | P | I | 缓解 |
| --- | --- | --- | --- | --- |
| 1 | **API amplification**（transit 默认查询增加调用） | 中 | 中 | staged 短路（walking 1 call）+ budget 降级（≥80 跳 transit）+ 96 上限不变；§13 测算 7 日 worst ≤88 |
| 2 | **阈值（R/N/W）校准不当** | 中 | 高 | Golden 校准在前、常量在后；边界 case 人工复核；G1-G8 全覆盖三类 mode |
| 3 | **DRIVING cost 语义错配**（过路费 vs 票价直接比较） | 低（设计已排除） | 高 | v1 不比较 cost；transit cost 仅 trace；§7 明示禁止 |
| 4 | provider failure（transit/driving 可恢复）导致推荐质量下降 | 中 | 低 | §10 failure matrix：降级为可用候选，最终无可用 mode 走既有 policy |
| 5 | **time-dependent transit**（同一 pair 不同出发时刻结果不同） | 中 | 低 | departure_at=origin["end"]；cache 含日期+15min bucket（B19-B 已建） |
| 6 | **feasibility conflict**（推荐 TRANSIT 后 fixed-slot 不可行） | 中 | 中 | 真实 duration 进入 forward-fit/fixed-slot（C13/C14）；既有 repair/fail-closed；v1 不做 mode override（§12 登记 future） |
| 7 | cache 复用不足导致重复查询 | 低 | 低 | 三 mode key 隔离已建；C11 锁定；同 pair 命中内存 cache |
| 8 | **mode oscillation**（同一 leg 不同运行结果漂移） | 中 | 中 | 确定性 ordered rules + 固定 departure_at 语义 + 已持久化版本不重查（B19-B reproducibility 原则） |
| 9 | scope creep（滑向全局优化/加权 score/天气/偏好） | 中 | 高 | §3 明确排除；ordered rules 固定；Golden 不可表达时才局部扩展 |
| 10 | **manual edit 不一致**（用户看到真实 transit 后手动编辑变 DEMO） | 高（已知） | 中 | **本批不修**，登记 B19-D 必做；不影响 planner 链路验收 |
| 11 | D1 暴露面扩大（transit 默认查询） | 低 | 低 | §16：NON_BLOCKING；执行期可选补丁（跳段+2点） |
| 12 | mobility 修正语义不清 | 低 | 中 | v1 仅收紧 W/N；实施若发现歧义回退为不参与（决策点记录） |

---

## 25. Acceptance Criteria

- [ ] walking ≤20min 仍优先 WALKING（C1；road 更快不翻转——非 fastest wins）
- [ ] walking 不合适时会真实查询并考虑 TRANSIT（C2）
- [ ] TRANSIT vs DRIVING 使用真实 provider facts（duration/walking_distance/transfer_count），非前端估算（C2-C5/C12）
- [ ] recommendation 不只是 fastest wins（C1/G2 反例锁定）
- [ ] transfer burden 有影响（C3/G4：N 阈值）
- [ ] transit walking burden 有影响（C5/G5：W 阈值）
- [ ] TRANSIT NO_RESULT 安全 fallback DRIVING（C6/G6）
- [ ] provider 可恢复失败安全 fallback（C7/C8/C9）；非可恢复错误不吞（§10）
- [ ] selected mode route facts 同源（C12）
- [ ] selected duration 参与 forward-fit（C13）
- [ ] fixed-slot/capacity 无假时长（C14；用真实推荐 duration）
- [ ] route call budget 不失控（C10：96 上限 + 80 降级；7 日 worst ≤88）
- [ ] cache 被复用（C11）
- [ ] 普通规划能够实际产出 TRANSIT（C2/G1 smoke）
- [ ] Golden WALKING/TRANSIT/DRIVING 三类均成立（G1-G3）
- [ ] B18-B 调用序列无回归（C15/C16 + B1-B9 原样通过）
- [ ] B19-B targeted 51 项无回归；B17 None-omit 无回归
- [ ] 不引入 ROAD/TAXI/PUBLIC_TRANSIT breaking change（scope 审计）
- [ ] 不修改 UI 语义（Web 0 修改）
- [ ] 不升级 event version（v11 足够）、无 DB migration、Java 0 生产修改
- [ ] 不做 manual edit real transit（登记 B19-D）
- [ ] 不做 feasibility mode override（v1 固定，登记 future）
- [ ] 全量回归：Python full pytest + ruff + Java mvn + Web vitest/typecheck

---

## 26. Recommended Execution Order

```
Phase 1  Golden collection（真实 AMAP 广州 ~10 对 OD，节制 ≤30 calls；人工判定 expected mode，先于代码）
Phase 2  RED fixtures（C1-C16 依据预批准的 Golden expectations 先写；C1/C15/C16 记 baseline GREEN）
Phase 3  Threshold calibration（扫描 R/N/W 网格 → 求 expected-match 最大化 → 边界人工复核 → 写常量）
Phase 4  实现（mode_recommendation.py + _route_for_pair staged 分支 + city 透传 + budget 降级 + trace）
Phase 5  timing 集成验证（C13/C14：forward-fit/fixed-slot/capacity 使用真实推荐 duration）
Phase 6  API budget 验证（calls 计数 / 降级行为 / cache 命中；2/3/5/7 日 smoke 测量）
Phase 7  真实 smoke（2-3 日广州规划：mode distribution 观测、avg calls/leg、无 RATE_LIMITED 暴力重试）
Phase 8  全量回归（Python targeted/full + ruff + contract + Java + Web）
Phase 9  Execution Report（docs/execution/B19/execution-report-c.md）
```

**RED-first 说明**：Phase 2 的 RED 测试基于 Phase 1 预批准的 Golden 期望（expected mode 已知）——校准常量（Phase 3）在 RED 绿灯之前不写死，实现（Phase 4）只填充规则框架，保证"先定预期、再定阈值、后写代码"的严格顺序。

每个 Phase 完成后停留确认；B19-C 不自动进入 B19-D。

---

## 附：关键决策速览

| 决策点 | 结论 |
| --- | --- |
| 推荐层 | **Python planner**（`_route_for_pair` 单一出口；B17/B18 timing 已建立在真实 duration 之上） |
| 算法 | **Ordered rules（Option A）**，不用 weighted score |
| walking 短路 | 保持 ≤1200s → WALKING（road 更快不翻转；非 fastest wins） |
| TRANSIT vs DRIVING 比较字段 | duration 比（R）+ transfer_count（N）+ walking_distance（W）；**不比较 cost** |
| DRIVING cost | 过路费语义（市区常 0/None），**不参与 v1 比较**；transit cost 仅 trace |
| mobilityLevel | 参与（仅 REDUCED/STEP_FREE 收紧 W/N 容忍）；pace/weather/luggage/偏好不参与 v1 |
| reason | 结构化 enum（ModeRecommendation.reason），logging/trace 层，不持久化 |
| feasibility override | **v1 不做**（mode 固定；登记 future bounded override） |
| TRANSIT failure | 可恢复 → 视为不可用 → DRIVING；非可恢复 → raise（不吞） |
| DRIVING failure | 可恢复 → TRANSIT（ROAD_UNAVAILABLE）；双失败 → 既有 provider policy |
| worst-case route calls | 7 日 35 legs 全 3-call = 105 → budget 降级后 ≤88 |
| MAX_ROUTE_CALLS_PER_PLAN | **保持 96**；新增 `BUDGET_DEGRADE_THRESHOLD=80`（初值） |
| 阈值校准 | Golden 数据扫描网格（R/N/W），不采用 Web AUTO 1.6 |
| D1 | **NON_BLOCKING_FOLLOW_UP**（不影响 facts）；执行期可选补丁 |
| v12 | **NO**（v11 已够） |
| DB migration | **NO** |
| Java / Web 生产 | **NO / NO** |
| manual edit | 继续延期（B19-D 必做 follow-up） |
| replan | 不改（B19-B 已支持） |
| Golden | G1-G8（G1/G2/G3 为 B19-A 真实锚点） |
| RED | C1-C16（C1/C15/C16 baseline GREEN） |
