# 09 — Agent Maturity（重新评分）

> Phase D-0 · 按用户 §十五 的 Level 0-5 重新评分（Phase C 后的现状）。

## 评分

**TripPilot（对话运行时）= Level 3（Agent Loop），向 Level 4 缺三类 Recovery。**
**TripPilot（规划运行时）= Level 2（Conditional Workflow）+ 一个有界确定性修复子循环。**
**整体产品视角 = Level 3。**

## 逐级证据

| Level | 定义 | 满足？ | 证据 |
|---|---|---|---|
| 0 普通函数调用 | — | 超越 | 管线早已条件化 |
| 1 Workflow | 固定序列 | ✅ 超越 | worker 全链 |
| 2 Conditional Workflow | 评估分支 | ✅ | feasibility has_blocker → COMPLETED/REVIEW/修复循环（processor.py:298, 371-426）；agent _route 条件边（graph.py:423-430） |
| 3 Agent Loop | Goal→Observe→Decide→Act→Evaluate | ✅ | LangGraph 循环（graph.py:365-377）+ AgentState（slots/observations/goal/plan_evaluation，C-3）+ 9 工具语义 + 观测驱动决策（graph.py:141-176） |
| 4 Recoverable Agent | Retry/Ask/Replan/Stop **按失败类型** | ⚠️ **部分** | Ask ✅（CAPABILITY/INFEASIBLE 两类，但 resume 不闭环）；Stop ✅（但以 Ceiling 形态）；Retry ❌（provider 层有、agent 层无分类）；Replan（不改约束的）❌ |
| 5 Adaptive Agent | 按 Evaluation 选不同 Recovery | ❌ | plan_evaluation/decision_summaries 为 passive memory（06/07 文档） |

## 与 C-0 评分的对比

C-0 评 2/5（当时：对话侧 demo 行程、工具未接线、无 State 决策记忆）。
Phase C 关闭了 P0（真规划）与半个 P1（State 字段入列）→ 升至 3/5。
距 Level 4 的差距就是 Phase D 的全部内容：**分类 + 闭环 resume + 重复失败守卫**。

## 一个重要的诚实注记

Level 3 的"Evaluate"环节，其评估口径在两个运行时并不一致：
- worker：11 条硬规则 + 修复循环 + PlanEvaluator（完整）；
- agent：结构门 4 项 + run_validation 摘要（观测级）。
Phase D 不要求 agent 侧复制修复循环（worker 已有），但要求摘要成为决策输入——
否则 Level 3 的 E 是装饰。
