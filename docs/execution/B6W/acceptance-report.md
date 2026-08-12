# B6W 验收报告（Acceptance Report）

- 批次：B6W（完整 Feasibility 前端）
- 验收 Agent：独立验收（只读复现，未修改任何业务文件）
- 日期：2026-08-12
- Verdict：**NEEDS_CORRECTION**

## 1. 前置基线

| 项 | 结果 |
| --- | --- |
| branch | `codex/feasibility-foundation` ✓ |
| HEAD | `e72b8f662cc466010011d0929131c53910242223` ✓ |
| staged | 空 ✓ |
| B6W 已提交 | 否（全部未 stage、未 commit）✓ |
| B6F | NOT_STARTED（总控计划 778 行与 plan.md 一致）✓ |
| 保护目录 | `.omo/`、`.serena/`、`docs/audits/` 均 untracked ✓ |
| `git diff --check` | 通过（仅 TripWorkspace.vue CRLF 提示）✓ |

## 2. 精确文件范围

tracked 修改 10 个（与预期逐一吻合）：`ItineraryVersionPanel.vue`、`PlanEvaluationPanel.vue`、`PlanningProgress.vue`、`TripDetail.vue`、`lib/api.ts`、`pages/TripWorkspace.vue`、`App.test.ts`、`ItineraryVersionPanel.test.ts`、`PlanEvaluationPanel.test.ts`、`api.test.ts`。

新增 9 个（与预期逐一吻合）：`e2e/feasibility-outcomes.spec.ts`、`FeasibilityReportPanel.vue`、`PlanningReviewPanel.vue`、`lib/feasibility.ts`、`FeasibilityReportPanel.test.ts`、`PlanningReviewPanel.test.ts`、`feasibility.test.ts`、`docs/execution/B6W/execution-report.md`、`docs/execution/B6W/plan.md`。

**无** Python/Java/contracts/Flyway/Rabbit/pnpm-lock 改动；无第 20 个未知业务文件。

## 3. 独立门禁结果（验收复跑）

| 门禁 | 结果 |
| --- | --- |
| `pnpm test` | 33 文件 **235 passed** ✓ |
| `pnpm typecheck` | 通过 ✓ |
| `pnpm build` | 通过 ✓ |
| `pnpm test:coverage`（默认配置） | 通过——但 include 仅 `TripMap.vue`/`amap.ts`/`map.ts`（vite.config.ts:43-47），**本批文件未被统计**（见 H-3） |
| 本批文件独立 coverage（CLI 显式 include） | **branches 69.38% < 80% 门槛，ERROR**（见 H-3） |
| `pnpm test:e2e`（CI=1，bundled Chromium） | **9 passed** ✓（首轮非 CI 配置因本机无 Chrome 失败，记录见下） |
| `scripts/check_markdown_links.py`（仓库自带） | 87 文件链接有效 ✓ |
| `git diff --check` / staged 空 | ✓ |
| `as any`/`@ts-ignore`/`@ts-expect-error` 扫描（本批文件） | 0 ✓ |
| score/feasible 推导扫描（`overallScore`/`evaluation.feasible` 出现在可行性链路） | 0 ✓ |

环境说明：Playwright 首轮按非 CI 配置 `channel: 'chrome'` 启动失败（本机无 Chrome）；以 `CI=1` 使用 Playwright bundled Chromium 复跑全部通过。与执行报告记录一致。

## 4. 各组结论（A-I）

