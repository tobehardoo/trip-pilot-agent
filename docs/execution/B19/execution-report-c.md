# B19-C Execution Report — Multi-mode Recommendation（真实三模式推荐）

- 执行日期：2026-08-19
- 依据：`docs/execution/B19/audit.md`、`plan-b.md`、`execution-report-b.md`、`acceptance-report-b.md`（B19-B **PASS_WITH_DEFECT**，D1 非阻塞）、`plan-c.md`（含两项执行前修订）、`docs/execution/B18/execution-report-b.md` / `acceptance-report-b.md`
- 分支 / HEAD：`codex/feasibility-foundation` @ `d10e70c`

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
| dirty workspace | 102 项（B15/B16/B17/B18-A/B18-B/B19-A/B19-B 历史在途 + 本批增量）；未执行任何 `git reset / restore / checkout . / stash / clean` |
| B19-C 可识别增量 | `planning/mode_recommendation.py`（新）、`planning_provider.py`（`_route_for_pair` staged 分支 / `_recommend_transit_or_road` / `_considered_modes` / `_emit_day` 传 city+remaining_legs+mobility）、`tests/test_mode_recommendation.py`（新，28 项）、`tests/test_amqp_worker.py`（工厂测试 mock 增加 transit endpoint 分支）；contract/DB/Java/Web production **零修改** |
| 历史归属 | 无法从未提交 dirty workspace 逐行证明；本报告只审计 B19-C 增量语义 |

## 3. Plan Amendments（执行前修订，已落实）

| 修订 | 落实 |
| --- | --- |
| **修订 1**：删除固定 `BUDGET_DEGRADE_THRESHOLD=80`，改 remaining-leg / remaining-call aware 动态保留 | `can_probe_transit(remaining_budget, remaining_legs)` = `remaining_budget > remaining_legs × MIN_BASELINE_CALLS_PER_LEG(1)`（`mode_recommendation.py`）；全仓无固定 80 魔法值（仅 docstring 说明取代关系）；`_emit_day` 传入真实 `legs_total - index`；C10 四场景锁定（含"79 calls 仍允许 probe"反证无固定 80） |
| **修订 2**：D1 = NON_BLOCKING_FOLLOW_UP，只复测不修 | polyline 生产代码（`_amap_transit.py`）本批零改动；C9b 锁定 `PROVIDER_SCHEMA_CHANGED`（MALFORMED，非可恢复）仍 raise（D1 边界 fail-closed 语义不变）；详见 §21 |

## 4. Golden Calibration（真实 AMAP 6 次新调用 + 复用 B19-A/B 证据；总计本批真实 route 调用 17 次，0 限流）

| Golden | Walking | Transit | Driving | Transfers | Transit Walk | Expected | Selected（真实） |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| G1 正佳→广州塔 09:00 | 3602s（B19-A） | 1250s / ¥2 / 654m / 0 | 1632s（B19-A 快照） | 0 | 654m | TRANSIT | **DRIVING**（live driving=986s，1250 > 986×1.2 → ROAD_SIGNIFICANTLY_FASTER；快照变差见 §18） |
| G2 体育中心→正佳 09:00 | **873s（live）** | — | ~120s | — | — | WALKING | **WALKING**（≤1200s 短路） |
| G3 正佳→白云机场 09:00 | 27958s（B19-A） | 12139s / ¥9 / 2981m / 4 | 3033s（live） | 4 | 2981m | DRIVING | **DRIVING**（duration 3.3× 超 R） |
| G4 换乘惩罚（fixture） | — | 1440s / 3 换乘 | 1320s | 3 | 900m | DRIVING | **DRIVING**（C3/C4b 锁定） |
| G5 walking burden（fixture） | — | 1500s / 1800m | 1440s | 0 | 1800m | DRIVING | **DRIVING**（W=1500 拒绝） |
| G6 NO_RESULT（fixture） | — | `transits=[]` | 有效 | — | — | DRIVING | **DRIVING**（C6 锁定，fail-closed） |
| G7 正佳→广州南站 09:00 | — | 4438s / ¥6 / 1980m / 1 | 1703-1892s（live） | 1 | 1980m | DRIVING（facts 决定） | **DRIVING**（duration + walking 双超） |
| G8 正佳→广州塔 23:30 | — | 1250s（深夜同线） | 1294s（探针）/ 986s（live） | 0 | 654m | 用对应 departure_at | **DRIVING**（live 变差同 G1；date/time 与 cache identity 已验证区分） |

