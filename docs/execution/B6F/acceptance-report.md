# B6F 全链路统一验收报告

- 批次：B6F（Feasibility 全链路统一验收与提交）
- 验收 Agent：B6F 最终验收（只读业务验收，未修改业务代码/测试/契约）
- 日期：2026-08-12
- Verdict：**FAIL（B6F_FIX_REQUIRED）**

## 1. 基线

- branch=`codex/feasibility-foundation` ✓；HEAD=`b05ac8f3c75ffc72bb8c179e5bd9ceac9a1005c1` ✓；staged 空 ✓；tracked 工作树干净 ✓；仅 `.omo/`、`.serena/`、`docs/audits/` 保护目录 untracked ✓；`git diff --check` 通过 ✓；无 upstream ✓
- 提交链祖先核验：`faa8737`（B6J.1 前身/Hard Validation）、`dfc158e`（B6J.1）、`e72b8f6`（B6J.2）、`b05ac8f`（B6W）均为 HEAD 祖先 ✓
- B7A/B7B：NOT_STARTED ✓

## 2. Commit 链

| 提交 | 内容 |
| --- | --- |
| `faa8737` | Hard Validation 11/11、standalone validator、ValidationInputs |
| `dfc158e` | B6J.1 feasibility-gated outcomes |
| `e72b8f6` | B6J.2 Task API/SSE/read model/VersionSummary |
| `b05ac8f` | B6W Web authoritative feasibility（latest discovery、统一 outcome parser、7 E2E） |

## 3. 三条主场景验证

### 场景 1：VERIFIED 正式完成闭环（17/17 成立）

1. Hard Validator 11/11：`validator.py` `_RULE_DISPATCH` 覆盖 `IMPLEMENTED_RULE_IDS` 全 11 条，无 missing（catalog 驱动）✓
2. `build_feasibility_report` 聚合：无 FAIL/UNKNOWN/missing → VERIFIED ✓
3. `processor.py` VERIFIED 分支经 `get_plan_evaluator().evaluate` 生成 evaluation（v9 payload `evaluation: object` 必填）✓
4. v9 completion 无 candidate 字段（`PlanningCompletedPayloadV9` 仅 itinerary/knowledge/factImpacts/provenance/evaluation/feasibilityReport）✓
5. fingerprint：Python `compute_itinerary_fingerprint`（SHA-256，sort_keys+compact+UTF-8+exclude_none=False）→ 模型校验与 payload 一致 → Java `ItineraryFingerprintVerifier.matches` 复算 ✓
6. Java `PlanningCompletedEventParser` schemaVersion!=9 拒绝（"unsupported eventType or schemaVersion"）✓
7-10. `PlanningCompletionService`（@Transactional）：guard identity/dates/baseline → `createReplanVersion`/`createVersion` → task SUCCEEDED → current version 更新（integration：`PlanningTaskFlowIntegrationTest` 14 tests、`PlanningCompletionFlowIntegrationTest` 42 tests 全绿）✓
8. report 与 version 同事务：V33 `itinerary_feasibility_report` 在 completion 事务内写入（`persistFeasibilityReport`），DB CHECK 强制 status='VERIFIED'/schema_version=1/fingerprint 64hex/report_json 与列深一致 ✓
11. task event payload 与 V33 report_json 深结构一致：B6J.2 验收 + `FeasibilityReportContractTest` 48 tests ✓
12. entity refs remap：`FeasibilityEntityRefMapperV4Test` 10 tests（activity/transit remap 为持久化 UUID）✓
13. Task API：`PlanningTaskReadModelIntegrationTest.succeededExposesVerifiedReportAndEvaluationWithoutCandidate`（MockMvc + 真实 Postgres）✓
14. SSE payload 与 DB task event：`PlanningTaskEventHub.toView` 直接 readTree(event.payloadJson())，无转换 ✓
15. Web "已验证"：E2E `renders the authoritative VERIFIED report with the experience evaluation` ✓
16. PlanEvaluation 仅体验质量：PlanEvaluationPanel "仅代表体验质量，不代表硬可行性验证" + E2E 断言 ✓
17. 无 score 推导：扫描确认（feasibility 链路无 overallScore/feasible 推导）✓

### 场景 2：NEEDS_REPAIR review 闭环（13/13 成立）

