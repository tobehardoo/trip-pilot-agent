# 当前状态评估（代码与测试基线）

## 2026-08-01 Provider 策略收口

- [已验证] 三种显式模式、旧配置冲突校验、严格真实模式零 Demo 构造/调用、稳定错误分类、有限重试和集中 fallback 白名单均已实现。
- [已验证] `planning-failed-event-v2` 已贯通 Python producer、Java v1/v2 parser/consumer、任务持久化、SSE 与查询 API；重复/乱序失败不会生成版本或覆盖已成功任务，completion 继续使用 v6 并拒绝 v7。
- [已验证] completion v6 可选 provenance 已贯通 Python producer、严格 Schema/共享 fixture、Java parser/event model、版本与终态 JSONB、任务 API/SSE 和 Web 类型/来源标签；历史 v6 缺失字段保持未记录，v7 继续拒绝。
- [已验证] 本轮门禁：Python `502 passed, 37 skipped`，真实 AMap 显式 `3 passed`；Java `195 passed` 且 JaCoCo/Flyway V1-V27 通过；Web `110 passed` 且 typecheck/build 通过；开发/生产 Compose 与 `git diff --check` 通过。
- [高置信] 本切片判断为 `RC_BASELINE_READY_WITH_LIMITATIONS`：局部/整单 fallback provenance 已闭环，mixed 成功由数据库查询、API、SSE 和最小 Web 标签共同验证；限制是工作区仍跨主题未提交、公网 HTTPS/白名单/公交/长期告警仍缺外部证据。

## 2026-07-31 真实 Provider 与发布候选验收

- [已验证] 在显式 `RUN_REAL_PROVIDER_TESTS=true` 下，固定广州样例的真实 AMap POI、步行/驾车路线、两日约束规划和不可行约束测试为 `3 passed`；普通测试默认跳过真实配额测试。
- [已验证] 独立 Compose 项目 `trip-pilot-rc` 使用生产文件、独立端口 `18080/19090` 和独立卷冷启动；8 个长期服务健康，`knowledge-init` 退出码为 0，Flyway 为 V27。
- [已验证] 样例 B 通过 Web/API → Java → Outbox → RabbitMQ → Python → AMap → 完成事件 → Java 持久化 → SSE → Web 全链路，最终版本 `935ee389-efb8-4c19-8be0-4b0b9b56dd52` 为 AMAP。
- [已验证] 样例 C 以 `NO_FEASIBLE_ITINERARY/BUDGET_EXCEEDED` 失败且没有半成品版本；样例 A 曾在真实链路中落到 DEMO，结果明确归类为 `PASS_WITH_FALLBACK`，不是 AMap 样例通过。
- [已验证] 已验证 Rabbit 重启、Redis 清空后重启、整栈重启、重复完成事件、Java Consumer 停机积压、Worker 在 `TASK_ACCEPTED` 后停机回队，以及 PostgreSQL dump/空库恢复。
- [待确认] 尚未取得公网 HTTPS 域名、证书、长期运行和真实公交路线证据，因此本轮不是无条件公开生产认证。

## 2026-07-30 收口更新

- [已验证] 已消除 Transit 列表下标作为身份键：Java/Python 均以完整、唯一的相邻活动端点集校验 Transit；真实数据库中的重复端点会被重规划持久化层拒绝并回滚。
- [已验证] 编辑幂等返回由 `business.itinerary_edit_idempotency.result_version_id` 固定到首次结果，且 PostgreSQL 故障注入证明中途失败不会遗留 `PROCESSING` 或部分版本；同一 key 可在故障解除后成功重试。
- [已验证] v6 是唯一活动完成事件契约。此前“v7 过渡中”的表述已不适用：v7 仅为草案，尚未有完整的 producer/consumer/Web 升级证据。
- [高置信] 下一轮若需要 Transit 成本或 `TAXI`，应作为独立 v7 升级而不是混入版本/幂等稳定性修复。

