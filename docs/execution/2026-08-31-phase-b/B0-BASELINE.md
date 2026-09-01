# Phase B-0 · 工作树基线报告（BASELINE）

> Phase B：System Convergence & Simplification · 2026-08-31
> 模式：一刀一验收 · 本报告为 Phase B 起点基线，不修改任何代码。

---

## 1. Git Working Tree 状态

**判定：CLEAN（干净）**

| 项 | 状态 |
|---|---|
| git status | 无 modified / 无 untracked（`output/audit/` 已被 `001a3f0` 加入 ignore） |
| HEAD | `e55c171` feat (P2-3): themed user explanations — read-only assembly only |
| 历史长度 | 16 commits（已从审计时的 8-commit 损坏历史恢复为完整历史） |
| context_view 重构 | **已提交**：`09b9f80` refactor (P2-0): PlanningContextView（2026-08-31 14:06） |

### 1.1 与审计报告（15:58）的时间线差异（重要澄清）

审计时（15:58）观察到 `context_view.py` / `test_context_view_construction.py` 为 untracked、`planning_provider.py` 为 modified，且实测 2 个失败测试。**根因是 Git 历史损坏**（`9d0f131` baseline 为 corruption 后快照，09b9f80 之后的提交当时不可见），并非代码本身处于未完成状态：

| 时间 | 状态 |
|---|---|
| 14:06 | `09b9f80` P2-0 提交（提交说明：full suite 1937 passed；simulate_v2 30/30） |
| 15:58 | 审计时 git 历史损坏 → 同一批文件显示为未提交；实测 2 failed（中间态误判） |
| 16:13 后 | 历史恢复（16 commits）；HEAD `e55c171` |
| 16:30 | 实测：**1960 passed / 39 skipped / 0 failed** |

**2 个失败测试的修复方式（已核验）**：`test_context_view_construction.py` 自 09b9f80 后再无修改（git log --follow 确认），失败被**实现修复**消除——`planning_provider.py:765` 现传递 `budget_per_person=context_view.budget_per_person_per_day`（P2-1 接入），`context_view.py` 的 cost 解析每天/每预算一次。**非改断言绕过**，符合 Phase B 纪律。

### 1.2 结论（B-0 选项判定）

> **选项 A 成立**：context_view 重构属于 3.0 正式方向（与既有审计 `planning-intelligence-v3-decision-context-audit.md` 方案 B「PlanningContextView 一次构造」一致），且**已收敛完成**（后续 P2-1..P2-3 提交顺带修复了审计发现的餐食预算死参数）。无需回退，无需再修复。

---

## 2. 测试基线（2026-08-31 实测）

| 套件 | 命令 | 结果 | 状态 |
|---|---|---|---|
| Python（agent-service） | `pytest --ignore=test_real_amap_provider.py`（.venv，自定义 basetemp） | **1960 passed / 39 skipped / 0 failed**（16.6s） | ✅ PASS |
| Java（travel-server） | `mvn test`（JDK 24 编译 release 21，临时 Launcher 绕开污染的环境变量） | **618 tests / 0 failures / 0 errors / 0 skipped / BUILD SUCCESS**（~5min） | ✅ PASS |
| Web（apps/web） | `vitest run` | **52 files / 533 tests 全过**（40s） | ✅ PASS |
| 反事实验证 | `scripts/simulate_planning_v2.py` | **34/34 通过**（V2 决策闭环成立） | ✅ PASS |
| ruff（Python lint） | 既有 CI 门禁（本次未重跑） | 审计报告 0 errors | 引用 |

> 注：审计报告 07 中「2 个失败测试」条目**已被本次基线实测废止**——该状态是历史损坏造成的中间态，当前 HEAD 无失败测试。

## 3. 环境事实记录（供后续每一刀复现）

