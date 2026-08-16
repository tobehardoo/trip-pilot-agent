# B13_FIX 执行计划：关闭 GitHub 正式版本冻结前的全部阻断项

- 文档状态：生效中
- 批次：B13_FIX（由 B13 独立验收 `NEEDS_CORRECTION / RELEASE_FREEZE_BLOCKED` 触发）
- 基线 branch：`codex/feasibility-foundation`；HEAD：`89236ea731b3d9aea55a81f96101940299f2c983`（B12）
- 关联：[B13 验收报告](../B13/acceptance-report.md)（只读）、[总控计划](../../product/系统完善长期执行与验收总控计划.md)
- 交付：`B13_FIX_READY_FOR_REVIEW`（unstaged、未 commit、未 push；不得创建 acceptance-report.md）

## 1. 缺陷 → 修复矩阵（来自验收报告 P0/P1）

| 编号 | 缺陷（真实复现） | 为什么既有全绿测试没捕获 | 修复 | RED 测试 | 验收证据 |
| --- | --- | --- | --- | --- | --- |
| P0-1 | arrivalAt/departureAt 只落库不进规划快照（候选首项 09:00 早于 18:00 到达） | 单元测试各自手工构造输入，没有「Java 实际 outbox body → Python model」跨层断言；Golden 无晚到/早离场景 | create v4 快照携带权威边界时间（+offset ISO）；新增 replan v2 / candidate-validation v2；Java/Python/schema 共享 fixture 双端读取；晚到/早离入 Golden | R1 第 1–6 条 | 跨层 outbox 契约测试 + Compose Golden 3/4 |
| P0-2 | Java 接受 schema3 混合 legacy/structured，Python 拒绝 → 永久 QUEUED | Java/Python 各自构造输入，无共享规则测试；worker command failure 无终态 | 统一规则：legacy names + 空 refs 合法（历史文本），refs 非空时数量必须相等；Java/JSON Schema/Python 同一规则；worker invalid command → 安全 PLANNING_FAILED 终态（稳定 category/code，不泄露 body，幂等） | R2 | 跨层 HTTP→outbox→Python→outcome 测试 + Compose Golden 7/8 |
| P0-3 | meal binding 按位置 zip（抵达日唯一晚餐被绑成 LUNCH） | 投影测试只用「顺序正确」的固定输入，未覆盖抵达日单餐 | meal activity 显式携带 meal type；validation_projection 按类型 identity 关联，禁止 positional zip；同餐型重复 fail-closed | R3 10 条场景（断言 RuleResult/binding/reasonCode/report） | 定向规则测试 + Compose Golden 9 |
| P1-1 | 直辖市 provinceCode==cityCode 被拒绝（北京 400） | 区域校验只有普通省市用例 | 明确直辖市模型：仅 4 个直辖市行政代码允许同码；名称/code 一致性校验；普通省市仍强制隶属 | R4 6 条 MockMvc/DB round-trip | 集成测试 + Compose Golden 1 |
| P1-2 | 地点真实性未闭环（伪造 providerPoiId 200 落库；anchor 自由文本；Python 名称降级） | 服务端只校验形状；无 issuance 校验；Python 无精确 id 匹配测试 | Java 签发 owner-scoped、TTL、有界 opaque selection token；保存时 canonicalize（忽略客户端可伪造字段）；token 绑定 owner/city/query/candidate；过期/伪造/跨 owner/city mismatch 400；Python 按 providerPoiId 精确解析，找不到 fail closed（TRAVEL_ANCHOR_UNAVAILABLE），structured 禁止同名降级，legacy 保留名称兼容 | R5 8 条 RED | token 集成测试 + Compose Golden 5/6 |
| P1-3 | 创建页 4 个时间字段（顶层 + 约束编辑器内重复） | 无「创建页只有两个 datetime」的 DOM 断言 | 删除 ConstraintEditor 内 legacy 到达/返程时间输入；创建页只保留 arrivalAt/departureAt；startDate/endDate 仅派生展示 | R6 | App 级 DOM 断言（无第二个到返时间输入） |
| P1-4 | WAITING_USER 候选在 y≈2445，技术详情默认铺满；reasonCode/validatorVersion 直接可见 | E2E 只断言天气与 review 容器关系，未断言候选 bbox/顺序/默认折叠 | PlanningReviewPanel 前置（候选概要/日期导航/预算/主要风险），Feasibility 默认只显示 status/FAIL/UNKNOWN 数/中文摘要/受影响日期；技术详情（reasonCode/validatorVersion/UUID/repair ids）默认折叠；「我的要求」隐藏未设置项 | R7 App/E2E 断言（bbox.bottom≤900、DOM order、默认不可见技术字段） | E2E + Compose Golden 12 |
| P1-5 | replan/candidate v1 携带 schema3 约束（事实性改义） | 无版本矩阵测试 | 新增 replan v2 / candidate-validation v2 schema+fixtures；Java 改发 v2；Python 显式接收 v2；v1 保留 legacy fail-closed | R1 第 4 条 + R2 | 版本矩阵测试 |
| P1-6 | 搜索资源/竞态：无界 cache、per-request AsyncClient、城市切换旧响应覆盖 | 无并发/长查询/城市切换测试 | Java 有界 TTL cache（最大容量+过期淘汰+结构化 key）；Python 生命周期复用 AsyncClient 并在 shutdown 关闭；Web request generation + AbortController 立即失效旧城市请求 | R5 | 并发/切换测试 + E2E |
| P1-7 | WAITING_USER + 正式版本共存时天气联动旧正式版本 | 测试只覆盖 itinerary 404 | WAITING_USER 优先候选：滚动 candidate-day/review，不选旧路线 activity；无候选才回退正式 | R7 | App/E2E 反例 + Compose Golden 12 |
| P1-8 | 报告收口：IN_PROGRESS、337→339、coverage 白名单缺高风险文件、PlaceAutocomplete 71% | — | coverage include 纳入全部 B13 生产文件（分支≥80）；执行报告如实更新（NEEDS_CORRECTION 历史保留）；完整验收矩阵落盘 | — | coverage 门禁数字 + 报告 |

