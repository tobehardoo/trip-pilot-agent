# 07 — Decision Memory Audit（decision_summaries 是 passive 还是 active）

> Phase D-0 · 回答用户五问：谁写入？谁读取？跨 checkpoint？参与决策？阻止重复？

## 1. `decision_summaries`（C-3）

| 问题 | 答案 | 证据 |
|---|---|---|
| 谁写入 | `_build_itinerary` 工具（BuiltItinerary 分支），来源 RealItineraryBuilder 截取的 `result.decision_traces` 摘要（≤12 条） | tools.py C-3 partial；itinerary_builder.py:277-279 |
| 谁读取 | **无人**——AskingDecider/LLM prompt/_route 均不读取 | graph.py:135-220, 348-352 无引用 |
| 跨 checkpoint | ✅ 保留（v2 序列化，state.py C-3 dump/load） | state.py |
| 参与下一次决策 | ❌ | 同"谁读取" |
| 阻止重复失败动作 | ❌（它只记录成功路径的决策摘要，且不含失败签名） | — |

**判定：PASSIVE MEMORY。**

## 2. `plan_evaluation`（C-3）

同上：写入（build handler）→ checkpoint 保留 → **零消费者**。**PASSIVE MEMORY。**

## 3. 唯一的 active memory：`observations`

真正改变下一步行为的记忆是 `observations` 序列：
- AskingDecider 读 `builds[-1].error_code` 分派（graph.py:141-161）；
- gate 分支读 `any(validate ok)`（:167-172）；
- LLM prompt 注入 recent_observations（:352）。

但它是**原始流**，没有失败签名/重复检测——所以"能改变行为"仅限
C-1 加的两个分支，其余失败全部漏过。

## 4. 结论与含义

Phase C-3 完成了"资产入 State"，但**没有完成"State 驱动决策"**。
Phase D 的 Decision Memory 改造不是加字段，而是让既有字段被读：
- 失败签名（从 observations 派生：`tool + error_code + 关键参数摘要`）进入决策分支；
- `plan_evaluation.status` 成为 VALIDATION_BLOCKED 分类的输入；
- `decision_summaries` 保持被动记录即可（它是给用户/LLM 的上下文，不是控制流）。
