# 历史归档

- 文档状态：生效中
- 最后更新：2026-08-05

本目录保存项目的历史文档，用于追溯设计、验收和审查上下文，不再作为当前事实来源。当前事实以 `docs/` 顶层和新结构化目录中的活跃文档为准。

## 目录结构

| 目录 | 说明 |
| --- | --- |
| `audits/` | 历史审计报告，包含审计索引 |
| `phase-reports/` | 阶段性执行计划和验收报告 |
| `deprecated/` | 已被新文档体系替代的旧版活跃文档 |
| 本目录 | 整合前的原始文档（预 PR #27） |

## 原始归档文档

| 文件 | 内容 | 状态 |
| --- | --- | --- |
| `27-product-completeness-and-requirements-baseline.md` | V1 产品完整度与需求总账 | 已归档 |
| `28-current-system-status-and-v1-4-plan.md` | V1.3 系统状态与 V2 交接 | 已归档 |
| `api.md` | 原接口与消息契约详稿 | 已归档 |
| `architecture.md` | 原系统架构详稿 | 已归档 |
| `architecture-refactoring-plan.md` | 架构重构执行记录 | 已归档 |
| `database.md` | 原数据库设计详稿 | 已归档 |
| `decision-record.md` | 原完整 ADR 记录（ADR-001 至 ADR-013） | 已归档 |
| `deployment.md` | 原部署详稿 | 已归档 |
| `domain.md` | 原领域模型详稿 | 已归档 |
| `planning.md` | 原规划算法与 Agent 工作流详稿 | 已归档 |
| `planning-progress.md` | V2 规划进度契约原文 | 已归档 |
| `release-checklist.md` | V1.3 发布验收清单 | 已归档 |
| `roadmap.md` | 整合前产品路线图 | 已归档 |
| `v2-code-review-findings.md` | V2.0 审查与验收报告 | 已归档 |
| `v2-delivery-checklist.md` | V2.0 交付与验收清单 | 已归档 |
| `v2-release-evidence.md` | V2.0 发布证据原文 | 已归档 |
| `v2-roadmap.md` | V2.0 方针与范围草案 | 已归档 |
| `v2.1-delivery-statement.md` | V2.1 交付声明（未实施） | 已废弃 |
| `v2.1-product-execution-plan.md` | V2.1 产品执行计划（未实施） | 已废弃 |
| `v2.5-release-evidence.md` | V2.5 发布证据 | 已归档 |
| `v2.5-stage0-stage1-preparation.md` | V2.5 阶段 0/1 准备记录 | 已归档 |
| `post-v2.5-p0-p2-execution-plan.md` | V2.5 之后执行规划 | 已归档 |
| `p0-execution-evidence.md` | P0 配置、CI、Compose 与备份恢复演练 | 已归档 |
| `p0-local-amap-validation.md` | P0 本地 AMap 验证记录 | 已归档 |

## 审计报告

历史审计报告和审计索引位于 [audits/](audits/README.md)。

## 阶段报告

阶段性执行计划、交付基线和验收报告位于 [phase-reports/](phase-reports/)。

## 已废弃文档

被新文档体系替代的旧版文档位于 [deprecated/](deprecated/)。

## 规划领域替代关系

历史规划文档中的长期规则已被当前权威文档吸收，不在本目录继续作为现行事实来源：

| 原文档 | 当前权威文档 |
| --- | --- |
| `domain.md` | [行程真实性与旅行骨架](../architecture/行程真实性与旅行骨架.md)、[行程版本与编辑模型](../architecture/行程版本与编辑模型.md) |
| `planning.md` | [规划工作流](../architecture/规划工作流.md)、[行程真实性与旅行骨架](../architecture/行程真实性与旅行骨架.md) |
| `planning-progress.md` | [事件契约](../architecture/事件契约.md)、[规划工作流](../architecture/规划工作流.md) |

## 使用规则

- 需要判断当前能力、接口、部署或发布状态时，回到顶层维护文档。
- 需要追溯某个方案曾被如何提出或某次验收如何执行时，再阅读本目录。
- 新的一次性报告应放入 `phase-reports/`，并在此处保留简短索引。
