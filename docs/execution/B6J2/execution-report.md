# B6J.2 执行报告

- 批次：B6J.2（Java Task Event、SSE、Task API、VersionSummary 闭环 + F5 typed refs）
- 分支：`codex/feasibility-foundation`
- 已提交基线：`dfc158e9b1f56c79ece1b6419027435657797cf9`
- 计划：[plan.md](plan.md)
- 状态：READY_FOR_REVIEW（B6J.2.1 验收修复完成，输出 `B6J2_FIX_READY_FOR_REVIEW`）
- 最后成功命令：见各组记录

## R0：代码事实核对（characterization）

本组先做只读核对，不改代码。逐项记录事实：

- [x] PlanningCompletionService.handle/report 持久化：`persistFeasibilityReportIfPresent` 写 V33 report_json（约 134-171），`CompletionPayload`（约 407-421）**无 feasibilityReport 字段**（R2 断点）
- [x] CompletionPayload（约 407-421）：仅 status/runId/version/provider/provenance/evaluation，无 feasibilityReport ✓
- [x] PlanningReviewService.ReviewPayload（约 101-112、152-161）：已保存 status/runId/provider/candidateItinerary/knowledge/factImpacts/providerProvenance/feasibilityReport ✓
- [x] PlanningTaskEventMapper.findLatestTerminal（约 61-70）：仅 PLANNING_COMPLETED/PLANNING_FAILED，**无 PLANNING_REVIEW_REQUIRED**（R3 断点）
- [x] PlanningTaskService.toResponse/readTerminalMetadata（约 395-458）：仅 evaluation 与旧终态元数据，**无 feasibilityReport/candidateItinerary**（R3 断点）；PlanningTaskResponse（约 537-582）无这两个字段
- [x] PlanningTaskEventHub.subscribe/replay（约 37-60）：`isTerminal`（约 112-115）**无 PLANNING_REVIEW_REQUIRED**（R4 断点）；`publishAfterCommit` 用 `TransactionPhase.AFTER_COMMIT` ✓
- [x] PlanningTaskEventStreamService.TERMINAL_STATUSES（约 15-33）：{SUCCEEDED, FAILED, CANCELLED}，**无 WAITING_USER**（R4 断点）
- [x] ItineraryVersionMapper.findAllOwned/VersionSummaryRecord（约 17-32、107-119）：**无 LEFT JOIN report**（R5 断点）
- [x] ItineraryVersionService.list/VersionSummary（约 44-53、443-448）：无 feasibility 嵌套 ✓
- [x] ItineraryFeasibilityReportMapper：V33 insert/find 可用 ✓
- [x] FeasibilityEntityRefMapper.remapOne（约 71-92）：仅 legacy UUID heuristic，任意可解析 UUID 都尝试映射（F5 断点）
- [x] Python feasibility：`VALIDATOR_VERSION = "hard-validator-v3"`（需 v4）；rules/core.py DUPLICATE_POI 输出 `poi_id`；continuity.py ROUTE_ENDPOINT 用 `_activity_ref`（activity_id/fallback poi）、CROSS_DAY 用 `accommodation.provider_poi_id`；opening.py activity_id/fallback poi；duration.py `_activity_ref`；coverage.py `place`（must-visit 名）
- [x] 契约：feasibility-report-v1、completion-v9、review-v1 schema 与 fixtures 已读；fixture 目录 6 个

**R0 结论**：全部断点确认属实，characterization 与既有测试/验收一致（不伪造 RED）。

## R1：F5 typed refs 与 validator v4

### RED

- `tests/feasibility/test_entity_refs.py`（新增 30 用例）：`ModuleNotFoundError: No module named 'trip_agent.feasibility.entity_refs'` —— 模块不存在
- 既有 feasibility 测试 11 个失败（v3→v4 迁移）：validator version 断言、DUPLICATE_POI/ROUTE_ENDPOINT/CROSS_DAY/MUST_VISIT/VISIT_DURATION 的 affected_entity_refs 断言

### GREEN

