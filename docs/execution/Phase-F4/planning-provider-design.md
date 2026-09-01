# F-4.1 planning_provider.py 拆分设计

- 目标文件：`apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py`（2450 LOC，全仓最大 Python 文件）
- 依据：`docs/execution/Phase-F4/INVENTORY.md` §A.2 + §E.1（职责地图粗扫）
- 方法：Evidence First——本文档所有行号基于当前 HEAD（`440aa5c`）实读
- 原则（用户提示词约束）：拆分后 `AmapPlanningProvider` 仍是清晰的 **Facade / Orchestrator**；禁止拆成十几个互相调用的小文件形成新 spaghetti；目标 **High Cohesion / Low Coupling / Clear Dependency Direction**

---

## 当前职责地图

`AmapPlanningProvider`（class L358，核心方法 386-2450）实载 8 组职责（方法级行号为当前 HEAD 实测）：

| 职责组 | 方法（行号） | LOC | 依赖的注入对象 |
|---|---|---|---|
| 顶层编排 | `plan`(:386), `_plan_with_skeleton`(:391-950) | ~570 | 全部 |
| POI 收集/候选 | `_collect_pois`(:1947), `_poi_from_ref`(:974), `_to_candidate`(:996), `_magnitude_for_poi`(:1031), `_is_must_visit_poi`(:953), `_is_complex_experience`(:1125) | ~250 | map_provider |
| 事实/证据构建 | `_entity_facts_for_pois`(:204, 模块级), `_amap_opening_value`(:276, 模块级), `_non_weather_guide_statements`(:317, 模块级), `_with_opening_availability`(:1060) | ~180 | 无（纯函数） |
| 日排程发射 | `_emit_day`(:1260-1514), `_fixed_schedules_on`(:1130), `_slot_from_item`(:1539), `_activity_from_slot`(:1564), `_meal_window_constraints`(:1035), `_special_day_date`(:1239), `_fixed_slot_timing_error`(:1517) | ~450 | map_provider + 路由 + 锚点 |
| 路线/交通 | `_route`(:2030), `_route_for_pair`(:2077), `_route_cached`(:2413), `_leg_from_route`(:1616), `_transit_cost`(:2005), `_transit_cost_source`(:2019), `_recommend_transit_or_road`(:2276), `_try_walking_route`(:2390), `_mobility_repair_candidate`(:1156) | ~520 | route_provider / transit_route / route_fallback / fallback_policy / provider_mode |
| 锚点/餐解析 | `_resolve_travel_anchors`(:1843), `_resolve_fixed_place`(:1673), `_resolve_meal_poi`(:1701), `_meal_keywords`(:1806), `_anchor_unavailable`(:1925) | ~260 | map_provider |
| 修复/重规划 | `repair`(:1830), `replan`(:1817), `_capacity_repair_candidate`(:1176), `_can_relax_window_start`(:1206) | ~120 | 委托 LocalReplanningProvider；修复策略纯函数 |
| 约束/辅助 | `_considered_modes`(:140, 模块级), `_avoid_provider_ids`(:325, 模块级), `_titles_with_reason`(:336, 模块级), `_resolver_clock`(:188, 模块级), `_fixed_slot_timing_error`(:1517) | ~100 | 无（纯函数） |

模块级常量：`_COMPLEX_TERMS`(:297)、`_DINING_TERMS`(:314)、`_REDUCED_MOBILITY_MAX_HOP_METERS`(:162)、`_MAX_MOBILITY_REPAIR_ATTEMPTS`(:163)、`_WINDOW_RELAX_STEP_MINUTES`(:170)、`_WINDOW_RELAX_FLOOR_MINUTE`(:171)；`_FetchedPoi` dataclass(:174-185)。

**问题诊断**：2450 行的根因不是"方法太多"（60 个方法在 2450 行里平均 40 行/方法，尚可），而是 **8 组职责共存于一个类 + 一个文件**。类内无状态耦合（仅注入依赖），方法间通过 `self._xxx` 互调——这是"内聚的巨型类"，按职责拆分后协作关系不变，风险可控。

---

## Runtime Call Graph

