# F-4 验收记录 — 代码库收敛

- 范围：F-0 收敛方案 §F-4（0 基线 → 1 大文件治理 → 2 架构边界 → 3 死代码 → 4 风格 → 5 文档）
- 纪律：每一刀 = 修改 + 单元测试 + Integration Test + Regression Test + Commit；跨文件同批避免半绿窗口
- 验收门：三端完整测试 + 基线对照（F-4.0 INVENTORY 快照）

## 验收门结果（基线对照）

| 端 | 基线（F-4.0 快照） | 验收实跑 | 结果 |
|---|---|---|---|
| Python（agent-service） | 2051 passed / 42 skipped | `pytest -q` → 2051 passed / 42 skipped | ✅ 与基线一致 |
| Java（travel-server） | 626 | `mvn test` → 626 Tests / 0 Fail / 0 Error / 0 Skip | ✅ 与基线一致 |
| Web（apps/web） | 307 | `vitest run` → 29 files / 307 passed | ✅ 与基线一致 |

> 说明：F-4 全程为**行为等同重构 + 死代码/文档收敛**，无功能变更。三端测试与 F-4.0 基线逐一相同，证明收敛未改变任何可观测行为。

## Commit 链（小原子，8 个）

| Commit | 阶段 | 内容 |
|---|---|---|
| `440aa5c` | F-4.0 | INVENTORY.md 收敛基线（Repository / Architecture / Dead Architecture 三件套） |
| `e75d771` | F-4.1 | planning-provider-design.md（职责地图 / Call Graph / Dependency Graph / 边界 / 风险 / 兼容策略） |
| `83f62c0` | F-4.1 | AmapPlanningProvider 拆分：Facade 861 + 6 协作者（poi_recall/opening_hours/anchor_resolution/route_resolution/day_emitter/repair_policy）；8 个测试面委托垫片；monkeypatch 跟随修正 |
| `bcc4b7d` | F-4.1 | INVENTORY 大文件表刷新（2450 → 861） |
| `f89061a` | F-4.2 | D-13：DemoItineraryBuilder 注解改 PlanningBackend 结构协议；processor/amqp 边界评估记录 |
| `25e1219` | F-4.3 | D-11：删除 2 个 100% 未读参数（current_kind/missed）；D-3/D-5/D-7/D-8 判定落档 |
| `cb4f2f3` | F-4.4 | D-9/D-10 过时 docstring 修正（纯注释） |
| `62f0684` | F-4.5 | D-4 关联：README ×5 / 系统架构.md ×4 / adr 索引 ×1 共 10 处 OR-Tools 失实声明修正 |

## F-4.1 设计文档验收标准核对

planning-provider-design.md §Compatibility Strategy 七条：

1. ✅ **模块路径稳定**：`infrastructure.amap.planning_provider` 未移动；组合根 runtime.py 与全部测试 import 零改动
2. ✅ **构造签名不变**：`__init__` 七参签名一字未改；协作者内部组装
3. ✅ **公共 API 不变**：`plan` / `replan` / `repair`（PlanningProvider 协议）原样
4. ✅ **测试面静态方法保留**：`_magnitude_for_poi` 委托 PoiRecaller，2 个测试文件零改动
5. ✅ **私有方法迁移 + 委托垫片**：8 个私有方法（~45 处直调）以纯委托垫片保留，测试零改动
6. ✅ **纯移动零改写**：方法体逐字节搬运，仅 import 与 `self._x → self._y.x` 调用点改写；`_plan_with_skeleton` 编排核心原样（含 B18-A / P2-1 / B17 / R12 决策逻辑）
7. ✅ **验证口径**：针对性单测（172 passed）→ 集成批次（363 passed / 3 skipped）→ 全量回归（2051 / 42）→ ruff 全绿 → 单 commit（`83f62c0`）

## 关键判定（Evidence First，快照纠正）

| 条目 | 判定 | 依据 |
|---|---|---|
| D-3 ConstraintPanel.vue | ✅ 已清理（无需动作） | 文件不存在（236d4de F-1b 已删）；INVENTORY 快照过时 |
| D-5 CREATED/RETRYING/CANCELLING | ⚠️ 保留（非死状态） | 无 Java 写入点但为状态机预留中间态（查询条件 + 语义注释引用）；收紧 CHECK 需不可逆 migration，留给 F-5 |
| D-7 budget_per_person | ✅ 已激活（非死代码） | V3 P2-1 软包络：test_meal_budget.py 专项 + anchor_resolution.py:157 生产读取 + daily_schedule.py:478-481 分支 |
| D-8 终态集合双源 | ✅ 已合并（无需动作） | PlanningTaskEventHub.java 已不存在；单一来源 PlanningTaskEventStreamService.java:22-23 |
| D-11 unused variable ×7 | ✅ 2/7 清理；5/7 保留 | current_kind/missed 100% 未读已删；其余 5 处为 Protocol 契约参数（vulture 误报） |
| D-9/D-10 docstring | ✅ 已修正 | TripSkeleton 已进 worker 校验路径；DecisionTrace reason_codes 已被 6 处构建点使用 |

## 遗留事项（移交 F-5 审计）

- **D-5**：CHECK 约束 9 值 vs 实际写入 6 值——F-5 评估是否值得收紧（需新增 migration + 存量数据核验）
- **D-6**：REPLAN 声明可达性（DECISION_SCHEMA 合法但无 tools 入口）——F-5.2 专项核验
- **D-12**：API_ONLY 端点（无 UI 消费）——F-5.6 记录
- **F-4.1 遗留**：`ItineraryService.java`（2038 LOC）编辑引擎/版本工厂分离（收敛计划 §四.3，F-4 规划内但未排入本轮 P0 刀序）

## Checkpoint

- **F-4 验收通过**：三端测试与基线完全一致（2051/42 + 626/0 + 307），8 个小原子 commit 无半绿窗口
- **基线标签**：建议在 F-5 开始前打 tag（如 `F4-accepted`）或记录 `62f0684` 为 F-5 审计起点
- **下一步**：F-5 最终发布就绪审计（AUDIT ONLY，禁止修改生产代码；基于 F-4 最终 HEAD 重新审计）
