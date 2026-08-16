# B14_FIX 独立验收报告

- 状态：**B14_FIX_NEEDS_CORRECTION / RELEASE_FREEZE_BLOCKED**
- 验收方式：独立审查 + 独立复跑（不复用执行 Agent 的任何测试输出；未修改任何生产代码/测试/schema/compose/配置；未触碰 plan.md/execution-report.md/保护目录/.env；未 stage/commit/push；用户 trip-pilot-prod 栈未操作）
- 验收隔离栈：`trip-pilot-b14accept`（独立项目名、WEB 38087、Prometheus 39096、独立网络 172.30.252.0/24、独立 volume、镜像 tag `b14-fix-accept`、REAL_ONLY；用后 down -v 清理）
- 验收日期：2026-08-16

## 1. 基线核对

| 项 | 要求 | 实测 |
| --- | --- | --- |
| branch | codex/feasibility-foundation | ✓ |
| HEAD | 89236ea731b3d9aea55a81f96101940299f2c983 | ✓ |
| staged | 空 | ✓（`git diff --cached --name-only` 0 行） |
| 工作区 | B13/B13_FIX/B13_FIX.1/B13_FIX.2/B14/B14_FIX 全部 unstaged | ✓（130 行，其中 docs/execution/B14_FIX/ 含 plan+execution-report 2 文件；执行报告自称 127 行为写作时点，含其自身与 3 个新增 untracked 差异，未发现越界修改） |
| 用户栈 | 不进入验收范围 | ✓（8 容器全程 healthy，验收前后复核未动） |

**diff 范围审查**：执行报告 §2 声明的本批文件清单与真实 git status/diff 一致（guide_intelligence/api.py、places/api.py、amap/demo planning_provider、PlanningProgressService、ItineraryVersionService、TripService、PlaceRefCanonicalizer、GuideImportContractTest、PlaceRefCanonicalizerTest、TripFlowIntegrationTest、PlanningReviewFlowIntegrationTest、GuideIntelligencePanel.vue、TripWorkspace.vue、TripDetail.vue、PlanningProgress.vue、共享 fixture、Test 文件）。未发现范围外修改；机械格式噪声仅限本批触碰的 4 个 Python 文件 ruff format（仓库其余 99 文件 drift 为基线既有）。

## 2. A 组：D01 天气同步契约 — PASS（1 观察项）

**独立验证**：
- Python 真实序列化：fixture（`contracts/fixtures/guide-city-intelligence-real-response.json`）逐字段核验——contentHash=sha256(normalizedDocument.content) 且 64 位小写 hex ✓；sourceUrl/finalUrl 为 qweather.com ✓；sourceHost 含「和风天气（天气）+ 高德（城市地点）」归因 ✓；trustedFacts 21/facts 25/decisions 21，selectedFactId/conflict/downgraded 全部 ∈ trustedFacts（dangling=0）✓；evidence 为 content 精确子串 ✓。
- Java 契约：独立运行 `GuideImportContractTest` **3/3 PASS**（真实 fixture 过 `validateFetchedGuide`）。
- **对抗性 fail-closed（独立 Java 探针，Temp 目录不落仓库）**：
  - 篡改 selectedFactId 为非 trusted → `ApiException GUIDE_SERVICE_INVALID_RESPONSE`（拒绝）✓
  - malformed JSON 响应 → `ApiException GUIDE_SERVICE_UNAVAILABLE`（502 安全）✓
- 原子落库：`GuideImportPersistenceService.persist` 整体 `@Transactional`，validate 在 persist 之前；CITY_INTELLIGENCE 走 lockTripForCityRefresh。无部分写入路径 ✓。
- Compose 实测（独立栈 REAL_ONLY）：guide-import 201 + `business.guide_import` rows=1 + facts=23 落库；非法 city 请求 400 无写入 ✓。
- Web：GuideIntelligencePanel 两处 catch（formError 中文 + submitting 恢复）、TripDetail.syncWeather catch（吞错但 handleImportGuide 已设中文 guideError 并在面板就地展示）、天气区块独立 Card 不消失；`GuideIntelligencePanel.test.ts` **11/11 PASS**（独立复跑）。

**观察项（不阻断）**：`_merge_decision_responses` 不显式过滤 `selectedFactId`，依赖结构性不变量（trusted_facts=merge.selected_facts 恒成立）；Java 侧不校验 contentHash 与内容匹配（仅格式）——均为既有边界，当前真实数据满足。

## 3. B 组：D02 owner 隔离 — PASS

**独立验证**：
- 代码审查：`ItineraryVersionService.list()/diff()` 开头 `tripService.get(ownerId, tripId)`（owner 检查在业务查询前）；detail 走 `findVersionOwned(tripId, versionId, ownerId)`；rollback/validateRollback 走 `lockOwnedState(tripId, ownerId)` + `findOwnedVersion`（owner-scoped SQL）。TripService 无 ItineraryVersionService 依赖，无循环依赖（mvn verify 启动上下文通过佐证）。
- 独立复跑：`TripFlowIntegrationTest#hidesItineraryVersionsFromUsersWhoDoNotOwnTheTrip` **1/1 PASS**（B→404、owner→200、不存在→404）。
- Compose 实测（独立栈）：跨用户 **versions 404 / version detail 404 / diff 404 / rollback 404**（带 Idempotency-Key header；rollback 404 错误码 ITINERARY_VERSION_NOT_FOUND 与无版本 owner 完全一致，不可区分）✓；不存在 trip 404 与跨用户 404 同形状（TRIP_NOT_FOUND）✓；无 200 []、无 403、无版本数量泄漏 ✓。
- 执行报告集成测试仅覆盖 list 的 404；detail/diff/rollback 的跨用户 404 由本验收 Compose 独立补验通过。

## 4. C 组：D03 token 城市绑定 — **FAIL（Important）**

**独立验证（真值表）**：

| 用例 | 预期 | 实测 | 结果 |
| --- | --- | --- | --- |
| 广州 token → 北京 trip | 400 PLACE_REF_TOKEN_INVALID | 400 ✓ | PASS |
| 广州 token → 广州 trip（candidate「广州市」vs destination「广州」） | 201 | 201 ✓ | PASS |
| 北京市 token → 北京 trip | 201 | normalize「北京市」→「北京」相等 ✓ | PASS |
| 上海/重庆直辖市 | 201 | normalize「上海市」→「上海」相等 ✓ | PASS |
| 香港特别行政区 → 香港 | 201 | normalize「香港特别行政区」→「香港」相等 ✓ | PASS |
| 大兴安岭地区 → 大兴安岭 | 201 | normalize「大兴安岭地区」→「大兴安岭」相等 ✓ | PASS |
| 阿拉善盟 → 阿拉善 | 201 | normalize「阿拉善盟」→「阿拉善」相等 ✓ | PASS |
| **大理白族自治州（AMap 真实 cityname）→ 大理（Web destination）** | **201** | **normalize「大理白族自治州」→「大理白族」≠「大理」→ 400 PLACE_REF_TOKEN_INVALID** | **FAIL** |
| 湘西土家族苗族自治州 → 湘西 | 201 | 截为「湘西土家族苗族」≠「湘西」 | FAIL |
| 延边朝鲜族自治州 → 延边 | 201 | 截为「延边朝鲜族」≠「延边」 | FAIL |
| 恩施/凉山/甘孜 等自治州 | 201 | 同模式截断错误 | FAIL |
| 跨省同名城市 | 低风险 | 实现无省份维度，理论碰撞；中国地级市名基本唯一，未实测到 | 观察 |
| token 过期 / owner 不同 / providerPoiId 不匹配 | 400 | 既有测试保留（PlaceRefCanonicalizerTest 9/9 独立复跑 PASS） | PASS |
| 坐标篡改 | canonical 覆盖 | `canonicalizeOne` 用 candidate 值重建，覆盖客户端字段 ✓ | PASS |
| unchanged persisted ref | 合法保存 | sameRef 分支保留 ✓ | PASS |

**对抗性证据链（独立探针 + 真实上游数据）**：
1. 用真实 AMap key 搜索「大理古城」（region=大理）→ 返回 `cityname=大理白族自治州`（上游真实形态）。
2. Web 端 `china-divisions.ts` 城市名为「大理」（用户级联选择 destination=「大理」），TripDashboard 提交 `destination: selection.city`。
3. 独立 Java 探针 `normalizeCity("大理白族自治州")` → `"大理白族"`（去「自治州」后缀截断错误，应为「大理」）。
4. 独立 Compose 实测：真实搜索大理 token → 创建 destination=「大理」trip → **400 PLACE_REF_TOKEN_INVALID**（C3 FAIL）。

