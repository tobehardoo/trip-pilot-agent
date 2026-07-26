# 接口与消息契约

## REST API 设计

### 资源模型

```
/api/auth/register          POST    注册
/api/auth/login             POST    登录 → JWT + Refresh Cookie
/api/auth/refresh           POST    刷新 Access Token
/api/auth/logout            POST    撤销 Refresh Token

/api/trips                  GET     我的旅行列表
/api/trips                  POST    创建旅行
/api/trips/{tripId}         GET     旅行详情（含约束）
/api/trips/{tripId}/constraints                 PUT     更新约束

/api/trips/{tripId}/planning-tasks          POST    创建规划任务
/api/trips/{tripId}/itinerary/replans       POST    创建局部重规划任务
/api/planning-tasks/{taskId}                DELETE  取消任务
/api/planning-tasks/{taskId}/events         GET     SSE 事件流

/api/trips/{tripId}/itinerary                  GET     当前行程
/api/trips/{tripId}/itinerary/edits/preview    POST    预览编辑影响
/api/trips/{tripId}/itinerary/edits            POST    应用编辑
/api/trips/{tripId}/itinerary/versions         GET     版本列表
/api/trips/{tripId}/itinerary/versions/{id}    GET     指定版本详情
/api/trips/{tripId}/itinerary/diffs            GET     两个版本的结构化差异
/api/trips/{tripId}/itinerary/rollbacks        POST    回滚并创建新版本

/api/trips/{tripId}/guide-imports           GET     攻略导入列表
/api/trips/{tripId}/guide-imports           POST    导入 URL、正文或城市情报
/api/trips/{tripId}/guide-imports/{id}      PUT     启用或停用攻略来源

/api/city-sources                           GET     查询已注册城市来源
/api/city-sources/{id}                      PUT     审核、启用或停用来源
/api/trips/{tripId}/city-intelligence       GET     刷新状态和最后成功快照摘要
/api/trips/{tripId}/city-intelligence/refreshes POST 手动触发幂等刷新
```

`GET /api/city-sources` 支持 `cityCode`、`enabled`、`reviewStatus` 过滤。更新来源时请求体
包含 `enabled`、`reviewStatus`、可选 `reviewNote` 与 `expectedVersion`；并发版本不匹配
返回 `409 CITY_SOURCE_VERSION_CONFLICT`，成功更新记录审核人、审核时间并递增版本。

攻略导入响应保留 V1.2 的 `facts`，并追加 `normalizedDocument`、`trustedFacts`、
`rejectedFacts`、`factMergeDecisions` 与 `modelExtraction`。`trustedFacts` 包含
`normalizedValue`、证据跨度、核验/过期时间、来源可靠性和
`hardConstraintEligible`；Java 会再次校验证据跨度和强约束资格后才持久化。

### 认证

所有 `/api/**` 请求（除 `/api/auth/**` 和 `/api/health` 外）需要 `Authorization: Bearer <accessToken>`。

Access Token 过期后，前端用 Refresh Cookie 调用 `/api/auth/refresh` 获取新 Access Token。如果 Refresh Token 也过期或已撤销，前端跳回登录页。

### 幂等性

创建规划或局部重规划任务时，前端携带 `Idempotency-Key: <UUID>` 头。服务端通过
`(trip_id, idempotency_key)` 去重；同一旅行内，相同幂等键的重复请求返回已存在的任务。
调用方不得在 CREATE 与 REPLAN 之间复用同一幂等键。服务端会校验任务类型；REPLAN
还会校验基线版本与规范化后的日期集合，不一致时返回 `409 IDEMPOTENCY_KEY_REUSED`。

回滚请求同样要求 `Idempotency-Key`，并在请求体携带 `baseVersionId` 与
`targetVersionId`。同一键重复提交返回第一次创建的新版本；键相同但目标不同返回
`409 IDEMPOTENCY_KEY_REUSED`。当前版本已变化时返回 `409 ITINERARY_VERSION_CONFLICT`。

## MQ 消息契约

### 命令（Java → Python）

```
trip.command.exchange
├── planning.create  (routing key)
│   契约: planning-create-command-v3.schema.json
│   载荷: tripSnapshot + constraints + planningContextSnapshot + traceId
│
├── planning.replan  (routing key)
│   契约: planning-replan-command-v1.schema.json
│   载荷: baselineVersionId + impactedDates + tripSnapshot + traceId
│
└── planning.cancel  (routing key)
    契约: planning-cancel-command-v1.schema.json
    载荷: taskId + traceId

city-intelligence.refresh
    契约: city-intelligence-refresh-command-v1.schema.json
    载荷: refreshId + tripId + city + tripDates + sourceIds + idempotencyKey
```

