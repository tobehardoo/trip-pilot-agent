# 开发路线图与 TODO

## 1. 时间与资源假设

- 当前基准日期：2026-07-17。
- 每天投入约 3 小时，约 21 小时/周。
- 主要使用 Codex 辅助，但架构决策、验收和关键代码必须由开发者理解。
- 开发机：i5-13500H、16 GB 内存、核显。
- 目标：2026-08-23 功能冻结，8 月底完成部署、修复和简历材料。
- 代码公开到 GitHub。

由于每周时间从最初假设的 25 小时降为约 21 小时，路线图采用纵向切片，优先保证端到端可运行，不并行铺开三个城市。

## 2. 六周计划

### 第 1 周：7.13 至 7.19，基础系统

- 仓库、文档、代码规范和 GitHub Actions 骨架。
- Java、Python、Vue 项目骨架。
- Docker Compose 核心依赖。
- Flyway、用户登录、旅行 CRUD 和约束模型。
- Vue 登录、旅行列表、创建旅行和工作台静态布局。

验收：用户可登录并创建“广州 4 日游”，填写日期、预算、同行类型和偏好。

截至 2026-07-15：上述核心验收已完成。Java 认证与旅行接口、Vue 注册/登录、旅行创建、详情深链和约束编辑流程已经通过自动化测试及真实浏览器联合验收；乐观锁冲突可保留表单并重新加载最新数据。

同时已提前完成第 2 周最小闭环：Java 在同一事务创建 `PlanningTask + Outbox`，通过 publisher confirm 投递 RabbitMQ，Python Demo Worker 发布确定性的 `PLANNING_COMPLETED`，Java 再幂等保存任务事件和不可变关系型行程版本。完成消费者具备契约拒绝与死信、过期基线保护、原子回滚和事件 ID 冲突保护；当前行程 API 与带历史补发的所有者隔离 SSE 已通过真实 RabbitMQ、PostgreSQL 和跨服务冒烟。

截至 2026-07-16，Vue 工作台也已完成任务创建、带 Bearer Token 的流式 SSE、断线事件补发、规划状态和 Demo 行程时间轴。网页注册、创建广州 4 日游、点击开始规划并自动显示 4 天行程已通过真实 Java -> RabbitMQ -> Python Worker -> PostgreSQL -> SSE 跨服务验收；桌面与 390 px 移动视口无横向溢出或元素重叠。

同日已提前开始第 3 周真实数据切片：Python 完成强类型 `MapProvider`、高德地点搜索 2.0 文本搜索、统一错误映射、Redis JSON 缓存与确定性 Demo 降级，且不读取真实 Key 做自动化测试。

截至 2026-07-17，`PLANNING_COMPLETED v2`、Java v1/v2 兼容解析、Flyway V6 活动来源元数据、异步 AMAP 规划器和真实模式 Worker 已完成。真实 Java -> RabbitMQ -> Python -> 高德 -> Redis -> PostgreSQL 验收为广州行程生成“南越王博物院（王墓展区）”，保存 POI ID 与 `113.261015, 23.137823` 坐标并由当前行程 API 返回。

同日继续完成独立 `RouteProvider`、高德 v5 步行路线适配器、确定性 Demo 路线和 Redis 路线缓存。真实高德验收在广州两个 POI 之间返回 8758 米、7006 秒、20 个分段和 258 个 polyline 点，第二次请求命中只含 SHA-256 键的 Redis 缓存。

随后完成 `PLANNING_COMPLETED v3`、相邻活动路线生成、Flyway V7 `transit_leg`、Java v1/v2/v3 兼容解析与当前行程 API。真实 Java -> RabbitMQ -> Python -> 高德 -> Redis -> PostgreSQL 广州验收在 3.1 秒内生成两个 AMAP 活动和一个 AMAP 步行段，路线为 1921 米、1537 秒、78 个 polyline 点。

同日完成 Vue 地图切片：当前行程坐标、地址和 polyline 已渲染为 Marker、路线和活动地址，地图与时间轴支持双向选择；浏览器缺少专用高德 JS API 凭据时显示不泄露服务端 Key 的可交互路线概览。43 个 Vue 测试、92.66% 地图切片行覆盖率、类型检查和生产构建通过，1280 px 桌面与 390 px 移动浏览器验收无横向溢出、越界或控制台错误。下一步进入广州知识资料导入与 RAG。

截至 2026-07-19，广州知识资料切片已完成：3 份官方来源 Markdown、TOML 元数据校验、稳定标题感知切分、离线 Demo Embedding、独立 `agent` schema 的 pgvector 持久化和精确 cosine 检索均已通过真实隔离 PostgreSQL 验收。`trip-agent-knowledge` 支持迁移、递归导入和带来源/版本/片段 ID 的 JSON 检索输出；同版本重复导入幂等，内容变化会拒绝覆盖。真实语义 Embedding、Rerank、推荐理由引用和前端来源展示仍留在下一阶段。