- 新增 `src/trip_agent/feasibility/entity_refs.py`：EntityReferenceKind、encode_activity_ref/encode_transit_ref/encode_poi_ref/encode_text_ref、parse_entity_ref/validate_entity_ref/decode_entity_ref（严格 grammar：首冒号分隔、activity/transit 规范小写 UUID、poi/text 非空可含冒号、≤200 字符、禁控制字符、未知 kind/裸 UUID/无前缀 fail closed）
- `validator.py`：VALIDATOR_VERSION v3→v4
- `models.py`：`_validate_semantics` 增加 validator_version 参数 + `_validate_entity_refs`（v4 严格校验 rule refs）+ `_validate_repair_entity_refs`（v4 严格校验 repair refs；v1-v3 宽松）
- 规则层：core.py DUPLICATE_POI → `poi:`；continuity.py `_activity_ref` → activity:/poi: fallback、accommodation → poi:；opening.py → activity:/poi:；duration.py → activity:/poi:；coverage.py → text:
- 迁移 11 个既有断言至 typed refs（含测试中 provider_poi_id 输入保持原始值、断言带前缀）

### 定向结果

- `uv run pytest tests/feasibility`：**356 passed**
- `uv run pytest tests/test_planning_outcome_events.py tests/test_planning_outcome_flow.py`：**19 passed**

### 未改变的控制组

- feasibility-report-v1/completion-v9/review-v1 schemaVersion 未变；envelope 版本未变
- v3 legacy heuristic 未删（FeasibilityEntityRefMapper 按 validatorVersion 分派，v3 走旧算法）

### R1 Java 侧

- RED：`FeasibilityEntityReferenceCodecTest`（10 用例）编译失败（类不存在）；`FeasibilityEntityRefMapperV4Test`（10 用例）7 失败（无 v4 分派）
- GREEN：`FeasibilityEntityReferenceCodec.java`（与 Python 同 grammar）；`FeasibilityEntityRefMapper` v3/v4 分派（v4 严格 activity/transit 映射 + poi/text 保留 + 未知版本 fail closed；v3 legacy 保持）；既有 `FeasibilityEntityRefMapperTest` 6 用例补 validatorVersion=v3
- 定向：codec 10 + mapper V4 10 + mapper legacy 6 = **26 passed**
- fixtures：completion-v9/review fixtures 更新为 `hard-validator-v4` + typed refs（`poi:` 前缀），经 Python 模型 round-trip
- 回归：Java parser/contract/review-flow 104 passed；Python 401 passed

## R2：completion report 单一持久化结果

- RED：`PlanningCompletionFlowIntegrationTest#completionTaskEventPayloadContainsVerifiedReportMatchingV33` —— 断言 PLANNING_COMPLETED task event payload 含 `feasibilityReport` 且与 V33 `report_json` 深结构相等、activity/transit refs 为持久化 ID；RED 失败（payload 无 report）
- GREEN：`PlanningCompletionService` —— `persistFeasibilityReportIfPresent` 改为 `persistFeasibilityReport` 返回 remapped report JSON；同一 JSON 既写 V33 `report_json` 也作为 `CompletionPayload.feasibilityReport`（JsonNode）写入 task event payload，两处永不发散；补 `JsonNode` import
- 回归：PlanningCompletionFlowIntegrationTest 39 + PlanningReviewFlowIntegrationTest 4 = **43 passed**

## R3：Task API read model latest outcome

- RED：`PlanningTaskReadModelIntegrationTest`（新增 4 用例）—— review 后 GET 缺 `feasibilityReport`/`candidateItinerary`（response 无字段）、completion 后 GET 缺 report、真值表 WAITING_USER/SUCCEEDED 步骤缺 report、malformed payload 静默返回 nulls；malformed 测试初版用 `{not-json` 被 jsonb 列拒绝（测试自身修正为合法 JSON 非对象 `[]`）
- GREEN：`PlanningTaskEventMapper.findLatestTerminal` 增加 `PLANNING_REVIEW_REQUIRED`；`PlanningTaskService` —— `PlanningTaskResponse`/`TerminalMetadata` 增加 `feasibilityReport`/`candidateItinerary`（JsonNode），`readTerminalMetadata` 解析两字段 + **非对象 payload fail closed**（`IllegalStateException`），新增 `optionalNode` helper
- 定向：PlanningTaskReadModelIntegrationTest **4 passed**；回归 Task/Review/Completion Flow **57 passed**

## R4：SSE live/replay

