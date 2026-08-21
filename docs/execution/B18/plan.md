# B18-A + B18-B 实施计划

- 计划日期：2026-08-18
- 基线：`docs/execution/B18/audit.md`（独立审计证据，本计划不复述审计全文）
- 分支 / HEAD：`codex/feasibility-foundation` @ `d10e70c`
- 工作区：B15/B16/B17 在途修改 73 个文件保持原样；本计划阶段未触碰任何生产代码
- 状态：**计划阶段，未开始实施**。本计划形成后可进入 RED→GREEN 实施

---

## 1. Scope

### 包含

- **B18-A — Must-Visit / Candidate Recall 语义修复**（解决 `P18-R2` + `P18-R3`，必须整体设计，不允许只修 R3）
- **B18-B — Transport Mode Baseline**（解决 `P18-R1`，只建立最小可靠 baseline，不做 multi-mode optimizer）

### 明确排除

- **B18-C — itinerary diversity objective**：延期。B18-A 修复候选池后重新观察真实规划，若仍存在同类/同商圈过度集中再设计。
- **B18-D — parent/complex semantic dedup**：延期。数据模型无 `parentPoiId/building/business_area`，不为单案例扩模型。
- 驾车/打车 UI 合并：**本批不做**（详见 §9 兼容性；仅记录为 B18-B UI follow-up）。
- 公共交通（AMAP transit API）：**本批不做**（需 city code / transfer / alternatives，范围大；`RouteMode` 与 AMAP provider 均不支持，非审计遗漏）。

---

## 2. Verified Baseline（关键代码点复核）

| 证据 | 位置 |
| --- | --- |
| 唯一 `RouteRequest(...)` 调用点硬编码 `mode="DRIVING"` | `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py:1093-1104`（`_emit_day` 内） |
| `RouteMode = Literal["WALKING","DRIVING"]`，无 TRANSIT/TAXI | `apps/agent-service/src/trip_agent/providers/_route_contracts.py:16` |
| AMAP 仅 walking/driving endpoint | `apps/agent-service/src/trip_agent/providers/_amap_route.py:38-39, 73` |
| `TransitLeg.mode = route.data.mode`（=DRIVING） | `planning_provider.py:1299-1317`（`_leg_from_route`） |
| DB 现存 34/34 leg 为 DRIVING，含「正佳广场→小林蓝鳄正佳广场」1m/1s/DRIVING | `business.transit_leg`（trip `ac27972d`） |
| `candidate_keywords` 将 must-visit 文本放在关键词最前 | `apps/agent-service/src/trip_agent/domain/shared.py:218-225` |
| `_collect_pois` 早停：`if len(ranking.selected) >= required_count: return`；`required_preference_queries = max(1, min(len(preferences), len(keywords)))`（preferences 为空时第 1 个 must-visit 关键词后即可早停） | `planning_provider.py:1523-1535, 1558, 1566-1582` |
| `MUST_VISIT_MATCH` 子串匹配 `_text_key(place) in searchable`，+100 且排序置顶 | `apps/agent-service/src/trip_agent/planning/candidates.py:187-190, 146-153` |
| `must_include` 仅按 exact providerPoiId（有 refs）/ exact normalized name（无 refs） | `planning_provider.py:669-699`（`_is_must_visit_poi`） |
| 前端 AUTO = 纯 UI 推荐器（`recommendedCommuteMode`：walking ≤ 20min 优先） | `apps/web/src/lib/transit.ts:65-76`；`apps/web/src/components/TransitLegControl.vue:66-70` |
| 前端切换 mode → Java 本地估算（无 provider），persist 不覆盖 planner 输出 | `apps/travel-server/.../itinerary/ItineraryService.java:583-626` |
| replan/repair 复用已有 leg mode 或 WALKING | `apps/agent-service/src/trip_agent/application/replan_service.py:264-273` |
| route 预算上限 96 次/规划，cache key 含 mode | `domain/shared.py:41`；`planning_provider.py:1651-1669` |
| `WALKING` 费用=0（`_transit_cost`），cost_source=RULE_ESTIMATE | `planning_provider.py:1584-1608` |

---

