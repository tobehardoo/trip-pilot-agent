# 架构决策记录（浓缩版）

- 文档状态：生效中。每条记录「决策 / 理由 / 后果」，取代旧版分散的 ADR 文件（历史版本见 git 历史）。
- 相关文档：[系统架构](architecture.md) · [开发指南](development.md)

## D1 · Java + Python 双栈分工

**决策**：Java（travel-server）承担业务权威、持久化、消息可靠性；Python（agent-service）承担规划算法、Provider 适配与 Agent 编排。两者只通过 RabbitMQ + JSON Schema 契约通信，不共享数据库 schema（Python 侧表独立迁移）。
**理由**：规划/调度/优化生态（OR-Tools、LangGraph、pydantic）在 Python 一侧压倒性成熟；而事务、Outbox、连接池、安全框架是 JVM 的强项。硬拆成单栈，要么放弃生态要么手搓可靠性。
**后果**：跨语言一致性必须靠契约测试与 fixtures 兜底（见 D8）；部署两个服务镜像。

## D2 · MyBatis 而非 JPA/Hibernate

**决策**：持久化用 MyBatis（注解 Mapper + 显式 SQL）。
**理由**：行程/版本/证据链的查询形态高度定制（JSONB、PostGIS、聚合），ORM 的隐式行为反成负担；SQL 完全可见、可审计、可控索引。
**后果**：字段变更需手工同步迁移与 Mapper（45 个 Flyway 迁移即演进记录）。

## D3 · 事务性 Outbox + 幂等消费者

**决策**：业务数据与待发布事件在同一事务落库（`outbox_event_record`），`OutboxPublisherJob` 批量发布到 RabbitMQ；所有消费者按 eventId / command_event_id 幂等，失败进死信。
**理由**："先写库再发 MQ"存在双写不一致窗口；"发 MQ 再写库"则事务回滚产生幽灵消息。Outbox 是唯一同时保证原子性与 at-least-once 的简单方案。
**后果**：消费侧必须天然幂等（本项目的编辑与事件处理都带幂等键）；发布有秒级延迟，可接受。

## D4 · SSE 而非 WebSocket

**决策**：规划进度与 Agent 对话用单向 SSE 推送，订阅时先回放持久化历史，支持 Last-Event-ID 断线续传。
**理由**：本场景数据流向固定（服务端 → 浏览器），SSE 复用 HTTP、自动重连、无需额外协议栈；历史回放使"刷新页面不丢事件"成为默认行为。
**后果**：`SseEventHub` 需要自行管理 emitter 生命周期（striped monitor、终态完成释放）。

## D5 · 有界 Agent：模型提议，代码裁决

**决策**：Agent 只负责意图、约束收集、澄清、解释；工具仅 5 个且无 emit 工具；行程发射由编排层在 `validate_itinerary` 通过且评估 ACCEPT 后自动触发；LLM 提议的槽位值只有在用户原话 evidence 中出现才升为 CONFIRMED；三重硬上限（steps/tool_calls/llm_calls）。
**理由**：LLM 输出不可作为权威数据源。让确定性系统拥有真值、模型只拥有发言权，才能同时获得对话灵活性与结果可信度——也使无模型密钥的确定性演示成为可能。
**后果**：Agent 能力边界清晰可测（失败签名、重复升级、反思预算均有确定性归宿）；代价是复杂意图表达依赖澄清轮次而不是模型的"自由发挥"。

## D6 · 决策器双模式，降级不冒充

**决策**：未配置 `STRUCTURED_MODEL_*` 时使用确定性 `AskingDecider`（可复现、零凭据）；配置后升级为 LLM 结构化输出决策，解析失败降级回确定性策略。`/health` 如实报告 DETERMINISTIC / STRUCTURED。
**理由**：同一套图与工具面要同时支撑"离线演示/测试"与"真实 LLM 体验"；降级必须可观测，不允许把降级冒充完整 Agent（fail-closed 原则的对外版）。
**后果**：两条决策路径都要维护测试（脚本化 fake decider + 契约固定的 LLM 输出路径）。