同日启动 Phase 12 知识采集基础：先建立官方来源注册表、固定 URL 发现、域名白名单和 SSRF 边界；后续再接 HTTP 条件请求、快照、正文抽取、审核发布和 freshness report。采集候选不能绕过审核直接写入 `knowledge_document`。

Phase 12 第一小步已完成：新增 `knowledge/sources/guangzhou.toml`、`trip_agent.acquisition` 来源模型/注册表/固定 URL 发现和 `trip-agent-acquisition validate` CLI；158 项 Python 测试通过，总覆盖率 91.60%。

2026-07-20 完成 Phase 12 第二小步：新增强类型 `HttpResourceFetcher`，支持 ETag/Last-Modified、304 未变化结果、拒绝压缩编码的原始字节流上限、白名单内显式重定向、白名单外/畸形重定向阻断，以及超时、网络失败和 HTTP 状态分类。173 项 Python 测试通过，知识检索与采集总覆盖率 91.60%；DNS 解析固定、限速、退避重试执行和快照持久化仍待后续。

2026-07-22 完成 Phase 12 第三小步：新增可注入的系统 DNS 解析边界，对全部 A/AAAA 结果执行公网单播校验，并把本次抓取固定到已核验 IP；HTTP Host、TLS SNI 和对外最终 URL 保留原始域名。同主机重定向复用固定结果，新主机重定向重新解析和校验；私网、回环、保留、组播、混合公网/私网、空结果和解析失败均在请求前分类阻断。抓取器使用禁用环境代理与 HTTP/2 的专用客户端，并在每一跳清空 Cookie，避免代理改变 TLS 身份或基于固定 IP 泄漏跨跳状态；transport factory 保证重复和并发抓取各自拥有独立生命周期。采集模块 49 项测试通过；本机 Docker 未运行时 Python 全量为 184 项通过、4 项 pgvector 集成测试跳过，知识检索与采集总覆盖率 83.94%，仍通过 80% 门禁。下一步实现每来源限速与有上限的指数退避重试。

同日完成 Phase 12 第四小步：新增强类型 `AcquisitionScheduler`、`RetryPolicy` 和尝试/执行结果，所有首次抓取与重试共享每来源实际放行间隔；只重试明确标记为可重试的采集错误，并执行最大 10 次、拒绝非有限参数的有上限指数退避。限速器使用每来源独立锁，在事件循环晚唤醒、等待取消和并发请求下仍按实际启动时间保持间隔，其他来源可独立前进；尝试时间统一为 UTC。采集相关 70 项测试通过；本机 Docker 未运行时 Python 全量为 205 项通过、4 项 pgvector 集成测试跳过，知识检索与采集总覆盖率 85.50%。下一步实现 `knowledge_resource`、`knowledge_snapshot` 和 `knowledge_fetch_run` 持久化。

同日完成 Phase 12 第五小步：新增 `AcquisitionExecutionRecorder`、`AcquisitionWorkflow`、并发安全的独立校验和迁移及 `PsycopgAcquisitionRepository`，生产工作流会读取“条件校验器 + 对应内容哈希”的版本化状态并强制组合调度与记录，以单个 PostgreSQL 事务持久化 `knowledge_resource`、不可变 `PENDING` `knowledge_snapshot` 和带完整尝试审计的 `knowledge_fetch_run`。原始内容按 SHA-256 与解析器版本幂等，解析器升级可产生新候选但不会误报页面变化，A→B→A 内容回退仍更新最近变化；304 不建快照且必须携带基线哈希，失败不更新最近核验，实际并发、乱序完成和 fetched-B/304-A 交错不会让内容哈希与 ETag 失配。采集相关 95 项测试、Python 全量 234 项测试在真实 pgvector PostgreSQL 上通过，知识检索与采集总覆盖率 93.29%。下一步实现官方 HTML 正文与发布时间抽取、质量检查和审核发布。

截至 2026-07-19 完成全局架构审计：当前核心链路可演示，但真实 Agent 规划、RAG 到规划理由的接入、采集快照/审核、生产级可观测性和公开部署安全仍未完成。后续按 `docs/21-global-architecture-review-and-optimized-roadmap.md` 的 P0/P1 顺序推进，不再同时扩展新城市和新 UI 功能。

### 第 2 周：7.20 至 7.26，Agent 最小闭环

- Java 创建 PlanningTask 和 Outbox。
- RabbitMQ Command/Event。
- Python Worker 消费任务。
- 模型解析结构化约束。
- Demo Provider 生成简单结构化行程。
- Java 保存结果并通过 SSE 推送。

验收：网页提交需求后，无需手动脚本即可看到结构化行程。

### 第 3 周：7.27 至 8.2，真实数据与 RAG

- 高德地理编码、POI 和路线 Provider。
- Redis POI/路线缓存。
- 地图 Marker、路线和时间轴联动。
- 广州第一批知识资料。
- Markdown 导入、切分、Embedding 和 pgvector 检索。
- 推荐理由显示来源。

验收：广州行程使用真实地点，地图可交互，知识引用可查看。

### 第 4 周：8.3 至 8.9，OR-Tools 优化

