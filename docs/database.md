# 数据库设计

## Schema 分治

一个 PostgreSQL 实例，两个 Schema：

- **`business`**（Java 拥有）——用户、旅行、行程、规划任务、攻略等业务数据
- **`agent`**（Python 拥有）——知识文档、嵌入向量、Agent 运行记录、评测数据

分 Schema 而非分数据库的理由：V1 只有两个消费者，分 Schema 即可满足隔离需求；跨 Schema 的 JOIN（例如规划证据查询）在同实例内性能可接受；运维只需备份一个实例。

## 为什么行程版本不可变

行程版本不可变（immutable）是一个影响全局的设计决策。它的代价是每次修改都要复制全部活动和交通段，但换来的收益是：

1. **可审计**：每个版本完整记录「谁在什么时间做了什么修改」，不依赖操作日志还原
2. **可回滚**：回滚复制目标快照并创建一个新的不可变版本，不需要逆向计算差异
3. **可比较**：版本差异计算基于两份完整的不可变快照，不担心中间状态
4. **规划可复现**：Python Worker 持有的基线版本不会被并行修改覆盖

表结构：

```sql
-- itinerary 是旅行的「行程头」，指向当前激活版本
itinerary (id, trip_id, current_version_id, ...)

-- 每次变更创建一个新版本
itinerary_version (id, itinerary_id, parent_version_id, version_source, ...)
  -- version_source: PLANNING_TASK | USER_EDIT | LOCAL_REPLAN | ROLLBACK

-- 每个版本有若干天
itinerary_day (id, version_id, day_date, day_index, ...)

-- 每天有若干活动和交通段
activity (id, day_id, ...)
transit_leg (id, day_id, from_activity_id, to_activity_id, ...)
```

`transit_leg.polyline` 始终是 JSON 数组。Provider 已核验的路线至少包含一个坐标点；
用户切换交通方式后生成的 `DEMO` 估算段允许暂时使用空数组，避免把旧交通方式的轨迹误当成
新路线展示，后续重规划可再写入新的轨迹。

## 约束的关系字段与 JSONB 边界

`trip_constraint` 将稳定、需要校验或查询的字段关系化，将结构可演进的列表保存在 JSONB：

```sql
trip_constraint (
  trip_id UUID PRIMARY KEY,
  budget_amount NUMERIC(12,2),
  travelers INT NOT NULL,
  pace VARCHAR(20),
  preferences JSONB NOT NULL,
  fixed_schedules JSONB NOT NULL,
  schema_version INT NOT NULL,
  ...
)
```

预算、人数、节奏和 V2 到返/住宿等字段需要数据库约束与明确迁移，因此使用关系列；
偏好和固定安排是结构化数组，使用 JSONB 并由 Java/Python 契约校验。规划任务另存不可变
约束快照，避免后续编辑改变正在执行任务的输入。

## PostGIS 和 pgvector 的选型

**PostGIS**：镜像安装扩展，为后续空间查询保留能力；当前业务 POI 坐标以经纬度数值列
和消息快照传递，没有建立 geometry 列或 GiST 索引。

**pgvector**：存储城市知识片段的嵌入向量，支持余弦相似度检索。使用 `vector(768)` 类型（维度取决于嵌入模型）。

选择 PostgreSQL 扩展而非独立向量数据库的理由：V1 的知识数据量（每个城市 ~50 个文档，~500 个片段）不需要专用向量数据库的性能；运维复杂度一致（同一个数据库实例）；向量检索结果可以直接 JOIN 文档表。

## 索引策略

| 表 | 索引 | 理由 |
|---|---|---|
| `planning_task` | `UNIQUE(trip_id, idempotency_key)` | 同一旅行内的命令幂等去重 |
| `planning_task_event` | `(task_id, event_id)` | SSE 补发：按任务 ID 查事件，按事件 ID 排序 |
| `outbox_event` | `(next_attempt_at, created_at) WHERE status='PENDING'` | Outbox Publisher 扫描到期的待发送记录 |
| `itinerary_version` | `(itinerary_id, created_at DESC)` | 版本列表和版本比较 |
| `activity` | 查询按 `(itinerary_day_id, activity_order)` 排序 | 当前依赖外键与数据量边界，尚无专用排序索引 |
| `guide_fact` | `guide_fact_identity_idx` | 按 `guide_import_id`、类别与事实哈希去重 |
| `city_source_registry` | `UNIQUE(city_code, source_url)` | 防止同一城市重复注册来源 |
| `city_intelligence_refresh` | `UNIQUE(trip_id, idempotency_key)` | 预热与规划前刷新幂等 |
| `guide_fact` | `(city_code, category, effective_date, expires_at)` | TTL、日期适用性与合并查询 |
| `planning_context_snapshot` | `UNIQUE(planning_task_id)` | 一个任务只冻结一个输入快照 |
| `itinerary_rollback_record` | `UNIQUE(trip_id, idempotency_key)` | 重复回滚返回同一新版本 |
| `planning_fact_impact` | `(itinerary_version_id, day_date)` | 结果页按版本与日期读取解释 |
| `knowledge_chunk` | `(document_id, chunk_index)` | 文档加载后按序取片段 |
| `knowledge_chunk_embedding` | `(embedding_model, embedding_dimensions, chunk_id)` | 先限定模型与维度，再做精确向量距离排序；当前未创建近似向量索引 |

## 迁移策略

使用 Flyway 管理数据库迁移。迁移文件命名 `V{n}__description.sql`，按序执行。

关键迁移原则：
- **向前兼容**。新迁移只增不删列，不重命名已有列。需要收紧约束时新建 NOT NULL 列并提供默认值
- **单实例迁移**。V1 假设迁移时旧版服务已停止，不支持滚动升级期间的 Schema 兼容
- **回滚不迁移**。回滚只切回旧镜像，不执行反向数据库迁移。数据恢复通过备份

### V1.3 向前迁移计划

V1.2 最新迁移为 V19；V1.3 从 V20 继续编号，不修改已发布文件：

- `V20__create_city_source_registry.sql`：来源注册、审核/启停字段、广州/北京/上海初始化
  数据和唯一索引。
- `V21__add_trusted_fact_lifecycle.sql`：规范化文档、刷新状态、事实可靠性/证据跨度/
  结构化值、合并决策、规划上下文快照和 TTL 查询索引。
- `V22__add_itinerary_version_recovery.sql`：版本原因/摘要、回滚来源、回滚幂等与审计、
  规划事实影响。

迁移先增加可空列并回填现有 `guide_import/guide_fact`：已有用户导入统一标为
`COMMUNITY`，已有 `CITY_INTELLIGENCE` 标为 `PROVIDER`，不把历史社区事实升级为官方。
回填完成后再添加约束。现有 V1.2 行程、活动、交通与知识引用不删除、不重写。

## 进一步阅读

- [领域模型](domain.md) — 理解表与领域聚合的对应关系
- [系统架构设计](architecture.md) — 了解 Java 和 Python 如何分治 `business` 和 `agent` Schema
- [部署](deployment.md) — 备份恢复的具体操作步骤
