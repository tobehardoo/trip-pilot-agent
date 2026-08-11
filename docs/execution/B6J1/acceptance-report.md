# B6J.1 验收报告

- 批次：B6J.1（跨服务安全修复）
- 验收角色：独立验收 Agent（只读）
- 分支：`codex/feasibility-foundation`
- 已提交基线：`faa87379f255e39aa80a12e89703111e2fa46b99`
- 计划：[plan.md](plan.md)
- 执行报告：[execution-report.md](execution-report.md)
- 日期：2026-08-11
- **Verdict：NEEDS_CORRECTION**

## 1. Git 与范围审计

- branch：`codex/feasibility-foundation` ✓
- HEAD：`faa87379f255e39aa80a12e89703111e2fa46b99` ✓
- staged：空 ✓；未 commit、未 push ✓
- `git diff --cached --name-only`：空 ✓
- `git diff --check`：干净（仅 CRLF 警告）✓
- 已发布 schema 字节级不变：`planning-completed-event-v8.schema.json`、`planning-failed-event-v2.schema.json`、`planning-completed-event-v6.schema.json` 无 diff ✓
- 范围保护：`apps/web/**`、B7、编辑/回滚、Provider projection、部署配置、`.env` 零改动 ✓；`.omo/`、`.serena/`、`docs/audits/` 未处理 ✓
- 全部 tracked/untracked 改动在 plan 允许路径内（Python worker、Java feasibility/mq/planning/itinerary、契约 fixtures、docs）
- acceptance-report.md 写入前不存在 ✓（本报告是唯一新增）

## 2. R1 验收：Routing 与真实 wire —— PASS

生产代码证据：
- Python `amqp.py:85`：`REVIEW_REQUIRED_ROUTING_KEY = "planning.review-required"`；`amqp.py:625` outcome 发布 `model_dump_json(by_alias=True, exclude_none=False)`；`amqp.py:190`（progress）与 `amqp.py:709`（failed）保持 `exclude_none=True` ✓
- Java `RabbitMessagingConfiguration.java:111`：`.with("planning.review-required")`；listener 用 `REVIEW_QUEUE` 常量 ✓
- `ItineraryFingerprintVerifier` 注释声明"完整 null wire、不恢复缺失字段"，与实现一致 ✓

独立复现（`verify_r1.py`，仓库外脚本）：
- 真实 v9 completion body 过 schema：PASS
- wire itinerary 原始树 hash == report fingerprint：PASS
- wire 显式 null（staleReason/providerProvenance/typeCode）：PASS
- **控制组**：`exclude_none=True` body 的原始树 hash ≠ report fingerprint（省略 null 无法错误通过）✓
- review NEEDS_REPAIR body 过 schema + fingerprint + repairAttempts：PASS
- 共享 fixtures 与真实 publisher 路径结构一致：PASS

结论：R1 真实关闭，无断链。

## 3. R2 验收：v9-only 门禁 —— PASS

生产代码证据：
- `PlanningCompletedEventParser.java:96`：`if (schemaVersion != 9) throw invalid(...)` ✓
- `PlanningCompletionService.handle` 入口四重防线（v9 + report 非空 + VERIFIED + evaluation 非空）✓
- `persistFeasibilityReportIfPresent`：report null 抛 IllegalStateException（无 optional 语义）；`requireOne` 强制 insert 成功 ✓
- `handle` 为 `@Transactional`，version/report/current/task status 同一事务 ✓

测试证据：
- 4 个 `serviceRejects*EvenWhenCalledDirectly` 集成测试**绕过 parser**（`objectMapper.treeToValue` 直接构造事件）调 service，断言抛 rejected + `itinerary_version` 计数为 0 + task 不 SUCCEEDED —— 真正证明 service 层防御，非仅 parser 拒绝 ✓
- 事务回滚：`rollsBackEveryCompletionWriteWhenAnActivityCannotBePersisted` / `...ATransitLegCannotBePersisted` 用 DB 触发器强制失败，断言 task 回 QUEUED、itinerary/version/day/activity 全零 ✓

真值表确认：v1–v8 REJECT；v9 缺 report/非 VERIFIED/缺 evaluation REJECT；v9 VERIFIED+evaluation ACCEPT ✓

**缺口（见第 8 节 F3）**：report insert 失败回滚无直接测试（仅有 activity/transit 失败测试）。

## 4. R3 验收：唯一模型 —— PASS

