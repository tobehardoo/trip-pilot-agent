# B6J.2 验收报告

- 批次：B6J.2（Java Task Event、SSE、Task API、VersionSummary 闭环 + F5 typed refs）
- 验收角色：独立验收 Agent（只读）
- 分支：`codex/feasibility-foundation`
- 已提交基线：`dfc158e9b1f56c79ece1b6419027435657797cf9`
- 计划：[plan.md](plan.md)
- 执行报告：[execution-report.md](execution-report.md)
- 日期：2026-08-11
- **Verdict：NEEDS_CORRECTION**

## 1. Git 与范围审计

- branch：`codex/feasibility-foundation` ✓
- HEAD：`dfc158e9b1f56c79ece1b6419027435657797cf9` ✓（无 B6J.2 业务提交）
- staged：空 ✓；`git diff --cached --name-only` 空 ✓
- `git diff --check`：干净（仅 CRLF 警告）✓
- acceptance-report.md 写入前不存在 ✓
- 全部 tracked/untracked 改动在 plan 允许路径内（Python feasibility、Java feasibility/itinerary/planning、v9/review fixtures、B6J2 测试、架构/路线图/总控文档）
- 零改动：`apps/web/**`、schema 文件（completion-v9/review-v1/feasibility-v1/failed-v2/v8 字节级不变）、Flyway migration、Rabbit routing、repair/replan、edit/rollback、PlanEvaluation 语义、deployment/.env ✓
- `.omo/`、`.serena/`、`docs/audits/`：均为 untracked 历史遗留；`.omo/run-continuation/ses_01e226951ffes40i1Ibnaop6Om.json`（2026-08-11 17:19）为本批次执行期间产生，未 staged，非业务文件 ✓

### 精确 diff 文件清单（35 tracked M + 6 untracked ??）

Modified：
- Python：`feasibility/models.py`、`feasibility/rules/{continuity,core,coverage,duration,opening}.py`、`feasibility/validator.py`；测试 `tests/feasibility/test_{b5_characterization,continuity_rules,core_rules,hard_validator,must_visit_rule,visit_duration_rule}.py`
- Java main：`itinerary/FeasibilityEntityRefMapper.java`、`itinerary/ItineraryVersionMapper.java`、`itinerary/ItineraryVersionService.java`、`planning/PlanningCompletionService.java`、`planning/PlanningReviewService.java`、`planning/PlanningTaskEventHub.java`、`planning/PlanningTaskEventMapper.java`、`planning/PlanningTaskEventStreamService.java`、`planning/PlanningTaskService.java`
- Java test：`itinerary/FeasibilityEntityRefMapperTest.java`、`itinerary/ItineraryEditFlowIntegrationTest.java`、`planning/PlanningCompletionFlowIntegrationTest.java`、`planning/PlanningReviewFlowIntegrationTest.java`、`planning/PlanningReviewServiceTest.java`
- fixtures：`completion-v9-verified-amap.json`、`review-v1-needs-repair-demo.json`、`review-v1-unverified-demo.json`
- docs：`事件契约.md`、`行程真实性与旅行骨架.md`、`规划工作流.md`、`系统完善长期执行与验收总控计划.md`、`项目路线图.md`

Untracked（新增）：
- `apps/agent-service/src/trip_agent/feasibility/entity_refs.py`
- `apps/agent-service/tests/feasibility/test_entity_refs.py`
- `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/feasibility/FeasibilityEntityReferenceCodec.java`
- `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/feasibility/FeasibilityEntityReferenceCodecTest.java`
- `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/itinerary/FeasibilityEntityRefMapperV4Test.java`
- `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningTaskReadModelIntegrationTest.java`
- `docs/execution/B6J2/plan.md`、`docs/execution/B6J2/execution-report.md`（批次文档，验收前存在）

无额外/缺失文件。

## 2. A 组：typed refs 与 validator v4 —— **FAIL（重要功能缺陷）**

### 成立部分

- Python `entity_refs.py` 与 Java `FeasibilityEntityReferenceCodec` grammar 逐项一致：首冒号分隔、activity/transit canonical lowercase UUID、poi/text 非空可含冒号、总长 ≤200、禁控制字符、未知 kind/裸 UUID/无前缀 fail closed（逐行比对确认）✓
- `hard-validator-v4`：Python 模型 `_validate_semantics`/`_validate_repair_entity_refs` 对 v4 严格校验 rule/repair refs ✓；validator.py 真实生成 v4 ✓；active fixtures 均为 v4 ✓
- v3 legacy：`FeasibilityEntityRefMapper` 按 validatorVersion 分派，v3 走旧 UUID heuristic，未删除 ✓；文档未声称 v3 ambiguity 消失 ✓
- UUID-like POI 碰撞：`poi:<uuid>` 在 v4 下由 codec 保持 POI kind，mapper 只 remap activity/transit ✓（codec 测试 `uuidLookingPoiStaysPoi` + mapper V4 测试 `v4PoiUuidCollisionIsPreserved`）
- 未知 validatorVersion：completion 持久化 mapper fail closed（`unknownValidatorVersionFailsClosed` 单元测试）✓；`FeasibilityEntityRefMapperV4Test` 10 用例覆盖 v4 严格映射/poi 保留/bare/unknown/缺失映射 fail closed/repair refs ✓

### 关键缺陷（独立实证，probe 位于工作区外 `C:\Windows\Temp\opencode`）

`FeasibilityReportValidator.validate` **不校验 affectedEntityRefs 语法**（仅校验 evidenceRefs 非 null/非空元素）。`PlanningReviewRequiredEventParser.validateFeasibilityReport` 只调 validator + status 非 VERIFIED 检查，**无任何 refs 校验**。`PlanningReviewService.handle` 也无 refs 防线。review 路径不经过 `FeasibilityEntityRefMapper`（mapper 只在 completion 持久化时调用），因此 mapper 校验不能作为 review 安全证据。

用真实 fixture 构造反例喂给真实 `PlanningReviewRequiredEventParser`（Java 21，Spring Boot 3.5.4 classpath）：

