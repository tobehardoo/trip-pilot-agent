# Phase F-0 · 系统资产清单（只读审计基线）

**审计基线：** HEAD `a56a769`（E-0 已提交）· 日期 2026-08-31 · 模式：全仓只读，零修改
**方法：** 仓库级盘点（git ls-files / 行数统计 / 垃圾扫描）+ 四路并行深挖审计（Python / Java / Web+构建 / 文档），全部结论附文件与行号证据；高影响结论已二次复核。

---

## 一、规模基线

| 维度 | 数值 |
|---|---|
| git 追踪文件总数 | **1037** |
| Python | 317 个 `.py`；agent-service src 145 文件 / 36.9k 行；tests 46.4k 行（测试比源码大 26%） |
| Java | 252 个 `.java`（travel-server main 181 / test 71）；main 约 20k 行；49 个 `.sql` |
| Web | 92 个 `.ts`（19,962 行）+ 40 个 `.vue`（9,484 行） |
| Markdown | 107 份（其中 docs/execution 61 份 / 3,753 行） |
| 被追踪的日志 | **6 个 `.run/*.log`**（约 51KB） |
| 被追踪的二进制/个人文档 | 3 pdf + 2 docx + 3 png（均在 `output/resume/`） |

## 二、顶层结构

```
apps/
  agent-service/   Python：FastAPI + AMQP worker（trip_agent 14 个包）
  travel-server/   Java：Spring Boot 3.5.4 / Java 21（tobehardoo.trippilot）
  web/             Vue3 + TS + pnpm（vue-router / Pinia / Vitest / Playwright）
contracts/         fixtures/（61 个）+ messaging/（36 个）— 跨语言契约唯一来源
docs/              adr / architecture / audit / development / execution / operations / product
infra/             docker/（postgres）+ monitoring/（prometheus）
knowledge/         产品知识源（7 个追踪文件，compose.prod knowledge-init 消费）— 保留
scripts/           14 个根脚本 + acceptance/ + tests/
compose.yaml · compose.prod.yaml · pom.xml（根 reactor 仅聚合 travel-server）
```

Python 包地图（trip_agent）：worker(4576 行) · guide_intelligence(5557) · agent(3935) · acquisition(3852) · planning(3700) · feasibility(3575) · infrastructure(3010) · providers(2350) · dialog(1669) · retrieval(1415) · evaluation(1386) · application(623) · domain(457) · routes(398) · places(193) · workflow(122)。

## 三、垃圾清单（Repository 层面）

### 3.1 被 git 追踪的运行时垃圾（确凿）
- `.run/agent-service.log`、`.run/agent-worker.log`、`.run/travel-server.log`、`.run/web-dev.log`、`.run/web.log`、`.run/worker.log` — 6 个开发日志，`.gitignore` 未覆盖 `.run/`。
- `.run/start-agent-api.sh` — 本地启动脚本。
- `.zcode/plans/plan-sess_30cb2b1d-….md` — AI Agent 会话残留（`.gitignore` 已列 `.omo/ .serena/ .workbuddy/`，漏了 `.zcode/`）。
- `output/resume/`（12 个追踪文件：简历、面试故事库、STAR 提炼、2 docx、2 pdf、2 png、审计与重设计报告）+ `output/TripPilot-简历审计与重设计报告.md` — **个人求职材料，非项目资产**。
- 处置方向：全部 `git rm --cached` + 补 `.gitignore`（`.run/`、`.zcode/`、`output/` 全目录）；`output/resume` 内容本地保留、移出仓库。

### 3.2 未追踪的本地垃圾（无 git 动作，仅记录）
- `apps/agent-service/.tmp/`（calibrate_pace.py、probe_routes.py 一次性实验 + pytest-fresh）— 已被 .gitignore 覆盖。
- `scripts/__pycache__/b15_user_flow.cpython-313.pyc` — 源文件已删除的孤儿字节码。
- `output/audit/*.log`、`test-results/`、`.pytest_cache/`、`.ruff_cache/` — 已被 .gitignore 覆盖。
- `apps/travel-server/contracts/messaging/` — **空目录树**（文件已删只剩壳，真契约在根 `/contracts`）；本地清理即可（git 不追踪空目录）。
- `.codegraph`（符号链接）、`.idea/` — IDE/工具状态，未追踪。

