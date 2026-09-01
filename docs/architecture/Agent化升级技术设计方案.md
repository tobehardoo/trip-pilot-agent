# TripPilot Agent 化升级技术设计方案

- 文档状态：设计稿（待评审）
- 最后更新：2026-08-29
- 事实来源：以当前代码为准（本方案全部结论基于对 `apps/agent-service`、`apps/travel-server`、`apps/web` 的实际代码核查）
- 关联文档：[ADR-010 单一 Agent] · [ADR-015 Agent 编排层与记忆系统] · [Agent化路线图](../product/Agent化路线图.md) · [事件契约](事件契约.md) · [系统架构](系统架构.md)
- 设计原则：**可靠性 > 自主性；确定性 > 幻觉；可维护 > 炫技**

---

## 0. 事实核查：文档口径与代码的三处差异

本方案先报告差异（遵循"文档与代码不一致时先报告差异"的门禁原则）：

| # | 文档口径 | 代码事实 | 影响 |
| --- | --- | --- | --- |
| F1 | 《系统架构》主链路含"OR-Tools 求解" | `ortools==9.14.6206` 仅存在于 `pyproject.toml`，`src/` 内 **0 处 import**；排程实际由 `planning/daily_schedule.py`（确定性日排程）+ `feasibility/`（hard-validator-v5）+ `repair/`（MAX_REPAIR_ATTEMPTS=3 有界修复）完成 | 本方案不把 OR-Tools 当作既有能力；求解器议题单列（见 §10.2） |
| F2 | 文档称"Agent 编排层已落地"于主链路 | `trip_agent/agent/` 完整实现了有界循环，但**仅被 `agent/__init__.py` 导出，worker / planning 链路 0 引用**，是未接线的原型 | 本方案的核心工作正是"接线"，见 §2 |
| F3 | 《系统架构》称 Tool 层"9 工具" | `agent/tools.py` 实际定义 **8 个工具**；且 D1–D5 缺陷（路线图已确认）在代码中全部存在：LLM 超时未捕获、工具异常未包装、emit 暴露给 LLM、validate 校验对象错位、confirmed 由 LLM 自评 | §5 逐工具裁决 |

除上述三点外，既有基线质量很高，本方案**不推翻** ADR-010（单一 Agent）、ADR-015（编排层+记忆）、既有 Phase 划分，而是给出可实施的精化设计。

### 0.1 当前生产链路（代码事实）

```
Vue ── POST /api/trips/{tripId}/planning-tasks (Idempotency-Key)
   → Java: 事务内写 business.outbox_event（PLANNING_CREATE_REQUESTED, routing key planning.create）
   → OutboxPublisherJob(1s) → publisher-confirm → trip.command.exchange
   → planning.create.queue（aio-pika, prefetch=1, Python）
   → worker/processor.py：POI 检索 → CandidateRanker → daily_schedule 确定性排程
     → feasibility hard-validator-v5 → 有界 repair(≤3) → evaluation rule-v3 五维打分
   → trip.event.exchange：PLANNING_COMPLETED(schema 11) / REVIEW_REQUIRED / FAILED / PROGRESS
   → Java PlanningCompletionService 事务落库（itinerary_version + feasibility_report + fact_impacts）
     幂等门：taskEventMapper.findByEventId + PlanningOutcomeGuard 基线校验
   → SSE（Last-Event-ID 续传，终态短路）
```

关键既有资产（Agent 化必须继承，不得破坏）：

1. **双端确定性 UUID 幂等**：Python 侧 `_completed_event_id/_run_id` 等 `uuid5(NAMESPACE_URL, ...)` 派生自 `command_event_id/task_id`；Java 侧 `findByEventId` 去重。任何 Agent 重试设计必须维持该约定。
2. **schema_version 门禁**：Java 仅接受 PLANNING_COMPLETED 的 schema 9/10/11；事件契约演进必须走版本化。
3. **取消机制**：`CancellationRegistry`（进程内）+ `PsycopgCancellationOracle`（PG 直查 `business.planning_task.status`），节点间协作式取消。
4. **WAITING_USER 已是任务状态**（`CREATED/QUEUED/RUNNING/WAITING_USER/RETRYING/CANCELLING/CANCELLED/SUCCEEDED/FAILED`），且是 SSE 终态之一，前端已有 `PlanningReviewPanel`。
5. **DEMO 模式与 AskingDecider**：无 Key 可全链路运行，是降级阶梯与测试底座。

---

## 1. Agent 架构设计

### 1.1 当前 Agent 是不是"真 Agent"？

分两层回答：

**形态上**：`agent/graph.py` 是一个真正的 ReAct 型结构——`decide`（结构化输出产出 thought+tool+args）→ `act`（工具执行产出 observation）→ 循环，且有三重上限（MAX_STEPS=8 / MAX_TOOL_CALLS=16 / MAX_LLM_CALLS=8）与 fail-closed 工具语义。它比"伪 Agent"（把 LLM 输出当摆设）强。

**实质上**：它 (a) 未接入任何生产路径；(b) 只会做槽位填充，不会触达规划、验证、交付；(c) 无跨进程记忆、无恢复、无多轮；(d) 五个已知缺陷（D1–D5）使它在异常路径上不可靠。因此**当前生产系统是 Workflow，Agent 是原型**。

### 1.2 四个概念辨析与 TripPilot 的定位

| 概念 | 控制流归属 | 典型形态 | 风险 | 在 TripPilot 的对应物 |
| --- | --- | --- | --- | --- |
| Workflow | 代码，固定 DAG | 现有 `worker/processor.py` 固定管线 | 无自主性，无法理解自然语言 | **现有生产路径（保留为内核）** |
| State Machine | 代码，显式状态+转移 | `planning_task` 状态机（9 态） | 低 | 任务生命周期（保留） |
| ReAct Agent | LLM，逐步决策直到停止条件 | 自由 thought→act→observe 循环 | 高：循环失控、幻觉事实、不可复现 | **仅作为理解层形态，且必须加界** |
| Agentic Workflow | 骨架代码固定，LLM 只在指定决策节点内自主 | LLM 节点（理解/澄清/解释/提议）+ 确定性节点（规划/校验/交付），边全部由代码定义 | 可控 | **TripPilot v2.x 的目标形态** |

**判定：TripPilot 应该做 Agentic Workflow，不做自由 ReAct。** 理由即项目护城河："行程真正可执行"只能由确定性系统保证；LLM 的自主权必须被限制在"理解、澄清、解释、提议"四类节点内，且每类节点的输出都要经确定性代码验证后才落状态。

### 1.3 TripPilot Agent v2.x 节点划分

| 节点 | 职责 | 输入 | 输出 | LLM 驱动 | 确定性驱动 |
| --- | --- | --- | --- | --- | --- |
| `receive_input` | 消费命令/用户答复，装载或新建 run，幂等检查 | MQ 命令 + checkpoint（如有） | 初始 AgentState | 否 | 是 |
| `route_intent` | 意图分类：NEW_PLAN / MODIFY / ANSWER / QUESTION / CANCEL | 用户输入 + 当前任务上下文 | intent + 置信度 | 半（自由文本用 LLM；卡片/按钮点选走确定性映射） | 是 |
| `understand` | 自然语言 → 结构化槽位提议 + 引用证据 | 用户原话 + 既有槽位 + memory_hints | 提议集（value, evidence, source） | **是** | 校验由下游做 |
| `merge_slots` | 提议落槽：来源判定、冲突检测、REJECTED 防重提、confirmed 规则化 | 提议集 + 现有 ConstraintSlots | 新 ConstraintSlots + 冲突清单 | 否 | **是**（D5 修复点） |
| `check_readiness` | 必填槽位是否 CONFIRMED；trip 级字段（目的地/日期）可投影 | ConstraintSlots | ready / 缺口清单 | 否 | **是** |
| `compose_question` | 把缺口/冲突转成结构化澄清（问题 + 选项 + 期望类型） | 缺口清单 + 上下文 | ClarificationCard | **是**（措辞）| 是（结构校验） |
| `plan_execute` | 触发确定性规划管线（recall→rank→schedule→validate→repair→evaluate），透传既有进度事件 | 约束投影 + TripSnapshot + knowledge | candidate itinerary + FeasibilityReport + PlanEvaluation | 否 | **是（内核，不拆散）** |
| `gate_result` | 读 feasibility + evaluation 结果，三分支：PASS / BLOCKED / FAILED | 管线产物 | 分支决策 | 否 | **是（一票否决落地处）** |
| `propose_relaxation` | BLOCKED 时，基于真实 rule violation 生成 ≤3 个放松建议（只建议，不改约束） | FeasibilityReport 的违规明细 | RelaxationProposal[] | **是** | 是（建议必须引用 rule id，不可凭空） |
| `explain_result` | 把 PlanEvaluation 五维 + fact_impacts + citations 转成用户可读解释 | 管线产物 + 产物引用 | 解释卡片（含"为什么"） | **是** | 是（数字全部来自结构化产物，LLM 不得改写） |
| `deliver` | 发终态/评审事件、落产物引用（复用既有 PLANNING_* 契约） | 分支结果 | 事件 | 否 | **是** |