| 输入 | Java parser 结果 | Python 模型结果 |
| --- | --- | --- |
| baseline-valid | ACCEPTED → WAITING_USER | ACCEPTED |
| v4 + `affectedEntityRefs=["8f5ef9c2-..."]`（裸 UUID） | **ACCEPTED → WAITING_USER** | REJECTED |
| v4 + `affectedEntityRefs=["unknown:value"]` | **ACCEPTED → WAITING_USER** | REJECTED |
| unknown validatorVersion + 空 refs | **ACCEPTED → WAITING_USER** | ACCEPTED |
| unknown validatorVersion + 裸 UUID ref | **ACCEPTED → WAITING_USER** | REJECTED |

违反 plan 不可变决策 2（"未知 kind、空 value、裸 UUID、无前缀字符串在 v4 中 fail closed"）与验收指令 A 组第 4/5 条（"review parser/service 也不能让未知版本或非法 v4 refs 进入 WAITING_USER"）。Python 与 Java 对同一输入行为不一致（跨语言语义漂移）。

**为什么现有测试未发现**：`FeasibilityEntityReferenceCodecTest` 只测 codec 单元（10 用例，不接线 parser）；`FeasibilityReportContractTest` 的 invalid fixtures 不包含非法 refs 变体；`PlanningReviewRequiredEventParserTest` 8 用例无 refs 反例；无任何测试覆盖"review + 非法 v4 refs"。

## 3. B 组：completion report 单一结果 —— PASS

- `persistFeasibilityReport` 返回 remapped JSON，同一字符串写 V33 `report_json` 与 `CompletionPayload.feasibilityReport`（JsonNode）✓ 生产代码确认同源
- `completionTaskEventPayloadContainsVerifiedReportMatchingV33`：真实 DB 读回 V33 与 task event payload，`assertThat(eventReport).isEqualTo(v33Report)` **深结构相等**（非 contains）✓
- activity/transit refs 断言为持久化 ID（jdbcTemplate 查真实行）✓；poi/text 保留由 mapper V4 测试覆盖 ✓
- evaluation 引用映射未退化（`remapEvaluation` 调用保持）✓
- report insert 失败整事务回滚：`reportInsertFailureRollsBackTheWholeCompletionTransaction`（B6J.1.1 已验收，保持）✓
- **缺口（非阻断）**：无"PLANNING_COMPLETED task-event insert 在 version/report 写入后失败"的直接测试（仅有 activity/transit/report insert failure 与 review event failure）。`@Transactional` + `requireOne` 保证语义，但验收指令 B 组第 7 项要求的特定失败点未直接覆盖。执行报告未声称此项已覆盖（R2 只写 report 回归），故为测试缺口而非报告不实。

## 4. C 组：Task API 六态真值表 —— **FAIL（重要功能缺陷）**

生产代码 `PlanningTaskService.readTerminalMetadata` 对 `feasibilityReport`/`candidateItinerary` 仅做：
```java
optionalNode(payload, "feasibilityReport"),
optionalNode(payload, "candidateItinerary")
```
`optionalNode` 是纯透传（`payload.get(field)`，null 时返回 null）。`parseEvaluation` 同样透传任何 `evaluation` 字段。**无 eventType/status 联合语义验证**。

独立实证（probe 模拟 read model 解析逻辑，payload 语义由 `findLatestTerminal` + `readTerminalMetadata` 原样透传）：

| 反例 | read model 输出 |
| --- | --- |
| WAITING_USER payload 意外带 evaluation | evaluation 被暴露 |
| SUCCEEDED payload 带 NEEDS_REPAIR report | NEEDS_REPAIR 被暴露（伪造非 VERIFIED） |
| SUCCEEDED payload 带 candidateItinerary | candidate 被暴露 |

违反 plan 不可变决策 3 真值表（SUCCEEDED：candidate=null；WAITING_USER：evaluation=null；禁止伪造 VERIFIED 反向即禁止暴露非 VERIFIED 于 SUCCEEDED）。

**测试真实性评估**：`getTaskSurfacesEveryOutcomeStatus` 真实运行（六状态经 API 返回断言），非假绿——但手工插入的 payload 恰好语义正确（WAITING_USER 无 evaluation、SUCCEEDED 无 candidate），只断言 status 字符串 + 部分字段存在，**未断言 evaluation/candidate 的 null/非 null 语义**，未覆盖任何真值表反例。执行报告 R3 声称"六态真值表 + malformed fail closed"——malformed（payload 非 object → IllegalStateException）成立，但真值表语义在读模型层面不成立。

**缓解因素**：正常写入路径由 Python/Java 模型保证 payload 语义正确（review 模型无 evaluation 字段、completion payload 无 candidateItinerary 字段、completion 强制 VERIFIED），故真实业务流不产生上述组合。但验收指令明确要求读模型 enforce 语义（"禁止从 evaluation 推导 feasibility；禁止伪造 VERIFIED；禁止为 WAITING_USER 生成 evaluation"），当前读模型不执行。

## 5. D 组：SSE live/replay —— 部分通过（报告与证据不一致）

- replay 使用真实 DB task_event（`findAfter`）✓；live 使用 `@TransactionalEventListener(AFTER_COMMIT)` ✓
- `toView` 从 DB payload 读 JSON，live/replay 同一来源（生产层结构一致成立）✓
- WAITING_USER/SUCCEEDED 流终止：`isTerminal` 含 PLANNING_REVIEW_REQUIRED、`TERMINAL_STATUSES` 含 WAITING_USER ✓；R4 两个测试验证（replay 10s 内终止 + live 终止）✓
- Last-Event-ID 不重放旧事件：`replaysOnlyTaskEventsAfterTheLastSeenEventAndClosesATerminalStream`（completion）+ R4 replay（review）✓
- owner isolation：`hidesTheTaskEventStreamFromAnotherUser` ✓
- event id 来自存储记录：`PlanningReviewService.stored()` 读回 DB record 再发布（handle + persistStaleFailure 两处）✓；completion 沿用 `insertTaskEvent` 读回 ✓；单测 fake 修复（insert 回填 eventByEventId 带 id=1L）模拟真实 insert/find，合理非掩盖 ✓

**缺陷（报告与证据不一致）**：执行报告 R4 声称"payload 深结构断言"，实际 SSE 测试：
- review live：`containsString("\"candidateItinerary\"")` / `containsString("\"feasibilityReport\"")` / `containsString("\"NEEDS_REPAIR\"")` —— 只检查字段名出现，非深比较
- completion live/replay：`containsString("event:PLANNING_COMPLETED")` —— 完全未断言 report payload 内容

