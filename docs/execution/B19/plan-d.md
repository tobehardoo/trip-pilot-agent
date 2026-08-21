# B19-D Road / Taxi / Self-driving Semantics Plan

- 计划日期：2026-08-20
- 基线：`docs/execution/B19/audit.md`、`plan-b.md`、`execution-report-b.md`、`acceptance-report-b.md`（B19-B **PASS_WITH_DEFECT**，`B19-B:D1` 未修）、`plan-c.md`、`execution-report-c.md`、`acceptance-report-c.md`（B19-C **PASS**，O1-O3 非缺陷）、`docs/execution/B18/execution-report-b.md` / `acceptance-report-b.md`（B18-A/B **PASS**）
- 分支 / HEAD：`codex/feasibility-foundation` @ `d10e70c`
- 工作区：~100 项在途修改（B15/B16/B17/B18-A/B18-B/B19-A/B19-B/B19-C 混合）保持原样；**本阶段未修改任何生产代码 / contract / DB / UI**；禁止 `git reset / restore / checkout . / stash / clean`
- 状态：**计划修订阶段，未开始实施**。三项 P0 语义门禁已写入；`B19-D0` 可独立进入 RED→GREEN。只有 D0 独立验收通过后才启动 `B19-D1` RED；manual `TAXI` 的目标状态与现有 DB constraint 冲突，须在 B19-D1 GREEN 前完成 §17.3 / §21 的门禁决策

---

## 1. Executive Summary

> B19-D 解决 TripPilot 交通系统最核心的领域语义债：**`DRIVING` 是 AMAP road-route 技术能力，却以"驾车"产品语义呈现给无车用户；`TAXI` 是前端/Java 本地估算，无 provider route；`TRANSIT` planner 真实而 manual edit 仍是 DEMO；Web 存在两套推荐引擎（Python B19-C staged ordered rules vs Web AUTO 估算）**。

**本计划的核心判断**：`DRIVING` 的技术语义是干净的（`AMAP v5/direction/driving`，`strategy=32`，`cost=toll_cost`），错误在于**把技术 route mode 直接当作产品交通意图**。修复的本质是**把"road route capability"与"user transport intent"分层**，但**第一版必须以最小非 breaking 变更收口**。

**推荐策略**：**Strategy A1 — Minimal semantic patch**（保留 provider `DRIVING`，不新增 `ROAD`/`SELF_DRIVING` enum，不新增 `roadIntent`/DB column，不升 event 版本）。在没有持久化 road intent 之前，**所有 persisted `DRIVING` 在所有用户通道统一显示为“打车”**，本批不提供可持久化“自驾”选择；manual `TRANSIT`/`TAXI` 复用真实 provider route（Java→Python 同步 API），manual `TAXI` 因 fare/wait 为本地估算而以 coarse-grained `estimated=true` 呈现；Web `AUTO` 后端化，Python B19-C recommendation 是唯一 authority，Web 本地 `1.6` 算法退出 decision 与 preview。`B19-B:D1` polyline defect 作为 `B19-D0` 独立小修先行，不与 `B19-D1` 语义改造混合。

一句话：**技术层保持 `DRIVING`，所有 persisted `DRIVING` 的用户语义统一为“打车”，真实 route 统一来自 AMAP driving/transit，TAXI 的费用/等待使整条 leg 保守标记为 estimated，AUTO 只服从 Python B19-C，首版不做 enum/event/column breaking migration。**

### 1.1 P0 Semantic Gates（本次修订）

| Gate | 决定 | RED 锁定 |
| --- | --- | --- |
| **P0-1 persisted DRIVING** | 无 `roadIntent` 时，不依据 planner/manual/request source 区分展示；`DRIVING` 在 read/reload/share/export/PDF 一律为“打车”。“自驾”不作为 D-min 可持久化用户模式提供 | `D17` |
| **P0-2 mixed provenance** | Python `RoutePlan` 仍返回真实 `DRIVING: AMAP/false`；Java 合成 manual `TAXI` 后，DB core 为 `mode=TAXI/provider=AMAP/estimated=true/duration=road+300s/estimated_cost=<rule fare>`，响应稳定派生 `route_duration_seconds`、`cost_source=RULE_ESTIMATE`、`wait_seconds=300` | `D18`；现有 `ck_transit_leg_provider_estimate` 阻止 `AMAP/true`，见 §17.3 / §21 |
| **P0-3 AUTO authority** | Python B19-C recommendation 是唯一 authority；Web `transit≤taxi×1.6` 从 decision、optimistic recommendation、offline fallback 与 preview 全部退出 | `D19` |

---

## 2. Verified Baseline

### 2.1 B19-B / B19-C 验收结论（必须确认）

| 批次 | 验收结论 | 含义 |
| --- | --- | --- |
| B19-B | **PASS_WITH_DEFECT** | 真实 AMAP `v3/direction/transit/integrated` + `v11`/`v2` 全链路建立；旧 `v10`/`v1` 未放宽；唯一非阻塞缺陷 **`B19-B:D1`**：`polyline` 全缺/单段缺失时 fail-closed `PROVIDER_SCHEMA_CHANGED`，未实现 plan-b §4.4“跳段+2点退化” |
| B19-C | **PASS** | 基于真实 `WALKING`/`TRANSIT`/`DRIVING` facts 的 staged ordered-rule 推荐（`R=1.2/N=2/W=1500`，9 案例 100% 校准）；walking 短路优先（非 fastest wins）；不比较 `cost`；动态 remaining-leg budget；无 feasibility override；contract `v11`/`v2` 不变；仅 3 项非缺陷观察 `O1-O3` |

### 2.2 `B19-B:D1` 与 B19-C O1-O3（本阶段输入）

- **`B19-B:D1`**：`_amap_transit.py:201-260` 对每 segment 无条件构造 `RouteStep(polyline=min_length=1)` → 空几何触发 `ValidationError` → `PROVIDER_SCHEMA_CHANGED`；需求是“跳段+全缺退化 2 点”（`origin→destination`）。真实数据从未触发（G1+fixtures 均带 polyline），facts 不受影响，fail-closed 安全。**处置见 §26。**
- **O1**：live `driving` 时长波动可翻转 `G1`/`G8` 的 `TRANSIT↔DRIVING`（B19-A 快照 1632s vs live 931-986s）→ facts 驱动预期行为，非缺陷。
- **O2**：walking 短路日志 `budget_degraded=false`（小写）vs stage-2 `False`（大写）→ 纯文案不一致。
- **O3**：`accessible_burdens` docstring 提 `STEP_FREE` 但调用方仅 `mobility_level=="REDUCED"` 生效 → 文档措辞。

### 2.3 工作区（本阶段开始时）

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `d10e70cf354d096300c4a348d6aef585b8d82dc8` |
| dirty | ~100 项（含 B15/B16/B17/B18-A/B18-B/B19-A/B19-B/B19-C 历史在途 + plan 增量）；已记录 `git branch --show-current` / `git rev-parse HEAD` / `git status --short` / `git diff --stat`（74-102 files，4364+ 插入）；未执行任何 `git reset / restore / checkout . / stash / clean` |
| B19-B/C 可识别增量 | `mode_recommendation.py`（新）、`planning_provider.py` 增量、`_amap_transit.py` 带 `cost` 解析、`_route_contracts.py`（`TRANSIT`+city 字段）、`processor.py` 切 `v11`/`v2`、Java parser `v11`/`v2` 分支、`transitModeRecommendation` 等 |

---

## 3. Current Mode Matrix

以真实代码为准（非猜测；不存在的值写 `N/A`）。

| Layer | WALKING | TRANSIT | DRIVING | TAXI | ROAD | SELF_DRIVING |
| --- | --- | --- | --- | --- | --- | --- |
| Python `RouteMode`（`_route_contracts.py:16`） | ✅ | ✅ | ✅ | N/A | N/A | N/A |
| Python `ItineraryTransitMode`（`worker/contracts.py:659`） | ✅ | ✅ | ✅ | ✅ | N/A | N/A |
| Provider request（`AmapRouteProvider`/`AmapTransitProvider`） | ✅ `v5/direction/walking` | ✅ `v3/direction/transit/integrated`（`city` 必填，`strategy=0`，`date/time` 来自 `departure_at`） | ✅ `v5/direction/driving`（`strategy=32`，`show_fields=cost,navi,polyline`） | N/A（无 provider） | N/A | N/A |
| `RoutePlan`（`_route_contracts.py:56`） | ✅ `mode=WALKING` | ✅ `mode=TRANSIT` + `walking_distance_meters`/`transfer_count` | ✅ `mode=DRIVING` | N/A | N/A | N/A |
| `PlanningCompleted` event（`v11` schema + Java parser `v11`） | ✅ | ✅ | ✅ | ❌（`v11` `TAXI` REJECT，schema+Java 双路径；见 acceptance-report-b §9 matrix） | N/A | N/A |
| Review event（`v2`） | ✅ | ✅ | ✅ | ❌（`v2` `TAXI` REJECT） | N/A | N/A |
| Java parser（`PlanningCompletedEventParser.java:329`） | ✅ | ✅（`v11` 分支） | ✅ | ❌（所有版本 `TAXI` REJECT） | N/A | N/A |
| Java domain（`ItineraryService.java:425` 白名单） | ✅ | ✅ | ✅ | ✅（`List.of("WALKING","TRANSIT","DRIVING","TAXI")`） | N/A | N/A |
| DB `CHECK`（`V23`） | ✅ | ✅ | ✅ | ✅ | N/A | N/A |
| REST DTO（`toTransitLegResponse` 透传） | ✅ | ✅ | ✅ | ✅（透传 `mode`） | N/A | N/A |
| Web TS union（`transit.ts:3` `ConcreteCommuteMode`） | ✅ | ✅ | ✅ | ✅ | N/A | N/A |
| Web AUTO（`transit.ts:65-76`） | ✅ `walk≤20min→WALKING` | ✅ `transit≤taxi×1.6→TRANSIT` | ✅ fallback | ✅ `taxi→TAXI` | N/A | N/A |
| Manual edit（`ItineraryService.applyTransitLegEdit:583` + `transit.ts:58`） | ✅ 本地估算 `DEMO`/`polyline=[]`/`estimated=true` | ✅ 本地估算 `DEMO`（`dist/5.5+420s` / `cost=2+⌊km/6⌋`） | ✅ 本地估算 `DEMO`（`dist/8.33+180s` / `cost=max(3, km×0.8)`） | ✅ 本地估算 `DEMO`（`dist/8.33+300s` / `cost=12+km×2.6`） | N/A | N/A |
| Replan（`replan_service.py:262`） | ✅ | ✅（`city=trip.destination` 同城） | ✅ | N/A（无 provider，不可 replan 为 `TAXI`） | N/A | N/A |
| Share（`SharedItineraryPage.vue:95`） | ✅ `{{ leg.mode }}` 原样 | ✅ | ✅ | ✅ | N/A | N/A |
| Export | ✅ `ItineraryExportService.java:77` `Transit {mode}` | ✅ | ✅ | ✅ | N/A | N/A |
| PDF | ✅ `TripDocumentService` 透传 | ✅ | ✅ | ✅ | N/A | N/A |
| ICS | N/A（`TripIcsService` 仅活动，不含 leg mode） | N/A | N/A | N/A | N/A | N/A |
| Evaluation（`evaluation/scoring.py:12` `routeEfficiency` 权重 15%） | ✅ | ✅ | ✅ | N/A（无分支） | N/A | N/A |

**关键不一致（B19-D 必须处理）**：
- `RouteMode`（provider 契约，3 值）≠ `ItineraryTransitMode`（产品契约，4 值含 `TAXI`）；`event v11` 仅 3 值（`TAXI` 被排除，因无真实 producer）。
- `TAXI` 全链路"持久化可、provider 无"：DB/Java/Web 可存 `TAXI`，但 Python 无路可产、event 不允许、replan 不支持。

---

## 4. DRIVING Technical Semantics

基于 `_amap_route.py:38-39,73,180-228` + `_route_contracts.py:16` 精读。

