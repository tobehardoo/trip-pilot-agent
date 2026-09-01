# 02 · 功能全盘盘点（Feature Inventory）

> 审计性质：PROJECT-WIDE AUDIT ONLY · 2026-08-31
> 方法：从 Controller 路由、Service、Python Worker/Agent/Tool、DB 表、Web 路由/组件、Event 契约、测试反向推导，而非仅凭 README。
> 状态分类：IMPLEMENTED / PARTIALLY_IMPLEMENTED / UI_ONLY / API_ONLY / DEAD / DUPLICATED / LEGACY / UNKNOWN

---

## 1. 功能总表（核心功能）

| 功能 | Web | Java | Python | DB | Event | Test | 当前状态 |
|---|---|---|---|---|---|---|---|
| 注册/登录/刷新令牌 | AuthView/useAuth | AuthController.java:28-47 + TokenService | — | user_account + refresh_token | — | AuthenticationFlowIntegrationTest | **IMPLEMENTED** |
| 创建旅行 | TripDashboard | TripController.java:33 + TripService(702) | — | trip | — | TripFlowIntegrationTest | **IMPLEMENTED** |
| 约束输入（目的地/日期/预算/人数/节奏） | ConstraintEditor.vue(249) + TripBoundaryEditor | TripConstraintValidator + TripService | dialog 槽位收集（dialog/service.py:546） | trip_constraint（jsonb） | — | TripFlowIntegrationTest | **IMPLEMENTED**（三入口：HTTP 表单 / dialog 向导 / Agent 槽位） |
| 候选召回 | — | — | planning_provider._collect_pois(:1732) + candidates.rank(:79) | — | — | test_b18_a_recall | **IMPLEMENTED** |
| 路线规划（确定性日程） | — | — | daily_schedule.plan_day(:527) + _emit_day(:1139) | itinerary_version/day | — | test_daily_schedule + golden_matrix | **IMPLEMENTED** |
| 预算约束 | TravelStyleEditor | — | budget_policy + cost_model | — | planning.completed evaluation | test_golden_scenarios 预算用例 | **PARTIALLY_IMPLEMENTED**（见 §3） |
| 时间窗/营业时间 | — | — | feasibility/rules/opening.py:153-362 | — | feasibility-report-v1 | test_opening_hours_rule | **IMPLEMENTED** |
| 必游点（must-visit） | ConstraintEditor | trip_constraint | feasibility/rules/coverage + must_visit_recall | — | — | test_must_visit_rule | **IMPLEMENTED** |
| 固定预约（固定安排） | — | — | daily_schedule 固定槽 | — | — | test_planning_context_v3 | **PARTIALLY_IMPLEMENTED**（依赖候选/时段数据，见 §3） |
| 不可行解释 | PlanningReviewPanel.vue(429) | PlanningReviewService(260) | feasibility/repair + evaluation/explanations | itinerary_feasibility_report(V33) | planning-review-required / feasibility-report-v1 | test_plan_evaluation_explanations + FeasibilityReportContractTest | **IMPLEMENTED** |
| 局部重规划（replan） | TripDetail 按钮 | PlanningTaskController replans:57 | worker/contracts.py:958 ReplanCommand | planning_task | planning-replan-command-v1/v2 | test_local_replanning + PlanningReviewFlowIntegrationTest | **IMPLEMENTED**（独立 MQ 命令，非 Agent 内 REPLAN） |
| 行程编辑（preview/apply/commit） | TripDetail.vue(1581) + useItineraryDraft | ItineraryController:96,114 + ItineraryEditRoutingCoordinator | candidate-validation command（契约 v1/v2） | itinerary_version | planning-candidate-validation-command | ItineraryEditFlowIntegrationTest | **IMPLEMENTED** |
| 回滚 | ItineraryVersionPanel | ItineraryVersionService(608) | — | itinerary_version（parent_version_id） | — | TripDetail 版本测试 | **IMPLEMENTED** |
| 分享 | TripDetail 分享入口 | ItineraryShareController:32-66 + PublicShareRateLimiter | — | itinerary_share(V24) | — | ItineraryShareFlowIntegrationTest | **IMPLEMENTED** |
| PDF 导出 | TripDetail | ItineraryExportService.java:110-177 renderPdf | — | — | — | ItineraryExportFlowIntegrationTest | **IMPLEMENTED**（文本行式简单 PDF） |
| ICS 导出 | TripDetail | ItineraryExportController:28 | — | — | — | 同上 | **IMPLEMENTED**（基础 ICS） |
| 攻略导入（URL/文本/MD/小红书/OCR） | GuideIntelligencePanel.vue(902) | GuideImportService(721) | guide_intelligence/service.py(899) + ocr.py + security_filter | guide_import/guide_fact/guide_source(V9/V18) | city-intelligence-refresh | GuideImportFlowIntegrationTest + test_security_filter | **IMPLEMENTED** |
| 城市情报/天气同步 | GuideIntelligencePanel | CityIntelligenceController:27,35 + CitySourceService | guide_intelligence/city_intelligence + qweather | city_source_registry(V20) | city-intelligence-refresh-command | CitySourceRegistryFlowIntegrationTest | **PARTIALLY_IMPLEMENTED**（前端绕过专用端点走攻略导入通道，见 02 §4.2） |
| Agent 对话（行程内） | planning-session/（UX3.0） | AgentDialogRunController:40,55 | agent/graph.py + agent_processor.py | agent_dialog_message(V41) + agent_run/step | agent-*-event-v1 | test_agent_loop + agent-workspace.spec.ts | **IMPLEMENTED**（双通道，见 §4.1） |
| Agent 创建旅行（对话建行程） | TripDashboard「AI 帮我规划」 | TripAgentCreateController:66,79 + AgentDialogCommandService | dialog/service.py（HTTP 向导） | agent_dialog_message | agent.start 命令 | test_agent_dialog | **IMPLEMENTED**（LEGACY 通道，UX3.0 已将其降级为会话输入之一） |
| 知识库/RAG 检索 | 无 UI | application/knowledge 空壳（仅 package-info） | retrieval/service.py + knowledge CLI | knowledge 向量表（pgvector） | — | test_knowledge_* | **API_ONLY / 部分 DEAD**（无 Java 端点、无前端 UI；Python 侧完整） |
| 城市资料源管理 | 无 UI | CitySourceController:28,37 | acquisition/（离线采集 CLI） | city_source_registry | city-intelligence-refresh | test_acquisition_* | **API_ONLY / DEAD**（前端未用，见 02 §4.3） |
| 内部诊断（失败重试） | 无 UI | InternalPlanningDiagnosticsController:33,42 | — | planning_task | — | InternalPlanningDiagnosticsIntegrationTest | **API_ONLY**（permitAll + header token 自校验） |
| 规划进度 SSE | PlanningProgress.vue | PlanningTaskEventController:27 + EventHub(151) | worker/progress.py | planning_task_event | planning-progress-event | PlanningProgress.test.ts | **IMPLEMENTED** |
| 版本 diff/对比 | ItineraryVersionPanel | ItineraryController versions/diff | — | — | — | TripDetailNavigation.test | **IMPLEMENTED** |
| 行程归档/搜索 | TripDashboard | TripController archive/search:60,80 | — | trip（V25 索引） | — | TripArchiveAndSearchIntegrationTest | **IMPLEMENTED** |
| 天气与行李 | TripWeatherTimeline.vue(240) | — | weather_policy + guide_intelligence/qweather | — | — | weather-window.spec.ts | **PARTIALLY_IMPLEMENTED**（天气事实可用；行李输入未落地） |

