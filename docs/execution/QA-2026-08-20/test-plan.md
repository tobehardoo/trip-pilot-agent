# QA-2026-08-20 Test Plan — TripPilot 综合质量验证

- 日期：2026-08-20
- 角色：资深测试工程师 + 全栈开发者（只读执行；不修改生产代码、不操作运行栈）
- 工作区：`C:\Users\未\Desktop\trippilotage`
- 分支 / HEAD：`codex/feasibility-foundation` @ `d10e70cf`
- 权威依据：`docs/development/测试策略.md`、`docs/architecture/golden-scenario-catalog.md`（G01-G30 + 10 不变式）、`docs/execution/B14/scenario-catalog.md`（S001-S100）、`.github/workflows/ci.yml`、`compose.prod.yaml`
- 说明：AGENTS.md 在仓库中不存在（已记录，跳过）。

## 保护约束（最高优先级）

- 严禁 `git reset --hard / checkout -- . / restore . / clean / stash`；严禁提交、推送、rebase。
- **trip-pilot-prod**（Web 127.0.0.1:38080，8 容器健康）与 **trip-pilot-b13fix1-verify**（遗留，travel-server Restarting）**不得操作**；仅允许对运行栈做只读健康探测（GET /api/health 等，不修改状态）。
- 主机进程 3306(MySQL)/6379(Redis)/6060 不得操作。
- 所有会修改 DB/队列/缓存/容器状态的测试使用**独立隔离栈**（`trip-pilot-b14-acceptance`，WEB_PORT=38085，测试专用 secret）。
- 不输出 `.env` / AMap Key / JWT / 令牌 / 敏感 URL；报告一律脱敏。
- 真实 AMap：仅边界、低调用量（≤6 次），绝不压测。

## 执行阶段

| 阶段 | 内容 | 命令入口 | 判定 |
| --- | --- | --- | --- |
| 0 | 基线与环境审计 | git status / 版本 / docker ps / netstat | 完成 |
| 1 | 静态质量门禁 | git diff --check / check_markdown_links / check_compose_defaults --with-docker / scripts unittest + CI 等价（compose config、tracked-secret 检查） | 全部 exit 0 |
| 2 | Python 套件 | uv 等价：ruff check；pytest --cov（retrieval/acquisition/guide_intelligence，fail-under 80）；benchmarks/run_plan_evaluation.py；B17/B18/B19 定向回归 | 全绿 |
| 3 | Java 套件 | mvn -pl apps/travel-server clean verify（JDK21 + Testcontainers + Flyway + JaCoCo） | BUILD SUCCESS + 覆盖率 |
| 4 | Web 套件 | pnpm test:coverage / typecheck / build；Playwright E2E（chromium） | 全绿 |
| 5 | 隔离 Compose 栈 | compose.prod.yaml + QA env，-p trip-pilot-b14-acceptance，DEMO_ONLY，WEB_PORT=38085；up --wait；健康检查 + 跨服务冒烟；config 校验（CI 等价） | healthy + smoke PASS |
| 6 | Golden G01-G30 | Python test_golden_matrix（G03-G06 等）、Java Testcontainers G23-G30、Web Playwright G23-G30、scripts/golden_scenarios_http.py | 按矩阵 |
| 7 | B14 S001-S100 | scripts/acceptance/b14/matrix_{a,b,param,real,fault}.py 对隔离栈；FAULT 仅操作隔离栈容器 | 记录 PASS/FAIL/FLAKY |
| 8 | 故障场景 | SSE replay（S080）、RabbitMQ 停/恢复（S081/S082）、worker 退出恢复（S083/S084）、95% stuck（B17 None-omit 契约回归）、垃圾消息（S086） | 无永久 QUEUED |
| 9 | 安全 | S001-S010（鉴权/越权/输入校验）、tracked-secret 检查、日志脱敏抽查、S036/S037 越权 token | 无敏感泄漏 |
| 10 | DEMO 负载 | S099（10 用户×10 trip=100 并发）DEMO_ONLY 隔离栈 | 100 终态 0 stuck |
| 11 | 真实 AMap（边界） | 低调用量（≤6 次）walking/transit/driving 对 2-3 个广州 pair | 全部成功或分类记录 |
| 12 | B19-D 回归 | Python transit_mode/mode_recommendation/amap_transit 套件；Java itinerary 编辑（TAXI/TRANSIT）；Web transit/AUTO；completion v11 schema | 全绿 |
| 13 | 汇总 | test-results.md / defects.md / results.json / evidence/ | Verdict |

## Verdict 判定

- PASS：全部核心门禁通过，无 P0/P1 缺陷。
- PASS_WITH_KNOWN_RISK：存在已知风险/非阻塞缺陷（如实分类）。
- FAIL：任一核心门禁失败或存在 P0/P1 缺陷。
- BLOCKED：环境无法提供必要资源。
