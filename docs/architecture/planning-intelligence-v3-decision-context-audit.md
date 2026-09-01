# TripPilot Planning Intelligence 3.0
## 统一决策架构审计与方案设计（Phase A · AUDIT + DESIGN ONLY）

> **阶段**：AUDIT + DESIGN ONLY。本文未修改任何代码。
> **日期**：2026-08-31
> **性质**：代码级审计。所有结论锚定 `file:line`（相对 `apps/agent-service/src/trip_agent/`，下称 `BASE`）。
> **前置**：V1（成本/天气/预算/人数）、V2（POI 语义治理、Trace 接线、Pace 生效）已实施并经 30/30 反事实验证（`scripts/simulate_planning_v2.py`）。

---

# 0. Executive Summary

V2 之后，系统的风险确实从「Policy 不够多」变成了「Policy 分散」。但审计的核心结论是：

**本系统已经拥有一个 Coordinator——只是它只有一个决策点那么大。**

`planning/transport_strategy.py` 就是 Weather × Budget × Mobility 三个 Policy 的统一裁决器：一张有序规则表（`MOBILITY_SAFETY > WEATHER_SAFETY > BUDGET_CONSTRAINT > COMFORT_ALLOWS_ROAD > DEFAULT`，transport_strategy.py:9-15），每天一次，把三个上下文解析成纯参数（步行阈值 + 公交容忍比 + 理由），再喂给无上下文感知的模式规则。**这个模式已被 30/30 反事实验证。**

因此本审计的推荐不是新建 Decision Coordinator（方案 C），而是：

1. **方案 B（推荐）**：把上下文解析收敛为一个一次构造的 `PlanningContextView`（消除散落与重复计算），Policy 保持纯函数；冲突裁决只在**真正存在多 Policy 冲突的决策点**按 transport_strategy 的既有模式落有序规则表。目前唯一多 Policy 冲突点就是交通（已解决），其次是新增的餐食预算（本审计给出设计）。
2. **不建 God Coordinator**：审计了全部 12 个决策点，其中 9 个是单 Policy 消费（见 §4），为它们引入中央协调是纯开销。
3. **Trace 复用**：现有 `DecisionTrace → DecisionExplanation` 体系足够（§8），禁止第三套模型。缺口不在模型而在**发射点覆盖**（DP-1 池准入、DP-2 排序、DP-5 餐食选择三个决策点静默）。
4. **餐食预算是最大的真实缺口**：`MealDemand.budget_per_person` 是全链死参数（daily_schedule.py:212 字段存在、431/451/464 一路透传，但 planning_provider.py:730 的 `plan_day` 调用点不传 → 恒 None），餐厅选择零成本参与。§7 给出最小落地设计。
5. **住宿成本账是诚实的**：每晚 300 元（按间不按人）随"返回住宿"节点入总额并参与 BUDGET_LIMIT 硬校验，但它是一个无价格来源的 `CITY_ESTIMATE` 常量（cost_model.py:56），不做选址、不看真实价格。Scope 保持，不做酒店平台（§7.4）。

---

# 1. 当前架构图（基于真实代码，禁止猜测部分的边界即边界）