## 2. 按 README 宣称 vs 实际

| README 宣称（README.md:19-27） | 实际状态 |
|---|---|
| Constraint-driven planning | ✅ 真实（trip_constraint + dialog 槽位 + Agent slots 三套输入） |
| Executable itinerary generation | ✅ 真实（确定性日程 + 硬校验） |
| Multi-source guide intelligence | ✅ 真实（URL/文本/MD/小红书/OCR + 事实校验链路） |
| Multi-mode transport（WALKING/TRANSIT/TAXI/DRIVING/AUTO） | ⚠️ 部分真实（TRANSIT 仅 Planner 生成真实；manual-edit TRANSIT 是本地估计，README.md:184 自述；AUTO 仅请求模型） |
| Feasibility validation + 不可行解释 | ✅ 真实（11 规则 + repair + feasibility-report 契约） |
| Editable & versioned itineraries | ✅ 真实（版本树 + diff + 回滚） |
| Real asynchronous workflow（Outbox→RabbitMQ→Python→Event→SSE） | ✅ 真实且是系统最强部分 |
| **OR-Tools 优化**（README.md:39,76 与 技术栈表） | ❌ **未落地**：pyproject.toml:12 声明，全库零引用（见 01 §4） |

## 3. 关键功能深挖

### 3.1 预算约束 —— PARTIALLY_IMPLEMENTED（P1 观察）
- 预算参与交通策略（transport_strategy.py:9-15 规则 3「budget beats comfort」）、总成本硬校验（BUDGET_LIMIT）——**是真的**。
- 但 **餐食预算参数是死参数**：`daily_schedule.py:212 budget_per_person` 定义并一路透传（:431,:451,:464,:541,:605,:694,:715），`planning_provider.py` 的 `plan_day` 调用点不传该参数（已 grep 核验：planning_provider 中无 budget_per_person 引用）→ 恒 None，餐厅选择零成本参与。
- **住宿成本是常数估算**：`cost_model.py:56 DEFAULT_ACCOMMODATION_PER_NIGHT = Decimal("300.00")`，来源类型 `CITY_ESTIMATE`（:38）——不做选址、不看真实价格。

