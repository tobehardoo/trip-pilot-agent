# B19-C Acceptance Report — Multi-mode Recommendation（独立验收）

- 验收日期：2026-08-20
- 验收角色：独立验收 Agent（只读，未修改任何生产代码，未修复任何发现的问题）
- 依据：`docs/execution/B19/audit.md`、`plan-b.md`、`plan-c.md`（含两项执行前修订）、`execution-report-b.md`、`acceptance-report-b.md`（B19-B PASS_WITH_DEFECT，D1 非阻塞）、`execution-report-c.md`（开发方声明，仅参考）；`docs/execution/B18/plan.md` / `execution-report-b.md` / `acceptance-report-b.md`（B18-A/B 已 PASS，本轮未重新打开）
- 方法：代码精读 + 独立测试复跑 + 独立真实 AMAP Golden 调用（3 案例 / 5 次调用）；所有结论由代码、测试与真实 provider 证据独立形成

---

## 1. Verdict

```
PASS
```

B19-C 核心能力已达成：基于真实 WALKING / TRANSIT / DRIVING route facts 的第一版 staged multi-mode recommendation 建立并验证通过——walking 短路优先（非 fastest wins）、TRANSIT vs DRIVING ordered rules（duration 比 + transfer + walking 三条件）、动态 remaining-leg 预算保留（无固定 80）、可恢复失败安全降级 / 非可恢复 raise、selected duration 真实进入 timing 且无 feasibility override、reason 结构化 trace 不污染 v11。**未发现 B19-C 范围内缺陷**；3 项观察（O1-O3，均非缺陷，见 §18）。

**准确表述**：B19-C 建立了基于真实 WALKING / TRANSIT / DRIVING route facts 的第一版 staged multi-mode recommendation。**不是**"最终智能交通推荐系统"——Road/Taxi/Self-driving 语义、用户交通偏好、天气/行李、manual edit 真实化、feasibility override 与全局 mode 优化仍属后续阶段（B19-D 或独立批次）。

---

## 2. Scope Reviewed

| 项 | 验证方式 |
| --- | --- |
| `mode_recommendation.py`（新） | 全文精读：ordered rules、reason 枚举、动态预算纯函数、mobility 修正、常量 |
| `planning_provider.py` 增量 | `_route_for_pair` staged 分支 / `_recommend_transit_or_road` / `_considered_modes` / `_emit_day` 调用点精读 |
| 测试 `test_mode_recommendation.py`（新） | 全文精读 + 28 项独立复跑（C1-C16 + mobility/boundary） |
| `test_amqp_worker.py` 增量 | 工厂测试 mock 补 transit endpoint 分支（独立复跑 28 passed） |
| 修订 1（动态预算） | 代码精读 + C10 四场景复跑 + 全仓 grep 无固定 80 |
| 修订 2（D1 不修） | `_amap_transit.py` mtime 核验（B19-B 时代，未动）+ C9b 复跑（PROVIDER_SCHEMA_CHANGED 仍 raise） |
| 真实 AMAP Golden | **独立调用 3 案例 5 次**（G1/G2/G3），0 限流 |
| 回归 | targeted 93 / related 330 / 全量 1654 + ruff / Java parser 89 / Web transit 9（独立复跑） |

---

## 3. Workspace Baseline

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `d10e70cf354d096300c4a348d6aef585b8d82dc8` |
| dirty workspace | 104 项（B15-B19 历史在途 + B19-C 增量）；未执行任何 `git reset / restore / checkout . / stash / clean` |
| B19-C 可识别增量 | Python：`planning/mode_recommendation.py`（新）、`planning_provider.py`（`_route_for_pair`/`_recommend_transit_or_road`/`_considered_modes`/`_emit_day`）、`tests/test_mode_recommendation.py`（新）、`tests/test_amqp_worker.py`（工厂测试 mock 分支）；**contract/DB/Java/Web production 零修改**（mtime 核验：2026-08-19 23:30 之后无任何 Java/Web/contract 生产文件改动） |
| 历史归属 | 无法从未提交 dirty workspace 逐行证明；本报告只审计 B19-C 增量语义正确性 |

---

## 4. Plan Amendments Acceptance（执行前两项修订）