## 3. B18-A Design

### 3.1 Exact Must-Visit Identity（R3 修复）

**identity 字段：`providerPoiId`（优先）→ normalized exact name（仅 legacy 无 id 时）**，与现有 `_is_must_visit_poi`（B13_FIX R5 语义）完全对齐。

- 有 `must_visit_place_refs`（结构化，主路径）：
  - `poi.provider_id in must_visit_ids` → `MUST_VISIT_MATCH`（+100，排序置顶）
  - **其余任何 POI 不得因名称获得 must-visit boost**
- 无 refs（legacy 自由文本，见 §3.3）：
  - `normalized(poi.name) == normalized(must_visit_name)`（alphanumeric casefold 精确相等）→ boost
  - 子串匹配（`contains`）**彻底移除**

**实现方式**：把 `_is_must_visit_poi` 的判定逻辑提取为共享纯函数（放 `planning/candidates.py`，`CandidateRanker._score` 与 `AmapPlanningProvider._is_must_visit_poi` 共用同一实现），消除"must_include 判定"与"ranking boost 判定"两套标准漂移。

示例（用户 A1/A2/A3）：
- `正佳广场 / B00140TFHO` → 命中（exact id）
- `小林蓝鳄正佳广场 / B0MDA73DXY` → 不命中（不同 id，名称含"正佳广场"无 boost）
- `正佳广场 / OTHER-ID`（同名不同 id）→ 有 refs 时不命中（exact id only）；无 refs 时命中（legacy 固有局限，见 3.3）

### 3.2 Recall：Required 与 Exploration 分离 + early-stop 修复（R2）

**结论：不新增领域类，在 `_collect_pois` 内做来源职责分离（最小修改）。**

- **Required 来源**：
  - 结构化 refs → exact id 由 `pinned_provider_ids` 注入（**现有机制不变**，`planning_provider.py:329-336`）
  - legacy 无 refs → must-visit 名称关键词搜索必须执行（**保留**，负责召回 exact-name POI 与 enrichment；代码注释 1561-1565 已声明其用途）
- **Exploration 来源**：preferences + 默认关键词（`DEFAULT_POI_KEYWORDS`），负责填充候选池多样性
- **early-stop 修改（核心）**：**移除 `len(ranking.selected) >= required_count` 数量早停分支**（`planning_provider.py:1580-1581`），关键词循环总是执行全部 `MAX_POI_QUERIES(6)` 个关键词：
  - must-visit 关键词（无论返回多少附近 POI）**永远不能**单独触发召回结束
  - 保留 `structured_ids and not structured_ids <= recalled_ids → continue` 检查（exact id 未召回则继续搜索）
  - `required_preference_queries` 变量随之删除（其 `max(1, min(len(preferences), len(keywords)))` 在 preferences 为空时=1，是"第 1 个 must-visit 关键词后即可早停"缺陷的根源）
  - rank 调用移出循环，循环结束后对合并候选执行一次（现循环内 rank 仅用于早停评估，无其它副作用）
  - **成本论证**：POI 搜索 6 次封顶（每次 1 次调用，limit ≤25），不是 route calls，预算影响可忽略（route 预算 96 单独存在）
- **must-visit 关键词返回的 sibling POI 处置**：**保留在候选池中，以普通候选身份参与 ranking**（基础分），不得过滤、不得排除——满足"禁止名称含 must-visit 即全排除"约束（大型综合体内部独立海洋馆/博物馆仍可作为普通候选入选，只是不再被 must-visit 名义置顶）。是否最终入选由 score/region 决定，不因 R3 修复而改变（sibling 从 120 分回落到 20 分自然失去竞争力，这是预期效果而非 B18-D 去重）。

### 3.3 Name-only Fallback 审计结论与策略

**name-only 路径真实存在**：
- `contracts.py:222-231`：schema v3 下 `must_visit_places` 非空、`must_visit_place_refs` 为空是合法输入（"legacy free text that was never structured"）
- 前端 `ConstraintEditor.vue:195-197`：允许自由文本必去地点（`entry.placeRef` 可为空）

