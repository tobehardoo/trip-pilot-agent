# TripPilot Agent UX 3.0 — Travel Planning Session 重构方案（评审稿）

- 状态：**已批准实施（2026-08-30）— P1–P7 全部落地（P3 约束板为降级模式，AGENT_SLOTS 契约未实施）**
- 日期：2026-08-30
- 前置：[Agent UX 2.0 重构方案](agent-ux-2.0-redesign-plan.md)（已实施并发布，镜像标签 `agent-ux-2.0`）
- 审计方法：本方案所有断言基于当前工作树代码逐条核验（file:line 可溯），事件矩阵经真实栈冒烟与 MQ 探针确认，未采纳提示词中任何未经代码证实的假设（含提示词自身的两处不准确，见 §3.3）

---

## 1. Executive Summary

**当前最大问题：产品的主对象仍然是"对话框"，而不是"一次旅行规划任务"。** 2.0 已把行程内对话从气泡流升级为事件驱动的工作台，但产品入口与创建链路仍是两个聊天抽屉（创建模式抽屉至今保留"你好！我是行程规划助手"逐句确认式交互，`dialog/service.py:537`），行程内工作台又把对话列作为视觉主体、把任务状态压成侧栏。3.0 的答案是：**把"规划会话（Planning Session）"确立为一等产品对象和一等路由页**——对话降级为会话的输入手段之一，约束板、执行态、结果成为会话的常驻内容。

---

## 2. Current Product Audit（当前产品真实状态）

### 2.1 两条 Agent 链路 + 一个确定性管线（现状拓扑）

| 通道 | 运行时 | 传输 | 前端载体 | 2.0 后状态 |
|---|---|---|---|---|
| 创建模式 | HTTP 槽位向导（`dialog/`，Redis 存 7 天） | 同步 HTTP 全量转录（`POST /api/agent/dialogue`） | `AgentDialogPanel.vue`（TripDashboard「AI 帮我规划」入口抽屉） | **未迁移**，仍是逐句确认式聊天抽屉 |
| 行程内 | LangGraph 有界循环（`agent/graph.py`）+ worker（`worker/agent_processor.py`） | Outbox → MQ → 事件落库 → SSE | `AgentWorkspace.vue`（TripDetail 头部「AI 助手」按钮抽屉，max-w-3xl） | 已工作台化，但载体仍是抽屉 |
| 确定性规划管线 | `worker/processor.py`（OR-Tools 内核 + Hard Validation + 评估） | 独立 SSE（`/api/planning-tasks/{id}/events`，12 阶段） | `PlanningProgress.vue` + TripDetail 规划条 | 与 Agent 工作台**完全分离**，两套进度心智 |

### 2.2 关键代码事实（逐条核验）

1. **死路由**：`/trips/:tripId/plan`、`/trips/new`、`/trips/:tripId/versions` 三个路由存在（`router/index.ts:24-27`），TripWorkspace 也为它们加载数据（`TripWorkspace.vue:94`），但模板只有 `trip-list` 和 `trip-detail` 两个渲染分支（`TripWorkspace.vue:1303,1323`）——**三个路由今天都落入 404 分支（:1372）**。会话页的地基已经预留。
2. **创建抽屉即提示词截图中的"Chatbot"**：问候语硬编码在 Python 向导（`dialog/service.py:537`"你好！我是行程规划助手。可以直接告诉我你的需求，我会逐项和你确认。"），前端按消息列表渲染全量转录，选项点击后走 `CardOption{SET/CONFIRM/EDIT/SKIP/ASK}`；无步骤、无时间线、无 SSE。
3. **行程内工作台（2.0 产物）组件清单核验**：`agent-workspace/` 下 StageBar / ClarificationCard / CompletedCard / ConstraintPanel / ErrorRecoveryCard / AgentWorkspace / useAgentWorkspace 全部在位；e2e `agent-workspace.spec.ts` 覆盖 3 场景；单测 28 用例。
4. **记忆（user_travel_profile）真实产品面 = 零**：PG 表 + `PENDING/CONFIRMED/REVOKED` 状态机（`agent/profile.py`）存在；仅在 MQ run 内加载进 `state.confirmed_preferences`（`agent_processor.py:209,288`）并注入 LLM 决策 prompt（`graph.py:336`）；写入口只有 run 内的 `update_preferences` 工具。**无任何 HTTP API、无 Java 代理、无 UI**；创建向导完全不用它。产品上用户无法知道记忆存在，也无法确认/修改/撤回（除 run 内被动的工具确认）。
5. **状态管理**：仅 auth 一个 Pinia store；TripWorkspace 1395 行 prop-drilling（~45 props 传 TripDetail）；Agent 工作台状态在 `useAgentWorkspace` 组合式函数内（组件级，非全局）。
6. **结果展示在别处**：行程结果的主场是 TripDetail（地图/逐日时间线/版本/评估/导出/分享）。工作台的 CompletedCard 只有摘要 + "应用约束" CTA——**"规划完成"与"看到计划"之间断开**。

### 2.3 真实事件矩阵（不允许猜，逐项核验）

