# 02 — Agent State Audit

> Phase C-0 · 审计事实。结论：**两个运行时各有一个不完整的状态模型，规划运行时没有显式 State 对象。**

## 1. AgentState（对话运行时，agent/state.py:266-296）

frozen dataclass，节点以 partial dict 传递（state.py:270-272）；单次 run 的工作记忆（docstring :268-269）；
跨 turn 通过 checkpoint 持久化（CHECKPOINT_VERSION=1，state.py:308；写 Postgres，persistence.py:255-267、388）；
WAITING_USER resume 时恢复并重置 steps、冻结 turn_baseline_observations（agent_processor.py:298-302）。

字段全量（state.py:274-296）：`slots`（ConstraintSlots）、`observations`、`pending_question/options/expected_type/call`、
`steps`、`stop_reason`、`answer`、`user_message`、`candidate_itinerary`、`trip_id`、`turn_baseline_observations`、
`user_id`、`confirmed_preferences`、`strategy`。

### 能力逐项核对

| State Capability | 是否存在 | 存储位置 | 生命周期 | 问题 |
|---|---|---|---|---|
| Goal | ❌ 无 | — | — | 隐含在 user_message + slots 里，没有显式目标表述；"产出通过守门的行程"不可见 |
| Constraints | ⚠️ 部分 | slots（ConstraintSlots，state.py:59-96，13 个槽位 + provenance 枚举 :22-41） | run 内 + checkpoint 跨轮 | 只覆盖对话采集阶段的需求槽位；不含 fixed_schedules/mobility 等规划约束全集 |
| Facts / Observation | ⚠️ 部分 | observations（ToolObservation 列表）+ turn_baseline_observations | run 内（跨轮冻结基线） | 只有**工具调用结果**，没有规划知识事实（weather/ticket/guide facts 不进 State） |
| Candidate Space | ❌ 无 | — | — | 无 POI/餐厅/交通候选集合；`candidate_itinerary` 是单数最终产物 |
| Decision Memory | ❌ 无（对话侧） | — | — | Phase B 的 DecisionTrace/Explanation 不进 AgentState（它们只存在于规划 provider 进程内，见 06 文档） |
| Current Plan | ⚠️ 半个 | candidate_itinerary（单数） | EMITTED 前 | 只有 demo 骨架行程；无版本、无与 evaluation 的关联 |
| Evaluation | ❌ 无 | — | — | StructuralFeasibilityGate 的结果只作为 ToolObservation（ok/error_code），没有结构化评估字段（分数/违例/警告） |
| Failure State | ⚠️ 弱 | stop_reason + observation.error_code | run 内 | stop_reason 有（EMITTED/WAITING_USER/ANSWERED/STOPPED/CEILING_REACHED/LLM_BUDGET_EXHAUSTED，graph.py:38-43,420,434）；但**没有"部分失败+可恢复"的失败状态**——gate 阻塞只会重试同一动作到上限（graph.py:154-161 + 386-387） |
| Iteration State | ⚠️ 半个 | steps 计数 + turn_baseline_observations（graph.py:280,402-406） | run 内（每 turn 重置） | 只服务预算封顶，不是 replan 语义的轮次 |

## 2. 规划运行时（worker）：没有显式 State

`process_planning_create`（processor.py:106-148）的全部中间产物是**函数局部变量**：

| 产物 | 所在 | 生命周期 |
|---|---|---|
| PlanningContextView（Phase B） | `_plan_with_skeleton` 局部（planning_provider.py:419） | 单次 plan() 调用 |
| decision_traces（Phase B） | 同上局部 list（planning_provider.py:424-427） | 单次 plan()，随 PlanningResult.decision_traces 离开（protocols.py:124-128，进程内） |
| PlanningResult（itinerary/skeleton/validation_inputs/evaluation） | protocols.py:86-128 | 单次处理，经事件 payload 出进程（evaluation 必填进 v11 payload，contracts.py:1184-1199） |
| feasibility report / repair session | processor.py:247-262 局部 | 单次处理，随事件出进程 |

没有跨步骤、跨尝试、跨消息的 State 容器；没有 attempt/iteration 概念（repair session 内部有 attempt_index，
engine.py:30-32，但不出 repair 边界）。

## 3. 结论

- 对话运行时的 AgentState 是**真实但薄**的 Agent State：有观测记忆、槽位约束、停止原因、跨轮 checkpoint；
  缺 goal/candidate space/decision memory/结构化 evaluation/replan 语义。
- 规划运行时**没有 Agent State**——它是无状态的确定性函数管线（这是它的优点：可测、可复现；
  也是它的边界：评估结果无法跨尝试积累）。
- Phase B 的全部决策资产（ContextView/Trace/Explanation）目前**只活在 provider 进程内**，
  经事件 payload "广播"但没有任何 State 承载（06 文档详述）。
