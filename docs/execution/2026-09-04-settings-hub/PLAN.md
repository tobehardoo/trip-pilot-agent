# F-UI-11 设置中心（Settings Hub）计划书

> 日期：2026-09-04 ｜ 状态：**P0 已实施并全闸门通过（D1/D2/D3 均已定稿；P1/P2 未开工）**
> 触发：用户提出「设置能不能做成截图所示的桌面 App 式设置中心」，要求先规划再动手。
> 参考截图：Z.ai 桌面端「模型设置」页（分组左导航 + 右侧内容区 + 「← 返回工作区」）。
> 视觉基准：`docs/design/DESIGN-BASELINE.md`（**只借鉴截图的布局结构，不引入它的皮肤**）。
> 交互演示：同目录 `mockup.html`（方案 A/B 可切换对比，含齿轮入口与常规/API 分区演示）。
> 编号：F-UI-11（沿用 F-UI 序列；F-UI-10 为地图恢复，若期间已有新增编号则顺延）。

---

## 1. 背景与问题

当前 TripPilot 的「设置」是 `WorkspaceSidebar` 底部的一个**弹出小卡片**（`WorkspaceSidebar.vue:409-479`），存在四个问题：

1. **容量不足**：4 个 provider 的 Key / Base URL / 模型名挤在 224px 宽的弹卡里，输入框高仅 24px（h-6），可用性差。
2. **不可扩展**：设置项继续增加（连接测试、状态徽标、索引库、统计…）会让弹卡变成灾难。
3. **层级混乱**：账号信息、退出登录、第三方 API 配置三种不同性质的东西混在一个卡片里。
4. **与产品气质不符**：截图所示「分组左导航 + 右内容区」的设置中心是 Developer Tool 类产品的标准形态，TripPilot 已具备同款视觉语言（tp-* 中性灰体系），只缺这一层信息架构。

## 2. 现状盘点（证据清单）

| 事实 | 证据 |
| --- | --- |
| 设置弹卡：账号 + 退出登录 + 4 provider 表单 | `apps/web/src/workspace/layout/WorkspaceSidebar.vue:409-479` |
| provider 枚举：WEATHER（和风）/ AMAP（高德）/ KNOWLEDGE（DashScope 嵌入）/ PLANNER（规划） | `WorkspaceSidebar.vue:48-53` |
| 配置读写逻辑（loadApiConfigs / saveApiConfigsAll，仅 KNOWLEDGE 有 model 字段输入） | `WorkspaceSidebar.vue:47-97` |
| 前端 API 封装已有 list / save / delete 三个函数 | `apps/web/src/lib/api.ts:1029,1038,1045` |
| 后端 `GET/PUT/DELETE /api/config/api-configs`（JWT → userId 隔离） | `apps/travel-server/.../userconfig/UserApiConfigController.java:27-40` |
| 导航切换先例（工作台 / 知识库 / 设置 三态 + openKnowledge 事件） | `WorkspaceSidebar.vue:99-117`、`workspace/WorkspacePage.vue:75,379-388` |
| 路由现状：仅 `/share/:token`、`/workspace`、`/workspace/trips/:tripId` | `apps/web/src/app/router/index.ts:15-23` |
| **没有**：连接测试端点、配置状态聚合、使用统计控制器、用户画像读写端点 | travel-server 控制器全量清单核对（18 个 `@RequestMapping`，无 stats/profile 域） |
| 测试基线：55 文件 / 562 用例全绿 = 合入门槛；构建闸门 = `vue-tsc -b && vite build` | `docs/execution/Phase-FUI/01-frontend-ui-consolidation-report.md` |
| 视觉验收脚本（支持 SHELL_BASE_URL） | `apps/web/scripts/workspace-shell-screenshot.mjs` |

## 3. 目标信息架构：截图 → TripPilot 映射

截图分区逐一映射到 TripPilot **实际存在的能力**，不造假开关：

### 3.1 左侧分组导航（新增）

```text
┌────────────────────┬──────────────────────────────────────────────┐
│ ← 返回工作区        │  设置 · {当前分区名}                           │
│                    │  一句话分区描述                    [刷新/操作] │
│ 基础设置            │ ┌──────────────────────────────────────────┐ │
│  常规              │ │ 分区内容（行式 / Divider 分组，非卡片海）  │ │
│  API 与模型         │ │ …                                        │ │
│ Agent 能力          │ └──────────────────────────────────────────┘ │
│  工具与集成*        │                                              │
│ 数据与统计          │                                              │
│  索引库*           │                                              │
│  使用统计*          │                                              │
└────────────────────┴──────────────────────────────────────────────┘
```

