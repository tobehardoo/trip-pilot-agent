# 发布状态

## 当前状态

2026-08-02 的组合代码已完成本地发布候选技术门禁。组合范围覆盖 PlanEvaluation、QWeather/AMap 城市情报、天气时间轴、地图日期联动，以及当前 itinerary version 对应评估结果的恢复与并发保护。

当前结论是“可部署到 staging 的本地 RC 候选”，不是已经通过 staging 签字的发布候选，也不是互联网生产发布。`093aef1` 是初始组合代码基线；强制审计随后修复了 Provider provenance、QWeather 配置/坐标和 planning preflight，最终候选应以审计提交后的分支 HEAD 为准。

这不是互联网生产发布声明。生产发布仍取决于部署者环境中的 HTTPS、Cookie 安全配置、真实 Provider Key、域名白名单和高德 Web JS 底图验收。

阶段 4 的执行顺序、真实 Provider 正负向矩阵、恢复/回滚/告警/soak 门禁和无泄密证据模板见[部署与运维：Staging 验收运行手册](deployment.md#staging-验收运行手册)。仓库预检脚本只能验证静态配置安全性，不能替代真实环境签字。

## 已验证能力

- 规划进度使用版本化契约、Worker 真实阶段事件、Java 幂等持久化、`Last-Event-ID` 回放和浏览器恢复。
- 方案评估使用无 LLM 的确定性规则和版本化权重；完成事件中的结果会持久化并随行程实体 ID 重映射，旧事件和失败任务保持 `evaluation = null`。
- 当前行程版本会恢复关联 planning task 的评估；用户编辑/回滚版本不继承陈旧评分，加载失败可见且可重试，跨行程和重开竞态受请求代次保护。
- 城市情报可组合 QWeather 当前天气、7 日预报、近期历史天气与 AMap 数据；QWeather 失败时按可用数据显式降级，不伪装为成功。
- 行程详情同时呈现评估面板、天气时间轴和地图日期筛选，选中日期在天气与地图之间保持一致。
- 通勤编辑保存 `TRANSIT` 与 `TAXI` 选择、重新计算的时长、费用、Provider 元数据、计算时间和 stale 状态。
- 匿名分享固定到不可变行程版本；Token 使用强随机值，只保存 SHA-256 哈希，并支持撤销、过期和匿名限流。
- PDF 使用支持中文的字体并经过 PDFium 渲染验证；ICS 使用 UTF-8 日历导出。
- 旅行列表支持归档/恢复、分页、目的地搜索和归档可见性切换。
- 内部诊断入口暴露脱敏失败任务上下文，并支持安全失败任务的幂等重试。
- 生产 Compose 能启动 PostgreSQL、Redis、RabbitMQ、Java、Agent API、Worker、Web 和 Prometheus。

## 验证命令

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| Java 测试、Flyway 和验证 | `mvn verify` in `apps/travel-server` | 208 tests passed；Flyway V1–V27；JaCoCo 通过 |
| Python 测试 | `python -m pytest -q --basetemp=.pytest-temp-codex-audit-final` in `apps/agent-service` | 541 passed, 37 skipped |
| Python 静态检查 | `python -m ruff check .` in `apps/agent-service` | 通过 |
| PlanEvaluation 基准 | `python benchmarks/run_plan_evaluation.py` in `apps/agent-service` | 8 scenarios passed；重复运行结果一致 |
| Web 单元测试与覆盖率 | `pnpm test:coverage` in `apps/web` | 126 passed across 24 files；语句/行 94.25%，分支 86.08%，函数 88.46% |
| Web 类型和构建 | `pnpm typecheck` and `pnpm build` in `apps/web` | 通过 |
| 浏览器验收 | `pnpm test:e2e` in `apps/web` | 6 passed；包含评估恢复、天气日期与地图过滤组合场景 |
| Compose | 开发/生产 `config`、生产镜像构建、隔离冷启动与健康检查 | 通过；8 个运行服务健康，`knowledge-init` 退出码 0，Web/API HTTP 200 |
| 仓库安全与文档 | gitleaks 全历史扫描、Markdown links、`git diff --check`、tracked secret-like file 检查 | 通过；87 commits 无泄露 |
| 分享回归 | `mvn -q -Dtest=ItineraryShareFlowIntegrationTest test` | 通过 |

## 数据库迁移

V2.0 证据包含以下新增迁移：

- `V23__complete_transit_leg_writeback.sql`
- `V24__create_itinerary_shares.sql`
- `V25__add_trip_archive_and_search_index.sql`

Flyway 升级路径已从空库验证到 V27。

## 外部发布前置条件

- HTTPS 终止可用，且 `REFRESH_COOKIE_SECURE=true`。
- 七类运行镜像均以批准的 registry `@sha256` 引用部署，解析后的 9 个服务镜像全部与候选证据一致；目标环境不重新构建。
- `INTERNAL_DIAGNOSTICS_TOKEN` 使用强随机值，并区别于其他应用凭据。
- `PROVIDER_MODE=REAL_ONLY` 时提供真实 Provider Key 和对应域名/IP 白名单；旧 `DEMO_MODE` 只用于兼容。
- QWeather Key 与控制台分配的真实 HTTPS Host 成对配置，并完成套餐范围内的真实天气验收。
- 高德 Web JS Key、安全密钥和最终浏览器域名完成真实底图验收。
- 日志脱敏复核通过，确认不会记录 Token、Cookie、Provider Key、模型 Key 或完整攻略正文。

## 已知风险

- 真实 QWeather 专用 Host/Key、AMap 服务端 Key 和 Web JS 最终域名白名单尚未在 staging 验收。
- HTTPS、Secure Cookie、告警、备份恢复、回滚和至少 24 小时 soak 尚无部署环境证据。
- 本地 Windows Maven 需显式指定 ASCII JaCoCo 数据路径；Linux CI 不受该路径编码问题影响，但仍需以远端 CI 结果确认平台一致性。
- 现有浏览器验收覆盖 SSE 恢复与核心组合链路，但不替代真实 Provider、浏览器域名/CSP 和故障注入验收。

## 归档证据

- [V2.5 之后的 P0–P2 执行规划](../post-v2.5-p0-p2-execution-plan.md)：生产可信度、架构治理与产品扩展的后续门禁。
- [P0 执行记录与剩余门禁](../p0-execution-evidence.md)：仓库内发布可信度工作和真实环境前置条件。

- [V2.0 发布证据原文](../v2-release-evidence.md)
- [V2.0 交付清单原文](../v2-delivery-checklist.md)
- [V2.0 审查与验收报告](../v2-code-review-findings.md)
- [V1.3 发布验收历史](../release-checklist.md)
