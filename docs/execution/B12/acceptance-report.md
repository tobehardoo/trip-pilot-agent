# B12 独立验收报告：Local-first planning lifecycle hardening

- 批次：B12
- 验收 Agent：只读业务验收（本报告为唯一写入物）
- 验收时间：2026-08-14（独立复跑）
- 关联：[plan.md](plan.md)、[execution-report.md](execution-report.md)、[系统完善长期执行与验收总控计划](../../product/系统完善长期执行与验收总控计划.md)
- 结论：**NEEDS_SMALL_FIX**（唯一阻塞项为 execution-report.md §7 一处测试数量笔误，见"发现的问题"；代码/测试/门禁全部 PASS）

---

## 1. 开始前与结束时 Git 状态核对

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| branch | `codex/feasibility-foundation` | `git branch --show-current` |
| HEAD | `136f0663b792200484c877a07abd06397faa1ec9`（与计划/报告一致） | `git rev-parse HEAD` |
| staged | 空（验收前、验收后均空） | `git diff --cached --name-only` 无输出 |
| 工作树改动面 | 17 个 modified + 5 个新增未跟踪文件，与执行报告 §7 精确一致 | `git status --porcelain=v1`、`git diff --name-status`、`git diff --stat`（377+/30-） |
| 保护目录 | `.omo/`、`.serena/`、`docs/audits/` 仅作为未跟踪目录存在，未入 diff；`.env` 被 gitignore 且未改动 | `git status`、`git check-ignore .env` |
| 越界路径 | 无 `contracts/`、无 Flyway 历史迁移（V1–V34）、无消息 schema 改动 | `git diff --name-only` 扫描 |
| secret 泄漏扫描 | diff 中 0 命中（AKIA/私钥/sk-/AIza/ghp_ 模式） | `git diff | Select-String ...` = 0 |
| `git diff --check` | 无空白错误（exit 0） | 独立复跑 |

验收过程未修改任何代码/测试/产品文档/Git 状态；冒烟所用临时 env 文件与脚本位于系统 TEMP，已删除；冒烟容器/卷已按项目名隔离清理。

---

## 2. A–K 对抗性验证逐项结论

### A. WAITING_USER 是否释放 one-active-per-trip 槽位 —— **PASS**

- 部分唯一索引 `uq_planning_task_one_active_per_trip` 活动集为 `('CREATED','QUEUED','RUNNING','WAITING_USER','RETRYING','CANCELLING')`，**不含 CANCELLED**：`apps/travel-server/src/main/resources/db/migration/V4__create_planning_and_outbox_tables.sql:31-33`。
- 放弃 SQL：`PlanningTaskMapper.abandonWaitingUserOwned` 仅把 owner 的 `status='WAITING_USER'` 行置为 CANCELLED（owner 校验 + 条件更新 + version+1）：`apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskMapper.java:182-193`。
- 活动查询同一集合：`PlanningTaskMapper.existsActiveByTripId` `:195-202`。
- 集成测试：放弃后同 trip 新 CREATE 返回 **202**（`PlanningReviewAbandonIntegrationTest.java:100-101`）。
- 独立冒烟（真实整栈）：放弃后再次创建任务 **202 QUEUED**（`TASK2_AFTER_ABANDON 202`），DB 中被放弃任务 `CANCELLED`。

### B. 是否存在"接受 UNVERIFIED/NEEDS_REPAIR 成为正式版本"的绕过 —— **PASS**

- 唯一版本创建入口 `PlanningCompletionService.handleInScope` 先过四重 fail-closed 门：`schemaVersion==9`（`:83-85`）、report 非空（`:86-88`）、`status==VERIFIED`（`:89-92`）、evaluation 非空（`:93-95`），其后才可能走到版本创建。
- 全仓 grep 确认 `createCandidateVersion` 仅被 `PlanningCompletionService.java:130` 调用（位于 VERIFIED 门之后）；`createReplanVersion`（`:149`）与 `createInitialItinerary`（`:160`）同门。
- Review 路径（WAITING_USER）**从不**建版本：`PlanningReviewService` 只 `markWaitingUser` + 写 review 事件（`PlanningReviewService.java:119-137`），且 `validateReport` 显式拒绝 VERIFIED review（`:189-191`）。
- 遗留直接写版本方法（`ItineraryService.applyEdit/applyEdits/persistEditedVersion`、`ItineraryVersionService.rollback`）存在但**无任何 HTTP 调用方**：控制器 `/edits`、`/edits/commit`、`/rollbacks` 全部路由到 `validateEditCandidate/validateEditCandidates/validateRollback`（`ItineraryController.java:85,111,124`）；`src/main/java` 内 grep `.applyEdit(`/`.rollback(` 无业务调用点（仅测试直调）。属 B8 遗留死代码，不可达，不构成绕过（详见 §4 残留观察）。
- Web 无"接受/强制保存/跳过验证"入口：`apps/web/src` grep 无命中（仅 `GuideIntelligencePanel.vue:450` 的 file-input `accept` 属性，与候选接受无关）；e2e 断言 `接受|强制保存|忽略验证|跳过验证` 按钮数为 0（`feasibility-outcomes.spec.ts:397`）。

