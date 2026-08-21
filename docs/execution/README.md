# 长期任务执行记录

- 文档状态：有效
- 更新日期：2026-08-21
- 总控计划：[系统完善长期执行与验收总控计划](../product/系统完善长期执行与验收总控计划.md)
- **最新发布判定：PASS_WITH_DEFECT / READY_WITH_MINOR_DEFECTS**（见 [release-readiness.md](QA-2026-08-21-closure/release-readiness.md)；已推 `main`。历史 NO-GO 判定见 [QA-2026-08-21-closure/report.md](QA-2026-08-21-closure/report.md)，已由 release-readiness 更新）

本目录保存长期完善任务中每个批次的持久化计划、执行报告和独立验收报告，以及 QA 审计轨迹。聊天内容不是唯一证据。

## 批次索引（按执行时间）

| 批次 | 目录 | 主题 | 状态 |
|---|---|---|---|
| B6F | `B6F/` | Feasibility 全链路统一验收 | ✅ 验收通过 |
| B6J1 | `B6J1/` | Java 骨架与契约（阶段一） | ✅ 验收通过 |
| B6J2 | `B6J2/` | Java 骨架与契约（阶段二） | ✅ 验收通过 |
| B6W | `B6W/` | Web 骨架 | ✅ 验收通过 |
| B7 | `B7/` | 规划骨架 | ✅ 验收通过 |
| B8 | `B8/` | 计划生成 | ✅ 验收通过 |
| B9 | `B9/` | 综合 | ✅ 验收通过 |
| B10 | `B10/` | 待补主题 | ✅ 验收通过 |
| B11 | `B11/` | 待补主题 | ✅ 验收通过 |
| B12 | `B12/` | 待补主题 | ✅ 验收通过 |
| B13 | `B13/` | 待补主题 | ✅ 验收通过 |
| B13_FIX | `B13_FIX/` | B13 修复批次 | ✅ 验收通过 |
| B14 | `B14/` | 100 场景验收矩阵（S001–S100） | ✅ 验收通过（含 scenario-catalog） |
| B14_FIX | `B14_FIX/` | B14 修复批次（含越权/幂等缺陷修复） | ✅ 验收通过 |
| B15 | `B15/` | 待补主题 | ✅ 验收通过 |
| B16 | `B16/` | 待补主题 | ✅ 验收通过 |
| B17 | `B17/` | timing / fixed-slot / capacity | ✅ 验收通过 |
| B18 | `B18/` | walking baseline（A/B） | ✅ 验收通过 |
| B19 | `B19/` | multi-mode recommendation（B19-C 验收通过；B19-D 后续闭环，QA 补正后并入正式发布） | ✅ 验收通过 |
| 日程重构 | `日程重构批次记录.md` | 日程生成重构（阶段一/二，历史批次记录，自 development/ 迁入） | 📦 已归档至此 |
| 评估校准 | `评估校准批次记录.md` | 评估校准 B1–B7（历史批次记录，自 development/ 迁入） | 📦 已归档至此 |
| QA-2026-08-20 | `QA-2026-08-20/` | 全面质量验证（快照：PASS_WITH_KNOWN_RISK，**已被 closure 修正**） | ⚠️ 见注记 |
| QA-2026-08-21-closure | `QA-2026-08-21-closure/` | QA 闭环补正 + Release Readiness（**权威结论：PASS_WITH_DEFECT，已推 main**） | ✅ 正式发布判定 |

## 目录约定

```text
docs/execution/<batch-id>/plan.md            # 批次计划（规划职责维护）
docs/execution/<batch-id>/execution-report.md # 执行报告（执行 Agent 写）
docs/execution/<batch-id>/acceptance-report.md # 独立验收报告（验收 Agent 写，只读）
docs/execution/QA-*/                         # QA 审计轨迹（含 evidence/ 原始证据）
```

`batch-id` 使用总控计划中的标识，例如 `B6J1`、`B6J2`、`B6W`、`B7A`。大批次可拆分子批次（如 `B19/plan-b.md`、`plan-c.md`、`plan-d.md`）。

## 文档必备内容

### plan.md 必填

- branch、预期 HEAD、已知在途改动；
- 目标和不可变语义；
- 允许修改路径与禁止路径；
- RED 测试清单；
- 定向、分层与全量门禁；
- 明确非目标；
- 完成标志。

### execution-report.md 必填

- 开始前 Git 状态；
- 每轮 RED 的真实失败；
- GREEN 实现与精确文件清单；
- 真值表和负向路径；
- 全部门禁结果；
- staged/commit/push 状态；
- 残留边界。

### acceptance-report.md 必填

- 实际 diff 范围；
- 生产链路追踪；
- 绕过、历史兼容、事务和错误 fixture 检查；
- 独立复跑结果；
- `PASS`、`NEEDS_SMALL_FIX`、`NEEDS_CORRECTION` 或 `BLOCKED`；
- PASS 后允许提交的精确文件清单。

在三份批次记录中，plan 只由规划职责维护，执行 Agent 只写 `execution-report.md`，验收 Agent 只写 `acceptance-report.md`。这不限制执行 Agent 按 plan 的允许路径修改业务代码和测试，也不限制验收 Agent 执行只读测试命令。批次实现与报告在独立验收 PASS 后一同进入该批次提交。

## 状态与发布判定指引

- 批次报告中的 `Verdict`（如 `READY_FOR_ACCEPTANCE` / `PASS`）为**执行/验收方在当批次范围内的自评**。
- 跨批次发布判定以**最近一次 QA 审计**为准：当前为 `QA-2026-08-21-closure`（release-readiness：PASS_WITH_DEFECT / READY_WITH_MINOR_DEFECTS，已推 `main`）。
- 任何旧报告与最新 QA 结论冲突时，以 QA 结论为准；旧报告保留原始证据但须带"已被修正"注记。
