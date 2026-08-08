# TripPilot 现有版本产品完整度与真实链路验收报告

**日期**：2026-08-04
**基线**：分支 `codex/plan-evaluation-weather-integration` @ `6c663dc`（PR #27，Draft）
**测试环境**：本地真实服务栈（DEMO_ONLY）——PostgreSQL 16 + PostGIS + pgvector（容器 `trip-pilot-r2-postgres-1`）、RabbitMQ、Redis、Java travel-server（端口 9000，当前 HEAD 源码）、Python worker（消费 planning.create/cancel）、agent FastAPI（端口 9010）。全部由当前 HEAD 代码启动，未用旧镜像。
**性质**：产品完整度验收与真实用户链路测试；未修改任何源码，未部署 staging/production，未调用真实 Provider。

---

## 1. 执行摘要

1. **当前版本能否作为完整旅行规划产品**：**不能，至少默认开箱（DEMO 模式）体验不能**。完整管道（创建→规划→消费→完成→落库→SSE→评估→版本→编辑→重规划→回滚→分享→导出）在本轮真实栈上全部跑通、API 级 `PRODUCT_COMPLETE`；但**产出物质量不达标**，且 Demo 模式对两类最常见的强约束（必去地点、固定预约）直接硬失败。
2. **用户能完成的任务**：注册/登录、创建行程、发起规划、查看进度（SSE 7 个事件）、查看版本、编辑、局部重规划、回滚、版本对比、分享、导出 ICS/PDF。这些链路**机械上都可用**。
3. **用户能获得的价值**：在 REAL 模式下（需 AMap key）理论可获得"时间/预算/约束自洽的可执行行程 + 确定性评估 + 天气/城市情报"；在本轮 DEMO 验证中，**只能获得占位行程**（每天 1 个"自主探索时段（演示）"、费用 0、无交通）和一个对空行程给出 97 分的失真评估。
4. **当前最大问题**：① Demo 模式是默认体验却几乎不可用于真实约束（必去→`NO_FEASIBLE_ITINERARY`，固定预约→`PLAN_EVALUATION_DATA_QUALITY_ERROR`）；② 结果质量与评估可信度在无真实 Provider 时无法成立；③ staging 仍被外部资源阻塞（同 round-1）。
5. **是否继续添加功能**：**否**。
6. **是否进入现有功能收敛**：**是**——当前最该做的是让"默认/演示体验"要么诚实降级（明确告知演示限制、给出可用的无约束演示）、要么在 REAL 模式下完成结果质量验收，而不是加新模块。

---

## 2. 当前用户体验叙述

一个普通用户打开 TripPilot（本地默认 = DEMO 模式）：
1. 注册/登录 → 看到空行程工作台。
2. 创建行程：填目的地"广州"、日期、预算、勾选偏好、填两个必去地点、一个固定预约。
3. 点击"开始规划" → 看到进度条（TASK_ACCEPTED → CONTEXT_VALIDATING → … 共 7 个事件，均来自 SSE）。
4. 数秒后**规划失败**：提示"演示降级无法验证必去地点，已停止生成以避免返回不符合约束的行程"（`NO_FEASIBLE_ITINERARY`），或"fixed schedule 'X' is not covered"（`PLAN_EVALUATION_DATA_QUALITY_ERROR`）。
5. 用户困惑：我的约束明明合理，为何"不可行"？——实际上这不是约束不可行，而是**演示 Provider 根本不具备验证能力**，错误语义误导。
6. 若用户移除必去/固定预约重新规划 → **成功**，看到每天一个"自主探索时段（演示）"，费用 0，无交通，地图无地点；评估面板显示 **97 分**。
7. 用户获得一份"97 分的空行程"，无法执行、无法信任。

若接入 REAL 模式（AMap key）：用户将获得真实 POI、时间窗、交通、费用明细，并可能看到评估 warning（长步行、紧换乘等）。**该路径的真实质量本轮无法验证（无授权凭据）**。