1. review payload 无 evaluation 字段（`PlanningReviewRequiredPayload`）✓
2. candidate 非空：payload.itinerary（原始树由 Java parser `withValidatedItinerary` 保留为 candidateItinerary）✓
3. fingerprint 与 candidate 一致：Python 模型校验 + Java parser 校验 + `PlanningTaskOutcomeReadModel.readReview` `ItineraryFingerprintVerifier.matches` 复算 ✓
4. task=WAITING_USER：`PlanningReviewService` markWaitingUser ✓
5. 不创建 itinerary/version/report V33 行：review 路径无 version 创建（`PlanningReviewService` 无 createVersion 调用；`PlanningReviewFlowIntegrationTest` 16 tests）✓
6. 不更新 current version ✓（同 5）
7. review task 与 current VersionSummary.planningTaskId 不混淆：`hydrateLatestPlanningTask` 仅 latest 发现 review，current task 只代表正式版本创建者 ✓
8. latest endpoint 可发现 WAITING_USER：`latestReturnsWaitingUserReviewOutcome` integration test ✓
9. Web "待修复"：E2E `shows the NEEDS_REPAIR review panel...` ✓
10. 规则/日期/实体/证据/repair history：FeasibilityReportPanel + E2E（fail rule/STALE evidence/repair history 断言）✓
11. candidate 明确非正式：PlanningReviewPanel "候选行程尚未成为正式版本" + 对照区 ✓
12. 无接受/强制保存/跳过按钮：组件测试 + E2E `toHaveCount(0)` ✓
13. 刷新后真实恢复：E2E `recovers a review-required task through the latest endpoint after a refresh`（current version→旧 SUCCEEDED task、latest→WAITING_USER task）✓

### 场景 3：UNVERIFIED review 闭环（10/10 成立）

1. report.status=UNVERIFIED：`_aggregate_status`（UNKNOWN 或 missing required → UNVERIFIED）✓
2. 由 UNKNOWN/missing 产生，不伪造 FAIL：聚合语义 ✓；`forged-verified-*` fixtures 拒绝 ✓
3. review v1 非 completion v9：processor 非 VERIFIED 分流 ✓
4. task=WAITING_USER ✓
5. evaluation 为空 ✓
6. 不创建正式版本 ✓
7. current 不更新 ✓
8. Web "未验证"：E2E `shows an UNVERIFIED review without any verified wording` ✓
9. UNKNOWN/STALE/CONFLICTING 不显示 VERIFIED/eligible：EvidenceReference 安全不变量（eligible 必须 VERIFIED）+ 组件徽章映射 ✓
10. Demo 缺证据可成候选不能成正式：review 分流 + candidate 隔离 ✓

## 4. Wire 与跨语言一致性

1. completion routing key=`planning.completed`（amqp.py:84）✓
2. review routing key=`planning.review-required`（amqp.py:85，精确匹配）✓
3. outcome publish 显式 null：`exclude_none=False`（amqp.py:625 completion/review 共用路径）✓
4. progress 用 exclude_none=True（190 行）与 failed 用 exclude_none=True（709 行）——既有行为未改变 ✓
5. Python fixture 与 schema 一致：`test_messaging_contract_schemas.py` 26 tests ✓
6. Java parser 读同一共享 fixture：`PlanningCompletedEventParserTest` 54 tests、`PlanningReviewRequiredEventParserTest` 19 tests（使用 contracts/fixtures 共享文件）✓
7. UTF-8 中文一致：fingerprint 序列化 ensure_ascii=False + Java 复算 ✓
8. fingerprint 全链相同：Python 计算 → Java 复算 → V33 report_json → API/SSE 返回（`ck_ifr_report_json_matches_columns` 校验列深一致）✓
9. nullable 字段 wire/Java/Web 一致：exclude_none=False 保留显式 null；Web reader 区分 null 与缺失 ✓
10. Java 单一 FeasibilityReport 权威模型：`feasibility/FeasibilityReport.java`（唯一 record）✓
11. validatorVersion 白名单对齐：Python（feasibility-v1、hard-validator-v1..v4）、Java `FeasibilityReportValidator`（同集合）、Web `VALIDATOR_VERSIONS`（同集合）✓
12. typed ref grammar 对齐：Python `entity_refs.py`（activity/transit 规范 UUID、poi/text 非空）、Java `FeasibilityEntityReferenceCodec`、Web `parseTypedEntityReference`——三方一致 ✓

