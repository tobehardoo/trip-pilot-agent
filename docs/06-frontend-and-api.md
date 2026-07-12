# 前端体验与接口契约

## 1. 产品界面原则

- 地图和时间轴是主体，聊天是辅助入口。
- 前端重点是可视化规划、快速修改和差异确认，不做传统后台菜单堆叠。
- 优先桌面规划体验；移动端至少支持查看、分享和基础操作。
- 动态内容必须有稳定尺寸和加载状态，避免地图、时间轴和按钮布局跳动。
- 不展示模型隐藏推理，只展示业务进度、来源和冲突依据。

## 2. 页面范围

- 登录与注册。
- 我的旅行列表。
- 创建旅行和结构化需求收集。
- 行程规划工作台。
- 行程历史版本。
- 只读分享页。
- 内部 Agent 运维与评测页。

## 3. 核心工作台

```text
┌────────────────────────────────────────────────────┐
│ 广州 4 日游 | 预算 | 天气 | 当前版本 | 重新规划     │
├───────────────────────────┬────────────────────────┤
│                           │ Day 1  Day 2  Day 3     │
│                           ├────────────────────────┤
│          高德地图          │ 09:00 活动             │
│     POI、路线、选中状态    │ 12:00 用餐时间窗        │
│                           │ 14:00 活动              │
│                           │ 拖拽、锁定、删除         │
├───────────────────────────┴────────────────────────┤
│ Agent 状态 / 冲突提示 / 辅助聊天 / 修改要求         │
└────────────────────────────────────────────────────┘
```

## 4. 关键交互

- 时间轴选中活动时，地图定位对应 POI 和路线段。
- 地图选中 POI 时，时间轴滚动并高亮对应活动。
- 拖拽活动生成明确的 `MOVE_ACTIVITY` 命令。
- 删除、锁定和修改预算都先显示影响范围。
- 局部重规划完成后展示旧版与新版差异。
- POI 详情显示数据来源、更新时间和是否估算。
- Agent 追问渲染成数字、日期、单选、多选等合适控件。
- 任务运行时支持取消，不能重复提交相同修改。
- 失败状态显示可操作的重试、修改条件或返回入口。

## 5. API 入口

浏览器只访问 Java 服务。Python Agent 不直接向公网暴露业务 API。

核心 REST 资源建议：

```text
/api/auth/**
/api/users/me/preferences
/api/trips
/api/trips/{tripId}/constraints
/api/trips/{tripId}/planning-tasks
/api/planning-tasks/{taskId}
/api/planning-tasks/{taskId}/events
/api/planning-tasks/{taskId}/clarifications
/api/planning-tasks/{taskId}/cancel
/api/trips/{tripId}/itinerary
/api/trips/{tripId}/versions
/api/trips/{tripId}/commands
/api/share-links
/api/ops/planning-tasks
/api/ops/evaluations
```

具体 URL 在 OpenAPI 设计阶段可以调整，但资源边界不变。

## 6. 异步任务 API

创建任务：

```text
POST /api/trips/{tripId}/planning-tasks
Idempotency-Key: UUID
```

成功返回：

```text
HTTP 202 Accepted
taskId
taskStatus = QUEUED
eventStreamUrl
```

前端随后订阅 SSE：

```text
GET /api/planning-tasks/{taskId}/events
Accept: text/event-stream
```

## 7. SSE 事件

每个事件包含：

```text
eventId
taskId
eventType
schemaVersion
payload
createdAt
```

浏览器重连携带 `Last-Event-ID`。Java 从 `planning_task_event` 补发遗漏事件，然后继续实时推送。

## 8. 消息和接口契约

- HTTP 使用 OpenAPI。
- RabbitMQ 事件使用 JSON Schema，时间允许时补充 AsyncAPI。
- Java DTO、Python Pydantic Model 和前端 TypeScript 类型基于同一契约验证。
- 事件包含 `schemaVersion`。
- 增加可选字段保持向后兼容；破坏性变更升级 Schema 版本。
- 前端类型优先由 OpenAPI 生成，减少手写重复 DTO。

事件信封示例：

```json
{
  "eventType": "PLANNING_COMPLETED",
  "schemaVersion": 1,
  "eventId": "uuid",
  "taskId": "uuid",
  "occurredAt": "ISO-8601",
  "payload": {}
}
```

## 9. 并发与错误体验

- 修改命令携带当前行程版本。
- 版本冲突返回 `409 Conflict`，前端提供刷新和差异比较。
- 限流返回明确等待时间，不静默失败。
- Agent 需要补充信息时进入结构化追问状态。
- Agent 发现硬约束冲突时展示事实、影响和可选方案。
- Demo 模式、估算数据和外部服务降级必须有清晰标识。

## 10. 运维页

运维页展示：

- 任务状态、当前节点、耗时和重试。
- 模型、Token、估算成本。
- 工具调用、缓存命中和错误分类。
- 取消、重试和死信重放操作。
- Agent 评测运行与模型对比。

原始 API Key、完整敏感输入、系统 Prompt 和隐藏推理不展示。