- RED：`PlanningReviewFlowIntegrationTest` 新增 2 用例 —— replay（任务 WAITING_USER 后带 Last-Event-ID 订阅，应回放 PLANNING_REVIEW_REQUIRED 并终止流）与 live（已订阅者收到实时 review 事件后流终止 + payload 深结构断言）；RED 均以 10s async 超时失败（review 事件未终止流）
- GREEN：`PlanningTaskEventHub.isTerminal` 增加 `PLANNING_REVIEW_REQUIRED`；`PlanningTaskEventStreamService.TERMINAL_STATUSES` 增加 `WAITING_USER`；修复 `PlanningReviewService` 发布路径 —— 原直接发布内存中 `id=null` 的 record（hub `send` 对 null id 拆箱 NPE，live 流永不终止），改为 `findByEventId` 读回存储 record 再发布（与 completion 的 `insertTaskEvent` 模式一致），新增 `stored()` helper（handle + persistStaleFailure 两处）
- 定向：2 个新 SSE 用例 **2 passed**；回归 Task/Review/Completion Flow **59 passed**

## R5：VersionSummary LEFT JOIN

- RED：`ItineraryEditFlowIntegrationTest#listsVersionSummariesWithNestedFeasibilityMetadataAndNullForHistory` —— completed v1（带 V33 report）应嵌套 feasibility metadata（reportId/schemaVersion/validatorVersion/status/itineraryFingerprint/validatedAt 与 V33 行一致），USER_EDIT v2（无 report）应 `feasibility: null`；RED 失败于 `$[1].feasibility.reportId` 无值
- **RED 测试前提修正**（非生产缺陷修复）：初版对历史版本用 `doesNotExist()`，假设 null 字段会被省略；实际 Spring Boot 默认序列化显式 `"feasibility": null`（application.yml 无 jackson inclusion 配置、无 @JsonInclude）。改为 `.value(nullValue())` 并补 validatedAt 断言（经 `report_json ->> 'validatedAt'` 与 V33 对齐）
- GREEN：`ItineraryVersionMapper.findAllOwned` 单次 **LEFT JOIN** `itinerary_feasibility_report`（不产生 N+1），`VersionSummaryRecord` 增加 6 个 report 元数据列；`ItineraryVersionService` 新增嵌套 `FeasibilityMetadata` record（reportId/schemaVersion/validatorVersion/status/itineraryFingerprint/validatedAt），`VersionSummary` 增加 feasibility 字段，`list()` 映射（reportId 为 null → feasibility null；summary 不含完整 reportJson）
- 定向：新用例 **1 passed**；回归 ItineraryEditFlowIntegrationTest 24 + TransitEdit 3 + EntityRefMapper 16 = **43 passed**（排序/current/owner isolation/rollback 未变）

## R6：review 事务回归

- `PlanningReviewFlowIntegrationTest#taskEventInsertFailureRollsBackTheWholeReviewTransaction`（新增）—— 用 `BEFORE INSERT` trigger 强制 `planning_task_event` insert 失败，断言：`reviewService.handle` 抛 `forced task event failure` 且**整个事务回滚**（task 停留 QUEUED 原版本、仅原始 QUEUED 事件保留、无 itinerary/version/report 残留）
- 结果：**1 passed**，现有 `@Transactional` + `requireOne` 已满足契约，未做生产代码改动（回归锁定测试）

## R7：文档与事实收口

- `docs/architecture/规划工作流.md`：差距表校验维度更新为 `hard-validator-v4` + typed refs + 已接入运行时门禁；任务状态机增加 `WAITING_USER`（PLANNING_REVIEW_REQUIRED，SSE 终止）；B6 段补充 task event payload 与 V33 一致、Task API latest outcome 真值表、SSE 终止/Last-Event-ID/owner 隔离、VersionSummary LEFT JOIN 嵌套 feasibility
- `docs/architecture/事件契约.md`：SSE 协议终态集合加入 `PLANNING_REVIEW_REQUIRED`（WAITING_USER 终止）与 `feasibilityReport` 字段；B6 段补充 completion payload 与 V33 深结构一致、review payload 保留 candidate/report、typed refs（v4）语法与 fail closed
- `docs/architecture/行程真实性与旅行骨架.md`：B6 段补充 typed refs（v4）/legacy v3 解读、V33 与 task event payload 同一 remap 结果
- `docs/product/项目路线图.md`：B6 节更新 validator v4 + typed refs + Task API/SSE/VersionSummary 已接入
- `docs/product/系统完善长期执行与验收总控计划.md`：B6J.2 状态表更新为「实现完成（未提交）」，符合「未提交工作不得写成 COMMITTED」约定

## 验证门禁

