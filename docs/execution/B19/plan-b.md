# B19-B Public Transit Provider Plan（TRANSIT Provider + v11 全链路）

- 计划日期：2026-08-18
- 基线：`docs/execution/B19/audit.md`（审计事实，本计划不复述审计全文）、B18-A/B 已 PASS（本计划不重新打开）
- 分支 / HEAD：`codex/feasibility-foundation` @ `d10e70c`
- 工作区：B15/B16/B17/B18-A/B18-B/B19-A 在途修改保持原样（80 项变更）；**本阶段未修改任何生产代码 / contract / DB / UI**
- 状态：**计划阶段，未开始实施**。本计划形成后可进入 RED→GREEN 实施

---

## 1. Scope

### 做什么（B19-B 唯一目标）

> 让 `TRANSIT` 成为与 WALKING / DRIVING 一样可信的**真实 Provider Route 能力**，并能安全穿过 Python → event → Java → DB → Web 全链路。

| # | 内容 |
| --- | --- |
| 1 | Python AMAP TRANSIT route provider（`v3/direction/transit/integrated`） |
| 2 | `RouteRequest` / `RoutePlan` 支持 `mode="TRANSIT"` |
| 3 | TRANSIT 请求的 `city` / `strategy` / `nightflag` / `departure_at` 映射 |
| 4 | TRANSIT cache identity（含 city / strategy / departure bucket） |
| 5 | TRANSIT response parsing（flat facts + recommendation metadata） |
| 6 | planning event **v11** contract（completion v11 + review v2） |
| 7 | Java v11/v2 parser 与兼容 |
| 8 | DB / Java / Web 现有 TRANSIT 能力复核（不改生产代码） |
| 9 | TRANSIT 全链路测试 |

### 不做什么（明确排除）

```text
自动 multi-mode recommendation、每 leg 自动三模式查询、mode scoring、公交 vs taxi 自动推荐
用户交通偏好、self-driving constraint、ROAD enum migration、删除 DRIVING/TAXI
驾车/打车 UI 合并、复杂公交换乘 UI、完整线路详情持久化
B18-C diversity、B18-D parent dedup、staged/lazy querying（B19-C）
```

普通 planner（`_route_for_pair`）行为**保持不变**——B18-B 的 walkable→WALKING / 否则 DRIVING 语义不因本批改变。`RouteRequest(mode="TRANSIT")` 是**显式能力**，只有显式请求才产生 transit route call（§21 门禁）。

## 2. Verified Baseline（复核后的关键代码事实）

| 事实 | 证据 |
| --- | --- |
| `RouteMode = Literal["WALKING","DRIVING"]`（provider 契约） | `_route_contracts.py:16` |
| `RouteRequest`：origin/destination/mode/departure_at/origin_poi_id/destination_poi_id（**无 city/strategy**） | `_route_contracts.py:24-36` |
| `RoutePlan`：mode/distance/duration/steps/polyline/estimated_cost（**无 walking_distance/transfer_count**） | `_route_contracts.py:46-52` |
| `ItineraryTransitMode = Literal["WALKING","TRANSIT","DRIVING","TAXI"]` | `worker/contracts.py:659` |
| **Python 生产写 completion `schema_version=10`** | `worker/processor.py:186, 283, 378` |
| **Java 接受 completion v9/v10**；transitLeg mode **只校验 `isTextual()`，不枚举** | `PlanningCompletedEventParser.java:97, 306-321` |
| Java review parser **只接受 v1** | `PlanningReviewRequiredEventParser.java:100` |
| **completion v10 与 review v1 的 transitLeg.mode 均为 `["WALKING","DRIVING"]`** | `planning-completed-event-v10.schema.json:645-650`、`planning-review-required-event-v1.schema.json:634-638` |
| **DB `business.transit_leg.mode` CHECK 已含 `('WALKING','TRANSIT','DRIVING','TAXI')`** | `V23__complete_transit_leg_writeback.sql:5-8` |
| Java mode 白名单已含 TRANSIT（4 值） | `ItineraryService.java:425` |
| Web `ConcreteCommuteMode` 已含 TRANSIT；label `TRANSIT:'公交/地铁'`；5 按钮含 TRANSIT | `web/src/lib/transit.ts:3`、`TransitLegControl.vue:97, 169` |
| replan 复用 `existing_leg.mode` 透传 RouteRequest（**无 city**） | `replan_service.py:262-277` |
| AMAP transit 官方 endpoint 与参数（B19-A 实测 4 case 成功） | `docs/execution/B19/audit.md` §4 |