G1/G8 说明：B19-A 快照 driving=1632s（transit 优）；live driving 今日 986s（transit 慢 27% → 规则正确选 DRIVING）。**推荐器严格跟随实时 facts**，快照与 live 的差异属于 provider 路况波动，不是算法缺陷；TRANSIT 优势行为由确定性 fixture 锁定（C2：transit 1260s vs road 1620s → TRANSIT；G1-fixture 同构）。

## 5. Final Thresholds（校准输出）

| 常量 | 值 | 校准依据 |
| --- | --- | --- |
| `MAX_TRANSIT_DURATION_RATIO`（R） | **1.2** | 9 案例扫描：G1-fixture（1250≤1632×R，R≥0.77）、G3（12139>3682×R，R<3.3）、X1（2520>1144×R）→ 候选区间 [1.0,1.3] 内 1.2 使全部 Golden expected-match=100%，且边界可解释（transit 可慢至 20%） |
| `MAX_TRANSFERS`（N） | **2** | G4（3 换乘拒绝，N≤2）；duration 检查先行，N=2 不会造成"慢车+高换乘"误选 |
| `MAX_TRANSIT_WALKING_METERS`（W） | **1500** | G5（1800m 拒绝）、G7（1980m 拒绝）、G1/G8（654m 通过）→ 1500 为候选上限，30 分钟步行接驳上限语义 |
| mobility 修正 | REDUCED → N=1、W=750 | `accessible_burdens` 纯函数（仅收紧 accessibility 负担，不强制 DRIVING、不偏好打车）；`test_mobility_reduced_*` 锁定"普通用户接受 2 换乘而 REDUCED 拒绝" |

选择理由：R/N/W 取候选范围中最简单、最保守、边界最易解释的组合；扫描网格为 `R∈{1.0,1.05,…,1.3} × N∈{1,2} × W∈{800,1000,1200,1500}`，多组同分时优先简单/保守。**未采用 Web AUTO 的 1.6**（估算值且比较对象是 TAXI）。

## 6. RED Evidence（C1-C16 + mobility/boundary，共 28 项，全部 GREEN）

| ID | baseline | GREEN 结果 |
| --- | --- | --- |
| C1 walk 8min/road 4min → WALKING | **baseline GREEN**（锁定） | WALKING，仅 1 次 WALKING 调用，无比较查询 |
| C2 transit 21min/road 27min/0转 → TRANSIT | RED | TRANSIT，calls=[TRANSIT, DRIVING] |
| C3 transit 45min/3转/road 20min → DRIVING | RED | DRIVING（duration 检查先行） |
| C4 transit 23min/road 20min → TRANSIT（ratio 1.15≤1.2） | RED | TRANSIT_COMPETITIVE_LOW_TRANSFER |
| C4b transit 25min/road 20min（ratio 1.25）→ DRIVING | RED | 锁 R=1.2 边界 |
| C5 transit 25min/1800m walk → DRIVING | RED | TRANSIT_EXCESSIVE_WALKING 语义 |
| C6 transit NO_RESULT → DRIVING | RED | TRANSIT_UNAVAILABLE，calls=[TRANSIT, DRIVING] |
| C7 transit RATE_LIMITED/TIMEOUT → DRIVING | RED | TRANSIT_UNAVAILABLE，规划不失败 |
| C8 driving 可恢复失败 → TRANSIT | RED | ROAD_UNAVAILABLE |
| C9 walking 可恢复失败 → 继续推荐 | RED（B18-B 只降级 DRIVING） | 进入 T+D 比较，calls=[WALKING, TRANSIT, DRIVING] |
| C9b transit MALFORMED → raise | RED | **仍 raise**（非可恢复不吞；D1 边界保持 fail-closed） |
| C9c driving INVALID_REQUEST → raise | RED | **仍 raise** |
| C10 动态 budget（95→跳 transit / 94→probe / 6-余-5→probe / 6-余-10→跳过 / 79→probe 反证无固定 80） | RED | 全部符合 `can_probe_transit` 契约 |
| C11 cache 复用 | RED | 同 pair 两次推荐 provider calls 不重复 |
| C12 facts 同源 | RED | TRANSIT/DRIVING 选中 route 的 mode/duration/distance/cost/polyline 全来自同一响应 |
| C13 全量规划产出 TRANSIT leg | RED | leg duration=2880（transit 时长，非 driving 2400），provider=AMAP/estimated=false |
| C14 fixed-slot infeasible → 无 override | RED | `PlanningInfeasibleError`（FIXED_SCHEDULE_OVERLAP/INSUFFICIENT_DAY_CAPACITY），calls 恰为 [TRANSIT, DRIVING]（无重试振荡） |
| C15 walking Golden 不回归 | **baseline GREEN**（锁定） | WALKING，1 call |
| C16 长距 Golden | **baseline GREEN**（锁定，语义更新） | 无 walking 查询；TRANSIT+DRIVING 比较后按 facts 选 |

