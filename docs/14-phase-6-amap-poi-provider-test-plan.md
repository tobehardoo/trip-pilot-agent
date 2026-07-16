# Phase 6 测试计划：高德 POI Provider 与 Redis 缓存

## 范围

- Python Agent 新增与规划流程解耦的 `MapProvider` 接口和不可变 POI/坐标/Provider 结果模型。
- 高德 Provider 调用地点搜索 2.0 文本搜索接口，严格限制城市并解析基础 POI 字段。
- Redis JSON 缓存适配器保存成功的 POI 搜索结果，缓存键不包含 API Key。
- 统一分类高德认证、限流/额度、参数、超时、网络和响应 Schema 错误。
- 提供确定性的 Demo Map Provider，保留无 Key、无网络的测试与演示能力。

本阶段不修改 Java `PLANNING_COMPLETED` v1 契约，不把 `AMAP` 结果写入现有行程版本，也不包含地理编码、路线矩阵、前端地图和真实 Key 冒烟。下一切片在升级跨服务契约后接入规划结果。

## 设计规则

- 规划用例只依赖 `MapProvider` Protocol；HTTP 与 Redis 是外层适配器。
- 高德地点搜索使用 `GET https://restapi.amap.com/v5/place/text`，发送 `keywords`、`region`、`city_limit=true`、`page_size` 和 Web 服务 Key。
- Provider 输入在发出网络请求前验证：城市与关键字不能为空，关键字最长 80 字符，单页数量为 1 至 25。
- 成功结果保留 Provider、延迟、缓存命中、抓取时间和 `estimated=false`。
- 空 POI 集合返回明确的 `POI_NOT_FOUND` 业务失败，供后续 Agent 扩大范围或改写查询。
- 缓存读取损坏或 Redis 暂时不可用时降级到高德请求；缓存写入失败不能丢弃已获得的 Provider 结果。
- API Key 不写日志、不进入缓存键、不出现在错误文本或测试快照中。

## 错误规则

- 无效 Key、权限、白名单和签名问题：`PROVIDER_AUTH_FAILED`，不可重试。
- 分钟/QPS 限流和服务繁忙：`PROVIDER_RATE_LIMITED`，可重试。
- 日额度或付费额度耗尽：`PROVIDER_QUOTA_EXHAUSTED`，不可立即重试。
- 非法参数或内容：`PROVIDER_REQUEST_INVALID`，不可重试。
- HTTP/网络错误和超时：分别返回可重试的 `PROVIDER_UNAVAILABLE`、`PROVIDER_TIMEOUT`。
- 非法 JSON、缺失字段或非法坐标：`PROVIDER_SCHEMA_CHANGED`，不可盲目重试。

## 必须覆盖

- 文本搜索请求参数符合高德地点搜索 2.0 官方契约，并解析 POI ID、名称、地址、类型、行政区和经纬度。
- 首次成功请求写缓存；相同城市、关键字和数量再次请求直接命中缓存且不访问 HTTP。
- 不同查询产生不同且不含 API Key/原始查询文本的稳定缓存键。
- 损坏缓存、缓存读失败和缓存写失败均按规则降级。
- 高德空结果、认证失败、限流、额度、非法参数和 Schema 变化得到正确错误码与重试标记。
- HTTP 超时、连接失败与 5xx 被分类为可重试基础设施失败。
- Redis 适配器使用秒级 TTL，并正确处理字符串和字节响应。
- Demo Provider 返回确定、明确标记为估算的数据。

## 质量门槛

- 每个新增行为先看到测试因功能缺失而失败，再编写最小实现。
- Python 全量测试与 Ruff 通过，`uv.lock` 与 `pyproject.toml` 一致。
- 不使用真实高德 Key，不发出真实高德网络请求，不提交本地缓存数据。
- 完成后更新 README、数据 Provider 文档、路线图和本文件执行结果，并通过独立代码审查。

## 官方依据

- [高德地点搜索 2.0](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch)
- [高德 Web 服务错误码](https://lbs.amap.com/api/webservice/guide/tools/info/)
- [redis-py](https://pypi.org/project/redis/)

## 执行结果

截至 2026-07-16，本阶段基础设施切片已完成：

- 新增不可变 Provider 领域模型、`MapProvider` Protocol、高德地点搜索 2.0 文本适配器、Redis JSON 缓存和 Demo Map Provider。
- 高德请求参数、成功解析、缓存命中、缓存损坏/读写失败降级、空结果及官方错误码分类均由自动化测试覆盖。
- HTTP 超时、连接失败、408/5xx、非法 JSON、缺失基础字段和非法坐标均转换为稳定的 `ProviderFailure`，不会把包含请求 URL 的第三方异常向上泄漏。
- 缓存键使用结构化查询的 SHA-256 摘要，不含 API Key、城市或关键字原文；错误文本使用本地固定消息，HTTPX INFO 日志会在进入 handler 前脱敏 `key`。
- `pyproject.toml` 与 `uv.lock` 已加入运行时 `httpx 0.28.1` 和 `redis 7.4.1`。
- 专项测试 `36 passed`；Python 服务全量测试 `57 passed`；`ruff check src tests` 通过。
- 自动化测试只使用 `httpx.MockTransport` 与内存 Redis 假客户端，未读取本地 `.env`、未调用真实高德接口、未消耗额度。

保留到下一切片：升级 `PLANNING_COMPLETED` 契约并把 `AMAP` POI 接入规划结果。地理编码、路线矩阵和前端地图仍按原路线图后续实现。
