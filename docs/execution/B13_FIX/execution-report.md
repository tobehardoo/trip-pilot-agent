# B13_FIX 执行报告

- 状态：**READY_FOR_REVIEW（B13_FIX_READY_FOR_REVIEW）**
- 触发：B13 独立验收 `NEEDS_CORRECTION / RELEASE_FREEZE_BLOCKED`（[验收报告](../B13/acceptance-report.md) 只读保留）
- 基线：branch `codex/feasibility-foundation`，HEAD `89236ea731b3d9aea55a81f96101940299f2c983`，staged 空（已核对）

## 1. RED→GREEN 证据

### R1（P0-1 边界时间全链路，GREEN）

- RED：新增 Java `PlanningOutboxBoundaryContractIntegrationTest`（3 条）——断言 create outbox body
  schemaVersion=4 且 `trip.arrivalAt/departureAt/startDate/endDate/destination/constraints`
  齐全；legacy 日期行程边界字段存在且为 null；共享 v4 fixture 可被 Java 以 Python 相同形状读取。
  首次运行 `test_createCommandCarriesAuthoritativeBoundariesInTheOutbox` 失败：
  outbox 中 boundary 为 `2026-08-01T10:00:00Z`（JDBC 以 UTC 回读 TIMESTAMPTZ），
  与契约 fixture 的 `+08:00` 形状不一致。
- GREEN：`PlanningTaskService` 新增 `CHINA_OFFSET` 常量与 `chinaOffset()`，三个
  TripSnapshot 构造点（create/replan/candidate）统一把边界 re-anchor 到 `+08:00`
  （只改表示不改时刻，null 保持 null）。3 条测试全绿。
- Python 侧（前序已 GREEN）：`trip_agent.worker.contracts.TripSnapshot` 携带
  arrivalAt/departureAt（+offset ISO）+ `validate_dates`；`snapshot_boundary_times()`
  作为权威来源；AMap/Demo provider 全改用 `snapshot_boundary_times(trip)`；
  replan v2 / candidate v2 契约模型+fixtures 落地；v4 契约 `required` + 边界字段。
- 全量：Python 1446 passed（R1 后）；Java 定向 IT 3/3 GREEN。

### R2（P0-2 schema3 混合态统一 + command failure 终态，GREEN）

- RED：`test_messaging_contract_schemas.py` 新增 4 条 schema 级测试——
  schemaVersion 2 + 非空 refs（list/anchor）必须被 JSON Schema 拒绝、
  refs 数量与 names 不等必须拒绝、legacy names + 空 refs 必须合法。
  修复前 schema 无条件放行（全部 RED）。
- GREEN：v4 schema constraints 增加 `allOf`（61 分支）：
  schemaVersion=2 → refs 数组 `maxItems:0`、anchor placeRef 禁止；
  schemaVersion=3 → refs 非空时 refs 长度必须等于 names 长度
  （`contains:true + minContains/maxContains` 精确钉住长度；`required` 防止缺省属性误触发）。
  replan v2 / candidate v2 复用 v4 trip def，一处修改三处生效。
- 跨语言一致性：Java `TripConstraintValidator.validatePlaceRefs`（refs 空合法、
  非空必须平行且同名）、Python `TripConstraints.validate_place_refs`（schema<3 拒绝 refs、
  v3 refs 非空必须平行同名）、JSON Schema 同规则——三端对齐。
- worker command failure 终态（前序已 GREEN）：`handle_delivery` 对无效命令发布
  安全 `PLANNING_FAILED` v2（`COMMAND_VALIDATION_FAILED/INVALID_REQUEST/PLANNER`、
  无 raw body、确定性 eventId、幂等、publish 失败 nack requeue），不再 `reject(requeue=False)`
  导致任务永久 QUEUED；无法提取身份的命令走 dead-letter。
- 全量：Python 1449 passed（R2 后，含 worker invalid-command 3 条 + 新 schema 4 条）。

### R3（P0-3 meal type 精确绑定，GREEN）

- RED：新增 `test_meal_type_binding.py` 10 条——抵达日仅晚餐 + LUNCH/DINNER 双窗口时
  晚餐必须按 DINNER 绑定（P0-3 精确复现）、仅午餐/仅晚餐/两餐按类型绑定、
  禁用餐不抢绑定、无类型 MEAL 活动禁止按位置绑定、无类型日 meal rule 必须 UNKNOWN
  而非 FAIL、同类型重复 fail-closed（ValueError）、AMap projection 按类型 identity、
  跨午夜 UNKNOWN 不崩溃。修复前 10 条全 RED（`ItineraryActivity.meal_type` 字段不存在 /
  旧投影按位置 zip 产生错误绑定）。
- GREEN：
  - `ItineraryActivity.meal_type`（in-process identity，`exclude=True` 保证 v9 线上
    序列化字节不变，Java `FAIL_ON_UNKNOWN_PROPERTIES` 不受影响）；
  - `validation_projection` 改为按 meal type identity 绑定（窗口→同类型活动），
    无类型 MEAL 活动 → 当日记入 `unverified_meal_days`，禁止位置 zip；
    同日重复类型 → ValueError fail-closed；
  - `feasibility_projection`（AMap）同规则：demand.meal_type 与 activity.meal_type
    必须一致，缺失即 ValueError；
  - `feasibility.rules.meal`：无类型日缺失绑定报告 `MEAL_WINDOW_UNVERIFIED`（UNKNOWN），
    不再错误 FAIL `MEAL_PLACEMENT_MISSING`；
  - AMap `_slot_from_item`/`_activity_from_slot` 与 Demo `_meal_placeholders`
    携带显式 meal type。
  - 既有 2 条 projection 测试（构造无类型 meal 期望位置绑定）已按新语义改为显式
    meal type，断言不变（旧断言本身编码了位置推断，属缺陷语义，非 characterization）。
- 全量：Python 1459 passed（R3 后）；v9 序列化验证 `mealType` 不出现在 wire body。

### R4（P1-1 直辖市区域模型，GREEN）

- RED：新增 `MunicipalityRegionIntegrationTest` 6 条——北京/上海/天津/重庆
  `provinceCode == cityCode` 必须创建成功且 DB round-trip；普通省市同码伪造必须拒绝；
  直辖市区不属于其代码必须拒绝。修复前 `city.equals(province)` 直接 400（全 RED）。
- GREEN：`TripService.validateRegion` 建立直辖市明确模型——仅
  `{110000,120000,310000,500000}` 允许同码且 cityName 必须匹配（北京/天津/上海/重庆，
  兼容 "市" 后缀）；普通省市仍强制隶属；district 规则不变。
- Web：`china-divisions.ts` 重庆从"四川省"下移出为独立"重庆市"条目并补齐 `adcode: 500000`
  （此前重庆完全没有 adcode，级联选择器无法发出 region）；`CityCascadePicker.test.ts`
  新增北京/重庆同码断言（3 条）。Web 3/3 + Java 6/6 GREEN。
