# Phase D-Final Design Verdict — Decision & Recovery End-to-End Acceptance

一刀一验收 · 本文档在任何改动之前写定，全部结论锚定当前 HEAD 的 file:line 或既有实测。
基线代码：`da2627f feat(agent): add duplicate failure recovery guard`（D-4 已提交）。
本文不复用 D-0..D-4 的历史结论作为证据，所有依赖事实已在当前 HEAD 重读确认。

---

## 〇、Workspace Check（Step 0 实测）

```text
HEAD            da2627f（D-4 已提交，工作区无未提交的 src 改动）
非本刀文件       .run/web.log（并行会话，M，不触碰）
                docs/execution/2026-08-31-phase-b/*（并行会话，??，不触碰）
本刀 Scope      apps/agent-service/tests/agent/（新增验收模块）
                docs/execution/Phase-DFinal/（本文 + 验收记录）
```

---

## 一、Fact Verification（Step 1，当前 HEAD 重读）

### FACT A — 决策链（控制权所在）

代码位置：`agent/graph.py:177-361`（`AskingDecider.decide`）。

当前真实行为（required_hard 链，顺序即优先级）：

1. `CAPABILITY_MISSING` → answer handoff（:184-189）
2. 末观测是 ask_user ∧ `failure_kind ∈ USER_OWNED_KINDS` ∧ attempts>0 →
   `_extract_adjustment` 解析；有调整 → `update_constraints`（REPLAN）（:190-209）
3. 末次 build `PLANNING_INFEASIBLE` ∧ `USER_CONSTRAINT` → 重复提问（:210-234）
4. `TRANSIENT` → Guard（:248-252）→ attempts≤1 一次 RETRY（:253-258）→
   末观测 ask_user 时用户授权再试（:259-264）→ 否则 ask 公告（:265-278）
5. 无候选 → Guard（:284-290）→ build（:291-295）
6. 未过闸 → Guard（:301-307）→ validate（:308-312）
7. 过闸 → EMITTED answer（:313-317）

控制权：**Decider 决定一切策略**；`_act_node` 只执行与记录；`_finish_node`
只做出口翻译（:733-736：无 stop_reason 时 `answer?"ANSWERED":"STOPPED"`）。

### FACT B — 失败记忆与重置（唯一释放路径）

- 写入点唯一：`_act_node` 每条非 ask 观测后 `classify_failure` →
  `advance_failure_memory`（graph.py:692-717）；ask_user 观测显式豁免（:693-694）。
- 唯一强重置：`tools.py:229-238`（applied 非空或有 rejection → 清三字段 + 候选作废）。
- 成功清零：`failure_policy.advance_failure_memory` 收 `(None,"")` → `(None,None,0)`。
- `WAITING_USER` 产生点：`tools.py:310`（ask_user handler 置 stop_reason）。

### FACT C — Guard（D-4，HEAD 现状）

- 纯函数判定：`failure_policy.py:344-374 escalate_duplicate`；预算表
  `:304-312`（TRANSIENT=3，其余 0）；`_STOPS_NOT_ASKS={TRANSIENT,INTERNAL,CAPABILITY_MISSING}`。
- Decider 侧：`graph.py:363-402 _duplicate_guard`（STOPPED → 裸 Decision；
  ASK_USER → ask_user 带冲突文案），只读不写，永不否决 ask/update_constraints。

### FACT D — 场景 A–H 的既有覆盖与缺口

| 场景 | 既有断言（file:test） | 缺口（本刀要补的） |
|---|---|---|
| A. TRANSIENT FAIL→RETRY→SUCCESS | `test_transient_retry.py:273`（loop 级 EMITTED）、`:456`（成功清 checkpoint 记忆） | 缺**处理器级**完整轨迹（start→fail→retry→emit 一步不少） |
| B. TRANSIENT Exhausted→WAITING_USER | `:375`、`:410`（有界、交还用户） | 缺统一口径：run status==WAITING_USER ∧ 非 CEILING ∧ 公告文案含「再试」 |
| C. USER_CONSTRAINT ASK→CHANGE→REPLAN→SUCCESS | `test_infeasible_resume.py:232`（预算）、`:337`（删必去） | 已覆盖；验收套间复用并统一断言口径 |
| D. Invalid Resume→MEMORY PRESERVED | `:283`（failure_kind 保留）、`:269`（约束不动）；FEASIBILITY 变体见 D-4 Test D | 缺对 **attempts/signature 也保留** 的显式断言（两 kind 各一） |
| E. FAIL X→RECOVERY→FAIL X→ESCALATE | D-4 Test E（TRANSIENT 授权循环，预算 3+1→STOPPED）、Test G（确定性→ASK/STOP） | 缺**处理器级**多 turn 轨迹：两次恢复尝试夹在同签名失败之间仍升级 |
| F. FAIL X→FAIL Y→不触发 | D-4 Test B（attempts 归 1 重获机会） | 已覆盖；验收套间显式纳入 |
| G. Constraint Safety | `:314`、`:431`（retry 不动约束）、`:269/:283`（无效回复不动） | 缺**跨场景不变量**：A–E 每个快照中硬约束只随用户证据变化 |
| H. CEILING 只是安全边界 | D-4 Test G（确定性重复非 CEILING）、`test_agent_loop.py:287/:320`（边界仍有效） | 缺**跨场景**断言：A–G 任一场景出口都不是 CEILING_REACHED |