| Event | Producer | Java 消费 | 持久化 | SSE | Web 呈现 | 状态 |
|---|---|---|---|---|---|---|
| `AGENT_STEP` | Python checkpoint sink，每工具观测一条（`ask_user` 排除；回合内 seq 从 0） | `AgentDialogEventListener` → parser → handler | `business.agent_dialog_message` | `agent.dialog.event.queue` → `AgentDialogEventHub`（per-trip，Last-Event-ID 重放，30min 超时无心跳） | TurnTimeline 步骤行（业务语言映射） | ✅ 在线（dev/prod 双栈冒烟验证） |
| `AGENT_ASK_USER` | Python `_publish_question`（stop_reason==WAITING_USER） | 同上 | 同上 | 同上 | ClarificationCard + 等待横幅 + runId 捕获 | ✅ 在线 |
| `AGENT_COMPLETED` | Python `_publish_completion`（stop_reason==EMITTED） | 同上 | 同上 | 同上 | CompletedCard + 约束区全量投影 + apply CTA | ✅ 在线 |
| `AGENT_RUN_FINISHED` | Python 终态兜底 + resume 拒绝（先发事件后进死信） | 同上（v1 契约 + fixture） | 同上 | 同上 | ErrorRecoveryCard / 答复气泡 | ✅ 在线（绑定在 dev/prod 两 broker 核实） |
| `AGENT_SLOTS` | — | — | — | — | — | ❌ **未实现**（2.0 §10.2 评审项被搁置）：约束区只能在 COMPLETED 后填充 |
| `PLANNING_PROGRESS/COMPLETED/REVIEW_REQUIRED/FAILED` | 确定性管线 | `PlanningTaskEventHub`（独立 SSE） | `planning_task_event` | per-task | `PlanningProgress.vue`（TripDetail 内） | ✅ 在线，与 Agent 链路互不相通 |

**其他运行时事实**：202 响应不含 runId（Python 消费时生成）；无 run 状态 REST API、无 run 列表 API——**SSE 重放是会话恢复的唯一通道**（已持久化，重放完整）；等待 TTL 7 天、陈旧 RUNNING 600s 恢复、command_event_id 幂等。

### 3. Runtime → UX Gap（Runtime 已有 / UI 未表达）

| Agent Runtime 能力 | 当前 UI 表达 | Gap 判定 |
|---|---|---|
| 有界 run、多回合会话（多 run 组成一次对话） | 单抽屉内连续时间线 | **"会话"无身份**：无 URL、无命名、无历史回合结构，关闭即失去任务上下文（重开靠重放拼回） |
| 澄清契约（expectedType 4 类） | 澄清卡已结构化 | 基本闭合；剩余见 §13 |
| research/planning/validation 步骤流 | 时间线业务语言映射 | 表达良好；但**与确定性管线的 12 阶段是两套视觉语言**，用户在"Agent 规划"与"生成行程"之间感到断裂 |
| WAITING_USER + checkpoint/resume（7 天） | 等待横幅 + 卡片锁定 | 表达了"在等你"；未表达"这个任务在你离开后仍然活着，随时可回来"——因为没有会话身份（URL/入口） |
| `user_travel_profile` 记忆 | 无任何表达 | Gap = 0 表达 + 0 控制权（§21 给出克制方案） |
| 确定性管线（12 阶段 + review + replan + 版本） | TripDetail 内独立进度条 | Agent 完成后"应用约束 → 生成行程"跳出生工作台，进度与结果分离 |
| 槽位五态 + 来源 | COMPLETED 后投影 | **无实时性**（AGENT_SLOTS 未实现，2.0 遗留 P1） |
| 终态事件族 | 错误恢复卡 | 表达闭合（2.0 完成） |

### 3.3 对提示词的两处纠正（以代码为准）

1. `AGENT_RUN_FINISHED` **不覆盖"正常完成"**——正常完成由 `AGENT_COMPLETED` 承载（含行程+槽位）；RUN_FINISHED 只覆盖无问题、无行程的终态（STOPPED/FAILED/EXPIRED/ANSWERED）。
2. "完整终态事件"现已真实存在，但**"Resume 被拒"仅对走 MQ 的行程内通道成立**；创建模式（HTTP 向导）无 run 概念，其错误面是 HTTP 状态码映射（2.0 已做 code→文案）。

---

## 4. Product Repositioning（产品再定位）

### 4.1 候选形态逐一裁决（基于真实能力，不做技术堆砌）

| 候选 | 裁决 | 理由 |
|---|---|---|
| AI Chatbot | ✗ | 正是 2.0 要走出来的形态；对话只是输入手段 |
| AI Form | ✗ | 向导式逐项确认是创建模式现状，恰是"最像 Chatbot"的根源的另一面——把任务拆成表单同样丢掉 Agent 的自主推进 |
| AI Travel Assistant | △ | 定性正确但无产品结构约束力，"助手"仍默认聊天载体 |
| Autonomous Travel Planner | ✗ | Runtime 是**有界 run + 人机协同**（clarification 一票悬停、validation 一票否决、apply 需用户 CTA），自治叙事与真实能力不符，会制造信任落差 |
| Agent Workspace | △ | 2.0 形态；"工作台"描述了界面密度但没回答"产品的单位是什么" |
| Conversational Planning Workspace | △ | 同上，且"Conversational"仍把对话放在定语位置 |

### 4.2 最终定位：**Travel Planning Session——AI 旅行规划会话**

> **TripPilot 是一个"会话制"旅行规划产品：每个会话是一次有身份、有状态、可恢复、可交付的旅行规划任务。用户提出目标，Agent 理解、追问、查证、规划、验证；用户在决策点介入；会话的产出是一份可执行的行程。**

"会话"作为产品对象的资格全部来自已验证的运行时能力：run 有 id、状态可持久化（7 天等待 TTL + checkpoint）、事件可重放（`agent_dialog_message`）、终态可感知（RUN_FINISHED 族）、产出可交付（itinerary wire + 版本库）。**这不是新命名，而是把已经存在的运行时事实提升为产品事实**——今天这些能力散落在抽屉里，用户永远看不到"这是一个任务"。

