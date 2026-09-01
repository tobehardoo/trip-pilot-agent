# Phase F-0 · Acceptance Summary

**Phase:** F-0 — 全系统减负审计（AUDIT ONLY，零代码修改）
**基线：** HEAD `a56a769` · 日期 2026-08-31
**交付物：** [01-system-inventory.md](./01-system-inventory.md) · [02-convergence-plan.md](./02-convergence-plan.md)

---

## 1. 范围合规

| 要求 | 状态 |
|---|---|
| 只读，零生产代码修改 | PASS — 提交仅含 Phase-F0 文档 |
| 扫描覆盖 apps/、contracts/、infra/、tests/、scripts/、docs/、根配置、CI/CD、Docker | PASS — 四路并行审计 + 仓库级盘点 |
| 每个删除/合并候选都有引用审计 | PASS — 全部条目附 file:line 或 grep 证据；高影响结论（OR-Tools 零 import、11 空壳包、Web 死文件、追踪的 .run/.zcode）已二次复核 |
| 区分"删除"与"归档" | PASS — 脚本/文档/契约版本均给出分类与理由 |
| 输出完整减负与收敛方案 | PASS — F-1..F-7 逐刀 + Canonical Vocabulary + 目标架构 + STOP 条件 |

## 2. 核心发现（五条）

1. **垃圾已入库**：6 个 `.run/*.log` + `start-agent-api.sh`、`.zcode/plans`、`output/resume/*`（13 个个人求职文件含 pdf/docx）被 git 追踪；`.gitignore` 漏 `.run/` 与 `.zcode/`。
2. **死依赖与文档失实互为因果**：`ortools` 零 import 却有 5 份文档宣称 "OR-Tools 求解"；Web 3 个死依赖、3 个死文件、双路由系统并存。
3. **跨语言重复**：Java 双事件解析器复制校验逻辑且**已分叉出真实缺陷**（`isPersistableMoney` review 侧放过负数金额）；4 个事件服务同骨架；双 SSE 栈；Python 3 处 provider 模式解析、4 处 env 读取。
4. **事件代际残留横跨三处**：Python 旧代事件类（仅测试引用）、Java 解析器 ~200 行 v1–v8 死分支、`contracts/messaging` v4–v8（v7 自述 ABANDONED）——必须同一刀同批终结。
5. **测试是最大的重复源**：Python 测试比源码大 26%（`_poi`×17 等工厂重复）；文档 107 份中约 30 份执行记录已被后续阶段整体取代。

## 3. 待批准时拍板的决策点

| 决策点 | 选项 |
|---|---|
| `output/resume/` 出仓 | 个人材料，建议 `git rm --cached` + 忽略（本地保留）；需确认 |
| `acceptance/b14/matrix_*.py` + results | 归档 vs 删除（`b14lib.py` 为 CI 依赖，保留） |
| `smoke_test.py` / `golden_scenarios_http.py` / `postgres_backup.py` / `check_compose_defaults.py` | 保留（有手动运维价值）vs 归档 |
| `compose.yaml` | 废弃（全部文档只用 prod，且其 postgres build context 疑似损坏）vs 修复 |
| F-5 中文注释化范围 | 方案采用"受限扩散"（仅本阶段修改过的文件），需确认 |

## 4. STOP 条件检查

无触发：未修改任何代码；未触碰 wire 契约 / DB schema / 用户确认约束；未对任何文件做删除动作（审计建议均待批准）。

## 5. Verdict

**ACCEPT。** F-0 完成审计闭环：资产基线已量化（1037 追踪文件、四端行数与最大文件清单）、垃圾/重复/遗留/大文件全部在册且附证据、F-1..F-7 逐刀方案就绪。**等待批准后自 F-1a 开始，逐刀执行、逐刀验收。**
