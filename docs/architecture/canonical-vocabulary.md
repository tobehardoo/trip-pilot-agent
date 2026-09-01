# Canonical Vocabulary（规范词表）

- 文档状态：生效中
- 最后更新：2026-09-01（F-2a，F-0 收敛方案第 49 行正式化；E-1 已落地，Evaluation 判词更新）
- 用途：全阶段共用术语基准。任何文档/评审/提交信息中的概念名词必须对照本表；发现表外概念或一义多词即视为重复源，按 F-2 处理
- 权威原则：**代码是最终事实**；本表只裁定"用什么词、指向哪里"，不新增设计

## 1. 概念 → Canonical 对照

| 概念 | Canonical | 判词 |
|---|---|---|
| Agent | `AgentLoop`（decide→act→finish 有界循环） | 唯一；不存在第二个 agent 拓扑 |
| Decider | `AskingDecider`（确定性默认）/ `StructuredOutputDecider`（可选 LLM 兜底） | 双轨刻意保留（无模型配置兜底） |
| Tool / Observation | `ToolRegistry` + `ToolObservation` | 唯一；9 个声明式工具 |
| Evaluation | `plan_evaluation`（state 字段） | E-1 落地后：结构化评估参与反射裁决（`reflect_on_evaluation` → ACCEPT / REJECT_HARD），有界（`REFLECTION_MAX_ATTEMPTS=3`）；quality 是反馈永不 gate |
| Feasibility | 结构门 `StructuralFeasibilityGate`（发射仲裁）+ 硬校验 `run_validation`（管线内） | 两者并存但职责不同；S2 分歧已由 E-1 裁决（NEEDS_REPAIR+失败不得 EMITTED） |
| Candidate / Itinerary | 管线候选 → `Itinerary` wire 契约 | 唯一 |
| Constraint | `ConstraintSlots`（槽位五态）+ `TripConstraints`（wire） | 两个层次，非重复；用户已确认约束不可变 |
| Event | 活跃集 = completed v9-11 / review v1-2 / progress v1-2 / failed v1-2 / AGENT_* v1 | 其余代际在 F-3c 终结（v4–v8 → `legacy/`） |
| Recovery | `failure_policy`（D-1 分类 + D-2 重试 + D-4 重复判定） | 唯一 |
| Provider | map/route/planning 三类 provider；demo/real 双轨刻意（`PROVIDER_MODE` 门控 + `ProviderFallbackPolicy`） | 保留 |
| Builder | `DemoItineraryBuilder` / `RealItineraryBuilder`（共享 `build_demo_command`） | 双轨刻意；可合并为一个类+可选 summary，列为可选项 |
| Planner | 确定性规划管线（candidates→daily_schedule→feasibility），**禁止 LLM 化** | 唯一 |

## 2. 使用规则

1. **一概念一名**：引用上述概念时只用 Canonical 词（或代码标识符原文），禁止同义替换（如 "agent loop" / "planning agent" / "AI assistant" 混用）。
2. **判词是约束**："唯一"= 不得再引入第二份实现；"双轨刻意"= 可保留但新增引用须先对照；"待终结"= 该概念指向的代际进入清理队列，不得新增消费者。
3. **跨端一致性**：Java / Python / Web 三端对同一概念的命名必须落在本表 Canonical 上；发现分叉（如 `isPersistableMoney` 双解析器不一致）即按 F-2c 类处置。
4. **评审清单**：架构级检查时逐项对照本表（死 import、死代码残留、重复入口、重复概念、旧目录/旧配置、无消费者 abstraction），见 F-0 方案 §128。

## 3. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-08-31 | F-0 收敛方案首次成表（docs/execution/Phase-F0/02-convergence-plan.md §F-2a） |
| 2026-09-01 | 正式化为独立文档；Evaluation 判词随 E-1 落地更新（反射闭环 + 预算上限）；Feasibility 判词更新（S2 已裁决）；Event 代际终结指向 F-3c |