| 修订 | 验收结果 | 证据 |
| --- | --- | --- |
| **修订 1**：删除固定 `BUDGET_DEGRADE_THRESHOLD=80` → 动态 remaining-leg/call aware 保留 | ✅ 落实 | `can_probe_transit(remaining_budget, remaining_legs)` = `remaining_budget > remaining_legs × MIN_BASELINE_CALLS_PER_LEG(1)`（`mode_recommendation.py:83-95`）；全仓 `BUDGET_DEGRADE_THRESHOLD` 仅 docstring 说明取代关系（`:91`），**无任何代码引用**；`_emit_day` 传真实 `legs_total - index`；C10 四场景独立复跑（95→跳 transit / 94→probe / 6-余-5→probe / 6-余-10→跳过 / **79 calls 仍 probe** 反证无固定 80） |
| **修订 2**：D1 = NON_BLOCKING_FOLLOW_UP，只复测不修 | ✅ 落实 | `_amap_transit.py` mtime `Aug 19 20:29`（B19-B 时代，B19-C 零改动）；C9b 独立复跑：transit `PROVIDER_SCHEMA_CHANGED`（MALFORMED，非可恢复）仍 raise；见 §16 |

---

## 5. Recommendation Model Acceptance

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| `ModeRecommendation(selected_route, reason, considered)` | ✅ | `mode_recommendation.py:69-80`；selected_route 进入 itinerary（facts 同源），reason/considered 仅 logging/tests |
| reason 结构化枚举 9 值 | ✅ | `WALKABLE / TRANSIT_FASTER_THAN_ROAD / TRANSIT_COMPETITIVE_LOW_TRANSFER / ROAD_SIGNIFICANTLY_FASTER / TRANSIT_TOO_MANY_TRANSFERS / TRANSIT_EXCESSIVE_WALKING / TRANSIT_UNAVAILABLE / ROAD_UNAVAILABLE / BUDGET_DEGRADED`（`:46-55`）——与 plan-c 一致，无自由文本判断 |
| reason/considered 不持久化 | ✅ | 不进 TransitLeg/event/DB；仅 `logger.info` + 测试断言；生产日志已捕获真实输出（`mode_recommendation origin=... mode=... reason=... provider_calls_used=... budget_degraded=...`） |
| 同源性 | ✅ | `_route_for_pair` 返回单一 `ProviderSuccess[RoutePlan]`，`_leg_from_route` 逐字段取自同一对象（C12 双断言：TRANSIT/DRIVING 选中 route 的 mode/duration/distance/cost/polyline 全来自同一响应，无混用） |

---

## 6. Ordered Rules Acceptance

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| walking 短路优先（非 fastest wins） | ✅ | `should_try_walking` + `is_walkable(≤1200s)` 语义未动（B18-B）；C1：walk 8min/road 4min → WALKING 且仅 1 次 WALKING 调用、无比较查询 |
| TRANSIT 接受 = duration 比 + transfer + walking 三条件同时满足 | ✅ | `decide_transit_or_road`（`:117-144`）：duration 超 R → ROAD_SIGNIFICANTLY_FASTER；transfer 超 N → TRANSIT_TOO_MANY_TRANSFERS；walking 超 W → TRANSIT_EXCESSIVE_WALKING；否则 TRANSIT（更快/竞争两 reason） |
| 缺失 facts 不构成拒绝 | ✅ | `transfer_count=None` / `walking_distance_meters=None` 跳过对应检查（纯函数测试锁定） |
| 不比较 cost | ✅ | 规则只使用 duration/transfer/walking；`estimated_cost` 仅进 `ConsideredMode` trace；代码与注释均无跨 mode cost 比较 |
| 阈值来源 | ✅ | R=1.2 / N=2 / W=1500 由 9 案例 Golden 校准（expected-match 100%），非拍脑袋；未采用 Web AUTO 1.6（估算值且比较对象为 TAXI） |

---

## 7. Failure Matrix Acceptance

