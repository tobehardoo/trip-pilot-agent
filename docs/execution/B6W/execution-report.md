# B6W 执行报告

- 批次：B6W（完整 Feasibility 前端）
- 分支：`codex/feasibility-foundation`
- 已提交基线：`e72b8f662cc466010011d0929131c53910242223`（B6J.2 已验收 PASS 并提交）
- 计划：[plan.md](plan.md)
- 状态：COMMITTED（本提交；最终复验 PASS）
- 最后成功命令：见各组记录

## W0：安全审计

- branch=`codex/feasibility-foundation` ✓
- HEAD=`e72b8f662cc466010011d0929131c53910242223` ✓
- staged 空 ✓；tracked 工作树干净 ✓
- 仅 `.omo/`、`.serena/`、`docs/audits/` 三个保护目录 untracked ✓
- B6J.2 已提交（git log 首条 e72b8f6）✓；B6W/B6F NOT_STARTED ✓

## W1：TypeScript 契约与运行时读取

### RED

- `apps/web/tests/feasibility.test.ts`（新增 25 用例）：`readFeasibilityReport`（VERIFIED/NEEDS_REPAIR/UNVERIFIED 读取、未知 status/outcome/evidence state 拒绝、缺 summary/ruleResults 拒绝、非数组 affectedDates/affectedEntityRefs/evidenceRefs 拒绝、非法 repairAttempts 拒绝、malformed 不抛错）、`parseTypedEntityReference`（activity/transit/poi 含冒号/text/未知 kind/裸串）、`readCandidateItinerary`（合法/缺 days/缺 time 字段/malformed）、VersionFeasibilityMetadata null 语义
- 真实失败：feasibility.ts 模块不存在（transform 失败）；实现后 5 失败——测试访问 `result.report`/`result.itinerary` 应为 `result.value`（测试 bug），`readRuleResults` 对 undefined 返回空数组（应为拒绝）
- 修正：测试字段访问改 `result.value`；`readRuleResults` 缺失拒绝

### GREEN

- `apps/web/src/lib/feasibility.ts`（新增）：FeasibilityStatus/RuleOutcome/EvidenceState/EvidenceReference/FeasibilitySummary/FeasibilityRuleResult/RepairAttempt/FeasibilityReport/VersionFeasibilityMetadata/CandidateItinerary/CandidateDay/CandidateActivity/CandidateTransitLeg/TypedEntityReference 类型；`parseTypedEntityReference`、`readFeasibilityReport`、`readCandidateItinerary`、`readVersionFeasibilityMetadata`、`formatValidatedAt`、`ruleIdLabel`（稳定中文标签）；`ReadResult<T>` 可区分 malformed
- `apps/web/src/lib/api.ts`：PlanningTask.status 改 `PlanningTaskStatus` union（含 WAITING_USER），加 `feasibilityReport?`/`candidateItinerary?`（unknown，运行时读取）；ItineraryVersionSummary 加 `feasibility: unknown`；PlanningTaskEvent.payload 加 feasibilityReport/candidateItinerary/evaluation，移除 envelope 顶层 `evaluation`（evaluation 在 payload 内）
- 定向：feasibility.test.ts **25 passed**；typecheck 通过；全量测试 **198 passed**（无回归）


## W2：FeasibilityReportPanel

### RED

- `apps/web/tests/FeasibilityReportPanel.test.ts`（新增 15 用例）：三态标签、summary 计数、四规则结果、四 evidence state（STALE/CONFLICTING/UNKNOWN 不得显示"证据已验证"）、hardConstraintEligible、affectedDates/entities 空与非空、repairAttempts 空与非空、missing required、null report（显示"没有可用的硬可行性报告"非 UNVERIFIED）、malformed（"验证结果暂时无法读取"）、无 score 推导文案
- 真实失败：组件不存在（transform 失败）；实现后 4 失败——getByText 多匹配歧义（"待修复"/"1"/"失败"/"不适用"）、"修复尝试"文案应为"修复历史"、`/评分/` 断言过严（说明文字含"评分"）

### GREEN

- `apps/web/src/components/FeasibilityReportPanel.vue`（新增）：三态主标签（Badge success/danger/warning + 图标）、"硬可行性验证"标题与"不代表体验评分"说明、summary 六格、规则明细（ruleId 稳定中文标签/outcome badge/reasonCode/message/repairable/affectedDates/affectedEntityRefs 短标签）、evidenceRefs（state badge 视觉区分，STALE/CONFLICTING/UNKNOWN 用 warning/danger/secondary 非绿色）、repairAttempts（"修复历史"）、validatorVersion/validatedAt 元数据、空集合明确文案、malformed/null 稳定降级；沿用现有 Card/Badge/TripPilot 视觉
- 定向：FeasibilityReportPanel.test.ts **15 passed**