> 设计要点：`plan_execute` 是**一个**节点，内部是既有确定性管线。不要把管线拆成 LangGraph 步骤去"Agent 化"——它已有自己的进度事件（TASK_ACCEPTED→…→RESULT_PUBLISHING）、provider 重试与降级、repair 有界循环。LangGraph 只包边界，不包内部。

### 1.4 多 Agent 角色裁决（逐个回答"是否值得存在"）

| 候选 | 裁决 | 理由 |
| --- | --- | --- |
| Supervisor Agent | **不引入** | 本域只有一条业务流水线，图的拓扑就是调度器。引入 Supervisor 等于用一个 LLM 复制 `StateGraph` 的路由功能，凭空增加一次 LLM 调用与一个失败面。与 ADR-010（单一 Agent）一致。 |
| Planner Agent | **不引入（作为 LLM 角色）** | 规划必须是确定性的（用户核心原则）。"Planner"存在的正确形式是 `plan_execute` 确定性节点。LLM 排行程 = 不可执行的行程。 |
| Critic Agent | **不引入（作为 LLM 评委员）** | 已有比 LLM 更强的 critic：hard-validator-v5（硬约束）+ rule-v3 五维评估（软质量）。LLM 给计划打分是拿幻觉替换规则。它的**建议通道**变体有价值，即 `propose_relaxation`（V2，见上表）。 |
| Reflection Agent | **不引入（作为自反思循环）** | "LLM 反思自己的计划再改一遍"= 无界的幻觉放大器。有界修复（repair engine ≤3 次、规则驱动）已是结构化反思的正确实现。V3 离线轨迹评估（P3.4）是反思的正确位置——人在环外、批处理、可评估。 |
| Memory Agent | **不引入（作为推理节点）** | 记忆是基础设施（表 + 检索），不是会思考的东西。需要的是 §4 的三层存储 + 注入策略，不需要一个 Agent。 |
| Multi Agent 协作 | **不引入** | 工具调用毫秒~秒级、领域窄、单租户单任务（每 trip 唯一活动任务）。多 Agent 的收益（并行探索、视角互补）在本域不存在，成本（通信、一致性、可观测性）却全额支付。 |

**结论：0 个新增"Agent 角色"。v2.x 是单 Agent + 确定性内核的 Agentic Workflow。复杂度预算花在可靠性（checkpoint/幂等/降级）而非角色数量上。**

---

## 2. LangGraph 设计

### 2.1 三条结构性决策

1. **两个环分离**。对话环（多轮、跨天、跨进程重启）由 LangGraph + PG checkpoint 承载；规划环（单任务、分钟级）保持既有 MQ + 确定性管线。两者在 `plan_execute` 节点相接，不互相渗透。
2. **暂停恢复 = "落盘终止 + 命令恢复"，不是常驻进程**。当前 worker 是 MQ 驱动的无状态消费者（prefetch=1，ack 前不释放消息），`WAITING_USER` 若挂起进程会占死通道。因此：到达 `compose_question` 时 → 写 checkpoint → 发 `AGENT_ASK_USER` → 消息 ack、进程释放 → 用户答复作为新命令 `AGENT_DIALOGUE_INPUT` 到达 → 新进程用 `thread_id=run_id` 装载 checkpoint 继续执行。这与既有 `PLANNING_REVIEW_REQUIRED → WAITING_USER` 的语义完全同构。
3. **LLM 失败必须有确定性出路**。每个 LLM 节点声明降级目标（见 §2.3 场景 5），任何场景下 run 都能收敛到终态，绝不因模型不可用而挂死。

### 2.2 V2 目标 Graph

```
START
  │
  ▼
receive_input ──(幂等拒绝/已取消)──→ END
  │
  ▼
route_intent ◄──────────────┐
  │                         │
  │ NEW_PLAN / MODIFY       │ ANSWER / QUESTION（继续对话）
  ▼                         │
understand (LLM) ──失败──→ deterministic_fallback（通用澄清 or 拒答）──┐
  │                                                                  │
  ▼                                                                  │
merge_slots (确定性，D5 修复点)                                        │
  │        │                                                         │
  │        └─(与 CONFIRMED 冲突)→ compose_question (LLM) ────────────┤
  ▼                                                                 │
check_readiness (确定性)                                             │
  │        │                                                        │
  │        └─(缺必填)→ compose_question → ASK_USER_INTERRUPT ────────┤
  ▼                                                                 │
[MODIFY 分支] impact_check (确定性: 受影响日期/实体 → 复用 replan/candidate-validation 命令)
  │                                                                 │
  ▼                                                                 │
plan_execute (确定性内核: recall→rank→schedule→validate→repair→evaluate)
  │                                                                 │
  ▼                                                                 │
gate_result (确定性一票否决)                                          │
  │        │                                                        │
  │        └─(BLOCKED)→ propose_relaxation (LLM, ≤3 条, 引用 rule id)
  │                        │                                        │
  │                        └─→ ASK_USER_INTERRUPT ──────────────────┤
  │        │                                                        │
  │        └─(FAILED)→ fail_run (确定性) → PLANNING_FAILED ─────────┤
  ▼                                                                 │
explain_result (LLM, 数字只来自结构化产物)                             │
  │                                                                 │
  ▼                                                                 │
deliver (确定性: PLANNING_COMPLETED / REVIEW_REQUIRED, 确定性 event id)│
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘
                          ASK_USER_INTERRUPT = checkpoint 落盘 + ack + WAITING_USER
                          恢复 = AGENT_DIALOGUE_INPUT 命令 → receive_input 装载 checkpoint
END
```

### 2.3 节点规格表（name / responsibility / state read / state write / failure handling）

| Node | Responsibility | State Read | State Write | Failure Handling |
| --- | --- | --- | --- | --- |
| `receive_input` | 命令解析、幂等键检查（`uuid5(command_event_id)`）、取消检查（CancellationOracle）、checkpoint 装载 | command envelope、checkpoint | `identity`、`conversation` 追加、`control.phase=INTAKE` | 契约非法 → 安全 `PLANNING_FAILED(COMMAND_VALIDATION_FAILED)` 后 ack（沿用既有 amqp 语义）；已取消 → ack 丢弃 |
| `route_intent` | 意图分类 | `conversation` 尾窗、任务状态 | `control.intent` | 自由文本 LLM 分类超时/失败 → 确定性规则兜底（含槽位变化判 MODIFY、纯疑问判 QUESTION），再不行按 NEW_PLAN 澄清；卡片点选不走 LLM |
| `understand` | 槽位提议抽取（structured output，含 evidence 引用） | `conversation`、`slots`、`memory_hints` | 产物写入 `pending_proposals` | 重试 1 次（缩 prompt）→ 降级：确定性通用澄清（AskingDecider 语义）；MODIFY 意图降级为"请到约束编辑器修改"的引导话术；全程受 `max_llm_calls` 预算 |
| `merge_slots` | 提议落槽：source 判定（用户原话含值→USER_EXPLICIT）、冲突检测、REJECTED 防重提、`to_constraint_patch` 投影 | `slots`、`pending_proposals` | `slots`（不可变替换）、冲突清单 | 纯函数，异常即 bug：包裹为 `INTERNAL_PLANNING_FAILED`；未知槽名静默拒绝并记录（沿用现状） |
| `check_readiness` | 必填槽位 CONFIRMED？日期在未来？ | `slots` | `control.ready` | 无失败面（纯函数） |
| `impact_check`（MODIFY） | diff 新旧约束 → impactedDates / 受影响实体 → 选择 replan 或 candidate-validation 命令 | `slots`、`artifacts.baseline` | `control.plan_command` | diff 为空 → 直接 ANSWER("没有变化")；基线版本过期 → 沿用 STALE_TRIP_VERSION 失败语义 |
| `plan_execute` | 触发既有确定性管线（同进程调用，或跨进程命令 + 等待既有进度事件） | `control.plan_command`、约束投影 | `artifacts.candidate_id / feasibility_report_id / evaluation_id`（引用，不存全量） | provider 失败由内核既有 retry/fallback 处理（PROVIDER_MAX_ATTEMPTS=3 + FALLBACK_CATEGORIES）；整体失败 → `gate_result` 判 FAILED；节点前置取消检查 |
| `gate_result` | PASS / BLOCKED / FAILED 三分支（一票否决的图结构化） | `artifacts` 引用 → 读取报告 | `control.gate_outcome` | 报告缺失/指纹不符（`ItineraryFingerprintVerifier` 语义）→ FAILED，绝不放行 |
| `propose_relaxation` | 依据真实违规生成 ≤3 条放松建议（每条必须引用 rule id + 影响面） | feasibility 违规明细 | `pending_proposals.relaxations` | LLM 失败 → 确定性兜底：直接列出违规清单让用户自行取舍（评审面板已有此能力） |
| `explain_result` | 生成解释卡片；数值与结论只允许引用结构化产物字段 | `artifacts`、`evaluation`、`fact_impacts` | `output.explanation` | LLM 失败 → 确定性模板拼接（五维分数表 + 违规清单），前端展示不降级 |
| `deliver` | 发终态事件（确定性 event id）、更新 run 终态 | 全部 | run 终态 | 事件发布失败 → nack(requeue)（既有语义，幂等由确定性 event id 保证） |