**策略**：
- 主路径（有 refs）：**只用 resolved providerPoiId，不引入任何额外 fallback**（服务端 token 签名保证 id 存在且 canonicalized）
- legacy（无 refs）：**保留 normalized exact name 匹配**（现状 `_is_must_visit_poi` 已是精确匹配，仅需让 ranking boost 与其一致），**禁止 substring**
- 风险与冲突处理：
  - 同名不同 id 在 legacy 路径可能误匹配（如两个"正佳广场"记录）——这是无 id 输入的固有局限；缓解：B13_FIX R5 已使结构化路径为主路径，legacy 场景逐步退场；文档记录，不新增 resolution 逻辑
  - legacy exact-name 未命中 → 现有 `MUST_VISIT_UNAVAILABLE` fail-closed 行为不变（`planning_provider.py:595-610`）

### 3.4 明确不做的事（防范围蔓延）

- 不新增 diversity/radius/同地址/同商圈去重（B18-D 边界）
- 不新增 required/exploration 领域对象（不重构候选池模型）
- 不修改 `CandidateRanker.rank` 签名（`must_visit_places` 参数保留，语义内部对齐）
- 不修改 `candidate_keywords`（关键词顺序保留，早停移除已足够）

---

## 4. B18-B Design

### 4.1 Mode Decision Point（决策层）

**决策点放在 Python planner 的 `_emit_day` 路线查询处**（`planning_provider.py:1093`），新增强制纯函数模块：

```
apps/agent-service/src/trip_agent/planning/transit_mode.py（新文件）
```

```python
# 纯函数（无 IO，可独立单测）
def decide_walkable(distance_meters, walking_duration_seconds, *,
                    walkable_haversine_meters, walking_threshold_seconds) -> bool
# 语义：haversine 预判放行 + AMAP 实测 walking duration 是否 ≤ 阈值
```

常量（初值，RED 阶段用真实 AMAP 数据校准，测试一律显式注入不依赖硬编码）：
- `WALKABLE_HAVERSINE_METERS = 1500`（预判上限，待校准）
- `WALKING_THRESHOLD_SECONDS = 1200`（20 分钟，与前端 `lib/transit.ts:71` 阈值语义对齐）

### 4.2 Walking Threshold 策略（用实测 duration，非纯直线距离）

用户要求优先比较 walking **route duration** 而非仅距离。流程（每对活动）：

```
haversine(distance) ≤ WALKABLE_HAVERSINE_METERS?
├─ 是 → 查 AMAP walking route（1 次调用）
│     ├─ walking 成功 且 duration ≤ 1200s → mode=WALKING（使用 walking 数据）
│     ├─ walking 成功 但 duration > 1200s → 查 driving → DRIVING（该 leg 共 2 次）
│     └─ walking 查询失败（provider error）→ 查 driving（fallback）→ DRIVING
└─ 否 → 只查 driving（现有行为，1 次调用）→ DRIVING
```

理由：500m 可能因河流/立交/园区导致实际步行远超直线估算；用 AMAP walking endpoint 实测值判定，语义与前端"步行 20 分钟"推荐一致。

### 4.3 Provider Query Strategy（避免双倍成本失控）

**采用"haversine 预判 + 按需双查"（方案 A 为主，B 为兜底分支）**，不是全量双查询：
- 每条 leg 常规仍为 1 次调用（短→walking，长→driving）
- 仅"≤1500m 但步行实测超时"的 leg 发生第 2 次调用（罕见分支）
- cache：`_route_cached` key 含 mode（`planning_provider.py:1657-1662`），walking/driving 缓存分离不互相污染；同规划重复 pair 命中

### 4.4 Fallback

- walking provider 失败 → **降级查 driving（road baseline）**，绝不导致整体规划失败（`ROUTE_CALL_BUDGET_EXHAUSTED`/provider error policy 保持：若 driving 也失败，走现有 `_route` → fallback policy → DEMO 或 fail-closed，与今日行为一致）
- 不新增 fallback 枚举/字段

### 4.5 Cost / Persistence / Frontend

