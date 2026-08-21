# B18-A Acceptance Report

- 验收日期：2026-08-18
- 验收角色：独立验收 Agent（只读，未修改任何生产代码）
- 依据：`docs/execution/B18/audit.md`（根因基线）、`docs/execution/B18/plan.md`（§3 B18-A Design + §12 验收标准）、`docs/execution/B18/execution-report-a.md`（开发方声明，以下所有结论均经独立复跑，不采信声明本身）

---

## 1. Verdict

```
PASS
```

B18-A 核心目标全部达成：must-visit 强匹配已收敛为 exact identity（structured=providerPoiId，legacy=normalized exact name），substring boost 彻底消失，candidate recall 不再被 must-visit 关键词截断（6 个关键词全执行），exact 正佳广场仍被可靠保留。剩余正佳 sibling（2 个）以普通 20 分候选身份入选，属于 B18-C/D 观察项，不构成 R2/R3 回归。未发现 B18-A 范围内的阻塞或非阻塞缺陷。

---

## 2. Scope Reviewed

| 项 | 结果 |
| --- | --- |
| 代码审计 | `planning/candidates.py`、`infrastructure/amap/planning_provider.py` 全文精读；`domain/shared.py`（candidate_keywords/MAX_POI_QUERIES）；全仓 grep must-visit substring 残留 |
| 测试 | `tests/test_b18_a_recall.py`（A1-A7）独立复跑 8 passed；相关既有测试 90 passed |
| Golden | `C:\Windows\Temp\opencode\b18_a_golden.py` 独立复跑（Stage 1-5 全采集） |
| pytest | 全量 1543 passed / 37 skipped（独立执行，`--basetemp` 可写路径） |
| ruff | `All checks passed!`（独立执行） |
| workspace | 已记录 baseline；无法逐行证明 unstaged 历史归属（B15/B16/B17 混合），见 §3 |
| provider evidence | 开发方 Smoke 1（真实 AMAP POI 层，6 keyword + 2 meal，0 POI 限流）；本次验收未重复消耗真实配额（POI 层行为已由 A5/A7 + Golden 独立证明；route 限流与 B18-A 无关，不阻塞） |

---

## 3. Workspace Baseline

| 项 | 值 |
| --- | --- |
| branch | `codex/feasibility-foundation` |
| HEAD | `d10e70cf354d096300c4a348d6aef585b8d82dc8` |
| dirty state | 59 个 tracked 文件修改 + untracked（`docs/execution/B18/`、`tests/test_b18_a_recall.py`、`.omo/`、`.serena/`、`.workbuddy/` 等），全部为 B15/B16/B17/B18 在途 |
| 历史归属 | **无法从 unstaged workspace 完全证明每一行的历史归属**（candidates.py 72 行 diff、planning_provider.py 343 行 diff 混有既有批次内容）；本报告审计 B18-A 增量语义的正确性，而非行级 git 归属 |
| 未执行 | 未执行任何 `git reset / restore / checkout . / stash / clean` |

---

## 4. Must-Visit Identity Acceptance

| 场景 | 结果 | 证据 |
| --- | --- | --- |
| Structured exact ID（正佳广场/B00140TFHO） | ✅ 命中 `MUST_VISIT_MATCH`，score=120 | A1 独立复跑 PASS；Golden Stage 3/4 |
| Same-name different-ID（正佳广场/OTHER_ID，有 refs） | ✅ **不命中**（exact id 优先，name 不覆盖 id） | A3 子测试 1 独立复跑 PASS；`is_must_visit_poi`（candidates.py:275-276）`must_visit_provider_ids` 非空时仅 `poi.provider_id in ids` |
| Legacy exact-name（无 refs，正佳广场==正佳广场） | ✅ 命中（normalized alphanumeric casefold **精确相等**） | A3 子测试 2 / A4 独立复跑 PASS；`is_must_visit_poi`（candidates.py:277-281） |
| Substring sibling（小林蓝鳄正佳广场/B0MDA73DXY） | ✅ 不命中，score=20，**不被过滤**（保留为普通候选） | A2/A4 独立复跑 PASS；Golden Stage 3（`must_visit_match=False`） |