### 2.4 六个关键场景

1. **多轮对话**：每次用户输入 = 一条 `AGENT_DIALOGUE_INPUT` 命令 = 一次有界的图执行（受三重上限）。`conversation` 尾窗（最近 20 条）+ `slots` 进入 prompt；全量历史在 `agent_run`/`agent_step`。多轮不是常驻循环，是"每轮一次有界 run + checkpoint 续接"。
2. **修改约束**：MODIFY 意图 → `merge_slots` 更新槽位（新 CONFIRMED 覆盖旧值，`override_of` 记录被覆盖槽的 revision，可审计）→ `impact_check` 算 impactedDates → 复用既有 `PLANNING_REPLAN_REQUESTED` / candidate-validation 链路 → 产物作为新 itinerary_version（版本单调递增，用户可在版本 Drawer 对比/回滚）。
3. **暂停恢复**：见 §2.1 决策 2。TTL：`WAITING_USER` 超 72h → run 置 EXPIRED（终态），用户再次输入即新 run（携带旧 slots 快照作 hints）。
4. **工具失败**：异常分类三档——TRANSIENT（网络/超时/限流：指数退避重试 ≤PROVIDER_MAX_ATTEMPTS）、PERMANENT（参数/不存在：转告用户，不重试）、CAPABILITY_MISSING（未配置：DEMO 标注降级）。分类落在 `ToolResult.error.category`（§5.2），节点按 category 决定重试/降级/终止。
5. **LLM 失败**：降级阶梯 = 重试 1 次（缩小 prompt）→ 确定性策略（通用澄清/模板话术/纯规则路由）→ 仍不行则 run 失败并给用户明确错误。核心不变式：**LLM 不可用 ≠ 规划不可用**；`DEMO_MODE` / 无 Key 环境走 AskingDecider 全链路可跑（既有验收，保留）。
6. **人工确认**：两种门——(a) 澄清门（缺信息，`ask_user`，WAITING_USER）；(b) 评审门（有 blocker，复用既有 `PLANNING_REVIEW_REQUIRED` + PlanningReviewPanel，候选行程落 candidate 版本，用户批准才转正）。两者都是 checkpoint 边界，前端卡片点选 = 结构化答复，降低解析风险。

### 2.5 V1 / V2 / V3 演进（对齐既有 Phase 1/2/3）

**V1 = 最小可用 Agent（≈ Phase 1 全部 + 最小接线）**

```
START → receive_input → understand(LLM) → merge_slots → check_readiness
        ├─缺→ compose_question → ASK_USER_INTERRUPT（checkpoint+WAITING_USER）→ END
        └─齐→ dispatch_existing_pipeline（确定性，原样调用）→ 既有 PLANNING_* 事件 → END
```
范围：修 D1–D5；`agent_run`/`agent_step` 表 + 幂等键；PG checkpointer；`AGENT_ASK_USER`/`AGENT_DIALOGUE_INPUT` 契约（schema_version 化）；`StructuredOutputDecider` 复用 `STRUCTURED_MODEL_*` 配置。
理由：V1 只让 LLM 做"理解与澄清"，规划/校验/交付一行不动——**先用最小暴露面证明 LLM 在环上不伤可靠性**。这一步没有它，后面全是空中楼阁。（对路线图的唯一调整：把 P2.1 的最小接线子集提前到 V1，因为 P1 单独交付无用户可见价值；P2.1 其余部分仍在 V2。）

**V2 = 增强 Agent（= Phase 2）**

```
V1 全部
  + route_intent（MODIFY/QUESTION 分支）→ impact_check → replan/candidate-validation 复用
  + gate_result BLOCKED 分支 → propose_relaxation（建议通道，critic 的正确形态）
  + explain_result（解释卡片，数字引用结构化产物）
  + 克制版 AGENT_THINKING / AGENT_TOOL 进度事件（阶段粒度，非每步刷屏）
  + 前端对话页（聊天 + 卡片，约束草稿模型）
  + 工具异常分类（TRANSIENT/PERMANENT/CAPABILITY_MISSING）与降级阶梯完善
```
理由：在 V1 证明可靠后，补齐"对话→修改→重规划→解释"闭环。这是产品价值与简历竞争力（端到端 Agentic Workflow）的主要来源。

**V3 = 生产级 Agent（= Phase 3 的收敛版）**

```
V2 全部
  + user_travel_profile（pending/confirmed 双栏，未确认不生效——对齐 ADR-011）
  + WAITING_USER TTL/EXPIRED、stale run reaper、心跳
  + 轨迹离线回放评估（agent_step 重放 + 场景基准）
  + Copilot 侧栏嵌入 Workspace（对话与版本状态双向同步）
  + （视时间）planner 策略节点：直出 / 检索 / 澄清 / 重规划的显式策略
```
理由：记忆与人在环路依赖 V2 的遥测与交互基座；没有轨迹数据先做"个性化"是无据之谈。

---

## 3. Agent State 设计

### 3.1 现有 `ConstraintSlot` 三态评审

**`UNKNOWN / INFERRED / CONFIRMED` 是对的，保留。** 它把"值"与"值的来源"绑定，`hard = CONFIRMED && value != None` 的 fail-closed 语义（INFERRED 永不成为硬约束）正是本项目"宁可多问、不可替用户做主"原则的代码化。`evidence` 字段与 `to_constraint_patch` 投影设计同样正确。

**但它有一个结构性缺陷：单一 `state` 字段被迫承载三个正交维度**——生命周期（提没提过）、来源（谁给的值）、验证（是否被事实核实）。这正是 D5（confirmed 由 LLM 自评）的根因：LLM 调 `update_constraints(confirmed=True)` 就能自封 CONFIRMED，"用户原话"这个事实没有被规则校验。

### 3.2 四个候选状态逐个裁决（不是简单加字段）

| 候选 | 裁决 | 存在价值分析 |
| --- | --- | --- |
| `REJECTED` | **采纳（加为状态）** | 价值明确：用户明确拒绝过的提议值，若无记号，下一轮 LLM 会重新提出同一值（extractor 无记忆），形成"反复推销"的糟糕体验。`REJECTED` 使 `merge_slots` 能静默丢弃重复提议并记入审计。成本低（一个枚举值 + 一条规则），收益直接。 |
| `USER_OVERRIDE` | **不采纳（作为状态）；其意图由 `source` 轴 + `override_of` 审计承载** | "用户改了系统/LLM 给的值"不是一个生命周期阶段，而是一个**来源事实**：值仍处于 CONFIRMED 状态，只是来源是 USER_EXPLICIT 且覆盖了某个前值。单独设状态会导致状态机分叉（CONFIRMED 与 USER_OVERRIDE 什么关系？能否互转？），纯粹是字段冗余。正确建模：`state=CONFIRMED, source=USER_EXPLICIT, override_of=<前值 revision>`，覆盖链可审计——这正是路线图 P1.5 想要的"改值可审计"，且少一个状态。 |
| `EXPIRED` | **不采纳（作为槽位状态）；其意图由 run 级 TTL 承载** | 槽位值本身不会过期——"预算 5000"没有保质期；会过期的是**约束集与任务的绑定关系**（任务 WAITING_USER 三天没人理、行程日期已成过去）。这是 run/会话的生命周期问题，落在 `agent_run.status=EXPIRED` + 恢复时校验日期在未来（`check_readiness` 已含），槽位层加 EXPIRED 只会引入"部分过期"的语义泥潭（哪些槽过期？全过期还是逐个？）。 |
| `TOOL_VERIFIED` | **采纳（作为 `verified` 轴，非状态）** | 价值真实且现有系统已有对应物：`must_visit="故宫"` 是用户确认的字符串（CONFIRMED），但只有被 `search_place` 解析成 POI id + 坐标后才可执行（既有 `feasibility/entity_refs.py` + fingerprint 机制就是这个思想）。一个槽可以 CONFIRMED 但未落地。建模为独立布尔轴 `verified: bool` + `verified_by: tool_name`，与 state 正交：CONFIRMED+UNVERIFIED 的槽在 `check_readiness` 中触发地面化（grounding）工具调用。 |

