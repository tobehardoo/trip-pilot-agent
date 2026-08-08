# TripPilot 路线图强制审计 1（2026-08-02）

## 1. 审计范围与结论

- 审计范围：第 1 轮双线集成与第 2 轮组合门禁，Git 范围 `56eee3c..4161b96`，以及本审计发现后的未提交修复。
- 审计方法：Git 差异与历史检查、代码/契约/配置审查、测试用例到业务链路映射、完整回归、浏览器验收、Compose 证据复核和全历史泄密扫描。
- 当前分支：`codex/plan-evaluation-weather-integration`；`main` 仍保持 `c256176`，未提交、推送、合并或创建 PR。
- 结论：自审与独立代码审查共发现 5 项 Important，均在审计期间修复并通过回归；未发现 Critical。剩余事项均为 Normal 技术债或需要真实部署资源的 Deferred 项。

| 级别 | 发现数 | 已修复 | 未解决 |
| --- | ---: | ---: | ---: |
| Critical | 0 | 0 | 0 |
| Important | 5 | 5 | 0 |
| Normal | 6 | 0 | 6 |
| Deferred | 3 | 0 | 3 |

## 2. 路线图符合性

| 路线图要求 | 审计结果 | 证据 |
| --- | --- | --- |
| 阶段 0 保护现场 | 通过 | 天气工作已形成提交；`.claude/`、`.pnpm-store/` 和产物目录均未受 Git 跟踪；`main` 未移动 |
| 阶段 1 天气/城市情报收口 | 通过 | QWeather、AMap 组合与显式回退实现及定向测试见 [`service.py`](../../../apps/agent-service/src/trip_agent/guide_intelligence/service.py) 和 [`test_service.py`](../../../apps/agent-service/tests/guide_intelligence/test_service.py) |
| 阶段 2 双线集成 | 通过 | [`TripDetail.vue`](../../../apps/web/src/components/TripDetail.vue) 同时装配评估、天气和地图；[`TripWorkspace.vue`](../../../apps/web/src/pages/TripWorkspace.vue) 绑定当前版本的 planning task |
| 阶段 3 完整组合验证 | 通过（本地） | Python 541、Java 208、Web 124、Playwright 6、benchmark 8/8、Flyway V1–V27、JaCoCo、构建和隔离 Compose 均通过 |
| 阶段 4 真实环境验收 | 未开始（外部阻塞） | 缺真实域名、证书、Key、Host、白名单、staging、告警和恢复环境 |

审计确认第 1–2 轮没有越权执行：未使用真实凭据、未访问第三方控制台、未推送、未创建 PR、未修改 `main`、未部署生产。

## 3. 发现与处置

### Important（均已修复）

#### I-01：缺少真正的 PlanEvaluation + 天气 + 地图组合 E2E

- 发现：第二轮最初通过的 5 个 Playwright 场景覆盖 session、编辑、SSE 和分享，但没有在一个真实浏览器页面中同时验证当前版本评估恢复、天气时间轴和地图日期过滤。仅凭组件/Workspace 测试不能称为“组合 E2E”。
- 处置：在 [`release-smoke.spec.ts`](../../../apps/web/e2e/release-smoke.spec.ts) 增加组合场景，通过当前 version 的 `planningTaskId` 返回成功任务与 91/100 评估，同时返回 QWeather 城市天气和两日 itinerary；断言点击 2026-08-02 后地图地点从 3 个收敛到当天 1 个。
- 验证：新增场景先单独通过；完整 Playwright `6 passed`；Web typecheck、124 项覆盖率测试和 production build 通过。

#### I-02：部分 QWeather 配置在 AMap 可用时被静默忽略

- 发现：[`service.py`](../../../apps/agent-service/src/trip_agent/guide_intelligence/service.py) 原先以 Key 和 Host 同时非空决定是否启用 QWeather。如果只设置其一但 AMap 已配置，系统会无提示退回 AMap，可能造成 staging 对 QWeather 配置的假阳性验收。
- 处置：先增加 Key-only 与 Host-only 两个失败用例，确认旧实现会继续请求 AMap；随后改为只要 Key/Host 完整性不一致就显式拒绝，并统一错误信息。
- 验证：Key-only、Host-only 和无 Provider 配置均有失败用例；全量 Python 与 Ruff 通过。

