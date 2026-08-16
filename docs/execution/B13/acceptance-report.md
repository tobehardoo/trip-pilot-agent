# B13 / GitHub 冻结前全项目独立验收报告

## 1. 结论

**Verdict: `NEEDS_CORRECTION`**

**Release verdict: `RELEASE_FREEZE_BLOCKED`**

当前版本尚不具备推送为正式冻结版本的条件。Python、Java、Web、数据库迁移、Compose 与安全门禁总体健康，但真实浏览器、数据库和 Java → RabbitMQ → Python 跨层验证发现 3 项会产生错误规划结论或卡死任务的 P0 问题，以及若干影响地点真实性、UI 可用性、契约演进和稳定性的 P1 问题。

本报告不授权 B13 Git 收口、push、PR 合并、tag 或 release freeze。修复后必须重新执行独立验收。

## 2. 验收基线与纪律

| 项 | 结果 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `89236ea731b3d9aea55a81f96101940299f2c983`（B12） |
| B13 状态 | 全部实现位于 unstaged/untracked 工作区；execution report 仍为 `IN_PROGRESS` |
| staged | 空 |
| upstream / push | 无 upstream；未 push |
| 保护项 | `.omo/`、`.serena/`、`docs/audits/`、`.env` 未处理 |
| 本验收写入 | 仅本文件 |

验收采用四层证据：静态 diff 与调用链审查、独立全量门禁、隔离 Compose + 真实浏览器/数据库冒烟、对抗性跨层输入。单元测试全绿不替代真实链路结果。

## 3. 独立门禁

| 门禁 | 独立结果 | 判定 |
| --- | --- | --- |
| Python pytest | `1415 passed, 37 skipped` | PASS |
| Python Ruff | `All checks passed` | PASS |
| Java `mvn verify`（JDK 21） | `463 tests, 0 failures/errors/skipped`；JaCoCo 通过 | PASS |
| Flyway | 36 个 migration 验证通过；干净库与 V34 → V36 均执行 | PASS |
| Web unit + coverage | `339 passed`；95.26% statements / 84.15% branches / 92.37% functions / 95.26% lines | PASS，但覆盖口径有缺口，见 P1-8 |
| Web typecheck / build | 通过；1654 modules | PASS |
| Playwright | `20 passed` | PASS，但部分关键断言不足，见 P1-8 |
| Compose defaults | 静态检查与 Docker 展开均通过；默认 `DEMO_ONLY`，消息开关为 true | PASS |
| Markdown links | 111 files valid | PASS |
| `git diff --check` | exit 0（仅既有 CRLF 提示） | PASS |
| Secret / security | 未发现高置信度 secret 泄漏或新增可利用安全漏洞 | PASS |

门禁全绿只能说明既有测试覆盖的行为稳定，不能抵消下述真实链路反例。

## 4. 隔离本地栈与真实链路

使用独立 Compose project、独立端口、独立网络与独立数据卷启动当前 B13 工作区：全部服务 healthy，`knowledge-init` 正常退出，Provider 为 `DEMO_ONLY`。验收结束后仅删除该隔离项目及其卷/网络，未触碰用户已有容器或数据。

### 4.1 已确认通过

- 创建页已移除城市快捷模板，统一为一个创建入口。
- 行程名称可选，空值能够生成预览名称。
- 省 / 市 / 区级联选择器、三餐默认策略、节奏 / 行动力 / 偏好分组已经出现。
- 广州行程的 `arrival_at` / `departure_at` 按 `+08:00` 正确落库并派生日期。
- DEMO_ONLY 创建规划能够到达 `WAITING_USER`；候选未创建正式 version/report，candidate/current 隔离正确。
- 无正式行程时天气条能够展示安全空态，未伪造 Provider 事实。
- 1440×900 与 390×844 均未发现横向页面溢出。

### 4.2 真实反例

- 北京市 → 北京 → 全市的正常创建请求返回 `Region city must belong to its province`。
- 广州行程明确设置首日 18:00 到达，候选首项仍安排在 09:00；数据库中的边界时间正确，但规划命令未携带它们。
- Java 接受 `schemaVersion=3` 的混合 legacy/structured constraints，Python 在 Provider 前拒绝，task 长时间停在 `QUEUED`，数据库只有 `PLANNING_QUEUED`。
- Java 接受并持久化伪造的 `providerPoiId=B-FAKE-RELEASE-AUDIT` 与任意合法范围坐标。
- `WAITING_USER` 页面默认先铺满 11 条规则技术详情；候选标题位于 y≈2445，远离 900px 首屏，同时直接显示英文 reason code 与 `hard-validator-v5`。

## 5. P0 冻结阻断项

### P0-1：到达 / 离开时间只落库，不进入规划快照

**影响**：首日与末日活动可能被放在用户尚未到达或已经离开的时间，Hard Validation 仍可能基于错误输入给出结论。

**代码证据**：

- `PlanningTaskService.java` 创建 `TripSnapshot` 时只携带 title、destination、start/end date、status、version、constraints，record 本身没有 `arrivalAt/departureAt`。
- Python `TripSnapshot` 同样无这两个权威字段；AMap planner 继续从可为空的 legacy constraints arrival/departure 读取时间。

