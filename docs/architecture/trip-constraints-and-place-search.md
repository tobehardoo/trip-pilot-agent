# 旅行约束与地点搜索

- 文档状态：生效中（权威需求基线）
- 负责模块：travel-server、web、agent-service、contracts
- 最后更新：2026-08-07
- 当前事实来源：是
- 相关文档：
  - [系统架构](../architecture.md)
  - [事件契约](./事件契约.md)
  - [产品与范围](../product.md)
  - [2026-08-02 可执行路线图](../roadmap-2026-08-02.md)

## 1. 目的与范围

本文档是 TripPilot 旅行创建与约束系统的**权威需求基线**。它定义：

1. 创建旅行的唯一入口与结构化约束模型；
2. 目的地（行政区范围）与地点（POI 锚点）的领域边界；
3. 地点搜索的交互、场景过滤、选中锁定与失败语义；
4. 到达 / 返程 / 酒店等约束的完整性与校验规则；
5. 三餐默认约束、北京时间与工作台展示规则；
6. 创建旅行到规划启动的时序要求；
7. 天气展示边界；
8. 从浏览器到行程版本持久化的全链路；
9. 真实验收场景（F1–F5）与完成标准。

具体字段以后端类型、数据库迁移和 `contracts/` 中的 JSON Schema 为准；本文档描述的是行为契约和产品语义。

### 1.1 与现有实现的关系

本文档同时是当前实现的验收基线。实现已覆盖的需求在正文中标为 **已实现** 并给出代码位置；尚未验证或存在缺口的部分标为 **待核对**，由后续批次按本文档补齐。禁止在未对照本文档的情况下重新大改已实现功能。

## 2. 创建旅行的唯一入口

### 2.1 单一入口

产品只保留一个创建入口：

```text
创建旅行
  → 结构化旅行约束表单
  → 创建并开始规划
  → 工作台
```

- 创建与编辑必须使用**同一个约束模型**（`TripConstraintForm`），不允许创建时填一次、进入工作台再填一次。
- 以下输入方式不属于产品范围，必须停止使用：
  - 快速开始；
  - 一句话自动填写；
  - NaturalLanguageInput；
  - 规则解析式约束输入；
  - 多套互相独立的创建入口。

- **已实现**：`apps/web/src/components/TripConstraintForm.vue`（创建/编辑共享）；工作台为 `apps/web/src/pages/TripWorkspace.vue`。unify 分支不含 NaturalLanguageInput 与规则解析组件。

### 2.2 创建与编辑使用同一约束模型

`PUT /api/trips/{tripId}/configuration` 以同一 `ConstraintInput` 原子更新标题、日期、目的地与全部约束（`TripRequests.UpdateConfigurationRequest`）。约束变更与行程重规划是两件事：配置更新只落库，重规划是独立操作。

## 3. 目的地：行政区范围（DestinationRegion）

### 3.1 目的地不是普通地点输入框

旅行目的地属于**行政区范围**，不是 POI。禁止把用户自由输入（`广州`、`广洲`、`广州附近`、不存在城市）作为新的权威目的地。

目的地的输入模型为级联选择：

```text
省份（必选）→ 城市（必选）→ 区县（可选、多选）
```

规则：

- 省份必选；
- 城市必选；
- 区县可选，支持多选；
- 不选区县代表整个城市；
- 修改省份时清空城市、区县以及已选 POI；
- 修改城市时清空区县以及到达、返程、酒店 POI；
- 不允许自由文本作为新的权威目的地；
- 使用稳定行政区编码（AMap adcode）；
- 后端校验省、市、区上下级关系；
- 编码与名称必须一致。

### 3.2 结构

```json
{
  "provinceCode": "440000",
  "provinceName": "广东省",
  "cityCode": "440100",
  "cityName": "广州市",
  "districts": [
    { "districtCode": "440104", "districtName": "越秀区" },
    { "districtCode": "440106", "districtName": "天河区" }
  ]
}
```

对应后端 `TripRequests.DestinationRegion`（`provinceCode/provinceName/cityCode/cityName/districts[]`）。

### 3.3 行政区数据来源

