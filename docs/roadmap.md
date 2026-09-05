# 产品与路线图

- 文档状态：生效中
- 相关文档：[系统架构](architecture.md) · [架构决策记录](decisions.md)

## 1. 产品定位

面向中国境内自由行场景的约束驱动旅行规划系统：目标不是生成"看起来合理"的行程，而是生成时间、交通、预算和现实条件上**真正可执行**的旅行计划。系统形态为「确定性规划引擎 + 有界对话式 Agent」——Agent 负责理解与沟通，确定性内核负责求解与守门。

## 2. 版本历史

### v1.0（2026-08-21 收口）

确定性规划平台基础：约束驱动的异步规划（Outbox → MQ → Worker → SSE）、逐日行程骨架（锚点/餐饮预留/固定安排/多日连续性）、真实 Provider 数据（高德 POI/路线/TRANSIT、QWeather）、11 条硬校验规则与有界修复、行程编辑（MOVE/时间/模式，候选预览→验证→提交，幂等重放）、不可变版本管理（diff/回滚）、分享与导出（匿名只读分享、PDF、ICS）、城市情报、健康检查与 Prometheus 观察。发布判定 PASS_WITH_DEFECT / READY_WITH_MINOR_DEFECTS。

### v1.1（2026-08-29 主线启动，已收官）

Agent 化主线，全部 Phase 完成并逐批验收（三栈测试全绿）：

- **Phase 1（生产性基础）**：修复架构评审缺陷 D1–D5（模型超时击穿、工具异常包装、ask_user 选项、LLM 提议+代码落槽、守门对象修正）；槽位状态机扩展 REJECTED / USER_OVERRIDE；agent_run / agent_step 轨迹表与幂等键；AgentState 版本化序列化与 Redis/PG checkpoint；AGENT_ASK_USER / AGENT_RESUME 契约；结构化决策器接线。
- **Phase 2（端到端体验）**：Agent 接入 AMQP、`build_itinerary` 触发确定性管线、发射权收归编排层（模型无 emit 工具）、AGENT_STEP / AGENT_COMPLETED 事件族 + Java 消费 + SSE 透传、Web 对话页（工具步/问题/行程卡渲染、确认槽位一键入 trip）。
- **Phase 3（高级能力）**：WAITING_USER 可恢复中断（TTL 过期、僵死恢复、防双执行）、跨会话偏好记忆（user_travel_profile，evidence-match 确认后生效）、显式策略选择进契约与轨迹、轨迹回放 harness 与 5 场景不变量基准。

### v1.1 之后（2026-09）

界面三栏重构、天气入日期条、Agent 通道令牌自动刷新、规划失败显式 FAILED、天气 15 天预报、CP-SAT 调度与 TRANSIT 真实化恢复、多源导入决策与设置中心。

## 3. 当前限制

- 单城市自由行；中国境内 Provider。
- 规划质量依赖外部 Provider 数据可用性。
- 网页攻略导入仅支持可公开访问的静态 HTTPS 页面。
- 截图 OCR 导入需配置视觉模型。
- 本地优先运行，未做公网生产部署。

## 4. 明确不做（进入前须重新立项）

跨城市联程规划、公网生产部署、多用户协作、Road/Taxi/Self-driving 完整交通语义、Feasibility override 治理。

## 5. 后续方向

**近期（包装，不新增功能）**：演示录屏与 README 截图；可选 demo compose profile。

**中期候选**：P3.5 Copilot 嵌入 Workspace（对话侧栏常驻、与行程版本双向同步）；天气/行李输入融入规划；交通偏好 ordered-rule 校准；跨日联合优化（日内 CP-SAT 已落地）。

**远期（默认不排期）**：跨城联程、多城市路线、公网部署与多用户。