**结论**：产品的"骨架"（约束→规划→结果→评估→编辑→版本→分享）真实存在且机械完整；产品的"血肉"（真实可执行的行程与可信的评估）只存在于 REAL 路径，而默认体验恰好把它藏起来并给出误导性失败。

---

## 3. 模块产品完整度矩阵

| 模块 | 产品状态 | 用户价值 | 链路完整性 | 信息质量 | 稳定性 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- |
| 注册与登录 | PRODUCT_COMPLETE | 高 | 完整 | 高 | 高 | 刷新 cookie 轮换已测 |
| 创建旅行 | PRODUCT_COMPLETE | 高 | 完整 | 高 | 高 | 校验错误中英混用 |
| 城市/日期输入 | PRODUCT_COMPLETE | 高 | 完整 | 高 | 高 | 日期校验英文文案 |
| 人数/预算/偏好 | PRODUCT_COMPLETE | 高 | 完整 | 高 | 高 | 预算校验文案中文 |
| 必去地点 | **BROKEN（DEMO）** | 高 | 完整 | 中 | 高 | Demo 直接失败 `MUST_VISIT_UNVERIFIABLE_IN_DEMO`，错误被归为"不可行" |
| 固定预约 | **BROKEN（DEMO）** | 高 | 完整 | 中 | 高 | Demo 保留时间窗但不建活动 → `DATA_QUALITY_ERROR` |
| 交通偏好 | FUNCTIONALLY_COMPLETE_BUT_UX_WEAK | 中 | 完整 | 中 | 高 | Demo 无交通；REAL 未验证 |
| 行程生成 | PARTIAL | 高 | 完整 | **低（DEMO）** | 高 | Demo 产出占位；REAL 质量 BLOCKED |
| 规划进度（SSE） | PRODUCT_COMPLETE | 中 | 完整 | 中 | 高 | 7 事件含 sequence/Last-Event-ID；消息英文 |
| 日程展示 | FUNCTIONALLY_COMPLETE_BUT_UX_WEAK | 高 | 完整 | 中 | 高 | 依赖行程质量 |
| 地图展示 | PARTIAL | 中 | 完整 | 中 | 高 | 依赖 AMap Web JS key（REAL 才有效） |
| Activity 信息 | PARTIAL | 中 | 完整 | 低（DEMO） | 高 | Demo 无地址/坐标/类型 |
| Transit 信息 | PARTIAL | 中 | 完整 | 低（DEMO） | 高 | Demo 无 transit |
| 时间安排 | PARTIAL | 高 | 完整 | 中 | 高 | Demo 为 09:00–11:00 固定块 |
| 预算与费用 | FUNCTIONALLY_COMPLETE_BUT_UX_WEAK | 高 | 完整 | **低（DEMO 恒为 0）** | 高 | Demo 费用恒 0，评估 budgetFit=100 失真 |
| PlanEvaluation | PARTIAL | 中 | 完整 | **低** | 高 | 对空行程打 97 分；interestMatch 为固定 80 占位 |
| Warning 与解释 | PARTIAL | 中 | 完整 | 中 | 高 | demo 下无 warning；explanation 存在但未在本轮触发 |
| 天气 | BLOCKED（无 key） | 高 | 完整 | UNKNOWN | UNKNOWN | 需 QWeather key；本轮未验证 |
| 城市情报 | BLOCKED（无 key） | 高 | 完整 | UNKNOWN | UNKNOWN | 需 AMap/agent-api；本轮未验证 |
| 编辑 | PRODUCT_COMPLETE | 高 | 完整 | 高 | 高 | 幂等/冲突/新版本均正确 |
| 局部重规划 | PRODUCT_COMPLETE | 高 | 完整 | 高 | 高 | evaluation 重算（97）；V3 正确 |
| 版本管理 | PRODUCT_COMPLETE | 高 | 完整 | 高 | 高 | V1/V2/V3 不可变、来源标注正确 |
| 差异比较 | PRODUCT_COMPLETE | 高 | 完整 | 高 | 高 | diff 返回 added/removed/changed |
| 回滚 | PRODUCT_COMPLETE | 高 | 完整 | 高 | 高 | 生成新 ROLLBACK 版本、ID 重映射、409 冲突保护 |
| 分享 | PRODUCT_COMPLETE | 高 | 完整 | 高 | 高 | 高熵 token、脱敏公共页 |
| PDF 导出 | PRODUCT_COMPLETE | 中 | 完整 | 中 | 高 | 200，2107 字节 |
| ICS 导出 | PRODUCT_COMPLETE | 中 | 完整 | 中 | 高 | 200，858 字节 |
| 失败提示 | FUNCTIONALLY_COMPLETE_BUT_UX_WEAK | 高 | 完整 | 中 | 高 | 结构化错误；但"演示限制"被归为"不可行"误导用户 |
| Demo Provider | PARTIAL | 低 | 完整 | 低 | 高 | 仅占位；对必去/固定预约硬失败 |
| 真实 Provider | BLOCKED | 高 | 完整 | UNKNOWN | UNKNOWN | 需授权 AMap key |
| 缓存与回退 | FUNCTIONALLY_COMPLETE | 中 | 完整 | 中 | 中 | 无真实 Redis 集成测试 |
| 历史行程管理 | PRODUCT_COMPLETE | 中 | 完整 | 高 | 高 | 列表/归档/搜索存在 |

