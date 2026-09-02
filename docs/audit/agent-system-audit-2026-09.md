# TripPilot Agent 系统级审计报告

日期：2026-09-02
范围：`apps/agent-service` + `apps/travel-server` + `apps/web`（全链路 Agent 闭环）
审计方式：真实代码引用（file:line）+ 运行时测试/仿真，非设计文档推断
执行原则：找真实问题，不以"证明是 Agent"为目的

***

## 0. 结论速览

> **TripPilot 不是伪 Agent，也不是 LLM Wrapper。**
> 存在真实 LangGraph ReAct 循环（decide→act→observe→decide→finish），
> Decision 基于 State（slots/observations/failure\_kind/plan\_evaluation），
> Tool Result 写回 observations 并进入下一轮决策，状态可持久化/恢复/续跑，
> 完成受确定性 Gate 把关，schedule/cost/route 由确定性引擎计算。

> **Agent Maturity Level（自评）：Level 4（Autonomous Planning Agent）**
> 已具备 Level 5 的多数要素（持久化、恢复、HITL、闭环、Gate），
> 距"可靠生产 Agent"的差距是若干 P2/P3 硬化项（并非缺失基础能力）。

> **关键架构事实（必须引起注意）**：Agent 循环实际产出两条链路——
> ① **Agent 对话框链**（`agent_processor` AGENT\_START/AGENT\_RESUME）构建行程但其
> `AGENT_COMPLETED` 在 Java 侧**仅存为 dialog 消息、不落库**；
> ② **Planner 管线链**（`PLANNING_*` → `PlanningCompletionService`）才是权威落库 +
> 置 `trip.status=COMPLETED` 的路径。
> 即：**"Agent 建的行程"是预览，系统持久化的行程由确定性管线重算**。
> 这是审计发现的最高价值项（见 AUDIT-01），非缺陷性的功能项，但需明确归边。

***

## 1. Executive Summary

| 维度             | 结论                          |
| -------------- | --------------------------- |
| 是否真 Agent Loop | ✅ 是（LangGraph 有界循环）         |
| 是否兑现旅行规划       | ✅ 是（真实 E2E：生成→Gate→落库→前端展示） |
| 主要能力等级         | Level 4（自主规划 Agent）         |
| P0 缺陷          | 0                           |
| P1 缺陷          | 0                           |
| P2 缺陷          | 1（双完成链冗余/分叉）                |
| P3 缺陷/观察       | 2（CREATE 路径输出侧预校验、无模型降级语义）  |
| 伪 Agent 迹象     | 未发现（详见 §5）                  |

***

## 2. Agent Architecture（真实代码依据）

### 2.1 运行态循环（非设计文档，依真实代码）

```
START → _decide_node ──工具待定──→ _act_node ──写回 observation──→ _decide_node …
                 │                                                    │
                 └──── stop_reason∈{EMITTED,ANSWERED,WAITING,CEILING} ┘
                                                                      ↓
                                                              _finish_node → END
```

- 循环与边界：`agent/graph.py` L50-52（`MAX_STEPS=8`/`MAX_TOOL_CALLS=16`/`MAX_LLM_CALLS=8`）、L58-55（`STOP_CEILING`/`STOP_BUDGET`）

- 节点实现：`agent/graph.py` L768-812（`_decide_node`/`_act_node`，tool result 包装成 `ToolObservation` 写回 state）

- Deterministic 发射：`graph.py` L13-18（validate\_itinerary 通过即自动 EMITTED，模型无 emit 工具）

### 2.2 三层对话/对话 + 规划边界

| 层           | 入口                                                        | 职责                                                        | 落库？                                        |
| ----------- | --------------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------ |
| 槽位收集中断      | `dialog/service.py` L575-606                              | 确定性收集约束（COLLECTING/READY），`START_PLANNING` 由前端截获          | 对话消息                                       |
| ReAct Agent | `worker/agent_processor.py` L200-331（AGENT\_START/RESUME） | decide/act/reflect，可 `build_itinerary`（Real/Demo builder） | AGENT\_COMPLETED 仅 dialog 消息               |
| Planner 管线  | `worker/processor.py` / `workflow/planner_pipeline.py`    | 权威确定性规划                                                   | `PlanningCompletedEvent`→Java 落库+COMPLETED |

***

## 3. Agent Loop Verification