**判定**：D03 的核心目标（跨城市注入 400）已达成，但引入**合法同城操作误拒**：所有 AMap 返回「自治州/地区/盟」完整后缀的城市的真实用户（Web 端可选「大理」）无法将搜索选中的地点保存到行程。任务书 C 组明确要求「自治州/地区/盟后缀规范化：按真实 region 语义 PASS」——**不满足**。另：plan.md 声称「region code 稳定比对」，实现实际传 `request.destination()` 自由文本 + 脆弱去后缀，未使用 `region.cityName/cityCode`——文档与实现不符，且正是本缺陷的根因（destination 与 AMap cityname 形态不一致）。

## 5. D 组：D04 无结果与 Provider 故障 — PASS

**独立验证**：
- 真实 AMap 数据：`asdfghjklqwerty`/`zzzzzzzz` → status=1 + 0 POI（POI_NOT_FOUND 路径）→ agent 修复后 200 + candidates=[]；`不存在的地点xyzabc`/`天河公园` → 5 模糊候选（200+候选）✓。
- 代码审查：`search_places` 仅 `NO_RESULT` 返回 200 空；其余 ProviderFailure（timeout/429/500/认证）→ 502 安全错误码+category，不泄露细节；places 层无 fallback（401/403 永不降级）✓。
- 独立复跑：`test_places_api.py` 12/12 + `test_amqp_worker.py` + `test_daily_skeleton_provider.py` **78/78 PASS**。
- Web 空态文案「未找到匹配地点」与服务故障文案（PLACE_SEARCH_UNAVAILABLE→「地点搜索暂时不可用」）不同且均中文 ✓。
- Compose 实测：无意义词 200 空、正常词 200 候选 ✓。

## 6. E 组：D05 progress 与终态竞态 — PASS

**独立验证**：
- 代码审查：DEMO provider `plan()` 在骨架生成前发 CANDIDATES_RANKING（真实边界）；AMap `_plan_with_skeleton` 在 ranker 前发 CANDIDATES_RANKING、日循环前发 ROUTES_CALCULATING + CONSTRAINTS_SOLVING；REPAIRING 仅 `_repair_if_needed` 真实启动时发（不伪造）✓。`PlanningProgressService` 对 WAITING_USER+RESULT_PUBLISHING 例外放行落库（跳过 QUEUED/RUNNING 检查与 markRunning），其余终态迟到事件静默忽略（不 DLQ）✓。
- 独立复跑：`PlanningReviewFlowIntegrationTest` + `PlanningCompletionFlowIntegrationTest` **62/62 PASS**（含 `persistsResultPublishingProgressArrivingAfterTheReviewEvent`、`stillIgnoresOtherLateProgressStagesAfterTheReviewEvent`、更新后的 B12 迟到忽略）；Web `PlanningProgress.test.ts` **3/3 PASS**（「未触发」文案）。
- Compose 实测（独立栈，REAL_ONLY，SLA 内 WAITING_USER）：
  - 10 阶段完整：TASK_ACCEPTED→…→RESULT_PUBLISHING，missing=[] ✓
  - sequence 1-10 严格递增 ✓；progress 5→95 单调 0-100 ✓；eventId 10/10 唯一 ✓
  - REPAIRING=0（无修复需要，不伪造）✓；lastStage=RESULT_PUBLISHING 后立即终态（无 95% 停留）✓
  - 终态事件唯一（12 事件含 1 终态）✓
- 跨队列乱序：RESULT_PUBLISHING→REVIEW_REQUIRED（worker 顺序）由 Compose 实测（完整序列）；REVIEW_REQUIRED→RESULT_PUBLISHING（review 抢先）由集成测试构造并断言不复活终态/不 DLQ/sequence 不破坏（Java 62/62）✓。
- E11（SSE 已关闭后 DB 迟到 progress 不破坏刷新）：`terminalMetadata` 由 `findLatestOutcome`（终态事件）驱动，与 progress 行无关 ✓。

## 7. F 组：D06 Web flaky — **FAIL（Important）**

**独立验证（全部全新进程）**：
| 项 | 结果 |
| --- | --- |
| 默认顺序三轮全量 | **401/401 × 3**（每轮 30-33s，flaky rate 0） |
| coverage 全量 | **401/401**（All files stmts 95.78/branch 85.36/funcs 95.3/lines 95.78；B13/B14 生产文件每文件 ≥80%） |
| App.test.ts + TripWorkspaceActions.test.ts 组合 | 80/80 |
| **测试顺序随机化（--sequence.shuffle）** | **第 1 次 2 failed / 第 2 次 1 failed / 第 3 次 2 failed（399-400/401）** |
| 分片 | 未单独分片（shuffle 已暴露问题） |
| typecheck / build | vue-tsc -b 通过；vite build 通过 |
| Playwright 全量 | 21 passed（VITE_AMAP_WEB_JS_KEY 置空复现 B14 dead-proxy 确定性环境；未改 spec） |

**随机化失败根因（顺序依赖 DOM 泄漏）**：`PlanEvaluationPanel.test.ts`、`TripDetail.test.ts`、`TransitLegControl.test.ts` 三个组件测试**无 `afterEach(cleanup)`**；vitest 未开 `globals`、无 setup 文件，@testing-library/vue 的 autoCleanup 不生效。shuffle 使同一文件内/跨文件 DOM 残留，`getByText('体验评分')`/`getByText('我的要求')`/`getByTestId('transit-option-TAXI')` 找到多个元素（错误输出显示 `<body>` 中残留两个组件实例）。这三个文件 mtime 08-08/08-09，非本批修改，但**D06 验收标准要求「测试顺序随机化或分片至少 1 次」且「每轮必须 401/401」「flaky rate 必须为 0」**——执行报告仅声称默认顺序三轮全绿，未执行随机化门禁；独立随机化稳定复现失败。判定：**D06 未按任务书关闭**。

## 8. 全量独立门禁

| 门禁 | 结果 |
| --- | --- |
| Python pytest 全量 | **1491 passed, 37 skipped**（独立 basetemp） |
| ruff check / format（本批 8 文件） | All checks passed / 8 files already formatted |
| Java mvn verify | **510 tests, 0 failures**；JaCoCo All coverage checks met；Flyway 干净 + 升级路径（TripPaceMigrationIntegrationTest 4/4，含故意回滚验证） |
| Java 定向 | GuideImportContractTest 3/3、PlaceRefCanonicalizerTest 9/9、TripFlowIntegrationTest 42/42、PlanningReview+Completion 62/62 |
| Web unit | 默认顺序 3×401/401 + coverage 401/401；**shuffle 399-400/401（FAIL）** |
| Web typecheck / build | 通过 |
| Playwright | 21 passed |
| 独立 Compose（trip-pilot-b14accept） | **27/28**（B4 修正后：跨用户 rollback 带 header 404 ✓；唯一 FAIL 为 C3 自治州 token 400 误拒——即第 4 节缺陷） |
| Markdown links | 270 links / 0 broken（Python 复检） |
| git diff --check | 通过（CRLF 警告为基线） |
| secret / 保护目录 / staged | 无 key/私钥泄漏；`.omo/`/`.serena/`/`docs/audits/`/`.env` 未触碰；staged 空；HEAD 未变 |

## 9. 新发现与对抗性反例

1. **C3（Important，阻断）**：D03 修复对自治州/地区/盟城市（AMap cityname 完整后缀）合法同城操作 400 误拒；`normalizeCity` 去「自治州」后缀截断错误（大理白族自治州→大理白族）；plan.md 声称 region code 比对而实现未用。独立真实上游数据 + 独立 Compose 复现。
2. **F 组（Important，阻断）**：shuffle 顺序下三个组件测试 DOM 泄漏稳定失败；执行报告未执行任务书要求的随机化门禁。
3. 观察项：`_merge_decision_responses` 未显式过滤 selectedFactId（结构性保证成立）；Java 不校验 contentHash 内容匹配；跨省同名城市无省份维度（理论碰撞，当前低风险）；TransitLegControl 等组件测试无 cleanup 属基线既有。

## 10. D07-D09 重新定级

