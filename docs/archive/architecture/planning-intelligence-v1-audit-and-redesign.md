# TripPilot Planning Intelligence V1
## 全链路信息参与度审计与确定性规划智能化重构方案

> **阶段**：AUDIT + DESIGN ONLY
> **日期**：2026-08-30
> **性质**：代码级、证据驱动审计。所有结论均锚定 `file:line`。

---

## 实施状态（2026-08-30 晚更新）

审计结论已确认后进入实施。以下阶段**已完成并全量回归通过**（pytest 1890 passed /
ruff 干净 / wire 字节兼容）：

| 阶段 | 状态 | 落地要点 |
|---|---|---|
| **P0-3** 解释诚实性 | ✅ | `trusted_context` 天气/门票 effect 改为回溯式；`provider_priced_targets` 由 `cost_source` 驱动 |
| **P1-1** 天气感知步行 | ✅ | `transit_mode.is_walkable(duration, threshold)` 参数化 + 新增 `planning/weather_policy.py`（1200/900/600/300） |
| **P0-1/P0-2** 成本真实性 | ✅ | 新增 `planning/cost_model.py`；`ItineraryActivity.cost_source`（`exclude=True`） |
| **P1-3** 交通冲突裁决 | ✅ | 新增 `planning/budget_policy.py` + `planning/transport_strategy.py`（有序规则，first-match-wins） |
| **P1-2** 预算感知排序 | ✅ | `CandidateRanker` 注入 `cost_hints` / `budget_ceiling`（仅 PROVIDER 成本判罚） |
| **P1-4** 人数贯通 | ✅ | 门票/餐费/公交票价按人数乘；打车过路费按车（不乘） |
| **P1-5** 住宿成本 | ✅ | 300 元/间/夜（CITY_ESTIMATE），挂在"返回住宿"节点（每晚恰好一个） |

**新增文件**：`planning/cost_model.py`、`planning/weather_policy.py`、
`planning/budget_policy.py`、`planning/transport_strategy.py`、
`tests/test_planning_intelligence_v1.py`（20 个测试，含 3 组反事实）、
`scripts/simulate_planning_v1.py`（模拟用户输入驱动测试）。

**范围决策**：P1-4 的"人均乘法"与 P1-5 的"住宿计入预算"是产品口径变更——
住宿常量 300 元/间/夜与餐费默认 50 元/人均为可调整的产品常量，需产品确认。

**模拟结果**（`python scripts/simulate_planning_v1.py`，杭州 3 天 2 人）：

| 反事实 | 决策变化 |
|---|---|
| 晴天 → 雷阵雨 | 交通 `WALKING` → `TRANSIT`（步行阈值 1200s → 600s）；总分 90 不变，预算分 84 → 83 |
| 预算 1500 → 10000 | 交通 `TRANSIT` → `DRIVING`（公交容忍比 1.6 → 1.2）；预算分 BLOCKED → 100 |
| 2 人 → 4 人 | 总成本 2230 → 3860 元；4 人/2500 预算被 `BUDGET_LIMIT` + 评估器拦截 |

后续正文仍按审计时的原始代码状态撰写（保留证据链），实施以本节为准。

---

# 1. Executive Summary

TripPilot 当前是一个 **Information-rich but Decision-poor**（信息丰富但决策贫瘠）的系统。

系统在**信息获取**层面做得相当扎实：12 类可信事实（含门票价、人均消费、天气、临时闭馆）、QWeather/AMap 双源采集、TTL 新鲜度管理、事实冲突降级、来源可信度分级。

但在**决策消费**层面，这些信息的绝大多数从未抵达任何决策点。

### 三个最严重的断层

**① 天气在生产链路中参与度为 Level 0（收集即丢弃）**

不是「影响较弱」，而是**完全没有参与**。`weather_statements_for_date()` 是一个写了但从未被调用的函数——全仓仅 3 处出现：定义（`planning_provider.py:316`）、测试 import、测试断言。排序器唯一的调用点（`planning_provider.py:400`）不传 `weather_statements`，该参数取默认值 `()`。

**② 成本模型失真，且失真被测试固化**

餐费恒定 `Decimal("0")`（即使解析到真实餐厅 POI）；门票统一 `Decimal("100.00")` 不区分免费/收费、不乘人数；住宿恒定 `0`。结果是 `test_planning_worker.py:292` 断言一个 4 天含餐行程总成本为 `0`——**错误的成本模型被写成了预期行为**。

**③ 系统对用户做了不实的解释**

`trusted_context.py` 会向用户输出两条说明，但两条都不成立：
- `"对应日期预计降雨，室内候选提高优先级"` —— 提权从未发生
- `"官方门票价格进入预算估算"` —— 门票价格从未进入成本

这比「缺少功能」更严重：它是**解释层的不实陈述**。

### 一个必须澄清的事实

**OR-Tools 在本项目中零使用。** 它只在 `apps/agent-service/pyproject.toml:12` 声明了依赖，全仓无任何 import。调度是 `daily_schedule.py:847 _fill_slots()` 的**贪心算法**。

因此问题 9「是否需要重写整个 OR-Tools」不成立——**没有 OR-Tools 可重写**。真正的求解层是一个 68 行的贪心填充函数。

---

# 2. Current Planning Architecture（真实代码架构）

```
User → Web → Java Travel Server → Outbox → RabbitMQ
     → Python agent_processor → planner_pipeline
                                      ↓
     ┌────────────────────────────────────────────────────────┐
     │ AmapPlanningProvider.plan()  (planning_provider.py)    │
     │                                                        │
     │  1. POI 搜索            _search / raw_pois             │
     │  2. 信任上下文过滤      hard_closed_fact()             │
     │  3. 候选排序            CandidateRanker.rank()  ← 唯一 │
     │  4. 营业时间投影        _with_opening_availability()   │
     │  5. 逐日规划            plan_day()  (daily_schedule)   │
     │       ├─ 时间窗         day_window_minutes(pace)       │
     │       ├─ 餐食需求       build_meal_demands()           │
     │       └─ 贪心填充       _fill_slots()  ← 真正的求解层  │
     │  6. 逐段路径            _route_for_pair()              │
     │       └─ 模式推荐       decide_transit_or_road()       │
     │  7. 成本汇总            total_cost = Σ slot + Σ leg    │
     └────────────────────────────────────────────────────────┘
                                      ↓
     run_validation() → 硬校验（BUDGET_LIMIT 等）
                                      ↓
     _repair_if_needed() → 有界修复（最多 3 次）
                                      ↓
     resolve_evidence() → planning_fact_impacts() → 解释输出
                                      ↓
     PlanningCompletedEventV11 → SSE → Web
```

**关键观察**：成本在**第 7 步才第一次出现**，而第 7 步是流水线的**末端**。候选选择（3）、排序（3）、调度（5）、交通（6）全部在成本未知的情况下完成。

---

# 3. Input Inventory（输入清单）

## 3.1 Constraint Inventory（约束清单）

来源：`worker/contracts.py` `TripConstraints`、`dialog/extractor.py`、`agent/state.py`