结论：机制全部存在且各自有刀内测试；**缺的是单一、可一次执行的场景级验收集合
+ 两条跨场景不变量（G 约束安全、H 非 CEILING）**。

### FACT E — 验收入口（复用，不新建）

处理器级入口：`worker/agent_processor.py:169 AgentDialogProcessor`
（`handle_start` / `handle_resume`）。既有 harness 全部可复用：
`test_transient_retry.py` 的 `_RecordingProcessor` / `_start_command` /
`_resume_command` / `_ScriptedBuilder` / `_collector`（D-4 已用相同方式跨模块导入）。
不新增任何生产抽象。

---

## 二、Design Verdict

```text
PROBLEM:
D-1..D-4 四刀各自有机制级测试，但「决策与恢复作为一个整体」从未被
按场景 A–H 统一验收：没有单一入口能证明 8 个场景同时成立，也没有
跨场景不变量（约束安全 / 非 CEILING 出口）的集中断言。

ROOT CAUSE:
验收单位与实施单位错位 —— 每刀测自己的机制，场景是跨机制的。

MINIMUM FIX:
新增一个验收测试模块（处理器级，复用既有 harness），把场景 A–H
逐一断言为完整轨迹，并加入两条跨场景不变量。
零生产代码改动：本刀是纯验收刀；若任何场景对 HEAD 失败，
触发 STOP CONDITION 1 —— 停止、重新裁定，修生产代码属于新刀。

CONTROL OWNER:
不变。Decider 决定、Tool 报告、State 记忆、Guard 防策略循环；
验收只观察，不引入新的控制权。

STATE CHANGE:
无（不新增字段、不动 checkpoint）。

WIRE CHANGE:
无。

BEHAVIOR CHANGE:
无（测试刀；全部断言针对既有行为）。

NON-GOALS:
· 不修任何生产代码（即使发现已知边界：NO_VALUES 自旋、守门签名粒度、模型 decider）
· 不重构既有测试，不抽公共测试库（复用现有跨模块导入约定）
· 不动 Worker / LangGraph 拓扑 / simulate 脚本

ACCEPTANCE:
1. 新模块 8 个场景 + 2 条不变量全部通过（处理器级真实链路）；
2. tests/agent 全目录与全仓回归零新增失败；
3. simulate_planning_v2 34/34（exit 0）；
4. ruff 对新文件通过；
5. Scope 审计：仅 1 个新测试文件 + Phase-DFinal 文档。

COUNTERFACTUAL:
A. 机制失效可被抓：临时令 Guard 预算=10000（D-4 同款反证）→
   场景 E（有界升级）与不变量 H（非 CEILING）必须失败。
B. 相似但不同：B 出口是 WAITING_USER（停摆公告）而 E 超预算是
   STOPPED（无问题）；F（异签名）不触发升级。
C. 边界：D 无效回复后三字段完整保留且约束不动；
   G 每个快照的硬约束只在用户证据出现时变化。
```

### 反事实的可证伪性说明

本刀产物只有测试，反事实 A 的「移除机制」不是删除本刀文件，
而是**让被测机制失效**（预算改 10000）后重跑本刀验收：
若 E/H 相关断言不失败，说明验收测试没有测到它声称测的东西 —— 不允许提交。

---

## 三、实现蓝图

| 文件 | 改动 |
|---|---|
| `apps/agent-service/tests/agent/test_decision_recovery_acceptance.py` | 新建：场景 A–H + 不变量 G/H，处理器级 |
| `docs/execution/Phase-DFinal/` | 本文 + 验收记录（写入最终 Verdict） |

不改动：`src/**` 全部、既有测试、simulate、Worker。

## 四、已知边界（本刀不宣称解决，与 01-D4 §三一致）

1. 模型 decider 路径不在验收范围（无 Key 确定性链路 + AskingDecider）。
2. `update_constraints:NO_VALUES` 同签名自旋仍开放（Guard 显式不否决该工具）。
3. `FEASIBILITY:validate_itinerary` 签名无 detail 段的粒度问题不变。
