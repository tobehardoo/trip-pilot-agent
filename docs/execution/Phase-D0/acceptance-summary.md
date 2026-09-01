# Phase D-0 Acceptance Summary（验收摘要）

> 十问 + 约束变更防线审计 + FOLLOW-UP 关联判定。文档 01-10 为详细依据。

## 约束变更防线审计（用户 §九核心原则）

| 变更点 | 谁改 | 改什么 | 用户确认 | Trace |
|---|---|---|---|---|
| update_constraints | Agent 提议、**代码裁决** | 槽位值/拒绝 | ✅ 值必须在用户原话 evidence 中出现才 CONFIRMED（tools.py:114-131, 188-205）；LLM 的 confirmed 标志被忽略（:149-151） | slot.provenance + evidence |
| rejections | 用户显式拒绝 | 槽位置 REJECTED | ✅ 仅响应"不想去 X"类原话 | 同上 |
| worker 修复循环 | 确定性引擎 | 活动**时刻/时长**（CLAMP/SHIFT）、删除重复非必去活动 | ⚠️ 属计划投影修复，非用户约束（预算/必去/日期/固定安排**永不被改**：fixed 不可移动 engine.py:583-591；预算 FAIL 不可修复 catalog.py:5-7） | RepairAttempt 记录 |
| 对话 Agent | — | **不存在自动约束变更** | — | — |

**判定：Constraint Mutation 防线完整**——Agent 无法擅自修改预算/必去/日期/固定安排；
唯一自动调整发生在"计划投影"层且有界、可追溯。Phase D 的 R3 Replan 设计
（08 文档）延续此纪律：只放宽 provider 内部自由度。

## 十问

1. **生产 Runtime 调用 LangGraph？** 是——对话运行时（agent/graph.py，C 系列后语义已扩展）。
2. **Graph 分类？** 规划运行时 = 类型 B（条件 Workflow + 有界修复循环）；对话运行时 =
   **类型 C 骨架 + Level 3 语义**（Goal/Observe/Decide/Act/Evaluate 已成环，Recovery 未闭环）。
   主分类（用户要求单选）：**C（骨架）/ B（能力）——严格按定义，对话图已是循环，
   但按"评估改变下一步"的成色判 B+。最终主分类取 C，因为决定性的
   observe→decide→act→evaluate 回边与语义停止原因已真实存在。**
3. **谁拥有 Agent State？** 对话运行时 AgentState（v2 checkpoint）；规划运行时无 State。
4. **谁拥有 Goal？** 对话运行时 `AgentState.goal`（C-3 派生）；规划侧隐含在 command。
5. **PlanEvaluator 控制权？** 无（post-hoc，payload 展示）；控制权在 feasibility report
   与 repair session。agent 侧 plan_evaluation 亦为 passive（06 文档）。
6. **真实 Replan？** worker 修复循环 = 有界 evaluate→repair→re-evaluate ✅；
   agent 侧 = INFEASIBLE → ask_user（等待用户调整）✅，但 resume 半环 FAIL（05 文档）；
   无约束自改型自动 replan（设计如此）。
7. **God Planner？** AmapPlanningProvider 是编排 God（~2200 行）；决策逻辑已纯模块化。
8. **tools.py 真工具？** 是——9 个 schema 化工具，生产接线 5/9 真能力
   （C-1 真规划 + C-2 四观测 + 偏好/门），demo 后端仅剩显式 DEMO 模式。
9. **完整 Agent 项目？** **PARTIALLY → 接近 YES**：循环/State/工具/评估真实；
   缺 Recovery 分类、resume 闭环、重复守卫（即 Phase D 的 D-1..D-4）。
10. **最小必要改造？** D-1（分类）+ D-3（resume 闭环）+ D-4（重复守卫）为最小集；
    D-2（瞬态重试）紧随。四者合计改动集中在 agent/graph.py + 新 failure_policy.py
    + state 2 字段——无 Coordinator、无新模型、无契约变化。

## AC 核对

AC-1 调用链 ✅（01）｜AC-2 file:line ✅ 全文档｜AC-3 分类 ✅（03：C 骨架/B 能力）
｜AC-4 State 生命周期 ✅（02）｜AC-5 Evaluator 控制权 ✅（06）｜AC-6 Provider 职责 ✅
（C-0 04 文档 + 本轮复核）｜AC-7 反模式 ✅（06）｜AC-8 所有权 ✅（C-0 07 文档复核）
｜AC-9 目标架构 ✅（08）｜AC-10 拆刀 ✅（10）。