验收指令第七组明确禁止"用 containsString 代替 JSON 深比较"，并要求"completion 是否同时有 live 与 replay 的 report 断言"——不满足。report 内容完整性由 B 组 R2 测试（task event payload vs V33 深比较）间接覆盖，但 SSE 通道本身无 report 断言。

## 6. E 组：VersionSummary —— PASS

- 单次 LEFT JOIN（`findAllOwned` SQL 确认），无 N+1 ✓
- `listsVersionSummariesWithNestedFeasibilityMetadataAndNullForHistory`：真实 completedItinerary + USER_EDIT，reportId/schemaVersion/validatorVersion/status/itineraryFingerprint/validatedAt 与 V33 行逐字段一致（`report_json ->> 'validatedAt'` 对齐）✓
- 历史无 report → `"feasibility": null` 显式断言（`.value(nullValue())`，正确测试前提）✓
- summary 不含完整 reportJson（record 仅 6 个元数据字段）✓
- 排序/current/owner isolation：既有 24 用例回归通过 ✓
- fail closed：V33 表全部 metadata 列 NOT NULL + DB CHECK 约束（status='VERIFIED'、schema_version=1、fingerprint 64hex、report_json 与列一致）兜底，LEFT JOIN 无 report 行为 null，无部分异常路径可构造 ✓

## 7. F 组：review 事务与 live 修复 —— PASS

- `taskEventInsertFailureRollsBackTheWholeReviewTransaction`：BEFORE INSERT ON planning_task_event trigger 命中真实 insert（rootCause "forced task event failure"），finally 可靠 DROP ✓
- 断言：task 停留 QUEUED 原版本、planning_task_event 仅 1（QUEUED）、无 itinerary/version/report ✓
- `PlanningReviewService` 两条发布路径（handle + persistStaleFailure）均经 `stored()` 读回存储 record 再发布，无 id=null record 发布 ✓
- 单测 fake 修复：`insert` 回填 `eventByEventId`（带 id=1L），模拟真实 DB insert→find 语义；`persistsCompleteCandidatePayload` 等通过 ✓

## 8. G 组：报告和文档真实性 —— 部分通过（有缺陷）

- 状态仍为 IN_PROGRESS：执行报告自述未更新为 READY_FOR_REVIEW（批次文档惯例，可接受但不规范）
- **重复标题残留**：88-94 行存在 `## R6：review 事务回归（未开始）` + `## R5：VersionSummary（未开始）` 重复占位，随后才是真实 R6 内容——文档缺陷
- **R4 声称"payload 深结构断言"与实际 containsString 不符**（见 D 组）
- **R3 声称"六态真值表 + malformed fail closed"**：malformed 部分成立，真值表语义在读模型层不成立（见 C 组）
- 123 行"等待独立验收（B6F）"：B6J.2 的独立验收不是 B6F（B6F 在 B6J.2、B6W 均验收提交后才开始）——表述不当
- v3 legacy ambiguity 描述准确（未声称消失）✓；总控计划 B6J.2 状态表"实现完成（未提交）"符合"未提交不得写成 COMMITTED"✓

## 9. 独立测试门禁结果（验收复跑）

Python（apps/agent-service）：
- 定向：`tests/feasibility + outcome_events + outcome_flow` = **375 passed** ✓
- 全量：`uv run python -m pytest --basetemp C:\Windows\Temp\codex-b6j2-accept-py-full` = **1280 passed, 37 skipped** ✓
- ruff check `src/trip_agent/feasibility tests/feasibility`：All checks passed ✓
- ruff format --check `entity_refs.py test_entity_refs.py`：2 files already formatted ✓

Java（仓库根）：
- 定向（11 类）：**212 passed, 0 failures/errors** ✓
- `mvn --batch-mode -pl apps/travel-server verify`：**BUILD SUCCESS**；tests run: **346**, failures: 0, errors: 0, skipped: 0 ✓
- JaCoCo：`All coverage checks have been met.` ✓
- Flyway：干净库成功迁移至 v33 ✓

仓库门禁：
- `python scripts/check_markdown_links.py`：**84 files valid** ✓
- `git diff --check`：干净（仅 CRLF 警告）✓
- `git diff --cached --name-only`：空 ✓
- staged 空、未 commit、未 push ✓

## 10. 发现项汇总

| # | 严重度 | 位置 | 描述 | 影响 |
| --- | --- | --- | --- | --- |
| F1 | 严重 | `PlanningReviewRequiredEventParser.validateFeasibilityReport`（387-401）；`FeasibilityReportValidator`（35-135 无 refs 校验） | review 路径无 v4 refs 语法校验；实证 v4+裸 UUID、v4+unknown kind、未知版本+裸 ref 均 ACCEPTED 进入 WAITING_USER；Python 模型拒绝同类输入 | 违反 plan 决策 2 fail closed 语义；跨语言漂移；非法 refs 可入库并流向 API/SSE |
| F2 | 严重 | `PlanningTaskService.readTerminalMetadata`（422-446） | read model 对 feasibilityReport/candidateItinerary/evaluation 原样透传，无 eventType/status 联合语义校验；实证 WAITING_USER+evaluation、SUCCEEDED+NEEDS_REPAIR、SUCCEEDED+candidate 均被暴露 | plan 决策 3 真值表在读模型层不成立；执行报告"六态真值表"夸大 |
| F3 | 中等 | R4 SSE 测试（`PlanningReviewFlowIntegrationTest` 358-384；`PlanningCompletionFlowIntegrationTest` 1052-1098） | SSE 测试用 containsString 检查字段名，非深比较；completion SSE 无 report 断言 | 执行报告 R4"payload 深结构断言"与证据不符；SSE 通道 report 完整性未被直接测试 |
| F4 | 中等 | `execution-report.md` 88-94 行 | 重复 `## R6`/`## R5` 标题与"未开始"残留 | 文档缺陷（SMALL_FIX 级） |
| F5 | 小 | `execution-report.md` 123 行 | "等待独立验收（B6F）"表述不当；B6J.2 独立验收不是 B6F | 语义混淆 |
| F6 | 小 | 测试缺口 | 无 completion 未知 validatorVersion 的 service 直调集成测试（mapper 单元覆盖 remap fail closed，集成链未直测）；无 PLANNING_COMPLETED task-event insert 失败点测试 | 测试缺口，生产语义由代码保证 |

