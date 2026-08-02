# 下一阶段执行计划

> 2026-08-02 起，PlanEvaluation 与天气/城市情报双线收口、组合验证和发布路线以 [2026-08-02 可执行路线图](roadmap-2026-08-02.md) 为当前事实来源。本文保留此前稳定性切片和历史执行上下文。

## 已完成：显式 Provider 模式与失败策略（2026-08-01）

- [已验证] `DEMO_ONLY`、`REAL_ONLY`、`REAL_WITH_EXPLICIT_FALLBACK` 已进入 `WorkerSettings` 和 provider factory；production 默认 `REAL_ONLY`，旧 `DEMO_MODE=false` 不再隐含 Demo fallback。
- [已验证] `ProviderErrorCategory`、`RetryingMapProvider`/`RetryingRouteProvider`、`ProviderFallbackPolicy`、AMap HTTP/infocode 映射和 `planning-failed-event-v2` 已实现；Java v1/v2 兼容、SSE/API、重复/乱序终态和零版本失败路径均有确定性测试。
- [已验证] 全量门禁为 Python 502/37、Java 195、Web 110；真实 AMap 显式 3/3，completion mixed/多 Transit/双 fallback/UUID 重映射均有定向证据。
- [已验证] completion v6 已以向后兼容可选字段完成成功 provenance 闭环；共享 fixture 同时被 Python Schema 测试与 Java parser/持久化测试消费，v7 未启用。
- [高置信] 下一推荐切片：先按 `project-delivery-baseline.md` 拆分并审查跨主题提交，再在 staging 完成公网 HTTPS/域名白名单/公交路线/长期告警；保持 completion v6，不能借机启用 v7。

## 已完成：真实 Provider、生产 Compose 与恢复验收（2026-07-31）

- [已验证] `RUN_REAL_PROVIDER_TESTS=true` 下真实 AMap 固定样例测试为 3/3；样例 B 已通过完整异步链路并写入 AMAP Activity/Transit，样例 C 明确失败且无半成品版本。
- [已验证] 独立 `trip-pilot-rc` 生产 Compose 冷启动、Rabbit/Redis/Java/Worker/整栈重启、重复完成事件幂等、Worker/Consumer 中断恢复和 Redis 丢失演练均完成。
- [已验证] PostgreSQL 16.9 `pg_dump -Fc` 备份恢复到隔离空库，28 张业务表逐表计数一致，恢复 API 可读取 AMAP 版本。
- [已验证] Java `verify` 179 项、Python 421 项、Web 107 项自动化测试通过；真实 Provider 测试保持显式开关，不进入默认 CI 配额路径。
- [待确认] 公网 HTTPS/证书/域名白名单、长期运行告警和公交路线仍是发布前置条件；本轮结论为 `RC_READY_WITH_LIMITATIONS`。

## 已完成：Transit 身份、数据库事务与完成事件收口（2026-07-30）

- [已验证] 已完成端点无序关联、重复端点拒绝、真实 PostgreSQL 写入故障回滚/同 key 重试，以及 v6 完成事件 wire 合同测试。
- [已验证] 当前决策为保持 v6；`planning-completed-event-v7.schema.json` 不进入运行时发布或消费路径。
- [高置信] 下一推荐切片：仅在产品确认 Transit 成本和 `TRANSIT`/`TAXI` 语义后，独立实施 v7 的 Python producer、Java parser/persistence、Web 展示、migration 需要性评估和跨语言 golden-message 测试。

## 已完成：编辑幂等与 Transit 版本安全（2026-07-30）