```
plan(command)
└─ _plan_with_skeleton(command)                                [编排核心，留在 Facade]
   ├─ report_planning_progress("POI_RECALLING")
   ├─ _collect_pois(command, max(day*3, 2))                    → PoiRecaller.collect
   │   └─ map_provider.search_pois(PoiSearchRequest) × N 关键词
   ├─ _poi_from_ref(ref, destination) × must-visit refs        → PoiRecaller.poi_from_ref
   ├─ build_context_view(command, candidate_pois)              (planning.context_view，不动)
   ├─ candidate_ranker.rank(...)                               [Facade 直持，编排动作]
   │   ├─ _avoid_provider_ids(constraints)                     → 留在 Facade（纯函数）
   │   ├─ _non_weather_guide_statements(facts)                 → 留在 Facade（纯函数）
   │   ├─ _entity_facts_for_pois(raw_pois, command)            → opening_hours 模块
   │   └─ _titles_with_reason(selected, prefix) ×3             → 留在 Facade（纯函数）
   ├─ _to_candidate(poi, ...) × ranked                         → PoiRecaller.to_candidate
   │   └─ _is_must_visit_poi / _is_complex_experience          → PoiRecaller 内部
   ├─ _resolve_travel_anchors(command)                         → AnchorResolver.resolve_travel_anchors
   │   └─ map_provider.search_pois × ≤3 + _anchor_unavailable  → AnchorResolver 内部
   ├─ _special_day_date(command, candidates)                   → DayEmitter.special_day_date
   ├─ [day loop 707-841]                                       [留在 Facade，编排动作]
   │   ├─ hard_closed_fact(context, date, title)               (planning.trusted_context，不动)
   │   ├─ _with_opening_availability(cands, ctx, date)         → opening_hours.with_opening_availability
   │   ├─ plan_day(...)                                        (planning.daily_schedule，不动)
   │   │   ├─ _fixed_schedules_on(...)                         → DayEmitter.fixed_schedules_on
   │   │   ├─ _meal_window_constraints(...)                    → DayEmitter.meal_window_constraints
   │   │   └─ context_view.budget_per_person_per_day
   │   ├─ _emit_day(...)                                       → DayEmitter.emit_day
   │   │   ├─ _resolve_meal_poi(...)                           → AnchorResolver.resolve_meal_poi
   │   │   │   └─ map_provider.search_pois + _meal_keywords    → AnchorResolver 内部
   │   │   ├─ _resolve_fixed_place(...)                        → AnchorResolver.resolve_fixed_place
   │   │   ├─ _slot_from_item / _activity_from_slot /
   │   │   │   _fixed_slot_timing_error                        → DayEmitter 内部
   │   │   ├─ _route_for_pair(...)                             → RouteResolver.route_for_pair
   │   │   │   ├─ _try_walking_route → _route_cached → _route  → RouteResolver 内部
   │   │   │   │   └─ route_provider.get_route / transit / fallback + fallback_policy.decide
   │   │   │   └─ _recommend_transit_or_road → _route_cached ×2 → RouteResolver 内部
   │   │   │       └─ _considered_modes                        → RouteResolver 内部
   │   │   └─ _leg_from_route(...)                             → RouteResolver.leg_from_route
   │   │       └─ _transit_cost / _transit_cost_source         → RouteResolver 内部
   │   ├─ _mobility_repair_candidate(day, cands)               → repair_policy 模块
   │   ├─ _capacity_repair_candidate(err, day_plan, cands)     → repair_policy 模块
   │   └─ _can_relax_window_start(day_plan, err, steps)        → repair_policy 模块
   ├─ project_amap_trip_skeleton(...)                          (accommodation_projection，不动)
   ├─ project_amap_validation_inputs(...)                      (feasibility_projection，不动)
   └─ return PlanningResult(...)
replan(command) → LocalReplanningProvider(...).replan(command)  [Facade 委托，不动]
repair(request) → LocalReplanningProvider(...).repair(request)  [Facade 委托，不动]
```

**调用方向要点**：
- `_plan_with_skeleton` 只向下调用 4 个协作者 + 纯函数模块，协作者之间不反向依赖 Facade。
- 唯一横向依赖：`DayEmitter.emit_day → AnchorResolver / RouteResolver`（发射一天需要解析锚点与算路线）。
- 无环。

