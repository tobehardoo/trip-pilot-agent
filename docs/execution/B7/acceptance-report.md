# B7 独立验收报告

## 1. 验收范围与纪律

- 验收基线：`3f69a780974c4dc085ab55b09fb8fea33db900c9`
- 验收范围：当前未提交的 B7A/B7B 实现，对照：
  - `docs/product/系统完善长期执行与验收总控计划.md` 的 B7A/B7B 章节；
  - `docs/execution/B7/plan.md`。
- 重点：正确性、安全边界、契约漂移、运行时顺序与缺失的验收测试。
- 纪律：独立审查不修改业务代码、测试、契约或实现文档；保护目录 `.omo/`、`.serena/`、`docs/audits/` 不在验收范围内。

## 2. 首轮独立审查：NEEDS_CORRECTION

首轮审查结论为 **`B7_NOT_READY_FOR_COMMIT`**。未发现需要标为 Critical 的缺陷，但发现以下三组高置信度 Important 阻断。

### 2.1 Provider repair 元数据不完整

首轮实现存在以下问题：

1. `LocalReplanningProvider.repair` 在路线刷新后继续复制候选的旧 provider provenance。实际路线如果从 AMap 降级到 DEMO，最终 completion/review 仍可能声称未发生 fallback。
2. 非步行路线没有保留 `RoutePlan.estimated_cost` 与对应的 `cost_source`，与 AMap 正常规划路径的路线投影语义不一致。
3. `_replan_day` 重建 `ItineraryDay` 时没有传递 `day_type`，受影响的 ARRIVAL/FULL/DEPARTURE 日会退化为 `null`。

风险：修复后候选的路线、provider provenance 和旅行日分类彼此不一致，不能作为可信的最终输出。

审查期间曾初步怀疑路线费用丢失会直接导致 `BUDGET_LIMIT` 产生伪 VERIFIED；进一步核对后确认，当前 `estimated_total_cost` 的既有口径只汇总活动费用，不包含 transit cost，因此撤回该 Critical 定性。路线费用字段和来源丢失本身仍是明确的契约与元数据正确性问题。

### 2.2 时间移动只尝试窗口边界

首轮 opening repair 只尝试开门时刻或 last-entry 时刻，meal repair 只尝试餐饮窗口起点。

可复现反例：上一活动 10:00 结束、交通 5 分钟，目标活动原为 19:00–20:00，营业窗口为 09:00–18:00。10:05–11:05 是合法解，但旧实现只尝试 09:00；该候选与上一活动冲突，最终错误进入 `NO_PROGRESS` 或 review。

风险：系统具有合法的有界修复解，却因搜索点过窄而放弃修复，未达到 B7A 对 opening、last-entry 与 meal 时间调整动作的要求。

### 2.3 超过 16 个动作时过早判定重复失败

每轮动作数上限为 16，但首轮 `_failure_signature` 仅使用聚合后的：

```text
rule_id + reason_code + affected_dates + affected_entity_refs
```

该签名不包含剩余 FAIL findings 的 locator。对于同日 17 个 `VISIT_TOO_SHORT`，第一轮修复 16 个以后，聚合字段可能保持不变，于是 session 在仍有 1 个合法动作时错误判定 `REPEATED_FAILURE`，不会使用第二次机会。

风险：三轮预算形同虚设，大输入在仍可继续收敛时被提前终止。

## 3. 修复后独立复审：PASS

修复完成后进行了第二轮独立复审，结论为：

**`PASS — B7_READY_FOR_COMMIT_REVIEW`**

### 3.1 Provider repair 阻断关闭

关闭证据：

- repair 会从修复后的 activities 与 transit legs 重建 `actual_providers`；
- 会从修复后的 legs 重建 `fallback_operations`、`fallback_attempted`、`fallback_succeeded` 与 `fallback_reason`；
- AMap 路线失败并由 DEMO fallback 成功时，最终 provenance 可发布且与 leg provider 一致；
- 非步行路线会保留 provider `estimated_cost`，并正确标记 `cost_source=PROVIDER`；
- `_replan_day` 会保留原 `day_type`。

回归覆盖：

- `test_repair_provider_preserves_day_type_and_provider_route_cost`
- `test_repair_provider_rebuilds_provenance_after_route_fallback`

### 3.2 时间窗口修复阻断关闭

关闭证据：

- opening、last-entry 与 meal 动作不再只尝试窗口边界；
- `_earliest_neighbor_compatible_start` 会综合：
  - 窗口最早/最晚时刻；
  - 活动时长；
  - 上一活动结束时刻与 incoming transit；
  - 下一活动开始时刻与 outgoing transit；
- 只有交集非空时才生成确定性的最早合法候选；
- 后续仍经过 day-span、neighbor 与 opening eligibility 校验，不绕过 Hard Validation。

回归覆盖：

- `test_opening_shift_uses_earliest_legal_time_after_previous_activity`
- `test_meal_shift_uses_earliest_legal_time_after_previous_activity`
- last-entry 的既有显式动作回归继续通过。

### 3.3 跨轮次重复失败阻断关闭

关闭证据：

- `_failure_signature` 改为基于仍然存在的 FAIL assessments/findings；
- 签名包含 finding 的 `reason_code`、`affected_date`、activity locator 与 finding/entity refs；
- 不再使用包含已通过实体的聚合 refs 作为唯一重复判断依据；
- 17 个 duration 违规项在第一轮修复 16 个后，session 不再错误停止，第二轮会生成剩余 1 个动作。

回归覆盖：

- `test_seventeen_duration_failures_continue_into_a_second_attempt`

## 4. 独立复审门禁

复审执行：

```text
python -m pytest \
  tests/test_repair_provider_boundary.py \
  tests/feasibility/test_repair_engine.py \
  tests/feasibility/test_repair_session.py
```

结果：**22 passed**。

相关文件 Ruff 检查结果：**All checks passed**。

第二轮对抗性检查覆盖：

- 空输入与无合法动作；
- 每轮 16 个动作和总计 3 轮的边界；
- provider failure 与显式 fallback；
- 修复候选不可变性；
- opening/meal 邻接时间边界；
- remaining-finding repetition signature；
- provider provenance、route metadata 与 day type 一致性。

未发现新的、置信度不低于 80% 的 Critical 或 Important 阻断。

## 5. 最终结论与 Git 收口授权

**最终 Verdict：PASS**

从独立代码审查角度，B7A/B7B 已关闭首轮三组阻断，允许进入 Git 提交收口：

**`B7_PASS_AND_AUTHORIZED_FOR_GIT_CLOSEOUT`**

收口时仍须遵守以下边界：

- 只暂存 B7 批次批准范围及本验收报告；
- 不暂存或处理 `.omo/`、`.serena/`、`docs/audits/`；
- 提交前保留执行 Agent 已完成的全量 Python、Java、Web、契约、Markdown 与 diff 门禁证据；
- 若提交前业务 diff 再发生语义变化，本 PASS 授权失效，须重新验收变化部分。