生产代码证据：
- 全仓唯一 `feasibility.FeasibilityReport` record（含 Summary/RuleResult/EvidenceReference/RepairAttempt）
- `PlanningCompletedEvent.java` / `PlanningReviewRequiredEvent.java` 均引用共享 DTO，无重复定义 ✓
- `evidenceRefs` 是 `List<EvidenceReference>`（对象），非 `List<String>` ✓
- `RepairAttempt` 字段与 standalone v1 一致（attemptIndex/triggeringRuleIds/actionCodes/affectedDates/affectedEntityRefs/beforeFingerprint/afterFingerprint/resultingStatus）✓
- 两个 parser 均调用 `FeasibilityReportValidator.validate`，IllegalArgumentException → fail-closed rejection（无 NPE 泄漏）✓
- completion 要求 VERIFIED；review 拒绝 VERIFIED ✓

Fixtures 双端覆盖（Java `FeasibilityReportContractTest` + Python `test_feasibility_schema.py`）：
- 非空 evidenceRefs（v9 fixture OPENING_HOURS PASS + VERIFIED eligible）✓
- 非空 RepairAttempt（review NEEDS_REPAIR fixture attemptIndex=1）✓
- forged summary、duplicate ruleId、missingRequiredRuleIds 不一致、opening PASS/FAIL 无 eligible evidence、repair index gap、>3 attempts、additional property —— 均有 fixture 且被双端消费 ✓
- parser 级 fail-closed 测试（`v9RejectsNonVerifiedReportStatus` 等）验证 validator 拒绝进入 parser rejection ✓

## 5. R4 验收：Review 安全与完整持久化 —— NEEDS_CORRECTION

生产代码证据（正确）：
- eventId 幂等：同 task + PLANNING_REVIEW_REQUIRED 幂等返回；其他归属抛 rejected ✓
- identity/date/baseline guard 接入（`PlanningOutcomeGuard` 同时被 completion/review 使用）✓
- stale trip/replan baseline → `persistStaleFailure`（FAILED + PLANNING_FAILED event + STALE_* 错误码）✓
- 正常 review：WAITING_USER + ReviewPayload 含 status/runId/provider/candidateItinerary/knowledge/factImpacts/providerProvenance/feasibilityReport ✓

**关键缺陷：**
- **F1 [严重]：无 review 集成 round-trip 测试。** 执行报告声称"集成测试 PlanningCompletionFlowIntegrationTest（38 tests）覆盖 review 事件 → WAITING_USER → DB 完整持久化链路"——**不实**。该文件 38 个测试全部是 completion，无任何 review 测试。全仓唯一引用 `PlanningReviewService` 的测试是 `PlanningReviewServiceTest`（fake mapper 单测）。
- **F2 [严重]：完整持久化证据不足。** `persistsCompleteCandidatePayload` 仅断言 payloadJson 字符串 `contains` 字段名（`"candidateItinerary"` 等），未反序列化比较关键值、report 或 candidate fingerprint——验收指南明确禁止这种检查方式（"不能只检查 JSON 字符串包含字段名；应反序列化并比较关键值、report 和 candidate fingerprint"）。无任何测试从 DB `planning_task_event` 读回 payload 验证结构。
- **F3 [严重]：stale baseline 无集成验证。** `STALE_TRIP_VERSION`/`STALE_ITINERARY_VERSION` 仅 fake 单测覆盖（断言 terminalStatus/errorCode/eventType），无 DB 集成验证（task 落库 FAILED + PLANNING_FAILED event 实际写入）。

## 6. R5 验收：实体引用映射 —— PASS（含低风险项）

生产代码证据：
- `FeasibilityEntityRefMapper.remap` 在 report insert 前调用（`PlanningCompletionService.java:159`）✓
- RuleResult 与 RepairAttempt 的 affectedEntityRefs 均处理 ✓
- 非 UUID 文本（POI/酒店/普通引用）经 `UUID.fromString` 失败返回 null 保持不变 ✓
- 零匹配 UUID 保持不变 ✓；歧义（同值在 activity+transit 映射表）fail closed ✓
- `itineraryFingerprint` 直接存 report 原值（`PlanningCompletionService.java:166`），不被映射改写 ✓

测试证据：`FeasibilityEntityRefMapperTest` 5 项 + 集成 `persistsFeasibilityReportWithMappedEntityReferences`（DB 读回 report_json，映射后 ID 能查到真实 activity/transit 行，POI-KEEP-1 保留）✓

低风险项（见 F5）：若 provider POI ID 恰好是合法 UUID 且与临时 activity/transit ID 同值，会被误映射——测试未覆盖，但概率极低且需要 source 与 POI 恰好同 UUID。

## 7. 事务与幂等专项 —— 部分通过