一次 Session 的定义（贯穿全文的模型）：

```text
Session = Goal（一句话/几次澄清）
        × SharedBoard（旅行约束：五态槽位投影）
        × AgentWork（有界 run 序列：理解→查证→规划→验证）
        × DecisionPoints（澄清/确认/应用）
        × Deliverable（行程草案 → 确定性管线 → 正式行程版本）
        × Lifecycle（START→…→COMPLETED；FAILED/EXPIRED 可恢复）
```

---

## 5. Information Architecture（信息架构）

### 5.1 入口与会话身份

```text
Trip Dashboard
 ├─ [主入口] 「开始规划」→ 创建会话页  /plan/new        （替代创建抽屉）
 │     └─ 会话完成 → 创建 trip（既有 /api/agent/trips）→ 跳 /trips/{id}/plan（同页承接管线进度）
 ├─ [次入口] 「手动创建」→ /trips/new（把死路由接到 TripDashboard 既有创建表单，替代抽屉内的兜底链接）
 └─ 行程卡/行程页「AI 规划」→ /trips/{id}/plan           （替代行程内抽屉）
```

- `/trips/{id}/plan`：**启用既有死路由**作为行程内规划会话页（RouteMarker 模式下在 TripWorkspace 增加 `trip-plan` 渲染分支）。
- `/plan/new`：创建会话页（无 tripId 阶段；会话 key 用客户端 sessionId，与向导存储键 `create:{sessionId}` 对齐，可收藏、可刷新恢复）。
- 会话 URL 可直达 = WAITING_USER 恢复体验的产品化：离开 7 天内回来，打开同一 URL，SSE 重放把任务原样摆回桌面。

### 5.2 会话页内结构（渐进式披露，非并置全量）

```text
┌────────────────────────────────────────────────────────────┐
│ SessionHeader：目标句 + 生命周期阶段 + [重新开始] [关闭]      │
├──────────────────────────────────────────────┬─────────────┤
│                                              │ SharedBoard │
│   WorkArea（随阶段变体重量的主区）             │ 旅行约束板   │
│   START→目标画布  CLARIFYING→决策点           │ （常驻右栏） │
│   EXECUTING→执行流  COMPLETED→结果面板        │ 桌面 ≥lg 常驻 │
│                                              │ 移动端折叠条  │
├──────────────────────────────────────────────┴─────────────┤
│ Composer：对话输入 + 快捷选项（会话始终可说话/可点选）         │
└────────────────────────────────────────────────────────────┘
```

对话、约束、执行、结果的**关系裁决**（提示词 §六的正面回答）：

| 内容 | 角色 | 呈现策略 |
|---|---|---|
| 结果（行程） | 用户的最终关注点 | COMPLETED 后成为 WorkArea 主体；会话全程在 Header 阶段条预告"会得到什么" |
| 约束板 | 共享工作对象（用户与 Agent 的共同事实） | 常驻右栏（桌面）/折叠摘要条（移动）；COLLECTING 起可见并随事件生长 |
| 执行流 | 过程可见性 | EXECUTING 阶段的 WorkArea 主体；完成后折叠为"执行摘要"（可展开审计），不与结果抢空间 |
| 对话 | 输入与解释通道 | Composer 常驻底部；消息流在 START/CLARIFYING 是主区，EXECUTING 降为执行流内的"用户输入时间线"节点，COMPLETED 收进"调整需求" |

**一切随阶段变，没有永远并置的全量组件**（落实 §十九）。

---

## 6. User Journey（从 Start 到 Completed）

| 阶段 | 用户看到 | 用户能做 | 真实信号 |
|---|---|---|---|
| START | 目标画布：一句话输入 + 3 个真实能力示例 + "会得到什么"说明 | 输入自然语言 / 点示例 / 转手动表单 | 无 run、无事件 |
| UNDERSTANDING | 约束板开始生长 + "正在理解你的需求" | 等待（≤90s 兜底） | 202 QUEUED → 首个 STEP |
| COLLECTING | 约束板 ✓/≈/？ 分布 | 继续补充发言 | `AGENT_STEP(update_constraints…)` |
| CLARIFYING | 决策点卡（问题=当前唯一焦点）+ 等待语义 | 结构化应答 / 自由文本 / 暂不确定 | `AGENT_ASK_USER` |
| RESEARCHING | 执行流："查证旅行信息"分组下真实子步 | 观察/等待 | `AGENT_STEP(retrieve/search/route/hours)` |
| PLANNING | 执行流："生成行程方案" | 等待 | `AGENT_STEP(build_itinerary)` |
| VALIDATING | 执行流："验证行程方案"（含失败→继续调整语义） | 等待 | `AGENT_STEP(validate_itinerary)` |
| COMPLETED（Agent） | 结果面板：行程摘要 + 约束满足度 + [应用并生成正式行程] | 应用 / 调整需求 / 重新开始 | `AGENT_COMPLETED` |
| PIPELINE（确定性） | 会话内嵌 12 阶段进度 + review 分流 | 取消 / 放弃候选 / 去完善 | `PLANNING_PROGRESS → COMPLETED/REVIEW_REQUIRED` |
| DONE | 结果面板切换为"查看完整行程"（跳 TripDetail 对应锚点）+ 会话归档态 | 查看/调整/重新规划/分享导出 | 行程版本就绪 |
| WAITING_USER 跨会话 | 用户离开→回来打开同一 URL：任务原样恢复 | 继续应答或重新开始 | SSE 重放（7 天 TTL） |
| FAILED/EXPIRED/LIMIT | 恢复卡（原因用户语言 + 动作） | 重试/重开 | `AGENT_RUN_FINISHED` |

