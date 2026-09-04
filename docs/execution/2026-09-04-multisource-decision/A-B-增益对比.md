# M1 闭环 — 多源证据决策机制「真生效」A/B 增益对比

日期：2026-09-04
范围：仅本环（接线 + A/B 证明）。不做 M2 定时刷新 / 多城市泛化 / UGC 爬虫。
上游：M0 commit `1e47424`（`candidates._evidence_guide_bonus` / `evidence_fusion` / `planning_provider` L403 死代码点）。

***

## 0. 结论（TL;DR）

**能证 B ≥ A。** 把 `guide_evidence.facts` 接进 `CandidateRanker.rank(evidence_facts=...)` 后：

- B 在「同一 POI 高可靠 vs 低可靠冲突」上**正确裁定高可靠/更新源**（reason 携带来源），A 平权无法区分；

- B 对「高可靠/近期 fact」的 POI 加分**显著高于**「OCR/过期 fact」的 POI（陈家祠 +30 vs 沙面 0，差分 30 分；A 两者都 +25 无差别）；

- B 的 `evidence_strength` 随证据充分度升降（多源一致 92 > 单弱 22；可裁定冲突仍 90\<strong），且 `overall == weighted_overall_score` 不变量成立；

- DEMO happy path 在 B 下仍 feasible + 非空行程 + 低分仅披露不拦截。

无需诊断返工：接线一次到位，分档在真实 provider 转换路径 `guide_evidence_validated_facts` 上被端到端测试命中。

**不能证（需网络/真实后端）**：

- 真实「高德路径 vs 开放数据源」的**联网抓取**无法在本环境执行（`data.gz.gov.cn` / AMap / QWeather 均需在线且凭据）；本环按任务允许用「仓库离线数据 + 可离线构造 fact」走通了「多源 → guide\_evidence.facts → 融合 → 分档」。

- 真实前端点击未执行（见 §6 原因）。

***

## 1. 改动（接线，不动既有契约）

仅改 `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py` + 新增一个测试文件。

### planning\_provider.py

1. **新增** **`_SOURCE_TYPE_RELIABILITY`** **映射 +** **`guide_evidence_validated_facts()`（纯函数，无 I/O）**
   `GuideFactEvidence`（wire 契约）只带 `source_type`，不带 `reliability_level`；把 `source_type` 映射到融合层共享的规范可信度词汇，再包成 `ValidatedFact` 给 ranker 的 `evidence_facts`。

   - `OFFICIAL_ATTRACTION/OFFICIAL_TOURISM → OFFICIAL_PORTAL`（rank5）

   - `CITY_INTELLIGENCE → CURATED`（= 注册表第二可信源 `guangzhou-culture-open-data` 声明的等级，二者对齐）

   - `PUBLIC_GUIDE_URL/PASTED_TEXT/TEXT_FILE → PUBLIC_GUIDE`

   - `XIAOHONGSHU_SHARED_TEXT → UGC`

   - `IMAGE_OCR → OCR_UNVERIFIED`

   - 排除 `WEATHER`（该路径单独走天气策略）。
2. **`rank(...)`** **调用补传** **`evidence_facts=guide_evidence_validated_facts(command.payload.guide_evidence.facts)`** **与** **`evidence_now=datetime.now(UTC)`**。
   死代码点 L403 关闭：运行时从「只 `guide_statements` 平权」切到「`_evidence_guide_bonus` 分档 + 权威时限」。
3. **不重复加分**：`_score` 内 `_evidence_guide_bonus` 命中即用分档，`elif` 才回退 `guide_statements` 平权 +25 —— 同一 fact 两者二选一，绝不叠加。facts 缺失/全弱时 `_evidence_guide_bonus` 返回 `None` 走旧平权，happy path 不变。

未改 `evidence_fusion` / `trusted_facts` / `extractor` 的任何对外签名，仅消费它们。

### 新增 tests/test\_m1\_ab\_multisource\_decision.py（7 个用例）

