# F-4.0 收敛基线 Inventory

- 基线 HEAD：`cdee033`（F-3d 验收后，工作树干净）
- 方法：Evidence First——所有结论基于当前 HEAD 实扫（grep / vulture / wc），不沿用旧报告
- 扫描日期：2026-09-01

---

## A. Repository Inventory

### A.1 文件数（排除 node_modules / .venv / .git / 构建产物）

| 类别 | 数量 |
|---|---|
| Python 生产（apps/agent-service/src） | 147 |
| Python 测试（apps/agent-service/tests） | 151 |
| Java 生产+测试（apps/travel-server/src） | 242 |
| TS/Vue（apps/web/src） | 61 |
| Markdown（docs/） | 110 |
| Markdown（全仓） | 166 |
| Docker/Compose | 6 |
| CI workflow | 1 |

### A.2 大文件三档（生产代码）

**Python（>500 LOC）**

| 文件 | LOC | 档位 | 备注 |
|---|---|---|---|
| infrastructure/amap/planning_provider.py | 861 | **>800** | ✅ F-4.1 已拆分（83f62c0）：Facade + 6 协作者（poi_recall/opening_hours/anchor_resolution/route_resolution/day_emitter/repair_policy，总计 2759） |
| worker/contracts.py | 1747 | **>1500** | 消息模型聚合（F-4 规划 §四.2 已列拆分子目标） |
| dialog/service.py | 1187 | >800 | 对话服务 |
| planning/daily_schedule.py | 1075 | >800 | 确定性日排程（收敛计划 §四 明示"不拆"） |
| acquisition/repository.py | 984 | >800 | 采集仓库（DORMANT，不拆） |
| agent/graph.py | 947 | >800 | Agent 编排 |
| guide_intelligence/trusted_facts.py | 917 | >800 | 可信事实四阶段拆（F-4 规划 §四.5） |
| guide_intelligence/service.py | 899 | >800 | |
| agent/tools.py | 865 | >800 | Agent 工具 |
| worker/amqp.py | 745 | >500 | F-3b 已拆分，余量合理 |
| worker/agent_processor.py | 648 | >500 | |
| worker/processor.py | 638 | >500 | |
| evaluation/rules.py | 627 | >500 | |
| feasibility/repair/engine.py | 614 | >500 | |
| providers/map.py | 586 | >500 | |
| application/replan_service.py | 521 | >500 | |

**Java（>500 LOC）**

| 文件 | LOC | 档位 | 备注 |
|---|---|---|---|
| itinerary/ItineraryService.java | 2038 | **>1500** | F-4 规划 §四.3（编辑引擎+版本工厂分离） |
| planning/PlanningTaskService.java | 1047 | >800 | |
| infrastructure/mq/PlanningCompletedEventParser.java | 873 | >800 | F-3c 后仍大，事件契约解析 |
| guide/GuideImportService.java | 721 | >500 | |
| trip/TripService.java | 699 | >500 | |
| itinerary/ItineraryVersionService.java | 607 | >500 | |
| itinerary/ItineraryMapper.java | 552 | >500 | |
| planning/PlanningCompletionService.java | 549 | >500 | |

**Web（>300 LOC）**

| 文件 | LOC | 备注 |
|---|---|---|
| lib/api.ts | 1341 | API 客户端 + DTO（F-4 规划 §四.3 提及 ~1300 行 DTO） |
| components/GuideIntelligencePanel.vue | 873 | 大组件（F-2 已并测试，组件本体待收敛） |
| lib/feasibility.ts | 863 | Java FeasibilityReport 手写镜像（F-0 已知，标注保留） |
| workspace/stores/tripStore.ts | 418 | |
| components/agent-workspace/useAgentWorkspace.ts | 364 | |

---

## B. Architecture Inventory

### B.1 Python 依赖方向（实扫复验）

| 检查 | 结果 | 证据 |
|---|---|---|
| providers → infrastructure 反向依赖 | ✅ 无 | `providers/` 全量 grep `trip_agent.infrastructure` 0 命中（F-3a 修复有效） |
| planning → infrastructure | ✅ 无 | `planning/` 0 命中 |
| evaluation → persistence/acquisition | ✅ 无 | `evaluation/` 0 命中 |
| domain → infrastructure | ✅ 无 | `domain/` 0 命中 |
| **agent → infrastructure（具体实现）** | ⚠️ **1 处** | `agent/itinerary_builder.py:27,134-135` import 并直接实例化 `DemoPlanningProvider`（构造默认值硬编码具体实现，绕过组合根；类型标注为具体类而非 `PlanningProvider` 协议） |
| worker → planning（业务决策） | ⚠️ 3 处 import | `worker/processor.py:35-37` 引用 `planning.cost_model` / `trusted_context` / `validation_projection`——需评估是否属编排职责 |

