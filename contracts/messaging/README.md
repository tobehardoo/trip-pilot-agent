# 消息契约状态

- 文档状态：生效中
- 最后更新：2026-08-13

## 活跃规划契约

| 事件 | 生产者 | 消费者策略 |
| --- | --- | --- |
| `planning-completed-event-v9` | Python | 当前成功事件；要求 VERIFIED feasibility report 与 PlanEvaluation，Java 仅接受 v9 |
| `planning-review-required-event-v1` | Python | UNVERIFIED/NEEDS_REPAIR 候选进入 WAITING_USER，不创建正式版本 |
| `planning-progress-event-v2` | Python | 当前进度事件；含 `REPAIRING` 与有界 attempt/action 统计，Java/Web 同时保留 v1 只读兼容 |
| `planning-failed-event-v2` | Python | Java 读取 v1 和 v2 |
| `planning-failed-event-v1` | 已废弃 | 仅作为历史不可行事件的只读兼容保留 |
| `planning-completed-event-v7` | 无 | **ABANDONED**：transit cost/mode 草案，未进入生产 |
| `planning-completed-event-v1`–`v8` | 历史/冻结 | Java runtime fail closed，不再据此创建正式版本 |

新的 Python 失败事件仅使用 v2。failure v2 仅携带安全 Provider 诊断信息：category/code、provider、operation、可重试性/次数、回退标记、安全消息和可选安全 Provider 码。不得包含凭据、授权数据、完整 Provider 请求/响应、用户敏感输入或堆栈跟踪。

completion v9 使用既有 itinerary/providerProvenance 结构，并新增权威 feasibility report。只有 `hard-validator-v5` 最终产出 VERIFIED 时才写 completion；报告与正式版本在同一事务中持久化。B7 的 RepairAttempt 最多三条且跨 Python、Java、Web 严格校验。无法安全修复或未验证的候选通过 review-required v1 暴露，不得伪装成完成事件。

共享 fixture 覆盖 completion v9、review-required v1、progress v2 与 failure v2；Python Schema 测试和 Java parser/持久化测试消费相同文件。缺少必填字段、错误类型、非法 provenance/repair history 和不支持的 schema 版本均被拒绝。

## 相关文档

- [Provider 策略 ADR](../../docs/adr/Provider模式失败与降级策略.md)
- [事件契约文档](../../docs/architecture/事件契约.md)
- [遗留契约说明](legacy/README.md)