| 约束 | 定义位置 | 采集方式 | 备注 |
|---|---|---|---|
| `budget_amount` | `contracts.py:168` | LLM 抽取 + 正则 | 总预算，非人均 |
| `travelers` | `contracts.py:169` | LLM 抽取 | 1–50 |
| `traveler_type` | Java `TripAgentCreateController.java:106` | 由 travelers 派生 | SOLO/COUPLE/FRIENDS/FAMILY/BUSINESS |
| `pace` | `domain/shared.py` `Pace` | LLM 抽取 | RELAXED/BALANCED/INTENSIVE |
| `preferences` | `contracts.py` | LLM 抽取 | 文本数组 |
| `mobility_level` | `contracts.py` | LLM 抽取 | STANDARD/REDUCED |
| `must_visit_places` / `_refs` | `contracts.py` | LLM + 服务端签名 | 支持结构化 PlaceRef |
| `avoid_places` / `_refs` | `contracts.py` | LLM + 服务端签名 | 同上 |
| `fixed_schedules` | `contracts.py` | LLM 抽取 | 固定预约 |
| `accommodation` | `contracts.py` | 用户指定 + AMap 解析 | 仅地名/坐标 |

## 3.2 Knowledge Inventory（知识清单）

来源：`guide_intelligence/trusted_facts.py:30-58`

| 事实类别 | TTL | 抽取器 | 规划层消费者 |
|---|---|---|---|
| `OPENING_HOURS` | 14d | `_TIME` 正则 | ✅ `daily_schedule` VERIFIED_WINDOW |
| `TEMPORARY_CLOSURE` | 6h | — | ✅ `hard_closed_fact()` 硬过滤 |
| `TICKET_PRICE` | 14d | `_PRICE`（成人门票…N元） | ❌ **无** |
| `REFERENCE_SPEND` | 14d | `_REFERENCE_SPEND`（人均…N元） | ❌ **无** |
| `WEATHER` | 6h | QWeather / AMap | ❌ **无** |
| `VENUE_ENVIRONMENT` | — | — | ❌ 无 |
| `TRANSPORT_ADVICE` | 14d | — | ❌ 无 |
| `RESERVATION_REQUIREMENT` | 7d | 正则 | ⚠️ 仅解释输出 |
| `RESERVATION_ENTRY` | 7d | — | ❌ 无 |
| `ADDRESS` / `COORDINATES` | 90d | 正则 | ✅ 去重/路由 |
| `ATTRACTION_IDENTITY` | — | — | ✅ `poi_quality.same_mapped_place` |

**12 类事实中，仅 4 类进入决策。** `TICKET_PRICE`、`REFERENCE_SPEND`、`WEATHER`、`VENUE_ENVIRONMENT`、`TRANSPORT_ADVICE` 五类**已抽取、已定级、已管理 TTL，然后被丢弃**。

---

# 4. Constraint → Consumer Matrix ⭐

> **判定规则**：❌ = 无消费者；⚠️ = 存在但弱/间接；✅ = 真实改变决策分支、排序、过滤或约束

| Input / Constraint | Source | Candidate Filter | Ranking | Transport | Scheduling | Solver* | Hard Validation | Evaluation | UI |
|---|---|---|---|---|---|---|---|---|---|
| **Budget** | ✅ `contracts.py:168` | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ `core.py:195` 事后 | ✅ `rules.py:111` | ✅ |
| **Weather** | ✅ `qweather.py` | ❌ | ❌ **死参数** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ 解释(不实) |
| **Travelers** | ✅ `contracts.py:169` | ❌ | ⚠️ 仅派生 traveler_type | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Traveler Type** | ✅ Java 派生 | ❌ | ✅ `candidates.py:234` FAMILY +15 | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Pace** | ✅ | ❌ | ❌ | ❌ | ✅ `daily_schedule.py:315,63` | ❌ | ❌ | ❌ | ✅ |
| **Preferences** | ✅ | ❌ | ✅ `candidates.py:193` +40 | ❌ | ❌ | ❌ | ❌ | ✅ `score_interest_match` | ✅ |
| **Mobility** | ✅ | ❌ | ❌ | ✅ `mode_recommendation.py:98` | ⚠️ `daily_schedule.py:874` −30min | ❌ | ❌ | ❌ | ✅ |
| **Must Visit** | ✅ | ✅ `planning_provider.py:413` pinned | ✅ `candidates.py:203` +100 | ❌ | ✅ `daily_schedule.py:860` 优先 | — | ✅ `coverage.py` | ✅ | ✅ |
| **Avoid** | ✅ | ✅ `candidates.py:129` | — | — | — | — | ✅ | — | ✅ |
| **Opening Hours** | ✅ | ✅ `planning_provider.py:497` | ❌ | ❌ | ✅ `daily_schedule.py:881` | — | ✅ | ⚠️ | ✅ |
| **Fixed Schedules** | ✅ | — | — | — | ✅ `build_fixed_items` | — | ✅ | — | ✅ |
| **Accommodation** | ✅ | — | — | — | ⚠️ 仅日始终点 | — | ❌ | ❌ | ✅ |

\* Solver 列中的 `—` 表示该输入本就适合在上游处理，非缺陷。

### 逐项证据说明

**Budget**
- 消费点仅 2 处，且都在规划**完成之后**：
  - `feasibility/context.py:53` → `ratio = cost / budget` → `feasibility/rules/core.py:195 assess_budget_limit`（事后 FAIL）
  - `evaluation/rules.py:111 score_budget_fit`（事后打分）
- **候选生成、排序、调度、交通全部无 budget 参与**
- `daily_schedule.py:205` 定义了 `MealDemand.budget_per_person`，但 `plan_day()` 在 `planning_provider.py:517-534` 被调用时**未传该参数** → 生产路径恒为 `None` → **死参数**

**Weather**
- `weather_statements` 是 `CandidateRanker.rank()` 的形参（`candidates.py:104`），默认 `()`
- 全仓唯一生产调用点 `planning_provider.py:400-420` 传入了 `guide_statements`、`entity_facts`，**未传 `weather_statements`**
- `weather_statements_for_date()` 全仓仅出现于：定义 `planning_provider.py:316`、测试 `test_candidate_ranking.py:10/206/209` → **零生产调用**
- `_non_weather_guide_statements()`（`planning_provider.py:301`）显式**排除** WEATHER 类事实
- 结论：**天气在生产链路中从未参与任何决策**

**Travelers**
- Python 侧仅 `contracts.py:169` 字段定义，planning/evaluation/feasibility/infrastructure 中**零引用**
- Java 侧 `TripAgentCreateController.java:106`：`travelers == 1 ? "SOLO" : travelers == 2 ? "COUPLE" : "FRIENDS"` → 被压缩为 3 值枚举后丢弃
- 成本计算**从不乘人数**

---

# 5. Knowledge → Decision Matrix ⭐

| Knowledge | Acquisition | Consumer | Decision Impact | Current Problem |
|---|---|---|---|---|
| **Weather** | ✅ QWeather/AMap 双源，`qweather.py` | ❌ 无 | **零** | 采集→丢弃；解释层声称已使用 |
| **TICKET_PRICE** | ✅ 正则抽取 + 14d TTL | ❌ 无 | **零** | 真实票价被 `100.00` 常数覆盖 |
| **REFERENCE_SPEND** | ✅ 人均消费正则 | ❌ 无 | **零** | 餐费因此恒为 0 |
| **OPENING_HOURS** | ✅ | ✅ `daily_schedule:881` | **强** | 健康，可作范式 |
| **TEMPORARY_CLOSURE** | ✅ | ✅ `hard_closed_fact` | **强** | 健康 |
| **POI Attributes** | ✅ AMap | ⚠️ 仅去重 `poi_quality.py` | 弱 | 无 `price` 字段（`providers/map.py:114`） |
| **Guide Statements** | ✅ | ✅ `candidates.py:217` +25 | 中 | 仅文本包含匹配 |
| **Route Data** | ✅ AMap 实时 | ✅ `_route_for_pair` | 强 | 但成本不参与模式选择 |
| **User Preferences** | ✅ | ✅ `candidates.py:193` +40 | 中 | 未进入调度 |
| **VENUE_ENVIRONMENT** | ✅ | ❌ 无 | 零 | 室内/外判断靠 POI 名称硬编码词表 |
| **TRANSPORT_ADVICE** | ✅ | ❌ 无 | 零 | 完全未消费 |

