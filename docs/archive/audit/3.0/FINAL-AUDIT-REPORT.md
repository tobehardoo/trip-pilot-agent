# FINAL-AUDIT-REPORT — TripPilot 全仓库审计最终报告（3.0 前置）

> 审计性质：**PROJECT-WIDE AUDIT ONLY**（只读；未修改任何生产/测试代码）
> 日期：2026-08-31 · 审计基线：HEAD `6351349`（docs: Planning Intelligence 3.0 Phase A audit）
> 证据标准：所有结论锚定 `file:line`；本报告引用的行号均在 01-09 子报告中逐条实测复核。
> 配套子报告：01 system-architecture · 02 feature-inventory · 03 code-complexity · 04 agent-audit · 05 data-model · 06 event-state · 07 test-audit · 08 dead-code · 09 security-performance

---

## A. 当前系统到底是什么？（500 字内）

TripPilot 是一个**三栈一体的约束驱动旅行规划系统**：Vue 3 前端（单页外壳）+ Java/Spring Boot 后端（API、版本化行程、Outbox 可靠性边界、SSE）+ Python 服务（规划智能）。核心链路是"Java 事务内写 Outbox → RabbitMQ → Python 确定性规划管线 → 事件回写 → Java 幂等落库 → SSE 推前端"——这是全系统最扎实的部分（SKIP LOCKED Outbox、eventId 幂等、乐观锁、契约双语言共享 fixture 测试）。规划侧由 11 条硬可行性规则 + 有界修复引擎守门（fail-closed），候选排序/日程/交通/预算全部是确定性代码。Python 外圈叠加了一个**有界 LangGraph ReAct 循环**（对话式约束收集、工具选择、澄清），但行程生成内圈是纯 Workflow。**系统宣称的"OR-Tools 优化"实际零实现**（pyproject 声明、全库无引用）；**Agent 循环内 REPLAN 策略声明但无工具**。系统存在显著的双对话通道（HTTP 向导 + MQ Agent）、多套行程/槽位数据模型（8+ 种"行程"名字）、两个重复 SSE Hub、无人消费的死信队列、无超时恢复的任务状态机。总体上是一个"可靠性工程优秀、规划确定性扎实、Agent 化刚刚起步、模型层重复严重"的中型系统（源码约 160K LOC）。

---

## B. 真实架构图

```
[Web] Vue3 SPA (TripWorkspace.vue:1314-1426 单页分发)
   │  fetch/SSE (api.ts:1269-1331, Last-Event-ID 重放)
   ▼
[Java travel-server] 18 Controller → 25+ Service → 32 MyBatis Mapper
   │  PostgreSQL (30 表 / Flyway V1-V42)         Outbox (SKIP LOCKED + 10 次重试→DEAD)
   ▼
[RabbitMQ] trip.command.exchange / trip.event.exchange / trip.dead-letter.exchange
   ▼
[Python agent-service]
   ├─ worker/processor.py     确定性规划管线（候选→骨架→日程→交通→可行性→repair≤3→发射）
   ├─ worker/agent_processor.py  LangGraph 有界 ReAct（graph.py:365-378 decide↔act）
   ├─ dialog/service.py       HTTP 槽位向导（创建模式，LEGACY 通道）
   ├─ feasibility/            11 规则 + repair 引擎（validator.py:62-74 / repair/engine.py:71,181）
   └─ guide_intelligence/     攻略导入/OCR/可信事实（LLM 抽取 + security_filter）
   ▼  事件（completed/failed/review/progress/agent.*）
[Java 6 个 @RabbitListener] → eventId 幂等 → 落库 → SSE EventHub → Web
```

---

## C. 核心业务链路（证据见 01）

| 链路 | 关键点 | 证据 |
|---|---|---|
| 创建旅行 | POST /api/trips → TripService → trip 表 | TripController.java:33 |
| 规划 | POST /planning-tasks → Outbox → MQ → Python processor → 事件 → Java 幂等落库 → SSE | PlanningTaskService.java / amqp.py:1018 / PlanningCompletionService.java:109-120 |
| Agent 对话 | AgentDialogCommandService(Outbox) → agent.dialog.queue → agent_processor → 9 工具 ReAct 循环 → agent.* 事件 → Java → SSE | graph.py:365-378 / tools.py:551-723 |
| Tool | 9 个工具由决策器按状态选择（LLM/规则），值确认权在代码 | tools.py:745 / tools.py:114-131 |
| Solver | **无**（OR-Tools 声明零使用） | pyproject.toml:12 |
| 持久化 | itinerary_version 不可变版本树 + planning_task + feasibility_report | V5/V33 迁移 |
| SSE | PlanningTaskEventHub + AgentDialogEventHub（重复实现） | 06 §1.3 |

