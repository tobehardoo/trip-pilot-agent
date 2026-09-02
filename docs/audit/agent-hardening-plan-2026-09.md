# TripPilot Agent 系统完善计划（Hardening Plan）

日期：2026-09-02
上游：`docs/audit/agent-system-audit-2026-09.md`（已定级 Level 4，验收达标）
性质：**先完善 → 再验证 → 最后泛化**，不在修复前盲目铺开全国测试

***

## 0. 总原则

1. **TRUE SUCCESS 定义**（贯穿所有验收）：
   `COMPLETED` + Valid itinerary + `days>0` + 天数==日期区间 + 每天≥1活动 + 有效 POI + 前端真实渲染。
   `COMPLETED` 本身不作测试成功标准，出现 `FALSE SUCCESS` 一律视为失败。
2. **完成不由 LLM/Agent 自判**：由确定性 Finalize/Feasibility Gate + Java 接收侧双闸共同决定。
3. **改一处、补一测、验一次**：每次改动必须带防回归测试 + 一次真实场景复验。
4. **先审计已收敛**：本计划基于审计结论实施，不引入未证实的重构。

***

## 阶段 0：缺陷修复（依审计，P2→P3 依次）

### 0.1 双完成链归边（AUDIT-01，P2）——最高优先

- 目标：消除"Agent 建的行程是预览、持久化是管线重算"的重复计算与分叉。

- 决策点：**二选一**（由你裁定）：

  - **选项 A（推荐，改动小）**：`worker/agent_processor.py` `_publish_completion` 不再携带完整 itinerary，只发简短摘要 + 已确认 slots（对话语义）；权威行程仍由 Planner 管线落库。

  - **选项 B（改动大）**：把 Agent 构建的行程送入与 Planner 相同的 Gate + Java 持久化，替代重算。

- 涉及文件：`worker/agent_processor.py` L429-458；`travel-server/.../agentdialog/AgentDialogEventService.java` L56-63；`worker/contracts.py` AgentCompletedEvent。

- 验证：一条真实 E2E（成都）确认只落一份行程且 Agent 摘要不产生二义。

- 防回归：断言 `AGENT_COMPLETED` payload 不再含完整 `itinerary.days`（选 A）。

### 0.2 Planner CREATE 输出侧前置校验（AUDIT-02，P3）

- 目标：Python 侧 fail-fast，而非依赖 Java 兜底。

- 改动：在 `worker/processor.py` `_outcome_event`（L238-294）前，对 `result.itinerary` 校验 `days 数 == (end-start)+1` 且每天≥1活动；不满足→回 `PlanningReviewRequired`（WAITING\_USER）或抛 `PlanningInfeasible`，不发送非法 `PlanningCompletedEventV11`。

- 涉及文件：`worker/processor.py`、`worker/contracts.py`（可复用 `PlanningReplanPayload.validate_scope` 的 expected\_dates 逻辑）。

- 防回归（Case）：

  - 4天·0天 → 必须否决；4天·1天 → 必须否决；4天·4天+validation → 放行；days=\[] → 否决；itinerary=None → 否决。

### 0.3 Decider 语义透明化（AUDIT-03，P3）

- 目标：部署环境明示当前决策器。

- 改动：health/metrics 暴露 `decider=STRUCTURED|DETERMINISTIC`（依据是否配置模型）；文档标注生产必须接模型，否则退化为 Level 2 行为。

- 涉及文件：`agent/factory.py`、`worker/runtime.py` 或 health 端点。

**阶段 0 退出标准**：以上 P2/P3 修复 + 各自防回归测试全绿；成都 4 天真实 E2E 仍 TRUE SUCCESS。

***

## 阶段 1：真实成功回归（Phase 1，先打通"真实成功"）

- 目标：单城市 Happy Path 连续稳定，彻底杜绝假成功。

- 场景：`成都 · 9月5日-9月8日 · 4天 · 1人 · ¥2500`，连跑 **≥5 次全链路 E2E**。

- 每次验收（TRUE SUCCESS）：

  1. 完成状态 = COMPLETED 且与真实数据一致（非 0 天）
  2. 地图存在地点（markers>0）
  3. itinerary ≥ 4 天、每天有合理活动
  4. 攻略非空、预算信息存在、前端渲染真实

- 失败即回归 0.x 修复链，禁止带病进入阶段 2。

- 产出：`tests/agent/` 内新增 happy-path 集成测试 + 脚本化 E2E 结果记录。

***

