# B15 独立验收报告

- 状态：**B15_NEEDS_CORRECTION / RELEASE_FREEZE_BLOCKED**（详见 §12）
- 验收方式：独立审查 + 独立复跑 + 对抗性 UI 验证（不复用执行 Agent 的任何测试输出；未修改任何代码/测试/文档；未 stage/commit/push；用户 trip-pilot-prod 未操作）
- 验收日期：2026-08-17
- 唯一写入：本报告（`docs/execution/B15/acceptance-report.md`）

## 1. 基线核对

| 项 | 要求 | 实测 |
| --- | --- | --- |
| branch | codex/feasibility-foundation | ✓ |
| HEAD | d10e70cf354d096300c4a348d6aef585b8d82dc8 | ✓ |
| log -1 | feat(platform): complete local-first trip planning release | ✓ |
| staged | 空 | ✓（`git diff --cached --name-only` 0 行） |
| B15 改动 | 全部 unstaged/untracked | ✓（13 M + 4 A，无 staged） |
| acceptance-report | 验收前不存在 | ✓ |
| 保护项 | `.omo/`/`.serena/`/`docs/audits/` untracked（23 项）、`.env` 未跟踪 | ✓ |
| 用户栈 | trip-pilot-prod 不进入操作 | ✓（未操作） |

## 2. Diff 范围审计

**真实状态**：13 M（全 `apps/web/`）+ 4 A（`feasibility-presentation.ts`/`.test.ts`、`docs/execution/B15/plan.md`/`execution-report.md`）。

- Java/Python/contracts/Flyway/RabbitMQ/compose：**零修改**（`git diff --name-only` 过滤 0 hits）✓
- `.env`/保护目录：零修改 ✓
- 无生成产物/截图/coverage/test-results/日志入仓库 ✓（截图在 Temp）
- 无 `.only`/`.skip` ✓（触碰文件扫描 0）
- coverage 阈值 80 未变（对比 HEAD）✓
- playwright retries=2/timeout=60s 为既有配置（非 B15 改动）✓
- 无 `as any`/`@ts-ignore`/`@ts-expect-error`/`v-html` ✓（触碰文件扫描 0）
- 无新增第三方依赖（package.json 零 diff）✓
- vite.config.ts 仅 +2 coverage include（PlanningProgress.vue、feasibility-presentation.ts）✓

**判定**：范围合规；**但执行报告 §9 文件清单自身矛盾**（M 列表 14 项含本应 A 的 feasibility-presentation.ts/test 与 plan.md，A 列表 4 项重复列出；§1/§6 声称"17 修改 + 4 新增"与真实 13 M 不符）——见 §11 对账。

## 3. 架构不变量审查（12 项）

| # | 不变量 | 结果 |
| --- | --- | --- |
| 1 | UNVERIFIED 不可被确认/保存 | ✓ 对抗探针：无确认/接受/保存候选/强制使用按钮 |
| 2 | NEEDS_REPAIR 不可被确认/保存 | ✓ 同探针 |
| 3 | VERIFIED 沿用后端自动持久化 | ✓ 不进入 review；E2E completed 断言 `行程已验证并保存`/`已保存`（不依赖前端确认） |
| 4 | 无确认候选/接受风险/仍然保存/强制使用按钮 | ✓ 探针断言 queryByText 全 null |
| 5 | 修改要求只打开已有编辑器 | ✓ `openEditor` 仅设 editing=true 本地状态；不 POST task/不 PUT version；单元探针 `emitted('edit')` 且无 start/create emit |
| 6 | 放弃本方案复用 abandon 链路 | ✓ `handleAbandonCandidate` → `cancelPlanningTask`；清除 candidate/report；E2E abandon 测试保留正式行程 |
| 7 | Candidate 与已保存行程隔离 | ✓ 组件 props 独立；E2E weather 联动只高亮候选日 |
| 8 | readPlanningTaskOutcome/EventOutcome fail-closed 未改 | ✓ `feasibility.ts` 未触碰（不在 diff） |
| 9 | UI 不从体验评分推导硬可行性 | ✓ 未触碰 PlanEvaluation 逻辑 |
| 10 | UI 不解析英文 message 推导 outcome/原因/数量 | ✓ `ruleIssueSummary` 只用 RuleId+outcome+typed refs；对抗探针恶意 message 不进 DOM |
| 11 | 不复制第二套 Feasibility 聚合器 | ✓ 新增 presentation helper 仅展示映射，不聚合状态 |
| 12 | malformed 不显示为可用/已保存/待确认 | ✓ 对抗探针：显示 `暂时无法读取规划结果`/`结果异常`/安全中文，无已保存/待确认 |