## 3. RouteMode Design

**决策：复用 `TRANSIT`，不新增 `PUBLIC_TRANSIT`。**

- domain（`ItineraryTransitMode`）、Java 白名单、DB CHECK、Web TS union 均已存在 `TRANSIT`——新增 `PUBLIC_TRANSIT` 会形成两套重复概念，且波及 DB/Java/Web 全部层。
- 扩展 `_route_contracts.py:16`：

```python
type RouteMode = Literal["WALKING", "DRIVING", "TRANSIT"]
```

- 用户显示保持"公交/地铁"（`TransitLegControl.vue:97` 既有 label），领域 mode 为 `TRANSIT`。

## 4. AMAP Transit Provider Design

新模块 `apps/agent-service/src/trip_agent/providers/_amap_transit.py`（与 `_amap_route.py` 同层，独立 adapter，**不复制 walking/driving 逻辑**）。

### 4.1 Request Building

```
GET https://restapi.amap.com/v3/direction/transit/integrated
params:
  key          AMAP_WEB_SERVICE_KEY
  origin       "lon,lat"（6 位小数）
  destination  "lon,lat"
  city         起点城市（必填；来源见 §6）
  cityd        终点城市（可选；跨城预留，第一版同城为主）
  strategy     0（最快捷；第一版固定 0，见 §4.3）
  nightflag    0（第一版固定 0）
  date         departure_at.date().isoformat()（如 2026-08-20）
  time         departure_at.strftime("%H:%M")（如 09:00）
  extensions   base
  output       JSON
```

### 4.2 Response Parsing（第一版）

解析 `route.transits[]`（多方案）→ 取 **`transits[0]`**（见 4.3）→ 输出：

| RoutePlan 字段 | 来源 |
| --- | --- |
| `mode="TRANSIT"` | 固定 |
| `duration_seconds` | `transit.duration`（总耗时，秒） |
| `distance_meters` | `transit.distance`（总旅程距离，米——**非 haversine 冒充**） |
| `estimated_cost` | `transit.cost`（元；空/缺失 → None，**不写 0**） |
| `polyline` | 各 `segment` 的 polyline 按序拼接（见 §12 用户要求 → 本 plan §4.4） |
| `steps` | 每条 `segment.walking.steps` / `bus.buslines[].polyline` 转 `RouteStep`（instruction=线路名或步行说明） |
| `walking_distance_meters`（新 metadata） | 顶层 `transit.walking_distance`；缺失则回退 `sum(segment.walking.distance)`；再缺失 → None（不发明 0） |
| `transfer_count`（新 metadata） | `公共交通 vehicle segments 数 - 1`（**排除 walking segment**，见 §6「transfer_count 定义」） |
| `provider="AMAP"` / `estimated=false` | 固定（真实 provider route，非估算） |

### 4.3 Alternative Selection（第一版）

**策略：官方 `strategy=0`（最快捷）+ `transits[0]`。**

- 依据：官方文档明确 `strategy=0` 即"最快捷模式"；`transits` 数组由官方按请求策略排序，取第一条是稳定、可解释、少变量的选择。
- **不做**跨 mode 比较（那是 B19-C）；本选择只解决"显式请求 TRANSIT 时 provider 内部选哪个方案"。
- 测试锁定：多方案 fixture 下总是选 transits[0]（T6）。

### 4.4 Polyline 拼接策略

AMAP transit 是多 segment 路线（walking 段 + bus/metro 段，各自 polyline）。

- **规则**：按 `segments[]` 顺序遍历，每段取 `walking.polyline` 或 `bus.buslines[].polyline`（若该 bus segment 有多条 busline，取第一条），**顺序拼接**为单条 polyline。
- **边界处理**：
  - segment 无 polyline → 跳过该段（不中断拼接）；
  - 相邻段重复端点（上段终点 == 下段起点）→ 去重，避免自交折返；
  - 全部缺失 → `polyline` 退化为 `(origin, destination)` 两点（与现有 DEMO/fallback 行为一致，仍满足 `TransitLeg.polyline` min_length=1 契约）。
