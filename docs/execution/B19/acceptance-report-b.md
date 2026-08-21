# B19-B Acceptance Report

- 验收日期：2026-08-19
- 验收角色：独立验收 Agent（只读，未修改任何生产代码，未修复任何发现的问题）
- 依据：`docs/execution/B19/audit.md`、`docs/execution/B19/plan-b.md`、`docs/execution/B19/execution-report-b.md`（开发方声明，仅参考）；`docs/execution/B18/execution-report-b.md` / `acceptance-report-b.md`（B18-B 已 PASS，本轮未重新打开）
- 方法：代码精读 + 独立测试复跑 + 真实 AMAP Golden 独立调用；所有结论由代码、测试、contract 与真实 provider 证据独立形成

---

## 1. Verdict

```
PASS_WITH_DEFECT
```

B19-B 核心能力已达成：真实 AMAP TRANSIT Provider（v3/direction/transit/integrated、真实 `segments[]` 结构）与 completion v11 / review v2 全链路（Python → event → Java → DB → REST → Web）建立并验证通过；旧 contract v10/v1 语义未放宽；cost/duration/distance/polyline/walking_distance/transfer_count 事实正确；cache/budget/fail-closed/scope 门禁全部通过。存在 **1 个明确但非阻塞的 polyline 边界缺陷（D1）**：全段/单段 polyline 缺失时的处理与 plan-b §4.4 及 execution-report-b §9 的声明不一致（实际为 fail-closed `PROVIDER_SCHEMA_CHANGED`，未实现"跳段/退化 2 点"）。

**准确表述**：B19-B 已建立真实 TRANSIT Provider 与 v11/v2 全链路能力。**不是**"已实现最佳交通方式推荐"——WALKING vs TRANSIT vs DRIVING 自动推荐属 B19-C。

---

## 2. Scope Reviewed

| 项 | 验证方式 |
| --- | --- |
| Python provider | `_amap_transit.py` / `_amap_transit_models.py` / `_amap_transit_failures.py` 全文精读 + 51 项 targeted 测试独立复跑 |
| models/parser | 真实 `segments[]`/`walking.steps[].polyline`/`buslines[]` 结构核对 + 真实 G1 响应通过 |
| cache/budget | `_route_cached` TRANSIT key/bucket/`MAX_ROUTE_CALLS_PER_PLAN=96` 代码精读 + `test_b19_transit_chain.py` 复跑 |
| event v11/v2 | 4 个 schema 文件 enum 核对 + `test_messaging_contract_schemas.py` 复跑 |
| Java | 两个 parser 全文精读 + targeted 137 / 全量 537 独立复跑 |
| DB | migration 文件核对（V23 CHECK 已含 TRANSIT，无新 migration） |
| REST | `toTransitLegResponse` mode/provider/estimated 透传代码确认 |
| Web | `TransitLegControl.vue`/`lib/transit.ts` 生产零改动确认 + persisted TRANSIT 显示测试 |
| replan | `replan_service.py` mode/city/departure_at 代码精读 + `test_local_replanning.py` 复跑 |
| B17/B18 regression | 212 related + 1626 全量 + B18-B 14 项 baseline + Java/Web 全量复跑 |
| 真实 AMAP | G1 独立真实调用 1 次（成功、无限流） |

---

## 3. Workspace Baseline

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `d10e70cf354d096300c4a348d6aef585b8d82dc8` |
| dirty workspace | 74 个 tracked 修改 + untracked 文件（B15/B16/B17/B18-A/B18-B/B19-A/B19-B 混合在途）；未执行任何 `git reset / restore / checkout . / stash / clean` |
| B19-B 可识别增量 | Python：`_amap_transit.py`/`_amap_transit_models.py`/`_amap_transit_failures.py`（新）、`_route_contracts.py`/`planning_provider.py`/`replan_service.py`/`processor.py`/`worker/amqp.py`/`providers/route.py`/`_amap_route.py`/`_demo_route.py`/`errors.py`/`map.py` 增量；contracts：v11/v2 schema + fixtures（新）+ README；Java：两个 parser + 测试增量；Web：仅测试文件（`TransitLegControl.test.ts`/`transit.test.ts`）；测试：`test_amap_transit.py`/`test_b19_transit_chain.py`（新）+ 若干断言更新 |
| 历史归属 | 无法从未提交 dirty workspace 逐行证明每一行的批次归属；本报告只审计 B19-B 增量语义正确性，不声称整个 diff 属于 B19-B |