### Information Exists ≠ Information Changes Decision

| 知识 | 信息存在 | 改变决策 |
|---|---|---|
| 天气（雷阵雨） | ✅ | ❌ |
| 门票价（成人 80 元） | ✅ | ❌ |
| 人均消费（120 元） | ✅ | ❌ |
| 营业时间（09:00–17:00） | ✅ | ✅ |

---

# 6. Input Participation Level Matrix

| Level | 定义 |
|---|---|
| **L0** Collected Only | 采集并存储，无任何消费者 |
| **L1** Post-hoc Evaluation | 仅参与事后校验或打分 |
| **L2** Decision Influence | 影响排序、过滤、策略 |
| **L3** Optimization Constraint | 进入求解约束 |

| Input | Level | 判定依据 |
|---|---|---|
| Must Visit | **L3** | pinned 过滤 + `must_include` 调度优先 + coverage 硬校验 |
| Opening Hours (VERIFIED) | **L3** | `VERIFIED_WINDOW` 约束最早合法放置 `daily_schedule:917` |
| Temporary Closure | **L3** | 硬过滤 `planning_provider:497` |
| Preferences | **L2** | 排序 +40，但不进调度 |
| Pace | **L2** | 时间窗 + 缓冲，`daily_schedule:63,315` |
| Mobility | **L2** | 交通负担收紧 + 日容量 −30min |
| Traveler Type | **L2** | FAMILY +15（仅 FAMILY，其余 4 值无效） |
| Route Data | **L2** | 真实时长驱动前向拟合 |
| **Budget** | **L1** | 仅事后 FAIL + 事后打分 |
| **Travelers** | **L0** | 仅压缩为 traveler_type 后丢弃 |
| **Weather** | **L0** | **生产链路零消费者** |
| **TICKET_PRICE** | **L0** | 知识层有，规划层零引用 |
| **REFERENCE_SPEND** | **L0** | 同上 |
| **Accommodation (cost)** | **L0** | 纯地理锚点 |

---

# 7. Information → Decision Gap（断层清单）

### GAP-1 · Weather：Acquisition → Planning 完全断裂 【P0】

```
QWeather API → PlanningContextFact(WEATHER)
             → PlanningContextSnapshot
             → ✂️ 断裂
             → （从未到达 CandidateRanker / _route_for_pair / plan_day）
             → ✂️ 断裂
             → planning_fact_impacts() 声称 "INDOOR_POI_UPRANKED"
```

**证据**：`weather_statements_for_date` 零生产调用；`planning_provider:301` 主动排除 WEATHER。

### GAP-2 · Budget：Post-hoc Constraint 【P0】

```
budget_amount → build_budget_context() → assess_budget_limit()  ✅ 事后
              → score_budget_fit()                              ✅ 事后
              → 候选选择 ✂️ / 排序 ✂️ / 调度 ✂️ / 交通 ✂️
```

**性质**：`Validation ≠ Planning`。预算只在方案生成后才被检查，超预算只能触发有界修复（删活动），而无法在生成阶段主动选择更便宜的方案。

### GAP-3 · Cost Data：Knowledge → Cost Model 断裂 【P0】

```
TICKET_PRICE（真实票价，正则抽取，14d TTL）  ✂️
REFERENCE_SPEND（人均消费，正则抽取）        ✂️
AMap poi.business.cost                       ✂️
        ↓ 全部丢弃
AMAP_ACTIVITY_ESTIMATED_COST = 100.00  ← 固定常数
MEAL cost                    = 0.00    ← 固定零
```

### GAP-4 · Travelers：Collection → Decision 断裂 【P1】

```
travelers(1–50) → SOLO / COUPLE / FRIENDS → 仅 FAMILY 触发 +15
                → ✂️ 成本计算从不乘人数
```

4 人出行与 1 人出行成本完全相同；4 人打车 vs 公共交通的经济性差异从未被比较。

### GAP-5 · Preference：Ranking → Scheduling 断裂 【P2】

偏好在排序中 +40，但 `_fill_slots()` 的排序键是 `(must_include, region!=primary, -score, title, poi_id)` —— score 间接受偏好影响，属**弱传导**，在候选密集时易被 region 项淹没。

### GAP-6 · Meal：Selection → Cost 断裂 【P0】

`planning_provider.py:1054-1064`：即使成功解析到真实餐厅 POI（含 AMap `business.cost`），传入 `cost` 仍是 `Decimal("0")`。

### GAP-7 · Accommodation：Anchor → Cost 断裂 【P1】

住宿仅作为日起终点地理锚点（`accommodation_projection.py`），无 nightly cost，不受预算影响。多日行程中住宿通常是最大开销，当前完全不计入。

---

# 8. Cost Model Audit（成本模型审计）

| 类别 | 真实值 | 代码位置 | 数据来源 | 是否×人数 | 问题 |
|---|---|---|---|---|---|
| **Meal** | `Decimal("0")` 恒定 | `planning_provider.py:1061, 1072` | 无 | — | 解析到真实餐厅也为 0 |
| **Attraction** | `Decimal("100.00")` 恒定 | `planning_provider.py:1087`←`domain/shared.py:38` | 无 | ❌ | 不区分免费/收费 |
| **Accommodation** | `Decimal("0")` 恒定 | `planning_provider.py:1086, 1108, 1121` | 无 | — | 完全不计 |
| **Transport** | 真实票价/过路费 | `planning_provider.py:1613-1634` | AMap | ⚠️ 票价本身已含单人语义，未复核 | 唯一真实成本 |
| **Walking** | `0` | `planning_provider.py:1616` | — | — | 合理 |

### 数据模型支撑度

| 能力 | 现状 |
|---|---|
| Activity `cost_source` | ❌ **缺失**（`contracts.py:623` 只有 `estimated_cost`） |
| TransitLeg `cost_source` | ✅ 存在 `PROVIDER/RULE_ESTIMATE/DEMO/UNKNOWN`（`contracts.py:673`） |
| Meal 人均预算字段 | ✅ 有 `MealDemand.budget_per_person`（`daily_schedule.py:205`）但**死参数** |
| `Poi.price` 字段 | ❌ **缺失**（`providers/map.py:114`） |
| 成本分类 breakdown | ❌ 缺失，仅一个 `estimated_total_cost` 总数 |

### 一个关键设计锚点

`TransitLeg.cost_source` 的 `PROVIDER / RULE_ESTIMATE / DEMO / UNKNOWN` 枚举**已经存在且被契约采纳**。V1 不需要发明 Cost Confidence 概念，**只需把同一套语义从 TransitLeg 推广到 Activity 与 Meal**。这是低风险改造路径。

---

# 9. Budget Intelligence Audit

### 当前参与层级：**Level 1（Post-hoc Evaluation）**

预算只做两件事，都在方案生成**之后**：

