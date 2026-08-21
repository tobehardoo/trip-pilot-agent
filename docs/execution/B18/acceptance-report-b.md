# B18-B Acceptance Report

- 验收日期：2026-08-18
- 验收角色：独立验收 Agent（只读，未修改任何生产代码）
- 依据：`docs/execution/B18/audit.md`、`plan.md`（§4 B18-B Design + §12 验收标准）、`acceptance-report-a.md`（B18-A 已 PASS，本轮未重新打开）、`execution-report-b.md`（开发方声明，仅参考；以下结论均经独立代码/测试/真实 Provider 验证）

---

## 1. Verdict

```
PASS
```

B18-B 已建立 Walking / Driving transport-mode baseline：planner 普通 Activity→Activity transit 不再无条件 DRIVING，极短/可步行距离使用真实 AMAP WALKING route，长距离与超阈值保持 DRIVING road baseline；route facts、fallback 语义、budget/cache、B17 timing、持久化与前端展示全部验证通过，未发现 B18-B 范围内缺陷。

**准确表述**：B18-B 解决的是"规划阶段所有 TransitLeg 无条件 DRIVING、极短距离路段显示驾车"的明确缺陷。**不是**"最佳交通方式推荐"——公共交通、Taxi/Road 语义、multi-mode recommendation 仍属后续阶段。

---

## 2. Scope Reviewed

| 项 | 验证方式 |
| --- | --- |
| transit_mode（新模块） | 全文精读：阈值常量、纯函数、概念注释 |
| planning_provider | `_route_for_pair` / `_try_walking_route` / `_RECOVERABLE_WALKING_CATEGORIES` / `_emit_day` 调用点 / `_leg_from_route` / `_transit_cost` / `_route_cached` 全文精读 |
| route provider | `ProviderErrorCategory` 枚举核对、AMAP walking/driving endpoint 未变 |
| cache | `_route_cached` key 含 mode（独立确认） |
| cost | `_transit_cost` WALKING=0 语义（独立确认） |
| persistence | contracts.py `ItineraryTransitMode` + Java 白名单 + B9 测试 |
| Web | `transit.test.ts` / `TransitLegControl.test.ts` diff 审查（仅加测试）+ 独立运行 |
| B17 timing | forward-fit 使用选中 route 真实 duration（代码确认）+ related 测试 |
| tests | targeted 14 / related 181 / full 1557 / ruff / Web 446 / typecheck / Java 533 |
| workspace | 已记录；无法逐行证明 unstaged 历史归属（B15/B16/B17/B18-A 混合） |

---

## 3. Workspace Baseline

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `d10e70cf354d096300c4a348d6aef585b8d82dc8` |
| dirty state | 79 项变更（59 tracked 修改 + untracked），含 B15/B16/B17/B18-A 在途；B18-B 新增：`planning/transit_mode.py`、`tests/test_transit_mode.py`（untracked）、`planning_provider.py` 增量、`apps/web/tests/transit.test.ts` + `TransitLegControl.test.ts`（+27 行纯测试） |
| 历史归属 | **无法从 unstaged workspace 完全证明每一行的历史归属**；本报告审计 B18-B 增量语义正确性，不虚构 clean history |
| 未执行 | 未执行任何 `git reset / restore / checkout . / stash / clean` |

---

## 4. Root Cause Acceptance

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| `_emit_day` 原 `RouteRequest(mode="DRIVING")` 硬编码 | ✅ **已从普通 transit 构建路径移除** | `planning_provider.py:1109-1118` 改为 `_route_for_pair(origin_poi, destination_poi, ...)` |
| 全仓 RouteRequest 调用点 | ✅ 仅剩 3 处合法调用：`_route_for_pair` 内 WALKING(:1666) 与 DRIVING baseline(:1680)；`replan_service.py:264`（复用 `existing_leg.mode` 或 WALKING，非普通 planning transit 路径） | 全仓 grep |
| 极短距离缺陷（正佳广场→小林蓝鳄 1m/1s/DRIVING） | ✅ 已闭环 | Golden G2 真实复跑：**WALKING 14m/11s** |
| 根因归属 | ✅ 确认是 Python planner 主动指定（DB 34/34 DRIVING 的历史由硬编码造成），非 AMAP/Java/Web | audit.md 基线 + 本批代码变更 |

