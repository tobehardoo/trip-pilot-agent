# Phase D-2 Implementation Notes — Transient Failure Recovery

一刀一验收 · 实施记录（提交前写定）。

## 改动清单（生产 2 文件，最小范围）

| 文件 | 改动 |
|---|---|
| `agent/failure_policy.py` | `_TRANSIENT_CODES` 增补生产前缀码 `PROVIDER_TIMEOUT` / `PROVIDER_RATE_LIMITED` / `PROVIDER_QUOTA_EXHAUSTED`（Fact B 前置缺陷修正；`PROVIDER_ERROR` 有意保持 INTERNAL） |
| `agent/graph.py` | `AskingDecider` 新增 TRANSIENT 分支（attempts≤1 → 一次重试；attempts≥2 → ask_user 出口；通知后的回复 = 用户授权再试一次）；策略标签 `RETRY` 进入 `DECISION_STRATEGIES` 与 `DECISION_SCHEMA` enum（LLM 内部契约，非 wire） |

未触碰：tools.py（边界已保全结构化错误）、state.py（零新字段）、
checkpoint version（保持 2）、provider 重试（providers/retry.py 原样）、
wire contract、planning semantics。

## 验收矩阵（§三十四）实测

| 场景 | 测试 | 结果 |
|---|---|---|
| A transient→retry→EMITTED | `test_transient_failure_retries_once_then_emits` | builds=[FAIL,OK]，策略序 ["DIRECT","RETRY"]，attempts 峰值 1，EMITTED，memory 清零 ✅ |
| B transient×N 有界 | `test_persistent_transient_failure_is_bounded_and_exits_to_the_user` | 首轮 builds==2 → WAITING_USER；resume 后 +1 → 再 WAITING_USER；attempts 2→3 连续计数；从不 CEILING ✅ |
| B' quota 有界 | `test_quota_exhaustion_is_bounded_the_same_way` | builds==2 → WAITING_USER（§二十六 无循环证明）✅ |
| C transient vs deterministic | `test_transient_retries_but_deterministic_failure_does_not` | builds 2 vs 1 ✅ |
| D 约束不变 | `test_retry_preserves_the_confirmed_slots_exactly` + `test_retry_never_touches_the_user_constraints` | slots 对象全等；confirmed_values 不变；无 OVERRIDE/REJECTED；must_visit/fixed_schedules 未被发明 ✅ |
| E memory 清零 | `test_successful_retry_clears_failure_memory_in_the_checkpoint` | 真实 checkpoint：COMPLETED + kind/signature None + attempts==0 ✅ |
| F 失败种类改变 | `test_retry_stops_when_the_failure_kind_changes` | 恰好一次重试 → USER_CONSTRAINT（新签名，attempts 复位 1）→ 既有 ask_user ✅ |
| 分类前置修正 | `test_production_transient_codes_classify_as_transient` + `test_provider_error_stays_internal` | 3 个生产前缀码 → TRANSIENT；PROVIDER_ERROR → INTERNAL ✅ |
| checkpoint（§二十四） | 折叠于场景 B/E | attempts 跨 checkpoint 续计（2→3，不归零、不双计）；每 build 恰好分类一次 ✅ |

## 观测性（§二十七）

- 重试决策带 `strategy="RETRY"`（进入 checkpoint state）+ thought；
- 观测轨迹可见 `build_itinerary FAILED(PROVIDER_*) → build_itinerary OK`
  序列（step 记录 TOOL_OBSERVATION 含 error_code）；
- 零新增 wire 字段；AgentAskUserEvent / AgentCompletedEvent /
  Itinerary / PlanningResult 形状不变（WIRE: UNCHANGED）。

## 回归门

- pytest：**2013 passed / 42 skipped**（D-1 基线 2003 + 本刀 10；basetemp
  规避既知 Windows Temp ACL 环境问题，非代码回归）
- simulate_planning_v2：**34/34 通过，exit 0**
- ruff：改动文件 **All checks passed**（全仓存在 6 个既存 E501 于
  `tests/test_daily_skeleton_provider.py` —— HEAD 上既有，不属本刀，不顺手修）

## 记录的既有限界 / FOLLOW-UP（本刀不修）

1. 四个观测工具把 provider 失败包成 `ok=True + data.error`
   （tools.py:326,346）—— 这类失败从不进入失败分类器；重试主体是
   build_itinerary，观测工具的失败呈现留待单独评审。
2. `ok=True 但硬验证失败` 的 BuiltItinerary（validation reason 如
   MUST_VISIT_PLACE_MISSING）在 decider 中没有 ask 出口 —— Test F 因此用
   同 FailureKind 的生产路径（PLANNING_INFEASIBLE + MUST_VISIT_UNAVAILABLE）
   证明种类转换。
3. WAITING_USER 出口后的"用户授权再试"循环受 D-4 重复失败升级策略接管
   （每次重试均需用户新回复驱动，自动重试门槛 `attempts<=1` 永不重开）。

## 成熟度

D-2 完成后：Transient Recovery 落地（Level 3 → 3.5）。
与 D-3（用户驱动 Recovery）并列；same-failure×2 升级留给 D-4。
