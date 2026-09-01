# 02 — Failure Taxonomy（失败分类审计）

> Phase D-0 · 全量盘点 Agent 路径可观测的失败，建立分类学。
> 错误码来源：agent/tools.py（工具层）、providers/errors.py（provider 层）、
> feasibility（校验层）、infrastructure/amap/planning_provider.py（规划层）。

## 1. 全量错误码清单（agent 路径可观测）

**工具输入类**（确定性、用户可自纠）：
`EMPTY_KEYWORD / EMPTY_PLACE / EMPTY_QUERY / EMPTY_QUESTION / INCOMPLETE_ROUTE /
INVALID_VALUES / INVALID_REJECTIONS / NO_VALUES / INVALID_CONSTRAINT_VALUES /
INCOMPLETE_CONSTRAINTS / NO_CANDIDATE / NO_PREFERENCES / PROFILE_UNAVAILABLE`
（tools.py:155-540）

**能力配置类**：`CAPABILITY_MISSING`（7 处：tools.py:310/325/344/364/386/490/570）

**规划语义类**：`PLANNING_INFEASIBLE`（tools.py:514 捕获 PlanningInfeasibleError；
conflicts 携带 MUST_VISIT_UNAVAILABLE / INSUFFICIENT_DAY_CAPACITY /
FIXED_SCHEDULE_OVERLAP / TRAVEL_ANCHOR_UNAVAILABLE / MUST_VISIT_UNVERIFIABLE_IN_DEMO，
protocols.py:34-41）

**校验类**：`FEASIBILITY_BLOCKED`（validate 观测，tools.py:540 区）；
硬校验失败明细在 C-3 的 `plan_evaluation.failures`（11 条规则的 rule_id/reason_code）。

**运行时吞咽类**：`TOOL_ERROR`（tools.py:802-808——handler 任何未捕获异常）；
`UNKNOWN_TOOL`（:799）

**provider 层类别**（经 PlanningProviderError.details.category）：
`NETWORK_ERROR / PROVIDER_UNAVAILABLE / RATE_LIMITED / QUOTA_EXCEEDED /
AUTHENTICATION_ERROR / PERMISSION_DENIED / MALFORMED_RESPONSE / INVALID_REQUEST /
INTERNAL_ERROR / DATA_QUALITY_ERROR / NO_RESULT / PROVIDER_ADAPTER_ERROR /
CONFIGURATION_ERROR`（providers/errors.py）+ 规划层错误码
`INSUFFICIENT_AMAP_POIS / PROVIDER_UNSUPPORTED_MODE / PLANNING_INFEASIBLE` 等。

## 2. 五类失败分类学（按用户 §五框架 + 上述证据）

### A. 用户约束不可满足 → 期望 ASK USER
| 失败 | 检测位置 | 现状 |
|---|---|---|
| Must Visit 不可覆盖（文本型） | run_validation 硬校验 MUST_VISIT_PLACE_MISSING → plan_evaluation.failures | ⚠️ 行程仍 EMITTED（结构门语义），冲突在摘要可见 |
| 结构化必去无法 pin | provider 抛 PlanningInfeasible(MUST_VISIT_UNAVAILABLE) → PLANNING_INFEASIBLE 观测 | ✅ C-1：ask_user |
| 固定安排不可满足 | INSUFFICIENT_DAY_CAPACITY / FIXED_SCHEDULE_OVERLAP | ⚠️ 经 forward-fit 抛出 → 视产生路径可能成为 TOOL_ERROR（未分类） |
| 预算+窗口互斥 | BUDGET_LIMIT FAIL → plan_evaluation.failures | ⚠️ 行程 EMITTED 带摘要（评估硬闸在 worker 路径才 raise） |

### B. 候选不足 → 期望 ASK USER 或 DEGRADE
| 失败 | 检测位置 | 现状 |
|---|---|---|
| POI 全被过滤（排序空） | provider **崩溃在 ItineraryDay 校验**（FOLLOW-UP ③）→ TOOL_ERROR | ❌ 未分类 |
| 餐厅全不合格 | _resolve_meal_poi 返回 None → placeholder（设计行为）| ✅ 不算失败 |
| INSUFFICIENT_AMAP_POIS | PlanningProviderError → TOOL_ERROR | ❌ 未分类 |

### C. 外部能力失败 → 期望 RETRY→DEGRADE
| 失败 | 检测位置 | 现状 |
|---|---|---|
| AMap 超时/网络/限流 | provider 层 Retrying*Provider 已重试（amqp.py:437-476）；耗尽后 PlanningProviderError → agent 层 TOOL_ERROR | ❌ agent 层无 RETRY/DEGRADE 分类——瞬态与确定性同貌 |
| knowledge DB 不可用 | _knowledge_stack 探测失败 → 能力不接线 → CAPABILITY_MISSING | ✅ 已降级（C-2） |
| build 后端缺配置 | _itinerary_builder_for_mode 降级 demo（agent_processor.py） | ✅ 已降级（C-1） |

### D. 规划结果失败（硬校验）→ 期望 ASK USER / 修复
| 失败 | 检测位置 | 现状 |
|---|---|---|
| 11 规则 FAIL | run_validation → plan_evaluation.failures | ⚠️ 摘要可见；结构门仍放行；修复循环只在 worker 路径存在，agent 路径无 |
| DATA_QUALITY raise | 仅 worker 路径（evaluator.py:87-98） | agent 路径不经过 |

### E. Agent 自身决策失败 → 期望 RECOVERY/STOP
| 失败 | 检测位置 | 现状 |
|---|---|---|
| 重复同一失败动作 | **无检测**（observations 有历史但 AskingDecider 不比对） | ❌ |
| Ceiling | steps/tool/llm 预算（graph.py:38-43,386-387） | ⚠️ 兜底出口，非策略 |
| 状态不推进 | 无检测 | ❌ |

## 3. 结论

当前系统**没有失败分类层**：provider 类别（retryable/类别）与工具错误码在
AskingDecider 眼里只剩三档被识别（CAPABILITY_MISSING / PLANNING_INFEASIBLE / 其他），
"其他"占大头且全部等价——这就是 §六"大量 Failure 被统一成 CEILING_REACHED"
的机制根源。
