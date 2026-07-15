# Phase 3 测试计划：异步规划命令最小闭环

## 范围

- Java 创建 `PlanningTask` 与 `Transactional Outbox`。
- 同一旅行只允许一个活动规划任务。
- `Idempotency-Key` 重放返回原任务且不重复创建 Outbox。
- Outbox 通过 RabbitMQ publisher confirm 进行至少一次投递。
- Python Worker 校验命令、调用 Demo Provider 并发布 `PLANNING_COMPLETED`。
- Command/Event v1 JSON Schema。

本阶段不包含 Java 消费完成事件、行程版本持久化和 SSE；这些属于下一条纵向切片。

## 必须覆盖

- 任务与 Outbox 在同一个 PostgreSQL 事务中写入。
- 非旅行所有者不能创建任务。
- 不同幂等键不能绕过活动任务唯一约束。
- Outbox 成功确认后标记 `SENT`，失败时记录错误并指数退避。
- RabbitMQ 消息持久化，携带 `messageId`、类型和 JSON 内容类型。
- Python 对未知字段和非法 Schema 拒绝并进入死信。
- Python 只有在完成事件发布成功后才确认命令。
- 完成事件发布失败时重新入队命令。
- 重复命令产生相同 `eventId` 与 `runId`。
- Java 真实消息可被 Python Pydantic Model 解析。

## 质量门槛

- Java 与 Python 自动化测试全部通过。
- Java 行覆盖率继续高于 80%。
- Ruff 检查通过。
- PostgreSQL、RabbitMQ、Java 与 Python 的真实跨服务冒烟通过。
- 不依赖模型或地图 Key，不产生外部调用费用。

## 执行结果

截至 2026-07-15 已完成核心闭环和独立审查收口：

- 创建任务 API、用户隔离、事务回滚、并发幂等和活动任务唯一约束通过 PostgreSQL 集成测试。
- 行程与约束由单条 JOIN 查询生成一致快照，并通过并发更新回归测试。
- Outbox 每条事件在独立事务内完成锁定、确认和状态更新；成功、失败退避及批次上限通过单元测试。
- 持久 JSON 消息与 publisher confirm 通过 RabbitMQ Testcontainers 测试。
- Python 严格校验字段别名、类型、长度、时区和基线版本；Demo Provider 与 ack/reject/nack 顺序通过自动化测试。
- 临时 PostgreSQL/RabbitMQ 上完成真实 HTTP -> Outbox -> RabbitMQ -> Python -> 完成事件冒烟。
- Java 46/46 通过，JaCoCo 行覆盖率 90.79%；Python 18/18 与 Ruff、`uv lock --check` 通过。
