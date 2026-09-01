# Agent 化路线图（v1.1 主线）

- 文档状态：生效中（未来方向的权威执行路线）
- 最后更新：2026-08-29
- 项目定位：约束驱动旅行规划平台，主线转向「Agent 编排层 + 确定性内核」混合架构
- 关联文档：
  - [项目路线图](项目路线图.md)（当前完成度与 v1.0 历史锚点）
  - [ADR-015 Agent 编排层与记忆系统](../adr/Agent编排层与记忆系统.md)（架构决策）
  - [系统架构](../architecture/系统架构.md)
- 说明：本文档吸收 v1.0 路线中仍有效的后续项（manual TRANSIT 真实化、D1 硬化、模式语义收敛等）；历史批次文档保留在 git 历史。

## 1. 当前基线（2026-08-29）

### 1.1 已具备

- **v1.0 完整收口**（2026-08-21）：约束驱动异步规划、OR-Tools 调度、Hard Validation 11/11、不可变版本、编辑/回滚、分享导出、城市情报；Python 1716 / Java 558 / Web 446 测试基线。
- **Agent 编排层骨架**（`trip_agent/agent/`，已落地）：
  - 约束槽位五态（UNKNOWN / INFERRED / CONFIRMED / REJECTED / USER_OVERRIDE，含 verified_by / override_of / updated_at 出处元数据），INFERRED / REJECTED 禁作硬约束
  - 8 个声明式工具 + 能力注入 runtime + fail-closed 错误语义
  - LangGraph 1.2.11 StateGraph 有界循环（MAX_STEPS=8 / MAX_TOOL_CALLS=16 / MAX_LLM_CALLS=8）
  - validate_itinerary 对 emit 一票否决；AskingDecider 无 Key 确定性退化；模型传输失败 / unparsable 输出均确定性退化（D1 已关闭）
  - Python 测试 1785 passed / 37 skipped（批次 A 后），ruff 全绿

### 1.2 已知缺陷（架构评审确认）

| # | 缺陷 | 位置 | 说明 | 状态 |
| --- | --- | --- | --- | --- |
| D1 | LLM 超时/HTTP 异常未捕获，会击穿整个 run | `agent/graph.py` `StructuredOutputDecider.decide` | 仅 catch JSONDecodeError/TypeError/ValueError | 已关闭（批次 A） |
| D2 | 工具 handler 异常未统一包装 | `agent/tools.py` `ToolRegistry.invoke` | 异常应转 ERROR observation，而非冒泡 | 已关闭（批次 A） |
| D3 | emit_itinerary 暴露给 LLM | `agent/tools.py` | 完成判定应交由确定性代码自动触发 | 已关闭（P2.4：工具表移除 emit，validate 通过即自动发射） |
| D4 | validate_itinerary 守门对象错误（slots 而非 itinerary） | `agent/tools.py` | 缺 build_itinerary 工具，Phase 2 补 | 已关闭（P2.3：守门落到候选行程对象） |
| D5 | update_constraints 的 confirmed 由 LLM 自评 | `agent/tools.py` | 改「LLM 提议 + 代码落槽」，confirmed 判定规则化 | 已关闭（批次 A） |

## 2. Phase 1（必须完成）——生产性基础

**目标**：Agent 层从"能跑的原型"变为"可用、可追踪、可恢复的子系统"。

| 任务 | 修改范围 | 验收标准 |
| --- | --- | --- |
| P1.1 修 D1：decide 捕获超时与 HTTP 错误 → 退化 ask_user / 确定性策略 | `agent/graph.py` + 测试 | 模型超时不产生 FAILED，run 正常收敛 |
| P1.2 修 D2：ToolRegistry.invoke 统一异常包装 | `agent/tools.py` + 测试 | handler 异常 → ERROR observation，run 继续 |
| P1.3 ask_user 支持 options / expected_type | `agent/tools.py` + `graph.py` + 测试 | 澄清带候选选项 |
| P1.4 修 D5：update_constraints 改「LLM 提议 + 代码落槽」 | `agent/tools.py` + `state.py` + 测试 | confirmed 判定规则化（用户原话含该值） |
| P1.5 槽位状态机扩展：REJECTED / USER_OVERRIDE + 元数据（verified_by / override_of / updated_at） | `agent/state.py` + 测试 | 用户否定候选后 Agent 不再重复提出；改值可审计 |
| P1.6 agent_run / agent_step 表 + 幂等键 | Python 侧 schema + repository（不碰 Java business schema） | 轨迹全量落库；command_event_id 幂等 |
| P1.7 AgentState 序列化 + checkpointer 接入 | `agent/state.py` + `agent/graph.py` + Redis/PG backend | 运行中 checkpoint 可保存/恢复 |
| P1.8 AGENT_ASK_USER / AGENT_RESUME 事件契约 | `worker/contracts.py` + JSON Schema + Java parser | 走 schema_version 机制，不破坏 v9–v11 completion |
| P1.9 StructuredOutputDecider 接线现有 `STRUCTURED_MODEL_*` 配置 | `agent/graph.py` + 工厂 | 无新凭据面，与 guide_intelligence 同配置 |

