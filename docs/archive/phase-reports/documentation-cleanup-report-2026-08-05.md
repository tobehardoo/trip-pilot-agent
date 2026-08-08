# 文档清理报告

> 文档状态：已归档
> 归档日期：2026-08-05
> 本文档记录 2026-08-05 文档系统清理的完整过程和结果。

## 一、文档盘点摘要

| 指标 | 数量 |
| --- | --- |
| 原有文档总数 | 53（含根目录 README、docs/ 主文档、ADR、审计、归档和 contracts） |
| 活跃文档数量（处理后） | 19 |
| 归档文档数量（处理后） | 34 |
| 新创建文档数量 | 17 |
| 已移动文档数量 | 19 |
| 替代的旧版活跃文档 | 8 |

## 二、处理清单

### 新创建文档

| 文档 | 路径 | 说明 |
| --- | --- | --- |
| 文档中心 | `docs/index.md` | 统一中文文档导航，按阅读目标组织 |
| 产品概述 | `docs/product/产品概述.md` | 合并 `product.md` 和 `release.md` 内容 |
| 项目路线图 | `docs/product/roadmap.md` | 从 `roadmap-2026-08-02.md` 提取，去除日期后缀 |
| 系统架构 | `docs/architecture/系统架构.md` | 从 `architecture.md` 重写 |
| 规划工作流 | `docs/architecture/规划工作流.md` | 从 `architecture.md` 和 `planning.md` 提取 |
| 行程版本与编辑模型 | `docs/architecture/行程版本与编辑模型.md` | 合并分散在多个文档中的编辑/版本/幂等内容 |
| 事件契约 | `docs/architecture/事件契约.md` | 从 `api.md` 和 contracts 目录整合 |
| Provider 集成 | `docs/architecture/Provider集成.md` | 合并分散在 architecture/deployment/ADR 中的 Provider 文档 |
| 本地开发指南 | `docs/development/本地开发指南.md` | 从 `deployment.md` 提取开发相关内容 |
| 测试策略 | `docs/development/测试策略.md` | 从 `release.md`、`README.md` 和 CI 配置整合 |
| 代码规范 | `docs/development/代码规范.md` | 新建，整合各语言编码规范 |
| 部署指南 | `docs/operations/deployment.md` | 从 `deployment.md` 重写 |
| 可观测性 | `docs/operations/observability.md` | 从 `architecture.md` 提取可观测性内容 |
| 故障排查 | `docs/operations/troubleshooting.md` | 新建，整合常见问题和恢复演练 |
| ADR 索引 | `docs/adr/README.md` | 从 `decision-record.md` 提取 ADR 索引 |
| 审计归档索引 | `docs/archive/audits/README.md` | 审计报告中文索引 |
| 清理报告 | `docs/archive/phase-reports/documentation-cleanup-report-2026-08-05.md` | 本文档 |

### 更新的文档

| 文档 | 更新内容 |
| --- | --- |
| `README.md` | 重写为简洁中文版，更新文档链接 |
| `docs/README.md` | 改为兼容入口，指向新 `docs/index.md` |
| `docs/archive/README.md` | 更新目录结构和文件说明 |
| `contracts/messaging/README.md` | 翻译为中文，更新文档引用 |
| `docs/adr/方案评估与解释策略.md` | 全文翻译为中文 |
| `docs/adr/Provider模式失败与降级策略.md` | 全文翻译为中文 |

### 归档文档

#### 移至 `docs/archive/deprecated/`（被新文档替代）

| 原路径 | 新路径 | 替代文档 |
| --- | --- | --- |
| `docs/product.md` | `docs/archive/deprecated/product.md` | `docs/product/产品概述.md` |
| `docs/architecture.md` | `docs/archive/deprecated/architecture.md` | `docs/architecture/系统架构.md` |
| `docs/api.md` | `docs/archive/deprecated/api.md` | `docs/architecture/事件契约.md` |
| `docs/deployment.md` | `docs/archive/deprecated/deployment.md` | `docs/operations/deployment.md` |
| `docs/decision-record.md` | `docs/archive/deprecated/decision-record.md` | `docs/adr/README.md` |
| `docs/release.md` | `docs/archive/deprecated/release.md` | `docs/product/产品概述.md` |
| `docs/roadmap-2026-08-02.md` | `docs/archive/deprecated/roadmap-2026-08-02.md` | `docs/product/roadmap.md` |
| `docs/current-system-understanding.md` | `docs/archive/deprecated/current-system-understanding.md` | `docs/architecture/系统架构.md` 和 `docs/architecture/规划工作流.md` |

#### 移至 `docs/archive/phase-reports/`（一次性报告）

