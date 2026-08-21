# B18 — 交通方式选择与 POI 多样性审计报告

- 审计日期：2026-08-18
- 审计范围：只读审计（未修改任何生产代码）
- 分支 / HEAD：`codex/feasibility-foundation` @ `d10e70c`
- 工作区状态：B15/B16/B17 在途修改保持原样，B18 审计与其隔离（未执行任何 git 写操作）
- 复现脚本：`C:\Windows\Temp\opencode\b18_trace.py`（未污染生产源码）

---

## 1. Executive Summary

三个问题均已通过 **代码 + 数据库 + 运行时复现** 三重验证，结论如下。

### Problem 1 — 默认交通方式（驾车）

**根因已确认，位于 Python planner 的路由层**：`AmapPlanningProvider` 在活动间路线查询时**硬编码 `mode="DRIVING"`**（`apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py:1100`，全仓唯一 `RouteRequest(...)` 调用点）。该 mode 原样写入 `TransitLeg.mode` → 消息契约 → Java 持久化 → 前端默认展示。

- **DB 铁证**：`business.transit_leg` 现存 34 条 leg，`mode` 全部为 `DRIVING`（0 条 WALKING / 0 条 TRANSIT / 0 条 TAXI）。
- **同坐标荒谬案例**：真实行程中「正佳广场 → 小林蓝鳄正佳广场」leg 为 **1 米 / 1 秒 / DRIVING**——两个 POI 坐标完全相同（113.327019, 23.132145），却被标记为"驾车"。
- 系统**不存在**交通方式自动选择算法（无 mode score、无 best-route 逻辑）。

### Problem 2 — 驾车 / 打车领域关系

**TAXI 无独立实现，DRIVING 与 TAXI 是"同一路线 + 不同费用/时长参数"**（用户预判中的 B 情形）。

- Python 侧 `RouteMode` 类型只有 `WALKING | DRIVING`（`providers/_route_contracts.py:16`）；AMAP provider 只实现 walking / driving 两个 endpoint（`providers/_amap_route.py:38-39`）。
- 契约 / 前端 / Java 虽然声明了 `TRANSIT` 与 `TAXI` 枚举，但二者仅在**用户编辑 leg 时由 Java 本地估算**（`ItineraryService.estimatedTransitDuration/Cost`，距离不变、polyline 清空），从不查询 provider。
- **用户"自驾"约束不存在**：`TripConstraints` 无 self-drive / transport-preference 字段；前端「出行方式偏好」只含节奏(pace)、行动能力(mobility)、兴趣标签(preferences)。

### Problem 3 — 必去"正佳广场"导致规划围绕正佳广场

**根因是多层叠加，问题第一次出现在 Candidate Recall（召回层），并在 Ranking 与 Scheduling 层被放大。**

- **真实行程铁证**（`business.itinerary` trip `ac27972d`，约束 `["正佳广场"]`，ref `B00140TFHO`）：9 个行程活动中有 **5 个位于正佳广场建筑内**（坐标 113.326~113.327 / 23.132，providerPoiId 各不相同）：正佳广场、小林蓝鳄正佳广场、广州天河正佳广场销服一体店（D1）+ 广州正佳广场万豪酒店、广正烧(正佳广场店)（D2）。
- **复现证据**（模拟 AMAP 关键词返回，结构与真实 DB 观察一致）：
  - Stage 2 Recall：第一关键词即"正佳广场"（`candidate_keywords` 把 must-visit 放最前），返回 9 个候选中有 **5 个（56%）距正佳广场 ≤0.11km**；候选数达到 `required_count` 后**早停**，"历史/景点/博物馆/公园"关键词从未搜索。
  - Stage 3 Ranking：5 个正佳相关 POI 因名称含"正佳广场"全部命中 `MUST_VISIT_MATCH` 子串加分（+100），与正佳本体**同分 120**；普通广州 POI 仅 20 分。
  - Stage 4/5 Selection：`must_include` 只 pin 精确 id，但 `_fill_slots` 排序 `must_include → region → score` 使 4 个非 must_include 的正佳 sibling 全部优先于普通 POI 被选入同一天；`_primary_region` 对 must_include 加权 3 倍进一步锁定天河区。

