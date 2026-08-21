# B19-B Execution Report — Public Transit Provider（真实 TRANSIT + v11/v2 全链路）

- 实施日期：2026-08-19
- 基线：`docs/execution/B19/audit.md`、`docs/execution/B19/plan-b.md`；B18-A/B 已 PASS（未重新打开）
- 分支 / HEAD：`codex/feasibility-foundation` @ `d10e70c`
- 状态：**READY_FOR_ACCEPTANCE**

---

## 1. Verdict

```
READY_FOR_ACCEPTANCE
```

## 2. Workspace Baseline

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `d10e70cf354d096300c4a348d6aef585b8d82dc8` |
| dirty workspace | 约 100 项（含 B15/B16/B17/B18-A/B18-B 历史在途 + B19-A audit/plan + B19-B 增量），未执行任何 `git reset / restore / checkout . / stash / clean` |

**重要说明**：本轮**不是从零实施**，而是在**并行会话留下的 B19-B 部分实现**基础上补齐。开始时已有：`_amap_transit.py`/`_amap_transit_failures.py`/`_amap_transit_models.py`、`_route_contracts.py`（TRANSIT）、`planning_provider.py`（transit dispatch/cache/budget）、`replan_service.py`（city）、v11/v2 schema+fixtures、`test_amap_transit.py`/`test_b19_transit_chain.py`（45 passed）、Java parser 测试（v11/v2 用例，但生产未实现）、Web 测试。

## 3. Existing Implementation Audit（本轮开始时）

| 状态 | 内容 |
| --- | --- |
| ✅ 已有且正确 | `RouteMode=Literal["WALKING","DRIVING","TRANSIT"]`；`RouteRequest.city/destination_city/strategy/nightflag` + `require_city_for_transit`；`RoutePlan.walking_distance_meters/transfer_count`；transit adapter 主体（endpoint/params/error mapping/alt selection）；planner 内存 cache（15min bucket 含日期/city/strategy/nightflag）；route budget 共享；replan city；v11/v2 schema（`["WALKING","TRANSIT","DRIVING"]`，TAXI 不在）；`test_amap_transit.py`/`test_b19_transit_chain.py` 45 passed |
| ❌ 缺失/缺陷 | ① `_to_plan` 未解析 `cost`（models 无 cost 字段）——**本批补齐**；② **Java completion v11 / review v2 consumer 未实现**（测试已写但生产只支持 v9/v10 与 v1）——**本批补齐（consumer-first）**；③ **Python producer 未切 v11/v2**（仍写 v10/v1）——**本批补齐**；④ **models 使用 `steps` 结构但真实 AMAP 返回 `segments` 结构**（真实调用 `PROVIDER_SCHEMA_CHANGED`）——**本批重写为真实结构** |

## 4. Cost RED→GREEN

先写 deterministic 测试（`tests/test_amap_transit.py` 追加 COST 用例），RED 3 failed；再补齐 `_amap_transit_models._AmapTransitPath.cost` + `_to_plan.estimated_cost` 解析，GREEN 全过。

| Case | 输入 | 期望 | 结果 |
| --- | --- | --- | --- |
| COST-1 | `cost="2"` | `estimated_cost == 2.0` | PASS |
| COST-2 | `cost="2.5"` | `estimated_cost == 2.5` | PASS |
| COST-3 | `cost=""` / `cost` 缺失 | `estimated_cost is None`（**0=免费 vs None=未知，不写 0**） | PASS |
| COST-4 | `cost="abc"` | `ProviderFailure(PROVIDER_SCHEMA_CHANGED)`（沿用 driving/walking 的 malformed 政策，不静默 None） | PASS |

TRANSIT 的 `estimated_cost` 为 **provider actual cost（AMAP `transit.cost`）**，作为 source of truth；经 `_leg_from_route` → `TransitLeg.estimated_cost`，不与 Java/前端本地估算混用。

## 5. Java Consumer-first

**实际执行顺序（硬门禁）**：

