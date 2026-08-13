# B8 编辑与回滚候选重验证执行报告

状态：`COMMITTED（本提交；独立验收 PASS）`

## 实现摘要

- 新增 candidate-validation v1 command、Python 模型/adapter/worker 消费与共享正反 fixtures；
- Java V34 为 planning task 增加 candidate 元数据，编辑与回滚 REST 改为 202 task 语义；
- EDIT/ROLLBACK 复用同一 command、Hard Validator、repair、completion v9/review v1；
- VERIFIED candidate 在同一完成事务中创建新版本、写入全新报告并切 current；
- 非 VERIFIED 只保存 task-scoped candidate/report，不创建版本；
- 编辑锁与 transit 锁跨 command、Worker、completion 持久化保留；
- Web 不再把编辑/回滚响应直接当作正式行程，而是复用规划任务与 SSE 状态机。

## RED→GREEN 关键证据

1. 候选 command 包缺失导致 Python collection/Java outbox 断链；补模型、schema、routing 后 EDIT/ROLLBACK 均可解析；
2. candidate DTO 不接受 MIXED、持久化 Demo transit 无内部 cost、dayType/locked 丢失；逐项补齐并锁定；
3. Java completion/review parser 对 wire 显式 null 的 knowledge freshness 漂移；按既有 schema 的 UNAVAILABLE 语义修正；
4. completion 测试证明 VERIFIED edit 原子生成 USER_EDIT + 新报告；review 测试证明 rollback NEEDS_REPAIR 保持 current；
5. REST 测试锁定 DELETE、MOVE、LOCK、transit edit、跨日 N-1/N/N+1、幂等复用和 stale baseline；
6. Web 原测试仍期待立即返回 Itinerary；更新为 PlanningTask/SSE 后通过。

## 安全边界

- 旧 direct-write application 方法仅由测试专用 controller 用于历史回归；生产 controller 不再暴露绕过接口；
- command payload 与 task 行同时保存 baseline、source version、request hash、changed/impacted dates；
- V34 CHECK 约束 taskType/candidateType/context 字段组合；
- stale candidate completion/review 转为明确失败，不覆盖并发产生的新 current version；
- PlanEvaluation 仍只在最终 VERIFIED 后运行。

## 门禁

- Python 全量：`1336 passed, 37 skipped`；全仓 Ruff：`All checks passed!`；
- Java `mvn verify`：`424 tests, 0 failures/errors/skipped`，JaCoCo 通过，干净库 Flyway 迁移至 V34；
- Web：`311 passed`，typecheck/build 通过，官方 coverage 为
  `96.04% statements / 82.20% branches / 95.52% functions / 96.04% lines`；
- Playwright：`13 passed`（本地缺少 Chrome channel 时使用 CI 配置的项目 Chromium，业务用例未变）；
- Markdown links：`94 files valid`；`git diff --check` 通过；
- staged 为空，未 commit、未 push。

## 残留边界

- Demo/replan 的完整 TripSkeleton/ValidationInputs 与主动放置属于 B9；
- Golden matrix、结构化日志和最终统一验收属于 B10/B11。
