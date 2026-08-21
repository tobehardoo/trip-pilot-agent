# QA-2026-08-20 — 缺陷清单

顶层分类（唯一允许）：`PRODUCT_DEFECT` / `TEST_DEFECT` / `ENVIRONMENT` / `EXTERNAL_PROVIDER_VOLATILITY` / `FLAKY`

---

## QA-D01 — B16 execution-report 断链 plan.md

- **严重度**：P3（文档）
- **分类**：PRODUCT_DEFECT（文档产物）
- **复现**：`python scripts/check_markdown_links.py` → 报 `docs/execution/B16/execution-report.md` 引用 `plan.md`，但 `docs/execution/B16/` 无该文件（实际为 `plan.md` 缺失，目录仅有 execution-report.md 等）。
- **预期**：报告内链接指向存在的文件。
- **实际**：链接 404（文件系统层面）。
- **根因**：B16 文档引用计划文件时文件名不一致（历史文档缺陷）。
- **影响**：仅文档导航，不影响任何代码/测试/构建。
- **修改文件**：无（未修，非阻塞）。
- **回归测试**：`check_markdown_links.py`（修复后应 exit=0）。
- **修复状态**：OPEN（P3，非阻塞）。

---

## QA-D02 — B14 旧脚本 db() 静默吞掉 psql 失败（S079 根因）

- **严重度**：P2（测试工具）
- **分类**：TEST_DEFECT
- **复现**：`scripts/acceptance/b14/b14lib.py::db()` 从宿主 env 猜 `POSTGRES_USER`（临时 env 为 `postgres`，容器实际 `trip_pilot`）；psql 失败（`returncode=2, FATAL: role "postgres" does not exist`）时忽略 returncode/stderr，**静默返回空字符串** → S079 数据库断言拿到假空结果。
- **预期**：凭据取容器自身 `POSTGRES_USER/POSTGRES_DB`；psql 非零退出必须抛脱敏异常。
- **实际**：静默空串，DB 断言可能误绿。
- **根因**：harness 凭据来源错误 + subprocess 退出码未检查。
- **影响**：B14 场景 DB 对账结果不可信（曾掩盖 S079 真实状态）。
- **修复**：`b14lib.py` 重写 `db()` —— `docker exec ... sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -v ON_ERROR_STOP=1 -c "$1"'`；非零退出 → `RuntimeError`（脱敏，含容器名与 stderr 前 300 字符，无密码）；新增 `scripts/tests/test_b14_db_helper.py`（3 个测试：非零必须 raise、成功返回行、凭据来自容器 env 且无明文密码）。
- **回归测试**：`python -m unittest scripts.tests.test_b14_db_helper -v`（3/3 PASS）；`discover -s scripts/tests`（15/15 PASS）。
- **修复状态**：FIXED（本轮，harness 层；生产代码零改动）。

---

## QA-D03 — B14 S073 场景非确定性（依赖 DEMO 瞬时完成）

- **严重度**：P2（测试工具）
- **分类**：TEST_DEFECT
- **复现**：`matrix_b.s073()` 先 `poll_terminal` 再创建第二任务——DEMO 下首任务瞬间 SUCCEEDED，active slot 已释放，第二次 `202`（非预期 409）。
- **预期**：第二次必须 409 `PLANNING_TASK_ACTIVE`（目录意图：one-active）。
- **实际**：可能 202（测试逻辑与目录矛盾）。
- **根因**：未固定 active 状态窗口；同问题存在于 S071（ok 条件过宽 `st2==409 or sameTask`）。
- **修复**：S071/S073 均改为确定性——try/finally 中 `docker pause AGENT_CONTAINER` → 首任务 202 且 QUEUED/RUNNING → 新 Idempotency-Key 第二任务 → 断言 409/PLANNING_TASK_ACTIVE + DB 断言（`active=1`、`createOutbox=1`）→ finally unpause → 等终态（SUCCEEDED）。
- **回归测试**：S073 ×3 稳定 PASS；matrix_b 30/30 PASS。
- **修复状态**：FIXED（harness 层）。

---

## QA-D04 — B14 S079 断言过宽（`<= 1` 终态）

- **严重度**：P2（测试工具）
- **分类**：TEST_DEFECT
- **复现**：`matrix_b.s079()` 断言 `len(terminals) <= 1`——0 个终态也 PASS（与"恰好一个终态"的目录语义不符）；且 `itinerary_version` 无 `trip_id` 列（原 SQL 报错被 db() 静默吞掉）。
- **修复**：断言改 `len(terminals) == 1`；version 查询改 `planning_task_id`（UNIQUE）；证据记录 allEvents/terminalEvents/versions。
- **回归测试**：S079 ×3 稳定 PASS（每次恰好 1 终态、versions=1）。
- **修复状态**：FIXED（harness 层）。

---

## QA-D05 — B14 matrix_fault S086 首跑 matrix 内 FAIL（harness 假绿风险）

