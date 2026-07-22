# 全局架构审计与优化路线

## 1. 结论

截至 2026-07-19，项目已经具备可演示的跨服务基础链路，但还不是可长期运行的生产版旅行规划系统。按功能风险而不是代码行数粗略估计：基础设施与业务骨架约 75%，Python Provider/Worker 约 60%，前端核心工作流约 70%，RAG 约 45%，知识采集约 15%，生产安全与可观测性约 30%，整体完成度约 55% 至 60%。

这个数字不是测试覆盖率，而是“用户提交真实需求后，系统能否可靠地产生有约束、有来源、可解释、可恢复的真实行程”的完成度判断。

## 2. 已有优势

- Java `PlanningTask + Outbox -> RabbitMQ -> Python -> Completed Event -> SSE` 已有幂等、死信、版本和历史补发契约。
- 高德 POI、步行路线、Redis 缓存和 Demo 降级已有独立 Provider 边界，真实模式不会把 Demo 元数据伪装成真实结果。
- Vue 已完成登录、任务提交、SSE、行程时间轴、地图 Marker 和 polyline 联动。
- RAG 已具备来源版本指纹、片段与向量分表、多模型/维度共存、最新有效版本检索和 CLI 导入。
- Phase 12 已开始把官方来源采集与 RAG 发布隔离，避免任意网页直接写向量库。

## 3. 当前主要不足

### P0：阻塞目标方案闭环

1. Python 当前规划核心仍是 Demo/启发式 Provider，尚未接入固定评测集、真实模型结构化输出、候选评分和 OR-Tools 约束优化。
2. `KnowledgeCitation` 尚未进入规划 Worker、Java 行程版本或 Vue 推荐理由；当前 RAG 检索是独立能力，不影响用户最终行程。
3. 官方采集已完成受控 HTTP、DNS 固定和限速重试，但还没有快照、正文抽取、审核发布和 freshness report。
4. 动态事实（营业时间、票价、预约、天气、交通）还没有统一的“必须实时核验”执行策略。

### P1：生产可靠性和安全不足

1. Refresh Token 仍按文档保存在 `sessionStorage`，公开部署前必须迁移到 `HttpOnly + Secure + SameSite` Cookie。
2. Prometheus、OpenTelemetry、跨服务 `traceId` 和 Agent 费用/Token 指标停留在设计文档，运行代码没有统一观测出口。
3. Compose 主要承载基础依赖，Java、Python、Web 的可复现生产镜像和备份/恢复演练仍未完成。
4. CI 目前没有真实 Java -> RabbitMQ -> Python -> PostgreSQL -> SSE 的全链路作业，也没有浏览器 E2E 作业；单模块测试不能代替系统验收。
5. 外部 Provider 的错误码、重试、限流和预算控制分散在适配器中，缺少统一任务级预算和熔断策略。

### P2：维护成本和扩展性不足

1. `TripDetail.vue`（948 行）、`TripDashboard.vue`（847 行）、`map.py`（489 行）和 `retrieval/repository.py`（364 行）已经超过单一职责的舒适范围。
2. Java/Python/JSON Schema 的消息契约仍以手工同步为主，字段变更容易产生跨语言漂移。
3. 目标目录中 `workflow`、`ranking`、`optimization`、`validation`、`evaluation` 尚未形成实际模块，设计文档容易让完成度看起来高于代码。
4. 目前只维护广州资料，采集、审核和 freshness 策略尚未经过第二个城市验证。

## 4. 优化后的目标结构

```text
Browser
  -> Java API/Security
  -> PlanningTask + Outbox
  -> RabbitMQ command
  -> Python Planning Application
       -> Constraint Validator
       -> Knowledge Port -> Retrieval/Acquisition snapshots
       -> POI/Route/Weather Ports
       -> Candidate Ranker
       -> Optimizer
       -> Citation Builder
  -> Completed Event with itinerary + citations + provider status
  -> Java immutable itinerary version
  -> SSE + Vue timeline/map/source panel
```

Python 只通过 Protocol 依赖 LLM、知识库、地图、天气和优化器；Provider 负责外部 API，Application 负责任务编排，Domain 负责约束和可解释结果。采集模块只能产生候选快照，审核发布适配器才可以调用 `KnowledgeImporter`。

