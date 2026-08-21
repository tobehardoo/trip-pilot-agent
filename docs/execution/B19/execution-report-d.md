# B19-D Execution Report — Road / Taxi / AUTO Semantic Convergence

- 执行日期：2026-08-20
- 依据：`docs/execution/B19/plan-d.md`（含 P0-1 / P0-2 / P0-3 门禁）
- 分支 / HEAD：`codex/feasibility-foundation` @ `d10e70cf354d`

## 1. Verdict

```text
READY_FOR_ACCEPTANCE
```

B19-D0 polyline hardening 与 B19-D1 semantic convergence 已实现；Python、Java、Web 全量自动化回归均通过。

> **⚠️ 注记（2026-08-21，独立审计）**：以上为执行方自评。独立审计（`docs/execution/QA-2026-08-21-closure/report.md` 及其后续结论）另发现 8 项 P1/P2 缺陷（AUTO 批量编辑旧 itinerary、v11 费用校验缺失、TRANSIT 票价漏算、evaluation 非必填、MIXED candidate、畸形 transit segment 数组、并发幂等重复调用、preview/commit 契约相反）与 harness 假绿问题。**发布判定 NO-GO / BLOCKED-INCOMPLETE**；本报告不构成可推 `main` 的依据，B19-D 待缺陷修复与重验后重新验收。

## 2. Locked Semantics

| 门禁 | 最终实现 |
| --- | --- |
| P0-1 persisted `DRIVING` | 仅保留 technical road mode；所有用户通道统一显示“打车”，不提供显式自驾编辑入口 |
| P0-2 manual `TAXI` provenance | Python 以 `DRIVING` 查真实 AMAP road facts；Java 增加 300s 等候并按 `12 + km × 2.6` 估价；持久化 `TAXI/AMAP/estimated=true/RULE_ESTIMATE` |
| P0-3 AUTO authority | Python B19-C 是唯一推荐权威；Web 不再运行 `1.6`、本地 preview、fallback 或 optimistic recommendation |
| provider/domain boundary | 内网 route API 只接受 `WALKING/TRANSIT/DRIVING`；`TAXI` 只存在于 Java 用户意图和持久化层 |
| compatibility | 不引入 `ROAD`、`SELF_DRIVING`、`roadIntent`、`vehicleAccess` 或 completion v12 |

## 3. Architecture Amendment Applied During Execution

生产 `/edits` 与 `/edits/commit` 实际走 candidate-validation 异步链，而不是旧 `applyEdit/applyEdits` 同步直写链。本批按真实生产架构实现：

```text
edit request
  -> early candidate-task idempotency lookup
  -> Java normalizes requested intent
  -> Python route/recommend endpoint
  -> candidate validation command
  -> completion/review event
  -> immutable candidate version persistence
```

- provider 调用不放在 itinerary 行锁/写事务内。
- 幂等查找前移到 current-version 冲突检查之前，已完成的同 key 重放可复用原任务/结果，不重复调用 provider。
- provider 失败只会使 candidate task 失败，不会写入半成品 itinerary version。
- completion v11 已贯通 parser 和 `PlanningCompletionService` 第二道版本门禁。

## 4. B19-D0 — Transit Polyline Hardening

`AmapTransitProvider` 现在区分三种输入：

- 缺失或空 polyline：跳过无几何 segment；其 distance/duration/transfer/walking facts 仍计入汇总。
- 所有 segment 均无几何：合成一个 OD fallback step，plan polyline 为 origin/destination 两点。
- 非空但畸形 polyline：继续 fail closed 为 `PROVIDER_SCHEMA_CHANGED`。
- 同一 transit segment 同时含 walking 与 bus geometry 时，两者均保留并相邻去重。

## 5. Python Route Boundary

- 新增 `POST /internal/v1/routes` 和 `POST /internal/v1/routes/recommend`。
- 复用内部 token 的常量时间校验，不回显 upstream secret/detail。
- request/response/error DTO 显式定义；不直接暴露内部 provider model。
- route endpoint 只接收 technical `WALKING/TRANSIT/DRIVING`，TRANSIT 继续要求 city。
- recommend 复用 B19-C walking short-circuit、TRANSIT/DRIVING 比较和有序规则。
- 单个内部 HTTP 请求最多 3 次 logical provider lookup；HTTP runtime 禁用额外 retry 放大，底层 provider cache 继续 fail-open。
- TRANSIT cache identity 使用 UTC 15 分钟 bucket。
- production replan/repair 已正确注入 transit provider。

## 6. Java Edit / Replan / Persistence

