# 05 · 数据模型审计（概念漂移与重复建模）

> 审计性质：PROJECT-WIDE AUDIT ONLY · 2026-08-31
> 核心问题：**同一个业务概念在系统中有多少种名字和数据结构？**

---

## 1. 概念漂移总表（跨语言）

| 业务概念 | 名字/结构（出现位置） | 漂移程度 |
|---|---|---|
| **行程** | Trip（Java trip/TripRecord）+ TripContext（dialog/models.py:47）+ Itinerary（worker/contracts.py:750）+ ReplanItinerarySnapshot（:851）+ CandidateItinerarySnapshot（:1528）+ candidate_itinerary（agent/state.py:286）+ TripSkeleton（planning/trip_skeleton.py:199，自述未进运行时 :22-24）+ 前端 Itinerary/CandidateItinerary/SharedItinerary | 🔴 **8+ 种，严重** |
| **槽位/约束** | ConstraintSlot（agent/state.py:49）+ SlotView（dialog/models.py:25）+ SlotSpec（dialog/service.py:74）+ AgentSlotView（worker/contracts.py:1793）+ 前端 AgentDialogSlotView（api.ts:863）/ AgentSlotViewWire（api.ts:923）/ slotTone 五态（agent-slots.ts:13-25） | 🔴 **6 种** |
| **活动** | ItineraryActivity（contracts.py:618）+ CandidateActivity（daily_schedule.py:159）+ PlacedActivity（:217）+ DayPlanItem（:226）+ 前端 activity 模型（api.ts:471-520） | 🟠 4 种 |
| **必游点** | must_visit_places（:177）+ must_visit_place_refs（:183）+ pinned_provider_ids（candidates.py:99） | 🟠 3 种 |
| **交通模式** | WALKING/TRANSIT/TAXI/DRIVING/AUTO（请求模型）vs 持久化模型（README.md:184 自述区分）+ 前端 CommuteMode（transit.ts:3-4，含 AUTO）vs PersistedCommuteMode（不含 AUTO） | 🟠 2 套 |
| **任务状态** | planning_task 状态（Java 写入 6 值）+ Python 契约状态（worker/contracts.py:1308,1394 等）+ 前端 PlanningTaskStatus 六值（api.ts:190-197） | 🟢 一致（已验证） |
| **可行性状态** | FeasibilityStatus（Java feasibility/FeasibilityStatus.java）+ 前端 feasibility.ts:5 | 🟢 一致 |

## 2. 跨层重复建模的危害案例

### 2.1 前端三套 itinerary 模型（P1）
- `Itinerary`（api.ts:520，正式行程）用 `fromActivityId/toActivityId`（api.ts:471-472）
- `CandidateItinerary`（feasibility.ts:76，候选）用 `fromActivityIndex/toActivityIndex`（feasibility.ts:107-108）
- `SharedItinerary`（api.ts:674，分享只读）
- **后果**：同一"行程-日活动-交通腿"关系在三个结构体中用不同字段名表达；前端靠运行时 safe-reader 兜底（feasibility.ts），无法编译期对齐。若 Java/Python 某侧改字段名，只有运行时报错才发现。

### 2.2 Python 侧五套行程快照（P1）
worker/contracts.py 单文件内并存：`Itinerary`（:750）、`ReplanItinerarySnapshot`（:851）、`CandidateItinerarySnapshot`（:1528）；state.py 有 `candidate_itinerary`（:286）；trip_skeleton.py 有 `TripSkeleton`（:199，364 行，**自述未进入 worker 运行时** trip_skeleton.py:22-24）。同类结构复制 5 份，schema 演进靠复制粘贴改字段。

### 2.3 槽位四模型 + 前端三模型（P1）
同一"待确认约束槽位"在 Python 侧 4 处、前端 3 处定义；前端 `AgentSlotViewWire`（字符串态）与 `agent-slots.ts` 的 `slotTone`（五态含 REJECTED/USER_OVERRIDE）定义不一致，Agent UX 3.0 文档 §P3 自述"AGENT_SLOTS 契约未实施"。

## 3. Java 侧模型生态（数据）

- record **267** 个（itinerary/ItineraryService.java 内部 record 约 60% 行数）、interface 27、DTO 命名类几乎全用 record。
- 同一事件在 Java 有 3 层模型：契约类（PlanningCompletedEvent.java:337）→ Parser 校验 → Record（PlanningTaskCompletionRecord）→ View（TaskEventView）。层级齐全但通过复制字段转换，无映射框架统一处理（MyBatis 注解 SQL 手写映射）。

## 4. DB 层冗余（与 06 交叉）

- **跨表冗余**：trip 表双写边界时间（V35 add_trip_datetime_boundaries 与 trip_constraint 内日期并存）——同一日期事实两个来源（P2）。
- **幂等表复制**：planning_task_event / agent_dialog_message / itinerary_share / guide_import 各自实现 eventId/幂等键查重，无统一幂等抽象（P2）。
- **planning_task 状态元数据双源**：status 存 planning_task 表；错误码/provider/评估从最新 outcome 事件重建（PlanningTaskService.java:725-754）——查询时需拼装两处（P2）。

## 5. 判定

| 发现 | 级别 | 建议 |
|---|---|---|
| 行程概念 8+ 种名字 | **P1** | 收敛为 3 个边界模型：契约模型（Java/Python 各 1）、持久化模型（DB）、展示模型（前端 1）；删除 TripSkeleton（未用）与前端 SharedItinerary（复用 Itinerary） |
| 槽位概念 6 种 | **P1** | 以 worker/contracts.py 的 AgentSlotView 为契约真源，前端 agent-slots.ts 与其对齐，删除 dialog/models.py 的 SlotView 或改为适配层 |
| 前端三套 itinerary | **P1** | 合并为单一类型 + 判别联合（union），字段名统一（fromActivityId） |
| contracts.py 版本复制类 | **P2** | 事件版本用增量/覆盖策略而非整类复制（见 08 §4） |
| DB 日期双写 | **P2** | 以 planning_context_snapshot 为权威，废除 trip 冗余列或加 CHECK 一致性 |
| 幂等表复制 | **P2** | 抽统一 IdempotencyRecord（event_type+event_id+handler 唯一键） |

> 结论：**数据模型层是全系统重复最严重的层**。Java/Python/前端三端各自建模，且 Python 内部与前端内部还有第二层重复。这是"契约版本化"策略（每批次一版本、冻结不删，contracts/messaging/README.md 自述）的直接代价：**为了兼容旧版本，同类结构被复制了 4-11 份**。
