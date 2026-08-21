# 文档中心

- 文档状态：生效中
- 最后更新：2026-08-21
- 项目口径：本地优先、`DEMO_ONLY` 默认；真实 Provider 为可选增强
- **当前发布判定：PASS_WITH_DEFECT / READY_WITH_MINOR_DEFECTS**（见 [Release Readiness](execution/QA-2026-08-21-closure/release-readiness.md)；已推 `main`，残留均为非阻塞 Minor）

## 第一次了解项目

1. [根 README](../README.md)：能力概览与最快启动路径
2. [产品概述](product/产品概述.md)：完整、真实、可执行的定义与项目边界
3. [本地运行指南](operations/本地运行指南.md)：通过 Docker Compose 运行完整系统
4. [项目路线图](product/项目路线图.md)：当前完成度与下一阶段工作

## 产品与规划

- [产品概述](product/产品概述.md)
- [项目路线图](product/项目路线图.md)
- [**系统未来方向与验收标准**](product/系统未来方向与验收标准.md)：完整系统目标、release-to-main 门禁与 GA 验收标准
- [系统完善长期执行与验收总控计划](product/系统完善长期执行与验收总控计划.md)
- [长期任务执行记录](execution/README.md)（批次索引 + 最新 QA 判定）
- [QA-2026-08-21 闭环审计](execution/QA-2026-08-21-closure/report.md)：QA 审计轨迹（结论经 release-readiness 更新为 PASS_WITH_DEFECT）
- [Release Readiness](execution/QA-2026-08-21-closure/release-readiness.md)：当前权威发布判定

## 架构设计

- [系统架构](architecture/系统架构.md)
- [行程真实性与旅行骨架](architecture/行程真实性与旅行骨架.md)
- [规划工作流](architecture/规划工作流.md)
- [行程版本与编辑模型](architecture/行程版本与编辑模型.md)
- [事件契约](architecture/事件契约.md)
- [Provider 集成](architecture/Provider集成.md)
- [架构决策记录](adr/README.md)

## 开发与测试

- [代码架构导读](development/代码架构导读.md)
- [本地开发指南](development/本地开发指南.md)
- [测试策略](development/测试策略.md)
- [Golden 场景目录](architecture/golden-scenario-catalog.md)
- [代码规范](development/代码规范.md)
- [日程重构批次记录](execution/日程重构批次记录.md)
- [评估校准批次记录](execution/评估校准批次记录.md)

批次记录用于解释历史设计过程，不应覆盖产品概述、路线图或架构文档中的当前结论。

## 本地运行与排障

- [本地运行指南](operations/本地运行指南.md)
- [可观测性](operations/可观测性.md)
- [故障排查](operations/故障排查.md)

`docs/operations/部署指南.md` 仅作为旧链接的兼容入口。当前项目没有服务器部署要求。

## 历史资料

- [历史归档索引](archive/README.md)

归档材料可能包含过去的 RC、staging、生产发布和版本数字，只用于追溯，不是当前项目门禁。

## 维护规则

- 代码行为优先于过时描述；发现不一致时修正文档并注明能力是“已完成、部分完成或计划中”。
- 不长期记录会快速变化的测试数量；验证结果以实际命令和 CI 为准。
- 新功能先更新产品概述或路线图，再补架构、测试和使用说明。
- 本地运行指南维护完整、权威的运行参数；根 README 只保留最短启动路径，其他文档通过链接引用，避免复制漂移。
- 公网部署如重新进入范围，应建立单独决策和发布手册，不直接复用历史 staging 门禁。