```
用户输入 (worker/contracts.py: PlanningCreateCommand)
  trip.constraints = budget / travelers / pace / mobility / preferences /
                     must_visit / avoid / fixed_schedules / meal_windows
  guideEvidence.facts + planningContext.facts   ← 知识层（天气/票价/人均消费/闭馆）
        │
        ▼
┌─ 上下文解析（planning_provider.py，模块级纯函数，每次消费现算）─────────────┐
│  weather_statements_for_date            :342  （guide facts 按日过滤）      │
│  planning_context_weather_statements    :354  （context facts 按日过滤）     │
│  weather_level_for_date                 :383  （→ WeatherLevel）            │
│  walking_threshold_seconds_for_date     :373  （→ 阈值）                     │
│  budget_pressure_for                    :417  （→ TIGHT/NORMAL/RELAXED）    │
│  _attraction_cost_hints                 :403  （全候选成本，排序前算一次）    │
│  resolve_transport_strategy_for_date    → transport_strategy.resolve（有序规则）│
└──────────────────────────────────────────────────────────────────────────┘
        │
        ▼
① 召回   _collect_pois (planning_provider.py:1836)  关键词含"美食"(domain/shared.py:35)
        ▼
② DP-1 池准入  classify_place == "ATTRACTION" (poi_quality.py:145/173; provider:503-507)
        ▼
③ DP-2 排序  CandidateRanker.rank (candidates.py:79) / _score (:188)
│            偏好+40 · 必去+100 · 导览+25 · 天气室内+20/室外−10 · 亲子+15 · 预算超上限−30
│            硬过滤：重复/空地址/跨城/避去/语义重复（pinned 全豁免 :126-147）
        ▼
④ DP-3 日调度  plan_day (daily_schedule.py:527)
│            day_window_minutes (:300)  ← pace(INTENSIVE 20:00)
│            _fill_slots (:854)         ← BUFFER_BETWEEN[pace] (:63)
│                                        ← mobility −30 (:881)
│                                        ← RELAXED −60 (:74/:885)
│            choose_activities (:465)   ← 区域聚合
        ▼
⑤ DP-4 餐位预留  build_meal_demands (:423)  ← 窗口/日型/pace/meal_windows
│               （budget_per_person 参数全链存在但恒 None，:730 调用点不传）
        ▼
⑥ DP-5 餐厅选择  _resolve_meal_poi (planning_provider.py:1600 区)
│            "美食"检索 → RESTAURANT 门槛(SI-5) → region 过滤 → candidates[0]
│            （无排序、无成本参与；失败 → placeholder，餐时保留）
        ▼
⑦ 产出  _emit_day (:1243)：槽序列 → 住宿节点(:1334-1366，每晚 300 CITY_ESTIMATE)
        ▼
⑧ DP-6 交通  _route_for_pair (:1966)
│            步行短路(:2008, is_walkable(时长, 阈值))
│            → _recommend_transit_or_road(:1966)
│            → decide_transit_or_road(mode_recommendation.py:117 有序规则)
│            策略参数来自 transport_strategy.resolve_transport_strategy(:67)
│              有序裁决表：MOBILITY_SAFETY > WEATHER_SAFETY > BUDGET_CONSTRAINT
│                          > COMFORT_ALLOWS_ROAD > DEFAULT (transport_strategy.py:9-15)
        ▼
⑨ DP-7 前向拟合  forward-fit (:1393-1415)  固定槽冲突 → _fixed_slot_timing_error(:1468)
        ▼
⑩ DP-8 成本  cost_model.resolve_{attraction,meal,transit}_cost (:104/:127/:141)
│            PROVIDER 事实 > RULE_ESTIMATE；人摊(票/餐/公交)×人数，车/间不乘
│            住宿：每晚一个"返回"节点挂 300（:1357-1370，CITY_ESTIMATE，不乘人数）
        ▼
⑪ DP-9 硬校验  feasibility 11 规则（catalog.py:14-27）
│            BUDGET_LIMIT: ratio>1.0 即 FAIL，零容差（rules/core.py:195-229）
│            有界修复 6 动作（repair/catalog.py:34-66）；预算 FAIL 不可修（catalog.py:5-7）
│            → 评估器重跑 5 规则并 raise（evaluation/evaluator.py:71-96）
        ▼
⑫ DP-10 评估  PlanEvaluator (evaluation/evaluator.py)
             五维评分 + BUDGET_WARNING_RATIO 0.85（rules.py:54）+ warnings
        ▼
⑬ Trace  DecisionTrace（planning/decision_trace.py，进程内）
             发射点：步行短路(:2036)/模式规则(:2102)/预算降权(:567)/节奏(:609)
             → explanations.py:56 → DecisionExplanation（ReasonCode 词表 models.py:35）
             PlanningFactImpact（trusted_context）→ WEATHER_WALKING_POLICY_APPLIED
             评估 warnings / feasibility RuleResults（独立既有通道）
```

**结构性事实**：`plan_day` 是纯函数；`_fill_slots` 是贪心；OR-Tools 仍零使用；`DecisionTrace` 是进程内对象（protocols.py:124-128），不入 wire。

---

# 2. Policy Inventory

