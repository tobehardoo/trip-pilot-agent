# B16 独立验收报告（信息不足非阻塞规划机制改造）

- 验收代理：momus（独立验收，非实现者）
- 日期：2026-08-17
- 用户约束执行情况：验收阶段未修改代码、未 commit；**用户授权方案 (a) 修复后**实施修复并复验通过；仍**未 commit/push**。

## A. 验收结论

**PASS**（经用户授权的修复闭环后）

B16 改造（has_blocker 语义、v10 事件契约、V37 迁移、Java 双读边界、前端 readTerminalOutcome / savableWithWarnings、e2e 21/21、完整 Docker 链路）**全部通过**。验收发现 3 个缺陷（1 个既有 + 2 个 B16 实现遗漏），用户选定方案 (a) 后已全部修复并复验：真实链路 `ACCEPTANCE_CHAIN=PASS`（SUCCEEDED / UNVERIFIED / 0 blocker / 行程版本已保存）。

## B. 问题清单

### B-1 [P0] 全链路阻塞缺陷（既有，非 B16 回归）

**现象**：真实规划任务提交后状态永远 RUNNING（90×3s 轮询超时），前端永不进入完成态。

**根因**：
- Python 侧 v10 事件 factImpacts 中 10/10 项携带 `"targetPoiId": null`（amqp.py L658 `completed.model_dump_json(by_alias=True, exclude_none=False)`，null 未剔除）。
- Java 侧 `PlanningCompletedEventParser.validateFactImpactTypes`（L155–196）要求字段存在时必须为字符串：`impact.has("targetPoiId") && !impact.path("targetPoiId").isTextual()` → `PlanningEventContractException: Invalid PLANNING_COMPLETED event: fact impact field types do not match the JSON Schema`。
- 事件被 `AmqpRejectAndDontRequeueException` 拒绝 → `planning.dead-letter.queue`（当前 2 条）。

**证据链**：
1. travel-server 日志：`AmqpRejectAndDontRequeueException: Rejected PLANNING_COMPLETED event: PlanningEventContractException: Invalid PLANNING_COMPLETED event: fact impact field types do not match the JSON Schema`（11:32:23、11:33:56 各一次）。
2. DLQ 消息 dump（`planning.dead-letter.queue`，2 条）：schemaVersion=10、hasBlocker=false、feasibilityReport.status=UNVERIFIED、factImpacts=10 项全部 `targetPoiId: null`（present-but-null）。
3. 用 Python 复现 Java 校验逻辑：10/10 因 `targetPoiId=None (present but not textual)` 失败。
4. 归属判定：`git show HEAD:...PlanningCompletedEventParser.java` 证实该 `targetPoiId` 校验（HEAD L155/L181-182/L187）与 Python 序列化（amqp.py L658，工作区未改动）均存在于 B16 基线 → **非 B16 引入**；真实提供商（REAL_ONLY + AMAP）全链路此前未被此类 null 场景覆盖。
5. 复现实例：run1 trip `c7956a9e…`/task `30e12b82…`（occurredAt 11:32:20Z）；run2 trip `0d1bcd09…`/task `eabd0624…`（11:33:56Z）。

**修复建议（两条路径，需用户决策，本次未执行）**：
- (a) Python 侧：completed 事件序列化剔除 null（`exclude_none=True` 或 `targetPoiId=None` 时省略字段）。
- (b) Java 侧：`validateFactImpactTypes` 对 null 容忍（null 视为缺省，与 JSON Schema 中 `targetPoiId` 非必填语义一致）。

**修复记录（用户选定方案 (a)，2026-08-17 已实施并复验）**：
- `apps/agent-service/src/trip_agent/worker/contracts.py`：`PlanningFactImpact` 增加 `@model_serializer(mode="wrap")`，`target_poi_id=None` 时从序列化输出省略 `targetPoiId`（有值时正常输出）。模型级修改，v9/v10/review-required 语义统一。
- **前置核对**：全量 `exclude_none=True` **不成立**——`FallbackOperation.transitId/fromActivityId/toActivityId` 为 Optional None 但 schema required 且 Java `nullableText()` 强制字段 present（缺失会被拒）。其余 Optional 字段（providerProvenance、impact date/targetName/sourceUrl、activity 元数据、dayType、knowledge.message、freshness、fallbackReason）均允许缺失表达。故仅省略 factImpacts.targetPoiId。
- 验证：模拟 Java 校验 10/10 reject → **0/10 reject**；`test_messaging_contract_schemas.py` 新增回归测试 `test_fact_impact_omits_none_target_poi_id_on_the_wire`；Python 全量 `1530 passed, 37 skipped`；ruff 0。