| 组 | 结论 |
| --- | --- |
| A 运行时读取与 fail-closed | **FAIL**（A1/A2/A3 部分/A4 空值/A5 transit 多个 fail-open 点） |
| B 状态组合门禁 | **FAIL**（WAITING_USER+VERIFIED、SUCCEEDED+NEEDS_REPAIR 均 fail open，probe 实证） |
| C 状态机与竞态 | **部分 FAIL**（C1/C2 新任务开始与取消/失败路径不清旧 report；C3-C11 成立） |
| D WAITING_USER 页面恢复 | **FAIL**（E2E 基于虚假 DB 关系；执行报告声明不实） |
| E FeasibilityReportPanel | **部分 FAIL**（eligible=false 无明确表达、repair 实体仅数量、左边框可被子 badge 覆盖） |
| F PlanningReviewPanel | **FAIL**（缺结束时间窗口、缺 transit 摘要；其余必做项成立） |
| G VersionSummary/PlanEvaluation | **PASS** |
| H 测试真实性 | **FAIL**（组合反例/清理/枚举反例缺失；E2E 场景不足且含虚假用例；本批 coverage 不达标） |
| I 文档与报告真实性 | **FAIL**（文档收口缺失；多处声明与事实不符） |

## 5. 发现清单

### CRITICAL

**B-1. WAITING_USER + VERIFIED report 被显示为"已验证"（fail open）**
- 位置：`apps/web/src/pages/TripWorkspace.vue:917`（REVIEW_REQUIRED 分支直接写入 payload report，不校验状态组合）；`apps/web/src/components/TripDetail.vue:824-839`（展示层无防护）
- 复现：临时 probe `tests/acceptance-probe-combos.test.ts`（render TripDetail，`planningState='waiting_user'` + `status:'VERIFIED'` report + candidate）→ 页面渲染"已验证"（probe 2/2 passed 后已删除）
- 实际：非法组合正常展示权威绿色"已验证"
- 期望：fail closed——显示 malformed/"验证结果暂时无法读取"，不得渲染 VERIFIED
- 后端对照：Java `PlanningTaskOutcomeReadModel.readReview`（102-139 行）对 VERIFIED review 抛 invalid，但 SSE `TaskEventView.payload`（PlanningTaskEventHub.java:142-149）是原始事件 JSON、**不经过** read model 校验，前端必须自行 fail closed
- 修复方向：TripWorkspace/TripDetail 增加组合校验（REVIEW_REQUIRED 要求 status∈{NEEDS_REPAIR,UNVERIFIED} 且 candidate 存在；否则置 malformed），并补组合反例测试

**B-2. SUCCEEDED/completed + NEEDS_REPAIR report 被显示为正式成功（fail open）**
- 位置：`apps/web/src/pages/TripWorkspace.vue:897-912`（COMPLETED 分支直接读 `payload.feasibilityReport`，不校验 status==='VERIFIED'）
- 复现：同上 probe（`planningState='succeeded'` + `status:'NEEDS_REPAIR'`）→ 渲染"待修复"与成功状态并存
- 期望：completed 事件若 report 非 VERIFIED 应 fail closed（置 malformed），不得把 NEEDS_REPAIR 当正式成功展示
- 修复方向：同 B-1

**D-1. "页面加载可恢复 WAITING_USER"为不实声明，E2E 恢复用例基于虚假 DB 关系**
- 位置：`docs/execution/B6W/execution-report.md`（W4 GREEN："页面加载可恢复 SUCCEEDED/WAITING_USER 状态"）；`apps/web/e2e/feasibility-outcomes.spec.ts:318`（`restores a review-required workspace when reopening a waiting task`）
- 复现/事实：
  1. 后端事实：WAITING_USER review-required 不创建 itinerary version、不更新 current version（B6J.2 语义；`PlanningTaskOutcomeReadModel` 注释 25-32 行）；`VersionSummary.planningTaskId`（ItineraryVersionService.java:457-463）指向创建该版本的 SUCCEEDED task
  2. `PlanningTaskController.java` 仅 GET `/api/planning-tasks/{taskId}`、POST create/replan、DELETE cancel——**无 trip→latest task discovery 端点**
  3. 浏览器刷新后 TripWorkspace 只从 `current VersionSummary.planningTaskId`（TripWorkspace.vue:334-339）发现 task → 只能发现旧 SUCCEEDED task，**无法发现 WAITING_USER task**
  4. E2E 的 `versionSummary()` fixture 把 WAITING_USER `taskId` 人工填入 `current: true` 版本（spec 中 `planningTaskId: taskId`）——真实 DB 中不可能存在该关系