- **不引入 GIS 模型**：不插值、不简化、不做拓扑清理。
- 测试：T3（含 walking+bus 段的 fixture 断言拼接顺序与去重）。

### 4.5 Error Mapping

**复用现有 `ProviderErrorCategory` 与 mapper，不建第三套逻辑。**

| AMAP transit 返回 | 映射 |
| --- | --- |
| HTTP ≥400 / `status=0` | `PlanningProviderError.from_failure(...)`（复用 `_amap_route` 的 AmapRouteFailures 同类构造，或共享 helper） |
| `status=1` 但 `transits` 为空 | `ProviderFailure(error_code="ROUTE_NOT_FOUND", category=NO_RESULT)`（**不生成假路线、不 fallback DRIVING 冒充**，§52 用户要求） |
| timeout / network | `PROVIDER_TIMEOUT` / `PROVIDER_NETWORK_ERROR`（TIMEOUT / NETWORK_ERROR） |
| `city` 缺失（编程错误） | `ValueError`（provider 层契约校验，属编程错误，不映射为 provider failure） |

TRANSIT 失败**不得**在 provider 层偷偷返回 DRIVING route——Provider query 与 recommendation/fallback 职责分离，mode fallback 属 B19-C。

## 5. RoutePlan Design

- `RoutePlan` 新增 **optional** metadata 字段（`_route_contracts.py:46-52`）：

```python
walking_distance_meters: int | None = Field(default=None, ge=0)
transfer_count: int | None = Field(default=None, ge=0)
```

- WALKING / DRIVING 默认 `None`（不破坏现有构造与测试）。
- **`TransitLeg` 保持 flat**（mode/duration/distance/polyline/cost/provider/estimated 原字段，不新增 segment/线路/站点持久化）——metadata 只在 provider `RoutePlan` 层存在，供 B19-C 推荐使用，本批不落 DB。
- `TransitLeg.estimated_cost` 语义：provider actual cost 优先（AMAP `transit.cost`）；缺失 → `None`（contracts.py:672 `JsonDecimal | None` 已允许），**不写 0**（不把未知误表示成免费）。

### transfer_count 定义

```
transfer_count = (transit 方案中公共交通 vehicle segment 数量) - 1
```

- vehicle segment = 含 `bus.buslines` 的 segment；**walking 段不计**。
- 例：`walking → metro → walking transfer → bus → walking` = 2 个 vehicle segment → `transfer_count = 1`。
- 官方 `segments.length - 1` 会误把 walking 段当换乘，**不使用**该算法。

## 6. Time-Dependent Request Design

| 参数 | 来源 | 说明 |
| --- | --- | --- |
| `city`（起点城市） | **`command.payload.trip.destination`**（planner 已知目的地城市；`_route_for_pair` 签名需透传或经 command 获取）。**不硬编码广州**；POI `city` 字段作为校验参考（若与 trip.destination 不一致，以 trip.destination 为准并记日志）。 | TRANSIT 必填；WALKING/DRIVING 忽略 |
| `destination_city` | 第一版：`None`（跨城预留在 RouteRequest 可选字段，B19-B 同城为主；跨城输入 → 由 provider 校验/NO_RESULT fail-closed） | 可选 |
| `strategy` | 第一版固定 `0`（最快捷） | 未来可扩展为约束输入 |
| `nightflag` | 第一版固定 `0` | 见 §7 夜间测试 |
| `departure_at` | **Activity A 的 slot end time**（`_emit_day` 中 `origin["end"]`，即 forward-fit 后的真实离开时刻）；replan 用 `origin.end_time`。**不是系统当前时间** | 已有字段，无扩展 |
| `date` / `time` | 由 `departure_at` 推导（`date` + `strftime("%H:%M")`） | provider 内部 |

**Reproducibility 原则**：一旦 RoutePlan 写入 itinerary version，后续展示/导出使用**持久化事实**（DB transit_leg 已存 duration/distance/polyline/cost），**渲染时不重查 provider**。transit 结果的 time-dependent 特性只影响未来重新规划，不影响已持久化版本。

## 7. Cache Design

