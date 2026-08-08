# Provider 集成

- 文档状态：生效中
- 负责模块：agent-service
- 最后更新：2026-08-05
- 当前事实来源：是
- 相关决策记录：
  - [Provider 模式与降级策略 ADR](../adr/Provider模式失败与降级策略.md)
  - ADR-007 Demo 模式是正式模式
- 相关代码：
  - `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py`
  - `apps/agent-service/src/trip_agent/infrastructure/demo/`
  - `apps/agent-service/src/trip_agent/worker/settings.py`

## 概述

TripPilot 支持三种外部数据 Provider 的集成模式。Provider 负责提供 POI 搜索、路线计算、天气查询等服务。系统通过 `PROVIDER_MODE` 环境变量控制 Provider 的选择和降级行为。

## Provider 模式

### DEMO_ONLY

- 本地开发和无凭据环境的默认模式。
- 不发起任何外部 API 调用。
- 使用确定性 Demo 数据，可复现。
- 结果必须清楚标记为估算值。
- Demo 费用和路线是明确标注的估算值，不代表实时供应商结果。

### REAL_ONLY

- 生产环境默认模式。
- 要求配置真实 `AMAP_WEB_SERVICE_KEY`。
- 完全使用真实 Provider，失败即失败。
- 不构造或调用任何 Demo Provider。
- Provider 失败经有限重试后发布 failure v2，不能转换为 Demo 成功。

### REAL_WITH_EXPLICIT_FALLBACK

- 仅供内部演示或容错验证使用。
- 同时构造真实和 Demo Provider。
- 降级仅在 `ProviderFallbackPolicy` 集中白名单明确允许时发生。
- Production 不应使用此模式。

## 高德地图（AMap）集成

### 服务端 API

- POI 搜索：地点查询、周边搜索。
- 路线规划：步行路线、驾车路线。
- 使用服务端 Web Service Key（`AMAP_WEB_SERVICE_KEY`）。
- 结果包含 `provider=AMAP` 和 `estimated=false` 标记。

### 浏览器地图

- 使用独立的 Web JS Key（`VITE_AMAP_WEB_JS_KEY`）和安全密钥（`VITE_AMAP_SECURITY_CODE`）。
- Key、安全密钥和域名白名单必须属于同一高德应用。
- 最终浏览器域名能加载真实底图，缺 Key 或失败时页面显示降级视图而非空白。

### Key 分离原则

服务端 Web Service Key 与浏览器 Web JS Key 必须分开使用，不能共用。两个 Key 通常属于同一高德控制台账号下的不同应用。

## QWeather 集成

### 天气数据

- 当前天气。
- 7 日天气预报。
- 近期历史天气（套餐范围内）。
- 使用控制台分配的专用 HTTPS Host（`QWEATHER_API_HOST`），不能使用开发默认 Host。

### 授权与归因

- QWeather 数据使用必须保留 `fxLink` 归因链接。
- 安全归一化后的实际链接贯穿到城市来源与可信天气事实。
- 非法类型、域名、端口或畸形 URL 候选被忽略。
- 没有其他有效候选时回退官方首页。

### 降级策略

- QWeather 运行失败且 AMap 可用时，显式回退到 AMap 天气并记录原因。
- 只有 QWeather 而无 AMap 时，保持失败可见。
- 规划前 refresh 是 best-effort 增强，不阻断规划。

## 数据来源标记

### Activity 和 Transit 来源

- 每条 Activity 和 Transit 均保留 `provider` 字段。
- Transit 额外保留 `estimated`、距离、时长、polyline 和过期状态。
- 只有 `provider=AMAP` 且 `estimated=false` 的记录才可作为真实 AMap 路线证据。

### completion v8 的来源追踪（承袭 v6）

成功的 completion v8 事件包含可选 `providerProvenance` 对象（字段与 v6 相同）：

- `requestedProviderMode`：请求的 Provider 模式。
- `primaryProvider`：主 Provider。
- `actualProviders`：实际使用的 Provider 列表。
- `fallback`：是否触发降级及原因。
- `operations`：结构化操作记录（Route operation 包含 `transitId`、`fromActivityId`、`toActivityId`、实际 Provider、error category/code、retry count）。

### 顶层来源聚合

| 场景 | 顶层 Provider | 说明 |
| --- | --- | --- |
| 纯 Demo | `DEMO` | `DEMO_ONLY` 模式 |
| 纯 AMap | `AMAP` | `REAL_ONLY` 模式，全部成功 |
| 混合 | `MIXED` | 局部 route fallback，目标 Transit 为 `DEMO/estimated=true` |
| 整单 fallback | `DEMO` | 显式 fallback 下全部降级 |

## 开放时间与时长证据

Provider 可能提供开放时间与游玩时长证据，这些属于**事实层**，用于支撑行程真实性：

