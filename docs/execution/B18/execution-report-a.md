# B18-A Execution Report — Must-Visit Identity + Candidate Recall 修复

- 实施日期：2026-08-18
- 依据：`docs/execution/B18/audit.md`（P18-R2 / P18-R3）、`docs/execution/B18/plan.md`（§3 B18-A Design）
- 状态：**READY_FOR_ACCEPTANCE**

---

## 1. Scope

本批仅实施 **B18-A**，解决两个已确认根因：

- **P18-R2**：must-visit keyword 主导 recall，并触发 candidate early-stop（`_collect_pois` 数量早停）
- **P18-R3**：must-visit 名称 substring 匹配导致 sibling POI 获得 +100 boost（`MUST_VISIT_MATCH`）

明确不在本批范围（未实施、未触碰）：B18-B（route mode selection）、B18-C（diversity objective）、B18-D（parent/complex dedup）、contract/Java/DB migration/Web 修改。

## 2. Workspace Baseline

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `d10e70cf354d096300c4a348d6aef585b8d82dc8` |
| 工作区状态 | B15/B16/B17 在途修改 59 个 tracked 文件 + 若干 untracked（`docs/execution/B15-B18/`、`contracts/fixtures/planning-completed-event-v10/` 等）保持原样 |

本轮未执行任何 `git reset / restore / checkout . / stash / clean`。目标文件 `candidates.py`（+17 行）与 `planning_provider.py`（+245 行）在实施前已包含 B15/B16/B17 在途修改；本轮仅做最小增量修改，未覆盖既有内容。

## 3. RED Evidence（A1-A7）

测试文件：`apps/agent-service/tests/test_b18_a_recall.py`（本轮新增，未触碰在途修改的既有测试文件）。

| ID | 断言 | baseline（修复前） | expected | actual（修复后） |
| --- | --- | --- | --- | --- |
| A1 | 结构化 exact identity（正佳广场/B00140TFHO）命中 `MUST_VISIT_MATCH`，score=120 | **baseline already GREEN**（现有 substring 在 exact-name 场景行为一致；RED 阶段因 `must_visit_provider_ids` API 缺失 TypeError） | PASS | PASS |
| A2 | 小林蓝鳄正佳广场/B0MDA73DXY 无 boost，score=20，不被过滤 | **RED**（substring 误判 +100） | PASS | PASS |
| A3 | 同名不同 id（有 refs）不命中；legacy（无 refs）exact-name 命中 | **RED**（无结构化参数 API，无法表达 exact-id-only） | PASS | PASS（2 个子测试） |
| A4 | legacy `正佳广场` exact-name 命中、`小林蓝鳄正佳广场` 不命中 | **RED**（substring 误判 sibling） | PASS | PASS |
| A5 | 正佳 keyword 返回充足候选后，全部 exploration keyword 仍执行（= MAX_POI_QUERIES） | **RED**（只执行 `['正佳广场','历史']` 即早停） | PASS | PASS |
| A6 | exact 正佳广场（低普通分）不被 ranking 淘汰，仍入选 | **baseline already GREEN**（B13_FIX R9 pinned 机制已存在） | PASS | PASS |
| A7 | 候选池同时含 exact must-visit 与 exploration 候选 | **RED**（early-stop 后 exploration 候选缺失） | PASS | PASS |

RED 阶段实测：`7 failed, 1 passed`（A5/A7 为真 RED：`map_provider.calls` 仅 `['正佳广场','历史']`；A1-A4 为 API 缺失 TypeError；A6 baseline GREEN）。
GREEN 阶段实测：`8 passed`（A3 两个子测试）。

## 4. Production Changes

