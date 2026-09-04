# 10 · 新版 Workspace UI 与旧版前端的功能对等审计（Feature Parity Audit）

> 审计性质：AUDIT ONLY · 2026-09-01 · 本文件不修改任何代码
> 基线：旧版 = `236d4de`（F-UI-1 之前，重构前最后一版） / 新版 = `HEAD`（F-UI-10 之后）
> 方法：路由对比、`lib/api.ts` 全量导出核对、workspace 目录 API 引用探测、旧版组件 testid 契约扫描、e2e 测试清单佐证。所有结论标注证据位置。

---

## 1. 核心结论（先读这里）

### 结论 1：旧版功能没有被删除，而是「入口被夺走」

旧版全部页面与组件在 `HEAD` 中**仍然存在、仍然连接真实后端**：

| 证据 | 位置 |
|---|---|
| 旧版主页面仍调用 `createPlanningTask` / `streamPlanningTaskEvents` / `updateTripConstraints` / `answerAgentRun` | `apps/web/src/pages/TripWorkspace.vue:23,46,48,810,847,1120` |
| 旧版路由全部保留（`/login` `/register` `/trips` `/trips/:id` `/trips/:id/plan` `/plan/new` `/share/:token`） | `apps/web/src/app/router/index.ts:14-31` |
| 唯一变化：`/` 默认重定向由 `trip-list` 改为新增的 `workspace` | 同一文件 `redirect` 行 |
| 曾被误判"删除"的 5 个文件，功能均已被合并承接（`PlanningProgress→AgentProgressPanel`、`ExecutionLane/StageBar→AgentProgressPanel kind='agent'`、`DecisionCard→ClarificationCard context`、`ResultPanel→ReviewPanel`） | `git diff --stat 236d4de HEAD` |

### 结论 2：新版 `/workspace` 是纯前端 demo 壳，不接任何后端

- `apps/web/src/workspace/` 全目录（36 个文件）**零 API 调用**，唯一例外是 `build-map-itinerary.ts` 的 `import type { Itinerary } from '../../lib/api'`（纯类型引用）。
- 数据来源：`workspace/demo/tripFixtures.ts` 硬编码假数据 + `stores/tripStore.ts` 的 `localStorage` 持久化。
- 后端 40 个 API 方法（`lib/api.ts` 导出）在 workspace 中**一个都没有被调用**。

### 结论 3：真正丢失的是「默认入口下用户能做的事」

用户打开产品 → 落在 `/workspace`（假数据壳）→ 看不到任何真实功能。真实功能全部退化为"手动输入 URL 才能到达"的隐藏路径。**风险不是功能丢失，而是功能失联**。

---

## 2. 后端能力总目录 vs 新版覆盖矩阵

后端 API 总目录（`apps/web/src/lib/api.ts`，40 个导出）：

| # | 能力域 | API（HTTP 路径） | 旧版 UI | 新版 /workspace |
|---|---|---|---|---|
| 1 | 鉴权 | `login/register/refresh/logout`（`/api/auth/*`） | `AuthView` + 401 自动轮换 | **无**（demo 直接进） |
| 2 | 行程列表 | `listTrips/searchTrips/archiveTrip/restoreTrip`（`/api/trips` `/api/trips/search`） | `TripDashboard` | **无**（fixture 列表） |
| 3 | 行程元数据 | `createTrip/getTrip/updateTripMetadata` | TripWorkspace | **无** |
| 4 | 约束 | `updateTripConstraints`（`/constraints`，乐观锁 409） | `ConstraintBoard` 行内编辑 | **无**（仅本地 updateConstraints，无版本号） |
| 5 | Agent 创建向导 | `sendAgentCreateDialogue/createTripFromAgent`（`/api/agent/dialogue` `/api/agent/trips`） | `CreateSessionView`（多轮槽位） | **无**（NewTripDrawer 本地表单） |
| 6 | Agent 对话流 | `streamAgentDialogEvents/startAgentRun/answerAgentRun`（`/agent-dialogue/runs`） | 澄清闭环（追问→回答→续规划） | **无**（假步骤动画） |
| 7 | 地点搜索 | `searchPlaces`（`/places/search`） | `PlaceAutocomplete` | **无** |
| 8 | 攻略导入 | `listGuideImports/createGuideImport/updateGuideImportEnabled`（`/guide-imports`） | GuideIntelligence 相关 | **无** |
| 9 | 规划任务 | `createPlanningTask/cancelPlanningTask/getPlanningTask/getLatestPlanningTask`（`/planning-tasks`） | 取消/恢复/刷新恢复 | **无**（仅 localStorage） |
| 10 | SSE 流式 | `streamPlanningTaskEvents`（12 阶段真实进度） | `PlanningProgress` 12 态 | **无**（fixture 静态步骤） |
| 11 | 行程读取 | `getCurrentItinerary`（`/itinerary`） | `TripDetail` | **无**（fixture） |
| 12 | 版本管理 | `listItineraryVersions/diffItineraryVersions/rollbackItinerary`（`/itinerary/versions` `/rollbacks`） | `ItineraryVersionPanel` | **无** |
| 13 | **行程编辑** | `previewItineraryEdit/applyItineraryEdit/commitItineraryEdits`（`/itinerary/edits*`；操作：`DELETE_ACTIVITY/LOCK_ACTIVITY/UNLOCK_ACTIVITY/MOVE_ACTIVITY/UPDATE_TRANSIT_LEG`） | `TripDetail` 草稿队列 | **无** |
| 14 | 重规划 | `createItineraryReplan`（`/itinerary/replans`） | `TripDetail` | **无** |
| 15 | 分享 | `listItineraryShares/createItineraryShare/revokeItineraryShare/getSharedItinerary`（`/itinerary/shares` `/api/shares/:token`） | `ItineraryActionsPanel` + `SharedItineraryPage` | **无** |
| 16 | 导出 | `downloadItineraryExport`（ics/pdf） | `ItineraryActionsPanel` | **无** |
| 17 | 城市/交通 | `china-divisions`/`transit`（纯前端 lib） | `CityCascadePicker`/`TransitLegControl` | **无** |