| 原路径 | 新路径 |
| --- | --- |
| `docs/next-stage-execution-plan.md` | `docs/archive/phase-reports/next-stage-execution-plan.md` |
| `docs/project-delivery-baseline.md` | `docs/archive/phase-reports/project-delivery-baseline.md` |
| `docs/release-candidate-validation-report.md` | `docs/archive/phase-reports/release-candidate-validation-report.md` |
| `docs/current-state-assessment.md` | `docs/archive/phase-reports/current-state-assessment.md` |

#### 移至 `docs/archive/audits/`（审计报告）

| 原路径 | 新路径 |
| --- | --- |
| `docs/audits/roadmap-audit-2026-08-02-1.md` | `docs/archive/audits/roadmap-audit-2026-08-02-1.md` |
| `docs/audits/roadmap-audit-2026-08-02-2.md` | `docs/archive/audits/roadmap-audit-2026-08-02-2.md` |
| `docs/audits/roadmap-audit-2026-08-04-3.md` | `docs/archive/audits/roadmap-audit-2026-08-04-3.md` |
| `docs/audits/roadmap-audit-2026-08-04-4.md` | `docs/archive/audits/roadmap-audit-2026-08-04-4.md` |
| `docs/audits/roadmap-audit-2026-08-04-5.md` | `docs/archive/audits/roadmap-audit-2026-08-04-5.md` |
| `docs/audits/current-version-product-completeness-2026-08-04.md` | `docs/archive/audits/current-version-product-completeness-2026-08-04.md` |
| `docs/audits/full-project-scan-2026-08-04.md` | `docs/archive/audits/full-project-scan-2026-08-04.md` |

### 删除

本次清理未删除任何文档。所有被替代的文档均移至归档目录，保留历史追溯能力。

## 三、当前事实来源清单

| 主题 | 当前事实来源 | 状态 |
| --- | --- | --- |
| 项目路线图 | `docs/product/roadmap.md` | 生效中 |
| 产品概述与发布状态 | `docs/product/产品概述.md` | 生效中 |
| 系统架构 | `docs/architecture/系统架构.md` | 生效中 |
| 规划工作流 | `docs/architecture/规划工作流.md` | 生效中 |
| 行程版本与编辑模型 | `docs/architecture/行程版本与编辑模型.md` | 生效中 |
| 事件版本与契约 | `docs/architecture/事件契约.md` | 生效中 |
| Provider 集成 | `docs/architecture/Provider集成.md` | 生效中 |
| 本地开发 | `docs/development/本地开发指南.md` | 生效中 |
| 测试策略 | `docs/development/测试策略.md` | 生效中 |
| 代码规范 | `docs/development/代码规范.md` | 生效中 |
| 部署 | `docs/operations/deployment.md` | 生效中 |
| 可观测性 | `docs/operations/observability.md` | 生效中 |
| 故障排查 | `docs/operations/troubleshooting.md` | 生效中 |
| 架构决策记录 | `docs/adr/README.md` | 生效中 |
| Provider 模式与降级 | `docs/adr/Provider模式失败与降级策略.md` | 已接受 |
| PlanEvaluation 策略 | `docs/adr/方案评估与解释策略.md` | 已接受 |
| 消息契约目录 | `contracts/messaging/README.md` | 生效中 |
| 历史审计 | `docs/archive/audits/README.md` | 生效中 |
| 历史归档 | `docs/archive/README.md` | 生效中 |

## 四、发现的问题

### 4.1 文档与代码一致性

- 已确认：所有活跃文档中的事件版本号（completion v6、failure v2）、数据库迁移版本（V1–V27）、服务名称和环境变量名称与代码一致。
- 已确认：Java 208 tests、Python 547 passed、Web 126 passed 等测试数字来自最新审计报告（2026-08-04 全项目扫描），与 CI 结果一致。

### 4.2 英文文档翻译完成

- 已翻译：`docs/adr/方案评估与解释策略.md`（原文英文，已全文翻译）
- 已翻译：`docs/adr/Provider模式失败与降级策略.md`（原文英文，已全文翻译）
- 已翻译：`contracts/messaging/README.md`（原文英文，已全文翻译）
- 遗留英文文档：`contracts/messaging/legacy/README.md`（英文，内容为历史 Schema 索引，保留英文可接受）
- 遗留英文文件：`knowledge/guangzhou/` 下的城市知识文档（英文 TOML frontmatter 由程序解析，保留英文）

### 4.3 仍需后续处理的事项

以下事项不属于本次文档清理范围，但已在文档中标注：