- report/task event insert 返回 0：`requireOne` 抛 IllegalStateException → `@Transactional` 回滚（代码正确，F3 缺 report 失败直接测试）✓
- version 已创建后 report 写入失败：同一事务回滚（代码路径正确）✓
- duplicate eventId 属其他 task/type：service 抛 rejected ✓（单测覆盖）
- task 在 SUCCEEDED/FAILED/WAITING_USER 收到事件：状态检查拒绝 ✓（单测覆盖）
- stale baseline + duplicate 同时发生：幂等检查在 baseline 之前短路 ✓（代码顺序正确）
- **F4 [中等]：REPLAN baselineItineraryVersionId 为 null 时 `isStaleReplanBaseline` 返回 false（放行）**。plan 语义要求"REPLAN baseline itinerary 已变化 → STALE_ITINERARY_VERSION"。正常 REPLAN task 创建时从 `request.baseVersionId()` 设置 baseline（幂等检查也校验），null 仅发生在数据异常；但此时 guard 放行而非 fail closed，若 currentVersionId 非空，会基于 current 创建 replan 版本——语义偏差（低概率但真实）。
- listener reject-no-requeue：contract/rejected → `AmqpRejectAndDontRequeueException` ✓；infrastructure 异常传播给 broker 重投 ✓（listener 测试覆盖）
- malformed body：parser 抛 contract exception，不进入 service ✓

## 8. 发现项（按优先级）

| # | 严重度 | 位置 | 描述 | 影响 |
| --- | --- | --- | --- | --- |
| F1 | 严重 | `PlanningCompletionFlowIntegrationTest`（无 review 测试）；`execution-report.md` §9 | 执行报告声称 review 集成 round-trip 已覆盖，实际不存在 | 验收门禁"从数据库实际读回并确认 task event 完整字段"未满足；报告与事实不符 |
| F2 | 严重 | `PlanningReviewServiceTest.persistsCompleteCandidatePayload`（196–203 行） | 仅断言 JSON 字符串包含字段名，未反序列化比较值/report/fingerprint | 完整持久化正确性未证明（验收指南明确禁止此检查方式） |
| F3 | 严重 | 集成测试缺失 | report insert 失败回滚、stale baseline（STALE_TRIP_VERSION/STALE_ITINERARY_VERSION）落库无集成测试 | 验收指南第九节明确列出的反例未覆盖 |
| F4 | 中等 | `PlanningOutcomeGuard.isStaleReplanBaseline`（63–64 行） | baselineItineraryVersionId 为 null 时返回 false（放行），而非 fail closed | 数据异常时可能基于 current 创建 replan 版本，偏离 plan 语义 |
| F5 | 低 | `FeasibilityEntityRefMapper.remapOne` | 合法 UUID 格式的 provider POI ID 若与临时 activity/transit ID 同值会被误映射 | 概率极低（需同 UUID），无测试覆盖 |
| F6 | 低 | `execution-report.md` §9 | "集成测试覆盖 review → WAITING_USER → DB 完整持久化链路"与事实不符 | 报告可信度问题 |

## 9. 独立测试门禁结果（验收复跑）

Python（apps/agent-service）：
- 定向：71 passed ✓
- feasibility：326 passed ✓
- 全量：1250 passed, 37 skipped ✓

Java（仓库根）：
- 定向（7 类）：156 passed, 0 failures/errors ✓
- `mvn --batch-mode -pl apps/travel-server verify`：**BUILD SUCCESS**；tests run: 306, failures: 0, errors: 0, skipped: 0 ✓
- JaCoCo：`All coverage checks have been met.` ✓
- Flyway：干净库成功迁移至 v33（4 个容器均确认）✓

仓库门禁：
- `python scripts/check_markdown_links.py`：81 files valid ✓
- `git diff --check`：干净 ✓
- `git diff --cached --name-only`：空 ✓

## 10. 范围保护证明

- 允许路径内改动：Python worker/amqp/tests、Java feasibility/mq/planning/itinerary、契约 fixtures、docs（架构文档小修）
- 规划产物：docs/index.md、总控计划、docs/execution/README.md、plan.md、execution-report.md
- 零改动：apps/web、v8/v2 schema（字节级）、failed v2、Hard Validator 聚合语义、Provider projection、部署配置、.env、.omo/、.serena/、docs/audits/
- staged 空、未 commit、未 push

## 11. Verdict

**NEEDS_CORRECTION**

R1、R2、R3、R5 真实关闭且门禁通过；但 R4 的验收门禁核心证据缺失：无 review 集成 round-trip 测试（F1）、完整持久化仅字符串包含断言（F2）、stale baseline 与 report 失败回滚无集成验证（F3），且执行报告存在与事实不符的声明（F6）。此外 REPLAN null baseline 语义偏差（F4）需修正为 fail closed。