- **Cost**：`_transit_cost` 已正确返回 WALKING=0（`planning_provider.py:1592-1593`），`cost_source=RULE_ESTIMATE`（1604-1605），无需修改；B6 测试验证
- **Persistence**：`TransitLeg.mode` 原样持久化（contracts.py:666 已含 WALKING；`business.transit_leg.mode` 列已存在，无 migration）。Java 保存链路（`PlanningCompletionService → ItineraryVersionPersister`）透传 event 字段，不覆盖 mode——B7 测试验证
- **Frontend**：`TransitLegControl` 已有 WALKING 按钮与 label（`modeLabel`），初始显示 = persisted leg.mode（`TripDetail.vue:304-307`），**无需改前端代码**；B8 为验证型测试
- **Replan/Repair**：`replan_service.py:264-273` 复用已有 leg mode（或 WALKING），本批不改

### 4.6 AUTO 一致性决策

**接受"双实现 + 统一语义阈值"（方案 B 折中）**：
- planner：AMAP walking 实测 duration ≤ 20min → WALKING
- 前端 AUTO：估算 walking duration（distance/1.25）≤ 20min → WALKING
- 不跨 Python/TS 共享代码（避免引入共享模块与构建复杂度）
- 缓解漂移：① 阈值常量在 plan.md 与代码注释中成对记录；② 新增 shared behavioral tests（Python `test_transit_mode.py` 断言 20min 阈值行为 + Web `lib/transit.test.ts` 断言 `20 * 60` 常量）
- 差异说明：planner 用实测值、前端用估算值，语义一致但数值允许不同（文档化）

### 4.7 驾车/打车边界（本批）

- **不改 UI、不删 TAXI/DRIVING 枚举、不做 DB migration、不做 contract breaking change**
- 前端"公交/驾车/打车为距离估算"note（`TransitLegControl.vue:213`）保留
- 驾车/打车 UI 收敛 → 记录为 **B18-B UI follow-up**（最小兼容方案：仅前端按钮收敛，routing mode 枚举保持）
- routing mode（WALKING/DRIVING）与 user-facing commute option（未来 ROAD→SELF_DRIVING/TAXI）概念区分写入代码注释，本批不引入新枚举

---

## 5. Files to Change（预计，本批不实施）

### B18-A

| 文件 | 修改 | 原因 |
| --- | --- | --- |
| `apps/agent-service/src/trip_agent/planning/candidates.py` | ① must-visit identity 判定提取为共享纯函数；② `_score` 中 `MUST_VISIT_MATCH` 从子串改为 identity 匹配（+100 仅 exact 命中） | R3 核心 |
| `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py` | ① `_is_must_visit_poi` 改为调用共享判定；② `_collect_pois` 移除数量早停、`required_preference_queries` 删除、rank 移出循环 | R2 核心 |
| （无 contract/Java/DB 变更） | — | 语义不改变任何外部契约 |

### B18-B

| 文件 | 修改 | 原因 |
| --- | --- | --- |
| `apps/agent-service/src/trip_agent/planning/transit_mode.py`（新文件） | 纯函数 `decide_walkable` + 阈值常量 | 可独立单测的 mode 决策 |
| `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py` | `_emit_day` route 调用处按决策流程查询 walking/driving；新增 walking-failure → driving fallback 分支 | R1 核心 |
| （无 Java/DB/frontend 代码变更） | — | 已具备 WALKING 全链路支持，B7/B8 为验证型测试 |

---

## 6. RED Test Matrix

### B18-A（新增/修改测试文件：`tests/test_candidate_ranking.py`、`tests/test_must_visit_recall.py`、新 `tests/test_b18_golden.py`）