**fail-closed 确认**：structured 路径下 providerPoiId 是最高优先级 identity；同名不同 id 的候选在结构化路径**必然**判 false（不存在 name 覆盖 id 的第三条路径）。

**全仓残留检查**（grep `MUST_VISIT_MATCH` / `must_visit.*in searchable` / substring 模式）：
- `MUST_VISIT_MATCH` 仅出现在 candidates.py:155（排序 key，前缀匹配 reason）与 :205/:211（reason 生成）——均在 `is_must_visit_poi` 判定通过后
- **无任何** `must_visit ... in searchable` / contains 形式的强匹配残留
- `_text_key(preference) in searchable`（candidates.py:192）为 `PREFERENCE_MATCH`（+40 普通偏好匹配），非 must-visit 路径，不算残留
- `_matches_any`（:252-254）仅用于 avoid_places（排除列表）语义，与 must-visit 无关

---

## 5. Ranking Acceptance

| 项 | 修复前（audit 复现） | 修复后（独立复跑） |
| --- | --- | --- |
| `MUST_VISIT_MATCH` 命中数 | 5（正佳本体 + 4 sibling） | **1**（仅 exact B00140TFHO） |
| sibling score | 120（+100 boost） | **20**（基础分） |
| exact boost | +100 | +100 保留（exact 命中） |
| pinned 行为 | exact id 绕过 cutoff | **保留**：`pinned_provider_ids=must_visit_ids`（planning_provider.py:366）；A6 独立复跑 PASS（低分 exact 必去点仍入选） |

---

## 6. Recall Acceptance

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 旧数量 early-stop 移除 | ✅ 已删除 | `_collect_pois`（planning_provider.py:1521）`for keyword in keywords:` 无条件全执行；`len(ranking.selected) >= required_count` 与 `required_preference_queries` 在代码中仅存注释提及（:1508-1509），无执行路径 |
| rank 移出循环 | ✅ | `_collect_pois` 不再调用 rank；由 `_plan_with_skeleton` 统一 rank 一次（:353） |
| MAX_POI_QUERIES 硬边界 | ✅ 保留 | `domain/shared.py:36`（=6）+ `candidate_keywords` `[:MAX_POI_QUERIES]`（:224）；`_collect_pois` 的 keywords 唯一来源是 `candidate_keywords`，10+ 关键词输入会被截断到 6，无绕开路径（A5 断言 `len(map_provider.calls) == len(keywords)`） |
| exploration 执行 | ✅ 6 个关键词全执行 | A5/A7 独立复跑 PASS；Golden Stage 2（正佳广场/美食/历史/景点/博物馆/公园） |
| 结构化完整性检查 | ✅ 保留 | `structured_ids <= recalled_ids` 检查（:1549-1551 日志）+ 调用方 pin + `MUST_VISIT_UNAVAILABLE` fail-closed 不变 |

---

## 7. Golden G1（独立复跑）

脚本：`C:\Windows\Temp\opencode\b18_a_golden.py`（开发方脚本，验收方独立执行；AMAP 返回形状与真实 DB trip `ac27972d` 一致）

### Stage 1 — Constraint
```
must_visit_places = ('正佳广场',)
ref name=正佳广场  providerPoiId=B00140TFHO  coord=(113.327019,23.132145)  district=天河区
resolved exact must-visit identity = {'B00140TFHO'}
```

### Stage 2 — Keyword Execution
```
query 1: 正佳广场  returned=5      ← must-visit，返回 5 个正佳相关候选
query 2: 美食      returned=4
query 3: 历史      returned=4
query 4: 景点      returned=8
query 5: 博物馆    returned=1
query 6: 公园      returned=2
total POI keyword queries executed = 6   ← 无早停
```