1. **事后校验** `feasibility/rules/core.py:195`
   ```python
   ratio = ctx.budget.budget_ratio
   ...
   message = f"estimated cost exceeds budget by {round((ratio - 1) * 100)}%"
   ```
2. **事后打分** `evaluation/rules.py:111`
   ```python
   if ctx.budget_ratio <= 0.70:  return 100
   if ctx.budget_ratio <= 0.85:  return round(100 - (ratio-0.70)/0.15*10)
   if ctx.budget_ratio <= 1.0:   return round(90  - (ratio-0.85)/0.15*20)
   return 0
   ```

### 打分实际效果测算

杭州 3 天 2 人，预算 2500 元：
- 门票：6 个景点 × 100.00 = **600**
- 餐费：**0**
- 住宿：**0**
- 交通：约 **100**（真实票价）
- 合计 ≈ **700** → ratio ≈ **0.28** → `budget_fit = 100`（满分）

**结论**：在成本模型修复前，`budget_fit` 几乎恒为 100，是一个**恒定 15 分的死维度**。它不区分 2500 元和 25000 元预算的行程。

### 关键断裂

预算**从不**参与：候选过滤（极端高价候选不被排除）、候选排序（预算紧张时高成本候选不降权）、交通决策（`mode_recommendation.py:15` 明写 `"Cost is intentionally NOT compared"`）、每日活动数量。

---

# 10. Weather Intelligence Audit

### 当前参与层级：**Level 0（Collected Only）**

**证据链（三重验证）**：

1. `weather_statements_for_date()` 定义于 `planning_provider.py:316`，全仓搜索仅 3 处命中：定义 + 测试 import + 测试断言 → **零生产调用**
2. `self._candidate_ranker.rank(` 全仓仅 1 处调用（`planning_provider.py:400`），参数列表见 `:400-420`，**不含 `weather_statements`**
3. `_non_weather_guide_statements()`（`planning_provider.py:301`）显式过滤 `fact.category != "WEATHER"`

### 天气数据实际去了哪里

| 去向 | 是否发生 |
|---|---|
| 候选排序提权/降权 | ❌ 从未 |
| 交通方式选择 | ❌ 从未 |
| 步行阈值调整 | ❌ 从未（`transit_mode.py:72` 硬编码 1200s） |
| 日程密度调整 | ❌ 从未 |
| 风险提示 | ❌ 仅 Java 侧可用性门控 `PlanningContextSnapshotService.java:112` |
| **解释文案** | ✅ 会输出（但不实） |

### 解释层的不实陈述

`planning/trusted_context.py:82-103`：
```python
if fact.category == "WEATHER" and _contains_rain(fact):
    effect = "INDOOR_POI_UPRANKED" if indoor else "OUTDOOR_POI_DOWNRANKED"
    reason = "对应日期预计降雨，室内候选提高优先级" if indoor
             else "对应日期预计降雨，露天候选降低优先级"
```

该 impact 会经 `worker/processor.py:647` → `fact_impacts` → 事件契约 → 前端展示。
**但提权从未发生**——生产排序器收到的 `weather_statements` 恒为 `()`。

这是**用户可见的不实陈述**，优先级高于「功能缺失」。

---

# 11. Other Context Audit

### 11.1 Travelers（人数）

| 应参与 | 现状 |
|---|---|
| 成本乘法 | ❌ |
| 餐厅选择（包间/大桌） | ❌ |
| 住宿房型 | ❌ |
| 交通经济性（4 人打车 vs 公交） | ❌ |
| 容量约束 | ❌ |

`travelers` 在 Python planning 侧**零引用**。Java 侧压缩为 `traveler_type` 三值后丢弃。

### 11.2 Pace（节奏）— 唯一健康的上下文

| 影响面 | 实现 | 位置 |
|---|---|---|
| 日时间窗 | INTENSIVE → 20:00（其余 18:00） | `daily_schedule.py:315` |
| 活动间缓冲 | RELAXED 20 / BALANCED 12 / INTENSIVE 8 分钟 | `daily_schedule.py:63` |
| 缓冲强制执行 | `_assemble_items` 位移非固定项 | `daily_schedule.py:1005` |

**判定**：Level 2，真实参与。**但缺 RELAXED 的日活动数上限**——RELAXED 只通过缓冲间接减少容量，未被显式约束。

### 11.3 Preferences（偏好）

- 排序：`candidates.py:193` 每个命中偏好 **+40**（基础分 20）
- 调度：仅经 `-c.score` 弱传导
- 性质判定：**Ranking Signal**，非硬约束也非求解约束
- 问题：命中判断为 `preference in f"{name} {type_name} {address}"` 的**子串包含匹配**，与 `is_must_visit_poi` 已修正的精确身份匹配不一致

### 11.4 Mobility（行动能力）

| 影响面 | 实现 | 强度 |
|---|---|---|
| 交通负担收紧 | 换乘上限 2→1，步行上限 ×0.5 | ✅ 有效 |
| 日容量 | 每 slot `capacity - 30` 分钟 | ⚠️ 极弱 |
| 步行阈值 | ❌ 不调整 | — |
| 主动选择无障碍 | ❌ | — |

`mode_recommendation.py:17-18` 明写：`"mobility accessibility only tightens the walking/transfer burdens — it never means 'prefer taxi'"`——设计为**只收紧不主动优化**。

---

# 12. Evaluation Trust Audit

权重：`scoring.py:22-27`
`constraint_satisfaction 30 | time_feasibility 25 | budget_fit 15 | route_efficiency 15 | interest_match 15`

| 维度 | 输入数据 | 数据真实性 | 决策价值 | Trust |
|---|---|---|---|---|
| `constraint_satisfaction` (30) | must-visit/avoid/fixed 覆盖 | ✅ 真实 | 高 | **HIGH** |
| `time_feasibility` (25) | 真实 AMap 路径时长 | ✅ 真实 | 高 | **HIGH** |
| `budget_fit` (15) | 失真的成本模型 | ❌ **失真** | 无（近恒定 100） | **LOW** |
| `route_efficiency` (15) | 真实路径时长 | ✅ 真实 | 中 | **MEDIUM** |
| `interest_match` (15) | POI type_code 前缀匹配 | ⚠️ 粗粒度 | 中 | **MEDIUM** |

### Trust 结论

- **可信**：`constraint_satisfaction` + `time_feasibility`（合计 **55%** 权重，输入真实）
- **不可信**：`budget_fit`（**15%** 权重，输入失真 → 恒定满分）
- **解释价值 > 评分价值**：`fact_impacts` 中两条不实陈述需优先修复

**总体**：综合分中 55% 可信、15% 无效、30% 部分可信。**综合分本身不宜跨方案绝对值比较**，可用于同目的地相对比较。

---

# 13. Root Cause Analysis（为什么会形成当前架构）

1. **成本是事后追加的**。成本汇总在 `planning_provider.py:1208`——流水线末端。架构先有调度后有成本，成本从未回流到决策。

2. **知识层与规划层由不同阶段建设**。知识层（12 类事实、冲突降级、TTL）明显更成熟，但它是**旁路**——`planning_fact_impacts()` 只做解释，不做决策。两者从未打通。

3. **解释层抢跑于决策层**。`trusted_context.py` 按**设计意图**写文案（`INDOOR_POI_UPRANKED`、`OFFICIAL_TICKET_BUDGET_APPLIED`），而非按**实际发生的决策**回溯生成。决策没接上时，文案照样输出。

