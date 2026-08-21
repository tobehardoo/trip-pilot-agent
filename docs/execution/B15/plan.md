# B15 执行计划：规划评审界面用户化、中文化与信息降噪

- 文档状态：**PASS / COMMITTED（本提交）**——授权依据：`B15_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT` + `RELEASE_READY`（独立验收最终复验，见 acceptance-report §26）；历史保留：B15_NEEDS_CORRECTION / B15_NEEDS_SMALL_FIX / RED→GREEN / B15.1 / B15.1.1 全部完整
- 基线 branch：`codex/feasibility-foundation`；HEAD：`d10e70cf354d096300c4a348d6aef585b8d82dc8`（= BASELINE_HEAD，`feat(platform): complete local-first trip planning release` 提交）；staged 空；tracked 工作树干净
- 关联：B14_FIX acceptance-report（已收口授权）、本批为 Web-only 用户化批次
- 禁止：reset/stash/checkout/restore/clean/rebase/amend；stage/commit/push；修改保护目录/`.env`；操作 Java/Python/contracts/Flyway/compose/RabbitMQ；降低 coverage 门槛；操作用户 `trip-pilot-prod`
- 不得创建：`docs/execution/B15/acceptance-report.md`（留给独立验收 Agent）

## 1. 用户截图中的真实问题（核心问题）

1. 页面暴露 `REVIEW`、`FEASIBILITY`、`ITINERARY`、英文规则消息、`validatorVersion`、`reasonCode`、UUID 等内部内容。
2. 「待确认」「候选待确认」没有对应的确认选项，语义错误——用户看到"待确认"却无处确认。
3. 候选行程与完整验证报告同时大面积展开，信息过度嘈杂（规则墙 + 全部日期展开 + 每段交通列出）。
4. 用户不知道方案为什么不能保存，也不知道下一步该做什么。

## 2. 当前错误文案与目标文案

| 当前（错误/内部） | 目标（用户化中文） |
| --- | --- |
| `Review` / `规划需要确认` | 按状态：`方案还需要完善` / `方案需要调整` / `暂时无法读取规划结果` |
| `待确认` / `候选待确认` | `部分信息待核实` / `存在需要处理的问题` / `结果异常` |
| `候选行程尚未成为正式版本` | 状态化说明（见真值表） |
| `Feasibility` / `硬可行性验证` | 不再作为普通用户页面标题 |
| `Itinerary`（操作区标签） | `行程安排` |
| `候选行程` | `预览方案` |
| `正式版本` / `当前正式版本` | `已保存行程` |
| `与当前正式版本对照` | `与已保存行程相比` |
| `未验证` | `部分信息待核实` |
| `放弃候选` | `放弃本方案` |
| `主要风险` + 英文 rule.message | `待核实信息（N）` / `需要调整（N）` + 中文摘要 |
| `查看验证详情` / `查看技术详情`（展开后 validatorVersion/reasonCode/ruleId/evidenceId/UUID） | 删除 |
| `验证时间 ...`（validatedAt 元数据） | 删除 |
| `当前尚无正式版本` | 轻量说明：`方案验证通过后会自动保存为正式行程。` |
| 规则统计卡（总数/通过/失败/未知/不适用/缺失） | 删除 |
| 日期 `2026-08-17` | `8月17日` / `8月17日、8月18日` |

## 3. UI 信息层级（页面顺序）

1. **状态和操作**：状态标题 + 徽标 + 说明 + 主按钮（修改要求）+ 次按钮（放弃本方案）
2. **预览方案**：折叠式日卡摘要（默认折叠）
3. **待核实/需要调整的问题摘要**：N≤3 直接显示；N>3 默认前 3 条 + `查看全部 N 项`
4. **已保存行程**（如果存在）：轻量说明或 `已保存行程` + 用户可理解的差异摘要

## 4. 状态真值表（用户视角）