### 事件（Python → Java）

```
trip.event.exchange
├── planning.completed  (routing key)
│   契约: planning-completed-event-v5.schema.json
│   版本演进:
│     v1: Demo 行程（无坐标）
│     v2: AMAP 行程（含 providerPoiId, coordinates）
│     v3: 增加 transitLegs（步行）
│     v4: 增加 knowledgeEvidence
│     v5: 交通段模式从 WALKING 扩展到 WALKING|DRIVING
│     v6: 增加 planningFactImpacts 与事实诊断摘要
│
└── planning.failed  (routing key)
    契约: planning-failed-event-v1.schema.json
    载荷: taskId + errorCode + conflictReasons + relaxationSuggestions
```

### 契约版本化策略

- 消息包含 `schemaVersion` 字段，消费者根据版本分支处理
- 新增可选字段不升级主版本（向后兼容）
- 删除必填字段或修改字段语义升级主版本
- 旧版本 Schema 保留在仓库作为历史参考，代码只处理活跃版本

### 活跃契约

- `planning-completed-event-v5.schema.json`（V1.2 兼容读取）
- `planning-completed-event-v6.schema.json`（规划事实影响，V1.3 写入格式）
- `planning-create-command-v3.schema.json`（完整约束+不可变城市情报快照）
- `city-intelligence-refresh-command-v1.schema.json`
- `planning-cancel-command-v1.schema.json`
- `planning-replan-command-v1.schema.json`
- `planning-failed-event-v1.schema.json`

### 遗留契约（仅历史参考）

- `planning-completed-event-v1/v2/v3.schema.json`
- `planning-create-command-v1.schema.json`
- `planning-create-command-v2.schema.json`

### PlanningContextSnapshot V3

快照包含 `snapshotId`、`schemaVersion`、旅行与任务 ID、城市、旅行日期、生成时间、
来源、采用事实、冲突决策、排除事实、刷新诊断和 stale 状态。事实包含可靠性、
`checkedAt`、`expiresAt`、适用日期、证据与结构化值。创建任务后快照不可更新；同一任务
重投递必须字节语义等价。Python Worker 不得用城市名重新抓取或读取 Java 业务表。

## SSE 协议

### 为什么用 SSE 而不是 WebSocket

规划进度推送是**单向**的——服务端向浏览器推送事件，浏览器不需要向服务端发送实时消息（用户操作通过常规 REST 调用完成）。这种场景下 SSE 比 WebSocket 更合适：

- **协议简单**。SSE 是标准 HTTP 协议，不需要升级连接、不需要额外的帧格式。Nginx 和代理服务器天然支持。
- **自动重连**。浏览器内置 SSE 的断线重连机制，配合 `Last-Event-ID` 头可以精确恢复遗漏事件。
- **单向推送不需要双向通道**。WebSocket 的双向能力在这里是多余的——用户编辑行程用
  `POST /api/trips/{tripId}/itinerary/edits/preview`，不需要在 WebSocket 上发消息。
- **事件持久化**。规划事件存入 `planning_task_event` 表，SSE 断线后从数据库补发——这比 WebSocket 的会话级消息更可靠。

如果未来需要双向实时交互（例如多人协作编辑），再评估 WebSocket。

### 协议格式

```
GET /api/planning-tasks/{taskId}/events
Accept: text/event-stream

event: planning-task-event
id: 42
data: {"eventId":42,"eventType":"POI_SEARCHING","payload":{...}}

event: planning-task-event
id: 43
data: {"eventId":43,"eventType":"PLAN_GENERATED","payload":{...}}
```

- 每个事件包含递增的 `eventId`，浏览器用 `Last-Event-ID` 头恢复
- 服务端从 `planning_task_event` 表补发遗漏事件，然后继续实时推送
- 连接空闲时发送心跳注释行（`: heartbeat`），防止代理超时断开
- 任务完成/失败后服务端主动关闭 SSE 连接，前端据此停止重连

## 错误响应

```json
{
  "error": "VERSION_CONFLICT",
  "message": "行程已被修改，请刷新后重试",
  "details": {
    "yourVersion": 3,
    "currentVersion": 5
  }
}
```

- `401` — Access Token 过期或缺失
- `403` — 无权访问该资源（不是你的旅行）
- `409` — 版本冲突，需要刷新
- `429` — 触发限流，等待 Retry-After 秒数

## 进一步阅读

- [系统架构设计](architecture.md) — 消息拓扑和投递语义的完整设计
- [规划算法与 Agent](planning.md) — 规划命令和事件的业务含义
- [数据库设计](database.md) — 任务事件表的持久化设计