---

## D. 真实功能数量统计

| 分类 | 数量 | 说明 |
|---|---|---|
| IMPLEMENTED | 20 | 认证、建行程、约束、候选召回、日程、时间窗、必游点、不可行解释、replan 命令、编辑、回滚、分享、PDF、ICS、攻略导入、Agent 行程内对话、SSE、diff、归档、天气事实 |
| PARTIALLY_IMPLEMENTED | 3 | 预算（餐食死参数+住宿常数估算）、固定预约（依赖数据完整）、多模式交通（TAXI/AUTO 局限） |
| API_ONLY | 4 | 知识检索、城市资料源、users/me、内部诊断 |
| DUPLICATED | 3 | 双对话链路、城市情报双通道、前端三套行程模型 |
| DEAD | 5+ | Parser 死分支、legacy 契约、ConstraintPanel、trip-versions 路由、DB 死状态值 |
| LEGACY | 2 | 创建模式 HTTP 向导、planning-completed v1-v8 冻结契约 |

> **不存在"UI 有而后端无"的假功能**（逐端点核验）；问题全部在"同一能力多套实现"。

---

## E. 最大的 10 个架构问题（P0→P3）

| # | 问题 | 级别 | 证据 |
|---|---|---|---|
| 1 | **事件链路无收敛**：死信队列双向声明、无人消费；任务永久 RUNNING 无超时/补偿 | **P0** | RabbitMessagingConfiguration.java:95 vs 无 @RabbitListener；PlanningProgressService.java:83-85 |
| 2 | **验证基线漂移**：工作树存在未提交重构（context_view 抽取），2 个新测试失败（test_context_view_construction） | **P0** | git status `??` + 实测 2 failed |
| 3 | **规划核心能力"宣称≠实现"**：README/技术栈宣称 OR-Tools 优化，全库零引用 | P1 | pyproject.toml:12 / README.md:39,76 |
| 4 | **Agent REPLAN 策略声明未实现**（prompt 会引导模型声明 REPLAN 但无对应工具） | P1 | graph.py:227,346 vs tools.py:551-723 |
| 5 | **双对话系统并存**：MQ 驱动 Agent 循环 + HTTP 槽位向导，同一槽位两套状态机 | P1 | agent_processor.py:534 vs dialog/service.py:546 |
| 6 | **状态机死值污染活跃判定**：CREATED/RETRYING/CANCELLING/STALE 从不写入却参与查询；WAITING_USER 终态路径存疑 | P1 | PlanningTaskMapper.java:199,217,135 |
| 7 | **Java 行程读取 N+1**：1 次详情读取 ≈ 1+N×2 次 DB 往返 | P1 | ItineraryService.java:366-376,424-433,806-828 |
| 8 | **前端双超级组件 + 40+ props prop-drilling** | P1 | TripWorkspace.vue(1445)/TripDetail.vue(1581) |
| 9 | **数据模型漂移**：同一"行程"8+ 种名字与结构，跨三语言 | P1 | 见 05 §1 |
| 10 | **agent.start/resume 路由键无 Java 本地绑定声明**（依赖隐式外部约定） | P1 | AgentDialogCommandService.java:28-30 vs RabbitMessagingConfiguration.java:138-176 |

## F. 最大的 10 个代码臃肿来源

| # | 文件 | 行数 | 臃肿原因 | 建议 |
|---|---|---|---|---|
| 1 | itinerary/ItineraryService.java | 2,044 | 读取/编辑/候选落地/版本 4 职责 + 60% 私有 record | 按写路径拆分 3 类 |
| 2 | infrastructure/amap/planning_provider.py | 2,331 | provider+编排+决策追踪混居；`_plan_with_skeleton` 449 行 | 继续 context_view 式抽取 |
| 3 | worker/contracts.py | 1,860 | 同文件 4 个完成事件版本类 + 2 个失败版本类 | 版本增量策略 |
| 4 | planning/PlanningTaskService.java | 1,051 | 创建/取消/查询 + 200 行私有 DTO | 拆 DTO 层 |
| 5 | infrastructure/mq/PlanningCompletedEventParser.java | 1,004 | 含 v1/v6/v8 不可达分支（:393,:477,:605,:871） | 删死分支 |
| 6 | dialog/service.py | 1,205 | 向导状态机+解析+grounding+存储 4 职责 | 拆 store/extractor |
| 7 | worker/amqp.py | 1,076 | 连接/消费/事件发射/取消协作 4 职责 | 拆 messaging 层 |
| 8 | planning/daily_schedule.py | 1,061 | 计划器+模型类 | 拆模型 |
| 9 | pages/TripWorkspace.vue | 1,445 | 认证+数据装载+SSE 状态机+路由分发 | 拆 layout/store |
| 10 | components/TripDetail.vue | 1,581 | 15+ 面板、40+ props | 拆 feature 组件 |

