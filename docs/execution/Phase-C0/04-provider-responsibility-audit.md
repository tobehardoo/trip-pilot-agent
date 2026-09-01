# 04 — Provider Responsibility Audit（God Planner 判定）

> Phase C-0 · 对象：`AmapPlanningProvider`（infrastructure/amap/planning_provider.py，约 2200 行）。

## 1. 职责清单（对照 Agent Phase）

| Responsibility | 当前 Owner | file:line（planning_provider.py 除注明外） | 是否合理 |
|---|---|---|---|
| Observe（数据获取） | AmapPlanningProvider（经注入的 MapProvider/RouteProvider） | `_collect_pois` :1836、`_route_for_pair` :1966、`_resolve_meal_poi` :1652、`_resolve_travel_anchors` :1732、`_resolve_fixed_place` :1668 | ⚠️ 获取本身经 provider 接口（可替换）✓，但获取策略/关键词/limit 全写死在类内 |
| Build Context | PlanningContextView（V3 P2-0 抽出） | planning/context_view.py:121-160；provider 仅构造 :419 | ✅ 已收敛（Phase B 成果） |
| Retrieve（候选） | 同上 | :499-508 池过滤 | ⚠️ 与分类策略强耦合在同文件 |
| Rank（排序） | 委托 CandidateRanker（planning/candidates.py:79） | provider :525-558 仅组装参数 | ✅ 合理（排序是独立纯策略） |
| Decide（约束裁决） | transport_strategy / mode_recommendation / daily_schedule / budget_policy / poi_quality（全部纯模块） | provider 为编排者：:559-640 traces、:1393-1415 forward-fit、:2142/2208 trace 发射 | ⚠️ 裁决逻辑在纯模块 ✓，但**编排+发射+缓存+重试预留**都在 provider |
| Act / Emit（行程生成） | `_emit_day` + `_plan_with_skeleton` | :1145-1530（槽组装、住宿节点 :1334-1366、前后拟合 :1393-1415、逐腿路由+trace） | ⚠️ 这是最大的一坨 |
| Evaluate | **不在 provider**（processor.py:315 调 PlanEvaluator） | — | ✅ 职责已分离 |
| Explain | trace 发射点在 provider（:567 预算、:609 节奏、:2142/2208 交通、:503-540 准入/排序），转换在 evaluation/explanations.py:56 | — | ⚠️ 发射在 Act 途中（合理——证据在源头），但与 Act 强耦合 |
| Repair（修复执行） | provider.repair（:1790s）+ feasibility/repair/* | — | ✅ 分层正确 |

## 2. 判定：God Planner？

**是——但不是"逻辑 God"，而是"编排 God"。**

- 决策逻辑本身已经 Phase B 化：全部是可测纯模块（planning/ 下 13 个文件）。
- 但 `AmapPlanningProvider` 同时承担：召回编排、池过滤调用、排序参数组装、调度调用、
  餐食解析、交通决策调用与每腿路由、住宿锚点、前后拟合、成本解析调用、trace 发射、
  修复执行、事件进度上报调用——**一个类 10+ 个编排职责，约 2200 行**。
- 佐证：类内私有方法 30+；`_plan_with_skeleton`（:381-1143）单函数约 760 行；
  `_emit_day`（:1145-1530）约 385 行。
- 与 V2 审计 §15 的结论一致并加重：当时是"宽 DTO + 散落函数"；V3 P2-0 收敛了 Context，
  但**编排体量**继续全部落在这一类。

## 3. 影响链

1. Phase B 的决策资产（ContextView/DecisionTrace）被锁死在 provider 进程内——
   对话 Agent 无法复用（06 文档）。
2. 任何新决策点（如 Fixed×Budget）都只能继续往这个类里加（P2-2c 即如此）。
3. 可测试性靠补丁维持（harness 重复造 fake provider）。

## 4. 处置方向（详见 07 文档）

不是"拆成几十个 Node"（伪 Agent 化），而是把 `_plan_with_skeleton` 的**编排骨架**
提升为一个显式的确定性 Pipeline 步骤序列（每步已是现成函数/模块），provider 退化为
"AMap 适配器 + 步骤装配"。这是 C 系列的可选刀，**不是本次必须**——当前阻塞项是对话侧
demo 行程与工具接线（08 文档 C-1/C-2）。