**修复方向（供下一轮执行）**：
1. 新增 review 集成测试：真实 review 事件 → listener/parser → service → DB `planning_task_event` 读回 → 反序列化 ReviewPayload → 比较 status/runId/provider、candidate itinerary 关键值、feasibilityReport fingerprint 与状态、knowledge/factImpacts/providerProvenance 完整性；断言 task=WAITING_USER、不创建 version、不更新 currentVersion。
2. 新增 stale baseline 集成测试：trip baseline 与 replan baseline 变化 → task=FAILED + PLANNING_FAILED event（errorCode=STALE_TRIP_VERSION/STALE_ITINERARY_VERSION）落库。
3. 新增 report insert 失败回滚集成测试（DB 触发器强制 `itinerary_feasibility_report` insert 失败 → version/task 全回滚）。
4. 修正 `isStaleReplanBaseline`：REPLAN 且 currentVersionId 非 null 而 baseline 为 null/不匹配 → stale（fail closed）；补 null baseline 负向测试。
5. 更新 execution-report 使其与事实一致。

---

# B6J.1.1 重新验收

- 日期：2026-08-11
- 验收角色：独立重新验收 Agent（只读）
- **Verdict：NEEDS_SMALL_FIX**

## 1. 前置 Git 状态

- branch：codex/feasibility-foundation ✓
- HEAD：aa87379f255e39aa80a12e89703111e2fa46b99 ✓
- staged：空 ✓；未 commit、未 push ✓
- git diff --cached --name-only：空 ✓；git diff --check：干净（仅 CRLF 警告）✓
- B6J.1.1 增量精确为：PlanningOutcomeGuard.java（修改）、PlanningOutcomeGuardTest.java（新增）、PlanningReviewFlowIntegrationTest.java（新增）、FeasibilityEntityRefMapperTest.java（追加 characterization）、execution-report.md（追加章节）✓
- 原 acceptance-report.md（NEEDS_CORRECTION）保留未动 ✓；本章节为追加

## 2. F1/F2：正常 review 数据库 round-trip —— 成立（含 1 项断言缺口）

PlanningReviewFlowIntegrationTest.persistsCompleteReviewOutcomeToDatabaseAndReadsItBack 使用真实基础设施：

- 真实 Spring context（extends PostgresIntegrationTest → @SpringBootTest + Testcontainers PostgreSQL + Flyway V33）✓
- 真实 PlanningReviewService（@Autowired）、真实 parser、真实 MyBatis mapper、真实 planning_task/planning_task_event 表 ✓
- 无 fake/mock；测试类无 @Transactional（非外层回滚伪装）✓
- task 经 API 创建（QUEUED）→ review service 返回后独立 jdbcTemplate 查询 ✓

验证结果（从 DB 重新读取，非 contains）：
- task=WAITING_USER、version 从 N → N+1 精确递增 ✓
- task event envelope：eventType=PLANNING_REVIEW_REQUIRED、schemaVersion=1、eventId/taskId 正确 ✓
- payload JSONB 解析后逐结构比较：status/runId/provider、candidateItinerary（title/days/date/activities/estimatedTotalCost）、knowledge（REAL/citations/freshness）、factImpacts、providerProvenance、feasibilityReport ✓
- report：summary totalCount=11、failCount=1、ruleResults 11、repairAttempts 1 且 attemptIndex=1 ✓
- fingerprint：storedFingerprint 匹配 64 hex 且与原始 report fingerprint 相等（证明无损读回；parser 已在 wire 层验证 fingerprint 绑定 itinerary，传递成立）✓
- 无新 itinerary/version/day/activity/transit/report 行（usiness.itinerary 计数 0、itinerary_feasibility_report 计数 0）✓
- task event 提交后独立查询可读（planning_task_event 计数 = 2：QUEUED + REVIEW）✓

**发现 S1（小）**：验收指南第 8 条要求"非空 EvidenceReference"无损读回，但
eview-v1-needs-repair-demo.json 的全部 ruleResults 的 evidenceRefs 均为空（OPENING_HOURS=UNKNOWN + []），测试仅断言 openingResult 非 null，未断言任何 evidenceRefs 非空。该结构解析正确性已由 R3 的 v9 fixture（非空 EvidenceReference）+ FeasibilityReportContractTest 覆盖，但 review round-trip 集成测试未显式断言。修复：给 review fixture 加一条带 VERIFIED eligible evidenceRefs 的规则并断言，或断言现有规则中 evidenceRefs 的存在性。

**发现 S2（极小）**：测试注释 "after-commit event row exists" 实际验证的是"事务提交后 DB 行可读"（独立连接查询证明提交边界），并非 PlanningTaskEventCreated 的 AFTER_COMMIT 发布语义（当前为事务内同步 publish）。措辞建议澄清为 "committed event row"；该应用事件的 SSE 消费属 B6J.2 范围。

## 3. F3A：Stale trip baseline 集成验证 —— 成立（含 1 项极小缺口）