---

## 2. Current Architecture（三个问题发生的实际位置）

```
用户约束 (web ConstraintEditor / PlaceAutocomplete 结构化选择, 服务端 token 签名)
  │ must_visit_places=[正佳广场] + must_visit_place_refs=[B00140TFHO, 坐标]
  ▼
[问题3·Recall] Python _collect_pois (planning_provider.py:1504)
  │ candidate_keywords = (must_visit_places + preferences + defaults)[:6]
  │   → "正佳广场" 是第一关键词; len(selected)>=required_count 即早停
  │   → 候选池 56% 为正佳建筑内 POI
  ▼
[问题3·Ranking] CandidateRanker._score (candidates.py:170-215)
  │ MUST_VISIT_MATCH: _text_key(place) in searchable → 名称/地址子串匹配 +100
  │   → 小林蓝鳄正佳广场 / 正佳广场万豪酒店 / 广正烧(正佳广场店) 全部同分 120
  │ pinned_provider_ids 只 pin B00140TFHO (exact id)
  ▼
[问题3·Scheduling] daily_schedule.plan_day / _fill_slots (daily_schedule.py:847-914)
  │ 排序: must_include → region==primary_region → -score → title
  │ _primary_region: must_include 权重 3 → 天河区成为主区域
  │ 无 geo/category/diversity penalty → 4 个正佳 sibling 全部入选同一天
  ▼
[问题1·Routing] _emit_day → RouteRequest(mode="DRIVING") (planning_provider.py:1094-1104)
  │ 硬编码 DRIVING, 契约 RouteMode 仅 WALKING/DRIVING
  │ TransitLeg.mode = "DRIVING", 距离=provider 返回
  ▼
[问题1·持久化] contracts.py:659 (ItineraryTransitMode 4枚举, 实际只出现 DRIVING)
  ▼ Java transit_leg.mode = DRIVING (business schema)
  ▼
[问题1·前端] TripDetail.transitModeFor (TripDetail.vue:304-307) = leg.mode → "驾车"
  [问题2] TransitLegControl.vue 5按钮 (AUTO/WALKING/TRANSIT/DRIVING/TAXI)
      │ 点击 → lib/transit.ts 前端估算 → Java estimatedTransitDuration/Cost 本地估算
      │ TAXI/TRANSIT 无任何 provider 路线; DRIVING↔TAXI 同一距离不同 label
```

---

## 3. Transport Mode Findings

| 问题 | 结论 | 证据 |
| --- | --- | --- |
| planning 实际查询哪些 route mode | **仅 DRIVING**（活动间路线）。`RouteRequest` 全仓唯一调用点硬编码 `mode="DRIVING"` | `planning_provider.py:1100`；`RouteMode = Literal["WALKING","DRIVING"]`（`_route_contracts.py:16`） |
| 默认 DRIVING 在哪一层写入 | **Python planner**（`planning_provider.py:1100`），经 `_leg_from_route`(1303) 写入 `TransitLeg.mode`。不是 AMAP 决策、不是 Java 默认值、不是前端默认值 | 见上；DB 34/34 leg 为 DRIVING |
| 前端点击其它 mode 会发生什么 | 前端 `lib/transit.ts` 按距离估算时长/费用 → 提交 Java → Java `estimatedTransitDuration/Cost` 本地估算覆盖 duration/cost、polyline 置空、provider 置 "DEMO" | `TripDetail.vue:354-362`、`ItineraryService.java:583-626` |
| AUTO 的真实语义 | **纯前端 UI 快捷选择器**。`TransitLegControl.vue` 中 `AUTO` 展开为 `recommendedCommuteMode`（`lib/transit.ts:65-76`：≤20min 选步行 → transit≤taxi×1.6 选 transit → 否则 taxi），点击后**立即落为具体 mode 提交保存**。规划阶段不存在 AUTO，持久化 leg 永远是一个具体枚举 | `TransitLegControl.vue:66-70` |
| 前端"推荐"来源 | 前端本地距离估算（速度常量 1.25/5.5/8.33 m/s），**与 planner 无关** | `lib/transit.ts:13-63` |
| 是否存在 mode selection score | **不存在**。无 score_mode / transport_score / travel_mode_score / best_route / recommended_route 等任何选择算法；不考虑距离/耗时/费用/换乘/用户偏好/天气/时间窗口 | 全仓搜索无命中 |
| replan / repair 的 mode | 复用已有 leg 的 mode（`existing_leg.mode if ... else "WALKING"`），不引入新 DRIVING，但初始 plan 已全部 DRIVING | `application/replan_service.py:273` |