---

## 4. Real AMAP Model Acceptance

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 顶层结构 `transits[]` + `segments[]`（非旧假想 `steps`） | ✅ | `_amap_transit_models.py`：`_AmapTransitRoute.transits` → `_AmapTransitPath.segments`（min_length=1）；模块 docstring 明确记录真实结构 |
| `segment.walking` 可为 `[]` | ✅ | `_empty_segment_array_to_none`：`[]` → None（真实 AMAP 以空数组表示缺失） |
| `segment.bus` 可为 `[]` | ✅ | 同上；`_AmapSegmentBus.buslines` 默认空 tuple |
| `buslines` 可为空 | ✅ | 空 → 该 segment 不作为 vehicle segment，可回落 walking 处理 |
| `walking` 内 polyline 在 `steps[].polyline` | ✅ | `_walking_polyline` 从 walking.steps 逐 step 取 polyline；真实 G1 响应验证通过 |
| `walking` 顶层无直接 polyline | ✅ | 模型无 walking 顶层 polyline 字段；`extra="ignore"` 容忍真实响应中的多余字段 |
| segment 部分字段缺失 | ✅（fail-closed） | 必填字段缺失 → pydantic ValidationError → `PROVIDER_SCHEMA_CHANGED`（不静默伪造） |
| 真实结构 Golden | ✅ | G1 独立真实调用：39 点 polyline / 2 steps（APM 线 + 步行），真实响应完整通过 parser |

结论：parser 已真正切换到真实 `segments[]` 结构，与 AMAP v3 transit/integrated 官方结构一致；此前"按 steps 建模导致 PROVIDER_SCHEMA_CHANGED"的问题已闭环（本次独立真实调用未再触发）。

---

## 5. Route Fact Acceptance

| 事实 | 来源 | 独立验证 |
| --- | --- | --- |
| `mode="TRANSIT"` | 固定 | G1 + fixture |
| `duration_seconds` | `transit.duration`（总耗时） | G1=1250s；fixture 断言 1250/2100 |
| `distance_meters` | `transit.distance`（总旅程，非 haversine） | G1=3444m；fixture 断言 6085/13000 |
| `estimated_cost` | `transit.cost` | G1=2.0；COST-1~4 测试 |
| `polyline` | 按 `segments[]` 顺序拼接 + 相邻重复端点去重 | G1=39 点；fixture 断言拼接顺序与去重（3 段 → 3 点，重复端点消除） |
| `walking_distance_meters` | 顶层 → `sum(walking.distance)` → None | G1=654m；三个 fixture（顶层/回退/缺失→None）全部 PASS |
| `transfer_count` | vehicle segments - 1（排除 walking） | G1=0（APM 1 段）；metro+bus fixture=1（2 vehicle 段 + 3 walking 段） |
| `provider="AMAP"` / `estimated=false` | 固定 | G1 + `_route` 元数据一致性检查（AMAP↔estimated 交叉校验） |

**同源性**：`RoutePlan` 的 mode/duration/distance/cost/polyline 全部在 `_to_plan` 内从同一次 `_AmapTransitPath`（同一 provider 响应）构建；`_route` 返回单一 `ProviderSuccess[RoutePlan]`，`_leg_from_route`/replan 逐字段取自该对象。不存在"mode=TRANSIT 但 duration 来自 DRIVING"或"cost 来自 AMAP 而 duration 来自本地估算"的混用路径。

---

## 6. Cost Semantics

| Case | 输入 | 结果 | 证据 |
| --- | --- | --- | --- |
| 正常整数 | `cost="2"` | `estimated_cost=2.0` | `test_amap_transit_parses_integer_string_cost` PASS |
| 正常小数 | `cost="2.5"` | `estimated_cost=2.5` | `test_amap_transit_parses_decimal_string_cost` PASS |
| 空字符串 | `cost=""` | `None`（**≠0**，0=免费/None=未知） | `test_amap_transit_missing_or_empty_cost_is_unknown_not_free` PASS |
| 字段缺失 | cost 不在响应 | `None` | 同上（参数化 `None`） |
| 非法值 | `cost="abc"` | `ProviderFailure(PROVIDER_SCHEMA_CHANGED)`，不静默 None | `test_amap_transit_malformed_cost_is_a_schema_change_failure` PASS |

