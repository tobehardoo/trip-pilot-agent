# B6J.2 Java Task Event、SSE、Task API、VersionSummary 闭环计划

- 状态：COMMITTED（本提交；最终验收 PASS）
- 创建日期：2026-08-11
- 分支：`codex/feasibility-foundation`
- 已提交基线：`dfc158e9b1f56c79ece1b6419027435657797cf9`（B6J.1 已独立验收 PASS 并提交，不得修改/amend/squash/重建）
- 总控计划：[系统完善长期执行与验收总控计划](../../product/系统完善长期执行与验收总控计划.md)
- 执行报告：`execution-report.md`（含 B6J.2/B6J.2.1/B6J.2.2 历史与修复记录）
- 验收报告：`acceptance-report.md`（保留 NEEDS_CORRECTION、NEEDS_SMALL_FIX、PASS 全部历史；B6J.2.2 最终重新验收 PASS）

## 目标

在 B6J.1 基础上完成 Java read-model 闭环：Task API 返回 feasibilityReport/candidateItinerary、SSE live/replay 完整输出 review/completion outcome、VersionSummary 暴露 report metadata，并处理 B6J.1 登记的 F5 typed entity refs 风险（validator v4）。

## 不可变架构决策

1. 运行时 envelope 不升级：completion schemaVersion=9、review schemaVersion=1、feasibility schemaVersion=1；无 v10/v2/新 routing key/新 Flyway；V33 继续作为 version report 表；failed v2 不变；v1-v8 completion runtime fail closed 不变。
2. F5 采用 typed string encoding（validatorVersion=hard-validator-v4）：
   - `activity:<canonical-lowercase-uuid>`、`transit:<...>`、`poi:<nonblank>`、`text:<nonblank>`
   - 仅按第一个冒号分隔 kind/value；poi/text value 可含后续冒号但非空；总长 ≤200；禁控制字符
   - 未知 kind、空 value、裸 UUID、无前缀字符串在 v4 中 fail closed
   - Python 与 Java 一致编码/验证规则
   - v3 历史报告保留 legacy UUID heuristic；新 producer 不再产生 v3
   - 未知 validatorVersion 在正式 completion 持久化映射路径 fail closed
   - 映射：v4 activity/transit → persisted ID；poi/text 原样保留；activity/transit 无唯一映射 fail closed
   - 准确口径：v4 新运行时消除 UUID-like POI 误映射；v3 历史报告保留 legacy ambiguity；API/SSE 原样暴露带前缀字符串
3. Task API 真值表：
   - SUCCEEDED：feasibilityReport=VERIFIED、candidateItinerary=null、evaluation≠null
   - WAITING_USER：feasibilityReport=UNVERIFIED/NEEDS_REPAIR、candidateItinerary≠null、evaluation=null
   - QUEUED/RUNNING：三者均 null
   - FAILED/CANCELLED：三者均 null，原错误字段保持
   - 禁止从 evaluation 推导 feasibility；禁止伪造 VERIFIED；禁止为 WAITING_USER 生成 evaluation
4. task event 与 DB 三处一致：V33 report_json、PLANNING_COMPLETED task event payload.feasibilityReport、PlanningTaskResponse.feasibilityReport（activity/transit 引用为持久化 ID）。review task event 保存完整 candidate/report（activity:/transit: 指向 candidate 临时节点），不创建 version/current/report 行。
5. SSE：不重新构造业务 payload，发送 task_event 保存的 JSON；live 与 replay 深结构一致；PLANNING_REVIEW_REQUIRED 为本轮 outcome；WAITING_USER 为流可结束状态；Last-Event-ID 不变。
6. VersionSummary 嵌套摘要 `feasibility: {status, reportId, validatorVersion, validatedAt}`；LEFT JOIN 一次查询；无 report 行 → feasibility=null；部分/非法 metadata fail closed。

## 允许修改范围

- Python：`apps/agent-service/src/trip_agent/feasibility/**`（typed refs 与 validator v4 最小修改）
- Java：`apps/travel-server/src/main/java/io/github/tobehardoo/trippilot/{feasibility,itinerary,planning}/**`
- 契约 fixtures：`contracts/fixtures/planning-completed-event-v9/**`、`planning-review-required-event-v1/**`；可新增小型跨语言 typed-ref fixture 目录；不得修改 schema 文件结构或版本
- 测试：`apps/agent-service/tests/**`、`apps/travel-server/src/test/java/**`
- 文档：`docs/execution/B6J2/**`、`docs/execution/README.md`、总控计划、项目路线图、架构文档（事件契约/规划工作流/行程真实性）

## 禁止范围

- `apps/web/**`；repair/replan 算法；编辑/回滚；用户接受 UNVERIFIED；failed v2 schema/producer；completion v8 schema；Rabbit routing；Worker outcome 分流（validatorVersion/typed refs 最小适配除外）；V33 或新 Flyway；部署配置；`.env`；Java 结构化日志（B10）；PlanEvaluation 语义；current version 选择（事务回滚测试断言除外）

## TDD 工作组

- R0：持久化计划与 characterization
- R1：F5 typed refs 与 validator v4（Python + Java RED/GREEN）
- R2：completion report 单一持久化结果（task event payload 含 report、与 V33 一致、refs 映射、insert failure 回滚）
- R3：Task API read model（latest outcome 含 review-required；SUCCEEDED/WAITING_USER/QUEUED/RUNNING/FAILED/CANCELLED 真值表；malformed fail closed）
- R4：SSE live/replay（真实 task_event DB + SseEmitter；WAITING_USER/SUCCEEDED 流终止；Last-Event-ID；owner 隔离；深结构比较）
- R5：VersionSummary（LEFT JOIN 一次查询；历史 null；嵌套 feasibility metadata）
- R6：review 事务回归（task_event insert failure 状态回滚）
- R7：文档与事实收口

## 验证门禁

Python（apps/agent-service）：`uv run pytest tests/feasibility`；`uv run pytest tests/test_planning_outcome_events.py tests/test_planning_outcome_flow.py`；ruff check/format（本批文件）；全量 `uv run pytest`。
Java（仓库根）：定向（FeasibilityReportContractTest、FeasibilityEntityRefMapperTest、新 codec/read-model/SSE/VersionSummary 测试、parser/service/flow 测试）；全量 `mvn --batch-mode -pl apps/travel-server verify`（记录 tests/failures/errors/skipped/JaCoCo/Flyway V33）。
仓库：`python scripts/check_markdown_links.py`；`git diff --check`；`git diff --cached --name-only` 为空。

## 完成标志

全部 R0-R7 与门禁通过，保持 unstaged、未 commit、未 push，输出 `B6J2_READY_FOR_REVIEW` 后停止；不得自我验收、不得创建 acceptance-report、不得进入 B6W。
