# Frontend UI Consolidation Report

范围：`apps/web`（前端展示层）
基线：`236d4de`（F-1b 之后的干净树）
收尾：`f7a4de7`（F-UI-5）
阶段：F-UI-0 审计 + F-UI-1..5 五刀，每刀独立验收、独立提交
改动规模：55 个文件，+2812 / −1959（含测试）

---

## 1. 当前问题（F-UI-0 审计结论）

整合前的 `apps/web` 已经从"轻量旅行规划器"长成"信息密集的规划后台"，问题集中在五类：

1. **一个容器挂五个全屏视图**：`pages/TripWorkspace.vue`（1445 行）在模板里用 `v-if` 互切 Dashboard / TripDetail / Session / Create / 404，切换即整页重挂，用户没有稳定的工作区。
2. **三套进度组件、三套状态 union**：`PlanningProgress.vue`、`agent-workspace/StageBar.vue`、`planning-session/ExecutionLane.vue` 各自渲染"规划到哪了"，各自有一套阶段命名。
3. **审阅面板双份**：`PlanningReviewPanel.vue` 与 `planning-session/ResultPanel.vue` 是同一件事的两个实现，文案与动作集不一致。
4. **约束三种呈现、真实文案冲突**：`ConstraintBoard` / `ConstraintEditor` / TripDetail 的 `dt/dd` 各写一份标签表；同一 pace 值在不同页面叫"舒缓"和"轻松"。
5. **内部键直接上屏**：hero 区的 `providerLabel`、`activity.source` 裸枚举、`SharedItineraryPage` 的 `reliabilityLevel`、进度组件里的 `attemptIndex: 2`（statistics 裸键）、6+ 处手写 Empty/Error/Loading、若干组件里的深色/渐变硬编码。

用户视角的结果是：不懂 LangGraph / Tool / Provider / Checkpoint 就无法判断"Agent 做到哪、做了什么、结果如何、需要我做什么"。

---

## 2. 信息架构调整

认证后统一为**持久工作台壳**（`components/shell/WorkbenchShell.vue`），取代 5 个全屏视图互切：

```
┌ ShellTopbar：品牌 + 用户 + 登出
├ TripRail（左）：行程列表唯一呈现（搜索 / 含归档 / 状态点 / 新建入口）
├ 中域：路由内容（TripHome / TripDetail / TripSessionView / 404）
└ ContextRail（右，仅 trip-detail / trip-plan，可折叠）：环境 / 变更 / 产出 + L3 详细信息
```

壳只负责布局与呈现，**不接管任何状态**：SSE、409 竞态恢复、终态短路、代际守卫全部留在 `TripWorkspace`，一行未动。左栏切选中只做 `router.push`，复用既有 `loadTrip` 路径。

**信息分层（贯穿全部面板的一致约定）**：

| 层 | 定义 | 内容 |
|---|---|---|
| L1 | 默认可见 | 状态、结果、下一步动作 |
| L2 | 折叠在"详情" | 过程、工具结果、验证结果、错误详情 |
| L3 | 默认隐藏的"详细信息"折叠区 | provider / versionId / taskId / errorCode / statistics / 原始枚举 |

约定：**L3 值必须可达，但绝不上默认表面**。

---

## 3. Agent 工作区调整

- **进度统一**：三套进度组件合并为 `components/progress/AgentProgressPanel.vue`（342 行，`kind: 'planner' | 'agent'`）。阶段名由单一 `steps` 表派生；`statistics` 白名单键翻译成用户文案，其余键进 L3。终态规则原样迁移（"行程规划已完成"时隐藏百分比）。
- **审阅统一**：`PlanningReviewPanel.vue` + `ResultPanel.vue` 合并为 `planning-session/ReviewPanel.vue`（579 行，`mode` × `variant` 两处复用）。动作集仍然只有后端的三个真实能力：**修改要求 / 放弃本方案 / 去补充核实**——未发明"批准方案"按钮。
- **等待用户收敛**：`DecisionCard.vue` 并入 `agent-workspace/ClarificationCard.vue`（新增可选 `context` prop 承载决策上下文说明行）。
- **错误与完成**：`agent-error-card` / `agent-error-restart` / `agent-completed-card` / `agent-apply-cta` 的语义与 testid 全部保留，仅换绑到统一组件。
- **CreateSessionView 的 NL 对话流原样保留**，未恢复搜索框式自动填充。