| 内部状态 | 主标题 | 徽标 | 用户说明 | 主按钮 | 次按钮 |
| --- | --- | --- | --- | --- | --- |
| UNVERIFIED | 方案还需要完善 | 部分信息待核实 | 已生成一份预览方案，但部分信息暂时无法核实，因此还不能保存 | 修改要求 | 放弃本方案 |
| NEEDS_REPAIR | 方案需要调整 | 存在需要处理的问题 | 当前安排存在冲突，请修改旅行要求后重新规划 | 修改要求 | 放弃本方案 |
| VERIFIED | 行程已验证并保存 | 已保存 | 沿用现有自动保存流程，不进入待处理页面 | — | — |
| malformed | 暂时无法读取规划结果 | 结果异常 | 系统无法安全读取本次规划结果，请重新规划 | —（保留安全失败） | — |

辅助文案（UNVERIFIED/NEEDS_REPAIR 共用）：`修改并保存要求后，可以重新开始规划。`

## 5. 系统不变量（不得改变）

1. 只有 `VERIFIED` 才能成为已保存行程。
2. `UNVERIFIED` 不能手动确认成为正式行程。
3. `NEEDS_REPAIR` 不能手动确认成为正式行程。
4. 不新增「仍然保存」「接受风险」「确认候选」等绕过按钮。
5. 不从 PlanEvaluation score 推导硬可行性。
6. 不修改 Java/Python Feasibility 语义。
7. 不修改 API/MQ/schema/DB。
8. 不改变 candidate 与 current itinerary 隔离。
9. 不修改 API/SSE outcome fail-closed reader。
10. VERIFIED 现有自动持久化行为保持不变。
11. 放弃候选不得删除或覆盖已保存行程。

若发现必须改后端才能实现 → `B15_ARCHITECTURE_BLOCKED`。

## 6. 术语统一

| 当前术语 | 新术语 |
| --- | --- |
| 候选行程 | 预览方案 |
| 正式版本 | 已保存行程 |
| 未验证 | 部分信息待核实 |
| 放弃候选 | 放弃本方案 |
| 与当前正式版本对照 | 与已保存行程相比 |
| ITINERARY | 行程安排 |

必须删除的普通用户文案：`待确认`、`候选待确认`、`规划需要确认`、`REVIEW`、`FEASIBILITY`、`ITINERARY`、`activity/activities`、`hard-validator-v*`、`schemaVersion`、`validatorVersion`、`reasonCode`、`ruleId`、`evidenceId`、内部 UUID、`PASS`、`FAIL`、`UNKNOWN`、`NOT_APPLICABLE`、`当前正式版本`、`正式版本对照`。

必要专有名称（地点/餐厅/酒店/Provider 品牌）保留原文；禁止"禁所有英文字母"的粗暴实现。

## 7. Feasibility 用户展示映射

不直接渲染后端 `RuleResult.message`；不解析英文 message 得到数量。用 RuleId + 结构化字段（affectedEntityRefs）生成中文摘要：

| RuleId | 中文名称 |
| --- | --- |
| TRIP_DATE_RANGE | 行程日期 |
| FIXED_SCHEDULE_COVERAGE | 固定安排 |
| BUDGET_LIMIT | 预算 |
| DUPLICATE_POI | 重复地点 |
| ACTIVITY_OVERLAP | 时间安排 |
| MUST_VISIT_COVERAGE | 必去地点 |
| ROUTE_ENDPOINT_CONTINUITY | 行程起止衔接 |
| CROSS_DAY_CONTINUITY | 跨日衔接 |
| OPENING_HOURS | 营业时间 |
| VISIT_DURATION | 游玩时长 |
| MEAL_WINDOW | 用餐时间 |

UNKNOWN 示例：OPENING_HOURS→`7个地点的营业时间暂未核实`；VISIT_DURATION→`4个地点缺少可靠的建议游玩时长`；其他→`该项信息暂时无法核实`。
FAIL 示例：OPENING_HOURS→`部分地点的营业时间与行程安排冲突`；ACTIVITY_OVERLAP→`部分活动时间发生重叠`；BUDGET_LIMIT→`当前方案可能超出预算`；MUST_VISIT_COVERAGE→`部分必去地点尚未安排`；其他→`该项安排需要调整`。