| Policy | 定义位置 | 输入 | 影响的 Decision | 输出 | Trace | 问题 |
|---|---|---|---|---|---|---|
| Weather | weather_policy.py:26-40,43,66 | 分日天气陈述（guide+context facts） | DP-6 模式（阈值）；DP-2 排序（室内/室外 ±） | WeatherLevel / 步行阈值 | ✅ TRANSIT_MODE + PlanningFactImpact | 阈值只作用于**步行时长**，对"是否值得打车"无经济性判断 |
| Budget | budget_policy.py:18-23,26,43,56 | budget_amount×travelers×days | DP-2 排序（−30/上限）；DP-6 策略（容忍比）；DP-9 BUDGET_LIMIT | BudgetPressure / ceiling | ✅ BUDGET_CONSTRAINT（排序侧）；策略侧经 reason 字符串 | **餐食零参与**（§7）；无"已消费预算"概念（事后才有总额） |
| Transport Strategy | transport_strategy.py:67（有序规则 ：9-15） | WeatherLevel+BudgetPressure+mobility_reduced | DP-6 模式参数 | TransportStrategy(阈值,容忍比,reason) | reason 随 TRANSIT_MODE trace 发出 | ✅ 这就是既有微型 Coordinator（唯一多 Policy 裁决点） |
| Mode Rules | mode_recommendation.py:117 | 真实路线事实（时长/换乘/步行） | DP-6 选 WALKING/TRANSIT/DRIVING | ModeRecommendation(reason,considered) | reason 进日志与 trace.mode_reason | considered_modes 数据齐全但**未进 trace**（可白捡） |
| Pace | daily_schedule.py:48,62-75,878 | constraints.pace | DP-3 容量（INTENSIVE 窗口/RELAXED 折扣/缓冲） | 日容量 | ✅ PACE_POLICY（仅 RELAXED） | INTENSIVE 无独立 trace（行为=窗口延长，可接受） |
| Mobility | mode_recommendation.py:98 + daily_schedule.py:873 | mobility_level | DP-6 负担上限（换乘≤1/步行×0.5）；DP-3 容量−30 | burden limits | ❌ **静默**（仅日志） | 与 Weather 同类的合法收紧，无任何解释载体 |
| Cost Model | cost_model.py:104/127/141 + provider:1334-1366 | 知识事实×人数/模式 | DP-8 全部成本行 | ResolvedCost(amount,source) | cost_source 逐行溯源（诚实） | 住宿是 CITY_ESTIMATE 常量（§7.4） |
| POI Semantics | poi_quality.py:145/173/342 | type_code/name | DP-1 池准入；时长画像 | PlaceKind/PoiRole/DurationProfile | ❌ 静默过滤 | UNKNOWN/OTHER 被剔除时用户不可见（ fail-closed 无解释） |
| Ranking | candidates.py:79/188 | 偏好/必去/导览/天气/人数型/成本提示 | DP-2 排序+入选 | RankedCandidate(score,reasons) | ❌ **reasons 只存在于内存对象，不进任何 trace** | 排序理由词表已存在（PREFERENCE_MATCH 等 8 种）但用户不可见 |
| MealDemand | daily_schedule.py:416 | 日型/窗口/pace/region | DP-4 餐位 | MealDemand(start,end,region,**budget_per_person=None**) | ❌ | budget_per_person 死参数（§7） |
| Meal Selection | planning_provider.py:1600 | 关键词/region/exclusions/RESTAURANT 门槛 | DP-5 餐厅绑定 | Poi \| None(placeholder) | ❌ 静默 | candidates[0] 无排序无成本——预算最大缺口 |
| Validation | feasibility/catalog.py:14-27（11 规则） | itinerary+validation_inputs+budget | DP-9 拒绝/修复 | RuleResults/RepairActions | ✅ 自有 RuleResult 通道 | 与 DecisionTrace 是两套并行解释体系（§8 论证：不合并，各司其职） |
| Evaluation | evaluation/rules.py | itinerary+budget_ctx | DP-10 评分/警告 | 五维分/Warnings/Decisions | ✅ DecisionExplanation | 样板文案（PLAN/DAY 级）与真实 trace 并存 |

---

# 3. Decision Point Inventory

判定标准：**改变输入会改变产出的最小决策单元**。每个决策点标注「输入 → Policy → 输出 → 责任模块 → Trace 现状」。