---

## 4. 组件合并 / 删除

**删除（7 个文件）**

| 文件 | 处置 |
|---|---|
| `components/TripDashboard.vue`（527 行） | 拆为 `shell/TripRail.vue` + `shell/TripHome.vue`，创建对话框迁移 |
| `components/PlanningProgress.vue` | 并入 `progress/AgentProgressPanel.vue` |
| `components/agent-workspace/StageBar.vue` | 并入同一进度面板 |
| `components/planning-session/ExecutionLane.vue` | turn 分组并入面板 L2 层 |
| `components/planning-session/ResultPanel.vue` | 并入 `planning-session/ReviewPanel.vue` |
| `components/PlanningReviewPanel.vue` | 重命名并合并为 `ReviewPanel.vue`（git 识别为 R065） |
| `components/planning-session/DecisionCard.vue`（32 行） | 并入 `agent-workspace/ClarificationCard.vue` |

**新增基元（一次性接真实数据，不留空骨架）**

- `components/ui/{EmptyState,ErrorState,LoadingState,Drawer}.vue` —— `Drawer` 是 `lib/modal.ts` 中 `useModalFocus` 的唯一共同持有者（Esc / 焦点还原 / aria）。
- `components/shell/{WorkbenchShell,ShellTopbar,TripRail,TripHome,ContextRail}.vue`
- `components/constraints/ConstraintSummary.vue`
- `lib/{status,constraint,source,fact-status}-presentation.ts`（纯函数 + 单测）

**F-UI-5 的收敛收尾**：三处手写 `Teleport` 抽屉（`DataStatusCard` / `ItineraryVersionPanel` / `GuideIntelligencePanel`）→ `ui/Drawer`；行内卡片/按钮类串 → `ui/Card` / `ui/Button`；`PlanEvaluationPanel` 的 33 行自定义调色板删除；`FeasibilityReportPanel` 整个 `<style scoped>` 删除，`ReviewPanel` 只保留 `prefers-reduced-motion` 可访问性规则。

---

## 5. 页面调整

- **trip-list**：左栏是行程列表唯一呈现（删除卡片网格）；中域 `TripHome` = 选中概览 + 单一创建入口（保持单入口约束，`agent-plan-entry` + 手工兜底）。
- **trip-detail**：`TripDetail.vue` 1581 → 1531 行；hero 区 `providerLabel` 与 `activity.source` 裸枚举移除；三态改用 ui 基元；`activityKindLabel` 改为 fail-closed（未知类型不渲染标签）；导航锚点（概览/行程/地图/质量/版本与导出）保留。
- **trip-plan / session**：`TripSessionView` 换绑统一面板，`'running'` 折叠规则不变。
- **shared**：`SharedItineraryPage` 移除 `provider` 与 `reliabilityLevel` 裸值。
- **路由表未改动**，`/trips/:id/versions` 等全部保留。
- `vite.config.ts` 仅同步了 `manualChunks` 的模块名（TripDashboard → Rail/Home/ContextRail/status-presentation），属构建内部分包，非行为改动。

---

## 6. 删除的无价值信息

| 原上屏内容 | 去向 |
|---|---|
| hero 区 `providerLabel`（AMAP / DEMO 徽标） | 聚合进"数据说明" L3 |
| `activity.source` 裸枚举 | 同上 |
| `SharedItineraryPage` 的 provider / `reliabilityLevel` | 删除 |
| 进度组件 `attemptIndex: 2` 等 statistics 裸键 | 白名单键→用户文案，其余→L3 |
| `ConstraintEditor` 的"演示" provider 徽标 | 删除 |
| 行程主页面平铺的 fact `effect` 语义标签（如 `OPENING_HOURS_EVIDENCE_AVAILABLE`） | 中性数据状态文案 + L3 高级诊断保留原始 reason/evidence |
| 6+ 处手写 Empty / Error / Loading | 三个 ui 基元 |
| 三套阶段命名、两套审阅文案、三套约束标签表、三套 Feasibility 映射 | 各归一 |
| 重复主题 token 的自定义 scoped CSS（`PlanEvaluationPanel` / `FeasibilityReportPanel` / `ReviewPanel`） | 删除，改用 Tailwind token 工具类 |

