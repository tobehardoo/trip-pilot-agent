# 数据、RAG 与外部 Provider

## 1. 数据分类

系统必须区分三类数据：

### 动态数据

- 高德 POI、地理编码和路线。
- 天气 Provider 返回的可用预报。
- Provider 的响应时间和数据版本。

### 增强城市知识

- 商圈、美食、文化、季节和旅行提示。
- 重点景点建议游玩时长、适合人群和预约提示。
- 住宿区域优缺点和主题路线。

### 系统估算

- 类别默认游玩时长。
- 出租车费用区间。
- 拥挤程度、强度和远期天气倾向。

数据库和界面都需要保留来源。系统估算不能显示成官方实时信息。

## 2. 高德 Provider

V1 使用高德作为主要地图数据源，能力包括：

- 地理编码和逆地理编码。
- POI 关键字、周边和区域搜索。
- 步行和公共交通路径规划。
- 前端地图、Marker 和路线展示。

官方参考：

- [高德地点搜索 2.0](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch)
- [高德路径规划](https://lbs.amap.com/api/webservice/guide/api/direction)

所有高德调用经过内部 `MapProvider`，Agent 节点不得散落直接 HTTP 请求。

截至 2026-07-16，Python Agent 已完成第一段 Provider 基础设施：

- `MapProvider` Protocol、不可变请求/POI/成功/失败模型和统一错误码。
- 高德地点搜索 2.0 文本搜索适配器，支持严格城市、分页上限、坐标和行政区解析。
- 高德鉴权、QPS、额度、参数、超时、网络、服务故障和 Schema 变化分类。
- 可选 JSON 缓存边界；缓存键只含查询摘要，不含 Key 或原始查询文本。
- 确定性的 Demo Map Provider，用于无网络测试和后续规划降级。

这一实现目前与 Worker 的 `PLANNING_COMPLETED v1` 契约解耦。真实 POI 写入行程版本前，必须先升级跨服务契约及 Java 消费端，不能把 `AMAP` 值直接塞入当前仅接受 `DEMO` 的完成事件。

## 3. 酒店与交通数据边界

### 车票和航班

- 用户输入到达地点、到达时间、返程地点和返程时间。
- 它们作为固定行程约束。
- V1 不获取实时余票，不提供下单。
- 预留 `TransportProvider` 接口和 Mock 实现。

### 酒店

- 用户可以指定酒店，系统将其作为每天起终点。
- 未指定时推荐住宿区域、商圈或地铁站附近区域。
- 可以展示地图中真实存在的酒店 POI，但不承诺实时价格和房态。
- 预留 `HotelProvider` 接口和 Mock 实现。

禁止通过不稳定或不合规的爬虫伪装实时数据。

## 4. Provider 统一返回模型

```text
ProviderResult<T>
├── success
├── data
├── provider
├── errorCode
├── errorMessage
├── retryable
├── latencyMs
├── cached
├── fetchedAt
└── estimated
```

错误至少区分：

- 参数或业务无结果。
- 超时和临时网络错误。
- 限流和额度耗尽。
- Provider 认证失败。
- 响应 Schema 变化。
- 数据不完整或低置信度。

## 5. Demo Provider

必须提供两种运行模式：

```text
real：调用真实模型和地图 API
demo：使用已脱敏、固定、可复现的数据
```

Demo Provider 用于：

- 面试现场无网络演示。
- 自动化测试不消耗额度。
- 固定 Agent 评测输入。
- 模拟超时、限流、非法 JSON 和无解。
- 前端并行开发。

前端必须明确显示演示模式，不能把固定数据伪装成实时结果。

## 6. RAG 使用范围

RAG 负责较稳定的城市知识：

- 商圈特点和住宿区域。
- 本地饮食和饮食区域。
- 城市文化、礼仪和季节建议。
- 景点主题关联和典型组合。
- 特定人群建议。
- 重点 POI 的建议时长和预约提示。

RAG 不负责：

- 实时路线和通勤。
- 可用预报窗口内的天气事实。
- 实时营业状态、票价、房态或余票。

## 7. 知识文档模型

```text
documentId
city
category
title
content
sourceUrl
sourceName
publishedAt
collectedAt
validFrom / validTo
applicableSeason
travelerTypes
reliabilityLevel
version
```

知识片段增加：

```text
chunkId
documentId
chunkIndex
chunkContent
embedding
tokenCount
metadata
```

资料更新创建新版本，不覆盖历史。每次生成行程保留使用过的文档和片段 ID。

## 8. 资料维护方式

第一版使用仓库内 Markdown：

```text
城市资料 Markdown
  -> 格式与来源校验
  -> 清洗、去重
  -> 按标题和语义切分
  -> 生成 Embedding
  -> 写入 PostgreSQL + pgvector
  -> 抽样检查检索结果
```

- 不做通用网页爬虫。
- 每个增强城市先维护约 30 个重点 POI，再扩展到 50 个。
- 后续增加知识库后台上传、版本发布和定时更新。

建议的仓库数据结构：

```text
knowledge/
├── guangzhou/
├── hangzhou/
└── xian/
```

## 9. 检索流程

```text
用户需求
  -> 查询改写：城市 + 月份 + 人群 + 偏好
  -> metadata 过滤：城市、季节、有效期
  -> pgvector 向量召回
  -> 相似度阈值过滤
  -> 可选 Rerank
  -> 返回内容、来源、版本和片段 ID
```

- Embedding 和 Rerank 模型属于“待评测”决策。
- 第一版不引入 Elasticsearch。
- 数据量扩大并证明有关键词召回问题后，再评估 Elasticsearch 混合检索。
- 生成推荐理由时附带引用，前端可以展示资料来源和更新时间。

## 10. 多模型官方能力参考

- [千问 Function Calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling)
- [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode)
- [OpenAI 模型与 API 指南](https://developers.openai.com/api/docs/guides/latest-model.md)

这些链接只证明相关接口能力。模型质量、价格和稳定性会变化，正式路由必须基于项目评测和实现时的官方信息。

## 11. 缓存和额度

- POI、路线、天气分别设置不同 TTL。
- 当前 POI 适配器使用秒级 TTL 的 Redis JSON 缓存；Redis 读写异常和损坏缓存会降级到实时 Provider，不丢弃已经成功取得的数据。
- POI 缓存键使用城市、关键字和数量的 SHA-256 摘要，禁止包含 API Key 和原始查询文本。
- 路线缓存包含起终点、方式、时间段和 Provider。
- 对同一用户和任务限制模型调用与重规划次数。
- 记录缓存命中、Provider 额度错误和估算费用。
- 不缓存包含敏感信息的完整 Prompt 或用户 Token。
