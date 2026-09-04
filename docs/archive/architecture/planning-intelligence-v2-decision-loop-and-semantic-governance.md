# TripPilot Planning Intelligence 2.0
## 决策闭环审计、POI 语义治理与规划智能增强方案

> **阶段**：AUDIT + DESIGN ONLY
> **日期**：2026-08-30
> **性质**：代码级、证据驱动审计。所有结论锚定 `file:line` 或可复现实证。本次未修改任何代码、测试、契约或数据库。
>
> **实施状态（2026-08-31 更新）**：P0-A + P0-B、P0-C、P1-A 三刀已实施并分四个 commit 落版本历史（git 仓库重建后基线 `9d0f131`，三刀 `845699c` / `54298f0` / `8a504e6`）。全量 1933 passed / 42 skipped；Golden 矩阵与场景全绿、无需重校准。两处设计修正：① §24 的"只做 P0-A 会餐厅消失"机制不成立——`_resolve_meal_poi` 是独立搜索、不消费景点池，原子性的真实理由是治理一致性而非事故风险；② SI-8 锚点校验失败走 `TRAVEL_ANCHOR_UNAVAILABLE` 硬失败（"保持 UNRESOLVED"状态在现有代码中不存在）。P0-C 落地时 subject_type 复用既有 `TRANSIT` 字面量而非新增 `TRANSIT_LEG`。P2 与 L5（pinned 绕过）、"美食"召回关键词仍按本文推迟。详见 `.workbuddy/memory/2026-08-31.md`。

---

# 1. Executive Summary

V1 让系统**开始做上下文驱动的决策**。V2 审计要回答的是另一件事：**这些决策是否形成闭环，以及喂给决策的领域对象语义是否正确。**

审计结论是：系统在两端同时存在断裂。

### 断裂一：语义入口是 fail-open 的

`poi_quality.classify_poi_role()` 只为「风景名胜(11)」「游乐场(0805)」和交通基础设施写了规则。**餐饮、住宿、购物一律落到最后的 `return "KEEP"`。**

实测（`classify_poi_role` + `activity_candidate_eligible` 直调）：

| type_code | 名称 | 角色 | 可进景点候选池 | 时长档 |
|---|---|---|---|---|
| 110000 | 西湖 | KEEP | ✅ | 180min |
| 140000 | 浙江省博物馆 | KEEP | ✅ | 180min |
| **050000** | **楼外楼（餐饮）** | **KEEP** | **✅ ← 泄漏** | **180min** |
| **100000** | **杭州君悦酒店** | **KEEP** | **✅ ← 泄漏** | **180min** |
| **120000** | **如家酒店** | **KEEP** | **✅ ← 泄漏** | **180min** |
| **060000** | **万象城（购物）** | **KEEP** | **✅ ← 泄漏** | **180min** |
| 150200 | 杭州东站 | ANCHOR_ONLY | ✅ 正确 | — |
| 150500 | 龙翔桥地铁站 | FILTER | ✅ 正确 | — |
| 150700 | 断桥公交站 | FILTER | ✅ 正确 | — |

值得注意的是：**最难的交通基础设施分类是正确的**（13 个前缀 + 名称兜底），唯独非交通类全部 fail-open。餐厅被排进景点池后还会拿到 **180 分钟**的游览时长——错误是复合的。

### 断裂二：决策闭环在 Trace 环节断开

V1 让天气真实改变了交通方式、让预算真实改变了候选分值。但系统**说不出为什么**：

实测（杭州 3 天、下雨、预算 2500，走完整管道 + 真实 `PlanEvaluator`）产出的 4 条 `DecisionExplanation`：

```
[PLAN] 「杭州 真实地点行程」基于约束求解生成      codes=('TIME_OPTIMIZATION',) evidence=['provider']
[DAY]  第 1 天安排了 5 个活动                   codes=('REGIONAL_GROUPING',)  evidence=[]
[DAY]  第 2 天安排了 6 个活动                   codes=('REGIONAL_GROUPING',)  evidence=[]
[DAY]  第 3 天安排了 5 个活动                   codes=('REGIONAL_GROUPING',)  evidence=[]
```

没有一条提到天气或预算。而 `ReasonCode` 枚举里**已经定义了** `TRANSIT_MODE` 和 `BUDGET_CONSTRAINT`——实测这两个码（以及 `NEARBY_CLUSTER`）**全仓 0 处发出**。追踪的词汇表存在，但没有接线。

### 断裂三：两个高频用户输入没有真实影响力

- **Pace = RELAXED 与 BALANCED 在日负载上完全无法区分**（实测见 §5）
- **Preference 改变分值但不改变选择**（实测见 §5）——现有测试甚至无法证明它有效

用户说「想轻松一点」和「喜欢历史文化」，前者几乎无效果，后者效果依赖竞争信号。

---

# 2. Current Planning Intelligence Status（V1 已完成什么）

| 阶段 | 能力 | 状态 |
|---|---|---|
| P0-3 | 解释诚实性：`cost_source == PROVIDER` 才能宣称票价进入预算 | ✅ |
| P1-1 | 天气 → 步行阈值 → 交通方式 | ✅ 有反事实测试 |
| P0-1/P0-2 | 成本真实性 + `cost_source` 溯源 | ✅ |
| P1-2 | 预算压力 → 候选降权（仅 PROVIDER 成本） | ✅ 有反事实测试 |
| P1-3 | Budget × Weather × Mobility → 交通策略（有序规则） | ✅ 有反事实测试 |
| P1-4 | 人数 → 成本（门票/餐/公交按人，过路费按车） | ✅ 有反事实测试 |
| P1-5 | 住宿按夜计费并计入预算 | ✅ |

**关键前提（必须澄清）**：架构图中的 OR-Tools 位置在真实代码中**仍然是空的**。`pyproject.toml:12` 声明了依赖，全仓零 import，调度是 `planning/daily_schedule.py:847 _fill_slots()` 的贪心算法。V2 的任何"优化约束"设计都必须以此为基线。

---

# 3. Decision Loop Matrix ⭐

> 判定链：`Input → Context → Consumer → Decision → Plan Output → Validation → Evaluation → Trace`
> 任何一环为 ❌ 即未形成闭环。