**最终槽位模型 = 生命周期（state）× 来源（source）× 验证（verified）三个正交轴**：

```python
class SlotState(str, Enum):
    UNKNOWN = "UNKNOWN"        # 未提出
    INFERRED = "INFERRED"      # LLM/规则推断，仅软偏好，禁作硬约束（语义不变）
    CONFIRMED = "CONFIRMED"    # 用户确认，可作硬约束
    REJECTED = "REJECTED"      # 用户明确拒绝的提议值，防重提

class SlotSource(str, Enum):
    USER_EXPLICIT = "USER_EXPLICIT"      # 用户原话直接包含（规则化判定，修 D5）
    USER_CONFIRMED = "USER_CONFIRMED"    # 用户对提议点选确认
    GUIDE_INFERRED = "GUIDE_INFERRED"    # 攻略/城市情报推断
    HISTORY_INFERRED = "HISTORY_INFERRED"# 用户历史偏好（V3 profile）
    SYSTEM_DEFAULT = "SYSTEM_DEFAULT"

@dataclass(frozen=True, slots=True)
class ConstraintSlot:
    value: Any = None
    state: SlotState = SlotState.UNKNOWN
    source: SlotSource = SlotSource.USER_EXPLICIT   # 新增
    verified: bool = False                          # 新增：TOOL_VERIFIED 轴
    verified_by: str | None = None                  # 新增：落地工具名（search_place/...）
    evidence: str = ""
    revision: int = 0                               # 新增：每次变更 +1
    override_of: int | None = None                  # 新增：被覆盖前值的 revision（审计链）
    updated_at: datetime | None = None
```

`confirmed` 判定规则化（D5 修复）：`understand` 输出提议时附带 `quote`（用户原话片段），`merge_slots` 用确定性规则判定 `USER_EXPLICIT`（原话含该值）vs `INFERRED`；只有用户点选确认卡或原话直陈才产生 CONFIRMED。LLM 无法再自封。

### 3.3 完整 AgentState（Pydantic，可序列化 = 可 checkpoint）

现状 `AgentState` 是 frozen dataclass——LangGraph 支持，但 checkpoint 序列化、字段演进（schema_version）用 Pydantic 更稳，且 worker 侧契约已是 Pydantic。**迁到 Pydantic v2**：

```python
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

class RunKind(str, Enum):
    CREATE = "CREATE"; REPLAN = "REPLAN"; CANDIDATE = "CANDIDATE"; DIALOGUE = "DIALOGUE"

class RunStatus(str, Enum):
    RUNNING = "RUNNING"; WAITING_USER = "WAITING_USER"
    SUCCEEDED = "SUCCEEDED"; FAILED = "FAILED"; CANCELLED = "CANCELLED"; EXPIRED = "EXPIRED"

class Intent(str, Enum):
    NEW_PLAN = "NEW_PLAN"; MODIFY = "MODIFY"; ANSWER = "ANSWER"
    QUESTION = "QUESTION"; CANCEL = "CANCEL"

class RunIdentity(BaseModel):
    run_id: str                      # uuid5(command_event_id)，继承既有幂等约定
    command_event_id: str
    task_id: str | None              # 规划任务（DIALOGUE 可为空）
    trip_id: str
    user_id: str
    trace_id: str                    # 全链路透传（既有）
    thread_id: str                   # = run_id，checkpointer 寻址

class RunControl(BaseModel):
    kind: RunKind
    status: RunStatus = RunStatus.RUNNING
    intent: Intent | None = None
    phase: str = "INTAKE"            # INTAKE/CLARIFY/PLANNING/GATING/EXPLAINING/DONE
    stop_reason: str | None = None   # WAITING_USER/EMITTED/CEILING_REACHED/LLM_BUDGET_EXHAUSTED/...
    steps: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    deadline_at: datetime | None     # run 级墙钟预算（如 120s）
    max_steps: int = 8               # 三重上限配置化（原常量）
    max_tool_calls: int = 16
    max_llm_calls: int = 8

class ConversationTurn(BaseModel):
    seq: int
    role: str                        # user / agent
    kind: str                        # TEXT / CARD / OPTION_CLICK / SYSTEM
    content: str
    at: datetime
    refs: dict[str, str] = {}        # 关联卡片/版本等引用

class ToolCallRecord(BaseModel):
    seq: int
    tool: str
    args_digest: str                 # args 摘要（大参数不进 state）
    ok: bool
    error_code: str | None = None
    error_category: str | None = None
    latency_ms: int = 0
    attempt: int = 1

class PlanArtifacts(BaseModel):
    """大产物一律引用化：state 只存 id + 指纹（对齐既有 itineraryFingerprint 思想）。"""
    baseline_itinerary_version_id: str | None = None
    candidate_id: str | None = None
    feasibility_report_id: str | None = None
    feasibility_fingerprint: str | None = None
    evaluation_id: str | None = None
    impacted_dates: list[str] = []

class MemoryHints(BaseModel):
    """本 run 注入的已确认长期偏好（V3）。只读副本，不入槽位。"""
    profile_revision: int = 0
    facts: dict[str, str] = {}       # 枚举键 → 值（pace=relaxed 等）

class AgentStateV2(BaseModel):
    # 1. 身份与控制
    identity: RunIdentity
    control: RunControl = RunControl(kind=RunKind.CREATE)
    # 2. 用户输入（尾窗，全量在 Episodic）
    conversation: list[ConversationTurn] = Field(default_factory=list, max_length=20)
    # 3. 约束状态（三轴模型，§3.2）
    slots: ConstraintSlots = ConstraintSlots.empty()
    pending_proposals: list[dict] = []          # understand 产出，merge_slots 消费
    # 4. 工具调用历史（尾窗；全量在 agent_step）
    tool_trace: list[ToolCallRecord] = Field(default_factory=list, max_length=32)
    # 5. 中间结果与产物（引用化）
    artifacts: PlanArtifacts = PlanArtifacts()
    # 6. itinerary / validation / evaluation：不在 state 存全量，
    #    经 artifacts 引用从 PG 读取（checkpoint 保持小而稳）
    # 7. 记忆注入
    memory_hints: MemoryHints = MemoryHints()
```

**核心原则：State 是"指针 + 小事实"，不是"仓库"。** 行程 JSON（数十 KB～MB 级）、可行性报告、评估结果都存 PG，state 只存 id 与指纹。这保证 checkpoint 轻量、校验可做（指纹不符即拒绝恢复）、且与既有 `itineraryFingerprint` 防篡改设计同构。现 `AgentState` 把 `observations.data` 全量塞进 state 的做法在 V2 中必须纠正（tool 全量返回值进 `agent_step` 表，state 只留 `ToolCallRecord` 摘要）。

---

## 4. Memory 架构设计

### 4.1 三层职责与载体

| 层 | 内容 | 载体 | 载体裁决 |
| --- | --- | --- | --- |
| **Working Memory** | 当前 run 的 AgentState：槽位、尾窗对话、工具摘要、控制预算 | LangGraph checkpoint → **PostgreSQL** | 用 PG 不用 Redis：worker 是 MQ 驱动的无状态进程，WAITING_USER 可能跨小时/跨天/跨进程重启，必须持久化；Redis 无持久化保证且团队已有 PG。Redis 继续只做它已擅长的事——provider 缓存（POI/ROUTE TTL 缓存，既有）。 |
| **Episodic Memory** | 每次运行的全量轨迹：每个节点的决策、LLM 元数据、工具调用、状态摘要 | **PostgreSQL** `agent_run` / `agent_step` | 用途是**审计、调试、回放、离线评估**（服务工程师与 eval 管线），不是给 LLM"回忆"用。结构化存储（JSONB 列 + 约束），可查询可聚合。 |
| **Long-term User Memory** | 跨会话用户偏好 | **PostgreSQL** `user_travel_profile`（**结构化枚举键**，非向量） | 见 4.2 论证。 |
| （既有）Semantic 知识 | 攻略事实、城市情报 | **pgvector**（`retrieval/` + DashScope embedding，已落地） | 向量的正确位置：非结构化文档的语义检索。继续沿用，不扩展到记忆域。 |

### 4.2 哪些数据必须结构化（为什么不用向量库存记忆）

**必须结构化的数据及理由**：

