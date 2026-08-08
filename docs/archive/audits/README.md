# 历史审计索引

- 文档状态：生效中
- 最后更新：2026-08-08

本目录保存 TripPilot 项目的历史审计报告。审计报告用于追溯设计验证、代码审查和发布候选评估过程，不再作为当前实现依据。

## 审计列表

| 编号 | 日期 | 审计范围 | 主要结论 | 当前状态 | 对应 PR/提交 |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-08-02 | PR #27 第 1–2 轮集成审查 | 修复 5 个 Important；阶段 0–3 通过，阶段 4 阻塞 | 已归档 | `56eee3c..4161b96` |
| 2 | 2026-08-02 | 第 3–4 轮（Web 日期稳健性、staging 准备） | 修复 5 个 Important；新增 release tooling、digest 契约 | 已归档 | `b60f36a..8c62119` |
| 3 | 2026-08-04 | 远端推送与 Draft PR #27 范围验证 | PR 范围确认，无密钥泄露；CI 发现 gitleaks 误报 | 已归档 | `9afb73c` |
| 4 | 2026-08-04 | 远端 CI 修复 | gitleaks 误报通过精确 fingerprint 修复；五项 CI 全部通过 | 已归档 | `4aa1964` |
| 5 | 2026-08-04 | Staging 预检与 Provider 合规 | QWeather 归因链接修复；S-01 至 S-13 全部 BLOCKED | 已归档 | `88028aa` |
| — | 2026-08-04 | 当时版本产品完整度 | Demo 体验问题（must-visit 失败、空行程 97 分等） | 已归档，未关闭发现已迁入当前路线图 | `6c663dc` |
| — | 2026-08-04 | 当时全项目工程扫描 | 7 Important + 15 Normal + 8 Minor；`LOCAL_CODE_HEALTHY + REMOTE_CI_VERIFIED` | 已归档，未关闭发现已迁入当前路线图 | `6c663dc` |

## 审计文件

| 文件 | 说明 |
| --- | --- |
| [roadmap-audit-2026-08-02-1.md](roadmap-audit-2026-08-02-1.md) | 第 1 次审计：集成轮次 1–2 |
| [roadmap-audit-2026-08-02-2.md](roadmap-audit-2026-08-02-2.md) | 第 2 次审计：staging 准备、不可变镜像契约 |
| [roadmap-audit-2026-08-04-3.md](roadmap-audit-2026-08-04-3.md) | 第 3 次审计：远端推送、Draft PR 范围 |
| [roadmap-audit-2026-08-04-4.md](roadmap-audit-2026-08-04-4.md) | 第 4 次审计：CI 修复、gitleaks 误报 |
| [roadmap-audit-2026-08-04-5.md](roadmap-audit-2026-08-04-5.md) | 第 5 次审计：staging 预检、QWeather 合规 |
| [current-version-product-completeness-2026-08-04.md](current-version-product-completeness-2026-08-04.md) | 产品完整度验收（当前有效） |
| [full-project-scan-2026-08-04.md](full-project-scan-2026-08-04.md) | 全项目工程扫描（当前有效） |

## 使用规则

- 审计报告中的当前有效发现已迁移到对应架构、测试、部署或路线图文档中。
- 需要追溯特定历史审查的详细过程时，阅读对应审计文件。
- 当前活跃的代码和配置状态以 `docs/` 顶层维护文档为准。
