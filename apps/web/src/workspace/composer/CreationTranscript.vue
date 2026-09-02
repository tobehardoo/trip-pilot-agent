<script setup lang="ts">
// 创建对话流渲染（Composer 交互重构 design §3.1）。
// 纯投影：渲染服务端每轮回传的 messages；选项卡点击 → emit(option)。
// 内部槽位枚举与技术信息不上屏——messages 文案本身已是用户语言。
import type { AgentDialogMessage, AgentDialogOption } from '../../lib/api'

defineProps<{
  messages: AgentDialogMessage[]
  sending: boolean
}>()

const emit = defineEmits<{
  option: [option: AgentDialogOption]
}>()

function isSummary(message: AgentDialogMessage): boolean {
  return message.kind === 'SUMMARY'
}
</script>

<template>
  <div class="space-y-4" data-testid="creation-transcript" aria-live="polite">
    <div
      v-for="(message, index) in messages"
      :key="index"
      class="flex flex-col"
      :class="message.role === 'user' ? 'items-end' : 'items-start'"
      :data-testid="`creation-message-${message.role}`"
    >
      <span class="mb-1 text-[10px] uppercase tracking-[0.08em]" :class="message.role === 'user' ? 'text-tp-faint' : 'text-tp-mute'">
        {{ message.role === 'user' ? '你' : 'TripPilot' }}
      </span>
      <div
        class="max-w-[92%] whitespace-pre-wrap text-[13px] leading-5"
        :class="message.role === 'user'
          ? 'rounded-lg bg-tp-active px-3 py-2 text-tp-ink'
          : isSummary(message)
            ? 'rounded-lg border border-tp-line bg-tp-panel px-3 py-2.5 text-tp-body'
            : 'text-tp-body'"
      >
        {{ message.text }}
      </div>
      <!-- 选项卡（仅最新一条 agent 消息可点，其余置灰防误触） -->
      <div v-if="message.options.length && index === messages.length - 1" class="mt-2 flex flex-wrap gap-1.5">
        <button
          v-for="option in message.options"
          :key="`${option.action}-${option.label}`"
          type="button"
          class="flex h-[26px] items-center rounded-md border border-tp-line bg-tp-panel px-2.5 text-xs text-tp-body transition-colors hover:border-tp-faint hover:bg-tp-hover hover:text-tp-ink disabled:cursor-not-allowed disabled:opacity-45"
          :data-testid="`creation-option-${option.label}`"
          :disabled="sending"
          @click="emit('option', option)"
        >
          {{ option.label }}
        </button>
      </div>
      <!-- 历史消息的选项：只读展示 -->
      <div v-else-if="message.options.length" class="mt-2 flex flex-wrap gap-1.5">
        <span
          v-for="option in message.options"
          :key="`old-${option.action}-${option.label}`"
          class="flex h-[26px] items-center rounded-md border border-tp-div bg-tp-panel px-2.5 text-xs text-tp-faint"
        >
          {{ option.label }}
        </span>
      </div>
    </div>
    <!-- 发送中指示 -->
    <div v-if="sending" class="flex items-center gap-1.5 text-xs text-tp-mute" data-testid="creation-typing">
      <span class="inline-block h-1.5 w-1.5 rounded-full bg-tp-dot animate-pulse" aria-hidden="true" />
      TripPilot 正在思考……
    </div>
  </div>
</template>