## 5. 安全与失败场景

A. malformed/forged：Python 模型校验（forged-verified-* fixtures）→ Java parser/read model fail closed（`PlanningTaskReadModelIntegrationTest` 负面用例）→ Web parser malformed。全链 fail closed ✓
B. duplicate delivery：`PlanningTaskIdempotencyTest` 4 tests + completion/review 事件幂等（event_id 唯一约束，`PlanningCompletedEventListener` 幂等）✓
C. stale baseline：`PlanningOutcomeGuard.isStaleTripBaseline/isStaleReplanBaseline` → `persistStaleFailure`（FAILED + STALE_TRIP_VERSION/STALE_ITINERARY_VERSION，不创建版本）✓
D. DB 事务失败：V33 CHECK 约束（status/schema/fingerprint/json 一致性）触发即回滚（completion 事务内）；`TripPaceMigrationIntegrationTest` 验证迁移回滚机制 ✓（本批无新增 migration）
E. 历史版本 feasibility=null：VersionSummary LEFT JOIN 返回 null → Web "无历史验证"（E2E `shows historical feasibility null...`）✓
F. completion v1-v8：`PlanningCompletionService` "Only schemaVersion 9 completions can create a version"（service 层拒绝，绕过 parser 也不能建版本）✓；v7 历史行为不回归（v7 ABANDONED）；v8 schema 文件存在但 runtime 拒绝 ✓

## 6. Task API、SSE 与 latest discovery

1. Task API 六态：ReadModelIntegrationTest 覆盖 QUEUED/RUNNING/SUCCEEDED/WAITING_USER/FAILED/CANCELLED ✓
2. eventType/status/report/candidate/evaluation 联合校验：read model 负面用例（mismatch/missing/malformed 全部 fail closed）✓
3. latest endpoint：owner scoped（SQL JOIN trip.owner_id）、无任务/他人统一 404、`created_at DESC, id DESC`、readOnly、复用 read model ✓（**唯一缺陷见发现 1——测试期望计算，非实现**）
4. SSE live/replay 与 DB 一致（EventHub 直接读 payload）、Last-Event-ID、terminal 语义、owner isolation：既有测试 + Web E2E reconnect ✓
5. Web API/SSE 共用 outcome parser：`readPlanningTaskOutcome`/`readPlanningEventOutcome` 共享 `readTerminalOutcome` ✓
6. malformed terminal 不刷新正式 itinerary：`attachPlanningStream` malformed 分支无 reload ✓

## 7. 全部门禁（独立复跑）

| 门禁 | 结果 |
| --- | --- |
| Python 定向（feasibility/契约/worker/amqp） | **436 passed** |
| Python 全量（独立 basetemp，首次 Windows basetemp PermissionError 已记录并用 `--basetemp=C:\Windows\Temp\opencode\pytest-b6f` 重跑） | **1286 passed, 37 skipped, 0 failed, 0 errors** |
| Python ruff（B6 相关路径） | **All checks passed** |
| Java verify | **BUILD FAILURE**：402 tests，1 failure（见发现 1） |
| Java JaCoCo / Flyway | JaCoCo 运行；Flyway 到 V33，无新增 migration |
| Web unit | **303 passed** |
| Web typecheck / build | 通过 / 通过 |
| Web coverage | **95.97 / 81.64 / 95.45 / 95.97**（statements/branches/functions/lines，≥80） |
| Web E2E | **13 passed** |
| Markdown links | **88 files valid** |
| git diff --check / staged | 通过 / 空 |
| 禁用断言扫描 | B6 相关文件 0；`constraint-parser.test.ts` 5 处 `as any` 为既有基线（非本批引入，非阻断） |
| score 推导扫描 | 无 |
| secrets / protected | 无 secret 进 tracked；保护目录未处理 |

## 8. 架构验收地图

### A. VERIFIED 调用链