---

## 4. 用户可获得的信息矩阵

| 信息 | 是否可获得 | 是否准确 | 是否易懂 | 是否可行动 | 问题 |
| --- | --- | --- | --- | --- | --- |
| 行程基本信息 | AVAILABLE_AND_USEFUL | 是 | 是 | 是 | — |
| 每日安排 | AVAILABLE_BUT_INCOMPLETE | 部分 | 是 | 部分 | DEMO 下为占位块 |
| Activity 名称 | AVAILABLE_BUT_INCOMPLETE | 是 | 是 | 部分 | DEMO 为"自主探索时段（演示）" |
| Activity 时间 | AVAILABLE_AND_USEFUL | 是 | 是 | 是 | 09:00–11:00 固定块 |
| Activity 地点/地址 | BACKEND_ONLY（DEMO null） | — | — | 否 | 需 REAL 才有 |
| Activity 类型 | NOT_AVAILABLE | — | — | — | 无类别字段 |
| 停留时长 | AVAILABLE_AND_USEFUL | 是 | 是 | 是 | 由时间窗推导 |
| 推荐原因 | AVAILABLE_BUT_INCOMPLETE | 部分 | 部分 | 部分 | explanation 存在但 demo 未触发 |
| 必去状态 | BACKEND_ONLY | — | — | — | demo 拒绝必去 |
| 固定预约状态 | BACKEND_ONLY | — | — | — | demo 无法满足 |
| Transit 方式/时间/距离 | NOT_AVAILABLE（DEMO） | — | — | 否 | 需 REAL |
| 每日费用 | AVAILABLE_BUT_INCOMPLETE | 是 | 是 | 部分 | demo 恒 0 |
| 总费用 | AVAILABLE_AND_USEFUL | 是 | 是 | 是 | demo 恒 0 |
| 费用来源 | BACKEND_ONLY | — | — | — | demo 无来源 |
| 预算状态 | AVAILABLE_AND_USEFUL | 部分 | 是 | 部分 | demo budgetFit=100 失真 |
| Evaluation 分数 | AVAILABLE_BUT_CONFUSING | **否（demo）** | 是 | 否 | 对空行程打 97 |
| Warning | AVAILABLE_BUT_INCOMPLETE | 部分 | 是 | 部分 | demo 无 warning |
| Explanation | AVAILABLE_BUT_INCOMPLETE | 部分 | 部分 | 部分 | 存在但 demo 未触发 |
| 天气 | NOT_AVAILABLE（无 key） | — | — | 否 | BLOCKED |
| 城市情报 | NOT_AVAILABLE（无 key） | — | — | 否 | BLOCKED |
| Provider 来源 | AVAILABLE_AND_USEFUL | 是 | 部分 | 是 | "DEMO/AMAP/MIXED" 用户可能不懂 |
| 版本 | AVAILABLE_AND_USEFUL | 是 | 部分 | 是 | 来源/编号清晰 |
| 差异 | AVAILABLE_AND_USEFUL | 是 | 部分 | 是 | changed/added/removed |
| 分享 | AVAILABLE_AND_USEFUL | 是 | 是 | 是 | 脱敏 |
| PDF/ICS | AVAILABLE_AND_USEFUL | 是 | 是 | 是 | — |
| 失败原因 | AVAILABLE_BUT_CONFUSING | 部分 | 部分 | 部分 | demo 限制被归为"不可行" |