行政区数据优先使用**项目内静态数据**（`apps/web/src/lib/china-divisions.ts` 与后端 `trip/RegionCatalog.java`）。不要求用户每次打开创建弹窗都依赖实时高德 API；行政区数据缓存后离线可用。

### 3.4 旧旅行兼容

旧旅行只有 `destination` 字符串时：

- 继续允许读取；
- 展示旧值并标记“目的地区域待确认”；
- 用户再次编辑时要求选择结构化行政区；
- **不得**根据字符串偷偷伪造 adcode；
- 后端保留 `destination` 字符串作为向后兼容字段（`CreateTripRequest.destination`），新创建请求同时携带结构化 `destinationRegion`。

### 3.5 后端校验

后端校验省、市、区上下级关系与编码/名称一致性（`trip/RegionCatalog.java`）。不存在的行政区或错误的上下级组合必须被拒绝。

## 4. 地点：POI 锚点（StructuredPoi）

### 4.1 到达、返程、酒店必须使用结构化 POI

以下字段不能使用普通文本：

- 到达地点；
- 返程地点；
- 酒店位置。

它们必须通过 **POI 联想搜索**（Search-as-you-type）选择，并以 `StructuredPoi` 保存。后端 `TravelAnchor` = `placeName + time(OffsetDateTime) + poi`，`Accommodation` = `placeName + poi`。

### 4.2 混合搜索结果列表

输入后约 300ms 防抖触发联想，返回三类结果：

```text
POI        广州南站
           高铁站 · 番禺区
           广州市番禺区南站北路

REGION     广州市
           地级市 · 广东省

SUGGESTION 广州南站附近酒店
```

结果类型与行为：

| 类型 | 行为 |
| --- | --- |
| `POI` | 可选中，成为可信地点（锁定 providerPoiId/名称/地址/坐标/行政区/类别）。 |
| `REGION` | 只用于调整搜索范围 / 继续搜索；**不能**直接保存为酒店或交通锚点。 |
| `SUGGESTION` | 点击后改变搜索关键词并执行二次查询；**不能**直接保存为锚点。 |

- **已实现**：`GET /api/places/suggest?keyword&cityCode&scene`（`PlaceSuggestService`），前端 `PlaceSearchField.vue`。

### 4.3 POI 场景过滤

统一地点组件支持场景：

- `ARRIVAL`（到达）
- `DEPARTURE`（返程）
- `HOTEL`（酒店）

场景过滤规则：

| 场景 | 允许类别 |
| --- | --- |
| `ARRIVAL` / `DEPARTURE` | 火车站、高铁站、机场、汽车站、港口、必要的地铁站（AMap 一级类别前缀 `150`，交通设施服务） |
| `HOTEL` | 酒店、民宿、青旅、度假村、公寓式酒店（AMap 一级类别前缀 `100`，住宿服务） |

不能把 `广州市`、`广州塔`、`广州南站` 作为酒店保存；`REGION`/`SUGGESTION` 不能作为到达/返程/酒店保存。

- **已实现**：后端 `TripConstraintValidator.belongsToScene`（`150*`=transport、`100*`=lodging）。

### 4.4 POI 选中锁定

用户选中具体 POI 后，展示锁定卡片：

```text
广州南站
高铁站 · 番禺区
广州市番禺区南站北路

[重新选择]
```

锁定后：

- 不再显示可任意修改的普通文本框；
- 锁定 `providerPoiId`、名称、完整地址、经纬度、省市区编码、类别；
- 只有点击“重新选择”才清空 `selectedPoi` 并重新搜索；
- 前端输入文本（`inputText`）与已选可信地点（`selectedPoi`）是两个独立状态，**禁止**用一个 `v-model` 同时表示正在输入的文字与已选中的可信地点。

`StructuredPoi` 字段（与 `PlacePoi` 一致）：

```json
{
  "provider": "AMAP",
  "providerPoiId": "B000A7BBX7",
  "name": "广州南站",
  "category": "高铁站",
  "categoryCode": "150302",
  "provinceCode": "440000",
  "cityCode": "440100",
  "districtCode": "440113",
  "district": "番禺区",
  "fullAddress": "广州市番禺区南站北路",
  "longitude": 113.269039,
  "latitude": 22.993494
}
```