- [x] 文档链接检查：`python scripts/check_markdown_links.py` —— **84 files valid**
- [x] `git diff --check` —— 无 trailing whitespace/space-before-tab 错误
- [x] `git diff --cached --name-only` —— 为空（全部 unstaged）
- [x] Python 全量：`uv run python -m pytest`（Windows 下 `uv run pytest` 直接调用输出异常，改用 `python -m` + `--basetemp` 绕过系统临时目录权限）—— **1280 passed, 37 skipped**
- [x] Python ruff：本批文件 `check` 通过；`format` 修正 6 个本批文件（R1 迁移遗留 F541/E501 + 格式），格式化后重跑 375 定向 + 1280 全量均绿
- [x] Java 全量：`mvn --batch-mode -pl apps/travel-server verify` —— **346 tests, 0 failures, 0 errors, skipped 0**，BUILD SUCCESS，JaCoCo check 通过，Flyway V33 迁移通过
- [x] 单测修复：`PlanningReviewServiceTest` 的 `FakePlanningTaskEventMapper.insert` 按真实语义回填 `eventByEventId`（R4 引入 `stored()` 读回后单测曾 4 errors → 12/12 修复）

## 残留边界

- Web UI 的 WAITING_USER 预览、WAITING_USER 生命周期界面、编辑后验证仍属后续批次（B7/B8）
- v3 legacy heuristic 保留（按 validatorVersion 分派），未删除
- 本批次保持 unstaged、未 commit、未 push，等待 B6J.2 重新独立验收（B6J.2 的独立验收不是 B6F；B6F 需 B6J.2、B6W 均验收 PASS 并提交后才开始）
- 总控计划 B6J.2 状态表更新为「实现完成（未提交）」，符合「未提交工作不得写成 COMMITTED」约定

## 完成标志

`B6J2_READY_FOR_REVIEW`（全部 R0-R7 与门禁通过，保持 unstaged、未 commit、未 push）

---

# B6J.2.1 验收修复

独立验收结论为 NEEDS_CORRECTION（A 组 review 接受非法 v4 refs、C 组 read model 透传非法组合、D 组 SSE 测试用 containsString、G 组报告残留）。本批次修复 A/C 严重缺陷并补齐 B/D/G 证据缺口。

## 1. A 组缺陷 RED 复现与修复（v4 typed refs 语义门禁）

### RED 复现（验收 probe 实证 + 新增测试）

- `PlanningReviewRequiredEventParser` 接受：v4 裸 UUID ref、v4 `unknown:value`、未知 validatorVersion + typed refs、未知版本 + 空 refs，全部进入 WAITING_USER
- Python 模型拒绝同类输入（跨语言漂移）
- 根因：`FeasibilityReportValidator` 不校验 `affectedEntityRefs`；review 路径不经过 `FeasibilityEntityRefMapper`

### RED 测试（全部先失败后通过）

- `PlanningReviewRequiredEventParserTest` +6：`rejectsV4BareUuidEntityRef`、`rejectsV4UnknownKindEntityRef`、`rejectsV4NonCanonicalActivityUuidRef`、`rejectsV4InvalidRepairAttemptRef`、`rejectsUnknownValidatorVersionWithTypedRefs`、`rejectsUnknownValidatorVersionEvenWithEmptyRefs`
- `PlanningCompletedEventParserTest` +5：`rejectsV9BareUuidEntityRef`、`rejectsV9UnknownKindEntityRef`、`rejectsV9NonCanonicalActivityUuidRef`、`rejectsV9InvalidRepairAttemptRef`、`rejectsV9UnknownValidatorVersion`（`amapV9Event` 显式设 v4，因 Java 内存 fixture 仍为 v3）
- `FeasibilityReportContractTest` +5：`v4RuleResultRefsAreValidatedStrictly`、`v4RepairAttemptRefsAreValidatedStrictly`、`v4ValidTypedRefsPass`、`legacyVersionsKeepUnprefixedRefsCompatible`（feasibility-v1/v1/v2/v3）、`unknownValidatorVersionFailsClosedEvenWithValidTypedRefs`
- service 直调防线：`PlanningReviewFlowIntegrationTest` +2（`serviceRejectsInvalidV4ReportEvenWhenCalledDirectly`、`serviceRejectsUnknownValidatorVersionEvenWhenCalledDirectly`，绕过 parser 用 `treeToValue`）；`PlanningCompletionFlowIntegrationTest` +2（`serviceRejectsInvalidV4ReportEvenWhenCalledDirectly`、`serviceRejectsUnknownValidatorVersionEvenWhenCalledDirectly`）

