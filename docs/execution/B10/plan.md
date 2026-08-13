# B10 Golden Scenarios、结构化日志与最终质量收口

- 状态：PASS / COMMITTED（B10 提交）
- 分支：codex/feasibility-foundation
- 基线 HEAD：7c0da66（B9 提交）
- 定位：本地优先小型项目。不引入 staging/TLS/registry/生产告警/24h soak。Prometheus/外部日志平台仍为可选。

## 目标

1. 建立单一权威 Golden Scenario catalog（稳定场景 ID + 期望矩阵），由 Python/Java/Web 三层测试消费或逐字锁定。
2. Python orchestrator 级 Golden 测试（非单条规则直调）。
3. Java 跨层 Golden 测试（真实 Spring/MyBatis/PostgreSQL Testcontainers/Flyway，DB read-back 深断言）。
4. Web Golden Journeys（Playwright，补 10 场景，不重复已有 13 场景）。
5. Java 结构化日志（SLF4J + MDC，8 落点，安全字段，finally 清理）。
6. Python 结构化日志（Worker 边界，caplog 字段断言，不泄密）。
7. 确定性/flaky/质量清理（仅高置信度机械修复）。
8. 文档更新（7 份）。
9. 完整门禁 + 独立验收 + Git 收口。

## 二、功能事实审计（主链矩阵）

审计入口（写代码前逐项核实，不因全绿跳过）：

| # | 主链 | 现状（待审计填写） | 跨层证明 | 审计结论 |
| --- | --- | --- | --- | --- |
| 1 | CREATE | | | |
| 2 | REPLAN | | | |
| 3 | EDIT_VALIDATE | | | |
| 4 | ROLLBACK_VALIDATE | | | |
| 5 | bounded repair | | | |
| 6 | completion v9 | | | |
| 7 | review-required v1 | | | |
| 8 | Java 持久化 | | | |
| 9 | Task API | | | |
| 10 | SSE live/replay | | | |
| 11 | Web authoritative outcome | | | |
| 12 | VersionSummary feasibility metadata | | | |

重点：仅单测无跨层证明的路径；报告声称完成但缺结构/DB 断言；Demo 与 AMap 漂移；枚举漂移（Python/JSON/Java/TS）；malformed fail open；stale/duplicate/rollback 并发遗漏；日志缺失/泄密/MDC 未清理；随机性/顺序依赖/时钟依赖；覆盖率未含新增模块。

## 三、Golden Scenario Matrix

权威位置：docs/architecture/golden-scenario-catalog.md

场景 ID（30）：G01_LATE_ARRIVAL … G30_HISTORICAL_VERSION_WITHOUT_REPORT（见 catalog 逐项矩阵）。

锁定的全局语义（逐项落实，任何一层违反即为缺陷）：
1. VERIFIED 才能创建正式版本。
2. NEEDS_REPAIR/UNVERIFIED 只能形成 review candidate。
3. UNKNOWN/STALE/CONFLICTING evidence 不得形成 hard PASS。
4. AREA_ESTIMATED/UNRESOLVED 住宿不得形成 confirmed continuity PASS。
5. Demo 主旅程可运行，但缺少真实证据时必须 UNVERIFIED。
6. repair 最多三轮，失败历史完整。
7. EDIT/ROLLBACK 不得绕过 candidate 门禁。
8. stale baseline 不得覆盖 current。
9. PlanEvaluation 只能在 VERIFIED 后执行。
10. 历史无 report 必须显示 null/无历史验证，不能伪装 UNVERIFIED。

## 四、实施计划

