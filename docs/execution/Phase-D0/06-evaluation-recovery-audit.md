# 06 — Evaluation Recovery Audit（评估是否形成 Recovery Signal）

> Phase D-0 · 核心问题：`plan_evaluation` 是 Decision Input 还是只是 Memory？

## 1. 数据流现状

```
build_itinerary（真后端）
  ↓ run_validation（itinerary_builder.py:246-262 _hard_validation_summary）
BuiltItinerary.feasibility = {"status": ..., "failures": [{rule_id, reason_code, message}]}
  ↓ 工具 handler（tools.py C-3 分支）
AgentState.plan_evaluation（state.py C-3 字段）
  ↓ checkpoint v2 持久化（跨轮保留）
……然后呢？
```

## 2. 消费者审计

| 消费者 | 是否读取 plan_evaluation | 证据 |
|---|---|---|
| AskingDecider.decide | ❌ **完全不读**（graph.py:135-220 无任何 plan_evaluation 引用） | 分支只看 observations 的 error_code 与 candidate_itinerary |
| LLM Decider prompt | ❌ 不注入（graph.py:348-352 只注入 recent_observations + slots） | 同上 |
| _route 条件边 | ❌（只看 stop_reason/answer/pending_call，:423-430） | — |
| trajectory 基准/测试 | ✅ 只断言字段存在（C-3 测试） | 非生产消费 |

**判定：`plan_evaluation` 目前是 PASSIVE MEMORY（纯记录），不是 Decision Input。**
`decision_summaries` 同理（见 07 文档）。

## 3. 由此产生的行为断层

硬校验 FAIL（如 MUST_VISIT_PLACE_MISSING、BUDGET_LIMIT 超限）发生时：

```
run_validation FAIL
  ↓ plan_evaluation.failures 记录
结构门（4 项结构检查）通过
  ↓ graph.py:417-420 强制 EMITTED
用户拿到一份带已知硬违例的行程，Agent 不提、不问、不修
```

对照 worker 路径：同样的 FAIL → has_blocker → 修复循环 → PLANNING_REVIEW_REQUIRED
（WAITING_USER，把决策交还用户）。**两个运行时对同一失败的处置不一致**——
agent 路径缺的就是"校验 FAIL → 告知用户/请求决策"这根线。

## 4. 要形成 Recovery Signal，缺的三件事（设计，不实施）

1. **分类**：plan_evaluation.status == NEEDS_REPAIR 且 failures 非空 → FailureKind
   `VALIDATION_BLOCKED`（区别于 INFEASIBLE——行程已产出，问题在校验层）。
2. **决策分支**：AskingDecider 对 VALIDATION_BLOCKED 的处置——按用户原则 2/3，
   正确动作是 **ask_user 列出冲突请用户决策**（提高预算/换必去/接受风险），
   而不是自动修复或静默发射。
3. **结构化问题**：failures 已含 rule_id/reason_code/message——足够生成
   "冲突涉及：预算/必去/固定安排"的选项化提问（pending_options）。

## 5. 反事实预览（Phase D 验收用）

```
现状（Counterfactual B'）：
  Impossible Constraint → build → run_validation FAIL
    → plan_evaluation 记录 → 结构门过 → EMITTED（带冲突行程）
目标（Counterfactual B）：
  Impossible Constraint → build → FAIL → CLASSIFY VALIDATION_BLOCKED
    → ask_user（选项=冲突映射）→ WAITING_USER
```
当前 B' ≠ B：**未形成闭环**。这是 Phase D 的核心改造点之一（D-3/D-5）。
