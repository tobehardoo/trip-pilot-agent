# Phase F · 减负与收敛方案（F-1 → F-7 逐刀计划）

**依据：** [01-system-inventory.md](./01-system-inventory.md)（基线 `a56a769`，全部条目附证据）
**总目标：** 代码真实结构 = 架构设计 = 项目概念 = 测试验证 = Docs 文档。
**纪律：** 每一刀独立 commit、独立验收；禁止一次全仓重构；禁止顺手改 Scope；禁止为减行数加抽象；禁止为修测试改业务语义。

---

## 〇、总体切分与顺序

| 刀 | 内容 | 风险 | 预计规模 |
|---|---|---|---|
| F-1 | Repository 减负（垃圾/死依赖/死代码/一次性脚本） | 低 | 2–3 个独立 commit（按 1a/1b/1c 拆分） |
| F-2 | 概念统一 + 重复合并（Python/Java/Web 各自） | 中 | 每端一刀，独立 commit |
| F-3 | 架构职责收敛（依赖方向、Worker 边界、事件代际终结） | 中 | 2 个 commit |
| F-4 | 大文件与测试基建治理 | 中高 | 每文件/每端一刀 |
| F-5 | 风格统一（含解释性内容中文化） | 低 | 受限扩散，随刀进行 |
| F-6 | 全量回归 + 架构级检查 | — | 验证刀，不改代码 |
| F-7 | Docs Final Convergence（最后一步） | 低 | 文档刀 |

顺序依据：先删无消费者之物（风险最低、收益立现），再合并重复（概念收敛），再动结构（拆分），最后以回归锁定、以文档收口。事件代际清理横跨 Python/Java/contracts 三处，必须**同一刀内同批处置**（见 F-3c），否则跨语言契约测试会半绿。

---

## 一、F-1 · Repository 减负（三个子刀）

### F-1a 运行时垃圾出仓 + .gitignore 补全
1. `git rm --cached` 全部 `.run/*`（6 log + start-agent-api.sh）与 `.zcode/plans/*`；`.gitignore` 增加 `.run/`、`.zcode/`。
   ⚠ 本项目既有约定：`.run/web.log` 与 `docs/execution/2026-08-31-phase-b/*` 不随任何提交入库 —— 本刀把它们彻底变成未追踪状态后，该约定自然退役，需在验收记录中注明。
2. `git rm` 全部 `output/`（13 个追踪文件：简历/面试材料属个人文档，非项目资产）；`.gitignore` 将现有 `output/*.log` 等零散规则合并为 `output/` 全目录。本地文件保留不删。
3. 本地清理（无 git 动作）：`apps/agent-service/.tmp/`、`scripts/__pycache__/` 孤儿 pyc、`apps/travel-server/contracts/` 空目录树、`output/audit/*.log`、`test-results/`。
- 验证：`git status --porcelain` 只剩预期项；`git check-ignore` 抽查；现有测试不受影响（这批文件无消费者，已逐一核引用）。

### F-1b 死依赖 + 死代码（纯删）
1. 删 `ortools`（pyproject.toml:12；src 0 import 已复核）+ 删 `framer-motion`/`radix-vue`/`class-variance-authority`（package.json:16/18/22；0 import）。注意：ortools 删除会同时消灭 "OR-Tools 求解" 的文档宣称基础，文档修正留到 F-7。
2. Python 死代码：`worker/processor.py:28-51` 兼容再导出块（测试改为直连真模块）、`amap/planning_provider.py:47-57` 再导出、`StaticUrlDiscoverer`、`DurationProfile` 别名、废弃开关 `DEMO_MODE`（5 处，先 `grep` compose/部署确认无人设置）。
3. Java 死代码：`PlanningCompletedEventParser` ~200 行 v1–v8 死分支（入口门只放行 v9/10/11，:98/:380；测试对 v6 fixture 只断言"被拒"，删除不伤断言）；11 个空壳包（仅 package-info）。
4. Web 死代码：`ConstraintPanel.vue`、`ui/Dialog.vue`、`lib/supported-cities.ts`、`lib/routes.ts` 的 `parseRoute`（连带 routes.test.ts 相应改写）。
- 验证：三端测试套件全绿（命令见 F-6 清单）+ 全仓 grep 确认无残留引用。

