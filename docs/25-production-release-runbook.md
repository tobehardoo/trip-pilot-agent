# V1 生产发布与恢复手册

## 发布前

1. 从 `.env.example` 创建仅存在于服务器的 `.env`，把 PostgreSQL、Redis、RabbitMQ 和 JWT 值替换为独立随机值；`JWT_SECRET` 至少 32 字节，并把 `IMAGE_TAG` 设置为本次不可变 Git SHA。
2. 公网必须由 HTTPS 反向代理终止 TLS，并保持 `REFRESH_COOKIE_SECURE=true`。只有本机纯 HTTP 验收可临时设为 `false`。
3. 运行 Java、Python、Web 全量测试、覆盖率门禁、Compose 配置校验和镜像构建。
4. 真实模式必须提供高德 Key，并先在固定广州评测集和供应商配额内验收；无凭据时只能发布明确标记的 Demo 模式。
5. Web 地图凭据由 `VITE_AMAP_WEB_JS_KEY` 和 `VITE_AMAP_SECURITY_CODE` 在镜像构建时注入；它们是浏览器可见凭据，绝不能复用服务端 Web Service Key。
6. Web 默认只绑定宿主机 `127.0.0.1`；TLS 边缘代理必须通过本机端口转发。`TRUSTED_PROXY_CIDR` 默认只信任固定生产 Docker 网关 `172.30.250.1/32`，修改网络时必须同步收窄为实际代理地址，禁止使用整段 RFC1918 或信任公网来源提供的 `X-Forwarded-For`。

## 启动与验收

```powershell
docker compose -f compose.prod.yaml --env-file .env build
docker compose -f compose.prod.yaml --env-file .env up -d
docker compose -f compose.prod.yaml --env-file .env ps
```

`knowledge-init` 会先迁移知识表并用与 Worker 完全相同的数据库、模型和向量维度配置幂等导入镜像内的广州语料，成功后才启动 Worker。静态语料的新鲜度以文档 `collected_at` 和官方来源目录的抓取间隔计算，不依赖 Acquisition 运行表；过期引用明确标记为 `STALE`。检查 `http://127.0.0.1:8080/api/health`，再执行注册、登录、创建广州旅行、开始/取消规划、SSE 完成和退出登录。浏览器中不得出现可读取的 Refresh Token，响应 Cookie 必须包含 `HttpOnly; Secure; SameSite=Strict`。

Prometheus 仅绑定宿主机回环地址 `http://127.0.0.1:9090`；确认 `travel-server` target 为 `UP`。公网监控访问应通过独立、受认证的运维入口，不通过业务 Nginx 暴露 `/actuator/**`。

## PostgreSQL 备份与恢复演练

备份使用自定义格式并在每次发布前复制到 Docker 卷之外：

```powershell
python scripts/postgres_backup.py backup backups/trip-pilot.dump
```

恢复必须先在独立数据库或演练环境验证，不直接覆盖生产：

```powershell
docker compose -f compose.prod.yaml --env-file .env exec -T postgres createdb -U trip_pilot trip_pilot_restore
python scripts/postgres_backup.py restore backups/trip-pilot.dump --database trip_pilot_restore
```

验收 Flyway 版本、用户/旅行/任务/行程版本数量，以及随机抽取的引用快照。确认后才安排正式维护窗口。

## 回滚

- 应用镜像以不可变 Git SHA 标记；回滚只切回上一镜像，不回写数据库迁移。
- 数据库变更必须向前兼容；需要数据恢复时进入维护模式并使用已验证备份。
- 回滚后再次验证健康检查、登录 Cookie、队列消费、规划完成/不可行事件和 SSE。
