# TripPilot 文档索引

- 文档状态：生效中
- 最后更新：2026-08-08

本文档是 TripPilot 项目的统一文档导航入口。按照阅读目标组织，每篇文档标注名称与简介。

---

## 初次了解项目

| 文档 | 简介 |
| --- | --- |
| [产品概述](product/产品概述.md) | 项目是什么、核心能力、已交付功能、非目标、已知限制、发布前置条件和验证状态 |
| [系统架构](architecture/系统架构.md) | 三服务 Monorepo 的服务职责、运行链路、领域边界、数据所有权、可靠性模型和安全合规 |
| [本地开发指南](development/本地开发指南.md) | 从零搭建本地开发环境：前置条件、快速启动、Provider 模式配置、各服务独立开发命令、常见问题 |

---

## 架构设计

| 文档 | 简介 |
| --- | --- |
| [行程真实性与旅行骨架](architecture/行程真实性与旅行骨架.md) | 规划领域权威口径："完整、真实、可执行"的定义、目标领域模型（Trip Skeleton / Anchor / 住宿状态 / Meal Window / Visit Duration）、骨架场景规则、硬校验与体验评估分工 |
| [规划工作流](architecture/规划工作流.md) | 异步规划的 10 个标准阶段、目标 pipeline（骨架→验证→评估）、当前/目标差异、修复循环、失败场景、局部重规划、协作式取消、城市情报刷新 |
| [行程版本与编辑模型](architecture/行程版本与编辑模型.md) | 不可变版本设计、编辑草稿与确认流程、幂等键机制、Typed Nodes 与骨架到版本转换、编辑后重新验证、Transit 端点匹配、回滚、版本差异、PlanEvaluation 绑定与并发控制 |
| [事件契约](architecture/事件契约.md) | 消息 Schema 版本策略（completion v8 当前基线、failure v2）、进度阶段与完成事件边界、REST API 资源分组与错误码、SSE 协议、跨语言兼容规则 |
| [Provider 集成](architecture/Provider集成.md) | 高德地图（AMap）服务端/浏览器双 Key、QWeather 天气与归因、Demo Provider、三种 Provider 模式、错误分类与重试策略、降级白名单、数据来源标记 |

---

## 开发与测试

| 文档 | 简介 |
| --- | --- |
| [本地开发指南](development/本地开发指南.md) | Docker Compose 开发环境搭建、各技术栈独立开发命令、Provider 模式选择、环境变量配置、Windows 特定问题处理 |
| [测试策略](development/测试策略.md) | Java/Python/Web 三层测试命令与门禁、覆盖率要求、真实 Provider 测试开关、浏览器 E2E 场景、GitHub Actions 五项 CI 说明 |
| [代码规范](development/代码规范.md) | Java（Spring Boot / MyBatis / Flyway）、Python（FastAPI / Pydantic / Ruff）、TypeScript/Vue 3 的编码约定、跨语言契约规则、Git 提交约定 |

---

## 部署与运维

| 文档 | 简介 |
| --- | --- |
| [部署指南](operations/部署指南.md) | Docker Compose 生产拓扑、完整环境变量参考、不可变镜像 digest 引用、启动命令、Staging 验收运行手册（S-01 至 S-13）、备份恢复、回滚 |
| [可观测性](operations/可观测性.md) | 健康检查端点、Prometheus 业务与基础设施指标、日志规范（关键字段、禁止记录内容）、诊断入口、建议告警规则 |
| [故障排查](operations/故障排查.md) | Docker Compose 启动失败、知识初始化失败、规划任务失败、SSE 断连、编辑冲突、Provider 验收失败、队列积压、数据库连接等常见问题的排查步骤 |

---

## 项目管理

| 文档 | 简介 |
| --- | --- |
| [项目路线图](product/项目路线图.md) | 当前版本状态、能力状态矩阵、旅行真实性里程碑、执行记录与当前风险 |
| [ADR 索引](adr/README.md) | ADR-001 至 ADR-014 摘要索引、PlanEvaluation 策略和 Provider 降级策略两份详细 ADR、变更原则与待复核决策 |

---

## 历史归档

| 文档 | 简介 |
| --- | --- |
| [历史归档](archive/README.md) | 原始归档文档（预 PR #27）的完整索引，包含 V1、V2.0、V2.5 的历史设计文档、验收证据和审查报告 |
| [历史审计索引](archive/audits/README.md) | 7 篇 PR #27 关联审计报告的索引，记录每次审计的范围、主要结论和对应提交 |
| [阶段报告](archive/phase-reports/README.md) | 一次性执行阶段报告索引（状态评估、交付基线、验证报告、执行计划） |
| [已废弃文档](archive/deprecated/README.md) | 被新文档体系替代的旧版活跃文档索引，含替代关系对照表 |

---

## 消息契约

| 文档 | 简介 |
| --- | --- |
| [消息契约状态](../contracts/messaging/README.md) | 活跃规划契约（completion v8 当前运行时、completion v6 历史只读、failure v2）、共享 fixture 说明 |
| [遗留契约说明](../contracts/messaging/legacy/README.md) | 已废弃的 v1–v4 Schema 历史参考 |

---

## 城市知识

| 文档 | 简介 |
| --- | --- |
| [陈家祠](../knowledge/guangzhou/chen-clan-museum.md) | 广州陈家祠（广东民间工艺博物馆）官方来源知识，含建筑装饰事实与参观建议 |
| [沙面历史](../knowledge/guangzhou/shamian-history.md) | 广州沙面历史街区官方来源知识，描述保护性滨水历史风貌区和步行游览建议 |
| [西关城市漫步](../knowledge/guangzhou/xiguan-citywalk.md) | 广州西关文化漫步路线骨架（陈家祠→永庆坊→沙面→白鹅潭），组合式路线主题知识 |

---

## 维护规则

- 当前能力只写入顶层活跃文档；归档文档不再更新当前状态。
- 新功能改变用户范围时，更新产品概述和路线图。
- 新功能改变服务边界、数据模型、规划流程或可靠性时，更新系统架构。
- 新增或修改 HTTP、消息、SSE、错误码或幂等语义时，更新事件契约。
- 部署变量、启动方式、测试门禁、备份恢复或发布条件变化时，更新部署指南。
- 只有长期有效且会约束后续实现的取舍才进入 ADR。
- 一次性的审查、验收和阶段报告放入历史归档。
