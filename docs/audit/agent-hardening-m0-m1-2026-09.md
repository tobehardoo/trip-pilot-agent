# TripPilot Agent Hardening — M0/M1 执行报告

日期：2026-09-02
执行范围：M0（AUDIT-01/02/03 修复 + TRUE_SUCCESS_GATE）+ M1（成都 5 次真实 E2E）
上游：`docs/audit/agent-system-audit-2026-09.md`、`docs/audit/agent-hardening-plan-2026-09.md`

---

## 1. 修改文件

| 文件 | 变更 | 原因 |
|---|---|---|
| `apps/agent-service/src/trip_agent/worker/contracts.py` | `AgentCompletedPayload` 移除 `itinerary` 字段 | AUDIT-01（选项 A）：对话框链不再携带权威行程 |
| `apps/agent-service/src/trip_agent/worker/agent_processor.py` | `_publish_completion` 不再塞完整行程，仅摘要+槽位；移除 `Itinerary` import；启动日志标注 decider | AUDIT-01 + AUDIT-03 |
| `apps/travel-server/.../mq/AgentCompletedEvent.java` | `Payload` record 移除 `itinerary` | 契约同步 |
| `apps/travel-server/.../mq/AgentCompletedEventParser.java` | 不再要求 itinerary，且**拒绝**携带 itinerary | 归边后 fail-closed |
| `contracts/messaging/agent-completed-event-v1.schema.json` | payload `required` 仅 summary，去除 itinerary | 跨语言 schema 同步 |
| `contracts/fixtures/agent-completed-event-v1/valid.json` | 移除 itinerary，保留 summary+slots | 跨语言 fixture 同步 |
| `apps/agent-service/src/trip_agent/worker/processor.py` | 新增 `_assert_plannable_outcome` 并在 `_outcome_event` 前 fail-fast | AUDIT-02：天数/活动预校验 |
| `apps/agent-service/src/trip_agent/agent/factory.py` | 新增 `resolve_decider_kind()` | AUDIT-03 |
| `apps/agent-service/src/trip_agent/main.py` | `/health` 暴露 `decider` 字段 | AUDIT-03 可观测 |
| `apps/agent-service/tools/true_success_gate.py` | 新增 TRUE_SUCCESS_GATE 脚本（10 项校验） | 统一真实成功验收 |
| 测试（Python 9 处 / Java 2 处 / 新 3 个测试文件） | 同步契约 + 修复过期 fixture（使手写 fixture 天数与 command 匹配） | 防回归 + 让 fixture 符合真实约束 |

> 说明：修复过程中发现并修正了若干**测试 fixture 本身天数不匹配**的问题（手写 1/2 天行程配 4 天 command）——这是 AUDIT-02 Gate 正确拦截的"假行程"，属测试数据过期而非放宽断言。

---

## 2. 测试

| 测试 | 结果 |
|---|---|
| Python 全量（agent + planning + dialog + worker） | **2031 passed, 42 skipped**（排除 4 个 Windows tmp 权限环境错误） |
| `test_planning_outcome_gate.py`（AUDIT-02 Case1-5 + 空天/None/无活动日） | 6 passed |
| `test_agent_event_contracts.py`（含 serialized wire 无 itinerary 断言） | passed |
| `test_agent_dialog_processor.py` 序列化 wire 断言（`itinerary` not in payload） | passed |
| `test_decider_transparency.py`（decider 透明化） | 3 passed |
| `test_true_success_gate.py` | 4 passed |
| Java `AgentCompletedEventParserTest` / `AgentDialogEventListenerTest` / `RabbitMessagingRoutingContractTest` / `PlanningOutcomeGuardTest` | 全绿 |

---

## 3. TRUE_SUCCESS_GATE

实现于 `apps/agent-service/tools/true_success_gate.py`，10 项校验：

1. status == COMPLETED
2. itinerary exists
3. days > 0
4. days == expected（= end-start+1）
5. every day >= 1 activity
6. every activity valid POI（title + providerPoiId/coordinates）
7. persisted itinerary non-empty
8. frontend itinerary rendered
9. map markers > 0
10. required user-facing result non-empty

