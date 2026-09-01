# ADR-015：Agent 编排层与记忆系统

- 状态：部分实施（Phase 0 与 Phase 1 前半段已完成：工具层与 LangGraph 编排层已落地；会话持久化、人在环路与前端未实施）
- 日期：2026-08-29
- 最后修订：2026-08-29
- 范围：Python `agent-service` 新增编排层；Java `travel-server` 新增会话与运行轨迹持久化；Vue Web 新增对话入口
- 关联 ADR：ADR-005（Python 规划 Worker）、ADR-010（单一 Agent）、ADR-012（冻结事实快照）、ADR-007（Demo 模式）
- 实施路线：[Agent化路线图](../product/Agent化路线图.md)

## 1. 问题

`agent-service` 名为 Agent，实为确定性流水线加 LLM 信息抽取。用户无法用自然语言表达意图，系统无法在多轮中澄清约束，也无法在跨会话中记住偏好。代码事实：主流程 `worker/processor.py` 硬编码固定步骤无分支；LLM 调用点全仓库仅 3 处且全部是单次 structured output；`function_call` / `conversation` / `memory` 在源码中 0 命中；唯一循环 `feasibility/repair/engine.py` 为确定性规则驱动；`WAITING_USER` 是终态事件，无回环通道。

结论：缺的不是模型能力，是**决策层、工具层、记忆层**。

## 2. 决策

**改造，但不替换内核。** 采用「Agent 编排层 + 确定性内核」的分层结构：

- LLM 负责：理解意图、选择调用什么、判断何时收敛、决定何时向人提问。
- 确定性代码负责：算路程、查营业时间、排班、校验可行性、优化。这些不允许交给模型。

理由：本项目护城河是"行程真正可执行"，纯 ReAct 自由循环最容易产出"看起来合理但不可执行"的行程。与 ADR-010（单一 Agent、可测试状态机）一致：只有一个 Agent，循环有界，状态显式可测。

### 2.1 不做什么

- 不引入多 Agent 协商（ADR-010）。
- 不把规划逻辑迁回 Java（ADR-005）。
- 不删除现有 pipeline：它降级为 Agent 路径的后备执行器。

## 3. 框架选型

LangGraph（Python）1.2.11：StateGraph 即显式状态机（ADR-010）；checkpointer 提供轨迹持久化与断点恢复（ADR-012）；`interrupt()` 原生支持人在环路。否决 Spring AI 迁移（违反 ADR-005）与自建编排层（checkpoint/并发/重试重复造轮子）。

## 4. 上下文记忆系统

| 层 | 内容 | 载体 | 状态 |
| --- | --- | --- | --- |
| Working | 约束槽位、工具观测、待澄清项 | Agent 状态对象 | 已落地 |
| Episodic | 决策轨迹；中断恢复 | `agent_run` / `agent_step` 表 | 规划中 |
| Semantic | 攻略事实、城市情报、向量知识 | `retrieval/` + pgvector + PlanningContextSnapshot | 复用 |
| Profile | 跨会话用户偏好 | `user_travel_profile` 表 | 规划中 |

### 4.1 约束槽位（Working memory 的核心）

槽位与 `TripConstraints` 字段对齐，三态：`UNKNOWN` / `INFERRED` / `CONFIRMED`。

**铁律：`INFERRED` 不得作为硬约束参与规划**，只能作为软偏好影响排序。只有 `CONFIRMED` 才写入 `TripConstraints`（`to_constraint_patch` 投影）。直接继承 fail-closed：宁可多问一句，不可替用户做主。

### 4.2 Profile 写入约束

对齐 ADR-011：模型提炼的偏好先以"待确认"落库，用户确认后才生效于后续规划。

### 4.3 可复现性（ADR-012）

每次 `agent_step` 记录：模型名与版本、temperature、seed、prompt 模板版本与 hash、输入输出 token、工具名与参数、工具返回摘要。

## 5. 工具调用设计