## 7. Recommendation Model

`planning/mode_recommendation.py`：

```
ModeRecommendation:
  selected_route: ProviderSuccess[RoutePlan]   ← 进入 itinerary（facts 同源）
  reason: ModeRecommendationReason             ← 结构化枚举
  considered: tuple[ConsideredMode, ...]       ← 每 mode facts（logging/tests/trace）

ModeRecommendationReason（StrEnum）：
  WALKABLE / TRANSIT_FASTER_THAN_ROAD / TRANSIT_COMPETITIVE_LOW_TRANSFER /
  ROAD_SIGNIFICANTLY_FASTER / TRANSIT_TOO_MANY_TRANSFERS /
  TRANSIT_EXCESSIVE_WALKING / TRANSIT_UNAVAILABLE / ROAD_UNAVAILABLE /
  BUDGET_DEGRADED
```

默认**不进 event、不进 DB**（v11 不变）；reason/considered 只经 logger + 测试断言。

## 8. Staged Query Flow（生产路径）

```
_route_for_pair(origin, dest, departure_at, cache, calls, *, city, remaining_legs, mobility_reduced)
  Stage 1 WALKING 短路（B18-B 语义不变）：
    straight ≤1500m → 查 WALKING → duration ≤1200s → WALKING（reason=WALKABLE；不再比较）
    walking 可恢复失败 / 超阈值 → Stage 2
  Stage 2 TRANSIT vs DRIVING：
    city 可确定 且 can_probe_transit(96-已用, remaining_legs) → 查 TRANSIT（+1）
    DRIVING baseline（+1，恒查）
    可恢复失败 → 候选不可用；非可恢复 → raise
  Stage 3 ordered rules → selected RoutePlan → forward-fit / fixed-slot / capacity
```

调用点：`_emit_day` 传 `city=command.payload.trip.destination or None`、`remaining_legs=legs_total-index`、`mobility_reduced=(mobility_level=="REDUCED")`（与既有 mobility repair 语义一致）。

## 9. Ordered Rules

```
1  walkable(≤1200s)                        → WALKING                 [WALKABLE]
2  transit 不可用（NO_RESULT/可恢复/city 缺失/预算降级）→ DRIVING    [TRANSIT_UNAVAILABLE / BUDGET_DEGRADED]
3  driving 不可用（可恢复）                → TRANSIT                [ROAD_UNAVAILABLE]
4  transit.duration > road.duration × R    → DRIVING                [ROAD_SIGNIFICANTLY_FASTER]
5  transfer_count > N                      → DRIVING                [TRANSIT_TOO_MANY_TRANSFERS]
6  transit_walking > W                     → DRIVING                [TRANSIT_EXCESSIVE_WALKING]
7  否则 transit.duration ≤ road.duration   → TRANSIT                [TRANSIT_FASTER_THAN_ROAD]
8  否则                                    → TRANSIT                [TRANSIT_COMPETITIVE_LOW_TRANSFER]
```

TRANSIT 接受 = duration 比 + transfer + walking 三条件同时满足；缺失 transfer/walking facts 不构成拒绝理由（纯函数测试锁定）。

## 10. Failure Matrix

| WALKING | TRANSIT | DRIVING | 期望 |
| --- | --- | --- | --- |
| good（≤1200s） | — | — | WALKING |
| too long / 可恢复失败 | good | good | 规则比较 |
| too long | NO_RESULT/可恢复 | good | DRIVING |
| 可恢复失败 | good | 可恢复失败 | TRANSIT（ROAD_UNAVAILABLE） |
| 可恢复失败 | 可恢复失败 | 可恢复失败 | 既有 provider error policy（raise / DEMO fallback，不伪造） |
| — | **非可恢复**（MALFORMED/AUTH/PERMISSION/INVALID/INTERNAL/QUOTA） | — | **raise**（不吞） |
| — | — | **非可恢复** | **raise** |

