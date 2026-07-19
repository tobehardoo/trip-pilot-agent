# Phase 12 官方知识采集测试计划

## 1. 目标与范围

本阶段把官方旅游资料获取拆成独立的采集边界。第一小步交付来源注册表、固定 URL 发现、域名白名单和基础 SSRF 防护；第二小步交付受控条件 HTTP 获取。当前仍不做开放式递归爬虫，不把候选内容直接发布到 RAG。

后续小步依次实现：DNS 解析固定、限速与退避重试、采集快照、官方文章正文抽取、质量校验与审核队列、`KnowledgeImporter` 发布适配器和 freshness report。

## 2. 第一小步契约

- 来源配置使用仓库内 TOML，记录城市、官方域名、固定资源 URL、可靠性等级、抓取间隔和响应大小上限。
- URL 只允许 `https`、白名单主机和公网 IP；禁止用户名密码、非标准端口、内网/回环/保留地址。
- 来源配置必须有唯一 `source_id`，整个注册表中的资源 URL 规范化后不能重复。
- `SourceCatalog` 只负责加载和校验；发现器已经保留独立适配器边界，抓取器和快照存储将在后续小步通过 Protocol 解耦。
- CLI 校验失败时返回非零状态并输出机器可读 JSON，不进行网络请求。

## 3. 第二小步契约

- `FetchValidators` 显式承载 ETag 和 Last-Modified；校验器存在时发送 `If-None-Match` 和 `If-Modified-Since`。
- 304 返回 `ResourceNotModified`，不读取或伪造正文；2xx 返回带抓取时间、最终 URL、内容类型和校验器的 `ResourceFetched`。
- 请求使用 `Accept-Encoding: identity`，非 identity 响应在读取前拒绝；正文按原始字节流累计并执行 `max_response_bytes`，同时提前拒绝已声明超限的 `Content-Length`。
- HTTPX 禁止自动重定向；每一跳使用来源白名单重新校验，白名单外跳转在第二次请求前阻断。
- 超时、连接失败、429/5xx 和普通 4xx 统一映射为 `AcquisitionFetchError`，供后续调度器判断是否重试；本小步尚不执行重试。

## 4. 自动化测试

- 有效广州官方来源配置可加载，并能按城市筛选。
- 重复来源 ID、重复资源 URL、非 HTTPS URL 和不在白名单的主机被拒绝。
- 私有、回环、链路本地和保留 IP 被拒绝；来源配置不能携带 URL 凭据。
- 抓取策略边界（超时、间隔、最大响应体）在领域模型边界校验。
- CLI `validate` 输出来源和资源数量，错误配置返回失败。

第一小步结果：19 项采集注册表测试通过，实际广州配置校验输出 1 个来源、3 个资源；未发生网络请求。

第二小步结果：新增 15 项条件请求、304、正文上限、压缩响应拒绝、重定向和错误分类测试。采集模块共 34 项测试，覆盖率 90.06%；连接隔离 pgvector 后 Python 全量 173 项测试通过，知识检索与采集模块总覆盖率 91.60%。

当前安全边界检查 URL 字面 IP、协议、凭据和域名白名单，并在每次重定向前重复 URL 策略校验；真正联网前还必须做 DNS 解析、解析结果固定和解析后内网地址阻断。

## 5. 验收命令

```powershell
Set-Location apps/agent-service
uv sync --extra dev
uv run pytest tests/test_acquisition_registry.py tests/test_acquisition_fetcher.py -q
uv run ruff check src tests
uv run trip-agent-acquisition validate ../../knowledge/sources
```

## 6. 后续验收边界

- DNS 结果必须全部为公网地址，请求期间固定解析结果；重定向目标重新执行同一检查。
- 调度器执行每来源限速和有上限的指数退避重试，并记录最终尝试结果。
- 304 不生成新快照，只更新采集运行与最近核验时间。
- 页面变化只生成候选快照，必须经过质量检查和审核才能调用 `KnowledgeImporter`。
- 每条候选保留来源 URL、发布时间、抓取时间、内容哈希和解析器版本。
- 价格、营业时间、预约和交通等动态事实不从静态采集内容直接承诺，回答时必须实时核验。