**判定**：12 项全部成立。

## 4. 展示映射审查（feasibility-presentation.ts）

代码审查确认：权威 RuleId/outcome 输入；数量来自 typed activity/poi refs（transit/text/unknown 忽略）；不解析 raw message；不显示 ref 原值；未知 RuleId 中文兜底；UNKNOWN/FAIL 不同语义；PASS/NOT_APPLICABLE 不进问题区；中文日期。

**对抗性探针（独立 7 用例）发现 2 个缺陷**：

1. **`countAffectedEntities` 不去重（Important）**：重复 activity refs 计数 3（期望 2）。任务书 §四 明确要求"typed refs 正确去重"。实际影响：同一活动被多规则/多 ref 引用时数量虚高（如 OPENING_HOURS 显示"7个地点"实为 4 个唯一地点）。
2. **`formatChineseDateList` 不排序（Important）**：输入 `['2026-08-18','2026-08-17']` 输出 `8月18日、8月17日`（期望稳定升序 `8月17日、8月18日`）。任务书 §十一 要求"受影响日期：中文且稳定排序"。

其余 5 用例通过（mixed refs 计数 2、缺失 refs 安全、恶意 message 不进 DOM、未知 RuleId 兜底、entityDisplayName 不返回 UUID）。`entityDisplayName` 的 activity 分支用 `Number(parsed.value)`（UUID→NaN）回退 find——逻辑脆弱但**不会泄漏 UUID**（Minor 观察，当前无调用方使用该函数）。

## 5. 用户内容泄漏审查（真实 DOM 断言）

独立视觉脚本（route 拦截 mock，真实渲染）在 1440×900 与 390×844 对 `body.innerText` 扫描：

- 泄漏词表（REVIEW/FEASIBILITY/ITINERARY/hard-validator/validatorVersion/schemaVersion/reasonCode/ruleId/evidenceId/reportId/`activity:`/`transit:`/`poi:`/PASS/FAIL/UNKNOWN/NOT_APPLICABLE/attemptIndex/待确认/候选待确认/规划需要确认/候选行程/正式版本）：**两个视口均 0 泄漏** ✓
- 允许内容（故宫博物院/奥华餐厅/AMap/金额/时间/交通方式）正常渲染 ✓
- 非 CSS 隐藏：组件模板无隐藏类；泄漏词确实不在 accessible tree ✓

**判定**：通过（未见 `待确认`/`候选待确认`/`规划需要确认`/`REVIEW`/`FEASIBILITY`/`ITINERARY`/UUID/英文消息）。

## 6. 状态真值表验收

| 状态 | 实测（对抗探针 + 视觉脚本） |
| --- | --- |
| UNVERIFIED | `方案还需要完善`+`部分信息待核实`+说明+`修改要求`+`放弃本方案`；无确认/保存动作 ✓ |
| NEEDS_REPAIR | `方案需要调整`+`存在需要处理的问题`+冲突说明+双动作；无接受按钮 ✓ |
| VERIFIED | 不进 review；`行程已验证并保存`+`已保存`（E2E 3 处断言）✓ |
| malformed | `暂时无法读取规划结果`+`结果异常`+安全中文；无已保存/待确认/raw payload ✓ |

## 7. 信息层级验收

真实 DOM 顺序：状态与操作 → 预览方案 → 待核实信息（N）→ 已保存行程/自动保存说明。

- `预览方案` 位于问题详情前 ✓（视觉脚本 orderOk=true）
- 无规则统计控制台 ✓、无技术详情 toggle ✓、无默认展开规则墙 ✓
- 问题 ≤3 全显示、>3 前 3 条 + `查看全部 N 项` 展开 ✓（执行 Agent 测试 + 组件审查）
- 展开后仍无技术字段 ✓

## 8. 预览方案降噪验收

- 日卡默认折叠 ✓（视觉脚本 aria-expanded=false 读取）
- 折叠摘要：中文日期/活动数/时间范围/地点名/交通汇总 ✓
- 展开后活动/时间/费用/交通完整 ✓（组件模板）
- 交通二级展开 ✓、aria-expanded 一致 ✓
- Enter/Space 键盘展开/收起 ✓（视觉脚本 afterEnter=true、Space 切换 true/false）
- focus-visible 存在 ✓（组件 class）
- 状态不只靠颜色 ✓（badge 文本 + aria-expanded）
- 天气联动：TripDetail `selectWeatherDate` 只高亮候选日（既有逻辑未改）✓