- **D07**（REAL_ONLY 缺 Key 文案）：未修复，fail-closed 正确仅文案缺失 → 维持 P3 非阻断。
- **D08**（基础设施 POI 候选质量）：未修复；Web 候选排序无基础设施过滤 + 失败文案误导，但系统 fail-closed（拒绝而非静默错误）→ 维持 P3 非阻断；不构成普通用户稳定选公交站后必然无法规划（用户可换候选）。
- **D09**（AMap route rate-limit 观察）：重试有界（retry_count 1-2 后成功），认证/权限仍不 fallback → 维持 P3 观察。

三者均未被执行报告错误声称已修复（§7 明确登记未解决），未形成新 P0/P1。

## 11. 判定

**B14_FIX_NEEDS_CORRECTION / RELEASE_FREEZE_BLOCKED**

授权 Git 收口：**否**；解除 release freeze：**否**。

### 必须修正（实现缺陷，非小问题）

1. **D03 自治州/地区/盟城市误拒**：`normalizeCity` 对「XX自治州/XX地区/XX盟」类 AMap cityname 与 Web 端 destination（省市区级联短名）的规范化错误（大理白族自治州→大理白族）。修正方向：按真实 region 语义规范化（如优先使用 `region.cityName`/adcode 绑定，或将「白族自治州/土家族苗族自治州/朝鲜族自治州」等复合后缀正确剥离为城市主名），并补充大理/湘西/延边等真实形态的单元 + 集成回归测试（先 RED 后 GREEN）。
2. **D06 随机化门禁**：`PlanEvaluationPanel.test.ts`/`TripDetail.test.ts`/`TransitLegControl.test.ts` 补 `afterEach(cleanup)`（或配置全局 autoCleanup），使 `--sequence.shuffle` 全量 401/401、flaky rate 0；执行报告应补充随机化验证记录。

### 复验通过项

D01（PASS）、D02（PASS）、D04（PASS）、D05（PASS）；Web 默认顺序三轮/coverage/Playwright/Java/Python/ruff/links/secret/staged/保护目录/用户栈 全部通过；D07-D09 维持非阻断。

### 证据与清理

- 独立探针（Temp 目录，不落仓库）：AcceptDanglingProbe（fail-closed PASS）、AcceptMalformedProbe（502 PASS）、AcceptNormalizeProbe（自治州 FAIL 矩阵）、accept-amap-probe（真实 cityname 数据）、accept-links（270/0）。
- 独立 Compose 栈 `trip-pilot-b14accept`（新项目名/端口 38087/39096/网络 172.30.252.0/24/独立 volume/tag b14-fix-accept）：**已 down -v --remove-orphans 全部清理**（容器+卷+网络删除）；镜像 tag 保留供复跑。
- 用户 `trip-pilot-prod` 8 容器验收前后未动（复核 healthy）。
- 本报告为唯一写入文件；未 stage/commit/push；未创建 GitHub release。

---

# B14_FIX.1 独立验收报告（追加章节）

- 状态：**B14_FIX_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT / RELEASE_READY**（详见 §10）
- 验收方式：独立审查 + 独立复跑（不复用执行 Agent 的任何测试输出；未修改任何生产代码/测试/schema/compose/配置；未触碰 plan.md/execution-report.md/保护目录/.env；未 stage/commit/push；用户 trip-pilot-prod 栈未操作）
- 验收隔离栈：`trip-pilot-b14fix1accept`（独立项目名、WEB 38089 / Prometheus 39098、独立网络 172.30.254.0/24、独立 volume、镜像 tag `b14fix1-accept`、REAL_ONLY；用后 down -v 清理）
- 验收日期：2026-08-16
- 前置：上方 B14_FIX 验收判定 NEEDS_CORRECTION（C 组自治州误拒 + F 组 shuffle DOM 泄漏）——本章节为对 B14_FIX.1 修正批次的复验；原 NEEDS_CORRECTION 历史完整保留。

## 1. 基线核对

| 项 | 要求 | 实测 |
| --- | --- | --- |
| branch | codex/feasibility-foundation | ✓ |
| HEAD | 89236ea731b3d9aea55a81f96101940299f2c983 | ✓ |
| staged | 空 | ✓（`git diff --cached --name-only` 0 行） |
| 工作区 | B13…B14_FIX.1 全部 unstaged | ✓（133 行 = tracked 修改 79 + untracked 54；B14_FIX 验收基线 130 行，+3 差异经 CreationTime 核实为本批非产物：验收 Agent 自身 10:49 写入的 acceptance-report.md 与 `.omo/` 会话状态文件等既有 untracked 内容，本批 B14_FIX.1 未在仓库新建任何文件） |
| 用户栈 | 不进入验收范围 | ✓（`trip-pilot-prod` 8 容器全程 healthy，验收前后复核未动；`trip-pilot-b13fix1-verify` 他批栈未操作） |

## 2. diff 范围审查

**B14_FIX.1 修改窗口（10:50 之后 mtime/CreationTime 核实，仅 8 个既有文件被修改，无新建文件）**：

| 文件 | 状态 | 归属 |
| --- | --- | --- |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/PlaceRefCanonicalizer.java` | untracked（B14_FIX 既有，本批修改） | R1 生产 |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripService.java` | M（B14_FIX 既有，本批修改） | R1 生产 |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/trip/PlaceRefCanonicalizerTest.java` | untracked（B14_FIX 既有，本批修改） | R1 测试 |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/trip/TripFlowIntegrationTest.java` | M（B14_FIX 既有，本批修改） | R1 测试 |
| `apps/web/src/components/PlanEvaluationPanel.test.ts` | M（既有，本批修改） | R2 测试 |
| `apps/web/src/components/TransitLegControl.test.ts` | M（既有，本批修改） | R2 测试 |
| `apps/web/src/components/TripDetail.test.ts` | M（既有，本批修改） | R2 测试 |
| `docs/execution/B14_FIX/execution-report.md` | untracked（本批追加 B14_FIX.1 章节） | 执行报告 |

**越界检查**：无 `.only`/`.skip`（全仓扫描仅 4 个既有 pytest.skip 数据库条件跳过 + 生产代码 `PlanningFactConflictResolver.skip(1)` 流操作，非测试禁用）；JaCoCo LINE 0.80 阈值未变；vitest coverage thresholds 80 未变；无 testTimeout/retry/串行配置；无捕获异常制造通过（R1/R2 均为正向断言或明确 400 断言）。

## 3. C 组：官方行政区语义复验 — PASS

### A. 代码审查（独立）

1. **create 使用请求 region.cityName 作为权威城市** ✓：`TripService.create` → `authoritativeCityName(request.region(), request.destination())` → 有 RegionRefInput 时取 `region.cityName()`。
2. **updateConstraints 使用 DB 持久化 RegionRef 官方 cityName** ✓：`authoritativeCityName(readNullableJson(trip.regionRefJson(), RegionRef.class), trip.destination())`——从 trips.region_ref 读回，不退回展示简称。
3. **destination 仅是展示字段** ✓：仅作为 `authoritativeCityName(String,String)` 的 null/blank fallback；有 region 时永不参与比较。
4. **无民族名硬编码** ✓：`PlaceRefCanonicalizer.normalizeCity` 后缀表仅 `{"特别行政区","地区","盟","市"}`，无「白族/土家族/苗族/朝鲜族」等任何民族语素；「自治州」明确不剥离（注释说明防「大理白族」残留）。
5. **无模糊 contains/前缀命中** ✓：`sameCity` 为 `normalizeCity(a).equals(normalizeCity(b))` 精确相等；无 startsWith/contains/模糊截断。
6. **token owner/过期/candidate/防篡改不回归** ✓：`PlaceSelectionTokenService` TTL 30 分钟保留（未触碰）；redeem 校验 owner + 过期 + candidate；`canonicalizeOne` 校验 providerPoiId 匹配 + 同城 + 服务端重建（坐标/名称/地址全部覆盖客户端伪造）；`sameRef` 无 token 分支仅精确匹配持久化值。
7. **legacy 路径保守** ✓：无 RegionRef 时 fallback destination 并 fail-closed（null 也拒绝跨形态）；未静默放宽。

### B. 独立测试（独立进程复跑）

**合法同城正例**（PlaceRefCanonicalizerTest 15/15 独立复跑 PASS）：
- 大理白族自治州：`officialAutonomousPrefectureNameMatchesItselfVerbatim` ✓（官方名全等）
- 湘西土家族苗族自治州：`officialXiangxiAutonomousPrefectureNameMatchesItselfVerbatim` ✓
- 延边朝鲜族自治州：`officialYanbianAutonomousPrefectureNameMatchesItselfVerbatim` ✓
- 阿拉善盟 / 大兴安岭地区：`officialLeagueAndPrefectureSuffixesStillNormalize` ✓（盟/地区后缀剥离仍无损）
- 北京市（直辖市）/ 广州市（普通市）：`ordinaryMunicipalityAndCityStillAcceptOfficialRegionCityName`（集成）+ 既有 D03 用例 ✓

