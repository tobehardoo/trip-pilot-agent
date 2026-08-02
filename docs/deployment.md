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

Staging/production 还必须为所有运行镜像提供完整 registry digest 引用；本地构建不设置这些变量，继续使用 `IMAGE_TAG`：

| 变量 | 对应服务 |
| --- | --- |
| `POSTGRES_IMAGE` | 自定义 PostgreSQL/PostGIS/pgvector 镜像 |
| `REDIS_IMAGE` | Redis |
| `RABBITMQ_IMAGE` | RabbitMQ |
| `TRAVEL_SERVER_IMAGE` | Java API |
| `AGENT_SERVICE_IMAGE` | Worker、Agent API、knowledge-init 共用镜像 |
| `WEB_IMAGE` | Web/Nginx |
| `PROMETHEUS_IMAGE` | Prometheus |

每个值必须采用 `registry/repository@sha256:<64-hex-digest>`，不能只用 tag。生产/预生产从 registry 拉取这些制品，不在目标环境重新 build。

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

## Staging 验收运行手册

本节是阶段 4 的可重复操作清单。它规定如何收集证据，不授权创建真实凭据、修改第三方控制台、变更 DNS/证书或部署生产。执行人必须使用组织批准的 staging、密钥库和变更窗口；仓库只记录脱敏结论，原始日志、截图、备份和配置快照放入受控证据存储。

### 1. 候选与现场保护

开始前填写以下记录，任一候选标识在验收中变化都必须重新开始受影响的门禁：

| 字段 | 必填证据 |
| --- | --- |
| Git 候选 | 完整 commit SHA、分支、审阅/批准记录；工作区必须无未提交产品变更 |
| 镜像 | PostgreSQL、Travel Server、Agent Service、Web、Prometheus 的 registry digest；不能只记录 `latest` 或可变标签 |
| 编排 | `compose.prod.yaml` 内容摘要、Compose 版本、目标主机/集群标识 |
| 数据库 | 发布前 Flyway 版本、备份对象、恢复演练记录 |
| 配置 | 密钥库条目版本或引用、非敏感配置摘要；禁止复制实际 Secret 到证据文档 |
| 外部资源 | HTTPS 域名、证书到期日、AMap 服务端应用、AMap Web JS 应用与域名白名单、QWeather 专用 Host 的脱敏标识 |

只读确认命令：

```powershell
git status --short --branch
git rev-parse HEAD
docker compose version
docker compose --env-file <private-staging-env> -f compose.prod.yaml config --quiet
docker compose --env-file <private-staging-env> -f compose.prod.yaml config --images
```

不要把完整 `docker compose config` 输出写入工单或仓库，因为展开后的内容可能包含凭据。镜像部署后应从 registry 或运行时读取 digest，并与批准记录逐项匹配。

### 2. 无泄密配置预检

仓库提供的预检只读取本地环境文件并输出变量名级错误，不输出变量值，也不联网：

```powershell
python scripts/validate_staging_env.py --env-file <private-staging-env>
```

通过表示以下静态条件成立：`APP_ENV` 为 staging/production、候选标签不是 local/latest、七类运行镜像全部使用完整 `@sha256` 引用、`PROVIDER_MODE=REAL_ONLY`、fallback 白名单为空、Secret 非示例值且关键令牌互不复用/不使用插值、所有服务端 Secret 与两个浏览器可见 AMap 值隔离、Secure Cookie 开启、可信代理 CIDR 有界、QWeather Key 与专用 Host 完整。它不能证明凭据真实有效、HTTPS 正确、域名已加入白名单或第三方套餐可用；这些必须由后续真实请求证明。

`.env.example` 应当被该命令拒绝，这是保护机制而不是失败。预检单元测试：

```powershell
python -m unittest discover -s scripts/tests -p 'test_*.py' -v
python -m ruff check scripts/validate_staging_env.py scripts/tests/test_validate_staging_env.py
```

### 3. 部署顺序与即时探测

1. 在变更窗口开始前完成数据库自定义格式备份，并在隔离数据库验证可读性、Flyway 版本和关键表计数。
2. 把七个 `*_IMAGE` 配置为已批准的完整 registry digest 并拉取镜像；运行生产 Compose 的 `config --quiet` 和 `config --images`，确认每项都以 `@sha256` 结尾，再启动隔离 staging 项目。目标环境禁止 `--build`。
3. 等待 PostgreSQL、Redis、RabbitMQ、Agent API、Worker、Travel Server、Web 和 Prometheus 健康，确认 `knowledge-init` 退出码为 0。
4. 通过最终 HTTPS 域名请求 Web 和 `/api/health`；不能用容器内部 HTTP 代替公网入口验证。
5. 记录开始时间、操作者、候选 SHA/digest、健康状态和证据位置。任何自动降级、重启循环或迁移异常都先停止验收并保留现场。

### 4. 必跑验收矩阵

