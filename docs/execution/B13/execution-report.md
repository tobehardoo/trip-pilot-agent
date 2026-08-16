# B13 执行报告：统一创建入口、创建行程表单重构、结构化目的地与真实地点选择

- 状态：**IN_PROGRESS（全量门禁通过，等待独立验收）**——工作组 A/B/C/E/F/D/G/I 已实现；最终输出 `B13_READY_FOR_REVIEW`（unstaged、未 commit、未 push）

## 1. 开始前 Git 状态（已核对）

- branch：`codex/feasibility-foundation`；HEAD：`89236ea731b3d9aea55a81f96101940299f2c983`（与任务预期一致）
- staged：空；tracked 工作树：干净；仅存在且未处理：`.omo/`、`.serena/`、`docs/audits/`、`.env`

## 2. 真实调用链审计（摘要，全部经 grep/read 核实）

- NLP/模板/ConstraintCard/constraint-parser 均只被 `TripDashboard.vue` 消费 → A 组整体删除可行。
- `CityCascadePicker`+`china-divisions`+`RegionRefInput`+V32 `region_ref` 已存在 → B 组复用并接线。
- `CreateTripRequest.title` `@NotBlank`、`TripService.updateConstraints` 已有乐观锁样板 → C 组改造。
- `TripRecord/TripSnapshotRecord/TripMapper` 为 @AutomapConstructor 记录 → E 组字段扩展方式确定。
- Python `MapProvider.search_pois`/`DemoMapProvider` 与 agent-api（仅 /health）已核实 → D 组将在 agent main 增加受保护搜索端点 + Java RestClient 代理（复用 `HttpGuideIntelligenceClient` 样板）。
- `worker/contracts.py::MealWindow` 无 source；Java `TripRequests.MealWindow` 无 source → F 组 additive。

## 3. RED→GREEN 证据（真实记录）

### A 组（统一入口）
- RED（vitest，基线 TripDashboard 还原后运行 `-t 'B13-A'`）：**4/4 失败**——模板/NLP 存在、空状态第二个按钮存在、目的地默认 `广州`（`expected '' to be '广州'`×2）。
- 实现：`TripDashboard.vue` 重写（删除 NLP/draft/ConstraintCard/模板/空状态第二按钮；`resetForm` 目的地为空；唯一 `openCreateTrip`）；删除 `NaturalLanguageInput.vue`、`TripTemplates.vue`、`ConstraintCard.vue`、`lib/constraint-parser.ts`、`tests/constraint-parser.test.ts`；`TripDashboard.test.ts` 模板预填测试替换为唯一入口测试。
- GREEN：`tests/App.test.ts` 53/53（含 4 个新用例）+ `TripDashboard.test.ts` 2/2。

### B 组（省市区级联）
- 复用 `CityCascadePicker`；修正 label `for/id` 关联（`getByLabelText` 可用）；`TripDashboard` 以级联替换自由文本目的地，提交 `destination=cityName` + `region=destinationToRegionRef(selection)`。
- 测试（新增 3 例 + 既有 3 例改写为级联）：天河区 440106 结构化提交、江门全市 districtCodes=[]、切换城市清空区。GREEN：55/55。

### C 组（可选标题 + 自动生成 + 改名）
- Java：`TripTitleGenerator`（Asia/Shanghai 纯函数）+ `TripTitleGeneratorTest`（6 例）；`CreateTripRequest.title` 可选；`TripService.create` 空标题生成默认；新增 `PUT /api/trips/{tripId}/metadata`（owner + `updateTitleOwned` 乐观锁，409 `TRIP_VERSION_CONFLICT`，空标题回退默认，绝不存空串）；`TripFlowIntegrationTest` +3 例（缺标题生成、改名/乐观锁/空标题回退、owner 隔离）。
- Web：`lib/trip-title.ts`（与 Java 字节级一致；修掉两处漂移：同年判断取反、空城市短路）+ `trip-title.test.ts`（6 例）；`TripDashboard` 标题可选 + 实时预览；`TripDetail` 行内改名 UI；`TripWorkspace.handleRenameTrip`；App 测试 +3 例（空标题不带 title、改名 PUT、409 文案）。
- GREEN：Java 31/31（25 集成含 3 新增 + 6 生成器）；Web 全绿。