> **回答**：用户完成一次操作后，**不能**在不依赖开发者解释的情况下理解并执行这份行程。DEMO 下行程为空壳、评估失真、失败语义误导；REAL 路径未验证。

---

## 5. Persona 测试结果

| Persona | 执行 | 结果 | 结论 |
| --- | --- | --- | --- |
| A 周末游客（无强约束） | 2 次 | SUCCEEDED | 管道完整；产出占位行程 + evaluation 97。重复性稳定 |
| A-必去变体 | 1 次 | FAILED `NO_FEASIBLE_ITINERARY` | Demo 无法验证必去 → 误导性失败 |
| B 强约束游客 | 2 次 | B1 固定预约 FAILED `DATA_QUALITY_ERROR`；B2 必去 FAILED | Demo 无法满足两类强约束 → 该 Persona 在默认体验完全不可用 |
| C 预算敏感 | 1 次 | SUCCEEDED | 低预算 300 → 费用 0 → budgetFit 100 → 失真 97 分 |
| D 密集游客 | 0 次 | BLOCKED | Demo 每天仅 1 活动，无法构造密集场景；需 REAL |
| E 反复编辑用户 | 2 轮 | 全部成功 | V1→编辑V2→重规划V3→diff→回滚V4(ROLLBACK)→分享→导出全通过；幂等重放不产生重复版本 |
| F 异常输入 | 5 例 | 全部正确拒绝 | 空城市/日期倒置/负预算/预约越界/超 7 天均返回清晰 400；文案中英混用 |
| G 旧数据用户 | 受限 | BLOCKED/UNKNOWN | 无法造 legacy 行（需改库，禁止）；前端 legacy 处理在 round-1 已分析（null evaluation → 隐藏面板），解析器 v6-legacy 测试通过 |

---

## 6. 多轮链路测试结果

| 轮次 | 输入 | 执行次数 | 成功 | 失败 | 偶发问题 | 结果差异 | 数据一致性 | 页面表现（API 视角） |
| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |
| 标准成功链路（Persona A/C/E） | 无强约束行程 | 5 | 5 | 0 | 无 | 版本恒 V1、天数正确、费用恒 0 | 一致 | SSE 7 事件正常结束 |
| 重复性 | 相同输入 x2（A）、同 key 重放（E） | 4 | 4 | 0 | 无 | 稳定 | 无重复版本/重复事件 | 幂等正确 |
| 边界值 | 2 天 / 5 天 / 7 天（B1）/ 低预算 | 4 | 2 | 2 | 无 | 失败均为约束语义 | 一致 | — |
| 编辑与版本 | V1→V2→V3→diff→回滚→分享→导出 | 2 轮 | 全过 | 0 | 无 | — | V1 不可变、ID 重映射、evaluation 绑定 V3 | 完整 |
| 失败与恢复 | 必去失败、固定预约失败、幂等冲突 | 3 | — | 3（预期） | 无 | — | 结构化错误、可重试语义清晰 | 用户可见错误 |
| 长时间连续 | 连续 8+ 个 trip/多次规划 | 多 | 全过 | 0 | 无 | — | 用户间隔离正确（A 读 B 返回 404/[]） | 稳定 |