| 文件 | 修改 | 原因 |
| --- | --- | --- |
| `apps/agent-service/src/trip_agent/planning/candidates.py` | ① 新增共享纯函数 `is_must_visit_poi(poi, must_visit_places, must_visit_provider_ids=None)`：有 ids 时只按 exact providerPoiId 判定，无 ids 时 normalized exact-name 相等（alphanumeric casefold），彻底禁止 substring/contains；② `rank()`/`_score()` 新增 `must_visit_provider_ids: frozenset[str]` 参数；③ `_score` 的 `MUST_VISIT_MATCH` 从 `_text_key(place) in searchable` 改为共享 identity 判定 | R3 核心：消除"ranking substring 判定"与"`_is_must_visit_poi` exact 判定"两套标准漂移；sibling 不再凭名称获 +100 |
| `apps/agent-service/src/trip_agent/infrastructure/amap/planning_provider.py` | ① `_is_must_visit_poi` 委托共享 `is_must_visit_poi`（签名不变，兼容既有测试）；② `_plan_with_skeleton` 的 `rank()` 调用新增 `must_visit_provider_ids=frozenset(must_visit_ids)`；③ `_collect_pois` 删除 `required_preference_queries` 与 `len(ranking.selected) >= required_count` 数量早停、循环内 rank 调用；关键词循环无条件执行全部 `MAX_POI_QUERIES(6)` 个 keyword；保留结构化完整性检查（循环后显式记录 `must_visit_ids_missing_from_recall` 日志，缺失 id 仍由调用方 pin + 既有 `MUST_VISIT_UNAVAILABLE` fail-closed 兜底） | R2 核心：recall 不再被第一个 must-visit keyword 截断；raw candidates 收集完后由 `_plan_with_skeleton` 统一 rank 一次 |

未修改：contract / Java / DB migration / Web / `domain/shared.candidate_keywords` / `CandidateRanker.rank` 的其它参数 / scheduling。

## 5. GREEN Evidence（定向验证）

命令（`apps/agent-service` 下）：

```
./.venv/Scripts/python.exe -m pytest tests/test_b18_a_recall.py -v
```

结果：**8 passed**（A1、A2、A3×2、A4、A5、A6、A7）。

相关既有回归（实施后）：

```
./.venv/Scripts/python.exe -m pytest tests/test_candidate_ranking.py tests/test_must_visit_recall.py tests/test_golden_matrix.py tests/test_planning_context_v3.py -q
→ 26 passed
```

## 6. Golden G1 Trace（广州 + must_visit=正佳广场）

追踪脚本：`C:\Windows\Temp\opencode\b18_a_golden.py`（诊断脚本，未提交生产源码）。AMAP 返回形状与真实 DB trip `ac27972d` 一致（正佳广场 + 同坐标 sibling）。

### Stage 1 — Constraint

```
must_visit_places = ('正佳广场',)
ref name=正佳广场  providerPoiId=B00140TFHO  coord=(113.327019,23.132145)  district=天河区
resolved exact must-visit identity = {'B00140TFHO'}
```

### Stage 2 — Keyword Execution

```
query 1: keyword='正佳广场'  returned=5     ← must-visit，返回 5 个正佳相关候选
query 2: keyword='美食'      returned=4
query 3: keyword='历史'      returned=4
query 4: keyword='景点'      returned=8
query 5: keyword='博物馆'    returned=1
query 6: keyword='公园'      returned=2
total POI keyword queries executed = 6
```

不再出现"正佳 query 足够 → stop"。

### Stage 3 — Candidate Pool（Top 13，按 rank 序）

| providerPoiId | name | source | type | score | must_visit_match |
| --- | --- | --- | --- | --- | --- |
| B00140TFHO | 正佳广场 | 正佳广场 | 购物服务;商场;购物中心 | 120 | **True** |
| B0AAA007 | 天河体育中心 | 景点 | 体育休闲;体育场馆 | 20 | False |
| B0MDA73DXY | 小林蓝鳄正佳广场 | 正佳广场 | 风景名胜… | 20 | **False** |
| B0AAA006 | 广东省博物馆 | 历史 | 文化场馆;博物馆 | 20 | False |
| B0AAA008 | 广州动物园 | 景点 | 风景名胜;动物园 | 20 | False |
| B0AAA002 | 广州塔 | 美食 | 风景名胜;现代建筑 | 20 | False |
| B0IAJKLSO9 | 广州天河正佳广场销服一体店 | 正佳广场 | 购物服务… | 20 | **False** |
| B00140W2J2 | 广州正佳广场万豪酒店 | 正佳广场 | 住宿服务… | 20 | **False** |
| B0FFJJ8VJ1 | 广正烧(正佳广场店) | 正佳广场 | 餐饮服务;中餐厅 | 20 | **False** |
| B0AAA004 | 沙面岛 | 美食 | 风景名胜… | 20 | False |
| B0AAA005 | 白云山风景名胜区 | 历史 | 风景名胜… | 20 | False |
| B0AAA001 | 越秀公园 | 美食 | 风景名胜;公园 | 20 | False |
| B0AAA003 | 陈家祠 | 美食 | 风景名胜;名胜古迹 | 20 | False |

