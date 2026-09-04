# 文档中心

- 文档状态：生效中
- 最后更新：2026-09-05
- 项目口径：本地优先、`DEMO_ONLY` 默认；真实 Provider 为可选增强
- **当前主线：有界的 Conversational Agent 编排（v1.1）**——确定性规划内核之上叠加有界的 LangGraph 会话编排层

本目录按用途组织：

| 子目录 | 内容 |
|---|---|
| `product/` | 产品概述、项目路线图、Agent化路线图 |
| `architecture/` | 系统架构、事件契约、Agent UX 3.0 方案等活文档 |
| `adr/` | 架构决策记录（ADR-001 ~ ADR-016） |
| `development/` | 新人上手指南、本地开发指南、测试策略 |
| `operations/` | 本地运行指南 |
| `archive/` | 历史快照与已被取代的文档（只读，不随新功能维护） |

## 第一次了解项目

1. [根 README](../README.md)：能力概览与最快启动路径
2. [产品概述](product/产品概述.md)：产品定义与边界
3. [系统架构](architecture/系统架构.md)：主链路与信任边界
4. [本地运行指南](operations/本地运行指南.md)：通过 Docker Compose 运行完整系统

## 产品与规划

- [产品概述](product/产品概述.md)
- [项目路线图](product/项目路线图.md)：当前完成度与版本锚点
- [Agent化路线图](product/Agent化路线图.md)：未来方向的权威执行路线（Phase 1–3）

## 架构设计

- [系统架构](architecture/系统架构.md)
- [运行模型](architecture/运行模型.md)：Agent/Planning/数据流/状态流/Constraint/Failure-Recovery 权威摘要
- [事件契约](architecture/事件契约.md)：Java / Python / Web 三端的命令与事件权威定义
- [Agent UX 3.0 方案](architecture/agent-ux-3.0-redesign-plan.md)：Travel Planning Session 重构方案（已批准实施）
- [Canonical Vocabulary](architecture/canonical-vocabulary.md)：全仓规范词表（F-2a）

## 决策记录

- [ADR 索引](adr/README.md)：架构决策记录（ADR-001 ~ ADR-016）

## 开发与运维

- [本地开发指南](development/本地开发指南.md)
- [测试策略](development/测试策略.md)：质量门禁
- [本地运行指南](operations/本地运行指南.md)：权威运行参数

## 归档

- 历史批次执行记录与已被取代的设计稿（v1.0 前 B 系列、Agent UX 2.0、Planning Intelligence v1/v2、Agent化升级技术设计方案、3.0 审计快照）统一归档在 [archive/](archive/) 与 git 历史（`git log -- docs/`）。归档内容只读，不保证与当前代码一致。

## 说明

- 文档与代码不一致时，以代码与测试为最终事实来源，并先报告差异。
