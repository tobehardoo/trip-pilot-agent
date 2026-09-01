# 消息契约状态

- 文档状态：生效中
- 最后更新：2026-08-19

## 活跃规划契约

| 事件 | 生产者 | 消费者策略 |
| --- | --- | --- |
| `planning-completed-event-v11` | Python | **当前成功事件**；在 v10 结构上允许 `TRANSIT` 为 planner 生成的 Provider-backed route mode（B19-B）；Java 接受 v9/v10/v11 |
| `planning-completed-event-v10` | 上一代 | B16 引入 `hasBlocker` 与可保存 UNVERIFIED 报告；Java 只读兼容；`transitLeg.mode` 仍仅 `WALKING/DRIVING` |
| `planning-review-required-event-v2` | Python | **当前 review 事件**；与 v1 结构一致，允许 `TRANSIT` route mode（B19-B）；Java 接受 v1/v2 |
| `planning-review-required-event-v1` | 上一代 | 只读兼容；`transitLeg.mode` 仍仅 `WALKING/DRIVING` |
| `planning-progress-event-v2` | Python | 当前进度事件；含 `REPAIRING` 与有界 attempt/action 统计，Java/Web 同时保留 v1 只读兼容 |
| `planning-failed-event-v2` | Python | Java 读取 v1 和 v2 |
| `planning-failed-event-v1` | 已废弃 | 仅作为历史不可行事件的只读兼容保留 |
| `planning-completed-event-v7` | 无 | **ABANDONED**：transit cost/mode 草案，未进入生产 |
| `planning-completed-event-v1`–`v8` | 历史/冻结 | 全部移入 `legacy/`（v4–v8 于 F-3c 迁移）；Java runtime fail closed，不再据此创建正式版本 |

新的 Python 失败事件仅使用 v2。failure v2 仅携带安全 Provider 诊断信息：category/code、provider、operation、可重试性/次数、回退标记、安全消息和可选安全 Provider 码。不得包含凭据、授权数据、完整 Provider 请求/响应、用户敏感输入或堆栈跟踪。

completion v11 使用 v10 结构（含 `hasBlocker`、权威 feasibility report、可保存 UNVERIFIED）并扩展 `transitLeg.mode` 允许 `TRANSIT`（B19-B 真实 Provider-backed route mode；TAXI 不进，因其仍无真实 Python provider）。v9/v10 仍只读兼容，旧版本语义不放宽。无法安全修复或未验证的候选通过 review-required v2 暴露，不得伪装成完成事件。

共享 fixture 覆盖 completion v10/v11、review-required v1/v2、progress v2 与 failure v2；Python Schema 测试和 Java parser/持久化测试消费相同文件。缺少必填字段、错误类型、非法 provenance/repair history 和不支持的 schema 版本均被拒绝。

## 相关文档

- [Provider 策略 ADR](../../docs/adr/Provider模式失败与降级策略.md)
- [事件契约文档](../../docs/architecture/事件契约.md)
- [遗留契约说明](legacy/README.md)
