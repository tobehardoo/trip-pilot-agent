# 04 · Agent 化专项审计（最高优先级）

> 审计性质：PROJECT-WIDE AUDIT ONLY · 2026-08-31
> 核心问题：**TripPilot 的 Python 侧到底是真 Agent，还是 LLM + Workflow？**
> 所有结论锚定 file:line（相对 `apps/agent-service/src/trip_agent/`）。

---

## 1. 判定结论（先行声明）

```
AGENT_WITH_WORKFLOW
```

**外圈（对话/约束收集/策略选择）是「有边界的真 Agent」**：LangGraph 上存在真实的 `decide → act → decide` ReAct 循环，工具由决策器根据状态选择，有步骤/工具/LLM 三重预算上限，工具失败可降级。

**内圈（行程生成）是纯确定性 Workflow**：规划管线零 LLM、零 OR-Tools，全部为规则/确定性代码；发射由 `validate_itinerary` 一票否决，模型无发射工具。

**且存在第三种形态**：未配置 LLM 模型时，整个 Agent 循环退化为规则驱动的确定性向导（AskingDecider），系统仍可完整运行。

---

## 2. 是否存在真正的 Agent State？（6.1）

### 2.1 AgentState 字段（agent/state.py:266-296，实测）
```python
slots（约束槽位）· observations（工具结果轨迹）· pending_question/pending_options/pending_call
steps / stop_reason / answer · user_message · candidate_itinerary
trip_id / user_id · confirmed_preferences（长期偏好）· strategy
```

### 2.2 对照「完整 Agent State」检查表
| 维度 | 有无 | 证据 |
|---|---|---|
| Goal（目标） | ⚠️ 隐式 | 无独立 goal 字段；目标=「收集必填约束+构建行程」（graph.py:340-353 prompt 内化） |
| Constraints | ✅ | slots（state.py:49 ConstraintSlot） |
| Context | ✅ | user_message + slots + confirmed_preferences（graph.py:331-353 prompt 组装） |
| Observations | ✅ | observations 轨迹 + recent_observations()（graph.py:352） |
| Decisions | ✅ | Decision(thought/call/answer/strategy)（graph.py:47-57） |
| Plan | ❌ | **无 plan 字段**（REPLAN 策略声明但无实现，见 §5） |
| Tool results | ✅ | observations 携带工具结果 |
| Evaluation | ⚠️ 外部 | 可行性由外部 validator 一票否决（graph.py:417-420），非 state 内循环评估 |
| Errors | ✅ | stop_reason（STOP_CEILING 等）+ 工具失败降级（graph.py:293-300） |
| Memory | ✅ | user_travel_profile（agent/profile.py:89）+ checkpoint（agent/persistence.py:260-268） |

### 2.3 结论
State 覆盖了 ReAct 循环所需的最小集（slots/observations/decision/answer），但**缺少 Plan 与内部 Evaluation**——Agent 没有"自己评估自己产出"的能力，评估权完全外置给确定性 validator。

---

## 3. 是否存在 Agent Decision Loop？（6.2）

### 3.1 真实执行链（agent/graph.py:365-378，实测）
```python
graph.add_node("decide") / add_node("act") / add_node("finish")
graph.add_edge(START, "decide")
graph.add_conditional_edges("decide", _route, {"act": "act", "finish": "finish"})
graph.add_edge("act", "decide")
graph.add_edge("finish", END)
```
这是**标准 ReAct 循环**：`decide →(有工具调用)→ act → decide → … → finish`。`_route`（条件边）根据 `pending_call` 是否存在决定继续还是结束。上限：`MAX_STEPS=8 / MAX_TOOL_CALLS=16 / MAX_LLM_CALLS=8`（graph.py:38-40）。

### 3.2 判定
✅ **是 Decision Loop，不是固定链**。但循环语义受限：
- **决策者**：StructuredOutputDecider（LLM，graph.py:287-329）或 AskingDecider（规则，graph.py:135-211）。
- **循环终点**：模型无 emit 工具；`validate_itinerary` 通过后由代码自动 EMITTED（graph.py:417-420）。
- **无 replan 边**：REPLAN 仅存在于策略枚举与 prompt（graph.py:227,245,346），工具集（tools.py:551-723）中无任何 replan/修改行程工具 → **声明了 re-plan 能力但循环内不可达**（P1 DEFECT）。