### C. WAITING_USER cancel 是否错误产生 cancel-command outbox —— **PASS**

- `PlanningTaskService.cancel` 双路径：先 `cancelOwned`（QUEUED/RUNNING/CANCELLING），失败再 `abandonWaitingUserOwned`（WAITING_USER）；outbox 写入被 `if (!abandonedReview)` 守卫（`PlanningTaskService.java:518-550`），放弃路径 **0 条** cancel-command。
- 集成测试断言 `PLANNING_CANCEL_REQUESTED` outbox 计数为 0（`PlanningReviewAbandonIntegrationTest.java:84-87`）；同时保留 QUEUED cancel 语义测试（`PlanningTaskFlowIntegrationTest.java:70-77` 断言 QUEUED 取消仍写 outbox）。
- 独立冒烟 DB 实测：被放弃任务 `cancelled_events=1, cancel_outbox=0, versions=0`。

### D. 重复 cancel / 迟到 completion / 迟到 review 幂等 —— **PASS**

- 重复 cancel：CANCELLED 状态早退返回稳定响应（`PlanningTaskService.java:508-510`）；集成测试 2 次 DELETE 后 `PLANNING_CANCELLED` 事件仍为 1（`PlanningReviewAbandonIntegrationTest.java:105-109`）；QUEUED 取消幂等（`PlanningTaskFlowIntegrationTest.java:49-78`）。
- 迟到 completion/review 在 CANCELLED 上被状态门拒绝：completion `PlanningCompletionService.java:111-113`、review `PlanningReviewService.java:97-99`；集成测试 `lateCompletionCannotResurrectAnAbandonedTask` / `lateReviewCannotResurrectAnAbandonedTask`（`PlanningReviewAbandonIntegrationTest.java:124-157`）。
- event_id 唯一：DB 约束 `event_id UUID NOT NULL UNIQUE`（`V5__create_itinerary_versions_and_task_events.sql:15`）+ 插入 `ON CONFLICT (event_id) DO NOTHING`（`PlanningTaskEventMapper.java:22`）+ 服务层 dedup（completion `:99-110`、review `:86-96`、progress `:46-53`）。
- 重复 review 投递幂等：`PlanningReviewServiceTest.ignoresRedeliveredReviewEventIdempotently`（`:69-81`）；eventId 跨任务/跨类型拒绝（`:84-104`）；completion eventId 复用拒绝（`PlanningCompletionFlowIntegrationTest.java:918-931`）。
- 附注：并发双 cancel 的败者会得到 409 `PLANNING_TASK_TERMINAL`（乐观更新只赢一次），顺序幂等保证成立；非阻塞。

### E. late progress 是否真正静默 —— **PASS**

- `PlanningProgressService.handle` 检查顺序：identity/trip/trace 归属（`:43-45`）→ eventId 冲突（`:46-53`）→ 终态容忍（`:54-63`，集合含 **WAITING_USER**）→ QUEUED/RUNNING 状态门（`:64-66`）。终态容忍分支直接 `return`：不改 status、不插事件、不抛异常。
- listener 只把 `PlanningEventContractException | PlanningEventRejectedException` 转成 reject/DLQ（`PlanningProgressEventListener.java:25-33`）；容忍分支无异常 → 不触发 DLQ。
- 集成测试 `lateProgressAfterReviewIsIgnoredWithoutTouchingTheTerminalState`（`PlanningReviewFlowIntegrationTest.java:890-908`）：无异常、状态保持 WAITING_USER、progress 事件 0 新增、review 事件唯一。

### F. 单 response 双 terminal 是否只应用一次 —— **PASS**

