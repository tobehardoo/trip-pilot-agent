# B14 产物清单（artifact-manifest）

## 1. 交付文档（docs/execution/B14/）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| plan.md | 已创建 | 批次计划（基线/纪律/专项/矩阵/门禁/判定） |
| scenario-catalog.md | 已创建 | 100 场景目录（含全部必填字段） |
| execution-report.md | 已创建 | 基线、B14-P0 专项六层对账、矩阵汇总、门禁数字、清理证据 |
| defects.md | 已创建 | 9 项缺陷（D01 P1 阻塞；D02-D09 P2/P3/观察） |
| artifact-manifest.md | 本文件 | 产物与文件清单 |
| acceptance-report.md | **未创建** | 留给独立验收 Agent（任务书禁止） |

## 2. 测试工具（scripts/acceptance/b14/）

| 文件 | 用途 |
| --- | --- |
| b14lib.py | API/DB/MQ/容器对账库（http/db/rabbit/logs/provider_mode） |
| matrix_a.py | S001-S040（账号/创建/区域/地点）+ 结果 results-a.json |
| matrix_b.py | S051-S080（餐饮/住宿修复/Task·MQ·SSE）+ results-b.json |
| matrix_fault.py | S081-S090（故障注入，docker 控制）+ results-fault.json |
| matrix_real.py | S041-S050（REAL 必去/避开）+ R01-20（20 动态样本）+ results-real.json |
| matrix_param.py | P001（110 参数化）+ S099（100 并发）+ results-param.json |

## 3. 生产代码改动

**零改动**（B14 为独立质量审计，未修改任何生产代码、测试、配置、文档除本批次交付物）。

## 4. 隔离环境与清理证据

| 资源 | 值 | 清理状态 |
| --- | --- | --- |
| 项目名 | trip-pilot-b14-acceptance | `down -v --remove-orphans` 已执行 |
| WEB 端口 | 38085 | 已释放 |
| Prometheus 端口 | 39094 | 已释放 |
| 网络 | 172.28.241.0/24（b14_default） | 已删除 |
| 数据卷 | b14_*postgres/redis/rabbitmq/prometheus-data | 已删除 |
| 镜像 | trip-pilot-*:b14-acceptance | 已删除 |
| 临时 env | C:\Windows\Temp\opencode\b14-acceptance.env | 已删除 |
| 浏览器脚本 | apps/web/b14-*.cjs、playwright.b14.config.ts | 已删除（归档逻辑见 execution-report §5） |
| e2e 静态服务容器 | b14-e2e-web（nginx 38084） | 已删除 |
| 用户栈 | trip-pilot-prod（8 容器） | 全程未操作，清理后复核 healthy |

## 5. 未提交证明

- 未 stage/commit/push；HEAD 保持 `89236ea731b3d9aea55a81f96101940299f2c983`；`git diff --cached` 空；未修改 acceptance-report.md、.omo/、.serena/、docs/audits/、.env。
- git status 中本批新增：`docs/execution/B14/`（5 文档）+ `scripts/acceptance/b14/`（7 文件）——全部为任务书允许的交付物/工具。

## 6. 已知 flaky / 环境观察

- Web unit 全量 5s 硬超时 1-2 例（单跑全过；同代码 B13_FIX.2 全绿）——环境性能（D06）
- S043 动态候选波动（D06）
- AMap ROUTE 429 重试（D09）
