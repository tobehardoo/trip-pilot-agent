<script setup lang="ts">
// F-UI-10 Phase 2：Agent Message —— 对话流中的单条助手消息。
//
// AgentExecutionStep 的 status 由 ok/errorCode 推导：
//   ok=true  → completed；ok=false → failed；默认 → running。
import { computed } from 'vue'

import type { AgentExecutionStep, ToolExecution } from '../../lib/agent-timeline'

const props = withDefaults(defineProps<{
  step: AgentExecutionStep
  toolExecution?: ToolExecution
  compact?: boolean
  showLabel?: boolean
}>(), {
  toolExecution: undefined,
  compact: false,
  showLabel: true,
})

type StepStatus = 'completed' | 'running' | 'failed'

const status = computed<StepStatus>(() => {
  if (props.step.ok) return 'completed'
  if (props.step.errorCode) return 'failed'
  return 'running'
})

const GLYPH: Record<StepStatus, { text: string; classes: string; animate?: boolean }> = {
  completed: { text: '✓', classes: 'text-tp-ok' },
  running: { text: '●', classes: 'text-tp-run', animate: true },
  failed: { text: '!', classes: 'text-tp-warn' },
}

const glyph = computed(() => GLYPH[status.value])
</script>

<template>
  <div class="flex gap-3" :data-status="status" :data-testid="`agent-message-${step.eventId}`">
    <span
      class="w-4 shrink-0 pt-0.5 text-center text-[13px] leading-5"
      :class="[glyph.classes, glyph.animate ? 'animate-pulse' : '']"
      aria-hidden="true"
    >{{ glyph.text }}</span>

    <div class="min-w-0 flex-1">
      <p v-if="!compact && showLabel" class="mb-1 text-[11px] leading-4 text-tp-mute">TripPilot Agent</p>

      <p class="m-0 text-[13px] leading-5" :class="compact ? 'text-tp-sub' : 'font-medium text-tp-ink'">
        {{ step.title }}
        <span v-if="compact && step.summary" class="ml-2 text-[11px] font-normal leading-5 text-tp-faint">
          {{ step.summary }}
        </span>
      </p>

      <p v-if="!compact && step.summary" class="m-0 mt-0.5 text-[13px] leading-5 text-tp-body">
        {{ step.summary }}
      </p>

      <p v-if="!compact && step.errorCode" class="m-0 mt-0.5 text-xs leading-5 text-tp-warn">
        {{ step.errorCode }}
      </p>
    </div>
  </div>
</template>