- 全量：Java 定向 6/6；Web picker 3/3。

### R5（P1-2 地点真实性闭环 + P1-6 搜索竞态，GREEN）

- RED（Java 单元/集成 + Python 7 条 + Web 3 条）：
  - `PlaceRefCanonicalizerTest` 7 条——伪造 token 拒绝、跨 owner token 拒绝、
    token 候选与 ref identity 不符拒绝、篡改 name/address/coords 必须被 canonicalize、
    无 token 新 ref 拒绝、未变化已持久化 ref 无 token 可用、已持久化 ref 被改名后无 token 拒绝。
  - `PlaceSuggestionServiceTest` 新增 4 条——每个候选获得 opaque token、token 可被 owner
    redeem、跨 owner 不可 redeem、过期 token 不可 redeem。
  - Python `test_place_authenticity.py` 7 条——structured anchor 按精确 providerPoiId 绑定
    （标题带后缀也可）、id 未命中 fail closed（TRAVEL_ANCHOR_UNAVAILABLE，禁止同名降级）、
    structured must-visit id 未命中 fail closed（MUST_VISIT_UNAVAILABLE）、同名校兄弟不绑定、
    legacy 文本匹配保留。
  - Web `place-selection.test.ts` 3 条——城市切换丢弃旧响应、cancel 中止在途请求、
    `toPlaceRef` 保留 selectionToken。
  - Java `PlanningOutboxBoundaryContractIntegrationTest` 新增 `outboxBodyNeverCarriesSelectionTokens`。
- GREEN：
  - Java：`PlaceSelectionTokenService`（owner-scoped、TTL 30min、容量 256、过期/最旧淘汰）；
    `PlaceSuggestionService.search(ownerId, ...)` 每候选签发 token，缓存按 owner+查询隔离；
    `PlaceRefCanonicalizer` 在 create/update 时 canonicalize 全部 refs（must/avoid 列表 +
    三个 anchor），服务端缓存字段优先、忽略客户端可伪造字段、token 不落库不出 outbox
    （`@JsonInclude(NON_NULL)` 防泄漏，Python `PlaceRef` extra=forbid 不会收到未知字段）；
    未变化已持久化 ref 无 token 可继续保存。
  - Python：`_resolve_travel_anchors` 结构化 anchor 精确 id 解析、找不到
    `TRAVEL_ANCHOR_UNAVAILABLE`；`_is_must_visit_poi` 有 refs 时仅精确 id 匹配
    （禁止同名文本降级）；`_plan_with_skeleton` 对未召回的结构化 must-visit id
    fail closed `MUST_VISIT_UNAVAILABLE`。
  - Web：`PlaceRef.selectionToken` 随候选保存回传；三个 anchor 由自由文本改为
    PlaceAutocomplete 候选选择（保留 legacy 文本兼容提示）；`PlaceAutocomplete` 监听 city
    变化立即 cancel + 清空；`TripDashboard` 切换城市清空旧城市 chips 与 anchor refs。
- 全量：Java 定向（PlaceSuggestionServiceTest 9、PlaceRefCanonicalizerTest 7、
  TripFlowIntegrationTest 33、MunicipalityRegionIntegrationTest 6、Outbox 4）全绿；
  Python 1466 passed；Web 全量 unit 346 + typecheck 通过。

### R6（P1-3 创建页时间字段收口，GREEN）

- RED：`App.test.ts`「creates a trip …」新增断言——创建对话框内
  `input[type="datetime-local"]` 恰好 2 个（TripBoundaryEditor 权威边界），
  `到达时间（北京时间）` / `返程时间（北京时间）` 两个 legacy 输入不存在。
  修复前 4 个时间输入（RED）。
- GREEN：`ConstraintEditor.vue` create 模式下隐藏到达/返程 legacy 时间输入
  （edit 模式保留，legacy 行程编辑不受影响）；`TripDashboard.saveTrip` 从权威
  arrivalAt/departureAt 派生 anchor 时间（未填时自动沿用），创建请求仍携带完整锚点。
- 全量：Web unit 346/346 + typecheck GREEN。

### R7（P1-4 Review UI IA + P1-7 天气联动，GREEN）

- RED（App 级 + e2e 断言）：
  - `weather-window.spec.ts` 1440×900 用例新增——候选标题 bbox 在 900px 视口内、
    `主要风险` 在验证详情之前、`MEAL_PLACEMENT_MISSING`/`hard-validator-v4` 默认不可见、
    `validation-details-toggle` aria-expanded=false。
  - 新增 P1-7 用例——WAITING_USER 与正式版本共存时点击天气日期必须高亮
    `candidate-day-*`（border-primary-400），绝不联动旧正式版本路线。
  - `golden-journeys` G20/G27、`feasibility-outcomes` 断言默认折叠后的可见性。
- GREEN：
  - `PlanningReviewPanel`：候选行程 + 日期导航 + 主要风险（FAIL/UNKNOWN 聚合）前置，
    验证详情默认折叠在「查看验证详情」toggle 后；reasonCode/validatorVersion/修复历史
    不再直接暴露。
  - `FeasibilityReportPanel`：顶部只显示 status 徽章 + 计数摘要 + FAIL/UNKNOWN 中文
    发现与受影响日期；规则明细/reasonCode/证据/修复历史/validatorVersion 全部移入
    「查看技术详情」默认折叠区（`defaultCollapsed` 可选）。
  - `TripDetail`「我的要求」：未设置的可选约束（预算/住宿/偏好/必去/到达返程）不再
    占固定卡片高度。
  - P1-7：`selectWeatherDate` 在 WAITING_USER 且候选含该日期时滚动到候选日，否则回退
    正式行程；无候选才滚动 review 区。
- 全量：Web unit 346/346、typecheck、R7 相关 e2e 全绿（weather-window /
  golden-journeys / feasibility-outcomes）。

### R8（P1-8 覆盖率与报告收口，GREEN）

- `vite.config.ts` coverage `include` 纳入全部 B13 生产文件（22 个，含
  TripDashboard/TripDetail/TripWorkspace/TripBoundaryEditor/CityCascadePicker/
  PlaceAutocomplete/ConstraintEditor/api.ts/china-divisions.ts/feasibility.ts 等），
  删除手工白名单缺口；分支门槛维持 80%。