## W3：PlanningReviewPanel

### RED

- `apps/web/tests/PlanningReviewPanel.test.ts`（新增 10 用例）："规划需要确认"标题、候选非正式声明、NEEDS_REPAIR authoritative report 嵌入、候选 title/cost/day/activity 展示、无正式版本文案、与正式版本对照、无"接受/强制保存/忽略验证"按钮、malformed candidate/report 稳定错误、candidate 不替换正式 itinerary
- 真实失败：组件不存在（transform 失败）；实现后 2 失败——`/09:00/` 断言错（candidate 时间 UTC 转本地时区 17:00，组件行为正确）、对照区未显示活动名（组件只显示数量）

### GREEN

- `apps/web/src/components/PlanningReviewPanel.vue`（新增）："规划需要确认"标题 + 候选非正式声明 + "调整约束后重新规划"说明；嵌入 FeasibilityReportPanel（malformed 稳定降级）；候选行程（title/cost/days/activities/time window）；与当前正式版本对照（标题/预算/每日活动列表）；无正式版本文案；无接受/强制保存按钮；沿用 TripPilot 视觉
- 定向：PlanningReviewPanel.test.ts **10 passed**


## W4：TripWorkspace 权威状态机

### RED

- `apps/web/tests/App.test.ts` 新增 2 用例：`PLANNING_REVIEW_REQUIRED shows waiting user review without replacing the itinerary`（打开已有正式行程 → 重新规划 → SSE QUEUED + REVIEW_REQUIRED → 面板出现且正式行程不被替换）、`PLANNING_COMPLETED with VERIFIED report renders authoritative feasibility panel`（SSE COMPLETED → 正式行程 + 权威验证面板 + evaluation 并存）
- 真实失败（功能缺失）：`findByText('规划需要确认')` 找不到——waiting_user 状态与 PLANNING_REVIEW_REQUIRED 处理未实现（预期 RED）
- 真实失败（测试环境）：`打开 广州周末四日` 按钮找不到——两个用例位于顶级 describe `itinerary knowledge evidence states`，缺少 `beforeEach` 重置 history（`replaceState('/trips')`），前一用例导航到 `/trips/{id}` 污染后一用例初始路由，App 直接渲染 TripDetail 而非列表页；修复为该 describe 补 `beforeEach`（重置 history）+ `afterEach`（cleanup + unstubAllGlobals），与主 describe 对齐
- 真实失败（测试与产品语义对齐）：正式行程已存在时规划按钮文本为"重新规划"而非"开始规划"（TripDetail 动态按钮）；itinerary 首次加载成功才能验证"正式行程不被替换"；`getByText('候选行程')` 双匹配（面板标题 + 候选标题本身）改 `getAllByText`；`91/100` evaluation 异步加载改 `await findByText`
- 真实失败（回归防护）：`reports evaluation hydration failure and retries without reloading the trip` 被破坏——独立 feasibility 加载函数与 evaluation 各自请求 planning task，消耗 mock 的"首次失败"导致 evaluation 不再失败、alert 消失；修复为单一 task 请求（feasibility 填充合并进 `loadEvaluationForCurrentVersion`），hydration 用例恢复通过

### GREEN

- `apps/web/src/pages/TripWorkspace.vue`：`planningState` union 加 `waiting_user`；新增 `authoritativeFeasibilityReport`/`candidateItinerary`/`feasibilityLoadState` 状态；handleEvent 新增 `PLANNING_REVIEW_REQUIRED` 分支（terminal → waiting_user，report + candidate 写入状态，**不触发 itinerary 重载**——候选严格隔离）；`PLANNING_COMPLETED` 分支读取 `payload.feasibilityReport` 作为权威报告；`loadEvaluationForCurrentVersion` 在 task 返回后同步填充 feasibility（SUCCEEDED → report loaded；WAITING_USER → report + candidate loaded 且页面加载恢复 waiting_user）；clearEvaluation/stopPlanningStream/clearLocalSession 清理新状态；删除不可达死代码（`feasibilityError`、`feasibilityLoadState` 的 loading/error 分支）
- `apps/web/src/components/TripDetail.vue`：props 加 `feasibilityReport`/`candidateItinerary`/`feasibilityLoadState` 与 `planningState` 的 `waiting_user`；模板 `waiting_user` → `PlanningReviewPanel`（含 malformed 降级）、`succeeded || loaded` → `FeasibilityReportPanel`；`readFeasibilityReportResult` computed 统一安全读取
- `apps/web/src/components/PlanningProgress.vue`：union 加 `waiting_user`，状态消息"行程规划待确认"
- `apps/web/tests/App.test.ts`：2 新用例全流程断言（面板文本/权威状态/候选隔离/正式行程保持/evaluation 并存）；`itinerary knowledge evidence states` describe 补 beforeEach/afterEach
- 定向：App.test.ts **43 passed**（含 2 新用例）；全量 **33 文件 225 passed**（无回归）；typecheck 通过；build 通过