## 2026-07-30 稳定性切片复验

- [已验证] 编辑幂等记录已从“仅按 key 返回当前版本”改为保存业务字段规范化后的 SHA-256 请求指纹；同 key、同指纹返回原 `result_version_id`，同 key、不同或无法确认的指纹返回 `409 IDEMPOTENCY_KEY_CONFLICT`。
- [已验证] V27 的 `(trip_id, idempotency_key)` 唯一约束用于跨进程并发仲裁。事务先写入 `PROCESSING` 预留记录，成功后更新为 `COMPLETED` 和结果版本；业务校验或持久化失败会整体回滚该预留记录。
- [已验证] 旧记录的空白或 NULL `request_hash` 采取保守拒绝策略，绝不将其视为当前请求的成功重试；无需新增数据库迁移。
- [已验证] `ItineraryEditFlowIntegrationTest` 在 Testcontainers PostgreSQL 中覆盖单笔/批量重试、语义冲突、失败回滚，以及同 key 和异 key 的并发结果。异 key 使用同一基线版本时恰有一个成功，另一个返回 `ITINERARY_VERSION_CONFLICT`。
- [已验证] 多 Transit 局部重规划已不再按 Transit 列表位置继承锁；锁状态按源活动端点 `(fromActivityId, toActivityId)` 匹配，规避源存储顺序变化造成的错配。

> 本文仅报告本轮实际代码与命令证据。当前分支 `main` 的工作区并不干净，故“通过”均指运行时工作区，不应被描述为干净提交的发布认证。

## 完成度判断

**结论：真实 AMap、生产 Compose、恢复演练与 completion v6 provenance 均已取得证据；当前适合 `RC_BASELINE_READY_WITH_LIMITATIONS`，但工作区未提交且不应表述为已完成公网生产发布。**

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 账户、Trip、结构化约束、归档/搜索 | [已验证] | `TripController`/`TripService`、相关集成测试 |
| 异步规划、进度、取消、重试诊断 | [已验证] | `PlanningTaskService`、Outbox、Worker、SSE 测试 |
| Demo 和 AMap Provider 抽象 | [已验证] | `infrastructure/amap/planning_provider.py`、`infrastructure/demo`、显式真实 Provider 测试 |
| 版本化行程、编辑、Transit mode/lock、局部重规划、回滚 | [已验证] | `ItineraryService`、`ItineraryVersionService`、`ItineraryEditFlowIntegrationTest` |
| 分享、PDF/ICS 导出、城市情报和知识证据 | [高置信] | REST 服务、迁移、对应测试类 |
| 真实 Provider 端到端结果 | [已验证] | 独立 RC Compose；样例 B 版本、Activity、Transit 均为 AMAP |
| 可公开生产发布 | [待确认] | 公网 HTTPS、域名白名单、长期运行和公交模式仍未验收 |

## 构建与测试结果

| 检查 | 本轮结果 | 说明 |
| --- | --- | --- |
| `mvn --batch-mode -pl apps/travel-server -am verify` | [已验证] 195/195 通过 | Testcontainers PostgreSQL、Flyway V1→V27、JaCoCo 门槛均通过 |
| `mvn -pl apps/travel-server -Dtest=ItineraryEditFlowIntegrationTest test` | [已验证] 14/14 通过 | Testcontainers PostgreSQL；Flyway V1→V27 成功 |
| 根目录 `mvn verify` | [待确认] | 64 秒执行上限内无结果，被终止；不是失败结论 |
| Agent `pytest --basetemp output/pytest-provider-provenance` | [已验证] 502 通过、37 跳过 | 37 个跳过包含默认关闭的真实 Provider 测试；显式真实测试另为 3/3 |
| Web `pnpm test` | [已验证] 110 通过 / 22 文件 | 生产构建和类型检查也通过 |
| Web `pnpm typecheck`、`pnpm build` | [已验证] 通过 | Vite 生产构建成功 |
| 浏览器真实 E2E | [已验证] | Playwright 截图 `output/playwright/rc-real-amap-itinerary.png`；CSP 修复后无地图脚本阻断 |
| Compose 配置/冷启动 | [已验证] | 开发与生产 `config --quiet`、独立 `trip-pilot-rc` 冷启动和整栈重启均成功 |