## D7 · 日内调度三模式：GREEDY / CPSAT / SHADOW

**决策**：默认贪心；`CPSAT` 精确求解失败自动回退贪心；`SHADOW` 贪心权威返回、CP-SAT 仅对照记录。基准（10 确定性场景）：CPSAT_BETTER 2 / TIE 8 / WORSE 0，单日最大 19.6ms。
**理由**：优化器是"可以变慢、不能变坏"的组件；直接切换无回退路径的精确内核是生产禁忌，SHADOW 提供了真实流量下的切换证据。
**后果**：三模式并存增加维护面，但基准结论明确支持当前默认值（贪心在常规日已近最优）。

## D8 · JSON Schema 契约权威 + 版本演进

**决策**：`contracts/messaging/` 的 JSON Schema 是 Java↔Python 消息的唯一权威定义；schema 版本演进（如 planning-completed-event v9→v11 并存），消费侧按版本分派；fixtures 两侧共用。
**理由**：跨语言系统的"口头约定"必然漂移（实际发生过两侧金额校验分歧）；契约先行 + 双侧契约测试让漂移在 CI 阶段暴露。
**后果**：改契约有固定流程（schema → fixtures → 双侧模型与测试，见[开发指南](development.md) §6）；旧版本需并存一段时间。

## D9 · fail-closed 的 Provider 与数据策略

**决策**：Provider 错误按 15 类分类（retryable / fallback_allowed）；降级与否由 `ProviderFallbackPolicy` 裁决而非无条件兜底；Demo Provider 遇 must_visit 直接拒绝；关键数据不确定时输出 UNKNOWN / 不可行，不伪造成功；畸形响应拒绝而非猜测。
**理由**：行程的可信度是产品核心价值——一个静默编造的"成功"比显式的失败危害大得多。
**后果**：用户会更多看到"不可行/待修复"而不是"看起来完整"的行程；凭据缺失时 Worker 启动即失败。

## D10 · 抓取层安全：HTTPS 强制 + SSRF 防护

**决策**：攻略导入仅支持公开静态 HTTPS 页面；不执行 JS、不登录、不绕过访问控制；抓取前 DNS 解析拒绝非公网 IP；AMap 凭据在日志中自动脱敏；内部服务 token 用常量时间比较。
**理由**：抓取器是最容易被外部输入驱动的组件，SSRF 与凭据泄漏是真实风险面；"不绕过平台控制"同时是合规边界。
**后果**：动态渲染/登录墙页面不可导入（产品已明示替代方案：粘贴正文或截图 OCR）。

## D11 · 手写 test double，不引入 Mockito

**决策**：Java 侧显式排除 Mockito 依赖，测试统一手写 fake/stub；Python 侧同样以手写 `_Fake`/`_ScriptedDecider` 为主。
**理由**：项目依赖面小、接口边界窄，手写 double 让测试意图显式、避免 mock 框架的行为差异（如参数匹配宽松度）掩盖真实回归。
**后果**：脚手架代码略多（共享夹具集中在 support/ 与 plan_evaluation_support.py）；换来的是测试即文档。

## D12 · 覆盖率与质量门禁做进构建

**决策**：JaCoCo BUNDLE 行覆盖 ≥ 80%（verify 硬门禁）；Python retrieval/acquisition/guide_intelligence 覆盖率 ≥ 80%（CI `--fail-under`）；Web 覆盖率 80%/75% 门禁 + vue-tsc 构建前置；9 镜像 digest 固定；gitleaks；Markdown 链接检查。
**理由**：单人项目最容易牺牲的是回归防护；把质量要求写成构建失败比写成"自觉"有效。
**后果**：临时跳过门禁需要显式改配置（留下痕迹），不能静默绕过。
