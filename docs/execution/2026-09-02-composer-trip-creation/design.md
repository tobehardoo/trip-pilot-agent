# Design — 以 Agent Composer 为核心的旅行创建工作台

> 前置：[ui-audit.md](./ui-audit.md)。本文是 DESIGN 阶段产出；**确认前不动生产代码**。
> 原则：最小必填上下文（目的地 + 日期）+ 对话式需求补全；复用既有 API / 状态 / 组件，不建第二套约束状态。

---

## 1. 产品交互模型：三态收敛为「一个 Composer、两种模式」

| 模式 | 触发 | 中央区域 | Composer 形态 | 底部 Command Bar |
| --- | --- | --- | --- | --- |
| **创建模式** | 未选中旅行（初始页），或点击 [+ 新建旅行] | 悬浮 Composer（视觉核心）+ 其上方对话流 | `floating`（居中悬浮） | 隐藏（Composer 即入口） |
| **旅行模式** | 选中一个旅行（draft/planning/completed） | 现有 mainView（draft/planning/completed 三视图不变） | `docked`（原 Command Bar 位置） | —（被 docked Composer 取代） |

模式判定只有一条：`tripStore.currentTrip == null → 创建模式，否则旅行模式`。不新增模式开关状态。

- **初始页（任务书·状态1）**：创建模式、对话流为空。中央 = 一句引导（"开始规划一次旅行"）+ 悬浮 Composer，大量留白；旧 EmptyState 卡片删除。
- **点击 [+ 新建旅行]（状态2）**：同样是创建模式——若已在初始页则仅聚焦 Composer（无需新界面）；若正在看某个旅行则清空当前选中（`router.push('/workspace')` + 新增 store 动作 `clearCurrentTrip()`），回到创建模式。**NewTripDrawer 不再出现。**
- **创建会话进行中**：对话流渲染在 Composer 上方（max-w 同宽、随内容增长滚动），Composer 保持悬浮锚定；右侧面板进入"旅行需求摘要"态。
- **[开始规划] 成功后（任务书·状态转换）**：`adoptTrip` + URL 同步 → 旅行模式；同一个 Composer 以 docked 形态继续作为旅行 Agent 入口（不复用为第二个聊天组件）。

## 2. Composer 三层结构（`WorkspaceComposer.vue`，新建）

```text
┌──────────────────────────────────────────────────┐
│ Layer 1  Required Context（chips 行，flex-wrap）  │
│ [📍 目的地：未设置]  [📅 日期：未设置]              │
│ [📍 广州]  [📅 2026/09/10 → 09/13]  （已填态）     │
├──────────────────────────────────────────────────┤
│ Layer 2  输入区（textarea 自动增高，max-h≈200px）  │
│ 告诉我你想怎么旅行，比如：想轻松一点，多看看历史文化… │
├──────────────────────────────────────────────────┤
│ Layer 3  动作条：[重新开始]  ·  TripPilot  [开始规划][↑] │
└──────────────────────────────────────────────────┘
```

### Layer 1 — Required Context（唯一新增的 UI 本地状态）

- 形状沿用 NewTripDrawer 现有字段：`{ destination, region: {provinceCode, cityCode} | null, startDate, endDate }`。创建成功后即失效（此后事实一律派生自 `currentTrip`），**不是第二套约束状态**。
- **目的地 chip**：点击展开既有 `CitySearchInput`（行政区划索引 + region 编码 + 下拉），不重写城市搜索。
- **日期 chip**：点击展开既有原生 date 双控件（紧凑样式照搬 NewTripDrawer），`endDate >= startDate` 前端校验，倒置即内联提示"结束日期不能早于开始日期"。
- **必填规则**：只约束 **[开始规划]** 与**首次发送**（见 §4 种子语义）——未就绪时按钮禁用 + Composer 下方一行轻提示"先填写目的地和日期"，**不用 alert**。
- **对话开始后 chips 锁定**（决策点 D3）：创建对话的 trip facts 在服务端是 `source=TRIP` 锁定槽，事后改 chips 无法进入对话。锁定 chip 显示"已锁定"，动作条提供 [重新开始]（新 sessionId、清空对话流、chips 恢复可编辑）。

### Layer 2 — 自然语言输入区

- 多行 textarea；`Enter` 发送 / `Shift+Enter` 换行；占位文案："告诉我你想怎么旅行，比如：想轻松一点，多看看历史文化……"。
- 用户不填 chips 直接输入时：轻提示引导先补齐 Required Context（首条消息必须携带种子上下文，见 §4），不弹错误。

### Layer 3 — 动作条