数量来源：typed affectedEntityRefs 中 activity/poi 实体数量（仅展示；不显示 ref 原值；不解析英文 message；refs 缺失用无数量安全文案）。实体名称：candidate itinerary 可安全映射则显示名称；否则只显示数量和日期；不得显示 UUID 代替名称。未知 RuleId：UNKNOWN→`该项信息暂时无法核实`、FAIL→`该项安排需要调整`，不显示未知 code。

## 8. 问题摘要界面

- 标题：UNVERIFIED→`待核实信息（N）`；NEEDS_REPAIR→`需要调整（N）`
- 只展示 UNKNOWN/FAIL；不展示 PASS/NOT_APPLICABLE/规则总数/通过数/失败统计卡/不适用数/缺失规则/validator metadata/reportId/validatedAt/repair 内部 ids/技术详情入口
- N≤3 直接显示全部；N>3 默认前 3 条 + `查看全部 N 项`；展开后仍只显示中文摘要

## 9. 预览方案降噪

- 标题 `预览方案`；推荐名 `北京行程建议` 或直接用旅行标题，不添加"真实地点"等内部能力宣传
- 每日卡片默认折叠；折叠显示：中文日期 · 活动数量 · 当天时间范围 · 最多两个主要地点名称 · 交通汇总
- 示例：`8月17日 · 6项安排 · 08:45–18:49` / `故宫博物院、奥华餐厅等` / `当天交通：5段 · 约1小时22分`
- 展开后完整数据不丢失（活动/时间/地点/费用/交通方式；每段交通二级可展开）
- 无障碍：button 或语义 details/summary；aria-expanded 正确；Enter/Space 可展开；focus-visible 明确；状态不只靠颜色；尊重 prefers-reduced-motion
- 天气联动：点击天气日期展开并高亮对应候选日、滚动到候选日；有旧已保存行程时不滚动/选择旧行程；「查看全部行程」清除日期过滤

## 10. 已保存行程区域

- 无已保存行程：删除「与当前正式版本对照」「当前尚无正式版本」、禁用按钮、巨型空白框；只显示 `方案验证通过后会自动保存为正式行程。`
- 有已保存行程：标题 `已保存行程`；对照标题 `与已保存行程相比`；candidate 与已保存行程视觉分隔；放弃 candidate 后已保存行程不变
- 只显示可理解差异（新增2个地点 / 调整1天安排 / 预计交通时间增加20分钟）；无可靠差异不渲染空对照区

## 11. TDD 轮次

- R0 基线 Characterization：运行现有 PlanningReviewPanel/FeasibilityReportPanel/TripDetail/TripWorkspace(App)/feasibility-outcomes E2E/weather-window E2E，证明旧行为（REVIEW/FEASIBILITY/ITINERARY、英文 rule message、validator/version/code、待确认无确认操作、候选过度展开、无正式行程仍有正式版本措辞）
- R1 内部内容泄漏 RED→GREEN（不显示 REVIEW/FEASIBILITY/ITINERARY/hard-validator-v5/reasonCode/ruleId/schemaVersion/UUID/英文 message/规则统计；必要地点名仍显示）
- R2 状态和动作 RED→GREEN（UNVERIFIED/NEEDS_REPAIR 中文状态+说明+两动作；无确认/接受按钮；VERIFIED 自动完成；malformed 安全失败；修改要求打开已有编辑器不建任务；放弃本方案调现有 API 保留已保存行程；重复放弃幂等）
- R3 中文摘要 RED→GREEN（OPENING_HOURS×7 UNKNOWN、VISIT_DURATION×4、ACTIVITY_OVERLAP/BUDGET_LIMIT/MUST_VISIT_COVERAGE FAIL、全 PASS/NA 无问题区、日期中文化、refs 不泄漏、N>3 折叠、未知 RuleId 降级、不解析英文 message）
- R4 候选方案降噪 RED→GREEN（日卡默认折叠、摘要正确、展开完整、交通汇总+二级展开、aria-expanded、键盘可操作、费用/时间/名称无丢失、天气点击展开正确候选日、有正式行程不选中旧活动）
- R5 正式行程空态 RED→GREEN（无正式行程无技术措辞、无"候选待确认"、轻量说明；有正式行程用"已保存行程"；对照区仅可靠差异显示；放弃候选不删已保存行程）
- R6 App/E2E（新 trip→WAITING_USER/UNVERIFIED；有正式行程→replan→NEEDS_REPAIR；放弃预览后旧行程保持；天气日期定位候选日；malformed outcome；1440×900；390×844；页面无内部英文标签/code/UUID/验证器版本）

