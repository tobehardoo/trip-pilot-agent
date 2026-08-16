# B13_FIX 独立验收报告

## 1. 结论

**Verdict: `NEEDS_CORRECTION`**
**Release verdict: `RELEASE_FREEZE_BLOCKED`**

B13_FIX 修复了 B13 验收的多数核心缺陷：边界时间已进入规划快照并约束候选首末活动、schema3 混合态三端一致且无效命令得到安全终态、meal 按类型绑定不再位置错配、直辖市可创建、selection token 闭环（伪造/缺失/跨 owner 均 400 且篡改字段被 canonicalize）、创建表单收敛为两个 datetime、Review UI 技术详情默认折叠。但独立复现发现 **6 项与验收任务书逐字要求冲突或执行报告与实际不符** 的问题，其中 P1-4"候选在 1440×900 首屏"为判定规则明确列举的不得 PASS 项，且对应 e2e 测试存在假绿。本报告不授权 Git 收口、push、PR 合并、tag 或 release freeze。

## 2. 验收基线与纪律

| 项 | 结果 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `89236ea731b3d9aea55a81f96101940299f2c983`（B12，未变） |
| staged | 空 |
| B13_FIX 实现 | 全部 unstaged/untracked；`docs/execution/B13_FIX/` 仅有 plan.md + execution-report.md |
| 本验收写入 | 仅本文件（`docs/execution/B13_FIX/acceptance-report.md`） |
| 保护项 | `.omo/`、`.serena/`、`docs/audits/`、`.env`、`docs/execution/B13/acceptance-report.md` 未处理 |
| 业务代码/测试/契约/migration | 未修改；未 stage/commit/push |

验收方法：静态调用链审查（Java/Python/Web 生产代码逐文件阅读）+ 独立全量门禁复跑 + 独立隔离 Compose（新 project `trip-pilot-b13fix-accept`、端口 38082/39092、网络 172.31.252.0/24、独立卷）+ 真实 HTTP 对抗输入 + 真实浏览器（Playwright chromium）+ PostgreSQL 直接 DB 核对。所有门禁/复现均为本验收独立执行，不采用执行报告数字。

## 3. 独立门禁（本验收亲自复跑）

| 门禁 | 命令 | 独立结果 | 判定 |
| --- | --- | --- | --- |
| Python 全量 | `.venv python -m pytest` | **1466 passed / 37 skipped** | PASS |
| Python lint | `ruff check src tests` | All checks passed | PASS |
| Java `mvn verify`（JDK 21） | `mvn -q verify` | **485 tests, 0 failures/errors/skipped**；JaCoCo line 85.81%（min 0.80） | PASS |
| Flyway | 干净库迁移 V1→V36 + V34→V36 升级 | 全部成功 | PASS |
| Web unit | `npx vitest run` | **384 passed (41 files)** | PASS |
| Web typecheck/build | `vue-tsc -b` + `vite build` | 通过；dist 正常产出 | PASS |
| Web coverage | `vitest run --coverage` + coverage-final.json 逐文件解析 | 22 个 include 文件 **全部** stmts/branch/funcs/lines ≥80%（aggregate 95.77/85.05/94.67） | PASS |
| Playwright e2e | `CI=1 npx playwright test` | **21 passed** | PASS（但 P1-4 断言假绿，见发现 1） |
| 仓库 | `git diff --check` / `check_markdown_links.py` / `check_compose_defaults.py` / `docker compose config --quiet` | 全部通过 | PASS |
| Secret | `git ls-files` 无 .env/.pem/.key/.p12/.pfx；gitleaks 未安装（按总控计划以 CI 为远端证据） | PASS | PASS |

## 4. 独立隔离 Compose Golden（真实 HTTP + 浏览器 + DB）

新 project `trip-pilot-b13fix-accept`：全部服务 healthy、`knowledge-init` 正常退出、DEMO_ONLY；结束后 `down -v --remove-orphans` 仅清理本验收项目，用户 `trip-pilot-prod` 栈（8 容器，38080/9090）未触碰。

### 4.1 通过项（真实请求/DB/浏览器证据）

