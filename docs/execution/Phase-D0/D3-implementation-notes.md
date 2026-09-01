# D-3 实施记录 — Infeasible Resume Loop 闭环（已落地）

> 2026-08-31 · 单 commit。Scope：agent/graph.py（AskingDecider）、agent/tools.py
> （update_constraints 尾部）、tests/agent/test_infeasible_resume.py（新）。

## Implementation

- `AskingDecider._extract_adjustment(state)`（新，确定性解析器）：
  - 复用 `_extract_slot_values`（预算/日期/人数/目的地），但**不套用采集阶段的
    "跳过 hard 槽"过滤**——用户在直接回答冲突提问，覆盖 confirmed 槽由 handler 的
    USER_OVERRIDE 规则裁决（证据门不变：值必须在原话中出现）；
  - must-visit 移除解析：**邻接判定**——删除词（删除/去掉/移除/取消/不要/别去/不想去）
    直接紧跟地名（"不要武侯祠"）才算点名删除；仅提及（"宽窄巷子还是可以去"）=保留；
    指代（"删除这个必去点"）仅在恰好一条时解析，多条目歧义 → 重复提问，绝不猜测；
  - 提议为空 → None → 重复提问（原行为）。
- INFEASIBLE 分支重写：**以 failure memory 未解决（failure_kind == USER_CONSTRAINT）
  为门**；门开时先解析调整 → 有调整走 update_constraints（REPLAN）；门关（约束更新
  已清记忆）→ 直接重建。
- `_update_constraints`：applied/rejected 非空时 partial 追加
  `candidate_itinerary=None`（旧候选作废）+ failure memory 清零（该失败的上下文已变）。
  NO_VALUES/仅 refused 的更新不清理。
- `_BUDGET_PATTERN` 扩展："预算可以提高到 4000" / "预算降到 3000" 可解析
  （用户 Test B 原话）。

## Verification

- pytest **2003 passed / 42 skipped**（新增 6 个 D-3 测试）；
- simulate_planning_v2 34/34（exit 0）；ruff PASS；
- Behavior Change：**YES**（本刀目标）——不可行 resume 从"重复同一问题"变为
  "解析调整 → 重建 → EMITTED（或带新冲突的再问）"；
- Checkpoint：version 2 不变（字段在 C-3 已入列，本刀零新增）；
- wire/DB：unchanged；Tool schema：unchanged。

## Counterfactual 结果

- Test A（删除必去）：INFEASIBLE→ask→resume"删除这个必去点"→update(移除)→重建→EMITTED ✅
- Test B（提预算）：2500→ask→resume"预算 4000"→USER_OVERRIDE(4000)→重建 ✅
- Test C（"随便吧"）：无调整→重复提问，约束不变 ✅
- Test D（无关回答"明天天气"）：不修改约束、继续 WAITING_USER、无 update ✅
- Test E（旧失败不污染）：resume 后第一个决策是 update（非 ask），
  重建成功后 failure memory 清零 ✅

## 幂等性与已知边界（按 §十一记录，未顺手修）

- 重复"不要 C"：第二次 reject 同值 → 槽保持 REJECTED，无破坏性副作用（幂等 ✅）；
- 被拒绝值的重新提议会被 handler REFUSED（防振荡设计）——用户想恢复原值需先明确
  拒绝该拒绝，属产品边界，记录不修；
- 多条目 must_visit 的批量删除（一条消息删两个）不支持 → 重复提问（每消息一个调整）；
- ask_user 观测跳过失败分类（提问是恢复动作的一部分，非成功解决）——
  失败记忆跨 ask 保留。
