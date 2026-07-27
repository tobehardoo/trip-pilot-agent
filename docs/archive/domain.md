# 领域模型

## 核心领域划分

TripPilot 的业务可以分为七个核心领域。每个领域拥有自己的数据表、业务规则和对外接口。

### Trip Domain（旅行）

**职责**：管理用户的旅行需求和结构化约束。这是整个系统的输入——用户在创建旅行时定义的「我想要什么样的旅行」。

**拥有的数据**：`trip`、`trip_constraint`

**关键规则**：
- 一个用户可以有多个旅行，每次旅行为 1-7 天
- 约束分为硬约束（必去地点、到返时间、固定预约）和软约束（偏好、节奏、步行上限）
- 约束使用 JSONB 存储而非关系表——因为不同用户会提供不同粒度的约束，JSONB 的灵活性优于大量可空列
- 约束修改使用乐观锁，防止并发覆盖

**对外接口**：`TripService`——创建旅行、获取详情、更新约束

### Itinerary Domain（行程）

**职责**：管理已生成的行程。这是系统的输出——规划完成后持久化的结构化多日计划。

**拥有的数据**：`itinerary`、`itinerary_version`、`itinerary_day`、`activity`、`transit_leg`

**关键规则**：
- 行程版本不可变。每次修改（规划生成、用户编辑、局部重规划）创建新版本，不覆盖历史
- 活动按天组织，天内按顺序排列
- 交通段连接相邻活动，存储方式、距离、时长、polyline 和来源 Provider
- 活动可以锁定（阻止被重规划移动）或解锁

**对外接口**：`ItineraryService`——读取当前行程、预览编辑影响、应用编辑

### Planning Domain（规划任务）

**职责**：管理异步规划任务的生命周期。这是一个状态机，不直接操作行程数据。

**拥有的数据**：`planning_task`、`planning_task_event`

**关键规则**：
- 任务状态严格按照 `QUEUED → RUNNING → COMPLETED/FAILED/CANCELLED` 流转
- 每个任务通过幂等键防止重复创建
- 取消是协作式的：Java 发出取消命令，Python 在下一个检查点响应
- 同一旅行只允许一个修改行程的活动任务存在
- 任务事件（SSE 推送的基础）持久化到 `planning_task_event`，支持历史补发

**对外接口**：`PlanningTaskService`——创建、取消任务；`PlanningTaskEventStreamService`——SSE 事件流

### Knowledge Domain（知识）

**职责**：管理城市知识、RAG 检索和外部攻略情报。

**拥有的数据**：`knowledge_document`、`knowledge_chunk`、`knowledge_chunk_embedding`、`guide_import`、`guide_fact`（知识文档和向量在 `agent` Schema，攻略在 `business` Schema）

**关键规则**：
- 城市知识以 Markdown 文档形式入库，经分块、嵌入后存入 pgvector
- 同一文档的不同版本不互相覆盖；检索时自动选择最新有效版本
- 攻略事实来自用户提交的公开 URL，系统自动提取景点、餐饮、交通、费用等结构化事实
- 每条攻略事实标记来源、采集时间、置信度和有效期

**对外接口**：`GuideImportService`（Java 侧攻略管理）、`RetrievalService`（Python 侧知识检索）

### City Intelligence Domain（城市情报）

**职责**：管理人工注册可信来源、文档规范化结果、事实生命周期、冲突决策、刷新诊断和
不可变规划上下文。

**拥有的数据**：`city_source_registry`、`normalized_document`、`city_intelligence_refresh`、
扩展后的 `guide_fact`、`fact_merge_decision`、`planning_context_snapshot`

**关键规则**：

- 来源由人工注册并审核，至少覆盖广州、北京和上海；运行时不自动发现全网官网。
- 官方来源只有在注册表审核通过且启用时才能产生 `OFFICIAL` 事实。
- 模型输出只是 `ExtractedFactCandidate`，必须通过 JSON Schema、证据跨度和
  `FactValidator` 后才能进入有效事实集合。
- 合并同时考虑类别、来源可靠性、核验时间、适用日期、过期时间、证据与景点身份；
  不使用单一固定分数覆盖所有类别。
- 只有新鲜、证据有效且来自审核官方来源的关闭和预约事实可形成硬约束。
- 高德参考消费与官网门票是不同语义；社区事实只能影响排序、提示和解释。
- 刷新失败保留最后成功事实并标记 `stale`，不得把旧事实伪装成实时数据。
- `PlanningContextSnapshot` 在任务创建时冻结并带 `schemaVersion`；同一任务重试复用原快照。

规范化端口固定为：

