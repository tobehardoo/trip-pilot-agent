# Phase D-4 Design Verdict — Duplicate Failure Guard

一刀一验收 · 本文档在改动任何生产代码之前写定，全部结论锚定 file:line 或实测输出。
基线代码：`803a421 feat (D-2)`。本文不复用 D-0 的任何结论，全部事实重读/重跑。

---

## 〇、Fact Verification 结果

### Fact A — failure memory 当前真实更新规则

三个字段（`agent/state.py:307-309`）：`failure_kind` / `failure_signature` /
`failure_attempts`。

**唯一写入点**：`agent/graph.py:570-587`（`_act_node`，每条观测之后）。

```text
ToolObservation
  → classify_failure(tool, ok, error_code, data, validation_reason_codes)   graph.py:570-576
      failure_policy.py:162-258   纯函数，结构化证据驱动，signature = "KIND:tool:detail"
  → advance_failure_memory(...)                                             graph.py:577-587
      failure_policy.py:270-288
        · kind is None / 空 signature   → (None, None, 0)     成功即清零
        · signature == current          → attempts + 1        同签名累加
        · signature != current          → (kind, sig, 1)      异签名归 1
```

| 问题 | 代码事实 |
|---|---|
| 同 signature attempts 如何变 | `+1`（failure_policy.py:286-287） |
| 异 signature 是否归 1 | 是，`return kind, signature, 1`（:288） |
| 成功如何清零 | `advance_failure_memory` 收到 `(None, "")` → `(None, None, 0)`（:284-285） |
| ask_user 是否错误清零 | **不清零**。`graph.py:563-564` 在分类之前 `return update`，memory 完整跨 ask 存活（D-3 语义，必须保持） |
| constraint update 何时清零 | `tools.py:229-238`：`applied` 非空 **或** 有 rejection → 同时清 `candidate_itinerary` 与三字段。`NO_VALUES`（:227）返回空 partial → **不清零** |
| checkpoint | 三字段完整往返（state.py:410-412 / 474-476），`CHECKPOINT_VERSION = 2`（:333） |

结论：**`failure_attempts` 已经是「同一动作 × 同一失败 × 无有意义变化」的连续计数**。
任何 meaningful change（约束变更被 apply、任一工具成功）都会把它打回 0，
任何不同失败都会把它打回 1。这正是 D-4 需要的计数器，无需新增字段。

### Fact B — 真实重复循环入口（实测，非推断）

探针：真实 `AgentLoop` + 真实 `AskingDecider` + 真实 `ToolRegistry`，
slot 全 CONFIRMED，builder 以固定方式永久失败。

| # | 注入 | 实测 stop | steps | 观测序列 | kind / signature / attempts |
|---|---|---|---|---|---|
| L1 | `PlanningInfeasibleError(INSUFFICIENT_DAY_CAPACITY)` | **CEILING_REACHED** | **8** | build ×8 全败 | `FEASIBILITY` / `FEASIBILITY:build_itinerary:INSUFFICIENT_DAY_CAPACITY` / **8** |
| L1b | 任意 `RuntimeError`（→ opaque `TOOL_ERROR`） | **CEILING_REACHED** | **8** | build ×8 全败 | `INTERNAL` / `INTERNAL:build_itinerary:TOOL_ERROR` / **8** |
| L1c | `PLANNING_INFEASIBLE(MUST_VISIT_UNAVAILABLE)` | WAITING_USER | 2 | build 败 → ask | `USER_CONSTRAINT` / …/ **1** ✅ D-3 已闭合 |
| L2 | builder 成功 + 结构守门永久 blocked | **CEILING_REACHED** | **8** | build 成 → validate ×7 全败 | `FEASIBILITY` / `FEASIBILITY:validate_itinerary` / **7** |
| L4 | `PlanningProviderError("NO_RESULT")` | **CEILING_REACHED** | **8** | build ×8 全败 | `CANDIDATE_EMPTY` / `CANDIDATE_EMPTY:build_itinerary:NO_RESULT` / **8** |
| L5 | 正常链路（对照） | EMITTED | 2 | build 成 → validate 成 | None / None / 0 |

**证明**：CEILING 目前是 L1 / L1b / L2 / L4 的**唯一**出口 —— 这正是 D-4 要退役的职责。

