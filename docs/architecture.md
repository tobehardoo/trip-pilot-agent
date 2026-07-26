# 系统架构设计

## 为什么是模块化单体而不是微服务

TripPilot 的核心业务——旅行规划——是一个强一致性的状态机：用户创建旅行、提交约束、异步生成行程、编辑活动、触发局部重规划、比较版本差异。这些操作共享同一个事务边界（用户—旅行—行程版本），天然适合单体中的模块化隔离。

选择模块化单体的具体原因：

1. **事务边界统一**。规划任务创建时需要同时写入 `planning_task`、`planning_task_event` 和 `outbox_event` 三张表，规划完成时需要原子性更新任务状态、创建行程版本、持久化活动和交通段。分拆为微服务意味着放弃数据库事务，改为最终一致性和补偿事务——在 V1 阶段这会显著增加复杂度而收益为零。

2. **部署运维简单**。V1 只需要 4 核 8 GB 即可运行完整的核心环境。维护 6-8 个微服务和对应的 CI/CD、服务发现、配置中心、分布式追踪，对于当前规模是过度设计。

3. **未来可演进**。代码按 `domain/` 包隔离，ArchUnit 或 Spring Modulith 可以校验模块边界。当某个模块真正需要独立扩展时（例如规划 Worker 的 CPU 密集计算），它可以被提取为独立服务而不影响其他模块。

## 为什么 Java + Python 两种语言

这不是为了展示多语言能力，而是因为两种语言在 TripPilot 中承担根本不同的职责：

**Java（业务事实的持有者）**负责：
- 用户、认证、权限——需要成熟的 Spring Security 生态
- 旅行、约束、行程版本——需要强事务保证和外键约束
- 规划任务状态机和幂等消费——需要可靠的数据库事务
- SSE 事件推送——需要与数据库事务协调

**Python（规划计算的执行者）**负责：
- 高德 POI 和路线 API 调用——Python 的异步 HTTP 生态（httpx、aio-pika）更轻量
- 候选 POI 过滤和偏好评分——需要灵活的数据处理
- OR-Tools 约束求解——Google OR-Tools 的 Python 绑定最成熟
- pgvector 向量检索——Python 的嵌入模型生态最完整
- 城市知识采集和处理——Python 的 HTML 解析和文本处理能力

两种语言通过 **RabbitMQ 消息队列**和**版本化 JSON Schema 契约**通信。Java 通过 Transactional Outbox 保证消息可靠投递，Python 通过幂等消费保证重复消息不影响业务结果。双方共享一个 PostgreSQL 实例但使用不同 Schema（`business` vs `agent`），保持逻辑数据所有权。

这本质上是**两个部署单元、两种语言、一个数据库、一套消息契约**的架构。

## V1.3 可信城市情报边界

V1.3 不新增微服务，也不让规划 Worker 在求解过程中访问网页。动态事实按以下单向数据流
进入规划：

```text
人工审核的城市来源注册表（Java / business）
  → Java 创建刷新任务并通过现有 Outbox + RabbitMQ 投递
  → Python Agent API 抓取、规范化、规则/模型候选抽取
  → Schema 与 FactValidator 拒绝无证据或非法候选
  → Java 复核来源身份并持久化旅行级事实、冲突和刷新诊断
  → 创建规划任务前按类别 TTL 检查，必要时限时刷新
  → Java 冻结 PlanningContextSnapshot V3
  → Python Worker 只消费快照并产生 PlanningFactImpact
  → Java 将影响记录随不可变行程版本持久化
```

责任边界：

- Java 拥有城市来源注册、审核/启停、旅行刷新状态、有效事实、合并决策、规划快照、
  版本差异、回滚与审计。
- Python Agent API 拥有抓取与规范化实现、规则抽取器、受限模型抽取器以及抽取侧校验；
  它返回候选和诊断，不直接写 `business` Schema。
- Python Worker 只读取命令中的冻结快照；后续 Provider 刷新不能改变已创建任务的输入。
- Redis 仅用于 Provider 缓存或短期并发协调；最后成功事实与刷新结果必须落 PostgreSQL。

创建旅行后的预热使用现有 Outbox，失败不回滚旅行。创建规划任务前的刷新采用有上限的等待：
高影响类别刷新失败时使用最后成功事实并标记 `stale`，没有历史事实时继续规划并返回明确
诊断，不因单个 Provider 故障伪造实时成功。

## 为什么用异步任务模型而不是同步 HTTP

旅行规划的执行链路包括：高德 POI 搜索（多次）→ 候选去重和排序 → 高德路线查询（多次）→ OR-Tools 约束求解 → pgvector 知识检索。在真实模式下，单次规划可能需要 10-30 秒。

如果使用同步 HTTP：
- 浏览器需要维持一个长时间打开的连接
- 网络中断意味着规划结果丢失
- 用户无法同时创建多个规划任务
- 前端需要处理超时重试的复杂逻辑

异步任务模型解决了这些问题：

```
前端 POST 创建任务 → HTTP 202 Accepted（秒级返回）
    ↓
Transactional Outbox → RabbitMQ → Python Worker
    ↓
SSE 事件流 → 前端实时显示进度
```

- **HTTP 请求快速返回**，前端拿到 `taskId` 后订阅 SSE
- **MQ 保证任务可靠传递**，Worker 重启也不丢失任务
- **状态机维护生命周期**：QUEUED → RUNNING → COMPLETED / FAILED / CANCELLED
- **SSE 提供用户反馈**，断线后通过 `Last-Event-ID` 补发遗漏事件

## 为什么用 Transactional Outbox 而不是直接发 MQ