| Input | Context | Consumer | Decision Type | Plan Output Impact | Validation | Evaluation | Trace |
|---|---|---|---|---|---|---|---|
| **Weather** | `weather_level_for_date` | `transport_strategy` → `_route_for_pair` | 策略参数（阈值+容忍比） | ✅ 交通方式改变 | ❌ 无天气规则 | ❌ 无天气维度 | ✅ `WEATHER_WALKING_POLICY_APPLIED` |
| **Budget** | `budget_pressure_for` | 候选排序 + 交通策略 | 排序信号 + 策略参数 | ✅ 排序位次/交通方式 | ✅ `BUDGET_LIMIT` | ✅ `budget_fit` | ❌ **BUDGET_CONSTRAINT 码从未发出** |
| **Travelers** | `constraints.travelers` | `cost_model` | 成本乘法 | ✅ 总成本变化 | ✅ 间接（经成本） | ✅ 间接 | ❌ |
| **Preference** | `constraints.preferences` | `CandidateRanker._score` | 排序加分 +40 | ⚠️ 见 §5（同分时无效） | ❌ | ✅ `interest_match` | ⚠️ 仅 `PREFERENCE_MATCH:` reason |
| **Pace** | `constraints.pace` | `day_window_minutes` / `BUFFER_BETWEEN_MINUTES` | 窗口 + 缓冲 | ⚠️ **RELAXED≡BALANCED** | ❌ | ❌ | ❌ |
| **Mobility** | `constraints.mobility_level` | `accessible_burdens` + 日容量 −30min | 负担收紧 | ✅ 交通方式（函数级证明） | ❌ | ❌ | ❌ |
| **Must Visit** | `must_visit_provider_ids` | pin + `must_include` | 硬过滤 + 调度优先 | ✅ | ✅ `MUST_VISIT_*` | ✅ | ✅ |
| **Fixed Appointment** | `fixed_schedules` | `build_fixed_items` | 硬时间约束 | ✅ | ✅ | ⚠️ | ✅ `FIXED_APPOINTMENT` |
| **Opening Hours** | `_with_opening_availability` | `_earliest_opening_placement` | 放置约束 | ✅ | ✅ | ⚠️ | ⚠️ `OPENING_HOURS_EVIDENCE_AVAILABLE` |
| **Accommodation** | `_resolve_travel_anchors` | 日起终点 + 成本锚点 | 地理锚点 | ⚠️ 仅首尾节点 | ❌ | ❌ | ❌ |
| **Route Data** | `_route_for_pair` | 前向拟合 + 模式选择 | 时间约束 + 模式 | ✅ | ✅ | ✅ `route_efficiency` | ❌ |
| **Guide Knowledge** | `_non_weather_guide_statements` | 排序 +25 | 排序加分 | ⚠️ 弱（可被 tie-break 吞没） | ❌ | ❌ | ✅ `PlanningFactImpact` |
| **Travelers → 语义** | — | — | — | ❌ **无**（餐厅选择不看人数） | — | — | — |

### 闭环完整性统计

| 完整度 | 输入 |
|---|---|
| **完整闭环（Level 4）** | Weather（唯一） |
| **决策+变化+反事实，缺 Trace** | Budget、Travelers |
| **决策+变化，缺反事实证明** | Preference、Mobility、Opening Hours、Route Data |
| **变化极弱/等价** | Pace（RELAXED≡BALANCED） |
| **仅锚点，无决策** | Accommodation |
| **完全未消费** | PlanningContext 的 `city` / `travel_start_date` / `travel_end_date` / `stale` / `sources` / `excluded_facts` |

---

# 4. Input Participation Level 2.0

| Level | 定义 | 输入 |
|---|---|---|
| **L0** COLLECTED_ONLY | 采集并存储，零消费者 | `city`、`travel_start/end_date`、`stale`、`sources`、`excluded_facts`、**BREAKFAST（模型中不存在）** |
| **L1** POST_HOC | 仅事后校验/评分 | `stale`（快照级）、住宿成本（仅进总额，不进任何决策） |
| **L2** DECISION_INFLUENCE | 影响过滤/排序/策略 | Preference、Pace、Mobility、Guide Knowledge、Route Data、Travelers（成本侧） |
| **L3** OPTIMIZATION_CONSTRAINT | 进入确定性约束 | Must Visit、Fixed Appointment、Opening Hours(VERIFIED) |
| **L4** END_TO_END_DECISION_LOOP | 全链：Context→Policy→Decision→PlanChange→Trace→Counterfactual | **Weather（唯一）**；Budget 缺 Trace |

### 应该达到什么级别（目标态判断）

| 输入 | 当前 | 应有 | 差距 |
|---|---|---|---|
| Weather | L4 | L4 | — |
| Budget | L4⁻（缺 Trace） | L4 | 补 `BUDGET_CONSTRAINT` 决策记录 |
| Travelers | L2 | L3（成本约束）+ L2（餐厅容量） | 人数未影响餐厅/房型选择 |
| Preference | L2 | L3（弱过滤）或保持 L2 但需反事实证明 | 现有测试无法证明 |
| **Pace** | **L2（实际 L1.5）** | **L3（日活动数上限）** | **RELAXED 无效果** |
| Mobility | L2 | L2/L3 | 缺计划级反事实 |
| Accommodation | L1/L2 | L2（地理决策） | 仅名称解析，无位置决策 |
| Opening Hours | L3 | L3 | — |

---

# 5. Counterfactual Test Audit

审计方法：不只查"有没有测试"，而是查**改变输入是否真的改变输出**。以下三条为实测。

### 5.1 已存在真反事实（✅）

| 输入 | 测试 | 证明内容 |
|---|---|---|
| Weather | `tests/test_planning_intelligence_v1.py:237` | 晴天 → WALKING；雷阵雨 → TRANSIT |
| Budget | `:490` | 紧张 → TRANSIT；宽松 → DRIVING |
| Travelers | `:529` | 1 人 vs 4 人 → 总成本显著不同 |
| Mobility（函数级） | `tests/test_mode_recommendation.py:611` | 同 OD：normal → TRANSIT，reduced → DRIVING |

### 5.2 存在测试但**无法证明**决策变化（⚠️）

**Preference** — `tests/test_candidate_ranking.py:39` 单臂断言顺序。实测对照：

```
有偏好 ('博物馆','岭南文化'): [('museum', 75), ('park', 35)]
无偏好 ()                 : [('museum', 35), ('park', 35)]
顺序是否不同: False
```

同一个夹具下，**偏好把分值从 35 抬到 75，但选中顺序完全没变**（无偏好时两者同分，靠名称兜底排序恰好同序）。该测试无法证明偏好有效。

**但这不代表偏好无效**——换一个存在竞争信号的夹具即可证明：

```
无偏好: [('park', 35), ('museum', 35)]
有偏好: [('museum', 75), ('park', 35)]   ← 顺序翻转
```

**结论**：偏好是真实排序信号（L2），但强度有限，且**现有测试选错了夹具**（tie-break 不敏感）。

### 5.3 根本不会变化（❌）—— 本次最重要发现

**Pace** — 实测（`plan_day` 直调，候选充足）：