重点：小林蓝鳄正佳广场 `must_visit_match=False`、score=20。

### Stage 4 — Ranking（前 5 名）

```
must_include= True  score=120  B00140TFHO    正佳广场      reasons=(VALID_CITY_AND_METADATA, MUST_VISIT_MATCH:正佳广场)
must_include=False  score= 20  B0AAA007      天河体育中心    reasons=(VALID_CITY_AND_METADATA,)
must_include=False  score= 20  B0MDA73DXY    小林蓝鳄正佳广场  reasons=(VALID_CITY_AND_METADATA,)
must_include=False  score= 20  B0AAA006      广东省博物馆    reasons=(VALID_CITY_AND_METADATA,)
must_include=False  score= 20  B0AAA008      广州动物园     reasons=(VALID_CITY_AND_METADATA,)
```

不再出现"5 个正佳内部 POI 全部因 MUST_VISIT_MATCH 同为 120"。

### Stage 5 — Final Itinerary（完整规划链路）

```
DAY 2026-08-20 (ARRIVAL_DAY)   08:00 到达 / 09:00 正佳广场 B00140TFHO / 11:45 天河体育中心 / 14:30 小林蓝鳄正佳广场 / 17:15 越秀公园 / 返回
DAY 2026-08-21 (FULL_DAY)      09:00 广东省博物馆 / 12:00 广州塔 / 13:15 广州天河正佳广场销服一体店 / 17:03 陈家祠 / 返回
DAY 2026-08-22 (DEPARTURE_DAY) 09:00 越秀公园 / 12:00 沙面岛 / 13:15 广州动物园 / 19:00 离开
```

### G1 PASS 门禁

- [x] exact 正佳广场（B00140TFHO）进入 itinerary
- [x] exact providerPoiId 正确 pin（`must_include=True`）
- [x] 名称含正佳广场的 sibling 不再获得 must-visit boost（4 个 sibling 全部 20 分 / False）
- [x] exploration keywords 确实继续执行（6 次查询）
- [x] 正常城市候选重新进入候选池并入选

未要求本批达成：正佳内部只能一个 POI、每天跨多个商圈（B18-C/D 语义）。注：D1/D2 仍有 2 个 sibling 以普通 20 分候选身份被 region/score 排序自然选中——记录为观察（见 §7 Case B 判断），不判 B18-A FAIL。

## 7. Before / After 对比

| 维度 | Before（审计复现） | After（G1） |
| --- | --- | --- |
| `MUST_VISIT_MATCH` 命中数 | 5 个（正佳本体 + 4 sibling） | **1 个**（仅 exact B00140TFHO） |
| 正佳相关 sibling score | 全部 120 | **20**（基础分） |
| exploration query count | 0（正佳 query 后早停） | **6**（全部 `MAX_POI_QUERIES`） |
| 候选来源 | 正佳 keyword 56% 建筑内 | 6 个 keyword 来源混合，普通广州候选进入 pool |
| 最终行程正佳内部 POI | 5/9 | **2/9**（D1 小林蓝鳄、D2 销服一体店，均为普通 20 分候选被 region 排序选中） |
| 最终行程城市候选 | 广州塔/沙面/越秀/陈家祠（分数被压） | 广州塔、越秀公园、陈家祠、沙面岛、广州动物园、广东省博物馆、天河体育中心正常入选 |

**Case 判断**：substring boost 已消失、recall 已修复；但仍有 2 个 sibling 以普通候选身份进入行程，说明 **R4/R5（无 geo/category/diversity objective）是独立真实问题** → 登记 B18-C/D candidate。`itinerary` 明显不再围绕正佳广场（exact 正佳 + 广州其它正常热门 POI）。

## 8. Full Regression

### pytest（全量）

```
./.venv/Scripts/python.exe -m pytest -q --basetemp="$LOCALAPPDATA/Temp/pytest-b18a-tmp"
→ 1543 passed, 37 skipped, 1 warning（exit 0）
```

说明：默认 tmp 路径 `C:\Windows\Temp\pytest-of-xx` 目录 ACL 损坏（`WinError 5`），导致 11 个使用 `tmp_path` 的 acquisition/knowledge CLI 测试 ERROR；该问题与 B18-A 无关（非沙箱运行同样复现、仅影响 CLI 模块），改用用户临时目录 `--basetemp` 后全绿。**B18-A 相关测试全部通过。**

### ruff

```
./.venv/Scripts/python.exe -m ruff check src/trip_agent tests
→ All checks passed!
```

