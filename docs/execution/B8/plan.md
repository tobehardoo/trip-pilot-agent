# B8 编辑与回滚候选重验证计划

状态：`COMMITTED（本提交；独立验收 PASS）`

## 基线

- 分支：`codex/feasibility-foundation`；
- 起始 HEAD：`f429f7bfe8dd25db384e1e489e843d35ab11e53b`；
- B7 已提交并通过独立验收；
- `.omo/`、`.serena/`、`docs/audits/` 为保护目录，不纳入批次。

## 目标与不变量

1. 编辑和回滚先形成 task-scoped 不可变 candidate，不直接写 `itinerary_version`；
2. 共用 `PLANNING_CANDIDATE_VALIDATION_REQUESTED` v1，EDIT/ROLLBACK 通过 typed discriminator 区分；
3. `changedDates` 精确记录变更日期，`impactedDates` 必须等于旅程内 N-1/N/N+1；
4. Worker 重新构建 TripSkeleton/ValidationInputs，执行 Hard Validation 11/11 和最多三轮有界 repair；
5. 只有 VERIFIED completion v9 可以原子创建 USER_EDIT/ROLLBACK 正式版本并切换 current；
6. UNVERIFIED/NEEDS_REPAIR 走 review-required v1，current 保持不变；
7. stale trip/version、幂等键复用、非法锁状态和错误 candidate identity 一律 fail closed；
8. 历史报告只用于审计，回滚不得继承历史验证状态。

## TDD 与门禁

- Python：command 正反模型、共享 fixtures、候选投影、outcome/repair；
- Java：REST→task/outbox、idempotency、N-1/N/N+1、VERIFIED 原子提升、review 隔离、stale baseline、V34；
- Web：编辑/批量编辑/回滚返回 PlanningTask，并复用统一 Task/SSE 状态机；
- 全量 Python、`mvn verify`、Web unit/coverage/typecheck/build/E2E、Markdown links、diff check；
- 独立验收 PASS 后才允许提交。

## 非目标

- B9 的 Demo/replan 输入完整化和主动 placement；
- B10 的结构化日志与全量 golden matrix；
- push、PR 或远端交付。