---

## 7. Agent Lifecycle → UX State Mapping

四层映射（Backend → Runtime → Product → UI Mode → Components）。产品状态名刻意用任务语言，不照搬内部枚举：

| Backend 信号 | Runtime 状态 | Product State | UI Mode | 主要组件 |
|---|---|---|---|---|
| 无 run & 重放为空 | — | `Draft`（目标未定） | Start Canvas | GoalCanvas, ExamplesRow, Composer |
| 202 QUEUED 无事件 | run=RUNNING（PG） | `TakingShape` | Understanding | ConstraintBoard(骨架), RunningPulse |
| `AGENT_STEP(UNDERSTANDING 组)` | run=RUNNING | `TakingShape` | Collecting | ConstraintBoard, TurnTimeline |
| `AGENT_ASK_USER` 未应答 | run=WAITING_USER | `NeedsYou` | Clarifying | DecisionCard, WaitingBanner |
| `AGENT_STEP(RESEARCH 组)` | run=RUNNING | `Working` | Researching | ExecutionLane(查证组) |
| `AGENT_STEP(build_itinerary)` | run=RUNNING | `Working` | Planning | ExecutionLane(方案组) |
| `AGENT_STEP(validate_itinerary)` | run=RUNNING | `Working` | Validating | ExecutionLane(验证组) |
| `AGENT_COMPLETED` | run=COMPLETED | `Draft Ready` | Result(Agent) | ResultPanel, ApplyCTA |
| `AGENT_RUN_FINISHED(STOPPED/FAILED)` | run=STOPPED/FAILED | `Stalled` | Recovery | RecoveryCard |
| `AGENT_RUN_FINISHED(EXPIRED)` | run=EXPIRED | `Dormant→Stalled` | Recovery | RecoveryCard(重新开始) |
| `AGENT_RUN_FINISHED(ANSWERED)` | run=COMPLETED | `Draft`（可续话） | Conversational | AnswerBubble |
| PUT constraints + POST planning-tasks | planning_task=QUEUED/RUNNING | `Building` | Pipeline | PipelineProgress(内嵌 12 阶段精简版) |
| `PLANNING_REVIEW_REQUIRED` | planning_task=WAITING_USER | `NeedsYou` | Review | ReviewCard（复用 PlanningReviewPanel 语义） |
| `PLANNING_COMPLETED` | planning_task=SUCCEEDED | `Delivered` | Result(Final) | ResultPanel(交付态) + 去行程页 |
| SSE 断连×3 | — | `Disconnected` | Recovery | ReconnectBanner |

派生规则沿用 2.0 已验证的实现（`deriveStage`，真实事件驱动、无事件无阶段、90s STARTING 兜底、事件在途输入锁），扩展点仅为新增的 Pipeline/Result(Final) 两态。

---

## 8. Start Experience（首屏）

**现状证据**：创建抽屉问候语 + "想去哪个城市？"（向导 tier-0 必问槽位）——先问再懂，任务感为零。

**设计**（3 秒内回答四件事）：

1. **这是干什么的**：标题区一句话"把你的旅行想法，变成一份验证过、可执行的行程"，副行标注真实边界："理解需求 → 查证信息 → 规划并验证 → 生成每日行程"（即阶段条预告，非能力夸口）。
2. **我应该做什么**：单一主输入（大输入框 + 发送），placeholder 用任务语言："例如：国庆去成都四天，两个人，预算 6000，轻松一点，必去熊猫基地"。
3. **Agent 会帮我完成什么 / 最终得到什么**：三个示例卡 = 三种真实可完成的任务剖面（直接绑定向导/循环已验证的槽位面）：
   - 「周末短途：城市 + 两天 + 轻松」→ 演示最短闭环
   - 「假期深度游：多约束 + 必去清单」→ 演示约束收集 + 澄清
   - 「按预算规划：预算 + 人数 + 节奏」→ 演示预算约束投影
   点击示例只**预填输入框**（不自动发送），用户保持发起权。
4. **不做**：能力清单罗列、AI 说明文、注册引导、以及任何"你好我是助手"的自我介绍（删除向导问候语的产品暴露，前端 START 画布不渲染该消息——后端消息保留，由前端按 `kind/role` 过滤，零契约改动）。

行程内入口的 START 变体：`/trips/{id}/plan` 已有 trip 事实（目的地/日期来自 trip），START 画布预填已知约束并标注来源"来自行程"，用户只补差异。

---

## 9. Constraint Experience（约束体验）

- **载体**：SharedBoard（会话页常驻右栏，`ConstraintPanel` 升级版）。选择"常驻右栏"而非"阶段性卡片/浮层"的依据：约束是**用户与 Agent 的共同事实基座**，澄清卡、结果面板、调整需求都引用它；它是唯一需要"随时可查、改动可见"的内容（对话会滚走、执行会结束，约束不会）。
- **数据与实时性**：当前唯一结构化来源 = `AGENT_COMPLETED.slots` + 向导 `slots`（state+source 最富）。**实时性缺口以 `AGENT_SLOTS` 事件补齐**（§20 契约项 R-1，2.0 §10.2 方案原样提审），未实施前维持降级模式（占位说明 + 完成后填充）。
- **修改流**：槽位行内编辑（数字/日期/chip）→ 通道 A 走 `CardOption(EDIT)`、通道 B 走 `PUT /constraints{version}` → 变更摘要条 + "按新条件重新规划？"（§15）。**不是第二张表单**：完整表单仍在行程页 ConstraintEditor，会话页只做增量。
- **状态呈现**：沿用 2.0 五态→用户语言映射（✓已确认 / ≈AI推测 / ？待补充 / 已排除 / 来自行程🔒），内部枚举零暴露（有测试钉死）。