4. **测试只锁接口不锁行为**。`weather_statements_for_date` 有测试、`score_budget_fit` 有测试，但测试的是**函数被调用时的行为**，而非**生产链路是否调用它**。缺口在于没有反事实测试。

5. **`travelers` 被过早降维**。Java 侧在入口就把它压成 3 值枚举，Python 侧因此拿不到原始数字。

6. **OR-Tools 引入了但从未落地**。`pyproject.toml` 声明依赖而代码未用，导致「求解层」这个位置在架构上是空的，实际由 68 行贪心函数承担，且**没有约束求解能力**（因此预算天然无法作为优化约束）。

---

# 14. Planning Intelligence V1 Target Architecture

```
User Constraints + Environment Context + External Knowledge
                        ↓
        ┌───────────────────────────────┐
        │   PlanningContext (新增)       │  ← 一次性归一化，全链路共享
        │  budget / weather / mobility  │
        │  / pace / party / preference  │
        └───────────────────────────────┘
                        ↓
        ┌───────────────────────────────┐
        │   Context → Strategy 解析      │  ← 确定性规则，非 LLM，非 Solver
        │  • WalkingPolicy               │
        │  • TransportPolicy             │
        │  • BudgetPolicy                │
        │  • LoadPolicy                  │
        └───────────────────────────────┘
                        ↓
    Candidate Filtering  ← 成本上界过滤、闭馆过滤
                        ↓
    Candidate Ranking    ← 偏好 + 天气 + 成本适配 + 攻略
                        ↓
    Scheduling (贪心)    ← pace / capacity / opening
                        ↓
    Transport Decided     ← 真实路由 + 上下文策略
                        ↓
    Cost Aggregation      ← 真实单价 × 人数，带 cost_source
                        ↓
    Hard Validation       ← 最后防线
                        ↓
    Evaluation            ← 输入可信后才计分
                        ↓
    Explanation           ← 回溯真实发生的决策（而非设计意图）
```

### 分层原则

| 层 | 适合承载 | 不适合承载 |
|---|---|---|
| PlanningContext | 归一化、冲突消解 | 业务规则 |
| Strategy | 上下文 → 参数（步行阈值、预算档位） | 排序、求解 |
| Filtering | 硬约束（闭馆、极端超预算） | 软偏好 |
| Ranking | 多信号加权 | 硬约束 |
| Scheduling | 时间/容量/顺序 | 成本优化（贪心无回溯） |
| Validation | 最后防线 | 唯⼀消费者 |

---

# 15. Planning Context Layer（是否新增）

### 建议：**YES，但保持最小**

不新增重型对象。建议一个 `@dataclass(frozen=True, slots=True)` 的 `PlanningContext`，从**现有** `TripConstraints` + `PlanningContextSnapshot` 派生，不引入新持久化、不改契约。

```python
@dataclass(frozen=True, slots=True)
class PlanningContext:
    # 预算
    budget_total: Decimal | None
    budget_per_person_per_day: Decimal | None   # = budget / travelers / days
    budget_pressure: Literal["TIGHT","NORMAL","RELAXED"] | None

    # 天气（按日）
    weather_by_date: Mapping[date, WeatherLevel]   # CLEAR/DRIZZLE/RAIN/STORM

    # 行动与节奏
    mobility_reduced: bool
    pace: Pace

    # 人数
    travelers: int

    # 派生策略（由 Strategy 层填充）
    walking_threshold_seconds: int
    max_activities_per_day: int | None
    cost_ceiling_per_activity: Decimal | None
```

### 为什么需要

当前上下文参数**散落在调用签名里逐层手工传递**，这正是 `weather_statements` 被漏传的根因——漏传不报错，因为形参有默认值。`PlanningContext` 把「必须被消费的上下文」变成**一个必填参数**，漏传即 `TypeError`。

### 为什么保持最小

- 不新增数据库表
- 不改事件契约
- 不引入新 provider
- 纯内存对象，生命周期 = 单次规划

---

# 16. Budget-aware Planning Design

## 16.1 成本数据来源优先级

```
1. PROVIDER_TICKET    知识层 TICKET_PRICE 事实（已抽取，14d TTL）
2. PROVIDER_SPEND     知识层 REFERENCE_SPEND（人均消费）
3. PROVIDER_BUSINESS  AMap poi.business.cost
4. CATEGORY_ESTIMATE  按 POI type_code 分类估算（博物馆/公园/商圈…）
5. CITY_ESTIMATE      城市级人均估算
6. UNKNOWN            未知 → 不参与比较，计入 confidence
```

## 16.2 Cost Source 推广

复用 `TransitLeg.cost_source` 既有枚举（`contracts.py:673`），推广到 Activity 与 Meal：

```python
cost_source: Literal["PROVIDER", "RULE_ESTIMATE", "CATEGORY_ESTIMATE", "CITY_ESTIMATE", "UNKNOWN"]
```

**契约影响**：`ItineraryActivity` 需新增可选字段。建议 `default="RULE_ESTIMATE", exclude=True`（参照 `meal_type` 在 `contracts.py:637` 的既有做法——`exclude=True` 保证 wire 兼容，Java 侧不解析未知属性）。

## 16.3 成本分类

建议在 `Itinerary` 增加 breakdown（可选、exclude）：
```python
cost_breakdown: {
    "attraction": Decimal, "meal": Decimal,
    "transport": Decimal, "accommodation": Decimal
}
```
总额 `estimated_total_cost` **保持不变**，breakdown 为附加信息。

## 16.4 预算的分层消费者

| 层 | 行为 | 说明 |
|---|---|---|
| **Filtering** | 单价 > `cost_ceiling` 的候选排除 | 仅当 cost_source ∈ {PROVIDER_*}，UNKNOWN 不过滤 |
| **Ranking** | `budget_pressure == TIGHT` 时高成本候选降权 | 软信号 |
| **Transport** | TIGHT 倾向 TRANSIT；RELAXED 允许 DRIVING | 见 §18 |
| **Scheduling** | 不参与 | 贪心无成本优化能力 |
| **Validation** | `total <= budget` | 保留为最后防线 |
| **Evaluation** | 成本修复后恢复可信 | 依赖 P0 完成 |

## 16.5 人数乘法

```
attraction_cost = unit_price × travelers
meal_cost       = per_person_spend × travelers
transport_cost  = 票价已按人 / 打车按车（不乘）
accommodation   = nightly_rate × nights ÷ travelers?（见 §22 待定）
```

---

# 17. Weather-aware Mobility Design

## 17.1 V1 最低要求

```
Weather（按日）→ MobilityContext → WalkingPolicy → Transport Decision
```

| WeatherLevel | 步行阈值 | 说明 |
|---|---|---|
| CLEAR | 1200s（现状） | 不变 |
| CLOUDY | 1200s | 不变 |
| DRIZZLE | 900s | −25% |
| RAIN | 600s | −50% |
| STORM | 300s | −75%，且室外候选强降权 |

改造点：`transit_mode.py:72 is_walkable()` 从
```python
def is_walkable(duration: int) -> bool:
    return duration <= WALKING_THRESHOLD_SECONDS
```
改为接收阈值参数（`WALKING_THRESHOLD_SECONDS` 保留为默认档位，保证向后兼容）。

**这是本次改动面最小、收益最明确的单点。**

⚠️ **调用点有 2 处，需同步改造**：
- `infrastructure/amap/planning_provider.py:1729`（规划主链路）
- `routes/service.py:66`（独立路径服务）

