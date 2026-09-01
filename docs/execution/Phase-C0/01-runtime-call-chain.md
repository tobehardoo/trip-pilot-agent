# 01 — Runtime Call Chain（真实执行路径）

> Phase C-0 · 审计事实。所有行号基于 `apps/agent-service/src/trip_agent/`（下称 `PY`）与
> `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/`（下称 `J`）。
> 结论全部来自代码追踪，非目录推断。

## 1. 两个运行时，不是一个是双职责

| | 规划运行时（worker） | 对话运行时（agent dialog） |
|---|---|---|
| 进程入口 | `pyproject.toml:33` `trip-agent-worker = trip_agent.worker.amqp:main` | 同一 worker 进程（同一 consumer，独立队列） |
| 队列 | `planning.create.queue`（amqp.py:93, 973-980，绑定 planning.create/replan/candidate-validation :998-1000） | `agent.dialog.queue`（agent_processor.py:50；amqp.py:990-997，绑定 agent.start/agent.resume :1002-1003） |
| 处理器 | `process_planning_create`（worker/processor.py:106） | `handle_agent_delivery`（worker/agent_processor.py:534-576） |
| 运行时内核 | AmapPlanningProvider 确定性管道（amqp.py:465 生产接线） | LangGraph AgentLoop（agent/graph.py:31, 365-377） |
| 产物 | 真实 Itinerary + feasibility report + evaluation | **Demo 骨架行程**（agent/itinerary_builder.py:176-177 默认 DemoPlanningProvider） |
| 互斥纪律 | "Planning commands never enter this module"（agent_processor.py:10） | "agent commands never enter the planning failure chain"（同上） |

## 2. 规划运行时完整调用链（生产）

```
[pyproject.toml:33] trip-agent-worker → amqp.py:1070-1072 main() → run_worker(:937-944) → _consume(:947-1032)
  ↓ RabbitMQ: trip.command.exchange → planning.create.queue
amqp.py:1035-1051 _handle_incoming → amqp.py:559 handle_delivery
  → 取消探测（amqp.py:604-614，PsycopgCancellationOracle 只读 business.planning_task :232-266）
  → amqp.py:642-648 asyncio.create_task(process_planning_create(...))
      ↓ processor.py:106 process_planning_create
      ├─ :122-126  CONTEXT_VALIDATING 进度
      ├─ :127      _command_with_fresh_guide_evidence（过滤过期 guide facts，:477-490）
      ├─ :134      provider.plan(command)          ← Phase B 全部智能在此（P\planning\*）
      ├─ :136-148  _resolve_and_emit（:226-270）
      │    ├─ :243  attach accommodation
      │    ├─ :247-254  feasibility run_validation（feasibility/validator.py:105-137）
      │    ├─ :260  _repair_if_needed（:371-426）← 有界修复循环（≤3 轮，见 03 文档）
      │    ├─ :261  _create_evidence（:332-351，知识检索 + fact impacts）
      │    └─ :262  _outcome_event（:273-329）→ :315 PlanEvaluator.evaluate（仅 completed 分支）
      ↓ amqp.py:674-702 终态事件发布（planning.completed / review-required / failed）
  ↓ ack（amqp.py:731）；异常 → _publish_terminal_failure（:703-729, 854-919）→ planning.failed → ack
Java 消费（落库权威）：
  PlanningCompletedEventListener.java:26-41 → PlanningCompletionService.java:68-182
    （itinerary 版本 / factImpacts / feasibility report / 任务置 SUCCEEDED，:139-456）
  PlanningReviewRequiredEventListener.java:26-41 → PlanningReviewService.java:70-152（WAITING_USER）
  PlanningFailedEventListener.java:26-43 → PlanningFailureService.java:41-92（FAILED，终态）
  PlanningProgressEventListener.java:21-33 → PlanningProgressService.java:38-104 → SSE（Hub :64-95）
```

## 3. 对话运行时完整调用链（生产）