## W5：TripDetail/VersionSummary/PlanEvaluation 分层

### RED

- `apps/web/tests/ItineraryVersionPanel.test.ts` 新增 4 用例：VERIFIED 元数据徽章、NEEDS_REPAIR/UNVERIFIED 徽章、`feasibility=null` 显示"无历史验证"（且**不**显示"未验证"）、malformed 元数据降级"验证信息无法读取"（不得显示 VERIFIED）
- `apps/web/tests/PlanEvaluationPanel.test.ts` 新增 2 用例："仅代表体验质量，不代表硬可行性验证"说明文案、无硬验证状态词（已验证/待修复/未验证）
- 真实失败：5 用例功能缺失（组件未展示可行性元数据 / 无说明文案）

### GREEN

- `apps/web/src/components/ItineraryVersionPanel.vue`：版本记录行加可行性元数据徽章（`readVersionFeasibilityMetadata` + `FEASIBILITY_STATUS_LABEL` + VERIFIED/NEEDS_REPAIR/UNVERIFIED 三态样式）；`feasibility=null`/undefined → "无历史验证"（不等于 UNVERIFIED）；malformed → "验证信息无法读取"；判别联合 `feasibilityMetaOf` 返回展示结果，避免模板多次调用跨调用类型收窄问题
- `apps/web/src/components/PlanEvaluationPanel.vue`：header 下加"仅代表体验质量，不代表硬可行性验证"说明，与硬验证面板语义分离
- `apps/web/tests/App.test.ts`：`PLANNING_COMPLETED` 用例"已验证"断言改 `findAllByText`（权威面板 + 版本元数据徽章双匹配，W5 功能在 App 全流程生效）
- 定向：ItineraryVersionPanel + PlanEvaluationPanel **11 passed**；全量 **33 文件 231 passed**（无回归）；typecheck 通过

## W6：API/SSE 契约单元测试

### RED

- `apps/web/tests/api.test.ts` 新增 4 契约用例：`getPlanningTask` 返回 WAITING_USER task 保留 `feasibilityReport` + `candidateItinerary`；SUCCEEDED task 保留 `feasibilityReport` + `evaluation`；`streamPlanningTaskEvents` 解析 `PLANNING_REVIEW_REQUIRED` 事件 payload（report + candidate）；解析 `PLANNING_COMPLETED` 事件 payload（report + evaluation）
- 真实失败：无（契约传输层已由 W1 类型定义与 W4 状态机消费实现；本组为契约固化与回归保护，首跑即绿）

### GREEN

- `apps/web/tests/api.test.ts`：4 个契约用例固化 Task API 与 SSE 的可行性字段传输（与 Java `TaskEventView` payload 形状一致），后续改动破坏契约时立即回归
- 定向：api.test.ts **16 passed**；typecheck 通过

## W7：Playwright E2E

### RED

- `apps/web/e2e/feasibility-outcomes.spec.ts`（新增 3 用例）：REVIEW_REQUIRED 流程（正式行程存在 → 重新规划 → SSE 面板出现且正式行程不被替换）、COMPLETED 流程（无行程 → 规划 → VERIFIED 权威面板 + evaluation 并存）、WAITING_USER 页面加载恢复（task GET 返回 WAITING_USER → review 面板 + 版本 NEEDS_REPAIR 元数据徽章）
- 真实失败（环境）：本机无 Chrome，非 CI 配置 `channel: 'chrome'` 启动失败 → 以 `CI=1` 环境变量运行（Playwright 自带 chromium）
- 真实失败（测试 bug）：mock 的 itinerary 404 误作为响应体 JSON（HTTP 200）→ App 进入错误态而非"尚未生成行程"，改为 `route.fulfill({ status: 404, ... })`；completed 流程 versions 静态返回 `[]` → 完成后无 currentVersion 链 → evaluation 不加载，改为动态 mock（`onStream` 置 completed，versions/itinerary 用函数）；`已验证`/`91/100` strict mode 多匹配（W5 版本徽章 + summary 子串）→ `.first()` / `{ exact: true }`

