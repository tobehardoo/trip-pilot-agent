# B13 执行计划：统一创建入口、创建行程表单重构、结构化目的地与真实地点选择

- 文档状态：生效中
- 批次：B13
- 基线 branch：`codex/feasibility-foundation`；基线 HEAD：`89236ea731b3d9aea55a81f96101940299f2c983`（B12 提交）
- 关联总控：[系统完善长期执行与验收总控计划](../../product/系统完善长期执行与验收总控计划.md)

## 1. 当前事实审计（已按代码核实，非臆造）

- Web 创建面在 `apps/web/src/components/TripDashboard.vue`：顶部唯一主按钮“创建旅行” + 空状态第二个“创建第一条旅行”按钮 + `TripTemplates`（广州 City Walk/长沙美食之旅/杭州周末游 3 个硬编码模板，trips.length<=2 时展示）+ `NaturalLanguageInput`（“用一句话描述旅行计划”textarea + 解析按钮）+ `ConstraintCard` + `parseConstraint`（`lib/constraint-parser.ts`）+ `form.destination` 默认 `'广州'`（resetForm 同样重置为广州）+ `destinationGradientMap`（6 城市外观样式映射，非表单默认值）。
- 消费面（git grep 核实）：`NaturalLanguageInput`、`TripTemplates`、`ConstraintCard`、`lib/constraint-parser` 均只被 `TripDashboard` 消费 → 删除入口后可整体删除，无其他真实消费者。
- `lib/constraint-draft.ts` 已有 `StructuredDestination`、`destinationToRegionRef`、`REGION_DATASET_VERSION='2023-06-30'`；`api.ts` 已有 `RegionRef` 类型与 `Trip.region`；Java `TripRequests.RegionRefInput` + `TripService.validateRegion` + V32 `trip.region_ref JSONB` 已存在；`TripService.planningCoverage` 已按 region 计算。
- `CityCascadePicker.vue` + `CityCascadePicker.test.ts` + `lib/china-divisions.ts` 已存在（省→市→区级联、全市互斥逻辑基本齐全，需修正外部 props 同步与默认空）。
- Java `CreateTripRequest`：title `@NotBlank`、destination `@NotBlank`、startDate/endDate `LocalDate`、constraints（含 arrival/departure `TravelAnchor{placeName,time}`、mealWindows 无 source、mobilityLevel）。`TripService.updateConstraints` 已用 `incrementVersion(tripId, ownerId, expectedVersion)` 乐观锁。无 metadata 更新接口。
- 契约：`worker/contracts.py::TripConstraints` schema_version Literal[1,2]（v2 现行）、`MealWindow{meal_type,start_time,end_time}` 无 source；`providers/map.py` 已有 `MapProvider.search_pois(PoiSearchRequest{city,keyword,limit}) → ProviderSuccess[tuple[Poi,...]]|ProviderFailure`，`Poi` 含 provider_id/name/coordinates/province/city/district/address/type_name/type_code；`DemoMapProvider.search_pois` 返回确定性 demo POI（`estimated=True`、`provider_id=demo-*`）。
- agent-api（`trip_agent/main.py`）当前仅 `/health`；Java 已有 RestClient 调 agent-api 的样板（`guide/HttpGuideIntelligenceClient`，`app.agent.base-url` + `app.agent.internal-token`）。
- V1–V34 已发布；下一可用迁移号 V35。消息契约活跃版本：planning-create-command **v3**、candidate-validation v1、replan v1；completed v9/review v1 等。当前 DB 最新版本 V34。

## 2. 数据模型

- **RegionRef（已有，补齐使用）**：provinceCode/cityCode/districtCodes/provinceName/cityName/districtNames/datasetVersion；`trip.region_ref` JSONB（V32）；新建表单初始 province/city/districts 全空。
- **PlaceRef（新增，additive）**：provider、providerPoiId、name、address、province、city、district、longitude、latitude；全部带长度/类型/坐标范围/provider 白名单校验；挂到 arrival/departure/accommodation/mustVisitPlaces/avoidPlaces（与旧 placeName 并存：PlaceRef 优先，placeName 为显示兜底；旧自由文本永远 legacy，不升级）。
- **旅程边界（新增，V35）**：`trip.arrival_at/departure_at TIMESTAMPTZ`（可空，兼容旧数据）；`startDate/endDate` 保留为投影列与规则依据；CHECK `arrival_at < departure_at` 且两列同空或同非空。
- **MealWindow source（新增三态，契约 additive）**：`DEFAULT|USER|DISABLED`；旧契约无 source 的 meal window 一律按 USER 兼容（不降级历史硬要求）。
- **标题**：`title` 改为可选；服务端确定性纯函数生成默认标题（Asia/Shanghai）；`PUT /api/trips/{tripId}/metadata`（title + expectedVersion，乐观锁 409）。

## 3. API 与消息流

