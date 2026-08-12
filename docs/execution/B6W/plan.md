# B6W 完整 Feasibility 前端执行计划

- 状态：COMMITTED（本提交；集中修复最终复验 PASS）
- 创建日期：2026-08-12
- 分支：`codex/feasibility-foundation`
- 已提交基线：`e72b8f662cc466010011d0929131c53910242223`（B6J.2 已验收 PASS 并提交，feat(platform): complete feasibility outcome read models）
- 执行报告：`execution-report.md`
- 验收报告：`acceptance-report.md`（首次 NEEDS_CORRECTION 已逐项关闭，最终复验 PASS 授权提交；本提交收口）
- B6W：COMMITTED（本提交；集中修复最终复验 PASS）
- B6F：NOT_STARTED

## 目标

让用户明确看到“已验证 / 待修复 / 未验证”三态硬可行性结论，并理解失败原因；WAITING_USER 候选行程与正式版本严格隔离；PlanEvaluation 只表示体验质量评分，不冒充硬验证。只做 Web 层及相应执行文档，不进入 B6F，不实现 B7。

## 非目标

- 不修改 apps/agent-service、apps/travel-server、contracts、Flyway、RabbitMQ
- 不实现 B7 repair 按钮或 API
- 不提供“直接接受 UNVERIFIED/NEEDS_REPAIR 为正式版本”的按钮
- 不重新聚合规则推导 report.status
- 不根据 PlanEvaluation score 推导 feasibility
- 不新增 npm 依赖（预期零新依赖）

## Authoritative status 语义

1. Feasibility Report 是硬可行性唯一权威结论。
2. 三态：VERIFIED（已验证）/ NEEDS_REPAIR（待修复）/ UNVERIFIED（未验证）。
3. 单规则：PASS / FAIL / UNKNOWN / NOT_APPLICABLE。
4. 证据：VERIFIED / UNKNOWN / STALE / CONFLICTING。
5. PlanEvaluation 只表示体验质量评分，绝不表示行程可执行/硬约束通过/已验证。
6. SUCCEEDED 对应正式版本并携带 VERIFIED report。
7. WAITING_USER 对应候选行程：report 只能 NEEDS_REPAIR/UNVERIFIED，candidate 不冒充正式版本，不更新 current itinerary。
8. 缺失/损坏/未知/过期/冲突证据不得显示为 VERIFIED。
9. 历史版本 feasibility=null 表示无历史验证元数据，不等于 UNVERIFIED。

## 数据来源

- Java Task API（`GET /api/planning-tasks/{taskId}`）：status、feasibilityReport、candidateItinerary、evaluation
- SSE（`/api/planning-tasks/{taskId}/events`）：PLANNING_COMPLETED / PLANNING_REVIEW_REQUIRED / PLANNING_FAILED / PLANNING_CANCELLED / PLANNING_PROGRESS，TaskEventView 包装 payload
- VersionSummary（`GET /api/trips/{tripId}/itinerary/versions`）：VersionSummary.feasibility（6 字段元数据或 null）
- 前端统一解析入口：`apps/web/src/lib/feasibility.ts`（Task API / SSE replay / SSE live 共用，避免三套分支漂移）

## 架构

```
Java Task API / SSE / VersionSummary
        ↓
apps/web/src/lib/api.ts（传输类型）
        ↓
apps/web/src/lib/feasibility.ts（运行时安全读取与展示辅助）
        ↓
TripWorkspace（单一状态所有者）
        ↓
TripDetail
        ├─ FeasibilityReportPanel
        ├─ PlanningReviewPanel
        ├─ PlanEvaluationPanel
        └─ ItineraryVersionPanel
```

## 工作组与 RED/GREEN 证据栏

| 组 | 内容 | RED 测试 | GREEN 关闭 | 状态 |
| --- | --- | --- | --- | --- |
| W1 | TypeScript 契约与运行时读取（feasibility.ts） | feasibility.test.ts 25 用例真实失败：模块不存在；result.report 应为 result.value；readRuleResults undefined 应拒绝 | 25 passed、typecheck、全量 198 passed；feasibility.ts + api.ts 类型 | done |
| W2 | FeasibilityReportPanel | FeasibilityReportPanel.test.ts 15 用例真实失败：组件不存在；getByText 歧义、文案"修复历史"、/评分/断言过严 | 15 passed；三态/规则/证据/repair 展示 + malformed 降级 | done |
| W3 | PlanningReviewPanel | PlanningReviewPanel.test.ts 10 用例真实失败：组件不存在；UTC 时区断言、对照区活动名缺失 | 10 passed；候选隔离面板 + 对照 + 无接受按钮 | done |
| W4 | TripWorkspace 权威状态机 | App.test.ts 2 用例真实失败：findByText('规划需要确认')（功能缺失）；history 污染致按钮缺失（describe 缺 beforeEach）；hydration 回归（双 task 请求） | 225 passed、typecheck、build；waiting_user 状态机 + REVIEW_REQUIRED 分支 + 权威 report 展示 + 候选隔离 | done |
| W5 | TripDetail/VersionSummary/PlanEvaluation 分层 | ItineraryVersionPanel 4 用例 + PlanEvaluationPanel 2 用例真实失败（组件缺可行性元数据徽章/缺说明文案） | 231 passed、typecheck；版本可行性元数据徽章 + null≠UNVERIFIED + malformed 降级 + 体验/硬验证语义分离 | done |
| W6 | API/SSE 契约单元测试 | api.test.ts 4 契约用例（首跑即绿——W1/W4 已实现传输，本组固化） | api.test.ts 16 passed；Task API/SSE 可行性字段契约固化 | done |
| W7 | Playwright E2E | feasibility-outcomes.spec.ts 3 用例（环境：无 Chrome 用 CI=1 自带 chromium；404 mock/动态 versions/strict mode 修复） | 完整 E2E 9 passed；REVIEW/COMPLETED/恢复三旅程全绿 | done |