### Stage 3 — Candidate Pool（13 个 eligible，关键行）
| providerPoiId | name | source | score | must_visit_match |
| --- | --- | --- | --- | --- |
| B00140TFHO | 正佳广场 | 正佳广场 | **120** | **True** |
| B0MDA73DXY | 小林蓝鳄正佳广场 | 正佳广场 | **20** | **False** |
| B0IAJKLSO9 | 广州天河正佳广场销服一体店 | 正佳广场 | 20 | False |
| B00140W2J2 | 广州正佳广场万豪酒店 | 正佳广场 | 20 | False |
| B0FFJJ8VJ1 | 广正烧(正佳广场店) | 正佳广场 | 20 | False |
| B0AAA001-008 | 越秀公园/广州塔/陈家祠/沙面岛/白云山/广东省博物馆/天河体育中心/广州动物园 | 美食/历史/景点/博物馆/公园 | 20 | False |

### Stage 4 — Ranking
```
must_include= True  score=120  B00140TFHO   正佳广场      reasons=(VALID_CITY_AND_METADATA, MUST_VISIT_MATCH:正佳广场)
must_include=False  score= 20  B0AAA007     天河体育中心   reasons=(VALID_CITY_AND_METADATA,)
must_include=False  score= 20  B0MDA73DXY   小林蓝鳄正佳广场 reasons=(VALID_CITY_AND_METADATA,)   ← 无 MUST_VISIT_MATCH
...
```

### Stage 5 — Final Itinerary
```
DAY 2026-08-20 (ARRIVAL_DAY)   08:00 到达 / 09:00 正佳广场 B00140TFHO / 11:45 天河体育中心 / 14:30 小林蓝鳄正佳广场 / 17:15 越秀公园 / 返回
DAY 2026-08-21 (FULL_DAY)      09:00 广东省博物馆 / 12:00 广州塔 / 13:15 广州天河正佳广场销服一体店 / 17:03 陈家祠 / 返回
DAY 2026-08-22 (DEPARTURE_DAY) 09:00 越秀公园 / 12:00 沙面岛 / 13:15 广州动物园 / 19:00 离开
SUMMARY:
  exact 正佳广场 (B00140TFHO) in itinerary : True
  mall-family POIs placed                  : [B00140TFHO, B0IAJKLSO9, B0MDA73DXY]  ← 本体 + 2 sibling（普通候选）
  non-mall POIs placed                     : [越秀公园, 广州塔, 陈家祠, 沙面岛, 广东省博物馆, 天河体育中心, 广州动物园]
```

### G1 PASS 门禁（独立判定）
- [x] exact 正佳广场（B00140TFHO）进入 itinerary
- [x] `MUST_VISIT_MATCH` 只命中 exact identity（5→1）
- [x] sibling 不再因名称包含正佳广场获得 +100（120→20）
- [x] exploration keywords 正常继续执行（6 次）
- [x] 正常广州候选重新进入 candidate pool 并入选（7 个非正佳 POI）

**剩余 sibling 判定**：D1 小林蓝鳄正佳广场、D2 销服一体店以 `must_visit_match=False`、score=20 的普通候选身份被 region/score 排序选中——**不属于 R2/R3 回归**，登记为 B18-C/D follow-up evidence（无 geo/category/diversity objective 的独立问题）。

---

## 8. Before / After

| 维度 | Before（audit 复现） | After（验收独立复跑） |
| --- | --- | --- |
| `MUST_VISIT_MATCH` 命中数 | 5 | **1** |
| 正佳相关 sibling score | 120 ×4 | **20 ×4** |
| exploration query count | 0（正佳 query 后早停） | **6**（全部 MAX_POI_QUERIES） |
| 候选池构成 | 正佳 keyword 56% 建筑内 | 6 关键词来源混合；8 个普通广州 POI 进入候选池 |
| 最终行程正佳内部 POI | 5/9 | 2/8（均为普通 20 分候选）+ exact 本体 |
| exact 必去保留 | ✓ | ✓（must_include=True，pinned 机制未削弱） |

---

## 9. Regression（独立执行）