| 项 | 值 | 证据 |
| --- | --- | --- |
| 类型 | **Provider RouteMode**（`RouteMode` 三值之一） | `_route_contracts.py:16` `Literal["WALKING","DRIVING","TRANSIT"]` |
| Endpoint | `GET https://restapi.amap.com/v5/direction/driving`（与 `WALKING` 共用 `AmapRouteProvider`） | `_amap_route.py:39,80` |
| 额外参数 | `strategy=32`（第一版固定）、`show_fields=cost,navi,polyline`；`isindoor=0` 仅 `WALKING` | `_amap_route.py:180-191` |
| `duration` | `path.cost.duration`（秒，**道路行驶时长**，不含等待/停车/步行接驳） | `_amap_route.py:224` `duration_seconds=int(path.cost.duration)` |
| `distance` | `path.distance`（米，**道路总距离**，非 haversine） | `_amap_route.py:222` |
| `polyline` | 各 `step.polyline` 按序拼接、相邻重复端点去重 | `_amap_route.py:209-213` |
| `cost` | **`toll_cost`（过路费）**；`WALKING` 固定 `0.0`；`DRIVING` 缺失→`None`（市区常 `0`/`None`） | `_amap_route.py:214-220` `path.cost.toll_cost` |
| `provider` | `AMAP`（成功时）/`DEMO`（fallback）；`estimated=false` ↔ `AMAP`，`true` ↔ `DEMO` | `contracts.py:687-692` `validate_provider_estimate`；`_amap_route.py:148-149` |
| `estimated` | `false`（真实 provider route） | 同上 |
| 时间语义 | `departure_at` 为 `origin["end"]`（forward-fit 后真实离开时刻）；精度小时 bucket（`departure_hour`） | `_amap_route.py:259-263` `departure_hour isoformat` |
| Cache key | `map:route:v1:{sha256(origin/destination/poi×2/mode/departure_hour/provider/data_version)}` | `_amap_route.py:258-278` |
| budget | 经 `_route_cached` 统一计数 `MAX_ROUTE_CALLS_PER_PLAN=96` | `domain/shared.py:41` |

**特别确认**：`DRIVING cost` 是 **`toll_cost`（过路费）**，不是 `taxi fare` / `fuel cost` / `total trip cost`。市区 `DRIVING` 常 `0` 元过路费与 `TRANSIT` 票价 `¥2-9` **不可比**（`plan-c §7` 已禁 `cost` 比较，本计划延续）。

---

## 5. TAXI Current Semantics

全仓精读追踪（Python/Java/Web/DB/event）。

### 5.1 TAXI 是否有 provider route？

**无。** `AmapRouteProvider.get_route` 对 `mode=="TRANSIT"` 已显式 `PROVIDER_UNSUPPORTED_MODE`；对 `TAXI` 无任何分支（`_amap_route.py:59-65` 仅拦截 `TRANSIT`，`TAXI` 走不到 `driving` 也走不到 `walking`，在 `_route_contracts.RouteMode` 层即被 `Literal` 拒绝）。`AmapTransitProvider` 同理只支持 `TRANSIT`。全仓无 `TAXI` endpoint。

### 5.2 TAXI 当前完整路径（谁产生/消费/持久化/估算）

| 环节 | 行为 | 证据 |
| --- | --- | --- |
| **产生** | 仅 **manual edit**（用户点击 `TAXI` 按钮）→ 前端 `emit('select', mode)` → `POST /api/trips/{id}/itinerary/edits/commit`；**planner 从未产生 `TAXI`**（`_route_for_pair` 无 `TAXI` 分支，`mode_recommendation` 无 `TAXI`） | `TransitLegControl.vue:66-70,169`；`planning_provider.py` 无 `TAXI` |
| **持久化** | `ItineraryService.applyTransitLegEdit:597-626` 写入新 `transit_leg` 版本（`versionSource=USER_EDIT`，`mode='TAXI'`，`DB CHECK` 已含 `TAXI`） | `V23__complete_transit_leg_writeback.sql:5-8`；`ItineraryService` |
| **duration 估算** | `distance/8.33 + 300s`（`8.33 m/s≈30 km/h` + 5 分钟等待） | `ItineraryService.java:605-614` |
| **cost 估算** | `12 + km×2.6`（起步价 12，里程 2.6/km；广州出租车基价，无城市化；`roundMoney`） | `ItineraryService.java:616-626`；`transit.ts:59` 同公式 `+120s` 等待（两套公式并存，值不一致：Java +300s vs 前端 +120s） |
| **`provider/estimated/polyline/providerRouteId`** | `provider="DEMO"`、`estimated=true`、`polyline=[]`（清空）、`providerRouteId=null` | `ItineraryService.java:597-602` |
| **AUTO 选择 TAXI** | `transit.ts:71-75`：`walk≤20min→WALKING`；`transit≤taxi×1.6→TRANSIT`；否则 `TAXI` | `transit.ts:65-76` |
| **event** | `v10`/`v11`/`v1`/`v2` 均 **REJECT** `TAXI`（schema enum + Java parser `validateTransitLegTypes` 版本化 enum） | `acceptance-report-b §9` matrix；`PlanningCompletedEventParser.java:329` |

### 5.3 结论

`TAXI` 是**基于 road geometry 的本地估算意图**，当前无 provider 事实、无 polyline、无真实 duration/distance，仅"相同 OD 距离 + 速度/等待/起步价公式"。

---

## 6. Manual Edit Current Flow

当前 manual edit 为**同步 HTTP** `POST /api/trips/{id}/itinerary/edits/commit` → `ItineraryService.applyTransitLegEdit` → **内存估算**创建新 `itinerary version`（不可变版本，原子写入；幂等经 `EditRequestFingerprint`/`idempotencyKey` 去重，但 provider 调用不在幂等内）。

> 下列"距离"指 `leg.distanceMeters`（沿用原 leg 距离，非重算 provider 距离）；`cost` 为前端/Java 两套估算并存，以 Java 持久化为准。

### manual WALKING

```
用户点击 WALKING（TransitLegControl → emit SELECT → TripDetail → commit）
→ Java applyTransitLegEdit(WALKING)
  → duration = distance/1.25（1.25 m/s）
  → cost = 0
  → polyline = []（清空）
  → provider = DEMO（若原 leg 为 AMAP 则降级为 DEMO）
  → estimated = true
  → providerRouteId = null
  → 新 itinerary version（不可变）
```

### manual TRANSIT

```
用户点击 TRANSIT
→ 同上 → Java 估算：
  → duration = distance/5.5 + 420s（5.5 m/s + 7 min 等待/换乘缓冲）
  → cost = 2 + floor(km/6)（每 6km +1，基价 2；非 AMAP transit.cost）
  → polyline = []（清空）
  → provider = DEMO
  → estimated = true
  → 新 version
【与 planner-generated TRANSIT 的 gap】planner=AMAP 真实 (duration/distance/cost/39点polyline/estimated=false) vs manual=DEMO 估算 (polyline 为空)。
```

### manual DRIVING

```
用户点击 DRIVING
→ Java：
  → duration = distance/8.33 + 180s
  → cost = max(3, km×0.8)（过路费语义的本地估算，非 AMAP toll_cost）
  → polyline = []
  → provider = DEMO
  → estimated = true
  → 新 version
【与 provider DRIVING 的 gap】planner/真实 DRIVING=AMAP road route (strategy=32, 真实 duration/distance/polyline/toll_cost) vs manual=本地估算 + 空几何。
```

### manual TAXI

```
用户点击 TAXI
→ Java：
  → duration = distance/8.33 + 300s（比 DRIVING 多 120s）
  → cost = 12 + km×2.6（出租车计价，非 toll）
  → polyline = []
  → provider = DEMO
  → estimated = true
  → 新 version
【与 provider DRIVING 的 gap】TAXI 无独立 geometry；当前 TAXI 的 duration 仅比 DRIVING 慢 2-5 分钟，cost 模型不同，但 geometry 共享被清空而非复用。
```

**哪些是真实 provider facts，哪些是 local estimate**：当前 **全部 manual edit 四模式均为 local estimate**（`DEMO/true/[]`），无一条是 `AMAP/false` 真实 route；planner-generated `WALKING`/`TRANSIT`/`DRIVING` 为真实 `AMAP/false`。

---

## 7. Problem Statement

| # | 问题 | 证据 | 严重度 |
| --- | --- | --- | --- |
| P1 | **planner `DRIVING` 被展示为"驾车"，暗示用户有车** | `TransitLegControl.vue:98` `DRIVING:'驾车'`；`TripConstraints` 无 `hasCar`/`selfDriving`/`vehicleAccess`/`transportPreference`（`contracts.py:167-190` 全无；`mobility_level`/`pace` 不表达车辆） | 高 |
| P2 | **"驾车"与"打车"同时存在但底层是同一 road route** | `audit.md §6` `DRIVING` 为 `v5/driving` road geometry；`TAXI` 为同一距离的速度/费用改算（`8.33 m/s` + 等待），polyline 本被清空而非复用 | 高 |
| P3 | **无车用户也会收到 `DRIVING`** | `docs/execution/B18/execution-report-b.md` 34/34 `DRIVING` 含「正佳→小林蓝鳄 1m/DRIVING」；B19-C 前 planner 无 `TRANSIT` 比较，后仅 staged 推荐在 road 更快时仍 `DRIVING` | 高 |
| P4 | **manual edit `TRANSIT` 仍是 DEMO** | §6 流程；`applyTransitLegEdit` polyline 清空；planner 真实 vs 手动估算严重不一致 | 高（B19-C 后严重度上升，因用户更常见真实 transit） |
| P5 | **两套 recommendation 引擎** | Python B19-C `mode_recommendation.py`（staged/ordered rules/R=1.2/N=2/W=1500/budget 保留）vs Web `transit.ts:65-76`（`walk≤20min/ transit≤taxi×1.6` 估算） | 中（算法漂移） |
| P6 | **费用语义混淆** | `DRIVING cost=toll_cost`（市区常 0）vs `TAXI cost=12+km×2.6` vs `TRANSIT cost=真实票价`；三者不可比却可能被 UI 并列为"费用" | 中 |
| P7 | **估算与真实 provenance 不区分** | `TransitLeg` 仅单一 `estimated`/`provider`；TAXI 的"road `AMAP` + fare `LOCAL_ESTIMATE`"无法表达 | 中 |
| P8 | **`B19-B:D1` polyline 边界** | 全缺/单段缺失 → `PROVIDER_SCHEMA_CHANGED`（§2.2） | 低（非阻塞，但暴露面随 TRANSIT 默认查询扩大） |

**一句话**：技术 `DRIVING` 与产品"打车/自驾"未分层；"真实 provider route"与"manual edit 本地估算"未对齐；两套推荐未收敛。

---

## 8. Architecture Options A/B/C

### Option A — 保留现有 DRIVING（Minimal semantic patch）

```
ProviderRouteMode:  WALKING / TRANSIT / DRIVING（不变）
TransitLeg.mode:    WALKING / TRANSIT / DRIVING / TAXI（不变，TAXI 仍为持久化意图）
新增:               无 enum / 无 DB column / 无 event 版本
planner:            B19-C 行为不变；任何 persisted DRIVING 的产品映射均为 TAXI（见 §11）
manual edit:        D-min 真实化 TRANSIT/TAXI；AUTO 选择结果使用真实 route；explicit WALKING 保持既有 local path，DRIVING 不作为 UI 入口
Web:                仅展示“步行/公交·地铁/打车”；无“自驾”入口；AUTO 只等待后端推荐
```

- 优点：enum/event/DB column 零 breaking；`v11`/`v2` 复用；历史 `DRIVING` 无需迁值；用户语义不依赖瞬时来源。
- 缺点：`DRIVING` 名称的技术/产品混用仍在代码层残留（仅展示层语义修复）；若未来需 `SELF_DRIVING`，需二次设计。

### Option B — DRIVING 重命名 ROAD（Full ROAD migration）

```
RouteMode:          WALKING / TRANSIT / ROAD（DRIVING 消失）
TransitLeg.mode:    WALKING / TRANSIT / TAXI / SELF_DRIVING（ROAD 消失，TAXI/SELF_DRIVING 为一等意图）
```

- 优点：模型最干净（`ROAD` = 道路几何，`TAXI`/`SELF_DRIVING` = 意图）。
- 风险：contract breaking（`v12`/`v13`）、DB `V??` migration（`CHECK` 重写 + 历史 `DRIVING` 回填）、Java/Web 全链路枚举重写、replan/edit/export/share/PDF/ICS/evaluation 全受影响、历史数据无法可靠归因（见 §28）、rollback 需双写。

### Option C — 保留 DRIVING 作为 provider mode，新增 intent 层（Add roadIntent）

```
ProviderRouteMode:  WALKING / TRANSIT / DRIVING（不变，provider 契约）
TransportIntent:    WALKING / TRANSIT / TAXI / SELF_DRIVING（新增意图层，复用 DRIVING geometry）
持久化候选:
  C1: mode=DRIVING + roadIntent=TAXI|SELF_DRIVING|NULL（兼容，旧数据 NULL）
  C2: mode=TAXI|SELF_DRIVING（新 mode 值，event v12 + DB CHECK 扩）
```