**关键路径组合**（TripFlowIntegrationTest 48/48 独立复跑 PASS）：
- create：`createsDaliTripWithOfficialRegionCityNameAndAutonomousPrefectureCandidate`（destination=大理 + region.cityName=大理白族自治州 + candidate.city=大理白族自治州 → **201** 且持久化 ref.city=大理白族自治州）✓；`createsXiangxiTripWithOfficialRegionCityNameAndAutonomousPrefectureCandidate`（201）✓
- updateConstraints：`updatesDaliTripConstraintsWithOfficialRegionCityName`（PUT /constraints 用 DB region → **200** 且官方名持久化）✓
- anchors + avoid：`anchorsAndAvoidRefsUseOfficialRegionCityName`（arrival.placeRef + avoidPlaceRefs 官方名 → 201）✓
- mustVisit：Dali/Xiangxi create 均含 mustVisitPlaceRefs ✓

**负例**（全部 400 或既定安全错误）：
- 大理 token → 北京 trip：`autonomousPrefectureCandidateStillRejectedForBeijingTrip`（集成 400 `PLACE_REF_TOKEN_INVALID`）+ `autonomousPrefectureCandidateStillRejectedForDifferentCity`（单元）✓
- 湘西 token → 西安：`xiangxiCandidateStillRejectedForXiAnTrip`（单元 400）✓
- 广州 token → 北京：既有 `rejectsSelectionTokenIssuedInAnotherCity`（集成）✓
- 修改 providerPoiId：`rejectsTokenWhoseCandidateDoesNotMatchTheRefIdentity`（单元 400）+ Compose 实测 400 ✓
- 修改坐标/名称/地址：`canonicalizesRefWithValidTokenIgnoringForgedFields`（单元：服务端重建覆盖伪造字段）+ Compose 实测 canonical 覆盖 ✓
- 其他用户使用 token：`rejectsTokenIssuedToAnotherOwner`（单元 400）✓
- 过期 token：`PlaceSuggestionServiceTest` **18/18 独立复跑 PASS**（`expiredTokenDoesNotRedeem`、`expiredTokenRedeemRemovesAndReturnsEmpty`）✓

**期望达成**：合法同城全部成功并持久化官方 RegionRef；跨城/篡改/跨用户/过期全部 400；未因 display destination 简称拒绝官方同城候选。

### C. Compose 真实验收（trip-pilot-b14fix1accept，REAL_ONLY，真实 AMap）

独立构建镜像（tag `b14fix1-accept`）+ 启动 8 容器全部 healthy；Temp 脚本（`b14fix1-accept2.py`/`accept-db-probe*.py`，不落仓库）真实 HTTP + DB 读回：

| 用例 | 预期 | 实测 | 结果 |
| --- | --- | --- | --- |
| 真实搜索「大理古城」（city=大理） | 返回候选 | 200，5 候选，`city=大理白族自治州`（官方形态） | PASS |
| 大理候选 → 创建 destination=大理 trip | 201 | **201** | PASS |
| DB 读回 `business.trip.region_ref.cityName` | 大理白族自治州 | **精确匹配（len=7）** | PASS |
| API 读回 mustVisitPlaceRefs[0].city | 大理白族自治州 | 精确匹配 | PASS |
| 真实搜索「凤凰古城」（city=湘西） | 返回候选 | 200，`city=湘西土家族苗族自治州` | PASS |
| 湘西候选 → 创建 destination=湘西 trip | 201 | **201** | PASS |
| DB 读回湘西 region.cityName | 湘西土家族苗族自治州 | 精确匹配（len=10） | PASS |
| 大理 token → 北京 trip | 400 | 400 `PLACE_REF_TOKEN_INVALID` | PASS |
| 广州（普通市）token → 广州 trip | 201 | 201（不回归） | PASS |
| owner 隔离：B 读 A 的 trip | 404 | 404 | PASS |
| 篡改 providerPoiId | 400 | 400 `PLACE_REF_TOKEN_INVALID` | PASS |
| 伪造 selectionToken | 400 | 400 `PLACE_REF_TOKEN_INVALID` | PASS |
| 篡改 ref.city → canonical 覆盖 | 201 且持久化官方值 | 201，持久化 city=广州市（非篡改值） | PASS |

注：初版 DB 查询用错表名（`trips` 应为 `business.trip`）与列名（`region_ref_json` 应为 `region_ref`）导致空结果，修正后精确匹配——属验收脚本构造错误，非产品缺陷。基础设施注记：真实 AMap 搜索全程 200（外部 Provider 正常，无基础设施失败混入）；注册瞬时 503 为 nginx `auth_limit` 限流（放缓重试通过），与业务无关。

## 4. F 组：Web 随机顺序稳定性复验 — PASS

### 代码审查（独立）

三个文件均新增 `afterEach(() => cleanup())`（`@testing-library/vue` 的 cleanup + vitest afterEach），并带中文注释说明原因。**资源扫描**（不只看 cleanup import）：
- 三文件均无 `vi.useFakeTimers`/`useRealTimers`/`setInterval`/`setTimeout`（无 fake timers 需恢复）
- 无 fetch/mock server（`vi.mock`/`fetchMock`/`vi.stubGlobal` 均无）——纯 props 渲染 + fireEvent
- 无 history/router/listener 操作（无 addEventListener/removeEventListener）
- 无 localStorage/sessionStorage 使用
- 无 Teleport 节点（组件仅 render 进 `<body>`，cleanup 卸载）
- 无 pending Promise（fireEvent 均 await；无未 flush 的异步）
- `render()` 次数与 `afterEach` 覆盖匹配（3/2/3 renders → 1 cleanup hook）

### 独立执行（全新进程）

| 轮次 | 命令 | 结果 |
| --- | --- | --- |
| 默认顺序 ×3 | `pnpm vitest run` | **401/401 × 3**（67.2s/36.0s/37.0s，flaky rate 0） |
| 固定 seed 1786850508413 | `--sequence.shuffle --sequence.seed=1786850508413` | **401/401** |
| 固定 seed 777 | `--sequence.seed=777` | **401/401** |
| 固定 seed 999 | `--sequence.seed=999` | **401/401** |
| 固定 seed 20260816 | `--sequence.seed=20260816` | **401/401** |
| 固定 seed 314159 | `--sequence.seed=314159` | **401/401** |
| 固定 seed 271828 | `--sequence.seed=271828` | **401/401** |
| 非固定随机 seed | `--sequence.shuffle`（Vitest 生成） | **401/401**（记录 seed `1786856125194`） |
| 三目标文件组合 | 三个文件定向 | **8/8** |
| coverage | `pnpm test:coverage` | **401/401**；All files stmts 95.78 / branch 85.36 / funcs 95.3 / lines 95.78（与 B14_FIX 基线一致，不下降） |
| 退出状态 | CI 模式 + seed 1786856125194 | **exit 0**，无 open handles、无未处理 Promise、无失败 stderr（仅既有 fireEvent.change deprecation 提示） |

## 5. A/B/D/E 回归 — PASS

| 项 | 独立复跑 | 结果 |
| --- | --- | --- |
| D01 天气同步契约 | `GuideImportContractTest` **3/3 PASS**；B14_FIX 既有对抗探针结论保留（dangling/malformed fail-closed，未在本批触碰相关代码） | PASS |
| D02 owner 隔离 | `TripFlowIntegrationTest` 48/48 内含 `hidesItineraryVersionsFromUsersWhoDoNotOwnTheTrip`；Compose 跨用户 404 实测（本批 §3.C） | PASS |
| D04 无结果 | `test_places_api.py`+`test_amqp_worker.py`+`test_daily_skeleton_provider.py` **78/78 PASS**（无结果 200 空 + 故障 502 不伪装） | PASS |
| D05 progress | `PlanningReviewFlowIntegrationTest` 19/19 + `PlanningCompletionFlowIntegrationTest` 43/43 = **62/62 PASS**（RESULT_PUBLISHING 竞态/终态唯一/序列单调） | PASS |

## 6. 完整门禁（独立运行）