## 11. Verdict

**NEEDS_CORRECTION**

B 组（completion 单一结果）、E 组（VersionSummary）、F 组（review 事务/live 修复）真实成立且测试可信；全部门禁（Python 1280、Java 346、JaCoCo、Flyway V33、markdown links、git 干净）通过；范围零越界。

但 A 组与 C 组为验收指令明确禁止通过的功能缺陷：
- **A 组**：review 能接受非法 v4 ref（裸 UUID、unknown kind）与未知 validatorVersion 并进入 WAITING_USER——验收指令 A 组明文"若 review 能接受非法 v4 ref 并进入 WAITING_USER，这是重要功能缺陷，不能 PASS"。
- **C 组**：Task API 读模型未执行 plan 决策 3 真值表语义（原样透传，反例全部暴露）——验收指令 C 组明文"如果只是原样透传 JsonNode，没有 eventType-aware 语义验证，则执行报告中的'六态真值表 + malformed fail closed'不成立"。

另有 D 组报告与证据不一致（containsString 冒充深比较）与 G 组文档残留。

**修复方向（供下一轮执行）**：
1. A 组：在 `FeasibilityReportValidator.validate`（或 `PlanningReviewRequiredEventParser.validateFeasibilityReport`）对 v4 report 的 ruleResults/repairAttempts.affectedEntityRefs 逐个调用 `FeasibilityEntityReferenceCodec.validate`（非法 → IllegalArgumentException → contract rejection）；未知 validatorVersion 在 review 路径 fail closed（与 completion mapper 一致）；补 review parser 反例测试（裸 UUID、unknown kind、未知版本），并与 Python 行为对齐。
2. C 组：`readTerminalMetadata` 增加 eventType/status-aware 语义校验（如 PLANNING_REVIEW_REQUIRED 且带 evaluation → fail closed；PLANNING_COMPLETED report status 非 VERIFIED → fail closed；SUCCEEDED 带 candidateItinerary → fail closed；FAILED/CANCELLED 带 report/candidate → fail closed），或按 plan 决策 3 在读取时过滤/拒绝非法组合；补真值表反例测试。
3. D 组：SSE 测试改为对 SSE payload JSON 深比较（解析 event data 与 DB task_event payload 逐字段相等），completion live+replay 补 report 断言；执行报告如实描述。
4. G 组：删除 execution-report 重复 R5/R6 占位标题；修正"B6F"表述为"独立验收"。

**禁止提交**：A/C 组缺陷修复前不得进入 Git 提交收口。

## 12. B6F 状态

B6F 尚未开始。B6F 只有在 B6J.2、B6W 均独立验收 PASS 并提交后才开始；本报告为 B6J.2 独立验收（NEEDS_CORRECTION），不构成 B6F。本报告不 stage、不 commit、不 push，未修改任何业务代码/测试/文档（probe 均在 `C:\Windows\Temp\opencode` 工作区外，已清理）。

---

# B6J.2.1 重新验收

- 日期：2026-08-12
- 验收角色：独立重新验收 Agent（只读）
- **Verdict：NEEDS_SMALL_FIX**

## 1. 前置 Git 状态

- branch：`codex/feasibility-foundation` ✓
- HEAD：`dfc158e9b1f56c79ece1b6419027435657797cf9` ✓（无 B6J.2/B6J.2.1 提交）
- staged：空 ✓；`git diff --cached --name-only` 空 ✓
- `git diff --check`：干净（仅 CRLF 警告）✓
- B6J.2.1 增量全部 unstaged；旧 acceptance-report（NEEDS_CORRECTION）保留未动 ✓
- 范围：`PlanningTaskOutcomeReadModel.java`（新增）、`FeasibilityReportValidator.java`、`PlanningReviewService.java`、`PlanningCompletionService.java`、`PlanningTaskService.java`、`PlanningTaskEventMapper.java`、Python `models.py`、相关测试、execution-report/总控文档——无 Web/schema/Flyway/Rabbit/repair/edit/rollback 越界 ✓
- `.omo/`、`.serena/`、`docs/audits/` 未处理 ✓

## 2. A 组重新验收：typed refs 与 validatorVersion —— PASS

### 版本白名单一致性（Python/Java 逐字比对）

| validatorVersion | Python `models.py` | Java `FeasibilityReportValidator` |
| --- | --- | --- |
| feasibility-v1 / hard-validator-v1/v2/v3 | legacy 放行 | legacy 放行（同集合） |
| hard-validator-v4 | strict（RuleResult + RepairAttempt refs 过 grammar） | strict（同一 codec） |
| 其他任意 | `ValueError` 拒绝 | `IllegalArgumentException` 拒绝 |

Python `_LEGACY_VALIDATOR_VERSIONS = {feasibility-v1, hard-validator-v1/v2/v3}` + `_V4_VALIDATOR_VERSION` 与 Java 常量逐项一致；两端均删除"未知版本当 strict"逻辑，未知版本无论 refs 是否为空都拒绝。

### 独立复现（probe，工作区外）

review parser（真实 `PlanningReviewRequiredEventParser`）对真实 fixture 变异输入：

| 输入 | 结果 |
| --- | --- |
| baseline-valid | ACCEPTED → WAITING_USER |
| v4 + 裸 UUID | REJECTED（invalid entity reference） |
| v4 + unknown:value | REJECTED |
| v4 + 非规范 activity UUID | REJECTED |
| unknown version + 空 refs | REJECTED（unknown validatorVersion） |
| unknown version + typed refs | REJECTED |

原 A 组缺陷（review 接受非法 v4 ref 进入 WAITING_USER）已关闭。

### 同一 validator 复用

`PlanningCompletedEventParser:523`、`PlanningReviewRequiredEventParser:394`、`PlanningCompletionService:155`、`PlanningReviewService:162` 均调用同一 `FeasibilityReportValidator.validate`——无复制版本判断。review service 在 `markWaitingUser` 前（85 行）调 `validateReport`，非法报告不置 WAITING_USER；completion service 在 `persistFeasibilityReport` 入口调 validator，非法 → IllegalStateException 事务回滚。

### service bypass

