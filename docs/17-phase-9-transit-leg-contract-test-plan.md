# Phase 9 测试计划：相邻活动路线、交通段持久化与行程 API

## 目标

- 让真实 POI 规划结果在每个行程日包含两个活动，并为每对相邻活动计算步行路线。
- 将 `PLANNING_COMPLETED` 升级为 v3，在跨服务契约中携带可持久化、可绘制的交通段快照。
- 在 Java 服务中把交通段关联到前后活动并原子落库，通过当前行程 API 返回。
- 保持 Java 对 v1/v2 完成事件的兼容；旧事件的交通段列表为空。

本阶段不实现 Vue 地图、路线编辑、公共交通、路线矩阵或 OR-Tools。地图 Marker、polyline 与时间轴联动属于下一阶段。

## v3 契约

- 每个 `day` 新增必填 `transitLegs` 数组；单活动日使用空数组。
- 每个交通段包含 `fromActivityIndex`、`toActivityIndex`、`mode`、`distanceMeters`、`durationSeconds`、`provider`、`estimated` 和 `polyline`。
- 本阶段 `mode` 固定为 `WALKING`；路线来源仅允许 `AMAP` 或 `DEMO`。
- 路线段数量必须等于当天活动数减一，并按顺序连接 `0 -> 1`、`1 -> 2` 等相邻活动。
- 距离和耗时必须是非负整数；polyline 为 1 到 5000 个合法经纬度坐标。
- 前一活动结束时间加路线耗时不得晚于后一活动开始时间，确保事件本身可执行。
- AMAP 算路失败时可使用明确标记 `provider=DEMO`、`estimated=true` 的确定性估算；未分类异常必须继续向上抛出并触发消息重试。

## 持久化与 API

- 新增 `business.transit_leg`，归属于 `itinerary_day`，并通过外键关联前后 `activity`。
- 保存顺序、方式、距离、耗时、来源、估算标志和 JSONB polyline 快照。
- 完成事件的行程版本、天、活动、交通段、任务状态和任务事件必须处于同一事务。
- 当前行程 API 在每个 `day` 下返回 `transitLegs`，包含数据库活动 UUID 和路线字段。
- v1/v2 事件继续可消费并返回空 `transitLegs`。

## 必须覆盖

- Python v3 模型拒绝缺失路线、跳过活动的索引、非法坐标和超出活动间隙的路线耗时。
- 高德规划器按每天两个 POI 生成活动与路线请求，并把路线元数据映射到完成事件。
- 已分类路线失败仅降级为 Demo 路线；未分类异常不被隐藏。
- Worker 工厂为真实模式同时注入共享 HTTP/Redis 资源的 POI 与路线 Provider，并使用独立路线 TTL。
- Java 解析器兼容 v1/v2，接受合法 v3，拒绝非法索引、数量、来源、数值、polyline 和路线时间。
- PostgreSQL 集成测试验证交通段外键、字段、polyline、API 响应、幂等和事务回滚。
- 契约 JSON Schema 拒绝未知字段和类型强制转换。

## 质量门槛

- 每个新增行为先观察到测试因功能缺失而失败，再实现最小代码使其通过。
- Python 全量测试和 Ruff、Java 全量 `verify` 与覆盖率门禁必须通过。
- 受影响代码行覆盖率不低于 80%，跨服务真实流程至少完成一次本地验收。
- 自动化测试不得读取 `.env`、调用真实高德或消耗用户额度。
- 真实高德验收仅从 Git 忽略的本地环境读取密钥，提交前扫描代码、Git 差异和日志，确保密钥未进入版本库。
- 独立代码审查通过后再提交并推送 GitHub。

## 执行结果

截至 2026-07-17，本阶段实现与验证结果如下：

- Python 完成事件升级为 v3；每个行程日显式包含 `transitLegs`，模型校验路线数量、相邻索引、可达时间、来源、估算标志和 polyline。
- AMAP 规划器每日至少选择两个唯一 POI，为相邻活动调用 `RouteProvider`；已分类算路失败只降级为明确的 Demo 估算，未分类异常继续触发消息重试。
- Worker 真实模式共享 HTTP 客户端和 Redis，分别构造 POI 与路线 Provider；POI TTL 默认为 86400 秒，路线 TTL 默认为 3600 秒。
- Java 解析器兼容 v1/v2/v3；旧事件交通段归一为空列表，v3 缺失或非法路线被严格拒绝。
- Flyway V7 新增 `business.transit_leg`，复合外键保证起终活动属于同一行程日，并在数据库层约束方式、数值范围、来源/估算一致性和非空 polyline。
- 完成服务在同一事务保存版本、天、活动、交通段、任务状态和任务事件；交通段插入失败的 PostgreSQL 集成测试确认所有业务写入回滚。
- 当前行程 API 在每天返回带活动 UUID、距离、耗时、来源、估算标志和 polyline 的交通段；Vue API 类型已同步，地图渲染保留到下一阶段。
- Python 全量 `119 passed`、Ruff 通过；受影响 Worker 模块行覆盖率 `91%`，其中 `amqp.py` `81%`、`contracts.py` `95%`、`processor.py` `96%`。
- Java 全量 `88 passed`、JaCoCo 行覆盖率 `91.08% (776/852)`；默认 fork 的 Unicode 路径问题通过临时 ASCII agent 路径完成等价 report/check，未修改仓库构建配置。
- 真实端到端广州验收通过：Java API 创建任务，经 RabbitMQ、Python Worker、高德 POI/步行路线、Redis 和 PostgreSQL 后，在 3.1 秒内返回两个 AMAP 活动与一个 AMAP 交通段；活动坐标位于广州范围，路线为 1921 米、1537 秒、78 个 polyline 点。
- Redis 路线键符合 `map:route:v1:<sha256>` 且 TTL 为正；Git 跟踪文件、当前 diff 和 API/Worker 日志中的真实高德 Key 原文匹配数均为 0。

保留到下一阶段：Vue 高德地图加载、Marker、polyline、选中活动与时间轴联动，以及桌面/移动视口视觉验收。
