# TripPilot 路线图强制审计 2（2026-08-02）

## 1. 审计范围与结论

- 审计范围：第 3 轮 Web 日期稳健性提交 `b60f36a`、第 4 轮 staging 准备提交 `8c62119`，以及审计期间形成的 CI、不可变镜像和文档修复。
- Git 现场：审计起点为 `codex/plan-evaluation-weather-integration` 的 `8c62119`；`main` 仍为 `c256176`。未 fetch、push、创建 PR、修改 main 或部署任何外部环境。
- 方法：路线图逐项映射、业务闭环复查、代码与测试有效性审查、生产 Compose 解析、CI 门禁审查、配置负向测试、Markdown/差异检查、tracked 文件卫生和容器化 gitleaks 全历史扫描。
- 结论：自审与独立复核共发现 5 项 Important，均在审计期间以先失败后修复的回归保护闭环；未发现 Critical。最终独立代码复核确认修复后 Critical/Important 为零。剩余项为不阻塞本地候选的 Normal 技术债，或必须由真实 staging/外部账号完成的 Deferred 门禁。

| 级别 | 发现数 | 已修复 | 未解决 |
| --- | ---: | ---: | ---: |
| Critical | 0 | 0 | 0 |
| Important | 5 | 5 | 0 |
| Normal | 4 | 0 | 4 |
| Deferred | 4 | 0 | 4 |

## 2. 路线图符合性

| 路线图阶段 | 当前判定 | 审计证据 |
| --- | --- | --- |
| 阶段 0：基线与现场 | 通过 | 当前分支独立，`main=c256176` 未移动；本地工具/生成目录未被跟踪 |
| 阶段 1：天气/城市情报收口 | 通过（模拟） | Python 541、Ruff、Provider provenance、QWeather 配置/坐标/并发回归均通过；真实 Provider 仍属 Deferred |
| 阶段 2：双线集成 | 通过 | 评估、天气时间轴、地图日期筛选共存；当前版本 hydration 和并发保护有单元/E2E 证据 |
| 阶段 3：组合完整验证 | 通过（本地） | Java 208、Python 541、Web 126、Playwright 6、benchmark 8/8、Flyway V1–V27、JaCoCo、镜像构建和隔离 Compose 已通过 |
| 阶段 4：发布候选与环境验收 | 本地准备完成，真实执行阻塞 | 运行手册、配置预检、digest override、CI 门禁已准备；S-01 至 S-13 未在 staging 执行 |
| 阶段 5：最小版本上线 | 未开始 | 依赖阶段 4 全部门禁、批准和变更窗口 |
| 阶段 6–7：增强/演进 | 未开始 | 不进入首发范围，避免范围膨胀 |

当前发布层级仍是“可提交、可集成、可部署 staging 的本地 RC 候选”，不是“发布候选”或“可生产发布”。本次新增运行手册和预检只降低真实验收的操作风险，不生成任何外部通过证据。

## 3. Important 发现与修复

### I-01：本地发布专用门禁没有进入 CI

- 发现：`ci.yml` 的 Python job 运行 pytest/Ruff，但没有运行 PlanEvaluation benchmark；新 staging 预检的标准库测试和脚本 Ruff 也没有远端门禁。代码变化后可能本地通过、PR CI 却不保护评分基准或发布预检。
- 处置：先增加 CI 契约测试并确认旧 workflow 失败；随后在 Python job 增加脚本 Ruff 与 benchmark，在 repository-safety job 增加全部 `scripts/tests`。
- 验证：CI 契约测试转绿；本地执行 10 项 release tooling 测试、Ruff 和 benchmark 8/8 通过。因未获准 push，GitHub Actions 实际运行仍为 D-02。

### I-02：生产 Compose smoke 只探测 Web，没有直接探测 API

- 发现：`up --wait` 和首页 curl 可证明容器健康及 Nginx 页面可达，但不能锁定 `/api` 反向代理与 Java 健康链路；这与本地组合门禁的 Web/API 双 200 口径不一致。
- 处置：先以 CI 契约测试复现缺失，再在 smoke 中增加 `http://127.0.0.1:8080/api/health` 的失败即停探测。
- 验证：契约测试确认 Web 与 API 两个 URL 均存在；Audit 1 的隔离 Compose 已实测两者 HTTP 200。远端 Linux runner 执行仍为 D-02。