`serviceRejectsInvalidV4ReportEvenWhenCalledDirectly` / `serviceRejectsUnknownValidatorVersionEvenWhenCalledDirectly`（review + completion 各 2 个，共 4 个）用 `treeToValue` 绕过 parser 直调 service，断言 reject/回滚（task 停留 QUEUED、仅原始 QUEUED 事件、无 version）。Java 定向通过。

### v3 legacy 与 UUID-like POI

`legacyVersionsKeepUnprefixedRefsCompatible`（feasibility-v1/v1/v2/v3）通过；`v4PoiUuidCollisionIsPreserved`（mapper V4）确认 `poi:<uuid>` 不被错误映射 ✓。

## 3. C 组重新验收：Task API 六态 —— PASS

`PlanningTaskOutcomeReadModel` 使用 `task.status` + `PlanningTaskEventRecord.eventType()` + payload 语义联合分派（读源码确认，非 JsonNode 透传）：

| 组合 | 行为 |
| --- | --- |
| PLANNING_COMPLETED + SUCCEEDED | report 经 validator 且 VERIFIED + evaluation 非空 + candidate absent；否则 fail closed |
| PLANNING_REVIEW_REQUIRED + WAITING_USER | report 非 VERIFIED + candidate 结构校验 + fingerprint 格式合法 + evaluation absent；否则 fail closed |
| PLANNING_FAILED + FAILED / PLANNING_CANCELLED + CANCELLED | 三者均须 absent；否则 fail closed |
| 其他组合/非对象 payload | IllegalStateException |

`PlanningTaskReadModelIntegrationTest` 19/19 通过（独立复跑）：六态正例 7 + 负向反例 12（WAITING_USER+evaluation、WAITING_USER+VERIFIED、缺 candidate、malformed candidate、malformed fingerprint、SUCCEEDED+candidate、SUCCEEDED+NEEDS_REPAIR、SUCCEEDED 缺 evaluation、FAILED+report、CANCELLED+evaluation、status/eventType 不匹配、report 缺必填字段、payload 数组）。反例经 DB 直插非法 payload + `planningTaskService.get` 断言 IllegalStateException——真实 fail closed，非仅 status 字符串断言。

`findLatestTerminal` → `findLatestOutcome`（含 PLANNING_CANCELLED）✓。

## 4. fingerprint 边界专项 —— NEEDS_SMALL_FIX（缺口登记）

### 真实数据流追踪（probe 实证）

- **正常路径**：review/completion 事件必经 Rabbit listener → parser → service；两个 parser 均在反序列化后用 `ItineraryFingerprintVerifier.matches(wireItinerary, reportFingerprint)` 强制绑定（`PlanningReviewRequiredEventParser:237`、`PlanningCompletedEventParser:144`）。**正常生产路径无法持久化 fingerprint mismatch** ✓
- **stored candidate 与 wire 不一致**：probe 实证 `valueToTree(stored DTO) == wire: false`（`TransitLeg.costSource` 默认 "UNKNOWN"、BigDecimal 规范化等），wire fp match=true 而 stored fp match=false——**stored candidate 复算必然失败**，read model 无法对 raw stored candidate 做 fingerprint 复算（会误杀所有合法 review）。执行报告声明属实。
- **service 绕过 parser**（`treeToValue` 直调，仅测试路径）：两个 service 均不复算 fingerprint——`PlanningReviewService` 无 fingerprint 校验，`PlanningCompletionService` 只存 `report.itineraryFingerprint()`。**但 B6J.2.1 已加 validator**（结构/refs/版本），且该路径非生产可达（无生产代码绕过 parser 直调 service）。**残余风险**：绕过 parser 的构造事件可带 mismatch fingerprint 入库。
- **read model 对篡改 stored payload**：`parseReport`（validator）拒结构非法 report；`isValidCandidate` 拒结构非法 candidate；但 **fingerprint mismatch 的 stored payload 被原样返回**（只查 `^[0-9a-f]{64}$` 格式，不复算匹配）。

### 判定

按验收指令："如果只有直接数据库损坏场景未复算，但 read model 已承诺 malformed stored payload fail closed，则至少登记为 NEEDS_SMALL_FIX"。当前：
- 正常路径无 fingerprint 绕过（parser 强制）→ 不构成 NEEDS_CORRECTION
- 只读 DB 损坏场景（手工篡改 stored payload 的 fingerprint 字段为合法 64 hex 但 mismatch）→ read model fail open，未复算
- read model 对结构 malformed payload 已 fail closed（validator + isValidCandidate）
- **登记为 NEEDS_SMALL_FIX 缺口 S1**：read model 的 `readReview` 可对 raw stored candidate 尝试 fingerprint 校验并**宽容 DTO 规范化差异**（或至少在 mismatch 时 fail closed 而非 fail open），以覆盖 DB 损坏场景；当前实现 fail open。

## 5. D 组重新验收：SSE 深比较 —— PASS

四条链路（review live/replay、completion live/replay）均：
- 解析 SSE frame 的 id/event/data（`parseSseFrames` helper）
- data 转 JsonNode（UTF-8 字节解码，非 `getContentAsString()` 默认编码）
- `data.path("payload")` 与 DB task_event payload `isEqualTo` **深比较**
- event id 断言为 DB 行 id（`TaskEventView.eventId` 是 DB id）+ eventId/taskId/eventType/schemaVersion 与 DB 一致
- review：report + candidate 完整、evaluation 无；completion：report + evaluation 完整、candidate 无
- WAITING_USER/SUCCEEDED 流终止（`getAsyncResult` 10s 内完成）、Last-Event-ID 不重放旧事件、owner isolation（既有测试）

containsString 仅保留于 `replaysProviderFailureMetadataThroughTheTerminalSseEvent` 的 provider 元数据 smoke 断言（非业务 payload 证据）✓。UTF-8 修复用 `getContentAsByteArray()` + `StandardCharsets.UTF_8`，非字符替换掩盖 ✓。

## 6. B 组补充：completion terminal-event failure —— PASS

`completedTaskEventInsertFailureRollsBackTheWholeCompletionTransaction`（PlanningCompletionFlowIntegrationTest）：
- BEFORE INSERT trigger 仅对 `NEW.event_type = 'PLANNING_COMPLETED'` 抛 `forced completed event failure`（version/day/activity/transit/report 先写入，terminal event 最后写入——同一事务）
- `assertThatThrownBy(...).rootCause().hasMessageContaining("forced completed event failure")` 证明 trigger 命中目标 insert
- 断言 itinerary/version/day/activity/transit/report 全零、task=QUEUED、仅原始 QUEUED 事件
- finally 可靠 DROP trigger/function
- 非 activity/transit/report 旧失败测试冒充 ✓（独立新增）