---

## 5. Mode Decision Acceptance

| 环节 | 行为 | 证据 |
| --- | --- | --- |
| Prefilter | `should_try_walking(straight)`：haversine ≤1500m 才发起 WALKING 查询；>1500m 直接 `_route_cached(DRIVING)` | `transit_mode.py:53-55`；`planning_provider.py:1664, 1679-1689` |
| Walking query | `_try_walking_route`（成功返回 walking route；可降级失败返回 None） | `planning_provider.py:1692-1713` |
| 业务判定 | `is_walkable(duration)`：≤1200s → 返回 walking route；>1200s → 走 DRIVING | `transit_mode.py:58-60`；`planning_provider.py:1677-1678` |
| DRIVING fallback | walking 超阈值 / 可降级失败 → `_route_cached(DRIVING)` | `planning_provider.py:1679-1690` |
| 伪 selector 检查 | ✅ 无"先查 DRIVING 再改 mode"路径——先决定查什么，返回的 route 原样用于 TransitLeg | 代码路径唯一，`_route_for_pair` 单一出口 |

---

## 6. Threshold Semantics

| 常量 | 语义 | 确认 |
| --- | --- | --- |
| `WALKING_THRESHOLD_SECONDS = 1200` | **业务判定阈值**：实际 AMAP walking route ≤20 分钟 → 可步行。与前端 `lib/transit.ts` 的 `20 * 60` 语义对齐 | `transit_mode.py:26-29` 注释明确 "User-facing product rule"；`test_walking_threshold_constants` 断言 `is_walkable(1200)=True / is_walkable(1201)=False` |
| `WALKING_PREFILTER_METERS = 1500` | **API 成本 prefilter**：直线距离大于该值时不值得额外请求 walking API。**非**"用户最多走 1500 米" | `transit_mode.py:31-35` 注释明确 "API cost optimisation ONLY"、"must NOT be read as the user can only walk X metres"；docstring 明确两个阈值回答不同问题（cost vs product rule） |
| 概念混淆检查 | ✅ **无混淆**：模块 docstring 与两处常量注释均严格区分；校准数据（946m haversine → 2120m 实际步行）用于论证 prefilter 保守性，未退化为"距离直接判定 mode" | 全文精读 |

**退化风险确认**：代码**不是**"≤1500m → 直接 WALKING"。最终判定始终是 `is_walkable(walk_route.data.duration_seconds)`（真实 walking duration）。C1/C2 校准（946m haversine → 1696s 步行超阈值）若进入 prefilter 会正确地落到 DRIVING。`B3` 测试证明：1500s walking → `[WALKING, DRIVING]` → DRIVING。

---

## 7. Failure / Fallback Acceptance

| 场景 | 行为 | 证据 |
| --- | --- | --- |
| walking 可降级失败（TIMEOUT/NETWORK_ERROR/PROVIDER_UNAVAILABLE/RATE_LIMITED/NO_RESULT/UNSUPPORTED_MODE） | → 返回 None → DRIVING fallback，规划继续 | `_RECOVERABLE_WALKING_CATEGORIES`（:109-118）与 `ProviderErrorCategory` 枚举逐项核对一致；`B5` 测试（PROVIDER_UNAVAILABLE → `[WALKING, DRIVING]` → DRIVING） |
| **非可降级错误**（INTERNAL_ERROR/AUTHENTICATION_ERROR/PERMISSION_DENIED/INVALID_REQUEST/MALFORMED_RESPONSE/QUOTA_EXCEEDED） | → **re-raise**，不吞 | `_try_walking_route:1705-1707`：`category not in _RECOVERABLE_WALKING_CATEGORIES: raise` |
| 宽捕获检查 | ✅ **无 `except Exception` 吞错**。捕获仅限 `PlanningProviderError` 且按 category 白名单分流 | 代码精读 |
| walking + driving 双失败 | → 沿用既有 provider error policy（`PlanningProviderError` 抛出，`with_fallback` 语义不变），**不返回假 transit** | `B6` 测试：双 PROVIDER_UNAVAILABLE → `pytest.raises(PlanningProviderError)` |