---

## 4. Must-Visit Findings

| 问题 | 结论 | 证据 |
| --- | --- | --- |
| must-visit 如何解析 | 结构化 `must_visit_place_refs`（服务端 token 签名，含 `providerPoiId`/坐标）+ 平行文本 `must_visit_places`；schema v3 校验二者名称一致 | `contracts.py:167-241`；`PlaceRefCanonicalizer.java` |
| 如何绑定 POI | 有 refs 时 `_is_must_visit_poi` 仅按 **exact providerPoiId** 判定（B13_FIX R5，名称回退被禁用）→ `must_include=True`；无 refs 时按**精确规范化名称**匹配 | `planning_provider.py:669-699` |
| 如何进入 candidate pool | (1) 名称作为**第一搜索关键词**召回（`candidate_keywords`）；(2) 未在搜索结果出现的 exact id 由 ref 数据 pin 进候选池；(3) 精确 id 经 `pinned_provider_ids` 绕过 cutoff 强制入选 | `domain/shared.py:218-225`；`planning_provider.py:329-343` |
| 是否存在 satisfied 状态 | **不存在**。没有 unsatisfied/satisfied 集合差逻辑。`must_include` 是候选的固定属性，只控制排序优先级，不随"已进入某天行程"而失效 | `daily_schedule.py:160-176, 847-914` |
| 已满足后是否继续 boost | **是（间接持续）**。`MUST_VISIT_MATCH` 是**子串匹配**（`_text_key(place) in searchable`，searchable = name+type+address），对**所有**名称/地址含"正佳广场"的 POI 永久 +100 且排序置顶，跨天不衰减 | `candidates.py:187-190, 146-153` |
| 名称匹配是否导致扩散 | **确认**。"小林蓝鳄正佳广场"/"广正烧(正佳广场店)"等与正佳同坐标、不同 providerPoiId 的 POI 获得与正佳本体相同的 MUST_VISIT_MATCH boost（复现中 5 个 POI 同为 120 分） | 复现 Stage 3；真实 DB 行程 |
| 唯一被"精确绑定"的 | 只有 `must_include` 标记（exact id）；**排序加分不是** | 见上 |

---

## 5. POI Dedup Findings

| 去重机制 | 是否存在 | 说明与证据 |
| --- | --- | --- |
| 精确 ID（providerPoiId） | ✅ 有 | `DUPLICATE_PROVIDER_ID`（`candidates.py:113-116`）；跨天 canonical key 排除（`planning_provider.py:547-559`） |
| 名称 + 距离（same place） | ⚠️ 部分 | `mapped_places_match`：canonical 名称相同 或 activity 前缀相同 且 ≤0.5km（`domain/shared.py:114-157`）。**正佳广场(购物→food) 与 小林蓝鳄正佳广场(风景→activity) 类别族不同、名称不同 → 不匹配 → 不去重** |
| Geo-near（几十米~200m） | ❌ 无 | 无 minimum-poi-distance / nearby-penalty / cluster / radius 逻辑 |
| Parent / complex | ❌ 无 | 无 parentPoiId / business_area / building / mall 字段；POI 模型只有 name/type/address/district/coordinates（`providers/map.py:113-128`） |
| 名称子串 | ❌ 无 | 名称去重仅 canonical 精确相等；子串不同名的 sibling 视为独立 POI |
| 类别 | ❌ 无 | 无 category dedup |