当前 key（`planning_provider.py:1721-1726`）：`(origin_poi_id|origin, destination_poi_id|dest, mode, departure_at.isoformat())`。

**TRANSIT key（本批新增）**：

```python
key = (
    request.origin_poi_id or str(request.origin),
    request.destination_poi_id or str(request.destination),
    request.mode,               # 含 "TRANSIT" → 与 WALKING/DRIVING 天然隔离
    request.city,               # transit 城市相关
    request.strategy,
    request.nightflag,
    _departure_bucket(request.departure_at),  # 见下
)
```

- **departure bucket**：`_departure_bucket(dt) = dt - (dt.minute % BUCKET) * 1min`，`BUCKET = 15`（**初值**，15 分钟）。
  - 理由：planner 时间精度是分钟级（slot end 有 buffer 后移，B17 的 `time_fixed` 边界也是分钟级）；15 分钟 bucket 足够区分"白天/晚间/深夜"班次差异，又避免秒级 cache miss。
  - **不未经验证拍死**：RED/Golden G3 用真实/确定性数据校准 bucket 粒度（若 15 分钟内 AMAP transit 结果差异显著则缩 bucket，反之可放宽）。常量在 `transit_mode.py`（或 `_amap_transit.py`）集中定义，测试显式注入。
- **夜间风险测试**：`08:00` 与 `23:00` 同一 OD → bucket 不同 → cache identity 不同（T9/T20 用户要求：不要求真实返回不同，只要求 request/cache 能区分）。
- walking/driving 的 key 保持不变（现有 `departure_at.isoformat()` 秒级对它们无影响，沿用）。

## 8. Event v11 Design

### 8.1 当前版本状态（复核确认）

| 项 | 状态 |
| --- | --- |
| Python 生产写 completion | **v10**（`processor.py:186` 等） |
| Java completion parser | 接受 v9/v10（`PlanningCompletedEventParser.java:97`） |
| Java review parser | 只接受 v1（`PlanningReviewRequiredEventParser.java:100`） |
| completion v10 `transitLeg.mode` | `["WALKING","DRIVING"]` |
| review v1 `transitLeg.mode` | `["WALKING","DRIVING"]` |
| 双事件 | **均含 transitLegs**（completion v10 `:610`、review v1 `:558-559`）→ **v11 必须双链路同步** |

### 8.2 v11 最小变化

**新文件（不修改 v10）**：
- `contracts/messaging/planning-completed-event-v11.schema.json`：基于 v10，**只改一处**——`transitLeg.mode` enum：

```json
"enum": ["WALKING", "TRANSIT", "DRIVING"]
```

- `contracts/messaging/planning-review-required-event-v2.schema.json`：基于 v1，同样只改 `transitLeg.mode` enum。

**其余字段一律不动**（不顺手加 segment 结构、不改 activity/feasibility/other fields、B17 的 `date/targetPoiId/targetName/sourceUrl` None-omit 语义原样保留——§48 用户要求，serializer 行为不回退）。

### 8.3 TAXI 是否进入 v11

**决策：不进。** v11 只表达 planner 当前真实可产出的 Provider-backed mode：

```text
WALKING / TRANSIT / DRIVING
```

理由（§五十）：Python planner 无真实 TAXI route provider（B19-A 审计确认 TAXI 为本地估算）；若 v11 直接含 TAXI 会扩大生产契约语义却无真实 producer 能力。TAXI 语义属 B19-D。

### 8.4 Rollout 策略（结合项目现状）

```
1. 新建 v11 / review-v2 schema + fixtures（含 TRANSIT leg 的 sample）
2. Python schema tests 消费 v11（test_messaging_contract_schemas.py 增加 v11 组）
3. Java parser 同时支持 v10+v11（completion）、v1+v2（review）——v10/v1 分支保持既有校验不放开
4. Python producer 切 v11 / review-v2（schema_version=11 / 2）
5. 全链路（Python→Java→DB→Web）集成测试
```

- v10/v1 保持只读兼容（旧版本仍可消费，不迁移历史数据）。
- v10 收到 TRANSIT 仍 REJECT（schema enum 不含 → validator 拒绝），v11 才接受（T13/G6）。
- 双事件分别有 completion v11 TRANSIT 与 review v2 TRANSIT 测试（§47 用户要求，B17 双链路高风险点）。