## G. 最大的 10 个重复/冗余问题

| # | 问题 | 证据 |
|---|---|---|
| 1 | "行程"8+ 种模型（Trip/TripContext/Itinerary/Replan/Candidate/TripSkeleton/前端 3 套） | 05 §1 |
| 2 | 槽位 6 种模型（ConstraintSlot/SlotView/SlotSpec/AgentSlotView/前端 2 套+slotTone） | 05 §1 |
| 3 | 前端 Itinerary/CandidateItinerary/SharedItinerary 三套结构、字段命名不一致 | api.ts:471 vs feasibility.ts:107 |
| 4 | Python contracts.py 五套行程快照（版本复制类） | worker/contracts.py:750,851,1528 |
| 5 | 两个 SSE EventHub 近乎逐字重复（151 vs 145 行） | PlanningTaskEventHub vs AgentDialogEventHub |
| 6 | 三套槽位值抽取（graph.py:97-118 / dialog/service.py:437 / dialog/extractor.py） | 04 §6 |
| 7 | 幂等实现四处复制（task_event/agent_message/share/guide_import 各自查重） | 06 §2 |
| 8 | 城市情报双通道（专用端点 vs 攻略导入通道） | CityIntelligenceController.java:27 vs TripDetail.vue:716 |
| 9 | 双对话链路（MQ Agent vs HTTP 向导） | 02 §4.1 |
| 10 | 终态集合双源（EventHub:112-116 vs EventStreamService:15-16） | 06 §4.2 |

## H. 最大的 10 个历史包袱

| # | 来源 | 当前用途 | 是否仍必要 | 建议 |
|---|---|---|---|---|
| 1 | 契约"每批次一版本+冻结不删"（v1→v11） | 兼容 v9/v10/v11 | 部分 | 改为增量演进策略（08 §4） |
| 2 | Parser 旧版本校验死分支 | 无（不可达） | 否 | 删除 |
| 3 | contracts/messaging/legacy 目录 | 无（零消费） | 否 | 删除（保留 README 归档说明） |
| 4 | Java 空壳分层（package-info-only） | 无 | 否 | 删除或兑现 |
| 5 | 创建模式 HTTP 向导（dialog/service.py） | LEGACY 通道仍在线 | 过渡期 | 并入 Agent 会话通道 |
| 6 | agent-workspace 2.0 组件（ConstraintPanel 孤儿） | 无 | 否 | 删除孤儿组件，保留被 3.0 复用的卡片 |
| 7 | DB 死状态值 CREATED/RETRYING/CANCELLING/STALE | 无（仅 SQL 查询引用） | 否 | 清理 |
| 8 | **Git 历史损坏**：baseline 为 store corruption 后快照（仅 8 commits） | 无法做历史溯源 | — | 3.0 前建立完整 git 基线并固化发布流程 |
| 9 | README 测试数字过期（1717/558/446 vs 实际 1878/618/523） | 误导 | 否 | 改为引用 CI/发布报告 |
| 10 | trip_skeleton/decision_trace 过时 docstring（自述未使用，实际在用） | 误导维护者 | 否 | 修正注释 |

## I. Agent 化最终判定

```
AGENT_WITH_WORKFLOW
```

**证据链**：
- **是 Agent 的部分**：LangGraph 上真实 `decide →(条件边)→ act → decide` ReAct 循环（graph.py:365-378）；工具由决策器按状态选择（tools.py:745，非固定链）；LLM 决策 + 规则降级双路径（graph.py:287-329 / :135-211）；步骤/工具/LLM 三重预算上限（graph.py:38-40）；工具失败可降级不崩（:293-300）。
- **是 Workflow 的部分**：行程生成内圈零 LLM（候选/日程/交通/预算/可行性全确定性）；发射由 validate_itinerary 一票否决、模型无发射工具（graph.py:417-420）；无 plan 状态、无内部评估、无自主 replan。
- **隐藏形态**：未配置模型时整体退化为规则向导（factory.py:159-161）——即系统最低形态是确定性向导。
- **反证（不是 NOT_AGENT）**：循环是真实的条件循环，不是固定 A→B→C 链；工具选择权在决策器而非硬编码。