```
候选 8 个 NORMAL(150min):
  RELAXED   窗口 9:00-18:00  景点 2  餐 2
  BALANCED  窗口 9:00-18:00  景点 2  餐 2
  INTENSIVE 窗口 9:00-20:00  景点 2  餐 2

候选 8 个 LIGHT(90min):
  RELAXED   景点 3
  BALANCED  景点 3
  INTENSIVE 景点 4
```

**RELAXED 与 BALANCED 在所有测试场景下产出完全相同。** 节奏的真实作用只有两条：INTENSIVE 把日终延到 20:00；缓冲分钟数不同（20/12/8）。

即使用户明确说「希望轻松一点」，系统给出的日负载与 BALANCED 毫无区别。V1 审计曾指出"RELAXED 缺日活动数上限"，本次实测确认了这一判断。

### 5.4 完全缺失反事实

| 输入 | 缺失内容 |
|---|---|
| Preference | 计划级（端到端）对照 |
| Pace | 任何对照（且实际无差异） |
| Mobility | 计划级对照（仅函数级存在） |
| Accommodation | 位置/路线影响对照 |
| Meal 语义 | 餐厅选择对照 |

---

# 6. POI Semantic Audit

## 6.1 POI 生命周期（真实代码路径）

```
① 召回    _collect_pois()          planning_provider.py:1719
          keywords = candidate_keywords(preferences, must_visit)
                   = (*must_visit, *preferences, "景点","博物馆","公园","美食")[:6]
                     ↑ 默认关键词永远包含 "美食"
② 过滤    activity_pois = [poi for poi in raw
                            if activity_candidate_eligible(poi)]      :499
③ 旁路    pinned_pois = must_visit refs 对应的 POI                    :491
          ↑ 完全绕过 ② 的语义过滤
④ 合并    candidate_pois = (*activity_pois, *pinned_pois)             :502
⑤ 排序    CandidateRanker.rank(candidate_pois, ...)                   :497
⑥ 构造    _to_candidate() → CandidateActivity(kind=ATTRACTION|EXPERIENCE)  :892
⑦ 调度    plan_day() → _fill_slots()
⑧ 产出    _emit_day() → ItineraryActivity(kind=..., estimated_cost, cost_source)
```

## 6.2 语义泄漏路径（三条）

**路径 A：默认分支 fail-open**
`poi_quality.py:122` —— `return "KEEP"`。餐饮(050000)、住宿(100000/120000)、购物(060000) 全部命中。
讽刺的是 `poi_quality.py:33` 的注释**已经列出**这些类（"06 = 餐饮, 05 = 购物, 12 = 商务住宅"），但从未为它们写规则。

**路径 B：默认召回关键词包含"美食"**
`domain/shared.py:35` `DEFAULT_POI_KEYWORDS = ("景点", "博物馆", "公园", "美食")` —— 即使偏好是"历史/文化"，也会用"美食"召回一批餐厅，它们经路径 A 进入景点池。

**路径 C：pinned 必去 POI 绕过语义过滤**
`planning_provider.py:491-502` —— 用户通过结构化 PlaceRef 指定的必去点，无论语义如何都直接进入景点池。一个被用户钉住的商场会成为"必去景点"。

## 6.3 分类能力评估

| 领域 | 是否正确 | 证据 |
|---|---|---|
| 交通基础设施 | ✅ 正确 | 13 个前缀 + 名称兜底，地铁站/公交站/停车场全部 FILTER |
| 交通枢纽 | ✅ 正确 | 机场/火车站/客运站 ANCHOR_ONLY |
| 风景名胜/游乐场 | ✅ 正确 | 11 / 0805 |
| 博物馆/科教文化 | ⚠️ 碰巧正确 | 140000 落到默认 KEEP，无显式规则 |
| **餐饮** | ❌ 错误 | 050000 → KEEP |
| **住宿** | ❌ 错误 | 100000 / 120000 → KEEP |
| **购物/商场** | ❌ 错误 | 060000 / 060100 → KEEP |

## 6.4 时长语义同样泄漏

`duration_profile_for()`（`poi_quality.py:273`）只认识景点类标记（庙/祠/寺/风景区/迪士尼…），对餐厅与酒店一律返回 **NORMAL = 180 分钟**。

即：餐厅不只是"排进了景点池"，还被当成**游览 3 小时**的景点。

---

# 7. Semantic Leakage（泄漏清单）

| # | 泄漏 | 严重度 | 证据 |
|---|---|---|---|
| L1 | Restaurant → Attraction Candidate | **P0** | 实测 050000 → KEEP → True |
| L2 | Hotel → Attraction Candidate | **P0** | 实测 100000/120000 → KEEP → True |
| L3 | Shopping Mall → Attraction Candidate | **P0** | 实测 060000 → KEEP → True |
| L4 | Restaurant/Hotel 拿到 180min 游览时长 | **P0** | `duration_profile_for` 无餐饮/住宿分支 |
| L5 | Pinned 必去 POI 绕过语义过滤 | P1 | `planning_provider.py:491-502` |
| L6 | 餐饮食义不校验：餐厅解析取 `candidates[0]` | **P0** | `_resolve_meal_poi:1592` 无 role 检查 |
| L7 | BREAKFAST 在模型中不存在 | P1 | `domain/shared.py:31` `MealType = LUNCH \| DINNER` |
| L8 | 住宿锚点仅按名称解析，无语义校验 | P1 | `_resolve_travel_anchors:1676` `text_matches(name)` |
| L9 | `MEAL` 既表示场所类型又表示时段类型 | P2 | `ActivityKind` 六值语义混载 |

---

# 8. Place Domain Model

## 8.1 现状

**不存在 Place 领域对象。** 只有 `Poi`（`providers/map.py:114`）——一个纯 provider DTO：

```python
class Poi:
    provider_id, name, coordinates, type_name, type_code,
    province, city, district, address,
    business_hours_today, business_hours_week
```

语义只通过两处间接表达：
- `type_code` / `type_name`（AMap 原始分类，未归一）
- `classify_poi_role()` 返回的 `KEEP / FILTER / ANCHOR_ONLY`

**问题本质**：`PoiRole` 是**相对某一个消费者（景点管线）**定义的角色，不是**领域本体**的类型。所以无法表达"这是餐厅"——只能表达"它能不能进景点池"。这就是路径 A 与 L6 同时存在的根因：餐厅既没能被景点池排除，也没能被餐饮池识别。

## 8.2 建议的 Minimal Design（不引入类层次）

不建继承体系，只加一个**归一化的语义类型枚举 + 纯函数**：