```
1. Java completion parser 加 v11 分支（版本判断/activityId/provenance/transitId/evaluation/feasibilityReport/validTransitLeg/strictAdjacency 全部纳入 v11）
2. Java review parser 加 v2 分支（validateJsonTypes + validateDay domain 校验，v1 保持 WALKING/DRIVING、v2 加 TRANSIT）
3. Java parser 测试先跑通：PlanningCompletedEventParserTest（64）+ PlanningReviewRequiredEventParserTest（25）= 89 PASS
4. Python producer 才切 v11/v2（processor.py）
```

关键修复：Java parser 原先**无 mode enum 校验**（只查 isTextual）——按 plan-b §十三/§四十二 补齐版本化 enum（v10/v1: WALKING/DRIVING；v11/v2: WALKING/TRANSIT/DRIVING；TAXI 一律拒绝），保证"旧 contract 不放宽"。

## 6. Event Version Changes

| 事件 | 切换前 | 切换后 | 证据 |
| --- | --- | --- | --- |
| completion producer | v10（B16） | **v11**（`processor.py` 3 处 `PlanningCompletedEventV11`/`schema_version=11`） | `test_planning_worker`/`test_amqp_worker`/`test_planning_outcome_*`/`test_local_replanning`/`test_daily_skeleton_provider`/`test_planning_context_v3`/`test_provider_provenance`/`test_golden_matrix`/`test_candidate_validation` 断言更新至 v11/v2 后全绿 |
| review producer | v1 | **v2**（`PlanningReviewRequiredEventV2`/`schema_version=2`） | 同上 |

consumer 支持矩阵：Java completion v9/v10/v11（v9/v10 只读兼容）、review v1/v2（v1 只读兼容）。

## 7. Compatibility（旧版本不放宽）

| 事件版本 | WALKING | DRIVING | TRANSIT | TAXI |
| --- | --- | --- | --- | --- |
| completion v10（schema + Java） | PASS | PASS | **REJECT**（schema enum + Java enum 校验） | REJECT |
| completion v11（schema + Java） | PASS | PASS | **PASS** | **REJECT** |
| review v1 | PASS | PASS | **REJECT** | REJECT |
| review v2 | PASS | PASS | **PASS** | **REJECT** |

测试：`PlanningCompletedEventParserTest`（v10RejectsTransitLegs/v11 accepts）、`PlanningReviewRequiredEventParserTest`（v1RejectsTransitLegs/acceptsV2TransitLegs）、`test_messaging_contract_schemas.py`（v11 TRANSIT accept / TAXI reject）。`rejectsSchemaVersionNotOne` 更新为 `rejectsUnsupportedSchemaVersion`（v99 reject；v2 现合法）。

## 8. B17 Serializer Safety（None-omit 无回归）

- `test_fact_impact_omits_none_optional_fields_on_the_wire`（v10 语义 + v11 共用）仍在相关回归中 **PASS**：`date/targetPoiId/targetName/sourceUrl` 为 None 时序列化 **omitted**，不产生 `null`。
- v11 serializer 基于 v10 结构（`PlanningCompletedEventV11` payload=PayloadV10），B17 的 optional-field omission 行为原样保留；Java v11 分支不新增必填字段。

## 9. TRANSIT Provider Facts（真实解析）

| 事实 | 来源 | 验证 |
| --- | --- | --- |
| `mode="TRANSIT"` | 固定 | Golden G1 |
| `duration_seconds` | `transit.duration`（总耗时） | G1=1250s |
| `distance_meters` | `transit.distance`（总旅程，**非 haversine 冒充**） | G1=3444m |
| `estimated_cost` | `transit.cost`（缺失→None 不写 0；malformed→PROVIDER_SCHEMA_CHANGED） | G1=2.0 |
| `polyline` | 按 `segments[]` 顺序拼接 + 重复端点去重 + 无 polyline 段跳过；全缺退化 2 点 | G1=39 点 |
| `walking_distance_meters` | 顶层 `walking_distance` → 回退 `sum(walking.distance)` → 缺失 None | G1=654m |
| `transfer_count` | **vehicle segments - 1**（排除 walking 段；buslines 非空的 segment 才计 vehicle） | G1=0 |
| `provider="AMAP"` / `estimated=false` | 固定 | G1 |

