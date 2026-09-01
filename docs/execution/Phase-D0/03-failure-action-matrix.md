# 03 — Failure → Action Matrix（Failure→Action Policy 审计）

> Phase D-0 · 每行：失败 → 当前检测位置 → 当前消费者 → 当前动作 → 合理性。

| Failure | 检测位置 | 当前消费者 | 当前动作 | 合理？ |
|---|---|---|---|---|
| `PLANNING_INFEASIBLE`（provider 抛） | _build_itinerary 捕获（tools.py:514） | AskingDecider INFEASIBLE 分支（graph.py:148-161） | ask_user（REPLAN strategy）→ WAITING_USER | ✅ 方向正确；❌ resume 不闭环（05 文档） |
| 文本型 must-visit 未覆盖（校验 FAIL） | plan_evaluation.failures（C-3） | **无人消费** | 行程照常 EMITTED，冲突只在摘要 | ⚠️ 半合理：结构门语义如此；但"覆盖不了还发射"缺一个用户可见的显式提醒（themed/事件层有摘要） |
| `CAPABILITY_MISSING`（build） | tools.py:490 | AskingDecider（graph.py:141-147） | answer 移交规划链路（ANSWERED） | ✅ |
| `CAPABILITY_MISSING`（观测工具） | tools.py:310/325/344/364 | **无人**（观测失败不进决策分支） | observation 记录后继续 | ✅ 可接受（观测失败≠规划失败）；❌ 无降级提示给用户 |
| `TOOL_ERROR`（含**瞬态 provider 失败**、内部异常） | invoke 吞咽（tools.py:802-808） | AskingDecider **无分支** | build 失败 → candidate None → **立即重试同一 build**（同 turn）→ 多数再失败 → CEILING | ❌ **最不合理**：瞬态失败（已耗尽 provider 层重试）与确定性失败同貌；无退避、无分类、无提示 |
| `FEASIBILITY_BLOCKED`（窄门 FAIL） | validate 观测 error_code | AskingDecider gate 分支（:167-172 检查 any ok） | **重复 validate 同一候选** → CEILING | ❌ 与 CAPABILITY 同类的"重复动作到上限"（test_a_blocked_gate 固化了此行为） |
| `INSUFFICIENT_AMAP_POIS` / 排序空崩溃 | provider 抛/崩 → TOOL_ERROR | 无分支 | 同 TOOL_ERROR 重试→CEILING | ❌ |
| `INVALID_CONSTRAINT_VALUES` / `INCOMPLETE_CONSTRAINTS` / `NO_CANDIDATE` | tools.py:516/492/540 | AskingDecider | 候选 None → build 重试（INCOMPLETE 时先 ask——missing_required 分支在非 hard 路径） | ⚠️ INCOMPLETE 在 hard 齐全时不会出现；语义 OK |
| 硬预算超限（BUDGET_LIMIT FAIL） | run_validation | 无 agent 消费 | EMITTED 携摘要 | ⚠️ worker 路径会 raise 拦截；agent 路径发射——两路语义不一致（记录，非本次修） |
| `UNKNOWN_TOOL` / 输入类 EMPTY_* | tools.py:799 等 | AskingDecider 重复提问分支（非 hard 路径） | 重复提问 | ✅ |
| `CEILING_REACHED` | graph.py:386-387 | finish | run 结束（STOPPED 语义落库） | ❌ 它是安全边界被当成了失败处理的最终答案 |

## 结论（直接回答用户的问题）

**是的——当前系统把大量不同 Failure 统一处理成了 `CEILING_REACHED`。**
机制：TOOL_ERROR / INSUFFICIENT / FEASIBILITY_BLOCKED 等失败在 AskingDecider 里
没有对应分支 → 决策器退回默认动作（重试 build/validate）→ 同一动作×同一失败循环 →
8 步上限 → CEILING_REACHED。已有测试甚至把它固化为预期
（test_a_blocked_gate_keeps_the_run_going 断言 CEILING_REACHED）。

仅两类失败有真正的分类处理：`CAPABILITY_MISSING`（→ 移交/降级）与
`PLANNING_INFEASIBLE`（→ ask_user，C-1 新增）。