- 优点：`DRIVING` 几何与意图分离明确；`TAXI`/`SELF_DRIVING` 复用同一 `DRIVING` route 纹理与 cache；兼容期可双读。
- 代价：event/DB/Java/Web 需扩展一列（`road_intent`/`roadIntent`）；新增校验与 dual-read；仍需回答默认意图、历史兼容、provider/fare 分层（见 §17）。

**本计划重点评估 C 是否比 B 更低风险且更符合当前架构**：是。C 的 provider 层零改动（`DRIVING` 仍是 `AmapRouteProvider` 的合法 `RouteMode`），仅在产品/持久化层加意图；而 B 需改 provider contract 与所有上游调用点（`RouteRequest`/`RoutePlan`/`_route` 分流/`cache key`/`tests` 全量）。C 的迁移面比 B 小一个数量级（见 §9）。

---

## 9. Decision Matrix

| 方案 | 用户语义 | Provider复用 | Contract改动 | DB改动 | Java改动 | Web改动 | 历史兼容 | 风险 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A1 保留 DRIVING（本批）** | 所有 persisted `DRIVING` 统一展示为“打车”；`TAXI` 仍为可持久化 manual 意图；不提供“自驾”持久化选择 | `DRIVING`/`TRANSIT` 复用既有 provider，`TAXI` 仅在 Java 业务层复用 `DRIVING` geometry + 本地 fare/wait | **无**（`v11`/`v2` 保持 `WALKING/TRANSIT/DRIVING`；UI 映射不进 contract） | 目标为**无列/enum migration**；但 `AMAP/true` 与现有 provider-estimate constraint 冲突，必须先决策 | **manual TRANSIT/TAXI 真实化**（`applyTransitLegEdit` 后端化）+ `AUTO` 强制后端化 | 统一标签 + 删除本地 recommendation path | 历史 `DRIVING` 保持原值，所有读通道稳定显示“打车” | **低-中**；语义稳定，DB constraint 为硬门禁 |
| **B ROAD migration** | 模型最干净 | `ROAD` 取代 `DRIVING` 作为 provider mode（全链路改） | `v12`（`ROAD` 替代 `DRIVING`）+ `v13`（`TAXI`/`SELF_DRIVING`） | `CHECK` 重写（`DRIVING→ROAD`）+ 回填 + code 侧枚举全改 | parser `mode` 白名单重写 + domain + replan + edit + 导出/分享全分支 | `WALKING/TRANSIT/TAXI/SELF_DRIVING`（`ROAD` 不暴露） | 历史 `DRIVING` 需解释为 `ROAD`/`TAXI`/`SELF_DRIVING` 之一，无法可靠还原 | **高**；全链路 breaking |
| **C roadIntent（`mode=DRIVING` + `roadIntent`）** | 语义清晰（`TAXI`/`SELF_DRIVING` 显式） | 同 A（`TAXI`/`SELF_DRIVING` 均→`DRIVING` route） | `v12`（新增 `roadIntent` 可选字段）或 `v12` + `TAXI`/`SELF_DRIVING` mode 值 | `road_intent VARCHAR` 可空 + `CHECK` 扩展 + 历史回填 `NULL` | domain + parser + `applyTransitLegEdit` + `replan_service` 意图传递 + share/export/ PDF 分支 | `ConcreteCommuteMode` 加 `SELF_DRIVING`，`AUTO` 后端化 | 旧 `DRIVING` → `roadIntent=NULL`（未知意图）；需 `unknown` 展示分支 | **中**；双读 + 消费者先行 |

**manual edit 真实化策略矩阵（§58 要求）**

| 策略 | 一致性 | 复杂度 | 延迟 | 失败处理 | 幂等 | 版本原子性 |
| --- | --- | --- | --- | --- | --- | --- |
| **Java 直接 provider**（Java 再实现 AMAP `v3`/`v5`） | 中（双实现易漂移，`B19-B:D1`/校准/重试与 Python 不一致） | 高（Java 需 `city/strategy/date/time/nightflag` 全套 + transit 模型复刻） | 低（同步 HTTP） | 中（Java 侧映射 `ProviderErrorCategory`） | 中（需自建 key） | 高（同步，失败不产 version） |
| **Java→Python 同步 API（推荐）** | **高**（复用 Python `_amap_route`/`_amap_transit` 单一事实来源） | 低-中（新增 `POST /internal/routes` 内网 API；鉴权 `AGENT_INTERNAL_TOKEN`） | 中（1 次内网 + 1 次 provider；cache 命中快） | 高（复用 Python taxonomy + `FallbackDecision`） | 高（见 §19） | 高（provider 成功后才写 version） |
| **Java→AMQP 异步 route command** | 高（同 Java→Python，但异步） | 高（新 command/event + 状态机 + 轮询/SSE） | 高（用户需等待异步完成；UX 复杂） | 中（超时/重试/死信） | 高 | 中（需"pending version"或补偿） |
| **复用 local replan**（把 edit 转为 replan impactedDates） | 中（重用 `replan_service`，但 edit 的语义是"单 leg 意图"而非"整日重算"） | 中（需构造 `ReplanItinerarySnapshot` + `impactedDates`，且仅对 TRANSIT 生效，WALKING/DRIVING 仍 local） | 中 | 中 | 中 | 低（replan 会重算整日多 legs，可能改动非目标 leg） |

**结论**：`Java→Python 同步内网 API` 最优（一致性最高、复杂度最低、版本原子性最强；与既有"Python 单一 route 事实来源"架构一致，见 §23）。

**同步 vs 异步（§59）**：
- 同步：简单、版本原子、幂等可控；风险为 provider latency（`TRANSIT`/`DRIVING` P50 秒级，cache 命中毫秒级）。
- 异步：符合 planning 异步架构但 UX 复杂（用户点 `TRANSIT` 后需"加载中→完成/失败"两态），且需新 polling/SSE 通道。
- **本计划推荐同步**（内网 API，超时 6s + `Retry-After` 透传 + degradable：超时/可恢复失败则明确告知"暂不可用，保留原 leg"而不产半版本）。

---

## 10. Recommended Domain Model

**推荐：Option A1 模型（本批），Option C 的 `roadIntent` 作为预留但不实现。**

```
# 本批（A）
ProviderRouteMode（RouteMode）:      WALKING / TRANSIT / DRIVING   ← 保持，provider 契约
ItineraryTransitMode（持久化）:       WALKING / TRANSIT / DRIVING / TAXI  ← 保持（TAXI 仅 manual edit 可达）
Event v11/v2 mode enum:             WALKING / TRANSIT / DRIVING  ← 保持（planner 不产 TAXI）
User-facing（所有读通道）:           步行 / 公交·地铁 / 打车
  - any persisted DRIVING           → 展示为“打车”（不检查来源，见 §11）
  - manual TAXI                     → 展示为“打车”
  - SELF_DRIVING / 自驾             → 本批不提供、不持久化
```

- **`RouteFacts` vs `TransportEstimate` 预留分层（§50，不新增字段，仅文档约定）**：
  - `RouteFacts`（provider）：`duration`/`distance`/`polyline`/`provider` 来自 `RoutePlan`（Python route response 为 `AMAP`/`false`）。
  - `TransportEstimate`（本地）：`taxi fare`（`12+km×2.6`）、`taxi wait`（D-min 统一 300s）、`transit fare`（`AMAP transit.cost`）、`driving toll`（`AMAP toll_cost`）。
  - 当前 `TransitLeg` 单一 `estimated`/`provider`/`estimated_cost` 无法细分“road 真实 + fare 估算”（见 §17）；D-min 采用保守聚合：只要关键用户可见字段含本地估算，合成后的 `TAXI` leg 就标记 `estimated=true`，同时保留 `provider=AMAP` 与派生/响应级 `cost_source=RULE_ESTIMATE`。

- **`ROAD`/`SELF_DRIVING` 预留**：不在 provider 契约引入 `ROAD`；`SELF_DRIVING` 与“自驾”入口均不在本批提供。只有未来引入可持久化 `roadIntent`（及必要的 `vehicleAccess`）后，才允许把 road route 展示为“自驾”（见 §12/§13）。

---

## 11. Default Road Intent Decision

**最终答案（§62 要求，一句明确）**：

> **在没有持久化 `roadIntent` 之前，所有 persisted `DRIVING` 在产品层一律解释为 `TAXI`（打车）；该规则不依赖记录来源或当前请求上下文。**

| 项 | 决定 |
| --- | --- |
| 统一映射 | persisted `DRIVING`（provider road）→ Web/read/reload/share/export/PDF **“打车”** |
| 例外 | **无。** planner 产出、历史记录、legacy client 显式提交 `DRIVING` 都不能推导“自驾”；request source 不进入持久化语义 |
| 用户选择 | D-min 不展示“驾车/自驾”按钮；manual `TAXI` 继续持久化为 `mode=TAXI`，技术 `/internal/routes` 请求仍使用 `mode=DRIVING` |
| 理由 | 国内单城市自由行默认交通为步行/公交/打车；"驾车"暗示有车/自驾，与多数用户事实不符；`B19-C` 的 `DRIVING` 本质是"road transport"，费用为过路费而非打车费，打车解释更贴合自由行默认语义（见 `audit.md §6`） |
| 费用边界 | persisted `DRIVING.cost` 是 AMAP `toll_cost`，绝不标成 taxi fare；Web/Share/PDF 一律隐藏该费用，Export JSON 仅以 `costMeaning=ROAD_TOLL` 保留 raw 值。只有 persisted `TAXI` 展示 `12+km×2.6` 的打车费用估算 |

**planner-generated DRIVING 的最终展示（§38 三方案，推荐第 3 种的退化版）**：
1. 直接显示“驾车” — 仅当有持久化车辆/意图依据时合理，本批禁止。
2. 统一显示“打车” — **本批采用**（所有 persisted `DRIVING` 与 `TAXI` 的用户标签均为“打车”）。
3. 根据 `roadIntent` 显示"打车/自驾" — **DEFER**（需 `roadIntent` 字段，见 §31）。

---

## 12. SELF_DRIVING Decision

**最终：`DEFER`**

- 原因：`SELF_DRIVING` 需要 `vehicleAccess`/`parking`/`toll`/`fuel`/`rental` 等配套能力与费用语义（市区过路费常 0，自驾成本不止 toll）；当前无任何用户车辆约束字段，且"打车"已覆盖 80% 自由行 road 语义。
- 触发条件：当用户明确需要“自驾”时，以 `B19-D2` 同批引入**持久化** `roadIntent`（以及必要的 `vehicleAccess=OWN_CAR|RENTAL`）；不得再次用瞬时 request source 推断标签。

---

## 13. User Constraint Decision

**最终：`NO`（本批不新增交通/车辆约束）**

- 审计：`TripConstraints`（`contracts.py:167-190`）现有：`mobility_level`、`pace`、`preferences`、`fixed_schedules`、`arrival/departure/accommodation`、`must_visit_places`/`avoid_places`/`meal_windows`；**无** `transportPreference`/`hasCar`/`selfDriving`/`rentalCar`/`preferTransit`/`avoidTaxi`/`vehicleAccess`。
- 决定：B19-D 不新增 `roadPreference: AUTO|TAXI|SELF_DRIVING`、不新增 `vehicleAccess: NONE|OWN_CAR|RENTAL`、不新增 `transportPreference`；`mobility_level` 已在 `mode_recommendation.accessible_burdens` 复用，无需再扩。
- 最小预留：若后续引入 `SELF_DRIVING`，新增 **单字段** `roadIntent: TAXI|SELF_DRIVING|None`（或 `vehicleAccess` 二值 `hasCar: bool`）即可，不一次造多字段。

---

## 14. Manual TRANSIT Realization

**最终：`YES`（本批真实化；见 §6 P4 高严重度）**