staleTripBaselineFailsTaskWithStaleTripVersion：
- 经 API 创建 task（持久化 baselineTripVersion=trip.version=0）→ updateConstraints 递增 trip version（DB 级真实 mismatch）→ 真实 review service ✓
- 从 DB 重新读取：task=FAILED、error_code=STALE_TRIP_VERSION、PLANNING_FAILED event 落库（payload status=FAILED + errorCode=STALE_TRIP_VERSION）✓
- 不进入 WAITING_USER（task=FAILED）、无新 version/itinerary 行 ✓
- **发现 S3（极小）**：调用前未显式断言 aselineTripVersion != currentTripVersion（结果 FAILED 间接证明 mismatch 已建立；建议加显式前置断言）。

## 4. F3B：Stale replan baseline 集成验证 —— 成立

staleReplanBaselineFailsTaskWithStaleItineraryVersion：
- 真实完成首个 v9 itinerary（current=version A）→ **DB 插入真实 REPLAN task**（baseline_itinerary_version_id=version A，满足 ck_planning_task_replan_context，status=RUNNING）→ **DB 级切换 current 到 version B**（模拟并发 replan 完成）→ 显式断言 B ≠ A ✓
- service 通过真实 mapper 读取 task（baseline=A）与 ItineraryCurrentVersionProvider（真实 getCurrentVersionForTask，返回 B）→ guard 判定 stale ✓
- 从 DB 重新读取：task=FAILED、error_code=STALE_ITINERARY_VERSION、PLANNING_FAILED event 落库、current 保持 B、version 计数=2（review 未新增）✓
- 替代方法说明（已确认）：ck_planning_task_replan_context 强制 REPLAN 必须 baseline 非空，且 planning_task 每 trip 唯一约束使"同 trip 并发第二个完成 task"无法构造；DB 级 current 切换跨越真实 mapper/DB/service 边界，达到验收标准 ✓

## 5. F3C：Report insert failure 原子回滚 —— 成立（最高风险项）


eportInsertFailureRollsBackTheWholeCompletionTransaction：
- 临时 BEFORE INSERT ON business.itinerary_feasibility_report 触发器 RAISE EXCEPTION，只作用于 report 表 INSERT ✓
- 触发器在 service 调用前生效；异常 rootCause = "forced report failure"（证明触发器真实执行）✓
- 失败点定位：v9 completion 顺序（createInitialItinerary 已插入 activity/transit → persistFeasibilityReportIfPresent → report insert 失败），若更早阶段失败会报不同错误 ✓
- 测试类无外层 @Transactional（PostgresIntegrationTest 无该注解），service 自身 @Transactional 真实开始/失败/回滚 ✓
- 捕获异常后 jdbcTemplate 独立连接查询：itinerary/version/day/activity/report 全 0、planning_task_event=1（仅 QUEUED，无 PLANNING_COMPLETED terminal event）、task=QUEUED（恢复事务前状态）✓
- trigger/function 在 finally 可靠 DROP ✓；每个测试 @BeforeEach TRUNCATE，顺序改变稳定 ✓
- 非 mock return 0、非 activity/transit trigger 替代 ✓

## 6. F4：Null replan baseline fail closed —— 成立（含 1 项极小缺口）

生产实现 PlanningOutcomeGuard.isStaleReplanBaseline：aseline == null || currentVersionId == null || !equals —— 无 NPE（== null 短路）、null 不被视为"不 stale" ✓

真值表（测试覆盖）：

| taskType | baseline | current | isStale | 测试 |
| --- | --- | --- | --- | --- |
| REPLAN | null | 非 null | true |
eplanWithNullBaselineIsStaleEvenWhenCurrentExists ✓ |
| REPLAN | 非 null | null | true |
eplanWithNullCurrentVersionIsStaleEvenWhenBaselineExists ✓ |
| REPLAN | A | B | true |
eplanWithMismatchedBaselineIsStale ✓ |
| REPLAN | A | A | false |
eplanWithMatchingBaselineIsNotStale ✓ |
| REPLAN | null | null | true（实现满足，未显式测试） | S4 |
| CREATE | 任意 | 任意 | 不进入该判断 | 调用方仅在 "REPLAN".equals(taskType) 分支调用 ✓ |

review 路径真实调用 guard（PlanningReviewService.handle REPLAN 分支）；stale 结果 → FAILED + STALE_ITINERARY_VERSION + 不进入 WAITING_USER ✓。null DB 状态受 ck_planning_task_replan_context 约束不可构造，单元测试作为非法历史状态防御证据成立；正常 mismatch 有集成证据 ✓。

**发现 S4（极小）**：测试矩阵缺 REPLAN null/null 行（实现通过第一个短路条件满足，建议补显式断言）。

## 7. F5 characterization 审计 —— 通过