---

## 4. Tool 是否真正属于 Agent？（6.3）

### 4.1 工具清单（agent/tools.py:551-723，9 个）
| 工具 | 行号 | 能力 |
|---|---|---|
| update_constraints | :579 | 提交结构化约束值 |
| ask_user | :602 | 向用户澄清 |
| search_place | :615 | POI 搜索 |
| get_route | :629 | 路线查询 |
| check_opening_hours | :642 | 营业时间查询 |
| retrieve_guide_knowledge | :655 | 攻略知识检索 |
| update_preferences | :703 | 更新长期偏好 |
| build_itinerary | :712 | 构建行程 |
| validate_itinerary | :721 | 行程可行性校验 |

### 4.2 选择机制（实测）
- **LLM 路径**：`_to_decision`（graph.py:303-329）解析模型返回的工具名 → 校验 `self._tools.has(tool)`（:316，未知工具被拒绝并回退 ask_user）→ `ToolRegistry.invoke`（tools.py:745）。
- **规则路径**：AskingDecider 按槽位缺失顺序选工具。
- **失败处理**：LLM 未解析/超时/传输失败 → 降级 AskingDecider（graph.py:293-300）；工具异常 → 观测记录 + 状态继续。
- **值确认权在代码**：LLM 提议的约束值需 evidence 匹配才确认（tools.py:114-131），模型不能单方面写入状态。

### 4.3 判定
✅ **工具真正由 Agent 按状态选择**（非固定节点硬调用）。❌ **工具不可组合成新工具**（无组合机制）；replan 工具缺失。工具执行结果进入 observations（Tool observation 存在）。

---

## 5. 是否存在 Replanning？（6.4）

### 5.1 系统内实际存在的三种"重规划"
| 机制 | 实现 | 是否 Agent 内 | 证据 |
|---|---|---|---|
| 局部重规划命令 | `planning-replan-command-v2` MQ 命令 | ❌ 独立于 Agent 循环 | worker/contracts.py:958 |
| 确定性修复（repair） | feasibility/repair/engine.py:71,181，6 动作 ≤3 次 | ❌ 无 LLM，局部变换+重校验 | worker/processor.py:371-426 |
| Agent 内 REPLAN 策略 | **仅声明**，无工具、无边 | — | graph.py:227 vs tools.py:551-723 |

### 5.2 判定
- 系统**有能力**在失败后观察→判断→重规划（repair 引擎 + replan 命令），但**都是确定性/命令驱动**，不是 Agent 自主决策。
- Agent 循环内部**只能"失败→结束"或"失败→问用户"**，无法自行修改行程后继续——这是 Agent 化最明确的缺口（P1）。

---

## 6. Agent 决策 / Rule 决策 / Solver 决策边界（6.5）

| 决策点 | 决策者 | 证据 | 是否合理 |
|---|---|---|---|
| 下一步动作（工具选择） | **Agent（LLM/规则）** | graph.py:287-329 | ✅ 合理 |
| 是否澄清/继续 | **Agent** | graph.py:303-329 | ✅ 合理 |
| 约束值确认 | **代码**（evidence 匹配） | tools.py:114-131 | ✅ 合理（防模型伪造） |
| 约束值抽取（自由文本） | LLM/规则 三套并存 | graph.py:97-118 / dialog/service.py:437 / dialog/extractor.py | ⚠️ 重复实现（P2） |
| 候选排序 | Rule（candidates.py:79） | — | ✅ 合理 |
| 每日日程 | Code（daily_schedule.py:527） | — | ✅ 合理 |
| 交通模式 | Rule 有序表（transport_strategy.py:9-15） | — | ✅ 合理 |
| 时间计算/时长 | Code（visit_duration） | — | ✅ 合理 |
| 预算计算 | Code（cost_model） | — | ✅ 合理（餐食死参数见 02 §3.1） |
| 可行性判断 | Rule（validator.py:62-74 11 规则） | — | ✅ 合理 |
| **路线优化** | **OR-Tools（声明）→ 实际无求解器** | pyproject.toml:12 零引用 | ❌ **P1 DEFECT** |
| 信息获取 | Tool（search_place/get_route/…） | tools.py:615-655 | ✅ 合理 |
| 不可行解释 | LLM + 规则 | evaluation/explanations.py | ✅ 合理 |
| 攻略事实抽取 | LLM（structured_model.py:176, ocr.py:292,430） | — | ✅ 合理（有 security_filter 边界） |
| 用户偏好理解 | LLM（update_preferences） | tools.py:703 | ✅ 合理 |

