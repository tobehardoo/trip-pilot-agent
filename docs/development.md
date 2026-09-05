# 开发指南

- 文档状态：生效中（基于当前代码）
- 相关文档：[系统架构](architecture.md) · [运行与运维](operations.md) · [架构决策记录](decisions.md)

## 1. 仓库结构

```text
apps/
  travel-server/        Java 21 / Spring Boot 3.5 / MyBatis —— 业务 API 与消息可靠性
  agent-service/        Python 3.12 / FastAPI / LangGraph —— 规划管线与 Agent 编排
    benchmarks/         调度器 / 行程评估 / Agent 轨迹基准
    src/trip_agent/
      agent/            LangGraph 循环、工具、状态、失败策略
      planning/         候选、日程、CP-SAT、交通（纯确定性，不碰 Provider）
      feasibility/      11 条硬校验规则 + 有界修复
      providers/        Provider 协议、错误分类学
      infrastructure/   高德/QWeather 适配、缓存
      guide_intelligence/  多源攻略导入、事实核验、OCR
      retrieval/        pgvector RAG
      acquisition/      受控抓取（HTTPS 强制、SSRF 防护）
      worker/           AMQP 消费、契约模型（pydantic）
      dialog/           对话服务（复用 AgentLoop）
  web/                  Vue 3 + TypeScript + Vite 前端
contracts/              Java↔Python 消息 JSON Schema（权威）+ fixtures
knowledge/              RAG 语料与来源注册表（运行数据，非文档）
infra/                  Docker 镜像定义与 Prometheus 配置
scripts/                运维与校验脚本（自带 unittest，纳入 CI）
```

## 2. 环境要求

- JDK 21（Temurin）
- Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)
- Node.js 24 与 pnpm 10
- Docker + Compose v2（完整栈联调、Testcontainers）

## 3. 三栈本地开发

### Python（agent-service）

```bash
cd apps/agent-service
uv sync --extra dev                    # 含 dev 依赖
uv run ruff check .                    # lint（0 违规为门禁）
uv run pytest                          # 全量测试
```

部分真实链路用例（真实 AMap/DashScope/数据库）默认 skip，需显式开启或设置 `KNOWLEDGE_TEST_DATABASE_URL`。异步测试全仓统一使用 `platform_util.run_async`（不引入 pytest-asyncio），这是既定约定。

### Java（travel-server）

```bash
cd apps/travel-server
mvn verify                             # 编译 + 测试 + JaCoCo 覆盖率检查
```

JaCoCo 在 `verify` 阶段强制 BUNDLE 行覆盖率 ≥ 80%，不达标即构建失败。测试不使用 Mockito（依赖已显式排除），统一手写 test double；跨 Postgres/RabbitMQ 的集成测试走 `support/PostgresIntegrationTest`（Testcontainers）。

### Web（apps/web）

```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm test:coverage                     # Vitest 单测 + 覆盖率门禁
pnpm typecheck                         # vue-tsc，构建前置
pnpm build                             # 生产构建
pnpm test:e2e                          # Playwright（自动起 vite dev server）
```

- E2E 常规 spec 用 `page.route` 级 mock（含手造 SSE 帧）；`qa-real-chain.spec.ts` 是零 mock 真实链路，只在本地跑（`playwright.local.config.ts`），CI 显式排除。
- 覆盖率门禁配置在 `vite.config.ts`（branches/lines/statements 80%、functions 75%），include 为手工维护的生产文件清单。

## 4. 测试门禁一览（CI 强制）

| Job | 检查 |
|---|---|
| java | `mvn verify`（621 测试 + JaCoCo ≥ 80%） |
| python | ruff 0 违规 · 语料注册表校验 · pytest（retrieval/acquisition/guide_intelligence 覆盖率 ≥ 80%）· PlanEvaluation 基准 |
| web | frozen-lockfile 安装 · 覆盖率门禁 · typecheck · build · Playwright E2E |
| infrastructure | compose config 校验 · 9 镜像强制 digest 固定 · 生产镜像构建 · Compose 冒烟（断言 `/api/health`） |
| repository-safety | scripts unittest · Markdown 链接检查（`scripts/check_markdown_links.py`）· gitleaks · 追踪密钥文件拒绝 |

当前基线：Python 2112 passed / 42 skipped，Java 621 passed，Web 350 passed。修改代码后三栈测试必须全绿。

## 5. 基准与评估工具

- **调度器基准**：`apps/agent-service/benchmarks/scheduler/run_scheduler_benchmark.py`——10 个确定性场景对照贪心与 CP-SAT，结果表见同目录 README。
- **行程评估基准**：`apps/agent-service/benchmarks/run_plan_evaluation.py`（CI 必跑）。
- **Agent 轨迹回放**：回放 harness + 5 场景不变量基准（`benchmarks/` 下 agent_trajectory）。
- **RAG 检索评估**：`knowledge/evaluations/` 语料版本锁定的中文查询期望集。
- **真实链路冒烟**：`scripts/smoke_test.py`、`scripts/golden_scenarios_http.py`。

## 6. 修改消息契约的流程

1. 先改 `contracts/messaging/` 下对应 JSON Schema（新版本文件，不破坏旧版本）。
2. 在 `contracts/fixtures/` 增加样例。
3. Python 侧改 `worker/contracts.py` pydantic 模型 + 契约测试；Java 侧改对应 Parser + 测试。
4. 消费侧按 `schema_version` 分派，新旧版本并存到迁移完成。

## 7. 约定

- Python：ruff（line-length 100，select E/F/I/B/SIM/UP）；依赖精确锁版（`uv.lock`）；配置数值越界直接 raise。
- Java：不使用 Lombok；优先 record；异常经 `GlobalApiExceptionHandler` 统一映射错误码。
- Web：strict TypeScript（全仓 `as any` 控制在个位数）；测试集中在 `apps/web/tests/`，生产代码内不放测试文件。
- 提交信息惯例：`feat|fix|refactor|chore (scope): summary`。