1. **约束槽位**：每个槽要参与硬约束判定、投影到 `TripConstraints`、做冲突检测——这是逻辑运算，不是语义相似度。向量检索"相似约束"毫无意义且危险。
2. **用户画像偏好**（pace/budget_band/mobility/transit_pref…）：需要精确读写、用户确认/撤回（ADR-011 的 pending→confirmed 语义）、审计与 GDPR 式删除。向量是"模糊的相似"，这里需要"精确的值 + 明确的生效状态"。
3. **轨迹（agent_run/agent_step）**：回放要求**按 seq 精确重演**，任何近似检索都会破坏可复现性。
4. **对话历史**：多轮澄清靠的是结构化槽位状态而非聊天记录相似度；`conversation` 尾窗 + 槽位投影已覆盖 LLM 需要的上下文。

**裁决：pgvector 只用于它已服务好的攻略知识检索（`retrieve_guide_knowledge`）。对话、记忆、画像一律结构化。** 理由：记忆的价值在**可审计、可撤销、可解释**（"系统为什么给我推日出路线？——因为你 3 月 2 日确认了 pace=relaxed"），向量检索三者皆无，且把不确定性引入了确定性系统的输入侧——违反本项目的第一原则。

### 4.3 表结构（Python 侧 `agent` schema，不碰 Java `business` schema——对齐 P1.6）

```sql
CREATE SCHEMA IF NOT EXISTS agent;

-- ── Episodic：run 头表 ────────────────────────────────────────────
CREATE TABLE agent.agent_run (
    run_id            UUID PRIMARY KEY,                    -- uuid5(NAMESPACE_URL, 'trip-pilot/agent-run/{command_event_id}')
    command_event_id  VARCHAR(80)  NOT NULL,
    task_id           UUID,                                -- DIALOGUE 类可为空
    trip_id           UUID         NOT NULL,
    user_id           UUID         NOT NULL,
    trace_id          VARCHAR(64),
    kind              VARCHAR(20)  NOT NULL,              -- CREATE/REPLAN/CANDIDATE/DIALOGUE
    status            VARCHAR(20)  NOT NULL,              -- RUNNING/WAITING_USER/SUCCEEDED/FAILED/CANCELLED/EXPIRED
    phase             VARCHAR(30),
    stop_reason       VARCHAR(40),
    input_ref         JSONB,                               -- 触发命令摘要（不存全量 payload）
    output_ref        JSONB,                               -- 产物引用 {itinerary_version_id, ...}
    budgets           JSONB,                               -- {steps, llm_calls, prompt_tokens, completion_tokens, wall_ms}
    checkpoint        JSONB,                               -- LangGraph checkpoint（或独立 checkpoint 表，见注）
    idempotency_key   VARCHAR(120) NOT NULL UNIQUE,        -- = run_id 派生串，命令重投不产生新 run
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    heartbeat_at      TIMESTAMPTZ                            -- reaper 识别孤儿 run
);
CREATE INDEX idx_agent_run_trip   ON agent.agent_run (trip_id, created_at DESC);
CREATE INDEX idx_agent_run_stale  ON agent.agent_run (status, heartbeat_at)
    WHERE status = 'RUNNING';

-- ── Episodic：step 明细（ADR-012 可复现性对齐）────────────────────
CREATE TABLE agent.agent_step (
    step_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id            UUID NOT NULL REFERENCES agent.agent_run(run_id),
    seq               INTEGER NOT NULL,
    node              VARCHAR(40) NOT NULL,               -- receive_input/understand/...
    driver            VARCHAR(12) NOT NULL,               -- LLM / DETERMINISTIC
    decision          JSONB,                              -- {thought, tool, args_digest}（LLM 节点）
    tool_calls        JSONB,                              -- [{tool, args_digest, ok, error_code, latency_ms, attempt}]
    llm_meta          JSONB,                              -- {model, temperature, seed, prompt_template, prompt_template_hash, prompt_tokens, completion_tokens}
    state_digest      VARCHAR(64),                        -- step 前状态哈希（防篡改/对账）
    state_delta       JSONB,                              -- 增量（可重建状态链）
    error_code        VARCHAR(60),
    started_at        TIMESTAMPTZ NOT NULL,
    duration_ms       INTEGER,
    UNIQUE (run_id, seq)
);

-- ── Long-term：用户画像（V3；pending/confirmed 双栏对齐 ADR-011）──
CREATE TABLE agent.user_travel_profile (
    user_id           UUID PRIMARY KEY,
    pending           JSONB NOT NULL DEFAULT '{}',        -- 模型提炼、待用户确认
    confirmed         JSONB NOT NULL DEFAULT '{}',        -- 枚举键：pace/budget_band/mobility/transit_pref/...
    revision          INTEGER NOT NULL DEFAULT 0,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

> 注：LangGraph 官方 `langgraph-checkpoint-postgres` 的 saver 表与上面 `checkpoint JSONB` 二选一。建议直接用官方 saver（省掉序列化维护），`agent_run.checkpoint` 存 saver 的 thread 指针即可；若引入官方 saver 表，命名放 `agent.checkpoints`。

---

## 5. Tool 设计

### 5.1 八个现有工具逐个裁决

原则：**LLM 只能提出意图（读事实、问用户、给提议）；一切写状态与放行动作由确定性代码在节点内完成。**"图结构的边"比"工具内的守卫"更强——守卫可被绕过，边不可绕过。

| 工具 | 是否存在 | 是否暴露给 LLM | 裁决理由 |
| --- | --- | --- | --- |
| `update_constraints` | 存在（转为内部函数 `merge_slots`） | **否（移出）** | D5 的根治：让 LLM 直接写约束状态 = 让它直接修改核心业务状态。改为：`understand` 节点产出**提议**（structured output）→ `merge_slots` 确定性落槽 + 规则化判定 source/confirmed。工具签名消失，语义更严格。 |
| `ask_user` | 存在 | **是（升级）** | 唯一的"写交互状态"工具，但写的是对话流不是业务状态。升级为结构化输出：`{question, options[], expects}`（P1.3），前端渲染选项 chip，用户点选 = 确定性答复。 |
| `search_place` | 存在 | **是** | 只读事实工具，地面化槽位（verified 轴）的主力。保留。 |
| `get_route` | 存在 | **是（降优先级）** | 只读。对话期 LLM 很少需要裸路线，但"为什么这么排"类问题（V2 explain）会用到。保留，暴露不裁剪。 |
| `check_opening_hours` | 存在 | **是** | 硬事实工具的样板（查不到返回 UNKNOWN，不编造）。保留。 |
| `retrieve_guide_knowledge` | 存在 | **是** | RAG 只读工具，接既有 pgvector 知识库。保留。 |
| `validate_itinerary` | 存在（转为 `gate_result`/管线内建） | **否（移出）** | D3/D4 的根治：校验不是 LLM 的可选项，是**必经的图边**。现状它校验的是 slots（D4 错位），移入管线后校验对象是真实 candidate itinerary；BLOCKED 分支才触发 `propose_relaxation`。从 LLM 工具表删除。 |
| `emit_itinerary` | 存在（转为 `deliver` 节点） | **否（移出）** | "一票否决靠检查 observations 里有没有 validate 成功记录"是把安全属性建立在 LLM 的调用序列上。V2 中 deliver 只能从 `gate_result=PASS` 的边到达——**用图拓扑替代运行时检查**，结构上不可绕过。 |

新增工具（克制）：`query_current_plan`（读当前版本摘要/差异，服务 QUESTION 意图，V2）、`get_fact_status`（读 fact_impacts 聚合，服务"数据可信吗"问题，V2）。两者均只读。路线图 P2.2 的 `build_itinerary` **不作为 LLM 工具**——"何时开始规划"由 `check_readiness` 的确定性规则决定，不由 LLM 决定（LLM 想提前规划就绕过了澄清门）。

**V2 的 LLM 工具面（6 个）**：`ask_user` / `search_place` / `get_route` / `check_opening_hours` / `retrieve_guide_knowledge` / `query_current_plan`。比现在还少 2 个——**工具面收敛是成熟标志，不是能力倒退**。

### 5.2 统一 ToolResult v2 契约

现状 `ToolResult{ok, summary, data, error_code}` 缺三样东西：失败分类（驱动重试策略）、前端展示载荷（驱动卡片）、来源引用（接入既有 fact_impacts/provenance 链）。

```python
class ErrorCategory(str, Enum):
    TRANSIENT = "TRANSIENT"                    # 网络/超时/限流 → 退避重试
    PERMANENT = "PERMANENT"                    # 参数错/不存在 → 不重试，转告用户
    CAPABILITY_MISSING = "CAPABILITY_MISSING"  # 未配置 → 降级（DEMO 标注），fail-closed
    VALIDATION = "VALIDATION"                  # 入参 schema 不合法 → 不重试