未执行：真实 Provider 探测（无授权 key）；D 密集场景；G legacy 真实数据；24h soak（明确不以短时循环冒充）。

---

## 7. 核心结果质量评估

- **时间**：DEMO 固定 09:00–11:00 块；无重叠、无 Transit 占用；REAL 未验证。评估为"结构合理但无真实内容"。
- **空间/交通**：DEMO 无坐标、无 transit、无地图 POI；无法评估折返/步行。REAL BLOCKED。
- **预算**：DEMO 恒 0；总费用=明细；但"预算不超限"恒成立，budgetFit=100 失真。
- **约束**：必去/固定预约在 DEMO 直接失败（诚实但误导）；REAL 未验证。
- **Evaluation**：**核心质量问题**——对空占位行程打出 97 分（constraintSatisfaction=100, timeFeasibility=100, budgetFit=100, routeEfficiency=100, interestMatch=80 基线）。评分机械正确但语义失真；`interestMatch` 为固定 80 占位（round-1 I-4）。绑定正确：replan 后 evaluation 重算并绑定 V3。
- **Weather/City**：未验证（无 key）；前端绑定正确性在 round-1 已审（天气不随版本，为设计取舍）。
- **可执行性**：DEMO 下不可执行；REAL 未验证 → 整体 `PARTIAL/BLOCKED`。

---

## 8. Bug 列表

### P0
- 无。

### P1
- 无（API 级主链路全部跑通，未发现"无法创建行程/版本串线/永久 loading/错误成功状态"）。

### P2
- **P2-1｜Demo 模式对"必去地点"返回 `NO_FEASIBLE_ITINERARY`（误导性不可行）**。场景：默认体验下填必去地点即失败。前置：PROVIDER_MODE=DEMO_ONLY + 任意 mustVisit。步骤：创建含 mustVisit 的行程并规划。预期：明确提示"演示模式无法验证必去地点，请用真实模式或移除该约束"。实际：错误归为 PLANNING_INFEASIBLE / `NO_FEASIBLE_ITINERARY`，用户以为约束不可行。复现频率：100%。证据：`demo/planning_provider.py:39-54`（`MUST_VISIT_UNVERIFIABLE_IN_DEMO`）；实测任务 `errorCode=NO_FEASIBLE_ITINERARY`。影响范围：默认体验的核心输入。阻塞发布：否（仅 demo）。建议：区分"provider 能力限制"与"约束不可行"，或在前端 demo 模式下禁用必去输入并说明。
- **P2-2｜Demo 模式对"固定预约"返回 `PLAN_EVALUATION_DATA_QUALITY_ERROR`**。场景：任何含固定预约的行程在 demo 必失败。证据：`demo/planning_provider.py` 为预约保留时间窗但不生成活动 → evaluation 硬约束检查 `activity_covers_fixed_schedule` 失败 → 阻断完成（实测 B1）。建议：demo 对固定预约要么生成占位活动、要么返回"演示不支持固定预约"的明确提示。
- **P2-3｜Evaluation 对空占位行程打出 97 分**。场景：demo 成功行程，无活动内容，评估显示"优秀"。证据：实测 overallScore=97、五维 100/100/100/100/80、费用 0。影响：用户获得不可信的"高分"。建议：demo 模式明确标注"演示行程，分数仅示意"，或对无实质活动（无坐标/无 transit/费用 0）降低/停用评分。
- **P2-4｜校验错误文案中英混用**。场景：F2 日期倒置/F4 预约越界/F5 超 7 天返回英文，F1 空城市/F3 负预算返回中文。证据：实测响应。建议：统一前端 i18n 映射或后端中文文案。
- **P2-5｜ROLLBACK / USER_EDIT 版本无 planningTaskId → 评估面板隐藏**。场景：回滚后当前版本不再显示评估（也无法回退展示父版本评估）。证据：实测 `planningTaskId=None`；round-1 N-5。影响：版本切换后评估信息丢失。建议：让评估与版本强绑定（存版本级）或对无任务版本展示父版本评估/legacy 文案。