---

## Dependency Graph

### 外部依赖（模块 import，现状，拆分后归属）

| 外部模块 | 符号 | 拆分后归属 |
|---|---|---|
| `domain.planning.protocols` | PlanningResult/PlanningInfeasibleError/PlanningProviderError/OptimizationConflict/RelaxationSuggestion/ResolvedTravelAnchors/PlanningRepairRequest | Facade + RouteResolver + AnchorResolver + DayEmitter |
| `domain.shared` | CHINA_TIME_ZONE, MAX_ROUTE_CALLS_PER_PLAN, candidate_keywords, coordinate_decimal, minute_datetime, snapshot_boundary_times, text_matches | 分散各归属 |
| `guide_intelligence.travel_entities` | FactProvenance/FactValue/TravelEntityLocation/build_attraction | opening_hours |
| `infrastructure.amap.accommodation_projection` | project_amap_trip_skeleton | Facade |
| `infrastructure.amap.feasibility_projection` | project_amap_validation_inputs | Facade |
| `planning.candidates` | CandidateRanker, is_must_visit_poi | Facade（Ranker）+ PoiRecaller（predicate） |
| `planning.context_view` | PlanningContextView, build_context_view, resolve_transport_strategy_for_date, weather_level_for_date | Facade + DayEmitter |
| `planning.cost_model` | DEFAULT_ACCOMMODATION_PER_NIGHT, DEFAULT_MEAL_COST, resolve_attraction_cost, resolve_meal_cost, resolve_transit_cost | DayEmitter + AnchorResolver + RouteResolver |
| `planning.daily_schedule` | plan_day, DayPlan, DayPlanItem, FixedSchedule, MealDemand, MealWindowConstraint, CandidateActivity, classify_day_type, BUFFER_BETWEEN_MINUTES, DEFAULT_DAY_START_MINUTE, RELAXED_SLOT_CAPACITY_DISCOUNT_MINUTES, opening_availability_from_resolved(局部) | Facade + DayEmitter + opening_hours |
| `planning.decision_trace` | DecisionTrace, DecisionEvidence | Facade + AnchorResolver + RouteResolver |
| `planning.mode_recommendation` | ModeRecommendation, ModeRecommendationReason, ConsideredMode, accessible_burdens, can_probe_transit, decide_transit_or_road, MAX_TRANSFERS, MAX_TRANSIT_WALKING_METERS | RouteResolver |
| `planning.poi_quality` | canonical_poi_key, classify_place, duration_profile_for, magnitude_for_duration | Facade + PoiRecaller + AnchorResolver |
| `planning.transit_mode` | RECOVERABLE_ROUTE_CATEGORIES, is_walkable, should_try_walking, straight_line_distance_meters | RouteResolver |
| `planning.transport_strategy` | DEFAULT_TRANSPORT_STRATEGY, TransportStrategy, deadline_strategy | Facade + RouteResolver + DayEmitter |
| `planning.trusted_context` | hard_closed_fact | Facade |
| `planning.weather_policy` | WeatherLevel | RouteResolver + DayEmitter |
| `providers.errors` | ProviderExecutionMode, ProviderFallbackPolicy, FallbackDecision, ProviderOperation | Facade + RouteResolver |
| `providers.map` | MapProvider, Poi, PoiSearchRequest, ProviderSuccess, ProviderFailure, Coordinates | Facade + PoiRecaller + AnchorResolver |
| `providers.route` | RouteProvider, RouteRequest, RoutePlan | RouteResolver |
| `worker.contracts` | Itinerary/ItineraryDay/ItineraryActivity/TransitLeg/PlanningCreateCommand/PlanningReplanCommand/TripConstraints/GuideFactEvidence/ActivityCoordinates/FallbackOperation | Facade + DayEmitter + RouteResolver |
| `worker.progress` | report_planning_progress | Facade |
| 局部 import（防环/延迟）：`guide_intelligence.opening_evidence/opening_resolver`, `planning.validation_projection`, `application.replan_service.LocalReplanningProvider` | — | opening_hours（保留局部 import）/ Facade（保留局部 import） |

### 模块间依赖（拆分后，目标形态）