## 9. Java / DB / Web Compatibility

| 层 | 现状 | B19-B 动作 |
| --- | --- | --- |
| Java parser（completion） | v9/v10；transitLeg.mode 只校验 `isTextual()`（**不枚举**） | 增加 `schemaVersion==11` 分支（v10 校验复制）；v10 分支不动 |
| Java parser（review） | 只接受 v1 | 增加 v2 分支 |
| Java domain / ItineraryService | 白名单 4 值已含 TRANSIT；`applyTransitLegEdit` 估算逻辑不变 | **无生产修改**（manual edit 不属本批） |
| DB | `transit_leg.mode` CHECK 已含 TRANSIT（V23） | **无 migration（DB migration required = NO）** |
| Web | `ConcreteCommuteMode` 已含 TRANSIT；label '公交/地铁'；按钮/icon 已支持 | **生产代码不改**，只补测试（persisted TRANSIT → 显示"公交/地铁"） |
| 旧 itinerary versions | 历史数据无 TRANSIT（现有 34 条 DRIVING） | 只读兼容，无需迁移 |

**DB migration 决策：NO。** 证据：`V23__complete_transit_leg_writeback.sql:5-8` CHECK 已含 TRANSIT；B19-A audit 曾写"可能 V38"是预留推测，复核后确认不需要。

## 10. Replan Compatibility

- 现状：`replan_service.py:262-277` 复用 `existing_leg.mode` 透传 `RouteRequest`。扩 `RouteMode` 后，existing `TRANSIT` leg 的 replan 请求 `mode="TRANSIT"` 不再 pydantic 失败。
- **需要配套**：replan 构造 `RouteRequest` 时补 `city`（来源：replan command 的 `trip.destination`——TRANSIT 必填；WALKING/DRIVING 忽略）。同步走 `_route_cached`/route budget（replan 已用 `self._route`，需确认走统一计数——若 replan 用 `_route` 不经 `_route_cached`，则保持一致即可，不新增第三路径）。
- **决策（选项 A）**：B19-B 让 replan 支持真实 TRANSIT（扩 RouteMode + 补 city 即天然兼容）。测试 T16 锁定"existing TRANSIT leg 的 local replan 不崩溃且产出 TRANSIT route"。
- 若 replan 的 `_route` 调用链对 TRANSIT 有其它缺失（如 error mapping），在实施时补最小分支，不重构。

## 11. Manual Edit Consistency

**决策：B19-B 不修 manual edit。**

- 现状：用户手动切"公交/地铁"→ 前端本地估算 → Java `applyTransitLegEdit`（`ItineraryService.java:583-626`）→ `provider=DEMO`、`polyline=[]`、`estimated=true`，**不调用真实 provider**。
- 本批只保证：**planner-generated TRANSIT 是真实 Provider route**（mode=TRANSIT / provider=AMAP / estimated=false）。
- **登记为 Known consistency gap**（B19-D follow-up）：planner 真实 transit vs manual edit DEMO 估算不一致。**不影响本批验收**（当前 UI 不会自动覆盖 planner 产出的真实 transit——`TripDetail.vue:304-307` 初始显示 persisted mode）。

## 12. Files to Change（预计，实施前复核）

**Python（apps/agent-service/src/trip_agent/）**
- `providers/_route_contracts.py` — `RouteMode` 加 `TRANSIT`；`RouteRequest` 加 `city/destination_city/strategy/nightflag`（可选默认）；`RoutePlan` 加 `walking_distance_meters/transfer_count`（optional）
- `providers/_amap_transit.py`（**新**）— transit adapter（request/parse/error mapping/alternative selection/polyline 拼接）
- `infrastructure/amap/planning_provider.py` — `_route_cached` key 扩展（city/strategy/nightflag/bucket）；`_route_for_pair` 加 `city` 透传（TRANSIT 分支仅当显式请求）；bucket 函数
- `application/replan_service.py` — RouteRequest 补 `city`
- `worker/contracts.py` — 无变化（`ItineraryTransitMode` 已含 TRANSIT）；`schema_version` 常量切 v11（processor.py）

**Contract（contracts/messaging/）**
- `planning-completed-event-v11.schema.json`（**新**，mode enum 3 值）
- `planning-review-required-event-v2.schema.json`（**新**，mode enum 3 值）
- `contracts/fixtures/` — v11 / review-v2 fixtures（含 TRANSIT leg）