### 4.5 搜索失败必须 fail-closed

地点搜索失败时展示“地点搜索暂时不可用，请稍后重试”，并允许用户：

- 暂不设置酒店；
- 暂不设置到达；
- 暂不设置返程。

**禁止**：搜索失败 → 用户随便输入文字 → 系统把文字当可信 POI 保存。

未从候选列表选择的自由文本不得成为可信地点。后端保存时重新校验（见 4.6）。

### 4.6 后端保存时重新校验 POI

后端不信任浏览器提供的地址/坐标。保存锚点时校验：

- 必须携带 `provider`（`AMAP`/`DEMO`）；
- 经纬度必须成对出现；
- 必须携带城市且与旅行目的地一致；
- 必须携带类别码且属于该场景（transport/lodging）；
- 没有 `providerPoiId` 的文本不得作为锚点。

校验失败返回 `400 VALIDATION_FAILED`（fail-closed），不静默降级为自由文本。

- **已实现**：`trip/TripConstraintValidator.java`。

### 4.7 地点搜索服务端代理

浏览器不得直接持有 AMap Key。地点搜索经由 Java 受限代理：

- `GET /api/places/search`：结构化 POI 搜索（`keyword`、`city`）。
- `GET /api/places/suggest`：混合联想（`keyword`、`cityCode`、`scene`，默认 `ARRIVAL`）。

代理至少限制：

- keyword 长度；
- cityCode 作用域（只能搜索目的地所在城市）；
- scene 类别过滤；
- 结果数量上限；
- 超时；
- 有限重试；
- 限流（`places/FixedWindowRateLimiter`）。

搜索不可用时抛 `PlaceSearchUnavailableException`，前端展示失败而非静默提交自由文本。

- **已实现**：`places/` 包（`PlaceSearchController`、`PlaceSearchService`、`PlaceSuggestService`、`AmapPlaceSearchClient`、`FixedWindowRateLimiter`）。

## 5. 到达与返程：完整日期时间

### 5.1 不能只输入时间

到达与返程必须是**日期 + 时间**：

```text
到达：日期 + 时间
返程：日期 + 时间
```

默认值：

- 到达日期 = `startDate`；
- 返程日期 = `endDate`。

保存为完整 OffsetDateTime，例如 `2026-08-10T14:30:00+08:00`。业务时区为 `Asia/Shanghai`。

### 5.2 校验规则

- 到达日期必须处于旅行日期范围内；
- 返程日期必须处于旅行日期范围内；
- 到达不能晚于返程；
- 修改旅行日期后重新校验到返时间；
- 只有地点没有时间不能提交；
- 只有时间没有地点不能提交；
- 输入了关键词但未选择 POI 不能提交。

- **已实现**：`TravelAnchor.time`（`OffsetDateTime`）；`TripConstraintValidator.validateAnchor`（锚点日期在行程范围内）与 `validateContext`（返程晚于到达）。

## 6. 三餐默认约束

默认三餐窗口：

```text
早餐 08:00–09:00
午餐 12:00–13:00
晚餐 18:00–19:00
```

生命周期：

- 新旅行：Java 归一化 → `SYSTEM_DEFAULT` → 真正持久化；
- 用户修改后：来源变为 `USER_SET`；
- 工作台始终展示当前值及其来源。

餐馆选择优先级：

1. 时间与营业可行；
2. 路线合理；
3. 用户偏好；
4. 餐馆不重复。

同日早中晚尽量不重复餐馆，但这是**软约束**（跨日软去重已实现）。

- **已实现**：`TripRequests.DEFAULT_MEAL_WINDOWS` + `normalizeMealWindows`；软去重见 `feat(planning): soft restaurant de-duplication within and across days`。

## 7. 北京时间

- 服务端业务时区为 `Asia/Shanghai`；
- 使用可注入 `Clock`，测试可固定“今天”；
- 创建旅行默认日期为当前北京时间今天；
- 禁止创建过去日期；
- 不能只依赖浏览器 `new Date()`。

