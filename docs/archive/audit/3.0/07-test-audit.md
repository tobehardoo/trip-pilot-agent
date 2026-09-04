# 07 · 测试体系审计

> 审计性质：PROJECT-WIDE AUDIT ONLY · 2026-08-31
> 方法：测试文件盘点 + 分类 + 能力覆盖矩阵 + **实际运行验证**（2026-08-31 实测）

---

## 1. 测试规模

| 模块 | 文件数 | LOC | 框架 | 实测/报告结果 |
|---|---|---|---|---|
| Python（agent-service） | 138 test + 5 benchmarks | 86,036 + 1,620 | pytest + ruff | **实测：1935 passed / 39 skipped / 2 failed**（14.08s，2026-08-31，忽略 3 个真实 AMap 可选用例） |
| Java（travel-server） | 71 | 39,044 | JUnit + Spring Boot Test + Testcontainers | 最近执行报告：**618 tests / 0 fail**（2026-08-30 发布报告 §2） |
| Web | 53 + 5 e2e | 21,778 | Vitest + Vue Test Utils + Playwright | 最近报告：**523 tests / 0 fail，行覆盖 94.37%**；e2e 24 通过/1 环境性失败 |
| scripts | acceptance + golden_scenarios_http + smoke_test + simulate_planning_v1/v2 | 10,308 | 自研 HTTP/规划模拟 | simulate_planning_v2 反事实验证 30/30（既有审计文档） |

### 1.1 README 数字已过期（OBSERVATION / P3）
README.md:170-174 宣称 "Python 1717 / Java 558 / Web 446"，实际 2026-08-30 发布报告为 **1878 / 618 / 523**，本次实测 Python 已到 1935 passed。README 测试数字滞后约 2-3 个迭代，需在 3.0 阶段统一改为"引用 CI/发布报告"而非手写数字。

### 1.2 ⚠️ 本次实测发现 2 个失败测试（重要）
- 文件：`apps/agent-service/tests/test_context_view_construction.py`（**未提交**，git status `??`）
- 失败 1：`test_context_resolved_once_per_day_and_once_per_budget` —— `ValidationError: planning context identity must match the command`（fixture 未带 contextIdentity 与新契约不符）
- 失败 2：`test_attraction_costs_resolved_once_per_candidate` —— `assert 8 == 2`（断言与当前实现不一致）
- 伴随：`src/trip_agent/planning/context_view.py`（**未提交**）与 `infrastructure/amap/planning_provider.py`（**已修改未提交**）
- 结论：**工作树存在进行中的 context_view 抽取重构，重构尚未收敛**（2 个新测试失败）。这不是已发布代码的回归，但意味着「当前工作树 ≠ 最近一次验证通过的快照」。3.0 阶段开始前应先收敛或回退这批改动。

---

## 2. 测试分类

| 分类 | Python 代表 | Java 代表 | Web 代表 |
|---|---|---|---|
| Unit（单函数/单类） | test_daily_schedule / test_candidates / test_opening_hours_rule / test_repair_engine / test_decision_traces | ItineraryServiceTransitEditTest / PlaceRefCanonicalizerTest / TripTitleGeneratorTest | constraint-editor / transit / feasibility / map / amap |
| Integration（跨组件/DB） | test_acquisition_scheduler_integration / test_golden_scenarios | **PostgresIntegrationTest 基类 + 16 个 *IntegrationTest**（TripFlow / ItineraryEditFlow / PlanningCompletionFlow / PlanningTaskFlow / Share / Export / GuideImport / Auth / Review / OutboxBoundaryContract） | api.test / planning-stream.test |
| Contract（契约 schema） | test_messaging_contract_schemas / test_agent_event_contracts / test_feasibility_schema / test_plan_evaluation_contract | PlanningCompletedEventParserTest / PlanningReviewRequiredEventParserTest / FeasibilityReportContractTest / RabbitMessagingRoutingContractTest / PlanningCandidateValidationCommandContractTest | nginx-config.test / region-ref.test |
| E2E（真实链路） | test_acceptance_hard_validation_injection / test_planning_outcome_flow | PlanningCompletedRabbitIntegrationTest / PlanningOutboxBoundaryContractIntegrationTest | Playwright 5 个 spec（agent-workspace / golden-journeys / feasibility-outcomes / v2-critical-journeys / release-smoke / qa-real-chain 排除在 CI 外） |
| Agent 专项 | test_agent_loop / test_agent_resilience / test_agent_dialog_processor / test_decider_factory / test_agent_persistence / test_agent_profile | AgentDialogEventListenerTest / AgentDialogCommandServiceTest | agent-slots / agent-timeline / agent-error-presentation / agent-workspace.spec |
| 回归/黄金 | test_golden_matrix / test_golden_scenarios / test_emitted_day_ordering / test_entry_matrix | TransitLegProviderEstimateMigrationIntegrationTest / TripPaceMigrationIntegrationTest / TrustedFactMigrationIntegrationTest | TripDetailItineraryEditing / TripWorkspaceActions |
| 反事实验证 | scripts/simulate_planning_v2.py（30/30 组 A-G） | — | — |