#### I-03：组合导入污染 trusted fact 的 Provider provenance

- 发现：组合路径虽然从顶层 facts 排除了 AMap `WEATHER`，却把完整 `amap.content` 拼回规范化文档，规则抽取会再次生成 AMap 天气；文档级 QWeather 来源又被复制给所有 trusted facts，导致 AMap 地点事实引用 QWeather URL。
- 处置：组合文档只拼接 QWeather 内容与 AMap 非天气 fact statements；验证后的 trusted facts 在 merge 前按类别重写来源，天气使用 QWeather/`WEATHER_PROVIDER`，非天气事实使用 AMap/`MAP_PROVIDER`，merge decision 与最终选择保持一致。独立复核进一步发现 AMap-only/回退天气仍引用 POI 搜索文档，随后把 AMap 天气 URL 修正为 `weatherinfo`、地点 URL 保持 `search`。
- 验证：测试断言组合文档不含 AMap 阵雨文本、只有 1 条天气 trusted fact，并验证组合、AMap-only 与 QWeather 失败回退三条路径的天气/地址分别携带正确 Provider 名称、端点 URL 与可靠性；17 项 service 定向测试和 Ruff 通过。

#### I-04：planning preflight 超时后仍可能把旧或空天气误当作本轮上下文

- 发现：QWeather 最多 10 个历史日期原为串行请求；Java 有界等待后直接继续，planning snapshot 对 pending 和“成功但日期无天气”的语义不够明确。
- 处置：历史天气改为并发、保持逐日失败可见；保留默认 `PT2S` 的 best-effort 非阻断语义，`prepare()` 返回 `DISABLED`/`TIMED_OUT`/终态结果。planning context 对运行中/超时写 `CITY_INTELLIGENCE_REFRESH_PENDING`，对成功但行程日期无天气写 `CITY_INTELLIGENCE_WEATHER_UNAVAILABLE`，两者均标 stale。严格 503 方案经复核被撤销，因为它会永久阻断远期行程、破坏无凭据 Demo，并扩大 servlet 线程占用。
- 验证：并发测试确认 3 个历史请求同时在途；Java 覆盖 success、timeout、provider failure、未来日期无天气和 pending snapshot，且这些状态不阻断规划创建。

#### I-05：AMap center 精度不符合 QWeather GeoAPI 坐标输入约束

- 发现：AMap `center` 被原样传给 QWeather，真实中心点可能超过 QWeather 城市查询允许的两位小数。
- 处置：跨 Provider 传递前解析 `lon,lat`、验证有限值与地理范围并格式化到两位；非法坐标沿既有显式 location fallback 使用城市名查询。
- 验证：高精度 `113.270123,23.130456` 回归确认 QWeather 收到 `113.27,23.13`。

### Normal（记录，当前不阻塞本地 RC）

#### N-01：Python 覆盖率阈值未覆盖城市情报模块

- 现状：CI 的 80% 覆盖率阈值只对 retrieval/acquisition 包计算；QWeather/城市编排由高密度定向测试和全量 pytest 保护，但没有独立覆盖率阈值。
- 建议：阶段 6 再决定是否扩展覆盖率口径，避免当前 RC 因历史未覆盖代码被迫进行无关补测；任何扩展应先记录新基线，再逐步提高。

#### N-02：Windows 非 ASCII 工作区需要显式 JaCoCo 数据路径

- 现状：复用 Maven daemon 时 `${env.SYSTEMROOT}` 曾保持为字面量；显式设置 `-Djacoco.data.file=C:/Windows/Temp/...exec` 后完整 verify 通过。Linux CI 配置不受该路径编码问题影响。
- 建议：若 Windows 成为正式开发门禁，在脚本中集中封装 ASCII 临时路径；当前记录在发布文档即可。

#### N-03：Web 丢弃结构化 `effectiveDate`

- 现状：Java API 已返回 `effectiveDate`，但 Web `GuideFact` 未声明它，天气时间轴仍从中文 statement 提取日期并回退 UTC `observedAt`。
- 建议：下一轮把 `effectiveDate` 纳入 TypeScript 契约并作为唯一首选日期，保留 statement 解析仅兼容旧数据。