---

## 10. Conversation Experience（对话的角色）

**对话保留的场景**：目标陈述（START 主输入）、补充约束/改需求（自由文本，evidence-match 直接受益）、对结果的追问、以及一切无结构输入。
**对话退位的场景**：可枚举决策（→ 决策卡）、已知事实的展示（→ 约束板）、过程可见性（→ 执行流）、交付物（→ 结果面板）。
**实现原则**：消息流不再作为会话页的常驻主列；它以两种形态出现——START/CLARIFYING 阶段的 WorkArea 主体，与 EXECUTING/COMPLETED 阶段折叠进执行流/结果区的"对话时间线"。Composer 始终在（会话永远可以说话），但**说话不再是对话框产品的证据，而是会话的输入之一**。

---

## 11. Clarification Experience（决策点卡）

2.0 已落地 expectedType 驱动控件与应答锁定。3.0 增量：

1. **升级为"决策点"语义**：卡片抬头从"需要你确认一个信息"改为任务语义——"Agent 已完成当前信息收集，还需要你一个决定"；卡片显示**该决定影响什么**（如日期未定 → 影响"逐日安排与开放时间校验"），数据来自槽位元数据（前端静态映射表，不新增契约）。
2. **等待页写明恢复承诺**：等待横幅补一句"这个会话已保存，离开后 7 天内回来可继续"（真实 TTL 产品化，`AGENT_WAITING_TTL_SECONDS=7d`）。
3. 保留：单选直发/日期选择/数字输入/文本 chips/「暂时不确定」逃生口/重复应答锁定/事件在途输入锁（均有测试）。
4. **不做**：多选（契约无 multi 语义，不发明）；把向导 `CardOption(SET/CONFIRM/EDIT/SKIP/ASK)` 的 action 语义塞进 MQ 通道（两通道卡片控件对齐渲染，但协议不合并）。

---

## 12. Execution Experience & 13. Timeline 的取舍原则

用户要的是"**它在认真工作**"的确认，不是日志。取舍规则（替代"全部展示"）：

| Tool 事件 | 呈现 | 理由 |
|---|---|---|
| `update_constraints` / `update_preferences` | 合并为一条"理解旅行需求 ✓（已记录 N 项）" | 用户关心结果（被理解了什么），不关心更新了几次；N 取该回合该组步数 |
| `retrieve_guide_knowledge` / `search_place` / `check_opening_hours` / `get_route` | "查证旅行信息"分组下逐条展示，**成功的子步默认折叠为计数，失败琥珀展开** | 查证细节只在异常时有信息量 |
| `build_itinerary` | 单条"生成行程方案 ●" | 关键节点，值得存在感 |
| `validate_itinerary` | 单条 + 结果语义：通过→"验证通过 ✓"；`FEASIBILITY_BLOCKED`→"方案未通过验证，正在调整" | 验证是信任来源，必须可见 |
| `ask_user` | 不出现在执行流（它是决策点，有自己的卡） | 语义不同层级 |
| 未知 tool | 兜底"处理旅行事务" | 防泄漏 |
| 耗时/seq/eventId/tool 原名 | 不展示 | 属观测不属于产品 |

**与确定性管线的视觉统一**：Agent 执行流与内嵌管线进度共用同一"执行流"容器与节点样式（阶段名不同：查证/方案/验证 vs 12 阶段业务名），用户感知为**同一次工作的两段**，而非两套系统（当前最大心智断裂点）。

---

## 14. Waiting Experience（WAITING_USER）

- 决策点卡 + 等待横幅（"任务已保存在此，回答后继续；7 天内有效"）+ Composer 获得焦点。
- **页面关闭**：事件与 checkpoint 均已持久化；无动作需要用户做。
- **再次进入**：打开会话 URL（dashboard 行程卡新增"继续规划"角标状态可后续做，本期以 URL + 行程页入口为准）；SSE 重放恢复全部回合与决策点。
- **多 Run**：一次会话由多 run 组成（每回合一个 run，resume 续接同一 run）。前端只跟踪最新 runId（2.0 行为），历史回合以重放事件渲染——保持现状，不引入 run 列表 API（无产品问题需要它）。
- **等待期修改已确认约束**：允许（会话可说话/可编辑）；修改经 `PUT constraints` 落到 trip，Agent 侧在下一回合经 `update_constraints(USER_OVERRIDE)` 对齐或由用户显式重新规划（§15）。UI 在约束板行内编辑时提示"Agent 正在等待你的回答，修改将同步到行程条件"。

---

## 15. Replanning Experience（真实能力，不装自主 Replan）

**如实模型**：Agent 循环内无改行程工具（`REPLAN` 策略仅可声明，V2）；真实重规划 = 确定性管线 `POST /itinerary/replans{baseVersionId,dates}`（409 冲突、12 阶段、LOCAL_REPLAN 版本源）。