| 门禁 | 结果 |
| --- | --- |
| Python pytest 全量 | **1491 passed, 37 skipped**（独立 basetemp） |
| ruff check | **All checks passed** |
| ruff format --check | 95 文件 drift 为基线既有（B14_FIX 验收同结论；本批未触碰 Python） |
| Java mvn verify | **522 tests, 0 failures, 0 errors**；JaCoCo **All coverage checks have been met**；Flyway 干净（36 migrations）+ 升级路径（TripPaceMigrationIntegrationTest 4/4） |
| Java 定向 | PlaceRefCanonicalizerTest 15/15、TripFlowIntegrationTest 48/48、PlaceSuggestionServiceTest 18/18、GuideImportContractTest 3/3、PlanningReview+Completion 62/62 |
| Web unit | 默认 3×401/401 + shuffle 7 seed（6 固定 + 1 随机）全 401/401 + 组合 8/8 + coverage 401/401 |
| Web typecheck / build | vue-tsc -b 通过；vite build 通过（dist 产物正常） |
| Playwright | **21 passed**（`VITE_AMAP_WEB_JS_KEY`/`VITE_AMAP_SECURITY_CODE` 置空确定性环境；独立复跑未复现执行 Agent 记录的首轮 flaky，与本批改动无关——地图定位按钮为 AMap SDK 加载时序） |
| Markdown links | **272 links / 0 broken** |
| git diff --check | 通过（CRLF 警告为基线既有） |
| secret / 保护目录 / staged | git diff 无 AKIA/私钥/证书模式；`.omo/`、`.serena/`、`docs/audits/`、`.env`（mtime 2026-08-15 18:02:35 未变）未触碰；`git ls-files` 无 .env/.pem/.key/.p12/.pfx；staged 空；HEAD 未变 |
| Compose config | `docker compose -f compose.prod.yaml --env-file .env.example config --quiet` exit 0 |
| 隔离栈清理 | `trip-pilot-b14fix1accept` **已 down -v --remove-orphans**（容器+全部 volume+网络删除）；`b14fix1-accept` 镜像 tag 保留供复跑 |
| 用户栈 | `trip-pilot-prod` 8 容器验收前后复核 healthy，全程未操作 |

## 7. 执行报告真实性对账

| 项 | 对账结论 |
| --- | --- |
| RED 来自旧行为 | ✓ 无法回放旧代码（禁止 checkout），但 B14_FIX 验收报告 §4 已独立证实旧 normalizeCity 行为（大理白族自治州→大理白族 400），与执行报告 RED 声明一致；集成 RED 4/6（create×2/update/anchor+avoid）与旧代码路径推理吻合 |
| GREEN 数字可复现 | ✓ 独立复跑 15/15、48/48 与报告一致 |
| 默认/shuffle 区分 | ✓ 报告 §3 表格明确区分默认×3、固定 seed×6、非固定×1 |
| Compose 真实证据 | ✓ 真实 HTTP（38089 栈）+ DB 读回（business.trip.region_ref 精确匹配大理 len=7/湘西 len=10）；非 mock |
| Playwright flaky 承认 | ✓ 报告如实承认首轮 1 flaky（release-smoke 地图定位按钮）并记录单独重跑 3/3 + 全量 21/21；独立复跑 21/21 未复现，属 AMap SDK 加载时序环境现象，与本批无关 |
| Provider 偶发不伪装 | ✓ 报告如实记录 nginx auth_limit 503 瞬时（放缓重试）；独立复跑同样遇到并复现结论 |
| HEAD/staged/保护目录/清理 | ✓ HEAD 89236ea、staged 0、保护目录 mtime 未变、隔离栈已清理均实测属实 |
| git status 行数 | ✓ 133 = 79 tracked + 54 untracked 实测一致；+3 相对验收基线 130 的解释中「acceptance-report.md 属验收 Agent 自身写入」属实，但「折叠目录不增加 git status 行数」使该 +3 归因在技术上不精确（观察项，非阻断——本批无新建文件已独立证实） |
| 直辖市 region 脚本错误 | ✓ 报告如实记录初版用 110100≠110000 触发 TRIP_REGION_INVALID 并修正；独立复跑用 110000/110000 成功 |

## 8. 发现项及严重级别

- **无 Critical/Important 发现**。
- 观察项 1（不阻断）：任务书负例字面组合（大理→昆明、湘西→长沙、广州→杭州）未逐一列出，但同语义负例（大理→北京、湘西→西安、广州→北京）已覆盖——`sameCity` 为通用精确比较，与具体城市无关，机制等价。
- 观察项 2（不阻断）：accommodation anchor 未单独以官方名断言（与 arrival/departure 走同一 `canonicalizeAnchor` 路径，anchors 测试已覆盖 arrival + avoid）。
- 观察项 3（不阻断）：执行报告对 130→133 行差异的归因表述技术上不精确（见 §7），但不影响「本批未新建文件」的事实。
- 观察项 4（不阻断）：跨省同名城市仍无省份维度（既有观察，维持）。

## 9. 精确 Git 收口授权文件清单

以下文件为 B14_FIX.1 可收口范围（与 B14_FIX 本批文件叠加后整体收口；A/M/D 状态以 Git 实际状态为准）：

| 文件 | 状态 |
| --- | --- |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/PlaceRefCanonicalizer.java` | A（新增，本批修改） |
| `apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripService.java` | M |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/trip/PlaceRefCanonicalizerTest.java` | A（新增，本批修改） |
| `apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/trip/TripFlowIntegrationTest.java` | M |
| `apps/web/src/components/PlanEvaluationPanel.test.ts` | M |
| `apps/web/src/components/TransitLegControl.test.ts` | M |
| `apps/web/src/components/TripDetail.test.ts` | M |
| `docs/execution/B14_FIX/execution-report.md` | A（新增批次报告，本批追加 B14_FIX.1 章节） |
| `docs/execution/B14_FIX/acceptance-report.md` | A（新增批次报告，本验收追加 B14_FIX.1 章节） |

（注：Git 收口执行时点应包含 B14_FIX/B14_FIX.1 两批次全部文件——B14_FIX 本批文件清单见上方原章节 §11，此处列出 B14_FIX.1 增量；`.omo/`、`.serena/`、`docs/audits/`、`docs/execution/B13*/B14/` 等历史批次与保护目录不在授权范围。）

## 10. 判定

**B14_FIX_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT**
**RELEASE_READY**

- C 组（自治州/地区/盟城市同城 400 误拒）**已关闭**：代码审查 7 项全过；合法同城正例（大理/湘西/延边/阿拉善/大兴安岭/北京/广州）全过；负例（跨城/篡改/跨用户/过期）全 400；Compose 真实 AMap 搜索 + DB 读回官方 cityName 全部通过。
- F 组（Web shuffle DOM 泄漏）**已关闭**：三个文件 afterEach(cleanup) 就位且无其他未恢复资源；默认 3×401/401、6 固定 seed + 1 随机 seed 全 401/401、组合 8/8、coverage 401/401 不下降、exit 0。
- 全量门禁通过；A/B/D/E 无回归；执行报告真实性对账无重大不实（仅观察项）；无 Critical/Important。
- 隔离栈已清理；用户 `trip-pilot-prod` 未触碰且 healthy；本报告为唯一写入文件；未 stage/commit/push；未创建 tag/release/PR；未修改 plan/execution-report。

---

# 集成 Git 收口范围校准（追加章节）

- 状态：**B13_B14_INTEGRATED_SCOPE_AUTHORIZED_FOR_GIT_CLOSEOUT / RELEASE_READY**（详见 §12）
- 审计方式：只校准最终提交授权范围；未修改任何业务代码；未重新实现功能；未 stage/commit/push；唯一写入本报告
- 审计日期：2026-08-16
- 触发原因：上方 §9 仅列出 B14_FIX.1 增量 9 文件并排除 B13*/B14 历史目录，而从 HEAD `89236ea` 到当前工作树，B13/B13_FIX/B13_FIX.1/B13_FIX.2/B14/B14_FIX/B14_FIX.1 的实现、测试、契约、迁移与文档均未提交；若机械按 9 文件提交将形成不能独立构建的部分提交。

## 11. 完整枚举与分类

审计基线（与 §1 相同）：branch `codex/feasibility-foundation`、HEAD `89236ea731b3d9aea55a81f96101940299f2c983`、staged 空、B14_FIX.1 独立验收 PASS（上方章节）。

### 11.1 Tracked 变更（79 files，+6407/-1827；74 M + 5 D）