- 期望：撤销"页面加载可恢复 WAITING_USER"声明；恢复用例不得用不符合真实 DB 关系的 fixture 冒充；登记"刷新后无法自动发现未知 WAITING_USER task"为 B6F 后端发现性边界
- 修复方向：修改执行报告与 E2E（恢复用例改为 SUCCEEDED task 恢复，或删除并登记边界）

### HIGH

**A-1. 必填数组字段缺失被静默转换为空数组（fail open）**
- 位置：`apps/web/src/lib/feasibility.ts:156-160`（`readStringArray` 对 undefined/null 返回 `[]`）、`162-166`（`readEvidenceReferences` 同）、`209-213`（`readRepairAttempts` 同）
- 影响：requiredRuleIds、missingRequiredRuleIds、evidenceRefs、repairAttempts 缺失时被当作正常空集合；Java `FeasibilityReport`（record，全部字段 required）wire contract 这些字段为必填
- 复现：`readFeasibilityReport` 删除 requiredRuleIds 后仍返回 ok（现有测试未覆盖）
- 期望：缺失拒绝（与 readRuleResults 已修的行为一致）
- 修复方向：`readStringArray`/`readEvidenceReferences`/`readRepairAttempts` 缺失返回 null，补反例测试

**A-2. schemaVersion / validatorVersion 门禁缺失**
- 位置：`feasibility.ts:272-278`——schemaVersion 仅查 `typeof number`，非整数（1.5）、负数、未知版本（99）均通过；validatorVersion 仅查 `typeof string`，未知版本不标记 malformed
- 期望：schemaVersion 必须正整数且为已知版本（当前 v1）；validatorVersion 未知应拒绝或标记 malformed；未知 schema 不得显示 VERIFIED
- 修复方向：reader 增加版本检查

**A-3. 数值边界不完整**
- 位置：`feasibility.ts` `readSummary`（238-254 行）`Number.isSafeInteger` 允许负数（-1 通过）；`readRepairAttempts`（215 行）attemptIndex=0 通过（非正）
- 期望：summary 计数非负；attemptIndex 为正整数

**A-4. 空 typed ref 伪装已知实体**
- 位置：`feasibility.ts:130-138`——`parseTypedEntityReference('poi:')` 返回 `{ kind: 'poi', value: '' }`；空值被标记为已知实体
- 期望：空 value 归为 unknown，不得伪装已知实体
- 修复方向：value 为空时返回 unknown

**A-5. candidate transit 损坏字段降级为默认值**
- 位置：`feasibility.ts:374-399`——`readCandidateTransitLegs` 对缺失 mode/provider 返回 `''`、非数组 polyline 返回 `[]`，不拒绝
- 期望：损坏 candidate 显示"候选行程暂时无法读取"，不得部分伪造

**F-1. 候选活动缺少结束时间窗口**
- 位置：`apps/web/src/components/PlanningReviewPanel.vue:102`——仅 `formatTime(activity.startTime)`，无 endTime
- 必做要求（验收 prompt）："开始和结束时间窗口"；总控计划 B6W 必做范围
- 修复方向：显示 `startTime - endTime` 时间窗口并补测试

**F-2. 候选与对照均无 transit 摘要**
- 位置：`PlanningReviewPanel.vue` 候选模板（无 transitLegs 渲染）；对照区（117-131 行）仅活动列表，无交通变化对比
- 修复方向：候选行与对照区增加 transit 摘要（mode/起终点/时长）

**E-2. hardConstraintEligible=false 无明确表达**
- 位置：`apps/web/src/components/FeasibilityReportPanel.vue:142`——仅 `v-if="evidence.hardConstraintEligible"` 显示"硬约束相关"，false 时静默消失
- 期望：false 明确表达"不具备硬约束资格"
- 修复方向：补 else 分支文案

