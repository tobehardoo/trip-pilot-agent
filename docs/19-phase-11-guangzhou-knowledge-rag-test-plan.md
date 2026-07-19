# Phase 11 广州知识导入与 RAG 基础链路测试计划

## 1. 目标与范围

本阶段交付一个可重复运行的知识库基础链路：仓库内 Markdown 资料经过元数据校验和标题感知切分，使用可替换的 Embedding Provider 生成向量，写入 PostgreSQL `agent` schema 和 pgvector，并按城市、版本模型、季节、人群和相似度返回带来源的片段。

本阶段不接入规划 Agent 的推荐理由、不引入网页爬虫、不承诺营业时间/票价等实时事实，也不把离线哈希向量当作生产语义模型。

## 2. 输入资料

第一批资料位于 `knowledge/guangzhou/`：

- 沙面历史文化街区与步行体验：广州市政府转载的保护利用规划。
- 陈家祠与岭南民间工艺：广州市政府的广东民间工艺博物馆介绍。
- 西关文化 Citywalk 线路骨架：广州市政府发布的文旅荔湾路线资料。

每个文档使用 `+++` 包围 TOML front matter，必填城市、来源 URL、采集时间、可靠性等级和版本；来源页面的实时开放状态不进入固定知识断言。

## 3. 自动化契约

- `test_knowledge_documents.py`：前置元数据、时区归一化、内容哈希、可靠性枚举、稳定标题感知切分、窗口边界，以及仓库广州资料的来源和版本唯一性。
- `test_knowledge_embeddings.py`：Demo Provider 确定性、维度、L2 归一化和空文本拒绝。
- `test_knowledge_service.py`：先切分再批量向量化，向量数量/维度/模型名契约，保存结果的 `created/unchanged` 传播。
- `test_knowledge_repository.py`：隔离 PostgreSQL + pgvector 的迁移、重复导入幂等、同版本正文/元数据变化拒绝、多模型维度共存、只取最新有效版本、城市和相似度过滤；本地未配置 `KNOWLEDGE_TEST_DATABASE_URL` 时跳过，CI 必须提供 pgvector 服务并运行。
- `test_knowledge_cli.py`：递归 Markdown 路径稳定排序、空输入错误、DSN 密钥不出现在配置 repr、UTF-8 导入和 JSON 输出。

## 4. 本地验收命令

```powershell
Set-Location apps/agent-service
uv sync --extra dev
uv run pytest --basetemp=.pytest-tmp
uv run ruff check src tests

$env:KNOWLEDGE_DATABASE_URL = "postgresql://<local-user>:<local-password>@localhost:<port>/<database>"
uv run trip-agent-knowledge migrate
uv run trip-agent-knowledge import ../../knowledge/guangzhou
uv run trip-agent-knowledge search "陈家祠 岭南工艺 西关路线" --city 广州 --limit 3
```

## 5. 已完成结果（2026-07-19）

- 真实隔离 PostgreSQL/pgvector：3 份文档首次导入为 `created`，再次导入全部为 `unchanged`。
- 真实中文检索返回西关路线和陈家祠片段，结果包含 source URL、document version、chunk ID 和 similarity。
- 迁移使用独立校验和表；`agent.knowledge_document` 与 `agent.knowledge_chunk` 不修改 Java `business` 表。
- pgvector 扩展由 Docker/数据库管理员预先安装；应用迁移只验证扩展并使用普通应用权限建表，缺失时明确失败。
- Python 全量 139 项测试通过；知识检索模块总行覆盖率 92.72%，超过 80% 门槛，Ruff 检查通过。
- GitHub Actions 的 Python job 启动 pgvector PostgreSQL、初始化扩展并设置 `KNOWLEDGE_TEST_DATABASE_URL`，数据库测试不再在 CI 静默跳过。

## 6. 未完成与下一阶段

- 用固定评测集比较 Qwen/OpenAI-compatible Embedding 与 Rerank，确定模型、维度、批量和费用预算。
- 将 `KnowledgeCitation` 接到规划 Agent 的推荐理由输出，并持久化使用过的文档/片段版本。
- 在前端工作台展示来源和更新时间；实时营业、票价和天气继续走 Provider，不从 RAG 静态资料推断。
