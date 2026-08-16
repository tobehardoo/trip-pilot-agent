# B14 执行计划：100 场景全系统真实用户仿真、卡死诊断与发布冻结验收

- 文档状态：生效中（执行 Agent 维护；acceptance-report 由独立验收 Agent 创建，本批不得创建）
- 批次：B14（独立质量审计批次，不是修复批次）
- 基线 branch：`codex/feasibility-foundation`；HEAD：`89236ea731b3d9aea55a81f96101940299f2c983`
- 隔离项目：`trip-pilot-b14-acceptance`（独立端口 WEB 38085 / Prometheus 39094、独立网络 172.28.241.0/24、独立 volume、独立测试账号、独立镜像 tag `b14-acceptance`）
- 目标：模拟真实用户输入，运行至少 100 个不同业务场景、至少 300 个参数化样本，找出能够真实复现的系统问题；输出真实缺陷、证据、复现步骤与建议修复方向；**不修改生产代码**

## 1. 纪律

- 禁止：reset/stash/checkout/restore/clean/rebase/amend；stage/commit/push；修改生产代码；修改既有 acceptance-report；删除/修改 .omo/、.serena/、docs/audits/、.env；操作用户 trip-pilot-prod 栈；测试失败后降低断言/吞异常/固定 sleep/伪报 PASS；把环境失败写成业务失败或反之。
- 测试结束后只清理 B14 隔离项目。

## 2. 专项

- B14-P0-RESULT-PUBLISHING-STUCK：基础二日广州行程，六层对账（Python/MQ/Java/DB/SSE/Web），DEMO 120s / REAL 300s 时间门禁，卡点分类 A-I，progress 单调性与"未执行"文案专项判断。

## 3. 场景矩阵

100 个强制场景 S001-S100（见 scenario-catalog.md），随机种子 20260815，参数化总量 ≥300：
- ≥30 真实浏览器用户流程
- ≥35 API/MQ/DB 集成场景
- ≥20 REAL_ONLY 动态 Provider 样本（并发 ≤2，记录配额与 429）
- 其余 DEMO_ONLY / fixtures / 故障注入
- 城市 ≥12 个（含直辖市、全市、搜索量少城市）；画像覆盖（人数/节奏/偏好/预算/住宿/必去/避开/餐窗/到离时间）

## 4. 门禁

Python 全量 pytest + ruff（check/format）+ 定向覆盖；Java mvn verify + JaCoCo + Flyway（干净库与升级库）+ planning/mq/trip 集成；Web test + coverage + typecheck + build + Playwright 全量 + B13/B14 生产文件每文件 ≥80%；Compose config/default + DEMO 冷启动 + REAL 隔离 + Rabbit/worker 故障恢复 + restart persistence + B14 Golden；仓库 markdown links + git diff --check + secret scan + staged 空 + 保护目录未进入 diff。

## 5. 缺陷报告格式

每个问题含：defectId、severity（P0-P3）、confidence、affected scenarioIds、用户可见现象、最小复现输入、重现次数/总次数、预期/实际、taskId/traceId、卡住层、文件行号、证据、数据损坏与否、是否阻塞发布冻结、最小修复方向、建议回归测试。写入 defects.md。

## 6. 最终判定

全部条件满足输出 `B14_SYSTEM_ACCEPTANCE_PASS` + `RELEASE_FREEZE_CANDIDATE`；任一 P0/P1、场景未执行或证据不足输出 `B14_SYSTEM_ACCEPTANCE_NEEDS_CORRECTION` + `RELEASE_FREEZE_BLOCKED`。完成后停止：不修改生产代码、不提交、不 push、不创建 release、不修改 acceptance-report。