### I-03：生产编排只能按 tag 启动，无法兑现不可变候选

- 发现：运行手册要求 staging 使用 registry digest，但 `compose.prod.yaml` 所有应用镜像只接受 `IMAGE_TAG`，Redis/RabbitMQ 甚至是固定 tag。验证 tag 后到启动前仍可被重指向，不能证明运行制品与批准候选一致。
- 处置：先增加“七类镜像必须可 override”与“每项 staging 镜像必须为完整 `@sha256`”失败测试；随后为 PostgreSQL、Redis、RabbitMQ、Travel Server、Agent Service、Web、Prometheus 增加完整 image reference override，本地 tag fallback 保持不变。预检强制七项 digest，运行手册禁止目标环境 build。
- 验证：10 项 release tooling 测试通过；默认 `.env.example` 的生产 Compose 仍可解析为既有本地 tag；注入七个假 registry digest 后，9 个服务解析镜像全部以 64 位 `@sha256` 结尾。

### I-04：API smoke 的任意 2xx 仍可能被 SPA fallback 伪装

- 发现：直接 curl `/api/health` 比只探测 Web 更强，但 `curl --fail` 只约束 HTTP 状态。若 Nginx 把 `/api` 错误回退到 `index.html`，仍可能返回 200，使 CI 假阳性。
- 处置：先加强 CI 契约测试并确认缺少身份断言；随后把 API 响应管道送入 JSON 解析，强制 `status=UP` 且 `service=travel-server`。
- 验证：契约测试转绿；workflow 经 actionlint 1.7.7 校验。Audit 1 的真实本地 smoke 响应为 `{"status":"UP","service":"travel-server"}`。

### I-05：digest override 只有本地证据，没有远端 Compose 行为门禁

- 发现：静态契约只证明变量出现在 Compose 中，本地 PowerShell 验证也不能保护 Linux CI 上的插值行为；后续改动可能让 staging 回到 tag，而 PR 仍全绿。
- 处置：CI infrastructure job 新增独立步骤，注入七个假 digest，执行真实 `docker compose config --images`，要求正好 9 个服务镜像且每行都匹配 64 位 `@sha256`。
- 验证：契约测试先失败后通过；本地相同行为验证得到 9 个 digest 引用；actionlint 通过。远端 runner 的实际执行仍诚实列为 D-02。

## 4. Normal 与 Deferred

### Normal

| 编号 | 事项 | 影响与建议 |
| --- | --- | --- |
| N-01 | GitHub Actions 使用主版本 tag 而非完整 action SHA | 属供应链加固项；在组织 Renovate/Dependabot 策略明确后统一 pin，避免当前零散锁定造成无人维护 |
| N-02 | staging env 解析器只实现发布所需的 Compose dotenv 子集 | 当前支持注释、单双引号和常见转义，并对 Secret 插值采取保守拒绝；若未来需要多行值，先加与 Compose 对照测试再扩展 |
| N-03 | Python 80% 覆盖率门禁仍只覆盖 retrieval/acquisition | 城市情报与 release tooling 有高密度定向/全量测试但不计统一阈值；阶段 6 先记录新基线再扩大范围 |
| N-04 | 天气日期仍保留 statement/observedAt legacy fallback | 新数据优先结构化 `effectiveDate`；旧 fallback 是兼容策略。未来 API 完成历史迁移后再去除文本解析 |

### Deferred

| 编号 | 外部事项 | 解除条件 |
| --- | --- | --- |
| D-01 | 真实 staging S-01 至 S-13 | HTTPS、Cookie、CSP/地图、AMap/QWeather 正负向、核心旅程、故障恢复、日志告警、备份恢复、回滚和连续至少 24 小时 soak 全部有证据 |
| D-02 | 当前提交的远端 CI | 获准 push/PR 后，Linux GitHub Actions 全部通过并绑定最终 SHA；当前不得伪造为通过 |
| D-03 | QWeather 套餐、署名与 `fxLink` | 依据真实账号条款完成产品/法务签字；若要求展示，补持久化/UI 后再发布 |
| D-04 | registry 不可变制品 | CI 构建并发布七类镜像、记录实际 digest，目标环境 `config --images` 与批准记录逐项一致 |

## 5. 业务闭环复核

