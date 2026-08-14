# B12 执行计划：Local-first planning lifecycle hardening

- 文档状态：生效中
- 批次：B12
- 关联总控：[系统完善长期执行与验收总控计划](../../product/系统完善长期执行与验收总控计划.md)

## 1. 基线

- branch：`codex/feasibility-foundation`
- 预期 HEAD：`136f0663b792200484c877a07abd06397faa1ec9`
- 开始前状态（已核对）：staged 为空；tracked 工作树干净；仅存在允许且不处理的 `.omo/`、`.serena/`、`docs/audits/`。

## 2. 目标与不变式语义

统一关闭五个缺陷，不得改变既有安全语义：

1. **WAITING_USER 无退出路径且占用 one-active-per-trip 槽位**
   - 新语义：`WAITING_USER --用户放弃候选--> CANCELLED`（显式放弃，**不是**接受候选成为正式版本）。
   - 允许 UNVERIFIED/NEEDS_REPAIR 候选成为正式版本的能力**始终为 0**（现有不变量不变）。
2. **WAITING_USER 后迟到的 PLANNING_PROGRESS 被拒并进 DLQ**
   - 新语义：对 SUCCEEDED/FAILED/CANCELLED/WAITING_USER 后的迟到 progress 幂等忽略：不改 task.status、不新增 progress 事件、不抛会导致 listener reject/DLQ 的异常。
   - 安全校验（identity/trip/task 归属、eventId 冲突、QUEUED/RUNNING 正常路径的 sequence 单调）保持 fail-closed 不变。
3. **Web SSE 对单 response 内重复 terminal frame 缺少直接短路**
   - 新语义：首个 terminal outcome 应用后，本次 stream 内后续 frame 全部忽略；被忽略帧不污染 lastEventId；malformed terminal 仍进入安全失败语义；Last-Event-ID 重连/replay/hydration 不回归。
4. **compose.prod.yaml 的 PROVIDER_MODE 默认值与 local-first 文档/WorkerSettings 不一致**
   - `compose.prod.yaml` 中 `PROVIDER_MODE: ${PROVIDER_MODE:-DEMO_ONLY}`；`WorkerSettings.resolved_provider_mode` 无显式配置时的 DEMO_ONLY 默认保持不变。
5. **Compose 配置漂移收口**
   - `compose.prod.yaml` 显式向 travel-server 传递 `OUTBOX_PUBLISHER_ENABLED: ${OUTBOX_PUBLISHER_ENABLED:-true}` 与 `EVENT_CONSUMER_ENABLED: ${EVENT_CONSUMER_ENABLED:-true}`（与 `.env.example`/`application.yml` 的默认值一致）。

## 3. 状态机变更

`business.planning_task.status`：

```text
新增：WAITING_USER --DELETE /api/planning-tasks/{taskId}（用户放弃候选）--> CANCELLED
不变：QUEUED/RUNNING/CANCELLING --DELETE--> CANCELLED（原有取消，含 cancel-command outbox）
不变：SUCCEEDED/FAILED/CANCELLED 无出边；迟到 completion/review 不得复活 CANCELLED
```

WAITING_USER 放弃的 Java 本地语义（无 Python 参与）：

- 行级/乐观锁保护（owner 校验 + `status='WAITING_USER'` 条件更新 + `version+1`）；
- task → CANCELLED；写一条 `PLANNING_CANCELLED` task event；提交后 `publishAfterCommit` 推送 SSE；
- **不创建** cancel-command outbox（Python 已结束该 review outcome）；
- 不创建 `itinerary_version`、不写 `itinerary_feasibility_report`、不改 `itinerary.current_version_id`；
- 历史 review event/candidate 保留（审计）；
- 重复放弃幂等：CANCELLED 后再次 DELETE 返回稳定 CANCELLED 响应，不产生第二条 terminal event；
- owner 隔离不变；非 owner 得到 404；
- 放弃后 `uq_planning_task_one_active_per_trip` 槽位释放，同 trip 可创建新 planning task。

## 4. 每个工作组的不变量

- **A（放弃候选）**：放弃 ≠ 接受；`planning_task_event.event_id` 唯一 + 单条 PLANNING_CANCELLED；WAITING_USER 放弃路径产生 0 条 outbox；版本/报告/current 三不变。
- **B（迟到 progress）**：终态集合 {SUCCEEDED, FAILED, CANCELLED, WAITING_USER} 后的 progress 是 no-op；安全校验先于容忍分支执行。
- **C（terminal 短路）**：terminal 判断基于 eventType；首次终端事件（含 malformed 处理）后短路；短路先于 lastEventId 更新。
- **D（配置一致）**：compose 展开值 = 文档声明 = 代码默认（DEMO_ONLY / true / true）；REAL_ONLY 显式设置且空 key 仍 fail-fast；DEMO_ONLY + 空 key 可启动。

## 5. RED/GREEN 测试矩阵