链路确认：AMAP `transit.cost` → `RoutePlan.estimated_cost` → `_leg_from_route` → `TransitLeg.estimated_cost`（`contracts.py` `JsonDecimal | None` 允许 None）。**没有任何 Java/前端本地估算混入** TRANSIT 路线（本地估算仅存在于 manual edit 路径，见 §19 Known Gaps）。

---

## 7. Cache / Time-dependent Acceptance

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 内存 key 字段 | `("TRANSIT", city, strategy, nightflag, origin, destination, departure_bucket.isoformat())` | `planning_provider.py:1736-1744` |
| 覆盖要求 | origin ✅ / destination ✅ / mode（固定 "TRANSIT" 前缀）✅ / city ✅ / strategy ✅ / nightflag ✅ / 日期 ✅ / 时间 bucket ✅ | 同上 + `test_transit_cache_key_distinguishes_city_strategy_and_nightflag` |
| destination_city | 不在 key | 合理：`destination_city` 恒为 None 且不进入 provider 请求（`_request_params` 未发送），不影响 cache identity |
| 日期进入 key | `departure_bucket.isoformat()` 含 `YYYY-MM-DD`；provider JSON key 含完整 UTC ISO | `test_transit_cache_key_includes_the_calendar_date`（08-19 vs 08-20 不同 key）PASS |
| 15 分钟 bucket | 单一定义点 `planning_provider.py:1731-1735`（UTC 下 `minute//15`）；测试 0/14 同桶 1 次调用、15 不同桶第 2 次调用 | `test_transit_cache_key_buckets_departure_time_to_15_minutes` PASS |
| walking/driving key | 未改动（原 `(poi×2, mode, departure_at.isoformat())`） | `planning_provider.py:1745-1751` |
| provider JSON cache key | `map:transit:v1:{sha256(origin/destination/poi×2/city/strategy/nightflag/departure/provider/data_version)}` | `_cache_key` 代码 + `test_amap_transit_cache_key_distinguishes_city_and_time` |
| G3 真实 | 同 OD 08:00 vs 23:00 → `date/time` 参数不同、cache key 不同 | 独立复跑脚本输出两条不同 key |

观察（非缺陷）：15 分钟 bucket 为 `planning_provider.py:1732` 的单处内联字面量（无命名常量），但全仓仅此一处定义，无散落；plan-b §7 期望"集中定义"，实现满足"单一集中点"。

---

## 8. Error / No-result Acceptance

| 场景 | 行为 | 证据 |
| --- | --- | --- |
| `transits=[]` | `ProviderFailure("ROUTE_NOT_FOUND", NO_RESULT, retryable=False)`；**无假 route、无 duration=0、无 DRIVING 冒充** | `test_amap_transit_empty_transits_is_a_typed_not_found_failure` PASS |
| 结构/字段非法 | `PROVIDER_SCHEMA_CHANGED`（retryable=True） | 7 个参数化 invalid payload + 非 JSON 测试 PASS |
| timeout/network | `PROVIDER_TIMEOUT` / `PROVIDER_UNAVAILABLE`（NETWORK_ERROR） | 传输层参数化测试 PASS |
| HTTP 状态 | 408→TIMEOUT、401/403→AUTH/PERMISSION、429→RATE_LIMITED、5xx→UNAVAILABLE、400→INVALID_REQUEST | 参数化测试 PASS |
| 业务 infocode | 10001→AUTH、10004→RATE_LIMITED、10003→QUOTA、10017/30000→UNAVAILABLE、20000→INVALID、20003→PROVIDER_ADAPTER_ERROR | 参数化测试 PASS |
| 统一 taxonomy | `ProviderErrorCategory`/`ProviderFailure`/`PlanningProviderError.from_failure` 复用，`ProviderOperation.ROUTE` | `_amap_transit_failures.py` + `planning_provider.py:_route` |
| 宽捕获检查 | ✅ 无 `except Exception: silently fallback`。provider 层无任何 mode fallback；`_read_cache`/`_write_cache` 的宽捕获仅限缓存退化（日志+直连 live），与既有 provider 架构一致 | 代码精读 |
| 非 TRANSIT provider 收到 TRANSIT | `AmapRouteProvider`/`DemoRouteProvider` 显式返回 `PROVIDER_UNSUPPORTED_MODE`（fail-closed，不误算） | `_amap_route.py:59-64`、`_demo_route.py:32-41` |

