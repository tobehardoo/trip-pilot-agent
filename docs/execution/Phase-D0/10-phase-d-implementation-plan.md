# 10 — Phase D Implementation Plan（D-1 ~ D-4，一刀一验收）

> 顺序按审计结果重排：分类先行（一切 Recovery 的前提）→ resume 闭环（P0）→
> 瞬态恢复 → 重复守卫。每刀：Scope / Non-goals / Architecture Change /
> Behavior Change / Compatibility / Acceptance / Counterfactual Tests。

## D-1 Failure Classification（纯函数 + State 字段）

- **Scope**：新建 `agent/failure_policy.py`（`FailureKind` + `classify_failure()` 纯函数，
  §08-1 的七类）；`agent/state.py` 增 `failure_kind: str | None` 与
  `failure_signature: str | None`（checkpoint v2 内追加，读取仍兼容 v1/v2）；
  `agent/tools.py` act 后由 **graph.py `_act_node`** 调 classify（工具层不动——职责划分已定）。
- **Non-goals**：不改任何工具 handler 的错误码；不加 Recovery 动作；不接 LLM。
- **Architecture Change**：State 增 2 字段；_act_node 在 observation 后追加分类调用。
- **Behavior Change**：**NONE**（分类只写字段，不改变任何分支——纯观测入列）。
- **Compatibility**：checkpoint 读写向后兼容（同 C-3 模式）；wire 不变。
- **Acceptance**：每类失败样本 → classify 返回正确 Kind（表驱动测试）；
  run 结束后 state.failure_kind 与失败类别一致。
- **Counterfactual Tests**：同一 run 内注入两种不同失败（mock）→ failure_kind 随之变化。

## D-2 Transient Recovery（R1：有界重试 + 分类提示）

- **Scope**：`agent/graph.py` AskingDecider 增 TRANSIENT_PROVIDER 分支（重试同一工具
  调用一次，重试后仍失败 → ask_user 说明能力暂时不可用）；LLM 路径 prompt 注入
  FailureKind；重试次数记录在 failure_signature 规则内（同签名第 2 次不再重试）。
- **Non-goals**：不在工具层加重试（provider 层已有）；不加退避 sleep（测试确定性优先，
  退避属 provider 层既有职责）；不覆盖 CAPABILITY/INFEASIBLE。
- **Architecture Change**：无新模块——决策分支 + 分类函数。
- **Behavior Change**：**是**——瞬态失败从"重试 build→CEILING"变为"重试一次→成功或
  ask_user"；CEILING 覆盖面缩小。
- **Compatibility**：wire/DB 不变。
- **Acceptance**：Counterfactual C 全链（第一次失败→重试→EMITTED）；重试后仍失败→
  WAITING_USER 携带"能力暂时不可用"。
- **Counterfactual Tests**：mock 后端第一次抛 NETWORK_ERROR 第二次成功 → EMITTED；
  两次都失败 → WAITING_USER；断言 retry 恰好一次（不是无限）。

## D-3 Ask User Resume 闭环（P0：让用户的回答真正生效）

- **Scope**：`agent/graph.py` AskingDecider——resume 且 last build 为
  PLANNING_INFEASIBLE / VALIDATION_BLOCKED 时，**先**把 `user_message` 作为
  `update_constraints` 的 propose（values 由既有 `_extract_slot_values` + 新增的
  "删除必去"模式解析；evidence=原话；信任规则不变：值必须在原话中出现），再走
  重建/再问分支；ask_user 的问题文本结构化（附 pending_options：冲突涉及的槽位）。
- **Non-goals**：不自动改约束（提议仍走证据信任规则，用户原话不含的值不会确认）；
  不实现自然语言理解（沿用既有正则抽取 + 显式模式）；不动 LLM 路径的解析（LLM 已
  从原话抽槽位）。
- **Architecture Change**：无新模块——decider 分支顺序调整 + 问题文本增强。
- **Behavior Change**：**是**——不可行场景的 resume 从"重复同一问题"变为
  "解析调整 → 重建 → EMITTED 或再次 ask（带新冲突）"。
- **Compatibility**：wire 不变（AgentAskUserEvent 增 pending_options 已有字段）；
  checkpoint 兼容。
- **Acceptance**：用户 §八示例全链——"删除 C" → must_visit 更新（移除 C 的提议按
  证据规则确认）→ 重建 → EMITTED；无效回答 → 重复提问（现行为保留）。
- **Counterfactual Tests**：Counterfactual B 全链（FAIL→ask→resume 调整→重建→EMITTED）；
  resume 回答不含可解析调整 → 原问题重现（防误改）。

## D-4 Repetition Guard（重复失败守卫 + Ceiling 退役为纯边界）

- **Scope**：`agent/graph.py` `_act_node`/decide——failure_signature 连续相同 ≥2 时，
  TRANSIENT/INVALID_INPUT 类强制升级（ask_user/STOPPED），禁止第三次同动作；
  `test_a_blocked_gate...` 类行为更新为升级语义。
- **Non-goals**：不建全局失败历史；不改 worker。
- **Architecture Change**：无新模块。
- **Behavior Change**：**是**——CEILING 的到达面收窄（多数失败在 ≤2 次内被分类处置）。
- **Compatibility**：不变。
- **Acceptance**：构造恒失败后端 → run 以 ask/STOPPED 结束且步数 ≤3（不再 CEILING）。
- **Counterfactual Tests**：恒定 FEASIBILITY_BLOCKED → 第 2 次失败后升级 ask_user；
  断言无第三次同动作。

## D-5（可选）ThemedExplanation 恢复消费（FOLLOW-UP ④ 的半闭环）

- **Scope**：ask_user 的问题文本由 themed/结构化 failures 生成（UI 渲染选项）。
- 依赖 D-3；纯读侧。**与 Recovery 的关系**：间接（解释质量），非控制流。

## 四个 FOLLOW-UP 的关联判定（用户 §十七）

| FOLLOW-UP | 与 Recovery 关系 | 判定 |
|---|---|---|
| ① _collect_pois 重复召回 | 无（效率问题） | 保持 FOLLOW-UP |
| ② 排序天气信号未接线 | 无（决策质量问题） | 保持 FOLLOW-UP |
| ③ 排序全拒不 fail-fast | **直接相关**：它使 CANDIDATE_EMPTY 类失败以崩溃形态出现，D-1 分类必须把它纳入（先修崩溃或分类器识别 TOOL_ERROR 语义）——D-1 前置小修或分类器兜底 | 升级为 D-1 依赖 |
| ④ ThemedExplanation 未消费 | 间接（D-5） | 保持 FOLLOW-UP |
