# 接口与契约

## `PLANNING_COMPLETED` 版本状态（2026-07-30）

- [已验证] 唯一运行时完成事件是 v6：Python producer 发出 `schemaVersion: 6`，Java `PlanningCompletedEventParser` 接受 v1-v6；v7 事件会在字段解析前以“不支持的 schemaVersion”拒绝。
- [已验证] v6 可选 `providerProvenance` 是向后兼容扩展；历史 v6 无该字段时仍合法且表示“未记录”，消费者不得从顶层 provider 或子项来源补造 requested mode/fallback。
- [已验证] v6 的 Transit wire 字段仅包含端点索引、`WALKING|DRIVING`、距离、时长、provider、estimated 与 polyline；内部 `estimatedCost`/`costSource` 不会序列化进 v6。
- [文档声明] `planning-completed-event-v7.schema.json` 仅保留为草案，描述 Transit 成本和 `TRANSIT`/`TAXI` 扩展；它不是当前 Python -> Java 契约。
- [待确认] v7 启用必须在独立切片中完成 producer、consumer、数据库语义、Web 展示与双语言样例测试，不能通过仅修改 schema 或文档启用。

本文记录当前维护的接口语义。具体字段以后端类型、数据库迁移和 `contracts/` 中的 JSON Schema 为准；本文负责说明跨服务约定和兼容规则。

## REST API

### Provider 来源与降级

- `PROVIDER_MODE` 取值为 `DEMO_ONLY`、`REAL_ONLY` 或 `REAL_WITH_EXPLICIT_FALLBACK`。production 默认 `REAL_ONLY` 并要求服务端 `AMAP_WEB_SERVICE_KEY`；旧 `DEMO_MODE=true/false` 分别兼容映射到 Demo/严格真实，冲突与非法值启动失败。
- 行程、Activity 和 Transit 均保留 `provider`；路线还保留 `estimated`、距离、时长和 polyline。只有 `provider=AMAP` 且 `estimated=false` 的记录才可作为真实 AMap 路线证据。
- `REAL_ONLY` 不构造或调用 Demo；Provider 失败经有限重试后发布 failure v2。只有显式 fallback 模式且 `ProviderFallbackPolicy` 返回允许时，才能使用 Demo。
- 局部 route fallback 的成功结果顶层为 `MIXED`，目标 Transit 为 `DEMO/estimated=true`，其他来源保持 `AMAP`。completion v6 的 `providerProvenance` 包含 `requestedProviderMode`、`primaryProvider`、`actualProviders`、fallback 状态、reason 和结构化 operations；整单显式 fallback 使用 `PLANNING`/`REPLANNING` operation 且关联 ID 为 `null`。
- Route operation 包含稳定 `transitId/fromActivityId/toActivityId`、requested mode、actual provider、安全 error category/code 与 retry count。Java 完成事务把消息 ID 重映射为新版本数据库 UUID，再写入既有 `planning_task_event.payload` JSONB；无需新增迁移。
- 回退日志的稳定标记为 `planning_provider_fallback`，包含安全原因、retry count 和关联 ID。Provider Key、JWT、Cookie、完整请求/响应和堆栈不属于 API、事件或日志输出。

### 行程编辑幂等约定

适用于 `POST /api/trips/{tripId}/itinerary/edits` 和
`POST /api/trips/{tripId}/itinerary/edits/commit`。两者必须提供 UUID 格式的
`Idempotency-Key`。

- 相同 key 且业务语义相同的请求返回首次生成的行程版本，不新增版本；该结果不随之后的编辑而漂移。
- 请求比较使用只包含编辑业务字段的确定性 SHA-256 指纹：对象字段顺序不影响结果，批量 `edits` 的顺序会保留；字段缺失、`null`、空字符串和空数组是不同的输入状态。
- 相同 key 与不同指纹返回 `409 IDEMPOTENCY_KEY_CONFLICT`。历史记录中空白或 NULL 指纹同样返回该错误，客户端应生成新的 key 并在确认业务意图后再次提交。
- 并发相同 key 由数据库唯一约束仲裁；并发不同 key 而基线版本相同，仍可能返回 `409 ITINERARY_VERSION_CONFLICT`。

主要资源分组：

| 分组 | 用途 |
| --- | --- |
| Auth | 注册、登录、刷新、登出和会话恢复 |
| Trips | 旅行创建、读取、约束更新、搜索、分页、归档和恢复 |
| Planning Tasks | 创建规划、创建局部重规划、取消、读取状态和订阅事件 |
| Itinerary Versions | 当前行程、版本列表、版本差异、回滚和活动/交通编辑 |
| City Intelligence | 来源注册、刷新、事实、冲突和规划快照 |
| Guide Intelligence | 公开 URL、正文、TXT/Markdown 和分享正文导入 |
| Shares | 创建、读取、撤销和过期匿名只读分享 |
| Exports | 固定行程版本的 PDF 与 ICS 导出 |
| Diagnostics | 受保护失败任务诊断和安全幂等重试 |

所有用户私有资源必须通过所有权校验；匿名分享只读取分享 Token 指向的不可变版本，不暴露内部字段。

## 认证

- Access Token 使用 JWT，适合普通 API 请求。
- Refresh Token 使用 HttpOnly Cookie，并在刷新时轮换。
- 本机 HTTP 可设置 `REFRESH_COOKIE_SECURE=false`；生产 HTTPS 必须为 `true`。
- 内部服务调用和诊断入口使用独立强随机令牌，不复用用户凭据。

