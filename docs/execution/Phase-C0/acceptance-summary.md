# 09 — Acceptance Summary（Phase C-0 验收摘要）

> 十问 + Verdict。所有结论见 01-08 文档（file:line 齐备）。

## 十问

**1. 当前生产 Runtime 是否真的调用 LangGraph？**
是——但只在**对话运行时**：`agent.dialog.queue` → AgentDialogProcessor → `run_agent` →
LangGraph AgentLoop（agent/graph.py:31, 365-377，全仓唯一 StateGraph）。生产链路真实：
前端 → Java outbox（AgentDialogCommandService.java:104-138）→ agent.start → Python。
**规划运行时（planning.create → process_planning_create → AmapPlanningProvider）不经过 LangGraph。**

**2. Graph 分类（单选）**：**B——条件 Workflow**（主规划运行时：线性管线 + feasibility 分支 +
有界确定性修复循环）。附注：对话侧的 LangGraph 是受限的类型 C 循环（真实循环 + checkpoint，
但能力面为槽位采集 + demo 行程）。

**3. 谁拥有 Agent State？**
对话运行时：AgentState（state.py:266-296，checkpoint 跨轮持久化，persistence.py:255-267）。
规划运行时：**无人拥有**——全部中间态是 processor/provider 的函数局部变量
（PlanningContextView：planning_provider.py:419；decision_traces：:424-427）。

**4. 谁拥有 Goal？**
当前**无人显式拥有**。对话侧隐含在 user_message + confirmed slots（无 goal 字段，
state.py:274-296 核对）；规划侧隐含在 PlanningCreateCommand.constraints（worker 契约）。
Goal 的"结构化表达"是 MISSING。

**5. PlanEvaluator 是否拥有 Runtime Control 权？**
**否（Post-processing Evaluator）**。输出只进 PLANNING_COMPLETED payload
（processor.py:312-316），completed/review 分支只看 feasibility has_blocker（:298），
无评分驱动的再规划。唯一控制点：硬违例 raise → PLANNING_FAILED 终态（evaluator.py:87-98）。
运行时控制权实际属于 feasibility report 与 repair session。

**6. 是否存在真实 Replan？**
部分。worker 的 **feasibility 修复循环是真实的有界 evaluate→repair→re-evaluate**
（≤3 轮、6 种确定性动作、session.py:61-113）。规划失败的 replan 不存在
（PLANNING_FAILED 终态 ack，amqp.py:917；Java 无自动重试，仅内部诊断手动端点）。
对话循环内 gate 失败无 replan 分支（重复同一动作至 CEILING，graph.py:154-161）。

**7. AmapPlanningProvider 是否是 God Planner？**
**是——"编排 God"**：~2200 行、`_plan_with_skeleton` ~760 行，承担
Observe/Context/Retrieve/Decide-编排/Act-Emit/Explain/Repair 执行 十余职责（04 文档）。
决策逻辑本身已纯模块化（Phase B），所以是编排体量问题而非逻辑不可测问题。

**8. tools.py 是否包含真正的 Agent Tools？**
**是（对话路径）**：9 个工具全部有 JSON Schema、ToolObservation 契约、由 graph act 节点
调用、可注入替换（ToolRuntime）。但生产装配只接 3 项（Demo 行程构建器、窄口径结构门、
偏好存储），4 个观测工具恒 CAPABILITY_MISSING（tools.py:308/323/341/357）；
`build_itinerary` 后端是 DemoPlanningProvider（itinerary_builder.py:176-183）。
规划路径的能力无 Tool 语义（Helper/Adapter）。

**9. 当前 TripPilot 是否可以称为完整 Agent 项目？**
**PARTIALLY**。具备：确定性证据驱动规划（类型 B 管线）、有界评估修复循环、
一个架构真实的 LangGraph 对话 Agent（循环/checkpoint/工具语义/可选 LLM 降级）、
Java 事务性 outbox 编排、SSE 全链。缺失：Agent 入口的规划产物是 demo；
AgentState 无 goal/plan/evaluation/决策记忆；4 工具未接线；评估与循环未在对话侧形成
replan 语义；规划运行时无 State。

