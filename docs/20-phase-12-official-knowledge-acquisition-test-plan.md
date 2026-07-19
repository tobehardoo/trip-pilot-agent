# Phase 12 官方知识采集基础测试计划

## 1. 目标与范围

本阶段把官方旅游资料获取拆成独立的采集边界。第一小步只交付来源注册表、固定 URL 发现、域名白名单和 SSRF 防护；不做开放式递归爬虫，不把候选内容直接发布到 RAG。

后续小步依次实现：HTTP 条件请求和快照、官方文章正文抽取、质量校验与审核队列、`KnowledgeImporter` 发布适配器和 freshness report。

## 2. 第一小步契约

- 来源配置使用仓库内 TOML，记录城市、官方域名、固定资源 URL、可靠性等级、抓取间隔和响应大小上限。
- URL 只允许 `https`、白名单主机和公网 IP；禁止用户名密码、非标准端口、内网/回环/保留地址。
- 来源配置必须有唯一 `source_id`，整个注册表中的资源 URL 规范化后不能重复。
- `SourceCatalog` 只负责加载和校验；发现器已经保留独立适配器边界，抓取器和快照存储将在后续小步通过 Protocol 解耦。
- CLI 校验失败时返回非零状态并输出机器可读 JSON，不进行网络请求。

## 3. 自动化测试

- 有效广州官方来源配置可加载，并能按城市筛选。
- 重复来源 ID、重复资源 URL、非 HTTPS URL 和不在白名单的主机被拒绝。
- 私有、回环、链路本地和保留 IP 被拒绝；来源配置不能携带 URL 凭据。
- 抓取策略边界（超时、间隔、最大响应体）在领域模型边界校验。
- CLI `validate` 输出来源和资源数量，错误配置返回失败。

当前小步结果：19 项采集注册表测试通过，实际广州配置校验输出 1 个来源、3 个资源；未发生网络请求。Python 全量 158 项测试通过，知识检索与采集模块总覆盖率 91.60%。

当前安全边界只检查 URL 字面 IP、协议、凭据和域名白名单；真正联网时还必须做 DNS 解析、解析结果固定、重定向复核和内网地址阻断。

## 4. 验收命令

```powershell
Set-Location apps/agent-service
uv sync --extra dev
uv run pytest tests/test_acquisition_registry.py -q
uv run ruff check src tests
uv run trip-agent-acquisition validate ../../knowledge/sources
```

## 5. 后续验收边界

- HTTP 层使用 ETag/Last-Modified，304 不生成新快照。
- 页面变化只生成候选快照，必须经过质量检查和审核才能调用 `KnowledgeImporter`。
- 每条候选保留来源 URL、发布时间、抓取时间、内容哈希和解析器版本。
- 价格、营业时间、预约和交通等动态事实不从静态采集内容直接承诺，回答时必须实时核验。