## 7. E/F 回归 —— PASS

- VersionSummary：ItineraryEditFlowIntegrationTest 24/24（含 `listsVersionSummariesWithNestedFeasibilityMetadataAndNullForHistory`：单次 LEFT JOIN、6 字段与 V33 一致、历史 null、无 reportJson）；B6J.2.1 未触碰 ItineraryVersionMapper/Service ✓
- review 事务：`taskEventInsertFailureRollsBackTheWholeReviewTransaction` 在 ReviewFlowIntegrationTest 9/9 中通过；`PlanningReviewService.stored()` 两条发布路径（handle:116 + persistStaleFailure:132）均读回 DB record 再发布，无 id=null record ✓
- fake mapper 修复（insert 回填 eventByEventId 带 id）模拟真实语义，非掩盖 ✓

## 8. G 组报告真实性 —— 部分通过（S2）

- 状态改为 READY_FOR_REVIEW ✓；重复 R5/R6 标题已清理、无"未开始"残留 ✓
- "等待 B6F"已改为"等待 B6J.2 重新独立验收（不是 B6F）" ✓
- B6J.2.1 章节承认 NEEDS_CORRECTION 原因（A/C/D/G 缺陷）并追加真实 RED/GREEN ✓
- 原失败历史保留（未删除）✓；B6F/B6W 未写成已开始 ✓；总控计划"修复完成，待重新验收（未提交）"非 COMMITTED/PASS ✓
- **S2（小）**：B6J.2.1 章节未用明确措辞逐条承认"原 R3 六态声明不成立""原 R4 深比较声明不成立"（仅隐含于缺陷列表）——报告仍基本如实，措辞可补强

## 9. 独立测试门禁（验收复跑）

Python（apps/agent-service）：
- 定向 `tests/feasibility`：**362 passed**；outcome_events + outcome_flow：**19 passed**
- 全量：**1286 passed, 37 skipped**
- ruff check `src/trip_agent/feasibility tests/feasibility`：All checks passed；format --check `models.py test_feasibility_models.py`：already formatted

Java（仓库根）：
- 定向（10 类）：**224 passed, 0 failures/errors**（FeasibilityReportContractTest 48、Codec 10、Mapper 6、MapperV4 10、CompletedParser 54、ReviewParser 14、CompletionFlow 42、ReviewFlow 9、ReviewService 12、TaskReadModel 19）
- 全量 `mvn verify`：**BUILD SUCCESS**；tests run: **382**, failures: 0, errors: 0, skipped: 0；JaCoCo `All coverage checks have been met.`；Flyway 干净库迁移至 v33

仓库：
- `python scripts/check_markdown_links.py`：**85 files valid**
- `git diff --check`：干净；`git diff --cached --name-only`：空（staged 空）

## 10. 发现项汇总

| # | 严重度 | 位置 | 描述 | 影响 |
| --- | --- | --- | --- | --- |
| S1 | 小 | `PlanningTaskOutcomeReadModel.readReview`（123-125 行） | 只读 DB 损坏场景：stored payload 的 fingerprint 若为合法 64 hex 但与 candidate mismatch，read model fail open（原样返回），不复算校验；service 绕过 parser 路径亦不校验 fingerprint 一致性 | 正常路径无绕过（parser 强制）；仅直接 DB 篡改场景未复核；结构 malformed 已 fail closed |
| S2 | 小 | `execution-report.md` B6J.2.1 章节 | 未用明确措辞逐条承认"原 R3 六态声明不成立 / 原 R4 深比较声明不成立"（隐含于缺陷列表） | 报告措辞可补强，内容基本如实 |

## 11. Verdict

**NEEDS_SMALL_FIX**

A 组（parser/service 双层 fail-closed、版本白名单一致、v3 legacy 兼容）、C 组（六态 + 12 反例真实 fail closed）、D 组（SSE 四链路深比较）、B 组补充（completion terminal-event 回滚）、E/F 回归全部真实成立，独立复跑全部门禁通过（Python 1286、Java 382、JaCoCo、Flyway V33、markdown links 85、git 干净）。

**S1**（fingerprint 只读 DB 损坏场景 fail open）与 **S2**（报告承认措辞不完整）为明确、有限、不改变架构的小问题，按验收指令第五组判定纪律登记为 NEEDS_SMALL_FIX。

**修复建议（供下一轮执行）**：
1. S1：`readReview` 对 raw stored candidate 尝试 `ItineraryFingerprintVerifier.matches`；因 stored candidate 与 wire 有 DTO 规范化差异，需在复算前按 fingerprint verifier 的 canonicalise 规则归一化或宽容 costSource/数值规范化；若无法可靠复算，则对 fingerprint 与 candidate 均存在但无法验证一致性的场景 fail closed（而非 fail open），并补"stored fingerprint mismatch → 拒绝"的反例测试。或在 service 层补 fingerprint 一致性校验（绕过 parser 时也不可持久化 mismatch）。
2. S2：execution-report B6J.2.1 章节补明确句："原 R3 '六态真值表' 声明不成立（read model 曾原样透传）；原 R4 'payload 深结构断言' 声明不成立（SSE 测试曾用 containsString）"。

**允许 Git 收口**：S1/S2 修复后可进入 B6J.2 重新验收收口；当前 NEEDS_SMALL_FIX 状态下不禁止修复后收口，但本报告不授权当前状态直接提交。

## 12. B6W/B6F 状态

B6W、B6F 均尚未开始。B6F 需 B6J.2、B6W 均独立验收 PASS 并提交后才开始。本报告为 B6J.2.1 重新验收（NEEDS_SMALL_FIX），不构成 B6F；未 stage、未 commit、未 push，未修改任何业务代码/测试/文档（probe 均在 `C:\Windows\Temp\opencode` 工作区外）。

---

# B6J.2.2 最终重新验收

- 日期：2026-08-12
- 验收角色：独立最终验收 Agent（只读）
- **Verdict：PASS**

## 1. 前置 Git 状态