**10. Phase C 最小必要改造？**
不是理想重构，是三刀（08 文档）：
- **C-1**：`build_itinerary` 接真规划后端（AmapPlanningProvider 同协议注入 +
  run_validation 口径评估）——让 Agent 入口产出真实行程；
- **C-2**：把已存在的四个观测能力接进 ToolRuntime——让 Agent 真的能观察；
- **C-3**：AgentState 补 goal/plan_evaluation/decision_summaries（checkpoint v2）——
  让评估与决策记忆进入 State。
（C-4 可选：对话内 evaluate→replan 语义。）
明确不做：worker LangGraph 化、Provider 拆 Node、PlanEvaluator 夺权、LLM 扩权、所有权调整。

---

## Verdict

```text
CURRENT CLASSIFICATION:
B（主规划运行时 = 条件 Workflow + 有界确定性修复循环；
  对话侧存在受限的类型 C LangGraph 循环，但不做真实规划）

CURRENT AGENT MATURITY:
2 / 5
（1=线性管线 2=条件分支+有界修复循环+真实对话循环框架
  3=评估驱动 replan 与统一 State 4=真实工具能力闭环 5=自主多轮规划）

REAL AGENT COMPONENTS:
- LangGraph AgentLoop（decide/act 条件回边、观测注入决策、8/16/8 预算，graph.py:365-430）
- AgentState checkpoint/resume 跨轮持久化（state.py:308+；agent_processor.py:230-316）
- ToolRegistry 9 工具带 JSON Schema、fail-closed 注入语义（tools.py:74-89, 551-765）
- 槽位证据信任规则（LLM 只能 propose，用户原话才 CONFIRMED，tools.py:114-131）
- 可选 LLM + 确定性降级（factory.py:144-167，AskingDecider 从不发明值）
- feasibility 修复循环（evaluate→repair→re-evaluate ≤3 轮，session.py:61-113）
- Java 事务性 outbox 编排 + 事件幂等落库 + SSE（OutboxPublisherJob.java:13-16 等）

FAKE / WORKFLOW COMPONENTS:
- 规划运行时全链（类型 B，无 State 无 Graph——但其确定性是资产而非缺陷）
- PlanEvaluator post-hoc（无控制权；控制权在 feasibility）
- 对话侧 DemoItineraryBuilder → DemoPlanningProvider（行程内容为占位）
- 4 个观测工具未接线（CAPABILITY_MISSING）
- StructuralFeasibilityGate 窄口径（4 项结构检查）
- gate 失败后无 replan 分支（重复动作至 CEILING）

CRITICAL GAPS:
P0  对话 Agent 产出 demo 行程（build_itinerary 假后端）
P1  4 观测工具未接线；AgentState 缺 goal/plan/evaluation/决策记忆；
    EMITTED 判据为窄口径
P2  Provider 编排 God（~2200 行）；ThemedExplanation 无消费方；
    规划 WAITING_USER 无恢复路径

MINIMUM REQUIRED CHANGES:
C-1 build_itinerary 真规划后端 + run_validation 口径
C-2 四观测工具接入 ToolRuntime（能力已在 main.py/knowledge 侧存在）
C-3 AgentState 补 goal/plan_evaluation/decision_summaries（checkpoint v2）
（C-4 可选：对话内 evaluate→replan 语义）

RECOMMENDED PHASE C CUTS:
C-1 → C-2 → C-3 →（C-4），一刀一验收，详见 08 文档

FINAL VERDICT:
PARTIALLY
—— 决策基础（Evidence-driven Deterministic Planning）真实且扎实（Phase A/B 已验证），
   Agent Runtime 骨架真实存在（LangGraph 循环 + checkpoint + 工具语义），
   但 Agent 入口尚未产出真实规划、观测工具未接、State 不完整：
   补齐 C-1/C-2/C-3 后，"完整 Agent 系统"的判定即可成立。
```