### 3.3 一次性脚本与历史产物（scripts/）
| 对象 | 判定 | 证据 |
|---|---|---|
| `validate_staging_env.py` + `scripts/tests/*` | **保留**（CI 依赖） | `.github/workflows/ci.yml:63,176,178` |
| `check_markdown_links.py` | **保留**（CI 依赖） | ci.yml:178 |
| `acceptance/b14/b14lib.py` | **保留** | `scripts/tests/test_b14_db_helper.py:25`、`test_b14_docker_helper.py:20` import，CI 每次运行 |
| `acceptance/b14/matrix_a/b/fault/param/real.py` + `results-*.json`(5) | **归档/删除** | 0 处 CI/docs/README 引用，一次性验收批次产物 |
| `simulate_planning_v1.py` | **删除候选** | 被 v2 取代（audit/3.0 §4 已证）；v2 保留（多份 execution 记录仍在用） |
| `reproduce_guangzhou.py` | **删除候选** | B8-2 一次性复现脚本 |
| `deadcode_audit.py` | **删除候选** | 自述"只报告不修改"的一次性审计 |
| `e2e-10-scenarios.sh` | **删除候选** | V2.0 批次一次性 bash |
| `multi_city_test.py` | **删除候选** | 一次性多城市验证 |
| `smoke_test.py` / `golden_scenarios_http.py` | **需确认** | 手动链路工具，硬编码 `:8081`，0 文档引用 |
| `postgres_backup.py` | **需确认** | 唯一运维备份工具，0 引用但有持续价值 |
| `check_compose_defaults.py` | **需确认** | B12 守卫，全仓 0 引用 |

### 3.4 死依赖（确凿，已复核）
- `ortools==9.14.6206`（pyproject.toml:12）— `apps/agent-service/src` 全量 grep **0 命中**；但根 README 等 5 份文档宣称 "OR-Tools 求解"，属文档失实而非依赖有效。
- `framer-motion`、`radix-vue`、`class-variance-authority`（package.json:16/18/22）— src/tests/e2e 全量 0 import。

## 四、大文件清单（按行数，含职责密度判定）

| 文件 | 行数 | 职责数 | 判定 |
|---|---|---|---|
| Python `infrastructure/amap/planning_provider.py` | 2455 | ~6（POI 收集/日发射/餐解析/锚点/路线交通/修复） | **拆分** |
| Java `ItineraryService.java` | 2044 | 4（读映射/用户编辑引擎/事件版本工厂/15+ record） | **拆分** |
| Python `worker/contracts.py` | 1860 | 1 职责跨 8 代事件 | **拆分**（commands / planning_events / agent_events），旧代类隔离后删 |
| Web `tests/App.test.ts` | 3112 | 56 tests / 2 describe | **拆分** + 提公共 fixture |
| Web `TripDetail.vue` | 1581 | ~45 props，宿主 12 子面板 | **拆分** |
| Web `TripWorkspace.vue` | 1445 | ~8（认证/装载/攻略导入/规划 SSE/视图分发） | **拆分**（composables） |
| Python `dialog/service.py` | 1205 | 3（解析归一/渲染/编排） | **拆分**（解析器簇独立） |
| Python `worker/amqp.py` | 1076 | 4（settings/provider 工厂/投递/消费循环） | **拆分**（settings+工厂移出） |
| Python `planning/daily_schedule.py` | 1075 | 1 | **保留** |
| Java `PlanningTaskService.java` | 1051 | 5 类命令+payload | 可选（拆 payload 构造） |
| Java `PlanningCompletedEventParser.java` | 1004 | 2（类型校验+6 域语义校验）+ **~200 行死分支** | 删死分支后合并校验核心 |
| Python `acquisition/repository.py` | 984 | 1 | **保留** |
| Python `guide_intelligence/trusted_facts.py` | 917 | 4（Normalizer/Extractor/Validator/Merger） | **拆分** |
| Python `agent/tools.py` 850 / `agent/graph.py` 800 | — | 工具簇 / 双 decider+loop | 可选（E 系列刚稳定，非本轮重点） |
| 大但内聚保留：`GuideImportService` 721 · `TripService` 702 · `ItineraryVersionService` 608 · `PlanningCompletionService` 554 · `ItineraryMapper` 552 | | | **保留** |

## 五、概念重复清单