会话页设计：
1. 约束板修改 → 变更摘要卡（字段级 diff，数据来自编辑动作本身）→「按新条件重新规划」→ 会话切入 `Building` 模式，内嵌管线进度（含 REPAIRING attemptIndex/actionCount 统计）。
2. 自然语言改需求（"第二天不要去陈家祠"）→ run 内落 `USER_OVERRIDE` → 完成卡/约束板给"条件已更新，重新规划?"——文案**如实**说"已更新你的旅行条件并重新规划"，不说"Agent 正在修改你的行程"。
3. **为 V2 预留的产品空间**：ResultPanel 的"调整需求"区即未来 Agent 自主 Replan 的入口；当前它路由到约束编辑+确定性重规划，契约不变、组件位置不变，V2 只换执行者。UI 永不出现"正在自主重新规划"的假执行流。

---

## 16. Completed Experience（交付时刻）

结果面板分两段（对应真实两段交付）：

1. **Agent 交付（Draft Ready）**：行程摘要卡（标题/天数/每日主线——复用 CompletedCard 数据面）+ 约束满足对账（约束板逐项 ✓ 对账：预算/日期/必去 是否落入草案）+ 注意事项（slots 中 ！ 待补充项）+ 主 CTA「应用并生成正式行程」+ 次级「先调整需求」。
2. **管线交付（Delivered）**：`PLANNING_COMPLETED` → 结果面板切交付态：评分（PlanEvaluation 总分+维度，数据在管线事件中现成）+ 验证徽标（FeasibilityReport 状态）+「查看完整行程」→ TripDetail（既有地图/逐日/版本/分享/导出全量承接）+ 会话归档提示"本次规划已完成，可随时回看执行记录"（执行流折叠为审计摘要）。
3. `PLANNING_REVIEW_REQUIRED` → NeedsYou 模式复用决策点语义（复用 PlanningReviewPanel 的状态真值与文案资产）。

**不做**：在工作台内重画完整行程页（TripDetail 已是行程的家）；虚构"保存"按钮（版本库即保存，交付即已持久化）。

---

## 17. Error & Recovery

2.0 已建立 code→用户语言映射、恢复卡（重试/重开）、90s 兜底、断连重连。3.0 增量：

- 恢复卡升级为会话语义：`Stalled` 模式下保留全部已理解约束与执行摘要，卡片写明"你的需求已保留"——重试不丢上下文（真实：重试=新 run，约束板是前端投影+trip 事实，不随 run 丢失）。
- EXPIRED（7 天）卡明示"会话已归档，重新开始即可"，一键携带原目标句开新会话（本地草稿保留）。
- 创建模式（HTTP 通道）错误同样走 `agent-error-presentation` 映射（2.0 已覆盖其 502/400 族）。
- 技术细节（errorCode/reasonCode/traceId）零上屏，只进控制台与测试 data-testid（现状保持，有断言）。

---

## 18. Responsive Design

- **Desktop（≥lg）**：三区（WorkArea + 右栏约束板 280px + 底部 Composer）；Header 阶段条 sticky。
- **Tablet（md–lg）**：约束板降为顶部可展开摘要条；WorkArea 全宽。
- **Mobile（<md）**：单列全屏；阶段条 sticky；约束板=可展开抽屉内浮层（点击 Header 摘要）；决策点卡全宽；Composer sticky 底部。沿用现有 Tailwind 断点实践，不引入新体系。
- 移动端会话 URL 不变（同一响应式页面），恢复体验与桌面一致。

---

## 19. Runtime / Event / API Impact（必须/不该改的边界）

**必须改（前端）**：路由分支（`trip-plan` 渲染 + 新增 `/plan/new`）、TripWorkspace 增 PlanningSession 页挂载、新组件（GoalCanvas/ExecutionLane/ResultPanel/SessionHeader 等）、AgentDialogPanel 退役、TripDashboard 入口改跳转。
**建议的契约新增（逐项提审，均为增量、向后兼容）**：
- **R-1 `AGENT_SLOTS` v1**（2.0 §10.2 原案）：约束板实时化。未批准则约束板维持降级模式，**不阻塞 3.0 主体**。
**明确不改**：
- 不改 4 个既有 Agent 事件契约（schema/fixture 已双侧钉死）；不改 ask_user 协议；不改 202 无 runId 的设计（前端 WaitingForStart 态已覆盖）；不加 run 列表/快照 API（重放已闭环）；不加 MCP/Skill/Multi-Agent/ReAct；不做记忆读写 API（§21）；不动 planning 管线任何 schema。
- Java 侧唯一改动：无（若 R-1 批准才涉及，模式与 RUN_FINISHED 相同）。

## 20. Component Architecture（前端组件设计）

```text
pages/PlanningSessionPage.vue            # /plan/new 与 /trips/:id/plan 共用壳
composables/usePlanningSession.ts        # 会话状态机（扩展 useAgentWorkspace：+Pipeline/Result 态、+通道 A 驱动）
components/planning-session/
  SessionHeader.vue        # 目标句 + 阶段条（复用 StageBar 语义）+ 会话动作
  GoalCanvas.vue           # START 画布（示例预填，不自动发送）
  WorkArea.vue             # 阶段权重的容器（路由子内容）
  ExecutionLane.vue        # Agent 执行流 + 内嵌管线进度（统一视觉）
  PipelineProgressCompact.vue  # 包装既有 PlanningProgress 数据面（复用 planning-stream.ts 短路器）
  ResultPanel.vue          # Draft Ready / Delivered 两态
  ReviewCard.vue           # REVIEW_REQUIRED（复用 PlanningReviewPanel 资产）
  ConstraintBoard.vue      # ConstraintPanel 升级（行内编辑 + 变更摘要）
  DecisionCard.vue         # ClarificationCard 升级（影响面说明）
  RecoveryCard.vue         # ErrorRecoveryCard 会话语义升级
  DialogueTrail.vue        # 对话时间线（START/CLARIFYING 主区 / 其余折叠形态）
stores/planningSession.ts # （可选）Pinia 收敛：trip 级会话事实 + 跨页恢复
```
**复用不动**：`useAgentWorkspace` 的 SSE 循环/回合 reducer/输入锁/幂等键、`agent-timeline/agent-slots/agent-error-presentation` 三个 lib、`planning-stream.ts`、ui/ 原语。**退役**：`AgentDialogPanel.vue`（+其测试）、`AgentWorkspace.vue` 外壳（组件族迁入 planning-session 命名）。