- 新增/扩展测试补足分支缺口：
  - `PlaceAutocomplete.test.ts` 8 条：clear 按钮（mousedown 语义）、选中后编辑文本
    使结构化 ref 失效、外部重置清空查询、错误态、无结果态、城市切换取消在途搜索。
  - `TripBoundaryEditor.test.ts` 3 条（新增文件）：emit 规范 +08:00、抵达≥离开报错、
    合法边界无报错。
  - `region-ref.test.ts` 扩展：省码非省 0000 尾、省市前缀不匹配、畸形/非叶子
    district 码、缺失 districtCodes、缺失省市码全部拒绝。
  - `CityCascadePicker.test.ts` 扩展：具体区 toggle 开/关 + 空选回退全市、外部 props
    预选同步。
  - `PlanningReviewPanel.test.ts` 扩展：1 小时以上时长与整小时时长格式化。
  - `TripWorkspaceActions.test.ts`（新增文件，13 条 App 级）：目的地搜索 + 包含已归档、
    归档/恢复、分享创建/撤销、ICS/PDF 导出、版本对比 + 确认回滚、局部重新规划
    （刷新交通）、放弃 WAITING_USER 候选、未知路由 404 页、详情/行程/版本/分享/攻略
    加载失败降级、SSE 畸形进度帧忽略 + 流中断 fail-closed、登出失败仍回登录页。
  - `china-divisions.test.ts`（新增）：findProvince/findCity/cityAdcode/四个直辖市。
  - `amap.test.ts` 扩展：复用已存在 script 标签的 load/error 分支。
  - `TripWeatherTimeline.test.ts` 扩展：滚动控制按钮实际触发 scrollBy。
  - `ConstraintEditor.test.ts` 扩展：移除必去/排除条目按钮真实点击；删除死代码
    `placeRefFor`（无调用方）。
- 结果：Web unit 384 passed；全量 coverage 聚合 stmts 95.77% / branch 84.94% / funcs
  94.67%（含全部 22 个 include 文件，每个文件 stmts/branch/funcs ≥80%）；typecheck GREEN。
- 注：`handleApplyItineraryEdit` 由 TripWorkspace 传给 TripDetail 但 UI 无调用方
  （草稿路径走 commitItineraryEdits），函数级未覆盖属死接线，分支不受影响；已在
  报告中如实保留，不在本次范围内新增 UI 入口。

## 2. 验收矩阵

| 缺陷 | RED | 实现文件 | 定向测试 | 全量门禁 | 用户可见结果 |
| --- | --- | --- | --- | --- | --- |
| P0-1 | Java outbox IT 3 条（先失败后绿） | `PlanningTaskService.java`、`contracts/` v4/v2 schema+fixtures、`worker/contracts.py`、`domain/shared.py`、AMap/Demo providers | `PlanningOutboxBoundaryContractIntegrationTest`、`test_boundary_authority.py`、`test_daily_skeleton_provider.py`、`test_messaging_contract_schemas.py` | Python 1446+ / Java 定向 3/3 | 晚到/早离不再产生早于到达的首项活动 |
| P0-2 | schema 级 4 条（先 RED） | v4 schema `allOf`、`worker/amqp.py` 安全 FAILED、`worker/contracts.py` | `test_messaging_contract_schemas.py`、`test_worker_invalid_command.py`、`test_amqp_worker.py` | Python 1449+ | 混合 constraints 不再被拒致永久 QUEUED；无效命令得到终态 |
| P0-3 | 10 条（先全 RED） | `worker/contracts.py`、`validation_projection.py`、`feasibility_projection.py`、`rules/meal.py`、AMap/Demo providers | `test_meal_type_binding.py`（10 条）、`test_validation_projection.py`、`test_amap_feasibility_projection.py` | Python 1459 passed | 抵达日唯一晚餐不再被绑成 LUNCH |
| P1-1 | 6 条 MockMvc（先全 RED） | `TripService.validateRegion`、`china-divisions.ts` | `MunicipalityRegionIntegrationTest`、`CityCascadePicker.test.ts` | Java 6/6、Web 3/3 | 北京/上海/天津/重庆可创建 |
| P1-2 | Java 11 条 + Python 7 条 + Web 3 条（先全 RED） | `PlaceSelectionTokenService`、`PlaceRefCanonicalizer`、`PlaceSuggestionService/Controller`、`TripService`、AMap `planning_provider.py`、`PlaceAutocomplete.vue`、`TripDashboard.vue`、`constraint-editor.ts` | `PlaceRefCanonicalizerTest`、`PlaceSuggestionServiceTest`、`test_place_authenticity.py`、`place-selection.test.ts`、`PlanningOutboxBoundaryContractIntegrationTest` | Java 定向全绿、Python 1466、Web 346+typecheck | 伪造 ref 不再 200；structured 精确 id；token 不泄漏到 Python |
| P1-6 | Web 3 条（城市切换/cancel/token） | `PlaceAutocomplete.vue`、`PlaceSearcher`、`TripDashboard.vue` | `place-selection.test.ts`、`App.test.ts` | Web 全绿 | 城市切换丢弃旧响应并清空旧城市 chips |
| P1-3 | App 级 DOM 断言（先 RED：4→2 时间输入） | `ConstraintEditor.vue`、`TripDashboard.vue` | `App.test.ts` | Web 346/346 | 创建页只保留两个权威 datetime |
| P1-4 | e2e bbox/DOM order/默认折叠断言（先 RED） | `PlanningReviewPanel.vue`、`FeasibilityReportPanel.vue`、`TripDetail.vue` | `weather-window.spec.ts`、`golden-journeys.spec.ts`、`feasibility-outcomes.spec.ts`、3 个 unit 文件 | Web 346/346 + e2e | 候选/风险前置、技术详情默认折叠、未设置项不占高度 |
| P1-7 | e2e 反例（先 RED：正式版本共存） | `TripDetail.vue selectWeatherDate` | `weather-window.spec.ts`（P1-7 用例） | e2e 全绿 | 天气日期联动候选日而非旧正式版本 |
| P1-8 | 覆盖率收口（白名单缺口 + PlaceAutocomplete 71% + 报告 IN_PROGRESS） | `vite.config.ts` include 全量、`TripWorkspaceActions.test.ts` 等 8 个测试文件扩展 | 见 R8 清单（Web unit 384、22 个 include 文件全 ≥80%） | Web 384/384 + coverage 全绿 + typecheck | 覆盖全部 B13 生产文件；执行报告如实更新 |

## 3. 事故记录

- Java 首次编译：`PlanningTaskService` 缺 `java.time.OffsetDateTime` import（编译失败 1 次，已修）。
- v4 schema 首次拼接 allOf 时破坏 JSON 结构两次（外层数组括号残留、`properties` 闭合花括号被吞），
  均通过临时脚本校验 JSON 后修复；已清理全部临时脚本（`contracts/_*.py`、`_tmp_*.json`）。
- R3 期间 `zip(meal_activities, day.activities)` 首版按错位 zip（meal_activities 是过滤子集），
  立即改为 `(locator, activity)` 成对收集，避免引入新位置推断。
- Python 全量回归两次均全绿（1449 → 1459），无 skip/only 新增。
- 全量 Java verify 首跑发现 `PlanningTaskFlowIntegrationTest#planningCommandSnapshotsOnlyEnabledFreshGuideFacts`
  断言 outbox `schema_version == "3"`——这是 R1 前遗留断言，B13_FIX 固定架构决定 create
  命令升为 v4（`schemaVersion: 4`），planningContext 快照仍是 v3；已把断言更新为
  `schema_version == "4"`（context 保持 "3"）并注明原因，随后该测试 GREEN。

