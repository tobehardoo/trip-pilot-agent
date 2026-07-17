# Phase 8 测试计划：高德步行路线 Provider 与 Redis 缓存

## 目标

- 在 Python Agent 服务中新增独立的 `RouteProvider` 能力边界，不扩张现有 POI `MapProvider` 的职责。
- 使用高德 Web 服务路径规划 2.0 的步行接口，返回距离、耗时、分段指令和可绘制的路线坐标。
- 使用 Redis JSON 缓存路线结果；缓存不可用或数据损坏时降级到实时 Provider。
- 提供确定性的 Demo 路线结果，为离线开发和下一阶段的规划降级保留稳定入口。

本阶段不修改 `PLANNING_COMPLETED`、Java 持久化、当前行程 API 或 Vue 工作台。路线进入完成事件、活动间交通段以及地图联动属于下一条跨端切片。

## 路线契约

- `RouteRequest` 包含起点、终点、出行方式、出发时间和可选的起终点 POI ID。
- 本阶段只接受 `mode=WALKING`；出发时间必须带时区，防止未来公共交通缓存产生歧义。
- 起终点坐标沿用 `Coordinates` 的经纬度范围约束；发送给高德时固定为最多 6 位小数。
- 起终点 POI ID 最长 100 字符，只作为提升高德算路准确性的可选参数。
- `RoutePlan` 包含：
  - `mode`：本阶段固定为 `WALKING`。
  - `distance_meters`：非负整数。
  - `duration_seconds`：非负整数。
  - `steps`：至少一个强类型路线分段。
  - `polyline`：按顺序去重后的经纬度坐标，供后续地图直接绘制。
- 每个 `RouteStep` 包含步行指令、距离、耗时和非空坐标序列。
- Provider 成功结果继续复用统一的 `ProviderSuccess` 元数据，明确 `provider`、`cached`、`fetched_at` 和 `estimated`。

## 高德适配规则

- 使用官方 `GET https://restapi.amap.com/v5/direction/walking`。
- 请求 `show_fields=cost,navi,polyline`，同时携带 `isindoor=0` 和 JSON 输出格式。
- 只采用第一条路线方案；路径为空时返回 `ROUTE_NOT_FOUND`，不伪造真实路线。
- HTTP、业务错误码和响应结构变化映射到稳定的 Provider 错误，不把 `httpx` 或 Pydantic 异常泄漏给调用方。
- 距离、耗时、坐标串和分段字段必须在 Provider 边界完成类型与范围校验。
- 日志中的 `key` 查询参数必须保持脱敏。

## 缓存规则

- 缓存键前缀为 `map:route:v1:`，后缀使用结构化输入的 SHA-256 摘要。
- 摘要输入至少包含：六位小数的起点、终点、出行方式、UTC 出发小时、Provider 和数据版本。
- 缓存键不得出现 API Key 或原始坐标文本。
- 默认 TTL 为 3600 秒，构造时允许覆盖但必须为正数。
- 命中缓存时返回原始 `fetched_at`，并将 `cached` 标记为 `true`。
- Redis 读取失败、写入失败或缓存 JSON 损坏时继续实时请求；成功取得的路线不得因缓存失败而丢弃。

## Demo 规则

- Demo Provider 使用起终点球面距离生成确定性步行估算，不调用网络或 Redis。
- Demo 路线只包含起点和终点，耗时按固定步行速度计算。
- 返回结果必须明确 `provider=DEMO`、`estimated=true` 和 `cached=false`，不得冒充高德结果。

## 必须覆盖

- 请求拒绝越界坐标、未知方式、无时区出发时间和过长 POI ID。
- 高德成功响应被解析为强类型路线，分段 polyline 合并时去除相邻重复点。
- 请求参数使用六位坐标、POI ID、`show_fields` 和脱敏 Key。
- 同一请求第二次读取缓存且不重复调用 HTTP；缓存 TTL 和哈希键符合约定。
- 起终点、方式或出发小时变化会生成不同缓存键。
- 空路线、业务错误、HTTP 错误、超时、网络错误、无效 JSON、缺失字段、非法数字和非法 polyline 都返回稳定失败类型。
- Redis 读写异常和损坏缓存均可降级到实时 Provider。
- Demo 结果确定、可序列化且不会共享高德来源标识。
- 自动化测试不得读取 `.env`、调用真实高德或消耗用户额度。

## 质量门槛

- 每个新增行为先观察到测试因功能缺失而失败，再实现最小代码使其通过。
- Python 全量测试与 Ruff 必须通过，受影响代码覆盖率不低于 80%。
- 真实高德验收只在自动化门禁通过后执行，密钥仅从被 Git 忽略的 `.env` 读取。
- 真实验收必须确认路线距离、耗时、分段、polyline 和 Redis 命中，并再次扫描提交候选与日志中的密钥。
- 完成独立代码审查后才能提交并推送 GitHub。

## 执行结果

截至 2026-07-17，本阶段实现与验证结果如下：

- 新增独立 `RouteProvider` 公共入口，并按公共契约、高德适配器、响应模型、失败映射和 Demo 估算拆分私有模块。
- 高德适配器使用官方 v5 步行路线接口，发送六位小数坐标、可选 POI ID、`show_fields=cost,navi,polyline` 和脱敏 Key。
- 路线结果包含距离、耗时、强类型分段和去除相邻重复点的 polyline；空路线返回 `ROUTE_NOT_FOUND`。
- Redis 缓存键使用 `map:route:v1:<sha256>`，摘要区分起终点、POI ID、方式、UTC 出发小时、Provider 和数据版本；默认 TTL 为 3600 秒。
- Python 路线测试 `41 passed`，全量 `112 passed`，Ruff 通过；新增路线模块行覆盖率 `100% (241/241)`。
- 真实高德与 Redis 验收通过：广州两个 POI 之间返回 8758 米、7006 秒、20 个分段和 258 个 polyline 点；首次结果 `cached=false`，第二次结果 `cached=true` 且数据一致。
- Redis 中路线键全部符合 64 位十六进制 SHA-256 格式且 TTL 为正；自动化测试未读取 `.env` 或调用真实高德。

保留到下一条跨端切片：相邻活动路线生成、`PLANNING_COMPLETED` 路线契约、交通段持久化、当前行程 API 和 Vue 地图/时间轴联动。