### E 组（arrivalAt/departureAt 双边界）
- Java：V35（`trip.arrival_at/departure_at TIMESTAMPTZ` 可空 + both-or-neither CHECK + 顺序 CHECK，不改 V1–V34）；`TripRecord/TripSnapshotRecord` +2 字段；`TripMapper` 全 select/insert 扩展；`CreateTripRequest` 接受 arrivalAt/departureAt（startDate/endDate 兼容可空）；`TripService.resolveBoundaries`：datetime 路径推导 Asia/Shanghai 日期、顺序校验、缺一/全缺 400 `TRIP_BOUNDARIES_INVALID`；旧日期路径不伪造时间；`TripResponse` +2 字段。
- 测试：`TripPaceMigrationIntegrationTest` +1（V34→V35 升级：旧行 null 边界、CHECK 双约束、合法更新）；`TripFlowIntegrationTest` +4（+08 边界投影与 DB 真值、UTC→China 日期投影、部分/逆序 400、旧日期兼容且不伪造时间）。
- Web：`TripBoundaryEditor.vue`（datetime-local → `+08:00` 规范串）；`CreateTripInput` 改为 arrivalAt/departureAt；`TripDashboard` 校验（必须成对、抵达<离开）；标题预览改用边界日期推导。
- GREEN：Java 门禁通过（TripTitleGeneratorTest+TripFlowIntegrationTest+TripPaceMigrationIntegrationTest BUILD SUCCESS）。

### F 组（meal source 三态：DEFAULT/USER/DISABLED）
- Python RED（先写测试后实现）：`tests/feasibility/test_meal_window_rule.py` +6（DEFAULT-only 不适用、DEFAULT 越界不 FAIL、DISABLED 不受约束、混合仅 USER FAIL、混合 DEFAULT 越界不 FAIL USER 通过、无 source 按 USER）；`tests/test_meal_window_placement.py` +5（DEFAULT 有空间放窗内、DEFAULT 无空间回退默认分钟且无 CONFLICT 警告、USER 无空间仍 CONFLICT、DISABLED 无 demand 无警告、DISABLED 晚餐保留 USER 午餐）；`tests/test_meal_window_source.py` +5（source 缺省 USER、三态解析、非法值拒绝、command 接受 source 无需新版本、无 source 命令按 USER）；`tests/test_validation_projection.py` +2（DISABLED 不进入 zip、按餐型而非声明顺序绑定）。首轮 RED：**16 failed / 28 passed**（含 zip 错绑 `{'DINNER': 0, 'LUNCH': 1}` 实证）。
- 实现：`worker/contracts.py::MealWindow` +`source: Literal["DEFAULT","USER","DISABLED"] = "USER"`（additive，v3 constraints 为 open object，无需新契约版本）；`daily_schedule.py` `MealWindowConstraint.source` + `_meal_demand`（DISABLED 抑制、USER 硬放置、DEFAULT 软建议失败回退默认分钟）+ `plan_day` 冲突警告仅 USER；`amap/planning_provider._meal_window_constraints` 携带 source；`rules/meal.py` 仅 USER 参与硬校验（DEFAULT/DISABLED → NOT_APPLICABLE）；`validation_projection._projected_meal_windows`（过滤 DISABLED/BREAKFAST，LUNCH→DINNER 规范序绑定，修复既有错绑）。
- Java：`TripRequests.MealWindow` +`source`（compact constructor null→USER，@Pattern DEFAULT|USER|DISABLED）；`TripFlowIntegrationTest` +2（三态回显+缺省 USER、非法 source 400）。RED：2/2 失败（`$.constraints.mealWindows[0].source` 不存在、未知 source 201 而非 400）。
- Web：`lib/api.ts` mealWindows item +`source?`；`constraint-editor.ts` `MealSource` + `MEAL_DEFAULT_WINDOWS`（08:00–09:00/12:00–13:00/18:00–19:00）+ 模型 `*Source` 字段（无窗口默认 DEFAULT、旧窗口无 source 按 USER）+ 校验仅 USER 需时间 + `buildMealWindows` 三态序列化；`ConstraintEditor.vue` 每餐「安排方式」三态 select（采用常用时间/自定义时间/不安排）+ 条件渲染时间输入；`constraint-editor.test.ts` +5；`App.test.ts` 创建/编辑 payload 断言更新为三 DEFAULT / 混合三态。
- GREEN：Python 全量 **1390 passed / 37 skipped**；Java 目标用例 2/2 通过（Flyway v35）；Web 全量 **311/311**。