## 阶段 2：复杂约束验证（Phase 2）

| 类别         | 场景示例         | 验收                                 |
| ---------- | ------------ | ---------------------------------- |
| 预算冲突       | ¥100 / 4 必去  | 识别不可行→REPLAN 追问，不伪造                |
| 天气变化       | 雨天→调整户外/室内布局 | 确定性 weather\_policy 生效             |
| Must Visit | 熊猫基地必须去      | 进入候选且进日程，地图有点                      |
| 固定事件       | 某日某时固定安排     | 时间窗约束被满足                           |
| 营业时间       | POI 打烊       | opening\_hours 规则拦截/调整             |
| 路线不可达      | 交通耗时超窗口      | 换序/换点，不产非可执行                       |
| 多轮对话       | 中途改预算/删必去    | AGENT\_RESUME 从正确 step 续跑，无重复 tool |
| 信息缺失       | 只说"我要去广州玩"   | ask\_user 主动补齐，不伪造                 |

- 每个场景：`自定义 Agent 仿真`（Demo/无 key 确定性路径）+ `真实 E2E`（有 provider）双跑。

- 防回归：把每日/营业/预算/固定事件规则用例并入 `tests/feasibility/` 与 `tests/agent/`。

***

## 阶段 3：全国泛化（Phase 3）

- 目标：城市多样性 + 数据稀疏抓漏。

- 范围：≥20 城市、≥50 个 scenario，覆盖：一线/热门（北上广深杭蓉渝）+ 二线/文化+ 高海拔/边远（数据稀疏）+ 特殊标签（美食/自然/历史/亲子）。

- 规则：

  - 单一城市连续 3 次 TRUE SUCCESS 才算该城市通过；

  - 数据稀疏城市允许"明确告知基于 POI+可用攻略"，但**禁止空行程完成**；

  - 全量结果汇入 `apps/agent-service/tools/national_eval/` 报表。

- 发现新问题 → 回到阶段 0/2 对应修复，不允许"显示完成即算过"。

***

## 测试体系完善（贯穿）

| 层级               | 覆盖                                      | 载体                                                 |
| ---------------- | --------------------------------------- | -------------------------------------------------- |
| Unit             | 函数/规则正确                                 | `pytest tests/feasibility tests/agent`（当前 75P/4S）  |
| Integration      | 模块协同（processor/guard/worker）            | `pytest tests/test_planning_* tests/test_worker_*` |
| Agent Simulation | Decision/Tool/Observation/State/Loop 行为 | `tests/agent/test_agent_loop.py` 等 + 自定义 harness   |
| Real E2E         | Frontend→Java→RabbitMQ→Python→DB→前端     | Playwright `apps/web/e2e/` + 本会话浏览器 E2E            |

- 补齐缺口：Agent 级"非法输出→降级"、双链路"不重复落库"、运行指标断言的集成测试。

***

## 可观测与守卫

- 暴露 `decider` 类型 + 每步 `steps/tool_calls/llm_calls`（已部分在 run 记录）。

- 新增指标：`agent_run_emitted/ceiling/expired`、`agent_retry/duplicate_guard`，用于判断收敛而不是靠看日志。

- 失败留痕：`agent_step`/`checkpoint` 已存，补 `failure_kind` 检索，便于排障。

***

## 里程碑与退出标准

| 里程碑 | 内容              | 退出标准                                         |
| --- | --------------- | -------------------------------------------- |
| M0  | 阶段 0 缺陷修复 + 防回归 | P2×1、P3×2 修复，测试全绿，成都 TRUE SUCCESS            |
| M1  | 阶段 1 真实成功回归     | 成都连续 ≥5 次 TRUE SUCCESS，无 0 天/空地图假成功          |
| M2  | 阶段 2 复杂约束       | 8 类约束场景各 ≥1 次真实通过，冲突/不可行正确归因                 |
| M3  | 阶段 3 全国泛化       | ≥20 城 × ≥50 scenario，单一城市连续 3 次 TRUE SUCCESS |

**全局退出标准**：无 P0/P1；AUDIT-01/02/03 已消除或明确归边；每个城市/场景均以 TRUE SUCCESS 而非 COMPLETED 验收。

***

## 附：执行建议顺序（若需我继续作战）

1. 先裁 AUDIT-01 归边方向（A 或 B）。
2. 落地阶段 0 三项修复 + 防回归测试。
3. 连续跑成都 E2E 至 ≥5 次稳定（阶段 1）。
4. 再进入复杂约束与全国泛化。

