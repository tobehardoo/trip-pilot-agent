# Phase D-Final Acceptance Notes — 决策与恢复链路验收（纯验收刀）

一刀一验收 · 本文记录**实测证据**（基线 `da2627f feat (D-4)`，HEAD 验收）。
设计裁定见 `01-design-verdict.md`；本文只写「测试里现在真的断言了什么、跑出了什么」。

---

## 一、改动清单（1 个新文件 + 本文档目录）

| 文件 | 内容 |
|---|---|
| `apps/agent-service/tests/agent/test_decision_recovery_acceptance.py` | 新建，9 项：场景 A–F 各一条处理器级完整轨迹 + 场景 D 双 kind + 跨场景不变量 G、H |
| `docs/execution/Phase-DFinal/` | `01-design-verdict.md`（Step 0–2 产物）+ 本文 |

**零生产代码改动**（`git diff --stat` 核对：`src/` 无 diff）。反证刀临时改过的
`MAX_TRANSIENT_SAME_FAILURE_ACTIONS` 已还原，工作树中无残留。

## 二、场景 → 测试映射（全部处理器级，真实链路）

| 场景 | 测试 | 关键断言（实测通过） |
|---|---|---|
| A 瞬时失败→重试→成功 | `test_scenario_a_transient_failure_retries_once_then_completes` | 2 次 build `[False, True]`；step 轨迹 `update_constraints → build ×2 → validate`；成功清空 memory `(None, None, 0)`；COMPLETED + AgentCompletedEvent |
| B 瞬时耗尽→交还用户 | `test_scenario_b_exhausted_transient_exits_to_the_user_with_memory` | 恰好 2 次 build；memory `(TRANSIENT, …PROVIDER_TIMEOUT, 2)` 保留；1 次 ask；WAITING_USER |
| C 用户约束冲突→用户改→重规划 | `test_scenario_c_user_constraint_adjustment_replans_and_completes` | USER_CONSTRAINT → ask；resume「预算 4000」→ COMPLETED；budget=4000 且 `USER_OVERRIDE`、evidence 含 4000；其余约束不动；成功清零 memory |
| D 无效回复→memory 保留 | `test_scenario_d_…`（USER_CONSTRAINT 与 FEASIBILITY 各一） | 「随便吧」后 kind/signature/attempts 原样保留；update_constraints 计数不增；问题重复（asks 2）；FEASIBILITY 侧不再发起 rebuild（build 恒 1 次） |
| E 重复失败→升级→授权有界 | `test_scenario_e_duplicate_failure_escalates_and_consent_stays_bounded` | 首轮 2 builds；每次「再试一次」各换一次重建（3 → 4）；第 4 次失败后 Guard 否决 → **STOPPED**；memory `(…, 4)` 不被出口重置 |
| F 不同失败不误触发 | `test_scenario_f_a_changed_failure_gets_a_fresh_attempt` | PROVIDER_TIMEOUT→RATE_LIMITED：签名变更、attempts 归 1、重新获得一次有界重试（共 3 builds）；memory `RATE_LIMITED/2`；出口是故障通知不是天花板 |
| G 约束安全 | `test_invariant_g_no_recovery_mechanism_edits_constraints_on_its_own` | 全部 7 条轨迹的终点 checkpoint 上，4 个约束与用户原话逐字一致（唯一例外是 C 中用户自己改的 budget） |
| H CEILING 仅安全边界 | `test_invariant_h_no_scenario_ever_ends_on_the_step_ceiling` | 全部轨迹终态 ∈ {COMPLETED, WAITING_USER, STOPPED}；且任何 AGENT_RUN_FINISHED 的 reason_code ≠ CEILING_REACHED |

## 三、回归证据（全部实测，命令见 01 §环境）

| 门禁 | 命令 | 结果 |
|---|---|---|
| Gate 1 本刀 | `pytest tests/agent/test_decision_recovery_acceptance.py -q` | **9 passed** |
| Gate 2 agent 目录 | `pytest tests/agent -q` | **183 passed, 5 skipped**（基线 174 + 9） |
| Gate 3 全量 | `pytest -q --basetemp=…` | **2036 passed, 42 skipped**（基线 2027 + 9，零回归） |
| Gate 4 决策闭环 | `PYTHONIOENCODING=utf-8 …/python scripts/simulate_planning_v2.py` | **EXIT=0，通过 34/34** |
| Gate 5 Lint | `ruff check`（新文件） | **All checks passed** |

`--basetemp` 指向仓库外（`/c/Temp/…`）：Windows Temp ACL 会让 pytest 临时目录
失败，与本刀无关（既有环境问题）。

## 四、反证（可证伪性实测）

把 `MAX_TRANSIENT_SAME_FAILURE_ACTIONS` 临时改为 10000（= 解除 D-2/D-4 的有界
授权语义）后重跑本刀：**场景 E 失败**——第二次「再试一次」不再得到 `STOPPED`，
而是继续 `WAITING_USER`（授权循环重新养成，无界重试回归）。其余 8 项不受
该常量影响（方向正确：A/C/D/F 走的是别的机制）。还原常量后 9/9 复绿。
不变量 H 的防线由既有套件覆盖（若循环只能靠天花板停下，`tests/agent` 中
D-2/D-4 的 CEILING 断言族会失败）。

## 五、验收中发现并如实修正的测试侧问题（非生产缺陷）

1. 场景 A 的 step 轨迹初稿漏了起始回合的 `update_constraints`（约束收集本就在
   build 之前）；已按真实轨迹补齐断言。
2. 场景 D 初稿断言「不存在 update_constraints 观测」——observations 跨回合累积，
   起始回合的合法收集也在其中；改为 resume 前后计数相等。
3. 契约事件 `payload` 是类型化模型而非 dict；改为属性访问。

三处都是断言写错，生产行为自始至终与 01 §FACT 一致 —— **STOP CONDITION 1
未触发**，设计裁定无需修订。

## 六、本刀没做（与 01 §NON-GOALS 对齐）

1. 未修任何生产代码（包括已知遗留：NO_VALUES 同签名自旋、守门签名粒度、
   模型 decider 无 Guard）。
2. 未重构既有测试；复用 `test_transient_retry` / `test_infeasible_resume` /
   `test_duplicate_failure_guard` 的 harness。
3. 未触碰 Worker、LangGraph 拓扑、`CHECKPOINT_VERSION`、wire 契约。