见 §3，覆盖任务 1/3/4 的断言 + 任务 2 的离线闭包。

***

## 2. 获取手段「多源」现状（任务 2）

**现状（代码事实）**：`guide_evidence.facts` 契约本就允许一条 POI 带多个 `source_type`（高德 `CITY_INTELLIGENCE`、官方攻略 `OFFICIAL_ATTRACTION/OFFICIAL_TOURISM`、`PUBLIC_GUIDE_URL`、`IMAGE_OCR`、`XIAOHONGSHU_SHARED_TEXT` 等）——因此「同 POI ≥2 来源」在运行时入口已可达。缺口只在可靠性未接线。

**本环补强**：

- `_SOURCE_TYPE_RELIABILITY` 让每个 `source_type` 落到明确可信分档，多源才能「分档」。

- `CITY_INTELLIGENCE` 对齐到第二可信源的 `CURATED` —— 知识库 path（含 open-data）与 `knowledge/sources/guangzhou.toml#guangzhou-culture-open-data` 声明的等级**一致**，同一 fact 无论走哪条采集路径强度一致。

**离线闭包证明**（`test_m1...::test_second_source_reliability_matches_knowledge_tier_offline`）：
CITY\_INTELLIGENCE fact → `guide_evidence_validated_facts` → `CURATED`（=注册表）→ 与 OFFICIAL fact 融合 → `VERIFIED` + ≥2 `sources` + `evidence_strength ≥70` → 分档后该 POI 排名高于弱源对手。

**能证/不能证**：

- 能证（离线）：多源 → guide\_evidence.facts → 融合 → 分档 的**闭环逻辑**。

- 不能证：`data.gz.gov.cn` 的**真实联网抓取**（需在线）未跑；`test_source_registry_m0::test_second_source_to_l1_to_scoring_closure_offline` 已证明注册表→L0→L1→L3 无需网络即可闭合。

***

## 3. A/B 增益对比表（同输入、确定性、同一批多源 fact fixture）

固定时钟 `NOW=2026-09-01 UTC`；A=旧（仅 `guide_statements` 平权 +25，无 `evidence_facts`、无证据维度）；B=新（`evidence_facts` 分档 + `evidence_strength` 维度）。

| 项                                             | A（旧）              | B（新）                                            | 增益              |
| --------------------------------------------- | ----------------- | ----------------------------------------------- | --------------- |
| 陈家祠（OFFICIAL 近期 fact）rank 分                   | 45（20 基数 + 25 平权） | **50**（20 + 30 `GUIDE_FACT_MATCH:OFFICIAL_GOV`） | +5，且 reason 带来源 |
| 沙面艺术馆（OCR 过期 fact）rank 分                      | 45（平权 +25）        | **20**（仅基数，过期 OCR 分档=0）                         | −25（弱源不再虚高）     |
| 同一 POI 冲突（官方近期 vs OCR 过期，value 冲突）rank 分      | 45（无法区分来源）        | **50**（裁定官方新源，reason=OFFICIAL\_GOV）             | +5，正确仲裁         |
| 双 POI 区分度（官方 vs OCR）                          | 差分 **0**（平权无法区分）  | 差分 **30**                                       | 可区分（≥20 达标）     |
| `evidence_strength`（多源一致 OFFICIAL+OPEN\_DATA） | —（旧无证据维度，=中性 80）  | **92**                                          | 随充分度上升          |
| `evidence_strength`（单弱 UGC）                   | —（中性 80）          | **22**                                          | 随充分度下降          |
| `evidence_strength`（可裁定冲突）                    | —                 | **90**                                          | 强源仲裁后仍高         |
| `overall`（多源 / 无证据 / 单弱 / 冲突）                 | 98（无证据进 B 基线）     | 99 / 98 / 93 / 99                               | 不变量成立，弱证据仅披露不拦截 |

**不变量**：所有 B 用例如 `overall_score == weighted_overall_score(dimensions)`（模型 + 测试双断言）。

