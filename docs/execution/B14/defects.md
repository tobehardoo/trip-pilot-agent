# B14 缺陷报告

缺陷编号规则：`B14-Dxx`；severity P0/P1/P2/P3；每项含复现、证据、修复方向与建议回归测试。独立审计批次未修改任何生产代码。

---

## B14-D01（P1，confidence=高）

- **affected scenarios**：S092、S093、S100（天气同步步骤）
- **用户可见现象**：行程详情页点击「同步天气/刷新天气」→ 报错「Guide intelligence service returned an invalid response」；天气区域无法获取数据。
- **最小复现输入**：REAL_ONLY 栈，任意 trip：`POST /api/trips/{tripId}/guide-imports` body `{"sourceType":"CITY_INTELLIGENCE","city":"广州","startDate":"2026-11-20","endDate":"2026-11-21"}`。
- **重现次数**：5/5（API 直调与浏览器 UI 均复现）。
- **预期/实际**：预期 200 + 天气导入成功（S092 场景）；实际 **502 `GUIDE_SERVICE_INVALID_RESPONSE`**。
- **卡住层/文件行号**：Java `GuideImportService.java`：`createRegisteredSource` L144 / `validateFetchedGuide` L354（`invalidServiceResponse()` L562）。agent-api `/internal/v1/guide-imports` 返回 200（容器日志），travel-server 对 agent 响应执行 `validateFetchedGuide` 契约校验失败（CITY_INTELLIGENCE 响应的 title/contentHash/sourceType 等不满足 `FetchedGuide` 校验：`contentHash` 需 `[a-f0-9]{64}`、title 非空 ≤300、fetchedAt 非空等）。
- **证据**：API 复现 `502 {"code":"GUIDE_SERVICE_INVALID_RESPONSE","message":"Guide intelligence service returned an invalid response"}`；浏览器 console `Failed to load resource 502` + alert 同文案；travel-server 日志无 parser Reject（非 MQ 层问题）；agent-api guide-imports 日志 200（契约在 Java 侧拒绝）。
- **数据损坏**：否（无写入；导入失败无孤儿行）。
- **是否阻塞发布冻结**：**是**（用户可见核心功能「天气同步」在 REAL 模式不可用；S092/S093 场景失败）。
- **最小修复方向**：对照 `agent guide_intelligence/api.py GuideImportResponse` 与 Java `GuideImportService.validateFetchedGuide` 的契约字段（contentHash 64-hex、title/sourceUrl/finalUrl/sourceHost/excerpt/fetchedAt 必填），使 CITY_INTELLIGENCE 响应满足校验，或按 sourceType 放宽/对齐校验（不弱化安全字段）。
- **建议回归测试**：REAL 模式 API 测试：CITY_INTELLIGENCE guide-import 返回 200 且 facts 落库；Java 单测：构造 agent 真实响应形状过 validateFetchedGuide。

---

## B14-D02（P2，confidence=高）

- **affected scenarios**：S007（跨用户访问）
- **用户可见现象**：用户 B 访问用户 A 的 `GET /api/trips/{tripId}/itinerary/versions` 返回 **200 空列表**（其余端点 trip/itinerary/task 均正确 404）。
- **最小复现**：A 建 trip（含正式版本后仍 200 空）→ B 请求 versions 端点。
- **重现次数**：3/3。
- **预期/实际**：预期 404（owner 隔离）；实际 200 + `[]`。
- **文件行号**：versions 列表端点缺少 owner 过滤（与 trip/itinerary 端点的 `get(ownerId, tripId)` 模式不一致；版本查询未以 owner 限定）。
- **证据**：`B-user versions status: 200 body: []`（A 有正式版本后 B 仍 200 空）；`B-user itinerary: 404`、`latest: 404` 对照。
- **数据损坏**：否（无内容泄露，仅响应状态差异泄露 trip id 存在性——枚举面）。
- **是否阻塞发布冻结**：否（P2，但建议随 P1 修复批次处理）。
- **最小修复方向**：versions 端点先 `tripService.get(ownerId, tripId)`（或查询加 owner 条件），非 owner 返回 404。
- **建议回归测试**：S007 场景扩展：B 访问 A 的 versions 断言 404。

---

## B14-D03（P2，confidence=高）

