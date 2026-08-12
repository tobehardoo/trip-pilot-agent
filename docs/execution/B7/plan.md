# B7 有界修复与运行时接入计划

状态：`PASS / COMMITTED（本提交）`

## 目标

在 Hard Validation 11/11 与 Feasibility outcome 链上加入确定性、最多三轮的 repair/replan。只有重新验证为 `VERIFIED` 的最终候选进入 completion v9；`UNVERIFIED`、无合法动作、无进展、重复失败或三轮耗尽继续进入 review-required v1。

## 已落实约束

- 最多三轮，每轮最多一次 Provider 调用、最多三个受影响日期；
- 纯 repair engine 不读取时钟、网络或数据库，Provider 调用由 Worker 协调；
- 只处理 catalog 映射且 `repairable=true` 的 FAIL；
- 不替换 must-visit，不伪造住宿、营业证据或时长证据；
- 每轮产生不可变新候选并重新执行完整 Hard Validator 11/11；
- 指纹不变、相同失败重复、`UNVERIFIED`、无合法动作或预算耗尽立即停止；
- RepairAttempt 最多三条，序号连续，动作、日期、实体引用和指纹均有界且跨语言 fail closed；
- 体验评分只在最终 `VERIFIED` 后执行。

## 已完成工作组

1. RepairAction catalog 与 `hard-validator-v5` repairability；
2. opening / last-entry / duration / duplicate / transit / meal 六类纯动作；
3. 三轮状态机、无进展/重复失败检测和 RepairAttempt 记录；
4. AMap、Demo 与 fallback Provider 的局部 reroute 边界；
5. Worker repair coordinator 与 progress v2 `REPAIRING`；
6. Java validator v5、RepairAttempt、progress v2 解析和持久化；
7. Web progress、repair history 与 v5 fail-closed reader；
8. Python、Java、Web、E2E 和文档全门禁。

## 验收结果

- Python：`1322 passed, 37 skipped`；
- Java：`mvn verify` `414 tests`、0 failures/errors，JaCoCo 与 Flyway V33 通过；
- Web：`311 passed`，typecheck/build/coverage 通过，CI 浏览器模式 E2E `13 passed`；
- repair history 的 3 次上限、连续序号、非空动作/触发规则、ISO 日期、typed refs 与 64 位十六进制指纹由 Python/Java/Web 共同锁定；
- Markdown links 与 `git diff --check` 通过；
- 未触碰保护目录 `.omo/`、`.serena/`、`docs/audits/`。

本批不包含编辑后重验证、回滚重验证、Demo/replan TripSkeleton 完整化或主动放置优化；这些分别属于 B8/B9。