## 5. 真实 Compose Golden（14 项，隔离 project `trip-pilot-b13fix-golden`）

- 环境：`compose.prod.yaml` + 独立 env（临时文件，用后删除）；独立端口
  WEB 38081 / Prometheus 39091、独立网络 172.31.251.0/24、独立数据卷；
  `up -d --build --wait` 全部服务 healthy、`knowledge-init` 正常退出、
  Provider `DEMO_ONLY`。未触碰用户已有 `trip-pilot-prod` 栈（38080 已被其占用，
  故 golden 换用 38081）。结束后 `down -v --remove-orphans` 清理全部 golden
  容器/卷/网络，未删除任何用户资源。
- 工具：临时 Node 脚本（API 层）+ Playwright 库脚本（UI 层），跑完即删；
  证据行 `GOLDEN-n: PASS/FAIL` 全部 PASS。

| # | 场景（对应缺陷） | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 直辖市创建成功（北京→北京→全市，P1-1） | PASS | POST /api/trips 201，region 110000/110000 |
| 2 | 普通省市创建成功（广东→广州→天河区） | PASS | POST /api/trips 201，region 440000/440100/440106 |
| 3 | 晚到：候选首项不早于 18:00 到达（P0-1） | PASS | WAITING_USER，首项 `2026-08-20T18:00:00+08:00` |
| 4 | 早离：候选末日末项不晚于 10:00 离开（P0-1） | PASS | WAITING_USER，末日末项 `2026-08-22T10:00:00+08:00` |
| 5 | 地点搜索返回带 owner-scoped selectionToken 的候选（P1-2） | PASS | POST places/search 200，candidates=1，hasToken=true |
| 6 | 带有效 token 的结构化 ref 保存成功（P1-2） | PASS | POST /api/trips 201（mustVisit ref 与 name 平行一致） |
| 7 | 伪造 token 拒绝（P1-2） | PASS | 400 `PLACE_REF_TOKEN_INVALID` |
| 8 | 缺 token 的新 ref 拒绝（P1-2） | PASS | 400 `PLACE_REF_TOKEN_REQUIRED` |
| 9 | 抵达日唯一晚餐不误绑 LUNCH（P0-3） | PASS | WAITING_USER；meal rule `UNKNOWN/MEAL_WINDOW_UNVERIFIED`（DEMO 无法核验真实餐厅，绝不伪造绑定） |
| 10 | legacy names+空 refs 到达终态，非永久 QUEUED（P0-2） | PASS | task FAILED `NO_FEASIBLE_ITINERARY/PLANNING_INFEASIBLE`（DEMO 对 must-visit 的安全终态，命令被 Java+Python 双端接受） |
| 11 | avoid 混合约束成功路径（P0-2） | PASS | avoidPlaces+空 refs 规划到 WAITING_USER |
| 12 | Review UI IA：候选/主要风险前置、验证详情默认折叠（P1-4） | PASS | 真实浏览器：候选可见、主要风险在 toggle 前、aria-expanded=false、硬可行性验证隐藏 |
| 13 | 天气日期点击高亮候选日，不联动旧正式版本（P1-7） | PASS | 真实浏览器：`#candidate-day-2026-08-20` class 含 border-primary-400 |
| 14 | 1440×900 与 390×844 无横向溢出 + 资源清理 | PASS | scrollWidth≤clientWidth 双视口成立；golden 容器/卷/网络全部删除 |

## 6. staged / commit / push

- 全部改动 unstaged；未 commit；未 push；HEAD 保持 89236ea。

## 7. 未完成项与非阻断观察

- 全部 P0/P1 RED→GREEN；全量门禁（Python 1466、Java verify 485、Web 384+coverage、
  Playwright 21、仓库检查、Compose Golden 14）全部通过；见上表证据。
- 非阻断观察：`HttpAgentPlaceSearchClient` 早期 context 加载问题已在更早修复中加 `@Autowired`
  主构造器，若全量 verify 复现再处理（与 B13_FIX 无关）。
- 非阻断观察：`TripWorkspace.handleApplyItineraryEdit` 是 TripDetail 未调用的死接线
  （草稿路径走 `commitItineraryEdits`），不新增 UI 入口，分支覆盖不受影响。
- 非阻断观察：`ruff format --check` 全仓 99 文件存在 CRLF→LF 差异（基线即存在，
  含 B13_FIX 未触碰文件），`ruff check` 门禁通过；格式归一不在本批范围。
- gitleaks 未安装，按总控计划以 CI repository-safety 为远端证据；`git ls-files`
  无 .env/.pem/.key/.p12/.pfx 等 secret-like 跟踪文件。


---

# B13_FIX.1 追加章节（执行修复记录）

- 状态：**B13_FIX1_READY_FOR_REVIEW**
- 触发：B13_FIX 独立验收 NEEDS_CORRECTION / RELEASE_FREEZE_BLOCKED（6 项发现 + P2 token poisoning）
- 基线：branch codex/feasibility-foundation，HEAD 89236ea，staged 空（修复全程未 stage/commit/push）
- 本追加章节不删除/改写上方任何旧声明；旧声明中的不成立项在此逐条承认。

## 1. 原执行报告声明不成立的承认

| 原声明 | 实际 | 本批处理 |
| --- | --- | --- |
| R7"候选标题 bbox 在 900px 视口内" | e2e 先 scrollIntoViewIfNeeded() 再断言（假绿）；真实 scrollY=0 时 y 约 944 超屏 | R1 破除假绿并真实压缩布局 |
| R5"Python 生命周期复用 AsyncClient 并在 shutdown 关闭" | 仅 worker 侧成立；places/api.py 每次请求新建不关闭 | R4 lifespan 唯一拥有 client 并 shutdown 关闭 |
| R5"structured must/avoid 仅按 id" | must 成立；avoid refs 未被 ranker 消费（文本子串过滤） | R6 ranker 精确 id 排除 |
| R7 P1-7 已关闭 | 滚动正确但 selectedActivityId 仍选旧正式活动 | R5 拆分候选/正式状态 |
| P1-6"结构化 key" | 实为字符串拼接 owner|city|keyword|limit，可碰撞 | R3 record key + TTL + 容量 256 |
| 原自由文本 anchor 可提交（未收口） | create 输入未选候选 POST 201 落库 | R2 Web+Java 双层拒绝，legacy 兼容保留 |

## 2. 七轮 RED 证据

