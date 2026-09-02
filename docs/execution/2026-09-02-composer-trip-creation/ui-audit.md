# UI Audit — 创建旅行 / Workspace Composer 交互重构

> 任务：把 TripPilot 的创建旅行过程重构成"以 Composer 为核心的 Agent 交互流程"。
> 本文是 AUDIT 阶段产出，只陈述现状，不改生产代码。
> 基线证据：`vue-tsc -b` 通过；vitest 29 个文件 / 307 用例全绿（2026-09-02）。

---

## 1. 当前"新建旅行"完整 UI 调用链

```
WorkspaceSidebar.vue  [+ 新建旅行]  (testid: workspace-new-trip)
  └─ emit('newTrip')
      └─ WorkspacePage.vue  @new-trip="newTripOpen = true"
          └─ <NewTripDrawer :open="newTripOpen">  （右侧 Drawer，Teleport 到 body）
              ├─ CitySearchInput   目的地（行政区划索引，emit region 编码）
              ├─ <input type="date"> ×2   开始/结束日期
              ├─ 人数 stepper / 预算输入 / 偏好标签多选 / PlaceSearchInput 必去地点
              └─ submit → emit('created', CreateTripInput)
                  └─ WorkspacePage.handleTripCreated(input)
                      └─ tripStore.createTrip(input)  → POST /api/trips
                          ├─ trips 列表头插 + 选中 currentTrip
                          └─ router.push(`/workspace/trips/${created.id}`)
                              └─ mainView = currentPhase（新建后 = 'draft'）→ TripDraftView
```

结论：这是一个**单次提交式表单**——创建瞬间把 destination/dates/人数/预算/偏好/必去地点一次性填满约束，
创建后进入 draft 视图（TripDraftView："还没有开始规划" + "继续完善旅行" 按钮 → ConstraintEditDrawer）。

## 2. 逐项审查结论（任务书 AUDIT 问题清单）

### 2.1 哪些组件可以复用

| 组件 | 位置 | 复用方式 |
| --- | --- | --- |
| `CitySearchInput.vue` | `workspace/lib/` | Layer 1 目的地 chip：直接复用（行政区划索引 + region 编码 + 下拉），不重新实现城市搜索 |
| 原生 `<input type="date">`（NewTripDrawer 内联样式） | `NewTripDrawer.vue` | Layer 1 日期 chip：抽出同样的紧凑样式复用；结束 ≥ 开始校验逻辑照搬 |
| `WorkspaceSidebar.vue` | `workspace/layout/` | 原样保留；只改 `newTrip` 事件的语义（开 Composer 模式而非开 Drawer） |
| `WorkspaceHeader.vue` / 三栏壳 / 抽屉响应式逻辑 | `WorkspacePage.vue` | 原样保留（1024/1280 断点逻辑现成） |
| `useAgentWorkspace.ts` | `components/agent-workspace/` | **旅行创建后**的对话引擎原样保留：send/answer/SSE 重放/turns reducer/slots 全部现成 |
| `AgentDialog.vue` / `AgentExecutionTimeline.vue` | `workspace/execution/` | planning 阶段的对话/时间线渲染原样保留 |
| `agent-slots.ts`（slotTone/slotStateLabel）+ `constraint-presentation.ts` | `lib/` | 右侧面板"已了解/待确认"摘要的文案与口径直接复用 |
| `present.ts`（formatChinaDate 等）、`trip-title.ts` | `workspace/lib/`、`lib/` | 日期/金额呈现、自动命名口径复用 |
| `tripStore.ts` | `workspace/stores/` | 唯一数据源，保留；只**新增一个** `adoptTrip(trip)` 动作（收编 Plan C 已创建的 Trip，内部复用现有 currentTrip 同步逻辑，不建新 store） |
| `sendAgentCreateDialogue` / `createTripFromAgent` | `lib/api.ts:904-921` | **已导出但从未被现有 UI 调用（死代码）**——Plan C 创建对话 API 两端（Python/Java）均已实现，这正是本次要接线的通道 |

### 2.2 哪些组件应该删除

| 组件 | 理由 |
| --- | --- |
| `NewTripDrawer.vue`（298 行） | 唯一职责就是旧表单创建；被 Composer 取代后必须整体退出生产路径（禁止双入口） |
| `WorkspacePage.vue` 中的兜底 EmptyState（"未选择旅行 / 从左侧选择…"） | 中央区域改为悬浮 Composer，占位卡片删除 |
| `WorkspaceCommandBar.vue`（55 行，纯单行输入框） | 被 `WorkspaceComposer` 的 docked 形态吸收（同一个组件、两种形态），避免两套聊天输入 |

`Drawer.vue`、`EmptyState.vue` 本身是通用 UI 组件（ConstraintEditDrawer 等仍在用），不删。

### 2.3 哪些只是"内容/样式问题"

