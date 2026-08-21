# B19-A — Transport Architecture Audit（交通架构审计）

- 审计日期：2026-08-18
- 审计范围：只读审计（未修改任何生产代码、未新增 DB migration、未修改 contract、未实现公交/地铁/mode scoring、未改驾车/打车 UI、未触碰 B18-A/B 已验收代码）
- 分支 / HEAD：`codex/feasibility-foundation` @ `d10e70c`
- 工作区：B15/B16/B17/B18-A/B18-B 在途修改保持原样（79 项变更）；未执行任何 `git reset / restore / checkout . / stash / clean`
- 基线：B18-A PASS（must-visit/recall）、B18-B PASS（Walking/Driving baseline）
- 证据基础：代码精读 + 高德开放平台官方文档 + 真实 API 探针（`C:\Windows\Temp\opencode\b19_transit_probe.py` 等，未提交）

---

## 1. Executive Summary

**当前最大的交通架构缺口**：系统只能产出 `WALKING`（明显可步行）与 `DRIVING`（其它一切）两种 TransitLeg，**不存在真实的公共交通路线能力，也不存在多模式推荐**。具体表现为四层缺失：

1. **Provider 层**：AMAP 适配器只有 walking / driving 两个 endpoint（`_amap_route.py:38-39`），高德官方具备完整公交/地铁 API（v3 transit/integrated，经真实调用验证可用）但完全未接入。
2. **Contract/模型层**：`RouteMode` 只有 WALKING/DRIVING（`_route_contracts.py:16`）；event schema v10 的 `transitLeg.mode` 只允许 `["WALKING","DRIVING"]`；`RoutePlan` 只有 mode/distance/duration/steps/polyline/cost，无法承载换乘次数/线路/站点/步行接驳。
3. **推荐层**：`_route_for_pair`（B18-B）只是"walkable→WALKING，否则 DRIVING"的阈值规则，没有模式比较（无 transit/road 对比、无费用/换乘/体验权衡）。
4. **语义层**：`DRIVING` 是路由技术模式（AMAP driving road route），但 UI 文案"驾车"暗示用户拥有车辆；`TAXI` 是纯本地估算（前端/Java 距离公式），无任何 provider 支持——`DRIVING` 与 `TAXI` 底层是同一 road route 语义的两副面孔。

一句话：**TripPilot 有 "walking/driving 技术路线"，但没有 "公交/地铁能力"，也没有 "road 的用户语义抽象"。**

---

## 2. Current Mode Matrix

以真实代码为准（全仓核对）：

| Layer | WALKING | DRIVING | TAXI | TRANSIT | AUTO | 出处 |
| --- | --- | --- | --- | --- | --- | --- |
| Python `RouteMode`（RouteRequest/RoutePlan.mode） | ✅ | ✅ | ❌ | ❌ | ❌ | `_route_contracts.py:16` `Literal["WALKING","DRIVING"]` |
| AMAP route provider endpoint | ✅（v5/direction/walking） | ✅（v5/direction/driving） | ❌ | ❌ | ❌ | `_amap_route.py:38-39, 73` |
| Python `ItineraryTransitMode`（TransitLeg.mode） | ✅ | ✅ | ✅ | ✅ | ❌ | `worker/contracts.py:659` `Literal["WALKING","TRANSIT","DRIVING","TAXI"]` |
| Planning event schema v10 `transitLeg.mode` | ✅ | ✅ | ❌ | ❌ | ❌ | `contracts/messaging/planning-completed-event-v10.schema.json:645-650` `enum ["WALKING","DRIVING"]` |
| Java parser / domain 白名单 | ✅ | ✅ | ✅ | ✅ | ❌ | `ItineraryService.java:425` `List.of("WALKING","TRANSIT","DRIVING","TAXI")` |
| DB `transit_leg.mode` | ✅ | ✅ | ✅ | ✅ | ❌ | `V7__create_transit_legs.sql:10` `VARCHAR(20)`；`V23__complete_transit_leg_writeback.sql:4-7` CHECK 四值 |
| Web `ConcreteCommuteMode` | ✅ | ✅ | ✅ | ✅ | ❌（AUTO 为 UI 快捷选择器） | `web/src/lib/transit.ts:3` `'WALKING'\|'TRANSIT'\|'DRIVING'\|'TAXI'` |
| Web UI 按钮 | ✅ | ✅ | ✅ | ✅ | ✅ | `TransitLegControl.vue:169` `['AUTO','WALKING','TRANSIT','DRIVING','TAXI']` |
| Web 展示 label | 步行 | 驾车 | 打车 | 公交·地铁 | 自动·{推荐} | `TransitLegControl.vue:94-101, 104-105` |