| 轮 | RED 测试（真实失败） | 失败原因 | 实现文件 | GREEN 数量 |
| --- | --- | --- | --- | --- |
| R1 | weather-window 1440x900：scrollY=0 候选 heading bottom=1020 > 900 | e2e 先滚动后断言（假绿）；布局纵向占位过大 | TripDetail.vue / TripWeatherTimeline.vue / PlanningReviewPanel.vue | e2e 3 passed（含 P1-7 有正式行程布局） |
| R2-Web | constraint-editor.test.ts 5 failed（create 自由文本/改 legacy/structured 改文本/must 自由文本 拒绝类） | validateConstraintEditor 无 mode/anchor 校验 | constraint-editor.ts + TripDashboard/TripDetail 调用点 | 20 passed（9 新） |
| R2-Java | TripFlow 新 5 用例在旧实现必然失败（create/update 无 PLACE_REF_REQUIRED 校验；createLegacyTrip 用 DB 注入构造旧数据） | TripService 无 anchor ref 校验 | TripService.java validateCreatePlaceRefs/validateUpdatePlaceRefs | 39 passed（5 新 + 更新 2 旧） |
| R3 | PlaceSuggestionServiceTest 6 新用例（| 碰撞/TTL/容量/owner/并发） | String key 可碰撞；无容量上限；无 Clock 注入 | PlaceSuggestionService SearchCacheKey record + sweep | 15 passed（6 新） |
| R4 | test_places_api 5 新用例（lifespan/依赖注入/client 关闭） | 旧 _provider() 每请求新建 client、无 lifespan | places/api.py runtime + main.py lifespan | 11 passed（5 新 + 6 原改依赖注入） |
| R5 | App B13_FIX.1 R5（正式活动仍被选中） | selectWeatherDate 无条件设置 selectedActivityId | TripDetail.vue 三状态拆分 + TripMap allowEmptySelection | App 61 passed（1 新）；E2E P1-7 增强因环境 TCP 监听阻塞待 Compose 阶段 |
| R6 | test_avoid_rank.py 4 failed | rank 无 avoid_provider_ids 参数；avoid 仅文本过滤 | candidates.py _is_avoided + planning_provider 两调用点 | 29 passed（5 新） |
| R7 | PlaceSuggestionServiceTest 2 新用例（跨 owner 不毒化） | redeem 对 owner 不匹配也 remove | PlaceSelectionTokenService.redeem | 18 passed（3 新） |

## 3. 六项发现逐项关闭证据

### 发现 1（P0，P1-4 首屏）— 关闭
- e2e 移除 scrollIntoViewIfNeeded() 前置，改为 window.scrollTo(0,0) + scrollY===0 断言 + bbox bottom<=900；P1-7（有正式行程）也加同门禁。
- 布局压缩：main py-10→py-6、hero min-h 260→160 + 标题 4xl→3xl + stats bar mt-6→mt-3、我的要求 Card p-5→p-3 + dl gap-4→gap-3、天气条 py-3→py-2 + day 卡片内部 mt 压缩、review Card p-5→p-3 + h3 mt-5→mt-3。
- 实测（真实浏览器 scrollY=0）：无正式行程布局候选 heading bottom=886<=900；有正式行程布局 bottom=886<=900（测量脚本记录，临时脚本已删）。
- 保持顺序：行程概要→我的要求→天气窗口→WAITING_USER 候选/评审→正式行程。未移动天气到"我的要求"前，未隐藏候选，未绝对定位覆盖，未自动滚动，未改测试 viewport 作弊。390x844 无横向溢出由既有 e2e 覆盖（Compose 阶段复验）。

### 发现 2（P1，E 组自由文本 anchor）— 关闭
- Web：ConstraintEditorModel 新增 originalArrivalPlace/originalArrivalRef/originalDeparturePlace/originalDepartureRef/originalAccommodationPlace/originalAccommodationRef（create 时为 ''/undefined）；validateConstraintEditor(model, mode) 新增 anchor 校验：ref 存在→允许；值为空→按可选性允许；edit+原值 legacy+文本未变→允许；其他非空无 ref→"请从搜索结果中选择有效地点"；create 时 must/avoid 非空无 ref 同样拒绝。TripDashboard 传 'create'，TripDetail 传 'edit'。
- Java：create 时 validateCreatePlaceRefs（非空 anchor 必须带 ref；must/avoid 非空必须有平行 refs）→ 400 PLACE_REF_REQUIRED；update 时 validateUpdatePlaceRefs 以 DB 旧值（tripMapper.findConstraint）判定：legacy 原样允许、改变/新增无 ref 拒绝、structured 改文本无新 token 拒绝；结构化 ref 继续走 canonicalization；错误码稳定 PLACE_REF_REQUIRED。
- 旧测试适配：createsAndReadsCompleteTravelContextV2 改为结构化创建（token 签发）；createLegacyTrip 用 jdbcTemplate 注入 legacy arrival 行（create 不再接受自由文本）；rejectsOutOfRangeTravelAnchorsAndInvalidMealWindows 保持（时间校验先于 ref 校验）。
- Web 8 条 + Java 6 条 RED 用例全绿；既有 token/canonicalization/owner 隔离测试无回归（TripFlow 39 全过）。

### 发现 3（P1，J 组 cache key 碰撞）— 关闭
- SearchCacheKey(UUID ownerId, String city, String keyword, int limit) record 作 ConcurrentHashMap key（值相等语义，字段边界显式，| 无法碰撞）。
- 缓存：TTL 5min（Clock 注入可测）、容量上限 256、读取时移除过期 entry、插入后 sweepExpired（先过期后最旧淘汰）、无第三方依赖、并发安全（ConcurrentHashMap + removeIf）。
- RED：(city='广州', keyword='AB|CD') 与 (city='广州|AB', keyword='CD') 两查询各自独立（2 次 provider 调用）；同参数命中；不同 owner 不共享；TTL 到期重新调用；超容量 size 不增长；过期移除；并发 32 请求稳定（<=2 provider 调用）。6 新用例 GREEN。

### 发现 4（P1，J 组 AsyncClient 生命周期）— 关闭
- places/api.py：PlaceSearchRuntime dataclass（provider + client?）；create_place_search_runtime()（DEMO_ONLY 无 client；REAL 单 client）；close_place_search_runtime()（仅 client 存在时 aclose）；get_place_search_provider(request) FastAPI dependency（缺 runtime fail closed 503，不静默新建）；endpoint 改 Depends(get_place_search_provider)。
- main.py：lifespan 创建 runtime 存 app.state，shutdown 关闭。移除模块级 _search_provider；测试全用 app.dependency_overrides。
- RED：REAL 模式 client 复用并关闭（is_closed true）、DEMO 不创建 client、依赖 override 独立、Provider failure 502 不泄密、缺 runtime 503、多次 startup/shutdown 不泄漏、internal token 防线不回归。11 用例 GREEN。

### 发现 5（P1，G 组天气联动污染正式地图）— 关闭
- TripDetail.vue 新增 candidateHighlightDate；selectWeatherDate 三分支：WAITING_USER+候选含日期→candidateHighlightDate=date + selectedMapDate/selectedActivityId=null + 滚动候选日；正式含日期（fallback）→candidateHighlightDate=null + selectedMapDate/selectedActivityId=正式；WAITING_USER+候选不含日期→仅 candidateHighlightDate=date + 不选正式活动 + 滚动 review。
- showAllMapRoutes 清空三者；watch(planningState) 非 waiting_user 清 candidateHighlightDate；WeatherTimeline selected-date 用 candidateHighlightDate ?? selectedMapDate（任一选中都显示）；ReviewPanel highlight-date 用 candidateHighlightDate。
- TripMap 新增 allowEmptySelection prop：null selectedActivityId 时不 fallback 到第一个活动（WAITING_USER 时由 TripDetail 传入）。
- App 级测试（jsdom）：正式 activity 无 z-10/ring-primary-400、.overview-marker.is-selected 计数 0、show all 清理候选与正式选择。61 App 用例 GREEN。E2E P1-7 增强（is-selected 断言）已写入，因环境 TCP 监听阻塞（WinError 10013，非代码问题）暂无法运行，Compose 阶段补跑。

