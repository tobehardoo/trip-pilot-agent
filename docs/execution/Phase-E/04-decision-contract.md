# Phase E · 04 — Decision Contract（决策契约）

**原则**：Reflection Decision 是确定性代码；LLM 只被注入评估上下文（决策输入
CURRENT STATE），永不拥有发射/反射裁决权。决策输出词汇不新增
（EMITTED / ASK_USER / ANSWERED / STOPPED / WAITING_USER 均既有）。

---

## 1. 决策输入：CURRENT STATE 结构（LLM prompt 注入）

`StructuredOutputDecider._prompt`（graph.py:600-622）在既有区段后追加两个区段，
结构稳定（T7 断言区段名）：

```
[既有区段：角色/规则/策略枚举/偏好/必填约束/已确认约束/最近用户消息/可用工具/最近观测]

当前行程评估 (PLAN EVALUATION):
- status: NEEDS_REPAIR
- failures:
  - MUST_VISIT_COVERAGE / MUST_VISIT_PLACE_MISSING: 必去地点未被覆盖
- quality: {"verdict": "POOR", "score": 58, "reasons": ["预算利用率偏高（92%）"]}
  （无评估时渲染 "(无)"）

反思预算 (REFLECTION BUDGET):
- attempts: 2 / 3
- 规则：若当前行程存在未解决硬校验失败（NEEDS_REPAIR），不得以完成姿态结束会话，
  必须调用 ask_user 请用户调整约束（必去地点/日期/预算）或调用 build_itinerary
  重新规划；反复失败时不得无限重试（达到上限将强制停止）。
```

- 无 `plan_evaluation` 时区段渲染 `"(无)"`，prompt 结构不变（兼容 demo 路径）。
- `quality` 仅在存在时渲染；缺失不补默认值。

## 2. 决策输出映射（Reflection Decision 的落地）

| Case | 判定位置 | 输出 | 退出 |
|---|---|---|---|
| A（ACCEPT） | `_act_node` EMITTED 门（graph.py:718-721 改判） | `stop_reason="EMITTED"` | AGENT_COMPLETED（agent_processor.py:420） |
| B（REJECT_HARD） | `AskingDecider.decide` 反射分支（build 成功后、validate 前） | D-4 护栏 → `ask_user`（模板按 failure kind）或 STOPPED | WAITING_USER / STOPPED |
| B'（REJECT_HARD，LLM 路径） | `_act_node` 门禁（LLM 若调 validate） | 不设 EMITTED，循环继续；prompt 已告知 | 由 LLM 决策，受 Case D 约束 |
| C（quality POOR） | 门禁**不**阻塞（ACCEPT） | build 观测摘要质量注记 + prompt 注入 | EMITTED 照常 |
| D（预算耗尽） | `_decide_node` 短路（graph.py:652-664 前） | `answer="当前约束下反复尝试仍无法生成可接受的行程，请调整必去地点、日期或预算后重新开始。"`，不调用决策器 | ANSWERED（_finish_node graph.py:733-736） |

## 3. AskingDecider 反射分支（Case B 的具体实现位置）

插入点：graph.py:177-361 中 `builds and builds[-1].ok` 的分支族之后、
`state.candidate_itinerary is None`（build 分支）之前：

```python
if builds and builds[-1].ok and reflect_on_evaluation(state.plan_evaluation) == "REJECT_HARD":
    if state.observations and state.observations[-1].tool == "ask_user":
        # 用户刚答复但无可用调整 → 诚实结束，不重复同问（防对话级死循环）
        return Decision(thought="...", answer="当前约束下无法生成可接受的行程，请调整约束后再试。", strategy="CLARIFY")
    guarded = self._duplicate_guard(state, action_tool="build_itinerary",
                                    detail=self._failure_detail(state, "build_itinerary"))
    if guarded is not None:
        return guarded
    return Decision(thought="evaluation rejected the draft; ask the user to adjust",
                    call=ToolCall("ask_user", {"question": _REFLECTION_QUESTION.format(detail=...)}),
                    strategy="REPLAN")
```

要点：
- **不重复同问**：用户答复不含调整 → 结束（与现状 D-4 的“答复无调整即结束”
  语义一致），不会 ask→validate→ask 死循环。
- **跳过注定放行的 validate**：REJECT_HARD 的候选不再走结构门
  （结构门救不了硬校验失败），省一步且语义更直白。
- D-4 护栏在预算 0（USER_CONSTRAINT/FEASIBILITY）下首次即 ASK_USER——
  确定性拒绝第二次尝试信息量为零（failure_policy.py:304-312）。

## 4. `_act_node` 改判（P0 核心）

```python
evaluation = update.get("plan_evaluation", state.plan_evaluation)
# 反射计数：仅 build 观测、且评估否决时 +1（validate 不改变评估，不计）
if observation.tool == "build_itinerary" and observation.ok:
    if reflect_on_evaluation(evaluation) == "REJECT_HARD":
        update["reflection_attempts"] = state.reflection_attempts + 1
# EMITTED 门：结构门通过 + 评估 ACCEPT 才发射（S2 修复）
if observation.tool == "validate_itinerary" and observation.ok:
    if reflect_on_evaluation(update.get("plan_evaluation", state.plan_evaluation)) == "ACCEPT":
        update["stop_reason"] = "EMITTED"
```

- 无 `plan_evaluation`（demo 路径 / 旧候选）→ `reflect_on_evaluation` 返回
  ACCEPT → 行为与 HEAD 完全一致（向后兼容）。

## 5. `_decide_node` Case D 短路

```python
async def _decide_node(self, state):
    if state.stop_reason is not None:
        return {}
    if state.steps >= self.max_steps:
        return {"stop_reason": STOP_CEILING}
    if reflection_budget_exhausted(state):          # 新增：两种决策器统一生效
        return {"steps": state.steps + 1, "answer": _REFLECTION_EXHAUSTED_ANSWER,
                "pending_call": None, "strategy": None}
    decision = await self.decider.decide(state)
    ...
```

`reflection_budget_exhausted(state)`（reflection.py 纯函数）：
`state.reflection_attempts >= REFLECTION_MAX_ATTEMPTS and
 reflect_on_evaluation(state.plan_evaluation) == "REJECT_HARD"`。

## 6. 不变式核对

- ✅ EMITTED 确定性代码，无 emit 工具。
- ✅ 用户是唯一可改确认约束的实体（evidence-match，tools.py:118-135）。
- ✅ 质量不阻塞、不冒充失败（Case C 只反馈）。
- ✅ 预算有界：同约束上下文 ≤3 个被否决候选；MAX_STEPS 等原样兜底。
- ✅ 不删 LangGraph / 不动态建 Tool / 不删 Guardrail / 无 Multi-Agent。