**E-4. 左边框颜色由任意子 badge 决定，可被内部规则 badge 覆盖**
- 位置：`FeasibilityReportPanel.vue:182-190`——`.feasibility-panel:has(.badge-success/.badge-danger/.badge-warning)` 命中面板内**任意** badge
- 复现（代码推演）：UNVERIFIED report 含 FAIL 规则 → 存在 `.badge-danger`（规则 badge）→ 左边框变红而非黄色；NEEDS_REPAIR 且无 FAIL（仅 UNKNOWN）→ 黄框而非红框
- 期望：左边框稳定表示主状态（`statusVariant`）
- 修复方向：边框类绑定主状态 computed，移除 `:has` 子元素选择器；补混合 outcome 快照测试

**E-3. repair attempt 的 affectedEntityRefs 只显示数量**
- 位置：`FeasibilityReportPanel.vue:163`——"实体：N 项"，无节点
- 修复方向：显示节点短标签（复用 `entityShortLabel`）

**H-3. 本批文件 coverage 未达标且默认门禁空跑**
- 位置：`apps/web/vite.config.ts:41-47`——coverage.include 仅旧文件；执行报告最终门禁"test:coverage 无门槛失败"未披露本批文件未被统计
- 独立统计（CLI 显式 include 三文件，thresholds 80%）：全局 branches **69.38%**（feasibility.ts Stmts 87.3/Branches 66.43/Funcs 93.33/Lines 87.3；FeasibilityReportPanel 100/74.28/100/100；PlanningReviewPanel 100/83.33/100/100）→ **ERROR: Coverage for branches (69.38%) does not meet global threshold (80%)**
- 修复方向：coverage.include 纳入本批文件并补齐分支（A 组反例、E/F 组缺口），或执行报告如实披露

**C-1/C-2. 新任务开始、手动取消、连接失败均不清除旧 report/candidate**
- 位置：`TripWorkspace.vue:860-866`（runPlanningTask 仅 `stopPlanningStream(false)`，不重置 report/candidate/feasibilityLoadState）；`994-996`（handleCancelPlanning 同）；`956-959`（连接中断 failed 同）
- 影响：queued/cancelled/failed 状态下 TripDetail 的 `v-else-if="... feasibilityLoadState === 'loaded'"`（TripDetail.vue:834）继续渲染旧 report 面板
- 期望：新任务开始、cancelled、连接失败均清除旧 report/candidate
- 修复方向：上述路径重置三个状态，补测试

**H-1. 测试缺口（unit）**
- 无状态组合反例（B-1/B-2 场景）；无 failed/cancelled 清理测试（C-2）；无 required 数组缺失反例（A-1）；无 schemaVersion 非整数/负数/未知（A-2）；无 summary 负数/attemptIndex 0（A-3）；无空 typed ref（A-4）；无 transit 缺 mode（A-5）；无 repair 非空 affectedEntityRefs；无 eligible=false 明确文案；无时间窗/transit 摘要（F-1/F-2）

**H-2. E2E 场景不足且含虚假用例**
- 总控计划必做："Playwright 覆盖 VERIFIED 成功、UNVERIFIED review、NEEDS_REPAIR review 和 SSE replay"——实际仅 VERIFIED（completed 用例）与 NEEDS_REPAIR review（REVIEW 用例）；**UNVERIFIED review 与 SSE replay/Last-Event-ID 无 E2E**；第三用例（恢复）为虚假 fixture（D-1）
- 修复方向：补 UNVERIFIED review 与 replay E2E；删除/改造虚假恢复用例

