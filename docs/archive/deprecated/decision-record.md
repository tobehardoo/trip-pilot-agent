# 技术决策

## ADR 014：完成事件运行时契约锁定为 v6（2026-07-30）

- [已验证] `apps/agent-service/src/trip_agent/worker/contracts.py`、`worker/processor.py` 均发布 `schemaVersion: 6`；`PlanningCompletedEventParser` 仅接受 v1-v6，并在 JSON 字段校验之前拒绝 v7。
- [已验证] v6 允许向后兼容的可选 `providerProvenance`，历史 payload 无该对象仍合法且不得被推断。v7 草案的业务增量仍是 Transit 成本与扩展 mode；该草案未随 v6 provenance 改动启用。
- [已验证] v6 producer 不再把内部 Transit 成本字段序列化到消息；`test_messaging_contract_schemas.py` 现以含 Transit 的 worker wire payload 验证 v6 JSON Schema。
- [已验证] provenance Route operation 以稳定消息 ID 关联 Transit/Activity，Java 在完成事务内重映射为版本数据库 UUID，并复用既有任务事件 JSONB；无需 ADR 或 Flyway 主版本升级。
- [文档声明] `contracts/messaging/planning-completed-event-v7.schema.json` 是下一次独立升级的草案，不是可投递、可消费或可持久化的运行时版本。
- [待确认] 启用 v7 前必须一次性完成 Python 生产、Java 解析/校验/持久化、Web 展示与跨语言样例测试，并明确成本来源和 `TRANSIT`/`TAXI` 的业务语义。

本文保留当前仍约束实现的关键 ADR 摘要。完整历史理由见 [原 ADR 详稿](../decision-record.md)。

## 当前决策

| ADR | 决策 | 当前约束 |
| --- | --- | --- |
| 001 | Java 作为业务后端 | 用户、旅行、行程版本、安全和事务编排继续由 Spring Boot 拥有 |
| 002 | MyBatis 而非 JPA | 复杂查询、Flyway 迁移和 PostgreSQL 特性使用显式 SQL |
| 003 | Transactional Outbox | 业务写入和消息发布必须通过 Outbox 保持最终一致 |
| 004 | RabbitMQ 而非 Kafka | 当前是任务队列和命令/事件拓扑，不引入流式平台 |
| 005 | Python 规划 Worker | OR-Tools、Provider 调用、文本处理和向量检索继续在 Python 侧演进 |
| 006 | 行程版本不可变 | 规划、编辑、局部重规划和回滚都创建新版本，不覆盖历史 |
| 007 | Demo 模式是正式模式 | 无 Key 环境和 CI 必须可完整运行，但结果需明确标记 Demo/估算 |
| 008 | pgvector 而非独立向量数据库 | 当前知识规模由 PostgreSQL + pgvector 承担 |
| 009 | 协作式取消 | 不强杀 Worker；在检查点响应取消并保持消息幂等 |
| 010 | 单一 Agent | 不引入多 Agent 协商；规划链路保持可测试状态机 |
| 011 | 人工注册可信来源 | “官方来源”是业务信任决策，不能由模型或爬虫自动授予 |
| 012 | 规划消费冻结事实快照 | 任务重试必须可复现，后续事实刷新不改变既有任务输入 |
| 013 | 回滚创建新版本 | 回滚本身可审计，版本号单调前进 |

## 变更原则

- 新基础设施必须先证明能降低当前复杂度或风险。
- 跨语言契约变更必须同步 JSON Schema、Java、Python、TypeScript 和示例消息。
- 影响数据模型的变更只通过向前迁移进入；不修改已发布迁移。
- 影响用户可见范围的变更必须同步 [产品与范围](product.md) 和 [发布状态](release.md)。
- 一次性审查结论不直接写成 ADR，除非它会长期约束实现。

## 待复核决策

- `planning-completed-event-v7` 通勤成本契约完成后，需要确认是否补充契约版本策略决策。
- 前端路由守卫需要在会话恢复流程稳定后再确定最终策略。
- E2E 和 Windows CI 完成后，再决定是否扩大官方支持平台矩阵。