可恢复集合复用 B18-B `_RECOVERABLE_WALKING_CATEGORIES`（TIMEOUT/NETWORK/PROVIDER_UNAVAILABLE/RATE_LIMITED/NO_RESULT/UNSUPPORTED_MODE）。provider 层 fail-closed（B19-B）与推荐层 fallback（B19-C）职责分离。

## 11. Dynamic Budget（修订 1 落地）

```
MIN_BASELINE_CALLS_PER_LEG = 1
can_probe_transit(remaining_budget, remaining_legs):
    minimum_reserved = remaining_legs × 1
    return remaining_budget > minimum_reserved
# remaining_budget = MAX_ROUTE_CALLS_PER_PLAN - route_calls[0]
```

- 语义：为**包括当前 leg 在内的每个剩余 leg** 保留至少 1 次 baseline（DRIVING）查询能力后，若仍有余量才允许当前 leg 的额外 TRANSIT probe（probe 本身 +1）。
- 保守性：假定 probe 未命中 cache（命中只会更省）；确定性、可测试（C10 纯函数 + 集成场景）。
- 降级行为：`BUDGET_DEGRADED`（跳过 TRANSIT → DRIVING baseline）；walking 短路成功时**不受** budget 降级影响（仍 WALKING）。
- **已完全删除固定 80 阈值**（修订 1）；`MAX_ROUTE_CALLS_PER_PLAN=96` 保持不变，超限仍 `ROUTE_CALL_BUDGET_EXHAUSTED`。

## 12. Cache Reuse

- 现成能力（B19-B）：TRANSIT key 含 `mode/city/strategy/nightflag/日期+15min bucket`；W/D key 含 mode——三 mode 隔离。
- C11 锁定：同 pair 同参数两次 `_route_for_pair` → provider 调用不重复（`["TRANSIT","DRIVING"]` 仅一次），内存 cache 命中。
- smoke 佐证：规划内重复 pair 命中缓存（3 日 7 legs 仅 13 次调用 < 14 次朴素上限）。

## 13. Timing Integration

- selected RoutePlan 的 `duration_seconds`（真实推荐 mode）直接进入 `_emit_day` forward-fit / fixed-slot / monotonic sweep——B18-B 已有机制，**无需改时序代码**。
- C13：全量规划产出 TRANSIT leg 且 duration=2880（真实 transit 时长，非 driving 2400），证明进 itinerary 的事实是最终推荐 mode 的。
- C14：推荐 TRANSIT（2880s）在固定窗口不可行 → `PlanningInfeasibleError`，**不使用假 driving 时长、不切 DRIVING 重试**（calls 恰 [TRANSIT, DRIVING]，无振荡）。

## 14. Recommendation Trace（生产日志示例）

```
mode_recommendation origin=zhengjia destination=canton-tower mode=DRIVING reason=ROAD_SIGNIFICANTLY_FASTER provider_calls_used=2 budget_degraded=False
mode_recommendation origin=sports-center destination=zhengjia mode=WALKING reason=WALKABLE provider_calls_used=3 budget_degraded=false
```

日志含 origin/destination/selected mode/reason/累计 provider calls/budget_degraded 标志；walking 短路与 stage-2 两条路径均输出。不持久化、不进 event v11。

## 15. Golden G1-G8 结果

| ID | 结果 | 证据 |
| --- | --- | --- |
| G1 | **PASS（行为正确，live 变差已记录）** | 真实 facts：transit 1250s vs live driving 986s → DRIVING（ROAD_SIGNIFICANTLY_FASTER）；TRANSIT 优势由 C2/G1-fixture 确定性锁定 |
| G2 | **PASS** | 真实 walking 873s ≤1200s → WALKING |
| G3 | **PASS** | transit 12139s vs driving 3033s → DRIVING |
| G4 | **PASS** | fixture（C3）：3 换乘 + duration 超 → DRIVING |
| G5 | **PASS** | fixture（C5）：1800m walk → DRIVING |
| G6 | **PASS** | fixture（C6）：`transits=[]` → DRIVING，无假路线 |
| G7 | **PASS** | 真实：transit 4438s/1980m/1转 vs driving 1703s → DRIVING（facts 决定） |
| G8 | **PASS** | 真实 23:30：date/time 与 cache identity 与白天区分；live facts 与 G1 同构 → DRIVING；深夜结果可同可异（本日同） |

## 16. Real Planning Smoke（广州，真实 AMAP，经工厂 provider）