## 2. 固定架构决策（任务书第三节）

1. **create v4 纠正**（未发布，可在首次提交前纠正，不新增 v5）：TripSnapshot 必须携带 arrivalAt/departureAt（带 offset ISO）+ startDate/endDate（派生，非时间权威）+ destination + constraints + identity/version 字段；v1–v3 已发布不动。
2. **replan v2 / candidate-validation v2**：新增 schema + valid/invalid fixtures；Java producer 改发 v2；Python 显式接收 v2；v1 保留 legacy 解析语义。
3. **schemaVersion 3 混合约束规则**（Java/JSON Schema/Python 同一规则）：legacy names 对应 refs 可为空（历史文本）；refs 非空时数量必须与 names 完全相等；planner 区分 legacy text-only 与 structured exact-identity 条目；structured 条目 id 未命中不退回同名文本。
4. **候选真实性（本地单实例方案）**：Java 签发 owner-scoped、TTL、有界 opaque selection token；token 对应服务端缓存 canonical PlaceRef（最大容量+过期淘汰）；创建/修改时新增/变化 PlaceRef 必须携带有效 token，服务端忽略客户端可伪造字段并 canonicalize；完全未变化的已持久化 PlaceRef 无改动保存可继续使用；token 不进入 Python planner；必要时拆分 request DTO 与持久化 domain DTO。

## 3. 工作组与 TDD 顺序

- R0：基线核对（已通过）+ 缺陷矩阵落盘 + 「为什么全绿没捕获」记录（见 §1）。
- R1：边界时间全链路（先 RED：晚到首项、早离末日、outbox body 双语言、版本矩阵、offset/跨日/边界相等/naive 拒绝、四入口一致）。
- R2：schema3 混合态统一 + command failure 终态（先 RED：混合 constraints 跨层、真实 outbox 同时过 schema+Python、task 终态；worker invalid command 安全 FAILED）。
- R3：meal type 精确绑定（先 RED：10 场景，断言 RuleResult/binding/reasonCode/affected refs/report status）。
- R4：直辖市区域模型（先 RED：4 直辖市成功、普通省市隶属、同码伪造拒绝、MockMvc/DB round-trip）。
- R5：地点真实性闭环（先 RED：fake token、篡改坐标 canonicalize、跨 owner、城市切换竞态、同名 A/B exact id、三 anchor 无改动保存、未选候选禁止提交）。
- R6：删除重复时间输入 + 创建表单收口。
- R7：Review UI 信息架构 + 天气联动（先 RED：bbox/DOM order/默认折叠/技术详情点击、WAITING_USER+正式版本共存天气、502 安全态、390×844）。
- R8：覆盖率、契约、资源、执行报告收口。

## 4. 强制验证门禁

按风险顺序定向 → 全量：Python（feasibility/validation projection/meal/place/worker/full/ruff）；Java（region/place token/outbox/completion/flyway/verify/JaCoCo/干净库+V34/36 升级）；Web（unit/coverage/typecheck/build/CI=1 Playwright/1440×900/390×844）；仓库（links/diff --check/secret/compose config/check_compose_defaults.py --with-docker）。

## 5. 真实 Compose Golden（唯一隔离 project、独立端口/网络/卷）

14 项见任务书第六节；全部账号/容器/卷在证据保存后清理，禁止删除用户现有资源。

## 6. 范围控制

不做：真实 Provider 多城市系统测试、OR-Tools、公网部署、K8s、staging/TLS/registry、支付/库存/票务、无关视觉重写。非阻断观察仅在与修复文件附近且风险小有测试时顺手关闭，否则记录。