`worker.processor.process_planning`（入口）→ `validate_itinerary`（validator.py，11 规则聚合）→ `PlanningCompletedEventV9`（contracts.py:982，VERIFIED 强制 + fingerprint 校验）→ Rabbit `planning.completed`（amqp.py:84/625，exclude_none=False）→ `PlanningCompletedEventParser`（schemaVersion==9、类型/语义/fingerprint）→ `PlanningCompletedEventListener` → `PlanningCompletionService`（@Transactional：guard → createVersion → persistFeasibilityReport V33 → task SUCCEEDED → task_event）→ `PlanningTaskService.toResponse`（terminalMetadata + OutcomeReadModel）→ Task API/SSE → `TripWorkspace.attachPlanningStream`（readPlanningEventOutcome）→ `TripDetail` → `FeasibilityReportPanel`。
- 数据所有权：report 属于正式版本（V33 行 + task event 双写一致）；事务边界：completion 单事务；fail-closed 点：parser（schema/类型）、service（schemaVersion/VERIFIED/stale）、DB CHECK、read model、Web parser。
- 推荐断点：`PlanningCompletionService.handle`、`PlanningTaskOutcomeReadModel.readCompleted`、`readPlanningEventOutcome`、`FeasibilityReportPanel`。
- 最小调试命令：`mvn -pl apps/travel-server -Dtest=PlanningTaskFlowIntegrationTest test`；`pnpm vitest run tests/App.test.ts -t "PLANNING_COMPLETED with VERIFIED"`。

### B. REVIEW 调用链

`worker.processor.process_planning`（非 VERIFIED 分流）→ `PlanningReviewRequiredEvent`（contracts.py:1035，forbid VERIFIED + fingerprint）→ Rabbit `planning.review-required`（amqp.py:85）→ `PlanningReviewRequiredEventParser`（schema v1、WAITING_USER、原始 itinerary 树保留）→ `PlanningReviewRequiredEventListener` → `PlanningReviewService`（markWaitingUser，不建版本）→ task_event → `PlanningTaskService.latest`/`get`（OutcomeReadModel.readReview：非 VERIFIED + fingerprint 复算 + 无 evaluation）→ API/SSE → `TripWorkspace.hydrateLatestPlanningTask`（latest 发现）→ `PlanningReviewPanel`（candidate + report + 正式对照）。
- 数据所有权：candidate 仅存 task event payload（无版本归属）；事务边界：markWaitingUser 单事务；fail-closed：parser、read model（candidate 篡改/fingerprint 不匹配拒绝）、Web parser。
- 推荐断点：`PlanningReviewService.handle`、`PlanningTaskOutcomeReadModel.readReview`、`hydrateLatestPlanningTask`。
- 最小调试命令：`mvn -pl apps/travel-server -Dtest=PlanningReviewFlowIntegrationTest test`；`CI=1 pnpm test:e2e -g "review"`。

### C. 验证核心调用链

`PlanningResult`/`ValidationInputs`（inputs.py）→ `ValidationContext`（context.py：budget/skeleton/inputs）→ 11 canonical rules（rules/core.py、coverage.py、continuity.py、duration.py、meal.py、opening.py）→ `build_feasibility_report`（models.py：聚合 status/summary/missing）→ `compute_itinerary_fingerprint`（fingerprint.py）→ outcome selection（processor.py VERIFIED→v9 / else→review v1）。
- fail-closed：模型 cross-field 语义校验（opening evidence 安全、summary 一致、repair 连续、entity refs）、fingerprint 绑定。
- 推荐断点：`validate_itinerary`、`_aggregate_status`、`_validate_opening_evidence_safety`。

### 推荐阅读顺序（12 文件）

1. `contracts/feasibility-report-v1/`（schema + fixtures）
2. `contracts/planning-completed-event-v9/`、`planning-review-required-event-v1/`
3. `apps/agent-service/src/trip_agent/feasibility/models.py`
4. `apps/agent-service/src/trip_agent/feasibility/validator.py`
5. `apps/agent-service/src/trip_agent/feasibility/fingerprint.py` + `entity_refs.py`
6. `apps/agent-service/src/trip_agent/worker/processor.py` + `contracts.py` + `amqp.py`
7. `apps/travel-server/.../feasibility/FeasibilityReport.java` + `FeasibilityReportValidator.java`
8. `apps/travel-server/.../infrastructure/mq/PlanningCompletedEventParser.java` + `PlanningReviewRequiredEventParser.java`
9. `apps/travel-server/.../planning/PlanningCompletionService.java` + `PlanningReviewService.java` + `PlanningTaskOutcomeReadModel.java`
10. `apps/travel-server/.../planning/PlanningTaskService.java` + `PlanningTaskMapper.java` + `PlanningTaskEventHub.java`
11. `apps/travel-server/.../db/migration/V33__create_itinerary_feasibility_report.sql`
12. `apps/web/src/lib/feasibility.ts` → `TripWorkspace.vue` → `PlanningReviewPanel.vue`/`FeasibilityReportPanel.vue` → `e2e/feasibility-outcomes.spec.ts`