### D 组（PlaceRef 真实地点搜索全链路）
- Python RED：`tests/test_places_api.py`（内部 token 401、demo 候选 estimated 标记、limit 边界、安全 502 不泄露原始信息）+ `tests/test_place_ref_contract.py`（PlaceRef 校验/非法 provider/坐标越界/字符串坐标拒绝、constraints v3 并行 refs、名称不匹配/长度不匹配拒绝、v2 拒绝 refs、anchor placeRef、v4 命令 ↔ constraints v3、v4 拒绝 v2、v3 拒绝 v3、v4 需 planningContext）+ schema 测试（v4 接受 fixture、拒绝未知 provider/错误版本）。首轮 RED：7 failed + 1 collection error（PlaceRef 不存在）。
- 契约：新增 `contracts/messaging/planning-create-command-v4.schema.json`（typed constraints + PlaceRef + mealWindow source，不动 v1–v3）+ `contracts/fixtures/planning-create-command-v4/valid.json`。
- 实现：`internal_security.py`（共享 token 守卫，guide api 复用）；`places/api.py`（POST /internal/v1/places/search，PROVIDER_MODE/AMAP key 环境解析，ProviderFailure → 安全 502）；`contracts.py` PlaceRef + anchors place_ref + constraints v3（并行 refs，schema_version<3 拒绝 refs）+ command v4（v4↔constraints3、v3↔2、v1↔1，fail-closed）；amap `_is_must_visit_poi` 支持 providerPoiId 精确匹配（结构化选择不降级为文本匹配）。
- Java：V36（`trip_constraint.must_visit_place_refs/avoid_place_refs JSONB` 可空，旧行 NULL 不升级）；`TripRequests.PlaceRefInput`（provider 白名单 AMAP|DEMO、坐标范围）+ anchors placeRef + 并行 refs 数组；`TripConstraintValidator` 并行/名称一致性校验；`TripService` schemaVersion 2/3 派生 + 序列化 + null-safe 读取；`PlanningTaskService` constraints v3 → 发布命令 v4（旧 trip 仍 v3）；`place/` 包：`PlaceSuggestionController`（POST /api/trips/places/search，owner JWT）+ `PlaceSuggestionService`（≥2 字符、limit 1–10、TTL 缓存、不写库）+ `HttpAgentPlaceSearchClient`（RestClient + X-Internal-Token，安全 502，复用 guide client 样板）。测试：TripFlowIntegrationTest +2（refs 三态回显+schemaVersion 3、名称/长度/provider 非法 400）+ PlaceSuggestionServiceTest 5 + HttpAgentPlaceSearchClientTest 2（MockRestServiceServer）。
- Web：`api.ts` PlaceRef/PlaceCandidate/searchPlaces；`lib/place-selection.ts`（PlaceSearcher：250ms 防抖、AbortController、≥2 字符、≤10 结果、过期响应丢弃、toPlaceRef 去传输标记、demo 判定）；`PlaceAutocomplete.vue`（下拉候选 + 演示徽标 + 编辑即失效 + 空态/错误态）；`ConstraintEditor.vue` 必去/排除改为「搜索选择 + chips」，全结构化才发 refs（旧自由文本永不升级）；TripDashboard/TripDetail/TripWorkspace 透传 getToken/city。测试：place-selection 8 + PlaceAutocomplete 4 + constraint-editor +3 + App.test.ts 编辑链路改写。
- GREEN：Python 全量 **1415 passed / 37 skipped**；Java 定向类通过；Web 全量通过。

### G 组（旅行方式与偏好整合）
- 新增 `TravelStyleEditor.vue`：单一「旅行方式与偏好」区域承载节奏/行动能力/偏好，域字段保持独立；`ConstraintEditor.vue` 移除旧的三个独立区块并删除重复的 mobility select。
- 测试：`TravelStyleEditor.test.ts` 3 例（单区域合并渲染、字段独立联动、序列化独立）+ 既有 App/constraint-editor 用例全绿（label 兼容）。