**Python 生产（14 M）**：`apps/agent-service/src/trip_agent/domain/shared.py`、`feasibility/inputs.py`、`feasibility/rules/meal.py`、`guide_intelligence/api.py`、`infrastructure/amap/feasibility_projection.py`、`infrastructure/amap/planning_provider.py`、`infrastructure/demo/planning_provider.py`、`main.py`、`planning/candidates.py`、`planning/daily_schedule.py`、`planning/validation_projection.py`、`worker/amqp.py`、`worker/contracts.py`、`src/trip_agent/places/api.py`（注意：`places/api.py` 在 git status 中为 untracked，见 11.2——此处在 tracked 列表中的是其余 13 个；`internal_security.py` 与 `places/api.py` 均为新增文件归入 11.2）

**Python 测试（7 M）**：`tests/feasibility/test_meal_window_rule.py`、`tests/test_amap_feasibility_projection.py`、`tests/test_amqp_worker.py`、`tests/test_daily_skeleton_provider.py`、`tests/test_meal_window_placement.py`、`tests/test_messaging_contract_schemas.py`、`tests/test_validation_projection.py`

**Java 生产（11 M）**：`itinerary/ItineraryVersionService.java`、`planning/PlanningProgressService.java`、`planning/PlanningTaskService.java`、`trip/TripConstraintRecord.java`、`trip/TripConstraintValidator.java`、`trip/TripController.java`、`trip/TripMapper.java`、`trip/TripRecord.java`、`trip/TripRequests.java`、`trip/TripService.java`、`trip/TripSnapshotRecord.java`

**Java 测试（4 M）**：`planning/PlanningReviewFlowIntegrationTest.java`、`planning/PlanningTaskFlowIntegrationTest.java`、`trip/TripFlowIntegrationTest.java`、`trip/TripPaceMigrationIntegrationTest.java`

**Web（26 M + 5 D）**：
- 组件：`src/components/CityCascadePicker.vue`、`CityCascadePicker.test.ts`、`ConstraintEditor.vue`、`FeasibilityReportPanel.vue`、`GuideIntelligencePanel.vue`、`PlanEvaluationPanel.test.ts`、`PlanningProgress.vue`、`PlanningReviewPanel.vue`、`TransitLegControl.test.ts`、`TripDashboard.vue`、`TripDetail.test.ts`、`TripDetail.vue`、`TripMap.vue`、`TripWeatherTimeline.vue`
- lib：`src/lib/api.ts`、`src/lib/china-divisions.ts`、`src/lib/constraint-draft.ts`、`src/lib/constraint-editor.ts`
- pages：`src/pages/TripWorkspace.vue`
- tests：`tests/App.test.ts`、`tests/FeasibilityReportPanel.test.ts`、`tests/GuideIntelligencePanel.test.ts`、`tests/PlanningProgress.test.ts`、`tests/PlanningReviewPanel.test.ts`、`tests/TripDashboard.test.ts`、`tests/TripDetailItineraryEditing.test.ts`、`tests/TripWeatherTimeline.test.ts`、`tests/amap.test.ts`、`tests/constraint-editor.test.ts`、`tests/region-ref.test.ts`
- e2e：`e2e/feasibility-outcomes.spec.ts`、`e2e/golden-journeys.spec.ts`
- 配置：`vite.config.ts`
- **删除（5 D，已批准旧 UI/NLP/parser）**：`src/components/ConstraintCard.vue`、`src/components/NaturalLanguageInput.vue`、`src/components/TripTemplates.vue`、`src/lib/constraint-parser.ts`、`tests/constraint-parser.test.ts`——均已核实 HEAD 中存在（真实删除）、工作树与全仓无残留引用（git grep 0 命中）

**文档（6 M）**：`README.md`、`docs/architecture/行程真实性与旅行骨架.md`、`docs/architecture/规划工作流.md`、`docs/development/代码架构导读.md`、`docs/product/系统完善长期执行与验收总控计划.md`、`docs/product/项目路线图.md`

### 11.2 授权新增文件（untracked，78 files）

**Python 生产（2 A）**：`apps/agent-service/src/trip_agent/internal_security.py`、`apps/agent-service/src/trip_agent/places/api.py`

**Python 测试（12 A）**：`tests/guide_intelligence/test_city_contract.py`、`tests/test_avoid_rank.py`、`tests/test_boundary_authority.py`、`tests/test_emitted_day_ordering.py`、`tests/test_meal_type_binding.py`、`tests/test_meal_window_source.py`、`tests/test_must_visit_recall.py`、`tests/test_place_authenticity.py`、`tests/test_place_ref_contract.py`、`tests/test_places_api.py`、`tests/test_worker_invalid_command.py`

（注：Python untracked 测试共 12 个；`test_city_contract.py` 属 guide 目录）

**Java 生产（8 A）**：`apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/place/AgentPlaceSearchClient.java`、`HttpAgentPlaceSearchClient.java`、`PlaceSearchDtos.java`、`PlaceSelectionTokenService.java`、`PlaceSuggestionController.java`、`PlaceSuggestionService.java`、`trip/PlaceRefCanonicalizer.java`、`trip/TripTitleGenerator.java`

**Java 测试（7 A）**：`guide/GuideImportContractTest.java`、`place/HttpAgentPlaceSearchClientTest.java`、`place/PlaceSuggestionServiceTest.java`、`planning/PlanningOutboxBoundaryContractIntegrationTest.java`、`trip/MunicipalityRegionIntegrationTest.java`、`trip/PlaceRefCanonicalizerTest.java`、`trip/TripTitleGeneratorTest.java`

**Flyway migration（2 A）**：`apps/travel-server/src/main/resources/db/migration/V35__add_trip_datetime_boundaries.sql`、`V36__add_trip_place_refs.sql`（V33/V34 已 tracked，迁移链连续无 gap）

**Java 测试资源（1 A）**：`apps/travel-server/src/test/resources/fixtures/guide-city-intelligence-real-response.json`

**Web（13 A）**：`e2e/weather-window.spec.ts`、`src/components/PlaceAutocomplete.vue`、`src/components/TravelStyleEditor.vue`、`src/components/TripBoundaryEditor.vue`、`src/lib/place-selection.ts`、`src/lib/place-selection.test.ts`、`src/lib/trip-title.ts`、`tests/PlaceAutocomplete.test.ts`、`tests/TravelStyleEditor.test.ts`、`tests/TripBoundaryEditor.test.ts`、`tests/TripWorkspaceActions.test.ts`、`tests/china-divisions.test.ts`、`tests/place-selection.test.ts`、`tests/trip-title.test.ts`（14 个）

**Contracts（8 A）**：`contracts/fixtures/guide-city-intelligence-real-response.json`、`contracts/fixtures/planning-candidate-validation-command-v2/valid-edit.json`、`contracts/fixtures/planning-candidate-validation-command-v2/valid-rollback.json`、`contracts/fixtures/planning-create-command-v4/valid.json`、`contracts/fixtures/planning-replan-command-v2/valid.json`、`contracts/messaging/planning-candidate-validation-command-v2.schema.json`、`contracts/messaging/planning-create-command-v4.schema.json`、`contracts/messaging/planning-replan-command-v2.schema.json`

**执行与验收证据（14 A）**：`docs/execution/B13/plan.md`、`docs/execution/B13/execution-report.md`、`docs/execution/B13/acceptance-report.md`；`docs/execution/B13_FIX/plan.md`、`docs/execution/B13_FIX/execution-report.md`、`docs/execution/B13_FIX/acceptance-report.md`；`docs/execution/B14/plan.md`、`docs/execution/B14/execution-report.md`、`docs/execution/B14/artifact-manifest.md`、`docs/execution/B14/defects.md`、`docs/execution/B14/scenario-catalog.md`（注：B14 目录实际含 5 文件——`artifact-manifest.md`、`defects.md`、`execution-report.md`、`plan.md`、`scenario-catalog.md`，无 acceptance-report.md）、`docs/execution/B14_FIX/plan.md`、`docs/execution/B14_FIX/execution-report.md`、`docs/execution/B14_FIX/acceptance-report.md`

**B14 可重复验收脚本（11 A）**：`scripts/acceptance/b14/b14lib.py`、`matrix_a.py`、`matrix_b.py`、`matrix_fault.py`、`matrix_param.py`、`matrix_real.py`、`results-a.json`、`results-b.json`、`results-fault.json`、`results-param.json`、`results-real.json`

### 11.3 明确排除（23 项，不提交）

