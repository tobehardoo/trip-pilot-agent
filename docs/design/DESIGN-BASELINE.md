# TripPilot Design Baseline

> **状态：正式生效（2026-09-01，F-UI-6b）**
> 基准截图：`apps/web/output/screenshots/workspace-shell-desktop.png`（/workspace 桌面视口）
> 本文档是 TripPilot 所有页面的唯一视觉基准。后续新增或修改任何页面前，先对照本文档检查视觉语言一致性。

---

## 1. 定位

TripPilot 的视觉定位是 **Developer Tool / AI Agent Workspace / IDE**（参考气质：Codex / Cursor / Claude Code / Copilot Workspace 的克制与工具感，不复制其品牌元素）。

**不是**：旅行 App、SaaS Dashboard、Notion 模板、AI Landing Page。

一句话判断标准：**把 "TripPilot" 文字遮掉，页面仍必须像一个专业 Agent 工具。**

## 2. 不可变更的三栏信息架构

```text
┌─────────────────────────────────────────────────┐
│ Application Bar（任务路径居中 + 运行状态）        │
├──────────┬──────────────────────────┬───────────┤
│ Left     │ Center                   │ Right     │
│ Workspace│ Agent Execution          │ Agent     │
│ / Trips  │ / Timeline / Tool Calls  │ Context   │
│          │ / Results                │ / Constraints │
│          │                          │ / Agent State │
│          │                          │ / Artifacts   │
├──────────┴──────────────────────────┴───────────┤
│ Agent Command Bar                               │
└─────────────────────────────────────────────────┘
```

## 3. 设计令牌（唯一取色来源）

代码位置：`apps/web/tailwind.config.js` → `theme.extend.colors.tp`。
**新页面禁止硬编码 hex，只允许使用 `tp-*` 类。**

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `tp-bg` | `#F7F7F5` | 应用背景 |
| `tp-panel` | `#FCFCFB` | 侧栏 / 面板背景 |
| `tp-line` | `#E5E5E5` | 主边框 |
| `tp-div` | `#EBEBE9` | 次级分割线 |
| `tp-active` | `#EFEFED` | 选中项背景 |
| `tp-hover` | `#F2F2F0` | 悬停背景 |
| `tp-ink` | `#1F1F1F` | 主文字 |
| `tp-body` | `#3D3D3B` | 次级正文 |
| `tp-sub` | `#6B6B6B` | 辅助文字 |
| `tp-mute` | `#999999` | 弱化文字 / 元信息 |
| `tp-faint` | `#C9C9C6` | 占位 / 禁用 / 最弱文字 |
| `tp-ok` | `#4A7C59` | Completed（仅小字形 ✓） |
| `tp-run` | `#8A8A86` | Running（仅小圆点 / 文字） |
| `tp-warn` | `#A65D57` | Failed / 提示（低饱和红） |
| `tp-dot` | `#B7B7B3` | 脉冲状态圆点 |

## 4. 十二条强制规则

1. **风格**：Developer Tool / AI Agent Workspace，克制、干练、工具感优先。
2. **色系**：中性灰白体系；颜色不得成为视觉主体。
3. **层级**：由细边框 + Divider + 排版建立，不靠颜色和阴影。
4. **密度**：紧凑；小标题 → 数据行 → Divider → 下一组。
5. **字号**：页面标题 18–20px；Section 12–14px；正文 13px；辅助 12px；元信息 11px；禁止 32px+ 大标题。
6. **装饰**：低装饰、低噪声；不确定时——加装饰还是减装饰？**减**。
7. **圆角**：容器 4px、按钮/输入 6px；禁止 8px 以上。
8. **阴影**：默认 none；层级用边框与背景区分。
9. **禁止**：渐变、玻璃拟态（glass/blur）、发光、彩色背景块。
10. **Card 纪律**：不把所有内容包卡片。默认用 Divider；仅 Tool Call / Execution Panel 这类真正需要边界的执行面板可用带边框容器。
11. **状态色预算**：仅 `✓`（tp-ok）、`●`（tp-run，可脉冲）、`!`（tp-warn）三种小字形/圆点；禁止彩色 Badge、彩色圆形图标、整块彩色背景。
12. **表达方式**：Tool / Agent / Context 信息用排版与边界表达——等宽字体（`font-mono`）用于工具名、标识符、数字；不用装饰性 AI 图标。

## 5. 语言原则（2026-09-01 补充，与视觉规则同级）

- **用户可见文案一律中文**：导航（工作区/旅行）、分区标题（智能体/旅行/旅行约束/规划信息/生成结果）、状态（规划中/运行中/已完成/待生成/已生成）。
- **仅以下内容保留英文**：技术产品名（OR-Tools、AMap）、第三方服务名、代码/API/工具 identifier、用户输入、品牌名。
- 技术名不作主文案：工具主名用中文（如「路线优化求解器」），技术标识以 mono 小字辅助（如 `OR-Tools`）。
- 中间区职责：**规划中 = Agent 执行时间线；已完成 = 旅行攻略/行程阅读区**（概览 → 每日攻略 → POI 推荐理由/游览建议/交通/注意事项），Agent 执行记录默认折叠（「查看智能体规划过程」）。右侧上下文不放攻略正文。