| 场景 | 期望 | 独立复跑结果 |
| --- | --- | --- |
| TRANSIT NO_RESULT → DRIVING | TRANSIT_UNAVAILABLE | ✅ C6 |
| TRANSIT 可恢复失败（RATE_LIMITED/TIMEOUT）→ DRIVING | TRANSIT_UNAVAILABLE，规划不失败 | ✅ C7（参数化 2 项） |
| DRIVING 可恢复失败 → TRANSIT | ROAD_UNAVAILABLE | ✅ C8 |
| WALKING 可恢复失败 → 继续 T+D 比较 | 规则比较照常 | ✅ C9（calls=[WALKING, TRANSIT, DRIVING]） |
| 双失败 → 既有 provider error policy | raise / DEMO fallback，不伪造 | ✅ 代码精读（`_recommend_transit_or_road:1831-1837`：raise road_error 或 transit_error） |
| **非可恢复失败（MALFORMED/INVALID_REQUEST 等）** | **raise，不吞** | ✅ C9b（PROVIDER_SCHEMA_CHANGED→raise）/ C9c（PROVIDER_REQUEST_INVALID→raise） |
| 可恢复集合 | 复用 B18-B `_RECOVERABLE_WALKING_CATEGORIES` | ✅ 同一 frozenset（TIMEOUT/NETWORK/PROVIDER_UNAVAILABLE/RATE_LIMITED/NO_RESULT/UNSUPPORTED_MODE） |

**职责分离确认**：provider 层 fail-closed（B19-B 语义不变）与推荐层 fallback（B19-C）严格分离；推荐不把非可恢复错误当作"不可用"信号吞掉。

---

## 8. Dynamic Budget Acceptance（修订 1 独立核验）

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 算法语义 | ✅ | `remaining_budget > remaining_legs × 1`：为每个剩余 leg（含当前）保留至少 1 次 baseline（DRIVING）后再允许额外 TRANSIT probe（probe 自身 +1） |
| 保守性 | ✅ | 假定 probe 未命中 cache（命中只会更省）；确定性、可测试 |
| 降级行为 | ✅ | BUDGET_DEGRADED → 跳过 TRANSIT → DRIVING baseline；walking 短路成功不受影响（仍 WALKING） |
| 固定 80 已删除 | ✅ | 全仓 grep 仅 docstring；C10 反证 79 calls 仍允许 probe |
| 96 上限未改 | ✅ | `MAX_ROUTE_CALLS_PER_PLAN=96` 保持；超限仍 `ROUTE_CALL_BUDGET_EXHAUSTED`（B19-B 测试在 suite 中通过） |
| worst-case | ✅ | 7 日 35 legs 全 3-call 场景动态保留后 ≤88，不击穿 96（C10 纯函数 + 集成场景覆盖边界） |

---

## 9. Cost Semantics Acceptance

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| TRANSIT cost 为真实票价 | ✅ | B19-B 已验收（AMAP `transit.cost` → RoutePlan → TransitLeg，空/缺失→None 不写 0） |
| DRIVING cost 为过路费语义 | ✅ | `_amap_route.py` `cost.toll_cost`（市区常 0/None）——与票价不同经济维度 |
| **规则不比较 cost** | ✅ | `decide_transit_or_road` 无 cost 参数；`ConsideredMode.cost` 仅供 trace；无"TRANSIT ¥2 vs DRIVING ¥0 → 更便宜"逻辑 |
| C12 cost 同源 | ✅ | TRANSIT 选中时 `estimated_cost` 来自 transit 响应（fixture 2.5 vs driving 8.0 → 取 2.5） |

---

## 10. Golden Calibration Acceptance

| Golden | facts 来源 | Expected | 校准结论 |
| --- | --- | --- | --- |
| G1 正佳→广州塔 | 真实（transit 1250s/¥2/654m/0 vs driving 1632s 快照） | TRANSIT | R≥0.77；确定性锁定 C2（transit 1260 vs road 1620 → TRANSIT） |
| G2 体育中心→正佳 | 真实（walking ≤1200s） | WALKING | 短路优先，无阈值参与 |
| G3 正佳→机场 | 真实（transit 12139s/4 转 vs driving 3033-3682s） | DRIVING | R<3.3（1.2 满足） |
| G4 换乘惩罚（fixture） | transit 1440s/3 转 vs road 1320s | DRIVING | N≤2 |
| G5 walking burden（fixture） | transit 1500s/1800m vs road 1440s | DRIVING | W<1800（1500 满足） |
| G6 NO_RESULT（fixture） | `transits=[]` | DRIVING | fail-closed |
| G7 广州南站 | 真实（transit 4438s/¥6/1980m/1 转 vs driving 1703-1892s） | DRIVING（facts） | duration+walking 双超 |
| G8 深夜 23:30 | 真实（transit 1250s 深夜同线） | 用对应 departure_at | date/time+cache identity 区分（B19-B 能力） |