```
planning_provider.py (Facade)
  ├── poi_recall.py        (PoiRecaller)
  ├── opening_hours.py     (纯函数模块)
  ├── anchor_resolution.py (AnchorResolver)
  ├── route_resolution.py  (RouteResolver)
  ├── day_emitter.py       (DayEmitter) ──→ anchor_resolution.py
  │                                   └──→ route_resolution.py
  └── repair_policy.py     (纯函数模块)
```

- 方向全部自上而下：Facade → 协作者；DayEmitter → Anchor/Route。无反向、无环。
- 模块间共享的类型全部来自 `planning.*` / `domain.*` / `worker.contracts`（第三方中立类型），不共享私有可变状态。

---

## Proposed Module Boundaries

6 个新模块 + 1 个瘦身 Facade，全部位于 `trip_agent/infrastructure/amap/`：

### 1. `planning_provider.py`（Facade，目标 ~750 LOC）
保留：`__init__`（签名不变）、`plan`、`replan`、`repair`、`_plan_with_skeleton`（编排核心）、纯函数 `_non_weather_guide_statements` / `_avoid_provider_ids` / `_titles_with_reason`、测试面静态 `_magnitude_for_poi`（委托 PoiRecaller）。`__init__` 内部组合协作者：
```python
self._recaller = PoiRecaller(map_provider)
self._anchor_resolver = AnchorResolver(map_provider)
self._route_resolver = RouteResolver(route_provider, transit_route, route_fallback, provider_mode, fallback_policy)
self._day_emitter = DayEmitter(self._anchor_resolver, self._route_resolver)
```
> 注：`_plan_with_skeleton` ~560 行保留在 Facade 是有意为之——它是编排循环本体（day loop 与 ~15 个共享局部变量强耦合），强行外提会制造参数束/上下文对象，反而形成新 spaghetti。Facade 仍 >500 LOC 是可接受的：大文件治理的目标是"单一职责文件"，而 Orchestrator 的职责就是编排。

### 2. `poi_recall.py`（`PoiRecaller`，~200 LOC）
`collect`（原 `_collect_pois`）、`poi_from_ref`、`to_candidate`、`is_must_visit_poi`、`is_complex_experience`、`magnitude_for_poi`（供 Facade 测试面委托）；`_FetchedPoi` dataclass、`_COMPLEX_TERMS`。依赖：map_provider + planning.poi_quality/candidates。

### 3. `opening_hours.py`（纯函数模块，~170 LOC）
`entity_facts_for_pois`、`amap_opening_value`、`resolver_clock`、`with_opening_availability`（原静态方法转模块函数）。保留函数内局部 import（opening_evidence/opening_resolver/validation_projection/daily_schedule.opening_availability_from_resolved）。`_FetchedPoi` 从 poi_recall import（方向：opening_hours → poi_recall）。

### 4. `anchor_resolution.py`（`AnchorResolver`，~290 LOC）
`resolve_travel_anchors`、`resolve_fixed_place`、`resolve_meal_poi`、`meal_keywords`、`anchor_unavailable`；`_DINING_TERMS`。依赖：map_provider + cost_model + poi_quality.classify_place。

### 5. `route_resolution.py`（`RouteResolver`，~480 LOC）
`route`、`route_for_pair`、`recommend_transit_or_road`、`try_walking_route`、`route_cached`、`leg_from_route`、`transit_cost`、`transit_cost_source`；`_considered_modes`。依赖：route 三件套 + fallback_policy + provider_mode + planning.mode_recommendation/transit_mode/transport_strategy + cost_model.resolve_transit_cost。

### 6. `day_emitter.py`（`DayEmitter`，~290 LOC）
`emit_day`、`slot_from_item`、`activity_from_slot`、`fixed_slot_timing_error`、`fixed_schedules_on`、`meal_window_constraints`、`special_day_date`。依赖：注入 AnchorResolver + RouteResolver + cost_model + contracts。

### 7. `repair_policy.py`（纯函数模块，~110 LOC）
`mobility_repair_candidate`、`capacity_repair_candidate`、`can_relax_window_start` + 4 个常量（`_REDUCED_MOBILITY_MAX_HOP_METERS` / `_MAX_MOBILITY_REPAIR_ATTEMPTS` / `_WINDOW_RELAX_STEP_MINUTES` / `_WINDOW_RELAX_FLOOR_MINUTE`）。