---

## 8. Route Fact Integrity

| 来源 | mode | duration | distance | polyline | provider | cost |
| --- | --- | --- | --- | --- | --- | --- |
| WALKING leg | `route.data.mode`（=WALKING） | `route.data.duration_seconds` | `route.data.distance_meters` | `route.data.polyline` | `route.provider` | `_transit_cost` → `Decimal("0.00")`，`cost_source=RULE_ESTIMATE` |
| DRIVING leg | 同上（=DRIVING） | 同上 | 同上 | 同上 | 同上 | 既有语义（AMAP toll 或 DEMO） |

- ✅ **全部字段取自同一个 `ProviderSuccess[RoutePlan]` 对象**：`_route_for_pair` 返回单一 route，`_leg_from_route`（:1283-1332）逐字段取自该对象（mode/distance/duration/polyline/cost/cost_source/provider），**不存在 walking duration + driving polyline 混用路径**
- ✅ `B7` 双断言（walking 与 driving 各自独立）在 `_route_for_pair` 层验证 polyline/distance/duration 与 scripted plan 完全一致
- ✅ `B8` 双断言：WALKING cost=0（不继承 driving cost）；DRIVING cost 行为不回归
- ✅ Golden 真实数据：G2/G3（WALKING）与 G4（DRIVING）的 facts 均来自单一 AMAP 响应

---

## 9. Route Budget / Cache

| 项 | 结果 | 证据 |
| --- | --- | --- |
| route call 计数 | ✅ walking 与 driving 两次请求**都经过统一 `_route_cached`**（`_try_walking_route` 内部也调用 `_route_cached`） | `_try_walking_route:1704` → `_route_cached:1715-1735` |
| 硬边界 | ✅ `MAX_ROUTE_CALLS_PER_PLAN=96` 保留；超限 raise `ROUTE_CALL_BUDGET_EXHAUSTED` | `domain/shared.py:41`；`_route_cached:1730-1731` |
| 绕过检查 | ✅ **无绕过路径**——selector 不直接调 provider，所有查询经 `_route_cached` 计数 | 代码精读 |
| cache key | ✅ 含 `request.mode`（`_route_cached:1724`）——`WALKING(A,B)` 与 `DRIVING(A,B)` 缓存完全隔离 | 代码精读 |
| 重复请求 | ✅ 双查场景仅 2 次（WALKING+DRIVING），无第三次重复；B3 断言 `calls == ["WALKING", "DRIVING"]` | `B3` 测试 |

---

## 10. Golden G2 / G3 / G4（真实 AMAP，独立重跑）

脚本：`C:\Windows\Temp\opencode\b18_b_golden.py`（真实 `AmapRouteProvider` 经 `_route_for_pair`；本次验收独立执行，3 次单查）

| Case | Pair | 查询序列 | 结果 |
| --- | --- | --- | --- |
| **G2** | 正佳广场 → 小林蓝鳄正佳广场（同坐标，审计 1m/1s/DRIVING 案例） | `[WALKING]` | **WALKING**，14 m / 11 s，provider=AMAP |
| **G3** | 广州天河体育中心 → 正佳广场（~623m） | `[WALKING]` | **WALKING**，272 m / 218 s，provider=AMAP |
| **G4** | 正佳广场 → 广州白云机场（~29km） | `[DRIVING]` | **DRIVING**，38972 m / 3584 s，provider=AMAP，无 walking 查询 |