- 纯模块 `apps/web/src/lib/planning-stream.ts`：`TERMINAL_PLANNING_EVENT_TYPES = {COMPLETED, REVIEW_REQUIRED, FAILED, CANCELLED}`（`:11-16`）；`createTerminalShortCircuit.accept` 首个终态帧 arm、其后全部返回 false（`:27-41`）。
- 接线顺序（`TripWorkspace.vue::attachPlanningStream`）：会话守卫 `isCurrentPlanningRequest`（`:979`）→ `terminalShortCircuit.accept`（`:980`）→ `lastEventId` 更新（`:981`），被忽略帧不污染 Last-Event-ID 游标。
- 单测 9 例（`tests/planning-stream.test.ts`）；e2e `applies a duplicated terminal frame only once and reloads the itinerary once` 断言 `itineraryLoads === 2`（`feasibility-outcomes.spec.ts:554-588`），独立复跑 18/18 全过。
- 重连/replay 不回归：`Last-Event-ID` 携带测试（`feasibility-outcomes.spec.ts:419-486`）通过。

### G. current itinerary 与 candidate 隔离 —— **PASS**

- 放弃 SQL 只 UPDATE `business.planning_task`（`PlanningTaskMapper.java:182-193`），不触碰 `itinerary_version` / `itinerary_feasibility_report` / `itinerary.current_version_id`。
- 集成测试断言放弃后 `current_version_id` 不变、版本/报告计数不变、历史 review 事件保留（`PlanningReviewAbandonIntegrationTest.java:91-96`）。
- e2e 断言放弃后面板消失、正式行程 `Formal itinerary` 保留（`feasibility-outcomes.spec.ts:627-631`）；Web `applyOutcomeState('cancelled')` 清空候选/report（`TripWorkspace.vue:373-378`）。
- 独立冒烟 DB：整栈无正式版本被创建（`itinerary_version_total=0, report_total=0`），被放弃任务无版本。

### H. Compose 默认值真实展开 —— **PASS**

- `scripts/check_compose_defaults.py --with-docker` 独立复跑：静态 OK + `docker compose config --format json` 展开断言 `agent-service.PROVIDER_MODE=="DEMO_ONLY"`、travel-server 两开关 `"true"`。
- 静态来源：`compose.prod.yaml:97`（`${PROVIDER_MODE:-DEMO_ONLY}`）、`:72-73`（`${OUTBOX_PUBLISHER_ENABLED:-true}` / `${EVENT_CONSUMER_ENABLED:-true}`）。
- 与代码默认一致：`application.yml:31-33`（`${...:true}`）；Python `WorkerSettings.resolved_provider_mode` 无配置时返回 `DEMO_ONLY`（`apps/agent-service/src/trip_agent/worker/amqp.py:359-369`），REAL_ONLY+空 key fail-fast（`:346-349`），测试 `test_worker_settings_default_to_demo_only_when_provider_mode_is_unset`（`test_amqp_worker.py:594-605`）。

### I. 开关真实进入 travel-server 容器环境 —— **PASS**

- `compose.prod.yaml` travel-server `environment` 块第 72–73 行显式透传两开关。
- 独立冒烟容器实测：`agent-service printenv PROVIDER_MODE` = `DEMO_ONLY`；`travel-server printenv OUTBOX_PUBLISHER_ENABLED EVENT_CONSUMER_ENABLED` = `true true`。

### J. 全层门禁可复现 —— **PASS**（见 §3 独立复跑表，全部与报告数字一致）

### K. execution-report 声明抽查 —— **基本属实，1 处数量笔误**

- RED→GREEN 记录与代码一致：变更前 `cancelOwned` 状态集无 WAITING_USER（diff 可证 → 旧实现 409）、变更前 progress 终态集无 WAITING_USER（diff 可证 → 旧实现 reject）、变更前 compose 默认 REAL_ONLY（diff 可证 → 脚本 RED）。
- 数字抽查：438 / 1372+37skipped / 323 / 18 / 21 / 覆盖率阈值 80 全部复现一致（覆盖率绝对值的 0.1–0.3 点漂移属 v8 插桩正常运行间噪声，远高于阈值）。
- **笔误**：execution-report §7 声称 `apps/web/tests/PlanningReviewPanel.test.ts`（"+4 例：按钮/文案/emit/忙碌态"），实际该文件由 14 → 17 个测试，**新增 3 例**（按钮+文案、emit、忙碌态），既有的"无接受按钮"测试未被修改。详见 §4 问题 1。
- 另：`check_markdown_links.py` 报告 107 个文件，独立复跑为 108（B12 的 plan/execution-report 计入后数量漂移，非虚假声明）。