顺带修掉一个真实缺陷：`var(--surface-500, #71717a)` 在本项目**永远无法解析**（项目没有 CSS 变量层，调色板是 `tailwind.config.js` 里的字面色值），所以它实际渲染的是 zinc `#71717a` 而非 surface-500 `#6b6259`。改为 `text-surface-500` 后回到正确 token。

---

## 7. 保留的核心功能

- SSE 规划流、断线重连、409 竞态恢复、终态短路、代际守卫（`TripWorkspace` 内一行未改）。
- 约束五字段编辑 + `ConstraintEditorModel` / 校验 / `toTripConstraints` PUT 载荷 / `agent-slots` 投影 / `agent-slot-*` testid。
- 审阅三动作（edit / abandon / verify）与 `reviewTaskId`、`abandonBusy` 守卫。
- 行程编辑草稿（`useItineraryDraft`）、路段模式选择与锁定、版本 diff / 回滚 / 对比、ICS / PDF 导出、分享链接创建。
- 攻略情报导入（公开链接 / 粘贴正文 / 截图）、城市情报同步、天气时间轴、地图。
- 计划质量评估（五维 + 警告）与 feasibility 报告的解析和 fail-closed 规则。
- 文案锚点：`'无法连接业务服务'`、`'真实数据 ✓'` 原样保留。

---

## 8. API Contract 影响 = 零

`git diff --name-status 236d4de..f7a4de7` 的全部 55 个文件都在 `apps/web/` 下：

- 无 Java / Python / `contracts/` / migration / OpenAPI 改动；
- 无请求体、请求路径、HTTP 方法、状态码、错误码语义改动；
- 无新增 API 调用；右栏三节数据全部是 `TripWorkspace` 现有状态的只读投影；
- 被独立挂载测试锁死的 6 类组件（TripDetail / PlanningSessionPage / ReviewPanel / AgentProgressPanel / DataStatusCard / ConstraintBoard）props/emit 原样保留。

**验收**：五刀全程 `git status` 逐刀审校，只出现 `apps/web` 路径；`docs/execution/2026-08-31-phase-b/` 三个文件保持未跟踪。

---

## 9. 验证结果

### 9.1 自动化门（每刀一次，均在 `apps/web` 下执行）

| 阶段 | commit | 文件 | 变更 | vitest | build |
|---|---|---|---|---|---|
| F-UI-1 | `b580527` | 18 | +1134 / −752 | 全绿 | 通过 |
| F-UI-2 | `42f5c5d` | 11 | +658 / −538 | 全绿 | 通过 |
| F-UI-3 | `731cdba` | 12 | +397 / −124 | 全绿 | 通过 |
| F-UI-4 | `58934cf` | 11 | +288 / −164 | 全绿 | 通过 |
| F-UI-5 | `f7a4de7` | 16 | +384 / −430 | 全绿 | 通过 |

F-UI-5 收尾实测：`corepack pnpm vitest run` → **Test Files 55 passed (55) / Tests 562 passed (562)**；`corepack pnpm build`（vue-tsc + vite 7.0.6）→ **✓ 1703 modules transformed ✓ built**（基线 1692）。基线计划书写的 530 测试，现已增长到 562（新增均为本改造的反事实用例）。

### 9.2 浏览器金色路径走查（`corepack pnpm dev`，只读）

- 登录 → 工作台壳 → 行程列表（左栏，2 条）→ 详情页。
- **裸值扫描**：在已生成行程的详情页对渲染文本做正则扫描 `\b[A-Z][A-Z0-9]*(_[A-Z0-9]+)+\b`（SCREAMING_SNAKE 枚举）与 UUID 模式 → **枚举命中 0、UUID 命中 0**；关键字表（AMAP / DEMO / versionId / TASK_ / errorCode / statistics / OPENAI / FULL_DAY / OFFICIAL / UNAVAILABLE …）命中 0。
- 控制台：仅 vite debug 与高德 SDK 的 `Canvas2D willReadFrequently` 提示，**无 error**。
- L3 可达性以单元/集成测试为证据：`DataStatusCard.test.ts`（`open-data-explainer` → `toggle-diagnostics` 后原始 category/evidence 可见）、`ItineraryVersionPanel`（`open-version-history` → diff/rollback/metadata）、`PlanningReviewPanel.test.ts:196`。走查的两段旅行恰好不满足这两个按钮的既有 `v-if`（分别为 `facts.length` 与 `historyVersions.length`），因此页面上未出现该按钮属预期行为，非缺失。

