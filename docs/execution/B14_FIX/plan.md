# B14_FIX 执行计划：关闭 B14 全系统验收发现的冻结前缺陷

- 文档状态：生效中；交付 `B14_FIX_READY_FOR_REVIEW`（unstaged、未 commit、未 push）
- 基线 branch：`codex/feasibility-foundation`；HEAD：`89236ea731b3d9aea55a81f96101940299f2c983`；staged 空
- 关联：[B14 缺陷报告](../B14/defects.md)（只读）、[B14 执行报告](../B14/execution-report.md)、[B14 场景目录](../B14/scenario-catalog.md)
- 禁止：reset/stash/checkout/restore/clean/rebase/amend；stage/commit/push；处理 .omo/、.serena/、docs/audits/、.env；操作用户 trip-pilot-prod；放宽安全校验；以放大超时冒充修复
- 不得创建/修改：B14_FIX/acceptance-report.md、B14/acceptance-report.md

## 修复矩阵（严格 TDD：先 RED 后 GREEN）

| 轮 | 缺陷 | 修复 | RED 测试 |
| --- | --- | --- | --- |
| R1 | D01 天气同步 502（P1 冻结阻断） | Python producer 输出满足 Java 安全契约（contentHash 64-hex/title/sourceUrl/finalUrl/sourceHost/excerpt/fetchedAt/facts/归因），CITY_INTELLIGENCE 200 原子落库；Web 就地中文错误 | Java 真实响应校验路径 RED + 共享 fixture |
| R2 | D02 versions owner 隔离（P2） | Controller/Service/Mapper 统一 owner-scoped trip 检查，统一 404 | Java 集成 RED（B 访问 A versions 当前 200） |
| R3 | D03 跨城市 PlaceRef（P2） | selection token 绑定规范化城市上下文（region code 稳定比对），跨城市 400 | Java 集成 RED（广州 token 建北京 201→400） |
| R4 | D04 无结果地点 502（P2） | POI_NOT_FOUND→200+candidates=[]；timeout/429/500/认证保持安全错误；Web 中文文案 | Python/API RED（无意义词 502→200 空） |
| R5 | D05 规划进度可观测性（P2） | 真实阶段边界发 progress（排名/路线/求解/修复启动/结果发布），不伪造 REPAIRING；UI 未触发/进行中/已完成中文 | Python RED（阶段事件缺失）+ Web RED（未执行文案） |
| R6 | D06 Web 全量 flaky | 未清理 timer/fetch/wrapper/资源排查、afterEach 完整 cleanup、必要时拆分；连续三轮 400/400、flaky rate 0 | 稳定性门禁（非"单跑通过"） |

## 延后项（仅登记，不实现）

D07（REAL_ONLY 缺 Key 文案）、D08（基础设施 POI 候选质量）、D09（AMap route rate-limit 观察）——execution-report 明确登记为未解决。

## 门禁

Python 全量 pytest + ruff（check/format）+ guide/places/progress 定向；Java mvn verify + JaCoCo + Flyway 干净/升级 + guide/owner/token 集成；Web unit 连续三轮 400/400 + typecheck + build + coverage（B13/B14 生产文件每文件 ≥80%）+ Playwright；隔离 Compose 8 项验收；仓库 links/diff/secret/staged/保护目录。

## 完成条件

D01-D05 全部关闭；D06 连续三轮 400/400；全门禁通过；无新 P0/P1；输出 `B14_FIX_READY_FOR_REVIEW` 后停止（不提交；由独立验收 Agent 复跑并写 acceptance-report）。
