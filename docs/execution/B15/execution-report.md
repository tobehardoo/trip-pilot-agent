# B15 执行报告：规划评审界面用户化、中文化与信息降噪

- 状态：**B15_READY_FOR_REVIEW**（unstaged、未 commit、未 push；由独立验收 Agent 复跑并写 acceptance-report）
- 批次：B15（Web-only 用户化批次）
- BASELINE_HEAD：`d10e70cf354d096300c4a348d6aef585b8d82dc8`（`feat(platform): complete local-first trip planning release`）
- 关联：[plan.md](plan.md)（本批计划）
- 未创建 `docs/execution/B15/acceptance-report.md`（留给独立验收 Agent）

## 1. 开始前 Git 状态

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `d10e70cf354d096300c4a348d6aef585b8d82dc8`（本批全程未变） |
| staged | 空（`git diff --cached --name-only` 0 行，本批全程保持） |
| tracked 工作树 | 干净（`git status --short` 只剩 `.omo/`、`.serena/`、`docs/audits/`） |
| `.env` | 未跟踪且未修改 |

纪律遵守：无 reset/stash/checkout/restore/clean/rebase/amend；无 stage/commit/push；未触碰保护目录与 `.env`；未修改 Java/Python/contracts/Flyway/compose/RabbitMQ；未降低 coverage 门槛；未操作用户 `trip-pilot-prod`（本批无需后端环境，未起任何 Compose）。

## 2. 每轮 TDD：RED 真实失败 → GREEN 实现

### R0：基线 Characterization

运行现有测试记录旧行为（PlanningReviewPanel/FeasibilityReportPanel/TripDetail/TripDetailPlanEvaluation/feasibility）：**134/134 通过**，证明旧行为存在——`Review`/`Feasibility`/`Itinerary` 英文标签、`规划需要确认`/`待确认`徽标、英文 rule message、`查看验证详情`内含 validatorVersion/reasonCode/UUID、规则统计卡、候选行程全展开、`与当前正式版本对照`/`当前尚无正式版本`。旧测试断言这些旧文案，作为 R1-R5 改造的 RED 基线。

### R3（先行）：中文摘要 helper

- **RED**：新增 `apps/web/src/lib/feasibility-presentation.test.ts`（15 测试）——helper 不存在，导入失败（RED 真实）。
- **GREEN**：新增 `apps/web/src/lib/feasibility-presentation.ts`——`ruleName`/`countAffectedEntities`/`formatChineseDate`/`formatChineseDateList`/`ruleIssueSummary`/`entityDisplayName`。RuleId→中文名；UNKNOWN/FAIL 中文摘要（OPENING_HOURS 7 个/ VISIT_DURATION 4 个等数量文案）；数量仅来自 typed activity/poi refs；refs 缺失用无数量安全文案；未知 RuleId 降级（`该项信息暂时无法核实`/`该项安排需要调整`）；日期中文化（`8月17日`/`8月17日、8月18日`）；**不解析英文 message、不显示 code/UUID**。
- **验证**：15/15 PASS。

### R1：内部内容泄漏 RED→GREEN

- **RED**：重写 `apps/web/tests/PlanningReviewPanel.test.ts`（31 测试）为新行为断言——初始 **28/31 失败**（旧组件渲染 REVIEW/FEASIBILITY/ITINERARY、英文消息、validator/code、统计卡、验证详情 toggle）。
- **GREEN**：重写 `apps/web/src/components/PlanningReviewPanel.vue`——删除 Review 标签/`待确认`徽标/`规划需要确认`/验证详情 toggle/规则统计卡/英文 message/validator 元数据/`当前正式版本`措辞；仅保留必要专有名称（地点名）。同步更新 `apps/web/tests/FeasibilityReportPanel.test.ts`（8 测试，初始 7/8 RED）并重写 `FeasibilityReportPanel.vue`（VERIFIED 展示 `行程已验证并保存`/`已保存`，无规则墙/技术详情/修复历史）。
- **验证**：PlanningReviewPanel 31/31、FeasibilityReportPanel 8/8。