- 新增 `AgentRouteClient` / HTTP client 与稳定 failure mapping。
- 显式 `DRIVING` 编辑请求在 production API 被拒绝；允许 `AUTO/WALKING/TRANSIT/TAXI`。
- manual TRANSIT 持久化真实 `TRANSIT/AMAP/false` facts。
- manual TAXI 在 wire 上规范化为 `DRIVING/AMAP/false`，completion 后按 source intent 恢复为：

```text
mode=TAXI
provider=AMAP
estimated=true
duration=road duration + 300 seconds
estimatedCost=12 + distanceKm * 2.6
costSource=RULE_ESTIMATE
```

- TAXI wait 会参与最终活动时间冲突/预算校验。
- replan 对 TAXI 采用同一 bridge；source endpoint 缺失或重复时 fail closed。
- replan itinerary total cost 按 impacted legs 的 old/new delta 重算，不再沿用陈旧 source total。
- technical DRIVING toll 不计入用户可见 itinerary total，也不进入 share/PDF display cost。
- V38 仅放宽 provider/estimate constraint，允许目标 `TAXI + AMAP + estimated=true`；无 enum、column 或数据重写。

## 7. Contracts

- completion v11 / review-required v2 transit legs 携带 `estimatedCost` 与 `costSource`。
- v9/v10/review v1 serializers 继续排除新字段，保持旧 wire compatibility。
- candidate/replan command schema 与 runtime 对 `TRANSIT`/snapshot metadata 对齐。
- Python Pydantic inbound validators 与 Java parsers 均拒绝 wire `TAXI`；只有 technical W/T/D 可跨 agent boundary。
- Java completion parser 和 completion service 均接受 v11。

## 8. Web / Share / Export

- requested mode 与 persisted mode 分型：requested 无 `DRIVING`，persisted 为 W/T/D/TAXI。
- Transit control 不再估算 duration/cost、推荐 mode、长步行 auto-stage 或展示本地 preview/delta/conflict。
- `DRIVING` 与 `TAXI` 在主站、历史版本、review、分享、导出和 PDF 均显示“打车”。
- DRIVING technical toll 对用户隐藏；TAXI 显示估算 fare、300s wait 与“路线来自高德·费用估算” provenance。
- ICS 原本不包含 transit leg，保持兼容。

## 9. RED Matrix Result

| ID | 结果 | 证据摘要 |
| --- | --- | --- |
| B19-B:D1 | PASS | partial/all-missing/malformed polyline 测试 |
| D1 / D8 / D17 | PASS | persisted/historical DRIVING 全用户通道统一“打车” |
| D2 / D5 / D6 / D18 | PASS | manual TAXI real route + local fare/wait + AMAP/true/RULE_ESTIMATE |
| D3 | DEFER | 未引入 SELF_DRIVING，符合计划 |
| D4 | PASS | manual TRANSIT real AMAP facts |
| D7 | PASS | TAXI replan DRIVING wire bridge、恢复与 total delta |
| D9 / D19 | PASS | AUTO backend-only，Web recommendation symbols/path 已清除 |
| D10 | PASS | async task idempotency 前移，重放不重复 provider call |
| D11 | PASS | provider failure 无 candidate version 写入 |
| D12 / D13 | PASS | read/share/export/PDF label、cost、provenance；ICS 回归 |
| D14 | PASS | TAXI 复用 technical DRIVING cache identity |
| D15 | PASS | v11/v2 接受 TRANSIT、拒绝 TAXI；旧版本兼容 |
| D16 | PASS | 既有 TAXI mode 保留；V38 仅修改 constraint |

## 10. Final Regression

```text
Python full:
  uv run python -m pytest -q -ra --basetemp=.pytest-tmp-b19d-full
  -> 1673 passed, 37 skipped, 1 warning, exit 0

Python lint:
  uv run ruff check src tests
  -> All checks passed

Java full (JDK 24 + Testcontainers/PostgreSQL 16):
  mvn -q test
  -> 551 tests, 0 failures, 0 errors, 0 skipped, exit 0

Web full:
  npm test
  -> 42 files, 446 tests passed, exit 0

Web typecheck:
  npm run typecheck
  -> exit 0

Repository whitespace check:
  git diff --check
  -> exit 0 (only existing CRLF/LF conversion warnings)
```

37 个 Python skip 中，34 个要求单独的 knowledge test database，3 个真实 AMap smoke 要求显式 `RUN_REAL_PROVIDER_TESTS=true` 以消耗配额。唯一 warning 是既有 `AnyHttpUrl` fixture 使用字符串触发的 Pydantic serializer warning，与 B19-D 无关。

## 11. Workspace Note

工作区在本批开始前已包含 B15-B19 多阶段未提交改动。本次未执行 `reset/restore/stash/clean`，也未把共享 dirty workspace 强行拆成提交；B19-D0 与 B19-D1 以测试和本报告作为逻辑验收边界。
