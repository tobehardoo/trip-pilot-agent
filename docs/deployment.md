# 部署与运维

TripPilot 使用 Docker Compose 作为默认运行方式。当前生产拓扑一次启动 PostgreSQL、Redis、RabbitMQ、Spring Boot、Agent API、Worker、Web、Prometheus 和知识初始化任务。

## 环境要求

- Docker Desktop 或 Docker Engine
- Docker Compose v2
- 建议至少 8 GB 可用内存
- 生产环境必须具备 HTTPS 终止、密钥管理和日志留存策略

## 最小配置

从 `.env.example` 复制 `.env`，至少替换：

| 变量 | 说明 |
| --- | --- |
| `POSTGRES_PASSWORD` | PostgreSQL 密码 |
| `REDIS_PASSWORD` | Redis 密码 |
| `RABBITMQ_PASSWORD` | RabbitMQ 密码 |
| `JWT_SECRET` | JWT 签名密钥，至少 32 字节随机值 |
| `AGENT_INTERNAL_TOKEN` | Java 调用 Agent API 的内部令牌 |
| `INTERNAL_DIAGNOSTICS_TOKEN` | 受保护诊断入口令牌 |
| `DEMO_MODE` | `true` 时使用 Demo Provider |
| `REFRESH_COOKIE_SECURE` | 生产 HTTPS 必须为 `true` |

真实 Provider 相关变量：

| 变量 | 说明 |
| --- | --- |
| `AMAP_WEB_SERVICE_KEY` | 服务端 POI、路线、天气等 Web Service Key |
| `VITE_AMAP_WEB_JS_KEY` | 浏览器高德 Web JS Key |
| `VITE_AMAP_SECURITY_CODE` | 浏览器高德安全密钥 |
| `KNOWLEDGE_EMBEDDING_PROVIDER` | 可选语义检索 Provider |
| `STRUCTURED_MODEL_ENDPOINT` | 可选结构化抽取模型端点 |
| `STRUCTURED_MODEL_API_KEY` | 可选结构化模型密钥 |

## 启动

```powershell
docker compose -f compose.prod.yaml --env-file .env build
docker compose -f compose.prod.yaml --env-file .env up -d
docker compose -f compose.prod.yaml --env-file .env ps
```

`knowledge-init` 会在 Worker 启动前执行迁移和知识导入。服务健康后访问：

- Web：<http://127.0.0.1:8080>
- Java 健康检查：<http://127.0.0.1:8080/api/health>
- Prometheus：<http://127.0.0.1:9090>

## 真实 Provider 验收

生产或预生产发布前必须确认：

- `DEMO_MODE=false`。
- 服务端和浏览器高德 Key 分离。
- Web JS Key、安全密钥和域名白名单属于同一高德应用。
- 最终浏览器域名能加载真实底图，缺 Key 或失败时页面显示降级视图而非空白。
- Provider Key、模型 Key、Cookie 和 Token 不进入日志。

Demo 模式通过不代表真实 Provider 通过。

## 测试门禁

```powershell
# Java
mvn --batch-mode -pl apps/travel-server clean verify

# Python
Set-Location apps/agent-service
uv sync --extra dev
uv run pytest
uv run ruff check .

# Web
Set-Location ../web
corepack enable
pnpm install --frozen-lockfile
pnpm test
pnpm typecheck
pnpm build
```

发布证据还应包含：

- Flyway 从历史版本升级到最新版本。
- JSON Schema 与 Java/Python/TypeScript 序列化校验。
- 浏览器 E2E 用户旅程。
- 生产 Compose 健康检查。
- PDF 渲染验证和分享隔离回归。
- 敏感信息扫描和日志脱敏复核。

## 备份与恢复

- PostgreSQL 数据使用 Docker Volume 保存。
- 备份前记录镜像标签、Git SHA、迁移版本和 `.env` 关键配置摘要。
- 恢复先在独立数据库验证，再进入维护模式切换。
- 数据库迁移只向前；应用回滚不执行反向迁移。

## 回滚

- 应用镜像使用不可变 Git SHA 或发布标签。
- 回滚只切换上一组镜像和配置。
- 数据恢复只能使用已验证备份。
- 诊断重试必须幂等，不能重复创建行程版本或绕过所有权校验。

## 停止

```powershell
docker compose -f compose.prod.yaml --env-file .env down
```

需要删除本地演示数据时：

```powershell
docker compose -f compose.prod.yaml --env-file .env down -v
```

## 历史详稿

- [原部署详稿](archive/deployment.md)
- [V2.0 发布证据原文](archive/v2-release-evidence.md)
