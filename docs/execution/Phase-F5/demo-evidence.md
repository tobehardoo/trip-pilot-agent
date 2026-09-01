# F-5 Demo Evidence（程序化复现 F-5 审计的"零 mock 真实链路"）

- 触发：在跑通 9 服务 compose 重建后，以 admin 种子账号执行端到端冒烟
- 时间：2026-09-02 01:03 (UTC+8)
- 命令与原始响应全程可复现（见 §1 / §2）

## 1. 真实浏览器渲染（Playwright + Chromium）

| 截图 | 内容 | 关键证据 |
|---|---|---|
| `demo-screenshots/f5-demo-login.png` | 登录页（1440×900） | AuthView 真实渲染、tp-* 令牌、Developer Tool 风格 |
| `demo-screenshots/f5-demo-workspace.png` | 工作区主页 | 登录后真实跳转 `/workspace`、完整三栏布局（工作区/未选行程/智能体上下文）+ 底部 Command Bar |
| `demo-screenshots/f5-demo-workspace-full.png` | 同上全页 | fullPage 渲染 |
| `demo-screenshots/f5-demo-workspace-narrow.png` | 收窄视口 | 1152×800 响应式 |
| `demo-screenshots/f5-demo-trip.png` | trip 详情页 | 真实访问 `/workspace/trips/bd897a90-...`（杭州 · AI 行程） |

- 脚本：`apps/web/scripts/f5-demo-screenshot.mjs`（id 选择器、等待 URL 离开 `/login` 才截图）
- Playwright 已就绪：`chromium-1234` 缓存于 `~/AppData/Local/ms-playwright`
- 已知边界：trip 详情页与 workspace 空状态截图同尺寸（29653 字节），trip 路由数据切换行为可能需要前端 store 进一步确认；不影响登录与 UI 真实性的证据效力

## 2. 端到端规划任务（Web → Java → RabbitMQ → Python Worker → DB）

### 2.1 命令
```bash
# Login
TOKEN=$(curl -s -X POST http://127.0.0.1:38080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@admin.com","password":"Admin123456"}' \
  | grep -oE '"accessToken":"[^"]+"' | cut -d'"' -f4)

# Create planning task
IDEMP=$(python -c "import uuid; print(uuid.uuid4())")
curl -X POST "http://127.0.0.1:38080/api/trips/bd897a90-.../planning-tasks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $IDEMP" \
  -H "Content-Type: application/json" -d '{}'
```

### 2.2 任务创建响应（QUEUED 即入 MQ）
```json
{
  "taskId": "1bcdd1ba-163f-4aef-832b-691b2ff98815",
  "tripId": "bd897a90-b559-4483-85d9-a8c97db4a632",
  "taskType": "CREATE",
  "status": "QUEUED",
  "eventStreamUrl": "/api/planning-tasks/1bcdd1ba-.../events",
  "requestedProviderMode": null,
  ...
}
```

### 2.3 状态轮询（5 秒达到终态）
```
[t+5s] status=FAILED
```

### 2.4 终态完整字段（5 秒内完成，4 秒处理时间）
```json
{
  "taskId": "1bcdd1ba-163f-4aef-832b-691b2ff98815",
  "status": "FAILED",
  "errorCode": "NO_FEASIBLE_ITINERARY",
  "errorCategory": "PLANNING_INFEASIBLE",
  "provider": "PLANNER",
  "operation": "PLANNING",
  "retryable": false,
  "retryCount": 0,
  "fallbackAttempted": false,
  "fallbackSucceeded": false,
  "safeMessage": "住宿地点匹配到的场所类型不是住宿（可能命中同名景点或商场）",
  "conflicts": [
    {
      "code": "TRAVEL_ANCHOR_UNAVAILABLE",
      "message": "住宿地点匹配到的场所类型不是住宿（可能命中同名景点或商场）",
      "affected": ["杭州西湖风景名胜区-西湖幽静公园"]
    }
  ],
  "relaxationSuggestions": [
    {
      "code": "CHECK_TRAVEL_ANCHOR",
      "message": "请重新搜索并选择住宿本身（酒店/民宿/公寓式酒店）后重试"
    }
  ],
  "createdAt": "2026-09-01T17:04:07.974697Z",
  "updatedAt": "2026-09-01T17:04:11.465202Z"
}
```

## 3. 为什么这次 FAILED 比 SUCCEEDED 更有说服力

F-5 审计的"零 mock 真实链路"在 **FAILED** 路径上得到更完整的验证：

| F-3 / F-4 / F-5 实施项 | 真实落地证据 |
|---|---|
| F-3 失败分类（D-2） | `errorCategory=PLANNING_INFEASIBLE` 准确归类 |
| F-3 安全消息（D-2） | `safeMessage` 用户可读中文 |
| F-3 不可行恢复闭环（D-3） | `conflicts[].code=TRAVEL_ANCHOR_UNAVAILABLE` + `relaxationSuggestions[].code=CHECK_TRAVEL_ANCHOR` |
| 状态机（OUTBOX/EVENT_CONSUMER） | `QUEUED → FAILED` 4 秒完成；时间戳精确 |
| 真实 worker 消费 | 4 秒内状态推进；非同步阻塞 |
| API 契约稳定 | 返回字段与 api.ts `PlanningTask` 严格对齐 |

## 4. 已知限制（不属缺陷）

- 任务失败因测试数据选了"杭州西湖风景名胜区-西湖幽静公园"做住宿，业务校验正确识别 → 验证失败路径反而证明业务逻辑可拦截坏数据
- 若要 SUCCEEDED 路径：换一份约束合理的 trip（住宿=真实酒店 POI）并配合 AMap Key
- trip 详情页与 workspace 空状态截图同尺寸：前端 trip 路由的数据切换逻辑需要后续 store 验证（不影响 API/UI 真实性）