| 项 | 设计 |
| --- | --- |
| 触发 | 用户在 `TransitLegControl` 点击 `TRANSIT`（或 `AUTO` 解析为 `TRANSIT`，见 §16）→ `TripDetail` → `POST /api/trips/{id}/itinerary/edits/commit`（`ItineraryTransitEditRequestV2`，`requestedMode=TRANSIT`） |
| 新路径 | **Java 调用 Python 内网同步 API** `POST /internal/routes`（`RouteRequest`：`mode=TRANSIT` + `city=trip.destination` + `origin/destination` 来自 leg 端点 POI 坐标 + `departure_at` 来自 `origin.end_time`）→ 复用 `AmapTransitProvider`（`_amap_transit.py` 带 `_to_plan`/`cache`/`budget`）→ 返回 `RoutePlan`（`mode=TRANSIT/provider=AMAP/estimated=false/含 walking_distance/transfer_count`）→ Java 构造新 `transit_leg` 版本；`B19-B:D1` 在 D0 修复后，单段缺 geometry 会跳过、全缺会退化为 OD 两点，不再仅因 geometry 全缺返回 `PROVIDER_SCHEMA_CHANGED` |
| 复用原则 | **不复制 AMAP Transit 到 Java**（§23）；**复用 Python route capability**（`_amap_transit.py` 为单一事实来源）；**复用既有 route budget/cache**（`MAX_ROUTE_CALLS_PER_PLAN=96` 不适用于 edit，edit 侧 `per-edit route budget=1`，见 §29） |
| 不可变版本/原子性 | provider 成功 → 写入新 `itinerary_version`（`versionSource=USER_EDIT`，`EDIT` 事务内）；provider 失败 → **不产生半版本**（回滚 + 明确错误透传至前端，保留原 leg） |
| 幂等 | `EditRequestFingerprint` 唯一定义为 `tripId + fromActivityId + toActivityId + requestedMode + departureBucket(15min)`（不用随版本变化的 `legId`）→ 同指纹重放复用同一 version/result，不重复烧 provider quota；provider 层 cache（`map:transit:v1:` TTL 3600s）为第二层保护 |
| 估算一致性 | 前端不显示本地推导的推荐 mode/duration/cost；提交后仅显示 loading shell 与当前 persisted leg，provider 响应后再替换；**不与 Java 估算双写持久化** |
| 成功标准 | `polyline` 非空 + `provider=AMAP/estimated=false` + `transfer_count`/`walking_distance` 可溯源 |

---

## 15. Manual TAXI Realization

**最终：`YES`（本批真实化；与 TRANSIT 同批）**

| 项 | 设计 |
| --- | --- |
| 语义 | `TAXI` = **road route facts（来自 `DRIVING` provider）+ taxi fare/wait 本地估算**（`§41` 判断：不需要独立 taxi provider） |
| 触发 | 用户点击 `TAXI` → Java 内网 `POST /internal/routes`（`RouteRequest`：`mode=DRIVING`，`city` 可选忽略，`origin/destination` 同 TRANSIT）→ 复用 `AmapRouteProvider.driving_endpoint`（`strategy=32`）→ `RoutePlan`（`mode=DRIVING/provider=AMAP/estimated=false`） |
| 持久化/响应 | Python `DRIVING RoutePlan` 提供真实 `road_duration/distance/polyline/provider=AMAP/estimated=false`；Java 持久化 `mode=TAXI/provider=AMAP/estimated=true/duration_seconds=road_duration+300/estimated_cost=12+km×2.6`。response/share/export DTO 稳定派生 `route_duration_seconds=duration_seconds-300`、`wait_seconds=300`、`cost_source=RULE_ESTIMATE`。总 duration 进入日程/冲突判断，避免 wait 成为装饰字段 |
| Cache 复用 | `TAXI` 与 `SELF_DRIVING`（未来）共用 **同一 `DRIVING` route cache**（`map:route:v1:DRIVING`，`§49`），同 `OD+mode=DRIVING` 不重复计费 |
| 估算规则 | fare 固定 `12+km×2.6`，wait 固定 `300s`（取现有 Java 规则为唯一 authority）；**已知限制**：城市起步价/里程价/候车波动未城市化，首版文案“费用/候车估算·不含动态加价”覆盖，二版再做 city-aware estimator |
| 与 persisted DRIVING 关系 | `DRIVING` 仅保留为 provider/event/legacy persisted 技术值，用户层仍显示“打车”；D-min 不提供显式“自驾”选择。manual `TAXI` 才承载本地 fare/wait 估算，并通过 `/internal/routes mode=DRIVING` 取得 geometry |

---

## 16. AUTO Convergence

### 16.1 当前 Web AUTO 审计

```
estimateCommuteOptions(leg) → 4 估算（WALKING/ TRANSIT/ DRIVING/ TAXI，速度/等待/费用公式）
recommendedCommuteMode(options):
  walk ≤20min → WALKING
  transit ≤ taxi×1.6 → TRANSIT
  else → TAXI → DRIVING
```
- 全部为**前端本地估算**（无 provider），与 Python B19-C 的"真实 `WALKING` + `TRANSIT vs DRIVING` ordered rules/R=1.2/N=2/W=1500"**必然漂移**（`audit.md §7` / `plan-c §7` 均确认不可比：`DRIVING toll` vs `TAXI fare` vs `TRANSIT fare`）。

### 16.2 决策

**最终：`BACKENDIZE`（AUTO 后端化；`AUTO` 保留为用户编辑时的 convenience entry，但推荐计算移至后端 Python）**

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| KEEP（保留 Web 估算） | ❌ | 两套推荐引擎长期漂移：`Python: TRANSIT` vs `Web: TAXI` |
| BACKENDIZE | ✅ **推荐** | `用户点击 AUTO` → Java 内网 `POST /internal/routes/recommend`（复用 `mode_recommendation.decide_transit_or_road` + 真实 `TRANSIT`/`DRIVING` 查询 + `can_probe_transit` 预算检查 + `accessible_burdens`）→ 返回 `ConcreteCommuteMode` + `RoutePlan` → 走 §14/§15 的真实 route 写入；`AUTO` 按钮变为"后端推荐"的快捷入口，无本地计算 |
| REMOVE（删除 AUTO） | ❌ | `AUTO` 作为"一键推荐"仍有产品价值，且 `planner` 的 `WALKING` 短路优先（非 fastest wins）语义值得在编辑时复用 |

- **唯一 authority**：Python B19-C recommendation 是 AUTO 的唯一模式决策源。`recommendedCommuteMode()` 删除，或保留为 deprecated export 但不得被任何运行时 decision/preview/fallback path 引用；Web `transit≤taxi×1.6` 不再向用户展示推荐结果。
- **前端等待态**：只允许 loading、optimistic shell 与当前 persisted mode；不得在后端响应前猜测 `WALKING/TRANSIT/DRIVING/TAXI`。
- **同步/异步**：同 §14（同步内网 API；latency 同真实 provider，cache 命中快）。
- **事实闭环**：`/internal/routes/recommend` 必须先取得真实 `WALKING` facts 并执行 B19-C walking short-circuit；未短路时再取得 `DRIVING`，并在 `can_probe_transit` 允许时取得 `TRANSIT`。不得假设 Web 已预计算 walking facts。
- **API 预算**：`AUTO` per-edit budget 最大 3 calls（`WALKING + DRIVING + TRANSIT`）；walking 短路时 1 call，`budget_degraded` 时跳过 `TRANSIT` 为 2 calls。不与 `MAX_ROUTE_CALLS_PER_PLAN=96` 共享（planning 侧 96 为 per-plan，该侧为 per-edit，见 §29）。
- **幂等/版本**：同 §14（指纹 + 原子版本 + 失败不产 version）。

---

## 17. Route Facts / Estimate Provenance

### 17.1 分层

```
RouteFacts（provider，真实）:
  route_duration_seconds ← AMAP route/transit duration（单一路线的真实值）
  distance_meters   ← AMAP distance（非 haversine）
  polyline          ← AMAP polyline（walking: steps；transit: segments→per-line；driving: path.steps）
  provider          ← "AMAP" | "DEMO"

TransportEstimate（本地，估算）:
  fare              ← TAXI: 12+km×2.6；TRANSIT: AMAP transit.cost；DRIVING: AMAP toll_cost / 本地  max(3, km×0.8)
  wait_time         ← TAXI: 300s；TRANSIT: walking_duration 已含步行接驳
  total_duration    ← TAXI: route_duration + wait_time（持久化为 TransitLeg.duration_seconds）
  parking/fuel      ← DEFER（自驾未引入）
```

- `TAXI`：`road RouteFacts (AMAP)` + `taxi fare/wait (LOCAL_ESTIMATE)`
- `SELF_DRIVING`（future）：`road RouteFacts` + `toll/fuel/parking (LOCAL_ESTIMATE)`

### 17.2 是否值得本批拆字段？

**不拆**（`TransitLeg.estimated` 保持 coarse-grained 单字段）。理由：拆为 `routeEstimated`/`costEstimated` 会触发 DB column + Java/Web/event 全链路；D-min 先采用保守聚合规则：只要关键用户可见字段由本地估算产生，整条 leg `estimated=true`。route/fare 的细粒度 provenance 通过 `provider=AMAP` 与 `cost_source=RULE_ESTIMATE` 解释，未来再拆 `routeEstimated/costEstimated`。

### 17.3 当前混合语义的风险记录（§51）

- **B19-D 目标语义**：manual `TAXI` 的 route facts 为 AMAP real，但 fare/wait 为 local estimate，因此 DB core 必须是 `mode=TAXI/provider=AMAP/estimated=true/duration=road+300s/estimated_cost=<rule fare>`；response provenance 为 `route_duration_seconds=duration-300/cost_source=RULE_ESTIMATE/wait_seconds=300`。不得以 `estimated=false` 暗示整条 leg fully-real。
- **现有硬冲突（实施前必须解决）**：数据库 `V7__create_transit_legs.sql` 的 `ck_transit_leg_provider_estimate` 只允许 `(AMAP,false)` 或 `(DEMO,true)`；Python `ItineraryTransitLeg.validate_provider_estimate`、event schema/parser 也采用同一耦合规则。manual `TAXI` 不进 event，故 event `v11/v2` 可保持；但 DB 不可能在“无 migration”前提下写入 `AMAP/true`。
- **GREEN 门禁**：不得把目标状态静默改回 `AMAP/false`，也不得伪装为 `DEMO/true`。进入 `B19-D1 GREEN` 前必须明确批准以下之一：① constraint-only DB migration 放宽为 `TAXI + AMAP + estimated=true`；② 引入同等可靠的持久化 provenance 模型。两者都未批准时，`D18` 必须保持 RED，语义实施不得开始。
- `route_duration_seconds`/`cost_source`/`wait_seconds` 当前不在 `transit_leg` 表或 `TransitLegResponse` 中；D-min 可由 persisted `TAXI.duration_seconds` 与固定 300s 规则稳定派生，无需 DB column，但必须在 reload/share/export 测试中证明不会丢失。

### 17.4 Provider 字段是否足够？（§52）

- 单一 `provider` 不足以表达“route provider=`AMAP` + fare provider=`LOCAL_ESTIMATE`”；因此 `provider` 严格表示 route provider，`cost_source` 严格表示 fare provenance。
- manual `TAXI` 的 `cost_source=RULE_ESTIMATE`、`wait_seconds=300` 与 `route_duration_seconds=duration_seconds-300` 可稳定派生；未来若出现多种 TAXI fare/wait provider，再升级为独立持久化字段。

---

## 18. Replan Integration

- 现状：`replan_service.py:262-285` 复用 `existing_leg.mode` → `RouteRequest(mode=..., city=trip.destination, departure_at=origin.end_time)`；已支持 `WALKING`/`TRANSIT`/`DRIVING`（`TRANSIT` 同城 via `AmapTransitProvider`，跨城为 Known Gap）。
- **兼容映射**：
  - **Java command producer boundary**：发布 replan command 前，将 snapshot 中 TAXI 变为 Python-valid technical projection。新 AMAP TAXI 投影为 `mode=DRIVING/provider=AMAP/estimated=false/duration=total-300/estimatedCost=null/costSource=UNKNOWN`；legacy/flag-fallback DEMO TAXI 投影为 `mode=DRIVING/provider=DEMO/estimated=true`，若原 `polyline=[]` 则用 source from/to activity coordinates 生成 OD 两点 geometry。immutable source version 保持 TAXI，planning task 保留 `baseVersionId`。因此 Python inbound validator 从不接收 `TAXI/AMAP/true` 或空 polyline，也不把 taxi fare 冒充 driving cost。
  - **Python provider/wire boundary**：只看到 `DRIVING`，`RouteRequest` 与 `PlanningResult`/event leg 均保持 `mode=DRIVING/provider=AMAP/estimated=false`，继续满足 `v11/v2`；`replan_service.py` 无需新增 TAXI domain 分支。
  - **Java completion boundary**：通过 task `baseVersionId` 重载 immutable source version；按 date + wire indices 映射回 source activities，再构造 `fromActivityId/toActivityId`。impacted date 的 source TAXI 用新 wire DRIVING facts按 §15重算；非 impacted date 的 source TAXI 直接复用 immutable source leg，不采信规范化 wire projection。intent 恢复不污染 provider/event contract。
  - `baseVersionId` 缺失、source version 不存在、index/endpoint identity/OD coordinates 缺失或匹配不唯一时，在 command publish 或 completion write 前 **fail closed**，不猜测 TAXI intent、不产生新 itinerary version。
  - `mode=SELF_DRIVING`（future）→ 同 `DRIVING`（若 `TAXI`/`SELF_DRIVING` 本批不作为 replan 输入，兼容分支为预留）
  - `mode=TRANSIT`/`WALKING`/`DRIVING` → 保持既有（同城 `TRANSIT` 真实，`WALKING`/`DRIVING` 经 `AmapRouteProvider`）