## 12. 测试矩阵（unit）

| 测试组 | 关键断言 |
| --- | --- |
| PlanningReviewPanel（R1/R2/R4/R5） | 无 REVIEW/FEASIBILITY/待确认；UNVERIFIED/NEEDS_REPAIR 状态文案；无确认按钮；修改要求/放弃本方案动作；日卡折叠/展开；aria-expanded；空态轻量说明；已保存行程标题 |
| feasibility-presentation（R3，新 helper） | RuleId→中文名称；UNKNOWN/FAIL 中文摘要含数量；refs 缺失安全文案；日期中文化；未知 RuleId 降级；N 折叠逻辑 |
| TripDetail（R2/R4/R5） | waiting_user 传入状态；天气点击展开候选日；无正式行程时不选中旧活动 |
| TripWorkspaceActions/App（R2/R6） | 放弃预览保留已保存行程；修改要求打开编辑器不建任务 |

## 13. 允许/禁止修改范围

允许：
- `apps/web/src/components/PlanningReviewPanel.vue`
- `apps/web/src/components/FeasibilityReportPanel.vue`
- `apps/web/src/components/TripDetail.vue`
- `apps/web/src/components/PlanningProgress.vue`（仅必要文案）
- `apps/web/src/pages/TripWorkspace.vue`（仅 emit/动作连接需要）
- 新增 `apps/web/src/lib/feasibility-presentation.ts`（纯展示 helper）
- 对应 Web unit tests / Playwright E2E
- `apps/web/vite.config.ts`（仅新增 helper 纳入 coverage）
- `docs/execution/B15/plan.md` / `execution-report.md`
- 必要用户文档小幅更新

禁止：Java、Python、contracts、Flyway、RabbitMQ、compose、`.env`、B13/B14 历史报告改写、B15 acceptance-report、保护目录。

## 14. 工程质量

禁止 `as any`/`@ts-ignore`/`@ts-expect-error`/`v-html`/CSS `:has()` 决定状态/字符串 contains 推导 outcome/从 score 推导 feasibility/复制第二套状态聚合器/显示 raw backend message/全局 CSS 隐藏技术字段伪装修复/新增第三方依赖/降低 coverage threshold/`.only`/`.skip`/增大超时掩盖 flaky。所有新生产文件进入 coverage include。

## 15. 门禁

Web：新增定向测试；`pnpm test` ×2；shuffle ≥3 固定 seed；`pnpm test:coverage`（触碰生产文件每项 ≥80%）；`pnpm typecheck`；`pnpm build`；`CI=1 pnpm test:e2e`；无 open handles/unhandled rejection。
仓库：Markdown links；`git diff --check`；staged 空；secret 扫描；diff 范围检查（Java/Python/contracts/Flyway/compose 零修改）；保护目录与 `.env` 未触碰。

## 16. 最终验收标准

- 普通用户页面无内部英文标签/code/UUID/验证器版本/规则统计墙
- 状态真值表文案全部落地，无"确认/接受/保存候选"按钮
- 问题摘要纯中文、数量来自 typed refs、不解析英文 message
- 预览方案默认折叠、展开不丢数据、天气联动正确
- 已保存行程空态/有态均正确，放弃不删已保存行程
- 1440×900 与 390×844 视觉检查通过
- 输出 `B15_READY_FOR_REVIEW` + `RELEASE_FREEZE_BLOCKED_PENDING_B15_ACCEPTANCE` 后停止
