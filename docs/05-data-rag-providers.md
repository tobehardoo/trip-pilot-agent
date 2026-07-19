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
- [高德路径规划 2.0](https://lbs.amap.com/api/webservice/guide/api/newroute)

所有高德调用经过内部 Provider 能力边界，POI 与路线分别使用 `MapProvider` 和 `RouteProvider`，Agent 节点不得散落直接 HTTP 请求。

截至 2026-07-17，Python Agent 已完成 POI、路线 Provider 与真实 POI 规划链路：

- `MapProvider` Protocol、不可变请求/POI/成功/失败模型和统一错误码。
- 高德地点搜索 2.0 文本搜索适配器，支持严格城市、分页上限、坐标和行政区解析。
- 高德鉴权、QPS、额度、参数、超时、网络、服务故障和 Schema 变化分类。
- 可选 JSON 缓存边界；缓存键只含查询摘要，不含 Key 或原始查询文本。
- 确定性的 Demo Map Provider，用于无网络测试和后续规划降级。
- 异步 AMAP Planning Provider 按偏好有界查询、按 POI ID 去重，并为每天分配一个真实地点。
- 已分类 Provider 失败和候选不足会降级 Demo；未知异常继续进入消息重试，不会被静默吞掉。
- `RouteProvider` 使用独立的不可变请求、路线、分段和结果模型，当前只开放 `WALKING`，并要求出发时间包含时区。
- 高德路径规划 2.0 步行适配器返回距离、耗时、分段指令和 polyline；空路线、HTTP/业务错误与 Schema 变化使用统一失败类型。
- 确定性 Demo Route Provider 使用球面距离和固定步速生成离线估算，不冒充高德结果。

`PLANNING_COMPLETED v2` 已携带 POI ID、坐标和地址。Java 继续接受 v1 Demo 事件，并通过 Flyway V6 把 AMAP 元数据保存到 `business.activity`；当前行程 API 可直接供后续地图消费。

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

### Phase 11 已实现的第一版边界

- 仓库内 Markdown 使用 TOML front matter（`+++`）描述城市、来源、版本、有效期和适用人群；解析、内容哈希和标题感知切分在 Python `trip_agent.retrieval` 中完成。
- `agent.knowledge_document`、`agent.knowledge_chunk` 与 `agent.knowledge_chunk_embedding` 使用独立迁移和校验和记录；同一文档版本的正文和全部元数据使用完整指纹保持不可变，更新必须创建新版本。
- 片段内容与向量分表保存；同一片段可按 `(embedding_model, embedding_dimensions)` 幂等增加多组向量，模型评测不需要篡改资料版本。检索先选择查询日期下的最新有效文档版本，再使用匹配模型和维度的向量，禁止混入仍在有效期内的旧版本。
- 当前默认的 `demo-hash-v1` 只用于离线开发和契约测试，向量已归一化并记录模型名/维度；真实语义 Embedding 与 Rerank 必须经过固定评测集后再接入，不把 Demo 结果当作生产质量。
- 提供 `trip-agent-knowledge migrate|import|search` 运维入口。第一批广州资料保存在 `knowledge/guangzhou/`，来源均回链到广州市政府页面。
- 数据规模较小时使用精确 cosine 扫描；确认模型和维度后再引入固定维度 HNSW 索引，避免在模型尚未评测时锁死迁移。

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
- 当前路线适配器默认使用 3600 秒 TTL；Redis 读写异常和损坏缓存同样降级到实时 Provider。
- 路线缓存摘要包含六位小数起终点、POI ID、方式、UTC 出发小时、Provider 和数据版本；键中不暴露 Key 或原始坐标。
- 对同一用户和任务限制模型调用与重规划次数。
- 记录缓存命中、Provider 额度错误和估算费用。
- 不缓存包含敏感信息的完整 Prompt 或用户 Token。