---

## 3. 独立复跑结果表

| # | 门禁（workdir） | 命令 | 独立复跑结果 |
| --- | --- | --- | --- |
| 1 | Java 定向（apps/travel-server，JAVA_HOME=LibericaJDK-21，显式 Maven 3.9.11） | `mvn test -Dtest=PlanningReviewAbandonIntegrationTest,PlanningReviewFlowIntegrationTest -DfailIfNoTests=false` | **Tests run: 21, Failures: 0, Errors: 0, Skipped: 0；BUILD SUCCESS** |
| 2 | Java 全量（apps/travel-server） | `mvn verify` | **Tests run: 438, Failures: 0, Errors: 0, Skipped: 0；"All coverage checks have been met"；BUILD SUCCESS；Flyway 新库迁移 32 个到 v34（未新增迁移）** |
| 3 | Python 全量（apps/agent-service） | `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp=C:\Windows\Temp\trip-pilot-b12-accept` | **1372 passed, 37 skipped** |
| 4 | Python lint | `ruff check src tests` + `ruff format --check tests/test_amqp_worker.py` | **All checks passed** / **1 file already formatted** |
| 5 | Web 单测（apps/web） | `pnpm test` | **34 files / 323 passed** |
| 6 | Web 覆盖率（apps/web） | `pnpm test:coverage` | 阈值 80/80/80/80；实测 statements **96.15** / branches **82.63** / functions **95.77** / lines **96.15**；`planning-stream.ts` **100/100/100/100**（vite.config.ts include 已纳入） |
| 7 | Web 类型/构建（apps/web） | `pnpm typecheck` / `pnpm build` | 通过 / built in 9.24s |
| 8 | Web e2e（apps/web，CI=1） | `$env:CI='1'; pnpm test:e2e` | **18 passed** |
| 9 | Compose（仓库根） | `python scripts/check_compose_defaults.py --with-docker` | **静态 OK + docker 展开 OK（DEMO_ONLY / true / true）** |
| 10 | 仓库级（仓库根） | `python scripts/check_markdown_links.py` | **Markdown links valid across 108 files** |
| 11 | 仓库级（仓库根） | `git diff --check` | 无空白错误（exit 0） |
| 12 | 仓库级（仓库根） | `git status --porcelain=v1` / `git diff --cached --name-only` | 与 §1 一致，staged 为空 |
| 13 | DEMO_ONLY 全栈冒烟（隔离项目 `trip-pilot-b12-accept`，WEB_PORT=38080 临时 env） | `docker compose -p trip-pilot-b12-accept -f compose.prod.yaml --env-file <临时env> up -d --build --wait` | 全服务 healthy（含 travel-server/web/agent-service/agent-api/prometheus）；`knowledge-init` 首跑 exit 2 后由 compose 重试成功（与本批无关的瞬时启动问题，报告 §9 已记录同类现象）；容器实测 env：`PROVIDER_MODE=DEMO_ONLY`、两开关 `true`/`true` |
| 14 | B12 主链 API 冒烟（容器内 Python 脚本，未提交） | register → trip → planning-task → poll → **WAITING_USER** → DELETE → **200 CANCELLED** → 重复 DELETE 幂等 → 新任务 **202** | **SMOKE PASS**；DB 真值：被放弃任务 `CANCELLED | cancelled_events=1 | cancel_outbox=0 | versions=0`；`itinerary_version_total=0, report_total=0` |
| 15 | 冒烟清理 | `docker compose -p trip-pilot-b12-accept ... down -v` | 仅删除 `trip-pilot-b12-accept_*` 卷/网络；无残留容器；仓库零改动 |

---

## 4. 发现的问题

### 问题 1（范围内、小修）：execution-report.md §7 测试数量笔误

- 位置：`docs/execution/B12/execution-report.md` 第 105 行。
- 复现：`git show HEAD:apps/web/tests/PlanningReviewPanel.test.ts` 有 14 个 `test(`，工作区版本有 17 个（差值为 **+3**，非 +4）；新增 3 例分别为 `offers only the abandon-candidate action with formal-version-safe wording`（按钮+文案）、`emits abandon exactly once per click`（emit）、`disables the abandon action while a request is in flight`（忙碌态）；既有"无接受按钮"测试未被修改。
- 影响：仅执行报告数字描述不准，不影响任何代码/测试/门禁结果。
- 精确修复方向：将第 105 行 `（+4 例：按钮/文案/emit/忙碌态）` 改为 `（+3 例：按钮+文案 / emit / 忙碌态）`，或 `（+3 例，覆盖按钮/文案/emit/忙碌态四方面）`。执行 Agent 修改后按总控 5.2 状态机重新进入 READY_FOR_REVIEW，验收 Agent 复验该行即可。

