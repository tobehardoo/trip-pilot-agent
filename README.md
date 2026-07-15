# 国内智能旅行规划 Agent

这是一个面向 Java 后端与 AI Agent 求职方向的简历项目。项目采用 Java 主业务后端、Python Agent 服务和 Vue 前端，目标不是生成泛化旅游攻略，而是生成满足时间、预算、地点和交通约束的可执行国内自由行行程。

当前仓库处于 M1 实施阶段。本文档集是后续实现、测试、部署和简历整理的设计依据。

## 当前实现状态

M1 正在实施。当前已经完成：

- Spring Security 注册、登录、JWT Access Token 和 Refresh Token 轮换。
- Access Token 过期自动刷新并重试一次，退出登录会在服务端撤销 Refresh Token。
- PostgreSQL、Flyway、MyBatis 持久化，以及按用户隔离的旅行基础业务。
- 旅行创建、列表、详情、结构化约束和乐观锁更新接口。
- Vue 注册/登录、会话恢复、旅行列表、结构化旅行创建和可刷新深链的旅行详情工作台。
- 旅行约束编辑会携带乐观锁版本、保留固定安排，并在并发冲突后支持重新加载最新数据。
- Java 规划任务 API 会在同一事务写入 `PlanningTask + Outbox`，支持幂等重放和单旅行活动任务约束。
- Outbox 通过 RabbitMQ publisher confirm 至少一次投递；每条确认使用独立事务，失败会记录原因并指数退避。
- Python Demo Worker 使用严格的强类型消息契约消费创建命令，并发布确定性的结构化完成事件。
- Java 幂等消费完成事件，在单事务内更新任务、保存任务事件和不可变关系型行程版本；过期基线结果会失败且不污染当前行程。
- 当前行程 API 按所有者隔离；任务 SSE 支持持久历史补发、`Last-Event-ID` 重连、实时终态通知与终态关闭。
- Java 73 个自动化测试、90.78% 行覆盖率，Python 21 个 Worker/API 测试，以及 Vue 25 个组件、API 边界、路由与仓库测试。

下一条纵向切片是把 Vue 工作台接入规划任务、SSE 和当前行程 API，无需脚本即可从页面看到 Demo 行程时间轴。

本地准备：

```powershell
Copy-Item .env.example .env
docker compose up -d --build
mvn test

Set-Location apps/agent-service
uv sync --extra dev
uv run pytest
uv run trip-agent-worker

Set-Location ../web
pnpm install
pnpm test
pnpm dev
```

`.env` 已被 Git 忽略。真实高德和模型 Key 只能放在本地 `.env` 或 GitHub Secrets 中。

## 文档索引

1. [项目定位与范围](docs/00-project-charter.md)
2. [系统架构与技术栈](docs/01-system-architecture.md)
3. [领域模型与数据设计](docs/02-domain-and-data.md)
4. [Agent 工作流设计](docs/03-agent-workflow.md)
5. [行程优化与约束求解](docs/04-planning-optimization.md)
6. [数据、RAG 与外部 Provider](docs/05-data-rag-providers.md)
7. [前端体验与接口契约](docs/06-frontend-and-api.md)
8. [可靠性、安全与可观测性](docs/07-reliability-security-observability.md)
9. [测试与 Agent 评测](docs/08-testing-and-evaluation.md)
10. [开发路线图与 TODO](docs/09-roadmap-and-todos.md)
11. [Phase 2 认证与旅行测试计划](docs/10-phase-2-test-plan.md)
12. [Phase 3 异步规划命令测试计划](docs/11-phase-3-test-plan.md)
13. [Phase 4 完成事件、行程版本与 SSE 测试计划](docs/12-phase-4-completion-and-sse-test-plan.md)

## 已确认的基础约束

- 开发者背景：熟悉 Java，了解 Python、HTML/CSS/JavaScript 和 Vue。
- 求职方向：Java 后端约 60%，AI 应用与 Agent 开发约 40%。
- 开发投入：每天约 3 小时，主要使用 Codex 辅助开发。
- 时间目标：2026 年 8 月 23 日前功能冻结，8 月底前完成部署和简历材料。
- 开发设备：Intel Core i5-13500H、16 GB 内存、核显。
- 开发预算：500 元人民币以内。
- 代码仓库：计划公开到 GitHub，禁止提交任何真实 API Key、Token 或个人敏感数据。
- 部署：开发期使用本地 Docker Compose，功能稳定后再选择腾讯云或阿里云。

## 决策规则

- 文档中标记为“已确认”的内容可以直接进入实现。
- 标记为“待评测”的模型、参数和权重必须通过固定评测集决定。
- 标记为“TODO”的功能不得阻塞 V1 核心链路。
- 架构变更应先更新对应文档，再修改代码。
- 实现与文档冲突时，以最新已评审的架构决策为准，并同步修正文档。