@dataclass(frozen=True, slots=True)
class ToolError:
    code: str                       # 稳定错误码（UNKNOWN_TOOL/CAPABILITY_MISSING/...）
    category: ErrorCategory
    message: str                    # 给日志/轨迹
    user_message: str | None        # 给用户的安全话术（不含内部细节）

@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    summary: str                    # 给 LLM：一句话事实摘要（prompt 预算内）
    data: Any = None                # 给确定性代码：全量结构化结果（不进 state）
    display: dict | None = None     # 给前端：卡片载荷（可选）
    error: ToolError | None = None
    citations: tuple[dict, ...] = ()  # 对齐 KnowledgeCitationSnapshot / fact_impacts
    latency_ms: int = 0

@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict              # JSON Schema（hand to model + validator 双用，沿用现状）
    output_schema: dict             # 新增：成功载荷 schema
    error_schema: dict              # 新增：错误载荷 schema（code 枚举固定）
    handler: ToolHandler
    timeout_seconds: float = 8.0    # 新增：工具级超时
    max_attempts: int = 1           # 新增：工具级重试上限（TRANSIENT 类才重试）
```

`ToolRegistry.invoke` 升级（D2 修复）：统一捕获异常 → 按异常类型映射 `ErrorCategory`（`httpx.TimeoutException/ConnectError → TRANSIENT`，入参校验失败 → `VALIDATION`，未配置 → `CAPABILITY_MISSING`）→ 返回失败 ToolResult + ERROR observation，**handler 异常永不冒泡击穿 run**。schema 三件套均带版本号，纳入既有 schema_version 门禁体系。

---

## 6. Java / Python 边界设计

### 6.1 能力归属表

| 能力 | 归属 | 理由 |
| --- | --- | --- |
| 用户身份、行程/版本持久化、回滚、分享导出 | **Java** | 业务事实权威：`itinerary_version` 哪个是"当前正式版"只有 Java 说了算 |
| 任务状态机（9 态）、幂等键、Idempotency-Key 校验 | **Java** | 事务边界在 Java（outbox + 唯一约束） |
| SSE 通道与事件回放（Last-Event-ID） | **Java** | 已落地，`planning_task_event` 表即事件存储 |
| 规划命令的创建与撤销（outbox → MQ） | **Java** | 已落地 |
| 意图理解、槽位抽取、澄清、解释、放松提议 | **Python（LLM 节点）** | Agent 编排层（ADR-005：规划能力留 Python；ADR-015：编排队列在 Python） |
| 确定性规划管线、feasibility、repair、evaluation | **Python（内核）** | 已落地，不动 |
| 工具运行时（registry/超时/重试/降级） | **Python** | 与 LLM 同进程才能 fail-closed |
| agent_run / agent_step / checkpoint / profile | **Python**（独立 `agent` schema） | 对齐 P1.6；Java 只读事件透传，不解轨迹 |
| 事件透传到前端（新 AGENT_* 事件） | **Java**（parser + SSE 透传） | 复用既有监听器模式 |

### 6.2 事件流设计（用户点名的 5 个事件逐一裁决）

裁决原则：**每条总线事件必须有唯一的事实源。既有 `PLANNING_*` 生命周期事件已经覆盖了 run 的宏观状态，重复发 AGENT_START/COMPLETE 会制造双源真相，Java 状态机将出现二义性。**

| 候选事件 | 裁决 | 理由 |
| --- | --- | --- |
| `AGENT_START` | **不新增**，由既有 `PLANNING_PROGRESS(stage=TASK_ACCEPTED, 5%)` + `planning_task_event` 承载 | 启动事实已有唯一源；再加一个事件 Java 要处理两个"开始" |
| `AGENT_STEP` | **不进总线**。step 落 `agent_step` 表；前端可见性由克制版 `AGENT_TOOL`（阶段粒度）+ 轨迹查询 API 承载 | 每步一事件 = 刷屏 + MQ 放大 + 与 progress 事件交错语义混乱（P2.7 "克制版"的正解） |
| `AGENT_ASK_USER` | **新增（schema v1）** | 澄清是新的用户可见状态，需要结构化载荷：`{taskId, tripId, runId, question{text, options[], expects}, phase, expiresAt}` → Java 落 `planning_task_event` → SSE，前端渲染澄清卡。任务状态同时置 `WAITING_USER`（复用既有状态与 SSE 终态语义） |
| `AGENT_RESUME` | **不作为事件；作为命令 `AGENT_DIALOGUE_INPUT`（routing key `agent.dialogue`）** | 恢复是用户→系统方向，是命令不是事件。载荷：`{runId, answer{kind: OPTION_CLICK/TEXT/CARD, optionId?, text?}, answerEventId}`；`answerEventId` 作幂等键。语义与既有 `PLANNING_REVIEW_REQUIRED → 用户决议` 同构 |
| `AGENT_COMPLETE` | **不新增**，由 `PLANNING_COMPLETED / PLANNING_REVIEW_REQUIRED / PLANNING_FAILED` 承载 | 终态事实已有唯一源与版本门禁（schema 9/10/11） |

新增事件（克制集）：

| 事件 | 方向 | schema | 载荷要点 |
| --- | --- | --- | --- |
| `AGENT_ASK_USER` | Py→Java（event exchange, key `agent.ask-user`） | v1 | 结构化澄清卡 + 过期时间 |
| `AGENT_MESSAGE` | Py→Java（key `agent.message`） | v1 | 阶段性说明/解释卡片（explain_result 的对话侧出口） |
| `AGENT_THINKING` / `AGENT_TOOL` | Py→Java（key `agent.trace`） | v1 | **阶段粒度**（进入节点/工具类别+耗时），非每 LLM 步；V2 引入 |
| `AGENT_DIALOGUE_INPUT` | Java→Py（command exchange, key `agent.dialogue`） | v1 | 用户答复命令；带 `answerEventId` 幂等键 |

### 6.3 RabbitMQ 是否需要调整

**拓扑基本不动，只加绑定**——这是本方案对既有基建的尊重，也是风险最小的路径：

1. `trip.command.exchange` 新增 binding：`agent.dialogue` → 既有 `planning.create.queue`（复用消费者与 prefetch=1；或独立 `agent.dialogue.queue`，若希望对话与规划消费互不阻塞——**建议独立队列**，对话请求轻而快，不应排在长规划任务后面）。
2. `trip.event.exchange` 新增 3 个 binding：`agent.ask-user` / `agent.message` / `agent.trace` → 新队列 `agent.dialogue.event.queue`，Java 新增对应 Listener（复制 `PlanningProgressEventListener` 模式，工作量小）。
3. DLX / 重试 / publisher-confirm / prefetch 策略**全部沿用**；死信绑定 `planning.#` 需扩为 `planning.#` + `agent.#`。
4. 所有新事件/命令走 schema_version 门禁（Java parser 白名单），历史事件只读兼容（P1.8 原则）。
5. **不引入新的交换机类型/延迟队列/请求-应答模式**。澄清的"等待"用 checkpoint + 新命令实现，不需要延迟消息。

---

## 7. 前端交互设计

### 7.1 三方案对比

| 维度 | 方案 A：纯聊天 | 方案 B：聊天 + 卡片 | 方案 C：Workspace Copilot |
| --- | --- | --- | --- |
| 用户体验 | 全部能力塞进对话流：改行程靠打字描述，地图/编辑/版本全部退化；行程这种强结构对象用聊天操作效率极低 | 对话负责意图与澄清，结构化对象（约束、行程、评审、版本）全部以卡片落在 Workspace 原生组件 | 对话常驻侧栏，可直接操纵工作区（选中某天、应用修改）；体验最好 |
| 开发成本 | 低（但**负资产**：要以破坏既有产品为代价重做一遍低配版） | 中：新增对话面板 + 卡片协议；复用现有评审/版本/约束组件 | 高：需要"对话动作 → UI 操作"的确定性映射层 + 双向状态同步 |
| Agent 特性体现 | 最强（对话即一切），但体现的是错误的 Agent 观——把 Agent 当产品替代品 | 好：Agent 的理解/澄清/解释以卡片显性化，确定性产物的权威展示不受损 | 最强且正确：Agent 作为副驾增强而非替代 |
| 与既有产品冲突 | **致命**：TripWorkspace / TripDetail / 地图 / 编辑 / 版本 Drawer / 回滚全部被边缘化 | 无冲突：对话是新入口，产物全部回流既有组件 | 无冲突，但工程量大 |

### 7.2 推荐方案：B（聊天 + 卡片），C 作为 V3 演进目标