**为什么不是更少/更多**：
- 不并入 Facade：`_emit_day`/路线/锚点三组若留在 Facade，Facade 回到 ~1900 LOC，失去意义。
- 不并入 DayEmitter：路线解析（含 fallback 决策、缓存、模式推荐）是独立领域，与"排程发射"（slot→activity/leg 投影）边界清晰。
- 不拆分 `_plan_with_skeleton`：见 §1 注。
- 模块总数 7（含 Facade）远小于"十几个"，每个模块单一职责、依赖单向。

---

## 拆分风险

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R1 | 行为漂移：移动中误改逻辑 | **高** | 逐方法 verbatim 搬运（git diff 应显示纯移动）；移动后跑全量回归（基线 2051 passed）比对 |
| R2 | `_FetchedPoi` 身份语义：`_plan_with_skeleton` 用 `id(fetched.poi)` 做对象身份（L927-930） | 中 | dataclass 原样搬到 poi_recall.py，import 引用；不动字段/构造 |
| R3 | 局部 import 循环：opening_hours 内 `daily_schedule.opening_availability_from_resolved` 等 | 中 | 保留函数内局部 import 原样（现状即局部，移动不改） |
| R4 | 测试面兼容：`AmapPlanningProvider._magnitude_for_poi`（2 个测试文件直调） | 低 | Facade 保留同名静态方法委托 PoiRecaller |
| R5 | 构造签名漂移：组合根 runtime.py:259 与 ~30 个测试文件位置参数/关键字参数 | **高** | `__init__` 签名一字不改；协作者在内部组装 |
| R6 | 协作者构造顺序/共享状态 | 低 | 协作者全部无状态（仅注入依赖），无共享可变状态；Facade 唯一持有 route_cache/route_calls |
| R7 | 私有方法被外部引用 | 低 | 已 grep 验证：测试仅经 `AmapPlanningProvider` 类入口，无 `provider._xxx` 直调；模块级私有函数无测试 import |

## Compatibility Strategy

1. **模块路径不变**：`trip_agent.infrastructure.amap.planning_provider` 保留，`AmapPlanningProvider` 类名不变（runtime.py:33 import 与 ~30 个测试 import 零改动）。
2. **构造签名不变**：`(map_provider, route_provider, transit_route=None, route_fallback=None, candidate_ranker=None, provider_mode=REAL_ONLY, fallback_policy=None)`——组合根 runtime.py:259 与全部测试实例化零改动。
3. **公共 API 不变**：`plan(command)` / `replan(command)` / `repair(request)`（PlanningProvider 协议要求，`WorkerRuntime.planning_provider: PlanningProvider` 类型约束）。
4. **测试面静态方法保留**：`AmapPlanningProvider._magnitude_for_poi`（委托 PoiRecaller.magnitude_for_poi），2 个测试文件零改动。
5. **私有方法自由迁移**：已 grep 证实无任何测试/生产代码直调 `provider._xxx` 或模块级私有函数（`_considered_modes`/`_entity_facts_for_pois` 等）。
6. **纯移动零改写**：除 import 调整与 `self._x` → `self._y.x` 调用点改写外，方法体逐字节保留。
7. **验证口径**：针对性单测（poi_recall/route/emit/repair 相关 ~20 个测试文件）→ 集成（test_planning_worker / test_amqp_worker / test_provider_modes / test_local_replanning）→ 全量回归（2051 passed / 42 skipped）→ ruff 全绿 → 单 commit。

---

## 验收标准（F-4.1 完成定义）

- [ ] `planning-provider-design.md` 已提交（docs commit）
- [ ] 6 个新模块 + Facade 落地，`AmapPlanningProvider` 仍为清晰 Facade/Orchestrator
- [ ] 模块依赖无环、单向（§Dependency Graph 目标形态）
- [ ] 针对性单测 + 集成 + 全量回归通过（2051 passed / 42 skipped 口径）
- [ ] ruff 全绿；`worker/runtime.py` 与全部测试零改动
- [ ] 单 refactor commit（跨文件同批，避免半绿窗口）
