# Phase D-4 Implementation Notes — Duplicate Failure Guard

一刀一验收 · 本文记录**实际落地**的形状与实测证据（基线 `803a421 feat (D-2)`）。
设计结论见 `01-design-verdict.md`；本文只写「代码里现在真的有什么」。

---

## 一、改动清单（3 个文件）

| 文件 | 净增 | 内容 |
|---|---|---|
| `apps/agent-service/src/trip_agent/agent/failure_policy.py` | +92 | D-4 判定段（:293-374）：预算表、派生集合、两个纯函数 |
| `apps/agent-service/src/trip_agent/agent/graph.py` | +162/-19 | 文案表（:138-164）、链首上提的解析（:190-209）、三处 Guard 调用（:248 / :284 / :301）、`_duplicate_guard`（:363-402）、`_failure_detail`（:404-424） |
| `apps/agent-service/tests/agent/test_duplicate_failure_guard.py` | 新建 14 项 | 纯函数单元测试 + Counterfactual A–G |

零改动（已用 `git diff --stat` 核对）：`state.py`、`tools.py`、`persistence.py`、
`worker/*`、`contracts.py`、LangGraph 拓扑、`CHECKPOINT_VERSION`、`AgentCompletedEvent`。
新增 State 字段：**无**。`failure_history[]` / `last_recovery_action`：**均未引入**。

---

## 二、failure_policy.py：判定为纯函数

```text
FAILURE_REPEAT_BUDGET: dict[FailureKind, int]      :304-312
    TRANSIENT = MAX_TRANSIENT_SAME_FAILURE_ACTIONS(=3)   # :298
    其余 6 个 kind = 0
_STOPS_NOT_ASKS: frozenset = {TRANSIENT, INTERNAL, CAPABILITY_MISSING}   # :317-319
USER_OWNED_KINDS = frozenset(预算表 keys − _STOPS_NOT_ASKS)              # :325-327
signature_tool(signature) -> str | None            :332-341   # KIND:tool:detail 的第 2 段
escalate_duplicate(kind, signature, attempts, action_tool) -> "ASK_USER"|"STOPPED"|None  :344-374
```

`escalate_duplicate` 的三个条件必须同时成立（缺一即返回 `None`，动作照发）：
动作工具 == 失败工具、memory 未解除且 `attempts > 该 kind 预算`、kind 已知。
`attempts` 单独永不构成充分条件。函数不写任何状态。

`USER_OWNED_KINDS` 是**派生**而非手写：「会问用户的 kind」与「回答会被解析成调整的
kind」由同一张表定义，因此两者不可能各自漂移（这是 §一.5 不变量的实现保证）。

## 三、graph.py：Guard 只出现在决策点

发出动作前的三处否决，全部在 `AskingDecider.decide` 内：

| 调用点 | 行 | 动作 | 传入 detail |
|---|---|---|---|
| TRANSIENT 分支（D-2 ladder 之前） | :248 | `build_itinerary` | 末次 build 观测 summary |
| 候选为空 → 首次规划 | :284 | `build_itinerary` | `_failure_detail(state,"build_itinerary")` |
| 候选已有 → 结构守门 | :301 | `validate_itinerary` | `_failure_detail(state,"validate_itinerary")` |

`_duplicate_guard`（:363-402）把升级翻译成**既有出口**：
`"STOPPED"` → `Decision(thought=...)`（无 call 无 answer，`_finish_node` 已产出
`stop_reason="STOPPED"`）；`"ASK_USER"` → `ToolCall("ask_user", {...})`
（`tools.py:310` 置 `WAITING_USER`，一个 step 内结束 turn）。
所以本刀没有新增 stop_reason 字符串、事件、DB 列或 checkpoint 字段。

`_failure_detail`（:404-424）优先取守门报告里的逐条冲突文案，其次取该工具最近一次
观测 summary，最后退化为 signature；一律截断到 140 字符（:164）以守住
`AgentQuestionText` 的 300 字符线上限。

## 四、链路上唯一的既有语义变化

