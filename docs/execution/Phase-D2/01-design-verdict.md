# Phase D-2 Design Verdict — Transient Failure Recovery

一刀一验收 · 本文档在改动任何生产代码之前写定，全部结论锚定 file:line。

## 〇、Fact verification 结果

### Fact A — Provider 重试已经在哪里结束

生产重试链（本刀不动它）：

```text
AmapMapProvider / AmapRouteProvider          providers/map.py, providers/route.py
  → RetryingMapProvider / RetryingRouteProvider   providers/retry.py:44,64
      _RetryExecutor.execute                      providers/retry.py:107
      · max_attempts=3，指数退避+jitter，max_elapsed 5s
      · 仅对 retryable 且 category ∈ {RATE_LIMITED, TIMEOUT,
        NETWORK_ERROR, PROVIDER_UNAVAILABLE, MALFORMED_RESPONSE} 重试
        (providers/retry.py:85-93)
      · 耗尽后返回 ProviderFailure(retry_exhausted=True)      (retry.py:124-135)
  → PlanningProviderError.from_failure            providers/errors.py:102
      ProviderFailureDetails 结构化保全:
      category / error_code / retry_count / retry_exhausted / safe_message
  → agent 工具边界                                 agent/tools.py:541-556
      error_code = details.error_code or details.category.value
```

结论：到达 Agent 的错误**已经是结构化的**，不存在 opaque TOOL_ERROR。
`_build_itinerary` 自 D-1 起显式保全 `error_code`（tools.py:541-556）。

### Fact B — D-1 的 TRANSIENT 输入是否真的能到达 classify_failure

生产抛出的真实错误码（`ProviderErrorCode` Literal，providers/map.py:76-88）：

| 生产错误码 | 来源 | retryable | 命中 D-1 `_TRANSIENT_CODES`? |
|---|---|---|---|
| `PROVIDER_TIMEOUT` | httpx.TimeoutException (map.py:288) | True | ❌ **不命中 → 误分 INTERNAL** |
| `PROVIDER_UNAVAILABLE` | httpx.RequestError (map.py:293) | True | ✅ 命中 |
| `PROVIDER_RATE_LIMITED` | AMap infocode RATE_CODES (map.py:436) | True | ❌ **不命中** |
| `PROVIDER_QUOTA_EXHAUSTED` | AMap infocode QUOTA_CODES (map.py:440) | **False** | ❌ **不命中** |
| `PROVIDER_ERROR` | 兜底 (map.py:297,465) | False | 正确地不命中（INVALID_REQUEST/ADAPTER 类，属 INTERNAL） |

**发现（D-2 前置缺陷，本刀必须修）**：D-1 的 `_TRANSIENT_CODES`
（agent/failure_policy.py:36-45）收录的是裸码（`TIMEOUT`/`RATE_LIMITED`/
`QUOTA_EXCEEDED`…），而生产边界保留的是 `details.error_code` —— 带前缀形式。
真实超时/限流会被误分为 INTERNAL，D-2 对真实链路将是 no-op。

修复：`_TRANSIENT_CODES` 增补 `PROVIDER_TIMEOUT` / `PROVIDER_RATE_LIMITED` /
`PROVIDER_QUOTA_EXCEEDED`（纯分类表扩充，零行为变更面=分类正确性）。
`PROVIDER_ERROR` **有意不加**：其类别是 INVALID_REQUEST / PROVIDER_ADAPTER_ERROR、
retryable=False，不是瞬态。

旁证（记录，不在本刀修）：四个观测工具（search_place 等）把 provider 失败包成
`ToolResult(ok=True, data={"error": code})`（agent/tools.py:326,346）——
这些失败从不进入失败分类器。重试主体是 build_itinerary（§九 的裁定对象），
观测工具的失败掩盖记为 FOLLOW-UP。

### Fact C — AskingDecider 当前如何处理 TRANSIENT

代码证明（agent/graph.py:150-198）：`required_hard` 分支只有两个失败出口 ——
`CAPABILITY_MISSING`（移交）与 `PLANNING_INFEASIBLE ∧ failure_kind ==
USER_CONSTRAINT`（D-3 分支）。TRANSIENT 失败两者皆不命中，落到
`if state.candidate_itinerary is None: build_itinerary`（graph.py:193-198）
—— **每个 decide 周期无条件重建**，直到 `steps >= MAX_STEPS=8`
（graph.py:484-485）→ `CEILING_REACHED`。即现状：无界重建烧满步数预算后撞顶。

### Fact D — 如何表达"重试一次"

复用现有 decide→act 循环：重试就是 decider 再返回一次
`ToolCall("build_itinerary")` —— 与现状的差别仅在于**有界**：
`failure_attempts == 1` → 重试一次；`>= 2` → 不再自动重试，走出口。
不新增 retry loop / while / Coordinator。

## 一、Design Verdict（§三十 十项裁定）

1. **transient 的生产来源**：`build_itinerary` → `RealItineraryBuilder` →
   `AmapPlanningProvider` → `Retrying*Provider`（provider 层已重试≤2 次）→
   耗尽 → `PlanningProviderError` → tools.py 边界 → 前缀错误码 →
   `classify_failure`。前置修正：`_TRANSIENT_CODES` 补生产前缀码（Fact B）。