**推荐方案 B。** 决定性理由：TripPilot 已有一个成熟的强结构 Workspace（版本、回滚、feasibility 报告、评审面板、地图、约束编辑器），Agent 化的正确姿势是**给 Workspace 加一个理解自然语言的入口**，而不是把 Workspace 降维成聊天记录。这与 ADR-015 已定的"对话入口与 TripWorkspace 并行，只做对话流+约束卡片+澄清问答"完全一致。

B 方案的卡片协议（每张卡 = 一类事件或产物，答复尽量点选化）：

| 卡片 | 数据源 | 用户操作 | 落点组件 |
| --- | --- | --- | --- |
| 澄清卡 | `AGENT_ASK_USER` | 点选选项 / 自由输入 → `AGENT_DIALOGUE_INPUT` | 新组件 `AgentDialogPanel` |
| 进度卡 | 既有 `PLANNING_PROGRESS` | 只读 | 复用 `PlanningProgress` |
| 结果解释卡 | `AGENT_MESSAGE`（explain 产物） | 只读 + "为什么"展开 | 新组件；数字复用 `PlanEvaluationPanel` / `FeasibilityReportPanel` |
| 放松建议卡 | `propose_relaxation` 产物 | 点选接受某建议 → 进入重规划 | 复用 `PlanningReviewPanel` |
| 评审卡 | 既有 `PLANNING_REVIEW_REQUIRED` | 批准/驳回/调整 | 复用 `PlanningReviewPanel` |
| 版本/回滚 | 既有版本事件 | 不变 | **不动 `ItineraryVersionPanel`** |
| 约束修改 | 用户操作 | ConstraintEditor 为权威编辑面；对话修改走 candidate-validation | **不动 `ConstraintEditor`** |

三条不破坏承诺：(1) 对话不产生"平行的行程真相"，一切行程变更仍走 itinerary_version 单调版本链；(2) 不移除任何现有入口，Agent 面板是增量；(3) 用户关掉对话面板，系统行为与今天完全一致（LLM 全部降级为确定性路径）。

---

## 8. 工程可靠性：生产级 Agent Runtime

在图之外包一层 `AgentRuntime`，它不参与决策，只负责让图"死得明白、活能续上"：

```
AgentRuntime
├── 预算治理    BudgetGovernor：steps / tool_calls / llm_calls / tokens / wall-clock 五维预算，
│               触顶 → 优雅收敛（finish with partial + 明确 stop_reason），绝不静默死循环
├── 超时        每 LLM 调用 8s（沿用）；每工具 spec.timeout；run 级 deadline（asyncio.timeout 包裹 ainvoke）
├── 异常分类    LLM: 解析失败→重试→降级；HTTP 超时→降级（D1 修复）
│               工具: ToolError.category 驱动重试/转告/降级（D2 修复）
├── checkpoint  每个超步（super-step）后写 PG（langgraph-checkpoint-postgres，thread_id=run_id）
│               写 checkpoint 在任何副作用（发事件、落产物）**之前**
├── 幂等        run 级：idempotency_key = uuid5(command_event_id)（继承既有约定）
│               恢复级：answerEventId 幂等；交付级：确定性 event id（既有）
├── 恢复        worker 崩溃 → nack(requeue)（既有）→ 新进程从 checkpoint 续跑
│               WAITING_USER 存 PG，与进程无关；heartbeat + reaper：RUNNING 超时无心跳 → 重新入队或 FAILED
│               WAITING_USER TTL 72h → EXPIRED（run 级，§3.2 裁决的落点）
├── 取消        节点边界检查 CancellationOracle（既有，PG 直查状态）+ 进程内 CancellationRegistry；协作式，不强杀
├── 轨迹        agent_step 全量落库（含 llm_meta: model/temperature/seed/prompt_hash/tokens——ADR-012 对齐）
├── 回放        确定性节点：bit 级重放；LLM 节点：按记录重放（不重调模型）；
│               state_digest 链校验完整性 → 支持离线评估与事故复盘
└── 观测        traceId 全链路透传（既有）+ 结构化日志（既有）+ 每节点延迟/成功率/预算消耗指标（新）
```

九项检查点的落点对照（用户清单 → 方案位置）：LLM timeout→Runtime 超时+降级阶梯（§2.4-5）；Tool exception→ToolError 分类（§5.2）；循环失控→三重上限+预算治理+stop_reason 显式化；幂等→三层幂等键（§8 幂等）；checkpoint→PG saver+副作用前置写；任务恢复→nack requeue+checkpoint 续跑+reaper；用户中断→协作式取消+WAITING_USER 即中断点；轨迹记录→agent_run/agent_step；可回放→digest 链+记录重放。

**验收不变式**（纳入既有测试门禁，Python 1732 / Java 558 / Web 446 不降）：任意时刻 kill -9 worker，系统要么在原地续跑、要么给出明确终态，绝不出现"无声无息丢失"；无 LLM Key 环境全链路可跑（DEMO）；同一命令重投 N 次，结果幂等。

---

## 9. 版本路线图（汇总）

| 版本 | 内容 | 对应既有路线 | 关键验收 |
| --- | --- | --- | --- |
| **V1 最小可用** | D1–D5 修复；三轴槽位模型；`agent_run`/`agent_step` 表；PG checkpoint；ASK_USER/DIALOGUE_INPUT 契约；understand→dispatch 最小接线 | P1.1–P1.9 + P2.1 最小子集 | 测试基线不降；无 Key 全链路可跑；kill -9 可恢复；澄清往返闭环 |
| **V2 增强** | route_intent 全量分支；MODIFY→impact_check→replan/candidate-validation；propose_relaxation；explain_result；克制版 trace 事件；前端对话页（方案 B）；工具异常分类 | P2.1–P2.8 | 端到端"对话→规划→修改→解释"闭环；9 个 benchmark 场景结果一致或更优 |
| **V3 生产级** | user_travel_profile（pending/confirmed）；TTL/EXPIRED/reaper；轨迹回放评估；Copilot 侧栏（方案 C）；（视时间）planner 策略节点 | P3.1–P3.5 | 跨会话偏好生效且可撤回；回放评估纳入 CI 可选门 |

---

## 10. 反面清单

### 10.1 不要做（明确否决）

1. **不要让 LLM 生成或修改行程 JSON**。行程是核心业务产物，只能出自确定性管线；LLM 一旦直写产物，可行性校验再严也只是在擦屁股。
2. **不要多 Agent 协作/Supervisor**（ADR-010 已否决，本方案重申）。本域没有需要多视角协商的问题。
3. **不要自由 ReAct 循环做规划**。LLM 循环只在理解层，且有界；规划环永远确定性。
4. **不要把既有确定性管线拆成 LangGraph 步骤**。它有自己的进度事件、重试、降级、有界修复；包一层节点边界即可，包内部是纯粹的破坏。
5. **不要向量库存对话/记忆/画像**（§4.2）。向量只留在攻略知识检索。
6. **不要 AGENT_START/AGENT_STEP/AGENT_COMPLETE 上总线**（§6.2）。双源真相比没有事件更糟。
7. **不要 token 级流式输出**。SSE 事件级（阶段/卡片）已满足需求，token 流是成本黑洞且与 MQ 无状态 worker 模型冲突。
8. **不要常驻对话进程 / LangGraph Platform**。暂停恢复用"checkpoint + 新命令"实现，与现有 MQ 架构同构。
9. **不要删除 AskingDecider 与 DEMO 模式**。它们是降级阶梯的终点和测试底座，是"LLM 挂了系统还能跑"的保证。
10. **不要在 Agent 化中夹带 OR-Tools 引入或求解器重写**。那是独立的算法议题，混入只会让失败归因变难。
11. **不要让 Java 复刻任何规划逻辑**（ADR-005）。Java 是事实权威，不是第二个 planner。

### 10.2 属于过度设计（V3 之后再说或不做）

- Reflection 自反思循环、LLM Critic 给行程打分（已有 rule-v3，更客观）
- Memory Agent / 记忆检索 Agent 化（记忆是基础设施）
- 用户画像向量化 / 对话语义检索
- 每 LLM 步骤的实时前端可视化（阶段粒度足够）
- 一次请求并行跑多版本行程让 LLM 择优（成本翻倍，确定性系统不允许"择优幻觉"）
- MCP 工具市场 / 工具动态注册（工具面应小而稳，版本化管控）

### 10.3 遗留工程问题（与 Agent 化并行处理）

- `ortools==9.14.6206` 是死依赖：要么移除，要么单独立项评估"OR-Tools CP-SAT 替代 daily_schedule 贪心排程"——建议后者作为独立算法批次，先建立排程质量的 benchmark 再动手。
- 《系统架构》与《Agent 化路线图》中"OR-Tools 求解/调度"的表述应修正为"daily_schedule 确定性排程 + hard-validator + repair"，消除 F1 差异。

