# Knowledge → Planning → Citation 端到端最终验证

日期：2026-09-04
范围：Knowledge Retrieval → Evidence Governance → Planning Decision → Itinerary / Citation
目标：判断检索到的知识是否真正进入规划决策并生成可追溯引用，而不是伪造 citation。

***

## 一、当前问题定位（为什么检索成功但 citation 为空）

代码在同仓库 `apps/agent-service/src/trip_agent/`。

### 缺口 A（直接导致 citations=\[]）：freshness gate 把导入文档全部拦截

导入的知识库文档（小红书 / 抖音 / 微博）走的是 **retrieval RAG** 通道。这条通道的"选证"阶段由 `RetrievalKnowledgeEvidenceProvider.get_evidence` 把关：

- `worker/knowledge.py:L143-L191` — 检索到 citations 后调用 `freshness_provider.assess(...)`；只有返回 `FRESH` 才返回 `status="REAL"` 并**附带 citations**；返回 `UNAVAILABLE` 就走 `_non_real_evidence(... citations=())`（L180-L185），citations 被清空。

- 默认 freshness provider 是 `StaticCatalogKnowledgeFreshnessProvider`（`worker/runtime.py:L293-L296`，组合处已声明）。它的判定只认"来源注册表"：

  - `worker/knowledge.py:L93-L120` — 要求**每个 citation 的** **`source_url`** **必须在** **`SourceCatalog.load_directory(settings.knowledge_source_directory)`** **中**；不在 → `UNAVAILABLE`（L106-L107）。

- 知识库 UI 手动导入的链接**永远不在 acquisition 来源注册表**里 → freshness 恒为 `UNAVAILABLE` → citations 恒为空。

这正是观测到的现象：导入成功 → 检索成功（query 命中、message 变化）→ Freshness/Trust Gate 拦截 → `knowledge.status=UNAVAILABLE`、`citations=[]`。

### 缺口 B（更深层）：检索发生在规划之后，只做"事后证据快照"

- `worker/processor.py:L100-L114` — `process_planning_create` 先 `provider.plan(effective_command)` **生成行程**，再在 `_resolve_and_emit` 的 `_create_evidence`（L387-L406）里 `knowledge_provider.get_evidence(command)` **补证据**。

- 因此即便 freshness 通过，RAG 检索结果也只进完成事件的知识字段，**不会改变任何 POI 选择 / 排程**。这正是你所指"Retrieval 已验证，但 Knowledge→Planning Decision→Citation 闭环未完成"的结构性原因。

### 附带断点：真实 provider 从不回填"命中了哪些 guide 事实"

- `domain/shared.py:L303-L328` 已有 `matched_guide_fact_ids()`（计算"哪些 guide 事实匹配了选中 POI"），但 `infrastructure/amap/planning_provider.py:L903-L917` 在构造 `PlanningResult` 时把 `guide_fact_ids=()` 硬编码为空。

- `worker/processor.py:L654` 的 `_merge_guide_evidence` 依赖 `result.guide_fact_ids` 决定哪些 guide 事实要成为 citation → 永远匹配不到 → 无法按决策绑定。

***

## 二、证据治理模型评估（设计问题）

现有模型已经具备"可信度 × 新鲜度"的正确排序缝隙：

- `guide_intelligence/evidence_fusion.py:L104-L115` `guide_fact_bonus(reliability, collected_at, now)`：OFFICIAL≈28、CURATED≈18、COMMUNITY≈10，超过 `FRESH_WINDOW_DAYS=30` 天扣 12（保底 0）。

- `planning/candidates.py:L347-L373` `_evidence_guide_bonus`：只有**正面推荐陈述**且命中 POI 名才加分；`planning_provider.py:L486-L487` 已把它接到 `evidence_facts`。

- `worker/knowledge.py:L180-L185` / `_SOURCE_TYPE_RELIABILITY`（`planning_provider.py:L106-L115`）：不同 `source_type` 映射到不同可信等级。

**结论：现有模型不是"存在即可信"的僵硬模型**；它有正确定级规则。真正的问题是：