- **已实现**：`trip/TripDatePolicy.java`（`BUSINESS_ZONE`、`today()`、`validateNewTripStartDate`）；`GET /api/system/time` 在认证前向浏览器提供北京日历锚点。

## 8. 工作台约束展示

创建旅行保存的约束必须直接进入工作台，**禁止**进入工作台后让用户再次填写一遍。

Java 持久化的 Trip/TripConstraints 是权威事实。工作台始终展示：

- 省 / 市 / 区；
- 日期；
- 人数；
- 预算；
- 节奏；
- 行动能力；
- 到达；
- 返程；
- 酒店；
- 早餐 / 午餐 / 晚餐；
- 偏好；
- 必去；
- 避开。

来源标签：

```text
用户设置
系统默认
Provider 确认
待重新确认
尚未设置
估算
```

桌面端优先使用**右侧 sticky 当前约束面板**，而不是要求用户滑到页面最底部。

- **已实现**：`feat(web): shared TripConstraintForm`、`feat(web): always-visible constraint summary and itinerary staleness`；`PUT /api/trips/{tripId}/configuration` 原子配置更新。

## 9. 创建弹窗稳定性

已出现“填写约束时窗口闪退”。稳定性规则：

- 弹窗只有一个状态源；
- 不使用多个 watch 与 key 竞争控制；
- 不频繁通过 `:key` 强制卸载整个表单；
- 异步搜索组件卸载时取消请求；
- 使用 `AbortController`；
- 使用 request sequence 防止旧响应覆盖新响应；
- API 错误显示在弹窗内部；
- 请求失败不能自动关闭弹窗；
- 创建按钮防双击；
- 创建失败保留输入。

布局：

```text
固定标题栏
+ 中间内容独立滚动
+ 固定底部按钮栏
```

- **已实现**：`fix(web): restore place search and stabilize the create modal`。

## 10. 创建旅行与规划启动时序

正确流程（基础规划曾出现回归，必须按下述时序）：

```text
提交创建表单
→ POST /api/trips
→ 等待成功返回 tripId
→ POST /api/trips/{id}/planning-tasks
→ 等待任务成功创建
→ 进入详情
→ 建立 SSE / 状态恢复
```

**禁止**：`void startPlanning()` → 不等待 → 立即跳转 → 异常被 catch 吞掉。

如果旅行创建成功但 PlanningTask 创建失败，页面显示“旅行已创建，但规划启动失败”，并提供“重新开始规划”，不能永久 loading。

- **已实现**：`fix(web): track auto-started planning task after trip creation`；Web 端 `POST /api/trips/{tripId}/planning-tasks`（`lib/api.ts`）。

## 11. 天气

- 天气只展示 `startDate ... endDate` 范围内的数据，不展示旅行前后额外日期；
- 天气失败不能阻塞基础行程规划；
- 本轮不得大规模重构天气 Provider。

- **已实现**：`feat(web): weather timeline shows only the trip date range`。

## 12. 架构边界

### 12.1 DestinationRegion ≠ StructuredPoi

| | DestinationRegion | StructuredPoi |
| --- | --- | --- |
| 职责 | 旅行规划范围（省/市/区） | 精确路线锚点（到达/返程/酒店） |
| 校验 | 省市区上下级关系、编码/名称一致 | provider、坐标、城市匹配、场景类别码 |
| 输入方式 | 级联选择 | 联想搜索 + 选中锁定 |
| 保存 | `Trip.destinationRegionJson` | 约束 JSONB 内 `arrival/departure/accommodation.poi` |

### 12.2 领域模型

```text
Trip
├── destinationRegion
│   ├── provinceCode
│   ├── provinceName
│   ├── cityCode
│   ├── cityName
│   └── districts[]
│
└── constraints
    ├── arrival
    │   ├── poi        # StructuredPoi
    │   └── datetime   # OffsetDateTime
    ├── departure
    │   ├── poi
    │   └── datetime
    ├── accommodation
    │   └── poi
    ├── mealWindows        # BREAKFAST/LUNCH/DINNER + source
    ├── fixedSchedules
    ├── mustVisitPlaces
    ├── avoidPlaces
    ├── preferences
    ├── budgetAmount
    ├── travelers / travelerType
    ├── pace
    └── mobilityLevel
```

