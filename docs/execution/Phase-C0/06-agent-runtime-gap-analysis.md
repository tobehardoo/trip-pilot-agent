# 06 — Agent Runtime Gap Analysis（Fake Agent 反模式 + Phase B 成果归属）

> Phase C-0 · 逐项判定，全部带证据。

## 1. Fake Agent 反模式核对

| 反模式 | 判定 | 证据 |
|---|---|---|
| **FA-1** Graph 只是函数调用包装 | **部分存在** | LangGraph 循环结构真实（条件回边 + 观测分支，graph.py:365-430）；但 `build_itinerary` 工具后端是 Demo（itinerary_builder.py:176-183），若把"图里包一个 demo 调用"算 FA-1，则对话图的**规划能力部分**命中 FA-1 |
| **FA-2** State 只是 Request+Result | **部分存在** | AgentState 远超 request+result（slots/observations/pending/steps/strategy，state.py:274-296）；但规划运行时**没有 State**（processor.py 局部变量），且 AgentState 缺 goal/candidates/evaluation/decision-memory（02 文档） |
| **FA-3** Evaluator 没有控制权 | **存在（规划路径）** | PlanEvaluator 输出只进事件 payload（processor.py:312-316），无 Graph Edge、无再规划分支；控制权在 feasibility has_blocker（:298）。对话路径例外：gate 结果直接决定 EMITTED（graph.py:417-420）——有控制但口径窄 |
| **FA-4** Tools 没有 Runtime Consumer | **不存在（对话路径）** | tools 由 graph act 节点真实调用（graph.py:407）；但 4 个工具无生产后端（CAPABILITY_MISSING，tools.py:308/323/341/357）——"有消费者、无能力" |
| **FA-5** 所有 Intelligence 都在 Provider | **存在（规划路径）** | AmapPlanningProvider ~2200 行、`_plan_with_skeleton` ~760 行（04 文档）；决策逻辑虽已纯模块化，编排/发射全部在 provider 内，Agent 不可达 |
| **FA-6** 没有 Replan（失败即终态） | **部分存在** | ✅ 修复循环是真实的有界 evaluate→act→re-evaluate（session.py:61-113）；❌ 但动作空间是 6 种预编排修复（catalog.py:34-66），失败终态 PLANNING_FAILED 无重试（amqp.py:917），WAITING_USER（规划）无恢复路径 |

## 2. Phase B 成果与 Agent Runtime 的关系（用户 §十二的核心问题）

| Phase B 资产 | 当前位置 | 进 Agent State？ |
|---|---|---|
| PlanningContextView | provider `_plan_with_skeleton` 局部（planning_provider.py:419） | ❌ Provider 内部局部变量 |
| DecisionTrace | result.decision_traces（protocols.py:124-128），进程内 | ❌ 同上（经事件广播但不入任何 State） |
| DecisionExplanation | PLANNING_COMPLETED payload（processor.py:312-316）→ Java 落库展示 | ❌ 展示用途 |
| ThemedExplanation（P2-3） | 纯函数，尚无生产消费方 | ❌ |
| 反事实测试体系 | 测试侧 | — |

**判定：当前是模型 A（Agent State → Provider → 内部完成全部工作 → 返回 Result）。
两个运行时互不相通：规划运行时无 State；对话运行时有 State 但拿不到真实规划。**

## 3. 缺口的根因

不是"缺 LangGraph"（对话侧已有），也不是"缺 LLM"（StructuredOutputDecider 可选，
无 key 确定性降级 AskingDecider，factory.py:144-167——这个降级设计是对的）。
根因是**两个运行时各自建设、能力没有桥**：

```
对话 Agent（有 State、有循环、有工具语义）
   └── build_itinerary ──→ DemoPlanningProvider（假后端）
规划 Worker（有真规划、有真评估）
   └── 无 Tool 语义、无 State、对话不可达
```

## 4. 缺口分级

- **P0**：对话 Agent 的 `build_itinerary` 产出 demo 行程 → 用户在 Agent 入口拿到的不是真实规划。
- **P1**：4 个观测工具未接线（能力存在于 main.py 生命周期与 provider 内部，只差 ToolRuntime 注入）；
  AgentState 缺 goal/evaluation/decision-memory；EMITTED 判据是窄口径结构门而非 run_validation。
- **P2**：规划 worker 的 God-Planner 编排（04 文档）；PlanEvaluator post-hoc 地位（可接受，但应显式声明）；
  ThemedExplanation 无消费方。
