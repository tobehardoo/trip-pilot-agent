# 文档中心

- 文档状态：生效中
- 最后更新：2026-08-29
- 项目口径：本地优先、`DEMO_ONLY` 默认；真实 Provider 为可选增强
- **当前主线：Agent 化改造（v1.1）**——在确定性内核之上叠加有界的 LangGraph Agent 编排层

## 第一次了解项目

1. [根 README](../README.md)：能力概览与最快启动路径
2. [产品概述](product/产品概述.md)：产品定义与边界
3. [系统架构](architecture/系统架构.md)：Agent 化后的主链路与信任边界
4. [本地运行指南](operations/本地运行指南.md)：通过 Docker Compose 运行完整系统

## 产品与规划

- [产品概述](product/产品概述.md)
- [项目路线图](product/项目路线图.md)：当前完成度与 v1.0 历史锚点
- [Agent化路线图](product/Agent化路线图.md)：未来方向的权威执行路线（Phase 1–3）

## 架构设计

- [系统架构](architecture/系统架构.md)
- [事件契约](architecture/事件契约.md)：Java / Python / Web 三端的命令与事件权威定义
- [Agent化升级技术设计方案](architecture/Agent化升级技术设计方案.md)：v2.x 设计稿（节点划分 / State 三轴模型 / Tool 收敛 / 事件裁决 / V1-V3 路线）

## 决策记录

- [ADR 索引](adr/README.md)：架构决策记录（ADR-001 ~ ADR-015）

## 开发与运维

- [本地开发指南](development/本地开发指南.md)
- [测试策略](development/测试策略.md)：质量门禁
- [本地运行指南](operations/本地运行指南.md)：权威运行参数

## 说明

- 历史批次执行记录（v1.0 前的 B 系列）与归档文档已从工作区移除，完整保留在 git 历史（`git log -- docs/`）与本地备份（`/tmp/trippilot_docs_backup_20260829`）。
- 文档与代码不一致时，以代码与测试为最终事实来源，并先报告差异。
