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
| `PROVIDER_MODE` | `DEMO_ONLY`、`REAL_ONLY` 或 `REAL_WITH_EXPLICIT_FALLBACK`；生产默认严格真实 |
| `DEMO_MODE` | 旧配置兼容：`true -> DEMO_ONLY`、`false -> REAL_ONLY`；与新值冲突时启动失败 |
| `PROVIDER_MAX_ATTEMPTS` | 规划 Provider 最大尝试次数，默认 3 |
| `PROVIDER_RETRY_BASE_DELAY_SECONDS` | 规划 Provider 重试初始延迟 |
| `PROVIDER_RETRY_MAX_DELAY_SECONDS` | 规划 Provider 单次最大重试延迟 |
| `PROVIDER_RETRY_MAX_ELAPSED_SECONDS` | 规划 Provider 最大累计重试时间 |
| `PROVIDER_RETRY_JITTER_RATIO` | 规划 Provider 重试抖动比例 |
| `PROVIDER_FALLBACK_CATEGORIES` | JSON 数组；仅可显式增加 `QUOTA_EXCEEDED`、`MALFORMED_RESPONSE`，生产默认 `[]` |
| `CITY_INTELLIGENCE_PLANNING_WAIT_TIMEOUT` | 规划前 best-effort 等待城市情报的上限，默认 `PT2S`；非正值用于不启动异步消费者的测试环境 |
| `REFRESH_COOKIE_SECURE` | 生产 HTTPS 必须为 `true` |

真实 Provider 相关变量：

| 变量 | 说明 |
| --- | --- |
| `AMAP_WEB_SERVICE_KEY` | 服务端 POI、路线、天气等 Web Service Key |
| `QWEATHER_API_KEY` | 服务端 QWeather Key；只用于城市天气情报 |
| `QWEATHER_API_HOST` | QWeather 控制台分配的专用 HTTPS Host；必须与 Key 成对配置 |
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

- `PROVIDER_MODE=REAL_ONLY`；不要在 production 使用 `REAL_WITH_EXPLICIT_FALLBACK`。
- 服务端和浏览器高德 Key 分离。
- QWeather Key 和专用 Host 成对配置，并在有效套餐窗口验证当前、预报和近期历史天气。
- 上述 `PROVIDER_RETRY_*` 和 `PROVIDER_FALLBACK_CATEGORIES` 约束规划 Provider；QWeather 城市情报失败使用独立的显式降级记录，不能误报为规划 Provider fallback。
- 规划前刷新是有界 best-effort 增强，不阻断 Demo、远期行程或 Provider 暂时失败。超时/运行中会写入 `CITY_INTELLIGENCE_REFRESH_PENDING`，成功但行程日期没有可用天气会写入 `CITY_INTELLIGENCE_WEATHER_UNAVAILABLE`；planning context 标为 stale 并保留诊断，不能把旧或空天气伪装为本轮新鲜数据。
- Web JS Key、安全密钥和域名白名单属于同一高德应用。
- 最终浏览器域名能加载真实底图，缺 Key 或失败时页面显示降级视图而非空白。
- Provider Key、模型 Key、Cookie 和 Token 不进入日志。

Demo 模式通过不代表真实 Provider 通过。

### 本轮 RC 证据

2026-07-31 的历史 RC 使用 `DEMO_MODE=false` 和生产 Compose 文件；当前兼容规则将该值解析为 `REAL_ONLY`。独立项目 `trip-pilot-rc` 使用独立网络/卷、Web `18080` 和 Prometheus `19090` 冷启动，没有停止或删除既有 `trip-pilot-prod` 数据。启动命令为：

```powershell
docker compose --env-file .env -p trip-pilot-rc -f compose.prod.yaml up -d --build --wait --wait-timeout 300
docker compose --env-file .env -p trip-pilot-rc -f compose.prod.yaml ps
```

本轮结果：PostgreSQL、RabbitMQ、Redis、Agent API、Worker、Java、Web 和 Prometheus 均健康，`knowledge-init` 退出码为 0；开发/生产 Compose 的 `config -q` 均通过。真实验收必须显式设置 `RUN_REAL_PROVIDER_TESTS=true`，普通 Python 测试不会消耗 AMap 配额。