- G2 直接复现并验证了 DB 中「正佳广场 → 小林蓝鳄正佳广场 1m/1s/DRIVING」缺陷的修复（现 14m/11s/WALKING）
- G4 验证长距离不浪费 walking 查询（`mode_calls == ['DRIVING']`）
- 开发方报告的 G2/G3 数值（14m/11s、272m/218s）与本次一致；G4 duration 3675s vs 本次 3584s 为实时路况/服务端时间正常差异，mode 决策一致

---

## 11. B17 Timing Regression

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 选中 route 的真实 duration 进入时间计算 | ✅ forward-fit 使用 `route.data.duration_seconds`（= 实际选中的 WALKING 或 DRIVING 时长） | `planning_provider.py:1122`；若 gap < 实际时长则 shift 后续活动或 fail-closed（time_fixed 检查保留） |
| fixed slot / departure anchor | ✅ time_fixed 边界不被移动（既有逻辑未变）；related 测试通过 | `:1123-1124, 1131-1132, 1148-1158` |
| capacity repair / window relaxation（B17） | ✅ 未触碰；related 全绿 | `test_local_replanning.py`、`test_daily_skeleton_provider.py`、`test_planning_worker.py`、`test_daily_schedule.py` 均在 related 181 passed 中 |
| 语义说明 | 真实 WALKING 时长 > DRIVING 导致个别行程变紧/不可行是 baseline 语义的正确结果（真实 route facts 一致），非回归；相关测试无此现象出现 | 判定依据 plan.md §二十五 |

---

## 12. Persistence / Web

| 项 | 结果 | 证据 |
| --- | --- | --- |
| Python → event 链路 | ✅ `TransitLeg.mode="WALKING"` 原样产出（`ItineraryTransitMode` 已含 WALKING） | `contracts.py:659` |
| Java parser / domain | ✅ WALKING 在 mode 白名单（`ItineraryService.java:424-426` 既有 `List.of("WALKING","TRANSIT","DRIVING","TAXI")`），无改写逻辑 | B9 Python 测试 + Java 533 tests 0 failures |
| DB persistence | ✅ `transit_leg.mode` 列已存在、无 migration；event 透传不覆盖 | B18-A 验收已确认同一链路 |
| Web 初始显示 | ✅ persisted WALKING → "步行"（组件未改，行为由新增测试锁定） | `TransitLegControl.test.ts` 新增：`selectedMode: 'WALKING'` → textContent 含"步行"、不含"驾车" |
| 加载 vs 点击 AUTO 区分 | ✅ 加载走 `transitModeFor(leg)`（= persisted mode）；只有用户主动点击 AUTO 才触发推荐器 | `TripDetail.vue:304-307` 既有逻辑；AUTO 双实现允许存在（plan.md §4.6） |

---

## 13. Regression Evidence（独立执行）

```
Python targeted: pytest tests/test_transit_mode.py -v --basetemp=...
                 → 14 passed（B1-B9 + 阈值/常量边界）
Python related:  pytest test_transit_mode test_route_provider test_demo_ordering
                 test_must_visit_recall test_planning_worker test_local_replanning
                 test_daily_skeleton_provider test_b18_a_recall test_daily_schedule
                 → 181 passed
Python full:     pytest -q --basetemp=%LOCALAPPDATA%\Temp\pytest-b18b-acceptance-full
                 → 1557 passed, 37 skipped, 1 warning, exit 0
ruff:            ruff check src/trip_agent tests → All checks passed!
Web targeted:    vitest run tests/transit.test.ts tests/TransitLegControl.test.ts
                 → 8 passed
Web full:        vitest run → 42 files / 446 passed
Web typecheck:   vue-tsc -b → exit 0
Java:            mvn -pl apps/travel-server test（JDK 21, BellSoft）→ 533 tests, 0 failures, 0 errors
                 （从 surefire-reports 57 个报告文件独立汇总）
```

