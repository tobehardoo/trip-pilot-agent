# 运行与运维

- 文档状态：生效中（基于当前代码）
- 相关文档：[系统架构](architecture.md) · [开发指南](development.md)

## 1. Compose 服务矩阵（compose.prod.yaml，9 个服务）

| 服务 | 镜像/构建 | 端口（均绑定 127.0.0.1） | 健康检查 | 依赖 |
|---|---|---|---|---|
| postgres | 自建 pgvector 镜像（infra/docker/postgres） | 内部 5432 | pg_isready | — |
| redis | redis:7.4-alpine（AOF + 密码） | 内部 6379 | redis-cli ping | — |
| rabbitmq | rabbitmq:4.1-management-alpine | 内部 5672 / 15672 | rabbitmq-diagnostics ping | — |
| travel-server | apps/travel-server/Dockerfile | 8080 | actuator health UP | postgres、rabbitmq、agent-api healthy |
| agent-service | apps/agent-service/Dockerfile（worker 进程） | 无对外端口 | 进程 cmdline 校验 | postgres/redis/rabbitmq healthy，knowledge-init 完成 |
| agent-api | 同 agent-service 镜像（uvicorn :8090） | 仅内部网络 | /health | — |
| knowledge-init | 同 agent-service 镜像（一次性迁移+导入） | — | 跑完即退（restart: no） | postgres healthy |
| web | apps/web/Dockerfile（nginx 反代 /api） | 8080（WEB_PORT 可调） | 首页含 app 挂载点 | travel-server healthy |
| prometheus | infra/monitoring/Dockerfile | 9090（PROMETHEUS_PORT 可调） | /-/healthy | travel-server healthy |

网络为固定子网（`APP_NETWORK_SUBNET`，默认 172.30.250.0/24），web 容器经 `TRUSTED_PROXY_CIDR` 声明可信代理。

## 2. 启动与停止

```bash
# 启动（--wait 会等所有健康检查通过）
docker compose -f compose.prod.yaml --env-file .env up -d --build --wait --wait-timeout 240

# 停止
docker compose -f compose.prod.yaml down

# 停止并删除数据卷
docker compose -f compose.prod.yaml down -v
```

## 3. 环境变量

**必需**（缺失时 compose 拒绝启动，`${VAR:?}` 强制）：`POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`RABBITMQ_PASSWORD`、`JWT_SECRET`、`AGENT_INTERNAL_TOKEN`、`INTERNAL_DIAGNOSTICS_TOKEN`——六者必须互不相同。

**行为开关**：

| 变量 | 默认 | 说明 |
|---|---|---|
| `PROVIDER_MODE` | `DEMO_ONLY` | `REAL_ONLY` / `REAL_WITH_EXPLICIT_FALLBACK` 需显式设置；REAL_ONLY 要求 `AMAP_WEB_SERVICE_KEY`；认证/权限类 Provider 错误永不回退 Demo |
| `PLANNING_DAY_SCHEDULER` | `GREEDY` | `CPSAT`（失败回退贪心）/ `SHADOW`（贪心权威、CP-SAT 对照） |
| `PLANNING_CPSAT_TIME_LIMIT_SECONDS` | 5 | CP-SAT 单日求解时限 |
| `STRUCTURED_MODEL_ENDPOINT/API_KEY/NAME` | 空 | 配置后 Agent 决策器从确定性升级为 LLM 结构化输出 |
| `OCR_MODEL_ENDPOINT/API_KEY/NAME` | 空 | 配置后启用截图 OCR 导入 |
| `OUTBOX_PUBLISHER_ENABLED` / `EVENT_CONSUMER_ENABLED` | true | 便于本地单侧调试隔离 |

**真实数据 Provider**：`AMAP_WEB_SERVICE_KEY`（高德 Web 服务）、`QWEATHER_API_KEY`（和风天气）、`VITE_AMAP_WEB_JS_KEY` + `VITE_AMAP_SECURITY_CODE`（前端地图，构建期注入 web 镜像）、`DASHSCOPE_API_KEY`（知识库真实 embedding）。

完整清单以 `.env.example` 为准。

## 4. 健康与监控

- 应用健康：`GET /api/health`（travel-server，返回 `status=UP`）；`GET :8090/health`（agent-api，内部）。
- 指标：travel-server 暴露 actuator + micrometer-prometheus；Prometheus 抓取配置在 `infra/monitoring/`，Web UI 在 <http://127.0.0.1:9090>。
- 死信与轨迹：消费失败进死信队列；Agent 轨迹落 `agent_run` / `agent_step` 表，可经内部诊断端点查询（需 `INTERNAL_DIAGNOSTICS_TOKEN`）。

## 5. 备份与冒烟

```bash
python scripts/postgres_backup.py        # Postgres 备份
python scripts/smoke_test.py             # 真实链路冒烟
python scripts/validate_staging_env.py   # staging 环境变量校验
python scripts/check_compose_defaults.py # compose 默认值安全校验
```

## 6. 安全清单

- 对外部署前**必须**删除或改掉预置演示账号：`DELETE FROM business.user_account WHERE email='admin@admin.com';`
- 生产部署时把镜像引用固定为 digest（CI 的 infrastructure job 会强制校验 9 个镜像全部 `@sha256:`）。
- JWT_SECRET 至少 32 字节；`REFRESH_COOKIE_SECURE` 生产保持 true。
- web 容器的 `TRUSTED_PROXY_CIDR` 按实际代理网段调整，不要放行 0.0.0.0/0。
- 仓库内置 gitleaks 扫描与追踪密钥文件拒绝（CI repository-safety job）；`.gitleaksignore` 记录已确认的历史豁免。
- 端口默认全部绑定 127.0.0.1，公网暴露请前置带 TLS 的反向代理。
