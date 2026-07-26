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
| `STRUCTURED_MODEL_ENDPOINT` | 可选的 HTTPS 结构化输出端点；留空时规则抽取继续运行 |
| `STRUCTURED_MODEL_API_KEY` | 仅注入 Agent API 的模型密钥，不进入 Web 或日志 |
| `STRUCTURED_MODEL_NAME` | 模型 Provider 上支持严格 JSON Schema 的模型名 |
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

### 高德 Web JS 底图验收

`VITE_AMAP_WEB_JS_KEY` 必须是“Web 端（JS API）”Key；`VITE_AMAP_SECURITY_CODE` 必须是
同一高德应用下与该 Key 匹配的安全密钥。代码只能校验两者是否同时存在，不能代替控制台
授权。

高德控制台需要人工完成：

1. 为本地验收加入实际访问域名，例如 `127.0.0.1` 与 `localhost`；端口按高德控制台
   当前规则填写。
2. 为生产加入最终 HTTPS 域名，不使用宽泛通配符。
3. 确认安全密钥与 Web JS Key 属于同一应用，保存后重新构建 Web 镜像。
4. 浏览器打开结果页，网络面板确认高德基础图块请求成功；页面在地图 `complete` 前应
   保持路线概览，成功后才出现 Marker/Polyline。

SDK 脚本加载成功不等于底图可用。8 秒内未收到地图 `complete`，或初始化/覆盖物失败时，
页面必须显示诊断提示并保留路线概览。生产 CSP 需要允许 `webapi.amap.com`、
`*.amap.com` 与高德实际图块域名；具体白名单见 `apps/web/nginx.conf`。

### V1.3 事实模型配置

规则抽取始终启用。结构化模型抽取是可降级增强，使用独立的模型 Provider 配置、有限输入、
超时和重试；缺少 Key 时记录 `SKIPPED`，不导致攻略导入失败，也不会把 Demo 数据当成
Provider 成功。任何模型密钥只注入 Python Agent API，不进入 Web 构建参数或日志。
默认限制为 30,000 字符、8 秒超时、最多重试 1 次；分别由
`STRUCTURED_MODEL_MAX_INPUT_CHARACTERS`、`STRUCTURED_MODEL_TIMEOUT_SECONDS` 和
`STRUCTURED_MODEL_MAX_RETRIES` 调整。端点必须是 HTTPS 且兼容严格
`response_format=json_schema`；若 Provider 不兼容会记录 `FAILED` 并只采用规则结果。

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