---

## 9. Event Version Acceptance

Schema enum（独立核对 4 个 schema 文件）：

| 事件版本 | transitLeg.mode enum | TAXI |
| --- | --- | --- |
| completion **v10** | `["WALKING", "DRIVING"]` | 无 |
| completion **v11** | `["WALKING", "TRANSIT", "DRIVING"]` | **无** |
| review **v1** | `["WALKING", "DRIVING"]` | 无 |
| review **v2** | `["WALKING", "TRANSIT", "DRIVING"]` | **无** |

Accept/reject matrix（schema validator + Java parser 双路径独立确认）：

| 事件版本 | WALKING | DRIVING | TRANSIT | TAXI |
| --- | --- | --- | --- | --- |
| completion v10（schema） | PASS | PASS | REJECT（`test_v10_completed_schema_rejects_a_transit_leg`） | REJECT |
| completion v11（schema） | PASS | PASS | PASS（`test_v11_completed_schema_accepts_a_transit_leg`） | REJECT（`test_v11_completed_schema_rejects_taxi_mode`） |
| review v1（schema） | PASS | PASS | REJECT（`test_review_v1_schema_rejects_a_transit_leg`） | REJECT |
| review v2（schema） | PASS | PASS | PASS（`test_review_v2_schema_accepts_a_transit_leg`） | REJECT |
| completion v10（Java） | PASS | PASS | REJECT（`v10RejectsTransitLegsUntilTheV11Contract`） | REJECT |
| completion v11（Java） | PASS | PASS | PASS（`acceptsV11TransitLegsWhileKeepingV10Compatible`） | REJECT |
| review v1（Java） | PASS | PASS | REJECT（`v1RejectsTransitLegsUntilTheV2Contract`） | REJECT |
| review v2（Java） | PASS | PASS | PASS（`acceptsV2TransitLegs`） | REJECT |

版本语义由 **schema enum + Java parser 版本化 enum 双重保证**，消费路径无绕过：Java `validateTransitLegTypes`（wire 类型层）与 `validTransitLeg`/`validateDay allowedMode`（domain 层）均按 schemaVersion 分支，v10/v1 分支校验未放宽。

---

## 10. Consumer / Producer Acceptance

| 角色 | 版本 | 证据 |
| --- | --- | --- |
| Java completion consumer | **v9 / v10 / v11** 接受（v9/v10 只读兼容，v11 新增） | `PlanningCompletedEventParser.java:98`（schemaVersion∈{9,10,11}）；parser 测试 64 项 PASS |
| Java review consumer | **v1 / v2** 接受（v1 只读兼容，v2 新增） | `PlanningReviewRequiredEventParser.java:104`；parser 测试 25 项 PASS |
| Python completion producer | **只写 v11**（`schema_version=11`） | `processor.py:190/292/392` 三条生产路径（create/replan/candidate-validation）；`test_planning_worker`（schema_version==11）、`test_amqp_worker`（completed.schema_version==11）、`test_completed_v11_contract_accepts_worker_output` PASS |
| Python review producer | **只写 v2**（`schema_version=2`） | `processor.py:211/313/408`；相关断言 PASS |
| 版本消费矩阵 | Java 读旧+新；Python 只写新 | 当前最终状态一致，**不存在 producer=v11 而 consumer 不认 v11 的生产窗口** |
| consumer-first 时序 | 当前最终状态正确；历史执行顺序（Java 先、Python 后）由 execution-report 描述支持，**无法从 dirty workspace 证明** | 如实记录：`current final state correct; historical sequencing partially supported by execution evidence` |

---