#### N-04：同一行程换版本后可能保留失效地图日期

- 现状：itinerary 更新会修正 activity selection，但新版本不含 `selectedMapDate` 时不会自动清除，可能显示空地图。
- 建议：在 itinerary/version watcher 中验证日期并重置，增加同一 trip 跨版本回归。

#### N-05：刷新 requested-category 词汇与 trusted fact 类别不一致

- 现状：刷新命令沿用 `CURRENT_WEATHER`、`DAILY_FORECAST`、`ATTRACTION_DETAILS` 等采集意图，而持久化事实使用 `WEATHER`、`ADDRESS`、`COORDINATES` 等类别。preflight 已直接以 `WEATHER` 作最低完成条件，但 diagnostics 的 requested categories 仍不可直接与完成事实集合比较。
- 建议：在不破坏 v1 消息契约的前提下增加显式映射；若升级枚举则走新的 schema 版本。

#### N-06：preflight 仍在请求线程内进行最多 2 秒轮询

- 现状：等待已恢复为原有 2 秒上限，不再放大为 20 秒；但高并发 planning POST 仍可能短时占用 servlet 线程。
- 建议：阶段 6 将刷新建模为异步 planning 前置状态或独立进度事件；在此之前保持 2 秒上限，并在 staging 做并发与超时负载测试。

### Deferred（必须在真实环境完成）

#### D-01：真实第三方与 HTTPS 环境验收

缺 QWeather 专用 Host/Key、AMap 服务端 Key、AMap Web JS 最终域名白名单、HTTPS、Secure Cookie、真实返回差异、错误 Key、超时、限流和配额证据。本地 `DEMO_ONLY` Compose 不可替代这些证据。

#### D-02：远端 CI 与发布签字

用户明确禁止推送和创建 PR，因此 GitHub Actions 尚未在当前提交运行。已执行本地等价门禁，但 Linux runner、远端 gitleaks action 和最终不可变 SHA 仍需在获准推送后确认。

#### D-03：QWeather attribution 与许可验收

当前模型未保留 QWeather 响应中的 attribution/license 与 `fxLink`。正式上线前必须根据账号套餐和许可条款确认展示要求；如要求展示，应持久化实际 attribution/链接，不能只指向通用 API 文档。

## 4. 业务闭环审计

| 业务链路 | 结论 | 主要证据 |
| --- | --- | --- |
| 创建规划成功 | 通过 | [`App.test.ts`](../../../apps/web/tests/App.test.ts) 验证创建、SSE 完成、itinerary/versions/evaluation 刷新；Java/Python completion 测试已纳入全量门禁 |
| 创建规划失败 | 通过 | `PLANNING_FAILED` 业务错误和三次网络重试耗尽均有 Web 回归；失败不会清除当前版本已有有效评分 |
| 重规划与编辑/回滚 | 通过 | 当前版本重新加载；`USER_EDIT`/`ROLLBACK` 无 `planningTaskId` 时不继承陈旧评分；编辑提交和回滚继续使用幂等键 |
| PlanEvaluation 五维、警告、解释 | 通过 | Python 确定性 benchmark 8/8；completion v6、Java 持久化/API、Web [`PlanEvaluationPanel.vue`](../../../apps/web/src/components/PlanEvaluationPanel.vue) 与组件测试贯通 |
| legacy/null | 通过 | succeeded legacy task 的 `evaluation=null` 显示兼容提示；非成功或无关联任务不展示评分 |
| SSE 断线与重复事件 | 通过 | `Last-Event-ID` 恢复、重复阶段去重、离开页面终止并忽略迟到 completion 均有 Web 测试；浏览器场景覆盖一次断线恢复 |
| 实体 ID 重映射 | 通过 | PlanEvaluation completion 的 activity/transit 引用在 Python/Java 契约与持久化测试中验证 |
| 天气/地图日期联动 | 通过 | 组件测试验证日期过滤；新增 Playwright 在浏览器中验证评估、天气和地图组合链路 |
| QWeather/AMap 回退 | 通过（模拟） | QWeather+AMap、仅 QWeather、仅 AMap、QWeather 失败回退、AMap enrichment 失败、部分配置拒绝、坐标转换和 provenance 均有 Python 测试；真实 Provider 仍属 D-01 |
| planning preflight | 通过（模拟） | 历史天气并发；超时/失败/远期缺 `WEATHER` 均形成结构化诊断且不阻断核心规划；真实延迟仍需 staging 验证 |
| 幂等与安全失败 | 通过 | Java 创建/刷新/编辑幂等测试、失败任务安全字段与重试路径纳入 208 项全量验证 |