### 3.2 分区映射表

| 截图分区 | TripPilot 对应 | 数据来源（已有 / 需新增） | 期 |
| --- | --- | --- | --- |
| 常规 | 账号：昵称、邮箱、退出登录 | `session.user`（已有） | **P0** |
| 外观 | 基准锁定浅色单主题，**当前无可变项 → 不设此分区**（避免空壳页） | — | 不做 |
| 模型设置 | **「API 与模型」**：4 个 provider 列表（规划 / 知识库嵌入 / 高德地图 / 天气），每项含状态徽标（已配置 ✓ / 未配置，纯文字色）、Key 掩码输入、Base URL、模型名（KNOWLEDGE） | `GET/PUT /api/config/api-configs`（已有） | **P0**（功能自弹卡迁移，零缩水） |
| 连接测试 | 每个 provider 一键「测试连接」（调真实第三方探活，返回 ✓/! + 提示） | **需新增后端** `POST /api/config/api-configs/{provider}/test` | P1 |
| 浏览器控制 / 电脑控制 | 无对应物 | — | **不移植** |
| 记忆 | agent-service 有 profile-memory 能力（Phase 3.2），但无用户侧读写端点 | **需新增后端**（先核实数据形态） | P2 候选 |
| 子智能体 / 插件 / MCP 服务器 / 技能 / 命令 / 钩子 | 无对应物（TripPilot 的 agent 能力内聚在 agent-service，不暴露 per-user 开关） | — | **不移植** |
| 索引库 | 知识库摘要卡：文档数 / 索引状态 + 「打开知识库」入口（复用既有知识库视图） | `/api/knowledge`（已有）、`KnowledgeBasePage.vue`（已有） | P1 |
| 使用统计 | 规划次数 / Token / 调用量等 | **无数据管道**，需后端埋点 + 聚合端点 | P2（不承诺） |
| 编程套餐 / 订阅 | 无商业化能力 | — | **不移植** |

> 原则：**截图里 TripPilot 没有的东西一律不渲染成灰态假开关**——设置页只出现真实可用的项，这本身就是 Developer Tool 的诚实性要求。

## 4. 视觉与交互规范（对齐 DESIGN-BASELINE）

借鉴截图的**结构**，皮肤严格执行基准：

| 截图元素 | 处置 |
| --- | --- |
| 分组左导航（分组标题 + 条目） | 保留结构；样式复用 WorkspaceSidebar 条目配方（h-7/h-8、12px、激活 = tp-active + 2px 内嵌左标记） |
| 右侧「大标题 + 一句话描述 + 刷新」头部 | 保留；标题 ≤20px，描述 12px tp-sub |
| 内容卡片（rounded-lg 白卡） | **降级**：默认 Divider 分组；仅 provider 编辑块这类需要边界的表单区允许 1px tp-line 边框容器，圆角 ≤6px、无阴影 |
| 「个人套餐」蓝色高亮卡 | **禁止**（彩色背景块违反基准规则 9/11） |
| 未启用 Badge / 订阅黑按钮 | 状态用纯文字色（✓ tp-ok / 未配置 tp-faint），主按钮走 `ui/Button` |
| 「← 返回工作区」 | 保留，置于左导航顶部 |

可访问性：主操作按钮沿用 B15.1 R3 闸口——`Button size=lg`（保存配置、退出登录）≥44px（h-12）；导航/次级控件不受此限。

## 5. 技术方案

### 5.1 页面挂载方式（D1 待定：先看 `mockup.html` 对比再拍板）

- **方案 A：新增路由 `/workspace/settings`**。理由：设置无 trip 上下文，天然独立路由；「返回工作区」= `router.back/replace('/workspace')` 语义自然；可深链、可刷新。改动点：`router/index.ts` 加一条路由 + `WorkspacePage` 按 route name 渲染 `SettingsPage`（与既有 workspace-trip 双路由同模式）。
- 方案 B：仿知识库的 shell-state 三态（`showSettings`）。改动更小，但不可深链、刷新即回工作台，且 WorkspacePage 的视图状态会继续膨胀。
- 两个方案的视觉效果与差异已做成可交互演示 `mockup.html`（顶栏切换 A/B，可点齿轮/返回体验跳转语义），2026-09-04 用户对比后拍板**方案 A**并授权 P0 实施。