- 候选 POI 过滤和评分。
- 地理粗分组和受控路线矩阵。
- OR-Tools 时间窗、必去、预算、首尾交通和锁定约束。
- 用餐时间窗、求解后校验和无解分析。

验收：包含预约、必去和返程条件的需求能生成可行行程；无解时报告明确冲突。

### 第 5 周：8.10 至 8.16，局部重规划

- 时间轴拖拽、删除和锁定。
- 影响范围分析和局部重规划。
- 不可变版本、差异和回滚。
- Checkpoint、人工确认、取消和失败重试。
- 最小运维页。
- 杭州、西安使用基础数据跑通；增强资料按时间逐步加入。

验收：修改第二天只影响第二天，其他日期与锁定活动保持不变。

### 第 6 周：8.17 至 8.23，质量与上线准备

- Java/Python 单元与集成测试。
- Testcontainers 和关键 Playwright E2E。
- 30 条初始 Agent 评测。
- 限流、费用统计和 Trace 关联。
- Prometheus/Grafana/OpenTelemetry 的最小可用配置。
- 云端 Docker 部署或至少完成可复现部署脚本。

验收：固定命令可启动、测试和评测；能查看一次完整规划的耗时、Token 和工具调用。

### 缓冲周：8.24 至 8.31

- 修复缺陷和补齐测试。
- UI 细节和响应式检查。
- GitHub README、架构图、截图和演示视频。
- 简历项目描述和面试问答。
- 视进度补充杭州、西安资料。

## 3. 每日工作节奏建议

每天约 3 小时可按以下方式分配：

- 15 分钟：确认当天目标和验收标准。
- 120 分钟：实现一个可验证的纵向任务。
- 30 分钟：测试、手动验证和修复。
- 15 分钟：提交代码并更新文档/TODO。

避免一天同时修改 Java、Python、前端和基础设施四条链路。优先完成一个端到端小切片。

## 4. 必须保留的核心

- Java 异步任务与 Outbox/RabbitMQ 链路。
- 真实 POI 和路线。
- OR-Tools 约束优化。
- 硬约束校验和无解解释。
- 局部重规划。
- 不可变行程版本。
- 地图与时间轴前端。
- 基础测试与 Agent 评测。
- Demo Provider 和可复现演示。

## 5. 延期时的删减顺序

1. PDF 导出。
2. 多套完整方案。
3. OAuth、短信、微信登录。
4. Langfuse。
5. 完整监控云端部署。
6. 杭州、西安的扩充资料。
7. 知识库后台管理。

不得为了“技术栈更广”牺牲核心链路的完整性和测试。

## 6. 已确认 TODO

### 交通与旅行能力

- 自驾路线、停车点、停车费用、拥堵、限行和租车。
- 多城市联程。
- 合法的实时酒店、车票和航班 Provider。
- 多套完整行程候选。

### 协作与输出

- 多人实时协作。
- PDF 或其他格式导出。
- 更丰富的分享和权限。

### 数据与 RAG

- 知识库后台上传、审核、发布和更新。
- 自动更新与失效检测。
- 数据规模扩大后评估 Elasticsearch 混合检索。
- Embedding 与 Rerank 模型评测。

### 平台与工程

- Debezium CDC Outbox。
- Langfuse Agent Trace。
- 接入数据库、Redis 和 RabbitMQ 后，将固定 liveness 拆分为依赖感知的 readiness。
- CI 增加 PostgreSQL 组合镜像构建和扩展运行时验证。
- OAuth、短信或微信登录。
- 托管数据库、Redis 或消息服务。
- Kubernetes，仅在部署规模证明需要后考虑。

## 7. 待实现时确定的技术决策

以下内容尚未最终锁定，必须在对应迭代前决定：

- 持久层已确定使用 MyBatis，以显式 SQL 展示事务边界、用户隔离和乐观锁实现。
- Element Plus 与 Naive UI 二选一。
- Vue 拖拽库。
- 具体模型标识和模型路由。
- Embedding 和可选 Rerank 模型。
- OR-Tools 权重和求解时间上限。
- Redis TTL、重试次数、限流阈值。
- 腾讯云或阿里云以及具体服务器配置。
- LangGraph checkpoint 的具体持久化实现。

这些决策通过小型实验、官方资料、评测结果和资源约束决定，不在没有证据时固定。

## 8. GitHub 交付物

- 清晰的项目 README 和快速启动。
- 架构图、Agent 状态图和关键时序图。
- `.env.example` 和 Demo 模式说明。
- 本地 Docker Compose。
- 测试与 Agent 评测命令。
- 关键页面截图或短演示视频。
- 技术决策、已知限制和后续 TODO。
- 不提交任何真实密钥或用户敏感数据。

## 9. 文档维护

- 新增核心功能前更新对应设计文档。
- 发生关键技术选型时在本文件“待实现时确定”中移除，并记录决定和理由。
- TODO 完成后移动到实现记录或 changelog，不直接删除历史背景。
- 每周结束检查路线图验收条件，而不是只统计完成了多少接口。