- 创建：`POST /api/trips`（title 可选；region 必须由级联产生；arrivalAt/departureAt 主输入，服务端投影 startDate/endDate；兼容：旧客户端仍可发 startDate/endDate）。
- 改名：`PUT /api/trips/{tripId}/metadata`（owner-scoped、乐观锁、空标题按产品语义兜底为自动名，不存空串）。
- 地点搜索：`Web PlaceAutocomplete → GET/POST /api/trips/places/search（owner JWT）→ Java PlaceSuggestionService（RestClient + internal token）→ agent-api POST /internal/places/search → MapProvider.search_pois`；浏览器永不接触 AMap key；DEMO_ONLY 返回明确 demo 标记候选；TTL 缓存；搜索不写库。
- 消息：planning create command 需携带 PlaceRef 与 meal source 时发布 **v4**（新增文件，不动 v3）；startDate/endDate 投影保留。

## 4. Flyway/契约演进策略

- V35：`trip.arrival_at/departure_at`（可空、CHECK、兼容回填不伪造时间）；需要时为 PlaceRef 增加约束字段；禁止改 V1–V34。
- 契约：planning-create-command-v4.schema.json + fixtures（valid/invalid）+ Python `PlanningCreateCommand` v4 模型 + Java 侧解析更新；旧版本 fail-closed 不变。

## 5. RED/GREEN 测试顺序（每组先写测试，记录真实 RED；立即通过则记录 characterization GREEN）

1. A：删除模板/NLP/重复入口/默认城市（Web 单测 + e2e）。
2. B：级联选择、上级变更清空下级与 PlaceRef、RegionRef 提交与旧数据兼容。
3. C：自动标题纯函数（前后端一致）、自定义优先、服务端兜底、PUT metadata + 409。
4. D：PlaceRef 校验器、Python 搜索端点、Java 代理、Web autocomplete（未选候选禁止提交）。
5. E：arrivalAt/departureAt 派生/校验、V35、旧数据兼容、契约投影。
6. F：meal source 三态跨层真值表（DEFAULT 不产生 FAIL、USER 参与 MEAL_WINDOW、DISABLED 不投影）。
7. G：旅行方式与偏好 UI 整合、字段独立序列化（单测 + e2e）。
8. 跨层/E2E/golden、旧 trip/旧契约/DEMO_ONLY 回归、文档收口。

## 6. 兼容旧数据方案

- 旧 trip 无 region_ref：列表/详情仍显示 destination 字符串；编辑目的地时提示重新选择，不伪造行政区代码。
- 旧 trip 无 arrival_at/departure_at：按 startDate/endDate 显示日期，时间为空，不伪造具体时间。
- 旧 meal window 无 source：按 USER 兼容。
- 旧自由文本地点：legacy/unverified 展示，仅用户编辑时要求重新选择。

## 7. 安全不变量（不可违反）

- 地点只能来自候选，自由文本永不提交为地点；DEMO 候选永不标记 VERIFIED evidence；浏览器永不接触 AMap Web Service Key/internal token；Provider 错误用安全错误码与文案，不写原始响应/URL/key 到日志。
- candidate/current 隔离、only-VERIFIED 持久化、Hard Validation 语义不变。
- 旧消息版本与旧 fixtures 行为不变；旧 Flyway 不改。
- 不得用 as any/@ts-ignore/@ts-expect-error/测试 .only/.skip/sleep 规避。

## 8. 文件范围

- 删除：`apps/web/src/components/{NaturalLanguageInput,TripTemplates,ConstraintCard}.vue`、`apps/web/src/lib/constraint-parser.ts`、`apps/web/tests/constraint-parser.test.ts`（先确认无其他消费者）。
- 修改：`TripDashboard.vue`（统一入口+新表单）、`TripWorkspace.vue`（改名入口/边界提交）、`constraint-draft.ts`/`constraint-editor.ts`、`CityCascadePicker.vue`、`lib/api.ts`、`App.test.ts`、相关 e2e。
- 新增：`PlaceAutocomplete.vue`、`TripBoundaryEditor.vue`、`TravelStyleEditor.vue`、`MealPreferencesEditor.vue`、`lib/place-selection.ts`、`lib/trip-title.ts`；Java `TripMetadataRequest`/`PlaceSearch*`/`V35__*.sql`；Python agent 搜索端点 + 契约 v4 + 测试。
- 文档：README、docs/index（如需）、docs/architecture/规划工作流.md、docs/architecture/行程真实性与旅行骨架.md、docs/development/代码架构导读.md、docs/operations/本地运行指南.md、docs/product/项目路线图.md、docs/product/系统完善长期执行与验收总控计划.md。

## 9. 验收矩阵

对应任务书 35 项验收场景逐条映射到测试（见执行报告 §验收矩阵）。

## 10. 停止条件

- 实现与定向/全量门禁通过；文档完成；`git diff --check` 干净；staged 空；未 commit/push；`docs/execution/B13/acceptance-report.md` 不存在（留给独立验收 Agent）；总控计划 B13 标记 `READY_FOR_REVIEW（未提交）`；最终输出 `B13_READY_FOR_REVIEW`。存在无法关闭的真实缺陷则输出 `B13_BLOCKED` 并给出证据。