2. **retry action 复用哪个现有 action**：`ToolCall("build_itinerary")`，
   即现有 build 动作本身；策略标签新增 `RETRY`（graph.py
   DECISION_STRATEGIES + DECISION_SCHEMA enum —— LLM 结构化输出内部契约，
   非 wire）。

3. **attempt 由哪里读取**：`AskingDecider.decide` 读
   `state.failure_kind` / `state.failure_attempts`（D-1 记忆，已随
   checkpoint v2 序列化，state.py:410-412,474-476）。

4. **attempt 由哪里更新**：不变 —— `_act_node` 在每个非 ask_user 观测后经
   `advance_failure_memory` 推进（graph.py:529-546）。每个 build 观测恰好
   分类一次，无双重递增；成功观测自动清零（failure_policy.py:274-275）。

5. **第一次失败后的出口**：`attempts <= 1` → decider 返回 RETRY
   （重建一次，约束不动）。

6. **第二次失败后的出口**：`attempts >= 2` → `ask_user` → 现有
   WAITING_USER 语义（tools.py:297-310），不新增终态。问题文本含错误码并
   声明已自动重试。resume 时：先经 D-3 `_extract_adjustment`
   （约束调整优先）；无调整的回复 = 用户对"再试"通知的应答 = 授权立即再试
   一次（一次普通 build 动作）。此后每次重试都必须由新的用户回复驱动，
   自动重试门槛 `attempts <= 1` 永不重开；重复失败的升级策略留给 D-4。

7. **成功后如何清 memory**：零新增代码 —— 成功观测经
   `advance_failure_memory(None, "")` 自动复位 (None, None, 0)；测试断言
   EMITTED 后 `failure_kind is None ∧ failure_attempts == 0`。

8. **checkpoint 是否需要变化**：不需要。failure 三字段已在 checkpoint v2
   序列化/恢复（state.py:410-412, 474-476）；resume 的 `replace(...)`
   （agent_processor.py:291-303）不触碰 failure 记忆，steps 归零是既有的
   per-turn 预算语义。版本保持 2，不 bump。

9. **是否需要修改 tools.py**：不需要。边界已保全结构化错误。

10. **是否需要修改 State**：不加字段。failure_kind/signature/attempts
    （D-1）与 strategy（P3.3）已存在。

## 二、生产文件改动清单（最小范围）

| 文件 | 改动 | 理由 |
|---|---|---|
| `agent/failure_policy.py` | `_TRANSIENT_CODES` 增补 3 个生产前缀码 | Fact B 前置缺陷：不修则 D-2 对真实链路 no-op |
| `agent/graph.py` | AskingDecider 增加 TRANSIENT 分支；`RETRY` 策略标签 | 本刀主体 |

Scope 说明：`failure_policy.py` 不在指令"原则上允许"三文件之列，但它就是
D-1 建立的分类器本身、属 agent 层、纯函数、零 wire 面。裁定：作为 D-2
前置修正纳入本刀，并在 Verdict 报告中显式申报。

## 三、QUOTA_EXCEEDED 特别记录（§二十六）

Provider 层事实：QUOTA 类别 `retryable=False`（map.py:440），且不在
`_RetryExecutor` 可重试集合（retry.py:85-93）—— 配额耗尽在 provider 层
从未被重试，到达 Agent 时是首次失败。D-1 已裁定 QUOTA_EXCEEDED ∈
TRANSIENT；D-2 沿用统一一次重试（有界、可观测），测试 B 证明 quota/timeout
均不会形成循环。若配额未恢复，第二次失败即进入 WAITING_USER 出口 ——
不试图"绕过"配额，也不建议用户改约束。

## 四、验收映射（§三十四）

| 场景 | 构造 | 断言 |
|---|---|---|
| A | PROVIDER_TIMEOUT ×1 → success | builds==2, EMITTED, attempts==0 |
| B | PROVIDER_TIMEOUT 永远失败 | 首轮 builds==2 → WAITING_USER；resume 后再 +1 次 → 再次 WAITING_USER；永不 CEILING |
| C | NETWORK_ERROR vs MUST_VISIT_UNAVAILABLE | builds 2 vs 1（transient 重试、deterministic 不重试） |
| D | TRANSIENT → RETRY → success | confirmed slots 全等（含 budget/must_visit/date/fixed_schedules），无 OVERRIDE/REJECTED |
| E | TRANSIENT → RETRY → success（真实 checkpoint） | checkpoint 内 failure_kind/signature 为 None、attempts==0 |
| F | PROVIDER_TIMEOUT → PlanningInfeasibleError(MUST_VISIT_UNAVAILABLE) | builds==2（恰好一次重试）→ USER_CONSTRAINT → 既有 ask_user |

构造说明（Test F）：指令示例码 `MUST_VISIT_PLACE_MISSING` 是硬验证 reason
码，只出现在 ok=True 的 BuiltItinerary 观测（tools.py:556-580）——现有
decider 对"ok 但硬验证失败"没有 ask 出口（既有限界，D-2 不扩）。故 Test F
用同一 FailureKind（USER_CONSTRAINT）的生产路径 `PLANNING_INFEASIBLE +
MUST_VISIT_UNAVAILABLE` 证明"新失败种类接管决策"。ok-build-验证失败无
ask 出口记为 FOLLOW-UP。