- 左：[重新开始]（仅创建模式，重置会话）；中：`TripPilot` 标识；右：**[开始规划]**（仅当 `reply.ready === true` 时出现，主按钮）+ 发送按钮 ↑。
- **不出现**人数/预算/偏好/交通/住宿等业务字段控件。

### 两种形态

- `floating`：创建模式，居中（上下留白），`max-w-2xl`，白底 + `border-tp-line` + **一层柔和阴影**（决策点 D2，见 §9）。
- `docked`：旅行模式，替换现 `WorkspaceCommandBar` 的位置与宽度（`max-w-2xl` 居中、高约 3 行内）；Layer 1 显示为只读上下文行（目的地 · 日期，来自 `currentTrip`），Layer 3 只有标识 + 发送。

## 3. 状态与数据流（对照任务书·九：不重造约束状态）

### 3.1 新增（最小集合，仅服务创建模式）

`workspace/composer/useCreationSession.ts`：

```ts
{
  sessionId: string | null        // crypto.randomUUID()，首次发送时惰性生成
  reply: AgentDialogReply | null  // 每轮全量替换：messages + slots + ready（服务端持有真相）
  sending: boolean
  error: string | null
  send(text): Promise<void>       // 首轮：POST /api/agent/dialogue {sessionId, tripContext, message}
  sendOption(option): Promise<void> // 对话卡片点选 → {sessionId, option}
  reset(): void                   // 新 sessionId + 清 reply（[重新开始]）
}
```

对话状态机（槽位、提问顺序、ready 判定）**全部在 agent-service**；前端只投影。transcript 组件 `CreationTranscript.vue` 渲染 `reply.messages`（role/kind/options），选项点击 → `sendOption`。

### 3.2 完全复用、不重建

- `tripStore`：新增 1 个动作 `adoptTrip(trip)`（收编 Plan C 创建的 Trip：写 currentTrip/列表/last-trip localStorage——逻辑镜像现有 `createTrip` 内联段，不另起炉灶）与 `clearCurrentTrip()`。
- `useAgentWorkspace`（旅行模式对话）不动逻辑，仅两处小修：
  1. **空 tripId 守卫**：未选中旅行时不发起 SSE 循环（现状会空转失败 3 次进 `lost`）；
  2. **run 终态后刷新旅行**：`AGENT_RUN_FINISHED` / `AGENT_COMPLETED` 后 `getTrip` 重取一次，让 `currentPhase` 不刷新页面也能 draft → planning → completed 流转（现状缺失，靠 reload/约束 PUT 副作用，本设计补齐）。
- DTO：web 侧 `AgentDialogInput` 增加可选 `tripContext`（与后端既有 `DialogueRequest.trip_context` 对齐），`sendAgentCreateDialogue` 透传。

### 3.3 右侧 Context Panel 三态（重写 `WorkspaceContextPanel.vue` 内容）

| 态 | 内容 |
| --- | --- |
| 创建模式·未开始 | 极弱化：一行"描述你的旅行想法开始"（无大面积"未选择"） |
| 创建模式·对话中 | **旅行需求**：✓ 目的地 / ✓ 日期（来自 chips）；**已了解**：CONFIRMED 且非 TRIP 来源的 slots（人数、预算、节奏、偏好、必去……用既有 `agent-slots` + `constraint-presentation` 文案）；**待确认**：INFERRED 或未答 tier0（○ 必去地点）。纯投影 `reply.slots`，不是第二个表单 |
| 旅行模式 | 现有信息（目的地 · N天N晚、约束摘要、生成结果）收紧为需求摘要 + 规划状态，去掉占位噪音 |

## 4. API 接线与创建时机（任务书·十）

```text
[填 chips] → [首条消息] POST /api/agent/dialogue {sessionId, tripContext:{destination,startDate,endDate}, message}
             └─ 服务端种子 destination/dates 为 CONFIRMED(source=TRIP)，锁定不问；从 travelers/budget 开始问
             └─ tier1 建议卡可跳过；tier2 永不主动问
[对话补全]  … 每轮返回全量 messages + slots + ready
[ready]     Composer 出现 [开始规划]（对应服务端 SUMMARY："约束已确认：……"）
[开始规划]  ① POST /api/agent/trips {sessionId}  → createTripFromAgent
              服务端拉确认槽位；destination/dates 缺失 → 422 AGENT_TRIP_INCOMPLETE（服务端兜底必填）
              must_visit/住宿/到达离开 → owner-scoped 地点搜索 grounding
            ② tripStore.adoptTrip(created) + router.push(/workspace/trips/:id)
            ③ 自动发出旅行模式首条消息："开始规划这次旅行"（startAgentRun，可见于旅行对话流）
               → 进入现有 planning flow（SSE runs → planning 视图 → AGENT_COMPLETED → completed）
```

