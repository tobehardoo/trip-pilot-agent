# 消息契约状态

- 文档状态：生效中
- 最后更新：2026-08-05

## 活跃规划契约

| 事件 | 生产者 | 消费者策略 |
| --- | --- | --- |
| `planning-completed-event-v8` | Python | **当前唯一运行时完成事件**：在 v6 基础上新增可选日程字段 `dayType`/`kind`/`timeFixed`；Java 读取 v1–v6（历史只读）与 v8 |
| `planning-completed-event-v6` | Python（历史） | 只读兼容：历史 v6 事件仍可解析/持久化，不再生产 |
| `planning-failed-event-v2` | Python | Java 读取 v1 和 v2 |
| `planning-failed-event-v1` | 已废弃 | 仅作为历史不可行事件的只读兼容保留 |
| `planning-completed-event-v7` | 无 | **ABANDONED**：transit cost/mode 草案，未进入生产 |

新的 Python 失败事件仅使用 v2。failure v2 仅携带安全 Provider 诊断信息：category/code、provider、operation、可重试性/次数、回退标记、安全消息和可选安全 Provider 码。不得包含凭据、授权数据、完整 Provider 请求/响应、用户敏感输入或堆栈跟踪。

completion v6 具有可选严格 `providerProvenance` 对象。新的成功 producer 使用它来记录 requested/primary/actual providers、回退状态/原因和类型化操作；Route operation 还携带稳定的 Transit/Activity ID 用于持久化重映射。没有该对象的历史 v6 仍然合法，表示未记录来源。Java 不得推断缺失字段。v7 已标记 ABANDONED；v8 为当前运行时版本，仅新增可选日程字段 `dayType`/`kind`/`timeFixed`，消费者（Java/DB/前端）已兼容并持久化。

`fixtures/planning-completed-event-v6/` 中的 fixture 覆盖了历史版本、Demo、纯真实、显式混合回退和故意乱序的多 Transit 混合结果；Python Schema 测试和 Java parser/持久化测试消费相同文件。`fixtures/planning-failed-event-v2/` 中的 Schema fixture 同样被两种语言共享。缺少必填字段、错误的 JSON 类型、非法的 provenance 组合和不支持的 schema 版本均被拒绝。

## 相关文档

- [Provider 策略 ADR](../../docs/adr/provider-mode-failure-and-fallback-policy.md)
- [事件契约文档](../../docs/architecture/事件契约.md)
- [遗留契约说明](legacy/README.md)