## 9. 操作链验收

- **修改要求**：`openEditor` 仅本地 editing 状态；不 POST task/不 PUT version/不改已保存行程/candidate 不消失（单元探针 + 代码审查）✓
- **放弃本方案**：`handleAbandonCandidate` → `cancelPlanningTask`（DELETE）；清除 candidate/report；E2E abandon 测试：`规划已取消` + 正式行程保留 + deleteCalls=1 ✓

## 10. 已保存行程区域验收

- 无已保存：`方案验证通过后会自动保存为正式行程。`（无"与当前正式版本对照"/"当前尚无正式版本"/禁用按钮/巨型空白框）✓
- 有已保存：`已保存行程` + `与已保存行程相比` + 差异（新增N个地点/增加N天安排/交通时间增减）；无可靠差异不渲染空对照区（comparisonDiffs 为空时 v-if 隐藏）✓
- 放弃 candidate 后已保存保留（E2E）✓

## 11. 独立测试门禁

| 门禁 | 独立复跑结果 |
| --- | --- |
| 定向测试 | PlanningReviewPanel 31、FeasibilityReportPanel 8、PlanningProgress 4、feasibility-presentation 15 = **58/58** |
| `pnpm test` ×2 | **415/415 × 2**（29.5s / 25.3s） |
| shuffle seed 20260816 | 415/415 |
| shuffle seed 314159 | 415/415 |
| shuffle seed 271828 | 415/415 |
| 随机 seed 889897（验收生成） | 415/415 |
| `pnpm test:coverage` | **415/415**；All files stmts 95.41/branch 85.91/funcs 94.82/lines 95.41 |
| 触碰文件每项 ≥80% | FeasibilityReportPanel 100/100/100/100；PlanningProgress 100/97.8/100/100；PlanningReviewPanel 97.4/84.4/100/100；TripDetail 95.3/83.9/86.2/100；feasibility-presentation 88.8/87.1/83.3/100 —— **全部 ≥80%** ✓ |
| typecheck | vue-tsc -b 通过 |
| build | vite build 通过 |
| `CI=1 pnpm test:e2e` | **21/21 passed**（独立复跑，无 AMap 时序失败复现） |
| open handles / unhandled | E2E exit 0；无挂起 |
| 仓库 | links 273/0；diff --check 0 错；secret 0；staged 空；HEAD 未变；保护目录 23 项原状；Java/Python/contracts/Flyway/compose 零 diff |

## 12. 视觉验收（独立浏览器）

| 项 | 1440×900 | 390×844 |
| --- | --- | --- |
| 横向溢出 | 0px ✓ | 0px ✓ |
| 页面错误 | 0 ✓ | 0 ✓ |
| 内部术语泄漏 | 0 ✓ | 0 ✓ |
| 核心文案 | 全部渲染 ✓ | 全部渲染 ✓ |
| 状态标题首屏 | y=704+28≤900 ✓ | y=844 贴边（需轻微滚动）⚠️ |
| 日卡默认折叠 | ✓ | ✓ |
| Enter/Space 键盘 | ✓ | ✓ |
| tab 顺序（修改要求→放弃本方案） | ✓ | ✓ |
| 按钮尺寸 | 88×40 / 126×40 | 同左（40px 高 < 44px 建议）⚠️ |
| 信息层级顺序 | 正确 ✓ | 正确 ✓ |