### GREEN

- `apps/web/e2e/feasibility-outcomes.spec.ts`：3 用例全流程覆盖（登录 → 打开行程 → 规划/SSE → 权威面板/候选隔离/evaluation 语义/版本元数据徽章）
- 定向：feasibility-outcomes.spec.ts **3 passed**；完整 E2E 套件 **9 passed**（含 release-smoke 4 + v2-critical-journeys 2，无回归）

## 最终门禁

- `pnpm test`：**33 文件 235 passed**
- `pnpm test:coverage`：**33 文件 235 passed**，覆盖率报告生成无门槛失败
- `pnpm typecheck`：通过
- `pnpm build`：通过（dist 366.59 kB js / 44.22 kB css）
- `pnpm test:e2e`：**9 passed**（chromium，CI=1）
- `git diff --check`：通过（仅 CRLF 提示）
- 禁用断言扫描：新增/修改的可行性链路文件无 `as any` / `@ts-ignore` / `@ts-expect-error`
- Markdown links：B6W 文档为相对链接（plan ↔ execution-report），文件均存在；`markdown-link-check` 非仓库依赖（未安装）
- Git 状态：仅 B6W 范围文件 modified/untracked + 三个保护目录（`.omo/`、`.serena/`、`docs/audits/`）；未提交（等待独立验收 PASS 后提交）

## 集中修复（首轮独立验收 NEEDS_CORRECTION 后）

### 承认的原缺陷

- 原状态组合门禁缺失：SSE 事件直接写入 payload report/candidate，未校验 WAITING_USER+VERIFIED、SUCCEEDED+NEEDS_REPAIR 等非法组合，probe 实证显示"已验证"/"待修复"被渲染。
- 原 WAITING_USER 刷新恢复 fixture 不真实：把 WAITING_USER taskId 人工填入 current VersionSummary（真实后端 review 不创建版本），且执行报告声称"页面加载可恢复 WAITING_USER"不实。
- 原 coverage 未统计本批：vite.config.ts include 仅旧地图文件，`pnpm test:coverage` 门禁空跑；本批文件独立统计 branches 69.38% 不达标。
- 原文档未收口：总控计划 B6W 仍 NOT_STARTED，架构/产品 5 文档零 diff。
- 原 W1-W7 READY 声明不成立：E2E 场景不足（缺 UNVERIFIED review、SSE replay）、F 组缺时间窗/transit、E 组 eligible/repair/主边框缺陷、A 组 reader 多处 fail open、C1/C2 清理缺失。

### 本轮纠正

- **latest task discovery 端点**：新增 `GET /api/trips/{tripId}/planning-tasks/latest`（Mapper `findLatestOwnedByTripId`：created_at DESC, id DESC LIMIT 1 + owner JOIN；Service `latest`；Controller 路由；只读、复用 `PlanningTaskOutcomeReadModel`、无 task event）。Java 8 个新集成测试全绿（owner/order/tie-break/404/review/succeeded/failed/只读）。
- **统一前端 outcome parser**：`readPlanningTaskOutcome`/`readPlanningEventOutcome`（共享 `readTerminalOutcome`）覆盖 Task API hydration、SSE live、SSE replay；非法组合一律 malformed → "规划结果无法安全读取，请重新规划" + 清空 outcome + 不刷新正式行程。真值表 30+ 用例。
- **reader fail-closed**：schemaVersion 必须整数 1；validatorVersion 白名单（feasibility-v1、hard-validator-v1..v4，与 Java 一致）；requiredRuleIds/missingRequiredRuleIds/evidenceRefs/repairAttempts 缺失拒绝（允许空数组）；summary 非负；attemptIndex>=1；typed ref 空值/非规范 UUID 归 unknown；candidate transit mode/provider/estimated/polyline 必填、index 非负且越界拒绝；新增 `readPlanEvaluation` 安全 reader。
- **状态机集中化**：`clearPlanningOutcome`/`applyOutcomeState`/`attachPlanningStream`/`hydrateLatestPlanningTask`；新任务启动、手动取消、terminal failed/cancelled、流中断重试耗尽均清除旧 report/candidate/evaluation；页面加载经 latest 端点发现 WAITING_USER/QUEUED 任务（current version task 只代表创建正式版本的 task）。
- **FeasibilityReportPanel**：eligible 双向表达（"具备/不具备硬约束资格"）；repair affectedEntityRefs 展示节点短标签；主状态边框改根组件动态 class（status-verified/needs-repair/unverified），删除 `:has(.badge-*)`。
- **PlanningReviewPanel**：候选活动完整开始–结束时间窗；候选/正式 transit 摘要（起点→终点、mode、时长、距离、估算标记）；正式版本对照含交通；index 越界由 reader 拒绝。
- **E2E 7 场景**：VERIFIED completed、NEEDS_REPAIR review（含 repair history/evidence/无接受按钮）、UNVERIFIED review、SSE reconnect+Last-Event-ID、历史 feasibility=null、真实 latest 恢复（旧 SUCCEEDED 版本 + WAITING_USER latest）、非法组合 fail-closed。
- **coverage 真实覆盖**：vite.config.ts include 加入 feasibility.ts、FeasibilityReportPanel.vue、PlanningReviewPanel.vue；官方 `pnpm test:coverage` 全局 95.97/81.64/95.45/95.97（statements/branches/functions/lines）全部 ≥80。
- **文档收口**：总控计划 B6W 状态更新、规划工作流/事件契约/行程真实性/项目路线图 4 个架构产品文档追加 B6W 章节。