```python
type PlaceKind = Literal[
    "ATTRACTION",     # 11 风景名胜 / 0805 游乐场 / 14 科教文化(博物馆等)
    "RESTAURANT",     # 05 餐饮服务
    "ACCOMMODATION",  # 10 住宿服务 / 12 商务住宅中的住宿
    "SHOPPING",       # 06 购物服务
    "TRANSIT_HUB",    # 15 中的枢纽（现 ANCHOR_ONLY）
    "TRANSIT_INFRA",  # 15 中的基础设施（现 FILTER）
    "UNKNOWN",        # ← 关键：默认改为 fail-closed
]

def classify_place(poi: Poi) -> PlaceKind: ...
```

三条约束：
1. **`UNKNOWN` 是 fail-closed 值**——未知类型默认不得进入任何业务池，而不是 KEEP。
2. `PoiRole`（KEEP/FILTER/ANCHOR_ONLY）**保留**为既有行为的兼容层，由 `PlaceKind` 派生，既有测试不破。
3. 分类结果可随候选一路携带（先以 `type_code` 现算即可，不必改持久化）。

## 8.3 不建议做的事

- ❌ 不引入 `Place` 抽象基类 + `Attraction/Restaurant/...` 子类继承树（改动面波及 ranking/scheduling/validation/evaluation/contracts 五层）
- ❌ 不新建数据库表或事件字段（语义可由 `type_code` 现算）
- ❌ 不改 `Poi` 契约结构（只加派生函数）

---

# 9. Activity Domain Model

## 9.1 现状：`ItineraryActivity` 职责过载

`worker/contracts.py:618+` 一个模型同时承载：

| 职责 | 字段 |
|---|---|
| 场所是什么 | `type_code` / `type_name` / `provider_poi_id` / `address` |
| 在计划中扮演什么 | `kind`（ATTRACTION/EXPERIENCE/MEAL/ACCOMMODATION/ARRIVAL/DEPARTURE） |
| 时间 | `start_time` / `end_time` / `time_fixed` / `magnitude` |
| 餐食时段 | `meal_type`（进程内，`exclude=True`） |
| 成本与来源 | `estimated_cost` / `cost_source`（V1 新增，进程内） |
| 来源 | `source`（AMAP/DEMO） |

## 9.2 语义混载的具体问题

- `kind = "MEAL"` 既表示"这个活动是吃饭"（时段语义），也隐含"这个 POI 是餐厅"（场所语义）。当餐厅解析失败时，系统生成一个 `kind=MEAL` 但**没有 POI** 的活动（标题"午餐（建议在当前区域自行选择餐馆）"）——此时"场所语义"为空，两种语义已经分家但未在模型中区分。
- `ATTRACTION` 与 `EXPERIENCE` 的区别**只由时长和名称标记决定**（`_to_candidate:905`），与场所类型无关。所以一个被误分类的餐厅，只要名字里带"乐园"就成了 EXPERIENCE。
- `ACCOMMODATION` 同时表示「从酒店出发」与「返回酒店」两个占位节点，真正的"入住/退房"语义并不存在。

## 9.3 建议

不拆模型（成本过高）。改为在**生成侧**强制语义约束，让 `kind` 成为可校验的产出：

- `kind=MEAL` **必须**由 `PlaceKind.RESTAURANT` 的 POI 产生，或显式标记为 `MEAL_PLACEHOLDER`
- `kind=ATTRACTION/EXPERIENCE` **必须**由 `PlaceKind.ATTRACTION` 产生
- `kind=ACCOMMODATION` **必须**由 `PlaceKind.ACCOMMODATION` 产生

这三条可作为语义完整性测试（§17）直接断言。

---

# 10. Place → Activity Mapping

| PlaceKind | 允许的 ActivityKind | 当前是否强制 | 备注 |
|---|---|---|---|
| ATTRACTION | ATTRACTION / EXPERIENCE | ❌ 未强制 | EXPERIENCE 由时长+名称标记决定 |
| RESTAURANT | MEAL | ❌ **未强制**（可变成 ATTRACTION） | **L1 泄漏** |
| ACCOMMODATION | ACCOMMODATION | ❌ **未强制**（可变成 ATTRACTION） | **L2 泄漏** |
| SHOPPING | （当前无对应活动类型） | ❌ | 建议暂不入任何池 |
| TRANSIT_HUB | ARRIVAL / DEPARTURE | ⚠️ 部分 | 由用户锚点驱动，非分类驱动 |
| TRANSIT_INFRA | （不允许） | ✅ 已强制 FILTER | — |
| UNKNOWN | （不允许，fail-closed） | ❌ **当前为 KEEP** | **路径 A** |

示例映射（用户 §10 的场景）：

```
西湖            → PlaceKind.ATTRACTION     → Sightseeing
Restaurant A    → PlaceKind.RESTAURANT     → Dining
Hotel B         → PlaceKind.ACCOMMODATION   → Accommodation(CheckIn/CheckOut)
Hangzhou East   → PlaceKind.TRANSIT_HUB     → Arrival/Departure
```

当前系统只有 `ARRIVAL/DEPARTURE` 这一条是真正按语义走的（且靠用户显式指定，非自动分类）。

---

# 11. Candidate Pipeline Governance

## 11.1 当前：单一候选池

```
_collect_pois（含"美食"关键词）
        ↓
activity_candidate_eligible（fail-open）
        ↓
   ★ 单一 candidate_pois ★
        ↓
CandidateRanker.rank()
        ↓
_to_candidate → ATTRACTION/EXPERIENCE
```

**餐食不在管线内**：`_resolve_meal_poi()`（`planning_provider.py:1561`）在 `_emit_day` 里**按日临时另起一次搜索**，取 `candidates[0]`，不经排序、不经评分、不经成本提示、不经语义校验。

## 11.2 目标：分离的三池（最小改动版）

```
_collect_pois()
        ↓
classify_place(poi)  ← 新增归一化
        ↓
┌───────────────┬────────────────┬──────────────────┐
│ ATTRACTION 池 │ RESTAURANT 池  │ ACCOMMODATION 池 │
│ rank + 成本   │ 餐食解析专用   │ 住宿锚点专用     │
└───────┬───────┴────────┬───────┴──────────────────┘
        ↓                ↓
   Sightseeing       Meal Planning
   Candidates        Candidates
        └────────┬─────────┘
                 ↓
            Scheduling
```

**最小落地方式**（不重构调度器）：
1. 给 `_collect_pois` 的召回结果按 `PlaceKind` 打标；
2. 景点池：`PlaceKind == ATTRACTION`（UNKNOWN 归入"待定"，不入池）；
3. 餐饮池：召回/解析餐食时**只接受** `PlaceKind == RESTAURANT`（保留 region 与偏好过滤，但加语义门槛；解析不到则退化为 placeholder——当前行为不变）；
4. 住宿锚点：解析后校验 `PlaceKind == ACCOMMODATION`，不匹配则保持 UNRESOLVED（现有语义）。