| Capability        | Status   | Evidence                                                                                                                                    |
| ----------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| State             | **PASS** | `agent/state.py` L265-314（AgentState 全字段）；migrations V1（agent\_run/step/checkpoint）                                                         |
| Decision          | **PASS** | `graph.py` L568-589（DECISION\_SCHEMA 约束）+ L628-650（非法输出→确定性降级）+ L680-709（prompt 含 slots/recent\_observations/plan\_evaluation）              |
| Action            | **PASS** | `graph.py` L652-678（tool→ToolCall/未知→ask\_user/缺失→追问）                                                                                       |
| Tool              | **PASS** | `agent/tools.py` L35-75（ToolSpec/ToolResult/ToolCall 统一抽象）                                                                                  |
| Observation       | **PASS** | `state.py` L252-264（ToolObservation 写回并 render 供决策）；`graph.py` L768-812                                                                     |
| Loop              | **PASS** | `graph.py` L768-812（decide/act 循环）                                                                                                          |
| Loop 保护           | **PASS** | `graph.py` L50-55（三重 ceiling）；运行时 test\_reflection\_loop/绑顶用例通过                                                                             |
| Recovery          | **PASS** | `persistence.py` L255-286（checkpoint 落 PG）、L324-389（run 中持久化）；`agent_processor.py` L249-335（handle\_resume 新鲜度/去重/恢复）                       |
| Human-in-the-loop | **PASS** | `agent_processor.py` L249-268（WAITING\_USER TTL 过期）、ask\_user 工具；`graph.py` L178-289（AskingDecider/升级问题）                                    |
| Completion Gate   | **PASS** | `agent/feasibility_gate.py` L29-67（StructuralFeasibilityGate）；Planner 侧 `worker/processor.py` L238-294 + Java `PlanningOutcomeGuard` L32-63 |
| 确定性引擎分工           | **PASS** | `planning/daily_schedule.py` L3-59（时间/时长确定性）、`cost_model.py` L1-20/L104-152（成本确定性）、providers/route retry                                    |

***

## 4. Defects

### AUDIT-01（P2）双完成链冗余/分叉

- **位置**：`worker/agent_processor.py` L429-458（Agent 发 AGENT\_COMPLETED 且带 itinerary）；Java `agentdialog/AgentDialogEventService.java` L56-63（handleCompleted 仅 `persist` 消息）；Java `planning/PlanningCompletionService.java` L112-136、L183-194、L451-471（真正落库+COMPLETED）

- **证据**：Agent 对话框链把完整行程塞进 `AgentCompletedEvent`，但 `AgentDialogEventService` 只把它作为 dialog 消息落库，不建 itinerary、不改 trip.status；真正落库走独立的 `PLANNING_COMPLETED` 链。

- **根因**：对话 Agent 与权威 Planner 是两条独立链路，设计上"Agent 负责对话、Planer 负责权威生成"，但 Agent 端仍构建/发射了完整行程（冗余计算）。

- **影响**：① 同一份行程被算两次；② Agent 展示的行程与最终持久化行程可能分叉（若重算偏好不一致）；③ 审计/排障时易误判"Agent 已完成落库"。

- **建议**：明确归边——若 Agent 行程仅是预览，则 `AGENT_COMPLETED` 只发简短摘要/槽位，不携带完整 itinerary；若要以 Agent 行程为权威，则将其送入同一 Gate 持久化而非重算。二选一，消除双写心智负担。

### AUDIT-02（P3）Planner CREATE 输出侧缺前置天数校验

- **位置**：`worker/processor.py` L238-294 `_outcome_event`（仅判 `not report.has_blocker`）

- **证据**：CREATE 路径发出 `PlanningCompletedEventV11` 前，Python 侧未校验 `days` 数与 `(end-start+1)` 一致；该校验只在 Java 接收侧 `PlanningOutcomeGuard.validateDates` L32-44 兜底，以及 Replan/Candidate 输入侧 `contracts.py` 存在。

- **影响**：Python→Java 需依赖第二道闸拦截非法完成，无法 fail-fast；不满足"在源头拒绝"。

- **建议**：在 `_outcome_event` 前对 result.itinerary 做"天数=日期区间 + 每天≥1活动"预校验，命中则走 `PlanningReviewRequired`/`FAILED`，避免把非法结果送进 RC。

### AUDIT-03（P3）无模型配置时的确定性降级语义需明示

- **位置**：`graph.py` L16-18（model 可选）、L178-289（AskingDecider fallback）

- **证据**：未配置 API key 时决策完全确定性（无自主推理），仅"入口补槽+到点发问"。

