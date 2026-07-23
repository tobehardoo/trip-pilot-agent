# 系统架构与技术栈

## 1. 架构结论

采用“Java 模块化单体 + 独立 Python Agent 服务 + Vue 单页应用”。

- Java 是唯一对前端公开的业务后端。
- Python 负责 Agent 编排、RAG、模型调用和约束优化。
- 长耗时规划通过 RabbitMQ 异步执行。
- 一个 PostgreSQL 实例可以承载多个 schema，但 Java 与 Python 保持逻辑数据所有权。
- V1 不拆 Spring Cloud 微服务群，不引入 Kafka。

```text
Vue 3 + TypeScript
地图、时间轴、结构化追问、运维页
            |
        Nginx / HTTPS
            |
      Spring Boot 主后端
用户、旅行、行程、版本、权限、任务、SSE
            |
  PostgreSQL  Redis  RabbitMQ
        \       |       /
       Python Agent Worker
 LangGraph、RAG、LLM、OR-Tools、Provider
            |
  高德、天气、模型 API、城市知识库
```

## 2. 选择模块化单体的原因

- 核心业务状态、权限和强一致性边界集中在 Java 服务中，便于统一事务管理。
- V1 的业务规模不需要维护大量微服务，模块化单体能降低部署和运维复杂度。
- Java 与 Python 两个部署单元已经足以展示跨语言通信、异步任务和最终一致性。
- 代码按业务模块隔离，未来需要时可以迁移为独立服务。
- 可使用 ArchUnit 或 Spring Modulith 检查模块依赖，但它们不是 MVP 阻塞项。

## 3. 组件职责

### 3.1 Vue 前端

- 登录、旅行列表和旅行创建。
- 地图与行程时间轴工作台。
- 结构化追问和辅助聊天。
- SSE 任务进度和断线恢复。
- 活动拖拽、删除、锁定和重规划。
- 行程版本差异、回滚和只读分享。
- Agent 运维和评测结果展示。

### 3.2 Spring Boot

- 用户、认证、权限和长期偏好。
- Trip、Constraint、Itinerary 和 Version 业务模型。
- 规划任务状态机、幂等、取消和重试。
- Transactional Outbox 与 RabbitMQ 消息。
- Python 返回结果的业务校验和持久化。
- SSE 业务进度推送。
- 分享链接、限流、审计和运维 API。

### 3.3 Python Agent

- LangGraph 状态机和 checkpoint。
- 自然语言需求结构化。
- 高德、天气、RAG 和 LLM Provider 适配。
- 候选 POI 召回、过滤与排序。
- 路线矩阵和 OR-Tools 约束优化。
- 结果校验、冲突分析和局部重规划。
- 模型、工具和评测执行记录。

### 3.4 基础设施

- PostgreSQL：业务数据、Agent 数据和 Outbox。
- PostGIS：坐标、空间距离和地理粗筛。
- pgvector：城市知识向量检索。
- Redis：缓存、限流、短期状态和快速并发拦截。
- RabbitMQ：持久规划命令、结果事件、重试和死信。
- Nginx：静态资源、反向代理和 HTTPS。

## 4. 推荐技术栈

具体小版本在实现时通过官方文档和兼容性验证后锁定。

### Java

- Java 21
- Spring Boot 3
- Spring Security
- MyBatis 或 MyBatis-Plus
- Flyway
- PostgreSQL JDBC
- Redis Client
- RabbitMQ Client / Spring AMQP
- Bean Validation
- SpringDoc OpenAPI
- JUnit 5、Testcontainers

### Python

- Python 3.12
- FastAPI
- Pydantic
- LangGraph
- SQLAlchemy
- OR-Tools
- pgvector 客户端
- pytest

### 前端

- Vue 3
- TypeScript
- Vite
- Pinia
- Vue Router
- Element Plus 或 Naive UI，最终在 UI 原型阶段二选一
- 高德 JavaScript API
- ECharts
- 支持 Vue 的拖拽库，最终在实现阶段验证维护状态后选择
- Playwright