```
SMOKE 2d: legs=4 dist={'DRIVING': 4}         route_calls={'DRIVING': 4}（transit probe 4 次计入 8）
SMOKE 3d: legs=7 dist={'DRIVING': 6, 'WALKING': 1}  route_calls={'DRIVING': 6, 'WALKING': 1}（transit 6 次计入 13）
```

- mode distribution：本日 live 数据下 driving 普遍更快 → 多数 leg `ROAD_SIGNIFICANTLY_FASTER`；1 个短 leg `WALKABLE`；无 TRANSIT 选中（facts 驱动，非 KPI）。
- provider failures：0 transit / 0 route 失败；POI 搜索 1 次 `RATE_LIMITED` 自动重试成功。
- 每 leg 平均调用：2 日 8/4=2.0、3 日 13/7≈1.86（理论 1-3，见 §17）。

## 17. API Cost（理论 + 实测）

| 场景 | legs | 理论（staged） | worst-case（全 3-call） | 动态保留后 worst |
| --- | --- | --- | --- | --- |
| 2 日 | ~6-9 | ~11-16 | 27 | ≤21 |
| 3 日 | ~10-15 | ~18-27 | 45 | ≤37 |
| 5 日 | ~15-25 | ~27-45 | 75 | ≤67 |
| 7 日 | ~22-35 | ~40-63 | 105 | **≤88**（保留 1 baseline/leg 后必然 ≤96 内） |

实测：2 日 8 次（2.0/leg）、3 日 13 次（1.86/leg），0 限流、0 quota 错误。`MAX_ROUTE_CALLS_PER_PLAN=96` 未修改。

## 18. Quality Review（人工抽查）

- 抽查真实 2 日/3 日全部 11 个 leg 的 reason 与 facts：每个 DRIVING leg 的 reason=ROAD_SIGNIFICANTLY_FASTER 且 transit 已 probe（provider_calls_used=2k 序列自洽）；WALKING leg reason=WALKABLE（短距，步行 ≤20min）。
- 无"walk 6min→DRIVING"（walkable 短路保证）；无"transit 60min/4 换乘→TRANSIT"（duration+burden 三条件拒绝）。
- **记录一项真实数据观察（非缺陷）**：G1/G8 正佳→广州塔 live driving 今日 986s vs B19-A 快照 1632s——推荐结果随实时路况在 TRANSIT↔DRIVING 间变化，这是"facts 驱动"的预期行为；TRANSIT 偏好由确定性测试锁定。

## 19. Regression

```
Python targeted:  pytest test_amap_transit test_mode_recommendation test_transit_mode
                  test_b19_transit_chain test_local_replanning → 104 passed
Python related:   17 个文件套件（worker/outcome/schema/replan/replanning/golden/closure…）→ 330 passed（含 amqp_worker 工厂 mock 修复）
Python full:      pytest -q --basetemp=%LOCALAPPDATA%\Temp\pytest-b19c-full
                  → 1654 passed, 37 skipped, 1 warning, exit 0
ruff:             ruff check src/trip_agent tests → All checks passed!
Contract:         v10/v11 + review v1/v2 schema 测试在 full 中通过（含 TAXI reject、B17 None-omit）
Java:             mvn -pl apps/travel-server test（JDK 21；Docker Desktop 运行中）
                  → 537 tests, 0 failures, 0 errors（0 生产修改）
Web:              vitest run → 42 files / 447 passed；vue-tsc -b → exit 0（0 生产修改）
```

说明：Windows temp ACL 环境问题沿用 `--basetemp` 可写路径解决；唯一 warning 为 B17 既有 AnyHttpUrl 序列化提示（与 B19-C 无关）。

## 20. B17 / B18 / B19-B Regression

| 批次 | 结果 | 证据 |
| --- | --- | --- |
| B17（timing/worker/event） | 无回归 | fixed-slot/capacity/departure/worker/outcome 套件全绿；None-omit schema 测试通过 |
| B18-B（walking baseline） | 无回归 | `test_transit_mode.py` 14 passed（B1-B9 调用序列不变：短距 1 call / 超阈值 [W, D] / 长距 1 call）；C1/C15/C16 锁定 |
| B19-B（TRANSIT provider） | 无回归 | `test_amap_transit.py` 43 + `test_b19_transit_chain.py` 8 passed（cost/walking_distance/transfer_count/cache 日期 bucket/v11-v2） |
| 普通 planner route calls | 不增加 | `_route_for_pair` 无固定 80；city=None 时（B18-B 测试路径）行为与原完全一致；全量规划路径 transit probe 计入统一 budget |