**关键不一致（B19 必须处理）**：
- **event schema v10 与 Python/Java/DB/Web 不一致**：schema 只允许 `WALKING/DRIVING`，其余层声明 4 值。当前 planner 只产出前两者所以从未触发，未来 PUBLIC_TRANSIT / TAXI 进入 event 必须先升级 schema（v11）。
- **RouteProvider 契约与产品契约割裂**：Python `RouteMode`（2 值，provider 契约）≠ `ItineraryTransitMode`（4 值，产品契约）。B18-B 的 `_route_for_pair` 内部用 `RouteMode`，replan 复用 `ItineraryTransitMode`（`replan_service.py:264`）——扩 mode 必须同时扩两个类型且不能串。

---

## 3. Current Routing Architecture

```
planner (_plan_with_skeleton / _emit_day)
  │ 每个相邻 activity pair
  ▼
_route_for_pair (planning_provider.py:1642)          ← B18-B 模式决策（唯一出口）
  │  haversine ≤1500m → _try_walking_route(WALKING)
  │    └ walking ≤1200s → 返回 walking route
  │    └ walking 超阈值/可降级失败 → DRIVING
  │  haversine >1500m → DRIVING
  ▼
_route_cached (planning_provider.py:1721)            ← cache key=(poiId×2, mode, departure_at.isoformat())
  │  budget: MAX_ROUTE_CALLS_PER_PLAN=96 (domain/shared.py:41)
  ▼
_route (planning_provider.py:1601)                   ← provider 调用 + fallback policy
  │  ProviderFailure → FallbackPolicy（REAL_ONLY 下 raise / REAL_WITH_EXPLICIT_FALLBACK 下 DEMO）
  ▼
AmapRouteProvider.get_route (_amap_route.py:57)      ← v5 walking / v5 driving endpoint
  ▼
RoutePlan (mode/distance/duration/steps/polyline/estimated_cost)
  ▼
_leg_from_route (planning_provider.py:1303)          ← 单一 route 对象逐字段映射（facts 单一来源）
  ▼
TransitLeg (mode/distance/duration/polyline/cost/provider/estimated)
  ▼
PlanningCompletedEvent（contracts v10，schema 校验）→ MQ
  ▼
Java PlanningCompletedEventParser → ItineraryService → DB transit_leg
  ▼
Web TripDetail.transitModeFor(leg) → TransitLegControl 显示
```

**关键架构事实**：
- forward-fit timing（`_emit_day:1119-1135`）与 fixed-slot validation（`_fixed_slot_timing_error:1187`）**使用选中的 `route.data.duration_seconds`**——B17/B18 已建立"真实 route duration 驱动 timing"。任何新 mode（transit）的 duration 必须能进入这条链路。
- 活动 kind（`domain/shared.py:26-28`）含 `ARRIVAL/DEPARTURE/ACCOMMODATION/MEAL/ATTRACTION/EXPERIENCE`；transit leg 两端可区分「酒店→景点」「景点→机场」等语义（Agent 审计确认）。
- 历史 DB 中 34 条 leg 全为 DRIVING（B18-B 前硬编码所致）。

---

## 4. AMAP Public Transit Capability

**Endpoint（官方）**：`GET https://restapi.amap.com/v3/direction/transit/integrated`

### 4.1 请求参数（官方文档）

| 参数 | 说明 | 必填 |
| --- | --- | --- |
| origin / destination | 经纬度 `lon,lat`，6 位小数 | 是 |
| **city** | 起点城市名/citycode（**市内公交换乘必须**） | 是 |
| **cityd** | 跨城规划时的终点城市 | 跨城必填 |
| **strategy** | 0 最快捷 / 1 最经济 / 2 最少换乘 / 3 最少步行 / 5 不乘地铁 | 否（默认 0） |
| **nightflag** | 是否计算夜班车 0/1 | 否 |
| **date / time** | 出发日期/时间，筛选班次 | 否（**time-dependent**） |
| extensions | base（默认）/ all（返回全部含火车/仓位） | 否 |
| output / sig / callback | 格式/签名/回调 | 否 |

