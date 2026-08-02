# 发布状态

## 当前状态

V2.0 已在 2026-07-27 形成本地交付证据。证据覆盖 Demo 模式、生产 Compose、本地浏览器验收、规划进度、通勤写回、分享、PDF/ICS 导出、归档搜索和诊断入口。

PlanEvaluation 交付闭环已在 2026-08-02 完成本地验证，覆盖确定性评分、警告与决策解释、事件持久化、实体 ID 重映射、SSE 回放、GET 查询和前端展示。

这不是互联网生产发布声明。生产发布仍取决于部署者环境中的 HTTPS、Cookie 安全配置、真实 Provider Key、域名白名单和高德 Web JS 底图验收。

## 已验证能力

- 规划进度使用版本化契约、Worker 真实阶段事件、Java 幂等持久化、`Last-Event-ID` 回放和浏览器恢复。
- 方案评估使用无 LLM 的确定性规则和版本化权重；完成事件中的结果会持久化并随行程实体 ID 重映射，旧事件和失败任务保持 `evaluation = null`。
- 通勤编辑保存 `TRANSIT` 与 `TAXI` 选择、重新计算的时长、费用、Provider 元数据、计算时间和 stale 状态。
- 匿名分享固定到不可变行程版本；Token 使用强随机值，只保存 SHA-256 哈希，并支持撤销、过期和匿名限流。
- PDF 使用支持中文的字体并经过 PDFium 渲染验证；ICS 使用 UTF-8 日历导出。
- 旅行列表支持归档/恢复、分页、目的地搜索和归档可见性切换。
- 内部诊断入口暴露脱敏失败任务上下文，并支持安全失败任务的幂等重试。
- 生产 Compose 能启动 PostgreSQL、Redis、RabbitMQ、Java、Agent API、Worker、Web 和 Prometheus。

## 验证命令

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| Java 测试、Flyway 和验证 | `mvn verify` in `apps/travel-server` | 203 tests passed；Flyway V1–V27；JaCoCo 通过 |
| Python 测试 | `python -m pytest --basetemp C:\tmp\trippilot-plan-eval-20260802` in `apps/agent-service` | 521 passed, 37 skipped |
| Python 静态检查 | `python -m ruff check .` in `apps/agent-service` | 通过 |
| PlanEvaluation 基准 | `python benchmarks/run_plan_evaluation.py` in `apps/agent-service` | 8 scenarios passed；重复运行结果一致 |
| Web 单元测试 | `pnpm test` in `apps/web` | 103 passed across 23 files |
| Web 类型和构建 | `pnpm typecheck` and `pnpm build` in `apps/web` | 通过 |
| 浏览器验收 | `pnpm test:e2e` in `apps/web` | 4 passed |
| 分享回归 | `mvn -q -Dtest=ItineraryShareFlowIntegrationTest test` | 通过 |

## 数据库迁移

V2.0 证据包含以下新增迁移：

- `V23__complete_transit_leg_writeback.sql`
- `V24__create_itinerary_shares.sql`
- `V25__add_trip_archive_and_search_index.sql`

Flyway 升级路径已从历史版本验证到 V25。

## 外部发布前置条件

- HTTPS 终止可用，且 `REFRESH_COOKIE_SECURE=true`。
- `INTERNAL_DIAGNOSTICS_TOKEN` 使用强随机值，并区别于其他应用凭据。
- `DEMO_MODE=false` 时提供真实 Provider Key 和对应域名/IP 白名单。
- 高德 Web JS Key、安全密钥和最终浏览器域名完成真实底图验收。
- 日志脱敏复核通过，确认不会记录 Token、Cookie、Provider Key、模型 Key 或完整攻略正文。

## 已知风险

- `planning-completed-event-v7` 通勤成本链路正在过渡，仍需确认 Python 模型、JSON Schema、Java 事件记录和前端展示全部一致。
- 行程编辑幂等键需要前后端配合补齐。
- 部分读取路径存在 N+1 查询，当前数据量影响低，但需要专项优化。
- 规划进度的持久化前后时序仍有进一步收紧空间。
- 路由守卫、Windows CI 和浏览器级 SSE 恢复测试尚未成为稳定门禁。

## 归档证据

- [V2.5 之后的 P0–P2 执行规划](archive/post-v2.5-p0-p2-execution-plan.md)：生产可信度、架构治理与产品扩展的后续门禁。
- [P0 执行记录与剩余门禁](archive/p0-execution-evidence.md)：仓库内发布可信度工作和真实环境前置条件。

- [V2.0 发布证据原文](archive/v2-release-evidence.md)
- [V2.0 交付清单原文](archive/v2-delivery-checklist.md)
- [V2.0 审查与验收报告](archive/v2-code-review-findings.md)
- [V1.3 发布验收历史](archive/release-checklist.md)
