# ADR：Provider 模式、失败与降级策略

- 状态：已接受
- 日期：2026-08-01
- 范围：Python 规划 Worker、AMap 适配器、消息失败契约、Java 任务/SSE/API 映射

## 1. 问题

旧的布尔值 `DEMO_MODE=false` 将 AMap Provider 与整单及路线级 Demo 回退耦合在一起。因此在真实 Provider 失败后，任务仍然可能以 Demo 数据"成功"，而调用方期望的是严格真实执行。可重试也仅是元数据而没有实际执行策略，failure v1 只能表达不可行行程。

## 2. 旧 `DEMO_MODE` 的风险

隐式回退使 `SUCCEEDED` 含义模糊，可能隐藏鉴权或实现缺陷，并可导致顶层 AMAP 结果与 Demo Transit 不一致。不可恢复的 Worker 异常也可能在没有终态业务事件的情况下被重新入队。

## 3. Provider 模式

- `DEMO_ONLY`：仅构造 `DemoPlanningProvider`；不需要 AMap Key 或不发起请求。
- `REAL_ONLY`：要求配置 AMap Key；构造 `AmapPlanningProvider`，不创建 `FallbackPlanningProvider` 或 `DemoRouteProvider`；每次失败都是失败。
- `REAL_WITH_EXPLICIT_FALLBACK`：同时构造真实和 Demo Provider，但仅通过 `ProviderFallbackPolicy` 授权降级。

当前项目本地无凭据运行默认为 `DEMO_ONLY`。拥有合法凭据并明确要求真实结果时使用 `REAL_ONLY`；如果未来公开提供服务，必须重新评估 Provider 配置，并禁止把真实调用失败静默包装成 Demo 成功。

## 4. 错误分类

`ProviderErrorCategory` 是稳定分类：配置错误（configuration）、鉴权错误（authentication）、权限错误（permission）、配额超限（quota）、限流（rate limit）、超时（timeout）、网络错误（network）、不可用（unavailable）、无效请求（invalid request）、无结果（no result）、不支持的模式（unsupported mode）、响应格式异常（malformed response）、数据质量错误（data quality）、Provider 适配器错误（provider adapter）、规划不可行（planning infeasible）和内部错误（internal error）。

`ProviderFailureDetails` 还携带安全的错误码/消息、Provider、操作、可重试性、重试次数、回退标记、可选安全 Provider 码和安全原因类型。排除密钥、授权数据、完整响应、请求载荷和堆栈跟踪。

## 5. 重试策略

`RetryingMapProvider` 和 `RetryingRouteProvider` 共享私有的 `_RetryExecutor`，这是唯一的重试层。默认策略：1 次调用加最多 2 次重试、有界指数退避、抖动、`Retry-After` 支持以及最大累计时间预算。测试注入 sleeper/clock 函数。

只有限流（rate limit）、超时（timeout）、网络错误（network）、不可用（unavailable）和部分响应格式异常（malformed response）可重试；永久性 category 从不重试，即使适配器将其标记为可重试。

## 6. 降级白名单

降级在 `REAL_WITH_EXPLICIT_FALLBACK` 之外始终被拒绝。重试耗尽后，内置显式模式策略允许限流、超时、网络错误和不可用进行降级。配额超限和响应格式异常默认不允许降级，可通过 `PROVIDER_FALLBACK_CATEGORIES` 添加。配置、鉴权、权限、无效请求、适配器和内部错误**不可配置**降级。未知失败默认为拒绝。

## 7. POI 局部失败

普通的 `POI_NOT_FOUND` 查询不贡献候选项，当有足够多其他候选项时规划可继续。缺失必去地点或固定业务约束会导致显式不可行/失败语义；Worker 不会在 `REAL_ONLY` 下凭空构造 Demo POI。

## 8. 路线局部失败

局部路线回退时：
- 目标 Transit 标记为 `DEMO`，`estimated=true`。
- 其他 Transit 和 Activity 保持 `AMAP`。
- 顶层来源聚合为 `MIXED`。
- 降级原因和关联 ID 记录在 completion v6 的 `providerProvenance` 中。

`REAL_ONLY` 下路线失败发布 failure v2，不能转换为成功。

## 9. 完成事件来源追踪

completion v6 的可选 `providerProvenance` 对象包含：
- `requestedProviderMode`：请求的 Provider 模式。
- `primaryProvider`：主 Provider。
- `actualProviders`：实际使用的 Provider 的非空列表。
- `fallback`：是否触发降级及结构化原因。
- `operations`：结构化操作记录。

Route operation 包含稳定的 `transitId`/`fromActivityId`/`toActivityId`、请求的 mode、实际 Provider、安全 error category/code 和 retry count。Java 在完成事务中将消息 ID 重映射为版本数据库 UUID。

`actualProviders` 与最终 Activity/Transit 的 provider 值一致。历史 v6 缺失 provenance 时任务 API 的对应字段为 `null`/缺失。

## 10. 失败事件 v2

新的失败事件使用 `planning-failed-event-v2`，携带安全诊断信息：category/code、Provider、操作、可重试性/次数、回退标记、安全消息和可选安全 Provider 码。不包含凭据、授权数据、完整 Provider 请求/响应、用户敏感输入或堆栈跟踪。

Java 消费者兼容 v1 和 v2；v1 仅作为历史不可行事件的只读兼容保留。

## 11. 配置迁移

| 旧配置 | 新配置 |
| --- | --- |
| `DEMO_MODE=true` | `PROVIDER_MODE=DEMO_ONLY` |
| `DEMO_MODE=false` | `PROVIDER_MODE=REAL_ONLY` |

启动时旧值映射到新模式。新值和旧值冲突时启动失败。`PROVIDER_MODE` 是权威配置。

## 12. 回滚兼容

回滚到旧镜像时切换到明确的 `DEMO_ONLY` 或回退上一已知良好版本。旧镜像中的 `DEMO_MODE` 仍然有效。不能恢复"真实失败静默 Demo 成功"的旧语义。

## 13. 验证

- 所有三种模式在 Python 中有专门测试。
- `REAL_ONLY` 下完全不会构造或调用 Demo Provider。
- 降级仅在显式模式且白名单允许时发生。
- 重试和回退有定向测试覆盖。
- completion v6 成功来源追踪和 failure v2 已在 Java 持久化、SSE 和 API 中验证。
- 共享 fixture 同时被 Python Schema 测试和 Java parser/持久化测试消费。
- Java 兼容 v1/v2 失败事件、重复/乱序终态和零版本失败路径。

## 14. 修订（2026-08-07）：v8 基线

- 当前运行时完成事件已升级为 completion v8（= v6 + 可选日程最小字段 `dayType`/`kind`/`timeFixed`）。本 ADR 中关于 `providerProvenance` 的字段与语义在 v8 中原样承袭。
- 具体版本状态以[事件契约](../architecture/事件契约.md)与[消息契约状态](../../contracts/messaging/README.md)为准。