- **影响**：若部署未接模型，则只能得到 Level 2（Workflow）行为，却可能被当成 Level 4 卖点。

- **建议**：健康检查/运行时暴露"当前 decider=STRUCTURED|DETERMINISTIC"，文档明确生产必须接模型。

> 说明：多次审计**未发现** P0/P1（无空结果完成、无无限循环、无状态丢失、无不落库）。

***

## 5. Pseudo-Agent Findings

逐一排查五类伪 Agent，**均不成立**：

1. **LLM→固定 Pipeline→END**：❌ 不存在。真实有 decide⇄act 循环（graph.py L768-812）。
2. **if step==1 search / step==2 plan**：❌ 不存在。决策由 `DecisionMaker`（模型或 AskingDecider）基于 State+failure\_kind+reflection 产生，非序号推进。
3. **Tool Result 不影响决策**：❌ 不存在。ToolObservation 写回 state 并渲染进决策 prompt（state.py L252-264；graph.py L680-709）。
4. **LLM Wrapper**：❌ 不存在。存在结构化工具抽象 + Deterministic Gate + 确定性引擎。
5. **Worker 固定流程、Graph 是装饰**：❌ 不存在。Agent Graph 才是决策/执行/发射的主体；Worker 只做事件消费/持久化壳。

***

## 6. E2E / Simulation Results

| 场景                            | Expected                    | Actual                                                   | PASS | Evidence         |
| ----------------------------- | --------------------------- | -------------------------------------------------------- | ---- | ---------------- |
| 全栈 Happy Path（成都 4天/1人/¥2500） | 真实 4 天行程 + COMPLETED + 前端展示 | 4 天、27 地图点、`共 4 天`、COMPLETED                             | ✅    | session 内浏览器 E2E |
| Scene A：必填约束齐                 | auto build→Gate→EMITTED＋行程  | `stop_reason=EMITTED`，产出 itinerary，obs=\[build,validate] | ✅    | 自定义 harness      |
| Scene B：信息缺失"我要去广州玩"          | ask\_user 追问，不伪造            | `WAITING_USER`，`pending_question=行程从哪天开始？`,answer=None   | ✅    | 自定义 harness      |
| Scene C：预算/必去冲突               | 识别不可行→REPLAN 追问             | test\_infeasible\_resume 通过                              | ✅    | pytest           |
| Agent 循环/恢复/重试/反射/去重          | 全部通过                        | `75 passed, 4 skipped`                                   | ✅    | `tests/agent/*`  |

***

## 7. 验收清单

- [x] 存在真实 Agent Loop

- [x] Decision 基于 State

- [x] Action 可动态选择（模型 / 确定性降级）

- [x] Tool Result 进入 Observation

- [x] Observation 影响下一轮 Decision

- [x] State 可持久化（PG checkpoint）

- [x] Agent 可 Resume（新鲜度/去重/续跑）

- [x] Human-in-the-loop 可用（WAITING\_USER/ask\_user/TTL）

- [x] 最大步数保护（MAX\_STEPS/MAX\_TOOL\_CALLS/MAX\_LLM\_CALLS）

- [x] Tool Failure 可恢复（retry/fallback/有界瞬态重试）

- [x] Completion 经 Deterministic Gate（agent + Java 双闸）

- [x] Agent 完成一次真实旅行规划（E2E）

- [x] 不完整信息主动询问（Scene B）

- [x] 冲突约束识别、不可行不伪造（Scene C / infeasible\_resume）

- [x] Agent Result 持久化 + Event Chain + Java 消费 + DB 保存 + 前端展示（全栈 E2E）

**结论：满足验收标准，TripPilot Agent 系统基本成立（Level 4）。**

***

## 8. Fix Plan（本轮不实施大规模重构，仅列出）

| 优先级 | 动作                                                      | 影响           |
| --- | ------------------------------------------------------- | ------------ |
| P2  | 归边双链路：Agent 对话框链不发冗余完整行程（改发摘要），或将其行程送入统一 Gate           | 消除重复计算/分叉    |
| P3  | `_outcome_event` 前加"天数=日期区间+每天≥1活动"预校验（fail-fast）       | 减少跨链非法完成     |
| P3  | 暴露 running decider 类型，文档标注生产需接模型                        | 语义透明         |
| 后续  | Phase 2 复杂约束（预算/天气/营业时间/must-visit/多轮）回归，再 Phase 3 全国泛化 | 用真实数据压测 Gate |

