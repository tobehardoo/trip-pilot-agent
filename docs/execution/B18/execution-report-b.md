# B18-B Execution Report — Transport Mode Baseline (Walking / Driving)

- 实施日期：2026-08-18
- 依据：`docs/execution/B18/audit.md`（P18-R1）、`docs/execution/B18/plan.md`（§4 B18-B Design）、`docs/execution/B18/execution-report-a.md` / `acceptance-report-a.md`（B18-A 已 PASS，本轮未改动其语义）
- 状态：**READY_FOR_ACCEPTANCE**

---

## 1. Scope

本批仅实施 **B18-B — Transport Mode Baseline**：

> 消灭"planner 所有 TransitLeg 硬编码 DRIVING、极短距离路段显示驾车"的明确缺陷，建立 Walking / Driving 第一版可靠 baseline。

目标语义（plan.md §4.2 决策流程）：

```
haversine ≤ WALKING_PREFILTER_METERS ?
├─ 否 → 查 DRIVING → DRIVING（road baseline）
└─ 是 → 查 WALKING
      ├─ 成功 且 duration ≤ WALKING_THRESHOLD_SECONDS → WALKING（用 walking 数据）
      ├─ 成功 但 duration > 阈值 → 查 DRIVING → DRIVING
      └─ 可降级 provider 失败 → 查 DRIVING → DRIVING
```

明确不在本批范围（未实施、未触碰）：公共交通 / 地铁 API、多模式评分、TAXI route provider、enum 增删（DRIVING/TAXI 保留）、DB migration、contract breaking change、用户自驾约束、驾车/打车前端按钮合并、B18-C diversity、B18-D parent/complex dedup、B18-A must-visit/recall/ranking。

## 2. Workspace Baseline

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `d10e70cf354d096300c4a348d6aef585b8d82dc8` |
| 工作区状态 | B15/B16/B17/B18-A 在途修改保持原样；本轮未执行任何 `git reset / restore / checkout . / stash / clean` |

目标文件 `planning_provider.py` 在实施前已含 B15/B16/B17/B18-A 在途修改；本轮仅做最小增量（见 §7），未覆盖既有内容。

## 3. Root Cause Reconfirmation

重新确认（生产代码修改前复核）：

- 全仓唯一 `RouteRequest(...)` 调用点位于 `planning_provider.py` `_emit_day`，`mode="DRIVING"` 硬编码（原 :1093，本轮修改后移除）。
- `RouteMode = Literal["WALKING", "DRIVING"]`（`_route_contracts.py:16`），AMAP provider 仅 walking/driving 两个 endpoint。
- DB 铁证：`business.transit_leg` 34/34 条 `mode='DRIVING'`，含「正佳广场 → 小林蓝鳄正佳广场」1m/1s/DRIVING。
- `TransitLeg.mode` 来自 `route.data.mode`（`_leg_from_route`），即 provider 对 request.mode 的响应——DRIVING 是 planner 主动指定的，非 AMAP 自动选择/Java 默认/前端默认。

## 4. RED Evidence（B1-B9）

测试文件：`apps/agent-service/tests/test_transit_mode.py`（本轮新增）+ `apps/web/tests/transit.test.ts` / `TransitLegControl.test.ts`（补充 Web 行为测试）。

| ID | 断言 | baseline（修复前） | expected | actual（修复后） |
| --- | --- | --- | --- | --- |
| B1 | 1m/同坐标 leg → WALKING | **RED**（无条件 DRIVING；`transit_mode` 模块不存在） | WALKING，只查 WALKING | PASS |
| B2 | 可步行（walking 600s）→ WALKING，事实来自 walking | **RED** | WALKING + walking facts | PASS |
| B3 | walking 1500s 超 20min → 再查 DRIVING → DRIVING | **RED** | DRIVING，calls=[WALKING, DRIVING] | PASS |
| B4 | 长距离（市区→机场 29km）→ 只查 DRIVING | **baseline already GREEN**（无条件 DRIVING 恰好符合"不查 walking"） | DRIVING，calls=[DRIVING] | PASS |
| B5 | walking 可降级失败 → fallback DRIVING，规划继续 | **RED**（无 walking 分支） | DRIVING，calls=[WALKING, DRIVING] | PASS |
| B6 | walking+driving 均失败 → 既有 provider error policy | **baseline already GREEN**（drive 失败 raise） | `PlanningProviderError` 抛出 | PASS |
| B7 | mode/duration/distance/polyline 来源一致（walking 与 driving 各自独立断言） | **RED**（无 walking leg 可验证） | 单一 route 来源 | PASS |
| B8 | WALKING cost=0（不继承 driving cost）；DRIVING 行为不回归 | **RED**（walking leg 不存在，cost 语义无法走通） | cost=0 + RULE_ESTIMATE | PASS |
| B9 | contract/DTO/Java/DB 兼容 WALKING；Web 初始显示"步行" | **baseline already GREEN**（contracts.py:659、ItineraryService.java:425、lib/transit.ts:71、modeLabel WALKING='步行' 均已就绪） | 补充验证/锁定测试 | PASS（Python 1 + Web 3） |

