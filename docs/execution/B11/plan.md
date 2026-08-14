# B11 最终统一验收与本地交付收口

- 状态：PASS / COMMITTED（B11 提交）
- 分支：codex/feasibility-foundation
- 基线 HEAD：f2040f0（B10 提交）
- 定位：验证 B1–B10 系统完整、可运行、可理解；不扩展功能。发现真实缺陷时经 B11_FIX 做 TDD 最小修复。

## 目标

1. 完成范围事实审计（18 项核心目标矩阵：已完成/部分完成/未完成/非目标，逐项引用实现/测试/入口/用户可见结果/残留限制）。
2. 架构调用链最终审计（创建/重规划、编辑、回滚、Feasibility 四条链，检查绕过/第二套规则/漂移）。
3. 最终功能验收矩阵（以 B10 Golden catalog 为权威，逐场景汇总）。
4. 本地运行验收（Compose config + 仓库 smoke + DEMO_ONLY 主链）。
5. 契约和数据库最终验收（schema/fixtures/parser/fingerprint/Flyway V1–V34/CHECK 约束）。
6. 安全与日志验收（secret 扫描、.env 未跟踪、MDC 清理、Outbox 日志、token 不回退）。
7. 完整门禁（Python/Java/Web/E2E/仓库）。
8. 最终文档事实校准（14 份文档，不保留 B1–B10 过时状态）。
9. 新增 docs/development/代码架构导读.md（基于真实代码，含建议阅读顺序）。
10. B11_FIX 规则（RED→最小修复→门禁，不立即提交）。
11. 独立最终验收（B11_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT 才可收口）。
12. 最终 Git 收口（提交后 parent 必须 f2040f0）。

## 禁止

- push/force push/配置 upstream；reset/stash/checkout/restore/clean/rebase/amend/squash
- git add ./-A、commit -a、--no-verify
- 删除或暂存保护目录；处理 .env
- skip、弱化断言、吞异常、降低 coverage 阈值
- 未经证据扩大功能范围；把公网部署要求重新设为门禁（staging/TLS/registry/24h soak 为非目标）

## 完成范围审计矩阵（18 项）

| # | 核心目标 | 结论 | 实现位置 | 关键测试 | 运行时入口 | 用户可见结果 | 残留限制 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Hard Validation 11/11 | 待审计 | | | | | |
| 2 | Feasibility Report 三态 | 待审计 | | | | | |
| 3 | Trip Skeleton 与住宿三态 | 待审计 | | | | | |
| 4 | 路线端点与跨日连续性 | 待审计 | | | | | |
| 5 | Opening evidence 与营业时间 | 待审计 | | | | | |
| 6 | Visit Duration Profile | 待审计 | | | | | |
| 7 | 显式 Meal Window | 待审计 | | | | | |
| 8 | bounded repair/replan | 待审计 | | | | | |
| 9 | 编辑后重新验证 | 待审计 | | | | | |
| 10 | 回滚重新验证 | 待审计 | | | | | |
| 11 | Feasibility 前端 | 待审计 | | | | | |
| 12 | Golden scenarios | 待审计 | | | | | |
| 13 | Java/Python 结构化日志 | 待审计 | | | | | |
| 14 | completion v9 / review v1 | 待审计 | | | | | |
| 15 | Java 持久化/Task API/SSE/VersionSummary | 待审计 | | | | | |
| 16 | Demo 与真实 Provider 安全边界 | 待审计 | | | | | |
| 17 | 本地 Compose 运行 | 待审计 | | | | | |
| 18 | 契约/迁移/跨语言一致 | 待审计 | | | | | |

## 验收重点（独立验收 Agent 复用）

1–20 项见 B11 指令第十二节：完成矩阵真实、11/11、三态权威、Demo 不假 VERIFIED、VERIFIED-only 门禁、三轮上限、candidate 隔离、stale/duplicate/fingerprint fail closed、事务原子性、Task API/SSE/Web 一致、Golden 跨层真实、日志安全与 MDC、Compose/smoke、门禁真实、文档数字无漂移、本地优先定位、架构导读真实、无保护目录/secret/产物、无未解释核心缺口、execution-report 不夸大。

## 收口

提交信息（无代码修复时）：docs(project): complete local-first system acceptance
提交信息（含 B11_FIX 时）：chore(platform): complete local-first system acceptance
parent 必须为 f2040f0。最终输出 B11_PASS_AND_COMMITTED。不 push。