**I-1. 文档收口缺失**
- 总控计划 `系统完善长期执行与验收总控计划.md:777` 仍为 `B6W | NOT_STARTED`；plan.md 文件范围列出的 `docs/architecture/规划工作流.md`、`事件契约.md`、`行程真实性与旅行骨架.md`、`docs/product/项目路线图.md`、总控计划 **全部零 diff**
- 执行报告未声称"文档收口完成"，但批次以 READY_FOR_REVIEW 结束而未登记该缺失
- 修复方向：更新总控计划 B6W 状态与上述文档，或明确登记为未完成项

### MEDIUM

**I-2. Markdown 链接验证方式声明不实**
- 执行报告：`markdown-link-check 非仓库依赖（未安装）`——未运行仓库自带 `scripts/check_markdown_links.py`（独立运行：87 文件链接有效，结果巧合正确）
- 修复方向：报告改用仓库脚本结果

## 6. 执行报告真实性核对

| 声明 | 核对结果 |
| --- | --- |
| "页面加载可恢复 SUCCEEDED/WAITING_USER 状态" | **不实**（SUCCEEDED 可恢复；WAITING_USER 无 discovery 路径，见 D-1） |
| "W1-W7 全部完成 / READY_FOR_REVIEW" | **不准确**（B 组 fail open、F 组必做字段缺失、coverage 不达标、E2E 场景不足） |
| W6"首跑即绿" | 如实标注 characterization/契约锁定 ✓ |
| Playwright"REVIEW/COMPLETED/恢复三旅程全绿" | **不准确**（恢复旅程基于虚假 fixture；总控计划 4 场景仅覆盖 2 个） |
| "test:coverage 无门槛失败" | 真实但**误导**（本批文件未在 include 内，独立统计 branches 69.38% 不达标） |
| Markdown links 验证 | 验证方式声明不实（未运行仓库脚本，见 I-2） |
| B6F NOT_STARTED | 一致 ✓ |

## 7. Probe 说明（临时验收测试）

- 输入：`apps/web/tests/acceptance-probe-combos.test.ts`（2 用例：waiting_user+VERIFIED、succeeded+NEEDS_REPAIR，render TripDetail 展示层）
- 实际输出：2/2 passed——证明两个非法组合分别渲染"已验证"/"待修复"（fail open 实证）
- 清理证明：probe 已删除；`git status --short --untracked-files=all` 无 probe 残留；staged 为空
- 未修改任何业务文件、未覆盖既有文件

## 8. Verdict

**NEEDS_CORRECTION**

触发项（验收判定规则）：状态组合 fail open（B-1/B-2，probe 实证）；review 恢复测试建立在不真实后端关系上（D-1）；强制场景缺失但报告声称完成（F-1/F-2 时间窗与 transit、H-2 E2E 场景、H-3 coverage 空跑）；多项文档/报告声明与事实不符（I-1/I-2）。

## 9. 是否允许 Git 提交

**否**。本次验收未 stage/commit/push/切换分支；建议按发现清单修正后重新验收。

## 10. B6F 状态

B6F 保持 **NOT_STARTED**（总控计划 778 行与 plan.md 一致，本次未改动任何后端/契约/Python 文件）。

# B6W 集中修复最终复验

- 复验 Agent：最终独立复验（只读复现，未修改任何业务文件）
- 日期：2026-08-12
- 结论：**PASS（授权 B6W Git 提交收口）**

## 1. 前置基线

- branch=`codex/feasibility-foundation` ✓；HEAD=`e72b8f662cc466010011d0929131c53910242223` ✓；staged 空 ✓；B6W 未提交 ✓；B6F=NOT_STARTED ✓；保护目录 untracked ✓；`git diff --check` 通过（仅 CRLF 提示）✓

## 2. 精确范围

33 个业务文件与预期完全一致（23 M + 10 A + 0 D）：Java tracked 5、Web tracked 13、Web 新增 7、文档 tracked 5、执行文档新增 3。无 Python/contracts/Flyway/Rabbit/pnpm-lock 改动，无第 34 个业务文件。release-smoke/v2 改动仅为 completed/task fixture 适配真实 v9 契约（补 VERIFIED report + evaluation，无断言删除、无 skip/only）；PlanningReviewServiceTest 仅补 mapper 接口新方法（UnsupportedOperationException，不改 review 安全语义）。

