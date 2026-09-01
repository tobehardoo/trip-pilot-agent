# ADR-016：Agent 对话的传输边界

- 状态：生效中（P2.1 的依据）
- 日期：2026-08-29
- 关联：[ADR-015](Agent编排层与记忆系统.md)（Agent 编排层）、[Agent化路线图](../product/Agent化路线图.md) §3 P2.1

## 1. 问题

Agent 对话回合（AGENT_START / AGENT_RESUME 命令 → 一次有界 run → 追问或答复）需要选定传输：复用既有 AMQP 命令骨干，还是沿用现网 dialog 的同步 HTTP 通道。

## 2. 决策

**对话回合走 AMQP。**

- `AGENT_START` / `AGENT_RESUME` 作为命令进入 `trip.command.exchange`，Python worker 新增 `agent.dialog.queue`（绑定 `agent.start` / `agent.resume`）消费。
- `AGENT_ASK_USER` 作为事件发布到 `trip.event.exchange`（routing key `agent.ask-user`）。
- 现网 HTTP dialog 通道保持不动，直至 P2.8 前端对话页完成切换时再评估退役。

## 3. 理由

1. 回合时长有界但不紧凑（LLM 超时 × MAX_LLM_CALLS + 工具时延），异步彻底消除 HTTP 超时类失败；崩溃回合以死信收场，且轨迹已落 PG（P1.6），可审计可重放。
2. 复用被验证的命令骨干（outbox、路由、死信、幂等），不新增需运维的传输面。Java 发布侧的 `RabbitPlanningCommandPublisher` 按 `OutboxEventRecord` 泛化实现——`routingKey=agent.start` 即用，零新发布器；触发端点随 P2.8 落地。
3. P1.8 契约（ASK_USER 事件 / RESUME 命令）成为在用传输；批次 B 的 checkpoint / 恢复机制获得生产调用方（resume 从 checkpoint 续跑）。
4. P2.7 的 SSE Agent Trace 是同一事件流的自然延伸（镜像 `PlanningTaskEventHub` 模式）。

## 4. 否决的替代方案

- **同步 HTTP**：超时风险随上限配置增长；绕开 checkpoint / 恢复机制（生产路径不使用即为死代码）；P1.8 契约被搁置。
- **HTTP + SSE 混合**：一个对话走两条传输，复杂度反而更高。

## 5. 后果

- 回合时延增加队列跳数（毫秒级），由 P2.7 的步骤级可见性补偿。
- resume 的重复投递语义 = worker 状态守卫（run 非 WAITING_USER 一律拒绝进死信）+ 事件消费方按 eventId 查重（与 planning 既有实践一致）。
- 现网 dialog 路径与 agent 路径并行至 P2.8，切换是产品决策，不在 P2.1 内。