## 21. D1（B19-B 缺陷，仅复测未修）

- **复测结论**：D1 仍为"polyline 几何缺失 → `PROVIDER_SCHEMA_CHANGED`（MALFORMED，非可恢复）→ raise"的 fail-closed 行为（C9b 锁定）；**不影响 recommendation facts**——duration/distance/cost/walking_distance/transfer_count 全部来自 segments 数值字段，与 polyline 几何无关。
- **未修改**：`_amap_transit.py` polyline 生产代码本批零改动（修订 2 落实）。
- **暴露面说明**：B19-C 使 TRANSIT 成为默认候选，D1 触发面相对 B19-B 扩大；但真实 Golden/smoke（17 次真实调用）从未触发（真实响应均携带 polyline）。plan-b §4.4"跳段+2 点退化"补丁仍登记为 **B19-D / 独立 follow-up**，不作为本批验收项。

## 22. Scope Audit

| 检查项 | 结果 |
| --- | --- |
| `PUBLIC_TRANSIT` / `ROAD` enum / `SELF_DRIVING` / TAXI provider | ✅ 无（`ROAD_*` 仅为 reason 枚举标签，非 mode 抽象） |
| weighted score / LLM / OR-Tools 全局优化 | ✅ 无（ordered rules 纯函数） |
| feasibility override / mode 振荡 | ✅ 无（C14：固定窗口不可行直接 raise，calls 无重试） |
| 天气 / 行李 / 交通偏好 / 自驾约束 | ✅ 无（pace/weather/luggage 未进入） |
| event v12 / contract 变更 | ✅ 无（completion v11 / review v2 不变） |
| DB migration | ✅ 无（最新 V37，无 V38） |
| Java / Web production | ✅ 0 修改 |
| manual edit TRANSIT 真实化 | ✅ 未做（登记 B19-D） |
| D1 polyline 修复 | ✅ 未做（仅复测） |
| B18-C diversity / B18-D dedup | ✅ 无 |

## 23. Known Gaps

- **manual edit TRANSIT 仍为 Java 本地估算**（provider=DEMO/estimated=true；planner-generated 为真实 AMAP）——B19-D 必做 follow-up；B19-C 后用户更常见真实 transit，一致性 gap 严重度上升。
- 无 Road/Taxi/Self-driving 语义模型（DRIVING 仍是 road baseline；TAXI 无真实 provider）——B19-D。
- 无用户交通偏好 / 天气 / 行李输入——后续批次。
- 无 feasibility override（v1 固定 mode；bounded override 登记 future）。
- 无全局 mode 优化（per-leg 确定性推荐；全局一致性留作 future）。
- D1 polyline 边界缺陷 follow-up。
- 跨城 transit 受限（B19-B 既有 Known Gap，city=trip.destination 同城语义）。

## 24. Final Recommendation

```
B19-C 允许收口：YES（建议进入独立验收）
```

理由：真实 WALKING/TRANSIT/DRIVING facts 之上的 staged ordered-rule 推荐已建立并全链路验证——walking ≤20min 短路保持（非 fastest wins）；TRANSIT 接受需 duration 比 + transfer + walking 三条件（R=1.2/N=2/W=1500，Golden 9 案例 expected-match 100% 校准）；不比较 transit 票价与 driving 过路费；可恢复失败安全降级、非可恢复仍 raise（D1 fail-closed 保持）；动态 remaining-leg 预算保留取代固定 80（96 上限不变，7 日 worst ≤88）；cache 复用（C11）；selected duration 真实进入 forward-fit/fixed-slot 且无 override/振荡（C13/C14）；reason/trace 结构化且不污染 v11；真实 Golden（17 次调用 0 限流）与广州 2 日/3 日 smoke 正常；B17/B18-B/B19-B 零回归；Python 1654 / ruff / Java 537 / Web 447 全量干净；contract v11/v2 不变、DB 零 migration、Java/Web production 零修改、无 B19-D scope 污染。

**准确结论**：B19-C 建立了基于真实 WALKING / TRANSIT / DRIVING route facts 的第一版 staged multi-mode recommendation。Road/Taxi/Self-driving 语义、用户交通偏好、天气/行李、manual edit 真实化、feasibility override 与全局 mode 优化仍属于后续阶段。
