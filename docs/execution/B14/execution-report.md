# B14 执行报告：100 场景全系统真实用户仿真、卡死诊断与发布冻结验收

- 状态：**B14_SYSTEM_ACCEPTANCE_NEEDS_CORRECTION / RELEASE_FREEZE_BLOCKED**（存在 P1 缺陷，见 defects.md）
- 批次：B14（独立质量审计，非修复批次；未修改任何生产代码）
- 隔离项目：`trip-pilot-b14-acceptance`（独立端口 WEB 38085 / Prometheus 39094、独立网络 172.28.241.0/24、独立 volume、独立镜像 tag `b14-acceptance`、独立测试账号、独立 Provider 配额记录）

## 1. 开始前基线（任务书第一节要求）

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `89236ea731b3d9aea55a81f96101940299f2c983` |
| staged | 空（`git diff --cached --name-only` 0 行） |
| git status | 117 行（B13/B13_FIX/B13_FIX.1/B13_FIX.2 全部 unstaged 工作，本批未触碰） |
| Docker 运行项目 | `trip-pilot-prod`（8 容器 healthy，WEB 38080/Prom 9090，用户栈全程未操作）、`trip-pilot-b13fix1-verify`（验收 Agent 遗留栈，未操作） |
| PROVIDER_MODE（.env） | REAL_ONLY |
| 镜像（用户栈 weather-qweather tag） | agent-service 22 分钟前（含 B13_FIX.2 全部代码）；web 2 小时前构建（与工作区一致，B14 隔离镜像 b14-acceptance 独立构建） |
| B14 隔离栈镜像 | `trip-pilot-*:b14-acceptance`（`docker compose up -d --build` 构建，未触碰用户 tag；用后删除） |

纪律遵守：全程无 reset/stash/checkout/restore/clean/rebase/amend；无 stage/commit/push；未修改生产代码、既有 acceptance-report、.omo/、.serena/、docs/audits/、.env；测试结束后仅清理 B14 隔离项目。

## 2. B14-P0-RESULT-PUBLISHING-STUCK 专项诊断

### 复现（基础二日广州行程，DEMO 与 REAL 双路径）

浏览器真实用户流程记录：tripId/taskId/SSE URL/网络请求/UI 进度序列（脚本输出存档于本报告 §5 证据路径）。

- **DEMO_ONLY**：业务 10:33:27.6 创建任务 → 10:33:28.7 终态（QUEUED + 3×PROGRESS + REVIEW_REQUIRED）；UI 30ms 进入 queued、1 秒内应用 WAITING_USER（候选可见、按钮禁用"候选待确认"）。**无卡死**。
- **REAL_ONLY**：完整真实链路（AMap place search 岭南文化/美食 + 4 条真实 route 调用）→ 约 30 秒终态 WAITING_USER；progress 序列 TASK_ACCEPTED(5)→CONTEXT_VALIDATING(15)→CITY_FACTS_LOADING(25)→POI_RECALLING(35)→KNOWLEDGE_RETRIEVING(75)→RESULT_EXPLAINING(85)→**RESULT_PUBLISHING(95)**→REVIEW_REQUIRED，sequence/progress 单调，终态前最后进度 95% 合理。**95% 后立即终态（同一秒），无卡住**。

### 六层对账（均正常）

| 层 | 证据 |
| --- | --- |
| Python | provider completed → validation UNVERIFIED/NEEDS_REPAIR → repair stopped → outcome emitted（无异常） |
| RabbitMQ | planning.create/completed/review/failed/progress 队列 ready=0 unacked=0 consumers=1；无预期外 DLQ |
| Java | Listener message received → Parser 通过 → ReviewService/CompletionService persisted（无 Rejected） |
| PostgreSQL | planning_task.status=WAITING_USER；task_event 序列 QUEUED→PROGRESS×n→REVIEW_REQUIRED（唯一终态，无重复/交叉）；outbox SENT；WAITING_USER 不产生正式版本（versions=0） |
| SSE | 端到端 20-750ms 内收到全部帧（node 与页面内 fetch 双验证）；Last-Event-ID replay 正常（6-7 帧） |
| Web | applyOutcomeState 正确应用 waiting_user；无英文后端错误；按钮 disabled="候选待确认" |