分支表（`graph.py:146-294`，required_hard 链，实测校准）：

| FailureKind | attempts | 当前行为 | 能否机器自旋 | D-2/D-3 是否已限 |
|---|---|---|---|---|
| TRANSIENT | 1 | `build_itinerary` RETRY（:206-211） | 否（单发） | ✅ D-2 |
| TRANSIENT | ≥2 | 末观测是 ask_user → 再 build（:212-217）；否则 ask 公告（:218-231） | 否（每 turn 一次），**但轮次无上界** | ⚠️ 部分 |
| USER_CONSTRAINT | ≥1 | D-3 分支：解析调整 → update_constraints；否则 ask（:159-192） | 否（每次 ask 结束一个 turn） | ✅ D-3 |
| FEASIBILITY | ≥1 | 无分支接住 → 落到 `candidate is None` → **重复 build**（:232-237）；或落到 **重复 validate**（:238-245） | **是 → CEILING** | ❌ |
| VALIDATION | ≥1 | 同上（无映射 reason code → VALIDATION） | **是 → CEILING** | ❌ |
| INTERNAL | ≥1 | 落到重复 build | **是 → CEILING** | ❌ |
| CANDIDATE_EMPTY | ≥1 | 落到重复 build | **是 → CEILING** | ❌ |
| CAPABILITY_MISSING | ≥1 | 直接 answer handoff（:153-158） | 否 | ✅ 既有 |

补充（结构性，未被探针复现）：`update_constraints` 抛 `NO_VALUES` 时
signature 为 `USER_CONSTRAINT:update_constraints:NO_VALUES`，D-3 分支会以同一
`user_message` 重复同一提案 → 同签名自旋。本刀**不**闭合它：Guard 的边界是
「永不否决 `ask_user` / `update_constraints`」（§一.4），把 `update_constraints`
纳入否决范围会让用户的每一次真实调整都有被吞掉的风险，收益（少一次无效工具调用）
与代价（用户证据路径变得不确定）不成比例。记为 §三 已知边界，不属于本刀职责。

### Fact C — 什么叫「没有新信息」

**会解除（strong）**，均已由代码保证：
- `update_constraints` 真正 applied / 记录了 rejection → 三字段清零 + 候选作废（tools.py:229-238）；
- 任一非 ask_user 工具成功 → `advance_failure_memory` 清零（failure_policy.py:284-285）。

**不解除（weak）**：
- ask_user 观测本身（graph.py:563-564 显式豁免）；
- resume、无效回答、无关回答（都不产生成功的非 ask 工具调用）。

因此 D-4 **不需要**「新信息」布尔位：attempts 的归零路径本身就是新信息证明。
这也满足约束「如果 D-3 已清 failure memory，则复用，不得实现第二套 reset」。

### Fact D — CEILING 当前真实职责

只有两处产生 `CEILING_REACHED`：
- `graph.py:525-526` `steps >= max_steps`（`MAX_STEPS = 8`，graph.py:42）
- `graph.py:541-545` 本 turn 工具调用数 ≥ `MAX_TOOL_CALLS = 16`（:43）

按 D-0 的划分，实测（Fact B）表明 CEILING **今天完全在做正常策略的收尾工作**：
L1/L1b/L2/L4 都是「 deterministic 失败 → 重复同一动作 → 撞步骤上限」。
真正的安全保护（模型/工具调用爆炸）在 D-4 之后仍归 CEILING 管。

### Fact E — 出口词表（决定实现形状）

`stop_reason` 的下游映射是封闭集合：
- `agent/persistence.py:33-46`：`WAITING_USER` / `EMITTED` / `ANSWERED` / `CEILING_REACHED` / `LLM_BUDGET_EXHAUSTED`，未知 → `STOPPED`；
- `worker/agent_processor.py:446-460`：`ANSWERED` → 可见 answer；`CEILING_REACHED` → 专属文案；`None|WAITING_USER|EMITTED` → 不发 RUN_FINISHED；**其它一律 `status="STOPPED"` + `_STOP_DEFAULT_MESSAGE`**。
- `AgentRunFinishedPayload.reason_code: AgentErrorCode`（contracts.py:1756, 1840）= `Annotated[str, 1..60]`，**不是 Literal**。