- `TripConstraintRecord`（约束 JSONB 列）、`TripSnapshotRecord`（含 `destinationRegionJson`）位于 `apps/travel-server/.../trip/`。

## 13. 全链路

真正的旅行规划链路（任何一跳失败都不能称“创建旅行成功完成”）：

```text
Browser
→ POST /api/trips                      # Java TripController/TripService
→ PostgreSQL trip + trip_constraint    # 事务写入
→ POST /planning-tasks                 # PlanningTaskController/Service
→ planning_task + constraint_snapshot  # 冻结输入
→ Outbox                               # Transactional Outbox
→ RabbitMQ                             # planning-create-command
→ Python Worker                        # 消费 + 校验
→ Provider (Demo / AMap)               # POI / 路线
→ daily skeleton                       # 容量驱动的日骨架
→ completion v8                        # planning-completed-event-v8
→ RabbitMQ
→ Java consumer                        # PlanningCompletionHandler
→ itinerary_version / day / activity / transit
→ SSE / GET                            # 浏览器展示行程
```

关键契约与可靠点：

- Outbox 保证 DB 写入与消息发布最终一致；
- RabbitMQ at-least-once，消费者按任务/消息/序列号幂等；
- completion v8 是当前运行时完成事件（见 [事件契约](./事件契约.md)）；
- 行程版本不可变，规划结果持久化为 `itinerary_version/day/activity/transit`。

## 14. 真实验收场景

### F1 基础规划

- 广东省 → 广州市 → 不选区县；
- 不设置酒店、不设置到返；
- 默认三餐；
- `BALANCED`、`STANDARD` 行动能力；
- 从浏览器创建，最终必须显示有效 itinerary。

### F2 完整 POI

- 广东省 → 广州市；
- 广州南站到达、真实返程站、具体酒店门店、完整日期时间；
- 最终必须使用结构化 POI 规划成功。

### F3 弹窗稳定

连续打开关闭 20 次，并覆盖：

- 搜索中关闭；
- 快速输入；
- 快速切换城市；
- Provider 失败；
- 创建 API 失败；
- 双击提交。

不得闪退。

### F4 非法输入

以下输入前后端都必须正确拒绝：

- 不存在的行政区；
- 错误的省市区上下级；
- 未选择 POI；
- REGION 作为酒店；
- SUGGESTION 作为到达地点；
- 跨城市 POI；
- 到返时间不完整；
- 过去日期。

### F5 真实 AMap

Demo Provider 全链通过后，至少运行一次真实 AMap 规划。外部失败要分类，不能伪造 PASS。

## 15. 完成标准

以下全部满足才可宣称本阶段完成：

- [ ] 本文档为当前权威需求；
- [ ] 文档独立提交并推送；
- [ ] 当前运行 SHA 可验证；
- [ ] 基础旅行规划全链可用（F1）；
- [ ] 目的地为省市区结构化选择（F2）；
- [ ] 不存在的城市不能保存（F4）；
- [ ] 区县可选和多选；
- [ ] 到达/返程/酒店可正常输入；
- [ ] 地点输入自动产生混合联想列表；
- [ ] POI/REGION/SUGGESTION 行为正确；
- [ ] POI 选中后锁定；
- [ ] 未选择的自由文本不能保存成可信地点；
- [ ] 后端重新验证 POI；
- [ ] 到达/返程保存完整北京时间日期时间；
- [ ] 创建弹窗不闪退（F3）；
- [ ] 创建请求只一次；
- [ ] PlanningTask 只一次；
- [ ] 默认三餐存在；
- [ ] 工作台无需重新填写创建约束；
- [ ] 工作台始终显示当前约束；
- [ ] Demo Provider 全链成功；
- [ ] 真实 AMap 已验证（F5）；
- [ ] completion v8 正常；
- [ ] itinerary 正常持久化；
- [ ] 浏览器真实显示行程；
- [ ] Full-stack Playwright 不 Mock 核心 API；
- [ ] Java / Python / Web 全量通过；
- [ ] Flyway 空库通过；
- [ ] worktree 干净；
- [ ] PR #28 保持 Draft。