- **Cache**：replan 走 `LocalReplanningProvider._route`（不经 `_route_cached` 计数，B18-B 既有设计，全 mode 一视同仁；本批不新增第三路径）。
- **验证**：`C` 由 `test_local_replanning` + `T16`（B19-B）锁定；B19-D 新增 `replan TAXI leg` Fixture（见 §27 `D7`）。

---

## 19. Immutable Version / Idempotency

- **不可变版本**：manual mode edit（`TRANSIT`/`TAXI`/`DRIVING`/`WALKING`/`AUTO`）均创建**新 `itinerary_version`**（`versionSource=USER_EDIT`，`EDIT` 事务内 `transit_leg` 全量快照 + `itinerary_day` 关联），旧版本只读（历史 `DRIVING` 不回填意图）。
- **原子性**：`route provider lookup → version write → leg snapshot` 在同一事务边界内；provider 失败 → **不产生半成品版本**（§22、`D11`）。
- **幂等**：
  - `EditRequestFingerprint = tripId + fromActivityId + toActivityId + requestedMode + departureBucket(15min)`；`IdempotencyKey`（UUID）用于请求重放。fingerprint/key 必须在 provider 调用前检查，命中即 **replay same version/result**；不把 `RoutePlan` hash 纳入 fingerprint，否则无法在调用 provider 前去重。
  - 明确不会重复 provider call：指纹命中 → 直接返回已持久化的 `transit_leg` 行，不触发 `POST /internal/routes`。

---

## 20. Event Contract Decision

**最终：`NO`（不升 `v12`/`v13`；`v11` 已足够）**

| 项 | 决定 | 理由 |
| --- | --- | --- |
| completion event | `v11` 保持（`schema_version=11`，`mode ∈ [WALKING,TRANSIT,DRIVING]`） | planner/replan wire 仍只产三种 provider-backed mode；replan TAXI 在 Python/event 中为 `DRIVING`，Java consumer 按原 snapshot 恢复 persisted `TAXI`；`v11` `TAXI` REJECT 保持 |
| review event | `v2` 保持 | 同上 |
| `roadIntent` | 不在 event 承载（`mode=DRIVING, roadIntent=TAXI|SELF_DRIVING` 候选为 `C` 方案，但本批不实现） | 若未来引入 `roadIntent`，再评估 `v12`（`mode=DRIVING + roadIntent可空` 更兼容）vs `mode=TAXI/SELF_DRIVING` 直枚举；当前无需为未引入的字段升版 |
| 省略语义 | B17 `PlanningFactImpact` `date/targetPoiId/targetName/sourceUrl` `None` 时 `omit`（非 `null`）保持 | serializer 行为不回退（§48 用户要求） |

---

## 21. DB Decision

**最终：`NO enum/column migration`；provider-estimate constraint-only migration 为 `D18` 实施门禁，尚未批准**

| 候选 | 评估 |
| --- | --- |
| **Option 1：继续单字段 `mode`** | ✅ **语义模型采用**：`transit_leg.mode` `VARCHAR(20)` + `CHECK IN ('WALKING','TRANSIT','DRIVING','TAXI')`（`V23` 已含 `TAXI`），不新增 `road_intent` 列；`TAXI` 已可持久化 manual intent |
| Option 2：增加 `route_mode + transport_intent` 双字段 | ❌ 本批不需要（`SELF_DRIVING` 未引入） |
| Option 3：保持 `mode` + 另加 `road_intent` 可空 | 仅 `C` 方案需要，本批 DEFER |

- 若未来引入 `roadIntent`：`V??__add_road_intent_to_transit_leg.sql`（`road_intent VARCHAR(20) CHECK IN ('TAXI','SELF_DRIVING') NULL`，旧 `DRIVING` 行保持 `NULL`（`unknown`），查询时 `COALESCE` 为 UI 展示）。

**DB 门禁结论**：本批仍不需要 enum/column migration，但“完全无 DB migration”与 `D18` 的 `AMAP/true` 目标不兼容。若坚持 `D18`，至少需要 constraint-only migration；若坚持零 migration，则 B19-D1 不得宣称 GREEN。该决策不影响 `B19-D0`。

---

## 22. Java Impact

**本批需要修改生产代码**（§24 最终 `YES`）。

| 文件 | 改动 | 说明 |
| --- | --- | --- |
| `infrastructure/mq/PlanningCompletedEventParser.java` | **0**（不改） | `v11`/`v2` 分支已在 B19-B 落地；本批不升 `v12`，不新增 `TAXI` 分支（`TAXI` 仍被 event 拒绝，manual `TAXI` 的 `TAXI` mode 为 DB/Web 侧持久化，不经 event） |
| `planning/PlanningTaskService.java`（replan command producer） | **是** | D7 producer half：从 `baseVersionId` 构造 Python-valid TAXI→DRIVING technical projection（同步规范化 provider/estimated/duration/cost provenance）；task 保存 immutable `baseVersionId`，不扩 command/event contract |
| `planning/PlanningCompletionService.java` | **是（仅 replan bridge）** | D7 consumer half：用 task `baseVersionId` 重载 source version，按 date + indices 构造 endpoint identity，将 wire DRIVING 恢复为 persisted TAXI，再应用 rule fare/wait 与 `estimated=true`；普通 planning completion 不改 |
| `PlanningTaskOutcomeReadModel.java` | **0** | read model contract 不改 |
| `itinerary/ItineraryService.java` — `applyTransitLegEdit` | **是**（核心） | `TRANSIT`→调用 Python `POST /internal/routes(mode=TRANSIT)`；`TAXI`→调用 `mode=DRIVING` 再套用 fare/wait 估算并将合成 leg 标记 `estimated=true`；`DRIVING` 仅作 legacy/technical compatibility，不作为“自驾”入口；`AUTO`→调用 `/internal/routes/recommend`；失败不产 version；幂等复用 |
| `api/TripItineraryController.java`（或 `ItineraryEditController`） | **轻量** | 透传 `EditRequestFingerprint` + `requestedMode` 至 service；错误映射（`ROUTE_NOT_FOUND`/`PROVIDER_SCHEMA_CHANGED` → 409/502 + 可重试提示） |
| `config/RouteProviderClient.java`（新，内网 HTTP 客户端） | **新增** | `RestClient`/`WebClient` 内网调用 Python `route` 服务（`AGENT_INTERNAL_TOKEN` 鉴权，超时 6s，`Retry-After` 透传，`JsonCache` 不经过 Java） |
| `evaluation/*`（若有 `mode==DRIVING` 分支） | **0**（审计确认无此分支，`routeEfficiency` 为分数聚合，不按 mode 分支） | 列入 `Files To Change` 审计但本批不改 |

---

## 23. Web Impact

**本批需要修改生产代码**（§25 最终 `YES`），但**不新增 `ROAD`/`SELF_DRIVING` UI**。

| 文件 | 改动 | 说明 |
| --- | --- | --- |
| `lib/transit.ts` — `ConcreteCommuteMode` | **0**（不改 union） | 保持 `'WALKING'\|'TRANSIT'\|'DRIVING'\|'TAXI'`（`TAXI` 已在 Web 既有；`DRIVING` 为 provider 语义，展示映射不改类型） |
| `lib/transit.ts` — `estimateCommuteOptions` / `recommendedCommuteMode` | **退出 recommendation** | 删除 `recommendedCommuteMode`，或仅保留 deprecated export 以完成调用方迁移；`rg`/测试必须证明它不再进入 AUTO decision、preview、offline fallback 或 optimistic recommendation。`estimateCommuteOptions` 不得为 AUTO 猜测 mode；如仍被非推荐 UI 使用，必须与 AUTO 路径隔离 |
| `components/TransitLegControl.vue` | **是** | `displayModeLabel` 对 `DRIVING` 与 `TAXI` 无条件返回“打车”，不检查 `userSelectedDriving`/request source；D-min 移除“驾车/自驾”选择；`AUTO` 文案改为“自动·后端推荐”，只走后端 API（loading + 当前 persisted leg，失败保留原 leg）；`modeHasConflict` 使用后端返回的 total `durationSeconds`（TAXI 已含 300s wait） |
| `components/TripDetail.vue` / `lib/api.ts` | **是** | `TripDetailPlanEvaluation` / `TripWorkspaceActions` 的 `updateTransitLeg` 调 `POST /api/trips/.../edits/commit` 的按钮 loading/error 透传；`transitModeFor` 的旧 `DRIVING` persisted leg 加载时显示"打车"（无需 migration，仅展示映射） |
| `lib/feasibility.ts` / `PlanningReviewPanel.vue` | **0** | 不改 |

**UI 目标（§34，最小交互）**：`步行 / 公交·地铁 / 打车 + 自动·{后端推荐}`；本批不显示“驾车/自驾”，`AUTO` 无本地推荐 preview；不画新原型。

---

## 24. Share / Export / PDF / ICS Impact

| 通道 | 审计结论 | B19-D 动作 |
| --- | --- | --- |
| **Share DTO**（`SharedItinerary` / `ShareController`） | `leg.mode` 透传 + `SharedItineraryPage.vue:95` `{{ leg.mode }}` 原样 | 保留 raw `mode`，新增/派生 `modeLabel`；TAXI 同时派生 `routeDurationSeconds/costSource=RULE_ESTIMATE/waitSeconds=300`，页面展示 total duration 与“含候车约 5 分钟/费用估算” |
| **Export JSON**（`ItineraryExportService.java`） | `mode` 直出；`transitLeg.mode` 为 4 值透传 | 保留 raw `mode`，新增 `modeLabel`。TAXI 导出 `routeDurationSeconds/costSource/waitSeconds`；DRIVING raw cost 增加 `costMeaning=ROAD_TOLL`，不得当作 taxi fare |
| **PDF**（`TripDocumentService` / `ItineraryExportService.java:77-81` `Transit {mode}`） | 原生英文枚举展示 | 使用 label 映射；TAXI 展示 total duration、“含候车约 5 分钟”与“费用估算”；DRIVING 显示“打车”但**隐藏 cost**，未知 mode 原样 fallback |
| **ICS**（`TripIcsService`） | **不含 leg mode**（仅活动 `DTSTART/DTEND`，与 §336 事实一致） | **无改动**（列入 impacted 但本批不改） |

**DRIVING cost 门禁（确定行为）**：persisted `DRIVING` 虽显示为“打车”，其 provider cost 仍只是 AMAP `toll_cost`，不是 taxi fare。Web/Share/PDF **一律隐藏 DRIVING cost**；Export JSON 保留 raw cost 时附 `costMeaning=ROAD_TOLL`。只有 `mode=TAXI` 才在人类可见通道展示 `RULE_ESTIMATE` taxi fare。

---

## 25. Historical Compatibility

| 历史值 | 策略 | 理由 |
| --- | --- | --- |
| `legacy DRIVING`（已持久化的 `transit_leg.mode='DRIVING'`） | **继续保留原值，仅新 version 引入新语义**（`§29` 最安全策略） | 无法可靠区分历史 `DRIVING` 是打车还是自驾（无 `vehicleAccess` 约束、无意图字段）；**不迁移历史值语义**（不回填 `roadIntent`，不批量 `DRIVING→TAXI`） |
| 旧 `DRIVING` 加载时显示 | **固定 label**：“打车” | 不能从历史值或 request source 恢复“自驾”意图；Web/Share/Export/PDF 使用同一无来源映射 |
| 新 `TAXI` leg | `mode='TAXI'`（manual edit 产出） | 历史 leg 不受影响；fare provenance 可由 `TAXI` 稳定派生 |
| 回滚 | 旧 `DRIVING` 数据始终可读 | `v11`/`v2` 均接受 `DRIVING`；DB mode `CHECK` 保持 |

**旧 DRIVING persisted leg 加载时标签（§76）**：
- Web `TripDetail.transitModeFor(leg)` → `modeLabel(leg.mode)`（`DRIVING`→"打车" 默认；若 `leg.mode==='TAXI'`→"打车"；`leg.mode==='TRANSIT'`→"公交·地铁"）。
- Share/Export/PDF 同映射，未知 `mode`→`mode` 原样 + `estimated` 文案兜底。

---

## 26. `B19-B:D1` Disposition

**最终：`B19-D0` 收口 `B19-B:D1`（前置小修，独立 RED→GREEN / commit / acceptance，不与 `B19-D1` 语义迁移耦合）**

