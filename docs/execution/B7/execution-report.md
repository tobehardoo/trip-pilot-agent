# B7 执行报告

状态：`PASS / COMMITTED（本提交）`

## 交付结果

B7A 与 B7B 已完整实现：canonical Hard Validation 产生的可修复 FAIL 会进入确定性三轮状态机；本地动作先生成不可变候选，需要路线刷新的日期再通过 Provider 边界重算；每轮完成后执行完整 11/11 重验证。最终只有 `VERIFIED` 进入 completion v9 和体验评分，其余安全地进入 review-required v1。

## Repair catalog 与安全边界

- 支持 `SHIFT_ACTIVITY_TO_OPENING_WINDOW`、`SHIFT_ACTIVITY_BEFORE_LAST_ENTRY`、`CLAMP_VISIT_DURATION`、`REMOVE_DUPLICATE_OPTIONAL_POI`、`REFRESH_TRANSIT_LEGS`、`SHIFT_MEAL_TO_WINDOW`；
- opening、last-entry、duration、meal 使用内部 `ActivityLocator` 定位，locator 不进入 wire；
- duplicate 只移除非首尾、非 fixed、非 must-visit 的后续普通 POI；
- 时间动作禁止跨日，纯时间修复不改变总成本，删除活动只扣除被删活动成本；
- `UNVERIFIED`、证据不足、闭馆、must-visit、住宿和预算失败不自动猜测；
- 每轮最多 16 个动作、最多三个 Provider 日期，最多三轮。

## 运行时与契约

- `PlanningProvider.repair` 统一承载 AMap、Demo 和 fallback 的局部 reroute；
- Worker 发布 progress v2 `REPAIRING`，统计含 `attemptIndex` 与 `actionCount`；倒退的 Provider 内部进度不会覆盖 repair 阶段；
- `hard-validator-v5` 携带最多三条 RepairAttempt；Java parser/validator、DB task event 与 Web reader/UI 无损消费；
- repair history 的上限、连续序号、字段长度、日期、typed refs 与指纹均跨语言 fail closed；
- v1 progress 保持历史只读，v2 是当前 producer 版本；completion v9、review-required v1 与 failure v2 未原位变义。

## TDD 与门禁

- catalog、ValidationRun、engine、session、Provider boundary、Worker outcome/progress、Java parser/DB、Web reader/UI 均先留 RED 再完成 GREEN；
- Python 全量：`1322 passed, 37 skipped`；
- Java `mvn verify`：`414 tests`、0 failures/errors，JaCoCo 通过，Flyway 到 V33；
- Web unit：`311 passed`；typecheck、build、coverage 通过；
- Playwright：本机未安装配置的 Chrome channel，使用 CI/bundled Chromium 后 `13 passed`，属运行环境选择而非代码失败；
- Markdown links 与 `git diff --check` 通过。

独立代码复审首次发现 provider repair 元数据、窗口内部合法时刻和 16 动作跨轮签名三类阻断；均补充 RED 回归并修复，第二轮复审结论为 `PASS — B7_READY_FOR_COMMIT_REVIEW`。

## 残留边界

- 用户编辑仍未生成 `UNVERIFIED` 不可变版本并自动验证 N-1/N/N+1；
- 回滚仍未重新验证；
- Demo/replan TripSkeleton 与主动营业时间放置优化属于 B9；
- Golden scenarios、Java 结构化日志与最终交付属于 B10/B11。