### F-1c 一次性脚本与历史产物
1. 删：`simulate_planning_v1.py`、`reproduce_guangzhou.py`、`deadcode_audit.py`、`e2e-10-scenarios.sh`、`multi_city_test.py`（均 0 CI/docs/README 消费者，证据见清单 §3.3）。
2. 归档（移入 `docs/archive/acceptance-b14/` 或删，待批准时二选一）：`acceptance/b14/matrix_*.py` + `results-*.json`（`b14lib.py` 保留——被 `scripts/tests/*` import，CI 依赖）。
3. 需批准时确认：`smoke_test.py`、`golden_scenarios_http.py`、`postgres_backup.py`、`check_compose_defaults.py`（0 文档引用，但可能有手动运维价值）。
4. `contracts/messaging/`：completed v4–v8 schema 移入 `legacy/`，同步修改 `test_messaging_contract_schemas.py:465` 的 glob 范围与受影响断言（该测试扫全部顶层 schema，必须同批改）。

## 二、F-2 · 概念统一与重复合并

### F-2a Canonical Vocabulary（规范词表，全阶段共用）
| 概念 | Canonical | 判词 |
|---|---|---|
| Agent | `AgentLoop`（decide→act→finish 有界循环） | 唯一；不存在第二个 agent 拓扑 |
| Decider | `AskingDecider`（确定性默认）/ `StructuredOutputDecider`（可选 LLM 兜底） | 双轨刻意保留（无模型配置兜底） |
| Tool / Observation | `ToolRegistry` + `ToolObservation` | 唯一；9 个声明式工具 |
| Evaluation | `plan_evaluation`（state 字段） | E-0 判定为 PASSIVE MEMORY；E-1 落地前保持现状，不得提前动 |
| Feasibility | 结构门 `StructuralFeasibilityGate`（发射仲裁）+ 硬校验 `run_validation`（管线内） | 两者并存但职责不同；S2 分歧由 E-1 裁决，不在 F 阶段动 |
| Candidate / Itinerary | 管线候选 → `Itinerary` wire 契约 | 唯一 |
| Constraint | `ConstraintSlots`（槽位五态）+ `TripConstraints`（wire） | 两个层次，非重复；用户已确认约束不可变 |
| Event | 活跃集 = completed v9-11 / review v1-2 / progress v1-2 / failed v1-2 / AGENT_* v1 | 其余代际在 F-1c/F-3c 终结 |
| Recovery | `failure_policy`（D-1 分类 + D-2 重试 + D-4 重复判定） | 唯一 |
| Provider | map/route/planning 三类 provider；demo/real 双轨刻意（`PROVIDER_MODE` 门控 + `ProviderFallbackPolicy`） | 保留 |
| Builder | `DemoItineraryBuilder` / `RealItineraryBuilder`（共享 `build_demo_command`） | 双轨刻意；可合并为一个类+可选 summary，列为可选项 |
| Planner | 确定性规划管线（candidates→daily_schedule→feasibility），**禁止 LLM 化** | 唯一 |

### F-2b Python 合并（一刀）
- provider 模式解析 3 处 → 1 处（建议落 `application/settings` 或现有 WorkerSettings 同层）；`STRUCTURED_MODEL_*` 读取 4 处 → 1 处；中文日期解析 2 处 → 1 处（入 domain）；`failure_policy._TRANSIENT_CODES` 改为从 `providers/errors.py` 派生。
- 每处合并单独可验证：合并前后测试全绿、行为不变。

### F-2c Java 合并（一刀）
- 双事件解析器校验核心抽共享 `ItineraryContractValidator`（**顺带修复 `isPersistableMoney` 分叉：review 侧放过负数金额，:481 vs completed :994**——这是审计发现的真实缺陷，修复需单独测试用例锁定）。
- 4 个事件服务公共骨架抽组件；`writeJson`×11 / `requireOne`×6 / `rejected()`×4 入公共支持类；双 SSE Hub 合并为按 UUID 泛化的单一 Hub；4 个异常类并为 2 个。
- 每项独立可回归；Hub 合并必须同时覆盖 agent-dialog 与 planning 两条 SSE 的既有测试。

### F-2d Web 合并（一刀）
- 测试双位置三组统一到 `tests/`（内容互补，需合并而非简单移动）；抽 `tests/harness.ts` + fixtures 模块（App.test.ts:10-20 与 TripWorkspaceActions.test.ts:16-24 的重复 render 包装、authResponse/tripResponse fixture）。
- `vite.config.ts` coverage include 修正为真实集合。

## 三、F-3 · 架构职责收敛

目标架构（最终口径，与现状基本一致，收敛=消除双轨歧义而非重画）：

```
Web (Vue3)
 ↓ HTTP/SSE（唯一客户端 lib/api.ts）
Java travel-server（业务/持久化/事务边界，outbox 发命令）
 ↓ RabbitMQ 命令/事件（9 队列，contracts/messaging 为唯一契约源）
Python worker / agent runtime（worker/amqp 消费 + FastAPI 对话面）
 ↓ 工具调用
确定性规划管线（candidates → daily_schedule → feasibility，非 LLM）
 ↓
PostgreSQL（Flyway V1–V42 不可删改）
```