> 注：新版已恢复的部分 = 地图（`TripMap.vue` 复用，F-UI-10）+ 三态信息架构。除此之外**零覆盖**。

---

## 3. 逐项丢失清单（按用户可感知度排序）

### P0 — 数据链路断裂（用户每次使用都会撞到）

| 丢失功能 | 旧版实现 | 新版现状 | 恢复成本 |
|---|---|---|---|
| **登录/注册 + 401 自动轮换**（token 过期无感重放） | `app/stores/auth.ts` + `TripWorkspace.vue:644` `withAccessToken` | demo 直接进入 | 中（auth store 可整体复用） |
| **真实行程列表/创建/归档/恢复** | `TripDashboard` + `loadTrips()` | fixture 3+1 条 | 中（tripStore 换成 api 调用） |
| **SSE 流式规划（真实进度 12 阶段）** | `streamPlanningTaskEvents` + `PlanningProgress` | fixture 静态步骤动画 | 中（planning-stream.ts 可复用） |
| **Agent 澄清/追问闭环**（Agent 提问→用户回答→继续规划，`expectedType` 自适应控件） | `ClarificationCard` + `answerAgentRun` | **完全无** | 高（前后端契约齐全，纯接线） |
| **失败恢复/重试**（3 次 SSE 断流降级、90s 首事件超时、409 抢占恢复） | `useAgentWorkspace` + `ErrorRecoveryCard` | **无** | 高 |

### P1 — 内容能力丢失（已完成旅行的阅读体验降级）

| 丢失功能 | 旧版 | 新版现状 |
|---|---|---|
| **行程编辑**（删除活动/锁定活动/移动活动/改交通方式，带预览与幂等提交） | `TripDetail` + `useItineraryDraft` | **完全无**（只看不能改） |
| **版本管理**（版本列表/对比 diff/回滚） | `ItineraryVersionPanel` | **无** |
| **行程分享**（创建链接/撤销/免登录只读页） | `ItineraryActionsPanel` + `SharedItineraryPage` | **无** |
| **导出 ics/pdf** | `downloadItineraryExport` | **无** |
| **数据来源与可信度**（每地点 sources 外链 + reliabilityLevel + estimated/stale 标记） | `TripDetail` 活动卡片 | **无**（fixture 无此数据） |
| **天气时间线**（按日天气窗口） | `TripWeatherTimeline` | **无** |
| **方案质量评估**（维度评分 + 警告项） | `PlanEvaluationPanel`（`dimension-row`/`warning-item`） | **无**（右侧仅文案） |
| **可行性报告**（不可行项 + 数据状态） | `FeasibilityReportPanel` + `DataStatusCard`（诊断） | **无** |

### P2 — 交互闭环丢失（操作类）

| 丢失功能 | 旧版 | 新版现状 |
|---|---|---|
| 取消进行中规划 / 放弃 WAITING_USER 候选 | `cancelPlanningTask`（`pipeline-cancel`/`review-abandon`） | **无** |
| 约束编辑乐观锁（`version` 字段 + 409 冲突提示） | `ConstraintBoard` 行内编辑 | 仅本地覆盖 |
| 规划态刷新恢复（review/queued/completed 恢复） | `hydrateLatestPlanningTask` | 仅 localStorage 三态 |
| 地点搜索/自动补全（`searchPlaces`） | `PlaceAutocomplete` | **无** |
| 城市级联选择（省市区） | `CityCascadePicker` | **无**（自由文本） |
| 旅行风格/边界编辑（`pace`/`mobility`/`must_visit` 等 17 字段） | `TravelStyleEditor`/`TripBoundaryEditor` | 仅 6 字段表单 |
| 行程编辑结果按新条件重生成（陈旧交付提醒） | `ConstraintBoard` `regenerate-prompt` | **无** |

