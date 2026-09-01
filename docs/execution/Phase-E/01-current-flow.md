# Phase E · 01 — Current Flow（HEAD 现状）

**Audit target:** HEAD（Phase D-Final 之后，含 C-1/C-3/D-1..D-4）· **Mode:** read-only
**Evidence base:** 全部为 HEAD 实测（file:line），不以旧快照结论为证据。

---

## 1. 循环骨架（真实 Runtime Data Flow）

```
START ─▶ decide ──▶ act ──▶ decide ──▶ ... ──▶ finish ─▶ END
             │                  │
             └──── pending_call ┘（条件边 _route）
```

- `AgentLoop.build`（graph.py:634-647）：`START→decide`，`_route`（graph.py:724-731）在 `stop_reason`/`answer` 存在或 `pending_call is None` 时走 `finish`，否则走 `act`。
- `_decide_node`（graph.py:652-664）：步数上限 `MAX_STEPS=8`（graph.py:44）先于决策器；决策器产出 `Decision`（工具调用 or 最终答案）。
- `_act_node`（graph.py:666-722）：调用工具 → 追加 `ToolObservation` → 失败分类写入记忆 → **唯一发射点**。
- 三重预算：`MAX_STEPS=8 / MAX_TOOL_CALLS=16 / MAX_LLM_CALLS=8`（graph.py:44-46）。

## 2. Evaluation 的现状：PASSIVE MEMORY + 一个分类旁路

**生产端（唯一）**：`RealItineraryBuilder` 在 build 时运行完整硬校验
`run_validation`，压缩为 `{"status", "failures":[{rule_id, reason_code, message}]}`
（itinerary_builder.py:243-267 `_hard_validation_summary`），经 `build_itinerary`
工具写入 AgentState（tools.py:580-586：`candidate_itinerary` / `plan_evaluation` /
`decision_summaries` / `goal`；state.py:301）。

**消费端只有两处，均不改变分支**：
1. **提问文本**：`_failure_detail` 读 `plan_evaluation.failures[*].message` 拼进
   ASK_USER 问题（graph.py:404-424），只读 message，不读 status，不改分支。
2. **分类旁路**：`_act_node` 从观测时点的 `plan_evaluation` 提取 `reason_codes`
   喂给 `classify_failure(ok=True, validation_reason_codes=...)`
   （graph.py:692-706；failure_policy.py:190-204）。这是硬校验失败唯一能影响
   恢复路径的通道——但它来自观测旁路，**不来自决策器对 state 的读取**。

**实测反例**（Phase-E0/01-fact-verification.md S1/S2）：
- S1：硬校验 PASS + 明显低质量 → 无质量信号，照常 EMITTED。
- S2：硬校验 FAIL（NEEDS_REPAIR）→ 结构门放行 → 仍 EMITTED。

## 3. 发射判定（P0 修复点）

```python
if observation.tool == "validate_itinerary" and observation.ok:
    update["stop_reason"] = "EMITTED"          # graph.py:718-721
```

- 判据 = 结构门通过（`StructuralFeasibilityGate`，feasibility_gate.py:29-68，
  仅 4 项检查：wire 重构、无 days、日期逆序、活动 end<=start）。
- **不读取** `plan_evaluation`（status/failures/quality 均不参与）。
- 结构门**故意**窄于硬校验（feasibility_gate.py:6-10 自述），因此 S2 是
  “检查顺序的意外”，不是任何规则裁决的结果。

## 4. 双决策器与模式不对称

| 维度 | AskingDecider（graph.py:167-485） | StructuredOutputDecider（graph.py:518-622） |
|---|---|---|
| 构造 | 无 `STRUCTURED_MODEL_*` 时默认（factory.py:144-167） | 配置后启用，LLM 失败降级 AskingDecider |
| 失败恢复 | D-2 瞬态重试 / D-3 用户调整 / D-4 重复护栏（读 failure memory） | **读不到** failure memory；prompt（graph.py:600-622）无任何评估/失败信息 |
| Evaluation | 决策分支从不读 `plan_evaluation`（graph.py:177-361） | prompt 不含 `plan_evaluation` |
| 发射 | 确定性：validate 通过即交给门 | 无 emit 工具，门仍是唯一发射点 |

结论：**D-2/D-3/D-4 只活在 AskingDecider 路径**；LLM 路径对评估与失败完全失明
（模式不对称，Phase-D0 遗留）。

## 5. 失败分类（Failure 通道，现状）

- `classify_failure`（failure_policy.py:164-260）：结构化证据优先——校验 reason
  codes → CAPABILITY_MISSING → PLANNING_INFEASIBLE（按 conflict codes 细分）→
  瞬态码 → CANDIDATE_EMPTY → 用户输入码 → INTERNAL。
- `advance_failure_memory`（failure_policy.py:272-290）：同签名连续计数，成功/换
  签名则重置。
- `FAILURE_REPEAT_BUDGET`（failure_policy.py:304-312）：除 TRANSIENT（3）外全为 0
  ——确定性拒绝的第二次尝试信息量为零。
- `escalate_duplicate`（failure_policy.py:344-374）：同一动作+未解失败+超预算 →
  ASK_USER（`USER_OWNED_KINDS`，failure_policy.py:325-327）或 STOPPED
  （`_STOPS_NOT_ASKS`：TRANSIENT/INTERNAL/CAPABILITY_MISSING）。

## 6. REPLAN 路径现状（重新审计）

**Agent 侧 REPLAN（唯一真实闭环）**：
`ask_user → WAITING_USER → checkpoint → AGENT_RESUME（agent_processor.py:234-320）
→ update_constraints（D-3 解析用户调整，tools.py:142-253）→ 失败记忆清零
（tools.py:235-238）→ 重新 build`。
- REPLAN 策略名：`strategy="REPLAN"`（graph.py:207、233）。
- 用户是唯一可以改确认约束的实体；Agent 从不自主改约束（evidence-match 规则，
  tools.py:118-135）。

**MQ 侧 REPLAN（绕过 Agent）**：`process_planning_replan`（processor.py:116-147）
→ `LocalReplanningProvider`（确定性局部重规划），产物走 `_outcome_event`
（processor.py:238-294）——评分版 `PlanEvaluation` 只在此路径生成
（processor.py:280），与 Agent 状态无关。**Phase E 不改此路径**（无新复杂度）。

## 7. 结论：唯一核心断点

```
Agent ──build──▶ 确定性规划管线 ──▶ Itinerary
                                        │
                                        ▼
                                  Evaluation（plan_evaluation 已进 state ✓）
                                        │
                                        ▼
                             ✗ 没有 Evaluation → Next Decision 分支 ✗
                                        │
                        （唯一出口：结构门 EMITTED，graph.py:718-721）
```

- **Itinerary → Evaluation → AgentState** 已通（C-3）。
- **Evaluation → Next Agent Decision 缺失**：质量信号不参与决策、硬校验 FAIL
  可随结构门放行（S2）、LLM 决策器对评估失明。
- 用户判断正确：项目是 **Agentic Workflow，核心缺 Planning Reflection Loop**。

## 8. 修复边界（Phase E 不变式）

- 不删 LangGraph、不动态创建 Tool、不删 Guardrail、不引入 Multi-Agent。
- EMITTED 保持确定性代码（永远不是 LLM 工具）。
- 确认约束不可变：质量/硬校验失败只能 ask，不能自主改约束。
- 无 wire-contract / schema 变更；checkpoint 保持 v2 兼容。
- 预算保持有界：MAX_STEPS=8 等不动，Reflection Budget 新增且有上限。
