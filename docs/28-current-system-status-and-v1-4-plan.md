# 当前系统状态与 V1.3 实施基线

> 审计日期：2026-07-26
>
> 当前发布版本：V1.2 发布候选
>
> 当前开发目标：V1.3 可信城市情报与可恢复版本
>
> 分支：`codex/complete-v1`
>
> 审计提交：`aebb7be3ed4308f559ec166bf465592877e4b056`

## 1. 审计结论

仓库在 V1.2 之上已经形成一条 V1.3 窄纵向切片，但尚未达到 V1.3 退出标准。

已经存在并应复用：

- Java 旅行、规划任务、Outbox、RabbitMQ、SSE、不可变行程版本与所有权校验。
- Python 官方来源 TOML 目录、SSRF/DNS 固定解析抓取器、采集/审核/发布和 pgvector。
- 公开 HTTPS HTML、粘贴正文、UTF-8 TXT/Markdown、小红书分享正文导入。
- 手动高德城市天气/景点详情同步，规则事实分类、有效期与 `effectiveDate`。
- 创建任务时冻结的 `guide_evidence_snapshot`，日期级雨天候选排序。
- 地图 `complete` 事件、8 秒超时、覆盖物生命周期与路线概览降级。

尚未实现：

- Java 业务侧可审核的广州、北京、上海城市来源注册表。
- 创建旅行后自动预热、规划前 TTL 检查、限时刷新与最后成功 stale 降级。
- 统一 `NormalizedDocument`、严格模型候选抽取、独立 `FactValidator/FactMerger`。
- 官方/社区冲突决策、关闭/预约/开放/票价硬规则和结构化影响记录。
- 包含来源、冲突、刷新诊断和 stale 事实的 `PlanningContextSnapshot`。
- 结果页“本次规划依据”摘要与事实影响明细。
- 行程版本列表、结构化差异、幂等回滚与审计。
- 真实高德控制台授权下的底图成功证据。

## 2. 文档与代码差异

- 旧文档记录最后提交为 `5e01b1a`，实际已推送提交为 `aebb7be`。
- 旧文档把地图和多来源情报写成“本地未推送”，实际已包含在远端分支与 CI #72。
- 旧发布清单记录 Java 162 项；本次 `mvn --batch-mode verify` 实际汇总为 124 项。
- 旧路线图称 V1.2 只支持 URL；当前分支已支持正文、TXT/Markdown 和小红书分享正文。
- 领域文档声称版本比较已存在，但代码只有当前版本读取和不可变版本持久化。

## 3. 当前真实数据流

```text
用户手动导入 URL/正文或点击城市同步
  → Java 校验旅行所有权
  → Python Agent API 抓取/清洗/规则分类
  → Java 写 guide_import / guide_fact
  → 创建规划任务时只选择未过期事实
  → planning-create-command-v2
  → Worker 以社区排序和日期级天气权重使用部分事实
  → 实际匹配事实被转成知识引用
```

缺口在于：过期事实会被直接排除，没有最后成功 stale 快照；来源可靠性没有进入 Java
业务模型；Worker 没有关闭、预约、开放时间和票价的分类规则，也没有独立影响记录。

## 4. V1.3 目标数据流

```text
创建旅行
  → 同一事务写预热记录与 Outbox
  → Java 刷新消费者调用 Python Agent API
  → 规范化、候选抽取、Schema/证据校验
  → Java 持久化来源、事实、冲突、最后成功结果与诊断

创建规划任务
  → 按事实类别和旅行日期检查 TTL
  → 限时刷新缺失/过期类别
  → 失败则保留最后成功事实并标 stale
  → 冻结 PlanningContextSnapshot V3
  → Worker 只消费快照并输出 PlanningFactImpact
  → Java 创建不可变行程版本并持久化解释
```

详细边界见[系统架构](architecture.md)，领域规则见[领域模型](domain.md)，迁移计划见
[数据库设计](database.md)，接口与消息见[API 契约](api.md)。

## 5. 实施切片

1. V20 来源注册表与三城市初始化；查询、审核和启停 API。
2. 规范化文档、规则/模型候选、校验、合并与冲突测试。
3. V21 刷新状态、事实生命周期、TTL 与规划上下文快照。
4. 创建旅行 Outbox 预热与规划前限时刷新、stale 降级。
5. 规划命令 V3、完成事件 V6、Worker 硬/软规则和事实影响。
6. 前端规划依据与地图诊断收口。
7. V22 版本列表、差异、幂等回滚、审计和前端交互。
8. 三城市验收、Compose 健康、发布证据与外部凭据限制记录。

## 6. 主要风险与降级

- 高德 Web JS Key 类型、安全密钥和域名白名单只能在控制台人工配置；代码负责成对校验、
  超时、诊断和可用降级。
- 官方页面结构可能变化；解析失败必须写诊断并保留最后成功事实，不得转成 Demo 成功。
- 模型 Provider 未配置、超时或返回非法 JSON 时，规则抽取继续运行并标记
  `SKIPPED/FAILED`。
- 社区与 stale 事实永远不能形成关闭或预约硬约束。
- 跨服务浏览器 E2E、分享、导出、多方案和完整运营后台属于 V1.4，不阻塞 V1.3。

## 7. 审计门禁

2026-07-26 在审计提交上实际执行：

- Web：80 项 Vitest 通过；`pnpm typecheck` 与 `pnpm build` 通过。
- Python：Ruff 通过；389 项通过、34 项按环境跳过。Windows 默认临时目录无权限时，
  使用仓库内隔离 `--basetemp` 后全绿。
- Java：`mvn --batch-mode verify` 124 项通过，JaCoCo 80% 门禁通过。
- GitHub：CI run #72 成功；Draft PR #23 打开、可合并。
- Compose：生产拓扑中的 PostgreSQL、Redis、RabbitMQ、Java、Python API、Web 与
  Prometheus 在审计时均运行，带健康检查的服务为 healthy。

这些是编码前基线，不代表 V1.3 新增功能已经验收。最终状态只以
[V1.3 发布验收清单](release-checklist.md)为准。