## 11. B17 Serializer Regression

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| `date=None` 完全 omitted | ✅ | `PlanningFactImpact._omit_none_optional_fields` wrap serializer 无条件弹出 4 个字段（与 `exclude_none` 无关） |
| `targetPoiId=None` omitted | ✅ | 同上 |
| `targetName=None` omitted | ✅ | 同上 |
| `sourceUrl=None` omitted | ✅ | 同上 |
| wire 级验证（非仅模型） | ✅ | `test_fact_impact_omits_none_optional_fields_on_the_wire` 用 `exclude_none=False` 序列化（镜像真实 AMQP 发布路径 `amqp.py:672`）断言 4 键 absent；且 `"targetName": null` 会被 Java parser `validateFactImpactTypes` 拒绝 |
| v11/v2 两条路径 | ✅ | v11 payload 复用 `PlanningCompletedPayloadV10`，review v2 同用 `PlanningFactImpact`；两条路径共用同一 serializer，related 回归全绿 |
| 生产发布路径 | ✅ | 结果事件发布 `amqp.py:672` `model_dump_json(by_alias=True, exclude_none=False)`——omission 完全由模型 serializer 保证，B17 行为保留 |

---

## 12. Persistence / REST / Web

| 层 | 结果 | 证据 |
| --- | --- | --- |
| DB CHECK | `business.transit_leg.mode IN ('WALKING','TRANSIT','DRIVING','TAXI')`（V23 生效）；**无 B19-B migration（无 V38）** | migration 文件核对：最新 V37 为 B16 时代可行性报告放宽；V13 旧 CHECK 已被 V23 取代 |
| Java 持久化 | `TransitLegWrite(mode=leg.mode(), provider=leg.provider(), estimated=leg.estimated())` 直写，无改写 | `ItineraryService.java:1436-1446`；集成测试 DB+REST round-trip（WALKING/AMAP/false 与编辑流 TRANSIT 均验证） |
| REST DTO | `toTransitLegResponse` 直接透传 `leg.mode()/provider()/estimated()/polyline` | `ItineraryService.java:786-793` |
| Web 初始加载 | persisted `leg.mode` 显示（`transitModeFor`：无用户覆盖时返回 `leg.mode`）；`TransitLegControl` label `TRANSIT:'公交/地铁'` | `TripDetail.vue:304-307`；`TransitLegControl.test.ts` persisted TRANSIT → 含"公交/地铁" PASS |
| 加载 vs AUTO | 两套行为：加载显示 persisted mode；仅用户主动点击才走 AUTO 推荐 | `TripDetail.vue` 代码 + 测试 |
| Web 生产代码 | **B19-B 0 修改**：`TransitLegControl.vue`/`lib/transit.ts` 无 diff；`TripDetail.vue`/`api.ts` 的 diff 为 B15/B16/B17 历史批次（可行性 UI/文案/类型） | git diff 审查 |

---

## 13. Replan

| 场景 | 结果 | 证据 |
| --- | --- | --- |
| existing leg TRANSIT → 同城 replan | ✅ 成功，`RouteRequest(mode="TRANSIT", city=trip.destination, departure_at=origin.end_time)`；产出 leg mode=TRANSIT / provider=AMAP / estimated=false | `replan_service.py:271-285`；`test_replan_routes_a_transit_leg_through_the_transit_provider`（requests[0].mode=="TRANSIT"、city=="Guangzhou"）PASS |
| `departure_at` 来源 | `origin.end_time`（非 `datetime.now()`）；planner 路径 `_emit_day` 传 `origin["end"]` | `replan_service.py:281`；`planning_provider.py:1109-1113` |
| city 缺失（`city=None` + TRANSIT） | fail-closed：`RouteRequest.require_city_for_transit` → ValueError，不默认城市、不查错城市、不降级 DRIVING | 独立 python 探针：ValueError "transit route requests require a city"；`_route_contracts.py:43-46` |
| 跨城 | Known Gap：`city=trip.destination`（同城规划语义）；`destination_city` 预留但未发送；活动级 city 数据不足时不静默查错城市（fail-closed） | 代码 + plan-b §23；见 §19 |
| budget 说明 | replan 走 `LocalReplanningProvider._route`（不经 `_route_cached`）——**B18-B 既有设计**（plan-b §10 明确"保持一致即可，不新增第三路径"），对所有 mode 一视同仁，TRANSIT 未新增绕过；显式 TRANSIT 经 `_route_cached` 的路径已由 `test_transit_and_driving_share_the_route_call_budget` 验证计入 `MAX_ROUTE_CALLS_PER_PLAN=96` | 代码 + 测试 |