### 4.2 返回结构（官方 + 真实调用验证）

`route.taxi_cost`（出租车参考价）+ `transits[]`（**多条完整方案**，真实调用 count 3-5）：

| 字段 | 说明 | 真实证据 |
| --- | --- | --- |
| `cost` | 方案费用（元） | T1=2.0、T3=4.0、T5=9.0 |
| `duration` | 总耗时（秒） | T2=1250（APM 线方案） |
| `walking_distance` | 步行接驳总距离（米） | T5=2981 |
| `distance` | 总距离（米） | T3=9421 |
| `nightflag` | 是否含夜班车 | 0 |
| `segments[]` | 分段：`walking`（steps：instruction/polyline）+ `bus`（buslines[]）+ `taxi` | T5=5 段 |
| `buslines[].name` | 线路名（含方向），如 "地铁1号线(广州东站--西塱)"、"空港2路(长线)…" | 真实返回 |
| `buslines[].type` | 线路类型：**地铁线路/普通公交线路/快速公交系统/机场大巴/火车** | 真实返回 |
| `buslines[].departure_stop / arrival_stop` | 上/下车站名 + 站点 id + 坐标 | 真实返回 |
| `buslines[].duration / distance / polyline / start_time / end_time / via_stops` | 每段公交/地铁信息 | 官方文档 |
| （extensions=all）火车 alters/spaces/仓位费用 | 火车换乘 | 官方文档 |

### 4.3 能否判断"主要是地铁/公交"

**能**。每方案 `segments[].bus.buslines[].type` 明确标记 `地铁线路` / `普通公交线路` / `快速公交系统` / `机场大巴`；结合 `walking_distance` 占比与换乘段数（`segments` 长度）可计算"地铁主导 / 公交主导 / 混合"。

### 4.4 配额 / 限流

- 官方文档未披露 transit 与 walking/driving 的配额共享关系（不编造数字）。
- **真实调用**：本审计对 T1/T2/T3/T5 共 4 次 transit 调用**全部成功、0 限流**（同 key 的 walking/driving route API 此前曾触发配额限流）。观察提示 transit 接口配额表现与 route 接口不同，但**不足以下"独立配额"结论**。
- 与现有 walking/driving 同一 `key`（AMAP_WEB_SERVICE_KEY），`sig` 签名机制可共用。

---

## 5. Public Transit Data Gap

对比 AMAP transit 返回 vs 当前 `RoutePlan` / `TransitLeg`：

| 能力 | AMAP transit 返回 | RoutePlan | TransitLeg | 缺口 |
| --- | --- | --- | --- | --- |
| 总时长 | ✅ duration | ✅ duration_seconds | ✅ | 无 |
| 总距离 | ✅ distance | ✅ distance_meters | ✅ | 无 |
| 费用 | ✅ cost（元） | ✅ estimated_cost | ✅ | 无 |
| polyline | ✅ 每段+每线 | ✅ 单条 polyline | ✅ | 换乘分段 polyline 会被压平 |
| **换乘次数** | ✅ segments 数量 | ❌ | ❌ | **缺失** |
| **线路名** | ✅ buslines[].name | ❌ | ❌ | **缺失** |
| **线路类型** | ✅ buslines[].type（地铁/公交/BRT/机场大巴） | ❌ | ❌ | **缺失** |
| **站点** | ✅ departure/arrival_stop | ❌ | ❌ | **缺失** |
| **步行接驳** | ✅ walking_distance + segments | ❌（steps 是步行/驾车混合段，无语义标注） | ❌ | **缺失** |
| **分段 mode** | ✅ 每 segment 步行/公交/地铁 | ❌ | ❌ | **缺失** |

**结论**：现有 `RoutePlan` 无法承载公共交通的结构化信息（换乘/线路/站点/步行接驳/分段 mode）。若第一版只保存 flat leg（总时长/总距离/总费用/polyline），`RoutePlan` 只需新增 `PUBLIC_TRANSIT` mode + 可选 detail 字段；若保存 segments，需要新模型（见 §10）。