如果 Java 在数据库事务中写入 `planning_task` 后直接调用 RabbitMQ 客户端发送消息，存在不一致风险：

- 数据库事务提交成功，但 RabbitMQ 发送失败 → 任务创建了但 Worker 永远不知道
- RabbitMQ 发送成功，但数据库事务回滚 → Worker 收到消息但数据库中没有对应任务

Transactional Outbox 将消息写入与业务数据放在同一个数据库事务中：

```sql
BEGIN;
  INSERT INTO planning_task (...);
  INSERT INTO outbox_event (...);  -- 同一事务
COMMIT;
```

后台 `OutboxPublisherJob` 定时扫描未发送的 Outbox 记录，逐条投递到 RabbitMQ，确认后更新状态。

这保证了**数据库状态和消息投递的最终一致性**：只要数据库事务提交成功，消息最终一定会被投递。代价是消息投递有几秒延迟——对于旅行规划这种分钟级的异步任务，这是完全可接受的。

## 消息拓扑设计

```
trip.command.exchange
├── planning.create.queue   → Python Worker（绑定 planning.create 与 planning.replan）
├── city-intelligence.refresh.queue → Java 刷新消费者（调用 Python Agent API）
└── planning.cancel.queue   → Python Worker（独立控制通道）

trip.event.exchange
├── planning.progress.queue  → （预留，当前通过 SSE 直推）
├── planning.completed.queue → Java Consumer
└── planning.failed.queue    → Java Consumer

trip.dead-letter.exchange
└── planning.dead-letter.queue → 运维处理
```

设计理由：
- **Command 和 Event 分离**：Command 表示「要求执行动作」，Event 表示「某事已经发生」。不同交换机、不同消费语义。
- **计算与控制分队列**：CREATE 与 REPLAN 共用顺序消费的计算队列；CANCEL 使用独立
  控制通道，避免被长时间规划任务阻塞。
- **死信队列作为安全网**：超过最大重试次数的消息进入死信，运维可以查看和手动重放。

投递语义是 at-least-once，消费者必须允许重复投递。Java 消费者通过持久化的 `eventId`
去重；Python 使用确定性事件 ID，Java 在写入不可变版本前再次核对任务、旅行、
`traceId` 和基线版本。Python 端目前没有独立的持久化幂等表，因此不能声称 Worker
重启后已经实现严格的消费去重。

城市刷新消息携带 `messageVersion`、刷新 ID 和幂等键。Java 消费者先锁定刷新记录，
只允许 `PENDING/RETRYING` 状态进入执行，成功与失败都写结构化诊断；重复或乱序消息不会
覆盖更新版本的成功快照。

## 安全设计

**认证**：JWT Access Token（短期，内存持有）+ HttpOnly Refresh Cookie（长期，不可被 JavaScript 读取）。Access Token 过期后前端用 Refresh Cookie 无感轮换，退出登录时服务端撤销 Refresh Token 并清除 Cookie。

**密码**：BCrypt 哈希存储，不记录明文。

**数据隔离**：所有用户数据查询必须带 `ownerId`，服务层通过 `TripService` 验证所有权后返回数据。

**外部资源访问**：
- 用户提交的攻略 URL 经过 DNS 公网校验、同域重定向检查、响应大小限制
- 攻略抽取 API 只在 Compose 私有网络开放，使用服务间令牌
- 不会登录站点、绕过验证码或批量爬取

**公开仓库安全**：
- `.env`、真实 Token、API Key 不提交
- `.env.example` 只包含变量名和无效示例
- Demo 数据脱敏
- CI 使用 GitHub Secrets

## 可观测性

**Prometheus** 当前抓取 Spring Boot 暴露的 JVM、HTTP 和数据库连接池等指标。任务成功率、
队列积压等业务 SLI 仍属于后续运营能力，见[产品路线图](roadmap.md)。

**结构化日志**：每条日志携带 `traceId`、`taskId`、`tripId`，可以在 Java 和 Python 之间关联。

**跨服务关联**：Java 创建任务时生成 `traceId`，并随 Outbox、RabbitMQ、Python 结果事件
回传，用于日志关联。当前没有部署分布式追踪后端，不能把该关联 ID 描述成完整 Trace。

## 部署拓扑

```
Nginx (443/80)
  ├── Vue 静态资源
  ├── /api/* → Spring Boot (8080)
  └── /actuator/* → 仅本地回环

Spring Boot (8080)
  ├── PostgreSQL:5432 (business schema)
  ├── Redis:6379
  └── RabbitMQ:5672

Python Worker (8000)
  ├── PostgreSQL:5432 (agent schema)
  ├── Redis:6379
  ├── RabbitMQ:5672
  └── 高德 API / 模型 API

PostgreSQL 16 (5432)
  ├── business schema (Java 拥有)
  ├── agent schema (Python 拥有)
  └── PostGIS + pgvector 扩展

Redis 7
RabbitMQ 3
Prometheus (9090, 仅本地回环)
```

本地开发单机 16 GB 可运行核心服务。云端演示推荐 4 核 8 GB。

## 进一步阅读

- [当前系统状态与 V1.4 规划](28-current-system-status-and-v1-4-plan.md) — 当前运行证据、
  已完成/未完成边界与未来两个版本

- [领域模型](domain.md) — 理解各领域的边界和聚合关系
- [规划算法与 Agent](planning.md) — 了解规划 Pipeline 和约束求解的设计
- [技术决策记录](decision-record.md) — 查看每个架构决策的完整背景和取舍
- [部署](deployment.md) — 实际的启动命令和环境变量配置