**关键结论**：正佳广场（B00140TFHO）与 小林蓝鳄正佳广场（B0MDA73DXY）providerPoiId 不同、canonical 名称不同、类别族不同（food vs activity），当前算法**天然把它们视为两个合法 POI**。

---

## 6. Diversity Findings

| 惩罚项 | 是否存在 | 证据 |
| --- | --- | --- |
| same category penalty | ❌ 无 | `_fill_slots` 排序 key 只有 must_include / region / score / title（`daily_schedule.py:856-867`） |
| same area penalty | ❌ 无 | 区域只用于"偏好"（primary_region 优先），无重复区域惩罚 |
| parent complex penalty | ❌ 无 | 无 parent/complex 概念 |
| similarity penalty（名称/语义相似） | ❌ 无 | 无 MMR / novelty / repeat-penalty |
| geo clustering penalty | ❌ 无 | 无距离惩罚；跨天 canonical 排除是唯一"位置"类逻辑 |
| **Objective 分析** | — | 调度目标是**容量填充 + 区域一致性**（`choose_activities` docstring："region-coherent…preferred to reduce cross-region hops"），候选选择无 OR-Tools 目标函数，是确定性贪心（`_fill_slots`）。**数学上不存在 diversity 项**，聚集完全符合当前 objective |

**结论**：当前 objective 偏向交通效率（region 一致性即默认短距离）与分数，**没有对应的 itinerary diversity 维度**。

---

## 7. 正佳广场 Case Trace（真实 + 复现）

### Stage 1 — 原始约束（真实 DB trip ac27972d）

```
must_visit_places = ["正佳广场"]
must_visit_place_refs = [{providerPoiId: "B00140TFHO", name: "正佳广场",
                          address: "天河路228号 体育中心地铁站D3口步行300米",
                          district: "天河区", longitude: 113.327019, latitude: 23.132145}]
```

### Stage 2 — Candidate Recall（复现：关键词搜索顺序 `['正佳广场', '美食']`）

| providerPoiId | 名称 | 距正佳广场 | 来源关键词 |
| --- | --- | --- | --- |
| B00140TFHO | 正佳广场 | 0.000 km | 正佳广场 |
| B0MDA73DXY | 小林蓝鳄正佳广场 | **0.000 km** | 正佳广场 |
| B0IAJKLSO9 | 广州天河正佳广场销服一体店 | 0.008 km | 正佳广场 |
| B00140W2J2 | 广州正佳广场万豪酒店 | 0.110 km | 正佳广场 |
| B0FFJJ8VJ1 | 广正烧(正佳广场店) | 0.008 km | 正佳广场 |
| B0AAA001 | 越秀公园 | 6.369 km | 美食 |
| B0AAA002 | 广州塔 | 2.862 km | 美食 |
| B0AAA003 | 陈家祠 | 8.205 km | 美食 |
| B0AAA004 | 沙面岛 | 9.358 km | 美食 |

**Recall 已 56% 是正佳建筑内/同坐标 POI**；达到 `required_count` 后早停，"历史/景点/博物馆/公园"未搜索。

### Stage 3 — Ranking（score + reasons）