### GREEN 实现

- `FeasibilityReportValidator`：显式版本集合（`feasibility-v1` + `hard-validator-v1/v2/v3` 为 legacy，`hard-validator-v4` 为 v4，其余**直接拒绝**）；v4 时对 RuleResult 与 RepairAttempt 的每个 ref 调 `FeasibilityEntityReferenceCodec.parse`（未知 kind/裸 UUID/非规范 UUID/空值 fail closed）
- `PlanningReviewService`：入口 `validateReport()`（validator + status 非 VERIFIED），非法 → `PlanningEventRejectedException`（reject，不置 WAITING_USER）
- `PlanningCompletionService`：`persistFeasibilityReport` 入口调 validator，非法 → `IllegalStateException`（事务回滚，不建 version）
- parser/service 双层 fail-closed；不复制第二套 grammar（复用 codec）

### Java/Python validatorVersion 真值表（一致）

| validatorVersion | Java | Python |
| --- | --- | --- |
| feasibility-v1 / hard-validator-v1/v2/v3 | legacy，unprefixed refs 接受 | 同 |
| hard-validator-v4 | typed refs 严格；非法 refs 拒绝 | 同 |
| hard-validator-v5 / arbitrary / 未知 | 直接拒绝 | 同（修复前 Python 把未知当 strict） |

## 2. F2：Python validatorVersion 与 Java 对齐

### RED

- `test_feasibility_models.py` +6：`test_v4_accepts_valid_typed_refs`、`test_v4_rejects_bare_ref`、`test_legacy_versions_accept_bare_refs`、`test_v5_rejects_even_with_valid_typed_refs`、`test_arbitrary_validator_rejects_with_empty_refs`、`test_repair_attempt_refs_are_strict_in_v4`
- RED 确认 3 失败（v5/arbitrary 被当 strict 接受、feasibility-v1 被当 strict 拒绝）

### GREEN

- `models.py`：`_LEGACY_VALIDATOR_VERSIONS`（feasibility-v1/v1/v2/v3）+ `_V4_VALIDATOR_VERSION`；`_validate_entity_refs`/`_validate_repair_entity_refs` 显式分派——v4 严格校验、legacy 放行、其余 `ValueError` 拒绝。删除 `not in legacy => strict` 逻辑
- active producer 保持 `hard-validator-v4`；schemaVersion 仍为 1

## 3. F3：Task API eventType-aware 六态 read model

### RED

`PlanningTaskReadModelIntegrationTest` 重写为 19 用例：
- 六态正例：SUCCEEDED（VERIFIED report + evaluation 非空 + candidate null）、WAITING_USER（NEEDS_REPAIR report + candidate 非空 + evaluation null）、QUEUED/RUNNING/FAILED/CANCELLED（三字段均 null；FAILED 保留 errorCode）
- 负向反例 12：WAITING_USER+evaluation、WAITING_USER+VERIFIED report、WAITING_USER 缺 candidate、WAITING_USER malformed candidate、WAITING_USER malformed fingerprint、SUCCEEDED+candidate、SUCCEEDED+NEEDS_REPAIR、SUCCEEDED 缺 evaluation、FAILED+report、CANCELLED+evaluation、status/eventType 不匹配、report 缺必填字段、payload 为数组
- RED 确认：12 个反例被透传实现接受（失败），7 个正例通过

### GREEN

- 新增 `PlanningTaskOutcomeReadModel`（@Component）：输入 `PlanningTaskRecord` + `PlanningTaskEventRecord`，按 `event.eventType()` 分派：
  - PLANNING_COMPLETED：task.status=SUCCEEDED、report 经 validator 且 VERIFIED、evaluation 非空、candidate 必须 absent
  - PLANNING_REVIEW_REQUIRED：task.status=WAITING_USER、report 非 VERIFIED、candidate 结构校验（title/days/activities 必填）、fingerprint 格式合法、evaluation 必须 absent
  - PLANNING_FAILED：task.status=FAILED、无 report/candidate/evaluation；PLANNING_CANCELLED 同理
  - 任何矛盾组合/非对象 payload → `IllegalStateException`（fail closed）