---

## 14. Golden G1-G6

| ID | 场景 | 独立结果 |
| --- | --- | --- |
| **G1** | 正佳广场 → 广州塔，显式 mode=TRANSIT，**真实 AMAP 独立调用** | **PASS**：`mode=TRANSIT / duration=1250s / distance=3444m / cost=2.0 / walking_distance=654m / transfer_count=0 / polyline=39点 / provider=AMAP / estimated=false / cached=false`；steps：乘坐APM线(林和西--广州塔) 2790m/690s + 步行 95m/81s。与开发方数值完全一致（同源真实数据） |
| **G2** | metadata（walking_distance/transfer_count/polyline） | **PASS**：654m / 0 / 39 点；polyline 首尾与 OD 坐标吻合；线路名/type 可在 provider 响应读取（不持久化，符合 flat 设计） |
| **G3** | 同 OD 08:00 vs 23:00 | **PASS**：`date=2026-08-20 time=08:00` vs `time=23:00`，cache key 不同（`46ca0c...` vs `deb701...`）；不强制断言真实线路不同 |
| **G4** | TRANSIT NO_RESULT（fixture `transits=[]`） | **PASS**：`ProviderFailure(ROUTE_NOT_FOUND)`、retryable=False；无假 route、无 DRIVING 冒充（`test_amap_transit_empty_transits_is_a_typed_not_found_failure`） |
| **G5** | v11 全链路 | **PASS（等价证据链，非浏览器 E2E）**：见 §15 |
| **G6** | v10/v1 兼容 | **PASS**：v10 WALKING/DRIVING PASS、v10 TRANSIT REJECT；review v1 同理（schema + Java 双路径，见 §9 matrix） |

---

## 15. Full-chain Evidence

**明确声明：G5 为等价证据链（equivalent evidence chain），未运行完整浏览器 E2E。**

证据链各环节（均独立验证）：

```
Python RoutePlan(mode=TRANSIT, provider=AMAP, estimated=false)
  → 生产路径：replan 显式 TRANSIT 测试（requests[0].mode/TRANSIT、city、leg 字段保持）
  → completion v11 producer（processor.py schema_version=11；test_planning_worker/test_amqp_worker 断言）
  → v11 schema 校验（test_completed_v11_contract_accepts_worker_output + fixture completion-v11-transit-savable.json: TRANSIT/AMAP/false）
  → Java PlanningCompletedEventParser v11 分支（acceptsV11TransitLegsWhileKeepingV10Compatible PASS）
  → Java 持久化（代码透传 leg.mode()/provider()/estimated()；集成测试 DB+REST round-trip 覆盖 WALKING 与编辑流 TRANSIT；DB CHECK V23 已含 TRANSIT）
  → REST DTO（toTransitLegResponse 透传）
  → Web persisted TRANSIT → "公交/地铁"（TransitLegControl.test.ts PASS；transitModeFor 返回 persisted mode）
```

结论：`mode=TRANSIT / provider=AMAP / estimated=false` 在代码路径与测试证据上全程保持，无改写点。

---

## 16. Regression（独立执行）

```
Python targeted:  pytest tests/test_amap_transit.py tests/test_b19_transit_chain.py
                  → 51 passed, exit 0
Python B18-B:     pytest tests/test_transit_mode.py
                  → 14 passed, exit 0（B1-B9 调用序列：短距 WALKING=1、walking 超阈值=[WALKING,DRIVING]=2、长距 DRIVING=1）
Python related:   pytest test_transit_mode test_messaging_contract_schemas test_local_replanning
                  test_planning_outcome_events test_amqp_worker test_planning_worker
                  test_route_provider test_planning_outcome_flow test_provider_provenance
                  → 212 passed, 1 warning, exit 0
Python full:      pytest -q --basetemp=%LOCALAPPDATA%\Temp\b19-acceptance-full-1
                  → 1626 passed, 37 skipped, 1 warning, exit 0
ruff:             ruff check src/trip_agent tests → All checks passed! (exit 0)
Java targeted:    mvn -pl apps/travel-server test -Dtest=PlanningCompletedEventParserTest,
                  PlanningReviewRequiredEventParserTest, PlanningCompletionFlowIntegrationTest,
                  PlanningTaskOutcomeReadModelTest → 137 tests, 0 failures, 0 errors
Java full:        mvn -pl apps/travel-server test（JDK 21 BellSoft；Docker Desktop 运行中）
                  → 537 tests, 0 failures, 0 errors, BUILD SUCCESS
Web targeted:     vitest run tests/TransitLegControl.test.ts tests/transit.test.ts → 9 passed
Web full:         vitest run → 42 files / 447 passed
Web typecheck:    vue-tsc -b → exit 0
```