- 未修改 report schema、entity ref 格式、FeasibilityEntityRefMapper 生产语义 ✓
- 新增 uuidLookingPoiReferenceIsMappedWhenItCollidesWithATemporaryId 仅锁定当前行为（UUID-looking POI 与临时 activity UUID 碰撞时被映射），注释明确"known residual risk, not a fix" ✓
- R5 已验收行为无回归（歧义 fail closed、POI 保留、fingerprint 不改写均保持）✓
- 风险已在 execution-report 登记为 B6J.2 前显式残留风险，未声称解决 ✓
- **结论：F5 不阻塞 PASS，但须在 B6J.2 plan 登记 typed entity refs 议题**

## 8. F6 执行报告事实纠正 —— 通过

execution-report.md 保留原始报告并追加 "B6J.1.1 验收修复" 章节，明确承认并纠正 4 项不实声明：
1. review DB round-trip 并未覆盖（原声称不实）
2. 原 persistsCompleteCandidatePayload 只有 contains 断言
3. stale baseline 原缺集成验证
4. report insert failure 原未在 report 表失败点验证
无模糊措辞；新章节测试名、测试数与代码事实一致（execution report 的 B6J.1.1 声明与本验收复现一致）✓

## 9. 回归检查（R1/R2/R3/R5 未破坏）

- routing key：Python mqp.py:85 与 Java binding 均 planning.review-required ✓
- v9/review outcome：exclude_none=False（progress/failed 保持 True）✓
- completion v1–v8：parser gate schemaVersion != 9 拒绝 ✓
- service 防线：v9+report+VERIFIED+evaluation 四重 ✓
- Java 唯一 FeasibilityReport DTO（无重复）✓
- completion/review parser 均调 FeasibilityReportValidator.validate ✓
- entity ref 映射语义除 characterization 外未变化 ✓
- PlanningReviewServiceTest 12、PlanningCompletionFlowIntegrationTest 38 全绿（无回归）✓

## 10. 独立测试结果

Java 定向（6 类）：PlanningOutcomeGuardTest 5 + PlanningReviewServiceTest 12 + PlanningReviewFlowIntegrationTest 4 + PlanningCompletionFlowIntegrationTest 38 + PlanningCompletedEventParserTest 49 + PlanningReviewRequiredEventParserTest 8 = **116 passed, 0 failures/errors**（数量非 0，全部实际执行）。

Java 全量：mvn --batch-mode -pl apps/travel-server verify → **BUILD SUCCESS**；tests run: **316**, failures: 0, errors: 0, skipped: 0；JaCoCo All coverage checks have been met.；Flyway 干净库迁移至 v33（多容器确认）。

Python 契约回归（apps/agent-service）：45 passed（Python 生产代码零改动）。

仓库门禁：markdown links 82 files valid；git diff --check 干净；git diff --cached --name-only 空；staged 空。

## 11. 精确文件范围

B6J.1.1 增量（与执行报告一致）：
- pps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningOutcomeGuard.java（isStaleReplanBaseline fail closed）
- pps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningOutcomeGuardTest.java（新增）
- pps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningReviewFlowIntegrationTest.java（新增）
- pps/travel-server/src/test/java/io/github/tobehardoo/trippilot/itinerary/FeasibilityEntityRefMapperTest.java（追加 characterization）
- docs/execution/B6J1/execution-report.md（追加修复章节）

无范围泄漏：Web/Python 生产代码/契约/Flyway/Provider 零改动；.omo/、.serena/、docs/audits/ 未处理。

## 12. 发现项汇总

| # | 严重度 | 位置 | 描述 | 影响 |
| --- | --- | --- | --- | --- |
| S1 | 小 | PlanningReviewFlowIntegrationTest（236–251 行） | review fixture 全部 ruleResults 的 evidenceRefs 为空，测试未断言"非空 EvidenceReference"无损读回 | 验收指南第 8 条检查项未显式覆盖（R3 已覆盖解析层） |
| S2 | 极小 | 测试注释（267 行） | "after-commit event" 措辞实为"事务提交后 DB 行可读" | 措辞澄清，非语义错误 |
| S3 | 极小 | staleTripBaselineFailsTaskWithStaleTripVersion | 调用前未显式断言 baseline != current | 结果 FAILED 间接证明 |
| S4 | 极小 | PlanningOutcomeGuardTest | 缺 REPLAN null/null 矩阵行 | 实现短路满足 |

## 13. Verdict

**NEEDS_SMALL_FIX**

核心证据全部成立：正常 review 真实 DB round-trip（深比较）、stale trip/replan baseline 可信 DB 证据、null baseline fail closed、report insert failure 在真实 report 表阶段触发且 service 事务完整回滚（独立连接查询证明）、原报告事实已纠正、全部门禁通过、无范围泄漏。

