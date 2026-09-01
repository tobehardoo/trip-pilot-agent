# D-1 实施记录 — Failure Classification（已落地）

> 2026-08-31 · 单 commit。Scope：agent/failure_policy.py（新）、agent/state.py（+3 字段）、
> agent/graph.py（_act_node 分类接线）、agent/tools.py（provider 错误结构化保全）、
> tests/agent/test_failure_policy.py（新）。

## Implementation

- `agent/failure_policy.py`（新，纯函数模块）：
  - `FailureKind` 七类：TRANSIENT / CAPABILITY_MISSING / USER_CONSTRAINT / CANDIDATE_EMPTY / FEASIBILITY / VALIDATION / INTERNAL；
  - `classify_failure(tool, ok, error_code, data, validation_reason_codes)`：按**结构化证据**分类
    （error code → conflict codes → validation reason codes），禁止字符串猜测；
  - `failure_signature`：`{kind}:{tool}:{detail}`，detail = 具体 error code /
    conflict code / 校验 reason code（确定性、有界、无时间戳无 repr）；
  - `advance_failure_memory`：连续相同签名计数（同签名 +1，异签名归 1，成功清零）。
- `agent/state.py`：`failure_kind / failure_signature / failure_attempts` 三字段；
  checkpoint 读写覆盖；**版本保持 2**——新增键经 `data.get(...)` 默认读取，
  pre-D-1 v2 checkpoint 可直接加载（代码证据：tests 的
  `test_pre_d1_checkpoint_loads_with_empty_failure_memory`）。
- `agent/graph.py _act_node`：唯一分类入口——observation 合并后调用 classify +
  advance，写入 failure memory。**不改变任何出口决策**（EMITTED/WAITING_USER/
  STOPPED/CEILING 分支原样）。
- `agent/tools.py _build_itinerary`：`PlanningProviderError` 不再被 invoke 吞为
  TOOL_ERROR——handler 保全 `details.error_code/category` 与 `PlanningInfeasibleError`
  的 `conflict_codes`（进 data），使分类器拿到结构化证据。

## Verification

- pytest：**1997 passed / 42 skipped**（新增 18 个 failure-policy 测试 + 9 个接线断言）；
- Counterfactual：Timeout→TRANSIENT vs ValueError(未捕获)→INTERNAL ✅；
  MUST_VISIT_PLACE_MISSING→USER_CONSTRAINT vs INSUFFICIENT_AMAP_POIS→CANDIDATE_EMPTY ✅；
  FIXED_SCHEDULE_OVERLAP→FEASIBILITY vs 未识别校验原因→VALIDATION ✅；
- simulate_planning_v2：34/34（exit 0）；
- ruff：PASS；
- Behavior Change：**NONE**（failure memory 只记录；决策分支零改动——全部既有出口语义
  测试原样通过）；
- Recovery：UNCHANGED；
- wire/DB：unchanged；
- Checkpoint：version 2 不变（additive 字段，v1/v2 均可读，代码证据在测试中）；
- Scope：CLEAN（并行会话的 docs/execution/2026-08-31-phase-b/* 未触碰）。

## TOOL_ERROR 边界（D-2 前置依赖，按 D-0 §八记录）

handler 未捕获的异常仍被 invoke 吞为 TOOL_ERROR → 分类为 INTERNAL（不猜测）。
要在观测层区分 Timeout vs 编程错误，需 handler 保全异常类别——规划路径已做
（PlanningProviderError 结构化保全）；其余工具 handler 的异常保全列为 **D-2 前置依赖**。

## Recovery 候选映射（供 D-2/D-3/D-4 消费，本刀不执行）

| FailureKind | Recovery 候选 |
|---|---|
| TRANSIENT | R1 Retry（有界）→ 耗尽后 ASK |
| CAPABILITY_MISSING | R2 Degrade（现状）/移交 |
| USER_CONSTRAINT | R4 Ask User（结构化选项） |
| CANDIDATE_EMPTY | R3 Replan（仅放宽 provider 自由度）→ ASK |
| FEASIBILITY | R4 Ask User / worker 修复循环 |
| VALIDATION | R4 Ask User（选项化）|
| INTERNAL | R5 Stop |