- **affected scenarios**：S038（选中地点后切换目的地）
- **用户可见现象**：在广州搜索选中的候选（selectionToken 绑定广州查询）可被保存到**北京**行程（create 201，ref 原样保留 city=广州市）。
- **最小复现**：`place_search(city=广州, keyword=天河公园)` 取 token → `POST /api/trips` destination=北京 + mustVisitPlaceRefs=[该 token ref] → 201。
- **重现次数**：3/3。
- **预期/实际**：预期拒绝（token 应绑定城市/查询上下文，防跨城市注入）；实际 201 且 ref 保留广州坐标/城市，REAL 规划将把广州 POI 放入北京行程。
- **文件行号**：`PlaceSelectionTokenService` redeem 仅校验 owner+TTL+存在；`PlaceRefCanonicalizer` 未校验 token 对应城市与 trip destination 一致。
- **证据**：`cross-city create: 201`，响应 constraints.mustVisitPlaceRefs[0] 保留 `city=广州市, longitude=113.36`（destination=北京）；对照 S037（篡改坐标 999.9 → 400）说明 token 校验不覆盖城市维度。
- **数据损坏**：否（数据一致性问题：跨城市地点注入影响规划质量与证据真实性）。
- **是否阻塞发布冻结**：否（P2；建议与 D01 同批修复）。
- **最小修复方向**：token 缓存记录增加 city（已有 cache key 含 city）并在 redeem/canonicalize 时校验 token 城市与行程 destination 匹配；不匹配 400。
- **建议回归测试**：S038 扩展：跨城市 token 创建 400；同城市创建 201。

---

## B14-D04（P2，confidence=高）

- **affected scenarios**：S039（地点搜索无结果）
- **用户可见现象**：搜索无意义关键词（`asdfghjklqwerty`）→ **502 `PLACE_SEARCH_UNAVAILABLE`**；中文无结果词则返回 200+模糊候选（AMap 模糊匹配）。
- **最小复现**：`POST /api/trips/places/search {"city":"广州","keyword":"asdfghjklqwerty","limit":5}`。
- **重现次数**：3/3（ASCII 无意义词稳定 502；中文词 200+模糊）。
- **预期/实际**：预期 200（空/模糊结果）或明确业务错误；实际 502（agent 对该查询返回 502，travel-server 映射 PLACE_SEARCH_UNAVAILABLE）。
- **文件行号**：agent `places/api.py` 对 AMap 异常查询的 502 映射（B13_FIX.1 R4 设计为安全 502 不泄密）；`travel-server` `HttpAgentPlaceSearchClient` → `PLACE_SEARCH_UNAVAILABLE`。
- **证据**：`kw=asdfghjklqwerty status=502 body={'code':'PLACE_SEARCH_UNAVAILABLE',...}`；`kw=天河公园/不存在的中文词 status=200`；agent-api 日志对应请求 502。
- **数据损坏**：否。
- **是否阻塞发布冻结**：否（P2）。
- **最小修复方向**：agent 对 AMap 空/异常参数结果区分「无结果」（200 空）与「上游错误」（502）；或 travel-server 对 PLACE_SEARCH_UNAVAILABLE 展示中文「搜索暂时不可用」而非原始英文。
- **建议回归测试**：S039 参数化：多个无意义词断言 200 或稳定错误码（非 502 抖动）；Web 搜索失败态中文文案。

---

## B14-D05（P2，confidence=高）

- **affected scenarios**：S051-S080 全部规划场景（UI 观察）、B01-B30 浏览器流程、B14-P0 专项
- **用户可见现象**：规划进度步骤列表中「筛选地点优先级/计算交通路线/协调时间预算偏好/执行修复/发布规划结果」显示**未执行**，但业务实际执行（REAL 日志有真实搜索/路线调用；DEMO 有求解与发布）。
- **最小复现**：任意 REAL 规划任务 → task_event 序列只有 TASK_ACCEPTED/CONTEXT_VALIDATING/CITY_FACTS_LOADING/POI_RECALLING/KNOWLEDGE_RETRIEVING/RESULT_EXPLAINING/RESULT_PUBLISHING（**缺 CANDIDATES_RANKING/ROUTES_CALCULATING/CONSTRAINTS_SOLVING/REPAIRING**）；DEMO 更少（3 阶段）。
- **重现次数**：稳定（所有 REAL 任务；DEMO 任务）。
- **预期/实际**：预期：执行过的阶段有 progress 事件或 UI 明确「该阶段无进度事件」；实际：UI 按 observedStages 呈现「未执行」。
- **卡住层**：分类 I（只有 progress 事件缺失，实际业务步骤已执行）——**非卡死**。
- **文件行号**：`worker/processor.py`/AMap provider 的 `report_planning_progress` 调用点不全（部分阶段未上报）；`PlanningProgress.vue` 步骤状态按 observedStages 推断。
- **证据**：DB task_event 序列（REAL 7 阶段缺 4 阶段）；provider 日志真实执行路线调用；UI `planning-stage-*` 步骤显示未执行（浏览器截图）。
- **数据损坏**：否。**是否阻塞发布冻结**：否（P2，可观测性/文案）。
- **最小修复方向**：provider 各真实执行阶段补 `report_planning_progress`（或 UI 对未收到事件的阶段显示「无进度事件/执行中」而非「未执行」）。
- **建议回归测试**：REAL 规划任务断言 progress 事件覆盖所有真实执行阶段；UI 文案断言。