- `PlanningTaskEventMapper.findLatestTerminal` → `findLatestOutcome`（含 PLANNING_CANCELLED）
- `PlanningTaskService` 委托 read model，删除透传 helper（text/optionalNode/parseEvaluation 等）
- **fingerprint 复算说明**：验收要求"WAITING_USER 复算 candidate/report fingerprint"，但 DTO round-trip 不保真（`TransitLeg.costSource` 默认 "UNKNOWN"、BigDecimal 规范化——B6J.1 已记录 Python 同理，probe 实证 `valueToTree` 后 fingerprint 改变）。权威 fingerprint 绑定在 parser 层（原始 wire 树 vs report，入库前验证）。read model 改为结构校验 + fingerprint 格式门禁，避免对合法 review 误报。此为本批次记录的工程调整，非放宽验证

## 4. F4：SSE 测试深比较

### RED

- review live/replay、completion live/replay 4 个测试改为解析 SSE frame（id/event/data JSON），data.payload 与 DB task_event payload **深比较**（`isEqualTo`），并断言：event id 为 DB 行 id、eventId/taskId/eventType/schemaVersion 与 DB 一致、report/candidate/evaluation 语义
- 关键修复：SSE 响应用 `getContentAsByteArray()` + UTF-8 解码（`getContentAsString()` 默认 ISO-8859-1 致中文乱码）；`TaskEventView.eventId` 是 DB 行 id 而非事件 UUID

### GREEN

- `parseSseFrames` helper（两个测试类各一），保留 containsString 仅用于 `replaysProviderFailureMetadataThroughTheTerminalSseEvent` 的 smoke 断言

## 5. F5：completion task-event insert failure 回滚

- `PlanningCompletionFlowIntegrationTest#completedTaskEventInsertFailureRollsBackTheWholeCompletionTransaction`（新增）：BEFORE INSERT trigger 仅对 PLANNING_COMPLETED 抛 `forced completed event failure`；rootCause 证明 trigger 命中；断言 version/day/activity/transit/report 全零、task=QUEUED、仅原始 QUEUED 事件
- **直接 GREEN**：现有 `@Transactional` + `requireOne` 已满足契约，未修改生产事务（回归锁定）

## 6. 精确修改文件（B6J.2.1 增量）

生产：
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/feasibility/FeasibilityReportValidator.java`
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningReviewService.java`
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningCompletionService.java`
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskOutcomeReadModel.java`（新增）
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskService.java`
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskEventMapper.java`
- `apps/agent-service/src/trip_agent/feasibility/models.py`

测试：
- `PlanningReviewRequiredEventParserTest`、`PlanningCompletedEventParserTest`、`FeasibilityReportContractTest`
- `PlanningReviewFlowIntegrationTest`、`PlanningCompletionFlowIntegrationTest`
- `PlanningReviewServiceTest`（fake mapper 方法改名）
- `PlanningTaskReadModelIntegrationTest`（重写）
- `apps/agent-service/tests/feasibility/test_feasibility_models.py`

文档：
- `docs/execution/B6J2/execution-report.md`（本文件）
- `docs/product/系统完善长期执行与验收总控计划.md`（B6J.2 状态「修复完成，待重新验收（未提交）」）

## 7. 定向/全量门禁（B6J.2.1 复跑）

Python（apps/agent-service）：
- 定向 `tests/feasibility`：**362 passed**；`tests/test_planning_outcome_events.py tests/test_planning_outcome_flow.py`：**19 passed**
- 全量 `uv run python -m pytest --basetemp C:\Windows\Temp\codex-b6j21-py-full`：**1286 passed, 37 skipped**（+6 为 F2 新增）
- ruff check `src/trip_agent/feasibility tests/feasibility`：All checks passed
- ruff format `test_feasibility_models.py`：已格式化，check 通过

Java（仓库根）：
- 定向（12 类）：**262 passed, 0 failures/errors**（FeasibilityReportContractTest 48、Codec 10、Mapper 6、MapperV4 10、CompletedParser 54、ReviewParser 14、CompletionFlow 42、ReviewFlow 9、ReviewService 12、TaskReadModel 19、TaskFlow 14、ItineraryEdit 24）
- 全量 `mvn --batch-mode -pl apps/travel-server verify`：**BUILD SUCCESS**；tests run: **382**, failures: 0, errors: 0, skipped: 0；JaCoCo `All coverage checks have been met.`；Flyway 干净库迁移至 v33

仓库：
- `python scripts/check_markdown_links.py`：**85 files valid**
- `git diff --check`：干净（仅 CRLF 警告）
- `git diff --cached --name-only`：空（全部 unstaged）

## 8. acceptance-report 未修改