S1–S4 均为明确、有限、不改变架构的小问题（S1 为验收指南明确列出的一个断言缺失，S2–S4 为措辞/前置断言/矩阵补全）。修复后无需重新验收全部门禁，仅需复跑 PlanningReviewFlowIntegrationTest 与 PlanningOutcomeGuardTest 定向。

**修复建议（供下一轮执行）**：
1. S1：review fixture 增加一条含非空 VERIFIED eligible evidenceRefs 的规则（如 OPENING_HOURS PASS），round-trip 断言其 evidenceRefs 非空且结构完整。
2. S2：注释改 "committed event row"。
3. S3：调用前加 ssertThat(baselineTripVersion).isNotEqualTo(currentTripVersion)（经 DB 查询）。
4. S4：补 REPLAN null/null 断言。
5. B6J.2 plan 须登记 F5（typed entity refs）议题。

---

# B6J.1.2 最终验收

- 日期：2026-08-11
- 验收角色：独立最终验收 Agent（只读）
- **Verdict：PASS**

## 1. 前置 Git 状态

- branch：codex/feasibility-foundation ✓
- HEAD：aa87379f255e39aa80a12e89703111e2fa46b99 ✓
- staged：空 ✓；未 commit、未 push ✓
- git diff --cached --name-only：空 ✓；git diff --check：干净 ✓
- B6J.1.2 增量精确为：PlanningReviewFlowIntegrationTest.java、PlanningOutcomeGuardTest.java、
eview-v1-needs-repair-demo.json、execution-report.md ✓
- 生产 Java/Python、schemas、Flyway、Web 无 B6J.1.2 增量（PlanningOutcomeGuard.java 保持 B6J.1.1 验收的 fail-closed 版本，内容逐字核对一致）✓
- 历史验收记录（NEEDS_CORRECTION、NEEDS_SMALL_FIX）保留未动 ✓

## 2. S1：非空 EvidenceReference —— 通过

fixture 实际值（
eview-v1-needs-repair-demo.json）：
- OPENING_HOURS rule：outcome=UNKNOWN，evidenceRefs=[{"evidenceId":"opening-stale-001","evidenceType":"OPENING_HOURS","state":"STALE","hardConstraintEligible":false}] ✓
- report status=NEEDS_REPAIR（聚合保持）✓
- summary：totalCount=11/failCount=1/unknownCount=10，与 ruleResults（DUPLICATE_POI FAIL + 10 UNKNOWN）一致 ✓
- evidence 保持 STALE + eligible=false（未升级为 VERIFIED/eligible）✓
- itineraryFingerprint=dce5e94d...（evidence 修改不影响 fingerprint；fingerprint 只绑定 itinerary）✓
- repairAttempts=1（attemptIndex=1）保持 ✓

fixture 生成路径：B6J.1.2 修改脚本通过 PlanningReviewRequiredEvent.model_validate（补 estimatedCost 后）+ model_dump_json(by_alias=True, exclude_none=False) 重写——满足"由 Python 模型序列化路径生成"。说明：TransitLeg.estimated_cost 为 Pydantic exclude=True 字段（dump 排除、validator 要求），形成模型固有不对称——真实 review wire 均无法被模型直接读回，非本批手工拼凑，亦非 B6J.1.2 引入（B6J.1 遗留模型设计）；Python schema 测试与 Java parser 均接受该 wire 形态。

Java 集成测试（persistsCompleteReviewOutcomeToDatabaseAndReadsItBack）：
- 使用真实 fixture 经真实 parser 反序列化（非 service 后手工插入 JSON）✓
- DB read-back 逐字段断言：evidenceId=opening-stale-001、evidenceType=OPENING_HOURS、state=STALE、hardConstraintEligible=false ✓
- opening outcome 仍 UNKNOWN ✓；task 仍 WAITING_USER ✓；无正式 itinerary/version/report 行 ✓
- 输入前断言 evidenceRefs hasSize(1)（DB read-back 侧）✓

Python/Java semantic validator 均接受：Python schema 测试 45 passed（含此 fixture）、Java FeasibilityReportContractTest 43 passed（opening-stale 语义在 valid fixtures 中）✓

## 3. S2：注释语义 —— 通过

注释已修正为："The committed task_event row is readable through an independent query after the service transaction completed (QUEUED + REVIEW). This does not assert Spring after-commit callbacks or SSE publish; those belong to the J6 read-model batch."

与实际观察能力一致：仅声称"事务提交后 DB 行可独立查询读取"，明确不声称 after-commit callback/SSE/事件时序 ✓

## 4. S3：Stale trip baseline 前置断言 —— 通过