### 10.4 最能提升 Java 后端 / Agent 开发岗位简历竞争力的能力（按性价比排序）

1. **MQ 无状态 Worker × LangGraph PG Checkpointer 的暂停/恢复/幂等运行时**——Agent Runtime 工程是当前市场最稀缺的经验，且本项目的 MQ 同构恢复模型（checkpoint+新命令，非常驻进程）是有独立见解的设计，面试叙事极强。
2. **双端确定性 UUID 幂等 + 事务性 Outbox + schema 版本门禁的 LLM 事件扩展**——Java 后端含金量最高的部分，展示"把 LLM 系统当分布式系统做"的功力。
3. **fail-closed 槽位三轴状态机（state×source×verified）**——展示状态建模能力，直接回应"LLM 输出不可信"这一本质问题。
4. **可回放轨迹（agent_step + digest 链 + 记录重放 + 离线评估）**——AI 工程化的 eval 叙事。
5. **LLM 降级阶梯 + 预算治理**——可靠性工程叙事："我们假设 LLM 随时会挂"。
6. **结构化澄清协议（卡片点选 = 确定性答复）**——UX × 协议设计，展示产品级思考。
7. 既有加成如实呈现：SSE 断点续传 + 终态短路、版本/回滚/candidate-validation、dead-letter 全链路。

---

## 附：与既有决策的一致性对照

| 既有决策 | 本方案 | 一致性 |
| --- | --- | --- |
| ADR-005 规划能力留 Python | 编排层与内核均在 Python | 一致 |
| ADR-007 Demo 模式可运行 | AskingDecider 为降级终点，保留 | 一致 |
| ADR-010 单一 Agent | 0 个新增 Agent 角色 | 一致并强化 |
| ADR-011 偏好先待确认 | profile pending/confirmed 双栏 | 一致 |
| ADR-012 冻结快照/可复现 | agent_step llm_meta + state_digest + 引用化 artifacts | 一致并落地 |
| ADR-015 四层记忆 | §4 载体裁决具体化（checkpoint 用 PG，profile 用枚举键） | 一致并收敛其"待定问题" |
| 路线图 P1.5 REJECTED/USER_OVERRIDE | REJECTED 采纳；USER_OVERRIDE 以 source+override_of 承载 | 精化（语义更严，字段更少） |
| 路线图 P2.2 build_itinerary 工具 | 改为确定性 plan_execute 节点 | 精化（触发权归规则不归 LLM） |
| 路线图 P1.6 Python 侧 schema | agent schema 独立于 business | 一致（并收敛 ADR-015 范围行的二义） |

---

## 11. 实施记录：v0.1 可跑切片（方案 B）

- 状态：已实施（2026-08-29），Python 9 项新测试 + ruff 全绿；Java 编译通过；Web typecheck + 495 单测全过
- 范围：本节记录设计的第一块可运行纵切——**对话攒约束 → 澄清卡确认 → 一键应用并生成**

### 11.1 已实现

| 端 | 文件 | 内容 |
| --- | --- | --- |
| Python | `src/trip_agent/dialog/`（models / store / extractor / service / api） | 对话状态机：理解 → 提议（INFERRED）→ 确认卡（点选才 CONFIRMED）→ READY 摘要；无 Key 时确定性向导（人数→预算→节奏→必去） |
| Python | `main.py` | 挂载 `POST /internal/v1/agent/dialogue`（X-Internal-Token 守卫，沿用 `STRUCTURED_MODEL_*` 配置做槽位抽取） |
| Java | `agentdialog/AgentDialogController` + `HttpAgentDialogClient` | `POST /api/trips/{tripId}/agent-dialogue`：TripService 属主校验 → 同步转发，并把行程事实（目的地/日期）作为只读上下文传入 |
| Web | `components/AgentDialogPanel.vue` + TripWorkspace 接入 | 「AI 助手」悬浮按钮 + 右侧抽屉：气泡对话、澄清卡选项 chip、READY 后「应用并生成行程」（复用既有 version-aware 约束 PUT + `handleStartPlanning` + SSE 进度） |

### 11.2 与设计的偏差（有意为之）

1. **同步 HTTP 而非 MQ 命令**：v0.1 的对话是请求-应答式（每轮一次 POST），未引入 `AGENT_DIALOGUE_INPUT` 命令与事件。理由：最小纵切优先验证产品形态；guide-import 已有同步 HTTP 先例。迁到 MQ 属于 V1 正式范围。
2. **状态存 Redis（7 天 TTL，故障降级进程内存）而非 `agent_run` 表**：对话是可弃草稿态，丢失代价为零；`agent_run`/`agent_step` 落库随 MQ 化一起做。
3. **目的地/日期只读**：`updateTripMetadata` 仅支持标题，行程目的地与日期不可经对话修改——由 Java 以 `TripContext` 注入作为已确认事实（source=TRIP），对话只收集约束（人数/预算/节奏/必去），与"Java 是事实权威"一致。

### 11.3 本地运行

1. `cp .env.example .env`，默认 `PROVIDER_MODE=DEMO_ONLY` 即可跑（无需任何模型 Key）。
2. 可选：填 `STRUCTURED_MODEL_ENDPOINT/API_KEY/NAME`（OpenAI 兼容 chat-completions 完整 URL）启用自由文本抽取；留空则走向导向答。
3. 按本地运行指南起 compose；进入某行程详情页 → 右下角「AI 助手」→ 对话/点选 → 「应用并生成行程」。

### 11.4 后续（进入 V1 正式范围）

- 对话链路 MQ 化（`AGENT_ASK_USER` 事件 + `AGENT_DIALOGUE_INPUT` 命令），`agent_run`/`agent_step` 落库
- 抽取证据链（quote 引用）接入；`avoid` 槽位进向导；目的地/日期修改走 candidate-validation
- Java/Web 侧契约测试；AgentDialogPanel 组件测试；澄清卡接入 SSE 推送（当前为同步响应）

---

## 12. 实施记录：方案 C —— 对话式建行程（已实施）

- 状态：已实施（2026-08-29），Python 14 项 dialog 测试全绿；Java 编译通过；Web typecheck + 495 单测全过；真实 HTTP 端到端验证「对话 → 建行程 → 规划 SUCCEEDED」
- 入口：行程列表页「AI 帮我规划」主按钮（原「创建旅行」降为次按钮）

### 12.1 链路

```
Dashboard「AI 帮我规划」→ 客户端生成 sessionId → 对话（创建模式：目的地/日期/人数/预算/节奏/必去）
  → READY 摘要 → 「创建行程并开始规划」
  → POST /api/agent/trips {sessionId}
      Java 拉取 GET /internal/v1/agent/dialogue/confirmed/{sessionId}（确认槽位的事实源在 agent 侧）
      → tripService.create（同一条版本化创建路径；travelerType 由人数派生，region 暂空）
  → createPlanningTask → 跳转详情页 → 既有 SSE 接管
```

### 12.2 关键实现点

- **创建模式会话**：`DialogueRequest` 增加 `sessionId`；存储键 `create:{sessionId}`（trip 模式为 `trip:{tripId}`）；目的地/开始/结束日期在创建模式下进向导（trip 模式仍由 Java 事实注入跳过）
- **日期解析**：`_parse_date_text` 支持 `2026-10-01` / `2026年10月1日` / `10月1日`（缺省年份取最近的未来日期）；结束日期早于开始日期会被拒绝并重问
- **LLM 抽取扩展**：schema 增加 destination/start_date/end_date，抽取值同样只作 INFERRED 提议、需确认
- **契约坑**（已修）：Java 可空 `Boolean reset` 序列化为 `null` 会被 pydantic `bool` 拒绝（422）→ 控制器与命令一律用原始 `boolean`

### 12.3 边界与后续

- 目的地暂不传 RegionRef（`validateRegion(null)` 放行）；若某目的地规划前置失败，回退手动表单补齐行政区划
- `must_visit` 仅存名称串（不落 PlaceRef），实体锚点仍由详情页编辑器补齐
- 对话式修改已建行程（改日期/目的地触发 replan）是下一步
- **入口统一（2026-08-29 追加）**：Dashboard 移除「创建旅行」按钮，「AI 帮我规划」成为唯一创建入口；手动创建表单保留全部能力，收敛为 AI 面板内的「手动填写创建表单」回退链接（经 `manualCreateSignal` 打开，Escape 后焦点回落 body）。测试同步改写：B13 断言单一入口 + 信号开表单，App.test 12 处链路走 `openCreateForm()` 辅助；vitest 495/495、typecheck 全绿