## J. Agent 化缺口

| 当前能力 | 缺失能力 | 是否值得补 | 补什么 |
|---|---|---|---|
| 工具选择/澄清/约束收集（有界 ReAct） | **自主重规划（REPLAN 工具）** | ✅ 高价值 | 增加 `replan_itinerary` 工具：基于 feasibility report 的冲突（营业时间/时长/预算）生成局部修改动作（复用 repair/catalog.py 6 动作），循环内"观察→判断→修改→重校验" |
| observations 轨迹 | **Plan 状态**（agent/state.py 无 plan 字段） | ✅ | state 增加 `plan/plan_revision` 字段，使"第 N 版方案"可追踪 |
| 外部 validator 一票否决 | **内部自评**（agent 无法评估自身产出） | ⚠️ 可选 | 保持外置（fail-closed 更安全），不补 |
| checkpoint 最新快照 | 长会话复盘/多轮恢复 | ⚠️ 可选 | agent_step 已有 seq 幂等；补 checkpoint 历史 |
| 9 个工具 | 工具组合/新工具 | ✅ 中期 | 优先补 replan；其余按产品需要 |

> 核心结论：**3.0 应把「Agent 内 REPLAN」与「OR-Tools 求解器」这两个"声明的能力"真正落地或正式降级**——两者是当前系统宣称与实际最大的裂缝。修复引擎（repair/engine.py）已经是事实上的"有界自主修复"，将其接入 Agent 循环是成本最低的 Agent 化增强。

## K. 应删除什么？

| 对象 | 理由 | 风险 |
|---|---|---|
| contracts/messaging/legacy/（v1-v3 契约） | 零消费（08 §1.2） | 低（保留归档说明） |
| PlanningCompletedEventParser 死分支（:393,:477,:605,:871） | 不可达（08 §1.1） | 低（有契约测试兜底） |
| ConstraintPanel.vue | 0 引用（08 §1.4） | 低 |
| DB 死状态值 CREATED/RETRYING/CANCELLING/STALE | 无写入点（08 §1.6） | 中（需同步 SQL 查询） |
| ortools 依赖（或真正实现求解器） | 声明零用（08 §1.7） | 低（移除声明即可；若 3.0 要实现则保留） |
| 空壳 package-info 目录 | 形式主义（08 §1.3） | 低 |
| trip-versions 死路由 + lib/routes.ts 第二套路由类型 | 双真相（02 §4.4） | 低 |
| 前端 SharedItinerary 类型 | 与 Itinerary 重复（05 §2.1） | 低 |

## L. 应合并什么？

| 合并 | 结果 | 原因 |
|---|---|---|
| PlanningTaskEventHub + AgentDialogEventHub | 通用 SseHub（按 streamKey 订阅） | 两实现 90% 相同（03 §5.7） |
| dialog/service.py 向导 + agent/graph.py 循环 | 统一"Agent 会话通道" | 消除双槽位状态机（02 §4.1）；HTTP 向导降级为 Agent 输入适配器 |
| 五套行程快照（contracts.py:750/851/1528 + state.candidate_itinerary + TripSkeleton） | 单一 `PlanSnapshot` 契约模型 | 05 §2.2 |
| 前端 Itinerary/CandidateItinerary/SharedItinerary | 单一 Itinerary + 判别联合 | 05 §2.1 |
| 三套槽位值抽取（graph.py:97 / dialog/service.py:437 / extractor.py） | 单一 extractor | 04 §6 |
| 城市情报双通道 | 统一走 city-intelligence 专用端点 | 02 §4.2 |
| 幂等表复制 | 统一 IdempotencyRecord | 06 §2 |
| contracts.py 版本复制类 | 单类 + 版本增量字段 | 08 §4 |

## M. 应重构什么？（按优先级）

1. **P0**：DLQ 消费者（转 FAILED + 错误码）+ planning_task RUNNING 超时扫描 Job（保证状态机收敛）
2. **P0**：收敛工作树未提交重构（context_view 抽取完成并修复 2 个失败测试），重建干净发布基线
3. **P1**：Java 行程读取 N+1 → 批量查询（WHERE day_id IN）
4. **P1**：状态机清理（删死值；补 WAITING_USER→SUCCEEDED 路径或显式禁止）
5. **P1**：拆分 ItineraryService（读取/编辑/候选落地三职责）
6. **P1**：前端拆分 TripWorkspace/TripDetail（按 feature 域拆 composable/store）
7. **P1**：数据模型收敛（见 L）
8. **P2**：agent.start/resume 显式绑定声明；内部诊断端点收敛进 Security 层