**结论**：LLM 只参与「意图理解/约束抽取/偏好/解释/工具选择」，**所有核心业务决策（时间/预算/可行性/排序/日程）都是确定性代码**——职责划分总体正确，与 README 宣称的「LLM 语义推理、硬约束确定性守门」一致。**唯一名不副实的是 OR-Tools**：README 宣称"OR-Tools 求解"，实际没有任何求解器被调用。

---

## 7. 自主决策空间审计（6.5 续）

### Agent 拥有的自主空间
1. 选择下一步工具（9 选 1）与参数（LLM 自由生成 args）
2. 决定是否向用户提问/回答/继续（answer vs call）
3. 选择策略枚举（DIRECT/RETRIEVE/CLARIFY/REPLAN——但 REPLAN 无对应动作）
4. 更新长期偏好（update_preferences）

### Agent 没有的自主空间
1. 无法自主发射行程（validate_itinerary 通过即自动 EMITTED）
2. 无法自主重规划（无 replan 工具）
3. 无法否决确定性校验结果
4. 无法自主修改已确认的约束值

### 判定
**这是正确的设计取舍**：把"终态守门"留给确定性系统（fail-closed 哲学，README.md:108-110 自述），Agent 只在语义层有自主权。问题不在"自主空间小"，而在**声明的 REPLAN 能力未兑现**与 **OR-Tools 未兑现**——两处"宣称≠实现"。

---

## 8. 双 Agent/向导并存（架构事实）

| 通道 | 运行时 | 判定 | 证据 |
|---|---|---|---|
| 行程内 Agent 循环 | LangGraph 有界循环 + MQ worker | **真 Agent（外圈）** | agent/graph.py:365-378 |
| 创建模式 HTTP 向导 | dialog/service.py（同步请求-响应） | **规则向导 + 可选 LLM 抽取** | dialog/service.py:546,749-756 |
| 确定性规划管线 | worker/processor.py | **纯 Workflow** | 见 01 §4 |

三者并存导致：同一槽位概念存在 SlotState（agent/state.py:49）/ SlotView（dialog/models.py:25）/ SlotSpec（dialog/service.py:74）/ AgentSlotView（worker/contracts.py:1793）四套模型（P1，详见 05）。

---

## 9. 结论与证据汇总

| 问题 | 判定 | 关键证据 |
|---|---|---|
| 是否真 Agent？ | **外圈是**（有界 ReAct），内圈是 Workflow | graph.py:365-378 循环 + tools.py:745 按状态选择 |
| 是否是固定 Workflow？ | 不是（循环存在）但内圈是 | 同上 + planning 管线零 LLM |
| Agent 能力缺口 | REPLAN 未实现、无自主重规划、无 plan 状态、评估外置 | graph.py:227 vs tools.py:551-723 |
| 名不副实组件 | OR-Tools（声明零用）、CONSTRAINTS_SOLVING 假阶段 | pyproject.toml:12 / amqp.py:151 |
| 未配置模型时 | 完整退化为规则向导（可用） | factory.py:159-161 / graph.py:125 |
| 总体判定 | **AGENT_WITH_WORKFLOW** | — |

> 与 docs/architecture/planning-intelligence-v3-decision-context-audit.md（2026-08-31 既有审计）一致：该文档同样确认 transport_strategy 是有序规则表（:9-15）、MealDemand.budget_per_person 是死参数（daily_schedule.py:212 透传、planning_provider 调用点不传）、住宿为 CITY_ESTIMATE 常数（cost_model.py:56）——本次审计逐条复核通过。