| 编号 | 场景 | 通过条件 | 证据 |
| --- | --- | --- | --- |
| S-01 | HTTPS 与会话 | 证书链/主机名有效；登录、刷新和退出成功；refresh Cookie 为 Secure、HttpOnly 且 SameSite 符合部署策略 | 浏览器网络记录和响应头，需脱敏 |
| S-02 | CSP 与高德 Web JS | 最终域名已进同一 Web JS 应用白名单；底图、marker、polyline 正常；无 Key 时显示路线概览而非白屏 | 浏览器截图、控制台/CSP 摘要 |
| S-03 | 真实规划成功 | `REAL_ONLY` 创建规划成功；Activity/Transit 为真实 Provider；completion provenance 为 AMAP 且 `fallback=false`；PlanEvaluation 与当前版本一致 | task/version ID、脱敏 API 摘要 |
| S-04 | QWeather 正向 | 当前天气、未来预报和套餐允许的近期历史日期至少各命中一个；时间轴日期、行程日期和地图筛选一致 | 城市刷新 ID、日期/来源摘要、截图 |
| S-05 | QWeather 降级 | 在批准的负向凭据或网络故障注入下，失败原因可见；AMap 可用时只产生明确 AMap 天气回退，不能伪装成 QWeather | 错误分类、`weatherFallbackReason`、事实来源 URL 摘要 |
| S-06 | 配置失败 | Key-only/Host-only、非法 Host、AMap 无效 Key、`REAL_ONLY` 缺 Key 均安全失败；不得出现 Demo 成功 | 启动/任务状态和脱敏日志 |
| S-07 | 城市刷新时序 | 正常刷新可在有界等待内进入上下文；超时/运行中记录 `CITY_INTELLIGENCE_REFRESH_PENDING`；成功但无行程日天气记录 `CITY_INTELLIGENCE_WEATHER_UNAVAILABLE`，核心规划仍可完成 | planning context 诊断摘要 |
| S-08 | 核心用户旅程 | 新建行程、SSE 恢复、评估解释、天气/地图、编辑草稿、回滚、分享、PDF/ICS 全部完成；用户编辑版本不继承旧评分 | 测试账号、version/task ID、截图 |
| S-09 | 幂等与故障恢复 | 重复命令/事件不产生重复版本；Worker、Java consumer、RabbitMQ、Redis 分别重启后队列和最终状态收敛 | 队列计数、版本数、事件 ID |
| S-10 | 日志与告警 | 日志不含 Key、Authorization、Cookie、Token 或完整 Provider 响应；健康、任务失败、队列积压、Provider 错误和资源告警可触发并恢复 | 脱敏日志扫描、告警触发/恢复记录 |
| S-11 | 备份恢复 | 本候选前备份恢复到隔离数据库；Flyway、关键表计数、API 读取和所有权隔离通过 | 备份校验和、恢复记录，不提交 dump |
| S-12 | 应用回滚 | 切回上一组已知良好 digest 后健康与核心读取通过；不执行逆向迁移；新 schema 与旧应用兼容性已明确 | 回滚时长、digest、健康/API 证据 |
| S-13 | Soak | 必须连续持续至少 24 小时；全程健康，无 P0/P1、无无限重试/队列增长/持续 Provider 降级，资源与成功率基线已记录。缩短窗口只能按下一节的正式例外审批处理，不能直接标 PASS | 时间窗、指标图、异常清单 |

负向测试必须使用专用 staging 凭据、代理故障注入或 Provider 提供的测试能力；不得故意封禁生产账号、消耗不可控配额或把真实 Secret 写进命令历史。QWeather 授权/署名和 `fxLink` 展示要求必须依据实际套餐条款单独签字。

### 5. 发布判定与停止条件

以下条件全部满足，才可把当前状态从“本地 RC 候选”提升为“发布候选”：S-01 至 S-13 全部通过或有获得产品/安全/运维共同批准的限时例外；所有 Critical/Important 已关闭；候选 SHA 与镜像 digest 未变化；恢复与回滚真实执行；真实 Provider、HTTPS、白名单、日志和告警均有证据。

出现以下任一情况立即停止并回滚或恢复现场：凭据/个人数据泄露；迁移不可恢复；`REAL_ONLY` 出现 Demo 结果；版本/所有权/幂等破坏；HTTPS 或 Cookie 安全失败；核心规划持续失败；队列无界增长；候选 digest 不匹配；任何未接受的 Critical/Important。

### 6. 验收记录模板

验收记录至少包含：

```text
候选 SHA：
镜像 digest（逐服务）：
环境/最终域名：
变更窗口与操作者：
非敏感配置摘要/密钥库版本引用：
发布前 Flyway 与备份校验和：
S-01 ... S-13：PASS / FAIL / BLOCKED；证据位置；缺陷链接；复测时间
日志脱敏扫描：
告警触发与恢复：
恢复演练：
回滚演练：
Soak 时间窗与结论：
产品/测试/安全/运维签字：
最终判定：REJECTED / RC / PRODUCTION_APPROVED
```

推荐把原始证据放在访问受控的 `staging-acceptance/<完整 SHA>/`，仓库只提交无敏感信息的结论摘要。不得提交 `.env`、日志原文、HAR、数据库 dump、截图中的 Token/个人数据或第三方控制台导出。

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