## 3. 原八项关闭矩阵

| 原发现 | 判定 | 证据 |
| --- | --- | --- |
| A 非法状态组合 fail open | PASS | 统一 parser 真值表 11 行组合全部正确（SSE/Task API 共用 `readTerminalOutcome`）；独立 probe 4/4（WAITING_USER+VERIFIED、SUCCEEDED+NEEDS_REPAIR 双入口均 malformed）；集成测试验证 App 全流程渲染"规划结果无法安全读取，请重新规划"且无任何权威状态词、不刷新正式行程、清空旧 outcome |
| B WAITING_USER 无真实发现路径 | PASS | latest endpoint（Mapper/Service/Controller）+ 8 个集成测试（owner/order/tie-break/404/review/succeeded/failed/只读） |
| C Candidate 缺时间窗/transit | PASS | PlanningReviewPanel 显示开始–结束时间窗、候选与正式 transit 摘要（起点/终点/mode/时长/距离/估算标记）；组件测试 + E2E |
| D Reader 多处 fail open | PASS | schemaVersion===1、validatorVersion 白名单与 Java 一致、必填数组缺失拒绝（合法空数组允许）、summary 非负、attemptIndex>=1、typed ref 空值/非规范 UUID 归 unknown、candidate transit 必填与 index 越界拒绝、`readPlanEvaluation` 安全 reader；54 个新反例测试 |
| E Evidence/Repair/主边框 | PASS | eligible 双向表达、repair affectedEntityRefs 节点短标签、根组件 status class 决定边框（删 `:has(.badge-*)`）、NEEDS_REPAIR+混合 badge / UNVERIFIED+FAIL 主边框稳定（组件测试）；STALE/CONFLICTING/UNKNOWN 非绿色 |
| F 新任务/取消/失败清理 | PASS | `clearPlanningOutcome` 接入新任务启动、手动取消、terminal failed/cancelled、流中断重试耗尽、create/start catch；3 个集成测试 |
| G Coverage 空跑 + E2E 不足 | PASS | vite.config include 纳入本批 3 文件；官方 test:coverage 全局 95.97/81.64/95.45/95.97 ≥80；E2E 7 场景 |
| H 文档未收口 | PASS | 5 份文档真实 diff（24 insertions）；总控计划 B6W 状态更新；execution-report 追加集中修复章节并承认全部原缺陷 |

## 4. latest endpoint 安全审计

- SQL：`JOIN business.trip ON trip.id = planning_task.trip_id WHERE planning_task.trip_id = ? AND trip.owner_id = ?`——owner scoped；`ORDER BY created_at DESC, id DESC LIMIT 1`——稳定 tie-break ✓
- 404 语义：无任务、trip 不存在、非 owner 统一 `PLANNING_TASK_NOT_FOUND`（不泄漏 trip 存在性）✓
- Service `@Transactional(readOnly = true)`，`toResponse` → `terminalMetadata` → `PlanningTaskOutcomeReadModel`（fail-closed 复用）✓
- 无 DB 写入、无 task event、无 Flyway、无新增 migration ✓
- Integration tests 走 MockMvc + 真实 Postgres SQL（非 mock），验证真实代码路径 ✓

## 5. 状态组合真值表

`readTerminalOutcome` 独立核验：SUCCEEDED 仅接受 VERIFIED + 合法 evaluation + candidate 缺失；WAITING_USER 仅接受 NEEDS_REPAIR/UNVERIFIED + 合法 candidate + evaluation 缺失；QUEUED/RUNNING/FAILED/CANCELLED 携带任何 outcome 字段即 malformed；SSE 的 eventType 与 payload.status 必须一致；未知 status/eventType malformed。11 行组合全部符合期望表。malformed 行为：terminal、planningState=failed、显示稳定安全错误、清空 report/candidate/evaluation、不刷新正式行程（无 itineraryReload 路径）、不显示任何权威状态标签（App.test.ts fails-closed 集成测试 + E2E 非法组合用例实证）。