staleTripBaselineFailsTaskWithStaleTripVersion 在 service 调用前：
- 从真实 DB 读 aseline_trip_version（planning_task）✓
- 从真实 DB 读 ersion（trip）✓
- 显式断言两者不相等，.as("stale trip baseline precondition: baseline must differ from current") 提供清晰失败信息 ✓
- 非仅比较测试局部变量 ✓
- 后续断言保留：FAILED、STALE_TRIP_VERSION、PLANNING_FAILED event、非 WAITING_USER（task=FAILED）、无正式版本变化 ✓

## 5. S4：Null baseline 完整矩阵 —— 通过

PlanningOutcomeGuardTest 明确覆盖（
eplanWithNullBaselineAndNullCurrentIsStale 为独立测试输入，helper
eplanTaskWithCurrent(null, null) 未偷换默认 UUID）：

| taskType | baseline | current | stale | 测试 |
| --- | --- | --- | --- | --- |
| REPLAN | null | null | true |
eplanWithNullBaselineAndNullCurrentIsStale（独立输入） |
| REPLAN | null | A | true |
eplanWithNullBaselineIsStaleEvenWhenCurrentExists |
| REPLAN | A | null | true |
eplanWithNullCurrentVersionIsStaleEvenWhenBaselineExists |
| REPLAN | A | B | true |
eplanWithMismatchedBaselineIsStale |
| REPLAN | A | A | false |
eplanWithMatchingBaselineIsNotStale |
| CREATE | 任意 | 任意 | 不应用 replan stale | createTaskIsNotAffectedByReplanBaselineLogic |

生产 PlanningOutcomeGuard.java 本轮未修改（内容与 B6J.1.1 验收一致）✓

## 6. F5 延期状态 —— 通过

execution-report.md B6J.1.2 章节明确登记：
- UUID-looking provider POI 与临时实体 UUID 完全碰撞时，当前无类型字符串契约（affectedEntityRefs: string[]）无法无歧义区分 ✓
- F5 未解决 ✓
- 本轮未修改 schema / 生产 mapper（FeasibilityEntityRefMapper 未触碰）✓
- B6J.2 规划必须重新评估 typed entity refs ✓
- 无"已解决/不存在风险/可无条件区分"表述 ✓

## 7. 独立测试结果（验收复跑）

Java 定向（4 类）：PlanningReviewFlowIntegrationTest 4 + PlanningOutcomeGuardTest 6 + PlanningReviewRequiredEventParserTest 8 + FeasibilityReportContractTest 43 = **61 passed, 0 failures/errors**（测试数非 0，全部实际执行）。

Python 契约（apps/agent-service）：45 passed（fixture 修改后契约仍通过）。

仓库门禁：markdown links 82 files valid；git diff --check 干净；git diff --cached --name-only 空；staged 空。

本轮未重复完整 mvn verify：上轮独立 316 tests + JaCoCo + Flyway v33 已通过，B6J.1.2 无生产代码变化，Java 定向覆盖全部修改测试，fixture 由 Python/Java 契约测试双重验证——符合验收指南豁免条件。

## 8. 范围检查

- 无生产 Java/Python 代码修改
- 无 schemas/Flyway/Web/B7/编辑/回滚修改
- 无 acceptance-report 历史记录被删除或改写
- 无 .omo/、.serena/、docs/audits/、私有 .env 处理
- staged 空、未 commit、未 push

## 9. Verdict

**PASS**

B6J.1 可以进入 Git 提交收口。

### 允许提交的精确文件清单（基于实际 git status/diff）

B6J.1.2 增量（测试/fixture/报告）：
1. pps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningReviewFlowIntegrationTest.java
2. pps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningOutcomeGuardTest.java
3. contracts/fixtures/planning-review-required-event-v1/review-v1-needs-repair-demo.json

规划文档（纳入允许提交范围）：
4. docs/index.md
5. docs/product/系统完善长期执行与验收总控计划.md
6. docs/execution/README.md
7. docs/execution/B6J1/plan.md
8. docs/execution/B6J1/execution-report.md
9. docs/execution/B6J1/acceptance-report.md

说明：B6/B6J.1/B6J.1.1 的实现文件（Python worker、Java feasibility/mq/planning/itinerary、契约 fixtures/schemas、其余测试）随 B6 批次整体收口，由 Git 收口任务按 B6/B6J.1/B6J.1.1/B6J.1.2 已验收范围显式暂存。

### 收口约束

- **B6J.1 可以进入 Git 提交收口**（本验收 PASS 后由后续 Git 收口任务执行）。
- **F5 必须进入 B6J.2 plan**（typed entity refs 重新评估）。
- **不能直接进入 B6J.2**；必须先完成 B6J.1 Git 收口。

不要更新总控计划状态，不 stage、不 commit、不 push。验收完成，立即停止。