### R2：状态和动作 RED→GREEN

- RED 证据含于 R1 测试（初始失败）：`方案还需要完善`/`方案需要调整` 状态标题、徽标、说明、`修改要求`/`放弃本方案` 双动作均未实现；`确认/接受/保存候选` 按钮被断言不存在（3 个旧测试恰好通过，属旧组件已无接受按钮）。
- GREEN：用户状态真值表（UNVERIFIED→`方案还需要完善`/`部分信息待核实`；NEEDS_REPAIR→`方案需要调整`/`存在需要处理的问题`；malformed→`暂时无法读取规划结果`/`结果异常`）；`修改要求` emit `edit`（TripDetail 接 `openEditor` 打开已有约束编辑器，不创建任务）；`放弃本方案` emit `abandon`（复用现有取消 API）；无任何确认/接受/保存候选按钮；VERIFIED 走自动保存不进 review。
- 验证：31/31 含全部状态/动作断言。

### R4：候选方案降噪 RED→GREEN

- RED：初始失败——日卡全展开、无折叠摘要、交通全列出、无 aria-expanded、无键盘支持。
- GREEN：日卡默认折叠（`8月17日 · 1项安排 · 08:45–18:49` + 地点名 + `当天交通：N段 · 约X`）；展开后完整活动/时间/费用；交通二级可展开；`aria-expanded` + Enter/Space 键盘切换 + focus-visible；prefers-reduced-motion；天气 highlightDate 自动展开对应候选日并滚动（复用 TripDetail 既有 `candidateHighlightDate` 逻辑，仅高亮候选日不触碰已保存行程）。
- 验证：31/31（含键盘/展开/天气联动断言）。

### R5：正式行程空态 RED→GREEN

- RED：初始失败——`当前尚无正式版本`/`与当前正式版本对照`/禁用按钮仍在。
- GREEN：无已保存行程只显示 `方案验证通过后会自动保存为正式行程。`；有已保存行程显示 `已保存行程` + `与已保存行程相比` + 可理解差异（`新增N个地点`/`增加N天安排`/`预计交通时间增加X`）；无可靠差异不渲染空对照区；放弃候选保留已保存行程。
- 验证：31/31（R5 全部断言）。

### R6：App/E2E 集成

- App.test.ts/TripWorkspaceActions.test.ts 旧文案断言更新（`规划需要确认`→`方案需要调整`/`方案还需要完善`；`已验证`→`已保存`/`行程已验证并保存`；`候选待确认`→`等待规划结果`；`候选行程`→`预览方案`）；初始 7 个失败 → 更新后 **80/80 通过**。
- E2E：feasibility-outcomes/weather-window/golden-journeys 旧文案断言更新；初始 19/21 → **21/21 通过**。
- PlanningProgress.vue：`候选行程已生成，等待处理` → `预览方案已生成，等待处理`（视觉检查发现并修复的唯一术语泄漏）。
- 全量 unit **415/415**（含新增 PlanningProgress 折叠测试）。

## 3. 用户文案真值表（落地）

| 内部状态 | 主标题 | 徽标 | 用户说明 | 主按钮 | 次按钮 |
| --- | --- | --- | --- | --- | --- |
| UNVERIFIED | 方案还需要完善 | 部分信息待核实 | 已生成一份预览方案，但部分信息暂时无法核实，因此还不能保存 | 修改要求 | 放弃本方案 |
| NEEDS_REPAIR | 方案需要调整 | 存在需要处理的问题 | 当前安排存在冲突，请修改旅行要求后重新规划 | 修改要求 | 放弃本方案 |
| VERIFIED | 行程已验证并保存 | 已保存 | 行程已通过全部检查并保存为正式行程。 | —（自动保存） | — |
| malformed | 暂时无法读取规划结果 | 结果异常 | 系统无法安全读取本次规划结果，请重新规划 | —（安全失败） | — |