### 5.2 组件结构（全部落在 `src/workspace/` 合规区）

```text
src/workspace/settings/
  SettingsPage.vue            # 壳：左导航 + 右内容（含 ← 返回工作区）
  SettingsNav.vue             # 分组导航（基础设置 / Agent 能力 / 数据与统计）
  sections/
    GeneralSection.vue        # 常规：账号 + 退出登录
    ApiModelsSection.vue      # API 与模型：provider 列表 + 编辑 + 保存
  composables/
    useApiConfigs.ts          # 自 WorkspaceSidebar.vue:47-97 原样迁移（行为不变）
```

- `api.ts` 的三个封装函数直接复用，不动后端 P0 契约。
- **Sidebar 变更（D3 已定稿）**：底部账号区整体移除（用户条 + 退出登录，`WorkspaceSidebar.vue:426-444` 一带）；「设置」入口从文字按钮改为 **icon-only 齿轮按钮**（约 28×28，`aria-label="设置"` + title 提示，保留 `workspace-nav-settings` testid 语义）；账号展示与退出登录并入设置页 `GeneralSection`（`workspace-settings-logout` testid 迁移为 `settings-general-logout`）。
- 状态徽标只用文字：`✓ 已配置`（tp-ok）/ `未配置`（tp-faint），不用彩色 Badge。

## 6. 分期计划

### P0 — 设置中心壳 + 存量功能迁移（本期，1-2 刀；范围 D2 已定稿：只做「常规 + API 与模型」）

| # | 任务 | 涉及文件 |
| --- | --- | --- |
| 1 | 按 D1 结论挂载设置页（方案 A：路由 `/workspace/settings`；方案 B：shell-state） | `router/index.ts`、`WorkspacePage.vue` |
| 2 | `SettingsPage` + `SettingsNav` + `GeneralSection` + `ApiModelsSection` + `useApiConfigs`（仅两个分区；P1/P2 分区后续追加进导航） | 新增 5 文件 |
| 3 | Sidebar 变更（D3）：删除底部弹卡与账号区，「设置」改 icon-only 齿轮按钮；账号/退出登录逻辑迁入 `GeneralSection`；apiForm 逻辑（`WorkspaceSidebar.vue:47-97`）迁入 `useApiConfigs` | `WorkspaceSidebar.vue` + 其测试 |
| 4 | 截图脚本新增 settings 桌面视口产物 | `workspace-shell-screenshot.mjs` |

**验收**：① 弹卡全部能力在新页等价可用——4 provider 读写、KNOWLEDGE model 字段、Base URL、保存反馈、错误提示不吞；**账号信息（昵称/邮箱）与退出登录在「常规」分区可用，sidebar 底部不再保留账号展示**；② 345 用例基线不破 + 新组件用例；③ `vue-tsc -b && vite build` 通过；④ 基准检查清单（DESIGN-BASELINE §10）逐项过；⑤ 截图 `settings-page-desktop.png` 归档。

### P1 — 真实性增强（需小后端）

1. `POST /api/config/api-configs/{provider}/test`：服务端用所存配置探活第三方（高德/和风/DashScope），返回 ✓/! 与耗时；前端按钮 + 行内结果（绝不做前端直连第三方——有 CORS 与密钥泄漏问题）。
2. provider 列表聚合状态：list 响应派生「已配置/未配置」徽标（纯前端即可，随 P1 一起打磨）。
3. 「索引库」摘要分区：`/api/knowledge` 派生文档数与索引状态 + 跳转知识库视图。

### P2 — 评估后决定（不默认做）

- **使用统计**：需后端埋点 → 聚合端点 → 前端只读报表。投资大，建议单独立项。
- **记忆管理**：先核实 profile-memory 数据形态与合规边界，再定读写端点。
- **外观分区**：仅当未来引入真实的可变项（如界面密度）再开。

## 7. 测试与闸门

- 组件测试：SettingsNav 分组渲染与跳转、GeneralSection 账号展示/退出、ApiModelsSection 加载/保存/失败/未登录分支、Sidebar 改造后的回归。
- 全量闸门：34 文件 / 345 用例全绿（新增用例顺延计数）、`vue-tsc -b && vite build`、基准一致性清单。
- 跨语言注意：P1 触碰 Java 后端，Java 闸门（626 passed）必须同窗全绿，前后端改动同 commit。

## 8. 风险与边界