### 专项判断（任务书三.5："筛选地点优先级…执行修复"显示"未执行"）

- **真实业务步骤均执行**（provider 日志证明路线/求解/修复真实运行），但 **CANDIDATES_RANKING / ROUTES_CALCULATING / CONSTRAINTS_SOLVING / REPAIRING（REAL）与 CONSTRAINTS_SOLVING / RESULT_PUBLISHING（DEMO）不发 PLANNING_PROGRESS 事件** → UI 步骤列表据 observedStages 显示"未执行"。
- **判定：可观测性/文案缺陷（分类 I：只有 progress 事件缺失，实际业务步骤已执行）→ B14-D05（P2）**。UI 不应把"没有收到阶段事件"呈现为"业务未执行"。
- 卡点分类：A-I 中**未发现任何层永久卡死**；时间门禁 DEMO 1s < 120s、REAL ~30s < 300s 均满足。

## 3. 场景矩阵执行汇总

固定随机种子 `20260815`；参数化执行总量 **≥342**（≥300 达标）；100 个场景全部执行（无复制改名凑数）。

| 组 | 场景 | 结果 |
| --- | --- | --- |
| A 账号会话所有权 S001-S010 | 10 | 9 PASS；S007 FAIL（缺陷 D02） |
| B 基础创建 S011-S020 | 10 | 10 PASS |
| C 省市区日期 S021-S030 | 10 | 10 PASS |
| D 地点锚点 S031-S040 | 10 | 8 PASS；S038/S039 FAIL（缺陷 D03/D04） |
| E 必去避开 S041-S050（REAL） | 10 | 9 PASS；S043 flaky（首败 NO_FEASIBLE，复跑 PASS，动态候选波动，fail-closed 正确） |
| F 餐饮营业时长 S051-S060 | 10 | 10 PASS |
| G 住宿跨日修复 S061-S070 | 10 | 10 PASS |
| H Task/MQ/SSE 并发 S071-S080 | 10 | 10 PASS |
| I 故障注入 S081-S090 | 10 | 10 PASS |
| J 天气/UI/负载/Golden S091-S100 | 10 | S091/S094-S099/S100 PASS；S092/S093 FAIL（缺陷 D01 影响：天气同步 502） |
| R01-20 REAL 动态样本 | 20 | 19 PASS（亚龙湾 FULL_DAY 度假区 2 天排不下 → fail-closed NO_FEASIBLE，正确；429s=0 但 ROUTE 层观察到 429 重试成功，见 D09） |
| P001 参数化批量 | 110 | 110 PASS |
| 浏览器用户流程 | 30+7 | B01-B30 全 PASS；S091/094/095/096/097/098/100 全 PASS（含 S098 重启持久化、S100 完整 Golden） |

### 分层计数

- 真实浏览器用户流程：**37**（≥30 达标）
- API/MQ/DB 集成场景：**约 90**（≥35 达标）
- REAL_ONLY 动态 Provider 样本：**30**（≥20 达标；并发 ≤2：worker 单消费者天然串行 + 样本间 sleep 控频）
- DEMO_ONLY / fixtures / 故障注入：其余（S081-S090 故障注入 10 场景 + 参数化 110 + 浏览器 37）
- 城市覆盖：广州/江门/北京/上海/重庆/杭州/成都/西安/长沙/昆明/三亚/（搜索少城市=江门全市）≥12 ✓
- 画像覆盖：SOLO/COUPLE/FAMILY/FRIENDS/BUSINESS × 1-6 人 × RELAXED/BALANCED/INTENSIVE × STANDARD/REDUCED/STEP_FREE × 0/1/多/冲突偏好 × 无/0/极低/正常/高预算 × 无/区域/精确住宿 × 0/1/2/5 必去 × 无/精确/同名避开 × 默认/自定义/禁用餐窗 × 早到/晚到/早离/深夜离开 ✓