- `WorkspaceContextPanel.vue`：结构（右侧 aside、区块分隔）可用，内容全部重写——
  现在满屏"未选择旅行/未选择/— "占位（`agentStateLabel`、`tripInfoRows` 空态），改为三态：
  未选择（极弱化）/ 创建中（需求摘要：来自对话 slots）/ 已进入旅行（来自 trip constraints + 规划状态）。
- `WorkspaceHeader.vue`：`taskTitle` 兜底文案 `'未选择旅行'` 需在创建模式显示对应标题（如"新旅行"），其余保留。

### 2.4 哪些状态已存在，禁止重建

- **会话/认证**：`workspace/session.ts`（restoring/guest/authenticated 三态 + 401 单飞刷新）。
- **旅行数据**：tripStore（trips/currentTrip/creating/itinerary/versions/…），`currentPhase` 由 `Trip.status` 推导（draft/planning/completed）。
- **旅行态 Agent 对话**：`useAgentWorkspace`（SSE 事件流 + turn reducer + 约束回写 applyCompleted + 乐观锁）。
- **创建期对话状态**：**在后端**（agent-service `dialog/store.py`，按 `create:{sessionId}` 持久化，每轮回传全量 transcript + slots + ready）。前端只需要持有 sessionId 与最新响应，**不需要也不应该**在前端复制一份 slot 状态机。
- **DTO**：`Trip` / `TripConstraints` / `CreateTripInput` / `UpdateTripConstraintsInput` / `AgentDialogReply`（api.ts）。

唯一允许新增的前端状态：Composer 的 **Required Context**（destination 名称 + region 编码 + startDate + endDate）——
这是任务书第五节明确要求的 composer 顶部上下文，形状与 NewTripDrawer 现有 `form.destination/startDate/endDate/destinationRegion` 完全一致，
创建完成后立即失效（改由 `currentTrip` 派生），不是第二套约束状态。

### 2.5 创建旅行 API 现在需要哪些字段

**经典路径 `POST /api/trips`（`createTrip`）** — `CreateTripInput`：
- `destination`（必填）、`arrivalAt`/`departureAt`（必填，YYYY-MM-DD）
- `title?`（空则后端按「目的地 + 日期跨度」自动生成）、`region?`（RegionRef 行政区编码，CitySearchInput 提供）
- `constraints`（人数/预算/travelerType/pace/preferences/fixedSchedules/到达离开锚点/住宿锚点/必去与避开地点 refs/餐窗/无障碍）

**Plan C 路径（创建期对话）** — `POST /api/agent/dialogue`（`sendAgentCreateDialogue`，sessionId 键控）
与 `POST /api/agent/trips`（`createTripFromAgent`）：
- 前端只需 sessionId（crypto.randomUUID 客户端生成）+ 对话轮次（message/option/reset）。
- 创建时服务端拉取已确认槽位，**destination/start_date/end_date 任一缺失 → 422 `AGENT_TRIP_INCOMPLETE`**（服务端兜底 Required Context）。
- must-visit/住宿/到达离开由服务端经 owner-scoped 地点搜索落成 PlaceRef；人数默认 2、pace 默认 BALANCED。
- 最终走与表单完全相同的 `TripService.create` 落库路径（业务语义不变）。

### 2.6 destination / startDate / endDate 如何进入现有数据模型

- 经典路径：表单字段直接进 `Trip` 实体列（destination/startDate/endDate）+ `RegionRef`。
- Plan C：对话槽位 `destination` / `start_date` / `end_date` CONFIRMED 后，由
  `TripAgentCreateController.createTrip`（travel-server）映射为同一 `CreateTripRequest`。
- 对话模式（trip-mode）中，这两个事实由 Java 注入 `tripContext`，agent-service 以
  `source=TRIP, state=CONFIRMED` 种子化并**锁定不可在对话中修改**（`service.py:_locked`）——
  即"目的地/日期是事实，不是聊天可改的约束"，与产品原则一致。

### 2.7 Agent 对话目前如何保存上下文

- **旅行态**：对话状态在 travel-server/agent-service（runs + 事件表 + outbox）；前端 `useAgentWorkspace` 仅持有
  turns 投影 + lastMessageId（SSE 重放）。约束回写走 `PUT /api/trips/{id}/constraints`（乐观锁 version）。
- **创建态（Plan C）**：状态在 agent-service dialog store（session 键控），每轮回传**全量**
  `messages` + `slots` + `ready`；slots 含 `state`（UNKNOWN/INFERRED/CONFIRMED）与 `source`
  （TRIP/USER_EXPLICIT/USER_CONFIRMED/LLM_INFERRED）。ready 判定 = tier0+tier1 全部问过、无 pending、
  无 INFERRED 残留——即"Agent 判断信息已经足够"的服务端信号，**已经存在，无需前端重造**。

### 2.8 当前 Composer 是否已可复用

`WorkspaceCommandBar.vue` 只是 55 行的单行 input（placeholder "继续告诉 TripPilot 你想如何调整旅行…"），
没有上下文区、没有多行输入、没有动作区——只能作为"docked 形态的坯子"，
需要新建一个统一的 `WorkspaceComposer`（Layer1 上下文 chips + Layer2 输入 + Layer3 动作条，
floating/docked 两种形态），内部复用 CitySearchInput 与日期控件。**不存在可直接套用的现成 Composer 组件。**