辅助文案：`修改并保存要求后，可以重新开始规划。`；空态：`方案验证通过后会自动保存为正式行程。`

## 4. 被删除/隐藏的内部字段

- 英文标签：`Review`、`Feasibility`、`Itinerary`（→`行程安排`）
- 术语：`待确认`、`候选待确认`、`规划需要确认`、`候选行程`（→`预览方案`）、`正式版本`/`当前正式版本`（→`已保存行程`）、`未验证`（→`部分信息待核实`）、`放弃候选`（→`放弃本方案`）、`与当前正式版本对照`（→`与已保存行程相比`）
- 技术字段：`validatorVersion`/`hard-validator-v*`、`reasonCode`、`ruleId`、`schemaVersion`、UUID、`reportId`、`validatedAt`、`itineraryFingerprint`、修复历史/规则明细/统计卡（总数/通过/失败/未知/不适用/缺失）、`查看验证详情`/`查看技术详情` toggle、英文 rule message
- 保留：地点/餐厅/Provider 等必要专有名称；`已保存`徽标

## 5. 不变量（全部保持）

1. 只有 VERIFIED 成为已保存行程 ✓（FEASIBILITY 面板仅 VERIFIED 渲染）
2. UNVERIFIED/NEEDS_REPAIR 不可手动确认 ✓（无确认/接受/保存候选按钮，测试断言）
3. 无绕过按钮 ✓
4. 不从 PlanEvaluation score 推导可行性 ✓（未触碰）
5. Java/Python Feasibility 语义未改 ✓（diff 零修改）
6. API/MQ/schema/DB 未改 ✓
7. candidate 与 current itinerary 隔离 ✓（测试断言）
8. API/SSE outcome fail-closed reader 未改 ✓（feasibility.ts 未触碰）
9. VERIFIED 自动持久化不变 ✓（E2E G26/COMPLETED 断言）
10. 放弃候选不删已保存行程 ✓（E2E abandon 测试）

## 6. 门禁数字

| 门禁 | 结果 |
| --- | --- |
| 新增定向测试 | feasibility-presentation 15/15、PlanningReviewPanel 31/31、FeasibilityReportPanel 8/8、PlanningProgress 4/4 |
| `pnpm test` 默认 ×2 | **415/415 × 2**（28.5s / 26.4s，flaky rate 0） |
| shuffle 固定 seed ×3 | seed `20260816`/`314159`/`271828` 均 **415/415** |
| `pnpm test:coverage` | **415/415**；All files stmts 95.41/branch 85.91/funcs 94.82/lines 95.41 |
| 触碰生产文件每项 ≥80% | PlanningReviewPanel stmts 97.4/branch 84.4/funcs 100；FeasibilityReportPanel 100/100；feasibility-presentation 88.8/87.1/83.3；PlanningProgress 100/97.8/100；TripDetail 95.3/83.9/86.2 ✓ |
| `pnpm typecheck` | vue-tsc -b 通过 |
| `pnpm build` | vite build 通过（dist 产物正常） |
| `CI=1 pnpm test:e2e` | **21 passed**（首轮 20+1 flaky 为 release-smoke 地图定位按钮 AMap SDK 加载时序——单独重跑 2/2 通过，与本批无关，B14_FIX 同结论） |
| open handles / unhandled rejection | exit 0，无挂起 |

## 7. 1440×900 检查