---

## B14-D06（P3，confidence=中 — 环境/数据波动）

- **affected scenarios**：S043（五个结构化必去点）、Web unit 5s 超时（App.test.ts/TripWorkspaceActions.test.ts 4 个用例 3 轮全量各 1-2 个超时）
- **现象 1**：S043 5 个真实必去 3 天首跑 NO_FEASIBLE_ITINERARY（affected 为动态搜索候选，某次含 FULL_DAY 度假区型 POI），单独复跑同参数 WAITING_USER（5/5 放置）。系统 fail-closed 正确（2 天排 5 必去本地亦不可行），属动态候选波动 → flaky。
- **现象 2**：Web unit 全量运行（coverage）3 轮分别 4/2/1 个 5000ms 超时（refreshes an expired access token / stale list snapshot / updates constraints / compares an older version），**单独重跑 4/4 全过**（单测耗时 0.9-4.9s，全量时 jsdom 环境叠加超 5s）；同代码 B13_FIX.2 全绿 400/400 → 本机环境性能（vitest collect 120-350s）导致硬超时 flaky，非代码回归。
- **文件行号**：无（测试基建超时阈值 5s 与机器负载）。
- **证据**：单独 `vitest run -t` 4 passed；全量日志 5000ms Timeout；S043 首败/复跑对照。
- **是否阻塞发布冻结**：否（P3；建议 CI 环境与本地负载差异记录在案）。

---

## B14-D07（P3，confidence=高 — 可观测性）

- **affected scenarios**：S090（REAL_ONLY 缺 Key）
- **现象**：REAL_ONLY 且 AMAP key 为空时 worker 启动失败（fail-closed ✓ 不静默回退 DEMO），但错误为 pydantic `ValidationError`（`WorkerSettings` 校验，含 host 字段）而非明确的「AMAP_WEB_SERVICE_KEY required」。
- **最小复现**：`docker run ... -e PROVIDER_MODE=REAL_ONLY -e AMAP_WEB_SERVICE_KEY= trip-pilot-agent-service:b14-acceptance ... WorkerSettings()`。
- **预期/实际**：预期明确配置错误；实际 pydantic ValidationError。
- **是否阻塞发布冻结**：否（P3）。
- **修复方向**：WorkerSettings 对 REAL 模式缺 key 抛业务化配置错误。

---

## B14-D08（P3，confidence=中 — 候选质量观察）

- **affected scenarios**：S043/S045/S048 及 Web 候选选择
- **现象**：place search 首选候选可能是基础设施 POI（如「陈家祠(公交站)」BV10015239），用户从下拉选择时可能选中公交站 → 必去保存后 REAL 规划 fail-closed（该 POI 被活动过滤 → 「必去地点与排除或去重约束冲突」提示，文案误导，实为"该 POI 不可作为活动"）。
- **文件行号**：Web `PlaceAutocomplete.vue` 候选排序无基础设施过滤；失败文案 `unpinned_structured` 分支（B13_FIX.2）。
- **是否阻塞发布冻结**：否（P3）。

---

## B14-D09（P3 观察 — Provider 配额）

- **affected scenarios**：R01-20 及 REAL 样本
- **现象**：REAL_ONLY 高频运行时 AMap ROUTE 接口出现 `category=RATE_LIMITED` 重试（retry_count 1-2 后成功；重试机制正确）；place search 无 429（429s=0）。属上游配额压力，重试与安全回退工作正常。
- **是否阻塞发布冻结**：否（观察记录，配额记录见 execution-report）。