### 5.1 Python（确凿）
1. provider 模式解析 **3 份**：`agent/tool_capabilities.py:49-60`、`places/api.py:77-86`、`worker/amqp.py:370-380` → 合并一处。
2. `STRUCTURED_MODEL_*` env 读取 **4 份**：`dialog/extractor.py:187-196`、`guide_intelligence/ocr.py:461-463`、`guide_intelligence/structured_model.py:210-225`、`agent/factory.py:62-85` → 合并。
3. 中文日期解析（`M月D日`+跨年滚动）**2 份**：`agent/itinerary_builder.py:41-80` vs `dialog/service.py:285-313` → 合并入 domain。
4. `failure_policy.py:41-52` 手工重列 `providers/errors.py` 的 transient 类别码 → 改为派生。
5. 兼容再导出块：`worker/processor.py:28-51`（15+ 别名，生产只取 3 个）、`amap/planning_provider.py:47-57`（8 个 noqa 再导出，0 消费者）→ 删除。
6. 仅测试引用：`StaticUrlDiscoverer`（acquisition/discovery.py）、`DurationProfile` 别名（planning/poi_quality.py:238）→ 删除。
7. 废弃开关 `DEMO_MODE`：`routes/api.py:127` 注释自述 deprecated，仍散布 5 处（tool_capabilities:55、places/api:81、amqp:315/347-354）→ 删除（先确认部署环境不再设置）。
8. **刻意双轨（保留）**：Demo vs Real planning provider（`PROVIDER_MODE` 三态门控 + `ProviderFallbackPolicy`）；`AskingDecider` vs `StructuredOutputDecider`（无模型配置时的确定性兜底）；Demo/Real map·route providers。

### 5.2 Java（确凿）
1. **双事件解析器复制**：`PlanningReviewRequiredEventParser`(495) ≈ `PlanningCompletedEventParser` 的 itinerary/knowledge/transit/fingerprint 校验段；且**已分叉**——`isPersistableMoney` completed:994 检查 signum≥0，review:481 只查 scale（review 侧会放过负数金额）。→ 抽共享 ItineraryContractValidator（顺带修 bug）。
2. **4 个事件服务同一骨架**：Completion/Review/Failure/Progress Service 各自重写 findCompletionContext→identity 校验→幂等→状态门→stale baseline。→ 抽公共终态转换组件。
3. `writeJson` **11 个类逐字重复**；`requireOne` ≥6 处；`rejected()` 4 处。→ 公共支持类。
4. **两套 SSE 栈**：`AgentDialogEventHub`(145) ≈ `PlanningTaskEventHub`(151) + 两套 StreamService/EventCreated/Handler。→ 合并为按 UUID 泛化的 Hub。
5. 4 个近同形异常类（Agent/Planning × Rejected/Contract）→ 合并为 2 个。
6. **11 个空壳包**（仅 package-info）：`domain/`、`application/{identity,knowledge}/`、`infrastructure/`、`infrastructure/integration/`、`infrastructure/persistence/{identity,itinerary,knowledge,mq,planning,trip}/` — 未完成的 DDD 重组遗迹。→ 删除。

### 5.3 Web（确凿）
1. **双路由系统**：`lib/routes.ts` 手写 `parseRoute`(:11) 仅 `tests/routes.test.ts` 消费；真实路由是 vue-router（router/index.ts）。→ 删 parseRoute，路径助手并入 router 模块。
2. 死文件（已复核 0 引用）：`components/agent-workspace/ConstraintPanel.vue`(71，被 planning-session/ConstraintBoard.vue 取代)、`components/ui/Dialog.vue`(67)、`lib/supported-cities.ts`(36)。→ 删除。
3. **测试双位置**：`GuideIntelligencePanel.test.ts`（src 192 vs tests 379）、`PlanEvaluationPanel.test.ts`（55 vs 173）、`TransitLegControl.test.ts`（94 vs 135）。→ 统一到 tests/。
4. 测试基建重复：App.test.ts:10-20 与 TripWorkspaceActions.test.ts:16-24 逐字相同 render 包装；`authResponse`/`tripResponse` fixture 多处重定义。→ 抽 `tests/harness.ts`。
5. coverage 白名单与注释矛盾：`vite.config.ts` include 漏掉 `planning-session/*`、`useAgentWorkspace.ts`、`lib/agent-*.ts`、`SharedItineraryPage.vue` 等。→ 修正。

### 5.4 测试重复（三端共有，减肥主战场）
- Python：`_poi(` 工厂 **17 个文件**各写一份；`_command(` 12 份；`_itinerary(` 9 份；fake provider 散布 15 文件；`_confirmed_slots` 4 份。已有先例 `tests/plan_evaluation_support.py` + `tests/feasibility/conftest.py` 被 10+ 文件复用，证明抽公共 `tests/support` 可行。
- Java：`registerAndGetAccessToken` ×14、`bearer()` ×19、`json(MvcResult)` ×19、`createTrip` ×10。→ 下沉 support（并入 PostgresIntegrationTest 体系）。
- `guide-city-intelligence-real-response.json` 在 `contracts/fixtures/` 与 `src/test/resources/fixtures/` 两份字节相同。→ 保留一份。