⚠️ Minor 观察（非阻断）：390×844 下状态按钮 y=944 需滚动才能点击（DOM 可见、功能正常）；按钮高 40px（WCAG 建议 44px）。截图存 `C:\Windows\Temp\opencode\b15-accept-screens\`（不入仓库）。

## 13. execution-report 真实性对账

| 项 | 对账 |
| --- | --- |
| R0 旧行为 characterization | ✓ 134/134 旧断言证明旧文案（与我独立观察一致） |
| R1-R6 每轮 RED→GREEN | ✓ 报告 RED 数字（28/31、7/8）与我独立重放一致；RED 因目标行为缺失（非 import/fixture 错误） |
| 415/415 可复现 | ✓ 独立复跑一致 |
| coverage 数字真实 | ✓ 独立复跑一致；include 白名单含 B15 新文件（非排除高风险文件） |
| 触碰文件每项 ≥80% | ✓ 独立确认 |
| E2E 21/21 真实 | ✓ 独立复跑 21/21 |
| AMap flaky 披露 | ✓ 报告如实披露首轮 flaky 并记录单独重跑 2/2；我复跑未复现（与本批无关） |
| Temp 截图存在且未入仓库 | ✓ |
| Java/Python/contracts 零修改 | ✓ |
| **文件清单** | ✗ **不实**：报告 §9 M 列表 14 项（含本应 A 的 feasibility-presentation.ts/test 与 plan.md）且与 A 列表 4 项重复；§1/§6 声称"17 修改 + 4 新增"与真实 **13 M + 4 A** 不符。§9 内部矛盾（M 与 A 重复列出同一文件） |

**判定**：门禁数字全部真实可复现；唯一不实为 §9 文件清单数量/归属表述（§1/§6 的"17 修改"与实际 13 M 不符；§9 列表自身 M/A 重复）。属报告准确性缺陷（Important 级？见 §14 定性）。

## 14. 发现项及严重级别

- **Important 1（阻断修正）**：`countAffectedEntities` 不去重——重复 typed activity/poi refs 导致数量虚高（如 3 个 ref 含 2 唯一 → 显示 3）。任务书 §四 明确要求去重。影响 OPENING_HOURS/VISIT_DURATION 等数量型中文摘要的用户可见正确性。
- **Important 2（阻断修正）**：`formatChineseDateList` 不排序——受影响日期按输入顺序输出，非稳定升序（输入 18→17 输出 `8月18日、8月17日`）。任务书 §十一 要求"中文且稳定排序"。多日期场景（如跨日规则）日期顺序错乱。
- **Minor 观察 1**：390×844 状态按钮 y=944 需滚动访问（功能正常、DOM 可见；任务书 mobile 要求"按钮不被遮挡"——按钮可滚动到达且 isVisible=true，判定 Minor 不阻断）。
- **Minor 观察 2**：按钮高 40px < 44px WCAG 建议（触摸目标建议值，非硬性门禁；桌面 E2E 正常）。
- **Minor 观察 3**：`entityDisplayName` activity 分支 `Number(UUID)` 逻辑脆弱（NaN 回退），但当前无调用方使用且不泄漏 UUID。
- **Minor 观察 4**：comparisonDiffs 用 title 集合比较——同标题不同 ID 的活动不会计入"新增"（语义可接受，极端场景可能漏报差异）。
- **Minor 观察 5**：执行报告 §9 文件清单 M/A 重复且数量（17）与真实（13 M）不符——报告准确性缺陷（不改变验收结论但需修正报告或由收口授权清单校正）。

**定性说明**：Important 1/2 为 helper 用户可见逻辑缺陷，直接影响中文摘要正确性（数量虚高、日期乱序），按任务书 §四/§十一 明确要求未满足 → **需修正后才能 PASS**。未发现 Critical（无 UNVERIFIED 可保存、无泄漏、无 fail-open、无范围越界）。

## 15. 判定

**B15_NEEDS_CORRECTION**
**RELEASE_FREEZE_BLOCKED**

- 架构不变量 12 项全过；四态真值表全过；信息层级/降噪/操作链/已保存区域全过；泄漏 0；门禁全部独立复跑通过；视觉基本通过。
- **但 2 个 Important 缺陷**：helper 去重缺失 + 日期排序缺失（任务书 §四/§十一 明确要求）。这两个直接影响普通用户看到的中文摘要正确性，不可在 PASS 状态下带病收口。
- Minor 观察 5（执行报告文件清单不实）记录在案，不阻断修正方向但需在收口清单校准中纠正。

### 必须修正（实现缺陷）

1. `countAffectedEntities` 对 activity/poi typed refs 去重（唯一 ref 计数）。
2. `formatChineseDateList` 按 ISO 日期升序稳定排序后中文输出。
3. （建议）执行报告 §9 文件清单数量/归属纠正（M=13、A=4；去除 M/A 重复项）。

### 复验通过项

架构不变量、四态真值表、泄漏检查、信息层级、降噪、操作链、已保存区域、对抗性状态探针（6/6）、门禁全部（58/58、415×2、shuffle×4、coverage 全 ≥80%、typecheck/build/e2e 21/21）、视觉（0 溢出/0 错误/0 泄漏）。

### 证据与清理

- 独立探针（Temp，不落仓库）：`feasibility-presentation.probe.test.ts`（7 用例，2 缺陷确认）、`state-truth.probe.test.ts`（6/6 通过）、`b15-accept-visual.mjs`/`b15-mobile-detail.mjs`（视觉 DOM 断言）。探针文件已从仓库清理。
- 独立视觉截图：`C:\Windows\Temp\opencode\b15-accept-screens\`（desktop/mobile top，不入仓库）。
- 本报告为唯一写入文件；未 stage/commit/push；未修改任何代码/测试/文档；用户 trip-pilot-prod 未操作。

---

# B15.1 独立复验（追加章节）

- 状态：**B15_NEEDS_SMALL_FIX / RELEASE_FREEZE_BLOCKED**（详见 §21）
- 验收方式：独立审查（两遍：diff 实现审查 + 反证审查）+ 独立复跑 + 对抗性真值表 + 真实浏览器视觉（不复用执行 Agent 数字；未修改任何代码/测试/执行报告；未 stage/commit/push；用户 trip-pilot-prod 未操作）
- 验收日期：2026-08-17
- 前置：B15 首次验收 `B15_NEEDS_CORRECTION`（2 Important：去重缺失、日期未排序）+ 2 Minor（按钮 40px、报告清单不实）。B15.1 修复批次交付 `B15_1_READY_FOR_REVIEW`。本章节复验 B15.1 修复；原 NEEDS_CORRECTION 历史完整保留。

## 20. B15.1 复验基线

| 项 | 要求 | 实测 |
| --- | --- | --- |
| branch | codex/feasibility-foundation | ✓ |
| HEAD | d10e70cf354d096300c4a348d6aef585b8d82dc8 | ✓（全程未变） |
| staged | 空 | ✓（0 行） |
| B15/B15.1 改动 | 全部 unstaged | ✓（13 M + 5 A） |
| acceptance-report | 保留 `B15_NEEDS_CORRECTION`/`RELEASE_FREEZE_BLOCKED` | ✓（原历史未动） |
| 保护项/.env | 未处理 | ✓（23 项原状；`.env` 未跟踪） |
| Java/Python/contracts/Flyway/compose | 零改动 | ✓（git diff 过滤 0 hits） |
| 用户栈 | 未操作 | ✓ |

## 21. C1–C6 逐项结论

### C1：实体数量去重 — PASS

独立对抗性探针（临时，验收后删除）18/18 通过，去重真值表：

| 输入 | 期望 | 实测 |
| --- | --- | --- |
| `activity:A` ×2 | 1 | 1 ✓ |
| A、B、A | 2 | 2 ✓ |
| 顺序颠倒 | 2 | 2 ✓ |
| `activity:X` + `poi:X` | 2 | 2 ✓ |
| `poi:B001`×2 + `poi:B002` | 2 | 2 ✓ |
| 空 value/未知 kind/裸 UUID/普通文本 | 0 | 0 ✓ |
| undefined/null/[] | 0 不抛 | 0 ✓ |
| 输入数组不变 | 不变 | 不变 ✓ |
| 摘要用去重数量 | `2个地点` | ✓ |

代码级确认：canonical `(kind, value)` 去重（`seen.add(kind:value)`）；不同 kind 同 value 不合并；malformed 不计数；不解析英文 message/reasonCode/ruleId；结果与顺序无关；不修改输入。

### C2：日期排序 — PASS

独立探针真值表：

| 场景 | 期望 | 实测 |
| --- | --- | --- |
| 逆序 18→17 | `8月17日、8月18日` | ✓ |
| 重复 | 去重 | ✓ |
| 跨月 7月31日/8月2日 | 升序 | ✓ |
| 跨年 2025-12-31/2026-01-02 | 含年份升序 | ✓ |
| 闰日 2028-02-29/03-01 | 正确 | ✓ |
| 不同排列 | 输出一致 | ✓ |
| malformed/''/2026-02-30 | 安全忽略无 NaN | ✓ |
| 空输入 | '' | ✓ |
| 输入数组不变 | 不变 | ✓ |

代码级确认：严格 `YYYY-MM-DD` 校验 + 闰年感知天数（无本地时区 Date 解析）；先验证→去重→数字排序→格式化；跨年含年份；不对中文结果字典序排序。

### C3：用户可见摘要正确性 — PASS

- 重复实体不虚高：真实 DOM 中报告含 2 个相同 activity ref，摘要显示 `1个地点的营业时间暂未核实`（非 2）✓（独立视觉脚本断言）
- 日期升序、无 raw typed refs/UUID/英文 message/validatorVersion/reasonCode/ruleId/schemaVersion ✓（DOM 扫描 0 泄漏）
- 无规则统计墙/技术详情墙恢复 ✓
- malformed 安全中文空态不抛异常 ✓（组件测试）

### C4：移动端按钮可用性 — PASS

真实浏览器 390×844 与 1440×900：

| 项 | 实测 |
| --- | --- |
| 「修改要求」bounding box | **112×48px**（≥44px ✓） |
| 「放弃本方案」bounding box | **152×48px**（≥44px ✓） |
| 可见/可聚焦/可点击 | ✓（isEnabled true） |
| 横向溢出 | 0px（两视口） |
| 被覆盖 | 无（boundingBox 正常） |
| keyboard focus / aria | ✓（tab 顺序 edit→abandon；aria-expanded 正确） |
| 修改要求只开编辑器 | ✓（emit edit；TripDetail openEditor 本地状态） |
| 放弃走 cancel 链路 | ✓（emit abandon；handleAbandonCandidate→cancelPlanningTask） |
| 无接受/确认/保存候选按钮 | ✓（DOM 扫描） |
| 1440×900 布局未膨胀 | ✓（0 溢出，按钮 48px 视觉协调） |

### C5：核心业务不变量回归 — PASS（10 项全过）

1. VERIFIED 自动持久化 ✓（E2E completed 断言 `行程已验证并保存`/`已保存`，不依赖前端确认）
2. UNVERIFIED 不可保存 ✓（无确认/接受/保存候选按钮，组件探针）
3. NEEDS_REPAIR 不可保存 ✓（同上）
4. 修改要求只开编辑器 ✓（emit edit + openEditor 本地状态，无 POST task）
5. 放弃只调已有取消链 ✓（cancelPlanningTask）
6. malformed fail closed ✓（`暂时无法读取规划结果` 安全中文）
7. 不通过评分推断可行性 ✓（未触碰 PlanEvaluation 逻辑）
8. 候选与已保存隔离 ✓（weather 联动只高亮候选日）
9. 已保存文案不退化 ✓（`已保存行程`/`与已保存行程相比`，无"正式版本"）
10. Java/Python/契约语义零变化 ✓（diff 零修改）

### C6：执行报告真实性 — **NEEDS_SMALL_FIX（1 处数字不实）**

B15.1 章节已确认承认/纠正：
- ✓ 承认原 `countAffectedEntities` 未去重
- ✓ 承认原 `formatChineseDateList` 未稳定排序
- ✓ 承认原 §9 文件统计不准确且 M/A 重复
- ✓ 独立区分首次验收快照（13 M + 4 A）与最终状态（13 M + 5 A）
- ✓ 最终清单每路径唯一、A/M 与 git status 一致
- ✓ acceptance-report 计入 A 且注明"既有未跟踪验收产物"（未虚称执行 Agent 修改）
- ✓ 未虚构独立验收 PASS（`B15_1_READY_FOR_REVIEW` + 明确"未声称已独立复验 PASS"）
- ✓ entityDisplayName 脆弱性登记为非阻断观察（无调用方、无泄漏）

**不实 1 处**：B15.1 章节门禁数字写 **416/416**（unit ×2、shuffle ×3、随机、coverage），独立复跑实测 **435/435**（415 基线 + 19 helper 新测试 + 1 按钮测试 = 435）。416 与实际不符（少计 19）。属报告事实性错误——按任务书"统计或事实仍不准确时，至少判定 NEEDS_SMALL_FIX"。

## 22. 独立门禁（全部独立复跑）

| 门禁 | 结果 |
| --- | --- |
| helper 定向 | feasibility-presentation **34/34** |
| PlanningReviewPanel 定向 | **32/32**（含按钮尺寸断言） |
| FeasibilityReportPanel 定向 | **8/8** |
| App/TripDetail 相关 | 全量内通过 |
| `pnpm test` ×2 | **435/435 × 2** |
| shuffle 20260816 / 314159 / 271828 | **435/435 × 3** |
| 随机 seed 723864（验收生成） | **435/435** |
| coverage | **435/435**；All files stmts 95.43/branch 85.97/funcs 94.84/lines 95.43 |
| 触碰生产文件每项 ≥80% | FeasibilityReportPanel 100/100/100/100；PlanningProgress 100/97.8/100/100；PlanningReviewPanel 97.4/84.4/100/100；TripDetail 95.3/83.9/86.2/100；feasibility-presentation 92.0/88.7/85.7/100 —— **全部 ≥80%** ✓ |
| typecheck | vue-tsc -b 通过 |
| build | vite build 通过 |
| `CI=1 pnpm test:e2e` | **21/21 passed**（无 AMap 时序失败复现） |
| 1440×900 / 390×844 视觉 | 0 溢出、0 控制台错误、0 内部术语泄漏、按钮 48px |
| DOM 术语扫描 | 0 泄漏 |
| git diff --check / links / secret / staged | 0 错 / 273-0 / 0 命中 / 空 |
| scope 零修改 | Java/Python/contracts/Flyway/compose 0 hits |

## 23. 发现项及严重级别

- **NEEDS_SMALL_FIX（唯一）**：执行报告 B15.1 章节门禁数字 416/416 与实际 435/435 不符（少计 19）。不影响任何功能正确性（功能已全部 PASS），仅报告统计笔误。按任务书判定规则（"仅存在明确、有限、不影响用户正确性的文档小错"）→ **B15_NEEDS_SMALL_FIX**。
- 非阻断观察（登记，不伪装为已修复）：
  - `entityDisplayName` activity 分支 `Number(UUID)` 回退逻辑脆弱（无调用方、无泄漏）。
  - 移动端 390×844 状态区在首屏下方（按钮需轻微滚动访问；功能正常、DOM 可见）。
  - comparisonDiffs 用 title 集合（同标题不同 ID 活动不计入"新增"）。
  - B15 验收 Minor（状态区贴边）维持。

## 24. 判定

**B15_NEEDS_SMALL_FIX**
**RELEASE_FREEZE_BLOCKED**

- C1 去重、C2 日期排序：**修复确认**（独立真值表 18/18 + 代码级审查 + 真实 DOM 去重可见）。
- C3 摘要正确性、C4 移动端按钮（48px）、C5 不变量（10/10）、C6 除 1 处数字外：**全部通过**。
- 独立门禁全部通过（435/435 ×2、shuffle ×4、coverage 全 ≥80%、typecheck/build/E2E 21/21、视觉 0 溢出/0 泄漏）。
- **唯一未关闭项**：执行报告 B15.1 章节 416 vs 435 数字笔误（报告事实性小错，不影响功能）→ 需执行/文档职责修正后复验。

**Git 收口授权：否**（待小修关闭后复验）。本验收 Agent 未执行任何提交；Git 收口前不得进入 GitHub 发布/tag/release。

### 临时探针清理证明

- 独立探针（`b15-reaccept-probe.test.ts`、`b15-reaccept-visual.tmp.mjs`）已在验收结束前删除；`git status` 与开始前一致（13 M + 5 A，无残留）。
- 本报告为唯一追加写入；未 stage/commit/push；用户 trip-pilot-prod 未操作。

---

# B15.1.1 最终独立复验（追加章节）

- 状态：**B15_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT / RELEASE_READY**（详见 §25）
- 验收方式：纯文档统计修正验收（只读审查 execution-report/acceptance-report；未修改任何文件除本报告追加；未 stage/commit/push/tag/release/PR）
- 验收日期：2026-08-17
- 前置：B15.1 重新验收 `B15_NEEDS_SMALL_FIX`（唯一问题：B15.1 章节门禁数字 416/416 vs 实际 435/435）；B15.1.1 文档修正交付 `B15_1_SMALL_FIX_READY_FOR_REVIEW`。原 NEEDS_CORRECTION/NEEDS_SMALL_FIX 历史完整保留。

## 25. 最终复验

### 基线

branch `codex/feasibility-foundation`；HEAD `d10e70cf354d096300c4a348d6aef585b8d82dc8`（未变）；staged 空（0 行）；acceptance-report 保留 `B15_NEEDS_CORRECTION`/`B15_NEEDS_SMALL_FIX`/`RELEASE_FREEZE_BLOCKED`；B15/B15.1 代码测试全部 unstaged（13 M + 5 A）；保护目录 23 项原状；`.env` 未跟踪；Java/Python/contracts/Flyway/compose 零修改。

### 435 数字逐项对账（execution-report §17 门禁区）

| 项 | 记录 | 复验 |
| --- | --- | --- |
| unit ×2 | **435/435 × 2** | ✓ |
| shuffle 20260816/314159/271828 | 435/435 × 3 | ✓ |
| 随机 seed | 435/435 | ✓ |
| coverage | 435/435 | ✓ |
| 定向 feasibility-presentation | 34/34 | ✓ |
| 定向 PlanningReviewPanel | 32/32 | ✓ |
| 定向 FeasibilityReportPanel | 8/8 | ✓ |
| E2E | 21/21 | ✓ |

### 435 推导

415（B15 基线全量）+ 19（B15.1 新增 helper 去重/日期测试）+ 1（B15.1 新增按钮尺寸测试）= **435**——B15.1.1 章节 L328 明确推导 ✓，与 B15.1 独立复验实际复跑一致。

### 当前门禁区无错误 416 证明

全文件扫描：`416` 仅出现 3 处，全部位于 B15.1.1 纠正记录章节（L321/L326/L328），语义为"原 416/416 是统计笔误"的历史引用；§17 门禁区（L290-293）已全部为 435/435，**无把 416 当作成功测试总数的残留** ✓。

### 历史 416 引用为何允许保留

B15.1.1 章节的三处 416 是对被修正错误的**说明性引用**（"原（错误）：4 处 416/416"、"原 416/416 是统计笔误"），是修正记录的必要组成部分；引用明确标注"原（错误）"，不会误导当前门禁数字。按任务书"历史中的'原 416/416 是统计笔误'可以保留"→ 允许 ✓。

### B15.1.1 章节声明核对（12 项机械复验全过）

1. ✓ unit 两轮 435/435 ×2
2. ✓ shuffle 3 seed 435/435
3. ✓ 随机 seed 435/435
4. ✓ coverage 435/435
5. ✓ 定向 34/34、32/32、8/8
6. ✓ E2E 21/21
7. ✓ 415+19+1=435 推导
8. ✓ 历史 416 允许保留（标注"原错误"）
9. ✓ 门禁区无残留 416
10. ✓ B15.1.1 声明：只修文档、未重跑/伪造测试、引用上一轮独立复验真实结果、未声称提前获得 PASS
11. ✓ execution-report 保留原始 B15/B15.1 RED→GREEN 与 NEEDS_CORRECTION 背景
12. ✓ acceptance-report 在本轮追加前未被执行 Agent 修改（SHA256 与 B15.1.1 开始前一致）

### 代码/测试零漂移证明

- B15.1.1 期间唯一增量是 `execution-report.md` 文档修正（git status 13 M + 5 A 与 B15.1 验收清单一致，无新增 M/A 文件）。
- `feasibility-presentation.ts`/测试、PlanningReviewPanel/FeasibilityReportPanel/TripDetail/PlanningProgress、vite.config.ts 均未被本批触碰（git status 无变化）。

### 轻量门禁

`git diff --check` 0 错误；Markdown links 273/0；`git diff --cached --name-only` 空；scope 过滤 Java/Python/contracts/Flyway/compose 0 hits；secret 扫描 0 命中；HEAD 未变；保护目录 23 项原状。

（按任务书：本轮为纯文档数字修正，不重跑 unit/typecheck/build/E2E；门禁数字引用 B15.1 独立复验已实际完成的结果——435/435 ×2、shuffle 435/435 ×4、coverage 435/435、typecheck/build、E2E 21/21、双视口视觉验证。）

## 26. 判定

**B15_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT**
**RELEASE_READY**

- 首轮 B15 两个 Important（去重缺失、日期未排序）已在 B15.1 关闭（独立真值表 18/18 + 真实 DOM 去重可见 + 按钮 48px + 不变量 10/10 + 全部门禁独立复跑通过）。
- 唯一文档统计问题（416 vs 435）已在 B15.1.1 关闭（门禁区全部 435/435，推导正确，历史引用合理保留，零代码漂移）。
- 原 NEEDS_CORRECTION / NEEDS_SMALL_FIX 历史完整保留。
- **授权进入 B15 Git 提交收口**；本验收 Agent 未执行 Git 收口；Git 收口完成前不得创建 GitHub tag/release。
- 非阻断观察（entityDisplayName 脆弱性、移动端状态区需滚动、comparisonDiffs title 集合语义）保持登记，不伪装为已修复。

### 唯一写入证明

本报告（acceptance-report.md）为唯一追加写入；未修改 execution-report、Web 代码/测试、任何其他文件；未 stage/commit/push/tag/release/PR；未操作用户 trip-pilot-prod 栈。