**真实结构修复（关键）**：AMAP v3 transit 顶层是 `segments[]`（每段含 `walking`/`bus`/`taxi`，walking 的 polyline 在其 `steps[].polyline`，`buslines` 可能为空数组）——并行会话的 models 用假想 `steps` 结构，真实调用 `PROVIDER_SCHEMA_CHANGED`。本批重写 `_amap_transit_models.py`（`_AmapTransitSegment`/`_AmapSegmentWalking`/`_AmapSegmentBus`/`_AmapWalkingStep`）与 `_to_plan`/`_walking_polyline`，并用真实响应验证。

## 10. Cache / Budget

| 项 | 设计 | 验证 |
| --- | --- | --- |
| 内存 route cache key（TRANSIT） | `("TRANSIT", city, strategy, nightflag, origin, destination, departure_bucket.isoformat())` | `test_transit_cache_key_*`（city/strategy/nightflag 隔离、15min bucket：0/14 同桶 1 call、15 不同桶 2 calls、**日期隔离：08-19 与 08-20 同分钟不同 key**） |
| provider JSON cache key | 含日期+时间的确定性 hash（保守精确） | `test_amap_transit_cache_key_distinguishes_city_and_time` |
| 日期进入 bucket | `departure_bucket.isoformat()` 含 `YYYY-MM-DD` | Golden G3：08:00 vs 23:00 key 不同 |
| route budget | 所有 TRANSIT 经 `_route_cached` 统一计数，`MAX_ROUTE_CALLS_PER_PLAN=96` 超限 raise | `test_transit_and_driving_share_the_route_call_budget` |
| 普通 planner | `_route_for_pair` **无 TRANSIT 分支**（只有 `_route`/`_route_cached` 的显式 TRANSIT 路径） | grep 确认；B18-B 回归 79 passed |

## 11. Replan

- `replan_service.py:262-284`：复用 `existing_leg.mode`（含 TRANSIT）→ `RouteRequest(mode=..., city=city, departure_at=origin.end_time)`；city 来源 `command.payload.trip.destination`（同城规划）。
- **Same-city**：`test_local_replanning` 构造 TRANSIT leg → replan 请求 `mode="TRANSIT"` 且 transit provider 被调用（`requests[0].mode == "TRANSIT"`）PASS。
- **Missing city fail-closed**：`RouteRequest(mode="TRANSIT", city=None)` 被 `require_city_for_transit` 拒绝（明确失败，不默默查错城市）。
- **Cross-city**：B19-B 只承诺 same-city TRANSIT；跨城（机场/车站属其它城市）因当前模型无活动级 city 数据，`city=trip.destination` 为**已知限制**（plan-b §二十三），登记 Known Gap，不做复杂 city resolution。

## 12. Golden G1-G6

脚本：`C:\Windows\Temp\opencode\b19_b_golden.py`（真实 AMAP，未提交）。

