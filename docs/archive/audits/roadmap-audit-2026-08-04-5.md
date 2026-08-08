# TripPilot 路线图强制审计 5：Staging 预检与 Provider 合规修复

审计日期：2026-08-04

审计对象：Draft PR [#27](https://github.com/tobehardoo/trip-pilot-agent/pull/27)，staging 修复候选 `88028aa8f38749acf53fea98c4a3c144fb5a2660`

审计范围：staging 第 1 轮资源/配置预检，以及因真实 Provider 证据触发的第 2 轮合规修复。首次不可变镜像部署尚未开始，不能把本审计解释为 staging 部署或 S-01～S-13 验收完成。

## 1. 审计结论

候选、Draft PR 和远端 CI 基线正确；本地私有 `.env` 被 Git 忽略，预检与真实 Provider 探测均未输出 Secret。真实 QWeather 专用 Host 上的 GeoAPI、当前天气、7 日预报和近期历史天气接口成功，真实 AMap 三个固定样例在受控复测中通过。

真实 QWeather 响应同时证明产品原实现没有保留 `fxLink`，无法满足页面归因要求。修复提交 `88028aa` 通过 TDD 将安全归一化后的 QWeather `fxLink` 贯穿到城市情报来源、metadata 和可信天气事实；非法、畸形、非字符串或非默认端口候选被忽略，没有其他有效候选时回退官方首页，不能触发 Provider 降级或把响应原文写入异常。独立复审无剩余 Critical/Important/Normal，`88028aa` 的五项 GitHub Actions 全部成功。本审计文档将形成新的 head SHA；只有该 SHA 再次通过同一五项 CI，Audit 5 的远端闭环才成立。

staging 部署仍为 `BLOCKED`：当前执行环境没有可定位的 staging 主机/集群上下文、批准的镜像 registry 登录目标、七类 registry digest、完整私有 staging env、最终域名/TLS/出口 IP、监控/备份/证据存储入口。由于资源归属无法确认，审计在部署前保护现场，没有修改本机既有、归属未确认的容器或任何未知资源。

## 2. 候选与远端证据

| 项目 | 结果 |
| --- | --- |
| 分支 | `codex/plan-evaluation-weather-integration` |
| 修复 SHA | `88028aa8f38749acf53fea98c4a3c144fb5a2660` |
| PR | [#27](https://github.com/tobehardoo/trip-pilot-agent/pull/27)，`OPEN`、Draft |
| base/head | `main` ← `codex/plan-evaluation-weather-integration` |
| CI run | [30878940031](https://github.com/tobehardoo/trip-pilot-agent/actions/runs/30878940031) |
| Java | SUCCESS |
| Python | SUCCESS |
| Web | SUCCESS |
| Infrastructure | SUCCESS |
| Repository Safety | SUCCESS |

五个预期 job 均出现并执行，没有跳过；本次修复没有降低覆盖率、安全扫描、构建或 Compose 门禁。Node.js 20 action deprecation 是上游维护告警，不改变本次成功结论。

## 3. 第 1 轮：资源与配置预检

### 已确认

- 本地、upstream 和 PR head 在预检开始时均为 `e726ad0`，工作树干净；修复后统一为 `88028aa`。
- `.env` 存在且由 `.gitignore` 排除；仓库未跟踪 `.env`、私钥、`.claude/` 或 `.pnpm-store/`。
- 专用预检只输出变量名级问题，没有输出值。当前 `.env` 缺 10 项 staging 部署条件：七类 `*_IMAGE` digest、`PROVIDER_MODE`、空 `PROVIDER_FALLBACK_CATEGORIES` 和 `TRUSTED_PROXY_CIDR`。
- Docker 只配置本机 `desktop-linux`；没有明确的远端 staging Docker/Kubernetes/SSH 上下文。
- GitHub 仓库没有 Environment、Actions Secret、Actions Variable 或 staging deployment workflow；只有 CI workflow。
- Docker 凭据配置没有可识别的已登录 staging registry；现有本地镜像没有批准 registry 的不可变引用。
- 浏览器历史能定位 QWeather/AMap 官方控制台访问记录，但没有可读取的已打开控制台会话；页面字段读取连续超时，无法安全确认 staging 项目、白名单、套餐、配额或费用告警。

### 预检判定

`python scripts/validate_staging_env.py --env-file .env`：FAIL（10 项变量名级问题）。因此没有运行会展开部署镜像集合的 staging Compose，也没有构建、推送或部署不可变镜像。

## 4. 第 2 轮：真实 Provider 证据与合规修复

### 脱敏真实证据

- QWeather：`/geo/v2/city/lookup`、`/v7/weather/now`、`/v7/weather/7d`、`/v7/historical/weather` 共四个接口均为 HTTP/API 成功。
- QWeather：天气接口均返回 HTTPS `fxLink` 和 `refer`；事实日期覆盖近期历史 1 天、当天 2 项、未来 2 天。
- AMap：显式真实模式的 POI/路线、两日规划和不可行约束三个固定样例复测 3/3；首次运行有一次未能安全分类的暂态失败，因此该证据只证明凭据/接口当前可用，不等于 staging S-03 通过。
- 探测捕获输出的 Secret 扫描为阴性；没有保存或提交完整第三方响应。

### 发现与修复

#### A5-I01：QWeather 归因链接未使用实际 `fxLink`

- 影响：页面链接指向开发文档而不是 QWeather 天气来源页，不能完成 S-04 归因验收。
- 修复：`QWeatherWeatherProvider` 保留实时/预报响应的 `fxLink`，城市情报合并、normalized metadata 和 WEATHER trusted fact 使用同一来源 URL；缺失时回退 `https://www.qweather.com`。
- 状态：已修复。

#### A5-I02：外部 `fxLink` 的类型与 URL 失败关闭不足

- 影响：畸形 URL 可导致有效天气导入失败；非字符串载荷可进入 Pydantic 错误正文并被上层记录；非默认端口或非 QWeather 域名可能进入前端链接。
- 修复：外部字段以 `object` 边界接收，只有字符串进入共享 `validate_source_url`；强制 HTTPS、无凭据、默认端口和 `qweather.com`/子域，非法候选被忽略，没有其他有效候选时回退官方首页。
- 状态：已修复。

### 测试与审查

- TDD：实际 `fxLink` 贯穿测试先因缺少字段失败；service 贯穿测试先得到开发文档链接；畸形 URL、非默认端口和对象载荷三类新增负向用例均在旧实现失败，修复后转绿。
- Python：`547 passed, 37 skipped`（使用隔离 basetemp，避开 Windows 历史 pytest 临时目录权限污染）。
- Ruff：通过；PlanEvaluation benchmark：8/8；release tooling：12/12。
- staged gitleaks 8.24.3：无泄露。
- 独立复审：两项 Important 均修复，最终无 Critical/Important/Normal。

## 5. S-01～S-13 当前判定

| 场景 | 判定 | 说明 |
| --- | --- | --- |
| S-01 HTTPS 与会话 | BLOCKED | 缺最终 staging 域名、DNS、TLS 和入口访问 |
| S-02 CSP 与高德 Web JS | BLOCKED | 缺最终域名和 Web JS 应用白名单证据 |
| S-03 真实 AMap 规划 | BLOCKED | 真实 SDK 样例通过，但未在 staging 完整异步链路与 UI 验证 |
| S-04 QWeather 正向 | BLOCKED | 四接口与日期类别通过；缺部署后 UI、归因展示和套餐签字 |
| S-05 QWeather 降级 | BLOCKED | 未取得隔离故障注入入口 |
| S-06 配置失败 | BLOCKED | 自动化配置测试通过；未在 staging 隔离配置执行 |
| S-07 城市刷新时序 | BLOCKED | 缺部署中的 planning context 证据 |
| S-08 核心用户旅程 | BLOCKED | 缺 staging HTTPS 应用与测试账号 |
| S-09 幂等与故障恢复 | BLOCKED | 缺 staging 服务控制面 |
| S-10 日志与告警 | BLOCKED | 缺 staging 日志、Prometheus 和告警入口 |
| S-11 备份恢复 | BLOCKED | 缺 staging 数据库与批准备份存储 |
| S-12 应用回滚 | BLOCKED | 缺当前/上一组 registry digest 和部署控制面 |
| S-13 24 小时 soak | BLOCKED | 尚无已部署候选，未启动计时 |

## 6. 继续执行所需外部入口

- 明确标识为 staging 的主机、集群、Docker context 或 SSH alias。
- 批准的 registry endpoint 与现有认证，以及七类完整 `registry/repository@sha256` 引用的生成/推送路径。
- 完整私有 staging env 路径或密钥库引用；不得把当前不完整 `.env` 直接当作 staging env。
- 最终 HTTPS 域名、DNS/TLS 管理入口、固定出口 IP 和 AMap 两类应用白名单入口。
- QWeather staging 项目脱敏标识、套餐/归因签字与配额/费用告警入口。
- Prometheus/告警、备份存储和受控原始证据存储位置。

这些入口在当前仓库、本机配置、GitHub 仓库元数据、Docker 上下文/凭据和可用浏览器会话中均不可定位。资源未明确前继续部署会违反“只能操作明确标记为 staging 的资源”的边界。

## 7. 授权边界与发布判定

- 未修改或推送 `main`，未 force push，未合并 PR，未转 Ready。
- 未部署 staging 或 production，未操作生产账号、Key、白名单或数据。
- 未显示、提交或上传 Secret、完整 `.env`、Compose 展开配置或第三方完整响应。
- 未降低门禁，未把真实 Provider 失败转换成 Demo 成功。
- `88028aa` 的发布层级为“远端 CI 已验证的 RC 候选”；本 Audit 5 文档提交形成的新 SHA 仍须再次通过五项 CI，之后才能维持该层级。当前不是 `STAGING_ACCEPTED_AWAITING_SIGNOFF`，更不是 `PRODUCTION_APPROVED`。