### 5.1 工具清单（包装现有能力）

`search_place` / `get_route` / `check_opening_hours` / `retrieve_guide_knowledge` / `build_itinerary`（规划中）/ `validate_itinerary`（守门）/ `ask_user` / `update_constraints` / `emit_itinerary`。

### 5.2 三条铁律

1. **硬事实只能来自工具**：数据不确定时返回 `UNKNOWN` / `UNRESOLVED`，不编造。
2. **`validate_itinerary` 一票否决**：未通过不得 `emit`。
3. **循环必须有界**：`max_steps` / `max_tool_calls` / `max_llm_calls` 三项硬上限，触顶即停。

### 5.3 观测接入既有证据链

工具返回值接入 `provider_provenance` / `fact_impacts` / `KnowledgeCitationSnapshot`，前端解释能力不退化。

## 6. 与现有 ADR 的一致性

| ADR | 约束 | 本方案如何满足 |
| --- | --- | --- |
| ADR-005 | 规划能力留在 Python | 编排层建在 `agent-service` |
| ADR-007 | Demo 模式可完整运行 | 工具层在 DEMO_ONLY 下返回明确标注数据；无 Key 走 AskingDecider |
| ADR-010 | 单 Agent、可测试状态机 | 单循环 + 显式状态 + 有界 |
| ADR-012 | 冻结事实快照、重试可复现 | 轨迹全量落库，重试语义显式定义 |

## 7. 分阶段路线

- **Phase 0** 契约与埋点：agent_run/step 表、结构化 step 事件。（部分完成：Agent 包落地）
- **Phase 1** 对话入口与槽位填充：自然语言 → 约束抽取 → 澄清 → TripConstraints。（前半段完成）
- **Phase 2** 工具层与 Agent Loop：build_itinerary、critic、SSE Trace、前端对话页。
- **Phase 3** 记忆与人在环路：轨迹持久化恢复、Profile、planner 策略。
- **Phase 4** 人在环路：`WAITING_USER` 从终态改造为可恢复中断点。

## 8. 风险

| 风险 | 缓解 |
| --- | --- |
| 既有测试回归 | Agent 路径与确定性 pipeline 并行，后者保留为后备执行器 |
| 延迟与成本上升 | `max_llm_calls` 预算上限 + 超时降级 |
| 非确定性侵蚀可信度 | 全量轨迹落库 + prompt 版本 hash |
| 槽位被模型幻觉污染 | `INFERRED` 不得作为硬约束，必须经 `ask_user` 确认 |

## 9. 待定问题

- Agent 路径与确定性 pipeline 的最终边界。
- Profile 偏好的存储粒度：自由文本还是固定枚举（建议枚举）。
- 轨迹数据量与保留期限。

## 10. 实施进展（2026-08-29）

已完成：

- **`trip_agent/agent` 包**：`state.py`（约束槽位三态 + 工具观测 + AgentState + 契约投影）、`tools.py`（8 个工具的声明式 schema 与注册表）、`graph.py`（LangGraph StateGraph 有界循环 + 两种决策器）。
- **三条铁律落地**：硬事实缺失时 fail-closed 返回 `UNKNOWN` / `CAPABILITY_MISSING`；`emit_itinerary` 前置检查 `validate_itinerary`；三重上限。
- **编排骨架去重**：`worker/processor.py` 三个 `process_*` 抽共用 `_resolve_and_emit`，724 → 664 行，行为不变。
- **Phase 1 入口形态确定**：对话入口与 `TripWorkspace` 并行，只做"对话流 + 约束卡片 + 澄清问答"，行程编辑复用现有组件。

未完成：`agent_run` / `agent_step` 与 `user_travel_profile` 表、结构化 step 事件扩展、`WAITING_USER` 可恢复中断、前端对话页、AMQP 链路接线。

验证：Python 测试 1716 → 1732 passed，37 skipped，0 failed；ruff 全绿。