| 项 | 决定 |
| --- | --- |
| 何时修 | **B19-D0、语义真实化之前**（precondition）；因 `B19-B:D1` 暴露面随 `TRANSIT` 默认查询（B19-C）扩大，manual `TRANSIT` 真实化（本批）会直接放大触发面 |
| 内容 | 实现 `plan-b §4.4` **"跳段+全缺退化 2 点"**：`_amap_transit.py:_to_plan` 中 segment 无 `polyline` → **跳过该段**（不中断拼接）；全部缺失 → `polyline=(origin, destination)` 两点（与 DEMO/fallback 的 `min_length=1` 兼容）；相邻重复端点去重保持 |
| 不做 | 不因此升 `v12`，不改 contract；`ProviderFailure(PROVIDER_SCHEMA_CHANGED)` 的 fail-closed 语义保留，仅 geometry 缺失时 degradable |
| 验证 | `RED: test_amap_transit_polyline_missing_segments_skipped` + `test_amap_transit_polyline_all_missing_falls_back_to_two_points` + 真实 G1 回归（39 点） |
| 若延期 | 则 `manual TRANSIT` 真实化在 `B19-B:D1` 触发时会 `PROVIDER_SCHEMA_CHANGED` fail-closed（用户看到“暂不可用”而非半几何），虽安全但 UX 降级，故必须先在 D0 收口 |

---

## 27. RED Matrix

> **不修改生产代码，仅测试先行**；`already GREEN` 项如实记录为回归锁定，不故意破坏。
> 本节 `D1-D19` 是 **B19-D1 Semantic Convergence 测试 ID**；polyline defect 始终写作 **`B19-B:D1`** 并归 B19-D0，二者不得混用。
> 测试文件（预计）：`tests/test_b19d_semantics.py`（新，语义/映射）+ `tests/test_b19d_manual_edit.py`（新，manual 真实化）+ `tests/test_amap_transit.py` 扩展（`B19-B:D1`，归 D0）+ Java `PlanningCompletedEventParserTest` 扩展（兼容）+ Web `transit.test.ts`/`TransitLegControl.test.ts` 扩展。

| ID | 断言 | baseline（修复前） | GREEN 后 |
| --- | --- | --- | --- |
| **D1** | planner road recommendation（`DRIVING` road 事实）user-facing 语义为 **TAXI/打车** | RED（当前 Web 显示“驾车”） | planner 产 `DRIVING` → Web/分享/导出显示“打车”；不存在显式 `DRIVING→驾车` 例外 |
| **D2** | explicit `TAXI`：distance/polyline/route-duration 来自真实 DRIVING route，fare/wait 本地估算 | RED（当前 `TAXI: DEMO/[]/true`） | DB `provider=AMAP/estimated=true/duration=road+300/polyline≠[]/cost=12+km×2.6`；DTO `route_duration_seconds/cost_source=RULE_ESTIMATE/wait_seconds=300`；冲突判断使用 total duration |
| **D3** | explicit `SELF_DRIVING` route facts | **DEFER**（本批不引入 `SELF_DRIVING`，`§12`） | 预留；本批不测试 |
| **D4** | manual `TRANSIT` real provider：用户切 `TRANSIT` → 真实 `AmapTransitProvider` 结果（`mode=TRANSIT/provider=AMAP/false/polyline≠[]`） | RED（`DEMO/[]/true`） | 真实 `TRANSIT`（含 `walking_distance/transfer_count` 可溯源，`B19-B:D1` 修复后 geometry 必非空） |
| **D5** | manual `TAXI` real road provider：同 `D2`（内部 route request 只能为 `DRIVING`，Python 不接受 `TAXI`） | RED | 同 `D2`；`/internal/routes` request mode=`DRIVING`，persist/result mode=`TAXI` |
| **D6** | `route`/`fare` provenance 可解释：`route provider=AMAP` + `fare=RULE_ESTIMATE` 时 UI 文案“路线来自高德·费用估算” | RED（单一 `estimated` 语义模糊） | `estimated=true` 保守聚合 + provenance 文案（本批不拆字段） |
| **D7** | replan `TAXI` intent bridge | RED（当前 raw TAXI snapshot 会在 Python inbound validator/RouteRequest 被拒绝） | Producer 同步规范化 mode/provider/estimated/duration/cost/polyline（legacy 空几何→OD 两点）；Python impacted result=`DRIVING/AMAP/false`；consumer 重载 base version：impacted TAXI 重算、unimpacted TAXI 复用 source；persisted result=`TAXI/AMAP/true`；event 无 TAXI |
| **D8** | historical `DRIVING` compatibility：旧 `DRIVING` leg 加载/分享/导出不崩，且显示“打车” | RED（读取已 GREEN，但标签映射未实现） | 旧 `DRIVING` →“打车”（Web/Share/Export/PDF 均非崩） |
| **D9** | `AUTO` no algorithm drift：Web `AUTO` 不用本地 `transit≤taxi×1.6`，改调后端 Python recommendation | RED（两套引擎并存） | 后端先取真实 WALKING facts 并执行 B19-C short-circuit；未短路再取 DRIVING/可选 TRANSIT，最终写入真实 leg |
| **D10** | idempotent manual edit：同 `EditRequestFingerprint` 重放 → 同 version/result，不重复 provider call | RED（当前每次 edit 均本地估算新 version） | 同指纹二次 `commit` 复用已写 version（内网 API 不二次计费，`map:transit:v1:`/`map:route:v1:` cache 命中） |
| **D11** | provider failure atomic rollback：真实 `TRANSIT`/`DRIVING` 失败 → **不产生半版本** | RED（无法验证，当前无 provider 失败分支） | `ROUTE_NOT_FOUND/PROVIDER_SCHEMA_CHANGED/TIMEOUT` → 明确错误透传，前端保留原 leg，无新 version |
| **D12** | share/export presentation/provenance | RED（仅 raw mode，TAXI provenance 不完整） | raw mode 保留 + `modeLabel`；TAXI export/share 含 `routeDurationSeconds/costSource/waitSeconds`；Web/Share/PDF 隐藏 DRIVING cost；Export DRIVING 带 `costMeaning=ROAD_TOLL` |
| **D13** | PDF/ICS label：同 `D12`（`ICS` 不含 leg，锁定无改） | RED（ICS 已 GREEN；PDF 仍原样英文） | `PDF` 中文映射；ICS targeted regression 保持无 leg |
| **D14** | cache reuse for road intents：manual `TAXI` 的内部 `DRIVING` request 命中既有 `map:route:v1:DRIVING` cache | RED（`TAXI→DRIVING` edit path 尚未实现） | 同 OD 的 TAXI edit 与既有 DRIVING route lookup 共用 cache，不二次调用 provider；不以不存在的 SELF_DRIVING 作验收前提 |
| **D15** | contract compatibility：`v11`/`v2` 语义不放宽（`TAXI` 仍 REJECT，`TRANSIT` 已接受） | **already GREEN**（B19-B 已保证；锁定） | 同 `already GREEN`（本批不升版） |
| **D16** | DB mode/shape compatibility：`TAXI` 已在 `V23` `CHECK`，无需新 mode/column，既有值读写正常 | **already GREEN**（锁定） | 不新增 `road_intent`/mode；provider-estimate constraint 的 D18 决策单独验收 |
| **D17** | persisted `DRIVING` 无额外来源信息时，read/reload/share/export/PDF 均稳定显示“打车” | RED（现有主站“驾车”，且旧方案依赖瞬时来源） | 所有通道仅依据持久化 mode 映射；无 `userSelectedDriving`/request-source 分支 |
| **D18** | manual `TAXI` mixed provenance：real AMAP road facts + local fare/wait | RED（当前纯 `DEMO`; 且 DB constraint 禁止 `AMAP/true`） | DB `mode=TAXI/provider=AMAP/estimated=true/duration=road+300/polyline≠[]`；DTO `route_duration_seconds/cost_source=RULE_ESTIMATE/wait_seconds=300`；constraint 门禁已解决 |
| **D19** | AUTO 唯一 authority：Web local recommendation 与所有运行时 decision/preview/fallback path 完全断开 | RED（`recommendedCommuteMode` 与 `1.6` 仍存在） | 最终 mode 只来自 backend B19-C；Web 仅 loading/current persisted shell |

> **already GREEN** 仅用于完整断言已满足的回归锁定；本矩阵只有 D15/D16 属于此类。D8/D13/D14 均含尚未实现的目标，因此保持 RED。`D16` 只证明 `mode=TAXI` 无需新 mode/column，**不能**证明 `D18` 的 `AMAP/true` 可写。

---

## 28. Golden Matrix

| ID | 场景 | 期望 | 判定来源 |
| --- | --- | --- | --- |
| **G1** | 无车辆约束 + road 推荐：广州塔→正佳（B19-A 真实：`transit 1250s` vs live `driving ~986s`） | planner `DRIVING` → UI **"打车"**（文案，不改 `mode`） | 前端/分享/导出 label 映射 |
| **G2** | explicit self-driving | **DEFER**（本批无 `SELF_DRIVING`，也无“驾车/自驾”可持久化入口） | §12 |
| **G3** | explicit taxi：用户点击 `TAXI` | DB `mode=TAXI/provider=AMAP/estimated=true/duration=road+300/polyline≠[]/cost=12+km×2.6`；DTO `routeDurationSeconds/costSource=RULE_ESTIMATE/waitSeconds=300` | §15 / `D2` / `D18` |
| **G4** | manual `TRANSIT`：用户点击 `TRANSIT` | `mode=TRANSIT/provider=AMAP/false/polyline≠[]`（真实 `walking_distance/transfer_count`） | §14 / `D4` |
| **G5** | manual `TAXI`：同 `G3` | 同 `G3` | 同 `G3` |
| **G6** | `AUTO` edit：用户点击 `AUTO` | 后端推荐 `WALKING/TRANSIT/DRIVING`（真实 facts + R/N/W 规则，与 planner 同算法），写入真实 leg；Web 不先显示本地猜测 | §16 / `D9` / `D19` |
| **G7** | historical `DRIVING` itinerary load：旧 `DRIVING` leg（`V23` 后存量） | 加载正常，显示 **"打车"**（share/export/PDF 同映射，未知 `mode` 不崩） | `D8` / `D12` / `D15` |
| **G8** | replan existing road intent：已有 `TAXI` leg 的局部 replan | Java command snapshot=`DRIVING` + task 保留 baseVersionId；Python request/wire=`DRIVING/AMAP/false`；Java persisted/API=`TAXI/AMAP/true` + rule fare/wait；v11 仍拒绝 wire TAXI | `D7` |

脚本：`C:\Windows\Temp\opencode\b19_d_golden.py`（未提交；真实 AMAP 广州 OD 若干，节制 ≤15 次；其余用确定性 fixtures）。

---

## 29. API / Performance Budget

| 项 | 估算 |
| --- | --- |
| 单次 manual edit provider calls | D-min explicit `TRANSIT` 1；explicit `TAXI` 1（内部 `DRIVING`）；explicit `WALKING` 保持既有 local path，`DRIVING` 不作为 UI 入口；`AUTO` 最多 3（`WALKING+DRIVING+TRANSIT`），walking 短路为 1，`budget_degraded` 跳过 TRANSIT 为 2 |
| latency | `DRIVING`/`TRANSIT` P50 ~400-900ms（内网+AMAP），`cache hit`（`map:transit:v1:`/`map:route:v1:` TTL 3600s）时 <20ms；同步 HTTP 超时 6s（可重试 `Retry-After`）|
| rate limit / quota | edit 侧不与 planning 侧 `96` 共享；per-edit budget `1-3`（见上）；每日手动编辑频次远低于 planning；重复指纹直接复用 version/cache，不二次计费 |
| cache hit | 同 `OD+departure_bucket(15min)+city/strategy` 的 `TRANSIT` 二次编辑命中；同 `OD` 的 `TAXI`/`DRIVING` 二次编辑命中同一 `DRIVING` cache（`§49`）|
| `MAX_ROUTE_CALLS_PER_PLAN=96` | **保持不变**（planning 侧）；edit 侧为 `per-edit budget`（`§74` 独立），**不共用 96**（避免用户点按钮烧掉规划配额）|

---

## 30. Rollout

> 复用 `B19-B` 成功经验：**consumer-first / dual-read / producer switch / historical compatibility / rollback**。

```
B19-D0（独立 commit / 独立验收）
1. `B19-B:D1` 小修（_amap_transit.py 跳段+2点退化 + tests）
2. targeted acceptance + 真实 G1 回归；通过后关闭 D0

B19-D1 Semantic Convergence（不得与 D0 混 diff）
3. RED D1-D19；先证明 D17/D18/D19 失败，并解决 §17.3 DB 门禁
4. Python 内网 API（POST /internal/routes + /internal/routes/recommend）
   - 复用 _amap_route/_amap_transit/mode_recommendation/can_probe_transit/accessible_burdens
5. Java route-client（RouteProviderClient）+ ItineraryService.applyTransitLegEdit 后端化
   - TRANSIT→transit provider；TAXI→driving route facts + local estimate；AUTO→recommend
   - 失败不产 version；幂等指纹复用
6. Web 展示收敛（所有 DRIVING→“打车”；移除自驾入口；AUTO 无本地 recommendation）
7. Share/Export/PDF label 映射（DRIVING→“打车”）
8. 全链路集成 + Golden（G1-G8）+ 全量回归
```

