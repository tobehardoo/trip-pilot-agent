# V1.2 发布验收清单

> 基线日期：2026-07-26
>
> 发布分支：`codex/complete-v1`
>
> 目标：把已实现的单城市规划、攻略证据、行程编辑和局部重规划交付为可复现的 V1.2。

## 范围

本次发布包含 `TP-REQ-001` 至 `TP-REQ-004`。`TP-REQ-005` 至 `TP-REQ-018`
继续保留在[需求基线](27-product-completeness-and-requirements-baseline.md)，不得标记为
已完成，也不作为 V1.2 的发布阻塞项。

## 必须通过

- [x] README、API、架构、数据库和部署文档与代码一致，仓库内链接有效。
- [x] Java 非容器测试通过（42 项）。
- [ ] Java Testcontainers 与 JaCoCo 门禁在 GitHub Actions 通过。
- [x] Python 全量测试（378 通过、34 环境跳过）与 Ruff 通过。
- [x] Web 单元测试（73 项）、覆盖率、类型检查和生产构建通过。
- [x] 活跃 JSON Schema 可被自动解析，失败事件模型样例通过契约校验。
- [x] Playwright 浏览器烟雾测试覆盖登录态恢复、旅行工作台和行程编辑入口（2 项）。
- [x] `docker compose config` 与生产 Compose 配置校验通过。
- [x] 独立代码审查不存在 Critical 或 Important 问题。
- [x] `git diff --check`、敏感文件名检查通过。
- [x] 变更已提交到独立分支、推送 GitHub，并创建 Draft PR
      [#23](https://github.com/tobehardoo/trip-pilot-agent/pull/23)。

## 环境受限项

依赖 Docker 的 Testcontainers、完整 Compose 启动和跨服务浏览器链路，需要 Docker
Engine 可用。若发布机器无法运行 Docker，这些项目必须在 GitHub Actions 中形成通过证据，
本地报告需明确记录“未运行”，不得写成“通过”。

## 完成定义

清单全部有可复现命令或 CI 证据后，V1.2 才可标记为“发布候选”。生产上线还要求：

1. 使用真实 HTTPS 域名部署；
2. 使用部署平台密钥管理，不提交 `.env`；
3. 验证数据库备份恢复；
4. 观察一个完整规划任务的日志、指标和失败降级。