| # | 场景 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 北京直辖市创建（P1-1） | PASS | POST 201，region 110000/110000 |
| 2 | 重庆直辖市创建（P1-1） | PASS | POST 201，region 500000/500000/500103 |
| 3 | 普通省市创建 | PASS | POST 201，440000/440100/440106 |
| 4 | region read-back | PASS | API 回读 cityCode=440100, district=440106 |
| 5 | 晚到：候选首项不早于 18:00（P0-1） | PASS | WAITING_USER，firstStart=2026-08-20T18:00:00+08:00 |
| 6 | 早离：末日末项不晚于 10:00（P0-1） | PASS | WAITING_USER，lastEnd=2026-08-22T10:00:00+08:00 |
| 7 | 搜索返回 owner-scoped token（P1-2） | PASS | hasToken=true |
| 8 | 带 token 保存 | PASS | 201 |
| 9 | 伪造 token 拒绝 | PASS | 400 PLACE_REF_TOKEN_INVALID |
| 10 | 缺 token 拒绝 | PASS | 400 PLACE_REF_TOKEN_REQUIRED |
| 11 | 跨 owner token 拒绝 | PASS | 400 PLACE_REF_TOKEN_INVALID |
| 12 | 篡改 address/coords 被 canonicalize | PASS | 201；DB 持久化 address="Demo location in 广州"/lon=113.2644（服务端缓存值，非 HACKED/1.0） |
| 13 | 篡改 providerPoiId 拒绝 | PASS | 400 PLACE_REF_TOKEN_INVALID |
| 14 | 合法混合态：structured accommodation + legacy avoid text | PASS | 创建 201 → 规划 WAITING_USER（非永久 QUEUED） |
| 15 | Java 拒绝 refs/names 数量不匹配 | PASS | 400 VALIDATION_FAILED |
| 16 | 仅晚餐不误绑 LUNCH（P0-3） | PASS | 抵达日无 12:00 活动；meal rule UNKNOWN/MEAL_WINDOW_UNVERIFIED |
| 17 | DEMO_ONLY UNVERIFIED | PASS | report status=UNVERIFIED |
| 18 | WAITING_USER 不创建正式版本 | PASS | itinerary API 404；DB version_count=0、report_count=0 |
| 19 | 非法 command 安全终态（DB） | PASS | 1 任务 FAILED NO_FEASIBLE_ITINERARY（DEMO 对 must-visit 的安全失败，非混合约束被拒）；6 命令全部 SENT 非永久 QUEUED |
| 20 | 无 selectionToken 泄漏（DB） | PASS | outbox/REVIEW_REQUIRED payload 均无 selectionToken |
| 21 | outbox 权威边界（DB） | PASS | schemaVersion=4；arrivalAt/departureAt 带 +08:00 |

### 4.2 浏览器 UI Golden

| # | 场景 | 结果 | 证据 |
| --- | --- | --- | --- |
| 22 | 创建页仅 2 个 datetime（F/P1-3） | PASS | `input[type=datetime-local]` count=2 |
| 23 | legacy 到返时间输入不存在 | PASS | 到达时间（北京时间）/返程时间（北京时间）count=0 |
| 24 | 无快捷模板 / 无 NLP 入口 | PASS | 广州 City Walk 等 count=0 |
| 25 | 自动标题预览（F） | PASS | "2026年08月20日—08月22日 广州市旅行规划" |
| 26 | Review 主要风险在 toggle 前（G/P1-4） | PASS | DOM order 确认 |
| 27 | 验证详情默认折叠 + 技术字段隐藏 | PASS | aria-expanded=false；硬可行性验证/MEAL_WINDOW_UNVERIFIED/hard-validator 不可见 |
| 28 | 点击 toggle 后技术详情可见 | PASS | 可见 |
| 29 | 天气区域存在（G） | PASS | 行程天气 region 可见 |
| 30 | 390×844 无横向溢出 | PASS | scrollWidth≤clientWidth |

## 5. 发现清单（置信度 ≥80%，按验收任务书逐字要求核对）

### 发现 1（P0，G 组 / P1-4 未关闭）候选不在 1440×900 首屏，e2e 断言假绿