**扫描方法独立核验**：R∈{1.0…1.3} × N∈{1,2} × W∈{800…1500} 网格，9 案例 expected-match=100%；多组同分时选最简单保守组合（R=1.2/N=2/W=1500）。校准发生在常量写入前（先 facts、后 expected、再扫描、后写常量），符合"先定 Golden 预期，再定阈值"门禁。

---

## 11. Timing Integration Acceptance

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| selected duration 进入 forward-fit | ✅ | `_emit_day` 的 forward-fit 使用 `_route_for_pair` 返回 route 的 `duration_seconds`（选中 mode 的真实值）；C13 独立复跑：全量规划产出 TRANSIT leg，duration=2880（transit 时长，非 driving 2400），provider=AMAP/estimated=false |
| fixed-slot / capacity 无假时长 | ✅ | C14 独立复跑：推荐 TRANSIT（2880s）在固定窗口不可行 → `PlanningInfeasibleError`（FIXED_SCHEDULE_OVERLAP/INSUFFICIENT_DAY_CAPACITY），calls 恰为 `[TRANSIT, DRIVING]`——不静默用 driving 时长、不重试切 mode |
| **无 feasibility override / 无振荡** | ✅ | C14 calls 无第三次调用；代码无"infeasible→重查 DRIVING"路径（v1 固定 mode 语义，plan-c §12 决定） |
| 时序一致性 | ✅ | 推荐发生在 timing 之前/之中（`_route_for_pair` 是 `_emit_day` leg 循环内唯一出口），不存在"先按 DRIVING 排表再改 TRANSIT" |

---

## 12. Real AMAP Golden（独立调用，3 案例 5 次，0 限流）

脚本 `C:\Windows\Temp\opencode\b19_c_acceptance_golden.py`（未提交；真实 provider + `_route_for_pair` 生产路径 + REAL_ONLY）：

| Case | 独立结果 | 判定 |
| --- | --- | --- |
| **G2** 体育中心→正佳 09:00 | **WALKING**，873s / 1091m / cost=0 / provider=AMAP / estimated=false | ✅ 与开发方一致；walking ≤1200s 短路 |
| **G1** 正佳→广州塔 09:00 | **DRIVING**，931s / 6085m / AMAP / false | ✅ 与 live facts 一致：transit ≈1250s > 931×1.2=1117 → ROAD_SIGNIFICANTLY_FASTER（live driving 较 B19-A 快照 1632s 更快；facts 驱动行为正确，快照期望由确定性 C2 锁定） |
| **G3** 正佳→白云机场 09:00 | **DRIVING**，3054s / 38972m / AMAP / false | ✅ transit ≈12139s（多轮独立探针一致）> 3054×1.2 → DRIVING |

结论：推荐器在所有独立真实案例中严格跟随实时 route facts；`provider=AMAP / estimated=false` 保持；无假路线、无 DRIVING 冒充 TRANSIT。

---

## 13. Real Smoke（独立复核开发方证据）

开发方 smoke（广州 2 日/3 日，经工厂 provider）与执行报告一致，独立审查其自洽性：

| 项 | 2 日 | 3 日 |
| --- | --- | --- |
| legs / mode distribution | 4 legs 全 DRIVING | 7 legs（6 DRIVING + 1 WALKING） |
| 每 leg 平均调用 | 8/4 = 2.0 | 13/7 ≈ 1.86 |
| provider failures | 0 transit / 0 route | 0 transit / 0 route（1 次 POI 搜索 RATE_LIMITED 自动重试成功） |
| reason 一致性 | 全部 ROAD_SIGNIFICANTLY_FASTER（transit 已 probe，provider_calls_used=2k 序列自洽） | 同上 + 1 条 WALKABLE |

抽查 11 个 leg：无"walk 6min→DRIVING"（walkable 短路保证）、无"transit 60min/4 换乘→TRANSIT"（三条件拒绝）——与真实 facts 相符。