### 架构导读增量

1. 最新任务发现调用链：`PlanningTaskController.latest` → `PlanningTaskService.latest` → `PlanningTaskMapper.findLatestOwnedByTripId` → `PlanningTaskOutcomeReadModel.read` → `PlanningTaskResponse` → Web `getLatestPlanningTask`。
2. 页面 hydration 调用链：`TripWorkspace.loadTrip` → itinerary/versions/shares → `loadEvaluationForCurrentVersion`（current version task）→ `hydrateLatestPlanningTask`（latest endpoint）→ `applyOutcomeState`。
3. SSE replay/live 调用链：`attachPlanningStream` → `streamPlanningTaskEvents`（Last-Event-ID）→ `handleEvent` → `readPlanningEventOutcome` → `applyOutcomeState`。
4. current version task 与 latest task 语义区别：前者只代表创建正式版本的 SUCCEEDED task；后者是 trip 最新任务（可 WAITING_USER/QUEUED，无版本归属）。
5. report/candidate/evaluation 所有权：report 属于正式版本（VERIFIED）或候选预览（NEEDS_REPAIR/UNVERIFIED）；candidate 只属于 review；evaluation 只属于 completed。
6. fail-closed 状态组合：completed/review/queued/failed/cancelled/malformed 判别联合，非法组合一律 malformed。
7. 推荐阅读顺序：`feasibility.ts`（reader+parser）→ `TripWorkspace.vue`（状态机）→ `TripDetail.vue`（展示分层）→ `PlanningReviewPanel.vue`/`FeasibilityReportPanel.vue` → Java `PlanningTaskOutcomeReadModel`。
8. Java/Web 调试命令：`mvn --batch-mode -pl apps/travel-server -Dtest=PlanningTaskReadModelIntegrationTest test`；`pnpm vitest run tests/feasibility.test.ts`；`CI=1 pnpm test:e2e`。
9. 推荐断点：`PlanningTaskController.latest`、`PlanningTaskService.latest`、`PlanningTaskOutcomeReadModel.read`、`TripWorkspace.hydrateLatestPlanningTask`/`applyOutcomeState`、`readPlanningTaskOutcome`。
10. 本地调试实验：存在旧正式版本 → 产生 WAITING_USER review → 刷新页面 → latest endpoint 恢复候选 review 面板 → 正式版本保持不变（E2E `recovers a review-required task through the latest endpoint after a refresh` 即此实验的自动化复现）。

### 本轮门禁

- Java：`mvn --batch-mode -pl apps/travel-server verify` **BUILD SUCCESS**（402 tests，JaCoCo check 通过，无新增 migration）
- Web unit：**303 passed**（33 文件，含新增组合/清理/reader/parser/面板用例）
- `pnpm typecheck`：通过
- `pnpm test:coverage`：**303 passed**，全局 statements 95.97 / branches 81.64 / functions 95.45 / lines 95.97，thresholds 全绿；本批三文件逐项：`feasibility.ts` 95.14 / 82.01 / 100 / 95.14，`FeasibilityReportPanel.vue` 100 / 79.48 / 100 / 100，`PlanningReviewPanel.vue` 98.74 / 68.29 / 100 / 98.74
- E2E：feasibility-outcomes.spec.ts **7 passed**；完整套件 **13 passed**（chromium，CI=1）
- `python scripts/check_markdown_links.py`：87 文件链接有效
- `git diff --check`：通过；staged 空；无 `as any`/`@ts-ignore`/`@ts-expect-error`；Python worker/contracts/Flyway/Rabbit 零改动
- 状态：B6W 待最终独立复验（未提交）；B6F NOT_STARTED