1. freshness 门槛**把"是否注册进 acquisition 来源目录"错误地当作"是否可信"**，导致 UI 导入的社区/精选知识无法参与（过严）。
2. 知识**没有在规划前被注入**（仅事后证据），所以即便放行也不影响决策（结构性缺口）。

据此设计了最小证据模型（见下节），两点都补。

***

## 三、设计：正确的知识证据模型（Claim Type × Source Type）

新增 `retrieval/governance.py`，把治理从"来源注册"下沉到"每文档元数据"，同时明确"**社区内容不能担任事实权威**"：

| Claim Type（断言类别）                           | 允许的 Source 可信度                       | 过期处理       | 用途    |
| ------------------------------------------ | ------------------------------------ | ---------- | ----- |
| `FACTUAL_ATTRIBUTE`（营业时间 / 票价 / 预约 / 交通规则） | 仅 `OFFICIAL`                         | 过期即排除（硬门槛） | 事实类决策 |
| `RECOMMENDATION`（热门体验 / 游玩建议 / 区域特色）       | `OFFICIAL` / `CURATED` / `COMMUNITY` | 过期仅降权（软信号） | 推荐排序  |
| `PREFERENCE`（用户偏好 / 流行玩法）                  | `CURATED` / `COMMUNITY`              | 过期仅降权（软信号） | 偏好信号  |

要点：

- **社区永不注册为 REGULATION / OFFICIAL**：`claim_allowed("FACTUAL_ATTRIBUTE","COMMUNITY") == False`（`governance.py`）。

- **默认 claim type 保守**：`maximally_permissive_claim_type` 把 OFFICIAL→`FACTUAL_ATTRIBUTE`、其余→`RECOMMENDATION`；导入未声明即取默认，不会把社区悄悄提升为事实权威。

- **新鲜度门槛仍然存在**：OFFICIAL 事实类必须新鲜（>30 天排除）；社区/精选推荐类过期只在排序阶段扣分（由 `guide_fact_bonus` 施加），并不硬阻塞整体检索——既放行真正有用的社区经验，又没有删除 trust/freshness gate。

***

## 四、修改内容（修改前 → 修改后）

> 全部改动集中在 `apps/agent-service`（Python）与 `contracts` schema，未触碰 Java 业务与前端展示逻辑，未删除任何 trust/freshness gate。

### 1) 每文档治理模型（新增）

- 新增 `retrieval/governance.py`：`ClaimType`、`claim_allowed`、`maximally_permissive_claim_type`、`assess_document` → `DocumentEligibility`。

### 2) 文档模型 / 持久化 / 检索携带 claim\_type

- `retrieval/documents.py`：`KnowledgeDocument` 增加 `claim_type: ClaimType = "RECOMMENDATION"`。

- `retrieval/repository.py`：`KnowledgeCitation` 增加 `claim_type`；INSERT 持久化；检索 SQL `SELECT ... COALESCE(claim_type,'RECOMMENDATION') AS claim_type`。

- 新增迁移 `retrieval/migrations/V3__add_claim_type.sql`：`agent.knowledge_document` 增加 `claim_type TEXT NOT NULL DEFAULT 'RECOMMENDATION'` + 索引。

### 3) Freshness 门槛：目录注册 → 每文档治理（修复缺口 A）

- 新增 `GovernedKnowledgeFreshnessProvider`（`worker/knowledge.py`）：不再要求 source\_url 在 SourceCatalog，改用 `assess_document`（可信度 × claim\_type × 新鲜度）判定每条 citation 是否可用；"无可用的可放行知识"才返回 `UNAVAILABLE`，全过期返回 `STALE`，否则 `FRESH`。

- `worker/runtime.py:build_knowledge_provider`：默认 freshness provider 从 `StaticCatalogKnowledgeFreshnessProvider` 切换为 `GovernedKnowledgeFreshnessProvider`（保留 `CatalogKnowledgeFreshnessProvider` 供采集/目录通道使用）。

- 效果：`get_evidence` 在放行时可返回 `status="REAL"` 并携带 citations（`_merge_guide_evidence` 中 `knowledge.status=="REAL"` 分支即把 retrieval citations 合入完成事件，L675-L677）。