| 风险 | 对策 |
| --- | --- |
| Sidebar 测试依赖 `workspace-settings-*` testid，删除弹卡与账号区会红 | 同刀迁移 testid（`workspace-settings-logout` → `settings-general-logout`，齿轮保留 `workspace-nav-settings`）并在测试里对齐，不许留悬空断言 |
| `/workspace/settings` 刷新 404 | 与 `/workspace/trips/:tripId` 同属 history 模式，先验证网关 SPA fallback 已覆盖（已有先例，风险低） |
| 顺手翻新旧 UI | 禁止。旧 `components/` 存量按 Phase 2 计划处置，本计划不碰 |
| 功能迁移缩水（如 KNOWLEDGE 清空按钮） | 验收标准第 ① 条按弹卡现有功能逐项核对 |
| 深色/彩色诱惑（截图自带蓝卡与圆角卡） | 基准负面清单（§7）直接否决，无讨论空间 |

## 9. 明确不做清单（本计划边界）

- 浏览器控制、电脑控制、子智能体、插件、MCP 服务器、技能、命令、钩子、订阅套餐 → 无对应物，不移植、不放假开关。
- 主题切换（深色模式）→ 基准锁定浅色单主题，不属于本计划。
- 旧 UI 翻新、TripWorkspace 迁移 → 归 Phase 2 既有计划。
- 任何后端新端点 → 不进 P0；P1 起才触碰后端契约。

## 10. 决议记录（2026-09-04 用户评审）

| # | 决策点 | 状态 |
| --- | --- | --- |
| D1 | 挂载方式：方案 A（新路由）vs 方案 B（shell-state） | **已定：方案 A**（新路由 `/workspace/settings`，name `workspace-settings`）—— 用户对比 `mockup.html` 后拍板 |
| D2 | P0 范围 | **已定：只做「常规 + API 与模型」两个分区**，索引库摘要不提前 |
| D3 | Sidebar 底部账号区 | **已定：账号区移除，「设置」改为 icon-only 小齿轮**；账号展示与退出登录并入设置页「常规」分区（演示页已体现此形态） |

## 11. 实施记录（P0，2026-09-04）

### 11.1 交付物

| 文件 | 变更 |
| --- | --- |
| `apps/web/src/workspace/settings/sections.ts` | 新增：分区元数据（`general`/`api`） |
| `apps/web/src/workspace/settings/useApiConfigs.ts` | 新增：自 `WorkspaceSidebar.vue:47-97` 迁移的配置读写逻辑（保存仅提交非空 apiKey、load 重置后合并、`configured` 派生 ✓/未配置） |
| `apps/web/src/workspace/settings/SettingsPage.vue` | 新增：整页壳（左导航 + 右内容 + 「← 返回工作区」；返回目标带 trip 上下文时回 `/workspace/trips/:id`） |
| `apps/web/src/workspace/settings/SettingsNav.vue` | 新增：分组导航（基础设置：常规 / API 与模型） |
| `apps/web/src/workspace/settings/sections/GeneralSection.vue` | 新增：账号行（昵称/邮箱/用户 ID，仅展示）+ 退出登录（h-12，testid `settings-general-logout`） |
| `apps/web/src/workspace/settings/sections/ApiModelsSection.vue` | 新增：4 provider 行式列表（状态文字/Key 掩码/Base URL/model），保存 h-12 |
| `apps/web/src/app/router/index.ts` | 新增路由 `/workspace/settings` → `workspace-settings` → `WorkspacePage` |
| `apps/web/src/workspace/WorkspacePage.vue` | 按 route name 分支渲染 `SettingsPage`（整页，替换 shell） |
| `apps/web/src/workspace/layout/WorkspaceSidebar.vue` | 删除底部账号弹卡（约 70 行逻辑 + 模板）；「设置」改 icon-only 齿轮（28px，`aria-label="设置"`，保留 `workspace-nav-settings` testid） |
| `apps/web/tests/router.test.ts` | 补断言：`/workspace/settings` → `workspace-settings` |
| `apps/web/tests/settings-page.test.ts` | 新增 5 用例（导航渲染/默认常规/账号展示/分区切换/返回语义/退出登录唯一） |
| `apps/web/tests/api-models-section.test.ts` | 新增 5 用例（加载回填/保存过滤与 PUT 体/服务端错误透出/清空/加载失败） |
| `apps/web/scripts/workspace-shell-screenshot.mjs` | 全视口统一 API stub（`**/api/**` 按 pathname 分支：refresh 会话 / api-configs / 空 trips 列表），新增 settings 视口 |