## N. 应保留什么？（真正有技术价值的部分）

| 资产 | 价值 | 证据 |
|---|---|---|
| **Outbox + eventId 幂等 + 乐观锁**可靠性内核 | 全系统最扎实的部分 | 06 §2 |
| **契约双语言共享 fixture 测试**（Java Parser 测试与 Python Schema 测试消费同一 JSON） | 防跨语言契约漂移的正确姿势 | 07 §3 |
| **feasibility 11 规则 + repair 有界引擎**（fail-closed 守门） | 行业少见的高质量确定性规划内核 | validator.py:62-74 / repair/engine.py |
| **transport_strategy 有序规则表**（天然 Coordinator 模式） | 已 30/30 反事实验证 | transport_strategy.py:9-15 |
| **SSRF 双层防护**（DNS 固定 + 域白名单） | 安全亮点 | 09 A1 |
| **有界 ReAct 循环**（decide↔act + 三重预算上限 + 规则降级） | Agent 化的正确骨架 | graph.py:365-378 |
| **反事实验证套件**（simulate_planning_v2 30/30） | 稀缺的质量资产 | 07 §2 |
| **PostgresIntegrationTest 基类 + 16 个集成测试** | 可复验的集成验证 | 07 §2 |
| 攻略情报可信事实链路（trusted_facts + evidence） | 事实工程深度 | guide_intelligence/trusted_facts.py |
| 版本树 + diff + 回滚（immutable itinerary versions） | 产品差异化能力 | ItineraryVersionService |

---

## 3.0 架构收敛建议

```
CURRENT（三栈 + 双对话 + 契约版本复制 + 死信堆积）
   │
   ▼ REMOVE
死契约目录 / Parser 死分支 / 死状态值 / 空壳层 / 孤儿组件 / 未用依赖（ortools 或实现） / 死路由
   │
   ▼ MERGE
两个 SSE Hub → 通用 Hub；双对话 → 单 Agent 会话；五套行程快照 → 单 PlanSnapshot；
前端三套类型 → 单 Itinerary+union；三套抽取 → 单 extractor；城市情报双通道合一
   │
   ▼ REFACTOR
DLQ 消费者 + RUNNING 超时扫描（先做）→ N+1 批量查询 → Service 拆分 → 前端组件拆分 → 状态机清理
   │
   ▼ AGENTIZE（有界）
Agent 内 REPLAN 工具（复用 repair 引擎）→ Plan 状态 →（可选）checkpoint 历史 → 其余保持确定性守门
   │
   ▼ TARGET ARCHITECTURE
[Java 可靠性边界] 事务/幂等/Outbox/SSE/版本/分享 —— 收敛状态机、显式绑定、DLQ 兜底
[Python 规划内核] 确定性管线 + 有界 Agent 外圈 —— 收敛为 2 个运行时：worker(规划) + agent(对话)
[契约] 单事件族 + 增量字段演进（不再整类复制）
[Web] 收敛为 3 个页面域：会话页(planning-session) / 行程页(trip-detail) / 分享页
```

### Target Module Boundaries
- `travel-server`：`api`（Controller）→ `application`（Service/命令）→ `infrastructure`（Mapper/MQ/SSE）；删除空壳层；每层有真实类。
- `agent-service`：`agent`（对话/决策）· `planning`（确定性内核）· `feasibility`（守门）· `guide_intelligence`（情报）· `worker`（消息）；contracts.py 拆为 schema 目录。

### Target Agent Boundary
Agent = **语义层**（意图/约束收集/策略选择/解释/局部调整）；**终态生成与守门永远在确定性侧**（validator 一票否决）。REPLAN 工具走 repair 引擎（确定性动作），LLM 只决定"改什么"不决定"怎么算"。

### Target Java/Python Boundary
Java 拥有：状态机、持久化、幂等、SSE、导出、认证。Python 拥有：规划、可行性、情报、对话。**知识检索（RAG）是当前的最大孤儿**（Java 空壳、无 UI）——3.0 需决定：要么 Java 加查询端点 + Web 加 UI，要么正式移除。