⚠️ **阻塞测试**：`tests/test_transit_mode.py:153-155` 硬编码断言
```python
assert WALKING_THRESHOLD_SECONDS == 1200  # product rule
assert is_walkable(1200) is True
assert is_walkable(1201) is False
```
参数化后 `is_walkable(1200)` 在 RAIN 档位（600s）将返回 `False`，该测试需改为按档位参数化。

## 17.2 分层设计

| 阶段 | 范围 |
|---|---|
| **V1** | 步行阈值 + 室内外排序权重（**修复已有断裂**） |
| **V2** | 日容量调整（雨天 −1 活动）、室外连排惩罚 |
| **V3** | 室内外节奏编排（雨天优先室内时段） |

## 17.3 明确不做

不做 `Rain → Taxi` 的硬编码映射。见 §18。

---

# 18. Context Conflict Resolution（确定性冲突消解）

## 18.1 原则

**不使用 LLM。不把所有上下文塞进 Solver。**

采用 **Strategy 层 + 优先级裁决**：上下文先在 Strategy 层**解析为参数**，参数再进入各决策点。冲突在参数生成时一次性裁决，不在每个决策点重复判断。

## 18.2 Transport Strategy 裁决表

输入：`(weather_level, budget_pressure, mobility_reduced, straight_distance)`

| # | 条件 | 结果 | 优先级理由 |
|---|---|---|---|
| 1 | `mobility_reduced AND weather ∈ {RAIN, STORM}` | 步行阈值 = min，允许 DRIVING | 安全 > 成本 |
| 2 | `weather == STORM` | 步行阈值 = min，倾向 DRIVING | 安全 |
| 3 | `budget_pressure == TIGHT` | 步行阈值 = 正常，TRANSIT 优先于 DRIVING | 成本约束 |
| 4 | `budget_pressure == TIGHT AND weather == RAIN` | 步行阈值 = 降低，仍 TRANSIT 优先 | **成本 > 舒适度**（可配置） |
| 5 | `budget_pressure == RELAXED AND weather ∈ {RAIN, STORM}` | 允许 DRIVING | 舒适度 |
| 6 | 默认 | 现状行为（步行优先，TRANSIT vs DRIVING 按有序规则） | 保持 B19-C 语义 |

**冲突关键点（规则 4）**：预算紧 + 下雨 → **不加价打车**，而是降低步行阈值、优先 TRANSIT。理由：预算是硬约束，天气是舒适度软约束。此条应为**可配置项**，而非硬编码。

## 18.3 裁决实现形态

纯函数，无 I/O，可单测：

```python
def resolve_transport_strategy(
    *, weather: WeatherLevel, budget_pressure: BudgetPressure,
    mobility_reduced: bool,
) -> TransportStrategy:
    """Ordered rules — first match wins. Pure, no I/O, no LLM."""
```

**关键**：有序规则（first-match-wins），与 `decide_transit_or_road()` 现有风格一致，便于反事实测试。

---

# 19. P0 / P1 / P2 Roadmap

## P0 — Data Truth（数据真实性）

### P0-1 · 修复餐费恒为 0

- **Problem**：`planning_provider.py:1061/1072` 餐费硬编码 `Decimal("0")`，即使解析到真实餐厅；`test_planning_worker.py:292` 将总成本 0 固化为预期
- **Scope**：`planning_provider.py` `_emit_day()`；`providers/map.py` Poi 增加可选价格字段
- **Files**：`infrastructure/amap/planning_provider.py`、`providers/map.py`、`worker/contracts.py`
- **Architecture Impact**：低（局部）
- **Data Impact**：`ItineraryActivity` 增 `cost_source`（`exclude=True`）
- **Risk**：⚠️ **必须同步修改 `test_planning_worker.py:292`**，否则 gate 失败
- **Test**：解析到含 `business.cost` 的餐厅 → `estimated_cost > 0`
- **Acceptance**：`杭州3天2人` 行程餐费 > 0；`estimated_total_cost` 不为 0

### P0-2 · 修复门票成本失真

- **Problem**：统一 `100.00`，不区分免费/收费，不乘人数
- **Scope**：优先消费知识层已有 `TICKET_PRICE` 事实，缺失时回落分类估算
- **Files**：新增 `planning/cost_model.py`；`planning_provider.py:1087` 改为调用
- **Architecture Impact**：中（新增成本模型模块）
- **Data Impact**：同上 `cost_source`
- **Risk**：票价事实覆盖率可能低 → 必须有 `UNKNOWN` 回落路径，且 **UNKNOWN 不得计为 0**
- **Test**：西湖（免费）→ cost 0 & source=PROVIDER；某收费景区 → cost = 票价 × travelers
- **Acceptance**：同一行程 1 人 vs 4 人，`estimated_total_cost` 显著不同

### P0-3 · 修复解释层不实陈述

- **Problem**：`trusted_context.py:90-100`（天气提权）、`:144-155`（门票进预算）两条文案描述未发生的决策
- **Scope**：改为**回溯式**——只输出真实发生的 effect
- **Files**：`planning/trusted_context.py`、`worker/processor.py:635`
- **Architecture Impact**：低
- **Risk**：下游前端可能依赖这些 effect 值 → 需确认
- **Test**：未启用天气消费时，不产出 `INDOOR_POI_UPRANKED`
- **Acceptance**：`fact_impacts` 中每条 effect 均可回溯到一次真实决策分支

### P0-4 · 删除死参数 / 接通天气

- **Problem**：`weather_statements` 从未传入；`budget_per_person` 从未传入
- **Scope**：随 §15 `PlanningContext` 一并修复，改为必填上下文对象
- **Files**：`infrastructure/amap/planning_provider.py:400, 517`
- **Risk**：中（排序结果会变化 → Golden 矩阵可能需重校准）
- **Test**：见 §21 反事实测试
- **Acceptance**：雨天 vs 晴天，候选排序或交通方式产生可观测差异

---

## P1 — Decision Participation

### P1-1 · Weather-aware Walking Policy
- `transit_mode.py:72` 参数化步行阈值；`_route_for_pair` 接收该参数
- Acceptance：`RAIN` 下 900s 的步行段不再选 WALKING

### P1-2 · Budget-aware Ranking
- `budget_pressure == TIGHT` 时高成本候选降权
- 前置依赖：**P0-2 完成**（否则成本数据不可信）

### P1-3 · Transport Strategy（§18）
- 新增 `resolve_transport_strategy()`；`mode_recommendation` 接收预算压力
- 注意：`mode_recommendation.py:15` 现有 `"Cost is intentionally NOT compared"` 决策需重新评估——**TRANSIT 票价 vs DRIVING 过路费**语义不同是事实，但「预算压力」作为**用户约束**应参与，二者不矛盾

### P1-4 · Travelers 贯通
- 契约保留 `travelers` 原值至 Python 侧；成本乘人数；4 人时评估打车经济性
- 注意：Java 侧 `traveler_type` 派生逻辑保留（UI 用），但不再作为唯一载体

### P1-5 · Accommodation Nightly Cost
- 多日行程计入住宿成本（分类估算起步）
- **需产品决策**：住宿是否计入 `budget_amount`？影响验收基线

---

## P2 — Optimization Intelligence

### P2-1 · 带回溯的调度改进
- 当前 `_fill_slots()` 无回溯；预算超限时只能删除末尾活动
- 可选：局部搜索 / 引入 CP-SAT（**届时 OR-Tools 依赖才真正启用**）