**真实复现**：数据库保存 `2026-08-20 18:00 +08:00`，候选首项仍为 `2026-08-20 09:00 +08:00`。

**最低修复与验收**：

1. 新增规划命令版本，将权威 `arrivalAt/departureAt` 明确加入 snapshot；不得原地修改已发布契约。
2. Java shared fixture → 实际 outbox JSON → Python model/schema 做双语言测试。
3. Golden 场景锁定晚到、早离、跨时区与边界相等行为；真实 Compose 主链断言候选首末活动不越界。

### P0-2：Java 与 Python 对 schemaVersion 3 混合约束语义不一致

**影响**：Java 接受并发布任务，Python 在 Provider 前拒绝；任务不能产生 completion/review/failed 终态，用户看到永久排队。

**代码证据**：

- Java 允许 legacy `mustVisitPlaces` 与空 refs 共存；任一 anchor ref 又会把整体约束提升为 schema 3。
- Python schema 3 强制 names/refs 严格平行。
- 现有 Java 与 Python 测试分别手工构造输入，没有消费 Java 实际 outbox body 的跨语言测试。

**真实复现**：`accommodation.placeRef` + legacy `mustVisitPlaces=["陈家祠"]` + 空 `mustVisitPlaceRefs` 被 Java 接受；Agent 日志出现 `rejecting invalid planning command`，task 保持 `QUEUED`。

**最低修复与验收**：

1. 统一迁移策略：要么 Java 在持久化时将 legacy 列表完整升级为 typed refs，要么新版本契约显式支持混合态；两端必须逐字一致。
2. 对 worker command validation failure 增加 fail-safe terminal failure，禁止永久 `QUEUED`。
3. 增加 Java HTTP → task/outbox → Python `PlanningCreateCommand` → outcome 的真实跨层测试。

### P0-3：Meal binding 按位置 zip，可能把晚餐绑定成午餐

**影响**：抵达日只有晚餐活动但存在午餐/晚餐窗口时，唯一晚餐被绑定为 LUNCH，形成错误 PASS/FAIL/UNKNOWN；这会污染权威 Feasibility Report。

**代码证据**：`validation_projection.py` 先固定生成 LUNCH、DINNER 窗口，再将没有 meal type 的 MEAL locator 按位置 zip。抵达日 planner 正常只生成 DINNER，因此不是人为边界条件。

**最低修复与验收**：

1. Meal activity 必须携带明确 meal type，投影按 identity/type 关联，禁止位置推断。
2. 覆盖仅午餐、仅晚餐、两餐、禁用餐、跨午夜与抵达/离开日。
3. 修复前保存 RED，修复后验证 report 不产生错误硬结论。

## 6. P1 冻结前必须关闭

### P1-1：直辖市无法创建

级联选择器会为北京、上海等生成相同的 provinceCode/cityCode，Java `validateRegion` 却拒绝二者相等。真实浏览器已复现北京创建 400。必须建立直辖市明确模型或允许受控的同码组合，并覆盖北京、上海、天津、重庆。

### P1-2：地点真实性链路未闭环

- 到达、返程、住宿仍是自由文本输入，不符合“必须从候选选择”。
- 约束编辑模型不保留三个 anchor PlaceRef，无改动保存也可能丢失结构化身份。
- 服务端只校验 PlaceRef 形状，不验证是否由候选接口签发；伪造 ref 已真实 200 持久化。
- Python anchor 仍按名称搜首个候选，must-visit 的 id 未命中后仍可退回同名文本，结构化选择可能静默变成另一个 POI。
- 切换目的地不会清空旧城市 chips，也未取消/忽略旧城市在途搜索响应。

修复应采用服务端签发的 opaque candidate token 或等价 issuance 校验，并让精确 POI identity 沿 Java → 契约 → Python planner 全链保持；有 typed id 时禁止同名降级。

### P1-3：创建页仍存在四个时间字段

顶层 `arrivalAt/departureAt` 与下方约束编辑器中的 arrival/departure time 同时出现，存在冲突来源，也不满足已批准的“两项时间代替四项信息”。应删除 legacy 时间输入，只保留两个权威 datetime，并完成契约迁移。

### P1-4：候选内容优先级与信息密度未达到验收目标

`FeasibilityReportPanel` 在候选之前，并默认展开 PASS/UNKNOWN/NOT_APPLICABLE、reasonCode、repair rule id 与 validatorVersion。“我的要求”也持续展示大量“未设置”。真实 1440×900 页面中候选远在首屏之外。

最低 UI 语义：

- 候选概要、日期导航和主要风险先显示；验证详情默认折叠。
- 默认只突出 FAIL/UNKNOWN 聚合，PASS/NA 与技术字段进入“查看技术详情”。
- reasonCode、UUID、validatorVersion 不作为普通用户主界面信息。
- 未设置的可选约束不占固定卡片高度。
- Playwright 必须直接断言候选 bbox 在 900px viewport 内并位于验证详情之前。