## 5. 配置与安全审计

- `PROVIDER_MODE` 是权威配置；`DEMO_MODE` 只保留兼容，冲突启动失败。规划 Provider 的 `PROVIDER_RETRY_*` 与 `PROVIDER_FALLBACK_CATEGORIES` 不冒充 QWeather 重试配置。
- `QWEATHER_API_KEY` 与 `QWEATHER_API_HOST` 已在 `.env.example`、Compose、README 和部署文档统一，代码现强制成对配置；Host 只接受 HTTPS 域名且不能包含路径。
- `CITY_INTELLIGENCE_PLANNING_WAIT_TIMEOUT` 在示例环境、Spring 默认值、生产 Compose 与部署文档统一为 `PT2S`；超时继续规划但 planning context 必须显式 stale/pending。
- QWeather Key 只通过 `X-QW-Api-Key` header 发送；异常信息只暴露超时、HTTP 状态或安全业务码，测试验证不泄露 Key。
- gitleaks 容器扫描 87 个提交时发现 1 个历史 Java 幂等 UUID 误报；当前夹具已改为合法低熵 UUID，`.gitleaksignore` 只登记精确 fingerprint，复扫无泄露。
- `git ls-files` 未发现 `.env`、PEM/Key/P12/PFX、`.claude/`、`.pnpm-store/`、`target`、`dist`、`coverage` 或 `test-results` 被跟踪。

## 6. 测试有效性与门禁复核

| 门禁 | 最终结果 | 备注 |
| --- | --- | --- |
| Python 全量 | 541 passed, 37 skipped | 审计新增部分配置、坐标、provenance 与并发历史天气回归 |
| Ruff | 通过 | 全库零问题 |
| PlanEvaluation benchmark | 8/8，两次输出逐字节一致 | 确定性门禁 |
| Java verify | 208 passed | Flyway V1–V27；JaCoCo 全部门禁通过 |
| Web coverage | 124 passed / 24 files | 语句/行 94.25%，分支 85.84%，函数 88.46% |
| Web typecheck/build | 通过 | Vite production build 通过 |
| Playwright | 6 passed | 新增真实组合页面场景 |
| Compose | 通过 | 开发/生产 config、五类镜像、隔离冷启动、8 服务健康、Web/API 200、完整拆除 |
| 文档/差异 | 通过 | Markdown links、`git diff --check` |
| 泄密/仓库安全 | 通过 | gitleaks 87 commits；tracked secret-like files 0 |

37 个 Python skipped 均为既有需要外部服务、可选依赖或平台条件的测试，不被计作通过；本轮没有通过删除/跳过测试来制造全绿。

## 7. Git 卫生

- 提交序列职责清晰：天气切片 `6c19d67`、Web 运行时集成 `1e5c2f7`、组合证据 `093aef1`、第二轮候选门禁 `4161b96`。
- 审计修复聚焦 Python Provider 编排/QWeather、Java preflight、1 个浏览器组合场景、对应配置与证据文档；未混入本地工具目录或生成物。
- 未执行 fetch/push/PR；因此远端引用新鲜度与远端 CI 均明确保持“尚未确认”。

## 8. 审计后的下一步

本地 Critical/Important 已清零。下一轮应进入阶段 4 的“部署环境验收准备”，只完成无需真实凭据的内容：形成可执行的 staging 验收清单、不可变镜像/配置证据模板、真实 Provider 正向与负向用例、备份恢复/回滚/告警/soak 记录模板，并用本地假配置验证脚本或命令不会泄密。真实 Key、域名、证书、白名单和 staging 操作继续列为外部阻塞，不擅自执行。
