# B10 执行报告

- 状态：PASS / COMMITTED（B10 提交）
- 批次：B10 Golden Scenarios、结构化日志与最终质量收口

## 基线

- branch=codex/feasibility-foundation ✓
- HEAD=7c0da66（B9）✓
- staged 空 ✓；未跟踪仅 .omo/ .serena/ docs/audits/ ✓
- 总控计划 B8=COMMITTED、B9=PASS/COMMITTED、B10=NOT_STARTED、B11=NOT_STARTED ✓
- 断点=B10 ✓

## 二、事实审计结论

12 主链矩阵：CREATE/REPLAN/EDIT_VALIDATE/ROLLBACK_VALIDATE/bounded repair 由 `worker/processor.py` 三个 orchestrator + `_repair_if_needed` 承载，已有 orchestrator 级测试；completion v9/review v1/Task API/SSE/Java 持久化由 Java integration 测试（Testcontainers DB read-back）覆盖；Web authoritative outcome 由 feasibility-outcomes.spec.ts 覆盖。

发现：
- Java 主代码零结构化日志（`@Slf4j` 计数 0，无 MDC，无 logback 配置）——本批最大缺口，已补齐。
- Python Worker 日志为裸 `%s` 参数，无结构化字段——已补齐。
- 枚举无漂移：FeasibilityStatus/RuleOutcome/EvidenceState 在 Python 与 Java 完全一致。
- Java UUID 与 PostgreSQL 排序漂移已在 B6F 修复（`compareAsPostgresUuid`），本批确认无需再动。
- Python 测试 0 处 `datetime.now/uuid4/sleep`；Web E2E 0 处 sleep、0 处 .only/.skip；Java 测试 `LocalDateTime.now` 属 fixture 时间戳，非顺序依赖。
- Web coverage include 已含 feasibility 模块；Python 新增 logging 模块实测 100%。

## 三、Golden Scenario Matrix

权威位置：`docs/architecture/golden-scenario-catalog.md`（30 场景 ID + 10 条全局语义不变式 + 各层消费约定）。无各层复制定义。

## 四、子任务状态（全部 GREEN）

| 子任务 | 结果 |
| --- | --- |
| Golden catalog | 30 场景 + 不变式，单一权威文档 |
| Python Golden | `tests/test_golden_matrix.py` 5 用例（G04/G05/G06/G07/G09/G11），orchestrator 级、固定 UTC/固定 UUID、结构断言 |
| Java 跨层 Golden | 现有 integration 测试已覆盖全部 20 项（逐项映射确认，无需新增，避免重复）；新增 `PlanningLogContextTest` 5 用例 |
| Web Golden | `e2e/golden-journeys.spec.ts` 3 用例（G26/G27/G20） |
| Java 结构化日志 | `PlanningLogContext`（MDC 快照/恢复，嵌套安全）+ logback `LOG_CORRELATION_PATTERN`；8 落点全部接入 |
| Python 结构化日志 | `worker/structured_logging.py` + processor/amqp 边界日志 |
| 确定性清理 | Java UUID 排序已修复（B6F）；Python/Web 无时钟/顺序/随机问题；新增 logging 模块 100% 覆盖 |
| 文档 | golden-scenario-catalog（新增）、规划工作流、事件契约、行程真实性、测试策略、可观测性、项目路线图 |

## 五、门禁（真实数字）

| 门禁 | 结果 |
| --- | --- |
| Python 全量 | **1370 passed, 37 skipped**（B9 基线 1360 + 10 新增） |
| Ruff | All checks passed；format --check 通过 |
| Java verify | **BUILD SUCCESS，429 tests，0 failures/errors**（B9 基线 424 + 5 新增） |
| Web unit | **311 passed**（33 files） |
| Web coverage | **96.04 / 82.20 / 95.52 / 96.04**（branch 82.2 ≥80） |
| Web typecheck / build | 通过 / 通过 |
| Playwright | **16 passed**（13 基线 + 3 新增） |
| Markdown links | **101 files valid** |
| git diff --check | 通过（仅 CRLF 提示） |
| staged | 空 |

## 六、残留边界

- BREAKFAST meal window 在 planning 域外（LUNCH/DINNER only），AMap 转换跳过——契约现状。
- `as any` 5 处为既有 `constraint-parser.test.ts`，非本批新增。
- 新增模块覆盖率：Python `structured_logging.py` 100%；Java `PlanningLogContext` 100%。
- 本批不引入 staging/TLS/registry/24h soak/生产告警；Prometheus/外部日志平台仍为可选。

## 七、验收准备

待独立验收：`B10_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT` 才允许提交。验收重点见 plan.md。

## 八、B10.1 小修（NEEDS_SMALL_FIX-1/2 关闭）

状态：已关闭，独立复验 8/8 PASS，B10_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT（见 acceptance-report 末尾追加）

### S1：G08 catalog 语义修正（NEEDS_SMALL_FIX-1）

- 文件：`docs/architecture/golden-scenario-catalog.md`
- 原错误值：G08 expectedStatus=UNVERIFIED、blocking=ROUTE_ENDPOINT_CONTINUITY。
- 正确值：expectedStatus=**NEEDS_REPAIR**、blocking=**CROSS_DAY_CONTINUITY / OVERNIGHT_ENDPOINT_MISMATCH**（reasonCode 取自 `feasibility/rules/continuity.py` 实现中的真实稳定值，未自行发明）。
- G08 与 G06 的 FAIL/UNKNOWN 区分：G08 是明确断档（confirmed overnight 端点不匹配 → FAIL → NEEDS_REPAIR，绝不降级 UNKNOWN）；G06 保持 UNVERIFIED（UNRESOLVED 住宿是证据缺口 → UNKNOWN → UNVERIFIED）。全局词汇表已同步澄清该边界。
- 其他场景未改动。

### S2：G26 E2E 补足真实断言（NEEDS_SMALL_FIX-2）

- 采用 **A 方案**（补足断言，保留测试名）。Web read model 真实暴露 `versionSource='ROLLBACK'`（`ItineraryVersionPanel` 的 `sourceLabels.ROLLBACK` → 「历史回滚」badge），无需新增字段。
- TDD：先在新断言 + 原 fixture 下运行，确认 RED（「历史回滚」不可见，`test-failed-1.png` 留存）；随后补 fixture（`markCompleted` 回调置位 → completion 后 versions 返回 v3 ROLLBACK 版本且旧 current 降为非 current、itinerary 返回 v3），GREEN。
- 新增断言：completion 前「版本 2」可见且「历史回滚」计数 0（正式版本不变）；completion 后「版本 3」+「历史回滚」badge 可见 + VERIFIED report + 无 review 面板。
- 测试名保留 `creates a ROLLBACK version`，与断言一致。

### 验证结果

- 目标 E2E：**3 passed**（golden-journeys.spec.ts）
- Web unit：**311 passed**（33 files）
- typecheck：通过
- Markdown links：**102 files valid**（catalog 更新后 +1）
- git diff --check：exit 0
- staged：空；未 commit/push
- 未修改任何业务代码、schema、migration、RabbitMQ、API；改动仅限两个目标文件（catalog、golden-journeys.spec.ts）+ 本报告。
- 未修改 acceptance-report（保留完整 NEEDS_SMALL_FIX 历史）。