### Target Event Boundary
- 事件族收敛为：`planning.*`（create/replan/cancel/progress/completed/failed/review）+ `agent.*`（step/ask-user/completed/run-finished）。
- 版本策略：**向后兼容增字段**（v12 只加不删），冻结版本仅保留解析分支（Parser 删死分支）。
- 补：DLQ 消费者、Agent 事件幂等（run_id, seq 唯一键）。

### Target State Model
`planning_task`：QUEUED / RUNNING / WAITING_USER / SUCCEEDED / FAILED / CANCELLED（6 值，删除死值）；加 `heartbeat_at`，超时扫描 → FAILED(STUCK)。`agent_run`：RUNNING / WAITING_USER / EMITTED / STOPPED / FAILED / EXPIRED / ANSWERED（与前端对齐）。

### Target Data Model
- 契约层：`PlanSnapshot`（行程唯一契约模型，day/activity/transit_leg/feasibility）。
- 持久化层：trip / itinerary_version / day / activity / transit_leg / feasibility_report / planning_task（日期边界去重，以 snapshot 为权威）。
- 展示层：前端单 `Itinerary` 类型 + 判别联合（候选/正式/分享）。

---

## 问题分级汇总

| 级别 | 数量 | 代表 |
|---|---|---|
| **P0** | 2 | 事件链路无收敛（DLQ+永久RUNNING）；工作树未提交重构含失败测试（基线漂移） |
| **P1** | 10 | OR-Tools 零实现、REPLAN 未实现、双对话、状态机死值、N+1、双超级组件、模型漂移、路由键缺失、内部诊断暴露、budget_per_person 死参数 |
| **P2** | 12 | Parser 死分支、空壳层、死路由、Agent 事件无幂等、SSE Hub 重复、进度乱序丢事件、STALE 死状态、跨表日期双写、幂等表复制、版本快照逐行 insert、同步 DB 无池、终态元数据双源 |
| **P3** | 8 | README 数字过期、过时 docstring、CORS 隐晦、OCR 边界、无 UI 消费端点、supported-cities 手工同步、prewarm 冗余、日志/格式 |

## 必须区分的 DEFECT vs 观察（关键澄清）

- ItineraryService 2044 行 / planning_provider 2331 行：**DESIGN_DEBT**（高耦合、难测、修改风险真实存在），不是 Bug。
- 契约 v11 版本多：**设计策略选择**（每批次冻结一版），代价是模型复制——是"观察 + 建议改策略"，非缺陷。
- 双对话系统：**ARCHITECTURE_RISK**（同一概念两套状态机，修改需双处同步）。
- OR-Tools 缺失 / REPLAN 未实现：**DEFECT**（宣称≠实现，会误导架构决策与面试答辩）。

## UNKNOWN / NEED_VERIFY 清单

| 项 | 原因 |
|---|---|
| WAITING_USER → SUCCEEDED 终态路径 | updateTerminalStatus 仅 QUEUED/RUNNING（PlanningTaskMapper.java:135），评审接受后任务如何转终态 UNKNOWN / NEED_RUNTIME_VERIFY |
| agent.start/resume 命令实际可达性 | 无本地绑定声明（P1），实际依赖 Python 消费者存在性 |
| DLQ 堆积实际规模 | 无监控；NEED_RUNTIME_VERIFY |
| 生产 REAL_ONLY 链路行为 | 本地为 DEMO_ONLY；真实 AMap 行为基于代码推断 |
| Java 618 tests 通过数 | 本次未跑 mvn test（~4min）；引用 2026-08-30 发布报告 |
| OCR 上传大小/类型限制 | 未在代码中定位到显式校验 |

---

## 附：建议的下一阶段（Next Phase）

1. **Phase 0（先做，1-2 天）**：收敛工作树未提交重构（context_view 修复 2 个失败测试），重建干净发布基线 + README 测试数字改为引用 CI。
2. **Phase 1（可靠性收口）**：DLQ 消费者 + RUNNING 超时扫描 + 状态机死值清理 + agent 路由显式绑定 + Agent 事件幂等。
3. **Phase 2（模型收敛）**：按 §L 合并清单落地（先 contracts.py → 单一 PlanSnapshot + 增量字段，再前端类型统一）。
4. **Phase 3（Agent 化落地）**：实现 REPLAN 工具（复用 repair 引擎）+ Plan 状态；**同时正式决定 OR-Tools 的去留**（实现真实求解器 or 从 README/技术栈中移除宣称）。
5. **Phase 4（性能/安全）**：N+1 批量查询、Service/前端拆分、内部诊断端点收紧、CORS 显式化。