| score | providerPoiId | 名称 | reasons |
| --- | --- | --- | --- |
| 120 | B00140TFHO | 正佳广场 | MUST_VISIT_MATCH |
| 120 | B0MDA73DXY | 小林蓝鳄正佳广场 | MUST_VISIT_MATCH |
| 120 | B0IAJKLSO9 | 广州天河正佳广场销服一体店 | MUST_VISIT_MATCH |
| 120 | B00140W2J2 | 广州正佳广场万豪酒店 | MUST_VISIT_MATCH |
| 120 | B0FFJJ8VJ1 | 广正烧(正佳广场店) | MUST_VISIT_MATCH |
| 20 | B0AAA00x | 广州塔 / 沙面岛 / 越秀公园 / 陈家祠 | 基础分 |

### Stage 4 — 候选转换（must_include 标记）

仅 B00140TFHO 为 `must_include=True`；其余 4 个正佳 sibling `must_include=False` 但 score=120、region=天河区。

### Stage 5 — 最终行程（真实 DB，用户 trip ac27972d 全部 11 个活动）

**D1 (ARRIVAL_DAY)**：到达(火车站) → **正佳广场** → **小林蓝鳄正佳广场** → **广州天河正佳广场销服一体店** → 银记肠粉(沙河顶店) → 返回住宿
**D2 (DEPARTURE_DAY)**：从住宿出发 → **广州正佳广场万豪酒店** → 大鸽饭(体育西店) → **广正烧(正佳广场店)** → 离开(火车站)

**"正佳广场扩散"第一次出现在 Recall（Stage 2）**：must-visit 名称作为第一搜索关键词使候选池本身被正佳 POI 主导；Ranking（Stage 3）用子串 +100 放大；Scheduling（Stage 5）按 region+score 贪心选出，最终 5/9 个 POI 活动聚集在正佳广场内。

---

## 8. Root Cause Classification

| 编号 | 根因 | 所在层 | 证据 |
| --- | --- | --- | --- |
| **P18-R1** | **Route mode selection 缺失**：活动间路线硬编码 `mode="DRIVING"`，RouteMode 类型只有 WALKING/DRIVING，无任何 multi-mode 选择算法 | Routing (Python planner) | `planning_provider.py:1100`；`_route_contracts.py:16`；DB 34/34 DRIVING |
| **P18-R2** | **Must-visit 关键词主导召回**：`candidate_keywords` 把 must-visit 文本放第一，且候选数达标即早停，后续偏好关键词不查询 → 候选池被 must-visit 相关 POI 主导 | Recall | `domain/shared.py:218-225`；`planning_provider.py:1509-1582`；复现 Stage 2（56%） |
| **P18-R3** | **MUST_VISIT_MATCH 子串扩散**：`_text_key(place) in searchable` 使所有名称/地址含"正佳广场"的 sibling POI 获得与本体相同的 +100 与排序置顶 | Ranking | `candidates.py:187-190`；复现 Stage 3（5×120 分） |
| **P18-R4** | **ProviderPoiId-only 去重**：唯一强去重是精确 id；canonical-name 去重对不同名称/类别的同坐标 sibling 无效；无 geo-near / parent / category 去重 | Dedup | `candidates.py:113-116`；`domain/shared.py:114-157`；DB 中 5 个不同 id 同坐标 POI 全入选 |
| **P18-R5** | **无 itinerary diversity objective**：`_fill_slots` 贪心排序只有 must_include/region/score，`_primary_region` 加权 must_include 3 倍；数学上鼓励空间聚集 | Scheduling | `daily_schedule.py:788-803, 847-914` |
| **P18-R6**（次要）| **must_include 无 satisfied 状态**：一旦满足后不衰减，跨天继续以最高优先级与主区域身份影响后续选择 | Scheduling | `daily_schedule.py:152-176` |

---

## 9. Potential Fixes（候选方向，未实施）