---

## 14. Regression（独立执行）

```
Python targeted: pytest test_mode_recommendation test_transit_mode test_amap_transit
                 test_b19_transit_chain → 93 passed, exit 0
Python related:  17 文件套件（worker/outcome/schema/replan/golden/closure…含 amqp_worker 工厂修复）
                 → 330 passed, 1 warning, exit 0
Python full:     pytest -q --basetemp=%LOCALAPPDATA%\Temp\pytest-b19c-acc-full
                 → 1654 passed, 37 skipped, 1 warning, exit 0
ruff:            ruff check src/trip_agent tests → All checks passed! (exit 0)
Java targeted:   mvn -pl apps/travel-server test -Dtest=PlanningCompletedEventParserTest,
                 PlanningReviewRequiredEventParserTest → 89 tests, 0 failures, 0 errors
                 （Java production 0 修改；执行期全量 537/0/0 已由开发方在 Docker 运行下完成）
Web targeted:    vitest run tests/TransitLegControl.test.ts tests/transit.test.ts → 9 passed
                 （Web production 0 修改；执行期全量 447 + typecheck 0）
```

说明：Windows temp ACL 环境问题沿用 `--basetemp` 可写路径解决；唯一 warning 为 B17 既有 AnyHttpUrl 序列化提示（与 B19-C 无关）。

---

## 15. B17 / B18-B / B19-B Regression

| 批次 | 结果 | 证据 |
| --- | --- | --- |
| B17（timing/worker/event） | ✅ 无回归 | worker/outcome/schema/replanning 套件在 related 330 中全绿；None-omit schema 测试通过 |
| B18-B（walking baseline） | ✅ 无回归 | `test_transit_mode.py` 14 passed（B1-B9 调用序列不变：短距 1 call / 超阈值 [W,D] / 长距 1 call）；C1/C15/C16 baseline GREEN 锁定 |
| B19-B（TRANSIT provider） | ✅ 无回归 | `test_amap_transit.py` 43 + `test_b19_transit_chain.py` 8 passed（cost/walking_distance/transfer_count/cache 日期 bucket/v11-v2） |
| 普通 planner route calls | ✅ 不增加 | `_route_for_pair` 新增参数全部 keyword-only 带默认值（city=None/remaining_legs=1/mobility_reduced=False）→ B18-B 测试路径行为与原完全一致；全量规划路径 transit probe 计入统一 budget |

---

## 16. D1（B19-B 缺陷，验收确认未修、不影响 B19-C）

- **未修改**：`_amap_transit.py` mtime `Aug 19 20:29`（B19-B 时代），B19-C 零改动（修订 2 落实）。
- **复测**：C9b 独立复跑确认 polyline 几何缺失 → `PROVIDER_SCHEMA_CHANGED`（MALFORMED，非可恢复）→ raise，fail-closed 语义保持。
- **不影响 recommendation facts**：duration/distance/cost/walking_distance/transfer_count 全部来自 segments 数值字段，与 polyline 几何无关（B19-B 验收 §5/§19 已确认，本轮独立复核代码路径无变化）。
- **暴露面**：B19-C 使 TRANSIT 成为默认候选，D1 触发面相对扩大；但本验收独立真实调用（5 次）+ 开发方 Golden/smoke（12 次）从未触发（真实响应均携带 polyline）。plan-b §4.4"跳段 + 2 点退化"补丁仍登记为 B19-D / 独立 follow-up。

---

## 17. Scope Audit

| 检查项 | 结果 |
| --- | --- |
| 修订 1 无固定 80 魔法值 | ✅（docstring 说明取代关系，无代码引用） |
| 修订 2 D1 未修 | ✅（`_amap_transit.py` 零改动，C9b 保持 fail-closed） |
| `PUBLIC_TRANSIT` / `ROAD` enum / `SELF_DRIVING` / TAXI provider | ✅ 无（`ROAD_*` 仅为 reason 枚举标签，非 mode 抽象） |
| weighted score / LLM / OR-Tools 全局优化 | ✅ 无（ordered rules 纯函数） |
| feasibility override / mode 振荡 | ✅ 无（C14：单次 [TRANSIT, DRIVING]，无重试） |
| 天气 / 行李 / 交通偏好 / 自驾约束 | ✅ 无（pace/weather/luggage 未进入规则） |
| event v12 / contract 变更 | ✅ 无（completion v11 / review v2 不变；`contracts/` 无 v12） |
| DB migration | ✅ 无（最新 V37，无 V38） |
| Java / Web production | ✅ 0 修改（mtime 核验：2026-08-19 23:30 后无任何改动） |
| manual edit TRANSIT 真实化 | ✅ 未做（登记 B19-D） |
| B18-C diversity / B18-D dedup | ✅ 无 |
| 新增文件范围 | ✅ 仅 `mode_recommendation.py` + `test_mode_recommendation.py` + 两个既有文件最小增量 + `test_amqp_worker.py` mock 分支 |