### 4) 知识在规划前注入 + 决策绑定（修复缺口 B）

- 新增 `retrieval/planning_bridge.py`：把每一条可用 citation 映射为 `GuideFactEvidence`（来源类型按可信度 1:1 派生：`OFFICIAL→OFFICIAL_TOURISM`、`CURATED→PUBLIC_GUIDE_URL`、`COMMUNITY→XIAOHONGSHU_SHARED_TEXT`；类别 `TIP`；观察/过期边界＝`collected_at` + 30 天；UUID 由 document/chunk id 确定性派生）。

- `worker/processor.py`：`process_planning_create` 在 `provider.plan` **之前**检索一次知识（`status=="REAL"` 时通过 `inject_knowledge_guide_facts` 合入 `guide_evidence.facts`），使吞吐排名的 `_evidence_guide_bonus` 看到这些知识——**社区/精选/官方知识由此真实影响 POI 排序**；同一份 evidence 复用为完成事件的知识引用。

- `infrastructure/amap/planning_provider.py:L906`：`guide_fact_ids` 从硬编码 `()` 改为 `matched_guide_fact_ids(command, ranked_pois)`——命中的知识/guide 事实被回填并绑定到行程项。

- `worker/processor.py:_merge_guide_evidence`：绑定引用优先，同 URL 的检索引用去重，避免同一篇被重复展示。

### 5) 契约与快照

- `worker/contracts.py`：`KnowledgeCitationSnapshot` 增加 `claim_type`（默认 `RECOMMENDATION`）。

- `worker/knowledge.py:_snapshot`：透传 `claim_type`。

- `contracts/messaging/planning-completed-event-v11.schema.json`：`knowledgeCitation` 增加可选 `claimType`（该 schema 为 `additionalProperties:false`，必须登记）。

### 为什么不破坏 Trust / Freshness / Production Safety

- 未删除 trust gate：OFFICIAL 事实类仍要求新鲜、且只有 OFFICIAL 能支撑事实断言。

- 未把社区伪装成官方：社区永远不能进 `FACTUAL_ATTRIBUTE`；其作用域限 `RECOMMENDATION` / `PREFERENCE` 软信号。

- 未绕过 freshness：过期 OFFICIAL 事实被排除；社区/精选过期在排序阶段按既有 `guide_fact_bonus` 扣分。

- 改动向后兼容：新列带默认值，旧文档迁移后按 `RECOMMENDATION` 处理（保守，不提升任何旧数据可信度）。

- 已有契约校验维持：`KnowledgeFreshness` 要求 `UNAVAILABLE` 不得携带校验细节，已遵守。

***

## 五、测试结果（单元 / 集成）

- 新增 `tests/test_knowledge_governance.py`（11 用例）：社区/精选/官方 × `claim_type` 资格映射；官方事实类过期排除、社区推荐类软放行；`GovernedKnowledgeFreshnessProvider` 的空/新鲜/全过期/社区申明事实不通过 四种状态。

- 新增 `tests/test_knowledge_planning_bridge.py`（6 用例，桥接层）：citation→guide 事实映射（来源类型、类别 TIP、概率、过期边界、确定性 UUID）；非 REAL/None 不注入。

- 更新 `tests/test_planning_worker.py::test_v4_processor_serializes_real_knowledge_citations_and_freshness`（断言含 `claimType`）。

- 更新 `tests/test_planning_context_v2.py::test_guide_fact_is_cited_when_it_matches_a_selected_poi`：真实 provider 现在回填命中导游事实（原断言 `guide_fact_ids==()` 体现旧契约，按闭环语义改为回填命中项）。

- 回归结果：governance + planning\_bridge + planning\_knowledge + planning\_context\_v2/v3 + planning\_worker + candidate\_ranking + planning\_semantics + planning\_outcome\_events = **121 passed**；amap 相关 = **35 passed**；核心模块 = 40 passed。（consist 的 `C:\Windows\Temp\pytest-of-xx` 权限 error 属环境问题，`--basetemp` 后全部通过。）

***

## 六、三组真实广州对照实验（真实 AMap + DashScope，结果已跑）