RED 阶段实测：`ModuleNotFoundError: No module named 'trip_agent.planning.transit_mode'`（collection error，B1-B9 全部无法收集）。B4/B6/B9 记录为 **baseline already GREEN**（既有行为本就正确，不强行制造失败）。

## 5. Threshold Calibration（真实 AMAP）

脚本：`C:\Windows\Temp\opencode\b18_b_calibrate.py`（未提交）。真实 AMAP POI 搜索获取坐标 + 真实 walking route 查询。

| Case | Pair | Haversine | AMAP Walk Dist | Walk Duration | 结论 |
| --- | --- | ---: | ---: | ---: | --- |
| C0 | 广州天河体育中心 → 正佳广场 | 623 m | 272 m | 218 s | walkable（3.6 min） |
| C1/C2 | 广东省博物馆 → 广州塔 | 946 m | 2120 m | 1696 s | **超阈值**（28 min） |
| C3/C4 | 广东省博物馆 → 正佳广场 | 1934 m | 2008 m | 1606 s | **超阈值**（27 min） |
| C5 | 广东省博物馆 → 正佳广场（重试） | 1934 m | FAILED | — | route API 限流（样本截断，不编造数据） |

**关键观察**：haversine 明显低估真实步行距离（946 m 直线 → 2120 m 实际步行，≈2.2×）。样本中 walkable 的直线距离 ≤623 m；946 m 及以上实际均超 20 分钟。

## 6. Design Decision

| 常量 | 值 | 理由 |
| --- | --- | --- |
| `WALKING_THRESHOLD_SECONDS` | **1200**（20 分钟） | 业务阈值：实际步行 ≤20 分钟认为该 leg 适合步行（与前端 `lib/transit.ts:71` 的 `20 * 60` 语义对齐，plan.md §4.6 方案 B）。 |
| `WALKING_PREFILTER_METERS` | **1500** | API 成本预筛，**非**"用户最多走 1500 米"规则。理由：① 校准显示 haversine 低估步行距离 ~2×，直线 1500 m 以内的 leg 存在真实 ≤20min 步行可能；② 保守原则"宁多查少量 walking，不漏掉真实 ≤20min walking"（plan.md §3.2 / §三十一）；③ 代价可承受：prefilter 内超时/失败才发生 1 次额外 walking 查询，路线预算 96 次/规划余量充足。 |

**边界记录**：prefilter 是纯成本优化。`1500 + 10 m` 的 leg 不会发起 walking 查询（可能漏掉一个实际 ≤20min 的步行，换取 1 次 API 节省）。若后续真实数据表明 1500 m 内大量 leg 实际超阈值导致双查比例偏高，应评估更宽松 prefilter，而非设计复杂 scoring。

## 7. Production Changes

| 文件 | 修改 | 为什么 |
| --- | --- | --- |
| `apps/agent-service/src/trip_agent/planning/transit_mode.py`（**新增**） | 纯规则模块：`straight_line_distance_meters`（haversine）、`should_try_walking`（prefilter，成本优化）、`is_walkable`（业务阈值），常量 `WALKING_THRESHOLD_SECONDS=1200`、`WALKING_PREFILTER_METERS=1500` | 纯判定函数不联网、可独立单测；职责：transit_mode=纯规则，planning_provider=route IO/fallback/leg 构造（plan.md §十二） |
| `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py` | ① `_emit_day` 移除 `RouteRequest(mode="DRIVING")` 硬编码，改调新 `_route_for_pair`；② 新增 `_route_for_pair`（prefilter→walking→阈值判定→DRIVING fallback 决策）；③ 新增 `_try_walking_route`（walking 可降级失败→返回 None→DRIVING；非可降级失败保持 raise）；④ 模块级 `_RECOVERABLE_WALKING_CATEGORIES`（TIMEOUT/NETWORK_ERROR/PROVIDER_UNAVAILABLE/RATE_LIMITED/NO_RESULT/UNSUPPORTED_MODE，与 fallback policy 的 local/explicitly-allowed 对齐） | 消灭硬编码 DRIVING；walking 成功且 ≤阈值用 walking route（所有事实来自该响应）；超阈值或失败走 DRIVING baseline；不吞编程/契约类异常（INTERNAL/AUTH/PERMISSION/INVALID/MALFORMED/QUOTA 保持 raise） |