- `.omo/`（20 个 run-continuation 会话 JSON——Agent 会话状态）
- `.serena/`（2 文件——Agent 本地状态；`.serena/.gitignore` 与 `project.yml`；`.serena/cache/` 与 `project.local.yml` 已被 gitignore）
- `docs/audits/`（1 文件——营业时间硬校验审计，属保护目录）
- `.env`（存在且被 .gitignore 忽略，含真实凭据，绝不提交）
- 其余 gitignore 产物（`.codegraph/`、`.idea/`、`.pytest_cache/`、`.ruff_cache/`、`__pycache__/`、`.venv/`、`target/`、`dist/`、`coverage/`、`test-results/`、`.coverage` 等构建/测试产物——不在 status 中且被忽略）

### 11.4 异常项

无。全部 untracked 文件均可归属批次（Python/Java/Web/Contracts/Migrations/Evidence/scripts）；无生成产物混入；无 secret（见 §13 门禁）；无无法解释的删除。

## 12. 自包含性核对（全部闭环）

| 检查项 | 结果 |
| --- | --- |
| Java `place/` 包 import 闭环 | ✓ 仅依赖同包 `PlaceSearchDtos` + 已 tracked `common.ApiException` |
| `PlaceRefCanonicalizer`/`TripTitleGenerator` import | ✓ 仅标准库 + 同包/place 包 + tracked `common.ApiException` |
| Web 新组件/lib import | ✓ `PlaceAutocomplete.vue`→`../lib/api`（tracked M）；`TravelStyleEditor.vue`→`../lib/constraint-editor`（tracked M）；`place-selection.ts`→`./api`（tracked M）；`trip-title.ts` 无 import |
| messaging schema `$ref` | ✓ `planning-create-command-v4`/`planning-replan-command-v2`/`planning-candidate-validation-command-v2` 的 `$ref` 仅指向 `#/$defs/*`（自含）+ 已 tracked `planning-create-command-v3.schema.json`、`planning-completed-event-v5/v9.schema.json` |
| fixture 引用 | ✓ `planning-create-command-v4/valid.json` 等被已 tracked Java `PlanningCandidateValidationCommandContractTest` + Python `test_messaging_contract_schemas.py` 引用；guide fixture 双份（contracts + test/resources）SHA256 一致 |
| Flyway 链 | ✓ V33/V34 tracked + V35/V36 新增，连续无 gap（升级路径 TripPaceMigrationIntegrationTest 4/4 已验） |
| 删除无残留 | ✓ git grep 0 命中已删符号 |
| 新增测试均被全量套件覆盖 | ✓ Java 522（surefire 自动发现全部 untracked 测试）、Python 1491/37、Web 401 均包含各自 untracked 测试 |
| 文档链接 | ✓ 272 links / 0 broken |
| 提交后自包含 | ✓ 授权集合包含全部实现+测试+契约+迁移+文档+验收脚本，无"提交后仍依赖未跟踪文件" |

## 13. 轻量门禁（独立执行）

| 项 | 结果 |
| --- | --- |
| `git diff --check` | ✓ 0 whitespace errors（CRLF 警告为基线既有） |
| Markdown links | ✓ 272 / 0 broken |
| secret 扫描（tracked diff + 全部 untracked 文件） | ✓ 0 hits（AKIA/PRIVATE KEY）；`scripts/acceptance/b14/` 仅含测试专用弱密码 `b14-pass-123456`（非真实凭据），0 个 32-hex AMap key；results-*.json 0 secret |
| staged | ✓ 空（0 行） |
| 新增文件授权覆盖 | ✓ 78 个 untracked 全部在 §11.2 清单，无遗漏 |
| 删除均属批准删除 | ✓ 5 D 全部为旧 UI/NLP/parser（ConstraintCard/NaturalLanguageInput/TripTemplates/constraint-parser），HEAD 中存在、无引用残留 |
| acceptance-report 本次追加自身 | ✓ 本章节写入 `docs/execution/B14_FIX/acceptance-report.md`（已在 §11.2 授权清单） |

## 14. 历史状态解释

- **B13、B13_FIX 早期 NEEDS_CORRECTION 历史继续保留**：本校准不删除、不改写任何早期失败记录（B13/B13_FIX/B14 的 acceptance-report 原文完整保留在 `docs/execution/` 各批次目录）。
- **最终 B14_FIX.1 的独立全量验收覆盖完整工作树**：B14_FIX.1 验收（上方章节）在 HEAD `89236ea` + 全部 B13…B14_FIX.1 未提交改动的工作树上执行，Java 522/Python 1491/Web 401/Playwright 21 等全量数字已覆盖这些批次的最终实现。
- **最终 PASS 覆盖集成代码状态，但不替代早期失败记录**：功能验收结论针对当前完整工作树；各批次历史 NEEDS_CORRECTION 仍作为过程记录保留。
- **B14 是验收资产批次**：`docs/execution/B14/`（plan/defects/scenario-catalog/execution-report/artifact-manifest）与 `scripts/acceptance/b14/`（可重复验收脚本 + 结果 JSON）作为发布证据一并提交。

## 15. 授权清单（机器可核对，逐文件）

### A（新增，78 files）

```
A apps/agent-service/src/trip_agent/internal_security.py
A apps/agent-service/src/trip_agent/places/api.py
A apps/agent-service/tests/guide_intelligence/test_city_contract.py
A apps/agent-service/tests/test_avoid_rank.py
A apps/agent-service/tests/test_boundary_authority.py
A apps/agent-service/tests/test_emitted_day_ordering.py
A apps/agent-service/tests/test_meal_type_binding.py
A apps/agent-service/tests/test_meal_window_source.py
A apps/agent-service/tests/test_must_visit_recall.py
A apps/agent-service/tests/test_place_authenticity.py
A apps/agent-service/tests/test_place_ref_contract.py
A apps/agent-service/tests/test_places_api.py
A apps/agent-service/tests/test_worker_invalid_command.py
A apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/place/AgentPlaceSearchClient.java
A apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/place/HttpAgentPlaceSearchClient.java
A apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/place/PlaceSearchDtos.java
A apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/place/PlaceSelectionTokenService.java
A apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/place/PlaceSuggestionController.java
A apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/place/PlaceSuggestionService.java
A apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/PlaceRefCanonicalizer.java
A apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripTitleGenerator.java
A apps/travel-server/src/main/resources/db/migration/V35__add_trip_datetime_boundaries.sql
A apps/travel-server/src/main/resources/db/migration/V36__add_trip_place_refs.sql
A apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/guide/GuideImportContractTest.java
A apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/place/HttpAgentPlaceSearchClientTest.java
A apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/place/PlaceSuggestionServiceTest.java
A apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningOutboxBoundaryContractIntegrationTest.java
A apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/trip/MunicipalityRegionIntegrationTest.java
A apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/trip/PlaceRefCanonicalizerTest.java
A apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/trip/TripTitleGeneratorTest.java
A apps/travel-server/src/test/resources/fixtures/guide-city-intelligence-real-response.json
A apps/web/e2e/weather-window.spec.ts
A apps/web/src/components/PlaceAutocomplete.vue
A apps/web/src/components/TravelStyleEditor.vue
A apps/web/src/components/TripBoundaryEditor.vue
A apps/web/src/lib/place-selection.test.ts
A apps/web/src/lib/place-selection.ts
A apps/web/src/lib/trip-title.ts
A apps/web/tests/PlaceAutocomplete.test.ts
A apps/web/tests/TravelStyleEditor.test.ts
A apps/web/tests/TripBoundaryEditor.test.ts
A apps/web/tests/TripWorkspaceActions.test.ts
A apps/web/tests/china-divisions.test.ts
A apps/web/tests/place-selection.test.ts
A apps/web/tests/trip-title.test.ts
A contracts/fixtures/guide-city-intelligence-real-response.json
A contracts/fixtures/planning-candidate-validation-command-v2/valid-edit.json
A contracts/fixtures/planning-candidate-validation-command-v2/valid-rollback.json
A contracts/fixtures/planning-create-command-v4/valid.json
A contracts/fixtures/planning-replan-command-v2/valid.json
A contracts/messaging/planning-candidate-validation-command-v2.schema.json
A contracts/messaging/planning-create-command-v4.schema.json
A contracts/messaging/planning-replan-command-v2.schema.json
A docs/execution/B13/plan.md
A docs/execution/B13/execution-report.md
A docs/execution/B13/acceptance-report.md
A docs/execution/B13_FIX/plan.md
A docs/execution/B13_FIX/execution-report.md
A docs/execution/B13_FIX/acceptance-report.md
A docs/execution/B14/plan.md
A docs/execution/B14/execution-report.md
A docs/execution/B14/artifact-manifest.md
A docs/execution/B14/defects.md
A docs/execution/B14/scenario-catalog.md
A docs/execution/B14_FIX/plan.md
A docs/execution/B14_FIX/execution-report.md
A docs/execution/B14_FIX/acceptance-report.md
A scripts/acceptance/b14/b14lib.py
A scripts/acceptance/b14/matrix_a.py
A scripts/acceptance/b14/matrix_b.py
A scripts/acceptance/b14/matrix_fault.py
A scripts/acceptance/b14/matrix_param.py
A scripts/acceptance/b14/matrix_real.py
A scripts/acceptance/b14/results-a.json
A scripts/acceptance/b14/results-b.json
A scripts/acceptance/b14/results-fault.json
A scripts/acceptance/b14/results-param.json
A scripts/acceptance/b14/results-real.json
```

