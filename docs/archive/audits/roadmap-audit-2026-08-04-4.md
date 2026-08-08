# TripPilot 路线图强制审计 4：远端 CI 修复与 RC 闭环

审计日期：2026-08-04

审计对象：Draft PR [#27](https://github.com/tobehardoo/trip-pilot-agent/pull/27)，CI 修复 head `4aa1964e5edb1a412ce767d44c0a07e2267a6e37`

审计范围：Audit 3 后的 gitleaks 修复轮次与最终远端状态/文档轮次。

## 1. 审计结论

`4aa1964` 的五个 GitHub Actions job 已全部成功，且失败修复没有删除测试、降低 80% 覆盖率、放宽安全规则或掩盖真实泄露。PR 仍为 Draft，base/head 与授权一致。Audit 4 本轮发现的 2 项 Important 均已修复，当前无未解决的 Critical/Important。

本审计完成远端 RC 技术证据复核，不构成 staging 或生产发布签字。Audit 4 与路线图更新将形成新的文档 SHA；只有该 SHA 再次通过同一五项 CI，远端 RC 闭环才成立。

## 2. GitHub Actions 证据

| 项目 | 结果 |
| --- | --- |
| PR | [#27](https://github.com/tobehardoo/trip-pilot-agent/pull/27)，`OPEN`、`draft=true` |
| base/head | `main` ← `codex/plan-evaluation-weather-integration` |
| 验证 SHA | `4aa1964e5edb1a412ce767d44c0a07e2267a6e37` |
| Workflow run | [30874435735](https://github.com/tobehardoo/trip-pilot-agent/actions/runs/30874435735) |
| Java | SUCCESS |
| Python | SUCCESS |
| Web | SUCCESS |
| Infrastructure | SUCCESS |
| Repository Safety | SUCCESS |
| PR merge state | `CLEAN`，但保持 Draft且不合并 |

所有五个 workflow job 均出现并执行，没有被跳过。PR status rollup 未出现非 GitHub Actions 的外部检查。

GitHub API 返回 `main` branch protection 为 `404 Branch not protected`，repository rulesets 为空。因此仓库没有单独配置 required status checks；审计以 `.github/workflows/ci.yml` 定义并实际出现的五个 job 作为完整远端门禁。

## 3. 失败根因与修复对应关系

### 原始失败

- Run `30872938209` 与 Audit 3 后的 run `30873149095` 均只有 `repository-safety` 失败，其余 Java、Python、Web、Infrastructure 成功。
- gitleaks-action 使用 gitleaks 8.24.3 扫描完整 PR 历史，将提交 `56eee3c` 中 `apps/agent-service/benchmarks/run_plan_evaluation.py:183` 的固定 `idempotencyKey` UUID 识别为 `generic-api-key`。
- 日志提供的 fingerprint 为 `56eee3cb7393c02874e3ffa47e346063069c51e4:apps/agent-service/benchmarks/run_plan_evaluation.py:generic-api-key:183`。

### 聚焦修复

- 当前 benchmark UUID 改为 `00000000-0000-4000-8000-000000000001`，保持 UUID v4/variant 约束但明显低熵。
- `.gitleaksignore` 只加入日志报告的完整 commit SHA、路径、规则和历史行号，没有通配、目录级或规则级豁免。
- `scripts/tests/test_ci_release_gates.py` 同时锁定当前低熵值和精确 fingerprint，防止未来退回高熵 fixture 或扩大忽略范围。

### 验证

- TDD：新增契约测试在旧代码上按预期失败，修复后转绿。
- Release tooling：`12 passed`。
- PlanEvaluation benchmark：8/8；benchmark pytest：`2 passed`。
- Ruff：通过。
- gitleaks 8.24.3：staged diff 与 Actions 同范围完整历史扫描均无泄露。
- 独立代码审查：无 Critical、Important 或 Normal。
- 远端 `repository-safety`：SUCCESS。

## 4. 跨栈与门禁未削弱复核

- Python 覆盖率命令仍同时覆盖 retrieval、acquisition、guide intelligence，并保持 `--cov-fail-under=80`；远端 Python job 成功。
- Java `mvn --batch-mode verify`、Flyway/JaCoCo 路径未修改；远端 Java job 成功。
- Web coverage、typecheck、build、Playwright 路径未修改；远端 Web job 成功。
- Compose config、digest override、镜像构建、cold-start smoke 和健康断言未修改；远端 Infrastructure job 成功。
- create/replan/legacy/failure、evaluation、SSE/`Last-Event-ID`、Activity/Transit ID 重映射、天气日期/地图联动、QWeather/AMap 回退、幂等与并发代码均未被本轮改动。
- 改动仅涉及 benchmark fixture、精确 gitleaks fingerprint、对应契约测试以及文档，不改变产品运行时语义。

## 5. 审计发现

### Critical

无。

### Important

#### A4-I01：历史 benchmark UUID 被 CI gitleaks 8.24.3 误报

- 影响：阻塞 `repository-safety`，使远端 RC 无法全绿。
- 处理：使用低熵当前 fixture、精确历史 fingerprint 和契约测试；本地同版本扫描与远端 job 均成功。
- 状态：已修复。

#### A4-I02：PR 描述中文在一次 CLI 管道更新后损坏

- 影响：背景、范围和发布边界不可读，不满足长期审阅要求。
- 根因：PowerShell 字符串通过默认管道编码传给 `gh pr edit --body-file -`。
- 处理：改用显式 UTF-8 Markdown 文件更新完整描述；GitHub App 重新读取确认中文和链接正常。
- 状态：已修复。

### Normal

#### A4-N01：GitHub App 对 PR 写操作返回 403

- 处理：按技能回退到具备 `repo`、`workflow` 权限的 GitHub CLI；App 继续用于只读元数据交叉验证。
- 状态：已接受，不影响 PR 或 CI。

### Deferred

- 真实 AMap/QWeather 凭据、QWeather 专用 Host、域名/IP 白名单。
- HTTPS、Secure Cookie、CSP、告警、备份恢复、应用回滚。
- Staging S-01 至 S-13、至少 24 小时 soak 和发布负责人签字。

## 6. 授权边界复核

- 未修改或推送 `main`，未 force push，未删除远端分支。
- 未合并 PR、未转为 Ready、未创建 tag/Release。
- 未部署 staging/production，未修改仓库设置、branch protection、Environment 或 Secrets。
- 未读取、使用、上传或提交真实 Provider Key。
- 未降低或绕过 CI 门禁。

## 7. 最终放行条件

将本审计与路线图作为一个边界清晰的文档提交推送到 PR #27；确认 PR 仍为 Draft，最新 head SHA 的 Java、Python、Web、Infrastructure、Repository Safety 再次全部成功，且没有预期 job 被跳过。满足后可称为“远端 CI 已验证的 RC 候选”，但仍不可称为“可生产发布”。
