# 部署

## 为什么用 Docker Compose 而不是 Kubernetes

V1 只有两个核心服务（Java + Python）加三个中间件（PostgreSQL、Redis、RabbitMQ）。Docker Compose 对这个规模来说是最合理的：

- 一个 `compose.prod.yaml` 文件描述全部拓扑
- 一条命令完成构建和启动
- 不需要学习 Kubernetes 的 Pod、Service、Ingress、ConfigMap 等概念
- 资源开销小——K8s 控制平面本身消耗 ~2 GB 内存

当部署规模证明有必要时才迁移到 Kubernetes——例如需要横向扩展 Python Worker 到 5+ 个实例、需要滚动更新零停机、需要跨多台机器调度。

## Compose 拓扑

`compose.prod.yaml` 当前没有 Profile。一次启动会运行 PostgreSQL、Redis、RabbitMQ、
Java 业务服务、Python Worker、内部攻略 API、知识初始化任务、Nginx Web 与 Prometheus。
仓库当前不包含 Grafana 或 Jaeger，`traceId` 仅用于跨服务日志关联。

前端开发期间可以在宿主机直接运行 Vite，无需容器化；若只需服务端联调，可通过
`docker compose up` 明确列出要启动的服务。

## 快速部署

### 环境要求

- Docker Desktop 或 Docker Engine
- Docker Compose v2
- 至少 8 GB 可用内存

### 步骤

```bash
# 1. 准备配置
cp .env.example .env
# 编辑 .env：替换数据库密码、Redis 密码、RabbitMQ 密码、JWT 密钥

# 2. 构建并启动
docker compose -f compose.prod.yaml --env-file .env build
docker compose -f compose.prod.yaml --env-file .env up -d

# 3. 健康检查
curl http://127.0.0.1:8080/api/health

# 4. 访问
# Web: http://127.0.0.1:8080
# Prometheus: http://127.0.0.1:9090
```

`knowledge-init` 容器在 Worker 启动前自动执行数据库迁移和广州语料导入。

### 环境变量要点

| 变量 | 说明 |
|---|---|
| `POSTGRES_PASSWORD` | 数据库密码 |
| `REDIS_PASSWORD` | Redis 密码 |
| `RABBITMQ_PASSWORD` | RabbitMQ 密码 |
| `JWT_SECRET` | JWT 签名密钥，至少 32 字节随机值 |
| `AGENT_INTERNAL_TOKEN` | Java 调用 Python 攻略 API 的内部令牌 |
| `DEMO_MODE` | `true` 时不依赖高德 Key，使用 Demo Provider |
| `REFRESH_COOKIE_SECURE` | 生产 HTTPS 环境必须为 `true`；本机 HTTP 可设 `false` |

### 接入真实 Provider

```dotenv
DEMO_MODE=false
AMAP_WEB_SERVICE_KEY=your-server-side-amap-key
VITE_AMAP_WEB_JS_KEY=your-browser-amap-key
VITE_AMAP_SECURITY_CODE=your-browser-security-code
```

`AMAP_WEB_SERVICE_KEY` 同时注入规划 Worker 与内部 Agent API：前者用于 POI/路线，后者
用于城市天气和景点情报同步。缺失时公开正文识别仍可用，但城市情报同步会明确返回 502，
不会伪装为实时数据。

服务端 Key 和浏览器 Key 必须分开，避免把 Web Service Key 暴露到前端。

## 数据库备份

```bash
# 备份
python scripts/postgres_backup.py backup backups/trip-pilot.dump

# 恢复（先在独立数据库中验证）
docker compose -f compose.prod.yaml exec -T postgres \
  createdb -U trip_pilot trip_pilot_restore
python scripts/postgres_backup.py restore backups/trip-pilot.dump \
  --database trip_pilot_restore
```

## 回滚

- 应用镜像以不可变 Git SHA 标记；回滚只切回上一镜像
- 数据库变更必须向前兼容；不回写数据库迁移
- 需要数据恢复时进入维护模式并使用已验证备份

## 进一步阅读

- [系统架构设计](architecture.md) — 部署拓扑和服务依赖关系
- [数据库设计](database.md) — 迁移策略和备份恢复的数据库层面说明
- [产品路线图](roadmap.md) — 当前版本能力和后续计划
