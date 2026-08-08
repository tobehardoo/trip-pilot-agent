# TripPilot 路线图强制审计 3：远端推送与 Draft PR 范围

审计日期：2026-08-04

审计对象：Draft PR [#27](https://github.com/tobehardoo/trip-pilot-agent/pull/27)，审计时 head `9afb73c6de5b60da2496e28561324361ce52677c`

审计方法：本地 Git 与远端引用比对、GitHub CLI、GitHub App PR 元数据与分页文件列表、gitleaks、Markdown/差异检查。

## 1. 审计结论

PR 的 Draft 状态、base/head、提交范围、文件范围、描述和远端 SHA 均符合路线图授权；未发现缺失提交、无关用户文件、真实密钥、本地产物或对 `main` 的未授权修改。审计发现的 1 项 Important 已修复，当前无未解决的 Critical/Important。

该结论只证明远端 PR 范围正确，不证明 CI 已通过。审计快照中 `repository-safety` 已失败，其余 4 个 job 正在运行；失败原因留待下一轮按 Actions 日志诊断。

## 2. 远端身份与引用

| 检查项 | 证据 | 结论 |
| --- | --- | --- |
| 仓库 | `tobehardoo/trip-pilot-agent` | 正确 |
| PR | `#27`，标题 `feat: integrate plan evaluation and city intelligence` | 正确 |
| 状态 | `OPEN`、`draft=true`、未合并 | 正确 |
| base | `main@2cbd76607e0a10639c6cfd4143ee95ddc2e60294` | 正确 |
| head | `codex/plan-evaluation-weather-integration@9afb73c6de5b60da2496e28561324361ce52677c` | 正确 |
| 本地/远端 | 本地 HEAD、upstream 和 PR head 三者均为 `9afb73c` | 一致 |
| 本地 `main` | `c25617690c5df6270aa755aa1cb23a6321b04916`，未推送或修改远端 `main` | 合规 |

## 3. 提交与文件范围

- PR 含 25 个提交、153 个变更文件、15,396 行新增和 467 行删除。
- 提交从 Provider 分类/模式/失败 v2/provenance/幂等与 RC 基线，连续覆盖 PlanEvaluation、天气/城市情报、Web 组合集成、完整门禁、两次审计、staging 准备和远端预检记录。
- GitHub App 返回的提交数和分页文件列表与本地 `git log origin/main..HEAD`、`git diff --name-only origin/main...HEAD` 一致。
- 本地 `main` 比远端 base 多出的 7 个提交是 Provider 与 RC 必要前置，不是无关历史，不能从当前 PR 中移除而不破坏功能与契约。
- 变更路径未包含 `.claude/`、`.pnpm-store/`、`node_modules`、`target`、`dist`、coverage、pytest cache、`__pycache__`、私有 env 或密钥文件；`.env.example` 是公开示例配置。
- `git diff --check origin/main...HEAD` 通过；gitleaks 扫描 25 个提交、约 758 KB patch，无泄露。

## 4. PR 描述审计

描述已覆盖：

- PlanEvaluation 的确定性评分、warning、解释和 8 场景 benchmark；
- 天气/城市情报、QWeather/AMap provenance、重试和回退；
- `TripDetail.vue`、`TripWorkspace.vue`、天气时间轴和地图日期联动；
- create/replan、completion v6、failure v2、SSE、GET API 与 legacy 兼容；
- Flyway V1–V27、本地 Python/Java/Web/E2E/Compose/安全门禁；
- Audit 1、Audit 2、路线图、staging 手册和环境预检；
- staging、真实 Provider 与生产验收仍是外部阻塞；
- “本地 RC 候选，不代表可生产发布”和保持 Draft 的发布边界。

## 5. Actions 触发审计

GitHub Actions 工作流 `CI` 已针对 PR head `9afb73c` 启动，run 为 [30872938209](https://github.com/tobehardoo/trip-pilot-agent/actions/runs/30872938209)。审计快照：

- `java`：运行中；
- `python`：运行中；
- `web`：运行中；
- `infrastructure`：运行中；
- `repository-safety`：失败。

没有 job 被 PR 配置静默跳过。失败不能在无日志证据时归因，下一轮必须使用 GitHub CLI 获取 job 日志。

## 6. 审计发现

### Critical

无。

### Important

#### A3-I01：PR 发布资料最初不是可点击链接

- 证据：初始描述以反引号显示 5 个仓库路径，无法直接从 PR 打开审计和验收资料。
- 处理：已通过 `gh pr edit` 替换为指向当前分支的真实 Markdown 链接。
- 状态：已修复。

### Normal

#### A3-N01：GitHub App 无 PR 写权限

- 证据：创建和更新 PR 均返回 HTTP 403 `Resource not accessible by integration`。
- 处理：按 `github:yeet` 允许的回退流程使用已认证的 GitHub CLI；PR 创建和描述更新均成功。
- 影响：不影响 PR 内容；后续 PR 写操作继续使用 `gh`，元数据读取仍可交叉使用 App。

### Deferred

#### A3-D01：首次远端 `repository-safety` 失败

- 证据：run `30872938209` 的 `repository-safety` job 已进入 `FAILURE`。
- 处理：Audit 3 提交后使用 `github:gh-fix-ci` 的检查脚本和 `gh` 日志提取进行根因分类。
- 发布影响：阻塞远端 RC 通过，不阻塞本审计记录提交。

## 7. 授权边界复核

- 未 force push、未删除远端分支、未关闭或合并 PR、未转为 Ready。
- 未推送或直接修改 `main`，未创建 tag/Release，未部署 staging/production。
- 未修改仓库设置、分支保护、Environment 或 Secrets。
- 未读取、上传或提交真实 Provider Key。
- 未删除、跳过或降低测试、覆盖率、lint、安全或发布门禁。

## 8. 下一步

将本审计记录作为独立提交推送到同一分支，确认 PR head 更新且仍为 Draft；随后读取最新 SHA 对应的 Actions 日志，优先诊断 `repository-safety`，完成聚焦修复后持续观察所有 job。