### P3
- **P3-1** `/itinerary/versions` 对非属主 trip 返回 200/[] 而非 404（与 `/itinerary`、`/api/trips/{id}` 的 404 不一致；无数据泄露，`findAllOwned` 已按 owner 过滤）。证据：实测 A 访问 B 的 versions → 200 []。
- **P3-2** SSE progress 消息为英文（"Planning task accepted by the worker"），前端仅映射 stage 标签，消息文本可能外露英文。证据：实测 SSE 原始数据。
- **P3-3** `versions`/`diff`/`share` API 参数命名不统一（from/to vs versionId），增加前端/第三方使用难度（文档已列出，非 Bug）。

> 说明："功能不够丰富"（如 demo 无真实 POI、无天气）不计为 Bug，记为 BLOCKED/UNKNOWN。

---

## 9. 现有功能断链

1. **Demo 模式与强约束**：必去/固定预约在 demo 下无可用闭环（模块存在、链路通、但功能不可用）——最大的"名义存在但用户无法有效使用"项。
2. **结果可执行性**：规划→行程→展示闭环在 demo 只产出占位；REAL 结果质量链路未验收（BLOCKED）。
3. **天气/城市情报**：agent-api 与 QWeather/AMap key 依赖下未贯通验证（BLOCKED）。
4. **费用来源/Activity 类型**：后端模型无这些字段，前端无从展示（信息缺失）。
5. **D 密集行程 / G legacy**：无测试路径（demo 构造不出密集场景；legacy 需改库）。

---

## 10. 用户体验问题

1. **默认体验误导**：打开即 demo，填必去/固定预约即"不可行"；移除后得到"97 分的空行程"。用户无法理解产品价值。
2. **失败后不知道怎么办**：`NO_FEASIBLE_ITINERARY` 后无"改用真实模式"的可执行引导（尽管 relaxation 建议存在，前端未突出）。
3. **评估信息不可信**：空行程 97 分。
4. **版本切换后评估丢失**（P2-5）。
5. **错误文案语言不一**（P2-4）。
6. **进度消息英文**（P3-2）。
7. **无空状态/引导**：新用户首页无"如何规划一次旅行"的示例或模板入口（TripTemplates 存在但需确认是否默认可见）。

---

## 11. 信息质量问题

- 用户缺少：真实 Activity 地址/坐标/类型、Transit 时间与距离、费用来源、天气、必去/固定预约的落实状态。
- 用户看不懂：`DEMO/AMAP/MIXED` Provider 来源、evaluation 维度名、部分英文错误。
- 用户无法信任：demo 下 97 分评估、恒 0 费用、占位行程。

---

## 12. 自动化测试盲区

- **测试通过但未证明产品可用**：Python 547 / Java 43+32 / Web 126 全部通过，但没有一个测试断言"默认 demo 体验对必去/固定预约不误导失败"；没有测试断言"评估分数与行程实质内容相符"。
- 单元测试用真实模块 + MockTransport，验证了逻辑正确性，但**未验证 UI 在真实 stack 上的端到端行为**（Playwright 在本轮未运行；CI e2e 跑的是构建产物）。
- 契约测试共享 fixture 验证了消息一致性，但**未验证真实 RabbitMQ 全链路**（round-1 N-15：outbox 调度器无联合测试）。
- 无真实 Provider 结果质量回归（无 key）。
- 前端组件测试覆盖竞态，但**无"真实用户完成一次规划并理解结果"的验收脚本**。

---

## 13. 当前版本验收结论