---

## 6. DRIVING / TAXI Semantic Audit

### DRIVING（真实技术语义）
- 技术本质：**AMAP v5 driving road route**（`_amap_route.py:39, 73`），返回真实路线/时长/距离/过路费估算（`estimated_cost`）。
- 产品语义：UI 文案"驾车"（`TransitLegControl.vue:98`）。**系统不存在任何车辆归属信息**——TripConstraints 无 selfDriving/hasCar/rentalCar/transportPreference/vehicle 字段（`worker/contracts.py:167-185`、`TripConstraintRecord.java:7-26`、`TripRequests.java:74` 全无）。
- **domain/UX 语义错位**：`DRIVING` 是路由技术模式（road route），但"驾车"暗示用户拥有/驾驶车辆。对自由行用户，展示"驾车"与实际出行方式（打车/网约车）不符。

### TAXI（真实技术语义）
全链路追踪（Agent 审计 + 代码）：
- **无任何 Python route provider**（全仓零命中 TAXI endpoint）。
- Web：`lib/transit.ts:58-60` 估算 `TAXI duration = drivingDuration + 120`（8.33m/s + 2 分钟等待）、`cost = 12 + km×2.6`；`TransitLegControl.vue` 点击 TAXI 后 emit 具体 mode。
- Java：`ItineraryService.applyTransitLegEdit:583-603` 手动编辑时 `TAXI duration = distance/8.33 + 300`（605-614）、`cost = 12 + km×2.6`（616-626）；**polyline 清空、provider="DEMO"、estimated=true、providerRouteId=null**（597-602）；**不调用任何真实 provider**。
- 持久化：leg 复制进新版本（versionSource=USER_EDIT），DB `transit_leg.mode='TAXI'`。

### DRIVING 与 TAXI 底层关系
- **同一 road route geometry**（距离/路线来自 driving/估算），差异仅在 duration 加成（+120s/+180s 等待）与费用模型（km×0.8 vs 12+km×2.6）。
- **结论**：`TAXI` 不是独立交通模式，而是建立在 **road route** 上的费用/展示语义。这验证了 B18 审计的预判（"DRIVING 与 TAXI 是同一路线 + 不同费用/时长参数"）。

---

## 7. User Constraint Capability

| 输入 | 是否存在 | 当前用途 | 是否可复用于 mode recommendation |
| --- | --- | --- | --- |
| selfDriving / hasCar / rentalCar | ❌ 无 | — | 需新增（决定"驾车"是否对用户有意义） |
| transportPreference | ❌ 无 | — | 需新增（是否优先公交/打车/步行） |
| mobilityLevel | ✅ `contracts.py:180`（STANDARD/REDUCED/STEP_FREE） | `planning_provider.py:486` `mobility_reduced` → `_mobility_repair_candidate`（`:900`，`_REDUCED_MOBILITY_MAX_HOP_METERS=3000` 按 leg 距离剔除） | 可复用：LOW/REDUCED 应降低步行/换乘权重（当前只做距离筛选，未进 mode 决策） |
| pace | ✅ `contracts.py` | `daily_schedule.py:63-67` BUFFER（20/12/8min）、`:315`、`_fill_slots` | 部分可复用（影响时间预算，不直接约束 mode） |
| 天气（rain/temp） | ✅ guide_evidence.facts（WEATHER） | `_non_weather_guide_statements` 只在 ranking 用（`planning_provider.py:394` 显式排除 WEATHER）；`weather_statements_for_date` 在 src 无调用（仅测试） | **架构条件已具备**（`_emit_day` 持有 command，可访问 facts），但尚未接入交通阶段 |
| arrival/departure/accommodation | ✅ ActivityKind + anchors（`_resolve_travel_anchors:1432`） | 行程结构 | 可复用：区分「酒店→景点」「景点→机场」等场景（影响行李/赶车推荐） |

**结论**：系统**没有自驾约束**、**没有交通偏好字段**；`mobilityLevel` 是最接近的可复用信号（当前只做距离筛选）。未来 recommendation 需要**新增用户约束**（自驾与否、是否接受换乘、打车偏好），且 `mobilityLevel`/天气/出行场景应纳入 mode 决策输入。

