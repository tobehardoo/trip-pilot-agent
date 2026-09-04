# 03 · 代码复杂度与臃肿量化审计

> 审计性质：PROJECT-WIDE AUDIT ONLY · 2026-08-31
> 方法：脚本统计（临时分析脚本 output/audit/method_stats.py，只读）+ 人工复核关键文件。行号均为实测。

---

## 1. 规模总量（精确，awk 汇总）

| 模块 | 文件数 | LOC |
|---|---|---|
| Java main | 181 | 42,488 |
| Java test | 71 | 39,044 |
| Python src | 143 | 70,708 |
| Python tests | 138 | 86,036 |
| Python benchmarks | 5 | 1,620 |
| Web src+e2e（.vue 18,968 + .ts 17,866） | 60+5 | 36,834 |
| Web tests | 53 | 21,778 |
| scripts/*.py | 20 | 10,308 |

## 2. 结构声明统计

### 2.1 Java（src/main，声明级 grep 计数）
- class **104** · record **267** · interface **27** · enum **9**
- 命名类别出现次数（类名/引用含后缀）：`Service` 62 · `Mapper` 32 · `Client` 15+ · `Controller` 36(RestController) · `Parser` 14 · `Listener` 12 · `Hub` 2（SSE）· `Coordinator` 1（ItineraryEditRoutingCoordinator）· `Facade/Manager/Helper/Utils/Processor/Handler` **均为 0** —— Java 侧未出现"Manager/Facade 滥用"，这是事实。

### 2.2 Python（src）
- 模块文件数：acquisition **17** · guide_intelligence **16** · planning **16** · providers **14** · agent **9** · worker **8** · retrieval **7** · feasibility **8**（另有 rules/ 5 + repair/ 4）· dialog **6** · evaluation **6** · routes **3** · application **3** · workflow **2** · domain **2** · infrastructure 1

## 3. Top 20 最大文件

### 3.1 Java main（实测 wc -l）
| # | 文件 | 行数 |
|---|---|---|
| 1 | itinerary/ItineraryService.java | **2,044** |
| 2 | planning/PlanningTaskService.java | **1,051** |
| 3 | infrastructure/mq/PlanningCompletedEventParser.java | **1,004** |
| 4 | guide/GuideImportService.java | 721 |
| 5 | trip/TripService.java | 702 |
| 6 | itinerary/ItineraryVersionService.java | 608 |
| 7 | planning/PlanningCompletionService.java | 554 |
| 8 | itinerary/ItineraryMapper.java | 552 |
| 9 | infrastructure/mq/PlanningReviewRequiredEventParser.java | 495 |
| 10 | planning/PlanningTaskOutcomeReadModel.java | 410 |
| 11 | guide/GuideImportMapper.java | 399 |
| 12 | planning/PlanningContextSnapshotService.java | 389 |
| 13 | infrastructure/mq/PlanningCompletedEvent.java | 337 |
| 14 | feasibility/FeasibilityReportValidator.java | 333 |
| 15 | itinerary/ItineraryEditRoutingCoordinator.java | 312 |
| 16 | trip/TripAgentCreateController.java | 262 |
| 17 | infrastructure/mq/RabbitMessagingConfiguration.java | 261 |
| 18 | planning/PlanningReviewService.java | 260 |
| 19 | export/ItineraryExportService.java | 260 |
| 20 | agentdialog/AgentDialogCommandService.java | ~250 |

### 3.2 Python src（实测 wc -l）
| # | 文件 | 行数 |
|---|---|---|
| 1 | infrastructure/amap/planning_provider.py | **2,331** |
| 2 | worker/contracts.py | **1,860** |
| 3 | dialog/service.py | **1,205** |
| 4 | worker/amqp.py | **1,076** |
| 5 | planning/daily_schedule.py | **1,061** |
| 6 | acquisition/repository.py | 984 |
| 7 | guide_intelligence/trusted_facts.py | 917 |
| 8 | guide_intelligence/service.py | 899 |
| 9 | agent/tools.py | 765 |
| 10 | worker/processor.py | 673 |
| 11 | evaluation/rules.py | 627 |
| 12 | feasibility/repair/engine.py | 614 |
| 13 | worker/agent_processor.py | 602 |
| 14 | providers/map.py | 586 |
| 15 | application/replan_service.py | 521 |
| 16 | agent/persistence.py | ~500 |
| 17 | feasibility/validator.py | ~480 |
| 18 | planning/context_view.py | ~470 |
| 19 | guide_intelligence/security_filter.py | ~300 |
| 20 | planning/transport_strategy.py | ~260 |

### 3.3 Web（实测）
| # | 文件 | 行数 |
|---|---|---|
| 1 | components/TripDetail.vue | **1,581** |
| 2 | pages/TripWorkspace.vue | **1,445** |
| 3 | components/GuideIntelligencePanel.vue | **902** |
| 4 | components/TripDashboard.vue | 527 |
| 5 | components/PlanningReviewPanel.vue | 429 |
| 6 | lib/api.ts | ~1,330（约 40 个 API 调用 + SSE 客户端） |
| 7 | components/planning-session/TripSessionView.vue | 351 |
| 8 | components/ItineraryVersionPanel.vue | 333 |
| 9 | components/TripMap.vue | 308 |
| 10 | components/ConstraintEditor.vue | 249 |

## 4. Top 20 最大方法/函数（脚本实测）

### 4.1 Java main（≥5 行的方法共 452 个）
| 行数 | 位置 | 方法 |
|---|---|---|
| 119 | ItineraryController.java:22-140 | 类级 @RequestMapping 块（含 8 端点） |
| 109 | feasibility/FeasibilityReportValidator.java:45-153 | validate(FeasibilityReport) |
| 103 | planning/PlanningCompletionService.java:80-182 | handleInScope(PlanningCompletedEvent) |
| 90 | mq/PlanningCompletedEventParser.java:469-558 | validateEvaluation |
| 86 | mq/PlanningCompletedEventParser.java:78-163 | validateJsonTypes |
| 79 | guide/GuideImportPersistenceService.java:103-181 | persistTrustedPipeline |
| 79 | cityintelligence/CityIntelligenceRefreshProcessor.java:44-122 | process |
| 77 | mq/PlanningCompletedEventParser.java:599-675 | validateProviderProvenance |
| 68 | export/ItineraryExportService.java:110-177 | renderPdf |
| 68 | cityintelligence/CityIntelligencePrewarmService.java:77-144 | request |
| 67 | mq/PlanningReviewRequiredEventParser.java:89-155 | validateJsonTypes |
| 65 | planning/PlanningProgressService.java:40-104 | handle |
| 65 | itinerary/ItineraryVersionService.java:246-310 | readOwned |
| 65 | mq/PlanningReviewRequiredEventParser.java:331-395 | validateDay |
| 64 | mq/PlanningCompletedEventParser.java:295-358 | validateTransitLegTypes |
| 57 | planning/PlanningReviewService.java:82-138 | handleInScope |
| 56 | place/PlaceSuggestionService.java:92-147 | search |
| 55 | planning/PlanningTaskService.java:650-704 | cancel |
| 52 | guide/GuideImportService.java:82-133 | create |
| — | — | 其余 <50 行 |

> 观察：Java 侧**最大方法集中在事件解析/校验器**（Parser/Validator 天然冗长），业务 Service 以"长类多方法"而非"单方法超长"为主。

### 4.2 Python src（≥5 行的函数共 797 个）
| 行数 | 位置 | 函数 |
|---|---|---|
| **449** | infrastructure/amap/planning_provider.py:381-829 | `_plan_with_skeleton`（主规划管线） |
| 210 | feasibility/rules/opening.py:153-362 | `assess_opening_hours` |
| 175 | agent/tools.py:551-725 | `build_tool_specs`（9 工具声明） |
| 165 | feasibility/rules/meal.py:53-217 | `assess_meal_window` |
| 145 | feasibility/rules/continuity.py:224-368 | `assess_cross_day_continuity` |
| 142 | feasibility/rules/duration.py:75-216 | `assess_visit_duration` |
| 114 | dialog/service.py:903-1016 | `_ground_pending` |
| 107 | guide_intelligence/api.py:272-378 | `_to_guide_response` |
| 105 | feasibility/rules/continuity.py:79-183 | `assess_route_endpoint_continuity` |
| 99 | providers/_amap_route.py:57-155 | `get_route` |
| 98 | guide_intelligence/security_filter.py:131-228 | `_check_rules` |
| 96 | providers/map.py:259-354 | `search_pois` |
| 96 | providers/_amap_transit.py:67-162 | `get_route` |
| 88 | worker/agent_processor.py:230-317 | `handle_resume` |
| 87 | infrastructure/demo/planning_provider.py:128-214 | `_day_skeleton` |
| 82 | guide_intelligence/quality.py:55-136 | `compute_guide_quality` |
| 82 | feasibility/rules/core.py:235-316 | `assess_duplicate_poi` |
| 77 | agent/graph.py:135-211 | `decide`（规则降级决策器） |
| 75 | dialog/service.py:674-748 | `_apply_message` |
| 75 | dialog/service.py:599-673 | `_apply_option` |

> 观察：Python 侧**超长函数集中在 feasibility rules 与规划编排**；`_plan_with_skeleton` 449 行是单函数嵌套最深的点（provider+编排+决策追踪混在一起，context_view.py:9-10 已自述迁移过一批）。

## 5. 臃肿 TOP 发现（带证据）

| # | 发现 | 证据 | 分类 |
|---|---|---|---|
| 1 | **ItineraryService 2044 行巨型类**，其中约 60%（:867-2043）为私有 record/内部类 | ItineraryService.java:867-2043 | DESIGN_DEBT / P1 |
| 2 | **PlanningTaskService 1051 行**，约 200 行私有 record DTO（:858-1050） | PlanningTaskService.java:858-1050 | DESIGN_DEBT / P1 |
| 3 | **PlanningCompletedEventParser 1004 行**，含 v1/v6/v8 不可达分支：外层只接受 v9/10/11（:381-383），但 :393、:477-481、:605-607、:871 仍保留旧版本校验 | PlanningCompletedEventParser.java:381-383 vs :393/:477/:605/:871 | CODE_SMELL / P2（死代码见 08） |
| 4 | **planning_provider.py 2331 行**：provider + 编排 + 决策追踪三职责混居 | infrastructure/amap/planning_provider.py | CODE_SMELL / P2 |
| 5 | **worker/contracts.py 1860 行**：同文件并存 PlanningCompletedEvent V1/V9/V10/V11 四个版本类（:1163/:1221/:1259/:1277）与 PlanningFailedPayload V1/V2（:1393/:1413） | worker/contracts.py | CODE_SMELL / P2 |
| 6 | **TripWorkspace(1445) + TripDetail(1581) 双超级组件**：TripDetail props 超 40 个（:75-125），靠 prop-drilling 通信 | TripWorkspace.vue + TripDetail.vue | DESIGN_DEBT / P1 |
| 7 | **两个 SSE EventHub 近乎逐字重复**：PlanningTaskEventHub(151) vs AgentDialogEventHub(145)，结构一致（ConcurrentHashMap+monitor 数组+subscribe/publishAfterCommit/send/remove） | PlanningTaskEventHub.java:22-151 vs AgentDialogEventHub.java:27-145 | DUPLICATED / P2 |
| 8 | **RabbitMessagingConfiguration 手工 new 依赖**（:216-231 手工构造 ItineraryCurrentVersionProvider/PlanningOutcomeGuard/FeasibilityEntityRefMapper bean，绕过组件扫描） | RabbitMessagingConfiguration.java:216-231 | CODE_SMELL / P3 |
| 9 | **循环依赖靠 @Lazy 掩盖**：ItineraryService.java:52 ↔ PlanningTaskService.java:63 互相注入 | ItineraryService.java:52 / PlanningTaskService.java:63 | ARCHITECTURE_RISK / P2 |
| 10 | **dialog/service.py 1205 行**：向导状态机 + 解析 + grounding + 存储四职责 | dialog/service.py | CODE_SMELL / P2 |

## 6. 复杂度结构结论

- **Java 侧没有 Manager/Facade 滥用**（计数为 0），风险是"少而大"：2 个 1000+ 行 Service + 2 个 1000 行 Parser。
- **Python 侧风险是"大文件多"**：4 个 1000+ 行文件（planning_provider/contracts/dialog/amqp/daily_schedule），且 contracts.py 的"按版本复制类"是契约演进的错误姿势。
- **Web 侧风险是双超级组件 + 三套类型模型**（详见 05）。
- 空壳层：Java 的 `application/identity`、`application/knowledge`、`domain`、`infrastructure/persistence/*`（除 UuidTypeHandler）仅含 package-info.java（DDD 分层声明未兑现）—— OBSERVATION / P2。
