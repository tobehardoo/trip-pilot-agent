# 07 — Target Agent Architecture（Phase C 目标架构）

> Phase C-0 · 设计。原则：**Deterministic Agent 优先**；LLM 仅在已证明需要的对话决策层保留现状（可选、可降级）；
> 不把 Provider 机械拆 Node；不删 Phase B 决策架构。

## 1. Runtime Ownership 声明（先定权，再定形）

| 所有权 | Owner | 依据 |
|---|---|---|
| Business Workflow | **Java**（outbox、任务状态机 9 态、事件落库、SSE） | V4 迁移 :17-33、PlanningTaskMapper.java:130-193、各 Listener |
| Agent Runtime（对话循环） | **Python agent/**（LangGraph AgentLoop + checkpoint） | graph.py:365-377、agent_processor.py |
| Planning Ownership | **Python planning/**（确定性决策域，Phase A/B 成果） | planning/ 13 个纯模块 + provider 编排 |
| Persistence | **Java**（业务表）；Python 仅 agent 自有运行表（agent.agent_run/checkpoint） | processor 无业务写（01 文档 §5） |

**判定：Java 是业务流程编排，Python 是算法 Worker + 对话 Agent。这不是缺陷，是合理分层——
Phase C 不改变所有权，只桥接能力。**

## 2. 目标模型：双运行时 + 能力桥（不合并）

```
┌────────────────────────── Java（业务编排，不变）──────────────────────────┐
│  outbox → 命令 → Python ；事件 ← Python ；SSE                              │
└───────────────┬──────────────────────────────┬───────────────────────────┘
                ↓                              ↓
   规划运行时（worker，类型 B，保持）      对话运行时（agent，类型 C，补牙）
   ├─ process_planning_create            ├─ LangGraph AgentLoop（不变）
   ├─ AmapPlanningProvider（真规划）      ├─ ToolRuntime（9 工具，全接线）
   ├─ run_validation + repair loop       │   ├─ build_itinerary → ★真规划后端
   └─ PlanEvaluator（post-hoc，不变）     │   ├─ search_place/get_route/… → ★接 main.py 能力
                                         │   └─ validate_itinerary → ★run_validation 口径
                                         └─ AgentState ★补 goal/plan/evaluation 字段
```

关键决策：**对话 Agent 通过 Tool 调用规划能力（把 worker 的能力做成可注入后端），
而不是把规划管线搬进 Graph**。理由：
1. 确定性管线是核心资产（用户 §十五：优先 Deterministic Agent）；
2. Graph 的职责是 State Transition + Runtime Control（用户 §十七），决策留在 planning 域；
3. DemoPlanningProvider 与 AmapPlanningProvider 实现同一 `plan(command)` 协议
   （PlanningProvider，infrastructure/demo/planning_provider.py 与 amap 版同构）——
   桥的代价只是**接线与类型放宽**，不是重写。

## 3. Observe → Decide → Act 映射（目标态，粗体为补齐项）

| Agent Phase | 目标实现 | Owner | 现状 |
|---|---|---|---|
| Goal | AgentState.goal（由 confirmed slots + user_message 派生的结构化目标） | agent/state.py | **MISSING** |
| Observe | search_place/get_route/check_opening_hours/retrieve_guide_knowledge 全接线 | agent/tools.py + ToolRuntime | 4/8 MISSING |
| Build Context | 复用 PlanningContextView 语义：build_itinerary 后端构造 View | planning/context_view.py | ✅（锁在 provider 内，经工具间接可达） |
| Retrieve/Decide | planning 域（不变） | planning/* | ✅ |
| Act/Emit | build_itinerary → **真 provider.plan()** → 真实 Itinerary | agent/itinerary_builder.py | **Demo → 真实** |
| Evaluate | validate_itinerary 升级为 run_validation 口径（feasibility report 进 observation） | agent/feasibility_gate.py 或直连 validator | 窄口径 → **完整** |
| Reflect | decision 摘要进 AgentState（P2-2a/2b 的 trace 已有数据源） | agent/state.py | **MISSING** |
| Replan | 修复循环已有（worker）；对话侧 gate 失败 → 决策分支（问用户/换动作）而非重复同一动作 | graph.py AskingDecider | 部分 |
| Finish | EMITTED 语义对齐：结构门 + report 摘要随 AgentCompletedEvent | agent_processor.py:410-439 | 部分 |

## 4. 明确不做

- ❌ 规划 worker LangGraph 化（类型 B 是它的正确形态；修复循环已是它的"agent 性"）。
- ❌ PlanEvaluator 夺权（评分驱动下一步是伪需求；硬违例闸门 + feasibility 控制已够）。
- ❌ Provider 拆 Node 化。
- ❌ LLM 决策扩大化（STRUCTURED_MODEL 可选 + 证据信任规则 tools.py:114-131 是正确边界）。
- ❌ Java/Python 所有权调整。
