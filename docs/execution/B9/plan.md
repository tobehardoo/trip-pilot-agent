# B9 规划输入与主动放置完善计划

状态：`IN_PROGRESS`

## 基线

- 分支：`codex/feasibility-foundation`；
- 起始 HEAD：`f3f09f1be28f417454244cae068663e28cd6395e`（B8 收口提交 feat(platform): validate edit and rollback candidates）；
- B8 已提交并通过独立验收；
- `.omo/`、`.serena/`、`docs/audits/` 为保护目录，不纳入批次。

## 目标

所有生产规划入口（AMap create、Demo create、Local replan、AMap/Local repair 后重投影、B8 EDIT、B8 ROLLBACK）提供一致、非伪造的 TripSkeleton/ValidationInputs；规划器在具备 VERIFIED/fresh/hard-eligible 营业证据时主动放置到合法窗口；显式 meal window 接入真实放置；visit duration 绑定跨入口一致。

## 非目标

- B10 结构化日志与全量 golden matrix；
- 公网部署、TLS、生产告警；
- push、PR 或远端交付；
- 修改 opening_resolver 的 tier/fresh-stale/effective_date/Temporary Closure 安全语义；
- 修改生产 SQL 与 Java 契约（除非契约真实改变且经门禁验证）。

## 子任务

### B9.1 统一验证投影边界

- 抽取 `candidate_validation.py` 中通用投影为共享模块，Demo/replan/edit/rollback/repair 共用；
- AMap 保留 fetched_at 与真实 POI evidence 专用边界；
- Demo：多日住宿 UNRESOLVED、不伪造酒店/坐标/POI ID/城市中心/official evidence、缺真实营业证据必须 UNVERIFIED；
- Replan：从最终候选重建 skeleton/inputs，repair 后重建 binding/locator，dayType/locked/provider metadata 不丢；
- AREA_ESTIMATED/UNRESOLVED 只导致 continuity UNKNOWN；单日行程 0 overnight boundary；显式住宿无法解析不得静默变区域估计。
- 入口矩阵 RED 测试先行。

### B9.2 Opening-aware 主动放置

- CandidateActivity 增加类型安全不可变可用时间语义（不耦合 Worker DTO）；
- 营业窗口仅来自 resolver 最终 selected evidence（VERIFIED_WINDOW/VERIFIED_CLOSED + hard_constraint_eligible + effective_date 适用 + 未过期无冲突）；
- UNKNOWN/STALE/CONFLICTING/ineligible 不形成硬放置窗口、不得 VERIFIED PASS；
- 放置满足 opening interval + last-entry + recommended duration + 当日窗口 + 固定安排 + 餐饮占用 + buffer；
- 多窗口确定性：最早合法窗口优先，相同用稳定 POI/order tie-break；
- VERIFIED_CLOSED 普通候选排除；must-visit 对应日期 VERIFIED_CLOSED 必须 NEEDS_REPAIR/不可行；
- AMap provider evidence hard-eligible=False 不得升级为正式硬窗口；
- 路线 forward-fit 推离窗口时最终 Hard Validation 必须抓住。

### B9.3 Visit Duration Profile

- scheduler 以 recommended_minutes 放置；min/max 由 Hard Validator 判定；
- profile 带 source/confidence/version；system-default 不得声称 provider/official；
- 秒/微秒超过 max 必须 FAIL、精确等于边界 PASS；
- repair 后重建 binding/locator；
- 现有实现已满足的部分补 characterization 与跨入口测试。

### B9.4 显式 Meal Window

- planning domain 独立 meal window constraint（不 import Worker contract）；
- 显式 window 优先默认建议；每个适用日期必须有对应 MEAL binding；
- 冲突时确定性调整或真实 FAIL/NEEDS_REPAIR，不静默丢餐；
- AMap 无法解析餐厅时保留 unresolved meal placeholder；
- Demo 必须放置 meal placeholder；无显式 window 规则 NOT_APPLICABLE、有 window 不得错误 NOT_APPLICABLE；
- 跨午夜 meal window 按真实日期处理；repair/replan 后重新验证。

### B9.5 跨入口一致性与安全回归

- 表驱动矩阵：入口 × 住宿 × opening × meal；
- 证明：相同事实不同入口相同结论；Demo 缺证据只能 UNVERIFIED；未确认住宿不产生 continuity PASS；opening unknown 不产生 opening PASS；正式版本仅 VERIFIED 可持久化；B8 edit/rollback 门禁不回归；B7 repair 最多三轮不猜证据。

## 门禁

- Python：全量 pytest + ruff check + ruff format --check（新增文件）+ Feasibility/新增代码 coverage ≥80%；
- Java：Java 21 下 `mvn verify`（0 failures/errors、JaCoCo、Flyway 干净库、无新增非必要 migration）；
- Web：pnpm test / test:coverage / typecheck / build / CI=1 test:e2e；
- 仓库：check_markdown_links / git diff --check / staged 空；
- 独立验收 PASS 后才允许提交。

## 文件范围

允许修改：
- apps/agent-service/src/trip_agent/application/candidate_validation.py、replan_service.py
- apps/agent-service/src/trip_agent/planning/**（daily_schedule.py、visit_duration.py、trip_skeleton.py、candidates.py 等）
- apps/agent-service/src/trip_agent/infrastructure/**（demo/amap 投影）
- apps/agent-service/src/trip_agent/feasibility/**（inputs.py、rules/meal.py、rules/opening.py、rules/duration.py 等，仅在与生产一致性必要时）
- apps/agent-service/tests/**（新增 B9 测试）
- docs/architecture/规划工作流.md、事件契约.md（仅契约真实改变时）、行程真实性与旅行骨架.md
- docs/product/项目路线图.md、系统完善长期执行与验收总控计划.md
- docs/execution/B9/**

禁止修改：contracts/**（除非字段真实改变且 Java/Python 同步）、apps/travel-server/**（除非契约同步必须）、apps/web/**（除非 Web 必须适配）、Flyway、Rabbit、.env、保护目录。