1. `ItineraryService.java`（超过 1100 行）和 `TripDetail.vue`（超过 1300 行）需要拆分。
2. 旅行列表、行程读取和版本差异的 N+1 查询需要专项优化。
3. Java 服务日志输出较少（已知问题）。
4. Outbox 重试当前无上限（已知问题）。
5. Staging 验收（S-01 至 S-13）全部阻塞于外部资源。
6. `planning-completed-event-v7` 草案尚未启用。
7. 前端路由守卫需要在会话恢复流程稳定后确定最终策略。

### 4.4 术语统一

已在所有新文档中统一以下术语：

| 术语 | 统一用法 |
| --- | --- |
| 行程版本 | 统一使用"行程版本"而非 "itinerary 版本" |
| 局部重规划 | 统一使用"局部重规划"而非 "partial replan" |
| 事件契约 | 统一使用"事件契约"而非 "event schema" |
| 幂等键 | 统一使用"幂等键"而非混用 "idempotency key" |
| 数据来源 | 统一使用"数据来源"而非混用 "source" |
| 降级策略 | 统一使用"降级策略"而非混用 "fallback" |
| 当前事实来源 | 统一使用"当前事实来源" |
| 不可变行程版本 | 统一使用"不可变行程版本"（Immutable Itinerary Version） |
| 发布候选 | 统一使用"发布候选"（RC） |

## 五、验证结果

### 5.1 Git 状态检查

- **执行命令：** `git status --short`
- **结果：** 通过
- **说明：** 所有变更为 Markdown 文档的修改（M）、重命名（R）和新增（??）。无业务代码、数据库迁移、API 契约、构建逻辑或 CI 配置变更。

### 5.2 空白检查

- **执行命令：** `git diff --check HEAD`
- **结果：** 通过
- **说明：** 无空白问题。

### 5.3 文档链接检查

- **执行方式：** 手动检查所有活跃文档的相对链接。
- **结果：** 通过
- **说明：**
  - 根 `README.md` 的文档链接均指向新路径。
  - `docs/index.md` 的所有链接均有效。
  - 活跃文档之间的相对链接均有效。
  - 归档子目录的 `README.md` 中有正确的替代文档链接。
  - 无活跃文档引用已移动或已删除的文件路径。

### 5.4 内容一致性检查

- **执行方式：** 对比代码、配置和最新审计报告。
- **结果：** 通过
- **说明：**
  - 事件版本号（completion v6、failure v2）一致。
  - 数据库迁移版本（V1–V27）一致。
  - 服务名称、环境变量名称一致。
  - 测试命令可执行。
  - 当前版本状态（远端 CI 已验证的 RC 候选，不等同于可生产发布）准确。

### 5.5 中文检查

- **执行方式：** 逐个审查所有新创建和重写的文档。
- **结果：** 通过
- **说明：**
  - 所有标题使用中文。
  - 正文说明使用中文。
  - 表格字段使用中文。
  - 操作说明使用中文。
  - 无整段无必要英文。
  - 代码块、命令、标识符和技术名称保持英文（符合要求）。
  - 术语使用一致。

### 5.6 未执行的检查

| 检查 | 原因 |
| --- | --- |
| Markdown links 工具扫描 | 仓库没有配置 Markdown link checker；手动验证已覆盖所有活跃文档 |
| 全量测试运行 | 仅修改 Markdown 文档，不需要运行完整业务测试 |
| CI 验证 | 当前分支未推送；本次变更仅涉及文档，远端 CI 通过后方可合并 |

### 5.7 外部资源阻塞

本次文档清理不涉及外部资源。Staging 验收的 S-01 至 S-13 阻塞状态未改变。

## 六、结论

本次文档清理完成了以下目标：

1. **建立了清晰的中文文档体系**，按 `product/`、`architecture/`、`development/`、`operations/`、`adr/` 和 `archive/` 组织。
2. **建立了唯一当前事实来源**，每个核心主题只有一篇活跃文档负责。
3. **统一了全部活跃文档为简体中文**，标题、正文、表格、操作说明均使用中文。
4. **合并了重复文档**，8 篇旧活跃文档的内容整合到新体系中。
5. **归档了有历史价值的文档**，按 `audits/`、`phase-reports/`、`deprecated/` 分类。
6. **保留了所有原始文档**，无文档被删除，确保历史可追溯。
7. **修复了全部文档引用**，活跃文档之间的链接均有效。
8. **未修改任何业务代码、数据库、API 或 CI 配置**。

建议下一步操作：
1. 推送分支并创建 PR，让 CI 验证通过。
2. 合并后将新文档结构作为项目的正式文档入口。
3. 后续按维护规则持续更新活跃文档，不再更新归档文档。