**注意**：第 3 条会改变行为——当前餐食解析可能命中非餐饮 POI。因此退化为 placeholder 的路径必须保留，且需回归验证餐厅召回率是否下降（真实 AMap 环境下"美食"关键词通常会返回餐饮类，风险可控但需实测）。

---

# 12. Meal Planning Audit

## 12.1 餐食到底是什么？

**答案：是"排期后按日补进去的占位符 + 一次临时搜索"，不是规划管线的公民。**

| 环节 | 实现 | 位置 |
|---|---|---|
| 需求生成 | `build_meal_demands()` 预留时段（时间优先） | `daily_schedule.py:416` |
| 餐厅选择 | `_emit_day` 内按日搜索，取首个结果 | `planning_provider.py:1561` |
| 排序 | ❌ 无（不经 `CandidateRanker`） | — |
| 成本 | REFERENCE_SPEND 事实 → PROVIDER；否则 50×人数 | `cost_model.py` |
| 时间占用 | 固定 60 分钟 | `daily_schedule.py:58` |
| 去重 | `excluded_provider_ids`（跨餐不重复） | `:1052` |

## 12.2 关键结论

- ✅ **餐食时间**是规划的一部分（在容量计算阶段就预留，_provider 解析失败也不删除）
- ❌ **餐厅选择**不是规划的一部分（无排序、无评分、无语义校验、无跨日优化）
- ❌ **BREAKFAST 不存在**于模型中（`MealType = LUNCH | DINNER`）
- ❌ **人数不影响餐厅选择**（无容量/包间语义）
- ❌ `budget_per_person` 字段存在于 `MealDemand`（`daily_schedule.py:205`）但生产路径仍为 `None`（V1 已确认的死参数，未接）

## 12.3 语义完整性缺口

`_resolve_meal_poi` 取 `candidates[0]` 时**不校验该 POI 是不是餐厅**。搜索关键词是"美食"，但 AMap 完全可能返回名为"XX美食广场"的购物中心，或"XX美食街"的风景名胜。当前无防线。

---

# 13. Accommodation Audit

## 13.1 参与面

| 应参与 | 现状 | 证据 |
|---|---|---|
| 预算成本 | ✅ 300 元/间/夜，挂在"返回住宿"节点 | `planning_provider.py` P1-5 |
| 日起终点 | ✅ day_count>1 时插入首尾节点 | `:1211` / `:1226` |
| 位置决策 | ❌ **无**——住宿完全由用户指定名称，系统不做选址 | `_resolve_travel_anchors:1633` |
| 每日路线优化 | ❌ 无——不参与 primary_region 计算权重 | `_primary_region` 仅看活动 |
| 入住/退房 | ❌ 无语义——只有"从X出发"/"返回X"占位 | `:1214` / `:1229` |
| 语义校验 | ❌ 无——名称文本匹配即可 | `:1676` |

## 13.2 Participation Level

**Accommodation = Level 1（成本侧）+ Level 2（地理锚点侧）**。

它是一个**被动成本锚点与地理锚点**，不是决策对象。系统从不回答"住哪里更好"——因为住宿从来不是被选择的，只是被解析的。

## 13.3 风险提示

住宿锚点解析用 `text_matches(anchor.place_name, poi.name)`，无语义校验。若用户填写"西湖边酒店"而 AMap 返回"西湖"（风景名胜），住宿锚点会指向景点，进而让每天的首尾节点是景点——当前无防线。

---

# 14. Transport Decision Audit

## 14.1 是 Planning Decision 还是 Provider Result？

**两者都是，且分层清晰**：

| 层 | 内容 | 性质 |
|---|---|---|
| 事实层 | WALKING/TRANSIT/DRIVING 真实时长、距离、票价、换乘数 | Provider 返回（`_route_for_pair`） |
| 策略层 | 步行阈值（天气）、公交容忍比（预算）、换乘/步行负担（体力） | **Planning Decision**（`transport_strategy.py`） |
| 规则层 | 有序规则：步行短路 → TRANSIT vs DRIVING | **Planning Decision**（`mode_recommendation.py`） |

**结论：交通是真正的规划决策**，不是 provider 结果透传。V1 之后这一点是健康的。

## 14.2 上下文如何共同影响（现状）

| 上下文 | 影响路径 | 证据 |
|---|---|---|
| Weather | → `WeatherLevel` → 步行阈值（1200/900/600/300） | `weather_policy.py` |
| Budget | → `BudgetPressure` → 公交容忍比（1.6 宽松 / 1.2 基线 / 1.0 收紧） | `transport_strategy.py` |
| Mobility | → `accessible_burdens`：换乘上限 2→1，步行上限 ×0.5 | `mode_recommendation.py:98` |
| 冲突 | 有序规则 first-match-wins（MOBILITY_SAFETY > WEATHER_SAFETY > BUDGET_CONSTRAINT > COMFORT_ALLOWS_ROAD > DEFAULT） | `transport_strategy.py:73+` |

## 14.3 缺口

- ❌ **决策无 Trace**：选了 TRANSIT 还是 DRIVING，计划里不留原因（`ModeRecommendationReason` 仅用于日志）
- ❌ 交通成本不参与候选排序（只进总额）
- ⚠️ 步行短路是"产品规则优先"（`transit_mode.py` 注释明写 walkability wins），雨天靠阈值收紧来对抗它——这是正确做法，但阈值只对**步行时长**生效，对"是否值得打车"仍无经济性判断

---

# 15. Planning Context Audit

## 15.1 是否 God Object？

**答案：PARTIAL —— DTO 本身不是，但上下文解析已经散落。**

`PlanningContextSnapshot`（`worker/contracts.py:397`）字段与消费者实测：

| 字段 | Python 侧消费者数 | 判定 |
|---|---|---|
| `facts` | 8 | ✅ 核心 |
| `snapshot_id` | 5 | ⚠️ 多为序列化/测试 |
| `conflicts` | 1 | ✅（`trusted_context.conflicted`） |
| `diagnostics` | 1 | ✅（`refresh_failed`） |
| `city` | **0** | ❌ 死字段 |
| `travel_start_date` / `travel_end_date` | **0** | ❌ 死字段 |
| `stale` | **0** | ❌ 死字段（仅契约校验用） |
| `sources` | **0** | ❌ 死字段 |
| `excluded_facts` | **0** | ❌ 死字段 |

11 个字段中 **5 个无消费者**。这是"宽 DTO + 死字段"，不是 God Object（没有行为、没有职责膨胀）。