**验收**：Python 测试基线不降（每批开工时实测，当前 1785 passed / 37 skipped）；无 Key 环境 AskingDecider 全链路可跑；D1 / D2 / D5 关闭；D3 / D4 缓解在册（emit 一票否决），随 Phase 2（P2.3 / P2.4）收口。

**进展**：批次 A（P1.1–P1.5）已于 2026-08-29 完成并验收，见[批次 A 验收报告](../execution/2026-08-29-phase1-batch-a/验收报告.md)。P1.9 按就绪审查结论提前完成（决策器工厂 `build_decision_maker` 落地为唯一生产构造点，run 触发入口归 P2.1），见 [P1.9 验收报告](../execution/2026-08-29-phase1-p1.9-decider-wiring/验收报告.md)。批次 B（P1.6 轨迹落库 + P1.7 状态持久化）同日完成：agent_run / agent_step / agent_checkpoint 表、command_event_id 幂等、AgentState 版本化序列化、PG checkpoint 与 `run_agent` checkpoint_sink 流式钩子，见[批次 B 验收报告](../execution/2026-08-29-phase1-batch-b/验收报告.md)。批次 C（P1.8 契约）同日完成：AGENT_ASK_USER / AGENT_RESUME v1 schema、跨语言共享 fixture、Python 模型与 Java parser（契约先行，拓扑归 P2.1/P2.7），见[批次 C 验收报告](../execution/2026-08-29-phase1-batch-c/验收报告.md)。**Phase 1 全部完成，Gate 1 通过（基线 1816 passed）。** Phase 2 已开工：P2.1 于同日完成——传输边界决策见 [ADR-016](../adr/Agent对话传输边界.md)（对话回合走 AMQP），`agent.dialog.queue` 拓扑、AGENT_START/RESUME 分发、`AgentDialogProcessor` 三轮对话全链路与轨迹写回落地，见 [P2.1 验收报告](../execution/2026-08-29-phase2-p2.1-dialog-wiring/验收报告.md)（基线 1826 passed）。P2.2–P2.4 捆绑批同日完成：build_itinerary 触发确定性管线、D4 守门落到真实行程对象、D3 发射改编排层自动触发、回合独立预算，**D1–D5 全部关闭**，见 [P2.2–P2.4 验收报告](../execution/2026-08-29-phase2-p2.2-4-itinerary-loop/验收报告.md)（基线 1843 passed）。P2.7 拆为 7a/7b 两子批，**同日均完成**：7a（Python 事件面）——AGENT_STEP / AGENT_COMPLETED v1 契约与发布，Agent 事件族齐备（ask-user / step / completed）；7b（Java 消费 + SSE 透传）——`agent.dialog.event.queue` 拓扑、三 parser、`business.agent_dialog_message` 落库（eventId 幂等）、`AgentDialogEventHub` SSE（Last-Event-ID 重放、trip 维度订阅），见 [P2.7 验收报告](../execution/2026-08-29-phase2-p2.7-event-consumption/验收报告.md)（基线 1850 passed；Java 36 项断言全绿）。Web 订阅随 P2.8 交付。

**Phase 3 已启动**（按指令提前，P2.8 转 Phase 2 并行余项）：P3.1 于同日完成——WAITING_USER 生命周期（TTL 过期 → EXPIRED）、僵死 RUNNING 崩溃恢复、RUN_IN_PROGRESS 防双执行、稳定原因码；native interrupt() / Redis / 后台清扫按三问纪律**不引入**（取舍记录在批次计划），见 [P3.1 验收报告](../execution/2026-08-29-phase3-p3.1-resumable-interrupt/验收报告.md)（基线 1854 passed）。P3.2/P3.3/P3.4 同日完成：P3.2 跨会话偏好记忆（user_travel_profile + update_preferences 工具 + evidence-match 确认 + 决策注入，见 [P3.2 验收报告](../execution/2026-08-29-phase3-p3.2-profile-memory/验收报告.md)）；P3.3 显式策略选择（策略进契约/状态/轨迹，最小可观测形态，见 [P3.3 验收报告](../execution/2026-08-29-phase3-p3.3-strategy-node/验收报告.md)）；P3.4 轨迹回放 harness 与 5 场景基准（**Gate 2 可测性缺口补齐**，见 [P3.4 验收报告](../execution/2026-08-29-phase3-p3.4-trajectory-replay/验收报告.md)）（基线 1866 passed）。

**P2.8 拆 8a/8b，同日全部完成**：8a——`POST /agent-dialogue/runs` 与 `/runs/{runId}/answers` 触发端点经事务性 outbox 发布 AGENT_START/AGENT_RESUME（含 P3.2 的 userId），所有权守卫 + 幂等键；8b——**旅程风 Web 对话页**（珊瑚 token 换肤、SSE 订阅重放、工具步/问题/行程卡渲染、确认槽位一键入 trip）、COMPLETED 事件增确认槽位投影（三侧契约同步）。**v1.1 主线功能批次全部收官，用户可见闭环贯通，三栈测试全绿（Python 1866 / Java 609 / Web 499）**。见 [P2.8 验收报告](../execution/2026-08-29-phase2-p2.8-user-loop/验收报告.md)。