- [已验证] 完成原 Phase 1.1：`EditRequestFingerprint` 对单笔和批量编辑只选取影响业务语义的字段，固定对象字段顺序、保留批量编辑顺序，并明确区分字段缺失、`null` 和空值；结果为 SHA-256，未记录原始请求内容。
- [已验证] 完成原 Phase 1.2 的高风险覆盖：多 Transit、活动端点重新映射、锁状态与源 Transit 顺序无关、未受影响版本复制的既有覆盖均可复跑。
- [已验证] 未新增 schema 迁移：V27 已具备所需 `request_hash`、状态和唯一键。历史空白哈希记录采用 `409 IDEMPOTENCY_KEY_CONFLICT` 的保守兼容策略。
- [高置信] 下一项仍应是完成事件 v6/v7 契约决策和全量 Java 门禁；不要把本切片与工作区中未提交的天气、城市情报、Web、Compose 或 CI 变更合并为同一交付物。

## 策略选择

**主策略：C — 测试与稳定性收口；辅助策略：D — 文档与基线收敛。**

现在不宜直接继续功能开发：系统已经有异步任务、不可变版本、Transit、城市情报和多端 UI，最大不确定性在跨边界正确性与当前事实源，而不是功能数量。也不选择 A，因为 P1 幂等与 Transit 组合测试尚未闭环；不选择 B，因为尚无证据表明需要全局重构，现有端点 ID/FK/事务边界可用；不选择 E，因为产品闭环能力大多已存在，先证明其稳定更有价值。[高置信]

完成本阶段后，目标是获得一个干净、可复跑、可解释的发布候选基线：编辑/局部重规划/版本不会悄然误关联 Transit，幂等行为有明确契约，真实 Provider、故障恢复和文档事实均有证据。

## Phase 0：基线确认

### 切片 0.1：隔离当前工作区并固定审计证据

- **目标/背景：** 基线时当前 `main` 有 36 个已跟踪修改和 15 组未跟踪内容；在不知道其归属前，不能把它们并入发布或稳定性修复。
- **修改范围：** Git 工作流、四份基线文档、CI/测试命令记录；由代码所有者确认这些改动应提交到独立分支、保留为当前功能切片或移出工作区。
- **明确不改：** 业务逻辑、数据库 schema、公开 API、Provider 行为。
- **步骤：** 记录 `git status`/当前 SHA；按功能将现有差异归属；在独立干净 worktree 或提交后运行 Java/Python/Web/Compose 门禁；记录实际 Java 与浏览器 E2E 结果。
- **测试/验收：** 工作区归属明确；全量门禁的命令、版本、结果可复跑；文档只引用一个基线身份。
- **风险/回滚：** 不执行丢弃或重置；若归属不明，仅停止合并，不破坏现有变更。
- **完成后更新：** 本文、`current-state-assessment.md`、`project-delivery-baseline.md`。

## Phase 1：最高风险边界修复

### 切片 1.1：编辑幂等键绑定规范化请求

- **目标/背景：** 相同 `Idempotency-Key` 配不同编辑现在会被静默接受为旧结果，且 `request_hash` 未实际使用。
- **修改范围：** `ItineraryService`、`ItineraryMapper`、`ItineraryEditFlowIntegrationTest`；基于既有 V27 表计算并存储规范化单/批编辑请求哈希，读取时比较哈希，冲突时返回既有 `IDEMPOTENCY_KEY_REUSED` 风格的 409。
- **明确不改：** 编辑操作种类、行程表结构、REST 路径、Transit 路线算法。
- **前置条件：** 切片 0.1 完成；确认前端对 409 的展示行为。
- **步骤：** 定义稳定 canonical payload（含版本、操作、目标、Transit 字段与批次顺序）；写入哈希；同 key 同请求返回原 `result_version_id`；同 key 异请求拒绝；处理并发唯一约束竞争。
- **测试/验收：** 单编辑和批编辑均覆盖：重试不新增版本、异请求 409、后来出现新版本后重试仍返回原版本、事务失败不留下完成幂等记录；Testcontainers 集成测试全绿。
- **风险/回滚：** 规范化不稳定会误判；先仅使用既有字段，不需迁移。回滚为代码回退，历史空哈希记录按兼容策略只读处理。
- **完成后更新：** `api.md`、`architecture.md`、本计划和交付基线。

### 切片 1.2：Transit—活动映射与版本持久化测试矩阵