## 15.2 真正的问题：上下文解析散落且重复计算

V1 刻意**没有**创建 `PlanningContext` 类，而是用模块级函数：

- `weather_level_for_date()` / `walking_threshold_seconds_for_date()`
- `budget_pressure_for()`
- `resolve_transport_strategy_for_date()`
- `_attraction_cost_hints()`
- `planning_context_weather_statements()`

后果：
1. **重复计算**：`budget_pressure_for(command)` 在 `resolve_transport_strategy_for_date()` 内被逐日调用；`resolve_attraction_cost()` 在排序阶段算一次、`_emit_day` 阶段对每个活动再算一次（输入相同）。
2. **无缓存边界**：`_attraction_cost_hints` 在排序时算了全量候选，但 `_emit_day` 不用它，重新算。
3. **无类型约束**：漏传不会报错（这与 V1 审计中"weather_statements 漏传"是同一类风险，只是现在改成了必填的函数调用，风险已降低）。

## 15.3 建议

保持"不引入重量级对象"的 V1 决策，但把散落函数**收敛为一个 `PlanningContextView`**（frozen dataclass，一次性构造、逐日复用），消除重复计算，并让死字段的清理有据可依。

---

# 16. Decision Traceability Audit

## 16.1 现有四种"解释"载体

| 载体 | 能解释什么 | 覆盖范围 |
|---|---|---|
| `PlanningFactImpact` | 某个事实对计划的影响（含 reason） | 仅知识事实，且需 fact 存在 |
| `DecisionExplanation` | 计划/日/活动层决策（含 reason_codes + evidence） | **实际只有样板文案** |
| `EvaluationWarning` | 风险信号（BUDGET_NEAR_LIMIT、TIGHT_TRANSFER…） | 仅风险，不解释选择 |
| Agent Step / Trace | 对话与工具调用 | 规划内部决策不可见 |

## 16.2 实测：V1 决策全部无法解释

杭州 3 天、雷阵雨、预算 2500 的完整管道输出（§1 已列）证明：**天气收紧步行阈值 → 选了 TRANSIT** 这一真实决策，在任何解释载体里都不出现。

`ReasonCode` 使用统计（排除枚举定义本身）：

| 码 | 使用数 |
|---|---|
| FIXED_APPOINTMENT | 2 |
| PROVIDER_CONSTRAINT | 2 |
| MUST_VISIT | 1 |
| SHORTEST_ROUTE | 1 |
| TIME_OPTIMIZATION | 1 |
| REGIONAL_GROUPING | 1 |
| **BUDGET_CONSTRAINT** | **0** |
| **TRANSIT_MODE** | **0** |
| **NEARBY_CLUSTER** | **0** |

**词汇表存在，但没有接线。** 这是"能解释"与"真的解释了"之间的差距。

## 16.3 最小 Trace 设计建议

不新增数据库、不改事件契约。复用现有 `DecisionExplanation`：

```
DecisionExplanation(
    subject_type="TRANSIT_LEG", subject_id=<leg_id>,
    summary="因暴雨步行阈值收紧至 600s，该段 1100s 改为公交",
    reason_codes=("TRANSIT_MODE",),
    reasons=("步行时长超出天气阈值（雨天 600s）",),
    evidence=(EvaluationEvidence(key="weather_level", label="天气等级", value="RAIN"),
              EvaluationEvidence(key="walking_threshold_seconds", label="步行阈值", value="600"),
              EvaluationEvidence(key="walking_duration_seconds", label="步行时长", value="1100")),
)
```

数据已经在手：`TransportStrategy`（含 reason）与 `ModeRecommendationReason` 都是现成的，只是没往下传。**建议在 `PlanningResult` 中增加一个进程内的 `decision_traces` 元组（不进 wire），由 `_emit_day` 逐段填充，评估器转换为 `DecisionExplanation`。**

---

# 17. Semantic Integrity Rules

建议形成可执行的不变式（每条对应一个测试）：

| # | 规则 | 断言方式 |
|---|---|---|
| **SI-1** | `Restaurant MUST NOT enter SightseeingCandidatePool` | 050000 POI 排序后不出现在 `kind=ATTRACTION` 的活动中 |
| **SI-2** | `Accommodation MUST NOT become TouristActivity` | 100000/120000 POI 同理 |
| **SI-3** | `Shopping MUST NOT be ranked as Attraction` | 060000/060100 同理 |
| **SI-4** | `TransitHub MUST NOT be ranked as Attraction` | 150200 保持 ANCHOR_ONLY（已通过，需回归保护） |
| **SI-5** | `Meal Candidate MUST satisfy Restaurant Semantics` | `kind=MEAL` 且带 POI 者，其 `classify_place` 必须为 RESTAURANT |
| **SI-6** | `Unknown PlaceKind MUST NOT default to Activity` | UNKNOWN → 不入景点池（fail-closed） |
| **SI-7** | `Meal duration MUST NOT use attraction profile` | 餐厅活动时长 ≠ 180min |
| **SI-8** | `Accommodation anchor MUST satisfy Accommodation Semantics` | 锚点 POI 的 `classify_place` ∈ {ACCOMMODATION, UNKNOWN} |

---

# 18. Target Architecture

## 18.1 六层结构是否适合本项目？

用户建议的六层（Context → Policies → Domain Pools → Optimization → Validation → Evaluation）**与本项目的真实形态基本吻合**，但需要两处修正：

| 建议层 | 本项目现状 | 修正 |
|---|---|---|
| Layer 1 Context | 散落的模块函数 | 收敛为 `PlanningContextView`（一次性构造） |
| Layer 2 Policies | ✅ 已存在（weather/budget/transport/cost） | 保持，补 Trace 输出 |
| Layer 3 Domain Pools | ❌ 单一池 | **本次 P0**：分离 Attraction / Restaurant / Accommodation |
| Layer 4 Optimization | ❌ 无求解器，贪心 `_fill_slots` | 不引入 OR-Tools；语义修正后贪心已够用 |
| Layer 5 Validation | ✅ 硬校验 + 有界修复 | 保持，可加语义规则 |
| Layer 6 Evaluation | ✅ 五维评分 + 决策解释 | 补 Trace 接线 |

**结论：适合，但 Layer 4 目前是空的——不要为了填满它而引入求解器。** 当前瓶颈在 Layer 3（语义）与 Layer 6（Trace），不在优化。

## 18.2 目标数据流