### 观察 2（范围外、非阻塞）：B8 遗留直接写版本方法为不可达死代码

- `ItineraryService.applyEdit`（`ItineraryService.java:109-140`）、`applyEdits`（`:208-248`）、`persistEditedVersion`（`:637-682`）与 `ItineraryVersionService.rollback`（`ItineraryVersionService.java:100-170`）可直接创建 USER_EDIT/ROLLBACK 版本并更新 `current_version_id`，绕开 VERIFIED 门。全量 grep `src/main/java` 确认这些方法**无任何 Controller/业务调用点**（控制器均走 `validate*` 路径），仅集成测试直调（如 `ItineraryEditFlowIntegrationTest.java:519`），因此当前不可达、不构成 B 项绕过；B12 未触碰它们。
- 建议（后续批次，不在本批范围）：删除死代码或在方法内硬性断言仅允许 completion 服务调用，杜绝未来代码意外接入。

---

## 5. 最终 Verdict

**NEEDS_SMALL_FIX**

依据：
- A–K 全部验收项中，代码、测试与门禁层面**全部 PASS**（含独立复跑与真实整栈冒烟）；
- 唯一需修复项为批次自带执行报告 `docs/execution/B12/execution-report.md` §7 的一处测试数量笔误（+4 例 → +3 例），属"范围内有明确、有限的小修"，修复后即可转为 PASS；
- 无运行时断链、无门禁绕过、无事务/契约问题；不构成 NEEDS_CORRECTION 或 FAIL。

验收 Agent 已停止，未进入任何后续批次；Git 收口须在本次小修复验 PASS 后另行执行。

---

## 6. 最终复验（B12 复验 Agent，2026-08-14）

- 首轮 A–K 结论摘要：A–I（放弃语义/无接受绕过/无 cancel outbox/幂等/迟到 progress 静默/terminal 短路/候选隔离/compose 默认值/开关入容器）全部 **PASS**；J 全层门禁可复现 **PASS**；K 声明抽查**基本属实**（唯一笔误为 §7 测试数量）。唯一范围内阻塞项为问题 1（execution-report.md §7 笔误），本复验针对该小修逐项核实；观察 2（B8 遗留不可达直写版本方法）维持首轮"范围外、非阻塞"结论。

### 6.1 修正落地核实（问题 1 关闭）

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| §7 该行现状 | 第 105 行现为 `apps/web/tests/PlanningReviewPanel.test.ts`（+3 例，14→17：按钮与文案、emit 每击一次、忙碌态禁用；覆盖任务书“按钮存在/可点/文案/忙碌”四方面），即任务指定的修正文案 | 本文件 §4 问题 1 引用的原行 `（+4 例：按钮/文案/emit/忙碌态）` 已不复存在；对 execution-report.md grep `+4` **0 命中** |
| 仅该行改动、无内容漂移 | `docs/execution/B12/` 为未跟踪目录（`git status` 中 `??`），无 git 基线可比对 `git diff`；以两项替代证据确认无漂移：(a) 全部已跟踪文件 `git diff --stat` = 17 文件 / **377 insertions / 30 deletions**，与首轮验收 §1 记录逐字节一致，修正未触碰任何已跟踪文件；(b) 报告其余声明（438 / 1372+37skipped / 323 / 18 / 21 / 链接数漂移说明）与首轮 A–K 与 §3 记录一致，未出现新声明 | `git diff --stat`；对照本文件 §1/§2K/§3 |
| 无其他残留 | 报告全文无“+4”表述；除第 105 行外内容与首轮验收引用一致 | grep + 逐行对照 |

### 6.2 数字核实（14→17 = +3）

- `git show HEAD:apps/web/tests/PlanningReviewPanel.test.ts` 含 **14** 个 `test(`；工作树版本含 **17** 个 → **Δ=+3**（非 +4）。
- `git diff -- apps/web/tests/PlanningReviewPanel.test.ts` 仅一个插入 hunk、**无任何 `-` 行**，新增 3 个 test()：`offers only the abandon-candidate action with formal-version-safe wording`（按钮+文案）、`emits abandon exactly once per click`（emit）、`disables the abandon action while a request is in flight`（忙碌态）；既有测试（含 `never offers accept / force save / skip verification buttons`）未被修改——与首轮 §4 问题 1 描述一致。
- 定向运行（workdir=apps/web）：`pnpm test -- tests/PlanningReviewPanel.test.ts` → **Test Files 1 passed (1) / Tests 17 passed (17)**，exit 0。