***

## 4. 断言对应

| 任务要求断言                                               | 测试                                                                                                                | 结果                                                                           |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| 1) 冲突时 B 裁定高可靠/更新源（A 平权被弱源误导/不区分）                    | `test_b_conflict_resolution_beats_a_flat`                                                                         | A 无来源 reason、两 POI 等分；B 带 `GUIDE_FACT_MATCH:OFFICIAL_GOV` 且 ≥A               |
| 2) 高可靠近期 fact 的 POI 在 B 中比 OCR/过期 POI 更高，reason 携带来源 | `test_b_high_reliable_recent_poi_outranks_ocr_stale_poi`                                                          | B 差分 30，reason=OFFICIAL\_GOV；A 平权差分 0                                        |
| 3) evidence\_strength 随充分度升降 + overall==weighted 不变量 | `test_b_evidence_strength_rises_with_sufficiency_overall_invariant`                                               | 多源 92>单弱 22；不变量成立                                                            |
| 4) DEMO happy path 仍 feasible + 非空 + 低分仅披露不拦截        | `test_b_happy_path_without_evidence_still_completes` / `test_b_conflicting_evidence_discloses_but_does_not_block` | feasible=True、非空、EVIDENCE\_STRENGTH 披露不拦截                                    |
| 运行级：provider 转换真走分档                                  | `test_runtime_conversion_wires_guide_evidence_into_tiering`                                                       | OFFICIAL\_ATTRACTION→OFFICIAL\_PORTAL、IMAGE\_OCR→OCR\_UNVERIFIED；喂 rank 命中分档 |
| 任务2：第二可信源进 guide\_evidence 融合分档                      | `test_second_source_reliability_matches_knowledge_tier_offline`                                                   | CITY\_INTELLIGENCE→CURATED==注册表；融合 VERIFIED                                  |

***

## 5. 验证数字

- 新增测试 `tests/test_m1_ab_multisource_decision.py`：**7 passed**。

- 相关既有回归（M0 定向 + 规划 provider/语义 + outcome/worker，均离线、无外部服务），全绿：

  - `test_m0_candidate_evidence / test_source_registry_m0 / test_plan_evaluation_evidence / _evaluator / _models / test_acquisition_registry` 等：**48 passed**

  - 规划 provider/planning 语义/worker/上下文/provider\_\*（`test_candidate_ranking` … `test_provider_*`）：**196 passed**

  - outcome/worker module/failed-event：**47 passed**

- `ruff check src tests`：**0 错误**；`ruff format` 通过。

- 未跑（既有环境问题，属外部服务，会网络挂起）：real amap / amqp(rabbit) / redis(postgres) / places\_api lifespan 等真实后端依赖文件（如 `test_real_amap_provider.py`、`test_amqp_worker.py`）。与本改动无关，按既有约定排除。

***

## 6. 真实点击 / 运行级验证（任务 4）

- **运行级证明（已做，离线）**：任务 3 的确定性 fixture 直接驱动 `guide_evidence_validated_facts`（provider 真实转换函数）+ `CandidateRanker.rank` + `PlanEvaluator.evaluate`，覆盖「规划说明」证据相关条目的来源/证据维度（`EVIDENCE_STRENGTH` decision + `GUIDE_FACT_MATCH:<reliability>` reason）与行程可行性。

- **真实前端点击未执行原因**：本环境无可用后端容器/真实 AMap 路由网络（离线），前端点击需真实规划栈（Frontend→Java→RabbitMQ→Python→AMap 路由）才能产出来源/证据条目；故以「确定性基准 + 端到端测试」作为运行级证明，真实 UI 点击留待有网/有容器的环境复验。

***

## 7. 下一步（如需）

- 接真实网络后跑一次广州真实规划，确认「TripPilot 的规划说明」出现来源/证据相关条目；

- 如需 `data.gz.gov.cn` 的开放数据真实入库，需为该第二可信源接入采集执行（本环未做联网）。