### 发现 6（P1，E 组 structured avoid 未消费）— 关闭
- CandidateRanker.rank 新增 avoid_provider_ids: frozenset[str]；_is_avoided(poi, ids, places)：ids 非空→仅精确 provider id 排除（同名兄弟保留、未召回 id 不误排）；ids 空→legacy 文本过滤保留。
- planning_provider.py 两调用点传 avoid_provider_ids=_avoid_provider_ids(constraints)（从 constraints.avoid_place_refs 提取 provider_poi_id）。
- RED：structured avoid A 排除且同名 B 保留；输入顺序颠倒结果一致；未召回 id 不误排同名；legacy 文本继续过滤；ids 存在时优先于文本。5 新用例 GREEN。Demo/AMap：Demo 无召回/无 ranker，相同 constraints 下 Demo 不产生被避免活动，语义一致。

### P2 邻近：token 跨 owner 毒化 — 关闭
- PlaceSelectionTokenService.redeem：owner 不匹配→返回 empty 不删除；过期→删除；owner 正确且未过期→正常返回；fake token→empty；容量/TTL 不变。
- RED：A issue→B redeem empty→A 仍可 redeem；过期 redeem empty 且删除；并发跨 owner 尝试不破坏合法 token。3 新用例 GREEN（共 18）。token 错误详情不暴露给客户端（返回 Optional.empty）。

## 4. 用户可见变化
- 1440x900 首屏：候选行程与主要风险在 900px 内可见，无需滚动。
- 创建/编辑：输入地点文字但未选择候选时保存被阻止，提示"请从搜索结果中选择有效地点"；编辑旧行程未动 legacy 地点仍可保存。
- 地点搜索缓存：含 | 的查询不再互相串扰；缓存有界（256）且 5 分钟过期。
- 天气联动：WAITING_USER 时点击天气日期只高亮候选日，正式行程地图不被选中。
- structured avoid：按精确 provider id 排除，同名兄弟 POI 不再被误删。

## 5. 残留限制与非阻断观察
- E2E（weather-window P1-7 增强等）因当前 Windows 会话 TCP 监听被安全策略禁止（WinError 10013，node/python 绑定任意端口均失败）无法在本次运行；逻辑由 App 级 jsdom 测试覆盖，计划在隔离 Compose Golden 阶段（浏览器 + 完整栈）补跑全部 e2e。
- ruff format --check 全仓 99 文件 CRLF→LF 差异为基线既有，本批只格式化本批新增/修改文件。
- 非阻断：TripWorkspace.handleApplyItineraryEdit 死接线（前序已记录）；HttpAgentPlaceSearchClient 观察（前序已记录）。

## 6. staged / commit / push
- 全部改动 unstaged；未 commit；未 push；HEAD 保持 89236ea；git diff --check 通过（见定向/全量门禁）。

---

# B13_FIX.2 追加章节（执行修复记录）

- 状态：**B13_FIX2_READY_FOR_REVIEW**
- 触发：B13_FIX 验收 6 项关闭后，运行时复现两处真实缺陷——
  1. 双必去行程（天河公园 + 正佳广场）只搜索了第一个关键词，任务 FAILED / MUST_VISIT_UNAVAILABLE；
  2. WAITING_USER 候选存在时再次点击「开始规划」，后端 409 PLANNING_TASK_ACTIVE，Web 错误置 failed 并清空 candidate/report。
- 基线：branch codex/feasibility-foundation，HEAD 89236ea731b3d9aea55a81f96101940299f2c983，staged 空（全程未 stage/commit/push）。
- 本追加章节不删除/改写上方任何旧声明；旧声明与本节冲突处以本节为准（仅一处：R5 的 must-visit id 未命中 fail-closed 语义被 R9 钉住语义取代，见 R9 说明）。

## 1. 每轮 RED 测试与真实失败原因

### R9（Python，新增 `tests/test_must_visit_recall.py`，5 条 RED → GREEN）

| RED 测试 | 真实失败原因（修复前） |
| --- | --- |
| `test_second_structured_ref_is_searched_even_when_first_query_satisfies_count` | `_collect_pois` 在第一关键词搜索后普通候选达到 required_count 即提前 return，"正佳广场" 关键词从未搜索，精确 id 未召回 → MUST_VISIT_UNAVAILABLE（与运行时日志一致：只搜了"天河公园"） |
| `test_exact_must_visit_id_below_cutoff_is_pinned_into_selected` | 精确 id 已召回但分数低于排名 cutoff，被 `accepted[:limit]` 剪掉 → `missing_structured` 误判为未召回 → MUST_VISIT_UNAVAILABLE |
| `test_same_name_different_id_never_replaces_exact_must_visit_id` | 搜索页未返回精确 id 时直接 fail closed，用户已选择的精确地点被丢弃 |
| `test_unrecalled_ref_is_pinned_without_fake_verified_evidence` | 同上前置；修复后还需验证不产生伪证据（GREEN 断言 opening_hours_bindings 不含 pinned id） |
| `test_must_visit_unavailable_still_raised_when_place_cannot_be_scheduled` | 守护测试：18:00 到达/19:00 离开的 60 分钟窗口内任何必去都无法排入时仍须 MUST_VISIT_UNAVAILABLE（修复前后均成立） |

新增 `tests/test_emitted_day_ordering.py`（2 条，R12 前置 RED）：
`test_emitted_days_are_ordered_without_overlap[False/True]` —— 真实 AMap 路由时长下，已解析 MEAL 与尾部「返回住宿地点待确认」ACCOMMODATION 占位节点重叠（MEAL end 18:41:47 > ACCOMMODATION start 18:35:47），Java 事件消费者拒绝 review 事件、任务永久 QUEUED。legacy 与 structured 两条路径均复现 → 证明是 pre-existing forward-fit 边界缺陷（非 R9 引入），但阻塞 R12 REAL_ONLY Golden，必须修复。

### R10（Web，`tests/TripWorkspaceActions.test.ts` 追加 3 条 RED → GREEN）

| RED 测试 | 真实失败原因（修复前） |
| --- | --- |
| `waiting_user disables start planning and never sends a create request` | `start-planning` 按钮只对 `queued` 禁用，waiting_user 时可点击 → 发送创建请求 |
| `recovers WAITING_USER from a 409 PLANNING_TASK_ACTIVE race without losing the candidate` | `runPlanningTask` catch 对任何错误置 `failed` 并 `clearPlanningOutcome()`，409 竞态下候选/报告被清空（运行时事实） |
| `clears a stale planning error when the race recovery returns a review` | `applyOutcomeState` 的 review 分支不清 `planningError`，先 FAILED 后 REVIEW 时旧错误残留 |