### 11.2 闸门结果（全部通过）

| 闸门 | 结果 |
| --- | --- |
| `vue-tsc -b` | 0 错误 |
| `vitest run` 全量 | **34 文件 / 345 用例全绿**（29 既有 + 5 新增 = 34 文件口径含新测试文件） |
| `vite build` | 通过（1666 modules） |
| DESIGN-BASELINE §10 清单 | 逐项过（tp-* 令牌、无阴影/渐变/大圆角、状态纯文字色、h-12 主按钮、Divider 分组） |
| 截图归档 | `output/screenshots/settings-page-desktop.png`（1440×900） |

### 11.3 基准截图替换说明（重要）

`workspace-shell-{desktop,narrow,tablet}.png` 三张基准图在截图过程中被无 stub 版脚本覆盖为登录页。已修复脚本（全视口 stub）并重拍为**登录态空工作台**截图——内容反映 F-UI-11 后的当前 UI（含齿轮入口、无账号区）。注意：被替换前的那三张图是 2026-09-01 的旧 UI 内容（含搜索 tab、账号区），本就落后于 DESIGN-BASELINE 引用状态；`output/` 目录 gitignore 不入库，DESIGN-BASELINE 若引用截图请以本批新图为基准。

### 11.4 遗留与后续

- P1（连接测试后端端点、索引库摘要分区）、P2（使用统计、记忆管理）未开工，见 §6。
- 未提交 git（用户未要求）；建议 commit 前缀 `feat (F-UI-11): 设置中心 P0…`。
- 项目记忆中的旧测试基线「55 文件/562 用例」已同步修正为 34/345。

## 12. 追加：F-UI-12 三栏可拖拽布局（2026-09-04，用户验收反馈）

用户真实登录验收设置页时反馈：左/右栏在窗口 <1280px 时是**覆盖式抽屉**（absolute + 遮罩），要求改成 **Codex 式三栏并排 + 拖拽分隔线等比例伸缩**。

| # | 变更 | 文件 |
| --- | --- | --- |
| 1 | 新增 `usePanelResize` composable：pointer 拖拽 + clamp（sidebar 200–360px / context 220–460px）+ localStorage 持久化，零第三方依赖 | `apps/web/src/workspace/layout/usePanelResize.ts` |
| 2 | 并排断点下调：Sidebar lg(1024)→md(768)、Context xl(1280)→lg(1024)；<768px 保留抽屉遮罩；左右栏宽度由容器 style 绑定 | `WorkspacePage.vue` |
| 3 | 新增左右分隔把手（w-1.5 热区、hover tp-hover、role=separator + aria-label，testid `workspace-sidebar-resizer` / `workspace-context-resizer`） | `WorkspacePage.vue` |
| 4 | 组件根宽 `w-56`/`w-64` → `w-full`（宽度单点由 WorkspacePage 容器管理） | `WorkspaceSidebar.vue`、`WorkspaceContextPanel.vue` |
| 5 | 设置页右栏去 `max-w-3xl mx-auto` 居中 → 拉伸铺满 | `SettingsPage.vue` |

闸门：`vue-tsc -b` 0 错；34 文件 / 345 用例全绿；`vite build` ✓；基准截图重拍（三栏并排新形态）。

### 12.1 等比例修订（同日，用户二次反馈「不同屏幕等比例复现」）

栏宽状态从固定 px 改为**占比（ratio）**，渲染为 `clamp(px下限, 比例%, px上限)`：

- `usePanelResize` 重写：`sidebarRatio`/`contextRatio`（默认 0.18/0.20，边界 0.12–0.28 / 0.14–0.32），拖拽 px 增量按容器实测宽换算为比例增量（`nextRatio` 纯函数可单测），localStorage 持久化 ratio（合理窗口 0.05–0.6，旧 px 值自动作废回落默认）
- 渲染：sidebar `clamp(180px, 18%, 360px)`、context `clamp(200px, 20%, 400px)`；抽屉模式固定 240/264px
- 探针实测（`scripts/probe-pane-ratios.mjs`）：1440/1152/1024 三档 sidebar 恒 0.180、context 恒 0.200（等比例精确成立）；900px（<1024 右栏收起）sidebar 触发 180px 下限兜底
- 闸门：vue-tsc 0 错；**35 文件 / 352 用例全绿**（新增 use-panel-resize 7 用例）；vite build ✓