### M（修改，74 files）

```
M README.md
M apps/agent-service/src/trip_agent/domain/shared.py
M apps/agent-service/src/trip_agent/feasibility/inputs.py
M apps/agent-service/src/trip_agent/feasibility/rules/meal.py
M apps/agent-service/src/trip_agent/guide_intelligence/api.py
M apps/agent-service/src/trip_agent/infrastructure/amap/feasibility_projection.py
M apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py
M apps/agent-service/src/trip_agent/infrastructure/demo/planning_provider.py
M apps/agent-service/src/trip_agent/main.py
M apps/agent-service/src/trip_agent/planning/candidates.py
M apps/agent-service/src/trip_agent/planning/daily_schedule.py
M apps/agent-service/src/trip_agent/planning/validation_projection.py
M apps/agent-service/src/trip_agent/worker/amqp.py
M apps/agent-service/src/trip_agent/worker/contracts.py
M apps/agent-service/tests/feasibility/test_meal_window_rule.py
M apps/agent-service/tests/test_amap_feasibility_projection.py
M apps/agent-service/tests/test_amqp_worker.py
M apps/agent-service/tests/test_daily_skeleton_provider.py
M apps/agent-service/tests/test_meal_window_placement.py
M apps/agent-service/tests/test_messaging_contract_schemas.py
M apps/agent-service/tests/test_validation_projection.py
M apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/itinerary/ItineraryVersionService.java
M apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningProgressService.java
M apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/planning/PlanningTaskService.java
M apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripConstraintRecord.java
M apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripConstraintValidator.java
M apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripController.java
M apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripMapper.java
M apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripRecord.java
M apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripRequests.java
M apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripService.java
M apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/trip/TripSnapshotRecord.java
M apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningReviewFlowIntegrationTest.java
M apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/planning/PlanningTaskFlowIntegrationTest.java
M apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/trip/TripFlowIntegrationTest.java
M apps/travel-server/src/test/java/io/github/tobehardoo/trippilot/trip/TripPaceMigrationIntegrationTest.java
M apps/web/e2e/feasibility-outcomes.spec.ts
M apps/web/e2e/golden-journeys.spec.ts
M apps/web/src/components/CityCascadePicker.test.ts
M apps/web/src/components/CityCascadePicker.vue
M apps/web/src/components/ConstraintEditor.vue
M apps/web/src/components/FeasibilityReportPanel.vue
M apps/web/src/components/GuideIntelligencePanel.vue
M apps/web/src/components/PlanEvaluationPanel.test.ts
M apps/web/src/components/PlanningProgress.vue
M apps/web/src/components/PlanningReviewPanel.vue
M apps/web/src/components/TransitLegControl.test.ts
M apps/web/src/components/TripDashboard.vue
M apps/web/src/components/TripDetail.test.ts
M apps/web/src/components/TripDetail.vue
M apps/web/src/components/TripMap.vue
M apps/web/src/components/TripWeatherTimeline.vue
M apps/web/src/lib/api.ts
M apps/web/src/lib/china-divisions.ts
M apps/web/src/lib/constraint-draft.ts
M apps/web/src/lib/constraint-editor.ts
M apps/web/src/pages/TripWorkspace.vue
M apps/web/tests/App.test.ts
M apps/web/tests/FeasibilityReportPanel.test.ts
M apps/web/tests/GuideIntelligencePanel.test.ts
M apps/web/tests/PlanningProgress.test.ts
M apps/web/tests/PlanningReviewPanel.test.ts
M apps/web/tests/TripDashboard.test.ts
M apps/web/tests/TripDetailItineraryEditing.test.ts
M apps/web/tests/TripWeatherTimeline.test.ts
M apps/web/tests/amap.test.ts
M apps/web/tests/constraint-editor.test.ts
M apps/web/tests/region-ref.test.ts
M apps/web/vite.config.ts
M docs/architecture/行程真实性与旅行骨架.md
M docs/architecture/规划工作流.md
M docs/development/代码架构导读.md
M docs/product/系统完善长期执行与验收总控计划.md
M docs/product/项目路线图.md
```

### D（删除，5 files）

```
D apps/web/src/components/ConstraintCard.vue
D apps/web/src/components/NaturalLanguageInput.vue
D apps/web/src/components/TripTemplates.vue
D apps/web/src/lib/constraint-parser.ts
D apps/web/tests/constraint-parser.test.ts
```

### 汇总

- 总文件数：**157**（A 78 + M 74 + D 5）
- insertions/deletions：**+6407 / -1827**（tracked diff；新增文件行数未计入 numstat，需以 `git add -A` 后 staged numstat 为准）
- 排除文件清单：`.omo/`（20）、`.serena/`（2）、`docs/audits/`（1）、`.env`（gitignored）及全部 gitignore 构建产物
- 提交后预期 `git status --short`：仅剩 `.omo/`、`.serena/`、`docs/audits/` 三个 untracked 保护目录与 `.env`（gitignored 不显示）

### 授权清单机械纠正记录

（本节为后续机械修正追加，记录 §15 机器可执行清单的两处机械错误及修正；不改变上方任何验收 verdict、业务范围或代码，不删除早期 NEEDS_CORRECTION 或 PASS 历史。）

- **错误 1（幽灵 A 条目）**：原 §15 A 清单误列 `A docs/execution/B14/acceptance-report.md`，但该文件在磁盘、git status 与 git ls-files 中均不存在（`docs/execution/B14/` 实际仅含 5 文件：`artifact-manifest.md`、`defects.md`、`execution-report.md`、`plan.md`、`scenario-catalog.md`）。已删除该幽灵条目，A 计数恢复为 78；未创建任何文件来迎合错误清单。
- **错误 2（M 路径错字）**：原 §15 M 清单将 `docs/development/代码架构导读.md` 误写成 `docs/development/代码结构导读.md`（「架」误为「结」）。已修正为磁盘真实路径（字节级一致）。
- 两处均为清单机械错误，不改变验收 verdict、业务范围或代码。
- 上一轮 Git closeout 因此正确停止，输出 `GIT_CLOSEOUT_SCOPE_DRIFT`，未 stage/commit/push（HEAD `89236ea` 未变，staged 保持空）。
- 同步修正：§11.1「文档（6 M）」叙述中的同一错字与 §11.2「执行与验收证据（14 A）」叙述中的同一幽灵引用已一并对齐，保证报告内部一致。
- 修正后机器清单：A=78、M=74、D=5、total=157，与 `git status --porcelain=v1 -z -uall`（排除 `.omo/`、`.serena/`、`docs/audits/`、`.env`）严格相等（§17 重新对账确认）。

## 16. 判定

**B14_FIX_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT**
**B13_B14_INTEGRATED_SCOPE_AUTHORIZED_FOR_GIT_CLOSEOUT**
**B13_B14_SCOPE_MANIFEST_CORRECTED**
**RELEASE_READY**

- 完整工作树（HEAD `89236ea` + B13…B14_FIX.1 全部未提交改动）可形成单个自包含、已独立验收（Java 522 / Python 1491+37 / Web 401 / Playwright 21 / Compose 真实验收）、无 secret、无未归属文件的发布提交。
- 授权范围 = 79 tracked（74 M + 5 D）+ 78 A，共 157 文件；5 个删除均为已批准旧 UI/NLP/parser 且无残留引用；V35/V36、Place API（Java+Python）、Web 新组件、messaging v4/v2 schemas 与 fixtures、B13/B14 证据文档、B14 可重复验收脚本全部纳入。
- 未发现阻塞项；早期 NEEDS_CORRECTION 历史保留；本校准章节为 acceptance-report 唯一追加内容。