Java 测试类数量为 36、Python 测试文件为 45、Web 单测文件为 22，说明项目已有可观测试基础；但数量不等于对版本/Transit 边界的充分证明。[已验证]

## 问题分级

### P0：阻塞性问题

本轮**未发现已证实的 P0**。编辑、完成事件、回滚、真实 AMap 结果写入和备份恢复均有证据；该结论仍不等于公网生产认证。[高置信]

### P1：应先于新功能处理

1. **工作区仍含跨端未提交改动。** Provider 改动已通过当前工作区门禁，但不能描述为干净提交的发布认证；提交时必须按归属拆分。[已验证]
2. **历史不可表达 replan 只能标为未记录。** completion v6 的新 provenance 已覆盖局部与整单 fallback；但旧 `DEMO_ONLY` worker 对含 AMAP 历史 Activity 的 replan 无法满足合法组合，因此为兼容旧成功行为而省略 provenance。消费者不会推断，这不是纯 Provider 证明。[已验证]
3. **公网运行边界未验收。** HTTPS、正式域名/证书/AMap 白名单、长期 soak/告警和真实公交路线仍缺外部环境证据。[待确认]

### P2：一般改进

- `ItineraryService.toItineraryResponse`、版本读取和差异计算按天分别查询活动/Transit，存在数据量增长后的 N+1 风险；目前没有性能回归证据。[高置信]
- `planning-completed-event-v7.schema.json` 和模型的 Transit 成本字段是预备资产，当前 v6 运行路径没有正式收敛说明；应在一次独立契约切片中决定启用或归档。[已验证]
- 本轮只验证广州、步行/驾车路线；公交模式和其它城市未纳入真实 Provider 证据。[已验证]
- 公网 HTTPS、生产域名白名单、真实证书和长期运行告警未在本机完成。[待确认]

### P3：未来增强

真实预订/支付、多城市联程、协作、微服务拆分、多 Agent、推荐商业化和大型采集平台均不是当前缺陷，不应并入稳定性阶段。[文档声明]

## 文档一致性表

| 文档声明 | 代码实际状态 | 一致性 | 证据位置 | 建议 |
| --- | --- | --- | --- | --- |
| README：当前版本 V2.5 | 当前 `main` HEAD 的最新提交仅更新 README；工作区另有未提交功能 | 否 | `git log -1`、`git status` | 先定义本轮基线身份，再统一版本标识 |
| product/release：当前 V2.0 | 代码确有 V27 迁移、编辑/版本/分享等能力 | 部分 | Java 服务、迁移、测试 | 用本轮四文档作事实基线，后续合并/归档旧发布叙述 |
| API：v7 是过渡契约 | Worker 与 Java 接收器均固定 v6；v7 schema 存在 | 部分 | `worker/contracts.py`、`PlanningCompletedEventParser` | 将 v7 明确标为未启用，或单独完成升级 |
| 架构：三种显式 Provider 模式 | `DEMO_ONLY`、`REAL_ONLY`、`REAL_WITH_EXPLICIT_FALLBACK` 已实现；历史样例 A 发生于旧策略 | 是 | `worker/amqp.py`、Provider 策略测试、RC 报告增补 | 保持 production 默认 `REAL_ONLY` |

## 最大风险与产品缺口

Provider 失败、重试、回退与成功 provenance 已统一到 completion v6 的可选扩展；当前最大剩余风险是跨主题未提交工作区和公网运行边界尚未验收。版本、Transit、重复消息、重启和备份恢复已有本地证据；当前适合**受控发布候选环境**，不适合无 HTTPS、白名单和长期运行证据的公开生产承诺。[高置信]