- **历史兼容**：旧 `DRIVING` 行不迁移，查询时展示兼容；`v11`/`v2` 消费者不改，`v11` 仍双读（无 `v12`）。
- **dual-read**：Java 对 `transit_leg.mode` 的读侧保持 `WALKING/TRANSIT/DRIVING/TAXI` 四值白名单（`ItineraryService.java:425` 已含），无需双写。
- **producer switch**：`applyTransitLegEdit` 中"真实 provider"分支采用 feature-flag（`trippilot.manual-edit.real-routing.enabled`），默认 `true`，关闭即回退纯 `DEMO` 估算（见 §31）。

---

## 31. Rollback

> **如果 B19-D 上线后 road 语义出问题，如何快速回退到现有 `DRIVING`/`TAXI` 行为？**

| 场景 | 回滚手段 | 说明 |
| --- | --- | --- |
| manual edit 真实 provider 异常（`TRANSIT`/`TAXI→DRIVING route` 频发 `PROVIDER_SCHEMA_CHANGED`/超时） | **feature-flag 关闭**（`manual-edit.real-routing.enabled=false`）→ `applyTransitLegEdit` 回退本地 `DEMO` 估算（`polyline=[]/DEMO/true`），与 B19-C 前行为一致 | 无需 DB 回滚，无需代码回滚；开关秒级生效 |
| 统一“打车”展示出现产品问题 | 可关闭新 edit 入口或回滚整个 B19-D1 前端发布，但**不得**仅把 persisted `DRIVING` 恢复为“驾车”；没有 `roadIntent` 时该标签不可靠 | 语义门禁优先于局部 UI 开关 |
| 内网 `POST /internal/routes` 延迟/超时升高 | Java 侧 `timeout=6s` + toast“暂不可用”；保留当前 persisted leg，不产新 version；严重时关闭 real-routing edit feature | provider failure 不产半版本，不以 DEMO 结果冒充成功 |
| `AUTO` 后端不可用 | 禁用 AUTO 或显示“暂不可用”，保留当前 persisted leg | **禁止**回退 Web `recommendedCommuteMode`/`1.6` preview；否则重新引入双引擎 |

**回滚边界**：本批无 event `v12`、无 `ROAD` enum、无 DB column/mode 迁移，历史 `DRIVING` 数据无需回填。若为 D18 批准 constraint-only migration，必须在该 migration 中给出独立 rollback 验证；关闭 real-routing flag 可停止产生 mixed-provenance 新 leg，但不改变既有版本。

---

## 32. Risks

| # | 风险 | P | I | 缓解 |
| --- | --- | --- | --- | --- |
| 1 | `DRIVING cost=toll` 在“打车”标签下被误读为 taxi fare | 中 | 高 | §24 硬门禁：Web/Share/PDF 一律隐藏；Export 加 `costMeaning=ROAD_TOLL`；只有 TAXI 展示 rule fare |
| 2 | `TAXI fare` 全局固定，无城市化（北京/上海/深圳起步价不同） | 中 | 中 | §42 已评估为已知限制；首版`estimated` 文案覆盖，二版 city-aware estimator |
| 3 | `RIDE_HAIL vs TAXI` 命名（`§43`）：当前"打车"含出租车/网约车泛化，`TAXI` 命名偏出租车计价 | 低 | 低 | 本批不重命名 `TAXI`→`RIDE_HAIL`（`§44` 命名审计：`TAXI`=domain intent，`DRIVING`=provider mode，`ROAD`=技术几何，三者分离已在文档层明确） |
| 4 | manual edit 内网同步调用超时（AMAP `TRANSIT`/`DRIVING` 网络/限流） | 中 | 中 | 超时 6s + `Retry-After` 透传 + 明确"暂不可用"且不产半版本；`cache` 命中降低二次调用 |
| 5 | `MAP` 限流/配额（与 B18 时期 `route` 限流同源） | 低 | 中 | per-edit 1-3 calls；walking short-circuit / `can_probe_transit` 降级 + `D10` 幂等/cache 避免重复烧 quota |
| 6 | manual `TAXI` 的目标 `AMAP/true` 被现有 DB `ck_transit_leg_provider_estimate` 拒绝 | 高 | 高 | §17.3 / §21 硬门禁：D18 保持 RED，直至 constraint-only migration 或等价持久化模型获批；禁止退回 `AMAP/false` |
| 7 | persisted `DRIVING` 标签被瞬时 request source 再次分叉 | 中 | 高 | D17：所有通道无条件“打车”；移除 `userSelectedDriving`/显式“驾车”分支 |
| 8 | 两套 `TAXI` wait/fare 公式漂移（前端 `+120s` vs Java `+300s`） | 低 | 中 | Java 是 fare/wait 唯一估算源；Web 不显示本地估算 preview，仅 loading/current persisted shell |
| 9 | `B19-B:D1` polyline 缺失的极端 case 在 manual `TRANSIT` 真实化后首次暴露 | 低 | 低 | §26 将其作为 B19-D0 独立前置小修收口（跳段+2点） |
| 10 | `routeEstimated/costEstimated` 拆分的需求在近未来出现但被本批拒绝 | 低 | 中 | 登记 `B19-D2/B20`；当前用 `estimated=true` 保守聚合，route/cost provenance 分别由 `provider`/`cost_source` 表达 |

---

## 33. Files To Change

### Python（`apps/agent-service/`）

| 文件 | 本批动作 |
| --- | --- |
| `providers/_amap_transit.py` | **B19-D0 / `B19-B:D1` 小修**（跳段+2点退化；唯一 polyline 生产改动） |
| `providers/_route_contracts.py` | **0**（`WALKING/TRANSIT/DRIVING` 保持；`city`/`strategy` 已在 B19-B） |
| `infrastructure/amap/planning_provider.py` | **0**（本批不改 planning 侧；`mode_recommendation` 已在 B19-C） |
| `planning/mode_recommendation.py` | **0**（R/N/W 常量与 `decide_transit_or_road` 保持；仅被 Java `AUTO` 后端化时复用） |
| `api/routes_internal.py`（**新**）或 `worker/api.py` 扩展 | **新增** `POST /internal/routes`（只接受 provider modes `WALKING/TRANSIT/DRIVING`，绝不接受 `TAXI`）+ `POST /internal/routes/recommend`（`AUTO` 时复用 staged 推荐） |
| `application/replan_service.py` | **0**（Java producer 已把 TAXI 规范化为 wire DRIVING；Python 继续只处理合法 provider modes，不放宽 `TransitLeg` validator） |

### Java（`apps/travel-server/`）

| 文件 | 本批动作 |
| --- | --- |
| `infrastructure/mq/PlanningCompletedEventParser.java` | **0** |
| `infrastructure/mq/PlanningReviewRequiredEventParser.java` | **0** |
| `itinerary/ItineraryService.java` | **是**（`applyTransitLegEdit` 后端化；`TAXI→DRIVING RoutePlan + RULE_ESTIMATE → estimated=true`；`AUTO` 后端化 + 幂等/原子性） |
| `config/RouteProviderClient.java`（**新**） | **新增** 内网 `Route` 客户端（`RestClient` + `AGENT_INTERNAL_TOKEN` + 超时/重试） |
| `api/TripItineraryController.java` / `TransitLegResponse` | **轻量**（`requestedMode` 透传 + 错误映射；TAXI 响应派生 `routeDurationSeconds=durationSeconds-300`、`costSource=RULE_ESTIMATE`、`waitSeconds=300`） |
| `itinerary/ItineraryExportService.java` / `TripDocumentService.java` | **是**（raw mode + `modeLabel`；TAXI 导出 route duration/cost source/wait；PDF 显示候车/费用估算；DRIVING Web/PDF cost 隐藏、JSON 标 `ROAD_TOLL`） |
| `api/ShareController.java` / `web/ShareService` | **是**（Share DTO 保留 raw mode + 派生 `modeLabel/routeDurationSeconds/costSource/waitSeconds`；隐藏 DRIVING cost） |
| `feasibility/*` / `evaluation/*` | **0**（审计无 `mode==DRIVING` 分支） |

### Contract/DB

| 文件 | 本批动作 |
| --- | --- |
| `contracts/messaging/planning-completed-event-v11.schema.json` | **0**（`v11` 保持） |
| `contracts/messaging/planning-review-required-event-v2.schema.json` | **0** |
| `contracts/fixtures/*` | **0**（本批不新增 `v12` fixtures；`TAXI` fixture 仍 REJECT） |
| `db/migration/V*.sql` | **门禁待决**：无 enum/column migration；但现有 `ck_transit_leg_provider_estimate` 禁止 D18 的 `AMAP/true`。若批准 constraint-only migration，必须单独列出并验证 rollback；未批准则 B19-D1 不进入 GREEN |

### Web（`apps/web/`）

| 文件 | 本批动作 |
| --- | --- |
| `lib/transit.ts` | **是**（`recommendedCommuteMode` 删除或完全断开；`estimateCommuteOptions` 不得进入 AUTO decision/preview/fallback） |
| `components/TransitLegControl.vue` | **是**（`displayModeLabel` 映射 + `AUTO` 后端化 + loading/error） |
| `components/TripDetail.vue` / `lib/api.ts` | **是**（`updateTransitLeg` 调后端 + 旧 `DRIVING` 展示兼容） |
| `pages/SharedItineraryPage.vue` | **是**（share 侧 label 映射） |
| `lib/feasibility.ts` / `PlanningReviewPanel.vue` | **0** |

### Tests（`apps/agent-service/tests/` + `apps/travel-server/src/test/` + `apps/web/tests/`）

| 文件 | 本批动作 |
| --- | --- |
| `tests/test_amap_transit.py` | **B19-D0 扩展**（`B19-B:D1` 跳段+2点） |
| `tests/test_b19d_semantics.py`（**新**） | `D1/D8/D9/D15-D19` 等语义/兼容/唯一 authority |
| `tests/test_b19d_manual_edit.py`（**新**） | `D2/D4/D5/D10/D11/D14/D18` 真实 provider + mixed provenance + cache/幂等 |
| `tests/test_local_replanning.py` | **回归锁定**（D7 Python half：只接收 wire DRIVING，结果可过 v11；不放宽 TAXI validator） |
| `apps/travel-server/src/test/.../PlanningTaskServiceTest.java` | **扩展**（D7 producer half：AMAP/true TAXI → DRIVING/AMAP/false + route duration/UNKNOWN cost；legacy DEMO/true 空 polyline → OD 两点；缺坐标 fail closed；baseVersionId 保持） |
| `apps/travel-server/src/test/.../PlanningCompletionFlowIntegrationTest.java` | **扩展**（D7 consumer half：baseVersion TAXI + wire DRIVING → persisted/API TAXI；AMAP/true + rule fare/wait；缺/歧义 source fail closed） |
| `apps/travel-server/src/test/.../ItineraryServiceTest.java` | **扩展**（manual `TRANSIT`/`TAXI`/`AUTO` 后端化 + `AMAP/true/RULE_ESTIMATE` + 指纹幂等 + 失败无 version） |
| `apps/web/tests/transit.test.ts` / `TransitLegControl.test.ts` | **扩展**（D17：全来源 DRIVING→“打车”；D12：DRIVING cost 隐藏、TAXI wait/provenance；D19：AUTO 无本地 recommendation） |

---

## 34. Acceptance Criteria

