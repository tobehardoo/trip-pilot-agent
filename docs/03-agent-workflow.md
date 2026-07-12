# Agent 工作流设计

## 1. 设计原则

- 使用一个显式、可观测、可恢复的状态图，不构建多个自由对话的“专家 Agent”。
- LLM 负责语义理解、查询改写、解释和有限修复。
- 地图与天气工具负责实时或动态事实。
- OR-Tools 和确定性规则负责时间、路线、预算与硬约束。
- 所有模型输出先通过 Schema、语义和业务规则校验。
- 用户只看到业务进度和可解释依据，不展示模型隐藏推理。

## 2. LangGraph 工作流

```text
加载旅行上下文
  -> 解析用户需求（LLM）
  -> 约束完整性检查（规则）
  -> 缺失信息？
       是 -> 结构化追问 -> Checkpoint -> WAITING_USER
       否 -> 继续
  -> 检索城市知识（RAG）
  -> 搜索和补全真实 POI（高德）
  -> 候选过滤与偏好排序
  -> 地理粗分组和路线查询
  -> OR-Tools 生成日程
  -> 确定性约束校验
  -> 存在冲突？
       可自动修复 -> 局部修复，最多两轮
       需要决策 -> 结构化冲突选项 -> WAITING_USER
       无冲突 -> 继续
  -> LLM 生成推荐理由和说明
  -> 返回结构化行程
  -> Java 进行最终业务校验并保存版本
```

## 3. Agent State

状态至少包含：

```text
runId / taskId / tripId
workflowVersion / currentNode / retryCount
rawUserInput
normalizedConstraints
missingFields
lockedDays / lockedActivities
cityKnowledgeRefs
candidatePois
dayAssignments
routeMatrixRef
optimizationInputRef
draftItinerary
constraintViolations
toolErrors
replanScope
modelUsage / estimatedCost
cancellationRequested
```

大体量 POI、路线矩阵和模型原始输出保存在独立记录或对象中，Checkpoint 保存引用，避免状态无限膨胀。

## 4. 工具集合

- `geocode`：地点转换为坐标。
- `search_poi`：城市、类别、关键字和周边搜索。
- `get_poi_detail`：补充地址、类型等详情。
- `get_route`：步行和公共交通路线。
- `get_weather`：查询可用预报窗口内的天气。
- `retrieve_city_knowledge`：检索城市知识和引用。
- `calculate_budget`：确定性预算计算。
- `optimize_itinerary`：调用 OR-Tools。
- `validate_itinerary`：执行硬软约束校验。
- `compare_versions`：生成行程差异数据。

统一工具返回：

```text
success
data
errorCode
retryable
provider
latencyMs
cached
sourceTimestamp
```

## 5. 结构化追问

Agent 返回字段定义，前端渲染输入控件，而不是只返回自由文本：

```json
{
  "type": "CLARIFICATION_REQUIRED",
  "questions": [
    {
      "field": "budget",
      "question": "本次行程预算大约是多少？",
      "inputType": "NUMBER",
      "required": true,
      "unit": "元"
    }
  ]
}
```

聊天区负责解释，结构化控件负责准确采集。

## 6. 多模型策略

模型不能硬编码到业务节点，使用统一 `ModelProvider` 和任务级路由。

- 千问：中文需求提取、工具调用和说明生成的首选候选。
- DeepSeek：复杂冲突分析和方案修复的首选候选。
- OpenAI：离线质量基线和可配置高质量重试。
- 最终生产路由由固定评测集决定，以上只是初始候选。

每个模型调用记录：

- Provider、模型标识和用途。
- Prompt/Schema 版本。
- 输入输出 Token。
- 延迟和估算费用。
- 重试、降级和校验结果。

## 7. 输出校验链

```text
模型输出
  -> JSON/Pydantic Schema 校验
  -> 字段语义校验
  -> 业务规则校验
  -> 允许时执行一次结构修复
  -> 仍失败则切换模型或进入人工确认
```

模型的 JSON 模式也不能替代业务校验。

## 8. 人工确认

进入 `WAITING_USER` 的典型情况：

- 到达或返程时间缺失。
- 两个必去活动预约时间冲突。
- 预算无法覆盖所有必去地点。
- 天气变化导致锁定室外活动不可行。
- Agent 提供两个有明显取舍的方案。

用户补充后从 Checkpoint 恢复，不重新执行所有已完成步骤。

## 9. 局部重规划

影响范围规则：

- 删除普通景点：只重规划当天。
- 修改当天结束时间：重规划当天及交通段。
- 降低总预算：可能影响全部日期。
- 修改酒店位置：重新计算所有天首尾路线。
- 锁定活动：保留该活动，只调整周边内容。
- 天气变化：只替换受影响日期的室外活动。

重规划输入必须包含：

- 当前版本。
- 用户变更命令。
- 锁定日期和活动。
- 允许修改范围。
- 原始约束与新增约束。

结果先生成版本差异预览，确认后再激活新版本。

## 10. 取消与恢复

取消是协作式取消：

1. Java 将任务更新为 `CANCELLING` 并发布取消命令。
2. Python 在每个节点开始前检查取消状态。
3. 外部请求设置超时；已发出的请求不保证立即终止。
4. Agent 不再进入后续节点并发布取消结果。
5. Java 更新为 `CANCELLED`。

服务重启后通过 `agent_run` 和 `agent_checkpoint` 恢复，不依赖进程内存。

## 11. 重试与停止条件

- 瞬时网络错误、限流：指数退避并设置最大次数。
- JSON 结构错误：允许一次结构修复。
- POI 无结果：修改查询或扩大范围，但限制次数。
- 优化无解：进入约束分析，不重复盲目求解。
- API Key 无效、认证失败：直接失败，不重试。
- 自动修复循环最多两轮，防止 Agent 无限循环。
- 达到 Token、费用、工具调用或时间预算时停止并返回明确状态。

## 12. 业务进度事件

允许推送给用户的事件：

```text
TASK_STARTED
REQUIREMENT_PARSED
CLARIFICATION_REQUIRED
POI_SEARCHING
ROUTE_CALCULATING
OPTIMIZATION_RUNNING
CONFLICT_DETECTED
PLAN_GENERATED
TASK_COMPLETED
TASK_FAILED
```

事件只描述业务阶段、事实和下一步，不泄露系统 Prompt、API Key 或隐藏推理。
