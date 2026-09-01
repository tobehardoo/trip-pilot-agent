# Phase E · 02 — Reflection Design（闭环设计）

**目标**：补齐唯一断点 `Evaluation → Reflection Decision → Next Decision`，形成
有界的 Planning Reflection Loop，且不增加“为了像 Agent”的复杂度。

---

## 1. 闭环形态（Before → After）

```
Before（HEAD）:
  build ─▶ plan_evaluation 进 state ─▶ validate（结构门）─▶ EMITTED   ← 评估不参与

After（Phase E）:
  build ─▶ plan_evaluation 进 state ─▶ Reflection Decision（确定性代码）
                │
                ├─ ACCEPT ─▶ validate（结构门）─▶ EMITTED          （Case A）
                │
                └─ REJECT_HARD ─▶ 失败恢复通道（D-4 护栏）
                        └─▶ ask_user（用户调整约束）─▶ resume ─▶ update_constraints
                              └─▶（无调整答复）→ 诚实结束（ANSWERED）
                              └─▶（预算耗尽）→ 强制停止（Case D）
```

**关键点**：Reflection Decision 是**确定性代码**（与 EMITTED 同为代码裁决），
LLM 只被*注入*评估上下文，从不拥有反射裁决权。

## 2. 双通道语义（Failure vs Quality Feedback）

任务要求“必须区分 Failure 与 Quality Feedback”，与 Phase-E0 事实 C 一致：

| 通道 | 载体 | 语义 | 是否进失败记忆 | 是否阻塞发射 |
|---|---|---|---|---|
| **Failure（硬校验）** | `plan_evaluation.status` / `failures[]` | “这个候选违反硬性约束，当前输入下不可接受” | **是**（经 reason_codes → `classify_failure`，graph.py:692-706） | **是**（P0：REJECT_HARD 不 EMIT） |
| **Quality Feedback（质量）** | `plan_evaluation.quality`（新增子结构） | “硬性约束满足，但整体质量一般（可改进信号）” | **否**（永不进 failure_kind / 永不做 reason_codes） | **否**（硬 PASS 的行程是合法状态，E-0 Fact C） |

质量是**反馈信号**（记录、随观测摘要展示、注入 LLM 决策上下文），不是失败，
也永远不冒充硬失败。Demo 路径不产生质量（Fact A-7），quality 保持 None。

## 3. Reflection Decision 判决表（Case A-D）

纯函数 `reflect_on_evaluation(evaluation) -> Verdict`，输入仅 `plan_evaluation`
（status + failures），输出 `ACCEPT | REJECT_HARD`：

| Case | 输入（Evaluation） | 反射裁决 | Next Decision（行为变化） |
|---|---|---|---|
| **A** | status ∈ {VERIFIED, UNVERIFIED} 且 failures 为空（含 quality 任意/缺失） | ACCEPT | 维持原路径：validate 结构门 → EMITTED（graph.py:718-721 加 ACCEPT 前提） |
| **B** | status == NEEDS_REPAIR 且 failures 非空（即使结构门会放行，S2） | REJECT_HARD | **不 EMIT**。走既有失败恢复：D-4 护栏（failure_policy.py:344-374）→ ASK_USER（USER_CONSTRAINT/FEASIBILITY 均为 USER_OWNED）或 STOPPED；`reflection_attempts += 1` |
| **C** | 硬 PASS 但 quality.verdict == POOR | ACCEPT（门不阻塞） | 质量作为反馈：build 观测摘要携带质量注记（tools.py build summary）、state 记录、LLM prompt 注入；**不**进失败记忆、不阻塞发射 |
| **D** | `reflection_attempts >= REFLECTION_MAX_ATTEMPTS` 且当前裁决为 REJECT_HARD | STOP | `_decide_node` 短路（graph.py 决策节点内，两种决策器统一生效）：不调用决策器，直接产出最终答案（ANSWERED），“当前约束下反复尝试仍无法生成可接受行程” |

## 4. Reflection Budget（有界，禁止无限 REPLAN）

- **常量**：`REFLECTION_MAX_ATTEMPTS = 3`——与规划器 `MAX_REPAIR_ATTEMPTS = 3`
  （feasibility/repair/engine.py:30）同哲学：允许尝试，禁止空转。
- **计数**：`AgentState.reflection_attempts`；在 `_act_node` 对 **build 观测**且
  裁决为 REJECT_HARD 时 +1（validate 不改变评估，不计）。
- **重置**：`update_constraints` 应用了用户约束变更时清零（与失败记忆同块，
  tools.py:235-238）——“约束变更 = 新上下文”。
- **语义**：同一约束上下文内，被评估否决的候选至多 3 个；LLM 决策器若反复
  build（不改变约束）会在第 3 个候选后触发 Case D 强制停止；AskingDecider
  路径因每次否决即 ask（D-4 预算 0）天然每次只问一次，且“无调整答复”直接
  诚实结束（不会同问死循环）。
- **兜底不变**：MAX_STEPS=8 / MAX_TOOL_CALLS=16 / MAX_LLM_CALLS=8 原样保留。

## 5. 行为变化清单（可测试证据）

1. **P0/S2**：NEEDS_REPAIR + 结构门放行 → 不再 EMITTED；改为 ask_user
   （test_real_itinerary_backend.py:221-234 的反转会证明）。
2. **Case B**：build 产出被评估否决后，AskDecider 直接进入反射分支 ask
   （跳过注定放行的 validate），question 复用 D-4 模板。
3. **Case C**：build 观测摘要新增质量注记（如 `quality 58 (POOR)`）；质量子
   结构进 state/checkpoint；LLM prompt 可见。
4. **Case D**：misbehaving-LLM 场景（stub 决策器反复 build）在第 3 个候选后
   强制停止，不进 CEILING 空转。
5. **P1 注入**：LLM prompt 新增“当前行程评估 + 反思预算”区段（决策上下文
   CURRENT STATE 结构，见 04-decision-contract.md）。

## 6. 不变式（延续 Phase-E0 §Invariants + 任务书）

- EMITTED 仍是确定性代码；质量不阻塞发射（无“接受”机制新增）。
- 确认约束不可变；硬校验/质量失败只 ask，从不自主改约束、从不自主 REPLAN。
- 不删 LangGraph、不动态创建 Tool、不删 Guardrail、不引入 Multi-Agent。
- 无 wire/schema 变更；checkpoint v2 兼容（新字段可加性）。
- Demo 路径零质量、零新 I/O；质量生产复用既有 `PlanEvaluator`（确定性、只读）。