| 方向 | 解决什么 | 不解决什么 | 风险 | 预计影响范围 |
| --- | --- | --- | --- | --- |
| **A. MUST_VISIT_MATCH 改为 exact/canonical 匹配**（与 `_is_must_visit_poi` 一致） | P18-R3：消除 sibling 名称扩散；正佳 sibling 回落到基础分 | Recall 仍会带回正佳 POI（P18-R2 保留） | 低；历史 free-text must-visit 依赖子串匹配，需保留规范化名称精确匹配 | candidates.py + 相关测试 |
| **B. Recall 关键词策略调整**：must-visit 关键词仅用于 pin exact id，不以普通关键词召回；或对 must-visit 关键词结果做 sibling 过滤 / 降低配额 | P18-R2：候选池不再被 must-visit 相关 POI 主导 | Ranking 与 Scheduling 的放大（R3/R5）仍需单独处理 | 中；召回质量可能下降，需要新的多样性召回（如分区域采样） | planning_provider._collect_pois、domain/shared.candidate_keywords |
| **C. Geo-near / same-area 上限**（如 300m 内每日最多 1~2 个活动，或同 address 去重） | P18-R4/R5：直接消除"同坐标连续选择" | 不区分合法邻近景点（如两座并排博物馆），可能误伤 | 高误伤风险；需用 category/address 联合判定，且必须保留"合法邻近景点"例外 | daily_schedule._fill_slots、candidates 去重、domain/shared |
| **D. Category/area diversity penalty**（已选类别扣分或 MMR 重排序） | P18-R5：objective 增加多样性维度 | 需要一个明确的 objective 定义（目前是纯贪心） | 中；改变行程形态，需 golden-matrix 回归 | daily_schedule、candidates、测试矩阵 |
| **E. must_include satisfied 状态**（进入行程后从排序/主区域计算中移除） | P18-R6 | 不解决 sibling 被其他 POI 高分选中 | 低 | daily_schedule（_fill_slots/_primary_region 签名） |
| **F. Route mode 选择**：查询 walking/transit/driving（甚至 taxi）候选，按距离/耗时/费用/用户偏好选择；至少 <800m 或同坐标时不选 DRIVING | P18-R1 | 成本模型（费用、换乘）需要产品定义 | 中；新增 provider API 调用（预算内），AMAP transit API 需要凭据与计价模型 | planning_provider._emit_day、_route_contracts、_amap_route、Java 估算、前端 transit.ts |
| **G. DRIVING/TAXI 合并** | Problem 2：产品重复 | 若未来引入真实打车计价，需重新拆分 | 低（纯 UI/枚举语义） | 前端 TransitLegControl、Java 枚举、契约枚举 |
| **H. 前端 AUTO 上移为规划期偏好**（用户可选"默认交通偏好"传入 planner） | Problem 1/2 的产品语义 | — | 中；涉及契约、Java、前端 | TripConstraints 新字段、contracts、规划链路 |

---

## 10. Recommended Priority

基于审计证据（非预判照搬）：

1. **P1 — P18-R3（MUST_VISIT_MATCH 子串扩散）**：改动最小、直击正佳案例的最高优先级问题；与既有 `_is_must_visit_poi` 的 exact 语义对齐。
2. **P1 — P18-R1（Route mode selection / 至少短距离不驾车）**：产品感知最强（34/34 leg 全驾车 + 同坐标 1 米 leg 驾车）；建议先做"规则式兜底"（如 <800m 用步行估算、同坐标去重后再路由），再做完整 multi-mode。
3. **P2 — P18-R2（Recall 关键词策略）**：召回层是扩散起点，与 R3 修复配套才能根治正佳案例。
4. **P2 — P18-R5（diversity objective）**：需要先定义 objective 与 golden-matrix 回归，改动面大。
5. **P3 — P18-R4（去重增强）与 P18-R6（satisfied 状态）**：作为 R3/R5 的补强。

---

## 11. Files Involved（预计后续修改涉及，本轮未改动）

