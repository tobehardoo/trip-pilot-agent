# B6J.1 跨服务安全修复计划

- 状态：COMMITTED（本提交；验收 PASS 见 acceptance-report.md B6J.1.2 最终验收）
- 创建日期：2026-08-10
- 分支：`codex/feasibility-foundation`
- 已提交基线：`faa87379f255e39aa80a12e89703111e2fa46b99`
- 总控计划：[系统完善长期执行与验收总控计划](../../product/系统完善长期执行与验收总控计划.md)
- 执行报告：`execution-report.md`
- 验收报告：`acceptance-report.md`

## 恢复纪律

当前工作区包含 B6 Python 与 Java J1–J5 未提交实现，并可能已有 routing RED 测试。执行 Agent 必须先检查 Git 与复跑现有定向测试，不得 reset、restore、stash、clean 或重建整个 B6。

执行开始前记录：

```bash
git branch --show-current
git rev-parse HEAD
git status --short
git diff --cached --name-only
git log --oneline -8
```

预期 staged 为空；`.omo/`、`.serena/`、`docs/audits/` 保持未跟踪且不处理。

## 目标

在进入 J6 API/SSE read model 前，关闭 Python publisher、Rabbit routing、Java parser/service、FeasibilityReport DTO、review payload 和 baseline/idempotency 之间的真实运行时断链。

## 不可变语义

1. 活跃 completion 只允许 v9 + VERIFIED report + evaluation。
2. review v1 只允许 UNVERIFIED/NEEDS_REPAIR，无 evaluation，不创建版本。
3. v1–v8 completion 运行时 fail closed。
4. stale review 进入 FAILED task event，不进入 WAITING_USER。
5. report 复用唯一 Java `feasibility.FeasibilityReport` 并执行完整 semantic validator。
6. UNKNOWN/STALE/CONFLICTING 或 ineligible evidence 不得产生硬结论。

## RED→GREEN 工作组

### R1：Routing 与实际 wire

- 锁定 routing key 为 `planning.review-required`，Python publisher 与 Java binding 完全一致。
- 捕获真实 AMQP v9/review body，证明 explicit null、schema 和 fingerprint 一致。
- v9/review outcome 使用 `exclude_none=False`；progress/failed 旧消息不变。

### R2：v9-only 正式版本门禁

- parser 拒绝 completion v1–v8。
- 直接绕过 parser 调用 service，也不能创建非 v9、缺报告或非 VERIFIED 的版本。
- report 写入从 optional 改成 required，失败回滚整笔事务。

### R3：Java 报告模型唯一性

- MQ payload 使用 `io.github.tobehardoo.trippilot.feasibility.FeasibilityReport`。
- 删除 MQ 内重复的 report/summary/rule/repair records。
- completion/review parser 调用 `FeasibilityReportValidator`。
- fixtures 至少覆盖非空 EvidenceReference、非空 RepairAttempt、伪造 summary、重复/缺失规则和 opening evidence 安全。

### R4：Review 安全与完整持久化

- eventId 只对同 task + 同 event type 幂等；冲突归属拒绝。
- 校验 tripId、traceId、日期、trip baseline 和 replan itinerary baseline。
- stale task 状态 FAILED，分别写 `STALE_TRIP_VERSION` 或 `STALE_ITINERARY_VERSION`。
- 正常 review task event 保存 candidateItinerary、feasibilityReport、knowledge、factImpacts、providerProvenance。
- 不创建 version、不更新 current。

### R5：报告引用映射

- 临时 activity/transit UUID 映射到持久 ID。
- provider POI、酒店 POI 和普通文本不变。
- RuleResult 与 RepairAttempt 均处理。
- 歧义映射 fail closed；不静默改写 transport itineraryFingerprint。

## 允许修改范围

- `apps/agent-service/src/trip_agent/worker/` 中 v9/review outcome 发布与相关 contract；
- `apps/agent-service/src/trip_agent/feasibility/fingerprint.py`，仅为解除跨语言循环或保持既有算法；
- 对应 Python tests；
- `contracts/messaging/planning-completed-event-v9.schema.json`；
- `contracts/messaging/planning-review-required-event-v1.schema.json`；
- 对应两个 fixture 目录；
- Java feasibility DTO/validator/fingerprint verifier；
- Java completed/review MQ event/parser/listener/routing；
- `PlanningCompletionService`、`PlanningReviewService` 及共用 outcome guard；
- V33 report mapper/record 及相关测试；
- 执行 Agent 可写本批 `execution-report.md`；`plan.md` 只由规划职责维护，`acceptance-report.md` 只由验收 Agent 写入；
- 与本批事实直接相关的架构文档小修。

## 禁止范围

- `apps/web/**`；
- B7 repair/replan；
- 编辑与回滚实现；
- completion v8 schema、failed v2 schema；
- Hard Validator 11/11 规则语义；
- Provider projection、部署配置；
- `.omo/`、`.serena/`、`docs/audits/`、私有 `.env`。

## 验证门禁

Python（工作目录 `apps/agent-service`）：

```bash
uv run pytest tests/test_amqp_worker.py tests/test_messaging_contract_schemas.py tests/test_planning_outcome_events.py tests/test_planning_outcome_flow.py
uv run pytest tests/feasibility
uv run pytest
uv run ruff check .
```

Java 定向测试至少覆盖：

- `PlanningCompletedEventParserTest`；
- `PlanningReviewRequiredEventParserTest`；
- `PlanningReviewRequiredEventListenerTest`；
- `PlanningReviewServiceTest`；
- `PlanningCompletionFlowIntegrationTest`；
- `FeasibilityReportContractTest`；
- routing contract test。

Java 全量（仓库根目录）：

```bash
mvn --batch-mode -pl apps/travel-server verify
```

仓库门禁：

```bash
python scripts/check_markdown_links.py
git diff --check
git diff --cached --name-only
```

必须报告 Java tests/failures/errors/skipped、Flyway V33 和 JaCoCo。定向测试不能替代 verify。

## 完成条件

全部工作组和门禁通过，精确文件范围无越界，保持 unstaged、未 commit、未 push，写入 `execution-report.md` 并输出：

`B6J1_READY_FOR_REVIEW`

然后停止，不进入 B6J.2。