## 幂等与冲突

- 创建规划任务使用旅行内幂等键，重复请求返回已存在任务。
- 回滚和安全重试使用幂等键，重复请求返回第一次产生的结果。
- 行程编辑应携带幂等键和期望当前版本；目标不同但幂等键相同时返回冲突。
- 当前版本变化时返回 `409`，客户端需要刷新后重试。

## MQ 契约

活跃契约位于 `contracts/messaging/`：

| 契约 | 方向 | 说明 |
| --- | --- | --- |
| `planning-create-command-v3.schema.json` | Java -> Python | 创建规划，包含完整约束和冻结城市情报快照 |
| `planning-replan-command-v1.schema.json` | Java -> Python | 局部重规划，包含基线版本和受影响日期 |
| `planning-cancel-command-v1.schema.json` | Java -> Python | 协作式取消 |
| `city-intelligence-refresh-command-v1.schema.json` | Java -> Python | 城市情报刷新 |
| `planning-progress-event-v1.schema.json` | Python -> Java | 真实阶段进度 |
| `planning-completed-event-v6.schema.json` | Python -> Java | 当前稳定规划完成事件，包含事实影响、可选 Provider provenance 与可选 PlanEvaluation |
| `planning-completed-event-v7.schema.json` | —（未启用） | Transit 成本和扩展交通模式草案；不进入当前 Python 发布或 Java 消费路径 |
| `planning-failed-event-v2.schema.json` | Python -> Java | 当前唯一新写入失败事件，覆盖不可行、Provider 与内部失败 |
| `planning-failed-event-v1.schema.json` | Python -> Java（只读兼容） | 仅兼容历史 `NO_FEASIBLE_ITINERARY`，已废弃生产 |

兼容规则：

- 消息必须包含 `schemaVersion`。
- 新增可选字段保持向后兼容。
- 删除必填字段或改变字段语义需要升级主版本。
- 旧版本 Schema 保留在仓库作为历史参考，代码只处理活跃版本。
- Demo 模式和真实 Provider 模式使用同一契约，不能使用前端模拟进度代替 Worker 事件。
- v6 provenance 的 `actualProviders` 非空且与最终 Activity/Transit 来源一致；非法 mode/provider/fallback 组合被 Schema 或模型/parser 拒绝。历史 v6 缺失 provenance 仍可读取。
- v6 `evaluation` 使用独立 `schemaVersion=1` 和 `evaluatorVersion=rule-vN`，总分必须等于五维加权值并采用整数 half-up 舍入。create/replan 的新成功事件均携带 evaluation；历史 v6 缺失/null 时任务 API 返回 `null`，failure 事件不携带该字段。

## SSE 协议

规划事件持久化后通过 SSE 推送给浏览器。浏览器断线后使用 `Last-Event-ID` 恢复遗漏事件。

终态失败事件与 `GET /api/planning-tasks/{taskId}` 均可返回 `errorCode`、`errorCategory`、`retryable`、`provider`、`operation`、`retryCount`、`fallbackAttempted`、`fallbackSucceeded`、`safeMessage` 和可选 `safeProviderCode`。成功终态另可返回 requested/primary/actual providers、fallback reason、结构化 operations 和 `evaluation`。字段来自已持久化 task event payload，因此重连回放与任务查询语义一致；evaluation 内的 Transit/Activity ID 与持久化版本一致。历史成功事件缺失 provenance/evaluation 时相关字段为 `null`/缺失而非猜测值。

每个进度事件至少包含：

- `stage`：标准阶段名。
- `sequence`：任务内单调递增序列。
- `progress`：阶段边界进度，不按耗时虚构。
- `message`：用户可见状态。
- `occurredAt`：事件发生时间。
- `taskId`：任务标识。
- `statistics`：可选非负整数统计。

重复或乱序事件不得导致进度倒退；任务完成、失败或取消后，前端停止继续播放该任务。

## 错误响应

错误响应保持稳定结构：

```json
{
  "code": "ITINERARY_VERSION_CONFLICT",
  "message": "Current itinerary version changed. Refresh before retrying.",
  "details": {}
}
```

常见状态：

- `400`：请求格式、字段范围或业务约束非法。
- `401`：Access Token 缺失或过期。
- `403`：无权访问资源或诊断令牌无效。
- `404`：资源不存在或不属于当前用户。
- `409`：幂等键复用、版本冲突或活动任务冲突。
- `429`：限流，客户端应遵守 `Retry-After`。
- `500/502/503`：服务端或 Provider 暂时失败，前端可按场景重试。

真实 Provider 验收时，业务方应同时读取规划任务状态、完成/失败事件、`providerProvenance` 和行程来源；只有显式 `REAL_ONLY + actualProviders=[AMAP] + fallback=false` 才是本次纯真实证据。`MIXED` 表示最终数据同时包含 AMAP/DEMO；`DEMO` 需结合 requested mode 区分纯 Demo 与整单显式 fallback。历史无 provenance 事件只能称为未记录。不可行约束使用 `NO_FEASIBLE_ITINERARY`，例如预算冲突可在诊断冲突列表中以 `BUDGET_EXCEEDED` 表示。

## 历史详稿

- [原接口与消息契约详稿](archive/api.md)
- [规划进度契约原文](archive/planning-progress.md)
- [遗留消息契约说明](../contracts/messaging/legacy/README.md)