**Route fact integrity**：`_route_for_pair` 返回的 `ProviderSuccess[RoutePlan]` 被 `_leg_from_route` 原样使用（mode/distance/duration/polyline/cost/cost_source 全部取自同一响应对象），不存在 walking duration + driving polyline 混用路径。`_route_cached` cache key 含 `request.mode`，walking/driving 缓存分离。

**Cost 语义**：`_transit_cost` 对 WALKING 返回 `Decimal("0.00")`、`cost_source=RULE_ESTIMATE`（既有逻辑，未改动）——WALKING leg 不继承任何 driving cost。

## 8. GREEN Evidence（B1-B9）

命令（`apps/agent-service` 下）：

```
./.venv/Scripts/python.exe -m pytest tests/test_transit_mode.py -q
→ 14 passed
```

Web 补充测试（`apps/web` 下）：

```
./node_modules/.bin/vitest run tests/transit.test.ts tests/TransitLegControl.test.ts
→ 8 passed（含新增 20 分钟边界×2 + persisted WALKING 初始显示"步行"×1）
```

## 9. Golden G2 / G3 / G4（真实 AMAP）

脚本：`C:\Windows\Temp\opencode\b18_b_golden.py`（未提交），真实 `AmapRouteProvider` 经 `_route_for_pair`。

| Case | Pair | straight-line | 查询序列 | 结果 |
| --- | --- | --- | --- | --- |
| **G2** | 正佳广场 → 小林蓝鳄正佳广场（同坐标，审计 1m/1s/DRIVING 案例） | 0 m | `[WALKING]` | **WALKING**，14 m / 11 s，provider=AMAP |
| **G3** | 广州天河体育中心 → 正佳广场（真实短距离） | 623 m | `[WALKING]` | **WALKING**，272 m / 218 s，provider=AMAP |
| **G4** | 正佳广场 → 广州白云机场 | ~29 km | `[DRIVING]` | **DRIVING**，38972 m / 3675 s，provider=AMAP，无无意义 walking 查询 |

G2 直接复现并修复了 DB 中「正佳广场 → 小林蓝鳄正佳广场 1m/DRIVING」缺陷（现为 14m/11s/WALKING）。

## 10. Route Integrity

- G2/G3 的 leg：mode/distance/duration/polyline 全部来自同一次 AMAP WALKING 响应（`_route_for_pair` 直接返回 walking `ProviderSuccess`）。
- G4 的 leg：全部来自 AMAP DRIVING 响应。
- B7 双断言（walking/driving 各自独立）在 `_route_for_pair` 层验证 polyline/distance/duration 与 scripted plan 完全一致。
- B8：WALKING leg `estimated_cost=Decimal("0.00")`、`cost_source=RULE_ESTIMATE`；DRIVING leg 行为不回归。

## 11. API Cost

| 项 | 值 |
| --- | --- |
| 普通 leg | 1 次 route request（长距离直接 DRIVING；短距离通常 1 次 WALKING） |
| 短距离双查（walking 超阈值或 walking 可降级失败） | 2 次（WALKING + DRIVING） |
| 最坏增长 | 每 leg ≤2 次（仅 prefilter 内且 walking 不满足时） |
| 硬边界 | `MAX_ROUTE_CALLS_PER_PLAN = 96`（`domain/shared.py:41`）保留，`_route_cached` 超限 raise `ROUTE_CALL_BUDGET_EXHAUSTED` |
| 真实 Golden | G2 1 次、G3 1 次、G4 1 次（单查，无浪费） |
| 真实 Smoke | 完整规划 route 层触发 AMAP route API 限流（配额限制，见 §13）——POI 层无限制 |

缓存：`_route_cached` key 含 mode，walking/driving 分离，同规划重复 pair 命中。

## 12. Full Regression

```
Python targeted: pytest tests/test_transit_mode.py                → 14 passed
Python related:  pytest test_transit_mode test_route_provider
                 test_demo_ordering test_must_visit_recall
                 test_planning_worker test_local_replanning       → 95 passed
Python full:     pytest -q --basetemp=%LOCALAPPDATA%\Temp\pytest-b18b-tmp
                                                                  → 1557 passed, 37 skipped, exit 0
ruff:            ruff check src/trip_agent tests                   → All checks passed!
Web vitest:      vitest run                                        → 42 files / 446 passed
Web typecheck:   vue-tsc -b                                       → exit 0
Java:            mvn -pl apps/travel-server test (JDK21)          → 533 tests, 0 failures, 0 errors
```

