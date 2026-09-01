# 03 — Graph Agent Classification

> Phase C-0 · 最重要的单项审计。先画真实 Graph，再分类。

## 1. 对话运行时的真实 LangGraph（agent/graph.py:365-377）

```
START
  ↓ (graph.py:370)
decide  ←──────────────┐
  │ (_route :423-430)  │ (graph.py:376 回边)
  ├─ stop_reason != None ──────→ finish → END (:377)
  ├─ answer != None ───────────→ finish → END
  ├─ pending_call is None ─────→ finish → END
  └─ else → act (:397-421)
              │ tools.invoke (:407) → ToolObservation
              │ validate 通过 → 强制 stop_reason="EMITTED" (:417-420)
              └──────────────→ 回 decide
```

预算封顶：MAX_STEPS=8 / MAX_TOOL_CALLS=16 / MAX_LLM_CALLS=8（graph.py:38-40）；
`CEILING_REACHED` / `LLM_BUDGET_EXHAUSTED`（:42-43）。
decide 节点读取**上一轮 act 的结果**分支（AskingDecider: graph.py:141-166；
LLM 路径 prompt 注入 recent_observations，:352）。

## 2. 规划运行时的"真实 Graph"（无 LangGraph，但控制流等价图）

```
START
  ↓
process_planning_create（processor.py:106）
  ↓
provider.plan（确定性全链：召回→池准入→排序→调度→餐食→交通→成本→trace）
  ↓
run_validation（processor.py:247-254）
  ↓
FAIL? ── YES → repair loop（≤3 轮：plan_repairs → apply/provider.repair
  │              → run_validation → advance；停止条件 session.py:94-107）
  │              ├─ 修复后 PASS/UNVERIFIED → 继续
  │              └─ 仍有 FAIL → PLANNING_REVIEW_REQUIRED（WAITING_USER）
  ↓ NO
_plan 形 outcome_event（:273-329）
  ├─ not has_blocker → PlanEvaluator.evaluate（:315，硬违例 raise）
  │                    → PLANNING_COMPLETED（evaluation 入 payload）
  └─ has_blocker    → PLANNING_REVIEW_REQUIRED（WAITING_USER）
  ↓
异常（Infeasible/ProviderError/内部）→ PLANNING_FAILED（终态，无重试）
```

## 3. 分类判定

| 运行时 | 判定 | 依据 |
|---|---|---|
| **规划运行时** | **类型 B（条件 Workflow）**，内嵌一个**有界的确定性修复子循环** | 主链线性；分支依据是 feasibility `has_blocker`（processor.py:298），不是 PlanEvaluator 评分；修复循环是 evaluate→act→re-evaluate（session.py:61-113）但动作空间是**预编排的 6 种修复动作**（repair/catalog.py:34-66），没有"根据评估改变策略"的开放决策 |
| **对话运行时** | **类型 C（真实 Agent Loop）——但牙口受限** | LangGraph 循环真实（decide→act 条件回边 + 观测注入决策 + 语义停止原因 + checkpoint/resume）；但 9 个工具中 4 个生产未接线（tools.py:308/323/341/357 → CAPABILITY_MISSING），`build_itinerary` 产出 **Demo 骨架行程**（itinerary_builder.py:176-183 → DemoPlanningProvider "placeholder activities per day"，infrastructure/demo/planning_provider.py:40-43），评估是窄口径结构门（feasibility_gate.py:29-68），且 gate 阻塞后无修复分支只会重试到 CEILING（graph.py:154-161） |

## 4. 主分类结论（不模糊）

**TripPilot 的主规划产品运行时 = 类型 B（条件 Workflow）。**
对话侧存在一个架构真实的类型 C Agent Loop，但它当前是**槽位采集 + demo 行程生成器**，
不是规划 Agent。整体上，"用户要的旅行计划"是由类型 B 管线生产的。

## 5. PlanEvaluator 控制权（专项）

| 问题 | 答案 | 证据 |
|---|---|---|
| 谁消费 evaluation 输出？ | 只写入 PLANNING_COMPLETED payload 的 `evaluation` 字段 | processor.py:312-316；contracts.py:1184-1199 |
| 是否影响 Graph Edge？ | ❌ 否——completed vs review 分支只看 feasibility `has_blocker`（processor.py:298） | processor.py:298 |
| 是否影响下一轮 Planning？ | ❌ 否——无基于评分的再规划 | 全链无该分支 |
| 是否影响 Candidate/Strategy？ | ❌ 否 | — |
| 唯一控制点 | `evaluate()` 对硬违例 **raise**（evaluator.py:87-98，retryable=False）→ 终态 PLANNING_FAILED（amqp.py:703-712, 906-917，ack 无重试） | 隐藏闸门，非循环控制 |
| Java 侧 | evaluation 是落库**必填**（PlanningCompletionService.java:103-105），被重映射后入 task event 供前端展示 | 展示用途，非控制 |

**结论：PlanEvaluator = Post-processing Evaluator（情况 1）**。拥有运行时控制权的是
feasibility report（has_blocker → REVIEW/修复循环）与 repair session。

## 6. 真实 Replan 存在性

| 层 | 存在？ | 形态 |
|---|---|---|
| worker 修复循环 | ✅ | evaluate→repair→re-evaluate ≤3 轮，确定性动作目录，session.py:61-113 |
| 规划失败后的 replan | ❌ | PLANNING_FAILED 终态 ack（amqp.py:917），Java 无自动重试（唯一重试是内部诊断手动端点，J\planning\InternalPlanningDiagnosticsController.java:42-51） |
| WAITING_USER（规划）恢复 | ❌ | 只有用户放弃（PlanningTaskService.cancel:649-704 → abandon :182-193）或重新发起 |
| WAITING_USER（agent run）恢复 | ✅ | AGENT_RESUME + checkpoint（agent_processor.py:230-316） |
| 对话循环内的 evaluate→replan | ❌ | gate 阻塞 → 重复 validate 到 CEILING（graph.py:154-161） |
```
