# Phase F-1 · Repository 减负验收记录

> 依据：`docs/execution/Phase-F0/02-convergence-plan.md`（F-1 三子刀方案）
> 执行窗口：2026-09-01（F-1a `74a671c` → F-1b `236d4de` → F-1c `ef57729`）
> 验收基准：HEAD `ef57729` · 本记录只读，不改代码

---

## 1. F-1a 运行时垃圾出仓 + .gitignore 补全 — **PASS**

| 验收项 | 证据 |
|---|---|
| `.run/*`（6 log + start-agent-api.sh）不再被追踪 | `git ls-files \| grep -cE "\.run/"` = 0 |
| `.zcode/plans/*` 不再被追踪 | 同上 = 0（含 `.zcode/`） |
| `output/` 全目录不再被追踪 | 同上 = 0（13 个原追踪文件出仓，本地文件保留） |
| `.gitignore` 合并补全 | `.gitignore:45 .run/`、`:46 output/`、`:53 .zcode/`、`:19 apps/agent-service/.tmp/`（`git check-ignore -v` 抽查全中） |
| 无消费者破坏 | 提交信息注明 grep 验证无 CI/compose/script 消费这些路径 |

> 约定退役注记：项目既有约定「`.run/web.log` 与 `docs/execution/2026-08-31-phase-b/*` 不随任何提交入库」——本刀后 `.run/` 已成 gitignore 项，该约定自然退役。

## 2. F-1b 死依赖 + 死代码（纯删） — **PASS**

| 验收项 | 证据 |
|---|---|
| `ortools` 删除（pyproject.toml:12，src 0 import） | 当前 `pyproject.toml` 无 `ortools`（grep 空） |
| `framer-motion`/`radix-vue`/`class-variance-authority` 删除 | 当前 `apps/web/package.json` 无三者（grep 空） |
| Python 死代码：`processor.py` 兼容再导出块、`amap/planning_provider.py` 再导出、`StaticUrlDiscoverer`、废弃 `DEMO_MODE` 开关 | `StaticUrlDiscoverer` 全仓 grep 空；`VisitDurationProfile` 为保留真类型非残留别名 |
| Java：`PlanningCompletedEventParser` v1–v8 死分支、11 个空壳包 | 当前 `package-info.java` 空壳 = 0 |
| Web 死代码：`ConstraintPanel.vue`、`ui/Dialog.vue`、`lib/supported-cities.ts`、`lib/routes.ts::parseRoute` | 三者路径均不存在（ls 确认） |
| 三端测试全绿 | agent `2041 passed / 42 skipped`（E-1 基线复跑一致） |

## 3. F-1c 一次性脚本与历史产物 — **PASS**

| 验收项 | 证据 |
|---|---|
| 删 5 个一次性脚本（simulate_planning_v1 483 / reproduce_guangzhou 112 / deadcode_audit 106 / e2e-10-scenarios 326 / multi_city_test 123 = 1150 行） | 全部 `git rm`，无任何消费者（grep 空） |
| `acceptance/b14`：matrix_*.py + results-*.json（2032 行）移入 `docs/archive/acceptance-b14/` | 10 文件 rename 100%；`b14lib.py` 保留原位（被 `scripts/tests/test_b14_{db,docker}_helper.py` import） |
| 归档脚本自洽 | `os.path.dirname(__file__)` 相对路径 → 新目录写新 results；`py_compile` 5/5 OK |
| 测试验证 | `scripts/tests` 23 passed |

### 3a. 本刀执行期环境异常记录
执行 `git rm/mv` 期间，12 个**未列入本刀**的已跟踪文件（`b14lib.py`、`simulate_planning_v2.py`、`smoke_test.py`、`validate_staging_env.py`、`check_compose_defaults.py`、`check_markdown_links.py`、`golden_scenarios_http.py`、`postgres_backup.py`、`scripts/tests/*`×4）在磁盘上缺失（`git status` 显示 ` D`）。已用 `git checkout HEAD -- <paths>` 无损恢复，恢复后内容与 HEAD 逐一致（`git status` 无 diff）。疑似与仓库历史上 git store corruption（`9d0f131` baseline）同源的环境抖动，非本刀操作所致；恢复后全部验证通过。

## 4. 按计划暂缓项（非 FAIL，等待批准/后续刀）

| 项 | 计划出处 | 处置 |
|---|---|---|
| `smoke_test.py` / `golden_scenarios_http.py` / `postgres_backup.py` / `check_compose_defaults.py` | F-1c §3「需批准时确认」 | 保留在 `scripts/`，0 文档引用，可能有手动运维价值，待批准 |
| `contracts/messaging` v4–v8 → `legacy/` + 契约测试 glob 改写 | F-1c §4（与 F-3c 重叠） | 留给 F-3c 跨语言同批终结，避免半绿窗口 |

## 5. 结论

**ACCEPT。** F-1 三子刀全部落地且独立验收：垃圾出仓（F-1a）、死依赖死代码清除（F-1b）、一次性脚本清理与 b14 归档（F-1c）。验收证据全部可复跑。剩余两项按计划暂缓。下一刀按 F-0 方案进入 **F-2（概念统一与重复合并）** 或 **F-3c（事件代际终结）**。
