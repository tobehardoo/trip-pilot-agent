# Phase E-0 · Fact Verification（重新审计，全部证据取自 HEAD `7ef8340`）

> 审计刀，零生产代码改动。不复用 C-3 / D-0 旧报告结论——所有判定由本次代码阅读
> 与一次确定性反事实运行重新得出（旧结论只在 §九 做交叉对照）。

## Fact A — Evaluation 的真实产生位置

追踪链：`build_itinerary → BuiltItinerary → run_validation → plan_evaluation → AgentState`

1. **产生位置**：`_build_itinerary` 工具把后端结果写入 state 更新
   （`src/trip_agent/agent/tools.py:579-586`）：
   `plan_evaluation = built.feasibility`（tools.py:584）。
2. **内容构造**：`RealItineraryBuilder.__call__` 用
   `_hard_validation_summary(command, result)` 生成 feasibility
   （`src/trip_agent/agent/itinerary_builder.py:236`），其实现
   （itinerary_builder.py:243-267）对管线产物跑**完整硬校验** `run_validation`，
   返回 `{"status": report.status.value, "failures": [{rule_id, reason_code, message}]}`。
3. **status 词表**：`FeasibilityStatus = {VERIFIED, UNVERIFIED, NEEDS_REPAIR}`
   （`src/trip_agent/feasibility/models.py:32-35`），由规则结果聚合：
   任一 FAIL → `NEEDS_REPAIR`（models.py:321-325）；
   `RuleOutcome = {PASS, FAIL, UNKNOWN, NOT_APPLICABLE}`（models.py:38-42）。
4. **字段性质**：**100% 硬约束结果**。没有 score、没有 REVIEW、没有任何质量指标；
   "PASS/FAIL" 语义只存在于单条规则结果（RuleOutcome）层面。
5. **确定性来源**：全部来自确定性管线（`feasibility/validator.py` 的 11 条规则注册表，
   validator.py:64-66 等）；没有任何摘要来自模型。
6. **decision_summaries**：管线 DecisionTrace 的文本摘要，封顶 12 条
   （itinerary_builder.py:237-239），同样纯记录。
7. **Demo 路径无 evaluation**：`DemoItineraryBuilder` 返回裸 `Itinerary`
   （itinerary_builder.py:182-187），走 tools.py:588-596 分支——
   `plan_evaluation` 保持 `None`。

## Fact B — Evaluation 的真实消费者

全仓搜索（`src/` 内 `plan_evaluation` / `decision_summaries`）逐一核对
`产生者 → State → 消费者 → Decision`：

| # | 消费者 | 读取方式 | 是否改变 Decision |
|---|--------|----------|-------------------|
| 1 | `_act_node` 失败分类（graph.py:692-706） | 取 `plan_evaluation.failures[*].reason_code` 喂给 `classify_failure` | **间接**：只改失败记忆三字段；该记忆被 D-2/D-3/D-4 分支读取。仅对"失败方向"有贡献 |
| 2 | `AskingDecider._failure_detail`（graph.py:413-420） | 取 `failures[*].message` 拼 D-4 升级问题文本 | 否——只影响问题措辞，不产生分支 |
| 3 | checkpoint 序列化（state.py:408、472） | 存取 | 否（持久化） |
| 4 | `StructuredOutputDecider._prompt`（graph.py:600-622） | **完全不读**；只有 `recent_observations()` 文本里夹带 build 摘要（tools.py:562-568 的 "hard validation …" 字样） | 否 |
| 5 | agent 包外 | `src/` 全量 grep 无其他消费者；worker 路径的 `run_validation`（worker/processor.py:247、410）是 worker 自己的闸，不读 AgentState.plan_evaluation | — |

**关键验证**：`AskingDecider.decide`（graph.py:177-361）的每个分支条件只依赖
`observations`（tool/error_code）、`candidate_itinerary`、`failure_kind/attempts`、
slots——**没有任何分支读 `plan_evaluation.status` 或任何质量信号**。

> 判定：`plan_evaluation` 对"下一步做什么"而言是 **PASSIVE MEMORY**；
> 唯一的主动用途是 D-1 失败分类的输入侧通道（failure-only）。

## Fact C — Evaluate 与 Feasibility Gate 的关系

- `validate_itinerary` 工具（tools.py:599-633）调 `runtime.feasibility`，
  生产实现是 `StructuralFeasibilityGate`（feasibility_gate.py:29-68）：
  wire 契约重建 + 「无 days」+「日期倒挂」+「活动 end ≤ start」。**仅此四项**。
  模块自述（feasibility_gate.py:1-10）：该规则集**故意窄于**管线硬校验套件。
- 硬约束清单（日期、预算、must_visit、fixed_schedule、营业时间、时间窗、
  路线连续性等）全部在 `run_validation` 注册表（feasibility/validator.py）——
  它们进入 `plan_evaluation`，但**不是** EMITTED 的闸门。
- **Plan Quality 维度不存在于 agent 边界**：质量打分只活在管线内部候选排序
  （`planning/candidates.py:188-262` 的 `_score`；amap provider 使用点
  `infrastructure/amap/planning_provider.py:419、530`；
  `planning/daily_schedule.py:179` 的内部 score）——它们是**生成输入**，
  从不作为评估输出暴露。
- 结论：当前系统只有硬约束验证；「合法 ≠ 高质量」这一区分**没有任何代码承载**。