## 5. 优化后的实施顺序

### P0-1：完成知识采集闭环

- HTTPX 条件请求：ETag、Last-Modified 和超时错误分类已于 2026-07-20 完成；DNS 全结果公网单播校验、单次抓取 IP 固定、环境代理隔离和重定向新主机复核已于 2026-07-22 完成。
- 每来源限速、并发安全的实际放行间隔和有上限退避重试已于 2026-07-22 完成。
- `knowledge_resource`、`knowledge_snapshot`、`knowledge_fetch_run`。
- 官方正文抽取、内容质量检查、人工审核和过期报告。

### P0-2：把 RAG 接入规划结果

- 用固定广州评测集比较真实 Embedding/Rerank，不再把 `demo-hash-v1` 用于质量判断。
- Python Worker 返回 `KnowledgeCitation` 和 `freshness`，Java 持久化行程使用的文档/片段版本。
- Vue 展示推荐理由来源、来源时间和 Demo/真实状态。

### P0-3：补齐真实规划能力

- 结构化模型输出和失败修复循环。
- 候选 POI 去重、偏好评分和可解释淘汰原因。
- OR-Tools 时间、预算、固定安排和交通约束优化。
- 规划不可行时返回冲突解释和最小放宽建议，而不是强行生成。

### P1：生产安全与可运维

- Refresh Token Cookie 化、CSP、限流、任务配额和取消语义。
- OpenTelemetry/Prometheus 最小闭环：任务成功率、队列积压、Provider 延迟、模型成本、RAG 新鲜度。
- Java/Python/Web 可复现镜像、数据库备份恢复和发布回滚演练。
- 增加一次 nightly 跨服务 E2E，PR 保持快速契约测试。

### P2：有证据再重构

- 先用行为测试锁定，再把 Vue 大组件拆成 composable、状态容器和展示组件。
- 把 `map.py`、`retrieval/repository.py` 按端口/SQL/缓存职责拆分。
- 生成或校验跨语言消息契约，避免手工复制字段。
- 第二城市只在广州的采集、检索、引用和 freshness 指标稳定后加入。

## 6. 本次全局优化已落地

- CI Python 覆盖率同时包含 `trip_agent.retrieval` 和 `trip_agent.acquisition`。
- CI 明确执行官方来源注册表校验 CLI。
- Web CI 使用 `pnpm test:coverage`，真正执行 Vitest 的 80% 覆盖率门禁，不再只运行无覆盖率测试。
- 系统架构文档明确区分“当前已实现模块”和“目标目录”。
- 后续工作收敛到 P0/P1，不再以增加城市数量或继续堆 UI 作为主要进度指标。
- Windows Maven profile 将 JaCoCo 数据文件写入 ASCII 系统临时目录，本机可直接执行 88 个 Java 测试和 80% 覆盖率门禁。
- Phase 12 条件 HTTP 获取已落地，具备 304、拒绝压缩编码的原始字节流上限、显式重定向复核和错误分类；DNS 全结果公网单播校验、单次抓取 IP 固定、环境代理隔离、每来源限速与有上限重试已完成，快照持久化仍未完成。

本机验证补充：Windows + BellSoft JDK 21 会把 JaCoCo `destfile` 中的中文路径错误转码。`windows-ascii-jacoco-data` Maven profile 只在 Windows 激活，将执行数据写入 `${env.SYSTEMROOT}/Temp`；`mvn --batch-mode -pl apps/travel-server clean verify` 已通过 88 个 Java 测试和 JaCoCo 80% 门禁，Linux CI 仍使用模块 `target` 下的默认数据文件。

## 7. 完成定义

只有满足以下条件，才把项目称为 V1 完成：

- 广州真实需求经过规划、约束校验、POI/路线、知识检索和引用，生成可解释行程。
- 所有动态事实有实时 Provider 或明确的过期拒答策略。
- 任务失败、取消、重试、重复消息和服务重启后都能恢复或给出可操作错误。
- Java、Python、Web、RabbitMQ、PostgreSQL 的关键 E2E 在 CI 或 nightly 通过。
- 公开部署具备 Cookie 安全、限流、日志脱敏、Trace、费用上限和备份恢复记录。