## 21. Event Projection Architecture & Data Model

投影规则不变（真实事件→UI 态，2.0 lib 已实现并测试）；新增投影仅两处：
1. `ProductState = f(后端信号)` 二级映射表（§7）沉淀到 `agent-timeline.ts` 的 `deriveProductState()`。
2. UI State Model（前端类型，非后端契约）：

```ts
interface PlanningSessionView {
  id: string                       // tripId 或 create:{sessionId}
  channel: 'wizard' | 'run'        // 驱动源
  productState: ProductState       // §7 的 14 态
  goal: string | null              // 首条用户目标句
  constraints: SlotRowView[]       // 复用 agent-slots 投影
  turns: AgentTurn[]               // 复用回合模型
  pipeline?: { taskId, stages, outcome }   // 内嵌确定性管线投影
  deliverable?: { itineraryTitle, evaluation?, feasibility? }
  recovery?: { kind: 'stalled'|'dormant'|'disconnected', copy }
}
```

## 22. Memory 的克制方案（先审计后决定）

审计结论（§2.2.4）：记忆**运行时有效但产品面为零**——仅 MQ 通道、仅 LLM prompt 注入 + run 内 `update_preferences`。三个候选动作：
- A. 现状不动（零成本）：用户无感知，也无困惑。可接受的**本期基线**。
- B. 轻表达（需后端）：`GET /api/me/travel-preferences`（Java 代理 → Python 内部 profile 读接口）+ 会话 START 画布一行："根据你之前确认的偏好（轻松节奏、本地美食），将默认采用。 [调整] [不用了]"。调整/撤回走既有 `update_preferences` 提议路径或新写接口。**列为 P2 提审项，不阻塞 3.0**。
- C. 完整偏好中心：产品价值未证实（跨会话频率数据缺失），**明确不做**。
本期选 A，B 作为 R-2 提审（与 R-1 同批）。

## 23. Implementation Plan

| Phase | Scope | 关键文件 | 后端/契约 | 风险 | 测试与验收 |
|---|---|---|---|---|---|
| **P1 会话页骨架** | 启用 `/trips/:tripId/plan` 渲染分支；AgentWorkspace 组件族迁入 planning-session 命名；行程内入口改跳路由页；抽屉退役（行程内） | TripWorkspace.vue（新增 trip-plan 分支）、router、PlanningSessionPage、迁移组件 | 无 | TripDetail 旧挂载点清理、prop 面收敛 | 既有 28 组件单测迁移后全绿；e2e 3 场景改走路由页全绿；验收=行程内会话在 URL 上发生且刷新可恢复 |
| **P2 Start 体验** | GoalCanvas（两通道变体）；过滤向导问候语；TripDashboard 主入口改跳 `/plan/new`；`/trips/new` 接手动表单 | GoalCanvas、TripDashboard、TripWorkspace 创建流 | 无（前端过滤 kind=TEXT 问候） | 创建入口是唯一可见入口（App.test 钉死路径）需同步改测试 | 新 START 单测+e2e：3 秒可理解（示例可见+输入可用）；验收=Scenario 1 |
| **P3 约束板升级** | ConstraintBoard 行内编辑+变更摘要+对账高亮 | ConstraintBoard、usePlanningSession | **R-1（可选，提审）**；不批准则降级模式 | 编辑与 run 并发语义 | 槽位编辑单测；验收=Scenario 2/9 |
| **P4 执行/等待/决策升级** | ExecutionLane 统一视觉 + 合并规则；DecisionCard 影响面；等待恢复承诺文案 | ExecutionLane、DecisionCard、usePlanningSession | 无 | 合并规则的回合边界单测 | 验收=Scenario 3/4/5/6/7 |
| **P5 交付体验** | ResultPanel 两态 + 内嵌管线进度 + review 分流 + 去行程页衔接 | ResultPanel、PipelineProgressCompact、ReviewCard | 无（复用 planning SSE） | 与 TripDetail 规划组件双展示需 store 收敛 | 验收=Scenario 8/10 |
| **P6 创建模式迁移 + 退役** | `/plan/new` 承接向导驱动（slots/CardOption 全量）；AgentDialogPanel 删除；错误映射复验 | PlanningSessionPage(向导驱动)、删除 AgentDialogPanel | 无 | 创建链路回归面最大（App.test 路径） | 全量 e2e + 创建→规划→交付串测；验收=Scenario 1/12 |
| **P7 恢复/异常打磨** | 会话恢复深链、EXPIRED 携目标重开、断连恢复、Stalled 上下文保留 | usePlanningSession、RecoveryCard | 无 | 低 | 验收=Scenario 11/12 |

**推荐实施顺序**：P1 → P2 → P4 → P5 → P3 → P7 → P6（创建迁移回归面最大，放组件语义稳定后）。

## 24. Migration Strategy

