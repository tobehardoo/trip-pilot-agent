# 08 — Phase C Implementation Plan（C-1 ~ C-4，一刀一验收）

> **实施状态（2026-08-31）**：C-1、C-2、C-3 已实施并通过验收（commits `562f950` / `3bc7f47` / `7d36b9c`，
> 全量 1979 passed）。**C-4 的核心（不可行 → ask_user，strategy REPLAN）已在 C-1 中提前落地**
> （AskingDecider 分支，agent/graph.py）——因为轨迹基准的 ask-the-user 策略暴露了正确的职责划分：
> 工具只报告，决策者决定。剩余可选部分（基于收紧约束的自动重建）待真实使用反馈后再评估。
> 每刀：Scope / Non-goals / Architecture Change / Behavior Change / Compatibility /
> Acceptance / Counterfactual Tests。

## C-1：`build_itinerary` 接真规划（P0，最高价值）

- **Scope**：`agent/itinerary_builder.py`（provider 类型放宽为规划协议、新增真实后端装配）、
  `worker/agent_processor.py`（ToolRuntime 生产装配改接真实后端）、`agent/feasibility_gate.py`
  或其调用口径（EMITTED 判据保持结构门，新增 run_validation 摘要 observation）。
- **Non-goals**：不改 worker 规划路径；不改 LangGraph 拓扑；不加 LLM；不改事件契约字段
  （AgentCompletedEvent 已带 Itinerary）。
- **Architecture Change**：DemoItineraryBuilder 与 RealItineraryBuilder 共实现一个
  `ItineraryBuilder` 协议（`plan(command) -> PlanningResult`）；生产装配按环境选择
  （默认真实，DEMO_MODE 显式保留 demo）——对齐 worker 的 provider_mode 语义（amqp.py:370-380）。
- **Behavior Change**：**是**——agent 对话产出的行程从 demo 骨架变为真实规划
  （真实 POI/交通/成本/trace）；`PlanningInfeasibleError` 可能上抛为工具失败
  （observation.error_code，按 tools.py:752-765 既有语义，不炸循环）。
- **Compatibility**：wire 不变（AgentCompletedEvent 结构不变，内容变真）；
  `agent.agent_run`/checkpoint 不变。
- **Acceptance**：agent run（AGENT_START→build_itinerary→validate→EMITTED）产出
  itinerary.source=="AMAP"；硬违例场景 run 以 STOPPED/失败 observation 结束而非 EMITTED。
- **Counterfactual Tests**：同一 slot 集，DEMO 后端 vs 真实后端 → EMITTED 行程
  source/成本/活动不同；不可行约束（must_visit 不存在）→ build_itinerary
  observation.ok=False + error_code=PlanningInfeasible 语义，循环不 EMITTED。

## C-2：四个观测工具接线（P1）

- **Scope**：`worker/agent_processor.py` 两处 ToolRuntime 装配（:145-151, :588-594）
  注入 place_search/route/opening_hours/knowledge；能力来源：main.py 既有 runtime 工厂
  （main.py:20-26 create_place_search_runtime/create_route_runtime）与 knowledge 检索
  （worker/knowledge.py repository）。
- **Non-goals**：不加新工具；不改变工具 schema；不做对话 Web 搜索。
- **Architecture Change**：无结构变化——ToolRuntime 字段早已存在（tools.py:74-89）。
- **Behavior Change**：**是**——此前 CAPABILITY_MISSING 必失败的 4 类调用开始返回真数据
  （AskingDecider 决策分支 graph.py:141-147 将不再因 CAPABILITY_MISSING 提前终止）。
- **Compatibility**：wire 不变；ToolObservation 结构不变。
- **Acceptance**：生产装配下 search_place/get_route/check_opening_hours/retrieve_guide_knowledge
  的 observation.ok=True（有数据时）。
- **Counterfactual Tests**：接线 vs 不接线，同一工具调用 → observation ok/error 不同；
  下游 AskingDecider 分支行为不同（CAPABILITY_MISSING 终止 vs 继续采集）。

## C-3：AgentState 补全（goal / plan / evaluation / decision memory，checkpoint v2）

- **Scope**：`agent/state.py`（新增字段 + checkpoint 序列化 v2，state.py:308+）、
  `agent/graph.py`（build_itinerary/validate_itinerary 后写入字段）、
  `agent/persistence.py`（checkpoint 版本迁移读 v1/v2）。
- **Non-goals**：不改 worker；不加候选空间全量存储（只存决策摘要与评估摘要，防 State 膨胀）；
  不改 AgentCompletedEvent。
- **Architecture Change**：AgentState 增 `goal: str`（confirmed slots 派生）、
  `plan_evaluation: dict | None`（report 摘要：status/FAIL 规则/评分）、
  `decision_summaries: tuple[str, ...]`（来自 build_itinerary 后端的 decision_traces 摘要）。
- **Behavior Change**：**轻微**——LLM prompt 注入内容变多（graph.py:348-352 的 recent_observations
  旁新增 goal/evaluation），可能改变 LLM 路径决策；AskingDecider 路径行为不变（无 LLM 时仅 state 变化）。
- **Compatibility**：checkpoint v1 可读（迁移读 v1/v2）；wire 不变。
- **Acceptance**：WAITING_USER resume 后 goal/evaluation 字段保留；EMITTED 后 state 含
  evaluation 摘要。
- **Counterfactual Tests**：gate FAIL → state.plan_evaluation.status 变化；resume 后字段持久；
  LLM 路径 prompt 含 evaluation 摘要（注入文本断言）。

## C-4（可选）：把对话侧 evaluate→replan 语义补上

- **Scope**：`agent/graph.py` AskingDecider/LLM 决策对 gate FAIL 的分支——失败后允许
  （a）ask_user 说明冲突（WAITING_USER）或（b）以收紧后的约束重建 itinerary，
  而非重复同一动作到 CEILING（graph.py:154-161）。
- **Non-goals**：不做开放修复目录（保持与 worker repair 动作一致的保守面）。
- **Behavior Change**：**是**——gate 失败 run 从 CEILING_REACHED(8 步) 变为一次明确的
  ask_user/rebuild。
- **Acceptance / Counterfactual**：不可行约束 → run 以 WAITING_USER + 冲突说明结束
  （步数 ≤3），而非 CEILING；可行修复 → EMITTED。
- 前置依赖：C-1（真后端才有真 report）。

## 顺序与依赖

```
C-1（真规划后端）→ C-2（观测工具）→ C-3（State 补全）→ C-4（对话内 replan 语义，可选）
```
每刀独立 commit、独立验收；C-3/C-4 依赖 C-1 产出的真实 evaluation 数据。
