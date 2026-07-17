# Phase 7 测试计划：真实 POI 完成事件与 Demo 降级

## 目标

- 新增 `PLANNING_COMPLETED` v2，活动可携带高德 POI ID、经纬度和地址。
- Java 同时接受既有 v1 Demo 事件与新的 v2 事件，并把 AMAP 元数据保存到关系型行程。
- Python 规划器从 `MapProvider` 获取与目的地、偏好相关的去重 POI，生成每天一个真实地点的最小行程。
- 已分类的高德失败或候选不足时降级到 Demo；代码缺陷和未知异常继续使消息重入队。
- Worker 在 `DEMO_MODE=false` 时从集中配置装配 HTTP、Redis、高德和降级 Provider。

本阶段不实现路线矩阵、营业时间、停留时长优化、固定安排合并和前端地图。这些能力消费本阶段保存的坐标，不再修改消息主结构。

## 完成事件 v2

- Envelope 保持原字段，`schemaVersion` 从 `1` 升级为 `2`。
- `payload.provider` 允许 `AMAP` 或 `DEMO`。
- Activity 保留 title、时间、费用和 source，并新增可选字段：
  - `providerPoiId`：最长 100 字符。
  - `coordinates.longitude`：-180 至 180。
  - `coordinates.latitude`：-90 至 90。
  - `address`：最长 300 字符。
- `source=AMAP` 时三个新增字段全部必填，且 payload provider 必须为 `AMAP`。
- `source=DEMO` 时不得携带伪造的高德元数据，且 payload provider 必须为 `DEMO`。
- v1 仍只允许 DEMO，解析和持久化行为保持不变。

## 规划和降级规则

- 查询城市使用旅行 destination；关键字按用户 preferences 顺序，再追加稳定的默认类别。
- 对 Provider 结果按 `provider_id` 去重，收集数量达到旅行天数后停止，避免无界调用额度。
- `POI_NOT_FOUND` 可继续尝试下一个关键字；其他已分类 Provider 失败立即进入 Demo 降级。
- 所有查询完成后候选仍不足，也进入 Demo 降级。
- 每天安排一个 POI，当前仍使用 09:00 至 11:00 的确定性时间窗和 0 元占位费用。
- Demo 降级结果必须在 payload provider 和 activity source 上明确标为 `DEMO`。

## 持久化

- `business.activity` 新增 provider POI ID、longitude、latitude 和 address。
- 经纬度必须同时为空或同时存在，并受数据库范围约束。
- AMAP activity 必须有完整来源元数据；旧 Demo 数据允许这些列为空。
- 当前行程 API 返回嵌套 coordinates、providerPoiId 和 address，供下一阶段地图直接消费。

## 必须覆盖

- Java 解析器接受 v1 Demo 和合法 v2 AMAP，拒绝 provider/source 不一致、缺失元数据、越界坐标和未知字段。
- PostgreSQL 集成测试证明 AMAP 元数据原样写入并由所有者隔离 API 返回。
- Python v2 JSON 与 Java 字段名、数值类型和时区一致。
- Python 规划器按偏好查询、去重、限制调用，并把 POI 分配到完整日期范围。
- Provider 业务失败和候选不足降级到 Demo；未知异常不被吞掉。
- Worker 真实模式缺 Key 时启动失败；Demo 模式不要求 Key，也不创建网络客户端。
- 自动化测试不得读取 `.env`、调用真实高德或消耗额度。

## 质量门槛

- 每个行为先观察到对应测试因功能缺失失败，再实现最小代码。
- Java、Python、Vue 受影响测试和静态检查全部通过。
- JSON Schema、Python Pydantic 模型、Java parser、数据库约束和 API 响应保持一致。
- 完成真实跨服务冒烟前，先通过独立代码审查和密钥扫描。

## 执行结果

截至 2026-07-17，本阶段已完成：

- 新增严格的 `planning-completed-event-v2.schema.json`；AMAP 和 Demo 使用独立分支，禁止 provider/source 混用和伪造来源元数据。
- Java parser 同时接受 v1 Demo 与 v2 AMAP/Demo，拒绝缺失元数据、越界坐标、JSON 数字强制转换和来源不一致。
- Flyway V6 为 activity 增加 POI ID、经纬度和地址列及数据库约束；当前行程 API 返回嵌套 coordinates。
- Python 完成异步 AMAP Planning Provider、跨偏好有界查询、POI ID 去重、坐标 7 位小数量化与窄捕获 Demo fallback。
- Worker 在真实模式启动时验证 `SecretStr` Key，集中拥有 HTTP/Redis 生命周期，并把实际 Provider 注入 RabbitMQ 消费回调。
- Java 全量与 v2 Demo 兼容补充测试共 `81 passed`，JaCoCo 行覆盖率 `90.92% (691/760)`；Python 全量 `71 passed`，Ruff 与 uv lock 检查通过；Vue `33 passed` 且类型检查通过。
- 真实跨服务验收通过：正确 UTF-8 的广州/博物馆任务生成“南越王博物院（王墓展区）”，provider/source 为 AMAP，坐标为 `113.261015, 23.137823`，POI ID 非空，Redis 只保存 SHA-256 缓存键。
- 自动化测试不读取 `.env` 或调用高德；真实冒烟只把 Key 发送到高德官方 HTTPS endpoint，未打印、暂存或写入日志。

Phase 8 已完成路线 Provider 与路线缓存。继续保留到后续跨端切片：相邻活动交通段、前端地图 Marker 与时间轴联动，以及固定安排合并和真实路线时长。
