# 05 — Ask User Resume Audit（ask_user 闭环审计）

> Phase D-0 · 核心问题：用户回答后，Agent 是否真的获得了新信息？

## 1. 机制现状

```
PLANNING_INFEASIBLE 观测（tools.py:514）
  ↓ AskingDecider INFEASIBLE 分支（graph.py:148-161）
ask_user(question="行程无法在当前约束下生成：{conflict}。请调整必去地点或日期…")
  ↓ stop_reason=WAITING_USER（tools.py:291-297）
checkpoint 落库（state.py:333-380，v2；persistence.py:255-267）
  ↓ AGENT_RESUME（用户原话）
handle_resume（agent_processor.py:230-316）：
  replace(checkpoint, user_message=answer, pending_*=None,
          stop_reason=None, steps=0, turn_baseline=len(observations))
  ↓ run_agent 继续
```

## 2. 闭环判定：**FAIL（对不可行场景）**

resume 后 `decide` 的分支顺序（graph.py:139-220）：

```
required_hard = all(必填槽位 hard)          ← 不可行场景：destination/dates 均 hard → True
if required_hard:
    builds[-1] PLANNING_INFEASIBLE  →  再次 ask_user（同一问题，graph.py:148-161）
    ……
# user_message 的解析（_extract_slot_values → update_constraints）
# 只存在于 required_hard == False 的分支（graph.py:178-192）
```

**结论：用户的调整回答（"改去北京"/"删掉 C"）在 resume 后永远不会被解析为
constraint 变更**——`required_hard` 为 True 时消息解析分支不可达，而 INFEASIBLE
分支无条件重复同一问题。用户陷入"回答→同样的问题"循环，唯一出口是 7 天 TTL
（agent_processor.py:236-249）或放弃。

对照：**采集阶段（required_hard=False）的 ask 闭环是通的**——
resume → 消息解析 → update_constraints → 槽位确认 → 继续
（轨迹基准 clarification-loop 场景验证）。

## 3. 期望语义（用户 §八示例）与现实差距

```
期望：
  Agent：预算 3000 无法同时满足 A、B、C，请选择：1 提高预算 2 删除 C 3 缩短行程
  User：删除 C
  → 用户新信息 → State 约束更新 → 重新 Planning → 新结果
现实：
  Agent：行程无法在当前约束下生成：{conflict}。请调整必去地点或日期……
  User：删除 C
  → resume → required_hard=True → INFEASIBLE 分支 → 同一问题（用户回答被无视）
```

三个差距：
1. **resume 消息不解析**（上述分支不可达）——D-3 修复点。
2. **问题不含结构化选项**（pending_options 未用于不可行场景）——用户不知道合法答案形态。
3. **冲突没有映射到可调整的约束槽位**（conflict.message 是自由文本，如
   "所选必去地点不是可安排的景点"——没有说"必去=武侯祠不可达，请改"）。

## 4. 采集阶段闭环（对照，PASS）

`clarification-loop` 场景（benchmarks/agent_trajectory/run_agent_trajectory.py:198-204）
证明：非 hard 阶段 resume → 消息解析 → update_constraints（证据信任规则）→
槽位确认 → build → EMITTED 全链通。**问题只在"约束已齐后的失败恢复"阶段。**

## 5. 结论

ASK_USER LOOP：采集阶段 **PASS**；不可行恢复阶段 **FAIL**。
修复方向（D-3）：resume 时若最后 build 为 PLANNING_INFEASIBLE，先把用户回答
作为 update_constraints 的 propose（evidence=原话，信任规则不变——仍需用户原话
包含新值）再走 INFEASIBLE 分支；问题文本结构化（列出冲突涉及的槽位）。