- B10.1 Python Golden 测试（orchestrator 级，固定 UUID/时间/TZ，不访问网络，不依赖顺序/系统时钟，结构断言，指纹绑定 itinerary，repairAttempts 精确，provenance/fallback/impact 验证，月/年/闰日边界，AMap evidence 不伪装 hard eligible）。发现缺陷：先 RED 后最小修复 GREEN。
- B10.2 Java 跨层 Golden（20 项：command/outbox、completion v9 原子持久化、review-required 不建正式版、stale trip/itinerary baseline、duplicate event、EDIT VERIFIED→USER_EDIT、EDIT NEEDS_REPAIR→WAITING_USER、ROLLBACK VERIFIED→ROLLBACK、ROLLBACK UNVERIFIED 不继承、report JSONB 无损、typed refs、Task API 六态、latest discovery、SSE live/replay/Last-Event-ID、VersionSummary feasibility=null、非法组合 fail closed、insert 失败全回滚、V1–V8 拒绝、V34 CHECK）。DB read-back + JSON 深比较 + 行数/status/eventType 精确断言，禁止 mock service 替代 DB。
- B10.3 Web Golden Journeys（10 场景：edit 成功/待修复、rollback 成功/未验证、opening/meal/duration failure reasonCode、repair exhausted 三轮、WAITING_USER 刷新恢复、SSE reconnect 只应用一次、malformed fail closed、historical feasibility=null 显示"无历史验证"）。
- B10.4 Java 结构化日志：8 落点（PlanningCompletedEventListener/PlanningReviewRequiredEventListener/PlanningFailedEventListener/PlanningCompletionService/PlanningReviewService/PlanningFailureService/PlanningTaskService/TransactionalOutboxPublicationAttempt）；MDC 生命周期 listener 入口填充 + finally 清理；日志事件表（message received/contract rejected/duplicate ignored/stale baseline rejected/candidate queued/version persisted/review persisted/task completed/failed/waiting user/outbox sent/rescheduled/dead）；安全禁止清单；复用既有 trace 设施（若有）。
- B10.5 Python 结构化日志：Worker 边界（command received/provider started/completed/failed/validation result/repair attempt started/completed/stopped/outcome emitted）；字段对齐 Java；标准 logging + caplog 断言；不打印完整对象/原始响应/secret。
- B10.6 确定性清理：随机 UUID 排序、Java/PostgreSQL UUID 排序漂移、datetime.now 未注入、本地 TZ 依赖、unordered set/dict、E2E 固定 sleep、端口冲突、Testcontainers 误判、fixture 漂移、coverage include 漏文件、集成名实不符、containsString 冒充、只断言不抛异常。
- B10.7 文档：规划工作流/事件契约/行程真实性与旅行骨架/测试策略/可观测性/项目路线图/总控计划。
- B10.8 门禁 + 独立验收 + 收口。

## 五、门禁要求

- Python：uv run pytest 0 failed；新增 Golden/logging 模块覆盖率 ≥80%；不减少 Hard Validation 覆盖；记录真实数字。
- Java：mvn verify BUILD SUCCESS、0 failures/errors、JaCoCo、Flyway V34；除非数据模型变化不新增 migration。
- Web：pnpm test/coverage/typecheck/build；CI=1 test:e2e 全绿；branch ≥80%；无 .only/.skip/类型规避。
- 仓库：check_markdown_links.py、git diff --check、staged 空。

## 禁止

- reset/stash/checkout/restore/clean/rebase/amend；push/force push；git add ./-A；commit -a；--no-verify
- 删除/暂存/提交保护目录（.omo/ .serena/ docs/audits/）；处理 .env
- skip、弱化断言、吞异常、改覆盖率阈值制造通过
- 引入 staging/TLS/registry/生产告警范围
- 独立验收 Agent 只能写 acceptance-report

## 验收重点（预留）

1. Golden tests 是否真实跨层而非 mock 拼装。
2. VERIFIED/REVIEW 门禁能否被绕过。
3. 日志是否泄露 payload/secret/Provider body。
4. MDC 异常/duplicate/reject 路径是否残留。
5. Python/Java 日志字段漂移。
6. Golden catalog 与各层测试漂移。
7. edit/rollback candidate 与正式版本隔离。
8. Demo 假 VERIFIED。
9. repairAttempts 真实来自执行非 fixture 伪造。
10. coverage 实际包含本批文件。
11. E2E 不依赖不真实 DB 关系。
12. 随机性与顺序依赖。
13. B9 opening/meal/duration 回归。
14. 文档不重新引入生产部署门禁。
15. execution-report 无夸大。

只有出现 B10_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT 才提交。提交信息：test(platform): establish golden journeys and structured diagnostics