**Gate 2 评审就绪**：评审材料 = P3.4 回放 harness（5 场景不变量全过）+ 本报告全链路证据 + P2.8 录屏（待录）。**剩余包装项（v1.1.1）**：demo compose profile、中文 README 重写、基准指标表固化、录屏；P3.5 Copilot 嵌入 Workspace 建议在 v1.1.1 后按三问立项。

**风险**：低（契约版本化机制已具备）。**投入：必须，这是地基。**

## 3. Phase 2（提升竞争力）——端到端 Agent 体验

**目标**：对话→决策→执行→校验→评审→解释闭环，Agent 接入主链路。

| 任务 | 修改范围 | 验收标准 |
| --- | --- | --- |
| P2.1 Agent 接入 AMQP：AGENT_START 命令、worker 分流、轨迹写回 | `worker/amqp.py` + `worker/processor.py` + 契约 | 对话命令进入 Agent 路径；现有 planning 路径不变 |
| P2.2 build_itinerary 工具（触发确定性 pipeline，返回行程草案） | `agent/tools.py` + 接线 | 收集完约束可产出草案 |
| P2.3 修 D4：validate_itinerary 改为校验 itinerary | `agent/tools.py` + 测试 | 一票否决落到真实对象 |
| P2.4 修 D3：emit 改由编排层自动触发 | `agent/tools.py` + `graph.py` | LLM 工具表移除 emit |
| P2.5 intent 节点（新任务 / 修改 / 查询分类） | `agent/graph.py` V2 拓扑 | 意图分类准确率基准 |
| P2.6 critic 节点（评审走建议通道，不改硬约束） | `agent/graph.py` + 测试 | 评审意见结构化、可解释 |
| P2.7 SSE Agent Trace 事件（AGENT_THINKING / AGENT_TOOL / AGENT_QUESTION，克制版） | 契约 + Java 透传 + Web | 前端可见 Agent 步骤，原始轨迹走查询 API |
| P2.8 前端对话页（聊天 + 卡片，核心数据模型「约束草稿」） | `apps/web/src/pages/` + 组件 | 对话攒约束 → 一键应用 → workspace 渲染 |
| P2.9 并行维护线：manual-edit TRANSIT 真实化、D1 polyline 硬化复核、模式语义收敛 | 既有 B19 follow-up | 维持原验收标准 |

**验收**：端到端对话→规划→评审→编辑闭环；9 个 benchmark 场景在 Agent 路径结果一致或更优；循环上限生效。

**风险**：中（前后端联动；RabbitMQ 新事件类型需 Java 侧同步）。**投入：值得，这是竞争力所在。**

## 4. Phase 3（高级 Agent 能力）——记忆与人在环路

**目标**：个性化 Agent、跨会话记忆、真正的自主策略。

| 任务 | 修改范围 | 验收标准 |
| --- | --- | --- |
| P3.1 WAITING_USER 可恢复中断（checkpointer + interrupt + TTL） | `agent/graph.py` + `worker/` + 契约 | 中断 → 回答 → 继续，行程版本单调递增 |
| P3.2 user_travel_profile 表 + 偏好注入（用户确认后生效） | Java 侧 + Python 侧 + prompt 组装 | 跨会话偏好生效且可撤回；未确认偏好不生效 |
| P3.3 planner 策略节点（直出 / 检索 / 澄清 / 重规划） | `agent/graph.py` V3 拓扑 | 显式策略选择，可观测可测试 |
| P3.4 轨迹离线评估（回放 + 场景基准扩展） | `benchmarks/` + 评估工具 | 轨迹可回放，Agent 场景纳入基准 |
| P3.5 Copilot 嵌入 Workspace（对话侧栏常驻） | `apps/web/` | 与行程版本状态双向同步 |
| P3.6 远期合并项：交通偏好 ordered-rule 校准、天气/行李输入 | 规划侧 | 独立批次计划 |

**风险**：中高（checkpointer 与现有任务模型整合需设计；profile 数据治理）。**投入：部分值得**——P3.1/P3.2 值得；P3.3 视时间；P3.5/P3.6 按需。

## 5. 完成定义与门禁原则

- 每 Phase 进入前须新建批次计划，完成后独立验收（RED → GREEN → 回归 → 证据落盘）。
- Agent 相关变更不降低既有测试基线（Python 1732 / Java 558 / Web 446）。
- 确定性内核的任何变更必须先过 Hard Validation 与 9 个 benchmark 场景。
- 契约变更走 schema_version 机制，历史事件只读兼容。
- 文档与代码不一致时，先报告差异，不得伪造完成状态。