| 判定 | 结果 |
| --- | --- |
| 核心规划可用 | **PARTIAL**（管道 YES；DEMO 产出占位；REAL 结果 BLOCKED） |
| 结果可执行 | **NO**（DEMO 占位不可执行）；REAL `UNKNOWN/BLOCKED` |
| 编辑链路可靠 | **YES**（V2 生成、幂等、并发保护、回滚正确） |
| 版本链路可靠 | **YES**（V1/V2/V3 不可变、来源正确、diff/回滚正确） |
| Evaluation 有效 | **PARTIAL**（机械绑定正确；分数语义失真；interestMatch 占位） |
| Weather 有效 | **BLOCKED**（无 key，未验证） |
| 分享导出可靠 | **YES**（分享 201+脱敏公共页；ICS/PDF 200） |
| 普通用户可独立使用 | **NO**（默认 demo 体验对强约束失败、结果空壳、评估失真） |
| 当前模块已彻底完善 | **NO** |
| 应继续添加新模块 | **NO** |
| 应进入现有功能收敛 | **YES** |

---

## 14. 彻底完善计划

### Batch 1：P0/P1 正确性与数据问题
无 P0/P1。本批次为空（可跳过），但建议在收敛开始时重新核对。

### Batch 2：核心链路断链（本轮最高优先）
- **目标**：让默认（DEMO）体验对强约束"诚实且可用"，或对 REAL 模式完成结果质量验收。
- **任务 2a（demo 诚实化）**：`demo/planning_provider.py` 对 mustVisit/fixedSchedules 的失败返回**能力限制类错误**（新 errorCategory，如 `PROVIDER_CAPABILITY_LIMITATION`），而非 `PLANNING_INFEASIBLE`；前端对该类错误展示"演示模式限制"说明与"移除约束或启用真实模式"引导。
  - 验收标准：demo 下含必去/固定预约的规划返回可区分的错误码，前端展示对应说明。
  - 必须新增测试：断言 errorCategory 区分能力限制与真实不可行。
- **任务 2b（评估语义）**：当行程无实质活动（无坐标、无 transit、费用 0、活动为占位）时，评估标注"演示示意分数"或在面板展示免责声明；`interestMatch` 占位如实标注。
  - 验收标准：空占位行程的评估面板带"示意"标记。
- **任务 2c（REAL 结果质量验收）**：授权 AMap key 后在受控 staging 验证时间/交通/预算/约束质量（**需外部资源，属 BLOCKED 项**）。

### Batch 3：用户操作与错误恢复
- P2-4 错误文案统一中文（或前端 i18n 映射全部校验消息）。
- P2-5 评估与版本强绑定：对 USER_EDIT/ROLLBACK 版本展示父版本评估或 legacy 文案。
- P3-2 SSE 进度消息前端全部映射中文。
- 增加"如何规划"引导/空状态模板。

### Batch 4：结果信息质量
- 为 Activity 增加地址/坐标/类型的展示（REAL 已有字段，前端补齐）；Transit 时长/距离展示。
- 费用来源标注（估算 vs 真实）；必去/固定预约的落实状态徽标。

### Batch 5：多轮 E2E 与回归
- 新增 Playwright 场景：demo 必去失败引导、空行程评估免责、编辑/回滚后评估一致性。
- 新增 API 回归：错误码语义、版本绑定评估。
- 补 outbox 调度器 + Rabbit 联合测试（round-1 N-15）。

### Batch 6：staging 产品验收
- 前置：补齐 staging 资源（主机/registry/digest/env/域名/TLS/告警/备份）→ `validate_staging_env.py` PASS。
- 执行 S-01~S-13（当前全部 BLOCKED），其中 S-08 核心用户旅程须以 REAL 模式、真实 AMap 执行并留存结果质量证据。

---

## 15. 当前版本 Definition of Done