- **F-3a Python 依赖方向**：修 `providers/map.py:22 → infrastructure.amap.errors` 的反向依赖（错误类型上提到 providers 层）；评估 `domain/planning/protocols.py → worker.contracts` 的解耦成本（可能需引入 domain 侧协议副本，若成本>收益则记录豁免）。
- **F-3b Worker 边界**：`worker/amqp.py`(1076) 的 WorkerSettings+provider 工厂移出，amqp.py 只剩消费/投递（与 F-4 拆分协同，可并刀）。
- **F-3c 事件代际终结（跨语言同批）**：Python 旧代事件类（清单 §6.1 所列 6 组）删除 + `contracts/messaging` v4-v8 入 legacy + Java 死分支（若 F-1b 未删则此刀删）+ 契约测试同步改写，**一个 commit 完成**，避免半绿窗口。
- **F-3d compose 收敛**：`compose.yaml` 与 `compose.prod.yaml` 二选一——全部文档只引用 prod，ci.yml:100 仅 `config --quiet`；且 compose.yaml 的 postgres build context 与 Dockerfile COPY 路径不匹配。建议：废弃 compose.yaml（CI 改指向 prod 或新增最小 dev overlay），待批准定夺。

## 四、F-4 · 大文件与测试基建治理

拆分顺序（每项一刀，先测试后文档）：
1. `infrastructure/amap/planning_provider.py` 2455 → 按职责抽：日发射、餐解析、锚点解析、路线交通推荐（planning/ 包已有先例）。
2. `worker/contracts.py` 1860 → commands / planning_events / agent_events 三模块（旧代类此时已删，自然干净）。
3. `ItineraryService.java` 2044 → 编辑引擎 + 版本工厂分离。
4. `TripWorkspace.vue` 1445 → composables（useTripLoader / usePlanningStream / useGuideImport）；`TripDetail.vue` 1581 按面板宿主职责收敛。
5. `dialog/service.py` 1205 → 解析器簇独立模块；`trusted_facts.py` 917 → 四阶段拆。
6. `tests/App.test.ts` 3112 → describe-2 独立成文件 + 公共 fixture。
7. **测试基建三端统一**：Python 抽 `tests/support`（`_poi`×17、`_command`×12、`_itinerary`×9、fake provider×15、`_confirmed_slots`×4 → 公共工厂，沿用 `plan_evaluation_support.py` 已验证模式）；Java HTTP helper 下沉 support（registerAndGetAccessToken×14、bearer×19、json×19、createTrip×10）；Web harness（F-2d 已立）。`guide-city-intelligence-real-response.json` 双份 fixture 合一。
- 原则：拆分不改行为；每刀以该端全量测试为验收；不按行数机械拆（`daily_schedule.py`、`acquisition/repository.py`、`PlanningTaskService` 等保持）。

## 五、F-5 · 风格统一

- Python：既有 ruff 配置为准；补充统一 docstring 约定。
- **解释性内容中文化**（用户规范 §八）：注释、docstring、错误说明、核心日志改中文；**代码符号保持英文原名**（AgentState、FailureKind 等）；第三方术语保留。执行策略：**受限扩散** —— 只在本阶段已被修改的文件上做注释中文化，不做全仓注释重写（避免制造巨量无语义 diff）。
- Java：消除文件中部全限定类名（PlanningCompletionService:33-35）、`parseQuality` 吞异常小修；日志保持 SLF4J+PlanningLogContext。
- Web：统一 `it`/`test` 风格（随 F-4 拆分顺带）。
- 现状备注：Python 侧"英文 docstring + 中文用户文案"分工本就清晰，本刀目标是消除中英混杂的少数内联注释（如 graph.py:93-94/182、contracts.py:1760），不是推倒重来。

## 六、F-6 · 全量回归 + 架构级检查（验证刀）

回归命令（本项目验证环境约定：venv python、独立 `--basetemp`、`PYTHONIOENCODING=utf-8`）：
- Python：`apps/agent-service/.venv/Scripts/python.exe -m pytest --basetemp=<独立目录>`（现有 ~609 个测试文件规模）+ `ruff check`。
- Java：`mvn -q verify`（travel-server；CI 同口径）。
- Web：`pnpm vitest run` + `vue-tsc`/tsc + `pnpm build`；e2e 按 CI 口径（`qa-real-chain` 有意排除）。
- 基础设施：`docker compose -f compose.prod.yaml config`（F-3d 落地后含新口径）；CI workflow 全量触发一次。
- Simulation/契约：`simulate_planning_v2.py` 黄金场景 + 双端契约测试（fixtures 共读链不断）。