- **文件与位置**：`apps/web/e2e/weather-window.spec.ts:181-184`（先 `scrollIntoViewIfNeeded()` 再断言 bbox）；生产布局 `apps/web/src/components/TripDetail.vue`（天气区 + 我的要求 + review 面板纵向占位）。
- **触发输入**：真实隔离栈，1440×900 视口，WAITING_USER 页面加载后 `window.scrollTo(0,0)`（scrollY=0）。
- **实际行为**：候选标题 `.review-panel h3` 的 getBoundingClientRect().y=944、bottom=964，**超出 900px 首屏 64px**；`#planning-review-section` y=801（其标题在 944）。e2e 测试因先滚动再断言，`y>=0 && y+h<=900` 恒真 → 假绿。
- **预期行为**：任务书 G 组"candidate heading 的 boundingBox 必须在 viewport 内"、判定规则"candidate 不在 1440×900 首屏"不得 PASS；页面加载（不滚动）时候选标题应在 900px 内。
- **最小复现**：`docker compose -p trip-pilot-b13fix-accept up` → 注册→创建行程→开始规划→WAITING_USER→`window.scrollTo(0,0)`→读 `.review-panel h3` boundingBox（y=944）。已实测。
- **为什么现有测试未捕获**：weather-window.spec.ts 第 181 行在 bbox 断言前调用 `scrollIntoViewIfNeeded()`，把"首屏内"偷换成"滚动后可见"；App.test.ts 的 P1-7 用例只断言 `candidate-day` class，不断言页面级 bbox。
- **最小修复方向**：压缩天气条/我的要求/头部纵向占位，或把候选概要提升至首屏（例如天气条改为更紧凑横条、我的要求未设置项零高度已做但需实测），并删除 e2e 中的 `scrollIntoViewIfNeeded()` 前置，改在 scrollY=0 断言 bbox≤900。

### 发现 2（P1，E 组 Web 未关闭）未选候选的自由文本 anchor 可提交并落库

- **文件与位置**：`apps/web/src/components/ConstraintEditor.vue` `typeAnchor()`（自由文本保留为 legacy）、`apps/web/src/lib/constraint-editor.ts` `validateConstraintEditor()`（不要求 arrivalRef/departureRef/accommodationRef）；服务端 `TripService.canonicalizeAnchor()`（`anchor.placeRef()==null` 时原样放行）。
- **触发输入**：创建表单，到达地点输入"随便输入的车站名XYZ"，不选择任何候选，直接保存。
- **实际行为**：POST /api/trips **201 成功**，行程详情显示该自由文本；DB 中 arrival 为无 placeRef 的 legacy 文本。页面出现"自由文本地点保持原样"提示但**不阻止提交**。
- **预期行为**：任务书 E 组 Web："arrival/departure/accommodation/must/avoid 都不能自由文本提交；输入但未选择候选时必须阻止提交"。
- **最小复现**：真实浏览器已实测（POST 201 + 详情页可见自由文本）。
- **为什么现有测试未捕获**：既有测试只覆盖"选择候选后提交"成功路径与"必须从候选选择"的文案断言，没有"输入文本未选候选→保存"的负向测试；`typeAnchor` 保留文本是 B13 时代 legacy 兼容设计的延续，B13_FIX 未按任务书收口。
- **最小修复方向**：`validateConstraintEditor` 对三个 anchor 要求"有文本必须有 ref（或明确 legacy 兼容白名单）"，未选候选时阻止提交并给出中文错误；或按任务书彻底移除 legacy 文本提交路径（仅编辑既有 legacy 行程时允许）。

### 发现 3（P1，J 组 / P1-6 未关闭）地点搜索缓存 key 字符串拼接可碰撞

- **文件与位置**：`apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/place/PlaceSuggestionService.java:63` `String key = ownerId + "|" + city + "|" + keyword + "|" + limit;`
- **触发输入**：同一 owner 依次请求 `(city='广州', keyword='AB|CD', limit=10)` 与 `(city='广州|AB', keyword='CD', limit=10)`（`|` 在 city/keyword 中合法，Java 与 agent-api 均无字符集限制）。
- **实际行为**：两个请求生成相同 key `owner|广州|AB|CD|10`；第二个请求错误命中第一个的缓存，返回 `["AB|CD (demo)"]` 而非其自身应返回的 `["CD (demo)"]`。已实测（providerPoiId 相同 = 命中错误缓存）。
- **预期行为**：任务书 E/J 组"cache key 无字符串拼接碰撞"；不同查询不得共享缓存条目。
- **最小复现**：真实栈已复现（两次搜索返回相同候选 id）。
- **为什么现有测试未捕获**：`PlaceSuggestionServiceTest` 只测同参数缓存命中与 TTL，没有构造含分隔符的 city/keyword 组合。
- **最小修复方向**：使用结构化 key（record/对象作 ConcurrentHashMap key，或对字段做长度前缀 + 转义），并在测试中加入含 `|` 输入的碰撞反例。

### 发现 4（P1，J 组 / P1-6 未关闭）agent-api 地点搜索每次请求新建 AsyncClient 且不关闭