```
Vue（apps/web/src/lib/api.ts:1002-1013 startAgentRun/answerAgentRun）
  ↓ J\agentdialog\AgentDialogRunController.java:40-69（POST /runs、/runs/{id}/answers）
  ↓ AgentDialogCommandService.java:63-75 + writeCommand(:104-138)
  ↓ 事务性 outbox（business.outbox_event，V4 迁移 :35-49）→ OutboxPublisherJob.java:13-16（每 1s）
  ↓ trip.command.exchange → agent.dialog.queue
amqp.py:1015-1018 _handle_agent_incoming → agent_processor.py:534-576 handle_agent_delivery
  → AGENT_START(:545-548) / AGENT_RESUME(:549-550)
  → handle_start(:192-228)：uuid4 run_id → AgentRunRecorder.start（幂等 :200-204）
      → AgentState(user_message, trip_id, user_id, confirmed_preferences)（:205-212）
      → run_agent(loop, state, checkpoint_sink=...)（:213-219）  ← LangGraph ainvoke/astream
      → 发问（WAITING_USER→AgentAskUserEvent :376-408）/ 完成（EMITTED→AgentCompletedEvent :410-439）
        / 兜底 AgentRunFinishedEvent(:441-466)
  → recorder.finish(:227)
事件回流：AgentDialogEventListener.java:38-61 → AgentDialogEventService.java:37-110
  （持久化 business.agent_dialog_message，V41 迁移；SSE hub 推送）
resume：handle_resume(:230-316)——WAITING_USER TTL（7 天，:128/:236-249）、RUNNING 防双执行
  （600s stale，:250-260）、checkpoint 恢复 + 用户原话注入 + steps=0（:289-303）
```

## 4. 调用链分层表

| 层 | 规划运行时实现 | file:line | 生产真实调用 | 对话运行时实现 | file:line | 生产真实调用 |
|---|---|---|---|---|---|---|
| Entry | `trip-agent-worker` console script | pyproject.toml:33 | ✅ | 同一 worker 进程 | amqp.py:990-997 | ✅ |
| Consumer | amqp.py `_consume` | amqp.py:947-1032 | ✅ | 同左（agent.dialog.queue） | amqp.py:1015-1018 | ✅ |
| Processor | process_planning_create | processor.py:106 | ✅ | AgentDialogProcessor | agent_processor.py:534 | ✅ |
| Graph | **无**（无 LangGraph） | — | ❌ 不存在 | AgentLoop（StateGraph） | agent/graph.py:365-377 | ✅ |
| Agent Node | — | — | ❌ | decide/act/finish | graph.py:383-435 | ✅ |
| Planning | provider.plan（Amap，生产） | amqp.py:465；processor.py:134 | ✅ | DemoItineraryBuilder→DemoPlanningProvider | itinerary_builder.py:176-183 | ✅（demo 内容） |
| Evaluation | PlanEvaluator | processor.py:315 | ✅ post-hoc | StructuralFeasibilityGate（窄口径） | feasibility_gate.py:29-68 | ✅（仅结构） |
| Persistence | **无**（只发事件） | amqp.py:18 仅只读取消探测 | — | agent_run/checkpoint 写 Postgres | persistence.py:208, 236-252 | ✅ |
| Event/SSE | planning.* 事件 → Java 消费 → SSE | amqp.py:674-702; J\planning\*Hub | ✅ | agent.* 事件 → Java 消费 → SSE | J\agentdialog\*Hub | ✅ |
```

## 5. 关键澄清

- `workflow/planner_pipeline.py` **不是流水线**：只有 `FallbackPlanningProvider` 装饰器（planner_pipeline.py:29-121），仅在 `REAL_WITH_EXPLICIT_FALLBACK` 模式实例化（amqp.py:479），其余模式不经过。
- LangGraph 全仓唯一使用点 = `agent/graph.py:31`；`Command`/`ToolNode` 未使用。
- Python 侧对 planning 业务库**零写入**（只有只读取消探测 amqp.py:251-260）；agent 对话路径写自己的 `agent.*` schema（persistence.py:137/172/202/260 均为知识/运行表）。