说明：默认 `C:\Windows\Temp\pytest-of-*` ACL 环境问题延续（B18 已记录），使用 `--basetemp=%LOCALAPPDATA%\Temp\...` 可写路径后全量通过；唯一 warning 为 B17 既有测试的 Pydantic AnyHttpUrl 序列化提示（与 B19-B 无关，且该测试本身 PASS）。

---

## 17. Provider / Performance

| 项 | 值 |
| --- | --- |
| 本次验收真实 AMAP transit 调用 | **1 次**（G1），成功，latency 秒级，**0 限流 / 0 quota 错误** |
| G3 | 参数/cache key 推导（无额外网络请求） |
| 真实调用纪律 | 未做任何重试；未消耗多余配额 |
| 普通 planner API calls | **不增加**：`_route_for_pair` 无 TRANSIT 分支（只有 WALKING/DRIVING）；B18-B 14 项调用序列测试原样通过 |
| 显式 TRANSIT | 经 `_route_cached` 计数（+1/次），`MAX_ROUTE_CALLS_PER_PLAN=96` 超限 raise `ROUTE_CALL_BUDGET_EXHAUSTED`（测试 PASS） |
| cache | 内存 key 含 mode/city/strategy/nightflag/日期/15min bucket；provider JSON cache `map:transit:v1:` TTL 3600s |

---

## 18. Scope Audit

| 检查项 | 结果 |
| --- | --- |
| multi-mode scorer / 自动推荐 | ✅ 无（`_route_for_pair` 只有 WALKING/DRIVING；provider 只做显式 TRANSIT 查询） |
| `PUBLIC_TRANSIT` 新 enum | ✅ 无（全仓零命中；复用 `TRANSIT`） |
| `ROAD` enum | ✅ 无（仅注释文案） |
| `SELF_DRIVING` | ✅ 无 |
| TAXI provider / planner 内 TAXI | ✅ 无（v11/v2 schema 与 Java parser 均拒绝 TAXI；`TAXI` 仅存在于既有 `ItineraryTransitMode`/DB CHECK/前端枚举，为编辑/产品语义） |
| transport preference / same-area diversity / complex dedup | ✅ 无（B18-C/D 未进入） |
| 驾车/打车 UI 合并 / 交通 UI 重构 | ✅ 无（Web 生产代码 0 修改） |
| transit segments DB 持久化 / 线路详情 schema | ✅ 无（TransitLeg flat；metadata 仅 provider 层） |
| DB migration | ✅ NO（无 V38；V23 CHECK 已含 TRANSIT） |
| B18-C diversity / B18-D parent dedup | ✅ 无 |
| alternative 选择 | ✅ 仅 `strategy=0` + `transits[0]`（`_amap_transit.py:138`）；无 min(duration)/min(cost)/weighted score/min transfer |

结论：B19-B 严格停留在"真实 TRANSIT Provider + v11/v2 全链路"范围，**无 B19-C/D 或 B18-C/D 污染**。

---

## 19. Defects / Known Gaps

### B19-B Defect（1 项，非阻塞）

**D1 — polyline 全缺/单段缺失的处理与 plan-b §4.4 及 execution-report-b §9 声明不一致**