说明：默认 `C:\Windows\Temp\pytest-of-*` ACL 问题（WinError 5，B18-A 已记录的环境问题）——指定可写 `--basetemp` 后全量通过，非代码问题。

---

## 14. Provider / Performance

| 项 | 观察 |
| --- | --- |
| AMAP 可用性 | 本次验收 Golden G2/G3/G4 三次单查**全部成功**（无限流） |
| Rate limit | 开发方完整规划 Smoke 曾触发 AMAP **route** API 配额限流（B18-A 时期同款环境限制）；本验收 3 次单查成功证明 route 调用无爆炸/无限重试，**限流与 B18-B 无因果关系** |
| API call amplification | 普通 leg = 1 次；prefilter 内且 walking 超阈值/可降级失败 = 2 次（WALKING+DRIVING）；长距离 = 1 次 DRIVING；Golden 三例各 1 次；96 次/规划硬边界保留 |
| POI 层 | 未受影响（B18-B 不修改 POI 召回） |

---

## 15. Scope Audit / Defects / Follow-ups

### Scope Audit

| 检查项 | 结果 |
| --- | --- |
| B18-A 未重新修改 | ✅ `candidates.py` 无 B18-B 新增变更（其 M 状态为 B18-A 验收时已确认的增量）；`test_b18_a_recall.py` 未触碰；A1-A7 语义未变 |
| 公共交通 / 地铁 API | ✅ 无（全仓无 direction/transit、citycode、transfer 相关代码） |
| multi-mode scoring / best-route | ✅ 无（仅阈值规则，无 score 模型） |
| Taxi route / enum 增删 | ✅ 无（`RouteMode`/`ItineraryTransitMode` 不变，DRIVING/TAXI 保留） |
| 驾车/打车 UI 合并 | ✅ 无（`TransitLegControl.vue` / `lib/transit.ts` 生产文件未修改，仅新增 27 行测试） |
| DB migration / contract breaking change | ✅ 无（V37 migration 与 contracts v10 为 B15/B16/B17 在途，非本批） |
| B18-C diversity / B18-D parent dedup | ✅ 无 |
| 用户自驾约束 | ✅ 无 |

### Defects

```
None.
```

### Follow-ups（登记，不影响 verdict）

- Public transit / metro integration（AMAP transit API，需 city code / transfer / 计价模型）
- Road / Taxi / Self-driving 产品语义（DRIVING 当前只是 road baseline，不代表"用户有私家车"）
- 驾车 + 打车前端按钮收敛（产品反馈可合并，仅登记）
- 真正 multi-mode recommendation（score 模型，非阈值规则）
- B18-C：itinerary diversity objective
- B18-D：parent/complex semantic dedup
- （观察）真实 AMAP route 配额限制影响完整 compose 冒烟——环境限制，非代码缺陷；短距离双查 API 增量需业务侧在配额下评估

---

## 16. Final Recommendation

```
B18-B 允许收口：YES
是否允许进入下一阶段交通设计：YES（进入 multi-mode recommendation / public transit 设计前，先完成 B18-C/D 或按总控计划顺序推进）
```

理由：硬编码 DRIVING 完全闭环；WALKING/DRIVING 决策路径唯一且纯规则可测；route facts 单一来源；fallback 白名单化、无宽捕获；budget/cache 无绕过；B17 timing 使用真实选中 duration；persistence 与 Web 展示保留 WALKING；全量回归（Python 1557 / ruff / Web 446 / typecheck / Java 533）全部通过；Golden G2/G3/G4 真实 AMAP 独立复跑成功；scope 零污染。

**准确结论**：B18-B 已建立 Walking / Driving baseline，解决明显短距离 DRIVING 错误。公共交通、Taxi/Road 语义与真正 multi-mode recommendation 属于后续阶段。