```
targeted:  tests/test_b18_a_recall.py                     → 8 passed
related:   tests/test_candidate_ranking.py
           tests/test_must_visit_recall.py
           tests/test_golden_matrix.py
           tests/test_planning_context_v3.py
           tests/test_daily_schedule.py
           tests/test_poi_quality.py                       → 90 passed
full:      pytest -q --basetemp=%LOCALAPPDATA%\Temp\pytest-b18a-acceptance-full
                                                           → 1543 passed, 37 skipped, 1 warning, exit 0
ruff:      ruff check src/trip_agent tests                 → All checks passed!
```

说明：默认 `C:\Windows\Temp\pytest-of-*` 的 ACL 问题（WinError 5，影响使用 `tmp_path` 的 CLI 模块测试）为**环境问题非代码问题**——指定可写 `--basetemp` 后全量通过，不阻塞验收。

---

## 10. Provider / Performance

| 项 | 观察 |
| --- | --- |
| POI query count（设计变化） | 修复前 1-2 次（早停）→ 修复后恒 ≤6 次（`MAX_POI_QUERIES` 硬边界）；开发方真实 AMAP Smoke 1 实测 6 keyword + 2 meal = 8 次，**0 次 POI 限流** |
| POI latency | 真实 AMAP 平均 377ms/次，6 次串行 ≈2.3s，规划总耗时 4.06s（2 日）——无严重 regression |
| Route rate limit | 开发方 Smoke 2 触发 AMAP **route** API 限流（日配额/QPS），非 POI 层、非 B18-A 逻辑问题；B18-A 不修改 route 调用 |
| Cache | 真实链路 Redis cache 未在本轮验证 cache hit（B18-A 不改变 route cache key） |

1~2→6 次 POI 查询属于 B18-A 的有意设计变化（plan.md §8 已测算：POI 搜索 6 次封顶、与 route 预算 96 独立），轻微增长不构成 defect，未重新引入旧 early-stop。

---

## 11. Scope Audit

| 检查项 | 结果 |
| --- | --- |
| B18-B 触碰 | ✅ 无：`RouteRequest(mode="DRIVING")` 仍在（planning_provider.py:1087-1093，属 B18-B 范围，保留正确）；`transit_mode.py` 不存在；无 WALKING_THRESHOLD / WALKABLE_HAVERSINE |
| B18-C/D 触碰 | ✅ 无：candidates.py / planning_provider.py 无 diversity / MMR / radius / same-area / parent-complex / category-quota 逻辑 |
| 生产文件范围 | ✅ 仅 `planning/candidates.py`、`infrastructure/amap/planning_provider.py`（增量）+ 新测试 `tests/test_b18_a_recall.py`；无 contract / Java / DB migration / Web 修改 |
| 领域对象 | ✅ 未新增 required/exploration 领域类（逻辑分离在 `_collect_pois` 内完成） |

---

## 12. Defects

```
None.
```

（B18-A 范围内未发现缺陷。发现的全部遗留现象——剩余 sibling 以普通候选入选——经代码与数据验证属 R4/R5 范畴，非本批回归。）

---

## 13. Follow-ups

| 编号 | 内容 | 与 B18-A verdict 的关系 |
| --- | --- | --- |
| B18-B | Walking baseline / route mode selection（消除 `mode="DRIVING"` 硬编码） | 独立批次，不影响本 verdict |
| B18-C | itinerary diversity objective（剩余 sibling 问题的正式解） | 独立批次，Golden 中 2 个普通 sibling 入选即其输入证据 |
| B18-D | parent/complex semantic dedup（正佳广场 vs 小林蓝鳄正佳广场同坐标不同 id） | 独立批次，需数据模型扩展，暂缓 |
| （观察） | 真实 AMAP route 配额限制影响完整 compose 冒烟 | 环境限制，非代码缺陷 |

---

## 14. Final Recommendation

```
B18-A 允许收口：YES
建议进入 B18-B：YES
```

理由：R2/R3 已由 RED→GREEN 锁定并经独立复跑确认；exact identity 安全（structured fail-closed 已验证）；substring boost 全仓消失；exploration 恢复；exact must-visit 保留；全量回归 1543 passed + ruff 0 errors；scope 无污染。剩余 sibling 为普通候选，属 B18-C/D 独立问题，按计划登记后进入下一批。
