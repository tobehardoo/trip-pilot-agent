# 国内智能旅行规划 Agent

这是一个面向 Java 后端与 AI Agent 求职方向的简历项目。项目采用 Java 主业务后端、Python Agent 服务和 Vue 前端，目标不是生成泛化旅游攻略，而是生成满足时间、预算、地点和交通约束的可执行国内自由行行程。

当前仓库处于设计冻结阶段。本文档集是后续实现、测试、部署和简历整理的设计依据。

## 当前实现状态

M1 正在实施。仓库已经包含 Spring Boot、FastAPI 和 Vue 的最小可运行骨架，以及 PostgreSQL/PostGIS/pgvector、Redis、RabbitMQ 的本地 Compose 配置。

本地准备：

```powershell
Copy-Item .env.example .env
docker compose up -d --build
mvn test

Set-Location apps/agent-service
uv sync --extra dev
uv run pytest

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