### B-1b [P0] B16 实现遗漏：Java `validateProviderProvenance` 版本门禁漏加 v10

**现象**：targetPoiId 修复后，事件仍被拒 → `provider provenance is invalid`（14:11:23 / 14:17:15）。

**根因**：B16 的 diff 更新了 `validateProviderProvenanceTypes`（JSON 类型校验）为 v6/v8/v9/v10，但**语义校验 `validateProviderProvenance`（L574-575）漏改**——仍为 v6/v8/v9 白名单。真实 worker 事件总是携带 providerProvenance（REAL_ONLY），v10 事件必然触发 reject。`git diff HEAD` 证实该处无 hunk → **B16 引入的回归**（类型校验放行 v10 但语义校验未同步）。

**修复记录**：`PlanningCompletedEventParser.validateProviderProvenance` 白名单加入 v10。新增回归测试 `v10AcceptsProviderProvenanceWithRealOnlyEvidence`（ParserTest）。Java 全量 `531 tests, 0 failures`。

### B-1c [P0] B16 实现遗漏：`PlanningTaskOutcomeReadModel.readCompleted` 未适配 v10 UNVERIFIED

**现象**：事件消费成功后，任务查询返回 **500**：`IllegalStateException: Planning task terminal event is invalid: PLANNING_COMPLETED`（`PlanningTaskOutcomeReadModel.java:77`）。

**根因**：`readCompleted` 仍要求 `report.status() == VERIFIED`（L76），B16 未修改该文件（`git diff HEAD` 为空）。v10 允许「非 VERIFIED 但无 blocker」的 completed 事件被保存，读模型必须同步接受，否则任务详情/查询失败。

**修复记录**：`readCompleted` 改为与 Parser 相同的 blocker 语义——`failCount>0 || missingRequiredRuleIds 非空` 才拒绝。新增 `PlanningTaskOutcomeReadModelTest`（2 个用例：savable UNVERIFIED 可读、blocker 报告仍拒绝）。Java 全量 `531 tests, 0 failures`。

### B-2 [低] PlanningReviewPanel.vue L70 文案残留
「因此可能无法保存」为 B15 遗留；B16 后 UNKNOWN-only（无 blocker）场景不再进入该 review 分支，不可达，非回归。可后续清理。

## C. V37 迁移

- V33 `ck_ifr_status_verified_only CHECK (status = 'VERIFIED')` → V37 `ck_ifr_status_supported CHECK (status IN ('VERIFIED','UNVERIFIED','NEEDS_REPAIR'))`。
- 纯放宽、additive：不影响 v9 历史数据（仅放开未来写入），fresh 安装与存量升级均安全。
- 运行库已应用：`flyway_schema_history` 显示 `37 | relax feasibility report status | success=t`。

## D. v9/v10 契约边界

| 层 | v9 | v10 |
|---|---|---|
| Python Payload | 无 hasBlock 字段 | `has_blocker` 显式字段 + validator（必须与报告一致；has_blocker 时禁止 COMPLETED） |
| Python 发布 | — | 三处（processor L205/L302/L392）均发 v10，`if not report.has_blocker → COMPLETED`，否则 REVIEW_REQUIRED |
| Java Parser | 强制 VERIFIED | 允许 UNVERIFIED；`blockerFromReport = failCount>0 || missingRequiredRuleIds 非空`；hasBlocker 与报告不一致 → reject |
| Java Service | 要求 VERIFIED | 仅要求 hasBlocker=false |
| 前端 | — | `readTerminalOutcome` 不读 schemaVersion；非 VERIFIED + hasBlocker → malformed；非 VERIFIED 无 blocker → completed |

`has_blocker` 语义：`fail_count > 0 or bool(missing_required_rule_ids)`；`missing_required` 指 11 条硬规则（REQUIRED_RULE_IDS）未执行/结果缺失，POI 事实缺失产生 UNKNOWN 结果而非 blocker。

## E. 完整 Docker 链路（广州两日游场景）

**PASS**（修复后复验）。验收脚本 `b16-acceptance-chain.py`：register → places search（keyword）→ trip 创建（mustVisitPlaceRefs + selectionToken）→ planning-tasks（Idempotency-Key，响应 `taskId`）→ 轮询：

```
poll status=SUCCEEDED
terminal=SUCCEEDED reportStatus=UNVERIFIED failCount=0 unknownCount=4 missingRequired=0
itinerary OK title=「广州 真实地点行程」 days=2
version created id=None status=UNVERIFIED schemaVersion=1
ACCEPTANCE_CHAIN=PASS
```

