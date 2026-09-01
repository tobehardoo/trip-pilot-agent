<script setup lang="ts">
// F-UI-10：Agent 对话流 —— 主工作区的执行过程呈现。
//
// 信息表达模型（用户 §15）：Agent Execution 是消息，不是 Card；
// Timeline 是辅助，不是主视觉。本组件把执行步骤渲染成对话流：
//
//   用户
//   ▍帮我规划一个上海三日旅行，预算 3000 元。
//
//   TripPilot Agent
//   ✓ 已理解旅行需求
//   ✓ 已解析旅行约束 · 8 个硬约束
//   ● 正在优化旅行路线……
//      ⌄ 查看路线优化详情（点击展开工具指标）
import { computed } from 'vue'

import AgentMessage from './AgentMessage.vue'

import type { AgentExecutionStep } from '../../lib/agent-timeline'

const props = withDefaults(defineProps<{
  steps?: AgentExecutionStep[]
  /** 对话流起始的用户消息 */
  userPrompt?: string
  /** 全部步骤以简洁行渲染（completed 折叠区） */
  compact?: boolean
  /** 历史步骤收成简洁行，当前运行步骤完整（planning 态） */
  collapseHistory?: boolean
}>(), {
  steps: undefined,
  userPrompt: undefined,
  compact: false,
  collapseHistory: false,
})

const stepsResolved = computed(() => props.steps ?? [])
</script>

<template>
  <div class="flex flex-col gap-4" aria-label="Agent 对话流" data-testid="agent-conversation">
    <!-- 用户消息：右对齐 + 极浅底细边框（与 Agent 消息区分，§9） -->
    <div v-if="userPrompt" class="flex justify-end" data-testid="user-message">
      <div class="max-w-[85%]">
        <p class="mb-1 text-right text-[11px] leading-4 text-tp-mute">用户</p>
        <p class="m-0 rounded-md border border-tp-line bg-tp-panel px-3 py-2 text-[13px] leading-5 text-tp-ink">
          {{ userPrompt }}
        </p>
      </div>
    </div>

    <!-- Agent 消息列表 -->
    <AgentMessage
      v-for="step in stepsResolved"
      :key="step.eventId"
      :step="step"
      :compact="compact || (collapseHistory && step.ok)"
    />
  </div>
</template>