## 9. 高置信度发现

**发现 1（唯一阻断，FAIL 依据）：Java 测试期望计算与 PostgreSQL UUID 排序语义不一致（flaky 测试）**

- 严重度：HIGH（门禁失败；测试缺陷，非业务实现缺陷）
- 文件/行号：`apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningTaskReadModelIntegrationTest.java`，`latestTieBreaksByTaskIdWhenCreatedAtMatches`（约 292-303 行），期望计算行：`UUID expected = firstTaskId.compareTo(secondTaskId) > 0 ? firstTaskId : secondTaskId;`
- 复现场景：`mvn --batch-mode -pl apps/travel-server -Dtest=PlanningTaskReadModelIntegrationTest#latestTieBreaksByTaskIdWhenCreatedAtMatches test`——两次独立运行均失败：
  - 运行 1：expected `6f04d9f1-...` but was `f7ff096d-...`
  - 运行 2：expected `3b8ff043-...` but was `d3047559-...`
- 根因：PostgreSQL 对 UUID 的 `ORDER BY id DESC` 使用**无符号字节序**比较（`f7ff...`/`d304...` 最高字节 ≥0x80 时按更大值排序）；Java `UUID.compareTo` 使用**有符号 long** 比较（最高字节 ≥0x80 时为负数）。测试期望用 Java 语义计算，与 DB 语义不一致；随机 UUID 恰跨符号域时必失败（B6W 复验通过系随机 UUID 未跨符号域的巧合）。
- 实际结果：`mvn verify` BUILD FAILURE（402 tests, 1 failure）
- 期望结果：实现语义正确（`ORDER BY created_at DESC, id DESC` 满足"createdAt 相同使用 id 稳定 tie-break"），测试期望应与 PostgreSQL 排序一致
- 最小修复方向（B6F_FIX 范围，验收不自行修改）：测试的 `expected` 计算改为**无符号字节序比较**（如将 UUID 两段 long 转 unsigned 比较，或直接比较 16 字节数组），或断言返回值为 DB 按字节序更大者；不改实现 SQL、不改其他测试。
- 影响：仅该测试；其余 401 tests 全绿。

## 10. 非阻断观察

1. `constraint-parser.test.ts` 5 处 `as any` 为既有基线代码（非本批引入，与 B6 无关）。
2. Python 全量首次运行 11 errors 为 Windows `C:\Windows\Temp\pytest-of-xx` basetemp 权限问题（环境），独立 basetemp 重跑 0 errors。
3. Web 两个面板单文件 branch coverage <80（已接受观察，全局门槛通过）。
4. `readVersionFeasibilityMetadata` schemaVersion 未强制 ===1（已接受观察，展示路径低风险）。

## 11. Verdict

**FAIL（B6F_FIX_REQUIRED）**

- 三主场景闭环成立、安全场景成立、Python/Web/契约门禁全绿、无真实跨层漂移——业务链路本身 PASS 质量。
- 但 Java verify 门禁失败（1 个确定性可复现的测试缺陷），按判定规则"Java 门禁失败"且"发现测试需修改"→ 必须 FAIL。
- 最小 B6F_FIX 范围：仅修复 `PlanningTaskReadModelIntegrationTest.latestTieBreaksByTaskIdWhenCreatedAtMatches` 的期望计算（对齐 PostgreSQL 字节序），不涉及任何业务代码/契约/其他测试。

## 12. 是否允许推进 B7A

**否**。待 B6F_FIX 修复并重验 Java verify 全绿后，重新进行 B6F 验收；B7A 保持 NOT_STARTED。

## 13. 结束状态

- 未修改任何业务代码/测试/契约/Flyway/Rabbit
- 总控计划 B6F 状态已更新为 `NEEDS_CORRECTION（未提交）`（FAIL 指令要求）
- 未 stage/commit/push；无 upstream；保护目录未处理
- 唯一新增永久文件：`docs/execution/B6F/acceptance-report.md` 与总控计划状态行更新

# B6F 重验轮（第二轮最终验收）

- 复验 Agent：B6F 最终验收（重验）
- 日期：2026-08-12
- 结论：**FAIL（B6F_FIX_REQUIRED，与首轮一致）**