关键事实：`_finish_node`（graph.py:603-606）在 `answer` 为空且 `pending_call` 为空时
**已经**产出 `stop_reason = "STOPPED"`，且已在 worker 默认分支里被映射。

**因此 D-4 的升级只复用既有出口，不新增 stop_reason 字符串**：
- 需要用户行动 → `ask_user` → `WAITING_USER`（与 D-3 同类）；
- 无法由用户挽救 → `Decision(thought=...)`（无 call 无 answer）→ 既有 `"STOPPED"`。
`AgentCompletedEvent` / checkpoint version / wire / DB / Worker 全部零改动。

---

## 一、Design Verdict

### 1. Guard 放在哪里

**放在 `AskingDecider`（agent/graph.py）**，判定逻辑作为纯函数放在
`agent/failure_policy.py`。理由（对齐 §四职责表）：

```text
Tool        → Report      (tools.py 不改)
FailurePolicy → Classify + 本次新增 Judge（纯函数，无 I/O）
State       → Remember    (state.py 不改，不加字段)
Decider     → Decide Recovery + Prevent policy loop
```

不放进 `ToolRegistry`：工具不得决定 recovery policy。
不新增 LangGraph 节点/边：`AskingDecider.decide` 已经是每个动作的决策点，
Guard 是「在发出动作前否决重复动作」，无需拓扑改动。

### 2. Guard 模型（不新增字段）

判定条件（全部来自现有三字段）：

```text
IF  即将发出的动作工具 == failure_signature 中的工具     ← 同一动作
AND failure_attempts > 该 FailureKind 的重复预算          ← 同一失败、已无进展
THEN 升级（ASK_USER / STOPPED），而不是再发这个动作
```

「同一动作」为什么免费：`_failure_signature`（failure_policy.py:149-159）
格式为 `KIND:tool:detail`，工具名是 signature 的第二段，可直接解析，
不需要 `last_recovery_action`。

**§八 举证结论**：`failure_attempts` + signature 的 tool 段足以区分
「策略允许的 retry」与「策略循环」，因此**禁止新增 `last_recovery_action`**。
唯一需要额外预算的是 TRANSIENT（D-2 授权用户回执可再试），用一个常量表达。

### 3. 每 kind 的重复预算与升级

| FailureKind | 预算（允许的连续同签名失败） | 超预算升级 | 依据 |
|---|---|---|---|
| TRANSIENT | 3 | `STOPPED` | D-2 首发+1 retry+2 次用户授权；「无有效授权不得重启 retry cycle」 |
| USER_CONSTRAINT | 0 | `ASK_USER` | D-3 已让位给用户；重复同一 failing action 无意义 |
| FEASIBILITY | 0 | `ASK_USER`（带冲突说明） | 确定性失败：同输入必同输出，第二次 build 零价值 |
| VALIDATION | 0 | `ASK_USER` | 草稿未过闸，用户在环里才能改条件 |
| CANDIDATE_EMPTY | 0 | `ASK_USER`（换目的地/放宽/改关键词） | 同 query 必同空集 |
| INTERNAL | 0 | `STOPPED` | opaque 错误不该无限循环，也不该伪装成功 |
| CAPABILITY_MISSING | 0 | `STOPPED`（既有 handoff answer 优先命中，Guard 属兜底） | 保持现状 |

预算 0 的含义：**第一次失败就不允许再发同一个动作**，而不是「第二次失败才管」。
这与 D-3 现行为一致（`MUST_VISIT_UNAVAILABLE` 第一次失败即 ask，实测 L1c steps=2），
也让 Test G 的阈值收紧到 steps ≤ 3。

### 4. 不得越界

- Guard 只否决「重复失败工具本身」，永不否决 `ask_user` / `update_constraints`
  → 正常 clarification loop 与 D-3 调整路径不受影响（Test F）。
- Guard 不写任何字段：不清 memory、不改 slot、不动 budget/must_visit/日期/fixed_schedules。
- 不引入 `failure_history[]`；State 长度不变。
- 模型驱动路径（`StructuredOutputDecider`）本刀不加 Guard：它的决策不是确定性策略，
  且仍受 `MAX_LLM_CALLS=8` + steps/tools CEILING 双重约束。确定性保证只覆盖
  生产无 Key 链路与 fallback（本刀验收范围），差异记录于 §三 已知边界。