- **文件与位置**：`apps/agent-service/src/trip_agent/places/api.py:69-79` `_provider()` 在 REAL 模式每次调用 `httpx.AsyncClient(timeout=...)` 且从不 `aclose()`；`apps/agent-service/src/trip_agent/main.py` 无 lifespan shutdown 钩子。
- **触发输入**：`PROVIDER_MODE=REAL_ONLY` + AMap key 配置后连续多次 `POST /internal/v1/places/search`。
- **实际行为**：每次搜索新建一个 AsyncClient（连接池/文件描述符不释放）；worker 侧 `planning_provider_runtime` 用 `async with` 正确管理，但搜索端点（本缺陷原始 P1-6 所指路径）未修复。执行报告 R5 声称"Python 生命周期复用 AsyncClient 并在 shutdown 关闭"——对该端点不成立。
- **预期行为**：任务书 E/J 组"Python AsyncClient 被复用并可关闭"。
- **最小复现**：静态审查 + `_provider()` 无缓存/无关闭路径；REAL 模式（本机无 AMap key，无法真机触发，但代码路径确定）。
- **为什么现有测试未捕获**：`test_places_api.py` 在 DEMO_ONLY 下运行（`_provider()` 返回 DemoMapProvider，无 AsyncClient），REAL 分支无测试。
- **最小修复方向**：模块级缓存 provider + `app.add_event_handler("shutdown")` 关闭；或复用 worker 的 `async with httpx.AsyncClient` 上下文管理模式。

### 发现 5（P1，G 组 / P1-7 部分未关闭）WAITING_USER+正式共存时天气点击仍选中旧正式活动

- **文件与位置**：`apps/web/src/components/TripDetail.vue:500-501` `selectWeatherDate` 无条件 `selectedActivityId.value = activity?.id`（activity 取自**正式** itinerary 首活动），随后才判断 WAITING_USER+candidateHasDate 滚动到候选日。
- **触发输入**：WAITING_USER + 正式行程共存且同日候选；点击天气日期。
- **实际行为**：滚动到 `#candidate-day-2026-08-02` 正确（border-primary-400 ✓），但 `selectedActivityId` 指向正式活动 id：实测正式活动 `li#activity-dddd5555…` class 含 `z-10`、地图 fallback marker `.is-selected` 计数=1（**选中旧正式活动**）。任务书要求"不得选中旧正式活动"。
- **预期行为**：WAITING_USER 且候选含该日期时，`selectedActivityId` 不应指向正式行程活动（应为 null 或候选活动），地图不得高亮旧正式路线。
- **最小复现**：真实浏览器 mock 共存场景已实测（z-10 + is-selected）。
- **为什么现有测试未捕获**：weather-window.spec.ts P1-7 用例只断言候选日 class 与正式 heading 可见，不断言地图 marker/selectedActivityId；App.test.ts 同样只查候选日高亮。
- **最小修复方向**：在 WAITING_USER+candidateHasDate 分支不设置正式活动 selectedActivityId（置 null 或候选活动 id），仅回退分支才指向正式活动。

### 发现 6（P1，E 组 / P1-2 部分未关闭）`avoid_place_refs` 未被 Python planner 消费，"structured must/avoid 仅按 id"对 avoid 不成立

- **文件与位置**：`apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py:319` 仅传 `avoid_places=constraints.avoid_places`；`apps/agent-service/src/trip_agent/planning/candidates.py:207-213` `_matches_any` 为文本子串匹配；`avoid_place_refs` 全仓仅 contract 校验处出现（`worker/contracts.py:182,222,232`），无任何规划消费点。
- **触发输入**：用户 structured-avoid 一个 POI（带 providerPoiId），召回中出现同名兄弟 POI（不同 id）。
- **实际行为**：avoid 按文本子串过滤：同名兄弟可能被过度排除（文本命中），而结构化 avoid 的精确 id 从未用于决策；与 must-visit 的 exact-id 语义不对称。执行报告 R5 声称"structured must/avoid 仅按 id"——对 avoid 不成立。
- **预期行为**：任务书 E 组"structured must/avoid 仅按 id"；avoid refs 非空时应按 providerPoiId 精确排除。
- **最小复现**：静态调用链（rank 签名无 refs 参数）+ 测试 `test_planning_context_v2.py::test_ranker_filters_avoided_places...` 只传文本。
- **为什么现有测试未捕获**：无 structured avoid refs 的 ranker 测试；`test_place_authenticity.py` 只覆盖 must-visit 与 anchor。
- **最小修复方向**：`CandidateRanker.rank` 增加 `avoid_refs` 精确 id 集合（与 must_visit_ids 对称），`_plan_with_skeleton` 传入 `constraints.avoid_place_refs`；补充同名兄弟 avoid 反例测试。

### 发现 7（P2 观察，J 组安全副作用）跨 owner token 尝试会毒化原 owner 的合法 token