### I 组（恢复公共天气窗口）
- 修复前状态（代码审计确认）：天气条挂在正式 itinerary 的 v-else 分支内（旧 1007 行），WAITING_USER/planning 无正式行程时不渲染。
- **RED（真实捕获）**：将当前 TripDetail 天气区块临时移回正式 itinerary 分支（复现旧缺陷），运行 B13-I 回归测试 → **2/2 失败**（WAITING_USER + candidate + itinerary=null 无天气；queued 无正式行程无天气），证明回归测试能抓住该缺陷；恢复修复后 2/2 通过。
- 修复：天气窗口移出 itinerary 条件分支，置于「我的要求」之后、评审/进度/正式行程之前，任何 planning 状态（idle/queued/waiting_user/succeeded/failed/cancelled）且 trip 日期有效即渲染；`TripWeatherTimeline` 增加来源归因（和风天气/高德城市情报 + 安全 fxLink，来自城市情报 import 元数据）、「同步天气」按钮（复用 importGuide CITY_INTELLIGENCE 既有链路，不新增第二套天气 API）、同步中状态；日期联动：正式行程 → 滚动到 `day-{date}` 并过滤地图，WAITING_USER → 滚动到候选评审面板并高亮候选日（PlanningReviewPanel highlightDate），无日程 → 仅选择日期不报错，「查看全部行程」清除选择；空态沿用 待同步/历史天气尚未同步/预报未开放；Provider 失败不隐藏组件；横向紧凑条 + 移动端横向滚动不变；startDate/endDate 由 arrivalAt/departureAt 投影沿用（无后端改动，未发现独立后端缺陷）。
- 测试：TripWeatherTimeline +7（QWeather/AMap 归因、同步按钮/同步中、无事实、待同步时显示同步、无日程选择不报错）；App.test.ts +4（WAITING_USER 无正式行程仍显示天气 + 候选日期高亮 + Provider 失败安全空态、queued 无行程仍显示天气、failed 无行程仍显示天气、cancelled 无行程仍显示天气）；TripDetailItineraryEditing 1 例改为断言新行为（天气日期点击定位正式日程）；e2e `weather-window.spec.ts` 2 例（1440×900 天气条与候选行程在验证详情之前可见、同步天气复用城市情报链路）；SUCCEEDED 地图日期联动由既有 e2e（release-smoke「restores evaluation and links the weather date to the map route」）覆盖。
- 全量 Web 单测 **337/337**（含以上新增）。

## 4. 待办（下一轮继续）

- 全量门禁（Java mvn verify、Web build/e2e CI=1/coverage、Python ruff/pytest、仓库检查、DEMO smoke）+ 文档收口 + 总控计划 READY_FOR_REVIEW。

## 4a. 全量门禁结果（真实运行）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| Python 全量 | `pytest`（.venv，专用 basetemp） | **1415 passed / 37 skipped** |
| Python lint | `ruff check src tests` | All checks passed；本批文件 `ruff format --check` 8/9 通过（`contracts.py` 1 处 HEAD 基线既有格式漂移，未触碰） |
| Java 全量 | `mvn -q verify`（Maven 3.9.11，JAVA_HOME=LibericaJDK-21） | **BUILD SUCCESS**（463 tests，0 failures；Flyway 至 V36） |
| Web 单测 | `pnpm test` | **337 passed / 37 files** |
| Web 覆盖率 | `pnpm test:coverage` | **95.26% stmts / 84.15% branch / 92.37% funcs / 95.26% lines**（门槛 80%） |
| Web 类型/构建 | `pnpm typecheck` + `pnpm build` | 通过（0 errors；dist 正常产出） |
| Web e2e | `CI=1 pnpm exec playwright test` | **20/20 passed**（含新 `weather-window.spec.ts` 2 例） |
| 仓库 | `git diff --check` | 干净 |
| 仓库 | `docker compose config --quiet` + `check_compose_defaults.py` | 通过 |
| 仓库 | `check_markdown_links.py` | 通过 |
| 安全 | 变更文件密钥扫描（`AMAP_WEB_SERVICE_KEY`/`internal-token`/`.env` 未出现在源码/测试） | 通过 |

## 5. 事故记录（如实）

- 一次 PowerShell `Get-Content -Raw`（默认 cp936）重写 `App.test.ts` 造成中文乱码；已用 `git show HEAD:` + UTF8NoBOM 恢复并重新应用全部 B13 测试改动（工作树最终内容已通过定向测试验证）。
- 环境事实：`mvnw.cmd` 不存在（用显式 Maven 3.9.11）；`uv run` 本机静默失败（用 `.venv` python）；8080/8081 被 Windows 排除端口段占用（smoke 用 38080）。
- Web `PlaceSearcher` 默认绑定参数顺序错误（`searchPlaces(token, input, signal)` 被按 `(input, signal)` 调用，导致请求体变 `{}`）；由双自动完成组件测试暴露并修复。
- Java `HttpAgentPlaceSearchClient` 因测试缝 2 参构造器导致 Spring 无法选择构造器（"No default constructor found"，全量 verify 上下文加载失败）；以 `@Autowired` 标注主构造器修复。
- 全量 `mvn verify` 首轮 199 个上下文错误均为上述构造器问题级联；修复后 463 tests BUILD SUCCESS。
- 可选 compose DEMO_ONLY smoke 未运行：B13 未改动 compose 接线（B12 已验），Java 集成（真实 Postgres + Flyway V36）与 Web e2e 20 场景已覆盖运行链路。

## 6. staged / commit / push

- 全部改动 unstaged；未 commit；未 push。