**Python (apps/agent-service/src/trip_agent/)**
- `infrastructure/amap/planning_provider.py` — route mode 硬编码(1100)、recall(1504)、must_include 判定(669)
- `planning/candidates.py` — MUST_VISIT_MATCH 子串匹配(187-190)、去重(113-116)
- `planning/daily_schedule.py` — _fill_slots 排序(847-914)、_primary_region(788-803)、must_include 语义
- `domain/shared.py` — candidate_keywords(218)、mapped_places_match(114)、canonical_place_identity(160)
- `planning/poi_quality.py` — 候选分类/去重辅助
- `providers/_route_contracts.py` — RouteMode 类型
- `providers/_amap_route.py` — walking/driving endpoint
- `application/replan_service.py` — replan mode 复用(273)
- `worker/contracts.py` — ItineraryTransitMode(659)、TripConstraints

**Java (apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/)**
- `itinerary/ItineraryService.java` — estimatedTransitDuration/Cost(605-626)、applyTransitLegEdit(583)
- `trip/TripConstraintRecord.java`、`trip/TripRequests.java` — 若新增交通偏好字段

**前端 (apps/web/src/)**
- `lib/transit.ts` — estimateCommuteOptions / recommendedCommuteMode
- `components/TransitLegControl.vue` — 5 按钮 + AUTO 语义
- `components/TripDetail.vue` — transitModeFor 默认展示(304-307)

**契约 (contracts/)**
- 若新增交通偏好 / 修改 mode 语义

---

## 12. Test Gaps

### 为什么现有测试没发现

| 问题 | 测试缺口原因 |
| --- | --- |
| 默认驾车 | `test_route_provider.py` / `test_demo_ordering.py` 只验证 **WALKING/DRIVING 的契约解析与 provider 适配**，从不断言"活动间路线应该选哪种 mode 的产品规则"；没有任何测试断言"短距离不应是 DRIVING"或"leg.mode 来自哪里" |
| 正佳广场聚集 | `test_must_visit_recall.py` 只测"recall 不早停"与"exact id pinning"，**从不构造同坐标/同名 sibling 全部入选**的场景；`test_candidate_ranking.py` 验证 MUST_VISIT_MATCH 加分存在性，但**从不断言"名称含 must-visit 的 sibling 不应同分"**；`test_daily_schedule.py` 使用抽象候选（无坐标/类别/名称语义），无法暴露 geo 聚集 |
| must-visit 重复相关 POI | 无任何测试同时覆盖 recall → ranking → scheduling 全链路；无集成断言"整份行程的地理/类别多样性"；golden-matrix 测试用 `test_golden_matrix.py` 但未包含"must-visit=大型商业综合体"场景 |

### 建议的 RED 测试（先写失败测试再修）

1. **recall**：`must_visit_places=["正佳广场"]` 时，候选池中 must-visit 相关 POI 占比不应超过阈值（或必须包含足够的非相关关键词候选）。
2. **ranking**：`小林蓝鳄正佳广场`（不同 providerPoiId、同坐标）**不应**获得 `MUST_VISIT_MATCH` 同分（与 B00140TFHO 同分即失败）。
3. **schedule**：同一天内不允许两个距离 <200m 且名称含 must-visit 关键词的活动同时入选（或允许但必须扣分）。
4. **交通**：距离 <800m（或同坐标）的 leg 默认 mode 不应是 DRIVING；「正佳广场→小林蓝鳄正佳广场」1 米 leg 必须被识别为步行/合并。
5. **全链路**：一个 `must_visit=正佳广场` 的 3 日广州行程，断言最终行程中正佳广场建筑内活动 ≤2 个。

---

## 附：复现与审计证据清单

- 复现脚本输出：`C:\Windows\Temp\opencode\b18_trace.py`（Stage 1-4 数据）
- 真实 DB 行程：`business.itinerary` trip `ac27972d-6729-467a-b6d0-bc4bc48732a0`（约束含正佳广场 ref B00140TFHO）
- DB transit 统计：`business.transit_leg` 34/34 条 `mode='DRIVING'`
- 关键代码定位（见各节引用行号）