## 文件范围

允许修改/新增：
- apps/web/src/lib/api.ts、apps/web/src/lib/feasibility.ts（新增）
- apps/web/src/components/FeasibilityReportPanel.vue（新增）、PlanningReviewPanel.vue（新增）
- apps/web/src/components/TripDetail.vue、ItineraryVersionPanel.vue、PlanEvaluationPanel.vue
- apps/web/src/pages/TripWorkspace.vue
- apps/web/tests/**、apps/web/e2e/feasibility-outcomes.spec.ts（新增）
- docs/execution/B6W/plan.md、execution-report.md
- docs/architecture/规划工作流.md、事件契约.md、行程真实性与旅行骨架.md
- docs/product/项目路线图.md、系统完善长期执行与验收总控计划.md

禁止修改：apps/agent-service/**、apps/travel-server/**、contracts/**、Flyway、Rabbit、.env、.omo/、.serena/、docs/audits/

## 验收矩阵

- authoritative report 三态完整展示
- 规则/证据/影响节点/repair history 可展示
- WAITING_USER candidate 与正式版本严格隔离
- completed/review API 与 SSE 统一消费
- VersionSummary nullable metadata 正确
- PlanEvaluation 不冒充硬验证
- 空值和 malformed 稳定降级
- unit/typecheck/build/coverage/E2E 全绿
- 无 `as any` / `@ts-ignore` / `@ts-expect-error`
- 无 score/feasible 推导 report.status

## 最终门禁

apps/web：pnpm test、pnpm typecheck、pnpm build、pnpm test:coverage、pnpm test:e2e
仓库：Markdown links、git diff --check、git diff --cached --name-only、git status

## 当前 Checkpoint

- W0：安全审计通过（HEAD=e72b8f6、staged 空、tracked 干净、三保护目录）
- W1：done（feasibility.ts 25 用例，198 passed 基线）
- W2：done（FeasibilityReportPanel 15 用例）
- W3：done（PlanningReviewPanel 10 用例）
- W4：done（TripWorkspace 权威状态机，App.test.ts 43 用例 / 全量 225 passed / typecheck / build）
- W5：done（版本可行性元数据徽章 + PlanEvaluation 语义分离，全量 231 passed / typecheck）
- W6：done（API/SSE 契约固化，api.test.ts 16 passed）
- W7：done（Playwright E2E，完整套件 9 passed）
- 最终门禁：pnpm test 235 passed / test:coverage 235 passed / typecheck / build / test:e2e 9 passed / diff --check / 禁用断言扫描 全绿
- **集中修复（首轮验收 NEEDS_CORRECTION 后）**：latest task discovery 端点（Java+Web）、统一 outcome parser 与状态组合 fail-closed、reader 版本/必填/枚举/ref 门禁、真实 WAITING_USER 刷新恢复（latest 发现）、新任务/取消/失败清理、FeasibilityReportPanel 资格/修复实体/主状态边框、PlanningReviewPanel 时间窗/transit/对照、E2E 7 场景、官方 coverage 纳入本批文件、架构/路线图/总控/执行报告收口
- 批次状态：COMMITTED（本提交；集中修复最终复验 PASS，授权提交收口）

## 恢复执行说明

若会话中断：从本 plan 的 Checkpoint 恢复；每轮 RED 先运行对应测试确认真实失败（功能缺失），GREEN 后记录；先跑 `git status` 确认基线未漂移。完成所有 W1-W7 与最终门禁后，将本文件状态改为 READY_FOR_REVIEW 并输出 `B6W_READY_FOR_REVIEW`。

## 禁止事项

- 先写生产代码后补测试
- `as any` / `@ts-ignore` / `@ts-expect-error`
- 删除断言换取通过
- 用 contains 冒充结构化验证
- 用 PlanEvaluation score 计算 feasibility
- 组件内维护第二套 report 聚合规则
- 静默把非法 report 降级成 VERIFIED
- 新增不必要依赖 / 修改 pnpm-lock.yaml
- 大规模重写现有视觉系统
- 修改后端/契约/Python