- **创建实体发生在 [开始规划]，不在填 chips 时**：不产生半成品旅行，Sidebar 在确认前不出现新条目。
- "创建旅行"（trip 实体）与"开始规划"（agent run）语义分开，且都走既有 API，后端业务语义零改动。

### 唯一后端触点（决策点 D1，需拍板）

audit §3 已确认：agent-service 的 `DialogueRequest.trip_context` 已支持种子化（Python **零改动**），但 travel-server 创建代理不透传：

- `HttpAgentDialogClient.AgentCreateDialogCommand` 增加 `TripContext tripContext` 字段并随 body 发送（~3 行）；
- `TripAgentCreateController.CreateDialogRequest` 增加可选 `destination/startDate/endDate`（或嵌套 record）并传入（~8 行）；
- 补一个 controller/client 单测。

这是**打通既有设计能力**（该字段本就是给"Java 是事实权威"准备的），不是为 UI 新造后端语义。
**若完全不允许动后端（退化方案）**：创建对话从零开始，destination/dates 由对话 wizard 主动询问（tier0），
chips 退化为"已确认槽位的镜像展示"（点击 chip = 回答当前问题）——链路可用，但任务书 §八
"系统已知广州 9/10–9/13、直接追问人数"的体验无法达成，需明确接受。

## 5. 组件变更清单

| 动作 | 文件 | 说明 |
| --- | --- | --- |
| 新建 | `workspace/composer/WorkspaceComposer.vue` | 三层结构，`variant: 'floating' \| 'docked'`，内嵌 CitySearchInput/date 控件 |
| 新建 | `workspace/composer/useCreationSession.ts` | §3.1 创建会话（唯一新增状态） |
| 新建 | `workspace/composer/CreationTranscript.vue` | 创建对话流 + 选项卡渲染 |
| 修改 | `workspace/WorkspacePage.vue` | 双模式装配；删 EmptyState 兜底与 NewTripDrawer 引用；创建会话/adoptTrip/kickoff 装配 |
| 修改 | `workspace/layout/WorkspaceContextPanel.vue` | §3.3 三态内容（壳与断点行为保留） |
| 修改 | `workspace/stores/tripStore.ts` | +`adoptTrip` / +`clearCurrentTrip` |
| 修改 | `lib/api.ts` | `AgentDialogInput` +`tripContext` 透传（对齐既有后端契约） |
| 修改 | `components/agent-workspace/useAgentWorkspace.ts` | §3.2 两处小修（守卫 + 终态刷新） |
| 修改 | `workspace/layout/WorkspaceHeader.vue` | 创建模式标题（"新旅行"）与 null phase 兜底 |
| 删除 | `workspace/layout/NewTripDrawer.vue` | 旧表单入口整体退场（§五·13：不留双入口） |
| 删除 | `workspace/layout/WorkspaceCommandBar.vue` | 被 docked Composer 吸收（单输入组件，不留两套聊天框） |
| 保留 | `WorkspaceSidebar.vue` | 零改动（`newTrip` 事件语义由页面侧改为"进入创建模式"） |
| 保留 | `Drawer.vue` / `EmptyState.vue` / `PlaceSearchInput.vue` | 通用组件，他处仍在用（ConstraintEditDrawer 等） |

## 6. 视觉与响应式

- 全部取色走 `tp-*`（DESIGN-BASELINE §3）；克制、留白、无彩色装饰、小圆角（`rounded-md` 以内）。
- 悬浮感：白底 + `border-tp-line` + **单层柔和阴影**（D2）。基线文档禁阴影——本设计申请**仅 Composer floating 形态**一处例外并写入基线；若不批准则退化为纯边框 + 背景对比（视觉浮感略弱）。
- 响应式（复用现有 1024/1280 断点逻辑）：
  - 1440 / 1280：三栏；创建模式 Context Panel ≥1280 默认展开显示需求摘要；
  - 1024–1279：Context Panel 默认收起（现状行为），可手动展开；
  - <1024（抽屉模式）：Composer 全宽（左右 16px 边距）；chips `flex-wrap`，textarea 自增高——**任何宽度不溢出**；
  - 内部 Agent 技术信息（runId、slot 内部枚举、tool 名）一律不上屏（沿用 agent-slots 现有口径）。

## 7. 测试计划（对照任务书·十六）

**单测（vitest，随实现同步写）**