| 项 | 值 |
|---|---|
| Python 解释器 | `apps/agent-service/.venv/Scripts/python.exe` |
| pytest 注意 | 需 `--basetemp` 自定义（系统 Temp 目录权限问题，WinError 5） |
| Java | 系统默认 `java` 为 JDK 8（**不可用**）；JDK 21 未安装；使用 `C:\Program Files\Java\jdk-24`（release 21 兼容） |
| Maven | 环境变量 `MAVEN_HOME` 被污染（指向损坏的 maven-mvnd bin）→ 使用临时 Launcher `output/audit/mvn-run.sh`（直接 java + classworlds） |
| Web | 用 `node node_modules/vitest/vitest.mjs run` 或 `pnpm vitest run`（Git Bash 管道下 exit code 有怪癖，以输出为准） |

## 4. B-0 验收

```
Git working tree 状态明确   ✅ CLEAN @ e55c171
Python 测试通过            ✅ 1960 passed / 0 failed
Java 测试通过              ✅ 618 / 0 / 0 / 0 BUILD SUCCESS
Web 测试通过               ✅ 533 / 0
Counterfactual             ✅ 34/34
当前基线可复现              ✅ 以上命令均可复跑（§3 环境事实）
```

**B-0 = PASS** → 允许进入 B-1。

---

## 5. B-1 第一刀 Scope（等待验收，不执行）

### B-1-1 建议：删除 Web 孤儿组件 `ConstraintPanel.vue`

**理由**：审计 08 已证实零引用；是全部 B-1 候选中风险最低、验收边界最清晰的一刀（纯前端删除，40s 全量验证，零业务行为影响）。作为 Phase B 第一刀，可用于校验「一刀一验收」流程本身。

**预检证据（本报告内已完成）**：

```
Object:            apps/web/src/components/agent-workspace/ConstraintPanel.vue
Consumers:         src 全目录 0 引用（含 index 导出、类型引用）
Test references:   tests/ 0 引用；e2e/ 0 引用
Runtime:           UX3.0 的 ConstraintBoard.vue（planning-session/）已取代其职责（TripSessionView 未引用 ConstraintPanel）
Contract exposure: 无（纯前端展示组件）
Deletion safety:   高（删除后无需 fallback）
```

**执行内容（待批准后）**：
1. `git rm apps/web/src/components/agent-workspace/ConstraintPanel.vue`
2. 再次 grep `ConstraintPanel` 全 web 目录确认 0 引用
3. 跑 Web 全量单测（52 files / 533 tests）
4. 跑 `vue-tsc` typecheck
5. 输出 B-1-1 验收报告

**验收标准**：删除对象生产引用 = 0；Web 测试 533 全过；typecheck 0 错误；无新增 fallback/hack。

---

## 6. B-1 候选队列（后续各刀，按风险升序，待逐刀批准）

| 刀 | 对象 | 风险 | 预检状态 |
|---|---|---|---|
| B-1-1 | Web ConstraintPanel.vue | 低 | 完成（§5） |
| B-1-2 | contracts/messaging/legacy/ 目录（v1-v3） | 低 | 代码 0 引用；需检查 test_messaging_contract_schemas 是否显式枚举 legacy + README 链接 |
| B-1-3 | Java 空壳 package-info（9 个包） | 低-中 | 需确认 package-info 无注解/文档语义 |
| B-1-4 | Python `ortools` 依赖（pyproject.toml:12） | 低-中 | src/tests 0 引用；需检查 lock 文件与 README 同步 |
| B-1-5 | PlanningCompletedEventParser 死分支（:393/:477/:605/:871） | 中 | 需逐分支确认不可达 + Java 全量验证 |
| B-1-6 | PlanningReviewRequiredEventParser 旧版本残留 | 中 | 同上 |
| B-1-7 | DB 死状态值（CREATED/RETRYING/CANCELLING/STALE） | **高** | 影响 existsActiveByTripId 语义 → 需单独行为分析，放本阶段后期 |
| B-1-8 | Agent REPLAN 声明部分（graph.py:227,245,346） | 高 | 涉及 DECISION_SCHEMA 契约（Python 与前端共用）→ 需契约评审，放本阶段后期 |

> 以上队列仅为建议排序；**每一刀独立批准、独立验收**，B-1-1 验收通过前不启动任何后续修改。

---

## 7. 下一动作

等待用户验收 B-0（本报告）并批准 B-1-1 Scope。批准后执行 B-1-1 并输出其独立验收报告。