### 3.2 固定预约 —— PARTIALLY_IMPLEMENTED
- 固定安排进入 planning context（test_planning_context_v3 覆盖），日程布局可锚定固定槽；但依赖候选 POI 的真实营业/时段数据，数据缺失时降级 UNKNOWN（fail-closed 设计，符合 README 宣称，但能力边界低于"固定预约"的完整语义）。

## 4. 冗余/遗留功能

### 4.1 双对话链路（DUPLICATED / LEGACY，P1）
| 通道 | 运行时 | 传输 | 前端载体 | 状态 |
|---|---|---|---|---|
| 创建模式向导 | `dialog/service.py`（HTTP 槽位向导，Redis 7 天） | 同步 HTTP `POST /api/agent/dialogue` | TripDashboard 抽屉（TripAgentCreateController:66,79） | **LEGACY**（UX3.0 文档 §2.1 自述"未迁移"） |
| 行程内 Agent | `agent/graph.py` LangGraph + `agent_processor.py` | Outbox→MQ→事件→SSE | planning-session/（UX3.0） | **IMPLEMENTED（当前主线）** |
| 确定性规划管线 | `worker/processor.py` | 独立 SSE（/api/planning-tasks/{id}/events） | PlanningProgress.vue | **IMPLEMENTED（与 Agent 工作台分离）** |

### 4.2 城市情报双通道（DUPLICATED，P2）
- 后端有专用端点 `GET /api/trips/{tripId}/city-intelligence` + `POST /refreshes`（CityIntelligenceController.java:27,35），**前端未调用**；前端天气/情报同步走 `createGuideImport(CITY_INTELLIGENCE)`（TripDetail.vue:716-725）复用攻略导入通道。两套能力并存，前端只用其一。

### 4.3 前端未消费的后端能力（API_ONLY，P3）
- `GET /itinerary/versions/{versionId}`（ItineraryController.java:68）
- `GET/PUT /api/city-sources`（CitySourceController.java:28,37）
- `GET /api/users/me`（UserController.java:21）、`GET /api/health`
- `/api/internal/diagnostics/*`（内部诊断）

### 4.4 死路由（DEAD，P2）
- 前端 `trip-versions` 路由（router/index.ts:31）不在 `lib/routes.ts` 的 `AppRoute` 联合类型中，TripWorkspace 模板无对应渲染分支（TripWorkspace.vue:1314-1426 仅有 trip-list/trip-create/trip-detail/trip-plan/planning-session-create 五个分支）→ 落入 404 分支。

## 5. 功能状态统计

| 分类 | 数量 | 代表 |
|---|---|---|
| IMPLEMENTED | 20 | 认证/建行程/约束/候选/日程/时间窗/必游点/不可行解释/replan/编辑/回滚/分享/PDF/ICS/攻略导入/Agent 行程内对话/SSE/diff/归档/天气事实 |
| PARTIALLY_IMPLEMENTED | 3 | 预算（餐食死参数+住宿常数）、固定预约、多模式交通（TAXI/AUTO/手动 TRANSIT 局限） |
| API_ONLY | 4 | 知识库检索（无 Java 端点）、城市资料源、用户信息、内部诊断 |
| DUPLICATED | 3 | 双对话链路、城市情报双通道、前端三套 itinerary 模型 |
| DEAD | 2+ | trip-versions 死路由、ConstraintPanel.vue 孤儿组件、契约 legacy 目录 |
| LEGACY | 2 | 创建模式 HTTP 向导（dialog/service.py）、planning-completed-event v1-v8 冻结契约 |

> 结论：**不存在"UI 存在但后端完全无能力"的假功能**（Web 审计已逐端点点验，前端全部调用点后端均存在）。冗余集中在"同一能力的多套实现/多套通道"，而非缺失。