输出：`TRUE_SUCCESS` / `FALSE_SUCCESS` + 逐项 PASS/FAIL。

---

## 4. 成都 5 次运行（真实 E2E，非 mock）

场景：`成都 · 2026-09-05 ~ 2026-09-08 · 4天 · 1人 · ¥2500`，链路 Frontend→Java→RabbitMQ→Python→DB→Java→Frontend。

| Run | 变体 | Status | Days | Activities/天 | POI | Map | Frontend | TRUE_SUCCESS |
|---|---|---:|---:|---:|---:|---:|---|---|
| Run 1 | 冷启动完整 | COMPLETED | 4 | 2/6/6/5 | ✓ | 13 | ✓ | **TRUE_SUCCESS** |
| Run 2 | 相同输入重复 | COMPLETED | 4 | 2/6/6/5 | ✓ | 13 | ✓ | **TRUE_SUCCESS** |
| Run 3 | 刷新/重启后恢复 | COMPLETED | 4 | 2/6/6/5 | ✓ | 13 | ✓ | **TRUE_SUCCESS** |
| Run 4 | 完整重新规划 | COMPLETED | 4 | 2/6/6/5 | ✓ | 13 | ✓ | **TRUE_SUCCESS** |
| Run 5 | 最终稳定性 | COMPLETED | 4 | 2/6/6/5 | ✓ | 13 | ✓ | **TRUE_SUCCESS** |

trip_id：4399ca06-… / 280f78e5-… / ac41b301-…（Run2/3 共用 280f78e5，Run3 验证刷新恢复，Run4 在其上重规划）

---

## 5. Agent Loop Evidence

M0 之前本会话已通过 `test_agent_loop` 等（75 passed）确认 Decision→Tool→Observation→Decision 真实发生；M0 期间新增运行时证据：
- AgentCompletedEvent wire 序列化**不再含 itinerary**（`test_agent_dialog_processor`、`test_agent_event_contracts` 双断言）。
- Planner `_assert_plannable_outcome` 在 `_outcome_event` 前拦截非法天数（Case1-5 触发 `PlanningInfeasibleError`）。
- `/health` 暴露 `decider=DETERMINISTIC`（当前环境未接模型，如实报告，不伪装完整 LLM Agent）。
- 成都全栈 E2E：Agent 收集/确认约束 → AGENT_COMPLETED（仅摘要+槽位）→ 前端触发 Planning 管线 → PLANNING_COMPLETED → Java 落库 → SSE → 前端真实渲染 4 天行程。

---

## 6. Remaining Defects

| 级别 | 项 |
|---|---|
| P0 | 无 |
| P1 | 无 |
| P2 | AUDIT-01 已修复（选项 A 归边完成并验证）——关闭 |
| P3 | AUDIT-02（输出侧 fail-fast）已修复——关闭；AUDIT-03（decider 透明化）已修复——关闭 |
| 观察 | ① 当前部署为 DETERMINISTIC decider（未配模型），生产闭环需接模型（health 已如实标注）；② 4 个 acquisition/knowledge CLI 测试在 Windows 因临时目录权限报 ERROR（环境问题，非代码缺陷） |

---

## 7. Phase Decision

验收条件核对：

- [x] AUDIT-01 PASS（AGENT_COMPLETED 不再携带 itinerary，Java 拒绝携带）
- [x] AUDIT-02 PASS（输出侧 fail-fast，Case1-5 通过）
- [x] AUDIT-03 PASS（health 暴露 decider）
- [x] TRUE_SUCCESS_GATE PASS（脚本 + 测试就绪）
- [x] 成都连续 5 次 TRUE_SUCCESS
- [x] 无 P0/P1

**结论：PHASE_1_PASS — READY_FOR_PHASE_2**

（Phase 2 复杂约束与 Phase 3 全国泛化须待用户确认后再开始。）