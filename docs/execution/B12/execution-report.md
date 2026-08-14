# B12 执行报告：Local-first planning lifecycle hardening

- 批次：B12
- 状态：B12_READY_FOR_REVIEW（等待独立验收）
- 关联：`plan.md`（本目录）、[系统完善长期执行与验收总控计划](../../product/系统完善长期执行与验收总控计划.md)

## 1. 开始前 Git 状态（已核对）

- branch：`codex/feasibility-foundation`
- HEAD：`136f0663b792200484c877a07abd06397faa1ec9`（与计划一致）
- staged：空；tracked 工作树：干净
- 仅存在且未处理：`.omo/`、`.serena/`、`docs/audits/`

## 2. RED→GREEN 证据（真实记录）

### 工作组 A：WAITING_USER 显式放弃（Java）

- **RED**（测试 `PlanningReviewAbandonIntegrationTest`，2026-08-14 14:24，surefire）：
  - `abandoningAWaitingUserReviewCancelsLocallyAndReleasesTheActiveTaskSlot:77` → `AssertionError: Status expected:<200> but was:<409>`（现有 `cancelOwned` 不接受 WAITING_USER）；
  - `lateCompletionCannotResurrectAnAbandonedTask:127`、`lateReviewCannotResurrectAnAbandonedTask:148` → 同因（abandon 前置步 409）；
  - `abandonIsOwnerScoped` → 立即通过（GREEN characterization：owner 隔离 404 为既有行为）。
  - 失败原因：`PlanningTaskMapper.cancelOwned` 的 `status IN ('QUEUED','RUNNING','CANCELLING')` 无 WAITING_USER。
- **GREEN**（14:32，同一 surefire 运行）：实现 `PlanningTaskMapper.abandonWaitingUserOwned`（owner + `status='WAITING_USER'` 条件更新）与 `PlanningTaskService.cancel` 双路径分支后，两个测试类合计 **21/21 通过**。
- 中间编译修复：`PlanningReviewServiceTest.FakePlanningTaskMapper` 补齐新接口方法（未实现导致的编译错误，非行为失败）。

### 工作组 B：WAITING_USER 后迟到 progress 幂等忽略

- **RED**（14:30）：`PlanningReviewFlowIntegrationTest.lateProgressAfterReviewIsIgnoredWithoutTouchingTheTerminalState:899` → `PlanningEventRejectedException: Planning task cannot accept progress in status WAITING_USER`（`PlanningProgressService.handle:60`）。
- **GREEN**（14:32）：在 `PlanningProgressService.handle` 的终态容忍集合中加入 `WAITING_USER` 后 **21/21 通过**；任务保持 WAITING_USER、0 条新增 progress 事件、review 事件唯一。

### 工作组 C：Web 单 stream terminal 短路

- 新增纯模块 `apps/web/src/lib/planning-stream.ts`（`createTerminalShortCircuit`）+ `tests/planning-stream.test.ts` 9 例：双 COMPLETED、COMPLETED→REVIEW、REVIEW→COMPLETED、终态后 progress、reload 仅一次、malformed 首帧仍被处理、未知类型不 arm、跨 trip/session 守卫先于短路（wiring 契约）——**GREEN characterization**（纯新模块，测试与实现同批落地，9/9 通过）。
- 行为级 e2e：`applies a duplicated terminal frame only once and reloads the itinerary once`（`itineraryLoads === 2`，重复 COMPLETED 与迟到 progress 被短路）与 `abandons a waiting-user candidate via the cancel API and keeps the formal itinerary`（DELETE 调用 1 次、面板消失、正式行程保留）——CI=1 下 **2/2 通过**（首轮失败仅为定位器歧义 `getByText('规划已取消')` 命中两元素，改 `{ exact: true }` 后通过；功能链路首轮即达预期状态）。
- `TripWorkspace.vue::attachPlanningStream` 接线顺序：会话守卫 → `terminalShortCircuit.accept` → `lastEventId` 更新（被忽略帧不污染游标）。

### 工作组 D：Compose/文档配置一致

- **RED**（check 脚本 + compose 临时回退到旧值）：`FAIL: compose.prod.yaml agent-service must default PROVIDER_MODE to DEMO_ONLY`（旧默认 REAL_ONLY 被锁定为回归）。
- **GREEN**：恢复修复后 `scripts/check_compose_defaults.py` 静态检查 OK；`--with-docker` 展开 `docker compose config --format json` 解析：`agent-service.PROVIDER_MODE == "DEMO_ONLY"`、`travel-server.OUTBOX_PUBLISHER_ENABLED == "true"`、`EVENT_CONSUMER_ENABLED == "true"`。
- Python：`test_worker_settings_default_to_demo_only_when_provider_mode_is_unset`（新增，GREEN characterization——默认值早已存在，测试将其锁定）；既有 `test_real_worker_settings_require_a_secret_amap_key_at_startup`（REAL+空 key fail-fast）与 `test_demo_worker_factory_and_runtime_do_not_allocate_external_resources`（DEMO+空 key 构建 DemoPlanningProvider）继续通过。