## 6. 组件配方

### 时间线步骤（AgentExecutionStep）
```text
✓  理解旅行需求          ← 13px medium tp-ink
   已识别目的地、日期与偏好   ← 12px tp-mute
```
无圆形图标、无连接线、无卡片；字形列 16px 宽：`✓ / ● / ○ / !`。

### Execution Panel（ToolExecutionCard）
```text
TOOL CALL                          RUNNING   ← 10px tracking-widest tp-mute / tp-run
or-tools-solver                              ← 13px font-mono tp-ink
Candidate POIs                        24     ← label 12px tp-sub / value mono tp-ink
──────────────────────────────────────────
● Searching feasible solution…               ← 12px tp-mute
```
1px `tp-line` 边框、白底、无阴影。

### Inspector（WorkspaceContextPanel）
小标题 10–11px uppercase tracking；label/value 行式；分组间 `tp-div` 分割线；指标数值右对齐 mono。

### Sidebar（WorkspaceSidebar）
224px 宽；条目 h-7/h-8、12px 字号；激活项 = `tp-active` 背景 + 2px `tp-ink` 内嵌左标记；分组标题 10px uppercase `tp-mute`。

### Command Bar（WorkspaceCommandBar）
高 36px 单行输入；`tp-line` 边框、白底、focus 变 `tp-faint` 边框；无发光无阴影。

## 7. 明确禁止回退（Negative List）

- ❌ 大圆角 SaaS 卡片（rounded-xl/2xl/3xl）
- ❌ 彩色 Dashboard / 统计卡片 / Badge 群
- ❌ 大面积阴影 / 悬浮卡片 / glass-surface
- ❌ 渐变（dest-* / bg-gradient-*）
- ❌ 巨大标题（32px+）
- ❌ 大面积留白 / 一屏三张巨卡的排版
- ❌ 装饰性 AI 图标 / 大 Logo 块
- ❌ "旅行 App" 式视觉（彩色城市渐变卡、营销 Banner）

## 8. 允许的后续工作范围

仅限：间距微调、字体微调、对齐修正、响应式适配、交互状态完善、数据真实接入、Loading / Error / Empty State（同样遵循本基准：空态用文字 + 弱分割线，不用插画）、可用性与可访问性优化。

## 9. 遗留页面处置

旧 UI（`pages/TripWorkspace.vue` 关联的 shell/ 与表现组件）仍使用旧「珊瑚 + 卡片」风格——它们已在 Phase 2 删除/迁移计划内（见 `docs/execution/2026-09-01-workspace-shell/PHASE1-REPORT.md`），**不做风格翻新，直接按计划替换**。迁移过程中新写的任何界面必须直接使用 `tp-*` 令牌。

### 2026-09-01 全量审计结果

检测模式：`rounded-(xl|2xl|3xl|4xl)` / `shadow-(card|travel|soft|dialog)` / `glass-surface` / `bg-gradient` / `dest-*` / `primary-*`

| 区域 | 审计结果 | 处置 |
| --- | --- | --- |
| `src/workspace/` | **0 违规**，色值已全部收编为 `tp-*` 令牌 | ✓ 基准达标 |
| `src/components/ui/`（7 个共享原语） | 原 15 处违规 → 已重写为 0（Button/Badge/Card/Drawer/EmptyState/ErrorState/LoadingState 对齐 tp 令牌；保留 B15.1 R3 的 44px 触控闸口） | ✓ 已对齐 |
| `src/lib/`、`src/composables/` | 0 违规（纯逻辑层） | ✓ |
| `src/components/` 其余 31 个文件 | 旧风格（primary 彩色、rounded-xl/2xl、shadow-card、渐变） | Phase 2 按清单 REPLACE/DELETE，不翻新 |
| `src/pages/TripWorkspace.vue` | 1 个文件，旧风格入口（渐变加载屏、primary 按钮） | MIGRATE（业务状态机下沉后替换） |
| `src/main.css` | `glass-surface`、`dest-*` 渐变工具类 | 随旧页面删除时一并清理 |

**结论**：新旧风格当前以 `src/workspace/` + `src/components/ui/` 为合规边界；`components/` 其余文件是旧 UI 存量，随 Phase 2 API 接入逐步物理删除，禁止再向其添加任何新界面。

## 10. 一致性检查清单（每次改 UI 后过一遍）

- [ ] 只使用了 `tp-*` 令牌，无新硬编码 hex？
- [ ] 圆角 ≤ 6px？阴影为零？无渐变 / blur / 发光？
- [ ] 状态色只出现在 ✓ / ● / ! 小字形上？
- [ ] 没有新增 Card 包裹（能用 Divider 的用了 Divider）？
- [ ] 字号 ≤ 20px？信息密度没有下降？
- [ ] 遮住 Logo 后仍然像专业 Agent 工具？