```
User Constraints + Knowledge Facts
        ↓
PlanningContextView（一次构造，逐日复用）
        ↓
Policies: WeatherPolicy / BudgetPolicy / TransportPolicy / CostPolicy
        ↓                                    ↓
   place = classify_place(poi)         decision_traces（进程内累积）
        ↓
┌──────────────┬───────────────┬─────────────────┐
│ AttractionPool│ RestaurantPool│ AccommodationPool│
└──────┬───────┴───────┬───────┴─────────────────┘
       ↓               ↓
  Sightseeing      Meal Planning
       └───────┬───────┘
               ↓
        Scheduling（贪心）
               ↓
        Validation（硬校验 + 语义规则）
               ↓
        Evaluation（评分 + DecisionExplanation ← decision_traces）
```

---

# 19. Minimal Change Design

**原则：不重写，不新增持久化，不改事件契约。**

## 19.1 三个文件承担 P0

| 文件 | 改动 |
|---|---|
| `planning/poi_quality.py` | 新增 `PlaceKind` + `classify_place()`；`classify_poi_role()` 改为由 `PlaceKind` 派生（保留三值语义，既有测试不破）；`duration_profile_for()` 增加餐饮/住宿分支 |
| `infrastructure/amap/planning_provider.py` | 景点池按 `PlaceKind.ATTRACTION` 过滤；`_resolve_meal_poi` 加 `RESTAURANT` 语义门槛（失败则保持 placeholder）；`_resolve_travel_anchors` 住宿锚点加语义校验（不匹配保持 UNRESOLVED） |
| `tests/test_planning_semantics.py`（新建） | §17 的 8 条不变式 + 反事实回归 |

## 19.2 明确不做

- ❌ 不引入 `Place` 继承体系
- ❌ 不改 `Poi` / `ItineraryActivity` 契约字段
- ❌ 不新增数据库表或 Migration
- ❌ 不引入 OR-Tools
- ❌ 不重写候选排序器（只在入口加语义门槛）

## 19.3 兼容性保护

`classify_poi_role()` 保留，行为变化仅限：餐饮/住宿/购物由 KEEP → 非 KEEP。既有测试若依赖餐厅进景点池，**应当更新**——那正是缺陷行为（需在实施时确认，预计影响面小）。

---

# 20. P0 / P1 / P2 Roadmap

## P0 — Semantic Integrity（语义完整性）⭐ 本次最重要

### P0-A：POI 语义分类 fail-open 治理
- **Problem**：`poi_quality.py:122` 默认 `return "KEEP"`，餐饮/住宿/购物进入景点池，且拿到 180min 游览时长
- **Scope**：新增 `PlaceKind` + `classify_place()`；`classify_poi_role` 派生；`duration_profile_for` 增分支
- **Files**：`planning/poi_quality.py`
- **Risk**：中——改变候选池构成，Golden 矩阵可能需重校准
- **Test**：SI-1/2/3/4/7 + 现有 `test_poi_quality.py` 全绿
- **Acceptance**：14 个 POI 夹具中，050000/100000/120000/060000 四类均不进景点池；交通分类行为不变

### P0-B：候选池语义分离
- **Problem**：餐食不在管线内，`_resolve_meal_poi` 取 `candidates[0]` 无语义校验；住宿锚点无语义校验
- **Scope**：景点池/餐饮池/住宿锚点三处语义门槛
- **Files**：`planning_provider.py`
- **Risk**：中——餐食解析可能更多退化为 placeholder（需实测 AMap 召回率）
- **Test**：SI-5/SI-8 + 餐食回归测试
- **Acceptance**：`kind=MEAL` 且带 POI 者必为 RESTAURANT；住宿锚点不匹配时保持 UNRESOLVED

### P0-C：Decision Trace 接线
- **Problem**：V1 决策（天气→交通、预算→排序）无任何解释；三个 reason code 从未发出
- **Scope**：进程内 `decision_traces` → 评估器转 `DecisionExplanation`
- **Files**：`planning_provider.py`、`evaluation/explanations.py`
- **Risk**：低（进程内，不进 wire）
- **Test**：雨天场景断言出现 `TRANSIT_MODE` 决策记录
- **Acceptance**：交通方式决策与预算降权决策各有对应 `DecisionExplanation` 且 `evidence` 非空

---

## P1 — Decision Loop Completion

### P1-A：Pace 真实生效（本次实测的最大功能缺口）
- **Problem**：RELAXED ≡ BALANCED，用户说"轻松一点"无效
- **Scope**：`BUFFER_BETWEEN_MINUTES` 之外，增加 RELAXED 的日活动数上限/可用时长折扣
- **Files**：`planning/daily_schedule.py`
- **Risk**：中（改变所有 RELAXED 行程的产出）
- **Acceptance**：RELAXED 与 BALANCED 在同等候选下活动数不同

### P1-B：Preference 反事实证明
- **Problem**：现有测试夹具 tie-break 不敏感，无法证明
- **Scope**：新增能翻转顺序的计划级反事实测试（已实测可行）
- **Acceptance**：偏好历史 vs 自然 → 选中候选集合/顺序不同

### P1-C：Mobility 计划级反事实
- **Scope**：现有仅函数级（`test_mode_recommendation.py:611`），补端到端

### P1-D：Accommodation 决策参与
- **Scope**：住宿参与 primary_region 权重 / 提供选址建议（需产品确认）

---

## P2 — Optimization Intelligence

- P2-A：预算感知求解（**仅当**语义与 Trace 完成后，且确有回溯需求时再评估是否引入 CP-SAT）
- P2-B：住宿位置优化
- P2-C：多目标规划

**前置依赖**：P2 必须在 P0 完成后再评估。当前求解层是 68 行贪心，语义错误对其输出的污染远大于缺少优化——先修输入，再谈优化。

---

# 21. File-level Impact Analysis

| File | Current Role | Proposed Change | Risk |
|---|---|---|---|
| `planning/poi_quality.py` | POI 分类/去重/时长画像 | 新增 `PlaceKind` + `classify_place`；默认 fail-closed；时长增餐饮/住宿分支 | **中**（改变候选池构成） |
| `infrastructure/amap/planning_provider.py` | 主规划流水线（1700+ 行） | 景点池语义过滤；餐食/住宿语义门槛；decision_traces 累积 | **高**（核心文件） |
| `planning/candidates.py` | 候选排序 | 可能需接收 `PlaceKind`（或将过滤前移） | 低 |
| `planning/daily_schedule.py` | 贪心调度 | P1-A：RELAXED 日活动数上限 | 中 |
| `evaluation/explanations.py` | 决策解释生成 | 消费 decision_traces，发出 `TRANSIT_MODE`/`BUDGET_CONSTRAINT` | 低 |
| `evaluation/models.py` | 评分/决策模型 | 可能扩展 `SubjectType` 含 TRANSIT_LEG | 低 |
| `domain/shared.py` | 常量与字面量类型 | `DEFAULT_POI_KEYWORDS` 是否移除"美食"；`MealType` 是否加 BREAKFAST | 中 |
| `worker/contracts.py` | 事件契约 | **建议不改**（PlaceKind 现算，不落 wire） | — |
| `tests/test_poi_quality.py` | 分类单测 | 更新/新增 | 低 |
| `tests/test_planning_semantics.py` | — | 新建（SI-1..SI-8） | 低 |
| `tests/test_planning_intelligence_v1.py` | V1 反事实 | 保护性回归（成本/交通/天气） | 低 |