## Fact D — 当前 EMITTED 的真实判据

```
decide → validate_itinerary(ok) → _act_node: stop_reason = "EMITTED"
```

- 发射点在 `graph.py:718-721`：`validate_itinerary` 观测 `ok=True` ⇒
  `update["stop_reason"] = "EMITTED"`（P2.4：模型没有 emit 工具）。
- `ok` 的来源：`ok = not report.has_blocker`（tools.py:624-631），
  `has_blocker` 只由上述四项结构检查产生。
- 因此判据是：

```
结构合法（结构门 4 项检查）→ EMITTED
```

**不是** `结构合法 + quality threshold`。硬校验结论（`plan_evaluation`）
完全不参与发射判定。

## Fact E — 「质量差但合法」的确定性反事实（本次实测）

一次性脚本（审计后删除，不进仓）运行**真实循环**
（`AskingDecider` + 生产工具注册表 + 生产 `StructuralFeasibilityGate`），
三个确定性构造：

| 场景 | 构造 | 实测结果 |
|------|------|----------|
| S1 硬约束全过 + 质量明显低 | 3 天行程每天仅 1 个 1 小时活动（观光利用率 ~15%），`plan_evaluation = {"status": "VERIFIED", "failures": []}` | `stop_reason=EMITTED`；失败记忆清零；轨迹 `build(ok) → validate(ok)`；**无任何额外动作、无提问、无质量判断** |
| S2 硬校验 FAIL 已记录但结构门通过 | 同一行程，`plan_evaluation = {"status": "NEEDS_REPAIR", "failures": [BUDGET_LIMIT/BUDGET_EXCEEDED]}` | **仍然 EMITTED**。失败记忆最终为 `USER_CONSTRAINT / USER_CONSTRAINT:validate_itinerary:BUDGET_EXCEEDED / 1`（未解决！）——一个未被处理的用户级硬校验失败被直接发射 |
| S3 结构门拦截 | 活动 end 早于 start | `WAITING_USER`；`FEASIBILITY / FEASIBILITY:validate_itinerary / 1`；D-4 升级提问 |

结论：

1. **质量低不触发任何行为**——`validate PASS → EMITTED` 成立，Evaluation 未控制 Decision。
2. 比预期更尖锐的附带发现：**连已记录的硬校验 FAIL（NEEDS_REPAIR）也不阻止
   EMITTED**，只要窄结构门放行（S2）。硬校验与结构门脱钩，且未解决的
   `USER_CONSTRAINT` 失败记忆与 `EMITTED` 终态并存。
3. 唯一真正「评估驱动决策」的路径是结构门 blocker → D 系恢复（S3）。

## Fact F — Replan 的现有边界

- 当前 replan 只能由**用户约束变化**触发：
  D-3 路径 `_extract_adjustment → update_constraints`（strategy `REPLAN`，
  graph.py:190-209），门控条件是「最近观测是 ask_user 且失败记忆属于
  `USER_OWNED_KINDS`」；以及 `PLANNING_INFEASIBLE` 的提问分支（graph.py:210-234）。
- 全代码不存在 `Evaluation LOW → 自动 REPLAN` 的任何分支。
- D-4 守卫「只写决策、不写状态」（graph.py:363-402）；rebuild 预算由
  `FAILURE_REPEAT_BUDGET`（failure_policy.py:304-312）控制，
  非 TRANSIENT 一律为 0。

## Fact G — Constraint Immutability（E 阶段必须继承的防线）

- 只有 `CONFIRMED` / `USER_OVERRIDE` 是硬约束（`HARD_STATES`，state.py:39-41；
  `slot.hard`，state.py:70-76）。
- 写入硬槽位的唯一通道是带证据的 `update_constraints`（evidence-match 规则，
  tools.py 的 `_update_constraints`）与用户覆盖（D-3 复用同一处理器，
  graph.py:438-441 注释明确覆盖也必须走证据闸）。
- 自动恢复路径（D-2 重试、D-4 守卫）均不写槽位（graph.py:376-381）。
- D-Final 验收套件（`tests/agent/test_decision_recovery_acceptance.py`，
  invariant G/H）已在 `7ef8340` 证明 7 条轨迹零约束篡改。

## Fact H — LLM Decision 与 Deterministic Decision 的边界

- `AskingDecider`（graph.py:167-485）：**全确定性规则**，是当前验收基准与
  无 Key 路径的实际决策者。
- `StructuredOutputDecider`（graph.py:518-622）：LLM，可选项；解析/传输失败
  降级回 `AskingDecider`（graph.py:562-569）；预算 `MAX_LLM_CALLS=8`（graph.py:46）。
  其 prompt **不包含** `plan_evaluation` 结构，仅观测文本。
- 评估侧（`run_validation`、结构门、管线）全部确定性。
- 结论：**Evaluation → Decision 闭环可以先完全由确定性规则实现，无需新增 LLM**。

## 九、与旧审计的交叉对照（仅对照，不作为证据）

- C-3 审计与 D-0 `06-evaluation-recovery-audit.md` 的「PASSIVE MEMORY」结论：
  本次在 HEAD 重新验证**成立**，并新增两条当时未显式记录的事实：
  (a) S2 的「硬校验 FAIL 照样发射 + 未解决失败记忆并存」；
  (b) demo 路径 `plan_evaluation` 恒为 `None`。