**Java（apps/travel-server/）**
- `infrastructure/mq/PlanningCompletedEventParser.java` — v11 分支（校验复制 v10，mode 仍只校验类型）
- `infrastructure/mq/PlanningReviewRequiredEventParser.java` — v2 分支

**Web（apps/web/）**
- 生产代码不改；`tests/TransitLegControl.test.ts` 补 persisted TRANSIT 显示测试

**DB**：无 migration。

**文档**：`docs/execution/B19/execution-report-b.md`（实施后）。

## 13. RED Test Matrix

测试文件（预计）：`tests/test_amap_transit.py`（provider 单元）、`tests/test_route_contracts.py` 扩展（RouteMode/Request/Plan）、`tests/test_planning_worker.py`/`tests/test_b19_transit_chain.py`（v11 链路）、`tests/test_messaging_contract_schemas.py` 扩展（v11 schema）、Java parser 测试、Web `TransitLegControl.test.ts` 扩展。

| ID | 断言 | baseline（修复前） | GREEN 后 |
| --- | --- | --- | --- |
| T1 | `RouteRequest(mode="TRANSIT")` 合法 | **RED**（`RouteMode` 2 值，pydantic 拒绝） | 合法 |
| T2 | AMAP transit request 参数（endpoint/city/strategy/date/time/nightflag）映射正确 | **RED**（无 transit adapter） | MockTransport 断言参数 |
| T3 | transit parser flat facts（duration/distance/cost/polyline）正确；walking+bus 段 polyline 顺序拼接、重复端点去重 | **RED** | fixture 断言 |
| T4 | transfer_count 排除 walking 段（vehicle segments - 1） | **RED** | fixture 断言 |
| T5 | walking_distance 顶层字段 / segment 回退 / 缺失→None（不发明 0） | **RED** | 三种 fixture 断言 |
| T6 | 多 transit 方案 → 稳定选 `transits[0]` | **RED** | fixture 断言 |
| T7 | 无 transits → `ProviderFailure(NO_RESULT)`，不生成假路线、不 fallback DRIVING | **RED** | 断言 |
| T8 | `TRANSIT(A,B)` 不复用 `DRIVING(A,B)` 缓存 | **RED**（key 无 mode 语义隔离测试） | 断言两次独立 provider 调用 |
| T9 | 不同 departure bucket 的 TRANSIT 不复用缓存 | **RED** | 断言 |
| T10 | TRANSIT query 经过统一 `MAX_ROUTE_CALLS_PER_PLAN` 计数 | **RED** | 断言 calls 计数 |
| T11 | v11 serializer：`mode=TRANSIT` 合法序列化并过 schema 校验 | **RED**（v10 enum 拒绝） | 断言 |
| T12 | Java v11 consumer 接受 TRANSIT（provider=AMAP/estimated=false 保持） | **RED**（parser 不接受 v11） | 断言 |
| T13 | v10 WALKING/DRIVING PASS；v10 TRANSIT REJECT（未偷偷放宽） | baseline 部分 GREEN | 断言 |
| T14 | DB 持久化 TRANSIT 不被改写（经 event→Java 链路） | baseline GREEN（DB 已支持） | 断言 |
| T15 | Web 显示 persisted TRANSIT = "公交/地铁" | baseline GREEN（label 已有） | 断言 |
| T16 | existing TRANSIT leg 的 replan 不崩溃且产出 TRANSIT route | **RED**（RouteMode 拒绝 TRANSIT） | 断言 |

**baseline already GREEN 项**（如实记录，不故意破坏）：T14（DB 已支持）、T15（Web 已支持）。Java 白名单/DB/Web 的 TRANSIT 支持按 §四十五 记录为既有能力。

## 14. Golden Matrix（G1-G6）