## 重验基线

- branch=`codex/feasibility-foundation`；HEAD=`b05ac8f3c75ffc72bb8c179e5bd9ceac9a1005c1`（未变）；staged 空；tracked 工作树仅总控计划（上轮 FAIL 状态行）；**无任何 Java/测试改动（B6F_FIX 未执行）**
- 首轮发现的测试缺陷（`latestTieBreaksByTaskIdWhenCreatedAtMatches` 期望计算与 PostgreSQL 字节序不一致）仍然存在

## 环境故障记录（非业务）

- 首轮验收后至本轮，Docker Desktop 停止运行：`docker version` 连接失败（`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`），`~/.testcontainers.properties` 指定 NpipeSocket 策略
- 首次完整 verify 因此出现 177 errors（Spring Testcontainers ApplicationContext 加载失败，`InvalidPathException: Illegal char <">` 来自 Testcontainers DockerMachineClient 探测），非业务/测试逻辑问题
- 安全替代：启动 Docker Desktop（`C:\Program Files\Docker\Docker\Docker Desktop.exe`），等待 daemon 就绪（28.5.1）后重跑完整 verify

## 重验门禁

| 门禁 | 结果 |
| --- | --- |
| Python 定向/全量/ruff | 沿用首轮独立结果：436 passed / 1286 passed+37 skipped / All checks passed（本轮代码未变，未重跑） |
| Java verify（Docker 恢复后） | **BUILD FAILURE：402 tests，1 failure，0 errors**——`latestTieBreaksByTaskIdWhenCreatedAtMatches` 第三轮断言失败：expected `53564846-34b7-42a1-87e8-72b38c8637dd` but was `975cbf6d-4571-4770-ad8b-aa1f43a46312`（Postgres 字节序返回 0x97 开头 UUID，Java compareTo 期望 0x53 开头） |
| Flyway | 到 V33（日志确认），无新增 migration |
| Web | 沿用首轮独立结果：303 / 95.97-81.64-95.45-95.97 / typecheck+build / E2E 13（本轮代码未变，未重跑） |
| 仓库级 | 沿用首轮：88 files valid / diff --check / staged 空 / 无禁用断言（B6 范围）/ 无 score 推导 / 保护目录未处理 |

## 三轮独立复现（确定性缺陷证据）

| 运行 | expected（Java compareTo） | actual（PostgreSQL 字节序） |
| --- | --- | --- |
| 1（首轮 verify） | `6f04d9f1-...`（0x6f） | `f7ff096d-...`（0xf7） |
| 2（首轮单测重跑） | `3b8ff043-...`（0x3b） | `d3047559-...`（0xd3） |
| 3（本轮 verify） | `53564846-...`（0x53） | `975cbf6d-...`（0x97） |

规律完全一致：随机 UUID 对中恰有一个最高字节 ≥0x80（Java 视为负数）时，Java `UUID.compareTo`（有符号）与 PostgreSQL `ORDER BY id DESC`（无符号字节序）相反 → 断言必失败（触发概率约 50%，即 flaky）。实现 SQL 语义正确（满足"createdAt 相同使用 id 稳定 tie-break"）。

## 重验结论

- 业务链路（三主场景、wire 一致性、安全场景）质量结论不变：无跨层漂移、无业务功能缺陷
- **B6F_FIX 未执行**：测试缺陷仍存在，Java verify 门禁仍失败
- 最小 B6F_FIX 范围（不变）：仅修 `PlanningTaskReadModelIntegrationTest.latestTieBreaksByTaskIdWhenCreatedAtMatches` 的期望计算——用与 PostgreSQL 一致的无符号字节序比较（或断言 DB 字节序更大者），不涉及实现 SQL、不涉及其他测试、不涉及任何业务代码/契约
- B7A/B7B：NOT_STARTED，不允许推进 B7A
- 结束状态：未修改任何业务代码/测试/契约；总控计划 B6F 状态行已更新（含三轮复现证据）；未 stage/commit/push；无 upstream；保护目录未处理

# B6F_FIX 最终独立复验

- 复验 Agent：B6F_FIX 最终独立验收（未参与实现修复）
- 日期：2026-08-12
- 结论：**PASS（授权 B6F Git 提交收口）**

## 前置状态