## 3. WAITING_USER 新状态机

```text
QUEUED/RUNNING/CANCELLING --DELETE--> CANCELLED   （原有语义，含 cancel-command outbox，不变）
WAITING_USER             --DELETE--> CANCELLED   （新增：显式“放弃候选”，本地转换）
SUCCEEDED/FAILED/CANCELLED             （无出边，不变）
迟到 completion/review 在 CANCELLED 上被状态门拒绝（不变）
```

**是否向 Worker 发送 cancel command：否。** 放弃路径不写 `PLANNING_CANCEL_REQUESTED` outbox（Python 侧该 review outcome 已完成）；仅做本地转换。

**DB / task event / current version 真值表（放弃路径）**：

| 对象 | 结果 |
| --- | --- |
| planning_task.status | CANCELLED（乐观锁：owner + status='WAITING_USER' + version+1） |
| planning_task_event | 新增 1 条 PLANNING_CANCELLED（event_id 唯一；重复放弃不新增） |
| outbox_event | 0 条 cancel-command（冒烟 DB 实测 `cancelled_events=1, cancel_outbox=0`） |
| itinerary_version / itinerary_feasibility_report | 0 条新增（冒烟 DB 实测 versions=0, reports=0） |
| itinerary.current_version_id | 不变 |
| 历史 review event/candidate | 保留（审计） |
| one-active-per-trip 槽位 | 释放（CANCELLED 不在部分唯一索引活动集） |

## 4. 迟到 progress 处理真值表

| task.status | 行为 |
| --- | --- |
| QUEUED/RUNNING | 正常路径：sequence 单调 + markRunning + 插入 progress 事件（不变） |
| SUCCEEDED / FAILED / CANCELLED / **WAITING_USER（新增）** | 静默返回：不改状态、不插事件、不抛异常（listener 不 reject，不进 DLQ） |
| 身份/归属不匹配、eventId 冲突 | 仍 fail-closed（安全检查在容忍分支之前） |

## 5. Web 重复 terminal 测试

- 单测 9 例（`tests/planning-stream.test.ts`）：覆盖任务书场景 1–4、6 与 wiring 契约（场景 5 由既有 `isCurrentPlanningRequest` 四维守卫保持，见 plan §5 说明）。
- e2e 2 例（`feasibility-outcomes.spec.ts`）：单 stream 双 terminal 只应用第一个且 reload 恰 1 次（`itineraryLoads===2`：初始 1 + 终态 1）；WAITING_USER 刷新恢复后放弃成功。

## 6. compose config 最终展开值

- `agent-service.PROVIDER_MODE` = `DEMO_ONLY`（`${PROVIDER_MODE:-DEMO_ONLY}`）
- `travel-server.OUTBOX_PUBLISHER_ENABLED` = `true`；`travel-server.EVENT_CONSUMER_ENABLED` = `true`（新增透传，与 application.yml/.env.example 一致）
- 冒烟容器实测：`printenv PROVIDER_MODE`=DEMO_ONLY；两开关=true；Worker 日志 `provider_mode=DEMO_ONLY`、`planning worker consuming queues=...`

## 7. 精确修改文件清单

实现：

- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskService.java`（cancel 双路径：QUEUED/RUNNING/CANCELLING 原语义 + WAITING_USER 放弃，无 cancel outbox）
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskMapper.java`（新增 `abandonWaitingUserOwned`）
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningProgressService.java`（终态容忍 +WAITING_USER）
- `apps/web/src/lib/planning-stream.ts`（新增：terminal 短路纯逻辑）
- `apps/web/src/pages/TripWorkspace.vue`（短路接线、reviewTaskId/abandonBusy、`handleAbandonCandidate`、applyOutcomeState 清理）
- `apps/web/src/components/PlanningReviewPanel.vue`（放弃候选按钮 + 文案 + emit）
- `apps/web/src/components/TripDetail.vue`（abandonBusy 透传 + abandon 事件上抛）
- `compose.prod.yaml`（PROVIDER_MODE 默认 DEMO_ONLY + 两开关透传）
- `.env.example`（默认值/语义注释）

测试：

- `apps/travel-server/src/test/.../planning/PlanningReviewAbandonIntegrationTest.java`（新增，4 例）
- `apps/travel-server/src/test/.../planning/PlanningReviewFlowIntegrationTest.java`（+迟到 progress 集成例与 progressEvent 构造）
- `apps/travel-server/src/test/.../planning/PlanningReviewServiceTest.java`（Fake 补齐接口）
- `apps/web/tests/planning-stream.test.ts`（新增，9 例）
- `apps/web/tests/PlanningReviewPanel.test.ts`（+3 例，14→17：按钮与文案、emit 每击一次、忙碌态禁用；覆盖任务书“按钮存在/可点/文案/忙碌”四方面）
- `apps/web/e2e/feasibility-outcomes.spec.ts`（mockBaseline 支持 DELETE + 2 新用例）
- `apps/web/vite.config.ts`（coverage include 纳入 planning-stream.ts）
- `apps/agent-service/tests/test_amqp_worker.py`（+默认 DEMO_ONLY 锁定例）

文档与脚本：

- `scripts/check_compose_defaults.py`（新增：静态 + 可选 docker 展开断言）
- `docs/execution/B12/plan.md`（本批计划）
- `docs/operations/本地运行指南.md`（默认值契约 + REAL_ONLY/回退/放弃语义）
- `README.md`（放弃语义与默认模式说明）
- `docs/development/代码架构导读.md`（§5 默认值、§8 SSE 短路、§10 脚本、§13 新增不变量 10）

## 8. 定向与全量门禁数字

| 门禁 | 结果 |
| --- | --- |
| Python 全量 pytest | **1372 passed, 37 skipped**（`.\.venv\Scripts\python.exe -m pytest --basetemp C:\Windows\Temp\trip-pilot-b12-python-3`；`uv run pytest` 在本机静默失败无输出，已记录为环境偏差） |
| ruff check src tests | All checks passed |
| ruff format --check（修改文件） | 1 文件先被 format 修复，复检 clean |
| Java `mvn verify` | **BUILD SUCCESS**：Tests run: 438, Failures: 0, Errors: 0, Skipped: 0；JaCoCo "All coverage checks have been met"；Flyway 新库迁移至 v34（32 个迁移全部应用，未新增迁移） |
| Web `pnpm test` | 34 files / **323 passed** |
| Web `pnpm test:coverage` | 阈值 80/80/80/80；实测 statements 96.09 / branches 82.4 / functions 95.58 / lines 96.09（include 已纳入 planning-stream.ts） |
| Web `pnpm typecheck` / `pnpm build` | 通过 |
| Web e2e（CI=1） | **18/18 passed** |
| Compose 脚本 | 静态 OK + docker 展开 OK（DEMO_ONLY / true / true） |
| DEMO_ONLY 全栈冒烟 | 全服务 healthy；B12 API 冒烟 PASS（详见 §9）；容器实测 env 一致 |
| `scripts/check_markdown_links.py` | 107 个文件链接有效 |
| `git diff --check` | 无空白错误 |
| secret 泄漏扫描 | 无命中 |

## 9. DEMO_ONLY 全栈冒烟（隔离项目 `trip-pilot-b12-smoke`）

- 编排：`docker compose -p trip-pilot-b12-smoke -f compose.prod.yaml --env-file <临时env>` 构建并启动；所有服务 healthy；`knowledge-init` 首次运行 exit 2，**手动重跑 migrate/import 均成功、compose 重试后 exit 0**（与本批改动无关的瞬时启动问题；本批未触碰 agent-service 主代码/Dockerfile/postgres）。
- 环境端口：Windows 排除端口段 8033–8132 覆盖 8080/8081 → 冒烟用 `WEB_PORT=38080`（临时 env 文件，未提交）。
- B12 主链 API 冒烟（临时脚本，未提交）：注册 → 建旅 → 规划 → 终态 **WAITING_USER**（Demo 预期）→ itinerary 404（无正式版本）→ 第二个任务 **409 PLANNING_TASK_ACTIVE**（槽位占用）→ DELETE → **200 CANCELLED** → 重复 DELETE 幂等 → 新任务 **202**（槽位释放）。
- DB 真值（psql）：被放弃任务 `CREATE|CANCELLED|1 条 PLANNING_CANCELLED|0 条 cancel outbox`；新任务 `CREATE|WAITING_USER`；`itinerary_version=0`、`itinerary_feasibility_report=0`。
- 清理：`down -v` 仅删除 smoke 项目卷/网络；既存 `trip-pilot-prod_*` 用户卷未动。

## 10. 未完成项与残留风险

- 无未完成项。
- 残留风险（均不阻塞）：`uv run` 在本机的静默失败未修复（使用仓库文档钦定的 .venv python 作为门禁执行方式）；`mvnw.cmd` 在 `apps/travel-server` 下不存在（任务文本路径与仓库实际不一致，使用导读钦定的显式 Maven 3.9.11 路径）；`knowledge-init` 首次启动的瞬时失败值得在后续批次单独排查（与本批无关）。
- 范围声明：未改已发布消息 schema 与 Flyway 历史迁移；未新增“接受候选”入口；Hard Validation 与 only-VERIFIED 持久化未触碰。

## 11. staged / commit / push 状态

- staged：空；未 commit；未 push（按任务要求，等待独立验收 PASS 后再收口）。

## Verdict

**B12_READY_FOR_REVIEW**