## 六、历史遗留清单

### 6.1 事件代际（跨 Python/Java/contracts 三处联动，处置需同批）
- 生产活跃集：**PLANNING_COMPLETED v9/v10/v11**（Java parser 门 :98/:380 只放行这三代）、REVIEW_REQUIRED v1/v2、PROGRESS v1/v2、FAILED v1/v2（双版本为有意只读兼容）、AGENT_* v1、city-intelligence refresh v1。
- Python 旧代事件类（仅测试引用）：`PlanningCompletedEvent` v6/8（contracts.py:1163）、`PlanningCompletedPayload`(:1127)、V9(:1178/1221)、`PlanningCompletedEventV10`(:1259)、`PlanningReviewRequiredEvent` v1(:1342)、`PlanningFailedEventV1/PayloadV1`(:1393/1401)。
- Java `PlanningCompletedEventParser` 内 **~200 行 v1–v8 死分支**（:166/:253/:296/:393/:739/:773/:871/:891/:901-906/:937），测试对 v6 fixture 只断言"被拒"。
- `contracts/messaging/`：v7 README 自述 **ABANDONED**；completed v4–v8 对 Java 全部 fail-closed。→ 移入 `legacy/`（注意 `test_messaging_contract_schemas.py:465` 以 glob 扫全部顶层 schema，移动需同步改测试；`legacy/` 非零消费——`test_planning_worker.py:388` 读 legacy/v3 做负向测试）。
- `contracts/fixtures/` 61 个**全部有消费者**（双端契约测试共读），保留；唯 `planning-candidate-validation-command-v1/v2` 并存，需确认生产命令版本后合并。
- 其他小遗留：`evaluation/models.py:162,181-184` schemaVersion 1 分支（evaluator 只产 2）；`feasibility/models.py:356-362` `_LEGACY_VALIDATOR_VERSIONS`（现行只发 v5）；`dialog/store.py:1-7` 过时注释；阶段标签渗入 docstring（P1.6/P2.2/B5/B13_FIX 等）。

### 6.2 架构倒置（记录，非本轮必改）
- `providers/map.py:22` 反向依赖 `infrastructure.amap.errors`；`domain/planning/protocols.py:15-23` 依赖 `worker.contracts`，与 domain "无基础设施依赖" 自述矛盾。

### 6.3 构建/部署问题
- `compose.yaml` 存废：与 compose.prod 重复定义 postgres/redis/rabbitmq；全部运行文档只用 compose.prod；唯一消费者 ci.yml:100 `config --quiet`；且其 postgres build context 与 Dockerfile 的 `COPY infra/docker/postgres/init.sql` 路径不匹配（疑似本地构建即失败）。→ 确认后废弃或修复。
- `.dockerignore` 仅 8 行，而 compose.prod 全部镜像以仓库根为 context（compose.prod.yaml:6-8,52-54）——未排除 docs/ output/ scripts/ .run/ test-results/（`knowledge/` 必须保留，:195-196 knowledge-init 挂载）。
- Web 手写跨语言类型副本（`lib/feasibility.ts:3` 自述 mirror of Java FeasibilityReport；api.ts ~1300 行 DTO）：收敛需引入 codegen，**超出本轮范围**，保留+标注。

## 七、文档资产盘点（107 份，处置建议详见收敛方案 §7）

要点：
- **失实内容已验证**：5 处宣称 "OR-Tools 求解"（src 0 命中）；`AGENT_THINKING/AGENT_TOOL/AGENT_QUESTION` 死事件名（实际是 AGENT_STEP/ASK_USER/COMPLETED/RUN_FINISHED）；"规划中" 的 AGENT_START/RESUME、agent_run/agent_step、user_travel_profile 均已落地；"8 工具" 实为 9 个；事件契约队列清单缺 7 个队列（实有 9 个，RabbitMessagingConfiguration.java:22-30）。
- docs/execution 61 份中约 30 份（2026-08-29 批次 25 份 + 08-30 发布报告 + 08-31-phase-b 4 份）已被后续阶段整体取代。
- 16 主题知识库缺口中 8 个主题**无活文档**：Agent 运行、Planning 运行、Agent–Planner 协作、数据流、状态流、Constraint 模型、Failure-Recovery 模型、代码规范。