`docs/execution/B6J2/acceptance-report.md` 保持 NEEDS_CORRECTION 原样，未删除/覆盖/修改。

## 9. staged 空、未 commit/push

B6J.2.1 全部改动 unstaged；`git diff --cached --name-only` 为空；未 commit/push。

## 10. B6F/B6W 未开始

B6W、B6F 均保持 NOT_STARTED；本批次只做 B6J.2 验收修复，不进入 B6W/B6F。

输出：`B6J2_FIX_READY_FOR_REVIEW`

---

# B6J.2.2 小修：原始 Candidate Fingerprint 闭环

## 1. S1 根因

Review parser 在原始 wire `payload.itinerary` 上验证 `report.itineraryFingerprint == compute(wire)`，随后把 itinerary 反序列化为 Java DTO；`PlanningReviewService` 再把 DTO 序列化进 task_event。DTO round-trip 会补充默认/null 字段（`TransitLeg.costSource` 默认 "UNKNOWN"、BigDecimal 规范化），因此 task_event 中 candidate 不再等于原 wire tree。B6J.2.1 的 read model 因无法用 report fingerprint 校验 DTO 重序列化结果而只做格式检查——DB 中 candidate 被篡改后 Task API 仍会返回，形成 fail open（S1）。

## 2. RED 真实失败

- R1 `PlanningReviewRequiredEventParserTest` +5（快照存在/深相等/不序列化/防御拷贝/fingerprint mismatch 仍拒）：编译失败（`validatedItineraryJson()` 不存在）
- R2 `storedCandidateDeepEqualsWireItineraryAndBindsFingerprint`：修复前 stored candidate 与 wire 不相等（DTO round-trip 漂移）
- R3 `tamperedStoredCandidateFailsClosedOnTaskApi` / `tamperedStoredFingerprintFailsClosedOnTaskApi`：修复前 read model 对篡改 fail open（原样返回 WAITING_USER）
- R4 `serviceRejectsBypassEventWithoutRawCandidateSnapshot` / `...WithFingerprintMismatch` / `...WithRawTypedInconsistency` / `...WithUnknownRawField`：修复前缺快照/篡改不拒

## 3. raw candidate snapshot 设计

- `PlanningReviewRequiredEvent.Payload` 增加 `@JsonIgnore JsonNode validatedItineraryJson`（Java 内部元数据，**不是 wire property，不进入外部 review v1 Schema**，task_event 序列化不出现）
- 保留兼容构造器（旧签名 → 快照 null）；`validatedItineraryJson()` accessor 返回 `deepCopy()`（外部无法修改内部快照）
- Parser 在完成 schema/type/semantic/fingerprint 校验后，用 `tree.at("/payload/itinerary").deepCopy()` 构造带快照的 event（`withValidatedItinerary`）——不保留对 parser 临时 tree 的引用

## 4. parser/service/read-model 三层门禁

- **Parser**：现有 fingerprint 校验（wire itinerary vs report）不变，另捕获 raw 快照
- **Service**（`validateCandidateIntegrity`，在 `markWaitingUser`/task_event insert/SSE publish 之前）：
  1. raw 快照存在且为 object
  2. `ItineraryFingerprintVerifier.matches(raw, report.itineraryFingerprint())`
  3. raw 以 `FAIL_ON_UNKNOWN_PROPERTIES` 严格反序列化为 `PlanningCompletedEvent.Itinerary`，与 `event.payload().itinerary()` 语义相等
- **Read model**（`readReview`）：恢复 `ItineraryFingerprintVerifier.matches(candidate, report.itineraryFingerprint())`，删除"只查 64 hex 因 DTO round-trip 无法验证"的降级逻辑与注释；保留 candidate 结构校验、report validator、eventType/status 六态、evaluation 禁止

## 5. wire/DB/API/SSE candidate 深结构一致

`ReviewPayload.candidateItinerary` 字段类型改为 `JsonNode`，service 用 `event.payload().validatedItineraryJson()`（raw wire 树）写入 task_event，不再 DTO 序列化。因此 stored candidate 与 wire itinerary 深结构相等，report fingerprint 同时绑定 wire、DB、Task API、SSE candidate。R2 集成测试断言 `storedCandidate.isEqualTo(wireItinerary)` + fingerprint 复算匹配；SSE live/replay 深比较测试（B6J.2.1）在 raw candidate 下保持通过。

## 6. DB candidate/report fingerprint 两类篡改反例