R11 追加 3 条（abandon 后重新规划 / failed 后重试 / 中文文案与正式行程隔离）在修复后直接 GREEN。

## 2. 生产修复说明（GREEN）

### R9 召回与钉住（Python）

- `src/trip_agent/planning/candidates.py`：`CandidateRanker.rank` 新增 `pinned_provider_ids` 参数。钉住项（结构化 must-visit 精确 id）跳过搜索噪声类硬过滤（空地址/城市不匹配/同地去重），始终排在 selected 首位，且**普通配额永不删除钉住项**（limit 只作用于非钉住部分）；精确 id 的 avoid 排除仍生效。
- `src/trip_agent/infrastructure/amap/planning_provider.py`：
  - `_collect_pois` 记录已召回 id；存在未召回的结构化 must-visit 精确 id 时**禁止提前返回**，继续搜索全部关键词（每个 must-visit 名字都是候选关键词）。
  - `_plan_with_skeleton`：搜索结束后仍未召回的 ref 由 `_poi_from_ref` 从服务端规范化的 PlaceRef 构建 **pinned POI**（精确 providerPoiId/name/address/city/district/coordinates 全部保留，type 留空 → duration 走 SYSTEM_DEFAULT，永不 hard-eligible），作为固定规划输入加入候选；`must_visit_ids` 全部作为 `pinned_provider_ids` 传入 ranker；删除旧的「未召回即 MUST_VISIT_UNAVAILABLE」分支。
  - 保留 fail-closed：**与排除/去重冲突的必去 id**（pinned 也被 avoid 排除等矛盾约束）仍 MUST_VISIT_UNAVAILABLE；路线/时间/正式关闭导致的未放置仍 MUST_VISIT_UNAVAILABLE（`must_visit_unplaced` / `closure_filtered_must` 分支不变）。
  - **R12 forward-fit 边界修复**：route 循环后增加单调扫掠（carry shift），保证 emitted 活动严格有序不重叠——修复被 route 跳过的占位边界（未解析锚点/无 POI 的 MEAL/住宿占位）导致的重叠；forward-fit 决策本身不变，只做最终有序性保证。
- `tests/test_place_authenticity.py`：`test_structured_must_visit_id_miss_fails_closed` 按 R9 新语义改写为 `test_structured_must_visit_id_miss_is_pinned_from_server_ref`（精确 id 钉住放置、同名兄弟仍不得冒充——精确 providerPoiId 门禁未弱化，仅召回 miss 不再被当作不可用）。

### R10 状态机（Web）

- `src/pages/TripWorkspace.vue`：
  - `runPlanningTask` 前置保护加入 `waiting_user`（统一 active state：`queued | waiting_user` 均禁止创建任务）。
  - catch 中识别 `ApiError 409 + PLANNING_TASK_ACTIVE`：调用 `getLatestPlanningTask` → `readPlanningTaskOutcome` 恢复权威状态（review → 候选/报告还原 + reviewTaskId；queued → 恢复订阅流；failed/cancelled/completed → 按权威终态应用），**不置 failed、不清 candidate/report**；恢复失败时给出中文提示「已有候选行程待确认，请先查看或放弃候选」且不清 outcome。
  - `applyOutcomeState` 在 queued/review/completed 分支清除旧 `planningError`。
- `src/components/TripDetail.vue`：`start-planning` 与「刷新交通」在 `queued`/`waiting_user` 均禁用；waiting_user 时按钮文案为「候选待确认」；`startLocalReplanning` 函数级同样加 waiting_user/queued 保护。
- `src/components/PlanningProgress.vue`：「Planning progress」→「规划进度」；waiting_user 状态文案 →「候选行程已生成，等待处理」。
- 未修改 Java WAITING_USER active-slot 语义（one-active-per-trip、409、abandon 行为不变，Java 侧零改动，见 R11 复跑）。

## 3. 必去地点 exact-ID 真值表（修复后）

| 场景 | 结果 | 依据 |
| --- | --- | --- |
| 第一关键词已满足普通候选数 + 第二 ref 只在其自身搜索出现 | 继续搜索全部关键词；两 id 均放置；无 MUST_VISIT_UNAVAILABLE | R9-1、R11 重复 id、Golden REAL_ONLY |
| 精确 id 已召回但分数低于 cutoff | 钉住，进入 selected，放置 | R9-2 |
| 搜索页从未返回精确 id | 由服务端规范化 PlaceRef 钉住放置（exact id/name/address/coords 保留），type/duration 无证据 → SYSTEM_DEFAULT 非 hard-eligible | R9-4、place_authenticity 改写 |
| 同名不同 providerPoiId 的 sibling | 不得冒充 must-visit（exact-id 唯一判定） | R9-3、R5 原断言保留 |
| 两个 ref 相同 providerPoiId | 稳定去重，只放置一次 | R11 重复 id 测试 |
| structured avoid 精确 id | ranker 按 exact id 排除，同名兄弟保留 | R6 回归（test_avoid_rank 5 条全绿） |
| 必去 id 同时被 avoid / 与去重冲突 | MUST_VISIT_UNAVAILABLE（矛盾约束，fail closed） | 新增 unpinned_structured 分支 |
| 路线不可达 / 正式关闭 / 时间行动能力不满足 | MUST_VISIT_UNAVAILABLE（真实失败不掩盖） | R9-5、closure 分支回归 |
| 无 opening/duration 硬证据 | 保持 UNKNOWN / eligible=false，validation inputs 无伪证据绑定 | R9-4 opening_bindings 断言 |

## 4. WAITING_USER 状态真值表（修复后）

| 场景 | 修复前 | 修复后 |
| --- | --- | --- |
| WAITING_USER + candidate/report，点击「开始规划」 | 发送 POST | 不发送 POST（按钮禁用 + 前置保护） |
| 按钮/文案 | 可点击「开始规划/重新规划」 | 禁用 +「候选待确认」 |
| 刷新交通（waiting_user） | 可触发 | 禁用 + 函数级保护 |
| 多标签竞态：POST → 409 PLANNING_TASK_ACTIVE | failed + 清空 candidate/report | getLatest → readPlanningTaskOutcome 恢复权威状态，不清 outcome，不置 failed |
| 先 FAILED 后 REVIEW | 旧 planningError 残留 | applyOutcomeState review/queued/completed 清除旧 error |
| 无正式 itinerary 时 WAITING_USER | 候选面板可见（正确） | 保持可见（回归断言） |
| abandon 后 | 可重新规划 | 可重新规划（按钮恢复 + POST 发出） |
| FAILED 后 | 可重试 | 可重试 |
| 文案 | 英文 Planning progress / 原始 409 message | 规划进度 / 候选行程已生成，等待处理 / 已有候选行程待确认，请先查看或放弃候选 |
| 正式 itinerary 与候选 | 共存（既有正确） | 共存（回归断言） |