| ID | 层级 | 输入 | RED（修复前失败原因） | GREEN（修复后断言） |
| --- | --- | --- | --- | --- |
| A1 | 单元（ranker） | `must_visit_places=["正佳广场"]`, refs id=B00140TFHO；候选 `正佳广场/B00140TFHO` | 现行为不区分 id 也可命中，无法验证精确性 | `MUST_VISIT_MATCH` 命中，score=120，`must_include=True` |
| A2 | 单元（ranker） | 候选 `小林蓝鳄正佳广场/B0MDA73DXY`（名称含"正佳广场"，id 不同） | 现行为子串命中 +100 | **无** `MUST_VISIT_MATCH` reason，score=20（仅基础分），`must_include=False` |
| A3 | 单元（ranker） | 候选 `正佳广场/OTHER-ID`（同名不同 id，有 refs） | 现行为子串命中 +100 | 不命中（exact id only）；无 refs 时 exact-name 命中（legacy 语义单独断言） |
| A4 | 集成（`_collect_pois`） | `must_visit=["正佳广场"]` + refs；"正佳广场"关键词首轮返回 ≥required_count 候选 | 现行为第 2 个关键词后早停（搜索序 `['正佳广场','美食']`） | 全部 6 个关键词均执行（`KeywordMapProvider.calls` 断言包含 历史/景点/博物馆/公园） |
| A5 | 集成（`_collect_pois`） | 同上 | 候选池 56% 为正佳建筑内 POI | 候选池包含非正佳区域城市候选（来源覆盖断言：每类 exploration 关键词均贡献候选；不做脆弱比例断言） |
| A6 | 集成（全链路） | 同上 + `plan_day` | — | 最终 selected 集合含 `B00140TFHO`（exact id 不被普通 ranking 淘汰） |
| A7 | Golden（`test_b18_golden.py`） | 审计真实案例形状（正佳广场 + sibling 同坐标） | 现行为 sibling 与正佳同分 120 且置顶 | ① exact 正佳广场入选；② sibling 无 `MUST_VISIT_MATCH`；③ exploration 关键词执行。不断言"最多几个正佳内部 POI"（避免绑定 B18-D 语义） |

### B18-B（新增 `tests/test_transit_mode.py`、扩展 `tests/test_route_provider.py`、`tests/test_planning_worker.py`）

| ID | 层级 | 输入 | RED（修复前失败原因） | GREEN（修复后断言） |
| --- | --- | --- | --- | --- |
| B1 | 单元（mode 决策） | distance=1m/50m/200m，walking_duration 正常 | 现行为无条件 DRIVING | mode=WALKING |
| B2 | 单元（mode 决策） | distance=800m，walking_duration=900s（≤1200s） | 无条件 DRIVING | WALKING（以实测 duration 判定，非距离阈值） |
| B3 | 单元（mode 决策） | 酒店→机场 distance=21000m | 无条件 DRIVING（修复后不能误切） | DRIVING（walking 查询被 haversine 预判跳过） |
| B4 | 单元+集成（fallback） | distance=500m 但 walking provider 返回失败 | 现行为整体规划可能失败/DRIVING | walking 失败 → driving 查询成功 → DRIVING；规划不失败；不产生 INTERNAL_PLANNING_FAILED |
| B5 | 单元（数据一致性） | walking route 返回 duration/polyline | — | `mode=WALKING` 的 leg 其 duration/distance/polyline 全部来自 walking route（禁止混用 driving 数据） |
| B6 | 单元（cost） | WALKING leg 持久化链路 | — | `estimated_cost=0`、`cost_source` 正确（不泄漏 driving cost） |
| B7 | 集成（persistence） | 完整 plan 链路产出 WALKING leg → event → Java 保存 | 现行为全部 DRIVING | DB `transit_leg.mode='WALKING'`（Java 不覆盖回 DRIVING） |
| B8 | Web 验证 | 前端渲染 mode=WALKING 的 leg | — | `TransitLegControl` 初始显示与 persisted mode 一致（"步行"，非"驾车"） |
| B9 | 单元 regression | `正佳广场→小林蓝鳄正佳广场`（distance=1m，同坐标） | 现行为 1m/1s/DRIVING | mode 决策层输出 WALKING（下沉到单元层，不依赖最终行程包含该 leg——B18-A 可能使其不再被选中） |

---

## 7. Golden Cases

| ID | 场景 | 断言（行为级，非全量快照） |
| --- | --- | --- |
| **G1** | `must_visit=正佳广场(B00140TFHO)` 广州 3 日 | ① exact 正佳广场在最终行程；② 小林蓝鳄正佳广场等 sibling 无 `MUST_VISIT_MATCH`（score 120→20）；③ 候选召回执行全部 exploration 关键词 |
| **G2** | 极短 transit leg（≤200m） | 最终行程 leg 不是 DRIVING（mode=WALKING） |
| **G3** | 长距离（住宿→机场 21km，真实案例形状） | 最终行程 leg 保持 DRIVING（不误切 WALKING） |