### 9.3 testid 保活对照（计划书第 6 条 · 19 项）

19 项逐条核对结果：**17 项静态命中 + 2 项需脚注 = 无一项丢失**。

| # | testid | 现状 |
|---|---|---|
| 1 | `start-planning` | `TripDetail.vue:1037` |
| 2 | `abandon-candidate` | `planning-session/ReviewPanel.vue:312` |
| 3 | `planning-session` | `TripSessionView.vue:167`、`CreateSessionView.vue:49` |
| 4 | `agent-completed-card` | `agent-workspace/CompletedCard.vue:31` |
| 5 | `agent-apply-cta` | `agent-workspace/CompletedCard.vue:44` |
| 6 | `pipeline-building` | `planning-session/ReviewPanel.vue:496` |
| 7 | `agent-input` | `TripSessionView.vue:341`、`CreateSessionView.vue:171` |
| 8 | `agent-error-card` | `agent-workspace/ErrorRecoveryCard.vue:14` |
| 9 | `agent-error-restart` | `agent-workspace/ErrorRecoveryCard.vue:28` |
| 10 | `agent-command-error` | `TripSessionView.vue:328`、`CreateSessionView.vue:158` |
| 11 | `agent-plan-entry` | `shell/TripHome.vue:161` |
| 12 | `session-restart` | `planning-session/SessionHeader.vue:55` |
| 13 | `goal-canvas` | `planning-session/GoalCanvas.vue:28` |
| 14 | `goal-manual-fallback` | `planning-session/GoalCanvas.vue:60` |
| 15 | `open-version-history` | `ItineraryVersionPanel.vue:157` |
| 16 | `save-itinerary-draft` | `TripDetail.vue:1412` |
| 17 | `trip-map` | `TripMap.vue:170` |
| 18 | `agent-slot-budget` | **脚注 A**：源内为动态 `` :data-testid="`agent-slot-${row.name}`" ``（`ConstraintBoard.vue:99`、`CreateSessionView.vue:112`），`agent-slot-budget` 由 `row.name === 'budget'` 运行时生成，`e2e/agent-workspace.spec.ts:260` 与 `TripSessionView.test.ts:231` 均按此命中 |
| 19 | `validation-details-toggle` | **脚注 B**：全仓仅有**负向**断言（`e2e/golden-journeys.spec.ts:373`、`e2e/weather-window.spec.ts:191` 的 `toHaveCount(0)`，`PlanningReviewPanel.test.ts:196` 的 `toBeNull()`）。该 testid 在基线 `9d0f131` 就被刻意移除，断言的是"它不该出现"，因此 F-UI 各阶段都未导致该项丢失 |

阶段内新引入的钩子（供后续 e2e 使用）：`plan-evaluation-panel`、`dimension-row`、`warning-item`、`decision-context`、`constraint-summary`、`constraint-row-*`、`transit-leg-*`。

---

## 10. 剩余问题

1. **`ItineraryVersionPanel` 的琥珀色 回滚 / 确认回滚 按钮对仍是原生 `<button>`**。`ui/Button` 现有 variant 无对应"危险且琥珀"的组合，强行套用会改变外观；F-UI-5 的约束是"纯样式收敛、不动行为"，故留待 Button variant 扩展那一刀处理。
2. **`TripMap.vue` 仍保留 10 处字面色值**（Leaflet `:deep()` 覆盖，第三方 DOM 无法用 Tailwind 工具类命中）、**`TripWorkspace.vue` 的 restoring-pulse 关键帧** 亦为字面色。二者均与主题 token 同值，非视觉缺陷，属"无法用工具类表达"的合理残留。
3. **`PlanEvaluationPanel` 的 INFO 严重度徽标由蓝色归一到 `Badge variant="secondary"`**。语义更一致（三级 = 中性 / 注意 / 严重），但确实是一次可见的颜色变化，已提交在 F-UI-5 内。
4. **`TripDetail.vue:1346` "检索问题：{{ itinerary.knowledge.query }}"** 会把后端自由文本原样上屏，走查中观测到 `检索问题：杭州 SOLO`——其中的 `SOLO` 是后端拼 query 时带入的 travelerType 枚举。它是**基线既有行为、不在 F-UI-5 的行内映射清单内**，且所在小节（"推荐依据"）本身就是证据出处区，故未在本刀处理。
5. **F-1 遗留两项仍在挂起**（与本前端改造无关）：`#19 F-1c 一次性脚本 + 契约旧版本归档`、`#20 F-1 实施记录文档`。