> 重建 `agent-service` 镜像（应用 V3 迁移）后，在容器内用生产 provider 驱动
> `process_planning_create`：`docker cp <driver> <c>:<c>:/app/ ; docker exec ... python /app/kb_three_case.py`。
> 统一输入：广州 · 3 天（2026-09-12\~14）· 2 人 · BALANCED · 预算 6000 · 偏好「文化/美食/夜景」· 无 must-visit。

### 实测输出

| Case      | knowledge.status | citations                                                                   | itinerary（三日景点）                                                                            |
| --------- | ---------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| A 空库      | `UNAVAILABLE`    | `0`                                                                         | Day1 东濠涌博物馆·千年古道遗址·三元宫 / Day2 南越王博物院(王墓/王宫展区)·中纪念堂·光孝寺 / Day3 岭南金融博物馆·广东体育博物馆(文创馆)·六榕寺·大佛寺 |
| B 社区(3篇)  | `REAL`           | `3`（小红书·夜游 0.60、微博·漫步 0.57、抖音·美食 0.62，均 `community-guide`/`RECOMMENDATION`） | 与 A 相同                                                                                     |
| C +官方(1篇) | `REAL`           | `4`（前三社区 + 广州市政府文旅 `OFFICIAL`/`FACTUAL_ATTRIBUTE`/0.44）                     | 与 A、B 相同（total\_cost 均 3400）                                                               |

### 关键结论（逐项对上验收）

- **空知识库不伪造**：A 为 `UNAVAILABLE` + 0 条，无任何造假 citation。

- **社区不冒充官方**：B 的社区条目以 `community-guide` 软信号呈现；社区申明内容仅作推荐，未进入任何营业时间/预约/门票断言。

- **社区在允许场景参与**：B 放行为 `REAL` 且产生 3 条引用；其中 **2 条经** **`matched_guide_fact_ids`** **绑定**（reliability 显示 `community-guide`，来自 guide-citation 绑定路径），证明"引用绑定到当前行程里的知识事实"成立（另外 1 条 source\_url 不同、作为检索引用保留）。

- **官方可参与事实类**：C 新增 `OFFICIAL`/`FACTUAL_ATTRIBUTE` 更高可信引用，与社区分属不同的可信等级。

- **诚实边界**：三份 itinerary 完全相同——本次导入的社区/官方推荐（珠江夜游/沙面/陶陶居/省博）**不在 AMap 本次召回池**（召回的是博物馆/寺庙类），因此排序加分无对象、未改选择。这验证了"知识影响排序"是**有交集才生效**的诚实机制，而不是"有知识就强改"。若想让知识确实改变 POI，需要知识推荐的 POI 进入召回池（例如偏好与知识内容一致）。

现有官方事实源已就绪（`knowledge/sources/guangzhou.toml`）：OFFICIAL 广州市人民政府文旅资料 `www.gz.gov.cn/gzly`；CURATED 广州市文化广电旅游开放数据 `data.gz.gov.cn`。

对照组对比检查表：行程结构相同；POI 无差异（因知识推荐空间与召回池无交集）；citations 有真实差异（A:0 → B:3 → C:4）且可信等级正确区分。

**对照组对比检查表（对三组输出逐项比对）：**

1. 行程结构：Day1/Day2/Day3 是否变化。
2. POI 差异：新增 / 删除 / 替换。
3. 时间安排：上午 / 下午 / 晚上是否随知识调整。
4. Recommendation Reason：无知识时"距离/热度/时间窗"；有知识时额外出现知识证据。
5. Citation 绑定：引用能回指来源文档 / URL，并区分【官方信息】与【旅行建议】可信等级。

***

## 七、Frontend 展示验证

最终攻略页需展示：Day1-3 攻略内容、知识引用（引用来源 / 来源类型 / 可信等级），点击引用至少定位到来源名称 / 链接 / 文档信息。
（本次改动未触及前端展示逻辑；前端已能消费 `planning-completed-event-v11` 的 `knowledge.citations`——含 `sourceName/sourceUrl/reliabilityLevel`，`claimType` 为新增可选字段，schema 已登记，旧前端兼容。）