---

## 8. API Cost Analysis

| 项 | 当前 | B18-B 后 | 说明 |
| --- | --- | --- | --- |
| route calls / leg | 1（DRIVING） | 1 常规 / 2 仅"≤1500m 且步行实测超时"分支 | 短 leg 的 1 次 driving 换成 1 次 walking，成本不变 |
| 3 日典型行程（~25 leg） | ~25 calls | ~27-28 calls（估：1500m 内 leg 占 40%，其中超时分支 20% → 增量 ~10%） | 上限 `MAX_ROUTE_CALLS_PER_PLAN=96`，余量充足 |
| 最坏增长 | — | 2x（全部 leg 落入超时分支，实际不可能；即便 2x 也 < 96 上限） | 每 leg 最多 2 次 |
| POI 搜索 | 1-2 次（早停） | 恒 6 次（`MAX_POI_QUERIES` 上限） | B18-A 移除早停的代价；每次 1 调用、limit ≤25，与 route 预算独立 |
| cache 缓解 | — | 是：key 含 mode，walking/driving 分离；同规划重复 pair 命中 | `_route_cached` 现有实现 |

**结论**：无需为此调整任何限额常量；无未经测算的双倍全量调用。

---

## 9. Compatibility

| 层 | 影响 | 处置 |
| --- | --- | --- |
| Python contract（`worker/contracts.py`） | 无 schema 变更；`ItineraryTransitMode` 已含 WALKING | 不修改 |
| Java（ItineraryService / event parser） | 无代码变更；WALKING 已在 mode 白名单（`ItineraryService.java:424-426`） | 不修改 |
| DB | 无 migration；`transit_leg.mode` 列已存在 | 不修改 |
| 既有 TransitLeg（34 条 DRIVING） | 历史数据保持 DRIVING，只读展示正常 | 不回填、不迁移（旧行程语义不变） |
| 前端 | 已支持 WALKING 按钮/label/估算；无需代码变更 | B8 验证；驾车/打车合并 → B18-B UI follow-up（本批不做） |
| 旧 itinerary versions | 只读展示，不受影响 | 不处理 |
| replan/repair | 复用已有 leg mode，本批不引入新逻辑 | 不修改 |

**目标达成：零 breaking migration，B18-A 与 B18-B 各自可独立合入/回滚。**

---

## 10. Risks

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| must-visit exact identity resolution failure（refs 缺失/失效） | 中 | 结构化 refs 由服务端 token 签名保证存在；legacy 保持 exact-name 匹配；fail-closed 行为不变（`MUST_VISIT_UNAVAILABLE`） |
| candidate pool 变稀（must-visit 关键词不再主导后） | 中 | `DEFAULT_POI_KEYWORDS` 保证 4 个基础探索关键词全执行；候选池数量由 `required_count*3` limit 维持 |
| AMAP API 请求量增加 | 低 | §8 测算：增量 ~10%，96 上限余量充足；POI 6 次封顶 |
| walking provider failure | 中 | 明确 fallback 到 driving（road baseline），不导致整体失败；driving 也失败则维持现有 provider error policy |
| planner/frontend recommendation drift | 低 | 统一 20 分钟语义阈值 + shared behavioral tests + 文档化常量（§4.6） |
| golden itinerary 大量变化（正佳案例行程形态改变） | 中 | G1 用行为断言（exact 保留 / sibling 无 boost / exploration 执行），非全量快照；现有 golden-matrix 测试需逐条人工复核行程变化是否合理 |
| A/B 耦合风险 | 低 | 两个独立 commit；B18-A 先合入可独立验收（候选池变化），B18-B 后合入（mode 变化） |
| 早期早停移除导致 latency 增加 | 低 | 6 次 POI 搜索串行，每次 ≤25 结果；量级毫秒-秒级，可接受 |

---

## 11. Rollback