### 2.9 创建旅行后如何进入现有 planning flow

现状：新建 → draft（TripDraftView）→ 用户在底部 CommandBar 发第一条消息 →
`startAgentRun`（POST runs，outbox 排队）→ SSE 事件流 → trip status 由后端流转 →
`mainView='planning'`（TripOverview + 路线图 + AgentDialog）→ `AGENT_COMPLETED` →
applyCompleted 回写约束 → completed 视图（ItineraryWorkspace）。

新模型沿用同一条链，只是"第一条消息"由 [开始规划] 动作在创建成功后自动发出（见设计文档 §6）。

## 3. 关键架构发现：Plan C（trip-less 创建对话）已全线存在，仅 UI 未接线

这是本次审计最重要的结论：

1. **agent-service（Python，完成）**：`dialog/service.py` 实现了 understand→confirm→ready 闭环：
   - 槽位声明式定义（tier0 必问：destination/dates/travelers/budget；tier1 建议卡可跳过：pace/住宿/到达离开/必去；tier2 永不主动问）；
   - 自由文本多槽扫描（"想去广州玩几天，预算3000，2个人"→ 提案 + 确认卡）；
   - `DialogueRequest.trip_context` 支持外部注入 destination/startDate/endDate，种子为 `CONFIRMED/source=TRIP` 并锁定；
   - `ready` + SUMMARY 消息（"约束已确认：……点击「创建行程并开始规划」继续"）——服务端已经在说产品语言。
2. **travel-server（Java，基本完成）**：`/api/agent/dialogue` 代理（`TripAgentCreateController`）+
   `/api/agent/trips`（服务端拉确认槽位 → 地点 grounding → `TripService.create`）。
   **唯一缺口：创建模式代理 `AgentCreateDialogCommand` 不透传 `tripContext`**（record 只有 sessionId/message/option/reset），
   因此 Composer Layer 1 填好的目的地/日期目前无法种进创建对话——对话会从"想去哪个城市？"重新问起。
3. **web（死代码）**：`sendAgentCreateDialogue` / `createTripFromAgent` 已导出但无调用方；
   e2e `agent-workspace.spec.ts` 仍残留对 `/api/agent/dialogue`、`/api/agent/trips` 的 mock（createTrip:true 分支）
   与旧路由（`/plan/new`、`planning-session` 等 testid），证明该链路曾有 UI、在 F-UI-1~5 收敛成 Workspace 壳时被拆掉。
4. **治理含义**：采用 Plan C 不是"新增后端能力"，而是把既有半成品通道接到产品入口；
   符合任务书第九条"如果现有 UI 只是没有暴露：优先修改 UI → 现有状态"。

## 4. 现有测试盘点

- 单测（vitest，307 用例全绿）：tripStore（createTrip/listTrips/日期命名）、workspace-session、App 壳
  （含"logs in and shows the workspace empty state"——**该用例断言将被本次重构改变**）、
  constraint-presentation、agent-timeline/slots、api 等。
- e2e（Playwright）：7 个 spec。其中大量 spec 指向**已移除的路由**（`/trips`、`/trips/:id`、`/plan/new`、`/login`——
  现路由只有 `/workspace`、`/workspace/trips/:tripId`、`/share/:token`），属遗留资产；
  CI 仅排除 qa-real-chain。**实施前先跑一遍 e2e 基线记录哪些本来就红，避免把存量红误判为回归。**
- 后端测试不在本次 UI 重构范围（除非 tripContext 透传需要补 Java 侧测试，见设计文档 §8）。

## 5. 风险与注意点（给设计阶段输入）

1. **`useAgentWorkspace` 无"未选中旅行"守卫**：页面挂载即开 SSE（tripId 为空串时反复失败 3 次 → `connection='lost'`）。
   Composer 重构时需要让 docked 形态仅在选中旅行后启用，避免空跑。
2. **创建对话 transcript 与旅行态 runs 的 transcript 是两套存储**（create:{sessionId} vs trip 事件表），
   创建完成进入旅行后历史不会自动迁移——进入旅行后的可见上下文 = trip 实体约束 + 右侧摘要，设计里要如实呈现。
3. **PlaceSearchInput 在创建路径中的位置**：Plan C 的必去地点由对话收集、服务端 grounding；
   表单式 PlaceSearchInput 只剩 ConstraintEditDrawer 在用，创建流程不再使用（组件保留）。
4. **自动命名**：Plan C 服务端标题为「目的地 · AI 行程」，与经典路径的「上海三日旅行」口径不同——保持现状（后端语义不动）。
5. **pnpm 全局 shim 在本机损坏**（`Cannot find module .../pnpm.cjs`），验证一律用
   `node node_modules/<tool>` 直跑；e2e 需要时用 `node node_modules/@playwright/test/cli.js`。