| 链路 | 结论 | 当前证据/边界 |
| --- | --- | --- |
| 规划成功/失败/SSE 恢复 | 通过（本地） | Java/Python/Web 和 Playwright 覆盖成功、结构化失败、重连与重复事件；真实 AMap 失败语义待 D-01 |
| 当前版本 PlanEvaluation | 通过 | 评估与 planning task/version 绑定；编辑/回滚不继承旧评分；benchmark 8/8 已加入 CI 配置 |
| 天气日期与地图 | 通过 | `effectiveDate → statement → observedAt`；换版移除日期会恢复全部地图路线；组合 E2E 通过 |
| QWeather/AMap 组合与降级 | 通过（模拟） | 半配置拒绝、QWeather/AMap-only、失败回退、正确 weatherinfo/search provenance；真实 Host/套餐待 D-01/D-03 |
| planning preflight | 通过（模拟） | PT2S best-effort；pending/无天气形成结构化 stale 诊断而不阻断核心规划 |
| 编辑、回滚、分享、导出 | 通过（本地） | 幂等编辑/回滚、不可变分享、PDF/ICS 已在既有全量门禁覆盖；需在 S-08/S-09 复验真实环境 |
| 发布/恢复闭环 | 准备完成，未执行 | 运行手册含停止条件、备份恢复、应用回滚和签字模板；无 staging 证据 |

## 6. 测试、配置和安全证据

| 门禁 | 结果 | 备注 |
| --- | --- | --- |
| Python | 541 passed, 37 skipped；Ruff 通过 | Audit 1 最终全量；本审计未改 Agent 产品逻辑 |
| Java | 208 passed；Flyway V1–V27；JaCoCo 通过 | Audit 1 最终全量；本审计未改 Java |
| Web | 126 passed / 24 files；typecheck/build 通过 | 语句/行 94.25%，分支 86.08%，函数 88.46% |
| Playwright | 6 passed | 包含评估 + 天气 + 地图组合链路 |
| PlanEvaluation benchmark | 8/8 | 本审计再次执行，并加入 CI workflow |
| Release tooling | 10 passed；Ruff 通过 | env 安全、CI 契约、digest override；全部使用标准库测试 |
| Compose config / workflow | 通过 | 默认开发/生产解析不变；digest override 的 9 个服务均不可变；actionlint 1.7.7 通过 |
| Compose cold smoke | 通过（Audit 1） | 最终产品镜像、8 个常驻服务健康、init 成功、Web/API 200、资源已销毁 |
| Markdown / diff | 通过 | 链接检查与 `git diff --check` |
| 泄密扫描 | 通过 | gitleaks 扫描全部 refs 中 92 commits、约 4.90 MB，无泄露；新增差异另做 stdin 扫描 |
| tracked 卫生 | 通过 | `.claude/`、`.pnpm-store/`、构建/覆盖率/测试产物和 secret-like 文件均未跟踪 |

测试没有通过删除断言、跳过新用例或缩短外部门禁制造全绿。37 项 Python skip 保持既有外部依赖/平台条件；真实验收明确列为 Deferred，不计作 PASS。

## 7. Git 与发布判定

- 执行顺序保持原子：Audit 1 修复、AMap provenance 追加修正、Web 日期稳健性、staging 准备、Audit 2 修复。当前审计提交只会包含声明范围内的 CI、配置、Compose、测试和文档。
- `.claude/` worktree 的 PlanEvaluation 分支仍停在 `56eee3c`，产品组合分支承载后续提交；没有删除 worktree 或改写 main。
- 仓库当前没有真实 `.env`、Key、证书、HAR、日志原文、dump 或第三方控制台导出。
- 允许称为：可提交、可集成、本地 RC 候选、可交付 staging 执行。
- 不允许称为：staging 已验收、发布候选、可生产发布、生产已上线。

## 8. 下一步

本地阶段 0–4 可执行内容已基本收敛。下一步不是继续扩大首发功能，而是由具备外部权限的产品/测试/安全/运维角色按 [`deployment.md`](../deployment.md#staging-验收运行手册) 执行 S-01 至 S-13：先产出不可变 registry digest 和私有 staging 配置，通过预检与 Compose image 对账，再完成真实 Provider、HTTPS、恢复/回滚/告警和 24 小时 soak。若在真实执行前继续本地开发，应只处理审计中的 Normal 技术债，并保持每两轮一次强制审计。