### P1-5：已发布 candidate/replan v1 契约被新字段事实性改义

CREATE 已进入新结构，但 replan/candidate validation 仍发布 `schemaVersion=1`，同时携带 schema 3 constraints。已发布 JSON Schema 与运行时语义发生漂移。应新增命令版本与 fixtures，保留旧版本 fail-closed，不得继续扩大 v1。

### P1-6：地点搜索存在资源与竞态风险

- Java TTL cache 是无界 `ConcurrentHashMap`，过期项不清理，key 直接拼接存在碰撞可能。
- Python REAL search 每次新建 `httpx.AsyncClient` 且不关闭/复用。
- Web debounce 在城市切换或新查询的 250ms 窗口内未立即失效旧响应，旧城市结果可能覆盖新城市。

应加入有界缓存/淘汰、复用可关闭的客户端，以及 request generation/AbortController；通过并发和长时间查询测试。

### P1-7：WAITING_USER + 已有正式版本时天气联动错误

天气点击逻辑先匹配正式 itinerary，只有没有正式日程时才进入候选分支。重新规划进入 WAITING_USER 时会滚动到旧正式版本并选择旧路线，而不是待评审候选。测试当前只覆盖 itinerary 404。应增加正式版本与候选同日共存的 App/E2E 反例，WAITING_USER 必须优先候选。

### P1-8：B13 验收证据尚未收口

- `execution-report.md` 仍是 `IN_PROGRESS`，测试数字仍写 337，实际为 339。
- plan 承诺的 35 项“需求 → 测试 → 证据”矩阵未落盘。
- Web coverage 使用人工白名单，未纳入 `TripDashboard.vue`、`TripDetail.vue`、`TripWorkspace.vue`、`TripBoundaryEditor.vue`、`CityCascadePicker.vue`、`lib/api.ts` 等 B13 高风险文件。
- `PlaceAutocomplete` 实际覆盖约 71% statements / 63% branches，低于关键模块 80% 门禁。
- E2E 的 1440×900 用例只证明天气区与 review 容器关系，没有证明候选在首屏。

修复后 coverage 应至少覆盖全部 B13 生产文件，执行报告必须如实更新并保留本次 NEEDS_CORRECTION 历史。

## 7. 非阻断观察

- 81–120 字地点关键词可能通过外层校验后在内部 `PoiSearchRequest` 的 80 字限制处变成 5xx，应统一上限并映射为 4xx。
- Agent 返回 malformed 200 body 时部分路径可能逃逸安全错误映射，应增加候选 null/结构错误反例。
- DEFAULT/DISABLED meal window 是否参与 overlap 的语义需统一，避免“禁用”仍造成约束冲突。
- 天气/城市情报并发同步可能发生较晚响应覆盖较新结果，建议统一 generation guard。
- 活跃规划期间改名会递增 trip version，可能导致任务 stale；需明确标题是否属于规划基线。
- 地点搜索客户端未复用 access-token refresh 链，登录刚过期时体验不一致。

## 8. 安全审查结论

未发现置信度 ≥80% 且具有具体利用链的 B13 新增安全漏洞：地点搜索受全局 authenticated 保护；内部 token 比较与缺失配置 fail closed；Provider key 未进入响应且日志会脱敏；Vue 无 `v-html`，天气外链有 HTTPS/域名限制；新增查询使用参数绑定，无 shell/template/eval 路径。

伪造 PlaceRef 在当前权限模型下只能污染本人行程，归类为业务完整性与真实性阻断，不归类为越权/数据泄漏安全漏洞。

## 9. 冻结授权条件

只有同时满足以下条件，下一轮验收才可给出 `RELEASE_READY`：

1. P0-1 至 P0-3 全部以 TDD RED → GREEN 关闭。
2. P1-1 至 P1-8 全部关闭，或由用户明确书面降级且不破坏地点真实性/契约兼容/权威验证。
3. Java 实际 outbox body 通过共享 JSON Schema 与 Python model；真实 Compose 主链不再出现永久 QUEUED。
4. 晚到/早离、仅晚餐、直辖市、精确 POI、目的地切换、WAITING_USER+正式版本共存成为 Golden/E2E 场景。
5. 全量 Python、Java、Web、E2E、Flyway、Compose、links、diff、secret 门禁重新独立通过。
6. B13 execution report 状态、数字、矩阵与实际证据一致。
7. 独立验收报告最终明确 `PASS / RELEASE_READY_AND_AUTHORIZED_FOR_GIT_CLOSEOUT`。
8. 完成 Git 收口后，才允许 push、创建/更新 PR、合并并打冻结 tag；冻结动作本身另做远端预检。

## 10. 最终决定

**B13 不允许提交收口，不允许 push，不允许将当前工作树标记为正式版本。**

建议下一批命名为 `B13_FIX`，按顺序先关闭跨层正确性（时间、schema、meal），再关闭地点真实性与 UI 信息架构，最后统一补齐覆盖率、真实 Compose golden 和执行证据。修复实现与独立验收必须由不同 Agent 执行。