## 6. WAITING_USER 真实关系证据

E2E `recovers a review-required task through the latest endpoint after a refresh`：current VersionSummary.planningTaskId=旧 SUCCEEDED task（oldTaskId）；latest endpoint 返回新 WAITING_USER task（taskId）；WAITING_USER task 无 version；页面通过 latest 发现 review；正式行程标题与旧版本 VERIFIED 徽章保持；candidate 仅在 review 面板。`hydrateLatestPlanningTask` 代码核验：404/error 静默回退（current version 旧 task 已由 loadEvaluationForCurrentVersion 处理）、completed 仅当 latest.taskId===currentVersion.planningTaskId 才应用（防非当前成功 task 套到当前版本）、queued 恢复订阅 eventStreamUrl、malformed 不破坏正式行程。

## 7. UI 完整性

FeasibilityReportPanel：eligible=true"具备硬约束资格"/false"不具备硬约束资格"（组件测试双向断言）；repair affectedEntityRefs 显示节点短标签（测试断言具体 UUID 文本且无"实体：N 项"）；主边框由 statusClass 根 class 决定（status-verified/needs-repair/unverified），混合 badge 场景测试证明内部 PASS/UNKNOWN/FAIL 不改边框；null/malformed 中性；STALE/CONFLICTING/UNKNOWN 非绿色（既有测试）。PlanningReviewPanel：时间窗（`17:00–18:00` 断言）、候选 transit 摘要（`Activity 1 → Activity 2 · 步行（估算） · 5 分钟 · 300 米`）、正式 transit 对照（`Formal A → Formal B · 公共交通 · 20 分钟 · 2.4 公里`）、index 越界由 reader 拒绝（feasibility.test）、candidate 不进入正式 itinerary/map/edit（只读 props，测试断言对象不变）、无接受/强制保存/跳过按钮（测试 + E2E）。

## 8. E2E 七场景

独立复跑 13 passed（feasibility 7 + release-smoke 4 + v2 2）：VERIFIED completed（正式行程/权威 VERIFIED/evaluation 分层）、NEEDS_REPAIR review（fail rule/STALE evidence/repair history/候选隔离/无接受按钮）、UNVERIFIED review（未验证/证据未知/无已验证字样）、SSE reconnect（两次 HTTP stream 请求、第二次 Last-Event-ID='2'、terminal 只应用一次、无连接中断）、historical feasibility=null（无历史验证、无未验证）、真实 latest 恢复（不同 taskId：current version 用 oldTaskId、latest 用 taskId）、非法组合 fail closed。断言均为用户可见行为 + 关键请求关系，非仅 mock 调用。

## 9. Coverage

官方 `pnpm test:coverage` 独立复跑：303 passed；全局 statements 95.97 / branches 81.64 / functions 95.45 / lines 95.97，thresholds 全绿（未降低）。include 已纳入 `src/lib/feasibility.ts`、`FeasibilityReportPanel.vue`、`PlanningReviewPanel.vue`。逐文件：feasibility.ts 95.14/82.01/100/95.14；FeasibilityReportPanel 100/79.48/100/100；PlanningReviewPanel 98.74/68.29/100/98.74。

## 10. Java/Web/文档门禁（独立复跑）

