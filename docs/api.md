# 接口与契约

本文记录当前维护的接口语义。具体字段以后端类型、数据库迁移和 `contracts/` 中的 JSON Schema 为准；本文负责说明跨服务约定和兼容规则。

## REST API

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
| `planning-completed-event-v6.schema.json` | Python -> Java | 当前稳定规划完成事件，包含事实影响 |
| `planning-completed-event-v7.schema.json` | Python -> Java | 通勤成本和扩展交通模式的过渡契约，需随实现一起完成最终验证 |
| `planning-failed-event-v1.schema.json` | Python -> Java | 规划失败 |

兼容规则：

- 消息必须包含 `schemaVersion`。
- 新增可选字段保持向后兼容。
- 删除必填字段或改变字段语义需要升级主版本。
- 旧版本 Schema 保留在仓库作为历史参考，代码只处理活跃版本。
- Demo 模式和真实 Provider 模式使用同一契约，不能使用前端模拟进度代替 Worker 事件。

## SSE 协议

规划事件持久化后通过 SSE 推送给浏览器。浏览器断线后使用 `Last-Event-ID` 恢复遗漏事件。

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

## 历史详稿

- [原接口与消息契约详稿](archive/api.md)
- [规划进度契约原文](archive/planning-progress.md)
- [遗留消息契约说明](../contracts/messaging/legacy/README.md)