### P2-2 · 动态预算分配
- 按日分配预算，允许某日超支、他日节省

### P2-3 · Evaluation 升级
- 成本修复后重校准 `budget_fit` 阈值
- 增加 `cost_confidence` 维度（基于 `cost_source` 分布）

---

# 20. File-level Impact Analysis

| File | 当前职责 | 未来变更 | Risk |
|---|---|---|---|
| `planning/candidates.py` | 候选过滤 + 偏好排序 | 增加成本信号、天气信号（**参数已在**） | 中（需重校准排序） |
| `planning/daily_schedule.py` | 贪心日调度 | 接收 `PlanningContext`；RELXED 活动上限 | 中 |
| `planning/transit_mode.py` | 步行阈值硬编码 | `is_walkable(duration, threshold)` 参数化 | **低**（改 1 函数） |
| `routes/service.py` | 独立路径服务 | 同步传入阈值（`:66` 调用点） | 低 |
| `planning/mode_recommendation.py` | TRANSIT vs DRIVING 有序规则 | 增加 `budget_pressure` 输入 | 中 |
| `planning/trusted_context.py` | 事实 → 决策解释 | 改为回溯式，删除不实 effect | 中（前端依赖） |
| `planning/cost_model.py`（新增） | — | 成本解析 + 来源分级 + 人数乘法 | 低（新增） |
| `planning/planning_context.py`（新增） | — | 上下文归一化 + 策略解析 | 低（新增） |
| `infrastructure/amap/planning_provider.py` | 主规划流水线 | 接入 `PlanningContext`；成本改调 cost_model | **高**（1168 行核心） |
| `providers/map.py` | POI 模型 | `Poi` 增加可选价格字段 | 低 |
| `worker/contracts.py` | 事件契约 | `ItineraryActivity.cost_source`（`exclude=True`） | 低（wire 兼容） |
| `evaluation/rules.py` | 评分规则 | 成本修复后重校准 `budget_fit` | 中 |
| `domain/shared.py` | 常量 | `AMAP_ACTIVITY_ESTIMATED_COST` 降级为兜底 | 低 |
| `tests/test_planning_worker.py` | — | **必须修改 `:292`**（断言总成本 0） | 🔴 **gate 阻塞** |
| `tests/test_transit_mode.py` | — | **必须修改 `:153-155`**（硬编码阈值 1200） | 🔴 **gate 阻塞** |
| `tests/test_candidate_ranking.py` | 天气排序 | `:182` 手工注入 weather_statements；接通后应改为走生产路径 | 中 |
| `tests/test_golden_matrix.py` / `test_golden_scenarios.py` | Golden 基线 | 天气+成本接入后需重校准 | 中（预期失败，勿提前校准） |

---

# 21. Event / Contract Impact

### NO CHANGE（本阶段及 P0/P1 均不变）

- `PlanningCreateCommand` / `PlanningReplanCommand` 顶层结构
- `PlanningCompletedEventV11` 事件类型与版本
- `estimated_total_cost` 字段语义与位置
- `Itinerary` / `ItineraryDay` / `ItineraryActivity` 现有字段
- `TripConstraints` 全部字段（`travelers`、`budget_amount` 已存在）
- RabbitMQ exchange / routing key / outbox 机制
- Java 侧 `TripRequests`、`TripMapper`、`TripService`

### FUTURE CHANGE（需评估，非本阶段）

| 项 | 触发阶段 | 建议方式 |
|---|---|---|
| `ItineraryActivity.cost_source` | P0-1 | 新增 `exclude=True` 可选字段（仿 `meal_type`） |
| `Itinerary.cost_breakdown` | P0-2 | 同上 |
| Travelers 原值透传 | P1-4 | **无需改契约**，Java 已写入 `constraints.travelers`，仅 Python 侧未读 |

**结论**：**本次改造可在零契约破坏前提下完成。** 所有新增信息走 `exclude=True` 可选字段，Java 侧不解析未知属性，wire 保持字节兼容。

---

# 22. Database Impact

| 项 | 是否需要 | 说明 |
|---|---|---|
| Migration | **否** | P0/P1 全部为计算层改造 |
| 新表 | **否** | — |
| 新列 | **否**（P0/P1） | `cost_source` 仅存在于事件负载，不落库 |
| P2 待定 | 可能 | 若需持久化 `cost_breakdown` 供 UI 展示，则需新列 |

**待产品确认**：住宿成本是否计入 `budget_amount`。若计入，需确认现有 trip 的历史数据口径（是否回溯重算）。

---

# 23. Test Strategy

## 23.1 现状缺口（审计发现）

| 反事实测试 | 现状 | 证据 |
|---|---|---|
| 晴天 vs 雨天 → 行程不同 | ❌ 不存在 | 仅 `test_candidate_ranking.py:172` 手工注入 `weather_statements`，走生产不走的分支 |
| 预算 2000 vs 10000 → 行程不同 | ❌ 不存在 | 仅 `test_plan_evaluation_rules.py:19` 测打分函数 |
| RELAXED vs INTENSIVE → 活动数不同 | ⚠️ 单臂 | `test_daily_schedule.py:90` 仅测 INTENSIVE 时间窗 |
| travelers 1 vs 4 → 成本不同 | ❌ 不存在 | 且 `test_planning_worker.py:292` 反向断言成本 0 |
| REDUCED vs NORMAL → 行程不同 | ✅ **存在** | `test_mode_recommendation.py:596, 611` —— **真反事实，可作范式** |

**唯一健康的反事实测试**在 `test_mode_recommendation.py:611`：
> 同一 OD，normal → TRANSIT，reduced → DRIVING。
> 这正是 V1 其余维度应达到的标准。

## 23.2 测试金字塔设计

**Unit**
- `resolve_transport_strategy()` 全组合真值表
- `is_walkable(duration, threshold)` 各档位
- `cost_model` 各 `cost_source` 优先级回落链
- `PlanningContext` 派生正确性（`budget_per_person_per_day` 计算）

**Counterfactual（新增重点）**
```
test_weather_counterfactual:
    同一 command，注入 CLEAR vs RAIN
    assert 选中候选集合 or 排序 or 交通方式 不同

test_budget_counterfactual:
    budget 2000 vs 10000
    assert 高成本候选排序下降 or 交通方式不同

test_travelers_counterfactual:
    travelers 1 vs 4
    assert estimated_total_cost 显著不同

test_pace_counterfactual:
    RELAXED vs INTENSIVE
    assert 每日活动数 or 窗口 不同
```

**Regression**
- Golden 矩阵（`test_golden_matrix.py`、`test_golden_scenarios.py`）需重校准
- ⚠️ **预期会失败**：天气接入 + 成本修复必然改变排序与总额

**Integration**
- `AmapPlanningProvider.plan()` 端到端 + `run_validation()`，断言 `BUDGET_LIMIT` 在极端预算下正确触发

**E2E / Real Planning**
- 真实 AMap provider 冒烟（`test_real_amap_provider.py` 已有基础）
- 断言成本 > 0、cost_source 分布合理

## 23.3 关键前置：两个 gate 阻塞测试

改造开始前，**必须先确认并修改**以下两个测试——它们把当前缺陷固化成了预期行为：