---

## 8. Recommendation Placement（推荐层）

| 方案 | 优势 | 风险/约束 |
| --- | --- | --- |
| **A：Python Planner（推荐）** | ① forward-fit timing/fixed-slot/capacity repair 已建立在**真实 route duration** 之上（B17/B18 架构），planner 内推荐可让 timing 使用最终推荐 mode 的 duration；② 结果经既有 event→Java→DB→Web 链路天然持久化 | provider 调用增多（多 mode 查询），需 staged querying 控制预算 |
| B：Java | Python 产出活动、Java 决定 commute | **会破坏 timing feasibility**：Python forward-fit 无法预知最终 transit duration，B17/B18 的容量/固定时段校验失去意义 |
| C：Frontend | 仅 UI 推荐 | 若 planner timing 仍按 DRIVING 而 UI 显示 TRANSIT，计划时间与实际交通不一致（B19 产品问题 1 的根源会复现） |

**推荐：方案 A（Python planner）**。理由不是偏好，而是架构约束——B17/B18 已把"真实 route duration 驱动 timing"固化在 `_emit_day`/`_route_for_pair` 中，只有 planner 知道最终选择的 mode 及其 duration。Java/Frontend 推荐都无法保证计划可行性。

---

## 9. Route Budget / Cache Impact

### Budget 估算（基于真实规划结构）

| 场景 | 平均 transit legs | 现状（B18-B，1-2 次/leg） | 3-mode 全查（WALKING+TRANSIT+DRIVING） | 触 96 上限风险 |
| --- | --- | --- | --- | --- |
| 2 日 | ~6-9 | ~6-12 | 18-27 | 低 |
| 3 日 | ~10-15 | ~10-20 | 30-45 | 低 |
| 5 日 | ~15-25 | ~15-40 | 45-75 | **中**（接近 96） |
| 7 日（MAX_TRIP_DAYS） | ~22-35 | ~22-70 | 66-105 | **高**（超 96） |

**结论**：无脑每 leg 3-mode 全查在 5 日以上行程可能耗尽 `MAX_ROUTE_CALLS_PER_PLAN=96`（`domain/shared.py:41`，`_route_cached:1730` 超限 raise）。**必须采用 staged / lazy querying**（§「候选策略」），如：极短→walking only；中距离→transit + road；超长/机场→road（+transit 按需）。

### Cache 影响
- 现有 key = `(origin_poi_id, destination_poi_id, mode, departure_at.isoformat())`（`_route_cached:1721-1726`）。
- **transit 必须扩展 key**：加 `city`（或 adcode）+ `strategy`；且因 `date/time` 影响班次，**departure_at 不再是可选附加而是强相关**（同一 pair 不同时段班次/夜班不同）。
- 结论：`PUBLIC_TRANSIT(A,B)` 不能直接复用现有 key——不同 city/strategy/出发时间的 transit 结果会串缓存。

---

## 10. Public Transit MVP Options

| 方案 | 内容 | 优点 | 缺点 | 评估 |
| --- | --- | --- | --- | --- |
| **A：flat TransitLeg** | `mode=PUBLIC_TRANSIT`，只存总时长/总距离/总费用/polyline（provider 全段 polyline 压平） | 模型改动最小；timing/cost 链路复用；`RoutePlan` 只加一个 mode 值 | 丢失换乘次数/线路/站点——UI 无法展示"地铁3号线→1号线"，体验退化为"公交·地铁 45 分钟" | **第一版可行**（见 UI 能力 §「Web 展示」：当前 UI 只显示 mode+duration+distance+cost，flat 已够） |
| B：segment-rich | TransitLeg 扩展 segments（每段 mode/线路/站点/时长/步行接驳） | 可展示线路/换乘；推荐可用 transfer_count | 新模型 + event schema v11 + Java/DB/Web 大改 | 第二版（B19-C 需要 transfer_count 时可引入 metadata 承载） |
| C：metadata JSON | `RoutePlan`/`TransitLeg` 增加可选 detail（如 raw segments JSON） | 快速承载富数据，不改表结构 | 无类型安全；Java/Web 解析脆弱 | 过渡手段，不建议作为长期方案 |