- branch：`codex/feasibility-foundation` ✓
- HEAD：`dfc158e9b1f56c79ece1b6419027435657797cf9` ✓（无 B6J.2/B6J.2.1/B6J.2.2 提交）
- staged：空 ✓；`git diff --cached --name-only` 空 ✓
- `git diff --check`：干净（仅 CRLF 警告）✓
- B6J.2.2 全部改动 unstaged；acceptance-report 保留原 NEEDS_CORRECTION + NEEDS_SMALL_FIX 历史 ✓
- 范围：B6J.2.2 增量限于 `PlanningReviewRequiredEvent.java`、`PlanningReviewRequiredEventParser.java`、`PlanningReviewService.java`、`PlanningTaskOutcomeReadModel.java`（生产）+ 4 个测试文件 + execution-report——无 Web/Schema/Flyway/Rabbit/repair/edit/rollback 越界 ✓
- `.omo/`、`.serena/`、`docs/audits/` 未处理 ✓

## 2. S1-A：内部原始快照安全 —— PASS

独立 probe（`C:\Windows\Temp\opencode\ProbeS1A`，工作区外）实证：

| 检查点 | 结果 |
| --- | --- |
| 序列化 parsed event 无 validatedItineraryJson/rawItinerary/validatedCandidate | 无泄漏（JSON tree 检查，非注解推断） |
| 快照与输入 wire itinerary 深相等 | true |
| 修改原始 JsonNode 后快照不变（deepCopy 捕获） | true（title 保持 Benchmark itinerary） |
| 修改 accessor 返回值后内部快照不变（accessor deepCopy） | true |
| wire body 伪造 validatedItineraryJson 字段 | 反序列化后快照为 null（`@JsonIgnore` 不接受外部字段，无法伪装已验证快照） |

- `@JsonIgnore` 在 record component 上同时满足：序列化不输出 ✓、反序列化不接受外部 wire 字段 ✓、accessor 返回 deepCopy 不暴露可变引用 ✓
- 快照字段非 review v1 wire 契约（Schema/Producer/Rabbit 零改动）✓
- 兼容构造器（旧签名 → null）保留，缺快照不静默补造 ✓
- Parser 在 `validate(event)`（含 `ItineraryFingerprintVerifier.matches`）后调用 `withValidatedItinerary(event, tree.at("/payload/itinerary").deepCopy())`——捕获顺序正确（schema/type → 语义 → fingerprint → 快照）✓

## 3. S1-B：Parser 保存原始 wire candidate —— PASS

- R1 测试 `snapshotDeepEqualsInputWireItinerary`：快照与原始 wire `isEqualTo` ✓（probe 独立复现）
- 快照保留 wire 显式 null、provider metadata、costSource、dayType/kind/timeFixed、coordinates/address、transit 数据（deepCopy 原样，无 DTO 默认值补造/丢失）✓
- `fingerprintMismatchStillRejectedWithSnapshotDesign`：mismatch 仍被 parser 拒绝 ✓
- strict parser（FAIL_ON_UNKNOWN_PROPERTIES 于 `validateJsonTypes` 上游）拒未知字段，不把未知字段带进 task_event ✓（B6J.2.1 既有）

## 4. S1-C：Service bypass 第二道门禁 —— PASS

`validateCandidateIntegrity`（`PlanningReviewService`，在 `markWaitingUser`/task_event insert/SSE publish 之前，handle 第 86 行）：

1. 快照缺失/非 object → reject（"missing its validated itinerary snapshot"）✓
2. raw/report fingerprint mismatch → reject ✓
3. `FAIL_ON_UNKNOWN_PROPERTIES` 严格反序列化（未知字段/缺必填/类型错误 → JsonProcessingException → reject）✓
4. raw→typed 与 `event.payload().itinerary()` 完整 record `equals`（BigDecimal scale、list 顺序、nested activity/transit、provider metadata 全含）✓
5. `validateReport`（B6J.2.1）仍先执行（非法 typed refs/unknown validatorVersion → reject）✓

R4 集成测试（`serviceRejectsBypassEventWithoutRawCandidateSnapshot`/`WithFingerprintMismatch`/`WithRawTypedInconsistency`/`WithUnknownRawField`）真实绕过 parser 直调 service，断言 reject + task 状态/version 不变 + 无 review event。单测 `reviewEvent()` 显式提供合法快照（非测试专用默认值绕过）。合法生产 fixture 正常路径（R2）通过——**无"合法 fixture 被 DTO equality 拒绝"缺陷**。

## 5. S1-D：Wire → DB → API → SSE 同一 candidate —— PASS

- **wire → DB**：R2 `storedCandidateDeepEqualsWireItineraryAndBindsFingerprint` 断言 `storedCandidate.isEqualTo(wireItinerary)` + `ItineraryFingerprintVerifier.matches(storedCandidate, reportFingerprint)` ✓
- **DB → API**：`PlanningTaskOutcomeReadModel.readReview` 返回 raw candidate JsonNode（不转换），`PlanningTaskService.toTerminalMetadata` 透传 → API candidate 与 DB candidate 同一节点（代码审阅确认）。**轻微缺口**：无测试显式断言 `API candidate == DB candidate` 的 `isEqualTo`（仅断言 title/days 存在）——逻辑可推得（read model 不改写 payload），登记为 M1（非功能缺陷）
- **DB → SSE**：B6J.2.1 SSE 深比较测试 `data.payload` 与 DB payload `isEqualTo`（raw candidate 下保持，16/16 通过）✓
- report fingerprint 匹配 DB/API/SSE candidate（同一 raw 树 + read model 复算）✓
- API/SSE 无内部 snapshot 字段 ✓；review evaluation 无 ✓；不创建正式版本 ✓；WAITING_USER 流终止 ✓；live event id 来自持久化 record ✓；replay 遵守 Last-Event-ID ✓

## 6. S1-E：DB 篡改 fail closed —— PASS

- 场景一 `tamperedStoredCandidateFailsClosedOnTaskApi`：篡改 activity title（fingerprint 参与字段），report 不变 → `planningTaskService.get` 抛 IllegalStateException；**控制组**篡改前同一 task 正常返回 WAITING_USER ✓
- 场景二 `tamperedStoredFingerprintFailsClosedOnTaskApi`：candidate 不变，fingerprint 换为另一合法 64-hex → fail closed ✓
- read model 真正调用 `ItineraryFingerprintVerifier.matches(candidate, report.itineraryFingerprint())`（121 行），非仅 64 hex 格式检查 ✓