| 测试 | 行 | 当前断言 | 阻塞 |
|---|---|---|---|
| `tests/test_planning_worker.py` | `:292` | 4 天 DEMO 行程 `estimated_total_cost == 0` | 阻塞 **P0-1 / P0-2** |
| `tests/test_transit_mode.py` | `:153-155` | `WALKING_THRESHOLD_SECONDS == 1200`、`is_walkable(1200) is True` | 阻塞 **P1-1** |

**含义**：这两个测试不是「写错了」，它们准确反映了当前行为。但它们使「修复」看起来像「破坏」——任何让成本 > 0 或让阈值可变的改动都会先撞上它们。

**建议**：在 P0 开始前，先以独立 commit 将这两个测试改为**参数化/条件断言**，并明确注释「此断言此前锁定了缺陷行为」。

---

# 24. Acceptance Criteria（可验证）

### ❌ 反例（不可验收）
- "预算更智能"
- "天气影响规划"
- "成本更准确"

### ✅ 正例（可验证）

**AC-1 天气**
> 同一目的地、日期、偏好、`travelers=2`、`budget=5000`，仅将第 2 日天气事实从 `晴` 改为 `暴雨`：该日候选排序中室外类 POI（名称命中 `_OUTDOOR_TERMS`）的相对位次下降，或该日出现步行段改为非步行交通。

**AC-2 预算**
> 同一行程，`budget_amount` 从 10000 降为 2000：`budget_pressure` 变为 TIGHT，且（a）单价超过 `cost_ceiling` 且 source=PROVIDER 的候选被排除，或（b）交通策略中 TRANSIT 相对 DRIVING 被优先；最终 `estimated_total_cost <= budget`。

**AC-3 人数**
> `travelers=1` 与 `travelers=4` 的同一行程，`estimated_total_cost` 比值 > 2.0（门票+餐费按人计，交通按次计）。

**AC-4 成本真实性**
> 行程 `estimated_total_cost > 0`；餐费 > 0；`cost_source` 字段在各活动上取值 ∈ 枚举且不恒为同一值。

**AC-5 解释诚实性**
> 对任意规划结果，`fact_impacts` 中每一条 `effect` 均可回溯到本次规划中真实命中的一次决策分支；当天气未参与时，不产出 `INDOOR_POI_UPRANKED` / `OUTDOOR_POI_DOWNRANKED`。

**AC-6 契约兼容**
> Java 侧消费 `PlanningCompletedEventV11` 无解析异常；wire body 与改造前字节兼容（`cost_source` 等新字段 `exclude=True`）。

---

# 25. Recommended Implementation Order

## 第一刀（严格说第 0 刀）：`P0-3` 修复解释层不实陈述

**理由**：系统当前对**真实用户**输出两条不成立的说明（天气提权、门票进预算）。这是唯一一个「已经在对用户说错话」的缺陷，修复成本最低，且完全不依赖成本模型。

## 第二刀：`transit_mode.py` 步行阈值参数化

**理由**：
1. **改动面小**——核心单函数；但需同步 2 个调用点（`planning_provider.py:1729`、`routes/service.py:66`）
2. **收益最直接**——直接消除一个 Context Ignoring Product Rule
3. **不触碰成本模型**——不受 `test_planning_worker.py:292` 阻塞
4. **可立即写反事实测试**——`is_walkable(900, CLEAR) != is_walkable(900, RAIN)`

⚠️ 需同步修改 `tests/test_transit_mode.py:153-155`（硬编码阈值断言）

## 建议顺序

```
1. P0-3  修复解释层不实陈述        ← 最优先：用户可见的不实输出
         （低风险，无需等成本修复）

2. P0-1  餐费成本                  ← 需同步改 test_planning_worker.py:292
3. P0-2  门票成本 + cost_model.py
4. P0-4  PlanningContext 接通天气  ← 依赖 15 的对象设计

5. P1-1  Weather-aware Walking     ← 可独立于 P0 先行（第一刀）
6. P1-3  Transport Strategy
7. P1-2  Budget-aware Ranking      ← 依赖 P0-2 完成
8. P1-4  Travelers 贯通
9. P1-5  Accommodation 成本        ← 待产品决策

10. P2 视收益再评估（含是否真正启用 CP-SAT）
```

## 明确不建议

- ❌ **不先改评分**。`budget_fit` 的失真是**输入失真**导致，改评分函数只会让错误数据看起来更合理。-fix inputs first。
- ❌ **不引入 OR-Tools 求解**。当前贪心 + 有界修复能覆盖 V1 目标；引入 CP-SAT 的复杂度远超收益，且 P2-1 之前无必要。
- ❌ **不新增 Multi-Agent / ReAct / MCP**。本次改造全部是确定性规则。
- ❌ **不做大规模 Golden 重校准**直到 P0 全部完成——否则会校准两遍。

---

# 附录 A：核心证据速查

| 结论 | 证据 |
|---|---|
| OR-Tools 零使用 | `pyproject.toml:12` 声明；全仓无 import；调度 = `daily_schedule.py:847 _fill_slots` |
| 天气零参与 | `weather_statements_for_date` 定义 `:316`，零生产调用；`rank()` 唯一调用点 `:400` 不传该参 |
| 餐费恒 0 | `planning_provider.py:1061`（已解析餐厅）、`:1072`（未解析） |
| 门票恒定 100 | `domain/shared.py:38`；`planning_provider.py:1087` |
| 住宿成本 0 | `planning_provider.py:1086, 1108, 1121`；`accommodation_projection.py` 纯地理 |
| 人数零消费 | Python 侧仅 `contracts.py:169` 定义；Java `TripAgentCreateController.java:106` 压缩为枚举 |
| 预算仅事后 | `feasibility/rules/core.py:195`；`evaluation/rules.py:111` |
| `budget_per_person` 死参数 | `daily_schedule.py:205` 定义；`planning_provider.py:517-534` 调用未传 |
| 交通不考虑成本 | `mode_recommendation.py:15` `"Cost is intentionally NOT compared"` |
| 步行阈值硬编码 | `transit_mode.py:30` `WALKING_THRESHOLD_SECONDS = 1200`；`:72` 无上下文参数；2 个调用点 `planning_provider.py:1729`、`routes/service.py:66` |
| 步行阈值被测试锁定 | `tests/test_transit_mode.py:153-155` 硬编码 `== 1200`、`is_walkable(1200) is True` |
| 解释层不实 | `trusted_context.py:90-100`（天气）、`:144-155`（门票） |
| 成本 0 被测试固化 | `tests/test_planning_worker.py:292` |
| 唯一健康反事实测试 | `tests/test_mode_recommendation.py:611` |
| 知识层有价格但丢弃 | `trusted_facts.py:113` `_PRICE`；`travel_entities.py:76` `ticket_price` |
| `cost_source` 模式已存在 | `contracts.py:673` TransitLeg |

---

# 附录 B：审计方法说明

本次审计遵循以下纪律：

1. **不因变量存在而认定参与**。每个输入都追踪至「是否影响分支/排序/过滤/约束/输出」。
2. **区分生产路径与测试路径**。`weather_statements` 在测试中被传入并产生效果，但生产从未传入——此类「测试证明存在、生产实际不存在」的断层是本次审计的重点发现。
3. **对关键结论做双盲验证**。天气结论经三轮独立搜索确认（函数引用、rank 调用点、参数默认值）。
4. **区分「设计意图」与「实际行为」**。解释层按设计意图输出，实际行为未实现——这是最难被发现的一类缺陷。

---

**审计结束。未修改任何代码。等待人工审核。**