- **目标/背景：** 代码以活动端点 ID 映射 Transit，设计方向正确，但复杂重排没有自动化安全网。
- **修改范围：** 以 `ItineraryEditFlowIntegrationTest` 为主，必要时增加小型 `ItineraryService` 单测；仅在测试证明缺陷时最小修复 `ItineraryService`/`ItineraryMapper`。
- **明确不改：** DTO/Entity 大规模重命名、数据库表重构、重新设计规划算法。
- **前置条件：** 固定 3+ 活动、2+ Transit 的 Testcontainers fixture；确定 `polylineJson` 的比较标准（未修改时原文保持）。
- **步骤：** 覆盖删除活动后的局部重规划端点、移动/重排序、同日多 Transit、lock 后重规划、部分 Transit、活动 ID 全新生成、未受影响 Transit 的原始 JSON/metadata 复制、持久化异常回滚、并发编辑冲突。
- **测试/验收：** 新旧版本活动 ID 不共享；每条 Transit 两端均属于新版本同日活动；未影响日的 Transit 字段完全保留；失败后 current version 未改变；所有测试稳定复跑。
- **风险/回滚：** 测试暴露真正数据问题时不得只改断言；修复必须连同端点映射和版本写入作为一个原子提交。测试可独立回退。
- **完成后更新：** `architecture.md`、`api.md`（若错误语义变化）、本计划和评估文档。

### 切片 1.3：完成事件 v6/v7 契约决策与收口

- **目标/背景：** v7 JSON Schema 和 Transit 成本字段已存在，但 Worker 与 Java 接收器当前固定 v6；文档将其称为“过渡中”。
- **修改范围：** `contracts/messaging`、Python `worker/contracts.py`/序列化、Java `PlanningCompletedEventParser`、契约和集成测试，或将 v7 明确归档为未启用提案。
- **明确不改：** 消息基础设施、行程业务模型、对外 REST 路径。
- **前置条件：** 确认通勤成本是否必须进入当前发布范围。
- **步骤：** 在“启用 v7”与“保持 v6、归档 v7”之间作出单一决策；若启用，四端同一提交升级并验证未知字段/成本精度/模式枚举；若不启用，消除当前状态歧义。
- **测试/验收：** 一个 schema 版本是运行时唯一事实源；Python 产出、JSON schema 校验、Java 解析/持久化、前端展示均通过；旧版本兼容策略明确。
- **风险/回滚：** 消息契约不兼容可能积压或拒绝事件；使用显式版本和消费者兼容测试，回滚为继续接受 v6。
- **完成后更新：** `api.md`、`decision-record.md`、`product.md`、`release.md`。

## Phase 2：核心链路测试补齐

Java 模块 `mvn --batch-mode -pl apps/travel-server verify`、Python 全量测试、Web 单测/类型/生产构建和一条真实浏览器规划旅程已经形成可复跑证据。下一阶段补齐 staging/CI 中的编辑→局部重规划、版本差异→回滚、分享→PDF/ICS 旅程，并解决全库 Ruff 的既有 QWeather 规则问题；不把本机单条浏览器证据扩写成全部旅程认证。[已验证]

## Phase 3：工程收口

真实 Provider 的受控凭据验收、生产 Compose smoke、备份恢复演练、Provider 永久失败/显式回退策略和 completion v6 成功 provenance 已完成并记录在 `docs/release-candidate-validation-report.md`。下一切片只处理剩余边界：先冻结可审查提交，再做公网 HTTPS/白名单验收、真实公交路线、长期运行和告警演练，以及读路径 N+1 的测量后优化。它们仍应以部署证据而不是 README 宣称作为验收物。[已验证]

## 暂缓内容

不做微服务拆分、多 Agent 重构、数据库/前端框架替换、大规模 DTO/Entity 重命名、规划算法重写、多模态/小红书/抖音抓取、商业化或推荐系统。这些事项不能缓解已确认的版本和测试风险。[高置信]
