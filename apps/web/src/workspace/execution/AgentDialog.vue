<script setup lang="ts">
// F-UI-11 Phase 2：Agent 对话流渲染。
// 接收 useAgentWorkspace 的返回对象，渲染完整对话流。
// Agent 过程默认不能霸屏：默认显示折叠状态，展开才看到步骤详情。
import { computed, ref } from 'vue'

import AgentExecutionTimeline from './AgentExecutionTimeline.vue'
import type { AgentExecutionStep } from '../../../lib/agent-timeline'

const props = defineProps<{
  agent: {
    turns: { value: { id: number; userText: string | null; steps: AgentExecutionStep[] }[] }
    stage: { value: string }
    send: (text: string) => void
    inputDisabled: { value: boolean }
  }
}>()

const expanded = ref(false)

const allSteps = computed(() => {
  const steps: AgentExecutionStep[] = []
  for (const turn of props.agent.turns.value) {
    if (turn.userText) {
      steps.push({
        eventId: turn.id * 1000,
        seq: 0,
        tool: 'user_input',
        ok: true,
        summary: turn.userText,
        errorCode: null,
        phase: 'UNDERSTANDING',
        title: turn.userText,
      })
    }
    steps.push(...turn.steps)
  }
  return steps
})

const summaryText = computed(() => {
  const stage = props.agent.stage.value
  if (stage === 'idle') return '等待你的指令……'
  if (stage === 'starting') return '正在启动……'
  if (stage === 'collecting') return '正在了解你的旅行需求……'
  if (stage === 'clarifying') return '请回答旅行相关问题'
  if (stage === 'researching') return '正在查询旅行信息……'
  if (stage === 'planning') return '正在生成旅行方案……'
  if (stage === 'validating') return '正在验证旅行方案……'
  if (stage === 'completed') return '已生成行程方案，请查看'
  if (stage === 'failed') return '本次任务未能完成'
  return ''
})

const completedCount = computed(() => allSteps.value.filter((s) => s.ok).length)
const totalCount = computed(() => allSteps.value.length)
</script>

<template>
  <div class="space-y-3" data-testid="agent-dialog">
    <!-- 默认折叠状态：● 正在智能规划 · 已完成 5 / 12 -->
    <div class="flex items-center gap-2">
      <span class="flex items-center gap-1.5 text-xs leading-4 text-tp-sub">
        <span class="inline-block h-1.5 w-1.5 rounded-full bg-tp-run animate-pulse" aria-hidden="true" />
        {{ summaryText }}
      </span>
      <span v-if="totalCount > 0" class="text-[11px] text-tp-mute">
        · 已完成 {{ completedCount }} / {{ totalCount }}
      </span>
      <button
        type="button"
        class="ml-1 text-[11px] text-tp-sub underline transition-colors hover:text-tp-ink"
        data-testid="agent-dialog-toggle"
        @click="expanded = !expanded"
      >
        {{ expanded ? '收起规划过程' : '查看规划过程' }}
      </button>
    </div>

    <!-- 展开的规划过程 -->
    <div v-if="expanded" class="space-y-4 border-l border-tp-div pl-4">
      <AgentExecutionTimeline
        :steps="allSteps"
        :collapse-history="false"
      />
    </div>
  </div>
</template>