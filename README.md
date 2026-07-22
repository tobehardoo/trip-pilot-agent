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
- Python Worker 使用严格的强类型消息契约消费创建命令，支持真实高德 POI 规划和确定性的 Demo 降级。
- Python 已提供与规划流程解耦的强类型 `MapProvider`、高德地点搜索 2.0 适配器、Redis JSON 缓存和确定性的 Demo Map Provider；缓存故障可降级，第三方错误已统一分类。
- Python 已新增独立 `RouteProvider`、高德 v5 步行路线适配器和 Demo 路线估算，可返回距离、耗时、分段与地图 polyline；路线缓存按起终点、POI ID、方式和 UTC 出发小时生成 SHA-256 键。
- `PLANNING_COMPLETED` v3 携带 POI 元数据和相邻活动步行段；Java 向后兼容 v1/v2，并幂等保存不可变行程版本、活动与关系型交通段。
- 当前行程 API 按所有者隔离；任务 SSE 支持持久历史补发、`Last-Event-ID` 重连、实时终态通知与终态关闭。
- Vue 工作台可直接创建规划任务，使用带 Bearer Token 的流式 `fetch` 消费 SSE，并在断线后携带 `Last-Event-ID` 补发。
- 任务完成后自动读取当前行程，以日期和活动时间轴展示 Provider、版本与估算费用；UTC 活动时间统一按中国标准时间显示。
- Vue 工作台已显示活动地址、地图 Marker 和步行 polyline；地图与时间轴可双向选择，缺少浏览器专用高德凭据时安全降级为可交互路线概览。
- Java 88 个自动化测试、91.08% 行覆盖率，Python 当前 263 个 Worker/API/Provider/知识检索/采集测试在真实 pgvector PostgreSQL 上全部通过，以及 Vue 43 个组件、API 边界、SSE、地图、路由与仓库测试；知识检索与采集总行覆盖率为 92.81%，通过 80% 门禁，Vue 地图切片行覆盖率为 92.66%。
- Python 已新增知识导入链：广州官方 Markdown 资料、TOML 元数据与稳定切分、独立 `agent` schema 的 pgvector 持久化、版本不可变校验和 `trip-agent-knowledge` 迁移/导入/检索 CLI；演示哈希向量明确标记为离线实现，不替代生产语义模型。
- Phase 12 已建立官方知识采集基础：来源 TOML 注册表、广州官方固定 URL、城市筛选、白名单域名、HTTPS/凭据/公网 IP 校验、固定 URL 发现和 `trip-agent-acquisition validate` CLI；`HttpResourceFetcher` 已支持 ETag/Last-Modified 条件请求、304 强类型结果、流式响应上限、显式重定向复核、DNS 全结果公网单播校验、单次抓取 IP 固定、环境代理隔离和可重试错误分类，`AcquisitionScheduler` 已执行每来源限速、并发安全的实际放行间隔、有上限指数退避和强类型尝试记录。生产入口 `AcquisitionWorkflow` 会读取“校验器 + 对应内容哈希”的版本化条件状态，再强制执行并持久化调度结果；`knowledge_resource`、`knowledge_snapshot` 与 `knowledge_fetch_run` 通过并发安全的独立校验和迁移和单事务仓储保存当前内容状态、不可变 `PENDING` 候选及完整尝试审计。`GuangzhouGovernmentArticleExtractor` 已从 3 个真实官方页面提取正文、标题、来源和发布时间，`knowledge_extraction` 按快照与解析器版本不可变保存通过/拒绝结果和质量问题；人工审核与 RAG 发布仍未接通。

下一条纵向切片继续完成 P0-1：建立人工审核状态、审核操作与审核发布适配器；完成采集闭环后再把检索结果接入规划 Agent。

本地准备：

```powershell
Copy-Item .env.example .env
docker compose up -d --build
mvn test

Set-Location apps/agent-service
uv sync --extra dev
uv run pytest
uv run trip-agent-worker
uv run trip-agent-knowledge migrate
uv run trip-agent-knowledge import ../../knowledge/guangzhou

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
14. [Phase 5 网页规划闭环与 Demo 行程时间轴测试计划](docs/13-phase-5-web-planning-workbench-test-plan.md)
15. [Phase 6 高德 POI Provider 与 Redis 缓存测试计划](docs/14-phase-6-amap-poi-provider-test-plan.md)
16. [Phase 7 真实 POI 完成事件与 Demo 降级测试计划](docs/15-phase-7-real-poi-completion-contract-test-plan.md)
17. [Phase 8 高德步行路线 Provider 与 Redis 缓存测试计划](docs/16-phase-8-amap-route-provider-test-plan.md)
18. [Phase 9 相邻活动路线、交通段持久化与行程 API 测试计划](docs/17-phase-9-transit-leg-contract-test-plan.md)
19. [Phase 10 前端地图与时间轴联动测试计划](docs/18-phase-10-web-map-linkage-test-plan.md)
20. [Phase 11 广州知识导入与 RAG 基础链路测试计划](docs/19-phase-11-guangzhou-knowledge-rag-test-plan.md)
21. [Phase 12 官方知识采集测试计划](docs/20-phase-12-official-knowledge-acquisition-test-plan.md)
22. [全局架构审计与优化路线](docs/21-global-architecture-review-and-optimized-roadmap.md)

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