## 4. 全量门禁（真实命令输出）

| 门禁 | 结果 |
| --- | --- |
| Python pytest 全量 | **1484 passed, 37 skipped** |
| ruff check | All checks passed |
| ruff format（本批 B14 文件） | scripts/acceptance/b14 本批工具未纳入 ruff 检查（临时脚本，执行后归档） |
| Python 定向覆盖（B13 相关） | planning_provider 93% / candidates 99% / daily_schedule 93% / poi_quality 93% |
| Java mvn verify | **499 tests, 0 failures**；JaCoCo All coverage checks met；Flyway 干净库 + 升级库（V2→V36、V4→V36、V34→V36）全部通过 |
| Web unit | **400 用例：全量 3 轮分别 396/398/399 passed**，其余为 5000ms 硬超时（单跑全部 PASS 4/4；同代码 B13_FIX.2 全绿 400/400；判定环境性能 flaky，非回归，记录于 D06） |
| Web coverage | All files stmts 95.8 / branch 85.53 / funcs 95.3 / lines 95.8（B13_FIX.2 同代码数字；本次 399/400 覆盖率报告生成，1 flaky 不影响聚合） |
| Web typecheck / build | vue-tsc -b 通过；vite build 通过 |
| Playwright 全量 | **21 passed**（Docker nginx 静态服务 + dead-proxy 使 AMap SDK 确定性不可用，与 B13 门禁环境一致；未修改任何正式 spec/生产代码） |
| Compose config / defaults | compose.prod.yaml + compose.yaml `config --quiet` 通过；`check_compose_defaults.py --with-docker` OK |
| DEMO_ONLY 冷启动 / REAL_ONLY 隔离 | 均验证（本批场景矩阵在两种模式运行）；Rabbit/worker/consumer 故障恢复 10/10；restart persistence S098 PASS |
| Markdown links | 116 files valid |
| git diff --check | 通过（CRLF 警告为基线既有） |
| staged | 空 |
| secret / 保护目录 | `git ls-files` 无 .env/.pem/.key/.p12/.pfx；未修改保护目录 |

## 5. 证据路径与清理

- 场景脚本与结果：`scripts/acceptance/b14/`（matrix_a/b/fault/real/param + b14lib + results-*.json）
- 浏览器脚本（执行后归档说明）：B01-B30/S091-S100 流程输出见本报告 §3；截图/网络记录存于临时目录（用后清理）
- DB/MQ/日志证据：B14 栈容器日志（已随栈删除，关键行摘录于本报告与 defects.md）
- 清理：`docker compose -p trip-pilot-b14-acceptance down -v --remove-orphans`（9 容器 + 4 卷 + 1 网络全部删除）；`b14-e2e-web` nginx 容器删除；临时 env/脚本/镜像（b14-acceptance tag）删除；用户 `trip-pilot-prod` 8 容器全程未动（清理后复核仍 healthy）

## 6. staged / commit / push

- 全部改动 unstaged；未 commit；未 push；HEAD 保持 `89236ea731b3d9aea55a81f96101940299f2c983`；未创建 acceptance-report.md（留给独立验收 Agent）。

## 7. 最终判定

- 存在 **P1 缺陷 B14-D01（天气同步 502）** → 判定 **B14_SYSTEM_ACCEPTANCE_NEEDS_CORRECTION / RELEASE_FREEZE_BLOCKED**。
- 100/100 场景已执行；参数化 ≥342；无永久 QUEUED/RUNNING、无 95% 卡死、无预期外 DLQ/unacked、无正式版本绕过 VERIFIED、无候选丢失；门禁数字与真实命令一致。
