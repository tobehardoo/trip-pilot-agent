# 可靠性、安全与可观测性

## 1. Transactional Outbox

Java 创建规划任务时，在同一个数据库事务中写入：

- `planning_task`
- `outbox_event`

后台 Publisher 扫描未发送事件并投递 RabbitMQ。发送确认后更新 Outbox 状态。第一版使用定时扫描即可，Debezium CDC 只作为未来扩展。

该设计解决“数据库提交成功但消息未发送”的一致性问题。

## 2. 幂等与消息语义

- RabbitMQ 采用 at-least-once 投递。
- Python 命令消费者使用 `taskId + taskType + itineraryVersion` 作为幂等业务键。
- Java 结果消费者使用事件 ID 和任务 ID 去重。
- 数据库唯一约束是最终防线。
- 重复完成事件不得创建多个相同版本。

正确表述是“至少一次投递 + 幂等消费实现业务效果的最终一致性”，不是基础设施 exactly-once。

## 3. 重试分类

| 错误 | 处理 |
|---|---|
| 地图或模型超时、限流 | 指数退避重试 |
| RabbitMQ 重复消息 | 幂等返回 |
| LLM JSON 非法 | Schema 修复一次 |
| POI 无结果 | 修改关键词或扩大范围 |
| OR-Tools 无可行解 | 约束冲突分析 |
| API Key 无效 | 直接失败，不重试 |
| 用户取消 | 协作式终止 |
| 超过最大瞬时错误次数 | 进入死信队列 |

每次重试记录原因、次数、延迟和最终结果。

## 4. 外部服务治理

- 所有 HTTP 调用设置连接和读取超时。
- 按 Provider 和接口设置并发上限。
- 限流、指数退避和熔断参数通过配置管理。
- 只有幂等、可安全重试的操作自动重试。
- Provider Schema 变化作为非瞬时错误报警。
- 真实模式失败时不自动伪装成 Demo 数据。

## 5. Redis 职责

- 热门 POI 和路线矩阵缓存。
- 地图、天气和模型 API 限流计数。
- 用户每日任务和 Token 配额。
- 短期会话与快速任务锁。
- 多实例 SSE 通知或事件广播。

Redis 不作为业务事实主库。锁失效时仍依赖数据库版本和唯一约束。

## 6. SSE 可靠性

- 用户可见任务事件持久化到 `planning_task_event`。
- 事件 ID 单调递增或可稳定排序。
- 浏览器使用 `Last-Event-ID` 恢复。
- Redis Pub/Sub 可以用于多实例实时广播，但不作为历史恢复依据。
- 客户端定期心跳并处理认证过期。

## 7. 认证与授权

- 用户名或邮箱 + 密码。
- 密码使用可靠的自适应哈希算法。
- 短期 Access Token。
- 可轮换 Refresh Token，数据库只保存哈希。
- 当前 Web M1 将 Access Token 保存在内存，将 Refresh Token 限制在标签页级 `sessionStorage`；401 时只刷新并重试一次，退出登录会撤销服务端 Token。
- 公开部署前必须把 Refresh Token 迁移到 `HttpOnly + Secure + SameSite` Cookie，避免任何长期 Bearer Token 暴露给 JavaScript。
- 角色：`USER`、`OPERATOR`、`ADMIN`。
- 运维页只允许 `OPERATOR` 和 `ADMIN`。
- 死信重放等高风险操作只允许 `ADMIN`。
- 分享链接随机生成、可过期、可撤销，数据库保存 Token 哈希。
- 匿名分享只读，不能修改行程。

短信、微信和 OAuth 登录列为后续 TODO。

### M1 数据库迁移发布约束

- 当前 M1 按单实例停机迁移设计，不支持旧版与新版 Java 实例同时滚动写库。
- 发布 V3 前先停止旧 Java 实例；迁移会对 `business.trip_constraint` 获取排他锁，回填空 `pace` 后再增加非空和枚举约束。
- `NULL pace` 有明确默认值，会迁移为 `BALANCED`；未知非空值不会被静默覆盖，V3 会失败并保留原数据，需人工确认后重试。
- 进入多实例部署前，把数据库变更改为 expand/contract 流程，并在收紧约束前确认旧写路径全部退出。

## 8. 公开仓库安全

- API Key 和云凭证只通过环境变量或 Secret 管理。
- 提供 `.env.example`，不提交 `.env`。
- 日志脱敏，不记录密码、Access Token、Refresh Token 或完整密钥。
- 对用户自由文本设置合理长度上限。
- 运维接口与普通用户接口严格隔离。
- Demo 数据脱敏并经过人工检查。
- 依赖和容器镜像在 CI 中进行基础漏洞扫描，具体工具在实现阶段选择。

## 9. 费用和资源保护

- 每个用户每天最大规划次数。
- 单次任务最大模型调用次数。
- 最大自动重规划和修复轮数。
- 最大输入、输出 Token。
- 最大工具调用次数和任务总时长。
- 达到预算后明确停止，不继续隐式消费。
- 运维页按任务、用户、模型和日期统计费用。

## 10. Trace 关联

统一 `traceId` 贯穿：

```text
Browser
 -> Java HTTP
 -> Outbox
 -> RabbitMQ
 -> Python Agent
 -> LLM / Map / Weather / RAG / OR-Tools
 -> RabbitMQ
 -> Java
 -> SSE
```

消息信封传递 `traceId`、`taskId`、`tripId` 和 `runId`。

## 11. 结构化日志

日志至少包含：

```text
timestamp
level
service
traceId
taskId
tripId
runId
agentStep
provider
durationMs
retryCount
errorCode
```

模型输入输出默认只保存摘要、哈希或脱敏版本。需要完整内容用于评测时，使用单独受控存储和明确开关。

## 12. 指标

### 系统指标

- HTTP 延迟和错误率。
- JVM、Python 进程 CPU 和内存。
- 数据库连接池。
- Redis 命中率。
- RabbitMQ 队列深度和消费者积压。

### Agent 指标

- 各节点耗时和失败率。
- 模型 Token、费用、重试和降级。
- 工具调用成功率、延迟和缓存命中。
- OR-Tools 求解耗时、可行解率和超时率。

### 业务指标

- 规划成功率。
- 结构化追问率。
- 用户取消率。
- 局部重规划成功率。
- 版本回滚率。

## 13. 可观测性组合

- Prometheus + Grafana：指标。
- OpenTelemetry：跨服务 Trace 标准。
- Jaeger：开发环境调用链。
- 容器标准输出或结构化文件日志：V1 日志方案。
- Langfuse：Agent Trace 增强 TODO，不阻塞 MVP。

第一版不同时引入 ELK、Loki、Tempo 等完整日志平台。