- `tamperedStoredCandidateFailsClosedOnTaskApi`：篡改 stored candidate 的 activity title（fingerprint 参与字段），report 不变 → `planningTaskService.get` 抛 IllegalStateException（控制组：未篡改同 task 正常返回 WAITING_USER）
- `tamperedStoredFingerprintFailsClosedOnTaskApi`：candidate 不变，fingerprint 换为另一合法 64-hex → read model fail closed

## 7. service bypass 反例

`reviewEventWithoutParserValidationWithSnapshot` 绕过 parser 直调 service：
- 缺快照 → reject（"missing its validated itinerary snapshot"）
- 快照/report fingerprint mismatch → reject
- raw 篡改（title/bogusField，必破坏 fingerprint）→ reject
- 每个均断言 task 状态不变、review task_event 不存在

## 8. S2 明确认错文字

以下声明明确不成立，特此承认：

1. **原 B6J.2 R3 "六态真值表 + malformed fail closed 已完成"的声明不成立**：原 read model 只是原样透传 `feasibilityReport`/`candidateItinerary`；WAITING_USER+evaluation、SUCCEEDED+错误 status/candidate 等反例可穿透；B6J.2.1 才通过 eventType-aware `PlanningTaskOutcomeReadModel` 关闭。
2. **原 B6J.2 R4 "SSE live/replay 已深结构验证"的声明不成立**：原测试主要使用 `containsString` 检查字段名，未证明完整 payload 一致；B6J.2.1 才加入 frame 解析与 JsonNode 深比较。
3. **B6J.2.1 仍存在 S1**：DTO round-trip 导致 stored candidate 不再与 report fingerprint 绑定，DB 篡改 fail open；B6J.2.2 通过保存 parser 验证过的 raw candidate 修复。

## 9. 精确修改文件（B6J.2.2 增量）

生产：
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/infrastructure/mq/PlanningReviewRequiredEvent.java`（Payload 内部快照 + 兼容构造器）
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/infrastructure/mq/PlanningReviewRequiredEventParser.java`（捕获 raw 快照）
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningReviewService.java`（`validateCandidateIntegrity` + ReviewPayload 用 raw candidate）
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskOutcomeReadModel.java`（恢复 fingerprint 复算）

测试：
- `PlanningReviewRequiredEventParserTest`（+5 R1）
- `PlanningReviewServiceTest`（reviewEvent 提供合法快照 + withFingerprint helper + 日期越界测试更新）
- `PlanningReviewFlowIntegrationTest`（+7：R2 存储无损、R3 两类篡改、R4 四类 bypass；autowire PlanningTaskService）
- `PlanningTaskReadModelIntegrationTest`（read model fingerprint 恢复后保持 19 通过）

文档：
- `docs/execution/B6J2/execution-report.md`（本文件）

## 10. 定向/全量门禁（B6J.2.2）

Java 定向（7 类）：FeasibilityReportContractTest 48、PlanningCompletedEventParserTest 54、PlanningReviewRequiredEventParserTest 19、PlanningCompletionFlowIntegrationTest 42、PlanningReviewFlowIntegrationTest 16、PlanningReviewServiceTest 12、PlanningTaskReadModelIntegrationTest 19 = **210 passed, 0 failures/errors**。

Java 全量 `mvn --batch-mode -pl apps/travel-server verify`：**BUILD SUCCESS**；tests run: **382**, failures: 0, errors: 0, skipped: 0；JaCoCo `All coverage checks have been met.`；Flyway 干净库迁移至 v33。

仓库：`python scripts/check_markdown_links.py`（**85 files valid**）；`git diff --check` 干净；`git diff --cached --name-only` 空。

Python 生产代码零改动（缺陷在 Java wire→DTO→DB 边界），未改动共享 fixtures，故未重跑 Python 全量。

## 11. acceptance-report 未修改

`docs/execution/B6J2/acceptance-report.md` 保持原 NEEDS_CORRECTION + B6J.2.1 NEEDS_SMALL_FIX 原样，未删除/覆盖/修改。

## 12. staged 空、未 commit/push

B6J.2.2 全部改动 unstaged；`git diff --cached --name-only` 为空；未 commit/push。

## 13. B6W/B6F 未开始

B6W、B6F 均保持 NOT_STARTED；本批次只做 B6J.2.2 小修，不进入 B6W/B6F。

输出：`B6J2_SMALL_FIX_READY_FOR_REVIEW`