### 2026-08-02 组合候选证据

PlanEvaluation 与天气/城市情报的组合代码基线 `093aef1` 已完成本地生产编排复验。五类生产镜像构建成功；隔离项目 `trip-pilot-combined-gate` 使用 `PROVIDER_MODE=DEMO_ONLY`、假本地密钥、独立端口、网络和卷冷启动，PostgreSQL、Redis、RabbitMQ、Agent API、Worker、Java、Web 和 Prometheus 均健康，`knowledge-init` 退出码为 0，Web 与 `/api/health` 返回 HTTP 200，验收后独立资源已拆除。

该证据证明组合制品可在本地生产拓扑启动，不证明真实 Provider 或生产环境可用。staging 必须使用不可变镜像摘要与 `REAL_ONLY`，并另行记录 HTTPS、Secure Cookie、QWeather Key/专用 Host、AMap 服务端 Key、Web JS 最终域名白名单、负向凭据/限流、日志脱敏、告警、备份恢复、回滚和 soak 结果。

### 模式迁移、回退与日志

本地无凭据开发使用 `PROVIDER_MODE=DEMO_ONLY`；staging/production 使用 `REAL_ONLY`。只有内部演示或容错验证才使用 `REAL_WITH_EXPLICIT_FALLBACK`，且 fallback category 白名单应保持最小。回滚配置时应切换为明确的 `DEMO_ONLY` 或回退上一镜像，不能恢复“真实失败静默 Demo 成功”的旧语义。

AMap 规划返回的 itinerary、Activity 和 Transit 均应检查 `provider` 与 `estimated` 字段。显式回退日志使用 `planning_provider_fallback`，失败事件使用 schema v2，并携带安全 category、operation、retry count 和关联 ID。日志只允许出现关联 ID、安全 infocode 与错误分类，不允许出现 `AMAP_WEB_SERVICE_KEY`、JWT、Cookie、Authorization、完整 Provider 响应或堆栈。

成功验收还必须读取 completion v6 的可选 `providerProvenance`。纯真实要求 `REAL_ONLY + AMAP + fallback=false`；mixed/整单 fallback 必须有结构化 operation。历史或兼容 replan 缺失 provenance 时只能记为“未记录”，不能根据行程顶层 provider 推断本次 mode。pytest 临时输出位于各模块 `output/pytest-*`，由递归 `.gitignore` 规则排除但不自动删除。

启动配置矩阵必须覆盖：Demo 无 Key 通过、严格真实有 Key 通过、严格真实无 Key 拒绝、显式 fallback 有 Key 通过、非法 mode 拒绝、新旧配置冲突拒绝。

## 测试门禁

```powershell
# Java
mvn --batch-mode -pl apps/travel-server clean verify

# Python
Set-Location apps/agent-service
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run python benchmarks/run_plan_evaluation.py

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

本轮实际使用 PostgreSQL 16.9 的自定义格式备份：

```powershell
docker exec trip-pilot-rc-postgres-1 pg_dump -U trip_pilot -d trip_pilot -Fc -f /tmp/trip-pilot-rc-20260731.dump
docker cp trip-pilot-rc-postgres-1:/tmp/trip-pilot-rc-20260731.dump output/backups/trip-pilot-rc-20260731.dump
```

备份文件为 209287 字节，恢复到临时 `trip_pilot_restore_rc` 后 28 张业务表逐表计数一致，Flyway V27、外键验证和恢复 API 读取均通过。验证结束后只删除了这个本轮创建的临时数据库和 API 容器；dump 文件保留在工作区 `output/backups/`，不应提交 Git。

## 故障恢复检查

- RabbitMQ 重启后四条规划队列恢复 durable 配置、各有消费者且 ready/unacked 为 0。
- Worker 在 `TASK_ACCEPTED` 后停止时，`planning.create.queue` 保留 `ready=1`；Worker 恢复后任务成功且只生成一个 AMAP 版本。
- Java Consumer 停止时，`planning.completed.queue` 保留 `ready=1`；Java 恢复后继续持久化。
- Redis 清空并重启只清除缓存；PostgreSQL Trip、任务、版本、Activity、Transit、事件和 Outbox 计数不变。
- 整栈重启后全部长期服务健康，知识初始化退出码为 0。

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