## 7. 停止条件

所有 P0/P1 RED→GREEN；全量门禁通过；Compose Golden 通过；git diff --check 干净；staged 空；HEAD 89236ea；未 commit/push；保护目录未处理；输出 `B13_FIX_READY_FOR_REVIEW`。

---

# B13_FIX.2 追加计划（运行时复现缺陷修复）

- 状态：生效中；交付 `B13_FIX2_READY_FOR_REVIEW`（unstaged、未 commit、未 push）
- 触发：B13_FIX 验收关闭后运行时复现两处真实缺陷
- 基线：branch codex/feasibility-foundation，HEAD 89236ea，staged 空；B13/B13_FIX/B13_FIX.1 全部改动为合法 unstaged 工作，必须保留

## 1. 缺陷 → 修复矩阵

| 编号 | 缺陷（运行时事实） | 根因 | 修复 | RED 测试 |
| --- | --- | --- | --- | --- |
| R9 | 双必去（天河公园+正佳广场）任务 FAILED / MUST_VISIT_UNAVAILABLE，日志只搜索了"天河公园" | `_collect_pois` 普通候选达到 required_count 即提前返回，第二 ref 的精确 id（B00140TFHO）从未搜索；且精确 id 分数低时被排名 cutoff 剪掉；搜索页未返回 id 时直接 fail closed | 逐项处理 structured must-visit refs：未全部召回前禁止提前返回；`pinned_provider_ids` 钉住精确 id（优先于 cutoff，普通配额不删）；未召回 ref 由服务端规范化 PlaceRef 构建 pinned POI 作为固定输入；MUST_VISIT_UNAVAILABLE 仅保留给路线/关闭/时间等真实失败 | `test_must_visit_recall.py` 5 条（先 RED） |
| R10 | WAITING_USER 候选存在时再次点击「开始规划」，Web 收到 409 PLANNING_TASK_ACTIVE 后置 failed 并清空 candidate/report | `runPlanningTask` 无 waiting_user 前置保护；catch 对任何错误置 failed + clearPlanningOutcome；`applyOutcomeState` review 不清旧 planningError | 统一 active state（queued\|waiting_user）禁止创建；409 竞态走 getLatestPlanningTask + readPlanningTaskOutcome 恢复权威状态，不置 failed、不清 outcome；applyOutcomeState queued/review/completed 清旧 error；按钮禁用+「候选待确认」；中文文案（规划进度/候选行程已生成，等待处理/已有候选行程待确认，请先查看或放弃候选） | `TripWorkspaceActions.test.ts` 3 条（先 RED） |
| R12 前置 | REAL_ONLY Golden 中 Java 拒绝 review 事件（activities must be ordered without overlap），任务卡 QUEUED | forward-fit 只移动被 route 检查的相邻对，跳过 route 的占位边界（未解析锚点/无 POI MEAL/住宿占位）与真实活动相对位置被破坏 | route 循环后单调扫掠保证 emitted 活动严格有序不重叠（forward-fit 决策不变） | `test_emitted_day_ordering.py` 2 条（先 RED，legacy+structured 双路径复现） |

## 2. 允许/禁止路径

- 允许：上述三个生产文件 + 相关测试 + 两个报告文档追加章节。
- 禁止：reset/stash/checkout/restore/clean/rebase/amend；stage/commit/push；修改 .omo/、.serena/、docs/audits/、.env、acceptance-report.md；弱化精确 providerPoiId、安全证据或 Feasibility 正式版本门禁；修改 Java WAITING_USER active-slot 语义。

## 3. 门禁与 Golden

- Python 全量 pytest + ruff；Web unit/coverage/typecheck/build/Playwright；Java mvn verify（定向复跑 active task/abandon/409）；Compose config/default；Markdown links；git diff --check；staged 空；无 secret 泄漏。
- 隔离 Compose Golden（`trip-pilot-b13fix2-golden`，独立端口/网络/卷/tag）：REAL_ONLY 真实 place search 动态选取两个 POI → structured must visits → 任务必须 WAITING_USER 或 SUCCEEDED（不得 MUST_VISIT_UNAVAILABLE）→ candidate 含两个精确 providerPoiId → 409 重复创建 → abandon 后重规划；浏览器验证候选可见/按钮禁用/无英文错误/abandon 后可重规划；DEMO 语义不伪造 VERIFIED。结束后清理栈/卷/网络/镜像并记录证据。

## 4. 完成标志

所有 RED→GREEN；全量门禁通过；Golden 通过并清理；execution-report 追加完成（RED 证据、修复说明、双真值表、Golden/门禁数字、文件清单、未提交证明）；输出 `B13_FIX2_READY_FOR_REVIEW` 后停止，不自行修改 acceptance-report，不提交。