| ID | 场景 | 结果 |
| --- | --- | --- |
| **G1** | 正佳广场→广州塔，显式 `mode=TRANSIT`（真实 AMAP） | **PASS**：`mode=TRANSIT / duration=1250s / distance=3444m / cost=2.0 / walking_distance=654m / transfer_count=0 / polyline=39点 / provider=AMAP / estimated=false`；步骤含"乘坐APM线(林和西--广州塔)"（2790m/690s）+ 步行（95m/81s） |
| **G2** | metadata（walking_distance/transfer_count/polyline 解析；线路名/type 可从 provider 响应读取，不持久化） | **PASS** |
| **G3** | 同 OD 08:00 vs 23:00 → `date/time` 不同、cache key 不同 | **PASS**（真实结果是否不同不强制断言） |
| **G4** | TRANSIT NO_RESULT（fixture `transits=[]`） | **PASS**（`test_amap_transit_empty_transits_is_a_typed_not_found_failure`：`ProviderFailure/ROUTE_NOT_FOUND`，无假路线、无 DRIVING 冒充） |
| **G5** | v11 全链路（Python→v11→Java→DB→REST→Web） | **PASS**（等价证据链：Python `TransitLeg(mode=TRANSIT)` → v11 schema/fixtures → Java parser v11 TRANSIT accept → Java persistence（`PlanningCompletionFlowIntegrationTest` 在 Java 537 全量中）→ Web `TransitLegControl.test.ts` persisted TRANSIT 显示"公交/地铁"） |
| **G6** | v10/v1 兼容（v10 WALKING/DRIVING PASS、v10 TRANSIT REJECT；review v1 同理） | **PASS**（Java parser 测试 + schema 测试） |

## 13. Full-chain G5（详细）

```
Python RoutePlan(mode=TRANSIT, provider=AMAP, estimated=false)
  → TransitLeg.mode=TRANSIT（contracts.py ItineraryTransitMode 既有 4 值）
  → completion v11（processor.py schema_version=11）→ event JSON
  → Java PlanningCompletedEventParser v11 分支（transitId 白名单、mode enum 校验、validTransitLeg）
  → DB transit_leg.mode='TRANSIT'（V23 CHECK 已含，无 migration）
  → REST/mapper（mode 透传）
  → Web persisted mode → TransitLegControl modeLabel '公交/地铁'
mode=TRANSIT / provider=AMAP / estimated=false 全程保持，无改写。
```

## 14. API Evidence

| 项 | 值 |
| --- | --- |
| 真实 AMAP transit 调用 | 本轮：G1（1 次成功）+ G3（2 次参数构造，无额外请求）+ 结构探针（2 次）= 约 5 次；全部成功，**0 限流** |
| latency | 单次 transit 请求正常（G1 秒级返回） |
| rate limit / quota | 无限流记录（B19-A 已证实 transit endpoint 独立可用；walking/driving route API 的限流观察与 B19-B 无关） |
| 普通 planner API calls | **不增加**（`_route_for_pair` 无 TRANSIT；B18-B 回归证明默认调用序列不变） |

## 15. Regression

```
Python targeted:  pytest tests/test_amap_transit.py tests/test_b19_transit_chain.py
                  → 51 passed（含新增 COST-1~4、日期隔离、缺失 walking_distance 等）
Python related:   pytest test_transit_mode test_b18_a_recall test_route_provider
                  test_must_visit_recall test_planning_worker test_local_replanning
                  test_daily_skeleton_provider test_planning_outcome_* test_amqp_worker
                  test_messaging_contract_schemas test_golden_matrix
                  test_candidate_validation test_provider_provenance
                  test_planning_context_v3                              → 数百 passed
Python full:      pytest -q --basetemp=%LOCALAPPDATA%\Temp\pytest-b19b-tmp2
                  → 1626 passed, 37 skipped, exit 0
ruff:             ruff check src/trip_agent tests → All checks passed!
Web targeted:     vitest run tests/TransitLegControl.test.ts tests/transit.test.ts → 9 passed
Web full:         vitest run → 42 files / 447 passed
Web typecheck:    vue-tsc -b → exit 0
Java:             mvn -pl apps/travel-server test（JDK 21；需 Docker Desktop 就绪）
                  → 537 tests, 0 failures, 0 errors（57 个报告文件；含 v11/v2 parser、持久化/集成）
```

说明：默认 `C:\Windows\Temp\pytest-of-*` ACL 环境问题（B18 已记录）——指定可写 `--basetemp` 后全量通过。Java 集成测试依赖 Testcontainers（Docker Desktop 需运行）；本轮启动 Docker 后全量 537/0/0。

## 16. B17/B18 Regression

