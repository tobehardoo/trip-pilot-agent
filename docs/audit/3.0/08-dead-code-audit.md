# 08 · 死代码 / 过期实现审计

> 审计性质：PROJECT-WIDE AUDIT ONLY · 2026-08-31
> 方法：静态引用 + 调用关系 + 路由 + 配置 + Git 状态逐项验证；不凭"看起来没用"判死。

---

## 1. 已证实的死代码（DEAD）

### 1.1 Java：PlanningCompletedEventParser 旧版本校验分支不可达（P2）
- 入口只接受 v9/v10/v11：`PlanningCompletedEventParser.java:381-383`（`supportedVersions`）
- 但文件内保留旧版本校验：`:393 schemaVersion()==1` 分支、`:477-481` 接受 v6/v8 evaluation 字段、`:605-607`、`:871` 旧结构校验 —— 全部不可达。
- 文件 1004 行，其中约 30-40% 是死分支。同类：PlanningReviewRequiredEventParser.java 也有 v1 兼容残留（:89-155）。

### 1.2 contracts/messaging/legacy/ 目录（P3）
- 含 planning-completed-event-v1/v2/v3 与 planning-create-command-v1 及 legacy/README.md。
- 生产代码零消费（契约 README 自述 "legacy v1–v3 生产代码零消费"；Java/Python grep 无引用）。
- `apps/travel-server/contracts/messaging/legacy/` 另有同名副本目录。

### 1.3 Java 空壳层（P2）
- `application/identity`、`application/knowledge`、`domain`、`infrastructure/integration`、`infrastructure/persistence/{identity,itinerary,knowledge,mq,planning,trip}` —— **全部仅含 package-info.java**（DDD 分层声明未兑现）。
- `infrastructure/persistence/` 下唯一真实类是 `persistence/UuidTypeHandler.java`，且它放在 `io...trippilot.persistence`（不是 infrastructure/persistence），包结构错位。

### 1.4 前端 ConstraintPanel.vue（P3）
- `apps/web/src/components/agent-workspace/ConstraintPanel.vue`：全 src 0 引用（已全目录 grep 核验）。Agent UX 2.0 遗留组件，3.0 的 ConstraintBoard 取代了它。

### 1.5 前端 trip-versions 路由（P2）
- `router/index.ts:31` 定义 `/trips/:tripId/versions`，但 `lib/routes.ts:1-41` 的 `AppRoute` 联合类型不含它；TripWorkspace.vue:1314-1426 无对应渲染分支 → 落入 404 分支。

### 1.6 数据库死状态值（P1，与 06 交叉）
- planning_task 的 CREATED / RETRYING / CANCELLING / STALE：**全库无任何写入点**（Java 只写 6 个值，Python 只发事件）；仅出现在 SQL 查询（PlanningTaskMapper.java:199,217）与一处注释（PlanningTaskService.java:663）。

### 1.7 未使用依赖声明（P1）
- `pyproject.toml:12` `ortools==9.14.6206`：全库零引用（src+tests+benchmarks grep 无 import）。README.md:39,76 宣称 "OR-Tools 优化"，实际无求解器。
- 附带：`worker/amqp.py:151` `CONSTRAINTS_SOLVING` 进度阶段是装饰性的（无求解器阶段）。

### 1.8 Agent REPLAN 策略声明未实现（P1，与 04 交叉）
- `graph.py:227` DECISION_SCHEMA 枚举含 REPLAN、`:245` 合法策略集、`:346` prompt 引导模型声明 REPLAN —— 但 tools.py:551-723 无 replan 工具，循环内 REPLAN 不可达。

---

## 2. 已证实的过期实现（STALE，非完全死）

### 2.1 TripSkeleton docstring 过时（P3）
- `planning/trip_skeleton.py:22-24` 自述 "has not entered the worker runtime" —— **不准确**：`application/candidate_validation.py:74` 与 `application/replan_service.py:130,143,210` 均在 worker 路径使用 TripSkeleton（worker/processor.py:16-17,151-173 已接线）。代码在用，注释撒谎。
- 影响：后续开发者可能误删或误认为废弃。

### 2.2 DecisionTrace docstring 部分过时（P3）
- `planning/decision_trace.py:7-9` 自述 "so-far-unused reason-code vocabulary" —— 不准确：`planning_provider.py:423` 已构建 traces，`evaluation/explanations.py:54` 已将其转换为用户可见 DecisionExplanation。仍是进程内模型（不序列化），但"unused vocabulary"表述已过时。

### 2.3 死参数 MealDemand.budget_per_person（P2）
- `daily_schedule.py:212` 定义、`:431,:451,:464,:541,:605,:694,:715` 透传，但 `planning_provider.py` 的 `plan_day` 调用点不传 → 恒 None，餐厅选择零成本参与（既有 V3 审计已指出，本次复核通过）。

### 2.4 终态集合双源（P2）
- `PlanningTaskEventHub.java:112-116` 与 `PlanningTaskEventStreamService.java:15-16` 各维护一份 SSE 终态事件集合，易漂移。

---

## 3. API_ONLY / 前端未消费（P3，功能层面未死、UI 层面闲置）

| 端点 | 位置 | 说明 |
|---|---|---|
| GET /itinerary/versions/{versionId} | ItineraryController.java:68 | 前端只用 diff/rollback |
| GET /city-intelligence + POST /refreshes | CityIntelligenceController.java:27,35 | 前端绕过，走攻略导入通道 |
| GET/PUT /api/city-sources | CitySourceController.java:28,37 | 无 UI |
| GET /api/users/me | UserController.java:21 | 无 UI |
| GET /api/health | HealthController.java:11 | 无 UI（compose 健康检查用 actuator） |
| /api/internal/diagnostics/* | InternalPlanningDiagnosticsController.java:33,42 | 内部运维 |

## 4. 保留但只被 CLI/离线路径使用的模块（DORMANT，不建议删除）

| 模块 | 实际用途 | 证据 |
|---|---|---|
| acquisition/（17 文件） | 官方源离线采集 CLI（trip-agent-acquisition） | acquisition/cli.py:46-91；compose 未编排 → 手动运行 |
| retrieval/（7 文件） | 知识库 CLI：compose.prod.yaml:195-196 knowledge-init 执行 migrate+import | retrieval/cli.py；**但 Java 侧无知识查询端点**（application/knowledge 空壳），agent 工具 retrieve_guide_knowledge（tools.py:645）在未配置时返回 CAPABILITY_MISSING（tools.py:358） |
| scripts/simulate_planning_v1.py | V1 审计遗留模拟脚本 | 被 v2 取代；v2 仍用于反事实验证（30/30） |

## 5. 判定与建议

> 死代码总量不大（主要 1.1 的 Parser 死分支 + 1.6 死状态），但**「声明而未实现」类问题（OR-Tools / REPLAN / CONSTRAINTS_SOLVING 假阶段）比死代码更危险**——它们会让读者（和面试答辩）误信系统有求解器与重规划能力。
>
> 建议删除：legacy 契约目录、Parser 死分支、ConstraintPanel.vue、死状态值、ortools 依赖（或实现后保留）。
> 建议修正：TripSkeleton/DecisionTrace 过时 docstring（1 行注释即可，避免误删活代码）。
> 不建议删除：acquisition/（有 20+ 测试支撑，作为工具保留）、retrieval/（部署链使用）。