- [ ] `B19-B:D1` 跳段+2点退化已在 B19-D0 实现并回归 G1（39 点）
- [ ] persisted `DRIVING` 不再错误暗示用户一定有车（`D17`：不依赖来源，read/reload/share/export/PDF 一律“打车”）
- [ ] `TAXI` 与 `SELF_DRIVING` 语义不再混（`TAXI` 复用 `DRIVING` geometry，`SELF_DRIVING=DEFER` 已记录）
- [ ] provider road facts 不重复实现（Java 不复制 AMAP Transit；复用 Python `AmapTransitProvider`/`AmapRouteProvider`）
- [ ] manual `TRANSIT` 不再 `DEMO`（`D4`：`AMAP/false/polyline≠[]`）
- [ ] manual `TAXI` 不再纯 `DEMO`（`D18`：DB `AMAP/estimated=true/duration=road+300/polyline≠[]` + rule fare；DTO `routeDurationSeconds/costSource/waitSeconds=300`；冲突判断含 wait）
- [ ] `route`/`fare` provenance 可解释且 reload 后稳定（文案“路线来自高德·费用估算”）
- [ ] `AUTO` 不再与 Python recommendation 漂移（`D19`：最终 mode 只来自后端 B19-C；Web `1.6` 不进入 decision/preview/fallback）
- [ ] historical `DRIVING` 可兼容读取（`D8`/`D12`：`DRIVING`→"打车" + share/export/PDF 不崩）
- [ ] replan 正常（`D7`：`TAXI` leg `→DRIVING` route）
- [ ] immutable version / idempotency 正常（`D10`：同指纹复用 version）
- [ ] provider failure 不产生半版本（`D11`）
- [ ] share/export/PDF/ICS 不崩（`D12`/`D13`：raw mode + `modeLabel`；TAXI provenance 完整；Web/Share/PDF 隐藏 DRIVING cost，Export 标 `ROAD_TOLL`；`ICS` 无 leg）
- [ ] contract rollout 安全（`D15`：`v11`/`v2` 语义未放宽，`TAXI` 仍 REJECT，无 `v12`）
- [ ] DB 门禁已解决：若采用 constraint-only migration，已单独评审/回滚验证；若坚持无 migration，则不得把 `D18` 标为 GREEN
- [ ] `B19-C` recommendation 无回归（`R=1.2/N=2/W=1500`、`WALKABLE` 短路、`can_probe_transit` 动态预算、forward-fit/fixed-slot）
- [ ] `B17` `None`-omit 无回归（`PlanningFactImpact` 4 字段省略）
- [ ] `B18-B` walking baseline 无回归（`B1-B9`）
- [ ] 全量回归：Python `pytest` + `ruff` + contract schema tests + Java `mvn` + Web `vitest`/`typecheck`

---

## 35. Recommended Execution Order

> **禁止直接编码，本节仅为计划顺序；每个 Phase 完成后停留确认；不自动进入下一 Phase。**

```
Phase 0  B19-D0 — B19-B:D1 polyline hardening
         — 先写 RED，再完成 GREEN
         — _amap_transit.py 跳段+2点 + targeted tests + 真实 G1 回归
         — 独立 commit、独立 acceptance；验收通过后再启动 B19-D1

Phase 1  B19-D1 RED（D1-D19；D17-D19 为新增硬门禁）
         — test_b19d_semantics（D1/D8/D9/D15-D19）
         — test_b19d_manual_edit（D2/D4/D5/D10/D11/D14/D18）+ Java replan producer/consumer tests（D7）+ Python validator regression
         — Java/Web RED（D12/D13/D17-D19）
         — 记录 already GREEN，不故意破坏

Phase 2  DB feasibility gate
         — 证明 ck_transit_leg_provider_estimate 当前拒绝 AMAP/true
         — 明确批准 constraint-only migration 或等价持久化方案
         — 未决时停止；不得进入 semantic GREEN

Phase 3  Python 内网 route API
         — POST /internal/routes（mode=CITY_REQUIRED 校验复用 _route_contracts.require_city_for_transit）
         — POST /internal/routes/recommend（复用 mode_recommendation.decide_transit_or_road + can_probe_transit）
         — 鉴权 AGENT_INTERNAL_TOKEN + 超时/Retry-After + 结构化日志

Phase 4  Java manual edit 后端化（ItineraryService.applyTransitLegEdit + RouteProviderClient）
         — TRANSIT→transit provider；TAXI→DRIVING route facts + RULE_ESTIMATE；AUTO→recommend
         — persisted TAXI 为 AMAP/estimated=true；/internal/routes 不接受 TAXI
         — per-edit budget / cache / 失败不产 version / 指纹幂等 / versionSource=USER_EDIT

Phase 4b Java replan intent bridge
         — producer 从 baseVersionId 构造 snapshot：TAXI→wire DRIVING
         — Python 保持 DRIVING request/result，无 TAXI validator/event 改动
         — completion consumer 重载 baseVersionId，按 date+indices→endpoint identity 恢复 persisted TAXI
         — Java D7 targeted regression + Python validator/v11 regression

Phase 5  Web 收敛（TransitLegControl + TripDetail + transit.ts + Share/PDF label）
         — 所有 DRIVING→“打车”；移除“自驾”入口
         — AUTO→后端；删除/断开 1.6 recommendation；仅 loading/current persisted shell

Phase 6  Share / Export / PDF 映射 + 失败/幂等端到端

Phase 7  Golden（G1-G8，真实 AMAP 节制调用，广州为主，≤15 次）

Phase 8  全量回归（Python full/related/targeted + ruff + contract + Java full 537 + Web 447 + typecheck）

Phase 9  Execution Report（docs/execution/B19/execution-report-d.md）
```

### 最小可发布 B19-D（D-min，§80 要求明确）

```
D-min（分为独立可验收的 B19-D0 与 B19-D1）:
- B19-D0：`B19-B:D1` polyline hardening，独立 RED→GREEN、独立 commit、独立 acceptance
- B19-D1：Semantic Convergence；只有 D0 验收通过且 DB 门禁解决后才进入 GREEN
- 保留 provider DRIVING（不引入 ROAD/SELF_DRIVING/roadIntent/vehicleAccess）
- 所有 persisted DRIVING 在所有用户通道统一解释为“打车”；不提供“自驾”持久化选择
- manual TRANSIT 真实化（Java→Python 同步，阿 Transit 真实）
- manual TAXI 复用 DRIVING road route（RoutePlan AMAP/false；DB TAXI AMAP/true + total duration road+300 + rule fare；DTO 派生 route duration/RULE_ESTIMATE/300s wait）
- /internal/routes 只提供 WALKING/TRANSIT/DRIVING Route Facts，不接受 TAXI
- AUTO 后端化（Python B19-C 唯一 authority；Web 1.6 退出 decision/preview/fallback）
- SELF_DRIVING DEFER；ROAD enum DEFER；roadIntent DEFER；DB 无 enum/column migration；D18 的 constraint-only migration 待显式决策；event 0 bump
- 含幂等/原子性/失败不产半版本/fallback label 能力
```

---

## 附：关键决策速览（38 项汇报前置）

| # | 问题 | 结论 |
| --- | --- | --- |
| 1 | B19-D scope | D-min 上述 7 项；完整 scope 见 §5（12 项审计/设计） |
| 2 | DRIVING 技术语义 | `AMAP v5/direction/driving` `strategy=32` 的 **road route**（duration/distance/polyline + `toll_cost`） |
| 3 | TAXI 技术语义 | 无独立 provider；目标为 DRIVING road facts + 本地 fare/wait（`12+km×2.6` / `300s`）；当前前端 120s/Java 300s 漂移且为 `DEMO/[]/true` |
| 4 | planner DRIVING 当前问题 | 与 §7 `P1-P3`：展示"驾车"暗示有车、`DRIVING`/`TAXI` 重复、无车用户也收到 `DRIVING` |
| 5 | manual TRANSIT 当前问题 |  §6：`DEMO/[]/true` + 本地 `dist/5.5+420`/`2+⌊km/6⌋`，与 planner 真实 `TRANSIT` 严重不一致 |
| 6 | manual TAXI 当前问题 | 同 `P5` 侧：`DEMO/[]/true`，无真实 geometry，费用与 `DRIVING` 混用同一距离的两套等待/计价 |
| 7-8 | Option A/B/C 推荐 | A（保留 `DRIVING`）最小；B（`ROAD`）最干净但 breaking 最大；C（`roadIntent`）居中；**推荐 A**（本批），`roadIntent` 预留 |
| 9 | 是否引入 ROAD enum | **DEFER** |
| 10 | 是否引入 roadIntent | **NO**（本批）；预留 `mode=DRIVING+roadIntent` 在 C 方案 documentation |
| 11 | 是否引入 SELF_DRIVING | **DEFER** |
| 12 | 是否新增车辆/交通约束 | **NO**（`hasCar/vehicleAccess/transportPreference` 均不新增） |
| 13 | persisted road 默认解释 | **TAXI（打车）**（§11）；不依据来源区分 |
| 14 | persisted DRIVING 最终展示 | **所有通道统一“打车”**；本批无显式“驾车/自驾”例外 |
| 15 | manual TRANSIT 本批真实化 | **YES**（§14，Java→Python 同步） |
| 16 | manual TAXI 本批真实化 | **YES**（§15，复用 `DRIVING` route） |
| 17 | TAXI 是否复用真实 DRIVING road route | **YES** |
| 18 | Taxi fare 是否仍为估算 | **YES**（`12+km×2.6` 本地估算，`AMAP` 无 fare；`TRANSIT` 票价来自 `transit.cost` 为真实） |
| 19 | route/fare provider 如何表达 | Python RoutePlan=`AMAP/false`；DB TAXI=`AMAP/true/duration=road+300`；DTO 派生 `routeDurationSeconds/costSource=RULE_ESTIMATE/waitSeconds=300`（§17） |
| 20 | estimated 是否存在语义问题 | **已采用保守规则**：关键用户字段含本地估算则整 leg `estimated=true`；细粒度拆分 DEFER；现有 DB constraint 为 GREEN 门禁 |
| 21 | Web AUTO | **BACKENDIZE**；Python B19-C 是唯一 authority，Web `1.6` 不得用于 decision/preview/fallback |
| 22 | 是否需要 event version bump | **NO**（`v11`/`v2` 已足够） |
| 23 | 是否需要 DB migration | 无 enum/column migration；但 D18 的 `AMAP/true` 被现有 constraint 禁止，constraint-only migration 或等价持久化方案**待显式批准** |
| 24 | Java production 是否需要修改 | **YES**（`ItineraryService.applyTransitLegEdit` + `RouteProviderClient` + Export/PDF/Share label） |
| 25 | Web production 是否需要修改 | **YES**（全来源 `DRIVING` 映射 + 移除自驾入口 + `AUTO` 后端化 + 本地 recommendation 断开 + `TripDetail`/`Share` 展示） |
| 26 | replan 如何兼容 | `TAXI→DRIVING` route 复用（§18）；`TRANSIT` 同城真实 |
| 27 | 历史 DRIVING 如何兼容 | **保留原值**，新展示映射为"打车"；不批量迁移（§25） |
| 28 | immutable/idempotency 如何保证 | 新 version 原子写 + `EditRequestFingerprint` 重放复用 + provider 失败不产半版本（§19） |
| 29 | `B19-B:D1` 最终处置 | **B19-D0 独立小修**：独立 RED→GREEN / commit / acceptance；不与 B19-D1 混 diff |
| 30 | RED | `D1-D19`（§27）；`D17-D19` 为 persisted display / mixed provenance / AUTO authority 三项硬门禁 |
| 31 | Golden | `G1-G8`（§28，`G2` DEFER，其余真实/確定性） |
| 32 | API/latency/budget | §29：per-edit 1-3 calls（AUTO 含 WALKING），`cache` 3600s，`96` 不共享，latency/timeout 见预算表 |
| 33 | rollout | `B19-D0(B19-B:D1)→独立验收→B19-D1 RED→DB 门禁→内网 API→Java edit→Web→Share/PDF→Golden→回归` |
| 34 | rollback | §31：real-routing 可关闭；AUTO 不可回退本地 recommendation；无 roadIntent 时不得把 DRIVING 标签回滚为“驾车” |
| 35 | 主要风险 | §32 10 项（费用三语义/`fare` 无城市化/命名/`estimated` 混合/超时/限流等） |
| 36 | 最小可发布 B19-D | §35 `D-min` 7 项 |
| 37 | plan-d.md 路径 | `docs/execution/B19/plan-d.md`（本文件） |
| 38 | 是否建议进入 RED→GREEN | **B19-D0 YES；B19-D1 RED YES / GREEN 暂缓**，先解决 `AMAP/true` 与 DB constraint 冲突 |

---

> **本阶段最重要的判断**：如何把"真实 road route capability"（`DRIVING`/`TRANSIT` provider）与"用户实际是打车还是自驾"（`TAXI`/`SELF_DRIVING` intent）从语义上分开，同时尽量少做 breaking migration，并让 planner、manual edit、`AUTO`、replan 和 UI 最终只剩一套一致的交通逻辑。
>  本计划答案：**provider 层保持 `DRIVING`（road geometry 单一事实来源）；在没有持久化 `roadIntent` 时，所有 persisted `DRIVING` 的用户语义统一为“打车”，不提供“自驾”入口；manual `TAXI` 用 AMAP road facts + 本地 fare/wait 并保守标记 `estimated=true`；AUTO 只服从 Python B19-C。`B19-D0` 先独立修 `B19-B:D1`，`B19-D1` 在 DB provenance 门禁解决后再进入 GREEN。**

(End of file)