### Compose 质量冒烟

未启动完整 `compose.prod.yaml` 容器栈（Web/Java/RabbitMQ/DB 全链路构建成本高，且真实 AMAP route 配额受限，见 §9）。以 **Python 层真实 AMAP provider**（`PROVIDER_MODE=REAL_ONLY` + 真实 `AMAP_WEB_SERVICE_KEY`）执行两条冒烟：

**Smoke 1 — 广州 2日 must_visit=正佳广场（真实 AMAP）**：`SUCCESS`

```
POI query count=8（6 次 B18-A keyword 查询 + 2 次既有 meal 解析）
route query count=6    rate_limited=0（POI/route 层）
avg POI latency=377ms  total latency=4.06s
行程：D1 到达→正佳广场(B00140TFHO)→华侨新村历史文化街区→广东贡院历史陈列馆→广州酒家→返回
      D2 出发→广东革命历史博物馆→麦当劳(广州交易广场店)→广州警察历史展→三元宫→离开
```

- 规划到达终态 ✓
- exact 正佳广场（B00140TFHO）保留 ✓
- 候选池未被正佳 keyword 截断（6 次 keyword 全执行）✓
- 最终 POI 质量明显改善：1/8 为正佳建筑内，其余为广州各街区历史文化/博物馆/餐饮 ✓

**Smoke 2 — 广州 2日 普通规划 无 must-visit（真实 AMAP）**：`FAILED: PlanningProviderError: AMap route rate limit was reached`（route 层真实限流，非 B18-A 逻辑问题；POI 搜索层无限流）。为不继续消耗配额未重复重试。删除 early-stop 对普通规划的影响已由 A5/A7（模拟 provider）与 Smoke 1（真实 provider，同一 keyword 循环）覆盖验证。

## 9. API / Performance Observation

| 项 | 观察 |
| --- | --- |
| POI keyword query count | 修复前 1-2 次（早停）；修复后恒 ≤6 次（`MAX_POI_QUERIES`），真实冒烟实测 6 次 + 2 次既有 meal 解析 |
| POI search latency | 真实 AMAP 平均 377ms/次；6 次串行 ≈ 2.3s，规划总耗时 4.06s（2 日含 6 条 route），无严重 regression |
| Route query | 2 日 6 次（既有行为，未因 B18-A 改变） |
| Rate limit | **POI 层 0 限流**；Smoke 2 触发 AMAP route API 真实限流（日配额/QPS，与 B18-A 无关）——未重新引入旧 early-stop，仅记录 |
| Cache | 脚本未启用持久化 cache（既有 Redis cache 在 compose 链路启用，本次未验证 cache hit） |

## 10. Follow-ups（仅登记，本轮不实施）

| 编号 | 内容 |
| --- | --- |
| B18-B | Walking baseline / route mode selection（`RouteRequest` 不硬编码 DRIVING、`transit_mode.py`、WALKING threshold） |
| B18-C | itinerary diversity objective（same category/area penalty、diversity score、MMR、must_visit satisfied state machine） |
| B18-D | parent/complex semantic dedup（same building / parent complex / radius dedup、category quota） |

## 11. Scope Audit

- 生产代码仅修改 `candidates.py`、`planning_provider.py` 两文件（增量，未覆盖在途修改）
- 新增 `tests/test_b18_a_recall.py`（A1-A7）
- **无** contract / Java / DB migration / Web 修改
- **无** B18-B 修改（未触碰 `RouteRequest(mode=...)`、未新增 `transit_mode.py`、未改 `TransitLegControl.vue`）
- **无** B18-C/D 修改（无 diversity/radius/同区域/同类别/MMR/去重逻辑）
- 临时追踪脚本位于 `C:\Windows\Temp\opencode\`，未提交生产源码

## 12. Verdict

**READY_FOR_ACCEPTANCE**

B18-A 目标达成：R2/R3 被 RED→GREEN 锁定，并通过"广州 + 必去正佳广场"真实规划（G1 复现形状 + Smoke 1 真实 AMAP）验证——exact 正佳广场保留、sibling 无 boost、recall 不再被 must-visit keyword 截断。剩余"行程仍有 2 个正佳 sibling 以普通候选入选"问题证明 R4/R5 为独立问题，按 §二十四 登记 B18-C/D candidate，**不自动判 B18-A FAIL**。

**B18-A 结束，按指令停止，不自动继续 B18-B。**