客观可验收的完成条件（不做整体判定只做逐项布尔检查）：
1. **默认体验不误导**：DEMO 模式下，含必去/固定预约的规划返回"能力限制"类错误（非 `PLANNING_INFEASIBLE`），错误码可机器区分；空占位行程的评估面板显示"示意"标识。
2. **评估可信**：对无实质活动的行程，评估分数不可呈现为无保留的"优秀"；`interestMatch` 占位在 UI 如实标注；评估始终绑定当前版本（含 ROLLBACK/USER_EDIT 回退展示）。
3. **错误可恢复**：所有校验错误返回中文或前端 i18n 全映射；失败后 UI 提供明确下一步动作。
4. **信息完整**：行程页展示 Activity 地址/时间/停留时长、Transit 时长/距离、每日/总费用及来源、必去/固定预约落实状态；天气与城市情报在有 key 的环境按日期/城市正确展示。
5. **核心 E2E 稳定**：Playwright 覆盖"demo 必去失败引导""空行程评估免责""编辑→重规划→回滚→评估一致性"三条场景，连续 3 次通过。
6. **staging 可验收**：S-01~S-13 中 S-08 在 REAL 模式产出时间/交通/预算/约束自洽的行程，S-03/S-04 真实 AMap/QWeather 通过。
7. **无 P0/P1**；已知限制（demo 限制、评估维度占位）在 UI 与文档中显式声明。

---

## 16. 下一步唯一任务

**唯一立即执行项：Batch 2 的 2a + 2b（demo 体验诚实化 + 评估语义修正）** —— 让默认打开 TripPilot 的用户不再得到误导性的"不可行"与"97 分空行程"，而是明确知道"这是演示模式的能力限制"，并把"真实可执行行程"的验收押到 REAL 模式与 staging。该批次独立、可验证（新增错误码/UI 标识断言）、不混合其他目标，也不引入任何新模块。

---

## 结束回执

1. **启动的服务**：PostgreSQL/Redis/RabbitMQ（容器 `trip-pilot-r2-*`）、Java travel-server（端口 9000，当前 HEAD 源码）、Python worker（DEMO_ONLY）、agent FastAPI（端口 9010）。
2. **执行的测试**：Persona A/C/E/F 全链路（真实 API + SSE）、编辑/版本/回滚/分享/导出链路、幂等重放、跨用户隔离、重复性；另在前一轮已执行 Python 547 / Java 43+32 / Web 126 全量。
3. **Persona 测试组数**：A、B、C、E、F 共 5 组实际执行（约 14 次规划/编辑/导出操作）。
4. **每组次数**：A×3、A-必去×1、B×2、C×1、E×2 轮、F×5 例、重复性×4。
5. **未测试链路**：D（密集行程）、G（legacy 真实数据）、REAL 模式结果质量、天气/城市情报、Playwright e2e（本地）、outbox+Rabbit 联合端到端。
6. **未测试原因**：D/G/REAL 需真实数据或授权 key；天气/城市情报需 QWeather/AMap key；e2e 需浏览器 + 完整前端栈；outbox 联合测试为已知测试缺口（round-1 N-15）。
7. **是否调用真实 Provider**：**否**。全程 DEMO_ONLY，未做任何外部 Provider 调用。
8. **是否接触 Secret**：**否**。使用独立占位密钥（`.env.audit-round2`，gitignored）；未读取仓库 `.env` 值。
9. **是否修改文件**：**是，仅测试脚本与报告**——新增 gitignored `.env.audit-round2`、`/tmp` 测试脚本、`docs/audits/current-version-product-completeness-2026-08-04.md`（未跟踪）。未修改任何源码/配置/测试/Git 历史。
10. **工作区是否干净**：除 round-1 报告与 `docs/audits/current-version-product-completeness-2026-08-04.md`（均未跟踪）及 gitignored 文件外，干净。
11. **发现数量**：P0=0，P1=0，P2=5，P3=3。
12. **是否适合继续添加功能**：**否**。
13. **是否应冻结功能并彻底收敛**：**是**。
14. **最优先修复批次**：Batch 2（demo 体验诚实化 + 评估语义修正），即本报告第 16 节的唯一任务。