## 7. S2：执行报告真实性 —— PASS

execution-report B6J.2.2 章节第 8 节明确、直接承认（非模糊措辞）：
1. 原 B6J.2 R3 "六态真值表 + malformed fail closed 已完成"声明不成立（原 read model 原样透传、反例可穿透、B6J.2.1 才关闭）✓
2. 原 B6J.2 R4 "SSE live/replay 已深结构验证"声明不成立（原测试主要 containsString、B6J.2.1 才深比较）✓
3. B6J.2.1 遗留 S1（DTO round-trip 破坏绑定、DB 篡改 fail open、B6J.2.2 raw snapshot 修复）✓

原执行历史保留未删；头部状态 READY_FOR_REVIEW ✓；总控计划"修复完成，待重新验收（未提交）"（非 PASS/COMMITTED）✓；B6W/B6F NOT_STARTED ✓。

## 8. 此前通过项回归 —— PASS

| 组 | 验证 | 结果 |
| --- | --- | --- |
| A typed refs | FeasibilityReportContractTest 48、Codec 10、Mapper 6、MapperV4 10、CompletedParser 54 | 128/128 ✓ |
| C Task API 六态 | PlanningTaskReadModelIntegrationTest 19（六态 + 12 反例） | 19/19 ✓ |
| D SSE | review/completion flow 含 SSE 深比较 | 通过 ✓ |
| E VersionSummary | ItineraryEditFlowIntegrationTest 24（LEFT JOIN/null/无 reportJson） | 24/24 ✓ |
| F 事务 | CompletionFlow 42（含 task-event failure 回滚）、ReviewFlow 16（含 review task-event failure 回滚） | 58/58 ✓ |

## 9. 独立门禁结果

Java 定向（4 类）：PlanningReviewRequiredEventParserTest 19、PlanningReviewServiceTest 12、PlanningReviewFlowIntegrationTest 16、PlanningTaskReadModelIntegrationTest 19 = **66 passed, 0 failures/errors**。

Java 回归（7 类）：FeasibilityReportContractTest 48、FeasibilityEntityReferenceCodecTest 10、FeasibilityEntityRefMapperTest 6、FeasibilityEntityRefMapperV4Test 10、PlanningCompletedEventParserTest 54、PlanningCompletionFlowIntegrationTest 42、ItineraryEditFlowIntegrationTest 24 = **194 passed, 0 failures/errors**。

Java 全量 `mvn --batch-mode -pl apps/travel-server verify`：**BUILD SUCCESS**；tests run: **394**, failures: 0, errors: 0, skipped: 0；JaCoCo `All coverage checks have been met.`；Flyway 干净库迁移至 v33。

仓库：`python scripts/check_markdown_links.py`：**85 files valid**；`git diff --check` 干净；`git diff --cached --name-only` 空。

Python：B6J.2.2 增量经 `git diff --name-only` 核验无 Python/共享 fixture 变化（Python/fixture 改动均为 B6J.2/B6J.2.1 已验收遗留），按指令不强制重跑；共享 fixtures 未被 B6J.2.2 触碰。

## 10. 发现项汇总

| # | 严重度 | 位置 | 描述 | 影响 |
| --- | --- | --- | --- | --- |
| M1 | 极小 | `PlanningTaskReadModelIntegrationTest.waitingUserExposesReportAndCandidateWithoutEvaluation` | 未显式断言 API candidate 与 DB candidate `isEqualTo`（仅断言 title/days 存在）；逻辑可推得（read model 透传 raw 不改写） | 测试断言可补强，非功能缺陷 |
| M2 | 极小 | `PlanningTaskOutcomeReadModel.isValidCandidate` 注释（141-147 行） | 注释仍写"impossible for typed-DTO storage"（B6J.2.2 已改 raw 存储） | 过时注释，非功能缺陷 |

## 11. Verdict

**PASS**

S1-A 至 S1-E 全部真实成立（独立 probe 实证快照安全性与 wire 一致性、集成测试覆盖存储无损/篡改 fail closed/service bypass 门禁/SSE 深比较）；S2 明确认错；A/C/D/E/F 回归全绿；全部门禁通过（Java 394、JaCoCo、Flyway V33、markdown links 85、git 干净）。M1/M2 为极小测试/注释瑕疵，不影响语义与安全，不构成 NEEDS_SMALL_FIX。

**允许 Git 提交收口**：B6J.2 可以进入 Git 提交收口。

### 允许提交的精确文件清单（B6J.2.2 增量）

生产：
1. `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/infrastructure/mq/PlanningReviewRequiredEvent.java`
2. `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/infrastructure/mq/PlanningReviewRequiredEventParser.java`
3. `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningReviewService.java`
4. `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskOutcomeReadModel.java`

测试：
5. `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/infrastructure/mq/PlanningReviewRequiredEventParserTest.java`
6. `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningReviewServiceTest.java`
7. `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningReviewFlowIntegrationTest.java`
8. `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningTaskReadModelIntegrationTest.java`

文档：
9. `docs/execution/B6J2/execution-report.md`（含 B6J.2/B6J.2.1/B6J.2.2 全部章节）
10. `docs/product/系统完善长期执行与验收总控计划.md`（B6J.2 状态「修复完成，待重新验收（未提交）」）

说明：B6J.2/B6J.2.1 的实现与测试文件（Python typed-refs/validator v4、Java feasibility/planning/itinerary、契约 fixtures、其余测试）随 B6J 批次整体收口，由 Git 收口任务按已验收范围显式暂存；acceptance-report.md 与 plan.md 为批次记录文件。

## 12. B6W/B6F 状态

- **B6W 未开始**（NOT_STARTED）。
- **B6F 未开始**（NOT_STARTED）；B6F 需 B6J.2、B6W 均独立验收 PASS 并提交后才开始。
- **不得直接进入 B6W**：必须先执行 B6J.2 Git 提交收口。
- 本报告为 B6J.2.2 最终重新验收（PASS），不构成 B6F；未 stage、未 commit、未 push，未修改任何业务代码/测试/文档（probe 均在 `C:\Windows\Temp\opencode` 工作区外，已清理）。