---

## 4. 恢复路线图（待用户拍板，本轮不改代码）

### 方案 A（推荐）：/workspace 成为唯一入口，接真实后端
把 `tripStore` 从 fixture/localStorage 换为 `lib/api.ts` 真实调用，逐项迁移：
1. **阶段 1（数据链路）**：auth（复用 `app/stores/auth.ts`）→ trip 列表/创建（`listTrips/createTrip`）→ SSE 规划（`streamPlanningTaskEvents` + 12 阶段进度）→ Agent 澄清闭环（`answerAgentRun`）。
2. **阶段 2（内容能力）**：`getCurrentItinerary` 接 `ItineraryWorkspace`（数据模型从 `PlanSummary` 迁移到真实 `Itinerary`，字段映射）→ 版本管理 → 分享/导出 → 天气/评估/可行性。
3. **阶段 3（编辑闭环）**：行程编辑（`preview/apply/commit` 三连）→ 约束乐观锁 → 取消/放弃候选。
- 优点：产品形态与当前视觉方向一致；后端契约全在，纯前端接线。
- 风险：工作量大（估计 3 个阶段各 2–3 天）；需要后端环境跑通全链路。

### 方案 B：双入口并存
- `/` 重定向回 `trip-list`（旧版真实功能为默认），`/workspace` 保留为"视觉演示"入口。
- 优点：零风险、立即可用。
- 缺点：产品分裂，两个入口两套数据，"演示壳"长期存在会持续误导。

### 方案 C：先接数据链路，内容能力后续
- 同方案 A 阶段 1，先让 `/workspace` 读真实数据（列表/规划/澄清），编辑/分享/评估等 P1 能力在后续迭代迁移。
- 优点：最快让用户用到真实数据，P1 能力按需补。
- 缺点：P1 能力在过渡期仍然缺失。

---

## 5. 验收标准（恢复完成后）

1. `/workspace` 下**零 fixture 依赖**：`grep -r "tripFixtures" src/workspace/` 无结果（demo 目录删除或仅留类型）。
2. 真实后端跑通闭环：登录 → 列表 → 新建 → SSE 规划 → 澄清回答 → completed → 编辑行程 → 版本 → 分享 → 导出。
3. 断网/失败场景：SSE 断流 3 次降级提示、401 无感轮换、409 冲突提示，全部有 UI 反馈。
4. 既有 91 项浏览器验收继续通过（testid 契约 keep-alive）。
5. 视觉方向不变：Codex 风格、中性色、中文，恢复功能不破坏 F-UI-10 已验收的内容层级。

---

## 附录：关键证据

```
# 1. 新版 workspace 零 API 调用（唯一命中是类型 import）
grep -rn "lib/api\|planning-stream\|/api/" src/workspace/
  → src/workspace/plan/build-map-itinerary.ts:13: import type { Itinerary } from '../../lib/api'

# 2. tripStore 数据来源
src/workspace/stores/tripStore.ts:11: import { tripFixtures } from '../demo/tripFixtures'

# 3. 旧版页面仍接后端
src/pages/TripWorkspace.vue:810:   updateTripConstraints(token, tripId, input)
src/pages/TripWorkspace.vue:847:   createPlanningTask(token, created.id, ...)
src/pages/TripWorkspace.vue:1120: streamPlanningTaskEvents(token, tripId, ...)

# 4. 后端能力总目录 40 API
src/lib/api.ts → login/register/refreshSession/logoutSession/listTrips/searchTrips/
archiveTrip/restoreTrip/getTrip/createTrip/updateTripMetadata/updateTripConstraints/
sendAgentDialogue/sendAgentCreateDialogue/createTripFromAgent/streamAgentDialogEvents/
startAgentRun/answerAgentRun/searchPlaces/listGuideImports/createGuideImport/
updateGuideImportEnabled/createPlanningTask/cancelPlanningTask/getPlanningTask/
getLatestPlanningTask/getCurrentItinerary/listItineraryVersions/diffItineraryVersions/
rollbackItinerary/previewItineraryEdit/applyItineraryEdit/commitItineraryEdits/
createItineraryReplan/listItineraryShares/createItineraryShare/revokeItineraryShare/
getSharedItinerary/downloadItineraryExport/streamPlanningTaskEvents

# 5. 行程编辑操作枚举（后端契约）
src/lib/api.ts:621: export type ItineraryEditOperation =
  'DELETE_ACTIVITY' | 'LOCK_ACTIVITY' | 'UNLOCK_ACTIVITY' | 'MOVE_ACTIVITY' | 'UPDATE_TRANSIT_LEG'

# 6. e2e 佐证（旧版真实功能面）
e2e/agent-workspace.spec.ts  feasibility-outcomes.spec.ts  golden-journeys.spec.ts
qa-real-chain.spec.ts  release-smoke.spec.ts  v2-critical-journeys.spec.ts  weather-window.spec.ts
```
