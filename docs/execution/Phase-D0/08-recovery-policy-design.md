# 08 — Recovery Policy Design（Recovery 策略设计空间 + 最小策略）

> Phase D-0 · 只设计，不实现。原则：确定性分类 + 局部决策；无 God Recovery Manager；
> 不自动修改用户约束；ask_user 是合法 Action。

## 1. Failure Classification（新增的纯函数，不是 Coordinator）

```python
# agent/failure_policy.py（Phase D-1 目标形态）
type FailureKind = Literal[
    "TRANSIENT_PROVIDER",   # R1 Retry：NETWORK_ERROR/RATE_LIMITED/QUOTA_EXCEEDED/PROVIDER_UNAVAILABLE/TIMEOUT
    "CAPABILITY",           # R2 Degrade：CAPABILITY_MISSING / knowledge 不可用
    "INFEASIBLE_USER",      # R4 Ask User：PLANNING_INFEASIBLE（conflicts 携带用户约束冲突）
    "VALIDATION_BLOCKED",   # R4 Ask User（选项化）：plan_evaluation.status == NEEDS_REPAIR 且 failures 非空
    "CANDIDATE_EMPTY",      # R3 Replan（不改约束）/ASK：INSUFFICIENT_AMAP_POIS、排序空（FOLLOW-UP ③ 修复后成为语义失败）
    "INVALID_INPUT",        # 重问：EMPTY_*/INVALID_*/INCOMPLETE_*（用户可自纠）
    "UNKNOWN",              # R5 Stop：TOOL_ERROR 中不可归类的
]

def classify_failure(*, error_code: str | None, observation: ToolObservation,
                     plan_evaluation: dict | None) -> FailureKind
```

纯函数：输入只有观测与评估摘要；无 I/O；无 LLM。分类依据 = 既有错误码与
provider category（errors.py 已有 retryable 语义可复用），**不发明新的错误体系**。

## 2. Recovery 语义边界（R1-R5，含"是否修改约束"）

| Kind | Recovery | 动作 | 修改用户约束？ |
|---|---|---|---|
| TRANSIENT_PROVIDER | **R1 Retry**（有界：同 turn 最多 1 次立即重试 + 指数退避留给 provider 层） | 重发同一工具调用 | ❌ |
| TRANSIENT 耗尽 | **R5 Stop → ask_user 说明**（provider 层已重试过，agent 层盲重试无意义） | ask_user 说明能力暂时不可用 | ❌ |
| CAPABILITY | **R2 Degrade** | 现状已实现：观测工具继续/移交规划链路；保持 | ❌ |
| INFEASIBLE_USER | **R4 Ask User** | ask_user 携带冲突 + 结构化选项（涉及槽位） | ❌（由用户改） |
| VALIDATION_BLOCKED | **R4 Ask User（选项化）** | 列出 failures → "提高预算 / 调整必去 / 接受" | ❌（由用户选） |
| CANDIDATE_EMPTY | **R3 Replan（不改约束）** | 放宽**非用户**自由度：排序阈值/召回关键词（provider 内部策略），重试一次；仍空 → ASK | ❌（不改预算/必去/日期） |
| INVALID_INPUT | 重问 | 既有重复提问分支 | ❌ |
| UNKNOWN / 重复失败签名 | **R5 Stop** | STOPPED + 冲突摘要 | ❌ |

**R3 的关键澄清**（用户 §十二）：Replan 默认 = 改变**候选/排序/策略**（provider 内部
自由度），不触碰用户约束。约束变更永远经 ask_user → 用户确认 → update_constraints
（证据信任规则不变）。

## 3. 落点：分类进决策器，不进工具/Coordinator

```
act（观测产生）
  ↓
classify_failure（纯函数）        ← D-1
  ↓ FailureKind 进入 State（failure_kind + failure_signature 字段）
decide（AskingDecider / LLM prompt 注入 Kind）   ← 决策者按 Kind 选择 Action
  ├─ TRANSIENT → retry 同一调用（有界）
  ├─ INFEASIBLE / VALIDATION_BLOCKED → ask_user（结构化）
  ├─ CANDIDATE_EMPTY → provider 内部放宽重试一次 → 仍空 → ask_user
  └─ UNKNOWN / 重复签名 → STOPPED
```

- 工具层只报告（保持 C-1 的职责划分：tools report, deciders decide）。
- 重复失败检测：`failure_signature = f"{tool}:{error_code}:{摘要关键段}"`，
  State 记录上一次签名；同签名连续出现 ≥2 → 强制升级（Ask/Stop），不允许第三次
  同动作（D-4）。
- LLM 路径：FailureKind 注入 prompt（与 recent_observations 并列），模型仍只能从
  白名单工具中选择；约束确认权不变（tools.py:114-131）。

## 4. 反事实三景（Phase D 验收定义）

| | 输入 | 期望链 |
|---|---|---|
| A 成功 | 正常约束 | build → PASS → EMITTED（已存在，C-1 测试） |
| B 用户约束不可满足 | 不可行约束 | build → FAIL → CLASSIFY INFEASIBLE/VALIDATION_BLOCKED → ask_user → WAITING_USER；**resume 携调整 → update_constraints → 重建 → EMITTED**（resume 半环当前 FAIL，D-3 修） |
| C 瞬态能力失败 | provider 超时（mock 第一次失败第二次成功） | build → FAIL → CLASSIFY TRANSIENT → retry → 成功 → EMITTED（当前不存在，D-2 实现；不得为了测试提前伪造语义） |