架构级检查清单：死 import（ruff/vulture 级）、死代码残留、重复入口、重复概念（对照 F-2a 词表逐一过）、旧目录/旧配置、无消费者 abstraction、`.gitignore` 与追踪集一致（`git ls-files -ci --exclude-standard` 应为空）。

## 七、F-7 · Docs Final Convergence（最后一刀，代码稳定后执行）

处置总表（逐份明细在文档审计报告，此处为汇总）：

| 组 | 处置 |
|---|---|
| `docs/execution/` 61 份 | **整体归档**：移入 `docs/archive/execution/` 保持原结构；其中约 30 份已被后续阶段整体取代（2026-08-29 批次 25 份、08-30 发布报告、08-31-phase-b 4 份——phase-b 3 个未提交文件建议直接删除：冻结后 0 代码产出，内容与 Phase-C0/acceptance-summary 重复）；Phase-D0 的 02/03 与 Phase-E0 保留为"蒸馏原料"标记 |
| `docs/audit/3.0/` 10 份 | 归档（基线 `6351349` 快照，证据密度最高的历史审计，以 FINAL-AUDIT-REPORT 为入口） |
| `docs/architecture/` | 系统架构.md、事件契约.md **UPDATE 为唯一活文档**（修 OR-Tools 失实、补 9 队列、状态更新）；ux-3.0、planning-intelligence-v3 **KEEP**；ux-2.0、planning-intelligence-v1/v2、Agent化升级技术设计方案 **ARCHIVE** |
| `docs/adr/` | KEEP 2 份（传输边界、Provider 降级）；UPDATE 2 份（编排层状态、评估策略版本）+ 索引补登 ADR-016 |
| `docs/development/` + `operations/` + `product/` | 全部 UPDATE（刷新计数、去 OR-Tools、去"8 工具"）；本地运行指南 KEEP |
| `docs/README.md` | MERGE 入 index.md |
| 根 `README.md` | UPDATE（架构描述与测试计数） |

新建（8 个无活文档主题的缺口，原料已在执行文档中）：
1. Agent 运行模型（原料：Phase-C0 + ux-3.0）
2. Planning 运行模型（原料：planning-intelligence-v3）
3. Agent–Planner 协作与信任边界
4. 数据流 5. 状态流（任务状态机/槽位五态/run 生命周期）
6. Constraint 模型
7. Failure-Recovery 模型（原料：Phase-D0/D2/D4/DFinal）
8. 代码规范（含中文注释规范，配合 F-5 成文）

文档纪律：最终文档不得描述已不存在的类/文件/事件/状态；发现过时即更新或删除，禁止追加"注意：旧版本……"。

## 八、STOP 条件与风险边界

出现任一情况立即停刀上报：
1. 任一删除的引用审计出现反例（找到未记录的生产消费者）。
2. 契约测试在事件代际清理中出现跨语言不一致的半绿状态且无法单 commit 收敛。
3. `compose.yaml` 废弃影响 CI 未预期路径。
4. 需要修改用户已确认约束语义、wire 契约、DB schema（Flyway 历史）——均属禁区。
5. `output/resume/` 出仓：个人材料，执行前需单独确认（本地保留、仅移出 git）。

**禁止清单（沿用项目纪律）**：不 `git add .`/-A；不提交 `.run/` 与 phase-b 文件（F-1a 后该约定自然退役）；不为减行数引入新抽象；不把确定性规划器 LLM 化；不动 E-0/E-1 边界（plan_evaluation 归 E 阶段）；每刀独立验收。

## 九、预期量化收益（供最终 Complexity Reduction Summary 对照）

- 追踪文件：1037 → 约 -25（垃圾出仓）；`.run`/`output`/`.zcode` 全部出追踪。
- Python 死代码：旧代事件类 + 再导出块 + 死分支约数百行；测试侧 `tests/support` 抽取预计削减数千行重复（17+12+9+15+4 处工厂的重复）。
- Java：死分支 ~200 行、11 空壳包、双解析器重复 ~150-200 行、writeJson×11 等 helper 重复。
- Web：3 死文件 + 死依赖 3 个 + 双位置测试合一。
- 大文件：2455/2044/1860/3112 四个最大文件全部降到单一职责尺度。
- 文档：主入口从 107 份收敛到 ~30 份活文档 + 归档区；16 主题全覆盖。

---

**本方案为 F-0 审计产出，等待批准后自 F-1a 开始，逐刀执行、逐刀验收。**