- branch=`codex/feasibility-foundation` ✓；HEAD=`b05ac8f3c75ffc72bb8c179e5bd9ceac9a1005c1` ✓；staged 空 ✓；Docker Client/Server 28.5.1 可用 ✓
- 未提交状态符合预期：`M PlanningTaskReadModelIntegrationTest.java`（修复）、`M 总控计划`（既有）、`?? docs/execution/B6F/`、`?? .omo/`、`?? .serena/`、`?? docs/audits/`

## 精确 diff 范围

唯一代码 diff：`apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningTaskReadModelIntegrationTest.java`（+60 行）。生产代码/SQL/契约/Python/Web 零改动；生产 SQL `ORDER BY planning_task.created_at DESC, planning_task.id DESC`（PlanningTaskMapper.java:85）未修改。

## 原三轮 flaky 根因

Java `UUID.compareTo` 对两个 long 做**有符号**比较；PostgreSQL 对 uuid 按 **16 字节无符号大端**排序。随机 UUID 恰有一个最高字节 ≥0x80 时两者相反（触发概率约 50%）。三轮独立断言失败：`6f04d9f1`/`f7ff096d`、`3b8ff043`/`d3047559`、`53564846`/`975cbf6d`。

## helper 证据

`compareAsPostgresUuid(UUID left, UUID right)`（测试类内私有静态）：
1. 先 `Long.compareUnsigned(left.getMostSignificantBits(), right.getMostSignificantBits())`；
2. 非零即返回；相等时 `Long.compareUnsigned(left.getLeastSignificantBits(), right.getLeastSignificantBits())`。
与 PostgreSQL 无符号字节序语义一致。`latestTieBreaksByTaskIdWhenCreatedAtMatches` 的 expected 改用该 helper，不再用 `UUID.compareTo` 作为 DB 排序期望。无伪修复（无 SELECT max(id)、无复制 SQL、无随机重试、无字符串排序、无 id()/对象地址、未放宽或删除断言）。

## 固定边界回归

`postgresUuidOrderingTreatsBothHalvesAsUnsigned`：
- most-significant：`7fffffff-ffff-ffff-ffff-ffffffffffff` vs `80000000-0000-0000-0000-000000000000`——断言 Java `compareTo < 0`（顺序与 DB 不同）且 `compareAsPostgresUuid` 判定 `8000...` 更大（DB 语义）✓
- least-significant：`00000000-0000-0000-7fff-ffffffffffff` vs `00000000-0000-0000-8000-000000000000`——同断言（后者按无符号字节序更大）✓
- 全部固定 UUID，不依赖随机数或 DB 返回值构造期望 ✓

## 独立复跑结果

| 门禁 | 结果 |
| --- | --- |
| 固定边界 + flaky 测试 | **2/2 passed, BUILD SUCCESS** |
| flaky 测试独立复跑（2 次） | **2/2 passed, BUILD SUCCESS**（另含实现轮 3 次，共 5 次连续通过） |
| 整个测试类 | **28/28 passed**（原 27 + 新增边界测试 1） |
| `mvn verify` | **403 tests, 0 failures, 0 errors, BUILD SUCCESS**；JaCoCo 通过；Flyway 到 **V33**（33 migrations validated），无新增 migration |
| 机械检查 | Markdown links **89 files valid**；`git diff --check` 通过；staged 空 |

## B6F 业务链路证据复核

本修复仅改变 Java 测试，业务实现与 HEAD 均未变，Python/Web 证据沿用同基线（不虚构重跑）：Python 定向 436 / 全量 1286 passed+37 skipped / Ruff 通过；Web unit 303 / coverage 95.97-81.64-95.45-95.97 / typecheck+build / E2E 13。三条主链（VERIFIED completion、NEEDS_REPAIR review、UNVERIFIED review）与安全场景（routing/null/fingerprint/typed refs 一致、forged/malformed/未知 validatorVersion fail closed、duplicate 幂等、stale baseline 拒绝、事务回滚、v1-v8 拒绝、历史 null 不伪装）结论不受影响。

## Verdict

**PASS**。修复语义正确（helper 两段无符号比较与 PostgreSQL 一致）、固定边界回归覆盖 0x7f/0x80 两端、原 flaky 测试连续 5 次独立通过、全量 Java verify 全绿、生产 SQL 与业务实现零改动。授权 B6F Git 提交收口（3 文件：Java 测试修复 + acceptance-report + 总控计划）。