```text
DocumentSource → DocumentFetcher → DocumentNormalizer
  → NormalizedDocument → RuleFactExtractor / StructuredModelFactExtractor
  → FactValidator → FactMerger
```

`NormalizedDocument` 至少保存文档 ID、来源、城市、标题、标准化正文、内容哈希、编码、
语言、抓取时间、元数据与原始可靠性。公开 URL 继续执行 HTTPS、DNS 公网地址、同域
重定向、超时与大小限制；小红书只接受用户主动提供的分享正文，不保存 Cookie 或绕过访问控制。

### Identity Domain（身份）

**职责**：用户注册、登录和会话管理。

**拥有的数据**：`user_account`、`refresh_token`

**关键规则**：
- 密码 BCrypt 哈希存储
- Access Token（JWT，短期）用于 API 调用，Refresh Token（HttpOnly Cookie，长期）用于无感续期
- Refresh Token 轮换：每次使用后签发新 Token 并撤销旧 Token

**对外接口**：`AuthService`——注册、登录、刷新、登出

### Version Domain（版本）

**职责**：行程版本的生命周期管理——创建版本、复制知识引用、比较版本差异。

**为什么要独立成域**：
版本操作（`persistKnowledge`、`copyKnowledge`、版本比较）会在三个场景中被调用——规划完成、用户编辑、局部重规划。如果留存在 Itinerary 或 Planning 中，要么代码在三处重复，要么一个域跨越另一个域的职责边界。独立的 Version 域让版本克隆和知识引用复制成为可测试的单元操作。

**关键规则**：
- 每个版本记录父版本、创建原因（`PLANNING_TASK`、`USER_EDIT`、`LOCAL_REPLAN`、
  `ROLLBACK`）和可选关联规划任务
- 版本中包含的知识引用（`itinerary_version_knowledge`）和规划证据（`guide_evidence_snapshot`）不被后续版本修改
- 版本比较基于不可变版本 ID，不需要快照整个行程
- 回滚不修改历史版本或把指针直接指回旧版本；它复制目标版本并创建新的 `ROLLBACK`
  版本，记录 `rollbackFromVersionId`、幂等键、操作者和审计时间
- 结构化差异按稳定活动身份与内容匹配，输出新增、删除、移动、时间、交通、预算、
  日期、锁定状态、规划事实及影响原因的变化

## 聚合关系

```
User
 ├── Trip
 │    ├── TripConstraint
 │    ├── PlanningTask
 │    │    └── PlanningTaskEvent
 │    ├── CityIntelligenceRefresh
 │    ├── PlanningContextSnapshot
 │    └── GuideImport
 │         └── GuideFact
 │
 └── Itinerary
      └── ItineraryVersion
           ├── ItineraryDay
           │    ├── Activity
           │    └── TransitLeg
           ├── KnowledgeCitation
           └── PlanningFactImpact
```

## 数据所有权

**Java 拥有业务事实**（`business` Schema）：
- 用户、偏好、旅行、约束
- 规划任务及对用户可见的进度事件
- 最终行程、版本、活动和交通段
- Outbox 和审计记录
- 攻略导入和事实
- 城市来源、刷新、事实冲突、规划快照和影响记录

**Python 拥有 Agent 执行事实**（`agent` Schema）：
- Agent 运行和步骤记录
- 工具调用和模型调用日志
- 城市知识文档、片段和嵌入向量
- 评测用例和评测运行

**规则**：Python 不直接修改 `business` 表，Java 不直接修改 `agent` 表。双方通过消息契约通信。

## JSONB 与关系表的边界

适合 **JSONB** 的数据（结构灵活、扩展性强）：
- 用户约束（不同用户提供不同粒度的约束）
- Agent 中间候选方案
- 模型和 Prompt 配置快照

适合**关系表**的数据（需要查询、排序、约束）：
- 日期、活动顺序、起止时间、费用
- POI 引用和交通段
- 行程版本父子关系
- 状态、权限和审计字段

核心原则：**不把完整最终行程只保存成不可查询的大 JSON**。

## 并发控制

- 所有修改命令携带客户端看到的版本号
- 数据库使用乐观锁（版本字段），冲突时返回 `409 Conflict`
- 同一旅行只允许一个修改行程的活动任务
- 同一旅行同一刷新幂等键只能有一条刷新记录；数据库行锁和版本号阻止旧刷新覆盖新快照
- Redis 锁只做快速拦截，数据库约束是最终保障

## 进一步阅读

- [数据库设计](database.md) — 表结构、索引策略、JSONB 与关系表的边界选择
- [系统架构设计](architecture.md) — 各领域如何在运行时协作
- [接口与消息契约](api.md) — 领域之间的通信协议