- 证据：`_amap_transit.py:201-260` 对每个 segment 无条件构造 `RouteStep(polyline=...)`（`RouteStep.polyline` 有 `min_length=1`，`_route_contracts.py:53`）；任何 segment 的 polyline 为空（walking 无 steps / steps 无 polyline / busline 无 polyline）都会使整个响应在 `RoutePlan(polyline=())` 处触发 ValidationError → `PROVIDER_SCHEMA_CHANGED`。独立探针（构造全缺 polyline 的真实结构响应）确认返回 `ProviderFailure(PROVIDER_SCHEMA_CHANGED)`。
- plan-b §4.4 要求："segment 无 polyline → 跳过该段；全部缺失 → polyline 退化为 (origin, destination) 两点"。execution-report-b §9 声称"无 polyline 段跳过；全缺退化 2 点"——**均未实现**。
- 影响：仅当 AMAP 返回无 polyline 几何的 transit 响应时触发（真实 G1 与全部既有 fixture 均携带 polyline，当前真实数据未观测到）；失败模式为 fail-closed（REAL_ONLY 下规划失败；REAL_WITH_EXPLICIT_FALLBACK 下走既有 DEMO fallback），**不伪造几何、不把 fallback 误标为真实 provider geometry**——实际行为与既有 AMAP walking/driving malformed-response 政策（`_amap_route.py:205-227` 同款模式）一致，安全性不降级。
- 为何非阻塞：核心能力（真实 segments 解析、cost、facts、cache、v11/v2 链路）不受影响；edge 场景从未在真实数据出现；行为 fail-closed 优于伪造。
- follow-up：二选一——按 plan-b 实现"跳段 + 2 点退化"，或将 execution-report 文字修正为"缺失几何 → PROVIDER_SCHEMA_CHANGED（既有 malformed 政策）"。

### Known Gaps（不等于 Defect）

- **manual edit TRANSIT 仍为 Java 本地估算**（provider=DEMO、polyline 清空、estimated=true；`ItineraryService.applyTransitLegEdit` 未修改）；planner/replan-generated TRANSIT 为真实 AMAP（provider=AMAP/estimated=false）。**不能表述为"系统所有公交路线都已真实化"**。
- 无 multi-mode recommendation：WALKING vs TRANSIT vs DRIVING 自动选择属 B19-C。
- 无 Road/Taxi/Self-driving 语义模型：DRIVING 仍为 road baseline；TAXI 无真实 provider（B19-D）。
- 无 transit segment 持久化：线路/站点/换乘详情不落 DB（flat TransitLeg 设计）。
- 跨城 transit 有限：B19-B 只承诺同城；活动级 city 数据缺失时 city=trip.destination，跨城不静默查错城市（fail-closed），登记 Known Gap。
- replan 不经 `_route_cached`/budget 计数：B18-B 既有设计（所有 mode 一致），plan-b §10 已批准，非 B19-B 新增绕过。

---

## 20. Final Recommendation

```
B19-B 允许收口：YES（PASS_WITH_DEFECT；D1 非阻塞，需登记 follow-up）
是否允许进入 B19-C 计划阶段：YES（建议 D1 作为 B19-C 计划输入一并处理；B19-C 才承担 WALKING/TRANSIT/DRIVING 自动推荐）
```

理由：真实 AMAP TRANSIT provider 与真实 `segments[]` 结构完全一致（G1 独立真实调用复现：AMAP/1250s/3444m/2.0 元/654m/0 换乘/39 点/estimated=false）；cost 完整（normal/missing/empty/malformed 语义正确，unknown≠0）；duration/distance/cost/polyline 同源；walking_distance/transfer_count 语义正确；NO_RESULT fail-closed；cache 含日期+15min bucket+city/strategy/nightflag；route budget 覆盖显式 TRANSIT；普通 planner 不自动查 TRANSIT（Scope 门禁）；v11/v2 接受 TRANSIT 且 v10/v1 未放宽（schema+Java 双路径 matrix 全过）；Java consumer 与 Python producer 版本一致；B17 None-omit 无回归；DB/REST/Web 全程保持 TRANSIT；replan 同城可用、缺 city fail-closed；B18-B 基线 14 项与全量回归（Python 1626 / ruff / Web 447 / typecheck / Java 537）全部独立通过；scope 零污染。唯一缺陷 D1 为 polyline 缺失边界的行为/文档不一致，非阻塞。

**准确结论**：B19-B 已建立真实 TRANSIT Provider 与 v11/v2 全链路能力。WALKING vs TRANSIT vs DRIVING 的自动选择仍属于 B19-C。