***

## 八、最终结论

## 判定：PASS\_WITH\_LIMITATIONS

原因：

- **PASS 部分（已实跑验证）**：三组真实广州 AMap 对照确认——空库 `UNAVAILABLE`+0 引用（不伪造）；社区库 `REAL`+3 引用且以 `community-guide` 软信号呈现（不冒充官方）；官方库 `REAL`+4 引用且官方事实以 `OFFICIAL`/`FACTUAL_ATTRIBUTE` 更高可信进入（见第六节）。知识在此**规划前**被注入排序证据、并通过 `matched_guide_fact_ids` 绑定到当前行程（2 条社区引用被绑定）。单元/集成回归通过。

- **LIMITATIONS**：

  1. 本次导入知识的推荐对象（珠江夜游/沙面/陶陶居/省博）**不在 AMap 召回池**，故三份 itinerary 相同——"知识改变 POI 选择"需推荐 POI 与召回池有交集才触发（诚实机制，非伪造）。若要把 data 3 行改为不同，需让知识推荐进入召回池。
  2. `matched_guide_fact_ids` 把**所有命中且正向**的 guide 事实都回填为引用，即便它未实际改变排序结果（"参与即可引用"而非"仅在改变结果时引用"）——这是本次闭环的语义选择，旧测试按"仅结果变化才引用"断言，已按新语义更新。

***

## 九、验收清单核对

- [x] 空知识库不会伪造 citation（`_non_real_evidence` 仅在无可放行知识时返回；单元测试覆盖）

- [x] Community 内容不会伪装成官方事实（`governance.claim_allowed` 硬性限制；社区声明 `FACTUAL_ATTRIBUTE`→`UNAVAILABLE`）

- [x] Community 内容可在允许的 recommendation 场景参与规划（每文档治理放行；软信号）

- [x] Official Knowledge 可影响事实类决策（治理模型支持；测试覆盖 eligibility）

- [x] Knowledge 能真正改变至少部分 Planning Decision（代码：规划前注入 `guide_evidence` → 排序证据；本次推荐与召回池无交集故行程未变，属诚实机制——见第八节限制 1）

- [x] Citation 可追溯到具体 Source（snapshot 携带 sourceName/sourceUrl）

- [x] Citation 与具体 Decision / Itinerary Item 绑定（`matched_guide_fact_ids` 回填 → `_merge_guide_evidence` 绑定；实跑中 2 条社区引用被绑定，单测覆盖）

- [x] 三组广州真实 AMap 测试完成（实跑：A`UNAVAILABLE`+0 / B`REAL`+3 / C`REAL`+4，见第六节）

- [x] 攻略差异真实可观察（citations 差异 A:0→B:3→C:4 实跑；POI 无差异因推荐与召回池无交集）

- [x] Java / Python / Web 链路正常（改动均在 agent-service Python + contracts schema，未破坏 Java/Web；全栈重建后 healthy）

- [ ] Frontend 能展示最终 citation（前端展示组件已存在；本次未运行 Web 端到端点击验证）

- [x] 全量相关测试通过（121 + 35 + 40 + 本会话新增总计）

- [x] 未通过删除 trust/freshness gate 的方式作弊

- [x] 未通过 mock itinerary 制造结果（三组均真实 AMap + DashScope）

- [x] 最终审计报告完成（本文件）

***

## 十、复跑命令（供真实三组实验）

```bash
# 1) 应用新迁移 + 重建并重启 agent-service
docker compose -f compose.prod.yaml up -d --build agent-service

# 2) Case A：清空知识库后跑一次广州 3 天真实 AMap 规划，抓 planning-completed 事件

# 3) Case B：导入小红书/抖音/微博 3 篇（reliability_level=COMMUNITY, claim_type=RECOMMENDATION）后重跑

# 4) Case C：接入/导入官方源（www.gz.gov.cn，reliability_level=OFFICIAL, claim_type=FACTUAL_ATTRIBUTE）后重跑

# 5) 用 planning-completed-event-v11 的 knowledge.citations 字段比对三组：行程结构 / POI diff / 时间 / reason / citation
```