---

## 18. Observations（非缺陷，记录备查）

- **O1 — live driving 时长波动可翻转 G1/G8 的 TRANSIT↔DRIVING 结果**：B19-A 快照 driving 1632s（transit 优）；验收日 live driving 931-986s（transit 慢 27-34% → 规则正确选 DRIVING）。这是"facts 驱动"的预期行为，不是算法缺陷；TRANSIT 优势行为由确定性测试（C2/G1-fixture）锁定，不受实时路况影响。
- **O2 — walking 短路日志的 `budget_degraded=false`（小写）与 stage-2 日志的 `False`（大写）不一致**：纯日志文案差异，不影响语义（WALKABLE 分支恒为 false）；可选后续统一。
- **O3 — `accessible_burdens` docstring 提到 STEP_FREE，但调用方仅对 `mobility_level=="REDUCED"` 生效**：与既有 mobility repair 语义一致（全仓 STEP_FREE 均不视为 reduced），为文档措辞问题，非行为缺陷。

---

## 19. Known Gaps（不等于 Defect）

- manual edit TRANSIT 仍为 Java 本地估算（provider=DEMO/estimated=true）；planner-generated 为真实 AMAP——**B19-D 必做 follow-up**；B19-C 后用户更常见真实 transit，一致性 gap 严重度上升。
- 无 Road/Taxi/Self-driving 语义模型（DRIVING 仍为 road baseline；TAXI 无真实 provider）——B19-D。
- 无用户交通偏好 / 天气 / 行李输入——后续批次。
- 无 feasibility override（v1 固定 mode；bounded override 登记 future）。
- 无全局 mode 优化（per-leg 确定性推荐；全局一致性留作 future）。
- D1 polyline 边界缺陷 follow-up（plan-b §4.4 补丁）。
- 跨城 transit 受限（B19-B 既有 Known Gap，city=trip.destination 同城语义）。

---

## 20. Final Recommendation

```
B19-C 允许收口：YES（PASS）
是否允许进入 B19-D 计划阶段：YES
```

理由：独立代码精读确认 ordered rules（duration 比 R=1.2 + transfer N=2 + walking W=1500，9 案例 Golden expected-match 100% 校准）与 walking 短路优先（非 fastest wins，C1 锁定）；不比较 transit 票价与 driving 过路费；可恢复失败安全降级、非可恢复 raise（C6-C9c 全绿）；动态 remaining-leg 预算保留取代固定 80（修订 1 落实，96 上限不变，7 日 worst ≤88）；cache 复用（C11）；selected duration 真实进入 forward-fit/fixed-slot 且无 override/振荡（C13/C14）；reason 结构化 trace 不污染 v11；两项执行前修订（动态预算 / D1 不修）均如实落实；独立真实 AMAP Golden（5 次调用 0 限流）与开发方 smoke 证据自洽；B17/B18-B/B19-B 零回归；Python 1654 / ruff / Java parser 89 / Web 9 独立复跑干净；contract v11/v2 不变、DB 零 migration、Java/Web production 零修改、无 B19-D scope 污染；D1 保持非阻塞 follow-up。未发现 B19-C 范围内缺陷，仅 3 项非缺陷观察（O1-O3）。

**准确结论**：B19-C 建立了基于真实 WALKING / TRANSIT / DRIVING route facts 的第一版 staged multi-mode recommendation。Road/Taxi/Self-driving 语义、用户交通偏好、天气/行李、manual edit 真实化、feasibility override 与全局 mode 优化仍属后续阶段（B19-D 或独立批次）。