DLQ = 0 条，travel-server 无 contract rejected。agent 侧链路确认 `PLANNING_CREATE → validation UNVERIFIED → repair stopped → outcome emitted PLANNING_COMPLETED(v10)`。e2e（web 模拟数据）21/21 通过（`PLAYWRIGHT_WEB_PORT=4300` + `CI=true`，规避 Windows 4141–4240 排除端口）。

## F. 提交清单（B16 相关）

**Python 源**：
- `apps/agent-service/src/trip_agent/feasibility/models.py`
- `apps/agent-service/src/trip_agent/worker/contracts.py`
- `apps/agent-service/src/trip_agent/worker/processor.py`

**Python 测试**：
- `tests/feasibility/test_feasibility_models.py`、`tests/test_amqp_worker.py`、`tests/test_daily_skeleton_provider.py`、`tests/test_golden_matrix.py`、`tests/test_local_replanning.py`、`tests/test_messaging_contract_schemas.py`、`tests/test_planning_context_v3.py`、`tests/test_planning_outcome_events.py`、`tests/test_planning_outcome_flow.py`、`tests/test_planning_worker.py`、`tests/test_provider_provenance.py`、`tests/test_structured_logging.py`

**Java**：
- `PlanningCompletedEvent.java`、`PlanningCompletedEventParser.java`、`PlanningCompletionService.java`
- 测试：`PlanningCompletedEventParserTest.java`、`PlanningCompletionFlowIntegrationTest.java`、`PlanningCompletedEventFixture.java`

**新增文件**：
- `apps/travel-server/src/main/resources/db/migration/V37__relax_feasibility_report_status.sql`
- `contracts/messaging/planning-completed-event-v10.schema.json`、`contracts/fixtures/planning-completed-event-v10/`
- `apps/web/src/lib/feasibility-presentation.ts`、`feasibility-presentation.test.ts`

**Web（B16 标记：hasBlocker/savableWithWarnings）**：
- `apps/web/src/components/FeasibilityReportPanel.vue`、`apps/web/src/lib/feasibility.ts`、`apps/web/tests/FeasibilityReportPanel.test.ts`、`apps/web/tests/feasibility.test.ts`（后两者为 B15+B16 混合文件，含 B16 savableWithWarnings 用例，如 FeasibilityReportPanel.test.ts L86）
- e2e：`apps/web/e2e/feasibility-outcomes.spec.ts`、`apps/web/e2e/golden-journeys.spec.ts`（B15+B16 混合：含 B15 已授权中文摘要文案断言，以及 B16 新增断言——UNKNOWN 呈现为「部分地点的营业时间采用系统建议，建议出发前确认」/「待核实信息（1）」；注释明确标注 B15 与 B16 行为差异）

## G. 排除清单（B15 或更早遗留，不入 B16 commit）

**Python 更早遗留**：`domain/shared.py`、`feasibility/rules/core.py`、`infrastructure/amap/planning_provider.py`、`places/api.py`、`planning/candidates.py`、`planning/poi_quality.py` 及对应测试（`test_core_rules.py`、`test_candidate_ranking.py`、`test_must_visit_recall.py`、`test_places_api.py`、`test_poi_quality.py`）。

**Web B15**：`AuthView.vue`、`ConstraintEditor.vue`、`GuideIntelligencePanel.vue`、`ItineraryVersionPanel.vue`、`PlanningProgress.vue`、`PlanningReviewPanel.vue`、`TripDashboard.vue`、`TripDetail.vue`、`vite.config.ts`、`App.test.ts`、`PlanningProgress.test.ts`、`PlanningReviewPanel.test.ts`、`TripDashboard.test.ts`、`TripDetailPlanEvaluation.test.ts`、`TripWorkspaceActions.test.ts`、`apps/web/e2e/weather-window.spec.ts`（无 diff 改动）。e2e 另两 spec 因含 B16 断言已列入 F。

**其他**：`.omo/`、`.serena/`、`docs/audits/`、`docs/execution/B15/`（工具与历史文档，不入代码 commit）。

## H. commit 建议

1. **验收已 PASS，但按用户约束仍暂不 commit/push**（等用户明确指示）。
2. B16 代码（F 清单）独立、不影响 v9 行为；单元/契约/e2e/全链路全绿。修复（B-1a/B-1b/B-1c）已并入 B16 工作区。
3. 提交清单补充：本轮修复新增文件 `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningTaskOutcomeReadModelTest.java`；`PlanningTaskOutcomeReadModel.java`、`PlanningCompletedEventParser.java`、`contracts.py`、`test_messaging_contract_schemas.py`、`PlanningCompletedEventParserTest.java` 已列入 F 清单范围。
4. 可选后续：B-2 文案残留（B15 遗留）与 knowledge.freshness 的 schema 严格校验缺口（既有，Java 不受影响）可单独处理，不阻塞本批次。