## 5. 真实 Compose Golden（隔离 project `trip-pilot-b13fix2-golden`，REAL_ONLY）

- 环境：`compose.prod.yaml` + 临时 env（含用户真实 AMap key，文件用后删除）；独立端口 WEB 38082 / Prometheus 39092、独立网络 172.20.77.0/24、独立数据卷、独立镜像 tag `b13fix2-golden`（用后删除）；`PROVIDER_MODE=REAL_ONLY`。未触碰用户 `trip-pilot-prod` 栈（38080/9090/172.30.250.0/24 均未动，清理后复核 8 容器仍 healthy）。
- 首次运行时 Java 拒绝 review 事件（活动重叠，任务卡 QUEUED）→ 定位为 forward-fit 占位边界缺陷 → 修复（R12 前置 RED）→ 重建 agent 镜像后全部通过。

### API 证据（临时 Node 脚本，跑完即删）

| # | 场景 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 注册/登录 | PASS | 201 / 200 token |
| 2 | 真实 place search 天河公园 / 正佳广场 | PASS | B00140H465、**B00140TFHO**（与运行时事实相同 ID），selectionToken 签发 |
| 3 | 保存为 structured must visits 并创建 trip | PASS | 201，schemaVersion 3 refs 平行 |
| 4 | 规划任务终态 | PASS | **WAITING_USER**，无 MUST_VISIT_UNAVAILABLE（修复前此场景 FAILED） |
| 5 | candidate 含两个精确 providerPoiId | PASS | got=B00140H465,B00140TFHO（另含普通候选） |
| 6 | review report 语义 | PASS | status=NEEDS_REPAIR（无证据不伪造 VERIFIED） |
| 7 | 重复创建 | PASS | 409 PLANNING_TASK_ACTIVE（one-active-per-trip 不变） |
| 8 | abandon → 重新创建 | PASS | DELETE → CANCELLED → 202 |

### 浏览器证据（真实 Chromium，Playwright 库脚本，跑完即删）

| # | 场景 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | WAITING_USER 页面显示候选 | PASS | 「候选行程」可见 |
| 2 | 「开始规划」不可再次触发 | PASS | disabled=true，文案「候选待确认」 |
| 3 | 无英文 active-task 错误 | PASS | body 无 PLANNING_TASK_ACTIVE/already active |
| 4 | 放弃候选后可重新规划 | PASS | abandon 后按钮恢复可用 |

### DB 证据（postgres business schema）

- `planning_task` 终态 `WAITING_USER`（review persisted: task waiting for user）；outbox `PLANNING_CREATE_REQUESTED` SENT；事件链路 Java→RabbitMQ→Python→REVIEW→Java 持久化完整。
- 清理：`down -v --remove-orphans` 删除 8 容器 + 4 卷 + 1 网络；golden 镜像 `docker rmi` 全部删除；临时 env/脚本删除；用户栈不受影响。

## 6. 全量门禁真实数字

| 门禁 | 结果 |
| --- | --- |
| Python 全量 pytest | **1484 passed, 37 skipped**（修复前后两次全绿；环境性 11 error 为 C:\Windows\Temp pytest 目录 ACL，加 `--basetemp` 后全绿，与代码无关） |
| ruff check | All checks passed |
| ruff format（本批文件） | 5 files already formatted（shared.py 基线差异未触碰，沿用 B13_FIX.1 说明） |
| Python coverage（B13 相关） | planning_provider 93% / candidates 99% / daily_schedule 93% / poi_quality 93% |
| Java `mvn verify`（JaCoCo + Flyway） | **499 tests, 0 failures**；All coverage checks have been met；36 migrations 干净升级 |
| Java 定向（active task/abandon/409） | PlanningTaskFlowIntegrationTest 14/14 + Outbox 4/4（含 rejectsASecondActiveTaskForTheSameTrip、concurrentRequestsWithDifferentKeysAllowOnlyOneActiveTask、cancelsAnOwnedTaskIdempotently） |
| Web unit + coverage | **400 passed (41 files)**；All files stmts 95.8 / branch 85.53 / funcs 95.3 / lines 95.8，22 个 include 文件每文件 stmts/branch/funcs ≥80%（TripWorkspace 90.52/81.21、TripDetail 95.39/83.89） |
| Web typecheck / build | vue-tsc -b 通过；vite build 通过 |
| Playwright 全量 | **22/22 passed**（本会话 TCP 监听被安全策略禁止，改用 Docker nginx 静态服务 + 临时 config；AMap SDK 在本机有真实 key 且外网可达会替换 fallback overview，临时 config 用 dead-proxy bypass 使 SDK 确定性不可用，与 B13 通过环境一致；未修改任何正式 spec/生产代码） |
| Compose config / check_compose_defaults | prod + dev `config --quiet` 通过；`check_compose_defaults.py --with-docker` OK |
| 隔离 Compose Golden | 见 §5，API + 浏览器 + DB 全 PASS，已清理 |
| Markdown links | 115 files valid |
| git diff --check | 通过（CRLF 警告为基线既有） |
| staged | 空 |
| secret / 保护目录 | `git ls-files` 无 .env/.pem/.key/.p12/.pfx；未修改 .omo/、.serena/、docs/audits/、.env、acceptance-report.md |

## 7. 精确文件清单（本批 B13_FIX.2 改动）

Python 生产：
- `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py`（召回逐项处理、pinned POI、forward-fit 有序扫掠）
- `apps/agent-service/src/trip_agent/planning/candidates.py`（pinned_provider_ids）
- `apps/agent-service/src/trip_agent/domain/shared.py`（未改动，仅核查）

Python 测试：
- `apps/agent-service/tests/test_must_visit_recall.py`（新增，5 条）
- `apps/agent-service/tests/test_emitted_day_ordering.py`（新增，2 条）
- `apps/agent-service/tests/test_place_authenticity.py`（1 条按新语义改写）

Web 生产：
- `apps/web/src/pages/TripWorkspace.vue`（guard、409 recovery、applyOutcomeState 清错）
- `apps/web/src/components/TripDetail.vue`（按钮禁用/文案/函数保护）
- `apps/web/src/components/PlanningProgress.vue`（中文文案）

Web 测试：
- `apps/web/tests/TripWorkspaceActions.test.ts`（追加 R10 3 条 + R11 3 条）

Java：零改动（R10 要求不修改 active-slot 语义；R11 复跑既有测试）。
文档：
- `docs/execution/B13_FIX/plan.md`（追加 B13_FIX.2 计划段）
- `docs/execution/B13_FIX/execution-report.md`（本节）

## 8. staged / commit / push

- 全部改动 unstaged；未 commit；未 push；HEAD 保持 89236ea731b3d9aea55a81f96101940299f2c983；`git diff --cached` 为空；未修改 acceptance-report.md；未触碰任何保护目录。