`_extract_adjustment`（D-3）的调用位置从 infeasible 分支内**上提到 required_hard 链首**
（:190-209），条件为「末观测是 ask_user ∧ `failure_kind ∈ USER_OWNED_KINDS` ∧
`attempts > 0`」；D-3 分支（:210 起）收窄为「解析不出调整时才重复提问」。

原因（诚实升级不变量）：Guard 对 FEASIBILITY / VALIDATION / CANDIDATE_EMPTY 也走
`ASK_USER`，若回答仍不被解析，这些出口无法解除 → 永久重复同一个问题。
「末观测是 ask_user」这一条同时排除了同一 turn 重复解析自己原始消息的路径
（否则会落进 `update_constraints:NO_VALUES` 的异签名自旋）。

`test_infeasible_resume.py` / `test_transient_retry.py` 未改一行断言即全绿，
证明这是位置变化而非语义变化。

## 五、验收证据（全部实测）

| 检查 | 命令 | 结果 |
|---|---|---|
| 本刀单测 | `pytest tests/agent/test_duplicate_failure_guard.py -q` | **14 passed** |
| 反证（Guard 失效） | 临时把 `FAILURE_REPEAT_BUDGET` 全部改成 10000 后同跑 | **12 failed / 2 passed** —— 2 个通过的正是 Test F `test_the_normal_clarification_loop_never_meets_the_guard`（普通澄清本就不该被否决）与 `test_the_failing_tool_is_readable_from_the_signature`（只解析 signature 第 2 段，不读预算表）。**本刀要防的循环全部失去防线，本该不受影响的两项全部保留** —— 方向正确，且证明测试真的在测 Guard |
| agent 目录 | `pytest tests/agent -q` | **174 passed, 5 skipped**（基线 160 + 新增 14） |
| 全量回归 | `pytest -q --basetemp=.tmp-pytest-d4` | **2027 passed, 42 skipped**（基线 2013 + 14，零回归） |
| 决策闭环 | `PYTHONIOENCODING=utf-8 python scripts/simulate_planning_v2.py` | **通过 34/34** |
| Lint | `ruff check` 三个文件 | **All checks passed** |

关键 counterfactual 实测断言：
A 确定性拒绝 → 1 次 build + 1 次 ask，steps < MAX_STEPS，memory 保持
`FEASIBILITY / FEASIBILITY:build_itinerary:INSUFFICIENT_DAY_CAPACITY / 1`；
G（三种永久失败 + 永久 blocked 守门）→ 出口是 `WAITING_USER`/`STOPPED`，
**不再是 `CEILING_REACHED`**，planning 动作 ≤1 次、steps ≤3；
B 换一种失败 → attempts 归 1，重新获得一次机会；
C 用户真实改预算 → Guard 解除并 EMITTED（builds `[False, True]`，只问过 1 次）；
D 「随便吧」→ 约束不变、不再发 build、只重复问题；
E 用户连说两次「再试一次」→ 第 4 次 build 后 `STOPPED`（= 预算 3 + 1），
证明授权不能重新养成无上界 retry；
F 缺 slot 的普通澄清 → 观测只有 `["ask_user"]`，每个快照 memory 全空。

## 六、本刀没做（与 01 §三对齐）

1. 模型 decider（`StructuredOutputDecider`）不加 Guard，仍受 step/tool/LLM 三重上限。
2. `FEASIBILITY:validate_itinerary` 无 detail 段 → 不同守门原因共享签名，粒度偏粗。
3. `update_constraints:NO_VALUES` 的同签名自旋不收口（Guard 显式不否决该工具）。
4. 守门失败 → repair 链路不在范围内。

## 七、环境备忘（复现本刀验证时需要）

必须使用 `apps/agent-service/.venv/Scripts/python.exe`（全局 Anaconda python 会让
langgraph 采集失败）；Windows 下 pytest 需 `--basetemp` 以避开 Temp ACL；
`scripts/simulate_planning_v2.py` 输出含 emoji，GBK 控制台需
`PYTHONIOENCODING=utf-8`，否则 `UnicodeEncodeError`（与本刀无关的既有问题）。