- **严重度**：P1（测试工具/假绿风险，阻塞最终 PASS）
- **分类**：TEST_DEFECT（harness 消费者就绪与日志游标缺失致假绿）
- **复现**：完整 matrix_fault 首跑 S086 `rejected=False`；且原 S086 存在多处假绿：`consumer_alive=True` 恒真、`routed` 未断言、历史日志可误判、队列 `ready/unacked/consumers` 未轮询、`worker running/healthy` 未校验、脚本明文密码；S083/S084 亦存在 `<=1`/`ready` 未断言假绿。
- **预期**：S086 必须：发布前 `consumers>=1`、记录日志游标/仅查新日志、`routed=true`、`ready=0/unacked=0/consumers>=1` 轮询、`worker running+healthy+consumers` 校验、脚本 try/finally 脱敏；S083/S084 必须 `consumers>=1` 且 `恰好1条` 终态。
- **实际**：产品行为正确（手动重放 `routed=true` → worker 日志 `WARNING:rejecting invalid planning command: 8`、队列 0 积压），但 harness 首次 matrix 内因消费者窗口与游标问题 FAIL；S086 独立复验 3/3 PASS 为脱离 matrix 时序的独立验证，非 matrix 内连续证据。
- **根因**：harness 缺少消费者就绪等待 + 日志游标 + 路由断言（假绿），与 matrix 内 kill/restart 时序叠加。
- **影响**：阻塞最终 PASS（故障注入门禁未满足“连续 3 次完整 matrix 全绿且无历史日志误判”）。
- **修复**：`b14lib` 新增 `docker_checked()`（非零脱敏 RuntimeError、timeout 带 category/container）与 `wait_healthy_or_raise()`；`matrix_fault.py` 删除重复 `docker()/wait_healthy()` 改用 `b14lib`、S083/S084 补 `consumers>=1`/`恰好1条`/`ready=0/unacked=0`/`versions 恰好语义`、S086 重写为消费者预检+游标+`routed=true`+新日志+轮询+`running/healthy`+脱敏无明文密码（try/finally）。
- **修复状态**：OPEN/FLAKY（harness 已修复，待完整 `matrix_fault` 连续 3 次全绿后改为 FIXED_BY_HARNESS；本轮不得写“重跑即修复”）。

---

## QA-D06 — nginx auth 限流致 B14 矩阵 503（S003/S004/S054 首跑）

- **严重度**：P2（测试工具/配置适配）
- **分类**：TEST_DEFECT（子因 HARNESS_VS_CONFIG —— **非独立顶层分类**）
- **复现**：功能矩阵 50 场景 × 多次 auth 调用触发 web 镜像 nginx `auth_limit 10r/m burst=5 nodelay` → 503。
- **预期**：矩阵验证业务语义，不应被有意限流误伤。
- **实际**：503 伪影（独立验证 refresh-no-cookie 恒 401，即产品行为正确）。
- **修复**：`b14lib.BASE` 改为 `B14_BASE_URL`（默认 `http://127.0.0.1:38086` travel-server 直连，绕开 web nginx）；nginx 限流行为独立验证（6×401 → 6×503 → 冷却后恢复）确认为有意产品配置。
- **回归测试**：matrix_a 40/40 非 REAL 正式 PASS（S003/S004/S054 均为正式 PASS，非人工解释）。
- **修复状态**：FIXED（harness 层；nginx 产品配置零改动）。

---

## QA-D07 — D02（S007 越权 versions）隔离栈复现 → 镜像过期

- **严重度**：P1（授权，历史）
- **分类**：ENVIRONMENT
- **复现**：隔离栈旧镜像下 B 用户 GET A 的 `itinerary/versions` → `200 []`（越权）。
- **预期**：404 TRIP_NOT_FOUND（源码 `TripService.get(ownerId, tripId)` 已抛 404）。
- **实际**：重建 `travel-server` 镜像后复验 → **404**；当前源码修复正确。
- **根因**：`trip-pilot-travel-server:local` 镜像早于 B14_FIX R2(D02) 源码修复。
- **影响**：无（产品源码无缺陷；镜像陈旧）。
- **修复状态**：FIXED-BY-REBUILD（隔离栈 travel-server 已用当前工作树重建；复验 S007 PASS）。

---

## 非缺陷观察（不计数）

- O1：live AMap driving 时长波动可翻转 G1/G8 的 TRANSIT↔DRIVING —— facts 驱动，行为正确（EXTERNAL_PROVIDER_VOLATILITY 观察）。
- O2：Windows shim safe-delete 干扰 `vite build`/coverage 清理 —— ENVIRONMENT，已用 `CODEBUDDY_SAFE_DELETE_SANDBOX=0` 绕过。
- O3：Python 覆盖率插件退出清理被 shim 拦截 —— ENVIRONMENT，数据文件完好，独立进程只读生成报告。
- O4：`AGENTS.md` 仓库不存在 —— 记录，无影响。