脚本放 `C:\Windows\Temp\opencode\`（不提交）。

| ID | 场景 | 断言 |
| --- | --- | --- |
| **G1** | 正佳广场 → 广州塔，显式 `mode="TRANSIT"`（真实 AMAP） | 返回真实 transit RoutePlan：mode=TRANSIT、duration/distance/cost/polyline 非空、provider=AMAP、estimated=false。参考真实值：≈21min / ¥2（不硬断言数值，避免路况波动） |
| **G2** | 同一案例的 metadata | `walking_distance_meters` 与 `transfer_count` 可解析；vehicle segment 线路类型可识别（buslines[].type） |
| **G3** | 同一 OD：08:00 vs 23:00（真实或确定性） | request/cache identity 不同（bucket 不同）；不强制断言真实结果不同 |
| **G4** | TRANSIT NO_RESULT（fake provider 空 transits） | 明确 `ProviderFailure/NO_RESULT`，无 duration=0 假路线、无 DRIVING 冒充 |
| **G5** | v11 全链路（确定性 fixture 或真实）：Python→event v11→Java→DB→Web | `mode=TRANSIT / provider=AMAP / estimated=false` 保持 |
| **G6** | v10 compatibility | v10 WALKING/DRIVING PASS；v10 TRANSIT REJECT |

真实 AMAP Golden 仅做节制调用（4 类 OD 各 1-2 次 transit），记录 success/latency/rate limit（§53）。

## 15. API / Performance

| 项 | 设计 |
| --- | --- |
| 普通 planner route calls | **不增加**。`_route_for_pair` 不自动查 TRANSIT（Scope 门禁）；回归测试断言普通规划 calls 数与 B18-B 一致 |
| 显式 TRANSIT | +1 call/leg（与 WALKING/DRIVING 同走 `_route_cached` 计数） |
| Budget | `MAX_ROUTE_CALLS_PER_PLAN=96` 统一约束（T10） |
| Quota | 真实 Golden 节制调用（预估 ≤10 次 transit）；记录 endpoint success/latency/rate limit |
| Cache | transit key 含 city/strategy/nightflag/bucket；walking/driving key 不变 |

## 16. Risks

| # | 风险 | P | I | 缓解 |
| --- | --- | --- | --- | --- |
| 1 | **event v11 rollout**（生产写版本切换） | 中 | 高 | 先 Java 消费后 Python 切；v10 只读兼容；双链路同步测试 |
| 2 | v10/v11 双读兼容 | 中 | 中 | v10 分支校验不放开；T13/G6 回归 |
| 3 | transit time-dependent cache（bucket 粒度不当） | 中 | 中 | bucket 初值 15min + G3 校准；夜间测试（T9） |
| 4 | AMAP transit parser 复杂度（多 segment/buslines/via_stops） | 中 | 中 | 第一版只解析 flat facts + 2 个 metadata；fixture 驱动 |
| 5 | polyline 拼接（缺段/重复端点/自交） | 中 | 低 | 顺序拼接 + 端点去重 + 跳过缺段 + 退化 2 点；T3 |
| 6 | no-result/error taxonomy 不匹配 | 低 | 中 | 复用 ProviderErrorCategory mapper；T7/G4 |
| 7 | provider quota（transit 与 route 配额关系未披露） | 中 | 中 | 节制 Golden；失败记录不伪造 |
| 8 | route budget 被显式 TRANSIT 放大 | 低 | 低 | 普通 planner 不查 transit；96 上限统一约束 |
| 9 | replan existing TRANSIT 崩溃 | 中 | 高 | 扩 RouteMode + 补 city；T16 |
| 10 | manual edit DEMO 估算不一致 | 高（已知） | 中 | **本批不修**，登记 B19-D；不影响 planner 链路验收 |
| 11 | 旧 itinerary 兼容 | 低 | 低 | 无 DB migration；历史 leg 只读 |
| 12 | TAXI/TRANSIT enum 语义漂移 | 低 | 低 | v11 只含 WALKING/TRANSIT/DRIVING（TAXI 不进）；文档明确 |

## 17. Rollback

B19-B 独立可回滚（无 DB migration、无 breaking enum 迁移）：

```
commit 1（逻辑层）: Python provider（_route_contracts/_amap_transit/planning_provider/replan）
commit 2（契约层）: v11/v2 schema + fixtures + Python producer 切版
commit 3（消费层）: Java parser v11/v2 分支
```

回滚顺序：Java 停收 v11（退回 v10 分支）→ Python 切回 v10 → provider 层独立可留（不影响普通 planner）。各 commit 保持可独立编译/测试（不做强拆不可编译状态）。

## 18. Acceptance Criteria

- [ ] `RouteMode` 支持 TRANSIT（T1）
- [ ] AMAP TRANSIT 使用真实官方 endpoint（v3/direction/transit/integrated）（T2）
- [ ] city/strategy/date/time/nightflag 映射正确（T2）
- [ ] 多方案选择策略确定且有测试（T6：strategy=0 + transits[0]）
- [ ] duration/distance/cost/polyline 正确解析（T3）
- [ ] walking_distance 可获取（T5）
- [ ] transfer_count 可获取且排除 walking 段（T4）
- [ ] no-result 不生成假路线、不 fallback DRIVING 冒充（T7/G4）
- [ ] TRANSIT route 经过统一 route budget（T10）
- [ ] TRANSIT cache 与 WALKING/DRIVING 隔离（T8）
- [ ] time-dependent cache identity 正确（T9：bucket + nightflag）
- [ ] v11 正式允许 TRANSIT（T11）
- [ ] v10 未被偷偷放宽（T13/G6：v10 TRANSIT reject）
- [ ] completion/review 双链路兼容（§47：v11 + review-v2 各自测试）
- [ ] Java v11 consumer 接受 TRANSIT 且 provider/estimated 保持（T12）
- [ ] DB 持久化 TRANSIT 不被改写（T14；V23 已支持，无 migration）
- [ ] Web 正确展示 persisted TRANSIT（T15）
- [ ] B17/B18 行为无回归（related 回归套件）
- [ ] 普通 planner 不自动增加三模式查询（§15 门禁测试）
- [ ] 不实现 multi-mode recommendation / staged querying（scope 审计）
- [ ] 不引入 ROAD/TAXI breaking migration（scope 审计）

## 19. Recommended Execution Order

```
Phase 1  RED（T1-T16 先写，记录 baseline：T14/T15 already GREEN）
Phase 2  Python provider（_route_contracts → _amap_transit → planning_provider cache/key → replan city）
Phase 3  Contract v11（schema + fixtures + Python producer 切版 + schema tests）
Phase 4  Java consumer（v11/v2 parser 分支 + parser tests）
Phase 5  集成（Python→Java→DB→Web 全链路测试；Web TRANSIT 显示测试）
Phase 6  Golden（G1-G6，真实 AMAP 节制调用）
Phase 7  全量回归（Python targeted/full pytest/ruff + contract schema tests + Java mvn + Web vitest/typecheck）
Phase 8  Execution Report（docs/execution/B19/execution-report-b.md）
```

每个 Phase 完成后停留确认；B19-B 不自动进入 B19-C（recommendation 需本批效果确认后独立批准）。

---

## 附：本计划关键决策速览

| 决策点 | 结论 |
| --- | --- |
| 复用 TRANSIT vs 新增 PUBLIC_TRANSIT | **复用 TRANSIT**（domain/Java/DB/Web 已存在） |
| RouteRequest 新字段 | `city`（TRANSIT 必填）、`destination_city`（可选，跨城预留）、`strategy`（默认 0）、`nightflag`（默认 0）；`departure_at` 已有 |
| city 来源 | `trip.destination`（不硬编码） |
| alternative 选择 | 官方 `strategy=0` + `transits[0]` |
| RoutePlan metadata | `walking_distance_meters` / `transfer_count`（optional，WALKING/DRIVING=None） |
| TransitLeg | **保持 flat**（metadata 不落 DB） |
| transfer_count | vehicle segments - 1（排除 walking） |
| polyline | 按 segments 顺序拼接 + 重复端点去重 + 缺段跳过 + 全缺退化 2 点 |
| departure bucket | 15 分钟（初值，G3 校准） |
| v11 | completion v11 + review v2，mode enum `["WALKING","TRANSIT","DRIVING"]` |
| TAXI 进 v11 | **不进**（无真实 producer） |
| DB migration | **NO**（V23 CHECK 已含 TRANSIT） |
| Java | parser 加 v11/v2 分支；ItineraryService 无生产修改 |
| Web | 生产代码不改，只补测试 |
| replan | 扩 RouteMode + 补 city 天然支持（选项 A） |
| manual edit | **本批不修**（登记 B19-D） |
| 普通 planner API calls | 不增加（Scope 门禁） |