**建议路径**：B19-B 用 **A（flat）** 打通 provider→timing→event→Java→DB→Web 全链路；B19-C 做推荐需要 `transfer_count`/`walking_burden` 时，先通过 flat leg 的**可选项扩展**（或最小 segments 字段）补齐，避免一次引入完整 segment 模型。

---

## 11. Manual Edit Consistency Risk

**现状**（Agent 审计确认）：
- 用户手动切换任意 mode（含"公交/地铁"）→ 前端 `estimateCommuteOptions` 本地估算 → `TripDetail.updateTransitLeg` → `POST /api/trips/{id}/itinerary/edits/commit` → **Java `applyTransitLegEdit` 纯内存估算**（`TRANSIT duration = distance/5.5+420`、`cost=2+⌊km/6⌋`），**polyline 清空、provider="DEMO"、estimated=true，不调用任何真实 provider**（`ItineraryService.java:583-626`）。
- 前端估算与 Java 估算**两套公式并存**（如 TAXI：前端 +120s，Java +300s）——本身就是漂移源。

**B19 风险**：B19-B 后 planner 产出真实 transit（真实 duration/cost/polyline），但用户手动点"公交/地铁"仍是 Java 假估算 → **planner 真实 transit 与手动编辑假估算 transit 严重不一致**（时间/费用/几何都对不上）。

**架构建议**：手动编辑链路也应支持"回到 planner/provider 重算"（至少对 transit 模式），或明确接受估算并保持估算公式单一来源（Python 估算函数 vs Java 估算函数收敛）。

---

## 12. UI Semantics

### 当前驾车/打车按钮
`TransitLegControl.vue:169`：`['AUTO','WALKING','TRANSIT','DRIVING','TAXI']` 五按钮；label 步行/公交·地铁/驾车/打车。

### 收敛方案评估（仅设计，不实施）

| 方案 | 结构 | 开发成本 | 用户理解 | 领域一致性 |
| --- | --- | --- | --- | --- |
| **UI A**：`推荐 / 步行 / 公交·地铁 / 汽车` | 点击"汽车"内部决定打车/自驾 | 中（需底层 road 语义） | 好（自由行默认打车语义） | 需先定义 ROAD 抽象 |
| **UI B**：`推荐 / 步行 / 公共交通 / 打车·驾车` | 直接合并 TAXI+DRIVING | 低（纯按钮合并） | 中（"打车·驾车"模糊） | 弱（两语义合并） |
| **UI C**：有自驾声明→"驾车"，否则→"打车"，底层均 DRIVING route | 用约束驱动展示 | 低-中 | 好（贴近真实自由行） | 需新增自驾约束 |

**推荐方向**：以 **UI C 为核心 + UI A 的"汽车"折叠**为长期目标——先解决"无车用户看到'驾车'"的语义错位（需新增自驾驶别），再考虑按钮合并。**本轮不改 UI。**

---

## 13. Golden Matrix（未来 B19-B/C 设计候选，不实施）

| ID | 场景（真实广州） | 期望 | 数据依据 |
| --- | --- | --- | --- |
| G1 | 步行 8min / 汽车 4min（如体育中心→正佳 218s vs ~120s） | WALKING | B18-B 校准：623m→218s walking |
| G2 | 步行 35min / 地铁 18min / 汽车 27min（如正佳→广州塔） | PUBLIC_TRANSIT | 本审计真实探针：transit 1250s/2元 vs driving 1632s vs walking 3602s |
| G3 | 地铁 45min/3 换乘 vs 汽车 20min（如正佳→机场 transit 3.4h/5段 vs driving 61min） | ROAD（transit 换乘负担过高） | 本审计 T5：transit 12139s/5 段 vs driving 3682s |
| G4 | 地铁 25min vs 汽车 18min，费用差显著 | 由策略决定（cost/体验权重） | 需 B19-C 定义权重 |
| G5 | 机场/大行李/固定返程（DEPARTURE 场景） | 倾向 ROAD | ActivityKind 可识别（架构已具备） |
| G6 | mobility constrained（REDUCED） | 降低 walking/transfer 权重 | mobilityLevel 可复用（当前只做距离筛选） |

