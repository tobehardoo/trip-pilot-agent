# Phase E · 03 — State Contract（状态契约）

**原则**：沿用 Phase-E0 Q3/Q4 判定——**扩展现有载体，不新增模型、不新增独立字段
（唯一例外：反射预算计数器）**。

---

## 1. `plan_evaluation`（既有载体，扩展 quality 子结构）

```jsonc
// AgentState.plan_evaluation（state.py:301），checkpoint v2 round-trip 已有
{
  "status": "VERIFIED | UNVERIFIED | NEEDS_REPAIR",   // 既有：硬校验状态
  "failures": [                                        // 既有：硬校验失败
    { "rule_id": "MUST_VISIT_COVERAGE",
      "reason_code": "MUST_VISIT_PLACE_MISSING",
      "message": "必去地点未被覆盖" }
  ],
  "quality": {                                         // 新增（仅真实后端路径）
    "verdict": "GOOD | ACCEPTABLE | POOR",             // >=80 GOOD，>=60 ACCEPTABLE，否则 POOR
    "score": 58,                                       // 0-100，PlanEvaluator.overall_score
    "reasons": ["预算利用率偏高（92%）"]               // top-3 warnings message
  }
}
```

**生产端**：`_hard_validation_summary`（itinerary_builder.py:243-267）内，
`run_validation` 之后追加：

```python
if report.status.value != "NEEDS_REPAIR":        # 硬校验已干净才评质量
    quality = _quality_summary(command, result)   # 复用 get_plan_evaluator().evaluate
    if quality is not None:
        summary["quality"] = quality
```

- `_quality_summary` 任何异常（含 PlanEvaluator 对硬违例的
  `PlanningProviderError`，evaluator.py:71-98）都返回 `None`——**质量是反馈，
  永不阻断**（fail-open）；硬校验本身不变（fail-closed 权威）。
- **Demo 路径**（DemoItineraryBuilder）不产生 feasibility → quality 恒为 None
  （Fact A-7），tools.py:588-595 分支不动。
- **Failure 与 Quality 分离**：quality 永不进入 `failures[]`、永不进入
  `validation_reason_codes`、永不触发 `classify_failure`（T5 断言）。

**消费端**：
- `reflect_on_evaluation`（新模块 reflection.py，纯函数）只读
  `status` + `failures`（Failure 通道）。
- LLM prompt 注入 `status/failures/quality` 全文（04-decision-contract.md）。
- build 观测摘要携带质量注记（tools.py build summary 追加
  `; quality {score} ({verdict})`）。

## 2. 新增字段：`reflection_attempts: int = 0`

```python
# state.py AgentState（置于 failure_attempts 之后）
reflection_attempts: int = 0
```

- **写入**：
  - `_act_node`：build 观测且裁决 REJECT_HARD → `state.reflection_attempts + 1`
    （graph.py 改）。
  - `update_constraints`：应用用户约束变更时清零（tools.py:235-238 同块追加
    `partial["reflection_attempts"] = 0`）。
- **读取**：
  - `_decide_node` Case D 短路：`reflection_budget_exhausted(state)`（纯函数）。
  - LLM prompt“反思预算”区段。
- **checkpoint**：`agent_state_to_dict` / `agent_state_from_dict` 各加一行
  （state.py:360-477），默认 0。

## 3. Checkpoint 兼容性（保持 v2，不 bump）

- `CHECKPOINT_VERSION = 2`（state.py:333），`_READABLE_VERSIONS = (1, 2)`。
- **新读旧**：旧 v2 检查点无 `reflection_attempts` 键 → `data.get(...)` 默认 0 ✓。
- **旧读新**：旧版 `agent_state_from_dict` 逐字段构造，忽略未知键 → 新检查点
  中 `reflection_attempts` 被丢弃、默认为 0 ✓（无 schema 破坏）。
- `plan_evaluation["quality"]` 随既有 `_json_safe`（state.py:408）原样 round-trip，
  无迁移。

## 4. 变更文件清单

| 文件 | 变更 |
|---|---|
| `agent/state.py` | +`reflection_attempts` 字段与 round-trip |
| `agent/reflection.py` | **新增**：`REFLECTION_MAX_ATTEMPTS`、`reflect_on_evaluation`、`reflection_budget_exhausted` |
| `agent/itinerary_builder.py` | `_hard_validation_summary` 追加 quality 子结构；新增 `_quality_summary` |
| `agent/tools.py` | `update_constraints` 重置 `reflection_attempts`；build summary 质量注记 |
| `agent/graph.py` | `_act_node` 门禁 + 计数；`_decide_node` Case D；AskingDecider 反射分支；LLM prompt 注入 |
