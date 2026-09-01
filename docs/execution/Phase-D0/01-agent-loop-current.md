# 01 — Agent Loop Current State（Phase C 后重新审计）

> Phase D-0 · 全部行号基于 `apps/agent-service/src/trip_agent/`。Phase C 改变了 Runtime，
> 本文档从真实入口重新追踪，不复用 C-0 结论。

## 1. 真实入口链（生产）

```
Vue → J\AgentDialogRunController.java:40-69 → outbox（AgentDialogCommandService.java:104-138）
  → agent.start / agent.resume → agent.dialog.queue（amqp.py:990-997）
  → _handle_agent_incoming（amqp.py:1015-1018）→ handle_agent_delivery（agent_processor.py:534-576）
  → AGENT_START: handle_start(:192-228) / AGENT_RESUME: handle_resume(:230-316)
  → run_agent(loop, state, checkpoint_sink)（agent/graph.py:453-494）
```

## 2. 真实 Graph 拓扑（graph.py:365-377 不变，decide 节点分支已扩展）

```
START
  ↓
decide（graph.py:135-220，AskingDecider；LLM 路径 StructuredOutputDecider :249-300）
  │  输入：AgentState（slots/observations/user_message/goal/plan_evaluation/decision_summaries）
  │  分支（required_hard = 全部必填槽位 hard）：
  │  ├─ [hard] builds[-1] CAPABILITY_MISSING → answer 交给规划链路（:141-147）
  │  ├─ [hard] builds[-1] PLANNING_INFEASIBLE → ask_user（REPLAN，:148-161）★C-1 新增
  │  ├─ [hard] candidate_itinerary None → build_itinerary（:162-166）
  │  ├─ [hard] 无 validate 通过 → validate_itinerary（:167-172）
  │  ├─ [hard] 已通过 → answer EMITTED 语义（:173-176）
  │  ├─ [非 hard] user_message → _extract_slot_values → update_constraints（:180-192）
  │  ├─ [非 hard] 回答不可识别 → 重复提问（:193-203）
  │  └─ [非 hard] 缺槽 → ask_user（:204-210）
  ↓ _route（:423-430）：stop_reason/answer/pending_call None → finish；else → act
act（graph.py:397-421）
  │  tools.invoke（tools.py:788-808，异常吞为 TOOL_ERROR :802-808）
  │  with_observation + handler 的 state partial
  │  validate 通过 → 强制 stop_reason="EMITTED"（:417-420）
  └→ 回 decide
finish（:432-435）→ END
```

## 3. 每个 Node 的契约

| Node | 输入 State | 输出 Partial | Observation | Side Effect | file:line |
|---|---|---|---|---|---|
| decide | 全量 AgentState | pending_call / answer / strategy / thought（经 Decision） | 无 | 无（纯决策） | graph.py:135-220（LLM :249-300） |
| act | pending_call | observations+1、candidate_itinerary、（build 失败时不设 stop——见 04） | ToolObservation（ok/summary/data/error_code） | update_preferences 写 Postgres；build 触发真规划；事件经 checkpoint_sink→AgentStepEvent | graph.py:397-421；tools.py:467-548 |
| finish | stop_reason/answer | 无 | 无 | run 状态落库（agent_processor :220-227） | graph.py:432-435 |

## 4. 出口语义（当前真实集合）

| 出口 | 触发 | file:line |
|---|---|---|
| EMITTED | validate_itinerary 通过（结构门） | graph.py:417-420 |
| WAITING_USER | ask_user 工具（含 C-1 的不可行分支） | tools.py:291-297；graph.py:148-161 |
| ANSWERED | 决策给出 answer（如 CAPABILITY_MISSING 移交） | graph.py:434 |
| STOPPED | C-1 防御路径：provider 抛 Infeasible 时 **未再设置**（见 04——工具只报告，决策未 STOP）；finish 时无 answer 兜底 | graph.py:434-435 |
| CEILING_REACHED | 8 步 / 16 工具 / 8 LLM 预算耗尽 | graph.py:38-43, 386-387 |

**关键缺口预告**（后文详证）：出口集合里**没有 FAILURE 分类出口**——所有未匹配的失败
（TOOL_ERROR、FEASIBILITY_BLOCKED 循环、连续不可行）都汇入 `CEILING_REACHED` 或
`WAITING_USER` 循环，而不是被分类后选择 RECOVERY。