### 工程与可观测性

- Docker Compose
- GitHub Actions
- Prometheus + Grafana
- OpenTelemetry
- Jaeger 开发环境 Trace
- Langfuse 作为后续增强项，不阻塞 MVP

## 5. Java 模块建议

```text
travel-server
├── identity       用户、登录、Token、角色
├── profile        长期旅行偏好
├── trip           旅行项目、成员、基础约束
├── planning       规划任务、状态机、进度、取消
├── itinerary      日程、活动、交通段
├── versioning     行程版本、差异、回滚
├── sharing        只读分享链接和访问控制
├── messaging      Outbox、RabbitMQ、幂等消费
├── provider       Agent 与第三方服务边界
└── infrastructure 数据库、Redis、安全、监控
```

按业务功能组织代码，避免全局 `controller/service/mapper` 目录导致模块边界失效。

## 6. Python 模块建议

```text
agent-service
├── api             健康检查、内部管理、评测接口
├── worker          RabbitMQ 消费与任务生命周期
├── workflow        LangGraph 图、节点和状态
├── providers       LLM、地图、天气、知识库适配器
├── acquisition     官方来源注册、受控采集、快照与审核
├── retrieval       文档导入、切分、召回、引用
├── ranking         POI 过滤与偏好评分
├── optimization    OR-Tools 建模和路线优化
├── validation      约束校验和冲突解释数据
├── evaluation      数据集、Runner、指标
└── infrastructure 数据库、消息、缓存、Trace
```

当前 Python 已落地 `worker`、`providers`、`retrieval` 和 `acquisition` 的第一版边界；`workflow`、`ranking`、`optimization`、`validation`、`evaluation` 与统一 `infrastructure` 仍是目标结构，不应在路线图中误写成已完成能力。

## 7. 主要运行链路

```text
前端提交需求
  -> Java 事务保存 PlanningTask + OutboxEvent
  -> Outbox Publisher 投递 RabbitMQ Command
  -> Python Worker 消费并恢复/创建 AgentRun
  -> Agent 调用模型、知识库、地图和优化器
  -> Python 发布 Progress/Completed/Failed Event
  -> Java 消费、持久化任务事件和行程版本
  -> Java 通过 SSE 推送前端
```

## 8. 消息拓扑

```text
trip.command.exchange
  ├── planning.create.queue
  ├── planning.replan.queue
  └── planning.cancel.queue

trip.event.exchange
  ├── planning.progress.queue
  ├── planning.completed.queue
  └── planning.failed.queue

trip.dead-letter.exchange
  └── planning.dead-letter.queue
```

- Command 表示要求某个服务执行动作。
- Event 表示某件事已经发生。
- 投递语义是 at-least-once，消费者必须幂等。
- 不声称实现基础设施意义上的 exactly-once。

## 9. 部署配置

### 本地开发

16 GB 内存设备可以运行核心 Docker Compose，但应按 profile 启动：

- `core`：PostgreSQL、Redis、RabbitMQ、Java、Python、Nginx。
- `observability`：Prometheus、Grafana、Jaeger，需要时单独开启。
- 前端开发期可在宿主机运行 Vite，减少容器资源消耗。

### 云端演示

- 推荐 4 核 8 GB 运行完整核心环境。
- 2 核 4 GB 只运行核心服务，完整监控保留在本地。
- V1 可使用自建 PostgreSQL、Redis 和 RabbitMQ；流量增长后再评估托管服务。
- 云端成本取决于访问量、监控保留周期和外部 Provider 调用量，应通过指标和配额持续控制。

## 10. 仓库与公开安全

- 仓库可以公开发布，但公开内容必须经过敏感信息检查。
- `.env`、真实 Token、API Key、云凭证和个人数据必须加入忽略列表。
- 提供 `.env.example`，只包含变量名和无效示例。
- Demo 数据必须脱敏，不保存真实用户对话。
- CI 使用 GitHub Secrets，不在工作流日志输出敏感变量。