**候选第一版规则**（需 Golden 校准，不写死）：
- walking ≤1200s → WALKING（既有）
- 否则比较 PUBLIC_TRANSIT vs ROAD：
  - `transit <= road × X` 且 `transfer_count ≤ N` 且 `transit_walking ≤ W` → PUBLIC_TRANSIT
  - 否则 → ROAD
- X / N / W 需用 G1-G6 类真实 Golden 校准，同时受用户约束（mobility/自驾/偏好）修正。

---

## 14. Recommended Batch Breakdown

| 批次 | 内容 | 说明 |
| --- | --- | --- |
| **B19-A（本批）** | 审计 / 架构设计 | 已产出 |
| **B19-B** | Public Transit Provider + contract/domain 最小接入 | AMAP transit adapter（flat leg）、`RouteMode` 扩 `PUBLIC_TRANSIT`、event schema v11（mode enum 扩值）、Java/DB/Web 兼容、forward-fit 接入 transit duration、staged querying 第一版（transit + road）、route cache 扩 key（city/strategy） |
| **B19-C** | Multi-mode Recommendation | 模式比较规则（duration/cost/transfer/walking burden）+ 用户约束（mobility/天气/场景）+ Golden 校准 |
| **B19-D** | Road / Taxi / Self-driving 语义 + UI 收敛 | `ROAD` 领域抽象（底层仍 DRIVING）、自驾约束、驾车/打车 UI 收敛 |

**说明**：B19-B 先行打通 provider 与全链路（不引入推荐），B19-C 在真实 transit 数据之上做推荐，B19-D 处理产品语义与 UI。该拆分使每批可独立验收（与 B18-A/B 的模式一致）。

---

## 15. Files Involved（未来批次，本轮未修改）

**Python（apps/agent-service/src/trip_agent/）**
- `providers/_route_contracts.py` — RouteMode 扩 PUBLIC_TRANSIT、RoutePlan 可选扩展
- `providers/_amap_transit.py`（新）或 `_amap_route.py` 扩展 — v3 transit/integrated adapter
- `providers/errors.py` — transit 错误分类（若需）
- `infrastructure/amap/planning_provider.py` — `_route_for_pair` 加 transit 分支、cache key 扩 city/strategy、staged querying
- `planning/transit_mode.py` — 推荐规则（B19-C）
- `application/replan_service.py` — PUBLIC_TRANSIT 复用兼容
- `worker/contracts.py` — ItineraryTransitMode 已是 4 值（若加 PUBLIC_TRANSIT 需新增值）

**Contract**
- `contracts/messaging/planning-completed-event-v11.schema.json`（新）— transitLeg.mode enum 扩值

**Java（apps/travel-server/）**
- `infrastructure/mq/PlanningCompletedEventParser.java` — v11 解析
- `itinerary/ItineraryService.java` — 白名单加 PUBLIC_TRANSIT、手动编辑估算策略

**DB**
- 新增 migration（若 flat leg 无新列则无需；若加 detail/segment 字段则需 V38）

**Web（apps/web/src/）**
- `lib/transit.ts` — 模式估算对齐
- `components/TransitLegControl.vue` / `TripDetail.vue` — 展示与 UI 收敛（B19-D）

---

## 16. Risks