说明：默认 `C:\Windows\Temp\pytest-of-*` 的 ACL 损坏（WinError 5，B18-A 已记录的环境问题）——指定可写 `--basetemp` 后全量通过。

## 13. Real Provider Smoke

**执行方式**：Python 层真实 AMAP（REAL_ONLY + 真实 `AMAP_WEB_SERVICE_KEY`），脚本 `C:\Windows\Temp\opencode\b18_b_smoke.py`（未提交）。

- **Smoke 1**（广州 2日 must_visit=正佳广场）与 **Smoke 2**（广州 3日 普通规划）均因 **AMap route API rate limit** 未完成完整规划。
- 该限流与 B18-A 时期观察一致：AMAP key 的 route 配额（日配额/QPS）已受限，发生在 route endpoint，**非 POI endpoint**（POI 层在 B18-A/本批多次成功），**非 B18-B 双查询放大**（完整规划第一步 route 查询即触发，此前 Golden 的 3 次单查成功）。
- 处理：未重复重试消耗配额，未伪造 PASS。B18-B 核心模式决策已由 Golden G2/G3/G4（真实 provider）+ B1-B9（模拟 provider 全链路）覆盖。

## 14. Scope Audit

| 检查项 | 结果 |
| --- | --- |
| B18-A 语义 | ✅ 未改动（must-visit identity / recall / ranking 无变更；`test_b18_a_recall.py` 未触碰） |
| 公共交通 / 地铁 API | ✅ 无 |
| 多模式 scoring / best-route selector | ✅ 无（仅阈值规则） |
| TAXI route provider / enum 增删 | ✅ 无（`RouteMode`/`ItineraryTransitMode`/DB enum 不变） |
| 驾车/打车前端按钮合并 | ✅ 无（仅补 Web 行为测试，`TransitLegControl.vue` 未改） |
| DB migration / contract breaking change | ✅ 无 |
| B18-C diversity / B18-D parent-complex dedup | ✅ 无 |
| 用户自驾约束 | ✅ 无 |

## 15. Follow-ups

| 编号 | 内容 |
| --- | --- |
| — | Public transit / metro integration（AMAP transit API，需 city code/transfer/计价模型） |
| — | Road / Taxi / Self-driving 产品语义（DRIVING 当前只是 road baseline，不代表"用户有私家车"） |
| — | 驾车 + 打车前端按钮收敛（产品已反馈可合并，仅登记） |
| — | 真正 multi-mode recommendation（score 模型，非阈值规则） |
| B18-C | itinerary diversity objective |
| B18-D | parent/complex semantic dedup |
| （观察） | 真实 AMAP route 配额限制影响完整 compose 冒烟——环境限制，非代码缺陷；短距离双查的 API 增量在此配额下需业务侧评估 |

## 16. Verdict

**READY_FOR_ACCEPTANCE**

B18-B 验收标准对照：
- [x] planner 不再无条件 `mode="DRIVING"`（硬编码移除，改 `_route_for_pair` 决策）
- [x] 极短距离不再 DRIVING（G2：同坐标 → WALKING）
- [x] walking ≤20min 可选择 WALKING（G3：218s → WALKING；B2）
- [x] 超过 walking threshold 使用 DRIVING baseline（B3：1500s → DRIVING）
- [x] 明显长距离不查询 walking（B4/G4：只 DRIVING）
- [x] walking 可降级失败 fallback driving（B5）
- [x] walking+driving 均失败保持既有错误策略（B6）
- [x] mode/duration/distance/polyline 来源一致（B7/G2/G3/G4）
- [x] WALKING cost 正确（B8）
- [x] persistence 不覆盖 WALKING（contracts/Java 白名单既有；B9）
- [x] frontend 正确展示 persisted WALKING（modeLabel 步行；B9）
- [x] route request 数仍有硬边界（96 上限保留）
- [x] B17 fixed-slot/capacity 相关测试无回归（related 95 + 全量 1557 passed）
- [x] 无公共交通/enum/DB breaking scope 扩张

**正确表述**：B18-B 已建立 Walking / Driving baseline，解决明显短距离 DRIVING 错误；公共交通、Taxi/Road 语义和真正 multi-mode recommendation 仍属于后续阶段。

**B18-B 结束，按指令停止，不自动继续后续批次。**