- Java：`mvn --batch-mode -pl apps/travel-server verify` **BUILD SUCCESS**，**402 tests**，0 failures/errors，JaCoCo check 通过，Flyway 到 V33（"Successfully applied ... now at version v33"），无新增 migration
- Web：`pnpm test` **303 passed**（33 文件）；`pnpm typecheck` 通过；`pnpm build` 通过；`pnpm test:coverage` 通过；`CI=1 pnpm test:e2e` **13 passed**
- 仓库级：`python scripts/check_markdown_links.py` **88 files valid**；`git diff --check` 通过；staged 空；无 `as any`/`@ts-ignore`/`@ts-expect-error`；无 `.only`/`.skip`；无 score/evaluation.feasible 推导 feasibility（仅 `readPlanEvaluation` 校验类型与范围、PlanEvaluationPanel 显示分数）；contracts/Python/Flyway/Rabbit/pnpm-lock 零改动
- 文档：5 份架构/产品文档真实 diff；总控计划 B6W="集中修复完成，待最终独立复验（未提交）"、B6F=NOT_STARTED；execution-report 集中修复章节明确承认并纠正原五项声明（组合门禁缺失、恢复 fixture 不真实、coverage 未统计、文档未收口、READY 声明不成立），架构导读增量含调用链/数据所有权/阅读顺序/调试命令/断点/可重复实验

## 11. 高置信度代码审查发现

无（confidence>=80 的功能缺陷为零）。核验项：owner isolation（SQL JOIN）、latest 排序稳定（created_at DESC, id DESC + tie-break 测试）、hydration 竞态（isCurrentEvaluationOwner 三重守卫：detailSequence/sessionGeneration/route）、current/latest 混淆防护（completed 仅匹配 current task 才应用）、SSE retry/terminal（terminal=true 后循环退出、`!terminal` 才显示连接中断、最多 3 次重连）、malformed 不覆盖正式 itinerary（仅清 outcome 状态 + planningState=failed，无 reload 路径）、parser 不补造必填数据（mode/provider/estimated/polyline 缺失拒绝，可空字段保持 null）、candidate 不进入编辑/map（仅传 PlanningReviewPanel）、latest 端点单查询无 N+1 无写操作、测试验证真实代码（MockMvc+真实 SQL / 浏览器+route mock 用户可见断言）。

## 12. 非阻断观察

1. FeasibilityReportPanel branches 79.48、PlanningReviewPanel branches 68.29 单文件低于 80（项目配置为全局门槛，全局 81.64 达标）；未覆盖分支为次级展示格式（repair resultingStatus VERIFIED 标签、距离公里格式化等），必做行为均有直接测试，不要求新修复。
2. `readVersionFeasibilityMetadata` 对 schemaVersion 仅查 typeof number（未强制 ===1）；该路径为版本徽章展示，status 枚举已校验且数据由后端生成，风险低。
3. 复验 probe 的 UI 全流程版本因 probe 自身 mock 渲染问题无法运行，改用 parser 级独立复现（4/4 passed）+ 既有集成测试（App.test.ts fails-closed 用例，通过）作为流程渲染证据；probe 已删除、无残留。

## 13. Verdict

**PASS**。首次八类问题全部关闭；latest endpoint 安全（owner scoped/排序稳定/404 不泄漏/只读/复用 read model）；非法状态组合 fail closed（parser 单点 + 集成/E2E 实证）；真实 WAITING_USER 刷新恢复成立（真实 DB 关系 fixture）；UI 必做内容完整（时间窗/transit/eligible/repair 节点/主边框）；官方 coverage 真实通过（全局门槛）；E2E 七类真实；文档与报告一致（承认+纠正）；Java 402/Web 303/E2E 13 全门禁通过；无高置信度功能缺陷。

## 14. Git 提交授权

**授权 B6W Git 提交收口**。提交范围：本次验收范围核对的 33 个业务文件（Java 5 + Web tracked 13 + Web 新增 7 + 文档 5 + 执行文档 3）。B6F **不得开始**，必须先完成 B6W 提交。单文件 branch coverage 数字（观察 1）不作为提交阻断。

## 15. 复验结束状态

- 临时 probe（`tests/acceptance-final-probe.test.ts`）已删除，`git status` 无残留
- 唯一由复验 Agent 新增的永久内容是本 acceptance-report 追加段落
- staged 空；未 commit；未 push；未切换/创建分支；B6F 保持 NOT_STARTED
