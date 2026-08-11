# 长期任务执行记录

- 文档状态：有效
- 更新日期：2026-08-10
- 总控计划：[系统完善长期执行与验收总控计划](../product/系统完善长期执行与验收总控计划.md)

本目录保存长期完善任务中每个批次的持久化计划、执行报告和独立验收报告。聊天内容不是唯一证据。

## 目录约定

```text
docs/execution/<batch-id>/plan.md
docs/execution/<batch-id>/execution-report.md
docs/execution/<batch-id>/acceptance-report.md
```

`batch-id` 使用总控计划中的标识，例如 `B6J1`、`B6J2`、`B6W`、`B7A`。

## plan.md 必填内容

- branch、预期 HEAD、已知在途改动；
- 目标和不可变语义；
- 允许修改路径与禁止路径；
- RED 测试清单；
- 定向、分层与全量门禁；
- 明确非目标；
- 完成标志。

## execution-report.md 必填内容

- 开始前 Git 状态；
- 每轮 RED 的真实失败；
- GREEN 实现与精确文件清单；
- 真值表和负向路径；
- 全部门禁结果；
- staged/commit/push 状态；
- 残留边界。

## acceptance-report.md 必填内容

- 实际 diff 范围；
- 生产链路追踪；
- 绕过、历史兼容、事务和错误 fixture 检查；
- 独立复跑结果；
- `PASS`、`NEEDS_SMALL_FIX`、`NEEDS_CORRECTION` 或 `BLOCKED`；
- PASS 后允许提交的精确文件清单。

在三份批次记录中，plan 只由规划职责维护，执行 Agent 只写 `execution-report.md`，验收 Agent 只写 `acceptance-report.md`。这不限制执行 Agent 按 plan 的允许路径修改业务代码和测试，也不限制验收 Agent执行只读测试命令。批次实现与报告在独立验收 PASS 后一同进入该批次提交。