---

# 22. Test Strategy

| 层级 | 内容 |
|---|---|
| **Unit** | `classify_place()` 对 14 类 type_code 的映射表（§6 实测表直接作为夹具）；`duration_profile_for` 餐饮/住宿分支 |
| **Semantic Integrity** | SI-1 ~ SI-8，每条一个测试，失败信息直接指出哪个 POI 泄漏到哪个池 |
| **Counterfactual** | 天气（已有）、预算（已有）、人数（已有）；**新增**：偏好（能翻转的夹具）、节奏（RELAXED vs BALANCED 活动数）、体力（端到端） |
| **Integration** | 完整管道：餐厅 POI 出现在候选集中时，输出行程的 ATTRACTION 列表不含它，且 MEAL 列表只含 RESTAURANT |
| **Regression** | 现有 1890 个测试全绿；交通分类（ANCHOR_ONLY/FILTER）行为必须逐条保护 |
| **E2E / Real** | `scripts/simulate_planning_v1.py` 扩展为语义检查：打印每个活动的 `PlaceKind`，断言无泄漏 |

**关键纪律**：反事实测试必须**断言"变化"而不是"存在"**。§5.2 证明"测试存在但夹具不敏感"会让缺陷长期隐身——新增反事实测试时，必须先验证"去掉该输入后结果确实不同"。

---

# 23. Acceptance Criteria

### ❌ 反例
- "POI 语义更清晰"
- "决策更可解释"

### ✅ 正例

**AC-1（SI-1/2/3）**
> 候选集包含 050000 餐饮、100000/120000 住宿、060000 购物 POI 时，输出行程中 `kind ∈ {ATTRACTION, EXPERIENCE}` 的活动**不包含**上述任何 POI；且交通类（150200/150500/150700）的既有行为不变（ANCHOR_ONLY/FILTER）。

**AC-2（SI-5）**
> 输出行程中所有 `kind == "MEAL"` 且 `provider_poi_id is not None` 的活动，其 POI 的 `classify_place()` 必为 `RESTAURANT`；解析失败的活动保持无 POI 的 placeholder 形态（行为不变）。

**AC-3（SI-7）**
> 餐厅类活动的时长不等于 180 分钟（景点 NORMAL 档），且不等于由 `_FULL_DAY_MARKERS`/`_HALF_DAY_MARKERS` 推导出的任何景点档位。

**AC-4（Trace）**
> 在雨天场景（步行时长 1100s）下，输出中存在 `subject_type == "TRANSIT_LEG"` 的 `DecisionExplanation`，其 `reason_codes` 含 `TRANSIT_MODE`，且 `evidence` 至少包含 `weather_level` 与 `walking_threshold_seconds` 两项。

**AC-5（Pace，P1-A）**
> 同一命令、同一候选集，仅 `pace` 由 `BALANCED` 改为 `RELAXED`，输出行程的**日活动数或总活动数**发生可观测变化（当前为不变）。

**AC-6（回归）**
> `pytest tests` 全量通过（基线 1890 passed），且 wire 契约保持字节兼容（无新增 wire 字段）。

---

# 24. Recommended First Implementation

**只推荐一个第一阶段：P0-A + P0-B 合并为一次原子改动。**

理由：两者必须一起做。只做 P0-A（餐厅不进景点池）而不做 P0-B（餐食按语义解析），会把"餐厅泄漏"变成"餐厅消失"——餐食仍取 `candidates[0]`，只是更容易解析到非餐饮 POI。**分离候选池与给餐食加语义门槛是同一个动作的两半。**

### Files
1. `apps/agent-service/src/trip_agent/planning/poi_quality.py`
   - 新增 `PlaceKind` 类型与 `classify_place(poi)`
   - `classify_poi_role()` 改为由 `PlaceKind` 派生（保留 KEEP/FILTER/ANCHOR_ONLY）
   - `duration_profile_for()` 增加 RESTAURANT / ACCOMMODATION 分支
2. `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py`
   - `_plan_with_skeleton` 景点池：`classify_place(poi) == "ATTRACTION"`
   - `_resolve_meal_poi`：要求 `RESTAURANT`，否则继续下一个候选/关键词，最终退化为 placeholder
   - `_resolve_travel_anchors` 住宿锚点：语义校验，不匹配保持 UNRESOLVED
3. `apps/agent-service/tests/test_planning_semantics.py`（新建）

### Tests
- SI-1/2/3/4/6/7/8 七条不变式（SI-5 在本阶段为"尽力而为"：AMap 召回质量决定命中率，允许 placeholder 退化）
- 回归：现有 `test_poi_quality.py`、`test_candidate_ranking.py`、`test_meal_type_binding.py`、`test_planning_intelligence_v1.py`

### Acceptance Criteria
- AC-1、AC-2（best-effort）、AC-3、AC-6

### 明确推迟
- P0-C（Trace）放第二个改动——它独立性强，不与语义耦合，可单独验证
- P1-A（Pace）放第三——它改变行程产出，需 Golden 重校准，不应与语义改动混在一起
- P2 全部推迟

---

# 附：本次实证命令（可复现）

```bash
# 1) POI 语义分类实测
#    classify_poi_role / activity_candidate_eligible 对 14 类 type_code
#    结果见 §6.1 表格

# 2) 偏好反事实（夹具敏感性）
#    有偏好 [('museum',75),('park',35)] vs 无偏好 [('museum',35),('park',35)] → 顺序相同
#    换竞争夹具：无偏好 [park,museum] vs 有偏好 [museum,park] → 顺序翻转

# 3) 节奏反事实
#    NORMAL 候选：RELAXED/BALANCED/INTENSIVE 均为 2 景点
#    LIGHT  候选：RELAXED=3 BALANCED=3 INTENSIVE=4

# 4) 决策解释实测
#    杭州 3 天/下雨/2500 → 4 条 DecisionExplanation，均无天气/预算
#    reason code 使用统计：BUDGET_CONSTRAINT / TRANSIT_MODE / NEARBY_CLUSTER = 0
```

---

**审计结束。未修改任何代码。等待人工审核。**