- *Workspace*：无选中旅行 → `workspace-composer`（floating）可见；`未选择旅行` EmptyState 不存在；`workspace-new-trip` 点击后仍为创建模式且聚焦输入；旅行模式下 docked 形态渲染。
- *Required Context*：缺 destination / 缺任一日期 → [开始规划] 禁用 + 提示文案出现；日期倒置 → 内联提示；三者齐备 → 可继续（首条消息可发送）。
- *Conversation*：首条消息请求体含 `sessionId` + `tripContext`（destination/startDate/endDate）；后续轮次复用同一 sessionId；选项卡点击 → option 请求；`reply.messages/slots` 正确渲染；非必填约束（偏好/必去）缺失不阻塞输入。
- *Creation*：ready → [开始规划] 可见；点击 → `POST /api/agent/trips`（sessionId）→ `adoptTrip` 选中 + URL `/workspace/trips/:id` → `POST runs`（含 Idempotency-Key，kickoff 文案）→ Composer 转 docked；422 → 可读错误不跳转。
- *useCreationSession*：send/reset/sending/error 状态机；SessionChanged/ApiError 文案映射。
- *ContextPanel*：slots → 已了解/待确认分组；空态无"未选择旅行"噪音。
- *回归保护*：现有 307 用例保持绿（App.test.ts 中"workspace empty state"断言按新现实改写为 composer 断言）。

**e2e（Playwright）**

- 新增 `composer-creation.spec.ts`（mock `/api/agent/dialogue`、`/api/agent/trips`、runs/SSE，契约参考现有 mock）：初始 composer → 填 chips → 对话 → ready → 开始规划 → planning 视图 → docked composer 发消息。
- 先跑存量 e2e 记录基线（audit §4：大量 spec 指向已删路由的遗留红）；**不把存量红误判为本次回归**，也不在本任务里顺手修遗留 spec；受本次行为影响的用例（如引用 `workspace-command-bar`/NewTripDrawer 的）同步改写。

**后端（仅 D1 批准时）**：travel-server `TripAgentCreateController`/`HttpAgentDialogClient` 单测扩展（mvn test）。

## 8. 实施顺序（每步可独立验证；AUDIT→…→COMMIT 纪律）

1. **P1 壳**：`WorkspaceComposer` floating 形态 + 初始页替换 EmptyState + [+ 新建旅行] 进入创建模式（无对话）→ 单测/手验 1024–1440。
2. **P2 对话**：`useCreationSession` + `CreationTranscript` + tripContext 种子（含 D1 Java 透传与 Java 测试，若批准）+ ContextPanel 创建态摘要 → 单测 + 本地 mock e2e。
3. **P3 闭环**：[开始规划] → createTripFromAgent → adoptTrip/clearCurrentTrip → kickoff run → planning 视图 → 单测。
4. **P4 转换**：docked 形态替换 WorkspaceCommandBar；useAgentWorkspace 守卫 + 终态刷新；Header 适配 → 单测。
5. **P5 收尾**：删除 NewTripDrawer；全量 typecheck / vitest / build / e2e 对照基线；三端回归（web mock e2e + 后端测试仅涉 Java 触点）；`docs/execution/2026-09-02-composer-trip-creation/` 收尾报告 + commit。

## 9. 需要确认的决策点

| # | 决策 | 建议 |
| --- | --- | --- |
| D1 | Java 透传 `tripContext`（唯一后端触点，~15 行 + 测试）；否则对话需重问目的地/日期 | **批准**（打通既有能力，任务书 §八的体验依赖它） |
| D2 | floating Composer 使用单层柔和阴影（基线"禁阴影"的例外） | **批准**（悬浮感的主要来源；不批则纯边框方案） |
| D3 | 对话开始后 Required Context chips 锁定，[重新开始] 换会话 | 批准（符合"trip facts 服务端锁定"语义） |
| D4 | [开始规划] 成功后自动发 kickoff 消息（"开始规划这次旅行"，可见于旅行对话流） | 批准（Step 5 无缝进入 planning flow） |

## 10. 验收标准映射（任务书·十九）

- **A 初始 Workspace**：§1 创建模式空态 = 悬浮 Composer 居中、EmptyState 删除 → 单测 + 视觉核验。
- **B 创建旅行**：无 Drawer；chips 三字段必填、其余无表单 → §2/§7 测试。
- **C Agent**：自然语言 + 服务端逐步追问 + slots 投影 → §4/§7。
- **D 创建完成**：ready → [开始规划] → 现有 planning flow；Composer 转 docked 继续可用 → §4/§7。
- **E 架构**：单入口（Drawer 删除）、无平行约束状态（新增仅 sessionId/reply/chips 投影）、复用 Plan C API → §3/§5。
- **F 工程质量**：typecheck / vitest / build / 回归证据落盘 execution 目录；工作树干净（文档与代码同 commit）。