- **B18-A 独立 commit**：`git revert` 单个 commit 即可回滚（无 DB/契约变更，纯 Python 逻辑）
- **B18-B 独立 commit**：同样可单点回滚；若 B18-B 已产出 WALKING leg 数据，回滚后历史 leg 保持 WALKING（mode 枚举合法，前端/Java 均兼容显示）
- **不把两者强绑为不可拆提交**
- 无 DB migration 意味着回滚零数据风险

---

## 12. Acceptance Criteria

### B18-A

- [ ] resolved must-visit 只按精确 identity（providerPoiId，legacy 降级为 normalized exact name）获得强 boost
- [ ] 名称包含 must-visit 文本的 sibling 不再自动获得 `MUST_VISIT_MATCH`（A2 绿）
- [ ] must-visit 候选仍被强制保留（A6 绿；pinned 机制不变）
- [ ] must-visit 关键词不再单独垄断 candidate recall（A4 绿：全部 exploration 关键词执行）
- [ ] 正常 exploration sources 仍被执行（A5 绿）
- [ ] 正佳案例中 exact 正佳广场（B00140TFHO）仍出现（G1）
- [ ] 正佳内部 sibling 不再因 must-visit 名义集体 +100（A2/A7 绿）
- [ ] 不引入粗暴 radius/同区域硬去重（代码审查项：B18-A diff 不含任何距离/商圈过滤逻辑）
- [ ] 全量 pytest + ruff 通过

### B18-B

- [ ] planner 不再无条件 `RouteRequest(mode="DRIVING")`（B1/B2 绿）
- [ ] 明显可步行短距离选择 WALKING（B1/B2/G2）
- [ ] 长距离不误选 WALKING（B3/G3）
- [ ] walking route 失败有明确安全 fallback → driving（B4 绿）
- [ ] mode/duration/distance/polyline 来源一致（B5 绿）
- [ ] WALKING 费用语义正确 = 0（B6 绿）
- [ ] Java/DB 不把 WALKING 覆盖回 DRIVING（B7 绿）
- [ ] Web 初始显示与 persisted mode 一致（B8 绿）
- [ ] 未引入公共交通大范围实现（scope 审查）
- [ ] 未做 breaking enum migration / DB migration / contract 变更（scope 审查）

### 全量回归（本批实施后执行）

```
Python: targeted（test_candidate_ranking / test_must_visit_recall / test_daily_schedule
        / test_route_provider / test_transit_mode / test_b18_golden）→ 全量 pytest → ruff
Java:   mvn -pl apps/travel-server test（itinerary/mq/planning 相关）
Web:    pnpm test:coverage + pnpm typecheck（TransitLegControl / TripDetail / lib/transit）
compose smoke（3 cases）：
  Case 1  普通城市两日游，无 must-visit → 抽查候选来源与 mode 分布
  Case 2  广州 + must_visit=正佳广场 → 抽查 selected POIs（exact 保留、sibling 无 boost）、
          候选来源、transit mode 分布
  Case 3  含住宿 + departure 长距离 → 抽查长 leg 为 DRIVING、短 leg 为 WALKING
```

**质量指标（非成功率）**：验收关注①是否仍围绕单一 must-visit 扩散 ②是否仍存在 1m/DRIVING ③must-visit 是否保留 ④是否引入新的不合理选择。规划成功不是唯一指标。

---

## 执行顺序（Phase 1-8，本阶段不执行）

```
Phase 1  B18-A RED（A1-A7 + G1 测试先写，全部红灯）
Phase 2  B18-A implementation（candidates.py + planning_provider.py）
Phase 3  正佳 golden 验证（G1 绿 + golden-matrix 复核）
Phase 4  B18-B RED（B1-B9 + G2/G3 先写，全部红灯）
Phase 5  B18-B implementation（transit_mode.py + planning_provider.py）
Phase 6  交通 golden 验证（G2/G3 绿 + 真实 AMAP 模式抽查）
Phase 7  full regression（Python/Java/Web）
Phase 8  compose quality smoke（Case 1-3）
```

每个 Phase 完成后停留确认；B18-A 与 B18-B 各自独立 commit。