- **文件与位置**：`apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/place/PlaceSelectionTokenService.java:66-68` `redeem()` 在 owner 不匹配或过期时 `tokens.remove(token, entry)`。
- **实际行为**：B 用户持 A 的 token 尝试一次（400），随后 A 用同一 token 保存也变 400（实测 CHECK-6 确认"毒化"）。token 为 30 分钟短命 opaque，泄露途径有限，故为 P2。
- **预期/修复方向**：跨 owner redeem 仅拒绝不删除（或仅删除过期项），避免攻击者通过探测使受害者 token 失效。

## 6. 报告真实性对账

| 执行报告声称 | 独立核对 | 判定 |
| --- | --- | --- |
| Python 1466 / Java 485 / Web 384 / Playwright 21 | 全部一致（独立复跑） | 属实 |
| 22 个 include 文件 stmts/branch/funcs/lines ≥80% | coverage-final.json 逐文件解析全部 ≥80% | 属实 |
| 14 项 Compose Golden 全 PASS | 本验收独立复现 1-14 对应项（含 DB/浏览器）全 PASS | 属实 |
| R7"候选标题 bbox 在 900px 视口内" | 真实页面 scrollY=0 时 y=944 不在首屏；e2e 先滚动后断言 | **不符（假绿）** |
| R5"Python 生命周期复用 AsyncClient 并在 shutdown 关闭" | 仅 worker 侧成立；places/api.py 搜索端点每次新建不关闭 | **不符** |
| R5"structured must/avoid 仅按 id" | must-visit 成立；avoid refs 未消费 | **不符（部分）** |
| R7 P1-7 已关闭 | 滚动目标正确，但 selectedActivityId 仍选中旧正式活动 | **不符（部分）** |
| P1-6"结构化 key" | 实为字符串拼接，实测可碰撞 | **不符** |
| B13 NEEDS_CORRECTION 历史保留 | execution-report 触发段保留 | 属实 |
| 总控计划未提前写 PASS/COMMITTED/RELEASE_READY | B13 仍为 READY_FOR_REVIEW；无 B13_FIX 行 | 属实 |
| 环境故障记录 | ruff format 全仓 99 文件 CRLF 漂移（基线既有，非本批引入）已如实记录 | 属实 |

## 7. 判定依据（任务书第十七节）

- **不得 PASS 命中**：
  1. "candidate 不在 1440×900 首屏" → 实测 y=944>900（发现 1）；
  2. "WAITING_USER 天气联动旧正式行程" → 滚动正确但地图仍选中旧正式活动（发现 5）；
  3. "execution-report 与实际不符" → R5/R7 多项声称与实测不符（发现 1/3/4/6）；
  4. 另有任务书明确要求未满足：E 组"未选候选必须阻止提交"（发现 2）、"cache key 无字符串拼接碰撞"（发现 3）、"AsyncClient 复用并可关闭"（发现 4）、"structured must/avoid 仅按 id"（发现 6）。
- 业务/契约/事务/真实性主目标（边界时间、混合态终态、meal 绑定、token 闭环、直辖市、时间输入收口、默认折叠、coverage、契约版本、migration）经独立验证全部成立，故不属"整体未修复"，但上述 6 项为真实可复现缺口，其中 P1-4 首屏为 P0 级验收项。

**结论：`NEEDS_CORRECTION` / `RELEASE_FREEZE_BLOCKED`。不授权 Git 收口。**

## 8. 结束状态确认

- 唯一永久写入：`docs/execution/B13_FIX/acceptance-report.md` ✓
- 业务代码、测试、契约、migration 未修改 ✓
- staged 为空；未 commit、未 push；HEAD 未变（89236ea）✓
- 保护目录（`.omo/` `.serena/` `docs/audits/` `.env`、B13 acceptance-report）未处理 ✓
- 隔离栈 `trip-pilot-b13fix-accept` 已 `down -v --remove-orphans` 清理；用户 `trip-pilot-prod` 栈未触碰 ✓
- 临时脚本/env 已全部删除 ✓

## 9. 修复后复验要求（下一轮）

1. 修复发现 1-6 并保留真实 RED→GREEN 证据（P1-4 的 e2e 必须去掉 scrollIntoViewIfNeeded 前置、在 scrollY=0 断言 bbox≤900）。
2. 补 structured avoid refs ranker 精确 id 测试、缓存 key 碰撞反例、未选候选提交负向测试、P1-7 地图 marker 断言。
3. 重新独立执行全部门禁 + 隔离 Compose Golden（含本报告 4.1/4.2 全部场景）。