### B.2 Java 分层

| 检查 | 结果 | 证据 |
|---|---|---|
| Controller 直接注入 MyBatis Mapper | ✅ 无 | 全仓 Controller grep Mapper 仅命中 `ItineraryController.java` 的 Jackson `ObjectMapper`（JSON 工具，误报） |
| 空壳层（application/identity、application/knowledge、infrastructure/integration） | ✅ 已不存在 | find 0 命中（3.0 审计项已清理） |
| domain 包 | 待 F-4.2 细查 | — |

### B.3 Web

| 检查 | 结果 | 证据 |
|---|---|---|
| api.ts 单文件 DTO 聚合 | ⚠️ 1341 LOC | F-0 已标注（收敛需 codegen，超本轮范围） |
| feasibility.ts 手写 Java 镜像 | ⚠️ 863 LOC | F-0 已标注保留 |

---

## C. Dead Architecture Inventory（Evidence Chain 复验）

> 原则：删除前必须确认 Definition→References→Runtime→Tests→External Consumer。下表"当前状态"均为本次实扫结果。

| ID | 问题 | 文件 | 证据 | 当前状态 | 建议 |
|---|---|---|---|---|---|
| D-1 | 死路由 trip-versions | router/index.ts | 3.0 审计 §1.5；本次 grep `versions` 0 命中 | ✅ **已清理** | 无需动作 |
| D-2 | Java 空壳层 | application/* | 3.0 审计 §1.3 | ✅ **已清理** | 无需动作 |
| D-3 | ConstraintPanel.vue 0 引用 | apps/web/src/components/agent-workspace/ConstraintPanel.vue | 3.0 审计 §1.4；本次 src+tests grep 仅文件自身 | ⚠️ **仍存活** | F-4.3 删除（P3） |
| D-4 | ortools 死依赖 | pyproject.toml | 3.0 §1.7 / 4.0 复验：pyproject 已无 ortools；本次全仓 grep 0 命中 | ✅ **依赖已移除** | README 失实声明待 F-4.5 修 |
| D-5 | planning_task 死状态 CREATED/RETRYING/CANCELLING | V4 migration + PlanningTaskMapper | SQL CHECK 允许 9 值（V4__create_planning_and_outbox_tables.sql:17-22）；Java 实际写入点仅 QUEUED/RUNNING/WAITING_USER（Mapper:145,156-157）+ SUCCEEDED/FAILED/CANCELLED；CREATED/RETRYING/CANCELLING 仅出现在查询条件（Mapper:170,199）与注释（PlanningTaskService.java:663） | ⚠️ **仍存活** | F-4.3 评估收紧 CHECK 约束（P2，涉及 migration，谨慎） |
| D-6 | REPLAN 声明可达性 | agent/graph.py | 3.0 §1.8：REPLAN 在 DECISION_SCHEMA（graph.py:574,594）为合法策略，tools.py 无 replan 工具；但 graph.py:776-784 有 E-1 有界反射预算守卫"neither decider may REPLAN without end" | ⚠️ **语义已变，需 F-5.2 专项核验** | 不在 F-4 删（可能是设计：REPLAN 由外部 replan command 触发），F-5 审计判断 |
| D-7 | MealDemand.budget_per_person 死参数 | daily_schedule.py:212,431,451,464,541,605,694,715 | 3.0 §2.3：定义+透传但调用点不传 → 恒 None | ⚠️ 待复验（行号可能漂移） | F-4.3 确认后删（P2） |
| D-8 | 终态集合双源 | PlanningTaskEventHub.java:112-116 vs PlanningTaskEventStreamService.java:15-16 | 3.0 §2.4 | ⚠️ 待复验 | F-4.3 合并（P2） |
| D-9 | TripSkeleton docstring 过时 | planning/trip_skeleton.py:22-24 | 3.0 §2.1："has not entered worker runtime" 不准确（processor.py:16-17,151-173 已接线） | ⚠️ 待复验 | F-4.4 修正注释（P3） |
| D-10 | DecisionTrace docstring 过时 | planning/decision_trace.py:7-9 | 3.0 §2.2："so-far-unused vocabulary" 不准确（planning_provider.py:423 已构建 traces） | ⚠️ 待复验 | F-4.4 修正注释（P3） |
| D-11 | vulture unused variable ×7 | failure_policy.py:275, dialog/service.py:999, redis_cache.py:9, agent_processor.py:110, amqp.py:82,84,93 | vulture 100% confidence | ⚠️ 局部变量 | F-4.4 顺手清理（P3） |
| D-12 | API_ONLY 端点（无 UI 消费） | ItineraryController:68, CityIntelligenceController:27,35, CitySourceController:28,37, UserController:21, HealthController:11, InternalPlanningDiagnosticsController:33,42 | 3.0 §3 | ⚠️ 功能未死、UI 闲置 | 保留（内部运维/未来），不做动作，F-5.6 记录 |

---

## D. 已知非问题（本轮已排除）

| 项 | 结论 |
|---|---|
| F-3a/F-3b/F-3c/F-3d 目标 | 全部有效（F-3 验收文档 + 本 Inventory 复验） |
| 死函数/死类（Python 生产） | vulture ≥70% 置信度 0 命中（仅局部变量） |
| Controller→Mapper 泄漏 | 无（唯一命中为 Jackson ObjectMapper 误报） |
| 循环依赖 | 本轮扫描未见（F-3b 已消除 amqp↔runtime） |

---

## E. F-4 修改范围建议（供 F-4.1~F-4.5 排序）

1. **F-4.1**：`planning_provider.py`（2450）——按职责拆（候选边界见下节）——✅ 已完成（83f62c0，Facade 861 + 6 协作者）；`ItineraryService.java`（2038）——编辑引擎/版本工厂分离（收敛计划 §四.3）
2. **F-4.2**：`agent/itinerary_builder.py` 的 DemoPlanningProvider 硬编码 → 组合根注入（D-13 新发现）；worker/processor.py 对 planning 的 3 处 import 边界评估
3. **F-4.3**：D-3（ConstraintPanel.vue）、D-5（死状态，谨慎）、D-7（budget_per_person）、D-8（终态双源）、D-11（unused variable）
4. **F-4.4**：D-9/D-10（过时 docstring）、统一风格
5. **F-4.5**：README OR-Tools 失实声明（D-4 关联）、过期文档清理

### E.1 planning_provider.py 职责地图（F-4.1 前置）

`AmapPlanningProvider`（class 定义于 L358，核心方法 386-2450）实载 8 组职责：

| 职责组 | 方法（行号） | LOC 估算 |
|---|---|---|
| 顶层编排 | plan(:386), _plan_with_skeleton(:391-953) | ~570 |
| POI 收集/候选 | _collect_pois(:1947), _poi_from_ref(:974), _to_candidate(:996), _magnitude_for_poi(:1031), _is_must_visit_poi(:953), _is_complex_experience(:1125) | ~250 |
| 事实/证据构建 | _entity_facts_for_pois(:204), _amap_opening_value(:276), _non_weather_guide_statements(:317), _with_opening_availability(:1060) | ~180 |
| 日排程发射 | _emit_day(:1260-1517), _fixed_schedules_on(:1130), _slot_from_item(:1539), _activity_from_slot(:1564), _meal_window_constraints(:1035), _special_day_date(:1239) | ~450 |
| 路线/交通 | _route(:2030), _route_for_pair(:2077), _route_cached(:2413), _leg_from_route(:1616), _transit_cost(:2005), _transit_cost_source(:2019), _recommend_transit_or_road(:2276), _try_walking_route(:2390), _mobility_repair_candidate(:1156) | ~520 |
| 锚点/餐解析 | _resolve_travel_anchors(:1843), _resolve_fixed_place(:1673), _resolve_meal_poi(:1701), _meal_keywords(:1806), _anchor_unavailable(:1925) | ~260 |
| 修复/重规划 | repair(:1830), replan(:1817), _capacity_repair_candidate(:1176), _can_relax_window_start(:1206) | ~120 |
| 约束/辅助 | _considered_modes(:140), _avoid_provider_ids(:325), _titles_with_reason(:336), _resolver_clock(:188), _fixed_slot_timing_error(:1517) | ~100 |

> 注：以上为首次粗扫（方法级边界），精确依赖图与拆分设计在 F-4.1 的 `planning-provider-design.md` 输出。

---

## F. 基线快照（F-4 结束后对比用）

- Python 全量测试：2051 passed / 42 skipped（F-3c 验收口径）
- Java mvn test：626 passed（F-3c 验收口径）
- ruff：全绿
- Web vitest：29 文件 / 307 用例（F-2d 验收口径，F-4 前复核一次）