### 6.3 受影响定向门禁重跑

- `python scripts/check_markdown_links.py`（仓库根）→ **Markdown links valid across 109 files**，exit 0（首轮 108 → 现 109 为本验收报告自身计入导致的正常数量漂移，非虚假声明；与报告 §8 的 107 同属文件集合变化）。
- `git diff --check`（仓库根）→ 无空白错误，exit 0。

### 6.4 工作树一致性抽查

- `git status --porcelain=v1`：**17 个 modified**（与首轮 §1 记录完全一致）+ **5 个非保护新增未跟踪条目**（`PlanningReviewAbandonIntegrationTest.java`、`planning-stream.ts`、`planning-stream.test.ts`、`scripts/check_compose_defaults.py`、`docs/execution/B12/`）+ 3 个保护目录（`.omo/`、`.serena/`、`docs/audits/`，仅未跟踪存在）。
- `git diff --cached --name-only`：**空**（staged 为空，验收前/后均未 stage/commit/push）。
- `git diff --name-only`：仅 17 个已跟踪文件；**无 `.omo/`、`.serena/`、`docs/audits/` 条目**；无 `contracts/`、无 Flyway 迁移改动；`.env` 被 gitignore（`git check-ignore .env` 命中）且未改动。
- `git diff --stat` = 377+/30-，与首轮验收记录一致 → **全部业务代码与测试文件内容未变**（本复验唯一新增改动为对未跟踪验收报告自身的追加）。

### 6.5 复验结论

- 范围内唯一问题（execution-report.md §7 测试数量笔误）已真实落地修正：行文 `+3 例，14→17：按钮与文案、emit 每击一次、忙碌态禁用` 与实测 **+3（14→17，17/17 通过）** 完全一致。
- 修正仅发生在未跟踪的执行报告行内，未触碰任何代码/测试/门禁；定向门禁重跑（Web 单测 17/17、链接检查 109 文件、`git diff --check`）全部通过；staged 为空；保护目录未入 diff。
- 范围外观察 2（B8 遗留不可达直写版本方法，无 HTTP 调用方，不构成绕过）维持首轮非阻塞结论，不在本批范围。

## 7. 最终复验 Verdict

**PASS**

依据：
- 首轮 A–K 中代码、测试与门禁层面全部 PASS；
- 唯一小修项（问题 1）已核实真实落地、与实测数字一致，且无任何其他内容漂移；
- 本复验全部定向门禁重跑通过（17/17 单测、链接检查 exit 0、`git diff --check` exit 0），工作树与首轮记录一致；无运行时断链、无门禁绕过、无事务/契约问题，不构成 NEEDS_SMALL_FIX / NEEDS_CORRECTION / FAIL。

**允许 Git 收口的批准文件清单 = 当前 `git status` 中除 `.omo/`、`.serena/`、`docs/audits/` 外的全部改动文件**，即：17 个已跟踪修改（`.env.example`、`README.md`、`apps/agent-service/tests/test_amqp_worker.py`、`apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningProgressService.java`、`PlanningTaskMapper.java`、`PlanningTaskService.java`、`apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningReviewFlowIntegrationTest.java`、`PlanningReviewServiceTest.java`、`apps/web/e2e/feasibility-outcomes.spec.ts`、`apps/web/src/components/PlanningReviewPanel.vue`、`apps/web/src/components/TripDetail.vue`、`apps/web/src/pages/TripWorkspace.vue`、`apps/web/tests/PlanningReviewPanel.test.ts`、`apps/web/vite.config.ts`、`compose.prod.yaml`、`docs/development/代码架构导读.md`、`docs/operations/本地运行指南.md`）+ 5 个未跟踪新增条目（`apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningReviewAbandonIntegrationTest.java`、`apps/web/src/lib/planning-stream.ts`、`apps/web/tests/planning-stream.test.ts`、`scripts/check_compose_defaults.py`、`docs/execution/B12/`）。收口仍须按 plan.md §11 执行（显式路径 add、`git diff --cached --check`、commit message `fix(platform): close local planning lifecycle gaps`、不 amend/squash/push）。

复验 Agent 已停止；未修改除本报告外的任何文件，未 stage/commit/push。