## 3. 能力覆盖矩阵（测试覆盖的是代码还是系统能力）

| 能力场景 | 测试证据 | 覆盖 |
|---|---|---|
| 正常规划 | test_golden_scenarios / golden-journeys.spec / TripFlowIntegrationTest | ✅ |
| 时间冲突 | test_golden_scenarios（时间窗用例）/ test_opening_hours_rule / test_continuity_rules | ✅ |
| 预算不足 | test_golden_scenarios（预算用例）/ test_budget_policy（budget_policy 测试） | ✅ |
| 营业时间冲突 | test_opening_hours_rule / test_opening_placement / test_repair_window_relaxation | ✅ |
| 必游点冲突 | test_must_visit_rule / test_must_visit_recall / test_b5_characterization | ✅ |
| 固定预约 | test_planning_context_v3（固定安排语义） | ✅ |
| 数据缺失 | test_opening_hours_rule（UNKNOWN 分支）/ feasibility fixtures（opening-unknown-no-evidence 等 30 个 fixture） | ✅ |
| Tool failure | test_agent_resilience / test_provider_failure（providers 测试）/ test_provider_error_mapping | ✅ |
| LLM failure | test_agent_loop（降级 AskingDecider 路径）/ test_decider_factory | ✅ |
| Planner failure | test_provider_fallback_policy / test_planner_pipeline_observability / test_planning_failed_event_v2 | ✅ |
| 重复 Event | PlanningCompletedEventListenerTest / PlanningFailureService 查重测试 / test_planning_outcome_events | ✅ |
| 重试 | test_provider_retry_policy / OutboxPublicationServiceTest（指数退避） | ✅ |
| 超时 | provider 超时测试（test_provider_retry_policy）/ agent transport timeout（test_agent_loop） | ✅ |
| 重新规划 | test_local_replanning / PlanningReviewFlowIntegrationTest / test_replan_service | ✅ |
| 用户修改约束 | dialog 测试（test_agent_dialog）/ candidate validation edit 契约 fixture | ✅ |

**结论**：测试体系是**系统能力覆盖型**而非纯代码覆盖型——关键能力矩阵 15/15 有测试。这是本系统最强的质量资产之一（与契约 fixture 双语言消费、PostgresIntegrationTest 基类、反事实验证套件配合）。

## 4. 已知缺口（OBSERVATION）

| 缺口 | 说明 | 级别 |
|---|---|---|
| DLQ 消费无测试 | 死信队列无消费者（06 §5），因此也无 DLQ 路径测试 | P2（跟随功能缺口） |
| RUNNING 超时恢复无测试 | 无超时扫描代码 → 无对应测试 | P2 |
| qa-real-chain e2e 排除在 CI 外 | CI 不跑真实链路 spec（CI 配置观察） | P3 |
| 工作树未提交重构测试失败 | test_context_view_construction 2 failed（§1.2） | P1（进行中） |
| Java 测试未实测 | 本次审计未跑 mvn test（耗时约 4min）；引用 2026-08-30 发布报告 618/0 | NEED_RUNTIME_VERIFY |

## 5. 判定

> 测试覆盖的是「系统能力」——规划正确性、约束冲突、失败恢复、事件幂等均有端到端或契约级测试；且契约测试为双语言共享 fixture（Java Parser 测试与 Python Schema 测试消费相同 JSON 文件），这是防止两语言契约漂移的正确做法。
> 主要风险不在测试数量，而在**被测系统与发布快照的漂移**（工作树未提交改动）+ **可靠性缺口无恢复路径可测**（DLQ/超时）。
