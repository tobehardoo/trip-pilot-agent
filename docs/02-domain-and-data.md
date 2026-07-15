# 领域模型与数据设计

## 1. 数据所有权

Java 拥有业务事实：

- 用户、偏好、旅行、约束。
- 规划任务及对用户可见的进度。
- 最终行程、版本、分享和权限。
- Outbox 和业务审计。

Python 拥有 Agent 执行事实：

- AgentRun、Checkpoint 和步骤。
- 工具调用和模型调用。
- 城市知识文档和向量片段。
- 评测用例和评测运行。

部署时可以使用同一个 PostgreSQL 实例，但至少使用 `business` 与 `agent` 两个 schema。Python 不直接修改 Java 业务表，Java 不直接修改 Agent checkpoint。

## 2. 核心聚合关系

```text
User
 ├── UserPreference
 └── Trip
      ├── TripConstraint
      ├── PlanningTask
      │    └── PlanningTaskEvent
      └── Itinerary
           └── ItineraryVersion
                ├── ItineraryDay
                │    ├── Activity
                │    └── TransitLeg
                └── PlaceSnapshot
```

## 3. Java 业务表

### 身份与偏好

- `user_account`：账号、密码哈希、状态和角色。
- `refresh_token`：Refresh Token 哈希、过期时间、轮换和撤销状态。
- `user_preference`：饮食、节奏、兴趣、步行接受度和默认预算习惯。

### 旅行与约束

- `trip`：目的地、日期、所有者、状态、当前行程版本。
- `trip_member`：为未来同行成员和协作权限预留；V1 可以只保存所有者。
- `trip_constraint`：用户原始输入、标准化约束、schema 版本和更新时间。

### 规划任务

- `planning_task`：任务类型、状态、幂等键、行程基线版本、重试次数和错误。
- `planning_task_event`：递增事件 ID、事件类型、载荷和创建时间。
- `outbox_event`：聚合 ID、事件类型、载荷、发送状态和重试信息。

### 行程与版本

- `itinerary`：所属旅行和当前激活版本。
- `itinerary_version`：父版本、创建原因、创建者类型、约束快照和任务引用。
- `itinerary_day`：日期、起止时间、预算、强度和统计。
- `activity`：类型、地点、开始结束时间、费用、锁定状态和顺序。
- `transit_leg`：起止活动、方式、距离、时长、费用、数据来源。
- `place_snapshot`：规划时 POI 的名称、坐标、地址、来源、外部 ID 和字段置信度。
- `share_link`：Token 哈希、过期时间、撤销状态和访问权限。

截至 2026-07-15，V5 已落地后端最小闭环所需的 `planning_task_event`、`itinerary`、`itinerary_version`、`itinerary_day` 和 `activity`。最终行程按日期、顺序、时间和费用保存为关系数据；规划任务与行程版本均保存创建任务时的约束快照。`transit_leg`、`place_snapshot`、分享以及更完整的活动字段仍按后续真实 Provider 和前端切片实现。

## 4. Python Agent 表

- `agent_run`：对应 taskId、当前状态、workflow 版本和最终结果引用。
- `agent_checkpoint`：图状态快照、节点、序号和恢复信息。
- `agent_step`：节点输入输出摘要、状态、耗时和错误。
- `tool_call_log`：工具、参数摘要、Provider、缓存、延迟和错误码。
- `model_call_log`：模型、用途、Token、费用、延迟、重试和配置快照。
- `knowledge_document`：城市资料、来源、版本和有效期。
- `knowledge_chunk`：片段、Embedding 和 metadata。
- `evaluation_case`：固定输入、期望约束、检查器和标签。
- `evaluation_run`：模型配置、代码版本、结果和指标。

## 5. 关系表与 JSONB 边界

适合 JSONB：

- 用户原始自然语言需求。
- LLM 解析后的可扩展约束。
- Agent 中间候选方案。
- 模型与 Prompt 配置快照。
- 不同活动类型的少量扩展字段。

适合关系表：

- 日期、活动顺序、起止时间和费用。
- POI 引用和快照。
- 交通段。
- 行程版本和父子关系。
- 权限、状态和审计字段。

不得把完整最终行程只保存成不可查询的大 JSON。

## 6. 约束模型

约束分为三类：

- 硬约束：到返时间、预约时间、必去地点、预算硬上限、锁定活动。
- 软约束：偏好、少走路、行程节奏、多样性、期望预算。
- 上下文约束：天气、季节、同行类型、临时闭馆和工具异常。

约束至少包含：

```text
destination
startDate / endDate
arrivalPlace / arrivalTime
departurePlace / departureTime
travelerCount / travelerType
totalBudget / budgetPolicy
preferences / avoidances
mustVisit / excludedPlaces
pace
dailyStartTime / dailyEndTime
maxWalkingTime
hotel / accommodationArea
reservedActivities
```

## 7. 不可变版本

每次会改变可见行程的操作创建新版本：

```text
Version 1：Agent 首次生成
Version 2：用户删除景点
Version 3：Agent 局部重规划
Version 4：用户拖拽调整顺序
```

版本至少保存：

- `parent_version_id`
- 创建原因
- 创建者类型：用户、Agent、系统
- 约束快照
- 生成任务 ID
- 创建时间

`trip` 或 `itinerary` 只保存当前激活版本 ID。回滚是切换当前版本或基于旧版本创建新版本，不覆盖历史数据。

## 8. 并发控制

- 所有修改命令携带客户端看到的 `itineraryVersion`。
- 当前版本不一致时返回 `409 Conflict`。
- 行程和规划任务使用乐观锁版本字段。
- 同一旅行默认只允许一个会修改行程的 Agent 任务处于活动状态。
- Redis 锁只做快速拦截，数据库约束和状态检查是最终保障。

## 9. 任务状态机

```text
CREATED -> QUEUED -> RUNNING -> SUCCEEDED
                       |
                       +-> WAITING_USER -> RUNNING
                       +-> RETRYING -> RUNNING
                       +-> CANCELLING -> CANCELLED
                       +-> FAILED
```

状态流转由领域服务控制，不允许任意更新状态字符串。

## 10. 变更命令

前端修改应转换为明确命令，而不是提交任意 Prompt：

- `REMOVE_ACTIVITY`
- `MOVE_ACTIVITY`
- `LOCK_ACTIVITY`
- `UNLOCK_ACTIVITY`
- `CHANGE_BUDGET`
- `CHANGE_PACE`
- `CHANGE_DAILY_TIME`
- `CHANGE_HOTEL`
- `WEATHER_REPLAN`
- `ROLLBACK_VERSION`

命令中包含基线版本、目标对象、用户原因和允许修改范围。

## 11. 数据快照与来源

外部 POI、路线和天气会变化，最终行程必须保存生成时快照：

- Provider 和外部 ID。
- 获取时间。
- 原始字段摘要。
- 数据来源类型：官方接口、人工资料、规则估算、模型生成。
- 可信度或是否为估算。

LLM 推测不得被标记成官方事实，也不得直接成为硬约束。
