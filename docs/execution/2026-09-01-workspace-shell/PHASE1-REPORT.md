# TripPilot Workspace Shell 重建报告（Phase 1）

日期：2026-09-01 ｜ 冻结点：`legacy-ui-freeze` tag（HEAD: d6f77bd, F-UI-5）

## 1. Architecture Report

### 新增（New）
| 文件 | 职责 |
| --- | --- |
| `apps/web/src/workspace/WorkspacePage.vue` | Shell 顶层装配：Header / Sidebar / Execution / Context / CommandBar 四区；抽屉式响应式（<1024 抽屉互斥，1024–1279 Context 可折叠，≥1280 三栏） |
| `workspace/layout/WorkspaceHeader.vue` | Application Bar：面板开关、任务标题居中（`TripPilot / 上海三日旅行`）、演示数据标识 |
| `workspace/layout/WorkspaceSidebar.vue` | Workspace Navigation：WORKSPACE 功能区（工作台/我的旅行/搜索）+ TRIP PROJECTS 项目列表（状态点 + 当前项 Planning 高亮）+ 新建旅行 |
| `workspace/layout/WorkspaceContextPanel.vue` | Context Inspector：Agent 状态 / Task+Version / 旅行约束（编辑入口常驻）/ Agent Context 指标 / Artifacts |
| `workspace/layout/WorkspaceCommandBar.vue` | Agent Command Bar：UI 入口。**诚实设计**：命令执行通道未接入，提交时明示 Phase 6 扩展点，不伪造执行 |
| `workspace/execution/AgentExecutionTimeline.vue` | 主工作区核心：Agent 执行时间线 |
| `workspace/execution/AgentExecutionStep.vue` | 步骤行：✓ Completed / ● Running / ○ Pending / ⚠ Failed 五态 |
| `workspace/execution/ToolExecutionCard.vue` | 工具执行卡：真实求解器输入/产出，Running→Completed 两态 |
| `workspace/demo/demoWorkspace.ts` | Phase 1 演示数据。**事实边界**：stage 全部取自真实流水线枚举（`TASK_ACCEPTED…RESULT_PUBLISHING`），tool 全部取自 `lib/agent-timeline.ts` 已映射的真实工具名；数字为演示值，接入 API 后替换 |
| `apps/web/scripts/workspace-shell-screenshot.mjs` | Playwright 三视口截图脚本（视觉验收） |

### 保留（KEEP，未动一行）
- `lib/api.ts`（全部 API 客户端与类型）、`lib/planning-stream.ts`（SSE 重连）、`lib/feasibility.ts`（结果判别）、`lib/agent-timeline.ts`（回合折叠器）
- `lib/constraint-presentation.ts` / `status-presentation.ts` / `routes.ts` 等全部表现逻辑
- `app/stores/auth.ts`、`app/router` 基础设施、`composables/`、`components/ui/` 原语

### 待迁移 / 待删除（Phase 2+，本次不动）
- **MIGRATE**：`pages/TripWorkspace.vue`（约 1400 行业务状态机，所有数据流在此；后续按 API 接入顺序逐步下沉到 workspace 模块）
- **REPLACE**：`shell/WorkbenchShell.vue`、`ShellTopbar.vue`、`TripRail.vue`、`ContextRail.vue`、`TripHome.vue`（旧三区壳与卡片首页）
- **DELETE**：旧 Dashboard/卡片瀑布流表现组件（`TripDetail.vue` 拆解后按 Keep/Replace/Delete 清单执行）

## 2. Route Mapping

| Old Route | → New Route | 说明 |
| --- | --- | --- |
| `/`（redirect → trip-list） | `/`（redirect → **workspace**） | 产品默认入口变为 Agent Workspace |
| — | `/workspace`（name: `workspace`） | 新 Shell，Phase 1 演示数据 |
| `/trips`、`/trips/new`、`/trips/:id`、`/trips/:id/plan`、`/plan/new`、`/login`、`/register` | 保持不变 | 业务路由未破坏（562 个现有测试全绿） |

## 3. API Mapping（Step 2–6 接入计划）

| Existing API | → New UI Location | 接入阶段 |
| --- | --- | --- |
| `listTrips` / `searchTrips` | WorkspaceSidebar TRIP PROJECTS | Step 2 |
| `getTrip` + TripConstraints | ContextPanel（Task / Constraints / Agent Context） | Step 3 |
| `streamPlanningTaskEvents`（SSE PLANNING_PROGRESS, stage 枚举） | AgentExecutionTimeline（stage → 步骤状态） | Step 4 |
| `getPlanningTask` / PlanEvaluation / feasibility report | Artifacts + ArtifactViewer | Step 5 |
| `updateTripConstraints` / `createItineraryReplan` / `applyItineraryEdit` | CommandBar 提交 + ConstraintEditor | Step 6 |

## 4. Screenshot Verification（视觉验收）

截图位于 `apps/web/output/screenshots/`：
- `workspace-shell-desktop.png`（1440×900）：三栏 + 四区结构完整
- `workspace-shell-narrow.png`（1152×800）：Context 可折叠档
- `workspace-shell-tablet.png`（900×800）：抽屉模式（默认收起）
- `workspace-shell-tablet-drawer.png`：抽屉互斥验证（开 Context 自动关 Sidebar）

对照结论：
1. **第一眼结构**：IDE 式四区（Header / Sidebar / Agent Execution / Context / Command Bar），与旧「顶部渐变栏 + 卡片列表」完全不同 ✓
2. **产品定位**：主内容区是 Agent 执行时间线（真实阶段 + OR-Tools 工具卡），不是旅行卡片 ✓
3. **信息架构**：四区齐备 ✓
4. **真实能力**：时间线阶段一一对应 `planningProgressStages` 枚举；工具名全部来自 `TOOL_PRESENTATION` 映射表；无假 Thinking/Reasoning ✓
5. **工程闸口**：Type Check PASS / Build PASS / Vitest 55 文件 562 测试全 PASS ✓

## 5. 遗留与风险

- Command Bar 提交通道为 UI 入口（提交时明示未接入），Phase 6 接 Replan/约束编辑
- `TripWorkspace.vue` 仍承载全部业务状态；在 Step 2–6 迁移完成前旧表现组件不可物理删除
- agent-browser CLI 的 Chrome 在本机无法启动（Chrome exited early），验收截图改用项目自带 Playwright 完成