---

## 11. 建议下一步

1. **给 `ui/Button` 增加 danger/amber 确认态 variant**，随后收掉 `ItineraryVersionPanel` 最后一对原生按钮（第 10 节 #1），一次小刀即可完成。
2. **把 `knowledge.query` 从 L1 挪到"推荐依据"小节内的折叠行**，或对后端 query 做展示层清洗，消除第 10 节 #4 的枚举外泄。
3. **补一组 Playwright 断言**：在跨阶段 testid 表（第 9.3 节）之上，把 `constraint-summary`、`plan-evaluation-panel`、`decision-context` 三个新钩子纳入金色路径，锁定收敛成果不再回退。
4. **视觉回归**：本轮"暗色/渐变残留"清理依赖构建 CSS 级联与字节等值推导，未做像素对比。若要把视觉中性变成硬保证，加一次截图基线（Playwright `toHaveScreenshot`）成本最低。
5. 回到 F-1 主线，处理挂起的 `F-1c` 与 `F-1` 记录文档。

---

## 附录 A · 统一状态词汇定稿

全部为纯函数 / 常量表，未知值一律 fail-closed（不渲染或回落通用中文），**只统一展示层，不改任何状态机逻辑**。

### A.1 `lib/status-presentation.ts`

**planningState（L1 主轴）**

| 输入 | 文案 | tone |
|---|---|---|
| `idle` | 未开始 | neutral |
| `queued` 且无进度流动 | 排队中 | active |
| `queued` 且进度流动 | 规划中 | active |
| `waiting_user` | **需要你确认** | attention |
| `succeeded` | 规划完成 | success |
| `failed` | 规划失败 | danger |
| `cancelled` | 已取消 | neutral |
| 不可解析 | 暂时无法读取规划状态（fail-closed） | danger |

排队 / 规划中纯派生自现有 `planningProgress`，无新增数据源。

**Trip.status（左栏）**：`DRAFT`→草稿 / `PLANNING`→规划中 / `READY`→可使用 / `FAILED`→规划失败；未知值不渲染。
（运行时 `Trip.status` 只有 `DRAFT`——Java 侧唯一写入点 `TripService.java:78`，`TripMapper` 无 `UPDATE trip SET status`；其余为防御映射。）

**FeasibilityStatus（合并原三处映射）**：`VERIFIED`→已验证并保存 / `NEEDS_REPAIR`→部分信息待确认 / `UNVERIFIED`→未验证。
徽标色由 `ItineraryVersionPanel.vue:60` 的 `FEASIBILITY_BADGE_VARIANT` 单点派生：success / warning / secondary。

### A.2 `lib/constraint-presentation.ts`

字段标签：目的地 / 出发日期 / 返程日期 / **出行人数**（原"同行"）/ **总预算**（原"预算"）/ 旅行节奏 / 必去地点 / 避开地点 / 住宿位置 / 抵达安排 / 返程安排 / 行动能力 / 偏好标签 / 固定安排。

| 维度 | 映射 |
|---|---|
| pace | RELAXED→**轻松**（裁决：取代"舒缓"）/ BALANCED→均衡 / INTENSIVE→紧凑 |
| mobility | STANDARD→标准步行 / REDUCED→减少步行 / STEP_FREE→尽量无台阶 |
| travelerType | SOLO→独自出行 / COUPLE→伴侣同行 / FAMILY→家庭出行 / FRIENDS→朋友同行 / BUSINESS→商务出行 |
| accommodationStatus | CONFIRMED→已确认 / AREA_ESTIMATED→区域估计 / UNRESOLVED→未定位 |

### A.3 `lib/source-presentation.ts`