真实浏览器截图（`C:\Windows\Temp\opencode\b15-screens\`，不入仓库）：状态标题与双按钮在首屏（scrollY=0 boundingBox 断言通过）、预览方案摘要在首屏、待核实信息紧邻、无横向滚动（overflow px=0）、无页面错误（0 errors）、无内部英文标签/code/UUID（DOM 文本扫描 0 LEAK）。

## 8. 390×844 检查

真实浏览器截图（mobile 视口）：按钮不溢出、日卡可展开（截图含 expanded）、无横向溢出（overflow px=0）、无页面错误、无技术字段（DOM 文本扫描 0 LEAK）。

## 9. 精确修改文件清单

**修改（M）**：
- `apps/web/src/components/PlanningReviewPanel.vue`
- `apps/web/src/components/FeasibilityReportPanel.vue`
- `apps/web/src/components/TripDetail.vue`
- `apps/web/src/components/PlanningProgress.vue`（仅 waiting_user 文案）
- `apps/web/src/pages/TripWorkspace.vue`（未修改——`修改要求`通过 TripDetail 内部 openEditor 接线，无需 TripWorkspace 改动）
- `apps/web/vite.config.ts`（coverage include 增加 feasibility-presentation.ts/PlanningProgress.vue）
- `apps/web/tests/PlanningReviewPanel.test.ts`
- `apps/web/tests/FeasibilityReportPanel.test.ts`
- `apps/web/tests/App.test.ts`
- `apps/web/tests/TripWorkspaceActions.test.ts`
- `apps/web/tests/PlanningProgress.test.ts`
- `apps/web/e2e/feasibility-outcomes.spec.ts`
- `apps/web/e2e/weather-window.spec.ts`
- `apps/web/e2e/golden-journeys.spec.ts`

**新增（A）**：
- `apps/web/src/lib/feasibility-presentation.ts`
- `apps/web/src/lib/feasibility-presentation.test.ts`
- `docs/execution/B15/plan.md`
- `docs/execution/B15/execution-report.md`（本文件）

## 10. diff 范围证明

`git diff --name-only` 全部为 `apps/web/` 文件；**Java/Python/contracts/Flyway/compose/RabbitMQ 零修改**（0 hits）；`apps/web/e2e/release-smoke.spec.ts`/`v2-critical-journeys.spec.ts` 未触碰（无关）；`src/lib/feasibility.ts`（outcome fail-closed reader）未触碰。

## 11. 仓库检查

- `git diff --check`：0 错误
- Markdown links：272 / 0 broken
- staged：空（0 行）
- secret 扫描：0 命中
- 保护目录：`.omo/`/`.serena/`/`docs/audits/` 保持 untracked（23 项），`.env` 未触碰
- HEAD 未变：`d10e70cf354d096300c4a348d6aef585b8d82dc8`
- 临时脚本（b15-*.tmp.mjs）已清理；截图保留在 Temp 不入仓库

## 12. 残留风险（仅登记）

- `LIVE GUIDE INTELLIGENCE` 英文标签存在于 GuideIntelligencePanel（不在本批允许修改范围，未处理；不在任务书删除清单中，登记观察）。
- release-smoke 地图定位按钮 flaky 为既有环境时序（AMap SDK 加载），与本批无关，B14_FIX 验收同结论。
- 跨省同名城市无省份维度（既有观察，维持）。

## 13. 完成条件核对

- [x] R0-R6 全部 RED→GREEN（每轮真实 RED 记录见 §2）
- [x] 用户状态真值表四态落地，无确认/接受/保存候选按钮
- [x] 内部内容（英文标签/code/UUID/validator/统计卡/英文消息/技术详情）全部移除
- [x] 问题摘要纯中文、数量来自 typed refs、不解析英文 message、N>3 折叠
- [x] 预览方案默认折叠、展开不丢数据、交通二级、键盘/aria 无障碍、天气联动正确
- [x] 已保存行程空态/有态正确，放弃不删已保存行程
- [x] 1440×900 与 390×844 视觉检查通过（0 溢出 0 错误 0 LEAK）
- [x] 全门禁通过（unit×2/shuffle×3/coverage/typecheck/build/e2e/仓库检查）
- [x] Java/Python/contracts 零修改；未 stage/commit/push；保护目录未处理
- [x] 输出 `B15_READY_FOR_REVIEW` + `RELEASE_FREEZE_BLOCKED_PENDING_B15_ACCEPTANCE` 后停止

---

# B15.1 执行报告：用户可见摘要正确性与移动端交互收口

- 状态：**B15_1_READY_FOR_REVIEW**（unstaged、未 commit、未 push；等待独立验收 Agent 在原 acceptance-report 追加复验结论）
- 前置：B15 独立验收输出 `B15_NEEDS_CORRECTION / RELEASE_FREEZE_BLOCKED`（2 个 Important：去重缺失、日期未排序；2 个明确 Minor：移动端按钮 40px、执行报告清单不实）
- BASELINE_HEAD：`d10e70cf354d096300c4a348d6aef585b8d82dc8`（本批全程未变）
- 未创建/修改 `docs/execution/B15/acceptance-report.md`（只读）；`B15_NEEDS_CORRECTION` 历史保留

## 14. 开始前基线

branch `codex/feasibility-foundation`；HEAD `d10e70c`；staged 空；B15 改动全部 unstaged；acceptance-report 存在且含 `B15_NEEDS_CORRECTION`/`RELEASE_FREEZE_BLOCKED`；保护目录 23 项原状；`.env` 未跟踪。Java/Python/contracts/Flyway/compose 零 B15 改动。

## 15. 每轮 TDD

### R1：affected entity 数量去重

**RED**：`feasibility-presentation.test.ts` 新增 9 个去重测试，初始 **12 failed / 22 passed**（去重 8 用例 + 日期 4 用例混合失败）。关键 RED 失败值：
- `identical activity refs repeated count once`：expected 2 to be 1
- `three refs with only two unique entities count two`：expected 3 to be 2
- `input order does not change the count`：expected 3 to be 2
- `same value as activity and poi counts as two`：expected 3 to be 2（旧实现合并了 kind）
- `ruleIssueSummary with duplicate refs`：expected '3个地点...' to be '2个地点...'

**GREEN**：`countAffectedEntities` 改用 canonical typed identity `(kind, value)` 去重（`seen.add(\`${kind}:${value}\`)`）；空 value/未知 kind/非 typed ref 跳过；不解析 UUID；不解析英文 message；不修改输入数组。

**去重真值表**：

| 输入 | 期望 | 实测 |
| --- | --- | --- |
| `activity:A` ×2 | 1 | 1 ✓ |
| A、B、A（3 refs 2 唯一） | 2 | 2 ✓ |
| 顺序颠倒 | 相同 | 相同 ✓ |
| `activity:X` + `poi:X`（同 value 异 kind） | 2 | 2 ✓ |
| `poi:B001` ×2 + `poi:B002` | 2 | 2 ✓ |
| `activity:`/`   `/unknown/plain/`:`/'' | 0 | 0 ✓ |
| undefined/null/[] | 0 不抛 | 0 ✓ |
| 输入数组不变 | 不变 | 不变 ✓ |
| OPENING_HOURS 重复 refs 摘要 | 2个地点 | 2个地点 ✓ |

### R2：受影响日期稳定排序

**RED**（同上轮，12 failed 含）：`formatChineseDateList(['2026-08-18','2026-08-17'])` → `8月18日、8月17日`（旧按输入顺序）；跨年显示 `1月2日、12月31日` 无年份；malformed 日期泄漏 `NaN月NaN日`。

**GREEN**：`parseIsoDate` 严格校验 `YYYY-MM-DD` + 闰年感知天数（无本地时区 Date 解析）；`formatChineseDateList` 先校验、去重（Map by ISO key）、按 [year, month, day] 数字排序、再格式化；跨年列表含年份（`2025年12月31日、2026年1月2日`）；malformed/空/不可能日期安全忽略；不修改输入数组。

**日期排序真值表**：

| 输入 | 期望 | 实测 |
| --- | --- | --- |
| `['2026-08-18','2026-08-17']` | `8月17日、8月18日` | ✓ |
| 重复日期 | 去重 | ✓ |
| 跨月 `['2026-08-02','2026-07-31']` | `7月31日、8月2日` | ✓ |
| 跨年 `['2026-01-02','2025-12-31']` | `2025年12月31日、2026年1月2日` | ✓ |
| 闰日 `['2024-03-01','2024-02-29']` | `2月29日、3月1日` | ✓ |
| 输入顺序不同 | 输出一致 | ✓ |
| malformed/''/2026-02-30 | 安全忽略 | ✓ |
| 空输入 | '' | ✓ |
| 输入数组不变 | 不变 | ✓ |
| 同年简洁/跨年含年 | 正确 | ✓ |

**验证**：`feasibility-presentation.test.ts` **34/34 PASS**（8 去重 + 10 日期 + 16 既有）。

### R3：移动端按钮点击高度

**RED**：PlanningReviewPanel.test.ts 新增断言「修改要求」「放弃本方案」class 含 `h-12`（48px ≥44px）——初始 **1 failed**（两按钮当前 `size="md"` = `h-10` = 40px）。

**GREEN**：两按钮 `size` 从 `md` 改为 `lg`（`h-12` = 48px ≥44px）——最小改动，不新增 CSS、不引入依赖、不改变动作语义（修改要求仍 emit edit 只开编辑器；放弃仍 emit abandon 走 cancel 链路；无新增接受/确认/保存候选按钮）。

**验证**：PlanningReviewPanel.test.ts **32/32 PASS**（含新按钮尺寸断言）；视觉 bounding-box 证据见 §17（48px）。

### R4：执行报告真实性修正

本 B15.1 章节明确承认并记录：
1. 原 `countAffectedEntities` **未去重**（B15 独立验收确认，重复 typed refs 重复计数）。
2. 原 `formatChineseDateList` **未稳定排序**（按输入顺序输出，跨年无年份，malformed 泄漏 `NaN月NaN日`）。
3. 原 §9 文件统计**不准确且有重复路径**（M 列表 14 项含本应 A 的 feasibility-presentation.ts/test 与 plan.md，与 A 列表 4 项重复；§1/§6 声称"17 修改 + 4 新增"）。

`entityDisplayName` 脆弱性（activity 分支 `Number(UUID)` 回退）登记为**非阻断观察**：当前无调用方使用、不泄漏 UUID，本批不扩大修复范围。

## 16. 精确最终 A/M 文件清单（B15.1 完成后，git 实际状态）

**独立验收时快照（B15 验收）：13 M + 4 A**（见 B15 acceptance-report §2）。

**B15.1 完成后最终实际状态（13 M + 5 A，每路径唯一）**：

```
M apps/web/e2e/feasibility-outcomes.spec.ts
M apps/web/e2e/golden-journeys.spec.ts
M apps/web/e2e/weather-window.spec.ts
M apps/web/src/components/FeasibilityReportPanel.vue
M apps/web/src/components/PlanningProgress.vue
M apps/web/src/components/PlanningReviewPanel.vue
M apps/web/src/components/TripDetail.vue
M apps/web/tests/App.test.ts
M apps/web/tests/FeasibilityReportPanel.test.ts
M apps/web/tests/PlanningProgress.test.ts
M apps/web/tests/PlanningReviewPanel.test.ts
M apps/web/tests/TripWorkspaceActions.test.ts
M apps/web/vite.config.ts
A apps/web/src/lib/feasibility-presentation.ts
A apps/web/src/lib/feasibility-presentation.test.ts
A docs/execution/B15/plan.md
A docs/execution/B15/execution-report.md
A docs/execution/B15/acceptance-report.md
```

（B15.1 增量：M `PlanningReviewPanel.vue`、M `PlanningReviewPanel.test.ts`、A `feasibility-presentation.ts`、A `feasibility-presentation.test.ts`、A `execution-report.md`（本追加）——均在上述清单内，无新路径。）

## 17. 验证门禁

| 门禁 | 结果 |
| --- | --- |
| 新增定向测试 | feasibility-presentation 34/34、PlanningReviewPanel 32/32 |
| PlanningReviewPanel/FeasibilityReportPanel 定向 | 32/32 + 8/8 |
| 与修改要求/放弃/已保存相关的 App 测试 | App.test.ts + TripWorkspaceActions 定向通过（全量内） |
| `pnpm test` ×2 | **435/435 × 2** |
| shuffle seed 20260816 / 314159 / 271828 | 435/435 × 3 |
| 随机 seed（运行时生成） | 435/435 |
| coverage | 435/435；All files stmts/branch/funcs/lines 全 ≥80%（feasibility-presentation 含新分支仍 ≥80%） |
| typecheck / build | vue-tsc -b 通过 / vite build 通过 |
| `CI=1 pnpm test:e2e` | **21/21 passed** |
| 视觉（1440×900 + 390×844） | 0 横向溢出；0 控制台错误；0 内部术语泄漏；移动端按钮 bounding-box 高 **48px ≥44px** |
| `git diff --check` | 0 错误 |
| Markdown links | 273 / 0 broken |
| secret 扫描 | 0 命中 |
| staged | 空（0 行） |
| Java/Python/contracts/Flyway/compose | **零修改**（`git diff --name-only` 过滤 0 hits） |
| acceptance-report | **未修改**（mtime 保持 B15 验收时点；内容含 `B15_NEEDS_CORRECTION`/`RELEASE_FREEZE_BLOCKED` 原样） |

## 18. 回归不变量

- VERIFIED 自动持久化不变 ✓；UNVERIFIED/NEEDS_REPAIR 不可成为正式版本 ✓；修改要求只开编辑器 ✓；放弃走 cancel 链路 ✓；malformed fail-closed ✓；不解析英文 rule message ✓（helper 只读 RuleId/outcome/typed refs）。
- UI 无 REVIEW/FEASIBILITY/ITINERARY/validatorVersion/reasonCode/ruleId/schemaVersion/UUID/英文规则消息/技术统计墙 ✓（B15 验收 0 泄漏结论 + 本批未引入）。
- Java/Python/契约行为零修改 ✓。

## 19. 残留边界（仅登记）

- `entityDisplayName` 脆弱性：无调用方、不泄漏 UUID，登记非阻断观察（不修复）。
- B15 既有 Minor（移动端状态区需滚动、comparisonDiffs title 集合语义）维持登记。
- 未声称已独立复验 PASS（等待独立验收 Agent 追加复验结论）。

---

# B15.1.1 文档统计纠正

- 状态：**PASS / COMMITTED（本提交）**——授权依据：`B15_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT` + `RELEASE_READY`（独立验收最终复验，见 acceptance-report §26）；原 `B15_1_SMALL_FIX_READY_FOR_REVIEW`（unstaged、未 commit、未 push；等待 B15 最终重新验收）历史完整保留
- 前置：B15.1 独立重新验收输出 `B15_NEEDS_SMALL_FIX`——唯一未关闭项为 B15.1 章节 Web 全量测试数字 416/416 与独立复跑实际 435/435 不符。
- 本批仅修改 `docs/execution/B15/execution-report.md`；未修改任何业务代码、测试、配置、契约或验收报告。

## 20. 修正内容

- **原（错误）**：B15.1 章节门禁区（§17）4 处 `416/416`——`pnpm test` ×2、shuffle 20260816/314159/271828、随机 seed、coverage。
- **现（正确）**：以上 4 处全部修正为 `435/435`（`pnpm test` ×2 写作 `435/435 × 2`）。
- **原因**：415（B15 基线） + 19（B15.1 新增 feasibility-presentation 去重/日期测试） + 1（B15.1 新增 PlanningReviewPanel 按钮尺寸测试） = **435**。原 416/416 是统计笔误（19 个新增 helper 测试被漏计）。
- **独立验收证据**：B15.1 独立重新验收已实际复跑 435/435（unit ×2、shuffle ×4、coverage），非本批伪造。
- 定向测试 34/34、32/32、8/8 与 E2E 21/21 原已正确，未改动。
- 本批没有修改代码或测试，没有伪造新的测试运行结果；不声称已经获得最终 PASS（等待独立验收 Agent 在 acceptance-report 追加 B15.1.1 复验结论）。
