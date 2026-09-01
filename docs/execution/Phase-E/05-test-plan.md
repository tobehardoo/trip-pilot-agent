# Phase E · 05 — Test Plan（T1–T7 测试计划）

**新增文件**：`apps/agent-service/tests/agent/test_reflection_loop.py`
**反转既有测试**：`apps/agent-service/tests/agent/test_real_itinerary_backend.py::test_text_must_visit_conflict_surfaces_in_the_summary`（S2 活证据）

---

## 反转测试（先改，证明 P0 生效）

`test_text_must_visit_conflict_surfaces_in_the_summary`（test_real_itinerary_backend.py:221-234）
当前断言 `NEEDS_REPAIR (1 failing rules)` 仍 `stop_reason == "EMITTED"`——这正是
S2 缺陷。反转断言为：**不得 EMITTED**，改为 `WAITING_USER` 且提问含调整指引。
测试名改为 `test_text_must_visit_conflict_is_not_emitted`。

---

## T1 — P0/S2 回归：硬校验 FAIL 不得 EMIT

- **前置**：真实后端（`_real_builder()`，同 test_real_itinerary_backend 夹具），
  约束 `must_visit=["不存在的景点"]` → 硬校验 `MUST_VISIT_PLACE_MISSING` →
  `plan_evaluation.status == "NEEDS_REPAIR"` 且 failures 非空；结构门本可放行。
- **动作**：`run_agent(AgentLoop(AskingDecider, registry))`。
- **断言**：`stop_reason != "EMITTED"`；`stop_reason == "WAITING_USER"`；
  `pending_question` 含“调整必去地点/日期/预算”类指引；最终 state 中
  `reflection_attempts == 1`。

## T2 — Case A 回归：干净候选照常 EMIT

- **前置**：真实后端，`_SLOTS`（成都 3 天、预算 5000）→ 硬校验干净。
- **动作**：同 T1 运行。
- **断言**：`stop_reason == "EMITTED"`；`reflection_attempts == 0`；
  `plan_evaluation` 存在且 `status != "NEEDS_REPAIR"`。

## T3 — Case B：决策器真正读取 Evaluation（行为改变）

- **前置**：stub builder 返回 `BuiltItinerary(feasibility={"status":"NEEDS_REPAIR",
  "failures":[{rule_id, reason_code:"BUDGET_EXCEEDED", message}]})`（不依赖真实
  地理数据，纯单元）。
- **动作**：`run_agent(AskingDecider)`。
- **断言**：`stop_reason == "WAITING_USER"`；`failure_kind == "USER_CONSTRAINT"`；
  提问含 `BUDGET_EXCEEDED` 的 message 细节；**未调用 validate_itinerary**
  （反射分支跳过注定放行的结构门）——`observations` 无 validate 观测。

## T4 — 反射闭环完成：Evaluation → Reflection → Decision → Replan → EMIT

- **前置**：T3 场景；捕获 WAITING_USER 的 checkpoint state。
- **动作**：构造 resume state（`user_message="预算提高到 9000"`，仿
  agent_processor.handle_resume 的字段重置）→ 再跑 `run_agent`；stub builder
  第二次返回干净 feasibility。
- **断言**：第二轮 `stop_reason == "EMITTED"`；`reflection_attempts == 0`
  （约束变更已重置）；`plan_evaluation.status` 为干净值；两次运行观测合计含
  `update_constraints`（证据匹配确认 budget）。

## T5 — Failure ≠ Quality Feedback（区分测试）

- **前置**：直接构造 `AgentState`，`plan_evaluation = {"status":"VERIFIED",
  "failures":[], "quality":{"verdict":"POOR","score":58,"reasons":[...]}}`；
  模拟 `_act_node` 的分类（或直接调用 `classify_failure(ok=True,
  validation_reason_codes=())`，reason_codes 从 quality 之外的 failures 提取）。
- **断言**：`classify_failure` 返回 `(None, "")`（quality 不进失败记忆）；
  复用 `agent_state_to_dict/from_dict` round-trip 后 `quality` 原样保留；
  `reflect_on_evaluation` 对该 evaluation 返回 ACCEPT（quality 不阻塞门）。

## T6 — Case D：Reflection Budget 有界（禁止无限 REPLAN）

- **前置**：stub builder 恒返回 NEEDS_REPAIR；stub 决策器（模拟 misbehaving
  LLM）恒返回 `ToolCall("build_itinerary")`（不改变约束）。
- **动作**：`run_agent`。
- **断言**：终止且 `stop_reason == "ANSWERED"`（Case D 答案）；
  `reflection_attempts == REFLECTION_MAX_ATTEMPTS (3)`；总步数远小于
  MAX_STEPS=8（不进 CEILING）；观测中 build 恰好 3 次（第 3 个否决后短路）。

## T7 — P1：决策上下文（CURRENT STATE）注入契约

- **前置**：构造 `StructuredOutputDecider`（`max_calls` 高，无需 transport——
  只测 `_prompt`）；state 带 `plan_evaluation`（含 quality）与
  `reflection_attempts=2`。
- **断言**：prompt 含 `当前行程评估` 区段、`NEEDS_REPAIR` 与 `MUST_VISIT_PLACE_MISSING`
  文本、`quality` 的 verdict/score、`反思预算` 与 `2/3`、禁止无限重试规则文本；
  无评估的 state 渲染 `(无)` 且结构不崩。

---

## 验收核对（5 条）

1. **S2 修复**：T1 + 反转测试证明 NEEDS_REPAIR 不再 EMIT。
2. **Evaluation 可读**：T3 证明决策器读 state 中的 plan_evaluation 并改变行为；
   T7 证明 LLM 上下文注入。
3. **Reflection 改变行为**：T3/T4/T6 分别证明否决→ask、闭环→EMIT、预算→停止。
4. **Failure/Quality 区分**：T5。
5. **预算有界**：T6 + 全量回归（既有 55 文件/562 用例保持绿；本任务新增用例计入基线）。

## 执行顺序

1. 改既有测试断言（反转）→ 跑：应 RED（P0 未实现）。
2. 实现 P0/P1（03/04 契约）→ 跑：T1-T7 + 反转测试全绿。
3. 全量 agent 测试 + 全量基线回归。