AMAP→真实数据 / DEMO→演示数据 / MIXED→混合数据 / PLANNER→规划器数据；未知值 fail-closed。

### A.4 `lib/fact-status-presentation.ts`

类别：OPENING_HOURS→营业时间 / WEATHER→天气 / ROUTE→路线 / **其他→其他行程信息**（fail-closed 兜底）。
摘要层只说数据状态（保留 `'真实数据 ✓'`），原始 `effect` / `reason` / `evidence` 只出现在 L3 高级诊断，绝不误导为"已核验"。

### A.5 `lib/plan-evaluation-presentation.ts`

五维：约束满足 / 时间合理 / 预算匹配 / 兴趣匹配 / 路线效率。
警告严重度：INFO→提示 / WARNING→注意 / CRITICAL→严重。
决策主体：PLAN→总体 / DAY→当日 / ACTIVITY→活动 / TRANSIT→路段。
分数色阶：≥85 emerald-700 / ≥70 warm-700 / 其余 red-700。

### A.6 保留不动

`agent-timeline` 的 stageLabel（L2 层）、`slotStateLabel`、fact-status 摘要文案。

---

## 附录 B · 各阶段变更记录

| 刀 | commit | 主题 | 关键动作 |
|---|---|---|---|
| F-UI-0 | — | 事实审计 + 设计判定 | 核实 8 项地基事实（Trip.status 运行时单值、WAITING_USER 无批准动作、被测试锁死的文案、statistics 裸键断言、6 类组件独立挂载、19 项 testid 清单、ui/Button 无 loading prop、展示层先例）；产出实施方案 |
| F-UI-1 | `b580527` | 持久壳 + 左栏 + 右栏 + 状态模块 + 通用基元 | 新增 `status-presentation` + 5 个 shell 组件 + 4 个 ui 基元；`TripWorkspace` 模板套壳（状态与处理器零改动）；删除 `TripDashboard.vue`；`TripDashboard.test` 重写为 Rail + Home；`vite.config` manualChunks 同步 |
| F-UI-2 | `42f5c5d` | Agent 状态 / 审阅 / 错误 / 完成收敛 | 新增 `AgentProgressPanel`（合并 3 进度组件，statistics 白名单→文案，其余→L3）；`PlanningReviewPanel` + `ResultPanel` → `ReviewPanel`；删除 `PlanningProgress` / `StageBar` / `ExecutionLane`；`PlanningProgress.test:91` 裸键断言同刀更新 |
| F-UI-3 | `731cdba` | 创建流程 + 约束呈现统一 | 新增 `constraint-presentation` + `ConstraintSummary`；TripDetail `dt/dd` → 统一摘要；`ConstraintBoard` 标签走展示层（投影 / 编辑 / PUT / `agent-slot-*` 零改动）；`TravelStyleEditor` "舒缓"→"轻松"；`ConstraintEditor` 移除"演示"徽标；ContextRail 环境节接入 |
| F-UI-4 | `58934cf` | 结果 / 行程展示 + 导出分享 + 泄漏清零 | 三处手写 `Teleport` → `ui/Drawer`；TripDetail 移除 hero `providerLabel` 与 `activity.source` 裸渲染，三态换 ui 基元；`SharedItineraryPage` 移除 provider / reliabilityLevel 裸值；新增 `source-presentation`；Feasibility / PlanEvaluation 标签走统一词汇；ContextRail 产出节接入 |
| F-UI-5 | `f7a4de7` | 组件收敛收尾 + 视觉统一 + 本报告 | `DecisionCard` 并入 `ClarificationCard`（+`context` prop）；行内映射归一（`FEASIBILITY_*`、pace、fact 类别 fail-closed）；行内卡片/按钮类串 → `ui/Card` / `ui/Button`；`GuideIntelligencePanel` 手写覆盖层 → `ui/Drawer` 并删除死分支 `<ul v-if="false">`；`PlanEvaluationPanel` 33 行自定义调色板删除；`FeasibilityReportPanel` 整个 scoped style 删除（顺带修 ghost-token 缺陷）；`ReviewPanel` 只留可访问性规则；TripDetail 活动类型标签改 fail-closed 并补反事实用例 |

F-UI-5 提交内容：16 个文件，+384 / −430，`delete mode 100644 apps/web/src/components/planning-session/DecisionCard.vue`。