| 组 | 测试 | 初始预期 |
| --- | --- | --- |
| A | Java 集成：WAITING_USER 任务 DELETE → 预期 200 CANCELLED；当前实现 409 → **RED** | RED |
| A | Java 集成：放弃后无 cancel outbox、单条 PLANNING_CANCELLED、无版本、current 不变、新 CREATE 可入队 | 随实现新增（先 RED 后 GREEN） |
| A | Java 集成：重复放弃幂等；非 owner 404；CANCELLED 后迟到 completion/review 被拒 | 随实现新增 |
| A | Web 单测：PlanningReviewPanel 渲染“放弃候选”按钮并 emit；不出现“接受/强制保存/跳过验证” | 新按钮前 RED |
| A | Web e2e：WAITING_USER 点击放弃 → DELETE 调用 → cancelled 状态、正式 itinerary 不变 | 新用例 |
| B | Java 集成：review 先落库（WAITING_USER）后 progress 到达 → 无异常、状态不变、0 新增 progress、review 事件唯一 | 当前实现抛异常 → **RED** |
| B | Java 单测/集成：终态后 progress 不触发 listener reject（DLQ 不触发） | 随实现 |
| C | Web 单测（新 `lib/planning-stream.ts`）：双 COMPLETED、COMPLETED→REVIEW、REVIEW→COMPLETED、终态后 progress、reload 只计一次 | 新文件 |
| C | Web e2e：单 stream 双 terminal 帧只应用第一个、reload 计数 1 | 新用例 |
| D | `scripts/check_compose_defaults.py`：静态锁定 compose 默认值与 travel-server 开关；可选 docker compose config 展开校验 | 当前 compose 默认 REAL_ONLY → **RED** |
| D | Python：`WorkerSettings` 无 PROVIDER_MODE → DEMO_ONLY（若缺）；REAL_ONLY+空 key fail-fast；DEMO_ONLY+空 key 建 provider | characterization |

RED 记录要求：测试名、失败原因、修复后关闭证据；characterization test 立即通过则如实记录为 GREEN characterization，不伪造 RED。

## 6. 允许修改路径与禁止路径

允许（实现所需）：

- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskService.java`
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskMapper.java`
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningProgressService.java`
- `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/` 相关测试（新增/扩展）
- `apps/web/src/pages/TripWorkspace.vue`
- `apps/web/src/components/PlanningReviewPanel.vue`
- `apps/web/src/components/TripDetail.vue`（如需透传事件）
- `apps/web/src/lib/planning-stream.ts`（新增，terminal guard 纯逻辑）
- `apps/web/tests/`（新增单测）、`apps/web/e2e/feasibility-outcomes.spec.ts`（新用例）
- `compose.prod.yaml`、`.env.example`（仅注释/说明，不动真实 secret）
- `docs/operations/本地运行指南.md`、`README.md`、`docs/development/代码架构导读.md`、`docs/product/系统完善长期执行与验收总控计划.md`
- `scripts/check_compose_defaults.py`（新增）
- `apps/agent-service/tests/test_amqp_worker.py`（如需补充 WorkerSettings 默认值测试）

禁止：

- 修改已发布消息 schema（`contracts/messaging/*`）或 Flyway 历史迁移（V1–V34）
- 弱化 Hard Validation、UNKNOWN→PASS、允许 UNVERIFIED 生成正式版本
- 增加“接受候选”入口
- 修改 `.env`（真实 secret）、`.omo/`、`.serena/`、`docs/audits/`
- `git add .`/`-A`、`commit -a`、reset/stash/clean/rebase/amend、push
- 用 sleep/随机重试/宽松断言掩盖竞态
- 范围外：真实 Provider 多城市验证、OR-Tools、公开部署、其他可选功能

## 7. 定向、分层与全量门禁

定向（每轮）：

- Java：`mvnw.cmd test -Dtest=<新测试类>`（JAVA_HOME=BellSoft LibericaJDK-21）
- Web：`pnpm test -- <新测试>`、`pnpm test:e2e -- feasibility-outcomes`

全量（四组全部完成后统一执行一次）：

- Python：`uv run pytest --basetemp C:\Windows\Temp\trip-pilot-b12-python`；`uv run ruff check src tests`；新增/修改 Python 文件 `uv run ruff format --check`
- Java：`apps\travel-server\mvnw.cmd verify`（BUILD SUCCESS、0 failures/errors、JaCoCo 通过、Flyway 到现有最新版本）
- Web：`pnpm test`、`pnpm test:coverage`、`pnpm typecheck`、`pnpm build`、`$env:CI='1'; pnpm test:e2e`
- Compose/本地：`docker compose -f compose.prod.yaml --env-file .env.example config`（或安全临时变量注入）；校验 PROVIDER_MODE=DEMO_ONLY、travel-server 两个开关存在；Docker 可用时跑 DEMO_ONLY smoke，只清理本任务测试容器
- 仓库级：`python scripts/check_markdown_links.py`、`git diff --check`、secret 泄漏检查、保护目录不入 diff、`git diff --cached` 为空直到独立验收 PASS

## 8. 明确非目标

- 不接受 UNVERIFIED/NEEDS_REPAIR 候选成为正式版本
- 不改已发布消息契约与历史 Flyway
- 不新增第二套取消 API
- 不改变生产语义声明（compose.prod.yaml 仍是本地整栈文件）
- 不进入真实 Provider 多城市验证、OR-Tools、公开部署或新功能批次

## 9. 完成标志

- 验收场景七.1–15 全部满足；
- 全量门禁全部通过；
- `docs/execution/B12/execution-report.md` 完成，Verdict = `B12_READY_FOR_REVIEW`；
- 保持 unstaged、不 commit、不 push；
- 停止实现，等待独立验收 Agent 产出 `docs/execution/B12/acceptance-report.md`；
- 仅独立验收 `PASS` 后按第 11 节执行 Git 收口（显式路径 add、`git diff --cached --check`、commit message `fix(platform): close local planning lifecycle gaps`、不 amend/squash/push）。