- **保留不动**：3 个投影 lib、useAgentWorkspace 核心、planning-stream、PlanningProgress/ReviewPanel/EvaluationPanel/VersionPanel（行程页资产）、ui/ 原语、全部 4+4 事件契约。
- **迁移**：agent-workspace 组件族 → planning-session（更名+增强）；TripDashboard 创建入口；TripDetail 的「AI 助手」按钮 → 路由跳转。
- **删除**（P6 末）：AgentDialogPanel.vue + 测试；AgentWorkspace.vue 外壳（由 SessionHeader+WorkArea 取代）。
- **暂时兼容**：`/trips/{id}` 页保留「AI 助手」入口一个版本，改为跳 `/plan`（书签/习惯过渡）；删除动作在 P6 验收后一个提交内完成，不做长期双轨。

## 25. Testing Strategy

| 层 | 资产 | 3.0 增量 |
|---|---|---|
| Unit | 既有 agent-timeline/slots/error 28 例 | deriveProductState 14 态映射表；ExecutionLane 合并规则；P3 编辑冲突语义 |
| Component | AgentWorkspace.test 7 例（迁移） | GoalCanvas/ResultPanel/ReviewCard/ConstraintBoard 编辑 |
| E2E(mock) | agent-workspace.spec 3 场景（改走路由页） | Scenario 1/3/8/9/11 的 URL 化版本；START 三入口 |
| Real Event | 契约 fixture 复用 | R-1 批准则加 fixture round-trip（Py+Java 双侧） |
| Real Stack | curl 冒烟脚本（本报告 §4 同款） | prod 入口 38080 全链路对话；会话 URL 重开重放验证 |
| Error/Resume/Waiting/Replan | RUN_FINISHED 单测+e2e；90s 兜底；resume 幂等 | EXPIRED 携目标重开；replan 409 分支；review 分流 |

## 26. Acceptance Scenarios（12 条，事件级可断言）

| # | 场景 | 通过断言（关键项） |
|---|---|---|
| 1 | 一句话开始（创建会话页） | URL=/plan/new；无问候气泡；约束板骨架出现；202→STARTING |
| 2 | Agent 理解约束 | STEP(UNDERSTANDING 组) 合并为一条"N 项已记录"；约束板出现对应行 |
| 3 | 主动澄清 | ASK_USER→NeedsYou 模式；决策卡含影响面说明；等待横幅含"7 天"承诺 |
| 4 | 回答后 Resume | 点选即发 answers；卡片锁定；runId 续接；重放后仍锁定 |
| 5 | Research | 查证组真实子步（计数+失败展开）；剔除检索步骤时该组不出现（反 Fake） |
| 6 | Planning | build_itinerary 单节点；阶段条 PLANNING |
| 7 | Validation | 通过/未通过两文案；FEASIBILITY_BLOCKED → "正在调整" |
| 8 | 完成行程 | COMPLETED→结果面板+对账；应用→内嵌 12 阶段→Delivered→去行程页 |
| 9 | 修改约束 | 行内编辑→变更摘要 diff→PUT 带 version；409 走重载分支 |
| 10 | 重新规划 | replans 202→Building 模式→REPAIRING 统计可见→完成/Review 分流 |
| 11 | Agent 失败 | RUN_FINISHED→Stalled；约束与摘要保留；重试=新 run |
| 12 | 离开后恢复 | 杀页→重开同 URL→重放还原到 Waiting/Completed/Stalled 对应态；EXPIRED 一键携目标重开 |

## 27. ADR Recommendations

- **ADR-017：Planning Session 作为一等路由页，退役 Agent Drawer**——依据：任务时长（分钟级）、四类内容需同屏、恢复依赖 URL 身份、移动端等价全屏；死路由 `/trips/:tripId/plan` 证明该结构本是规划意图。Drawer 不保留（含大号 Drawer）：抽屉天然是"页面附属品"，与会话的任务主体地位矛盾，且双入口（创建/行程内）用抽屉已产生两套载体债务。
- **ADR-018：会话=产品对象，通道（向导/Run）仅是实现细节**——统一 Session 模型，UI 面向 Session 编程；契约不合并，投影层吸收差异（防未来通道统一时前端二次重构）。
- **ADR-019（提审）**：`AGENT_SLOTS` v1 实时约束投影（2.0 §10.2 原案）；**ADR-020（提审，P2）**：偏好记忆只读代理 API。两案不批准不阻塞主体。

---

## 28. 明确不做清单（反"为 Agent 而 Agent"）

MCP / Skill 体系 / Multi-Agent / ReAct / Agent Marketplace / 无意义 Memory·Planner·Reflection / 自主 Replan 假执行流 / run 列表 API / 202 预分配 runId / 多选澄清契约 / 会话内重画行程页 / token 流 / 记忆完整偏好中心。Agent 化路线图中 V2 项（intent/critic/自主 REPLAN）不在本方案扩权，仅预留产品入口。

---

## 附：审计证据索引（关键 file:line）

死路由 `apps/web/src/app/router/index.ts:24-27` + `TripWorkspace.vue:94,98,1303,1323,1372`；向导问候 `dialog/service.py:537`；记忆加载/注入 `agent_processor.py:209,288` + `graph.py:336`；事件发布条件 `agent_processor.py`（_publish_question/_publish_completion/_publish_run_finished/publish_resume_rejected）；Java 消费 `AgentDialogEventListener.java` + 绑定 `RabbitMessagingConfiguration.java`；SSE `AgentDialogEventHub.java`（per-trip/重放/30min）；投影组件 `apps/web/src/components/agent-workspace/*`；e2e `apps/web/e2e/agent-workspace.spec.ts`；2.0 方案 `docs/architecture/agent-ux-2.0-redesign-plan.md`。