| # | Decision Point | 输入 | Policy（裁决规则） | 输出 | 责任模块 | Trace 现状 |
|---|---|---|---|---|---|---|
| DP-1 | 候选是否进景点池 | type_code/name（13+ 前缀+名称兜底） | POI 语义分类（fail-closed，SI-1..6） | 池成员集合 | poi_quality.py:145 / provider:499 | ❌ 静默（剔除无解释） |
| DP-2 | 候选如何排序/入选 | 偏好、必去、导览事实、天气、成本提示、pinned | 加权评分 + 硬过滤 + pinned 豁免（candidates.py:79） | 有序候选+score+reasons | candidates.py | ❌ reasons 未出管道 |
| DP-3 | 每天安排多少活动 | pace、mobility、锚点、固定预约 | 窗口×缓冲×折扣（RELAXED−60/mobility−30/INTENSIVE 窗） | PlacedActivity 集合 | daily_schedule.py:847 | ⚠️ 仅 RELAXED 有 PACE_POLICY |
| DP-4 | 餐位如何预留 | 日型、窗口、pace、USER 餐窗 | 时间优先+窗交集（:416） | MealDemand 集合 | daily_schedule.py | ❌（USER 窗冲突有 warning） |
| DP-5 | 餐厅怎么选 | 关键词召回、region、跨餐去重、RESTAURANT 门槛 | region 优先+候选顺序（**无成本/评分**） | 餐厅 Poi 或 placeholder | provider:1652 | ❌ 静默 |
| DP-6 | 每段什么交通方式 | 天气级别、预算压力、mobility、真实路线事实 | **两级裁决**：策略有序规则表 → 模式有序规则（步行短路优先） | mode + leg 事实 | transport_strategy + mode_recommendation + provider:1878 | ✅ TRANSIT_MODE（两分支） |
| DP-7 | 路线放不下怎么办 | 相邻槽 gap vs 实际路线时长 | forward-fit 平移；fixed 不可动 → fail-closed | 平移后时刻表 / PlanningInfeasibleError | provider:1393-1468 | ⚠️ 仅错误码（INSUFFICIENT_DAY_CAPACITY 等） |
| DP-8 | 成本怎么记 | 知识事实、人数、模式 | PROVIDER>RULE_ESTIMATE；人摊×人数/间车不乘 | 每行金额+cost_source | cost_model.py | ✅ 逐行 cost_source（溯源型） |
| DP-9 | 方案何时被拒绝 | 11 类硬规则输入 | 首个 FAIL 定 blocker；6 类有界修复 | VERIFIED/NEEDS_REPAIR/UNVERIFIED | feasibility/* | ✅ RuleResults（独立体系） |
| DP-10 | 方案怎么评分/解释 | itinerary+budget_ctx+day_stats | 五维分段评分；硬违例 raise | PlanEvaluation | evaluation/* | ✅ DecisionExplanation |
| DP-11 | 到返/住宿锚点解析 | place_name/place_ref + 检索结果 | 精确 id 优先→文本匹配；SI-8 语义门槛 | ResolvedTravelAnchors / TRAVEL_ANCHOR_UNAVAILABLE | provider:1732 | ⚠️ 仅错误码 |
| DP-12 | 上下文本身怎么解析 | command + facts | 各模块函数现算（见 §1 框） | WeatherLevel/Pressure/Strategy/CostHints | provider:342-435 | —（非决策，是输入层；**散落+重复计算**） |

**多 Policy 冲突只真实存在于 DP-6**（天气×预算×体力×模式）。DP-2 内部是多**信号**加和（无对抗），DP-3 是单 Policy 参数化。这直接决定 §6 的结论。

---

# 4. Policy Conflict Matrix

裁决现状：✅=已有明确裁决且实现；⚠️=无冲突但无解释；❌=潜在冲突未裁决（真实缺口）。

| 冲突对 | 现状与裁决点 | 裁决规则 | 评价 |
|---|---|---|---|
| Weather × Budget | ✅ transport_strategy.py:79-82 | TIGHT 压过雨天（规则 3：TIGHT+RAIN 仍放宽公交容忍——"budget beats comfort"）；RELAXED+雨天收窄容忍（规则 4，可以打车） | 唯一显式声明的跨 Policy 优先级，有测试有验证 |
| Weather × Mobility | ✅ transport_strategy.py:75-76 | MOBILITY_SAFETY 最高优先：reduced+雨 → 放宽公交容忍；同时步行阈值收紧 | 一票安全优先，正确 |
| Budget × Pace | ⚠️ 无交互 | 排序降分与容量折扣作用于不同决策点，效果可加（少排活动→自然省交通费），无对抗 | 无需裁决；**解释面**：两者可同日触发，trace 各自独立，用户可读 |
| Budget × Fixed Appointment | ❌ **未裁决** | 固定预约的准时性由 forward-fit/硬规则保证，但**去固定预约那段的模式选择对 deadline 失明**：TIGHT 预算可能选了慢公交导致 `INSUFFICIENT_DAY_CAPACITY` 硬失败（provider:1468） | **真实缺口**。倾向裁决：固定槽前一段的 leg 应以到达确定性优先（容忍比收紧或允许 road 短路），需要 P2 立项（见 §10 P2-2 备选） |
| Pace × Fixed Appointment | ✅ daily_schedule（fixed 优先占槽） | 固定项先占槽，RELAXED 折扣只压缩观光容量；不够时走容量修复（丢 optional POI/放宽系统默认边界，provider:755-795） | fixed 永不被移动/删除（repair engine:583-591）——硬保证 |
| Mobility × Route Efficiency | ✅ mode_recommendation.py:117-144 | 负担上限收紧可以否决更快的 TRANSIT（换乘>1 / 步行>750m 即拒）——效率主动让位安全 | 有意为之，文档明确 |
| Weather × Route Efficiency | ✅ mode_recommendation.py:6-8 | 步行短路是产品规则（walkability wins），天气只能收阈值不能推翻它 | 一致性正确 |
| Budget × Meal | ❌ **未裁决（最大缺口）** | 餐厅选择对预算完全失明（DP-5），`budget_per_person` 全链死参数 | §7 给出方案 |
| Accommodation × Budget | ⚠️ 单向参与 | 300/晚 CITY_ESTIMATE 进总额进 BUDGET_LIMIT，但无真实价格、无档位选择 | §7.4 保持 scope |
| Budget × Validation | ✅ BUDGET_LIMIT | ratio>1.0 即 FAIL，**零容差**，不可修复（repair catalog:5-7 故意不修） | "预算是硬约束"成立；容差策略（如 ≤5% 软警告）留产品决策 |

**结论**：系统需要统一裁决的地方， transport_strategy 已经示范了"每天一次、有序规则、输出纯参数"的正确形态；不存在需要全局 Coordinator 的证据。

---

# 5. 三种架构方案比较与推荐

比较维度按用户指定：复杂度 / 可维护性 / 可测试性 / 可解释性 / 扩展能力 / 侵入度。

## 方案 A：保持分散 Policy（现状）

- 现状即"每个决策点就近消费上下文函数"。真实成本：DP-12 散落的 7 个上下文函数存在**重复计算**（`budget_pressure_for` 在排序、trace、每个 `_emit_day` 各算一次；`resolve_attraction_cost` 排序期与 emit 期各算全量；V2 审计 §15 已记录），且**漏传无类型保护**（全靠调用点自觉）。
- 复杂度低、侵入零；可维护性随决策点数量线性恶化——每新增一个消费天气的决策点，都要自己记得调 `weather_level_for_date`。
- 反事实纪律下风险可控（30/30 验证在），但"新 Policy 接入成本"随决策点数上升。

## 方案 B：统一 Decision Context（PlanningContextView）⭐ 推荐

- **做法**：新增 frozen dataclass `PlanningContextView`（在 `planning/` 新文件），在 `_plan_with_skeleton` 入口**一次构造**：weather levels（逐日）、budget pressure、ceiling、per-person-per-day、mobility、pace、anchors、facts、cost_hints。全部现有模块级解析函数**改为**从 View 取值（或变为其私有方法）。Policy 保持纯函数（签名接收 View 的字段，不接收 View 亦可）。
- 复杂度：中低（一个数据类 + 消费点改道）；侵入：中（provider 内部改道，模块签名不变）；可测试性↑（View 可直接构造，策略函数已纯）；可解释性↑（消除重复计算后 trace 证据天然一致）；扩展性：新 Policy 只需在 View 加字段——接入成本从 O(决策点) 降为 O(1)。
- **不加 Coordinator**：冲突裁决不进 View。哪个决策点存在多 Policy 冲突，就在那个决策点落一张 transport_strategy 式有序规则表（目前仅 DP-6 已有；DP-5 餐食预算若引入"预算 vs 口味"裁决，也用同模式，见 §7.3）。
- 与 V2 审计 §15.3 的 `PlanningContextView` 建议一致，属于**兑现旧账**而非新架构。

## 方案 C：Decision Context + Decision Coordinator

- Coordinator 统一收集各 Policy 倾向、仲裁、下发决策。审计结论：**拒绝**。
- 证据：12 个决策点中仅 DP-6 存在多 Policy 对抗且已被裁决；其余为单 Policy 消费或多信号加和。Coordinator 在 9 个决策点上只是把函数调用换成消息传递——复杂度↑、可测试性↓（要 mock Coordinator）、可解释性反而受损（决策离裁决远了）。
- 这正是"为架构而架构"的形态。若未来出现 ≥3 个多 Policy 冲突决策点，再升级不迟——transport_strategy 的表驱动形态可以直接平移，不需要前置建设。

## 推荐

**方案 B**，分两刀落地（P2-0 上下文收敛 + P2-1 餐食预算），冲突裁决按"每决策点有序规则表"的既有模式就地解决（DP-5 的设计见 §7.3）。原 V2 审计 §15.3 的 PlanningContextView 建议在此兑现，且保持"不引入重量级对象、不建持久化"的既有纪律。

---

# 6. 统一 Context 设计（PlanningContextView）

```python
# planning/context_view.py（P2-0 新文件；示意，Phase B 按此实施）
@dataclass(frozen=True, slots=True)
class DayContext:
    trip_date: date
    weather_level: WeatherLevel | None
    walking_threshold_seconds: int
    transport_strategy: TransportStrategy   # 含 reason（DP-6 裁决结果）

@dataclass(frozen=True, slots=True)
class PlanningContextView:
    command: PlanningCreateCommand          # 只读引用
    budget_per_person_per_day: Decimal | None
    budget_pressure: BudgetPressure | None
    activity_cost_ceiling: Decimal | None
    facts: tuple[PlanningContextFact, ...]
    days: tuple[DayContext, ...]            # 逐日一次解析，杜绝重复计算
    # 派生只读方法（纯函数）：cost_hints已在构造期解析一次
```

满足用户六条要求：①输入快照（构造后不可变）；②不改业务状态（无 setter、无副作用）；③Policy 纯函数（现有 weather_policy/budget_policy/transport_strategy/candidates 均已是纯函数，保持）；④可测试（View 可手工构造——现有单测已用纯函数直测，View 只是把"解析"变成"构造"）；⑤可解释（Strategy.reason / BudgetPressure 本身就是证据）；⑥无万能 Service（View 无行为方法、无决策逻辑——与 V2 审计 §15"DTO 不是 God Object，散落才是问题"的判定一致）。

**明确不做**：View 不做缓存失效、不做跨请求缓存、不进 wire、不持久化。

---

# 7. Budget-aware Meal Planning 方案（最大真实缺口）

## 7.1 现状审计结论（全部实测）

| 环节 | 现状 | 证据 |
|---|---|---|
| MealDemand.budget_per_person | **死参数**：字段/透传链完整（daily_schedule.py:212 字段、:431 build_meal_demands 形参、:451/464 传入 _meal_demand、:746/:780 透传），但生产调用点 planning_provider.py:730-746 **不传** → 恒 None | grep 全量：无任何读取消费点 |
| 餐厅召回 | 关键词 `"美食"`（+可选 region 前缀+餐饮偏好），limit=5 | provider:1652 区 `_meal_keywords` |
| 语义门槛 | classify_place == RESTAURANT（V2 SI-5） | ✅ |
| 选择算法 | region 命中取 `regional[0]`，否则 `candidates[0]`；**无排序、无评分、无成本**；跨餐 excluded_ids 去重 | provider:1652-1628 |
| 餐成本 | REFERENCE_SPEND 事实（按餐厅名 text_matches）×人数；否则 50×人数 RULE_ESTIMATE | cost_model.py:127-138 |
| 预算参与 | 事后（BUDGET_LIMIT 总额 + budget_fit 评分），**决策期零参与** | cost 不进 DP-5 |
| 后果 | 预算 1500 时人均 250/天，一顿楼外楼（REFERENCE_SPEND 180×2=360）占掉日均预算 144%，与 30 元的小馆同权重 | 反事实验证 C 组实测 |

## 7.2 数据来源（不新增数据设施）

- 人均价格：`REFERENCE_SPEND` 知识事实（已有管道）；无事实的餐厅 → `DEFAULT_MEAL_COST`（50/人，RULE_ESTIMATE）。
- 预算侧：`budget_per_person_per_day`（budget_policy.py:26，已有纯函数）。
- **餐食预算包络（新常量）**：`MEAL_BUDGET_RATIO`（建议 0.30，文档化产品常量）→ 每人每餐包络 = per_person_per_day × MEAL_BUDGET_RATIO ÷ 当日餐数(1-2)。例：250/日 → 每餐 ~37.5-75/人。住宿/交通/门票占其余额（与 `ACTIVITY_CEILING_RATIO=0.35` 同风格，总和可 >1 因为是软包络不是硬切分）。

## 7.3 餐食选择的预算裁决（每决策点有序规则，不建中央协调）

```
Total Budget → per_person_per_day（budget_policy:26，已有）
            → MealEnvelope = per_person_per_day × MEAL_BUDGET_RATIO / 当日餐数
            → 逐餐厅人均价（REFERENCE_SPEND 事实；无事实 → 50 估算，**标记 UNKNOWN_COST**）
            → 有序规则（first-match-wins，transport_strategy 同形态）：
              1. region 命中的候选里存在「人均 ≤ 包络」的 → 取其中第一个（顺序即召回序）
              2. region 命中但全部超包络 → 仍取第一个，但发 trace（软超支，不拒绝——
                 饿肚子不是可接受输出，与"餐食总会发生"的既有不变式一致 provider:1278）
              3. 无 region → 全局候选按 1/2 同规则
              4. 全失败 → placeholder（现行为不变）
```

- **传参接通**：`plan_day` 调用点（provider:746）补 `budget_per_person=budget_per_person_per_day(...)`——管道早就在，只差最后一跳；`MealDemand.budget_per_person` 从死参数变活。
- **_trace**：规则 2 命中时发 `DecisionTrace(subject_type="ACTIVITY"/"PLAN", reason_codes=("BUDGET_CONSTRAINT",), evidence={meal_envelope_per_person, restaurant_spend_per_person, budget_pressure})`——**复用现有词表**，不新增 ReasonCode。
- **不做**：不做餐厅评分系统、不做跨餐全局优化、不做 `if price > budget: reject`（预算紧张时把餐厅全变 placeholder 是更坏的输出）。

## 7.4 住宿成本专项结论（保持 Scope）

- **账是诚实的**：每晚一个"返回住宿"节点挂 `DEFAULT_ACCOMMODATION_PER_NIGHT`（300，cost_model.py:56），`nights = day_count-1`（provider:1349-1366 注释明确"once per night"），按间不按人（注释+验证输出一致），cost_source=`CITY_ESTIMATE`，进总额 → 进 BUDGET_LIMIT（agent 实测：多日行程 BUDGET_LIMIT 含住宿）。
- **不做**：酒店搜索、档位选择（经济/舒适档）、选址建议——那是在重做预订平台，超出"用户输入约束真实进入决策"的边界。
- **可选小改进（P2-3b，默认不做）**：若知识层出现 `ACCOMMODATION_PRICE` 事实（用户自订酒店已知价），用它替换 300 常量（cost_source=PROVIDER）——成本模型已有同构模式（票价/餐标），增量极小。仅当产品真实产生该事实时实施。

---

# 8. Decision Output：结论是复用，禁止第三套模型

现有三套"解释"载体职责清晰、无重叠：

| 载体 | 回答的问题 | 状态 |
|---|---|---|
| `DecisionTrace → DecisionExplanation` | "这个决策为什么这么做"（决策级，ReasonCode 词表） | ✅ 保留，**扩发射点**（DP-1/2/5 静默点补 trace） |
| `PlanningFactImpact` | "这条知识事实改变了什么"（事实级） | ✅ 保留（WEATHER_WALKING_POLICY_APPLIED 等） |
| feasibility RuleResult / RepairAttempt | "哪条硬规则判了什么、修了什么"（校验级，自有词表） | ✅ 保留——它回答的是合规性不是偏好性，合并反而失真 |

缺口在**发射覆盖**而非模型：DP-1（池准入剔除）、DP-2（排序理由——`RankedCandidate.reasons` 词表已存在：`PREFERENCE_MATCH/MUST_VISIT_MATCH/GUIDE_FACT_MATCH/BUDGET_TIGHT_COST_PENALTY/WEATHER_INDOOR_PREFERENCE`，只差搬运到 trace）、DP-5（§7.3 补）。**不新建 Decision 模型、不加 SubjectType 之外的新结构。**

---

# 9. 产品层：用户将看到什么

Phase B 完成后，"为什么这份方案适合你"由现有 DecisionExplanation 直接支撑（全部已有或 P2 内补齐）：

- 【天气】`TRANSIT_MODE` trace + `WEATHER_WALKING_POLICY_APPLIED` 事实影响 → "第 X 天有暴雨，长距离步行已改为公交"（B 组验证已证明数据在）。
- 【预算】`BUDGET_CONSTRAINT` 排序 trace（宋城降权）+ §7.3 餐食 trace（"楼外楼人均 180 元超当日餐费预算，已优先小馆"）+ BUDGET_LIMIT 硬拦截文案。
- 【节奏】`PACE_POLICY` trace → "你选择轻松节奏，每天多预留 1 小时休息"。
- 【被剔除的】DP-1 静默剔除（P2-2 补 trace 后）→ "杭州东站/杭州大厦非游览地点，未列入行程"。

组装成用户文案是**纯读侧**工作（P2-3），不改任何规划决策。

---

# 10. P2 实施 Roadmap（每刀独立可回退）

## P2-0 PlanningContextView（上下文收敛，纯重构）

- **Scope**：新建 `planning/context_view.py`；`_plan_with_skeleton` 构造一次；DP-12 的 7 个模块函数改为 View 方法/消费 View；消除 `budget_pressure_for` 逐日重算与 `resolve_attraction_cost` 双算。
- **Files**：`planning/context_view.py`（新）、`infrastructure/amap/planning_provider.py`、（不改 daily_schedule/candidates 签名——它们继续收纯参数）。
- **Behavior Change**：**零**（输出字节不变；这是纪律——重构刀不带行为）。
- **Counterfactual Test**：现有全部反事实测试必须原样全绿（scripts/simulate_planning_v2.py 30/30 + pytest 1934）；新增一个"构造一次"断言（monkeypatch 计数 resolve 函数调用次数 ≤1/日）。
- **Regression Risk**：中低（纯改道；__pycache__ 级风险）。行为不变由全量回归背书。
- **Rollback**：单 commit revert 即可（无数据/契约变更）。

## P2-1 Budget-aware Meal Planning（最大行为增益）

- **Scope**：§7.2/§7.3 全部——接通 budget_per_person、MEAL_BUDGET_RATIO 常量、餐费包络、有序规则选餐、软超支 trace。
- **Files**：`planning/budget_policy.py`（envelope 纯函数）、`infrastructure/amap/planning_provider.py`（:746 传参、:1600 选餐规则+trace）、`planning/daily_schedule.py`（零改动或仅类型收紧）、`tests/test_meal_budget.py`（新）。
- **Behavior Change**：同region多餐厅时，紧张预算选择可变；可能出现"餐厅未变但新增 trace"。placeholder 路径不变。
- **Counterfactual Test**（用户 §十的硬要求）：夹具含餐厅 A（REFERENCE_SPEND ¥30）与 B（¥250）、同 region；断言 budget=1500 → 选 A；budget=10000 → 选 B（或 B 排序上升）；且两次都有/无对应 trace。再断言"只有 A 可用时预算再紧也选 A（不拒绝吃饭）"。
- **Regression Risk**：中——改变真实 AMap 下多餐厅命中时的选择结果（原 candidates[0] 行为被包络规则替代）；Golden 矩阵餐食绑定可能需重校准。
- **Rollback**：独立 commit；回退 = revert（包络常量与 trace 同 commit，一并回退）。

## P2-2 Trace 发射点补全 + 冲突裁决补课

- **Scope**：① DP-2 排序理由上 trace（RankedCandidate.reasons → 决策级 trace，subject=PLAN，汇总"哪些候选因偏好/预算/天气加分降分"）；② DP-1 池准入剔除汇总 trace（"N 个非游览地点未入池"）；③ **Budget × Fixed Appointment 冲突裁决**（§4 唯一未裁决项）：固定槽前一 leg 的模式选择把"到达确定性"纳入（有序规则前置一条："目标槽 time_fixed → 收紧容忍比至 1.0"，transport_strategy 追加规则行 + reason=FIXED_SCHEDULE_DEADLINE，**复用现有词表需评估是否新增 reason**——倾向复用 PROVIDER_CONSTRAINT 或新增一个 Literal）。
- **Files**：`candidates.py`（返回 reasons 已有，零改）、`planning_provider.py`（发射）、`transport_strategy.py`（+1 规则行）、`tests/`。
- **Behavior Change**：③ 会改变"有固定预约且公交显著慢"场景的选路（更保守）；①② 零行为。
- **Counterfactual Test**：①② 断言 trace 出现/内容；③ 断言"固定预约 + TIGHT 预算 + 公交 1.3× 路"原会硬失败（INSUFFICIENT_DAY_CAPACITY）的场景改为 DRIVING 且成功——输入变化 → 决策变化。
- **Regression Risk**：③ 中（改变含固定预约行程的交通选择）；①② 低。
- **Rollback**：①② 与 ③ 分两个 commit，独立回退。

## P2-3 用户解释面（读侧组装，零规划改动）

- **Scope**：把 DecisionExplanation 按主题（天气/预算/节奏/剔除）组装为用户文案列表；输出挂在既有 evaluation decisions 通道（不新增 wire 字段——若需新事件字段则**升级为契约变更另行评审**，默认进程内）。
- **Files**：`evaluation/explanations.py`（组装函数）、可选 agent 工具层消费。
- **Behavior Change**：零（规划结果不变）。
- **Counterfactual Test**：三个场景各断言对应主题文案出现/不出现（晴→无天气段）。
- **Regression Risk**：低。**Rollback**：revert。
- **P2-3b（可选，默认不做）**：住宿 `ACCOMMODATION_PRICE` 事实接入（§7.4）。

## 推迟/拒绝清单

- ❌ Decision Coordinator（§5 方案 C，证据不足）
- ❌ OR-Tools、LLM 决策、POI 重写、wire 契约变更、新 DTO 层（用户禁令 + 审计无需求）
- ⏸ 统一 DP-9 与 DP-10 的解释体系（两套词表职责不同，合并失真）
- ⏸ Pace trace 的 INTENSIVE 版本（行为=窗口延长，无新裁决）

---

# 11. 反事实测试纪律（对 P2 全部新增智能的硬约束）

沿用 V2 验证纪律并加严一条：

1. 每个新 Policy/规则必须有「单变量改变 → 决策改变 → 行程改变 → Trace」四段断言（用户 §十）。
2. 反事实必须先验证**去掉输入结果确实不同**（V2 §22 纪律）。
3. **新增**：包络类规则必须同时断言"软超支不拒绝"路径（饿肚子不可接受），防止把预算做成绝食。
4. 验证入口统一 `scripts/simulate_planning_v2.py`（扩展 G 组），pytest 层为单测、脚本层为验收。

---

# 12. 明确不做（继承用户禁令，逐条对审计）

| 禁令 | 审计确认 |
|---|---|
| 不引入 LLM 决策 | 全链确定性，保持 |
| 不把 OR-Tools 拉回内核 | 调度 68 行贪心，语义与解释优先 |
| 不重写 POI 系统 | DP-1 只补 trace，分类不动 |
| 不改 wire contract | View/Trace 全进程内；P2-3 文案走既有通道 |
| 不新增大量 DTO | 仅 +1 个 frozen dataclass（ContextView） |
| 不建 God Coordinator | §5 方案 C 被证据否决 |
| 不为架构而架构 | P2-0 是兑现 V2 审计 §15 旧账，非新设计 |
| 不改无关模块 | 四刀全部限定在 planning/ + provider + evaluation 读侧 |
| 先改代码再审计 | 本文档即 Phase A，未改一行代码 |

---

**审计结束。等待人工确认后进入 Phase B（按 P2-0 → P2-1 → P2-2 → P2-3 顺序实施）。**