- 有可靠开放时间/时长时作为优先事实，并记录来源与新鲜度（随事实快照冻结）。
- Provider 缺失时按 POI 类别、规模和场景使用版本化默认区间（见[行程真实性与旅行骨架](行程真实性与旅行骨架.md)）。
- 已确认的开放时间冲突属于 Hard Validation 硬规则；Provider 无开放时间时计划是否可标"已验证"是未决问题。

## Provider 与领域策略边界

**Provider 不决定规划政策。** Provider 的职责是提供 POI、路线、开放时间和可能的时长证据；领域策略（日类型、骨架结构、校验规则、评分权重、修复策略）由 Python 规划与评估层决定。Provider 数据只作为输入，不改变业务语义。Provider 未提供某类数据时，规划层使用默认值/估算并标记，而不是让 Provider 状态决定是否可规划。

## 缓存与过期策略

- Redis 用于 Provider 响应缓存和短期协调。
- 路线数据有 `stale` 标记表示可能已过期。
- 天气缓存有过期时间。
- Redis 清空只清除缓存，不影响 PostgreSQL 持久化数据。

## 错误分类与重试

### 错误分类

`ProviderErrorCategory` 稳定分类包括：
- `CONFIGURATION`：配置错误
- `AUTHENTICATION`：鉴权错误
- `PERMISSION`：权限错误
- `QUOTA_EXCEEDED`：配额超限
- `RATE_LIMITED`：限流
- `TIMEOUT`：超时
- `NETWORK_ERROR`：网络错误
- `PROVIDER_UNAVAILABLE`：Provider 不可用
- `INVALID_REQUEST`：无效请求
- `NO_RESULT`：无结果
- `UNSUPPORTED_MODE`：不支持的模式
- `MALFORMED_RESPONSE`：响应格式异常
- `DATA_QUALITY_ERROR`：数据质量错误
- `PROVIDER_ADAPTER`：适配器内部错误
- `PLANNING_INFEASIBLE`：规划不可行
- `INTERNAL_ERROR`：内部错误

### 重试策略

- `RATE_LIMITED`、`TIMEOUT`、`NETWORK_ERROR`、`PROVIDER_UNAVAILABLE` 和部分 `MALFORMED_RESPONSE` 可重试。
- 配置、鉴权、权限、配额、无效请求、Adapter 与内部错误默认不重试。
- 默认策略：1 次调用 + 最多 2 次重试，有界指数退避，抖动，`Retry-After` 支持，最大累计时间预算。

### 降级白名单

- 仅在 `REAL_WITH_EXPLICIT_FALLBACK` 模式下生效。
- 默认允许降级的 category：`RATE_LIMITED`、`TIMEOUT`、`NETWORK_ERROR`、`PROVIDER_UNAVAILABLE`。
- `QUOTA_EXCEEDED` 和 `MALFORMED_RESPONSE` 默认不允许降级，可通过 `PROVIDER_FALLBACK_CATEGORIES` 显式添加。
- 配置、鉴权、权限、无效请求、Adapter 和内部错误**不可配置**降级。

## 安全校验

- 服务端 Key 不暴露给浏览器。
- Provider Key、JWT、Cookie、完整请求/响应和堆栈不进入 API、事件或日志。
- 回退日志使用稳定标记 `planning_provider_fallback`，仅包含安全原因、retry count 和关联 ID。
- 日志只允许出现关联 ID、安全 infocode 与错误分类。

## 环境变量

| 变量 | 说明 | 适用范围 |
| --- | --- | --- |
| `PROVIDER_MODE` | `DEMO_ONLY`、`REAL_ONLY` 或 `REAL_WITH_EXPLICIT_FALLBACK` | 全局 |
| `AMAP_WEB_SERVICE_KEY` | 服务端高德 Web Service Key | 服务端 |
| `QWEATHER_API_KEY` | 服务端 QWeather Key | 服务端 |
| `QWEATHER_API_HOST` | QWeather 专用 HTTPS Host | 服务端 |
| `VITE_AMAP_WEB_JS_KEY` | 浏览器高德 Web JS Key | 浏览器 |
| `VITE_AMAP_SECURITY_CODE` | 浏览器高德安全密钥 | 浏览器 |
| `PROVIDER_MAX_ATTEMPTS` | 最大尝试次数，默认 3 | 服务端 |
| `PROVIDER_FALLBACK_CATEGORIES` | JSON 数组；可额外启用降级的 category | 服务端 |

## 已知限制

- 当前真实验收覆盖广州 POI、步行和驾车路线。
- 公交路线未验证。
- 其他城市未纳入真实 Provider 证据。
- QWeather 授权/署名和 fxLink 展示要求需依据实际套餐条款单独确认。

## 历史文档

- [Provider 模式与降级策略 ADR](../adr/Provider模式失败与降级策略.md)
- [P0 本地 AMap 验证记录](../archive/p0-local-amap-validation.md)
