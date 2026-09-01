# 05 — Tool Boundary Audit

> Phase C-0 · 对象：`agent/tools.py`（对话路径）与规划路径的"准工具"。

## 1. ToolRegistry 全量清单（agent/tools.py:551-723，9 个工具，全部有 JSON Schema 契约 :53-71）

| 工具 | 功能 | 真身 | 生产接线 | 分类 |
|---|---|---|---|---|
| `update_constraints` | 提交/拒绝槽位值，代码侧裁决 provenance（LLM 只能 propose，用户原话 evidence 才 CONFIRMED，tools.py:114-131, 188-205） | 纯内存规则 | ✅ 内置 | **Real Agent Tool**（Action，改变 State） |
| `ask_user` | 提问并置 WAITING_USER（tools.py:245-297） | 纯内存 | ✅ | **Real Agent Tool**（人机交互 Action） |
| `search_place` | 关键词搜地点 | 委托 runtime.place_search | ❌ 恒 None → `CAPABILITY_MISSING`（tools.py:308-309） | **Pseudo Tool（未接线）** |
| `get_route` | 两地路线 | 委托 runtime.route | ❌ → CAPABILITY_MISSING（:323-324） | **Pseudo Tool（未接线）** |
| `check_opening_hours` | 营业时间 | 委托 runtime.opening_hours | ❌（:341-342） | **Pseudo Tool（未接线）** |
| `retrieve_guide_knowledge` | 攻略知识检索 | 委托 runtime.knowledge | ❌（:357-358） | **Pseudo Tool（未接线）** |
| `update_preferences` | 跨会话偏好 propose/confirm/revoke | 委托 TravelProfileRepository（Postgres） | ✅（agent_processor.py:588-594） | **Real Agent Tool**（持久副作用） |
| `build_itinerary` | 触发规划管道出草稿 | 委托 DemoItineraryBuilder → **DemoPlanningProvider**（itinerary_builder.py:176-183） | ✅（但 demo 内容） | **Real Tool + Fake Capability**（接口真、后端假） |
| `validate_itinerary` | 结构可行性守门 | StructuralFeasibilityGate（feasibility_gate.py:29-68，仅 4 项结构检查） | ✅ | **Real Tool，窄口径**（真硬校验 run_validation 未接） |

## 2. 判定标准逐条核对（用户 §十）

- 被 Agent Runtime 调用？✅ 仅 graph 的 `act` 节点（graph.py:407）+ decider 白名单（:316）。
- Tool Schema？✅ 全部有（ToolSpec.parameters）。
- 明确 I/O？✅ ToolObservation（ok/data/error_code）。
- Side Effect？update_preferences 有（Postgres）；update_constraints 改 State；其余读类。
- 可独立替换？✅ ToolRuntime 是可注入 dataclass（tools.py:74-89），"缺失即 fail closed"（:78-81）。
- Observation/Action Capability？是——这正是 Tool 层的正确形态。

## 3. 规划路径的"准工具"（tools.py 之外）

规划 worker 的能力（搜 POI、算路线、查成本、验证）以**进程内方法**存在
（provider._collect_pois / _route_for_pair / cost_model / run_validation），
没有 Tool Schema、没有注册表、不被任何 Runtime 以 Tool 语义调用。
按本审计的分类标准：**Infrastructure Adapter / Helper**，不是 Agent Tool——
这不一定是缺陷（确定性管线不需要 Tool 语义），但意味着两个运行时的能力**不可互相调用**。

## 4. 生产接线事实（关键缺口）

`ToolRuntime` 全部生产构造点仅两处——agent_processor.py:145-151 与 588-594——
均只接 `itinerary_builder`（Demo）、`feasibility`（窄门）、`profile_store`。
`place_search / route / opening_hours / knowledge` 四字段恒 None，
而 **main.py 的 FastAPI lifespan 已经持有 place/route 运行时**（main.py:20-26,
app.state.place_search_runtime / route_runtime）——能力已存在，只是没接进 worker 的 ToolRuntime。
