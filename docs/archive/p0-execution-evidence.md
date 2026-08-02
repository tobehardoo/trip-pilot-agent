# P0 执行记录与剩余门禁

日期：2026-07-30  
状态：仓库内 P0 工作已完成；真实环境 P0 验收待外部前置条件

## 已完成

### 配置与 CI 门禁

- `INTERNAL_DIAGNOSTICS_TOKEN` 已写入 `.env.example`，并明确要求与
  `AGENT_INTERNAL_TOKEN` 分离、独立轮换。
- 生产 Compose 中 `travel-server` 的诊断 Token 已改为必填，避免生产环境
  静默回退到 Agent 内部 Token。
- GitHub Actions Web 作业新增 `pnpm typecheck`。
- GitHub Actions 基础设施作业新增完整生产 Compose 的启动、等待健康状态、
  HTTP 冒烟检查和 `always()` 清理步骤。

### 可复现验证

| 验证项 | 结果 |
| --- | --- |
| `.env.example` 生产 Compose 解析 | 通过 |
| 本地 `.env` 生产 Compose 解析 | 通过 |
| 本地完整 Compose `up -d --wait` | 通过；全部长期服务 healthy，知识初始化容器成功退出 |
| Web HTTP 冒烟检查 | HTTP 200 |
| 备份与隔离恢复 | 通过；恢复库包含 38 张业务/知识表，`business.trip` 与 `business.itinerary_version` 均存在 |

备份恢复演练使用了新建隔离数据库，不修改运行中的业务数据库；恢复验证后已删除
临时数据库。临时备份文件的删除被运行环境安全策略拒绝，因此该文件只能由持有
本机权限的操作者确认后手动删除；它不在仓库中，也未提交。

## 真实环境前置条件

以下事项无法由仓库代码或本机 Compose 代替，完成后才能将 P0 标记为完全验收：

1. 可访问的预生产 HTTPS 域名、反向代理/证书终止位置和部署责任人。
2. 预生产与生产独立的 PostgreSQL、Redis、RabbitMQ、镜像仓库和密钥管理位置。
3. 独立的 AMap 服务端 Web Service Key，以及最终浏览器域名的 Web JS Key、安全
   密钥、配额和白名单配置。
4. 告警接收渠道、值班责任人、规划失败率/队列积压/Provider 失败率的阈值。
5. 在预生产完成真实 POI、路线、地图、短暂失败、永久失败、密钥轮换、发布回滚
   和备份恢复演练的脱敏证据。

## 下一执行点

在以上前置条件到位前，后续工作保持在 P0，不进入 P1 的结构重构或 P2 的产品扩展。
前置条件确认后，按 [P0–P2 执行规划](post-v2.5-p0-p2-execution-plan.md) 的 P0.2、
P0.3 和 P0.4 场景执行真实环境验收。