- **B18-A**：`test_b18_a_recall.py` 未触碰，must-visit/recall 语义不变（回归 PASS）。
- **B18-B**：`_route_for_pair` 未修改（普通 planner 仍 walkable→WALKING / 否则 DRIVING）；`test_transit_mode.py` 79 passed（B1-B9）；短距离/长距离/walking fallback 行为不变。
- **B17**：fixed-slot/capacity/departure 相关（`test_local_replanning`/`test_daily_skeleton_provider`/`test_planning_worker`）全绿；v11 serializer None-omit 无回归。

## 17. Scope Audit

| 检查项 | 结果 |
| --- | --- |
| multi-mode scorer / auto recommendation | ✅ 无（`_route_for_pair` 无 TRANSIT；provider 只做显式查询） |
| PUBLIC_TRANSIT 新 enum | ✅ 无（复用 TRANSIT） |
| ROAD enum / TAXI provider / self-driving / transport preference | ✅ 无 |
| 驾车/打车 UI 合并 / 交通 UI 重构 | ✅ 无（Web 生产代码 0 修改，仅测试） |
| segments DB 持久化 / 线路详情 schema | ✅ 无（flat TransitLeg；metadata 仅 provider/planner 内部） |
| DB migration | ✅ **NO**（V23 CHECK 已含 TRANSIT） |
| B18-C diversity / B18-D parent dedup | ✅ 无 |

B19-B 可识别增量文件：Python `_amap_transit.py`/`_amap_transit_failures.py`/`_amap_transit_models.py`（新）、`_route_contracts.py`/`planning_provider.py`/`replan_service.py`/`processor.py`（增量）、`contracts/messaging/planning-completed-event-v11.schema.json` + `planning-review-required-event-v2.schema.json` + fixtures（新）、`contracts/messaging/README.md`、Java 两个 parser + 测试、`tests/test_amap_transit.py`/`test_b19_transit_chain.py`（新）+ 若干测试断言更新（v10→v11 产出）、Web 两个测试文件（+29 行纯测试）。其余 dirty 为历史在途批次。

## 18. Known Gaps

- **manual edit TRANSIT 仍为 Java 本地估算**（provider=DEMO、polyline 清空、estimated=true）——planner-generated TRANSIT 是真实 Provider route；手动编辑不一致登记为 B19-D / follow-up。Web 初始加载显示 persisted mode（`transitModeFor(leg)`），不会自动覆盖真实 transit。
- **无 multi-mode recommendation**：WALKING vs TRANSIT vs DRIVING 自动选择属 B19-C。
- **无 Road/Taxi/Self-driving 语义模型**：DRIVING 仍为 road baseline；TAXI 无真实 provider——属 B19-D。
- **无 transit segment 持久化**：线路/站点/换乘详情不落 DB（B19-B flat 设计）。
- **跨城 transit 有限**：B19-B 只承诺 same-city；活动级 city 数据缺失，跨城为已知限制。

## 19. Final Recommendation

```
B19-B 允许收口：YES
建议进入独立验收：YES
```

理由：真实 TRANSIT provider（AMAP v3 transit/integrated）经真实 Golden G1-G3 验证（mode/duration/distance/cost/polyline/walking_distance/transfer_count 全部正确）；cost 真实解析且未知不写 0；v11/v2 event 全链路（Python→Java→DB→Web）保持 TRANSIT/AMAP/false；consumer-first 顺序真实执行；v10/v1 旧语义未放宽（TAXI 不进 v11/v2）；B17 None-omit 无回归；cache 含日期+15min bucket；route budget 覆盖 TRANSIT；普通 planner 不自动查 TRANSIT（Scope 门禁）；DB 零 migration；全量回归（Python 1626 / ruff / Web 447 / typecheck / Java 537）全部通过。

**准确表述**：B19-B 建立了真实 TRANSIT Provider 与 v11/v2 全链路能力。WALKING vs TRANSIT vs DRIVING 的自动选择仍属于 B19-C。