| 风险 | 等级 | 说明 / 缓解 |
| --- | --- | --- |
| **API call amplification** | 高 | 每 leg 3-mode 全查在 5 日+ 行程超 96 预算（§9）。缓解：staged/lazy querying，先粗筛再按需查。 |
| **transit cache correctness** | 高 | transit 结果依赖 city/strategy/出发时间；现有 key 不含 city/strategy → 必须扩 key，否则串缓存。 |
| **time-dependent routing** | 高 | AMAP transit 支持 date/time 筛选班次、nightflag 夜班；同一 pair 不同出发时间结果不同 → 影响 planning reproducibility；规划产出与未来"按班次执行"需标注快照时间。 |
| **contract compatibility** | 高 | event schema v10 只允许 WALKING/DRIVING；PUBLIC_TRANSIT/TAXI 进 event 必须 v11 schema（新版本向后兼容，旧版本只读）。 |
| **stored old itinerary compatibility** | 中 | 历史 34 条 DRIVING leg 与既有 versions 只读展示，不受影响；transit leg 的 polyline 换乘压平后仅视觉信息。 |
| **manual edit inconsistency** | 高 | planner 真实 transit vs Java 手动编辑假估算（DEMO/estimated）→ 时间/费用/几何不一致（§11）。缓解：编辑链路支持 provider 重算或公式单一来源。 |
| **route fact integrity** | 中 | flat transit leg 必须保证 mode/duration/distance/cost/polyline 全部来自同一次 transit 响应（沿用 B18-B `_route_for_pair` 单一出口原则）。 |
| **UI enum compatibility** | 中 | Web `ConcreteCommuteMode` 需加 PUBLIC_TRANSIT 或映射为既有 TRANSIT；`PlanningReviewPanel.vue:161` 已有 `?? mode` 兜底，`TransitLegControl.vue` 无兜底（未知值渲染 undefined）→ 需处理。 |
| **provider quota** | 中 | 同一 key；本审计 4 次 transit 调用成功但 route API 曾限流；transit 与 route 配额关系官方未披露 → B19-B 需在真实配额下评估，必要时扩 key/降级策略。 |
| **导出/展示 fallback** | 低 | PDF 输出原生英文 `Transit {mode}`（`ItineraryExportService.java:77-81`），ICS 不含 leg；PUBLIC_TRANSIT 会增加一个英文枚举展示，需补 label 映射。 |
| **evaluation 缺 mode 质量分** | 中 | 现有 `routeEfficiency`（`evaluation/scoring.py:12`，权重 15%）与 `route_warnings`（`rules.py:340`，已含 LONG_WALKING）无 per-mode 质量分；B19 需定义"多模式推荐是否变好"的自动度量。 |

---

## 17. Open Questions

仅保留无法从代码/官方资料确认的问题：

1. **AMAP transit 与 route（walking/driving）接口的配额关系**：官方文档未披露是否共享配额/单独计费。B19-B 实施时需在真实配额下测量（当前证据：transit 4 次成功、route 曾限流，提示可能独立，但非定论）。
2. **AMAP transit 的 `transit_mode` 字段**（base 模式下为空）：该字段在何种条件下返回（extensions=all？）官方文档未明确——影响"地铁主导/公交主导"判定是否可以直接用该字段，还是必须从 buslines.type 推断。
3. **v5 transit endpoint 是否存在**：`restapi.amap.com/v5/direction/transit/integrated` 在第三方代码中出现，但高德官方文档（lbs.amap.com）当前仅列 v3；需在 B19-B 实施时用真实 key 验证 v5 可用性，优先以官方 v3 为准。

已确认、无需用户回答的问题（列出以免误解）：DRIVING 无自驾语义、TAXI 无 provider、event schema v10 仅 2 值、AUTO 仅前端、天气输入架构已具备但未接入、mobilityLevel 当前只做距离筛选——以上均有代码/文档/实测证据，直接进入 B19-B/C/D 设计即可。

---

## 附：真实数据采集证据

脚本（均未提交，位于 `C:\Windows\Temp\opencode\`）：
- `b19_transit_probe.py` — AMAP v3 transit/integrated 真实调用（T1/T2/T3/T5，4 次，0 限流）
- 补 driving/walking 对比查询（T2/T5，各 2 次，0 限流）

| Case | Pair | WALKING | PUBLIC TRANSIT | DRIVING |
| --- | --- | --- | --- | --- |
| T1 极短 <1km | 正佳→体育中心 | 218s（B18-B 校准 623m） | 1453s / 2.0元 / 步行756m / 公交 | — |
| T2 城市中距 3.4km | 正佳→广州塔 | 3602s / 4502m | **1250s / 2.0元 / 步行654m / APM线地铁** | 1632s / 6085m |
| T3 城市跨区 9.4km | 正佳→陈家祠 | — | 1569s / 4.0元 / 步行571m / **地铁1号线** | — |
| T5 景点→机场 42.6km | 正佳→白云机场 | 27958s / 34947m | 12139s / 9.0元 / 步行2981m / 5段（BRT+公交+机场大巴） | 3682s / 38972m |

**关键实证**：T2 即产品问题 1 的原型——地铁 21 分钟（2 元）优于汽车 27 分钟；当前系统会无脑选 DRIVING（1632s）。
