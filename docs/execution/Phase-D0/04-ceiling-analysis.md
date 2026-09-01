# 04 — Ceiling Analysis（CEILING_REACHED 语义审计）

> Phase D-0 · 回答用户四问：为什么走到 Ceiling？是否死循环？State 有无记忆？能否识别重复？

## 问题 1：为什么 Agent 会走到 Ceiling？

三条真实路径（全部有代码证据）：

**路径 1：TOOL_ERROR 循环（最常见）**
```
build_itinerary → provider 抛 PlanningProviderError（瞬态耗尽/排序空崩溃/内部异常）
  → registry.invoke 吞为 TOOL_ERROR（tools.py:802-808）
  → AskingDecider 无 TOOL_ERROR 分支 → candidate_itinerary 仍 None
  → 决策"build the draft"（graph.py:162-166）→ 再次 build → 同一失败
  → …… 8 步 → CEILING_REACHED（graph.py:386-387）
```

**路径 2：FEASIBILITY_BLOCKED 循环**
```
validate → 窄门 has_blocker → FEASIBILITY_BLOCKED（tools.py:540 区）
  → AskingDecider gate 分支只检查 any(ok)（:167-172）→ 再次 validate 同一候选
  → …… → CEILING_REACHED
（已被测试固化为预期：test_a_blocked_gate_keeps_the_run_going，
  tests/agent/test_agent_loop.py:201-219）
```

**路径 3：ask_user 死循环（跨 run，非 ceiling 而是 TTL）**
```
不可行 → ask_user → WAITING_USER → resume（用户调整）→ required_hard 仍 True
  → INFEASIBLE 分支再次 ask_user（graph.py:148-161，用户回答不进 update_constraints）
  → WAITING_USER → ……（每 turn 8 步预算重置，永不触发 ceiling，
  直到 7 天 TTL EXPIRED，agent_processor.py:236-249）
```

## 问题 2：是否死循环？

**是**——路径 1/2 是**单 run 内**的"同一动作→同一失败"循环（确定性输入下结果必然相同）；
路径 3 是**跨 run**的"同一问题→同一回答位"循环。三者的共同根因：
**AskingDecider 不比较"上一次动作与上一次失败"**。

## 问题 3：State 是否记录 previous_action / previous_failure / attempt_count？

| 字段 | 状态 | 替代物 |
|---|---|---|
| previous_action | ❌ 无 | `observations[-1].tool`（历史在，但无语义封装） |
| previous_failure | ❌ 无 | `observations[-1].error_code`（同上） |
| attempt_count | ❌ 无（按动作维度） | `steps`（全局步数，不是"同一动作第几次"） |

`decision_summaries`（C-3）记录的是**成功路径的决策摘要**，不含失败签名。

## 问题 4：Agent 能否识别"我刚做过这个动作且失败原因没变"？

**不能。** AskingDecider 的分支是**无记忆的模式匹配**（按最后一个 build 观测的
error_code 分派），没有任何"与上上次比较"的逻辑。识别重复所需的原始数据
（observations 序列）完整存在于 State 中——缺的是分类与比对，不是数据。

## 结论

`CEILING_REACHED` 当前承担了三种本应由策略承担的失败终点：
①瞬态/内部失败的放弃、②校验阻塞的放弃、③未知失败的兜底。
按用户原则 4，Ceiling 应退回为**纯 Runtime Safety Boundary**——
这要求 Phase D 先建立失败分类（D-1），让每一类失败在到达 Ceiling 之前
被分类并选择 RECOVERY。
