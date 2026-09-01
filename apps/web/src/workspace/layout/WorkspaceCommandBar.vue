<script setup lang="ts">
// Agent Command Bar（F-UI-11 Phase 2：真实 Agent 接入）。
// 连接 useAgentWorkspace.send() 实现真实 Agent 对话。
import { ref } from 'vue'
import { ArrowUp, LoaderCircle } from 'lucide-vue-next'

const props = defineProps<{
  disabled?: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  submit: [text: string]
}>()

const command = ref('')

function submit() {
  const text = command.value.trim()
  if (!text || props.disabled) return
  emit('submit', text)
  command.value = ''
}
</script>

<template>
  <footer class="shrink-0 border-t border-tp-line bg-tp-panel px-4 py-2.5">
    <form
      class="mx-auto flex h-9 max-w-2xl items-center gap-2 rounded-md border border-tp-line bg-white px-2.5 transition-colors focus-within:border-tp-faint"
      data-testid="workspace-command-bar"
      @submit.prevent="submit"
    >
      <input
        v-model="command"
        type="text"
        class="h-7 min-w-0 flex-1 border-0 bg-transparent text-xs text-tp-ink outline-none placeholder:text-tp-faint"
        :placeholder="placeholder ?? '继续告诉 TripPilot 你想如何调整旅行…'"
        :disabled="disabled"
        aria-label="向 TripPilot Agent 下达指令"
        data-testid="workspace-command-input"
      />
      <span class="hidden shrink-0 text-[11px] text-tp-faint sm:block">TripPilot</span>
      <button
        type="submit"
        class="flex h-6 w-6 shrink-0 items-center justify-center rounded text-tp-sub transition-colors hover:bg-tp-active hover:text-tp-ink disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="disabled || !command.trim()"
        title="发送指令"
        aria-label="发送指令"
        data-testid="workspace-command-send"
      >
        <component :is="disabled ? LoaderCircle : ArrowUp" :size="13" :class="disabled ? 'animate-spin' : ''" aria-hidden="true" />
      </button>
    </form>
  </footer>
</template>