### 5. 诚实升级不变量（实现期发现，已并入模型）

Guard 把 `ASK_USER` 作为四类 kind 的出口，就产生了一个新约束：

> **问出口必须可被回答解除。** 升级问题发出后，下一 turn 若解析不出用户意图，
> Guard 会在同一 memory 上再次命中并原样重复问题 —— 用户永远无法前进。

D-3 的调整解析（`_extract_adjustment`）原先只在 infeasible 分支内生效
（`PLANNING_INFEASIBLE` + `USER_CONSTRAINT`），因此 FEASIBILITY / VALIDATION /
CANDIDATE_EMPTY 三类升级是**不可解除的死锁**。本刀把它上提到 required_hard 链首，
条件改为「末观测是 ask_user 且 kind ∈ `USER_OWNED_KINDS`」，其中
`USER_OWNED_KINDS` 由 §一.3 的两张表派生（预算表 − 只 STOP 不 ASK 的 kinds），
所以「会问用户的 kind」与「回答会被解析的 kind」不可能再各自漂移。

`observations[-1].tool == "ask_user"` 这一条不是防御性冗余：没有它，同一 turn 会把
**自己的**原始消息再解析一遍 → `update_constraints:NO_VALUES` → 一个签名不同的失败
（Guard 不否决 update_constraints）→ 再问 → 自旋到 CEILING。判据与 D-2 的
「回执即授权」用的是同一个既有惯用语（末观测是否为 ask_user）。

代价：D-3 分支收窄为「只在解析不出调整时重复提问」，其全部既有断言不变
（`tests/agent/test_infeasible_resume.py` 与 `test_transient_retry.py` 全绿）。

---

## 二、实现蓝图（最小刀）

| 文件 | 改动 |
|---|---|
| `agent/failure_policy.py` | 新增纯函数 `signature_tool(signature)`、`escalate_duplicate(...) -> "ASK_USER" \| "STOPPED" \| None`；常量表 `FAILURE_REPEAT_BUDGET`（kind→预算）、`MAX_TRANSIENT_SAME_FAILURE_ACTIONS = 3`、由两张表派生的 `USER_OWNED_KINDS` |
| `agent/graph.py` | `AskingDecider` 三个发出动作点前调用 `_duplicate_guard(state, action_tool=…, detail=…)`；新增 kind→用户文案映射（FEASIBILITY / CANDIDATE_EMPTY / VALIDATION / USER_CONSTRAINT）；D-3 的「回答→约束调整」解析从 infeasible 分支上提到 required_hard 链首，对全部 `USER_OWNED_KINDS` 生效（见 §一.5） |
| `tests/agent/test_duplicate_failure_guard.py` | 新建：Counterfactual A–G + 纯函数单元测试 |
| `docs/execution/Phase-D4/` | 本文 + `02-implementation-notes.md` + verdict |

不改动：`state.py`、`tools.py`、`persistence.py`、`worker/*`、`contracts.py`、
LangGraph 拓扑、checkpoint version、`AgentCompletedEvent`。

---

## 三、已知边界（本刀不宣称解决）

1. 模型 decider 仍可能重复动作到 CEILING（受 step/tool/LLM 三重上限约束）。
2. `FEASIBILITY:validate_itinerary` 的 signature 无 detail 段
   （failure_policy.py:248-251，`FEASIBILITY_BLOCKED` 分支 detail=""），
   因此不同原因的结构守门失败共享同一 signature，会被判为 duplicate。
   影响：守门连续失败时更早 ask 用户 —— 方向正确，粒度偏粗。属 D-1 signature
   粒度问题，本刀不改分类器（避免连带回归），记录为 FOLLOW-UP。
3. D-0 FOLLOW-UP 中「守门失败 → repair」链路不在本刀范围内。
4. `update_constraints` → `NO_VALUES` 的同签名自旋不在本刀射程内（Guard 只否决
   失败工具本身，而 `update_constraints` 被显式排除）。§一.5 的「末观测是 ask_user」
   判据使升级路径不再触发它，但空提案路径本身的重复仍未收口 —— 需要 D-1 为
   `NO_VALUES` 提供不重复签名的语义，属独立一刀。
